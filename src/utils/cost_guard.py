# PRD Ref: §7.3, §11 · traps.md T19
"""LLM 비용 가드레일 — 월 하드실링 · 일일 상한 · 우선순위 큐.

참고 프로젝트에서 두 가지를 바꿨다:

1. **날짜 기준 가격 전환 로직을 제거했다** (T19).
   참고 프로젝트는 2026-09-01부터 Sonnet 5를 $3/$15로 전환하도록 짜여 있다.
   2026-08-13 Anthropic 공식 pricing 페이지 실측:
     "The $2/$10 pricing for Claude Sonnet 5 ... is now the standard price.
      The previously scheduled increase to $3/$15 on September 1, 2026 will not occur."
   그대로 이식하면 9월부터 비용이 50% 과대 계상되어 월 실링에 조기 도달한다.

2. **`cost_log.env`를 도입했다.**
   `check_budget()`은 `env='prod'`만 집계한다. 참고 프로젝트는 개발 중 테스트 실행이
   운영 일일 상한을 잡아먹어 실제 이벤트가 큐로 밀린 사고가 있었다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from src.config.constants import (
    ANALYSIS_MODEL,
    DAILY_ANALYSIS_LIMIT,
    FALLBACK_MODEL,
    HAIKU_CACHE_READ_PER_MTOK,
    HAIKU_CACHE_WRITE_PER_MTOK,
    HAIKU_INPUT_PER_MTOK,
    HAIKU_OUTPUT_PER_MTOK,
    MONTHLY_COST_CEILING_USD,
    OPENAI_ANALYSIS_MODEL,
    OPENAI_CACHE_READ_PER_MTOK,
    OPENAI_CACHE_WRITE_PER_MTOK,
    OPENAI_INPUT_PER_MTOK,
    OPENAI_OUTPUT_PER_MTOK,
    SONNET_CACHE_READ_PER_MTOK,
    SONNET_CACHE_WRITE_PER_MTOK,
    SONNET_INPUT_PER_MTOK,
    SONNET_OUTPUT_PER_MTOK,
)
from src.llm.provider import NormalizedUsage

ENV_PROD = "prod"
ENV_DEV = "dev"


@dataclass(frozen=True)
class PricingRates:
    """$ per 1M tokens. ★ 날짜 인자를 받지 않는다 — 그게 요점이다."""

    input: float
    cache_write: float
    cache_read: float
    output: float


_RATES: dict[str, PricingRates] = {
    ANALYSIS_MODEL: PricingRates(
        input=SONNET_INPUT_PER_MTOK,
        cache_write=SONNET_CACHE_WRITE_PER_MTOK,
        cache_read=SONNET_CACHE_READ_PER_MTOK,
        output=SONNET_OUTPUT_PER_MTOK,
    ),
    FALLBACK_MODEL: PricingRates(
        input=HAIKU_INPUT_PER_MTOK,
        cache_write=HAIKU_CACHE_WRITE_PER_MTOK,
        cache_read=HAIKU_CACHE_READ_PER_MTOK,
        output=HAIKU_OUTPUT_PER_MTOK,
    ),
}

if OPENAI_ANALYSIS_MODEL and all(
    rate is not None
    for rate in (
        OPENAI_INPUT_PER_MTOK,
        OPENAI_OUTPUT_PER_MTOK,
        OPENAI_CACHE_WRITE_PER_MTOK,
        OPENAI_CACHE_READ_PER_MTOK,
    )
):
    _RATES[OPENAI_ANALYSIS_MODEL] = PricingRates(
        input=OPENAI_INPUT_PER_MTOK,
        cache_write=OPENAI_CACHE_WRITE_PER_MTOK,
        cache_read=OPENAI_CACHE_READ_PER_MTOK,
        output=OPENAI_OUTPUT_PER_MTOK,
    )


class UnknownModelError(ValueError):
    """단가를 모르는 모델. **추측해서 계산하지 않는다** — 비용이 조용히 틀린다."""


def get_pricing(model: str) -> PricingRates:
    if model in _RATES:
        return _RATES[model]
    # 별칭·접미사 방어. 그래도 못 찾으면 추측하지 않고 실패시킨다.
    for known, rates in _RATES.items():
        if model.startswith(known):
            return rates
    raise UnknownModelError(
        f"단가를 모르는 모델: {model}. src/config/constants.py에 단가를 먼저 추가하라."
    )


def compute_cost_usd(
    model: str,
    *,
    input_tokens: int,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
    output_tokens: int = 0,
) -> float:
    rates = get_pricing(model)
    return (
        input_tokens * rates.input
        + cache_write_tokens * rates.cache_write
        + cache_read_tokens * rates.cache_read
        + output_tokens * rates.output
    ) / 1_000_000


def estimate_worst_case_cost_usd(
    model: str,
    *,
    input_tokens: int,
    max_output_tokens: int,
) -> float:
    """호출 전 계산하는 보수적 최대비용.

    입력 토큰은 uncached/cache-write/cache-read 중 하나로 분류된다. 어떤 분류가
    적용될지 호출 전에는 확정할 수 없으므로 셋 중 가장 비싼 단가를 쓴다. 실제
    usage를 더하는 사후 비용 계산과 달리, 이 함수는 **요청 자체를 막는 방어선**이다.
    """
    if input_tokens < 0 or max_output_tokens < 0:
        raise ValueError("token 수는 음수일 수 없다")
    rates = get_pricing(model)
    input_rate = max(rates.input, rates.cache_write, rates.cache_read)
    return (
        input_tokens * input_rate + max_output_tokens * rates.output
    ) / 1_000_000


@dataclass
class BudgetStatus:
    month_spent_usd: float
    month_ceiling_usd: float
    today_count: int
    daily_limit: int
    allowed: bool
    reason: str | None = None

    @property
    def month_remaining_usd(self) -> float:
        return max(self.month_ceiling_usd - self.month_spent_usd, 0.0)


def check_budget(*, env: str = ENV_PROD, now: datetime | None = None) -> BudgetStatus:
    """월 실링·일일 상한 확인. ★ `env='prod'`만 집계한다.

    실링에 도달하면 호출을 막고, 호출부는 우선순위 큐로 이월한다(PRD §7.3).
    """
    from src.db.supabase_client import get_client

    now = now or datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    db = get_client()
    month_rows = (
        db.table("cost_log")
        .select("cost_usd")
        .eq("env", env)
        .gte("created_at", month_start.isoformat())
        .execute()
        .data
        or []
    )
    today_rows = (
        db.table("cost_log")
        .select("id")
        .eq("env", env)
        .gte("created_at", day_start.isoformat())
        .execute()
        .data
        or []
    )

    spent = sum(float(r["cost_usd"] or 0) for r in month_rows)
    count = len(today_rows)

    if spent >= MONTHLY_COST_CEILING_USD:
        return BudgetStatus(spent, MONTHLY_COST_CEILING_USD, count, DAILY_ANALYSIS_LIMIT,
                            False, "monthly_ceiling_reached")
    if count >= DAILY_ANALYSIS_LIMIT:
        return BudgetStatus(spent, MONTHLY_COST_CEILING_USD, count, DAILY_ANALYSIS_LIMIT,
                            False, "daily_limit_reached")
    return BudgetStatus(spent, MONTHLY_COST_CEILING_USD, count, DAILY_ANALYSIS_LIMIT, True)


def record_usage(model: str, usage: NormalizedUsage, *, env: str = ENV_PROD) -> float:
    """Provider 중립 usage로 비용을 계산해 `cost_log`에 기록한다."""
    from src.db.supabase_client import get_client

    input_tokens = usage.input_tokens
    cache_write = usage.cache_write_tokens
    cache_read = usage.cache_read_tokens
    output_tokens = usage.output_tokens

    cost = compute_cost_usd(
        model,
        input_tokens=input_tokens,
        cache_write_tokens=cache_write,
        cache_read_tokens=cache_read,
        output_tokens=output_tokens,
    )

    get_client().table("cost_log").insert(
        {
            "model": model,
            "input_tokens": input_tokens,
            "cache_write_tokens": cache_write,
            "cached_tokens": cache_read,
            "output_tokens": output_tokens,
            "cost_usd": cost,
            "env": env,
        }
    ).execute()
    return cost


def month_to_date_key(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).date().replace(day=1)


def next_month_start(now: datetime | None = None) -> date:
    first = month_to_date_key(now)
    return (first + timedelta(days=32)).replace(day=1)
