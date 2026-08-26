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
from datetime import datetime, timezone

from src.config.constants import (
    ANALYSIS_MODEL,
    ENABLE_WEB_SEARCH,
    EXCERPT_MAX_CHARS,
    LLM_EFFORT,
    LLM_INPUT_TOKEN_BUDGET,
    LLM_MAX_TOKENS,
    WEB_SEARCH_ALLOWED_DOMAINS,
    WEB_SEARCH_MAX_USES,
)
from src.analysis.prompts import ANALYSIS_SCHEMA, ANALYSIS_TOOL_NAME, SYSTEM_PROMPT
from src.utils.cost_guard import ENV_PROD, check_budget, record_usage
from src.utils.env import require_env

# ★ `EXCERPT_MAX_CHARS`는 `constants.py`에서 온다 — 여기서 다시 정의하지 마라(T100).
#   수집기 예산(2,400)보다 작게 두면 저장해 둔 발췌를 **말없이 버린다.**


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
    #: 분기말 종가 시계열. ★ 이게 없으면 `price_position.price_history`를 쓰라고
    #  시켜 놓고 **주가 궤적을 안 주는** 셈이 된다 — 모델은 52주 고저만 보고
    #  "왜 이 가격인가"를 지어내야 한다(T101).
    quarter_prices: list[dict] = field(default_factory=list)
    #: 최근 공시 목록(공시명 + 접수일). 정기보고서 발췌와 별개다 —
    #  발췌는 **내용**이고 이건 **무엇이 언제 나왔는가**다.
    disclosures: list[dict] = field(default_factory=list)
    #: 데이터 기준일(YYYY-MM-DD). 모델이 "지금이 언제인지" 알아야
    #  다음 분기 전망과 트리거 시점을 제대로 잡는다.
    as_of: str | None = None


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


#: 최근 공시를 몇 건까지 보여줄 것인가. 오래된 것은 이번 분기 해석에 쓰이지 않는다.
DISCLOSURE_MAX_ROWS = 12


def _fmt_quarter_prices(rows: list[dict]) -> str:
    """분기말 종가 시계열 + 분기별 등락률.

    ★★ 이게 없으면 `price_position.price_history`를 쓰라고 시켜 놓고 **주가 궤적을
      주지 않는** 셈이다(T101). 모델은 52주 고저만 보고 "왜 이 가격인가"를
      지어내거나 침묵한다 — 숫자만 주고 사건을 쓰라는 T93과 같은 모양이다.
    ★ 등락률을 **여기서 계산해 준다.** 모델에게 산수를 시키면 틀린 값이 본문에 인용된다.
    """
    if not rows:
        return "- 분기말 주가: (없음)"
    ordered = sorted(rows, key=lambda r: (r.get("fiscal_year") or 0,
                                          r.get("fiscal_quarter") or 0))
    out = ["- 분기말 종가 추이 (마지막 행은 현재가):"]
    prev = None
    for r in ordered:
        close = r.get("close")
        if close is None:
            continue
        delta = ""
        if prev:
            pct = (close - prev) / prev * 100
            delta = f"  {pct:+.1f}%"
        out.append(f"    {r['fiscal_year']}.{r['fiscal_quarter']}Q "
                   f"({r.get('trade_date', '—')})  {close:,.0f}원{delta}")
        prev = close
    return "\n".join(out)


def _fmt_disclosures(rows: list[dict]) -> str:
    """최근 공시 목록. 발췌가 '내용'이면 이건 '무엇이 언제 나왔는가'다.

    ★ 실적 발표일을 모르면 모델은 트리거의 `expected_date`를 엉뚱하게 잡는다.
    ★ 정정공시가 있었는지도 여기서만 보인다 — 숫자표는 정정 후 값만 담는다.
    """
    if not rows:
        return "- (수집된 공시 없음)"
    ordered = sorted(rows, key=lambda r: r.get("disclosed_at") or "", reverse=True)
    out = []
    for r in ordered[:DISCLOSURE_MAX_ROWS]:
        day = (r.get("disclosed_at") or "—")[:10]
        out.append(f"- {day}  {r.get('report_nm', '—')}")
    if len(ordered) > DISCLOSURE_MAX_ROWS:
        out.append(f"- … 외 {len(ordered) - DISCLOSURE_MAX_ROWS}건 (오래된 것은 생략)")
    return "\n".join(out)


def build_user_message(data: AnalysisInput) -> str:
    """PRD §7.1의 7개 블록. **공시 원문 전체를 넣지 않는다.**"""
    cap = (
        f"{data.market_cap_krw / 1e12:.2f}조" if data.market_cap_krw else "—"
    )
    parts = [
        # ★ 모델은 "지금이 언제인지" 모른다. 기준일이 없으면 다음 분기 전망과
        #   트리거 시점(`expected_date`)을 학습 시점 기준으로 잡는다(T101).
        f"※ 데이터 기준일: {data.as_of or '—'} — "
        "이 날짜 이후의 사건은 입력에 없다. 모르는 것은 모른다고 써라.",
        "",
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
        _fmt_quarter_prices(data.quarter_prices),
        "",
        "## 6. 공시 발췌",
        (data.excerpt or "(발췌 없음)")[:EXCERPT_MAX_CHARS],
        "",
        "## 6-1. 최근 공시 (무엇이 언제 나왔는가)",
        _fmt_disclosures(data.disclosures),
        "",
        "## 7. 업종 비교 (동일 업종 상위)",
        json.dumps(data.peers, ensure_ascii=False) if data.peers else "(비교군 없음)",
    ]
    return "\n".join(parts)


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=require_env("ANTHROPIC_API_KEY"))


def count_input_tokens(data: AnalysisInput, *, web_search: bool = False) -> int:
    """호출 전 입력 토큰을 센다. 5,000토큰을 넘으면 호출하지 않는다(PRD §7.1).

    ★ 웹 서치가 **가져올** 본문은 여기에 안 잡힌다 — 검색 결과는 호출 중에 붙는다.
      예산은 '보내는 입력'만 재는 것이고, 검색분은 실제 사용량에 나타난다.
    """
    client = _client()
    resp = client.messages.count_tokens(
        model=ANALYSIS_MODEL,
        system=[{"type": "text", "text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": build_user_message(data)}],
        tools=_tools(web_search=web_search),
    )
    return int(resp.input_tokens)


def _tool_definition() -> dict:
    return {
        "name": ANALYSIS_TOOL_NAME,
        "description": "분석 결과를 구조화해 기록한다. 반드시 이 도구로만 응답한다.",
        "input_schema": ANALYSIS_SCHEMA,
        "strict": True,  # 스키마를 정확히 지키도록 강제한다
    }


def _web_search_tool() -> dict:
    """Anthropic 서버 툴. **출처를 화이트리스트로 묶는다.**

    ★ `allowed_domains`가 없으면 종목 토론방·블로그가 섞여 분석이 오염된다 —
      모델은 출처의 신빙성을 스스로 가리지 못한다.
    ★ 서버 툴 오류는 **예외로 오지 않는다.** HTTP 200에 오류 블록으로 온다
      (`web_search_tool_result.content`가 리스트가 아니라 오류 객체).
      그래서 여기서 잡을 것이 없고, 결과가 없으면 모델이 그냥 못 쓴다.
    """
    return {
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": WEB_SEARCH_MAX_USES,
        "allowed_domains": list(WEB_SEARCH_ALLOWED_DOMAINS),
    }


def _tools(*, web_search: bool) -> list[dict]:
    """★ 도구 목록은 캐시 프리픽스의 **맨 앞**이다(tools → system → messages).
    종목마다 목록이 달라지면 캐시가 통째로 깨진다 — 그래서 **실행 내내 고정**한다.
    """
    tools = [_tool_definition()]
    if web_search:
        tools.append(_web_search_tool())
    return tools


def analyze(
    data: AnalysisInput,
    *,
    env: str = ENV_PROD,
    enforce_budget: bool = True,
    token_budget: int = LLM_INPUT_TOKEN_BUDGET,
    web_search: bool | None = None,
) -> AnalysisResult:
    """웹 서치를 쓸지는 `ENABLE_WEB_SEARCH`가 정한다(인자로 덮어쓸 수 있다)."""
    if web_search is None:
        web_search = ENABLE_WEB_SEARCH
    if enforce_budget:
        status = check_budget(env=env)
        if not status.allowed:
            raise BudgetExceeded(
                f"{status.reason}: 월 ${status.month_spent_usd:.2f}/"
                f"${status.month_ceiling_usd} · 오늘 {status.today_count}/{status.daily_limit}"
            )

    user_message = build_user_message(data)
    client = _client()

    # ★★ 예산을 **실제로 검사한다.** 이 파라미터는 오래 선언만 돼 있고 아무 데서도
    #   쓰이지 않았다 — PRD가 "초과 시 호출하지 않는다"고 적어 둔 규칙이
    #   코드에는 없었다. 발췌를 싣기 시작했으므로 이제 진짜 방어가 필요하다.
    # ★ count_tokens는 무료이고 1초쯤 걸린다. 45초짜리 호출 앞에 붙일 만하다.
    if token_budget:
        tokens = count_input_tokens(data, web_search=web_search)
        if tokens > token_budget:
            raise AnalysisError(
                f"{data.code}: 입력 {tokens:,}토큰이 상한 {token_budget:,}을 넘었다. "
                f"공시 발췌가 너무 길다 — 호출하지 않는다(비용 0)."
            )

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
        tools=_tools(web_search=web_search),
        # ★★ **강제 tool_choice와 웹 서치는 함께 못 쓴다.**
        #   `{"type": "tool", ...}`는 모델에게 "지금 당장 이 도구를 불러라"라고 시키는
        #   것이라 검색할 틈이 없다 — 도구를 목록에 넣어 둬도 **한 번도 안 불린다.**
        #   그래서 검색을 켜면 `auto`로 풀고, 대신 시스템 프롬프트가
        #   "반드시 record_analysis로 끝내라"고 못박는다.
        #   ★ 그 대가로 모델이 도구를 안 부르고 글만 쓸 수 있다 — 아래에서 잡아 올린다.
        tool_choice=(
            {"type": "auto"} if web_search
            else {"type": "tool", "name": ANALYSIS_TOOL_NAME}
        ),
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
            continue
        # ★★ **타입까지 본다**(T103). 있고 비어 있지 않다고 정상인 게 아니다 —
        #   실측(금강공업 2026.2Q): `earnings_change`가 객체가 아니라
        #   `'{"cause":">skip'` 15자 문자열로 왔는데 **검증을 그대로 통과**했다.
        #   `None`도 `""`도 아니기 때문이다. 그래서 화면이 조용히 빈칸이 됐다(T95 모양).
        expected = (ANALYSIS_SCHEMA["properties"].get(key) or {}).get("type")
        actual = payload[key]
        if expected == "object" and not isinstance(actual, dict):
            problems.append(f"type:{key} — object가 아니라 {type(actual).__name__}")
        elif expected == "array" and not isinstance(actual, list):
            problems.append(f"type:{key} — array가 아니라 {type(actual).__name__}")
        elif expected == "string" and not isinstance(actual, str):
            problems.append(f"type:{key} — string이 아니라 {type(actual).__name__}")

    # ★ 아래 검사들은 **검증기 자신이 터지지 않게** 타입을 먼저 좁힌다.
    #   구조가 깨진 payload에서 `AttributeError`로 죽으면 배치가 그 종목을
    #   '실패'로 처리하고 **무엇이 잘못됐는지는 영영 안 남는다.**
    scenarios = payload.get("scenarios")
    scenarios = scenarios if isinstance(scenarios, dict) else {}
    probs = []
    for name in ("bull", "base", "bear"):
        node = scenarios.get(name)
        node = node if isinstance(node, dict) else {}
        if "probability" not in node:
            problems.append(f"missing:scenarios.{name}.probability")
        else:
            probs.append(float(node["probability"]))
    if len(probs) == 3 and not (0.9 <= sum(probs) <= 1.1):
        problems.append(f"scenarios.probability_sum={sum(probs):.2f} (1.0 근처여야 한다)")

    triggers = payload.get("triggers")
    triggers = triggers if isinstance(triggers, dict) else {}
    for window in ("within_3m", "within_6m"):
        if not triggers.get(window):
            problems.append(f"empty:triggers.{window}")

    quality = payload.get("acceleration_quality")
    quality = quality if isinstance(quality, dict) else {}
    if "is_genuine" not in quality:
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
            # ★★ **반드시 직접 넣는다.** DB 기본값은 INSERT에만 걸리므로 upsert로
            #   덮어쓸 때는 `created_at`이 **처음 분석한 날짜에 머문다**(T102).
            #   `--refresh-before`가 이 칸으로 "낡았는가"를 판정하는데, 값이 안
            #   움직이면 **방금 다시 돌린 종목이 계속 다시 대상이 된다** —
            #   배치가 끊겼다 재개될 때마다 상위 종목만 반복 결제한다.
            #   즉 의미는 '생성일'이 아니라 **'마지막으로 분석한 시각'**이다.
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="code,fiscal_year,fiscal_quarter",
    ).execute()
