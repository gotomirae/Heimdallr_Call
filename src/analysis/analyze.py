# PRD Ref: §7 전체, §11 · ADR 3, 4
"""게이트 통과 ★○ 종목 LLM 해석.

비용 설계가 이 모듈의 전부다:

1. **공시 원문 전체를 넣지 않는다.** 숫자는 이미 DB에 정확히 있다.
   입력은 PRD §7.1의 구조화 블록 + 발췌 2,000자, 총 5,000토큰 이내.
2. **시스템 프롬프트에 `cache_control: ephemeral`.** 종목마다 바뀌는 내용을
   시스템 프롬프트에 넣으면 캐시가 통째로 깨진다(ADR 4).
3. **`stop_reason == "max_tokens"`는 명시적 실패.** 잘린 JSON을 저장하면
   대시보드가 나중에 500을 낸다(PRD §7.3, T18).
4. **호출 전 `check_budget()`.** 월 실링·일일 상한에 걸리면 호출하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from src.config.constants import (
    ANALYSIS_MODEL,
    LLM_EFFORT,
    LLM_INPUT_TOKEN_BUDGET,
    LLM_MAX_TOKENS,
)
from src.analysis.prompts import ANALYSIS_SCHEMA, ANALYSIS_TOOL_NAME, SYSTEM_PROMPT
from src.utils.cost_guard import ENV_PROD, check_budget, record_usage
from src.utils.env import require_env

EXCERPT_MAX_CHARS = 2000  # PRD §7.1 — 공시 발췌 상한


class AnalysisError(RuntimeError):
    """분석 실패. 잘린/불완전한 결과를 저장하지 않기 위해 예외로 올린다."""


class BudgetExceeded(AnalysisError):
    """월 실링 또는 일일 상한. 호출부는 우선순위 큐로 이월한다."""


@dataclass
class AnalysisInput:
    """PRD §7.1의 7개 블록. 전부 이미 계산된 값이다."""

    code: str
    name: str
    board: str
    industry: str | None = None
    products: str | None = None
    market_cap_krw: int | None = None
    listed_at: str | None = None
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    is_estimate: bool = False
    quarters: list[dict] = field(default_factory=list)  # 8분기 표
    gate: dict = field(default_factory=dict)
    score: dict = field(default_factory=dict)
    consensus: dict | None = None
    price: dict = field(default_factory=dict)
    #: ★ 다시 계산한 밸류에이션. `price['per']`(후행)을 대신한다 — 아래 주석 참고.
    valuation: dict = field(default_factory=dict)
    pri: dict = field(default_factory=dict)
    excerpt: str | None = None
    peers: list[dict] = field(default_factory=list)


@dataclass
class AnalysisResult:
    code: str
    fiscal_year: int | None
    fiscal_quarter: int | None
    payload: dict
    model: str
    cost_usd: float
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int


def _fmt_quarters(quarters: list[dict]) -> str:
    """8분기 표. 억원 단위로 줄여 토큰을 아낀다."""
    if not quarters:
        return "(분기 데이터 없음)"
    header = (
        "| 분기 | 매출(억) | YoY% | 영업이익(억) | YoY% | OPM% | OPM YoYΔ%p | "
        "TTM매출(억) | TTM OPM% | 라벨 |"
    )
    lines = [header, "|---|---|---|---|---|---|---|---|---|---|"]
    for q in quarters:
        def eok(key):
            v = q.get(key)
            return "—" if v is None else f"{float(v) / 1e8:,.0f}"

        def pct(key):
            v = q.get(key)
            return "—" if v is None else f"{float(v):+.1f}"

        lines.append(
            f"| {q.get('fiscal_year')}.{q.get('fiscal_quarter')}Q | {eok('revenue')} | "
            f"{pct('revenue_yoy')} | {eok('op')} | {pct('op_yoy')} | {pct('opm')} | "
            f"{pct('opm_yoy_delta')} | {eok('ttm_revenue')} | {pct('ttm_opm')} | "
            f"{q.get('op_status_label') or ''} |"
        )
    return "\n".join(lines)


def _fmt_valuation(v: dict) -> str:
    """밸류에이션 두 배수를 **라벨과 함께** 준다.

    ★ 숫자만 주면 모델이 어느 쪽을 말하는지 섞는다. 무엇 기준인지와
      못 구했으면 왜 못 구했는지를 문장으로 붙인다.
    ★ 없는 값을 만들지 않는다 — 4개 분기가 안 모였으면 '계산 불가'라고 말한다.
    """
    if not v:
        return "- 밸류에이션: (계산 불가 — 시가총액 또는 순이익 데이터가 없다)"
    lines = ["- 밸류에이션 (**후행 PER은 쓰지 마라. 아래 두 개만 쓴다**)"]

    per4q = v.get("per_trailing_4q")
    if per4q is not None:
        lines.append(
            f"  · 최근 4개 분기 순이익 기준 PER: **{per4q:.1f}배** "
            f"(분모 {v['ttm_np'] / 1e8:,.0f}억 · 실제로 번 돈, 추정 없음)"
        )
    else:
        lines.append(
            "  · 최근 4개 분기 순이익 기준 PER: **계산 불가** "
            f"({v.get('per_trailing_reason', '4개 분기가 모이지 않았거나 누적 순이익이 0 이하')}) "
            "— 연율화해서 만들어내지 마라"
        )

    fwd = v.get("per_forward")
    if fwd is not None:
        lines.append(
            f"  · 향후 4개 분기 선행 PER: **{fwd:.1f}배** ({v.get('per_forward_basis')})"
        )
    else:
        lines.append(
            "  · 향후 4개 분기 선행 PER: **계산 불가** (연간 컨센서스가 없다) "
            "— 커버리지 공백이 이 시스템의 표적 구간이다"
        )

    if v.get("pbr") is not None:
        lines.append(f"  · PBR: {v['pbr']:.2f}배 (주가 ÷ 주당 순자산)")
    return "\n".join(lines)


def build_user_message(data: AnalysisInput) -> str:
    """PRD §7.1의 7개 블록. **공시 원문 전체를 넣지 않는다.**"""
    cap = (
        f"{data.market_cap_krw / 1e12:.2f}조" if data.market_cap_krw else "—"
    )
    parts = [
        "## 1. 기본정보",
        f"- {data.name} ({data.code} · {data.board})",
        f"- 업종: {data.industry or '—'}",
        f"- 주요제품: {(data.products or '—')[:200]}",
        f"- 시가총액: {cap} · 상장일: {data.listed_at or '—'}",
        f"- 대상 분기: {data.fiscal_year}.{data.fiscal_quarter}Q "
        f"({'잠정치' if data.is_estimate else '확정치'})",
        "",
        "## 2. 분기 실적 (최근 8분기)",
        _fmt_quarters(data.quarters),
        "",
        "## 3. 판정 결과",
        f"- 게이트: {json.dumps(data.gate, ensure_ascii=False)}",
        f"- 스코어: {json.dumps(data.score, ensure_ascii=False)}",
        "",
        "## 4. 컨센서스",
    ]
    if data.consensus:
        parts.append(json.dumps(data.consensus, ensure_ascii=False))
    else:
        parts.append(
            "**커버리지 없음** — 증권사 추정치가 없다(또는 추정기관 2곳 미만). "
            "C축(서프라이즈)은 0점이 아니라 분모에서 제외되어 정규화됐다. "
            "서프라이즈를 논하지 마라."
        )
    # ★★ 후행 PER은 **넘기지 않는다.** `price_snapshots.per`는 직전 사업연도 EPS
    #   기준이라 실적이 급가속하면 2~3배 과대평가된다(실측: 고영 131.6 vs 실제 40.5).
    #   이 시스템은 정확히 그런 종목만 고르므로 왜곡이 항상 최악으로 걸린다.
    #   대신 **다시 계산한 두 배수**를 라벨과 함께 준다.
    price_for_llm = {k: v for k, v in (data.price or {}).items() if k != "per"}
    parts += [
        "",
        "## 5. 주가",
        f"- 시세: {json.dumps(price_for_llm, ensure_ascii=False)}",
        _fmt_valuation(data.valuation),
        f"- 주가반영도(PRI) 분해: {json.dumps(data.pri, ensure_ascii=False)}",
        "",
        "## 6. 공시 발췌",
        (data.excerpt or "(발췌 없음)")[:EXCERPT_MAX_CHARS],
        "",
        "## 7. 업종 비교 (동일 업종 상위)",
        json.dumps(data.peers, ensure_ascii=False) if data.peers else "(비교군 없음)",
    ]
    return "\n".join(parts)


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=require_env("ANTHROPIC_API_KEY"))


def count_input_tokens(data: AnalysisInput) -> int:
    """호출 전 입력 토큰을 센다. 5,000토큰을 넘으면 호출하지 않는다(PRD §7.1)."""
    client = _client()
    resp = client.messages.count_tokens(
        model=ANALYSIS_MODEL,
        system=[{"type": "text", "text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": build_user_message(data)}],
        tools=[_tool_definition()],
    )
    return int(resp.input_tokens)


def _tool_definition() -> dict:
    return {
        "name": ANALYSIS_TOOL_NAME,
        "description": "분석 결과를 구조화해 기록한다. 반드시 이 도구로만 응답한다.",
        "input_schema": ANALYSIS_SCHEMA,
        "strict": True,  # 스키마를 정확히 지키도록 강제한다
    }


def analyze(
    data: AnalysisInput,
    *,
    env: str = ENV_PROD,
    enforce_budget: bool = True,
    token_budget: int = LLM_INPUT_TOKEN_BUDGET,
) -> AnalysisResult:
    if enforce_budget:
        status = check_budget(env=env)
        if not status.allowed:
            raise BudgetExceeded(
                f"{status.reason}: 월 ${status.month_spent_usd:.2f}/"
                f"${status.month_ceiling_usd} · 오늘 {status.today_count}/{status.daily_limit}"
            )

    user_message = build_user_message(data)
    client = _client()

    response = client.messages.create(
        model=ANALYSIS_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        # ★ 시스템 프롬프트만 캐시한다. 유저 메시지는 종목마다 바뀌므로 캐시 밖이다.
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        # ★ 사고가 출력 자리를 먹지 않도록 effort를 낮게 고정한다(constants 참조).
        thinking={"type": "adaptive"},
        output_config={"effort": LLM_EFFORT},
        tools=[_tool_definition()],
        tool_choice={"type": "tool", "name": ANALYSIS_TOOL_NAME},
        messages=[{"role": "user", "content": user_message}],
    )

    cost = record_usage(ANALYSIS_MODEL, response.usage, env=env)

    # ★ 잘린 응답을 저장하지 않는다 (PRD §7.3).
    if response.stop_reason == "max_tokens":
        raise AnalysisError(
            f"{data.code}: max_tokens({LLM_MAX_TOKENS})에 걸려 잘렸다. "
            f"비용 ${cost:.4f}는 이미 발생했다(cost_log 기록됨). 저장하지 않는다."
        )
    if response.stop_reason == "refusal":
        raise AnalysisError(f"{data.code}: 모델이 응답을 거부했다 (stop_reason=refusal)")

    payload = next(
        (b.input for b in response.content
         if getattr(b, "type", None) == "tool_use" and b.name == ANALYSIS_TOOL_NAME),
        None,
    )
    if payload is None:
        raise AnalysisError(f"{data.code}: tool_use 블록이 없다 (stop_reason={response.stop_reason})")

    # ★ 저장 전에 태그 누출을 걷어낸다(T61). 스키마 검증은 이걸 못 잡는다 —
    #   타입은 여전히 문자열이라 통과하고, 텔레그램도 esc() 덕에 발송에 성공한다.
    payload = sanitize_payload(payload)

    usage = response.usage
    return AnalysisResult(
        code=data.code,
        fiscal_year=data.fiscal_year,
        fiscal_quarter=data.fiscal_quarter,
        payload=payload,
        model=ANALYSIS_MODEL,
        cost_usd=cost,
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        cache_write_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


#: 모델이 값 안에 흘려 넣는 마커. 여기서부터 뒤는 그 필드의 내용이 아니다.
_LEAK_MARKERS = ("</", "<parameter", "<function_calls", "<invoke", "<")


def strip_tag_leakage(text: str) -> str:
    """문자열 값에 새어 든 **XML 태그와 그 뒤 전부**를 잘라낸다. 순수 함수.

    ★ **무엇이 조용히 틀리는가 (T61):** 도구 호출(`tool_use`)로 받아도 모델이
      값 **안쪽에** 닫는 태그와 다음 필드를 통째로 흘려 넣을 때가 있다.
      스키마 검증은 통과한다 — 타입은 여전히 문자열이기 때문이다.
      실측(042700, 2026-08-17): `one_line_thesis` 334자 중 뒤 230자가

          …구간이다.</one_line_thesis>\\n<parameter name="why_now">2026.1Q 매출이…

      였다. 텔레그램은 `esc()`가 태그를 escape해 **발송도 성공한다** —
      화면에 `&lt;/one_line_thesis&gt;`가 그대로 보일 뿐이다. 에러가 없다.

    ★ 자른 뒤 남는 게 없으면 **원문을 그대로 돌려준다.** 마커로 시작하는 정상
      문장은 없겠지만, 잘라서 빈 문자열을 만드는 것보다 원문이 낫다.
    """
    if not isinstance(text, str):
        return text
    cut = len(text)
    for marker in _LEAK_MARKERS:
        found = text.find(marker)
        if found != -1:
            cut = min(cut, found)
    trimmed = text[:cut].strip()
    return trimmed or text.strip()


def sanitize_payload(payload):
    """payload 안의 **모든 문자열**에 `strip_tag_leakage`를 적용한다(재귀).

    ★ 어느 필드에서 샐지 미리 알 수 없다 — 실측은 `one_line_thesis`였지만
      다음번엔 `why_now`나 리스크 항목일 수 있다. 전부 훑는다.
    """
    if isinstance(payload, str):
        return strip_tag_leakage(payload)
    if isinstance(payload, dict):
        return {k: sanitize_payload(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [sanitize_payload(v) for v in payload]
    return payload


def validate_payload(payload: dict) -> list[str]:
    """저장 전 필드 단위 검증 (T18). 상위 객체만 보면 대시보드가 나중에 500을 낸다."""
    problems: list[str] = []
    for key in ANALYSIS_SCHEMA["required"]:
        if key not in payload or payload[key] in (None, "", [], {}):
            problems.append(f"missing:{key}")

    scenarios = payload.get("scenarios") or {}
    probs = []
    for name in ("bull", "base", "bear"):
        node = scenarios.get(name) or {}
        if "probability" not in node:
            problems.append(f"missing:scenarios.{name}.probability")
        else:
            probs.append(float(node["probability"]))
    if len(probs) == 3 and not (0.9 <= sum(probs) <= 1.1):
        problems.append(f"scenarios.probability_sum={sum(probs):.2f} (1.0 근처여야 한다)")

    triggers = payload.get("triggers") or {}
    for window in ("within_3m", "within_6m"):
        if not triggers.get(window):
            problems.append(f"empty:triggers.{window}")

    if "is_genuine" not in (payload.get("acceleration_quality") or {}):
        problems.append("missing:acceleration_quality.is_genuine")

    return problems


def save(result: AnalysisResult) -> None:
    from src.db.supabase_client import get_client

    get_client().table("analyses").upsert(
        {
            "code": result.code,
            "fiscal_year": result.fiscal_year,
            "fiscal_quarter": result.fiscal_quarter,
            "model": result.model,
            "cost_usd": result.cost_usd,
            "payload": result.payload,
        },
        on_conflict="code,fiscal_year,fiscal_quarter",
    ).execute()
