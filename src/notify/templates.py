# PRD Ref: §8.3, §8.4, §8.5 · §4.4
"""텔레그램 메시지 템플릿 — 순수 함수. 외부 I/O 금지.

발송 대상은 매트릭스 등급 **★ 와 ○ 만**(constants.NOTIFY_GRADES).
△와 ·는 대시보드에만 남긴다.

★★ **모바일에서 읽는다는 전제로 만든다.**
   텔레그램 기본 폰트는 가변폭이라 바깥 본문에서는 공백 정렬이 통하지 않는다 —
   숫자 표는 반드시 `<pre>` 안에 넣어야 자릿수가 맞는다.
   한 줄은 32자를 넘기지 않는다(폰에서 접히면 표가 통째로 깨진다).
"""

from __future__ import annotations

from src.config.constants import FLASH_DAILY_MAX
from src.notify.telegram import PREFIX, esc

#: 스코어 항목이 **무엇을 재는지**. "게이트 통과"만으로는 왜 뽑혔는지 읽을 수 없다.
#: 모바일 표에 들어가므로 라벨은 짧게 — 길면 줄이 접힌다.
AXIS_LABELS: dict[str, tuple[str, int]] = {
    "A": ("성장가속", 35), "B": ("수익성", 32),
    "C": ("서프라이즈", 15), "D": ("회계품질", 18),
}
ITEM_LABELS: dict[str, tuple[str, int]] = {
    "a1": ("매출YoY델타", 14), "a2": ("영업익YoY델타", 10),
    "a3": ("TTM매출추세", 6), "a4": ("2분기연속가속", 5),
    "b1": ("OPM YoY", 14), "b2": ("TTM OPM추세", 7),
    "b3": ("영업레버리지", 6), "b4": ("업종대비OPM", 5),
    "c1": ("영업익서프라이즈", 9), "c2": ("매출서프라이즈", 6),
    "d1": ("현금흐름정합성", 6), "d2": ("주식수희석", 4),
    "d3": ("운전자본", 4), "d4": ("유동성", 4),
}
#: 축이 통째로 미측정일 때 그 이유를 사람 말로.
AXIS_MISSING_REASON = {
    "C": "컨센 없음 → 분모제외(0점 아님)",
    "D": "확정 재무 대기",
}

#: PRI 항목 — `src/screener/pri.py`의 PRI_NEW_WEIGHTS와 같아야 한다.
PRI_ITEMS = (
    ("earnings_reaction", "실적반응", 20),
    ("expectation_gap", "이익전망", 20),
    ("earnings_vs_multiple", "이익/멀티플", 20),
    ("valuation_burden", "밸류부담", 20),
    ("momentum_overheat", "모멘텀", 20),
)

# PRI 3.0 저장 행을 읽는 호환 표시. 새 계산은 위 다섯 항목만 쓴다.
PRI_V3_ITEMS = (
    ("event", "실적초과반응", 15),
    ("revision", "전망·주가괴리", 10),
    ("driver", "멀티플주도", 15),
    ("implied_growth", "내재성장갭", 20),
    ("valuation_history", "역사밸류", 10),
    ("valuation_peer", "피어성장단가", 10),
    ("relative", "중기상대주가", 10),
    ("overheat", "단기과열", 10),
)

KIND_FLASH = "flash"
KIND_DAILY = "daily"
KIND_UPGRADE = "upgrade"
KIND_BUDGET = "budget"

#: 결측 표기. 0으로 채우면 "측정해서 0"과 구분되지 않는다.
DASH = "—"


# ═══════════════════════════════════════════════════════════════════
# 모바일 가독성 — 숫자 폭 맞추기
#
# ★ 표 안에서 **단위를 섞으면 자릿수가 흔들려 표가 표로 안 보인다.**
#   1,714,995억과 135억이 한 열에 있으면 눈이 자릿수를 못 센다.
#   그래서 계열 전체의 최댓값으로 단위를 하나 골라 통일한다.
# ═══════════════════════════════════════════════════════════════════
def pick_unit(values) -> tuple[float, str]:
    """계열에 맞는 (나눗수, 단위). 표 하나에는 단위 하나만 쓴다."""
    biggest = max((abs(v) for v in values if v is not None), default=0.0)
    return (1e12, "조") if biggest >= 1e12 else (1e8, "억")


def amount(value, divisor: float, width: int = 0) -> str:
    """단위를 미리 정해 놓고 숫자만 찍는다."""
    if value is None:
        return f"{DASH:>{width}}" if width else DASH
    digits = 1 if divisor >= 1e12 else 0
    text = f"{value / divisor:,.{digits}f}"
    return f"{text:>{width}}" if width else text


def signed(value, width: int = 0, digits: int = 1, unit: str = "%") -> str:
    if value is None:
        return f"{DASH:>{width}}" if width else DASH
    text = f"{value:+.{digits}f}{unit}"
    return f"{text:>{width}}" if width else text


def display_width(text: str) -> int:
    """모노스페이스 표시 폭. **한글·이모지는 2칸**이다.

    ★ `len()`으로 재면 한글이 절반으로 계산돼 "32자 이내"가 실제로는 60칸이 된다.
      실측: 제품 줄이 len 기준으론 짧아 보였는데 폰에서 6줄로 접혔다.
    """
    return sum(1 if c.isascii() else 2 for c in text)


def clip(text: str, limit: int) -> str:
    """표시 폭 기준으로 자른다. 잘랐으면 …를 붙여 숨기지 않는다."""
    if display_width(text) <= limit:
        return text
    out, width = [], 0
    for ch in text:
        w = 1 if ch.isascii() else 2
        if width + w > limit - 1:
            break
        out.append(ch)
        width += w
    return "".join(out) + "…"


def pad(text: str, width: int, align: str = "<") -> str:
    """**표시 폭 기준** 패딩.

    ★ `f"{name:<10}"`은 **문자 수**로 채운다. 한글은 폭이 2라 열이 밀린다 —
      실측: 일일 요약에서 '저스템'(6칸)과 '하나머티리얼즈'(14칸)가 같은 10으로 계산돼
      점수 열이 종목마다 다른 자리에 찍혔다.
    """
    short = clip(text, width)
    gap = " " * max(0, width - display_width(short))
    return (short + gap) if align == "<" else (gap + short)


def bar(ratio: float, width: int = 5) -> str:
    """고정폭 막대. `<pre>` 안이라 폰에서도 정렬이 유지된다."""
    filled = round(min(max(ratio, 0.0), 1.0) * width)
    return "█" * filled + "·" * (width - filled)


def _pct(value, digits: int = 1, unit: str = "%") -> str:
    if value is None:
        return DASH
    return f"{float(value):+.{digits}f}{unit}"


def _num(value, digits: int = 0) -> str:
    if value is None:
        return DASH
    return f"{float(value):,.{digits}f}"


def _eok(value) -> str:
    if value is None:
        return DASH
    return f"{float(value) / 1e8:,.0f}억"


# ═══════════════════════════════════════════════════════════════════
# 한국어 문장 조립 — 알림은 사람이 읽는 글이다
# ═══════════════════════════════════════════════════════════════════
def has_final_consonant(text: str) -> bool:
    """마지막 글자에 받침이 있는가.

    ★ 받침을 안 보면 '제조업다'(→'제조업이다'), '반도체이다'(→'반도체다')처럼
      어색한 문장이 나온다. 눈에 걸린다.
    """
    if not text:
        return False
    last = text.strip()[-1]
    if not ("가" <= last <= "힣"):
        return False  # 영문·숫자로 끝나면 받침 규칙을 적용하지 않는다
    return (ord(last) - 0xAC00) % 28 != 0


def copula(text: str) -> str:
    """서술격 조사. 받침 있으면 '이다', 없으면 '다'."""
    return "이다" if has_final_consonant(text) else "다"


def subject_particle(text: str) -> str:
    """주격 조사. 받침 있으면 '은', 없으면 '는'."""
    return "은" if has_final_consonant(text) else "는"


def tidy_industry(industry) -> str:
    """업종명을 문장에 넣을 수 있게 다듬는다.

    ★ 통계청 업종명은 길고 딱딱하다. 그대로 자르면 '장비 제…'처럼
      **말이 안 되는 조각**이 남는다 — 어절 경계에서 자른다.
    """
    if not industry:
        return ""
    text = str(industry).strip()
    if display_width(text) <= 30:
        return text
    kept: list[str] = []
    for word in text.split():
        if display_width(" ".join(kept + [word])) > 30:
            break
        kept.append(word)
    return " ".join(kept) if kept else clip(text, 30)


def tidy_products(products) -> list[str]:
    """제품 목록에서 군더더기를 걷어낸다.

    ★ 원문에 '제조·도매·제품' 꼬리와 괄호 설명이 붙어 있어 그대로 쓰면
      '통신 및 방송 장비 제조(무선) 제품'처럼 길다. 핵심 명사만 남긴다.
    """
    if not products:
        return []
    out: list[str] = []
    for raw in str(products).split(","):
        item = raw.strip().split("(")[0].strip()
        for tail in (" 제조", " 도매", " 제품", " 판매"):
            if item.endswith(tail):
                item = item[: -len(tail)].strip()
        if item and item not in out:
            out.append(clip(item, 18))
        if len(out) == 3:
            break
    return out


# ═══════════════════════════════════════════════════════════════════
# ⚡ 즉시 알림
# ═══════════════════════════════════════════════════════════════════
def flash_message(ctx: dict) -> str:
    """⚡ 즉시 알림 (PRD §8.3). ★/○ 만 호출된다.

    ★★ **한 화면에 들어와야 한다.** 스크롤하며 읽는 알림은 안 읽힌다.
       분기 추이·컨센서스 상세는 대시보드로 넘기고, 여기서는
       "무슨 회사가 / 얼마나 좋아졌고 / 주가는 얼마나 알고 있고 / 비싼가"만 답한다.
    """
    grade = ctx.get("grade") or ""
    lines = [
        f"{PREFIX}<b>{grade} {esc(ctx.get('name'))}</b> <code>{ctx.get('code','')}</code>",
    ]
    for block in (
        profile_block, earnings_block, pri_block,
        valuation_block, warning_block, analysis_block,
    ):
        lines += block(ctx)

    lines += link_block(ctx)
    return "\n".join(lines)


def link_block(ctx: dict) -> list[str]:
    """바깥으로 나가는 링크 — 대시보드 · 네이버증권 · StockEasy."""
    parts = []
    if ctx.get("url"):
        parts.append(f'<a href="{ctx["url"]}">대시보드</a>')
    if ctx.get("naver_url"):
        parts.append(f'<a href="{ctx["naver_url"]}">네이버증권</a>')
    if ctx.get("stockeasy_url"):
        parts.append(f'<a href="{ctx["stockeasy_url"]}">StockEasy</a>')
    out = ["", "🔗 " + " · ".join(parts)] if parts else []
    for item in ctx.get("beneficiaries") or []:
        name = esc(item.get("name") or item.get("code"))
        out.append(
            f'↳ 수혜 {name}: <a href="{item["naver_url"]}">네이버증권</a> · '
            f'<a href="{item["stockeasy_url"]}">StockEasy</a>'
        )
    return out


def profile_block(ctx: dict) -> list[str]:
    """무엇으로 돈을 버는 회사인가 — **핵심 사업과 강점만.**

    ★ 업종 분류('통신 및 방송 장비 제조업')는 통계청 표기라 회사를 설명하지 못한다.
      제품이 훨씬 구체적이다.
    ★ '강점'은 지어내지 않는다. **스코어가 실제로 잰 것**에서만 끌어온다 —
      업종 대비 OPM 상위(b4)나 영업레버리지(b3)가 만점이면 그게 데이터로 확인된 강점이다.
    """
    name = esc(ctx.get("name") or "")
    raw_name = str(ctx.get("name") or "")
    cap = ctx.get("market_cap_label")
    rank, peers = ctx.get("market_cap_rank"), ctx.get("peer_count")

    items = tidy_products(ctx.get("products"))
    core = " · ".join(items) if items else tidy_industry(ctx.get("industry"))
    if not core:
        return []

    # 제품이면 '~를 만든다', 업종뿐이면 '~ 기업이다'로 문장을 맞춘다.
    if items:
        verb = "을 만든다" if has_final_consonant(core) else "를 만든다"
        line = f"{name}{subject_particle(raw_name)} <b>{esc(core)}</b>{verb}."
    else:
        line = f"{name}{subject_particle(raw_name)} <b>{esc(core)}</b> 기업{copula('기업')}."
    if cap and cap != DASH:
        line += f" 시총 {cap}원"
        line += f"({esc(str(ctx.get('board') or ''))} {rank}위)." if rank else "."

    out = ["", line]
    strength = strength_line(ctx)
    if strength:
        out.append(strength)
    return out


def strength_line(ctx: dict) -> str:
    """스코어에서 확인된 강점만 문장으로. 없으면 빈 문자열.

    ★ 만점 항목만 쓴다. 부분 점수를 '강점'이라 부르면 말이 헐거워진다.
    """
    raw = ctx.get("raw") or {}
    facts = []
    if raw.get("b4") == 5:
        facts.append("업종 내 수익성 상위")
    if raw.get("b3") == 6:
        facts.append("영업레버리지 작동")
    if raw.get("b1") == 14:
        facts.append("마진 개선 뚜렷")
    if raw.get("a4") == 5:
        facts.append("2분기 연속 가속")
    return f"💪 {' · '.join(facts[:3])}" if facts else ""


def earnings_block(ctx: dict) -> list[str]:
    """분기 실적 — **표 대신 줄 단위로.**

    ★ `<pre>` 표는 폰에서 폭이 빠듯하고, 항목이 셋뿐이면 표를 쓸 이유가 없다.
      이모지로 항목을 구분하면 눈이 세로로 훑는다.
    ★ 가속은 **매출·영업이익·OPM 셋 다** 보여준다 — 매출만 늘고 이익이 안 늘면
      그건 가속이 아니라 외형만 커진 것이다.
    """
    is_est = ctx.get("is_estimate")
    revenue, op = ctx.get("revenue"), ctx.get("op")
    divisor, unit = pick_unit([revenue, op])

    head = (
        f"📊 <b>{ctx.get('fiscal_year')}.{ctx.get('fiscal_quarter')}Q "
        f"{'잠정' if is_est else '확정'}</b>"
    )
    if not is_est and ctx.get("confirmed_delta"):
        head += " <i>← 확정 반영</i>"

    out = [
        "",
        head,
        f"💵 매출   <b>{amount(revenue, divisor).strip()}{unit}</b>"
        f"  {signed(ctx.get('revenue_yoy'))}",
        f"💰 영업익 <b>{amount(op, divisor).strip()}{unit}</b>"
        f"  {signed(ctx.get('op_yoy'))}",
        f"📐 OPM    <b>{signed(ctx.get('opm')).strip()}</b>"
        f"  {signed(ctx.get('opm_yoy_delta'), 0, 1, '%p')}",
    ]

    accel = accel_lines(ctx)
    if accel:
        # ★ 제목에 정의를 박아 둔다. '가속'만 쓰면 '성장률이 높다'로 읽힌다 —
        #   이 시스템이 보는 건 성장률이 아니라 **성장률의 변화**다.
        out += ["", "⚡ <b>가속</b> <i>(전분기 성장률 → 이번 분기)</i>"] + accel

    cd = ctx.get("confirmed_delta") or {}
    parts = [f"{k} {signed(v)}" for k, v in cd.items() if v is not None]
    if parts:
        out.append(f"🔁 잠정 대비 {' · '.join(parts)}")

    out.append(score_line(ctx))
    return out


def accel_lines(ctx: dict) -> list[str]:
    """매출·영업이익·OPM의 **전분기 대비 가속** 세 줄.

    ★ 이 시스템의 게이트가 보는 것이 정확히 이것이다 — 성장률이 아니라
      **성장률의 변화**. 셋을 나란히 놓아야 "이익이 같이 따라오는가"가 보인다.
    ★ 실적 가속의 정의(2026-08-17): 매출 YoY **와** 영업이익 YoY가 **둘 다** 높아진 것.
      그래서 이 표의 앞 두 줄이 게이트 G1·G2 그 자체다. OPM은 참고다.
    """
    rows = [
        ("매출", ctx.get("revenue_yoy_prev"), ctx.get("revenue_yoy")),
        ("영업익", ctx.get("op_yoy_prev"), ctx.get("op_yoy")),
        ("OPM", ctx.get("opm_prev"), ctx.get("opm")),
    ]
    out = []
    for label, before, after in rows:
        if before is None or after is None:
            continue
        # ★ 값 자체는 언제나 %다. **변화량만** %p다 —
        #   OPM 전분기 값을 '+42.8%p'로 쓰면 마진이 아니라 변화폭으로 읽힌다.
        delta = after - before
        mark = "▲" if delta > 0 else ("▼" if delta < 0 else "―")
        out.append(
            f"   {pad(label, 7)}{signed(before, 0, 1)} → {signed(after, 0, 1)}"
            f"  {mark}{abs(delta):,.1f}%p"
        )
    return out


def score_line(ctx: dict) -> str:
    """스코어 한 줄 — 총점 + 축별 요약.

    ★ 항목별 상세는 대시보드로 넘긴다. 여기서는 **어느 축이 점수를 냈는지**만.
    ★ 미측정 축은 '0'이 아니라 '—'다(ADR 2). 분모에서 빠졌다는 뜻이다.
    """
    bits = []
    for axis, (label, maximum) in AXIS_LABELS.items():
        value = ctx.get(f"score_{axis.lower()}")
        bits.append(
            f"{label} {value:.0f}/{maximum}" if value is not None else f"{label} —"
        )
    return (
        f"🎯 <b>기업매력 {_num(ctx.get('score'), 0)}</b>"
        f" <i>(실적근거 {' · '.join(bits)})</i>"
    )


def pri_block(ctx: dict) -> list[str]:
    """주가반영도 — **숫자 하나 + 반영/미반영 한 줄씩.**

    ★ 총점만으로는 62점이 무슨 뜻인지 모른다. 무엇이 반영됐고 무엇이 아직인지가
      곧 "왜 지금인가"의 답이다.
    """
    pri = ctx.get("pri")
    parts = ctx.get("pri_parts_detail") or {}
    label = (
        "미반영" if pri is not None and pri < 40
        else "부분반영" if pri is not None and pri <= 65
        else "선반영" if pri is not None else "판정 불가"
    )

    reflected, pending, unmeasured = [], [], []
    items = PRI_ITEMS if any(key in parts for key, _, _ in PRI_ITEMS) else PRI_V3_ITEMS if any(
        key in parts for key, _, _ in PRI_V3_ITEMS
    ) else (
        ("p1", "52주고점", 25),
        ("p2", "발표일대비", 25),
        ("p3", "9Q PER", 20),
        ("p4", "외국인5일", 10),
        ("p5", "RSI45", 20),
    )
    for key, name, maximum in items:
        value = parts.get(key)
        if value is None:
            unmeasured.append(name)
        elif value / maximum >= 0.65:
            reflected.append(name)
        else:
            pending.append(name)

    # ★ 미측정 항목은 **적지 않는다**(사용자 요청). 반영/미반영만 남긴다 —
    #   알림에서 "PER밴드 미측정"은 판단에 쓸 정보가 아니다.
    #   다만 **아무것도 못 쟀을 때는** 그 사실을 밝힌다. 62점이 없는 것과
    #   0점인 것은 완전히 다르기 때문이다.
    out = ["", f"📉 <b>주가반영도 {_num(pri, 0)}</b> · {label}"]
    if reflected:
        out.append(f"   ✅ 반영: {' · '.join(reflected)}")
    if pending:
        out.append(f"   ⬜ 미반영: {' · '.join(pending)}")
    if not reflected and not pending:
        out.append("   <i>시세를 못 받아 판정하지 못했다</i>")
    return out


def score_breakdown(ctx: dict) -> list[str]:
    """축별 막대 + 항목별 득점.

    ★ 총점만 보면 왜 뽑혔는지 모른다.
    ★ 미측정 축은 **0점이 아니라 분모 제외**다(ADR 2).
    ★ 축 **안의** 결측은 분모에서 안 빠져 조용히 감점된다(T26) — 따로 표시한다.
    ★ 측정해서 0점인 항목도 숨기지 않는다(T38).
    """
    raw = ctx.get("raw") or {}
    lines: list[str] = []
    for axis, (axis_name, axis_max) in AXIS_LABELS.items():
        score = ctx.get(f"score_{axis.lower()}")
        if score is None:
            lines.append(
                f"{axis} {axis_name:<7}  미측정"
            )
            lines.append(f"   {AXIS_MISSING_REASON.get(axis, '')}")
            continue

        lines.append(
            f"{axis} {axis_name:<7}{bar(score / axis_max)} {score:>2.0f}/{axis_max}"
        )
        for key in (k for k in ITEM_LABELS if k.startswith(axis.lower())):
            label, item_max = ITEM_LABELS[key]
            value = raw.get(key)
            if value is None:
                lines.append(f"   {label:<13} 미측정 -{item_max}")
            else:
                lines.append(f"   {label:<13}{value:>4.0f}/{item_max}")
    return lines


def valuation_block(ctx: dict) -> list[str]:
    """밸류에이션 — **최근 4분기 PER과 향후 4분기 Forward PER, 둘만.**

    ★ 증권사 화면의 PER은 과거 12개월 EPS 기준이라 실적 급가속 구간에서 크게
      과대평가된다 — 이 시스템이 겨냥하는 구간이 정확히 거기다.
      실측: 삼성전자 후행 41.8배 vs 최근 4분기 10.6배 vs 향후 4분기 3.9배.
      **후행 PER 값은 아예 싣지 않는다.** 나란히 두면 큰 쪽에 눈이 간다.
    ★ Forward PER의 재료는 **연간 컨센서스**다. 없는 종목에서는 표시하지 않는다 —
      만들어내지 않는다.
    """
    per_ttm, fwd_per = ctx.get("per_ttm"), ctx.get("fwd_per")
    if per_ttm is None and fwd_per is None:
        return ["", "💰 <b>PER</b> — 최근 4분기 순이익 미확보"]

    out = ["", "💰 <b>밸류에이션</b>"]
    if per_ttm is not None:
        out.append(f"   최근 4분기 <b>{_num(per_ttm, 1)}배</b>")
    if fwd_per is not None:
        out.append(f"   향후 4분기 <b>{_num(fwd_per, 1)}배</b> <i>(컨센 기준)</i>")
        if per_ttm is not None and per_ttm > 0 and fwd_per > 0 and fwd_per < per_ttm:
            drop = (1 - fwd_per / per_ttm) * 100
            out.append(f"   <i>이익 증가로 {drop:.0f}% 낮아진다</i>")
    else:
        out.append("   <i>향후 4분기는 컨센서스가 없어 계산하지 않았다</i>")
    return out


def warning_block(ctx: dict) -> list[str]:
    warn = []
    if ctx.get("base_effect_warning"):
        warn.append("기저효과")
    if not ctx.get("base_effect_measurable", True):
        warn.append("기저효과 판정불가")
    if ctx.get("sector_caveat"):
        warn.append("업종주의")
    if not ctx.get("has_consensus"):
        warn.append("컨센서스없음(정규화)")
    if ctx.get("is_estimate"):
        warn.append("잠정치")
    return ["", "⚠️ " + " · ".join(warn)] if warn else []


def analysis_block(ctx: dict) -> list[str]:
    out: list[str] = []
    if ctx.get("thesis"):
        out += ["", f"💡 {esc(ctx['thesis'])}"]
    if ctx.get("sustainability_quarters") is not None:
        out.append(f"<i>가속 지속 전망 {ctx['sustainability_quarters']}분기</i>")
    triggers = ctx.get("triggers") or []
    if triggers:
        out += ["", "🔔 <b>3개월 내 트리거</b>"]
        out += [f"· {esc(t)}" for t in triggers[:3]]
    if ctx.get("top_risk"):
        out += ["", f"⚠️ {esc(ctx['top_risk'])}"]
    return out


# ═══════════════════════════════════════════════════════════════════
# 📊 일일 요약 · 🔄 승격 · 💸 예산
# ═══════════════════════════════════════════════════════════════════
def daily_digest(ctx: dict) -> str:
    """📊 일일 요약 (PRD §8.4). 4,096자를 넘으면 상위 N개로 자르고 '외 M종목'."""
    rows = ctx.get("rows") or []
    counts = ctx.get("counts") or {}

    lines = [
        f"{PREFIX}<b>📊 {ctx.get('date')} 발굴 요약</b>",
        f"공시 {counts.get('disclosures', 0)} · 게이트 {counts.get('gate_passed', 0)} · "
        + " ".join(f"{g}{counts.get(g, 0)}" for g in ("★", "○", "△") if counts.get(g)),
    ]
    technical = ctx.get("technical_scan")
    if technical:
        if technical.get("status") == "complete":
            sent = int(technical.get("sent", 0) or 0)
            lines.append(
                f"📈 오늘의 종목 추천: 가격 {technical.get('price', 0)} → "
                f"5·20일선 {technical.get('sma', 0)} → MACD {technical.get('macd', 0)} "
                f"· RSI 보강 {technical.get('rsi', 0)} · "
                f"{'추천 발송 ' + str(sent) + '건' if sent else '조건 충족 추천 0건'}"
            )
        else:
            lines.append("⚠️ 기술 신호 점검/발송 오류 — 종목 알림 실행 기록 확인 필요")

    if not rows:
        lines += ["", "오늘 발송 대상(★/○)은 없다."]
    else:
        shown = rows[:FLASH_DAILY_MAX]
        lines += ["", "<pre>", f"등급 {pad('종목', 14)}점수  반영 매출YoY"]
        for r in shown:
            lines.append(
                f" {r.get('grade', ' ')}  {pad(str(r.get('name', '')), 14)}"
                f"{_num(r.get('score')):>4}"
                f"{_num(r.get('pri')):>6}"
                f"{_pct(r.get('revenue_yoy')):>8}"
            )
        lines.append("</pre>")
        if len(rows) > len(shown):
            lines.append(f"… 외 {len(rows) - len(shown)}종목")

    if ctx.get("url"):
        lines += ["", f'🔗 <a href="{ctx["url"]}">대시보드</a>']
    return "\n".join(lines)


def upgrade_message(ctx: dict) -> str:
    """🔄 승격 알림 (PRD §8.5). △의 PRI가 떨어져 ○/★로 올라온 종목."""
    lines = [f"{PREFIX}<b>🔄 승격 — 조정으로 담을 구간</b>", ""]
    for r in ctx.get("rows") or []:
        lines.append(
            f"{r.get('from_grade')} → <b>{r.get('to_grade')}</b> "
            f"{esc(r.get('name'))} <code>{r.get('code')}</code>"
        )
        lines.append(
            f"  스코어 {_num(r.get('score'))} · 반영도 "
            f"{_num(r.get('pri_before'))} → {_num(r.get('pri'))}"
        )
    if ctx.get("url"):
        lines += ["", f'🔗 <a href="{ctx["url"]}">대시보드</a>']
    return "\n".join(lines)


def technical_setup_message(ctx: dict) -> str:
    """📈 필수 교차 신호와 선택 RSI 보강을 구분해 알린다."""
    company = ctx.get("company_growth") or {}
    sector = ctx.get("sector_growth") or {}
    technical = ctx.get("technical") or {}
    revenue = company.get("revenue_yoy") or []
    op = company.get("op_yoy") or []
    sector_revenue = sector.get("revenue_yoy") or []
    sector_op = sector.get("op_yoy") or []
    strong = technical.get("strong_recommendation") is True
    early = ctx.get("early_priority") is True
    sma_state = "당일 상향 교차" if technical.get("sma_crossed") else "상향 교차 접근"
    macd_state = "당일 상향 교차" if technical.get("macd_crossed") else "상향 교차 접근"
    lines = [
        f"{PREFIX}<b>{'🔥 오늘의 강력 추천 종목' if strong else '📈 오늘의 추천 종목'} · 5·20일선/MACD</b>",
        "",
        f"<b>{esc(ctx.get('name'))}</b> <code>{esc(ctx.get('code'))}</code>"
        f" · {esc(ctx.get('sector'))} · {esc(ctx.get('grade'))}",
        "🔎 초기 흑전·낮은 주가반영도 우선 후보 · 실제 수주 증가는 공시 확인 필요"
        if early else "🔎 지속 가속 후보 · 실제 수주 증가는 공시 확인 필요",
        f"🏭 산업 {len(sector_revenue)}Q 중앙값  매출 {join_arrow(sector_revenue)} · 영업익 {join_arrow(sector_op)}",
        f"📊 기업 {len(revenue)}Q YoY     매출 {join_arrow(revenue)} · 영업익 "
        f"{'흑전(성장률 계산 금지)' if company.get('op_status_label') == '흑전' else join_arrow(op)}",
        f"📉 가격 {esc(technical.get('price_regime'))} · 50일 고점 대비 "
        f"{_pct(technical.get('drawdown_50d_pct'))} · 20일 {_pct(technical.get('ret_20d_pct'))}",
        f"🗓 최근 분기 실적 발표 {esc(technical.get('announcement_date'))} · 발표 다음 거래일 종가 대비 "
        f"{_pct(technical.get('announcement_return_pct'))} · 발표 후 고점 대비 "
        f"{_pct(technical.get('post_announcement_drawdown_pct'))}",
        f"📐 5일선 {_num(technical.get('sma5'), 1)} / 20일선 {_num(technical.get('sma20'), 1)} "
        f"· 간격 {signed(technical.get('sma_gap_pct'), 0, 2, '%')} · {sma_state}",
        f"〰️ MACD {signed(technical.get('macd'), 0, 2, '')} / Signal "
        f"{signed(technical.get('signal'), 0, 2, '')} · Gap "
        f"{signed(technical.get('histogram_pct'), 0, 3, '%')} · {macd_state}",
        f"🌡 RSI(14) {_num(technical.get('rsi'), 1)} · {'45 미만 상승 보강' if strong else '보강 조건 미충족(필수 아님)'}",
        *fundamental_investment_idea(ctx),
        "⚠️ 매수 확정 신호가 아닙니다. 두 교차의 유지와 저점·실적 근거를 재확인하고, "
        "조정 저점 이탈 또는 교차 실패 시 관찰을 취소합니다.",
    ]
    if ctx.get("url") or ctx.get("naver_url"):
        parts = []
        if ctx.get("url"):
            parts.append(f'<a href="{ctx["url"]}">대시보드</a>')
        if ctx.get("naver_url"):
            parts.append(f'<a href="{ctx["naver_url"]}">네이버증권</a>')
        lines += ["", "🔗 " + " · ".join(parts)]
    return "\n".join(lines)


def fundamental_investment_idea(ctx: dict) -> list[str]:
    """기술 신호와 분리한 기업 펀더멘털 투자 가설.

    공개된 구조화 수치와 주요 제품만 사용한다. 제품 수요 원인·수주·고객사는 이
    배치가 확인하지 않으므로 만들지 않고, 다음 분기 검증 항목으로 남긴다.
    """
    company = ctx.get("company_growth") or {}
    fundamental = ctx.get("fundamental") or {}
    consensus = ctx.get("consensus") or {}
    revenue = company.get("revenue_yoy") or []
    op = company.get("op_yoy") or []
    products = tidy_products(ctx.get("products"))
    core = " · ".join(products) if products else tidy_industry(ctx.get("industry"))
    stage = str(company.get("stage") or "지속 가속")

    lines = ["", "💡 <b>펀더멘털 투자 아이디어</b>"]
    lines.append(
        f"🏢 본업: <b>{esc(core)}</b>"
        if core else f"🏢 본업: <b>{esc(ctx.get('sector'))}</b> 사업군"
    )
    if stage == "초기 흑전" or company.get("op_status_label") == "흑전":
        lines.append(
            f"📈 실적 근거: 매출 YoY {join_arrow(revenue)}로 가속하면서 영업이익이 흑자전환했습니다."
        )
    else:
        lines.append(
            f"📈 실적 근거: 매출 YoY {join_arrow(revenue)}, 영업이익 YoY {join_arrow(op)}로 동반 가속했습니다."
        )

    profitability = []
    if fundamental.get("opm") is not None:
        profitability.append(f"OPM {_pct(fundamental.get('opm'))}")
    if fundamental.get("opm_yoy_delta") is not None:
        profitability.append(f"전년 동기 대비 {signed(fundamental.get('opm_yoy_delta'), 0, 1, '%p')}")
    if fundamental.get("ttm_opm_delta") is not None:
        profitability.append(f"TTM 변화 {signed(fundamental.get('ttm_opm_delta'), 0, 1, '%p')}")
    lines.append(
        "💰 수익성: " + (" · ".join(profitability) if profitability else "공개 분기 이익률 변화 추가 확인 필요")
    )

    pri = ctx.get("pri")
    pri_tone = (
        "낮은 반영 구간" if pri is not None and float(pri) < 35 else
        "부분 반영 구간" if pri is not None and float(pri) < 65 else
        "선반영 점검 구간" if pri is not None else "반영도 미측정"
    )
    valuation = [f"투자 매력도 {_num(ctx.get('investment_score'), 1)}", f"PRI {_num(pri, 1)}({pri_tone})"]
    if consensus.get("fwd_per") is not None:
        valuation.append(f"내년 F.PER {_num(consensus.get('fwd_per'), 1)}배")
    if consensus.get("roe_next_est") is not None:
        year = consensus.get("roe_next_year") or "내년"
        valuation.append(f"{year}년 F.ROE {_pct(consensus.get('roe_next_est'))}")
    lines.append("⚖️ 가치·반영: " + " · ".join(valuation))

    if pri is not None and float(pri) < 35:
        thesis = "실적과 수익성 개선이 이어지는 동안 주가 반영도가 낮아, 다음 분기에도 가속이 확인되면 재평가 여지가 있습니다."
    elif pri is not None and float(pri) < 65:
        thesis = "실적 개선은 일부 주가에 반영됐으며, 추가 재평가에는 다음 분기 성장 지속과 이익률 방어가 필요합니다."
    else:
        thesis = "실적 가속의 지속 여부가 핵심이며, 현재 가격에서는 다음 분기 이익률과 밸류에이션 부담을 함께 확인해야 합니다."
    lines.append(f"🧠 핵심 가설: {thesis}")
    lines.append("🔍 다음 확인: 다음 분기 매출·영업이익 YoY와 OPM, 공시로 확인되는 수주 또는 판매처·주요 고객 변화를 점검합니다.")
    return lines


def join_arrow(values: list | tuple) -> str:
    """성장률 이력을 `+1.0% → +2.0%`로 표시한다."""
    return " → ".join(_pct(value) for value in values) if values else DASH


def budget_message(ctx: dict) -> str:
    """💸 월 실링 도달 통지 (PRD §7.3). 큐로 이월했음을 알린다."""
    return "\n".join([
        f"{PREFIX}<b>💸 월 LLM 비용 실링 도달</b>",
        "",
        f"이번 달 ${ctx.get('spent'):.2f} / ${ctx.get('ceiling')}",
        f"대기 큐 {ctx.get('queued', 0)}건 — 다음 달로 이월했다.",
        "발굴·스크리닝은 계속 돌고 있다.",
    ])
