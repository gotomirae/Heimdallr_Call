# PRD Ref: §2 검토⑥, §6 · ADR 2
"""결과 추적 — 순수 함수. 외부 I/O 금지.

★★ **이 모듈의 존재 이유:** 스코어 배점(14/10/6…)에는 지금 이론적 근거가 없다.
   나중에 데이터로 조정할 수 있는 구조를 만들어 두지 않으면 이 시스템은
   영구히 검증 불가능한 자의적 룰로 남는다(PRD §2 검토⑥).

★ 발표 시점의 grade/score/pri를 **함께 스냅샷**한다. 나중에 재계산하면
  그때의 판단이 아니라 지금의 판단으로 과거를 채점하게 된다(사후확신 편향).

★ 측정 못 한 것은 **0이 아니라 None**이다. 수익률 0%("안 움직였다")와
  "아직 20거래일이 안 지났다"는 완전히 다른데, 0으로 채우면 평균이 0 쪽으로 끌려간다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: 측정 지점(**거래일** 기준). 음수는 발표 **전**이다.
#:   -5 = 발표 직전 5거래일 수익률 (미리 오른 정도 = 정보 선반영)
#:    0 = 발표 당일 등락률       (직전 거래일 종가 → 발표일 종가)
#:   +5 / +20 / +60 = 발표일 종가 대비
#: ★ D+60은 약 3개월이라 분기마다 한 번 채워진다.
HORIZONS = (-5, 0, 1, 5, 20, 60)

#: 화면에서 보여 주는 시점(사용자 지정). D+1은 저장만 하고 표시하지 않는다.
DISPLAY_HORIZONS = (-5, 0, 5, 20, 60)


def horizon_column(days: int) -> str:
    """DB 컬럼 접미사. **음수는 `m`으로 쓴다** — `ret_d-5`는 컬럼명이 될 수 없다."""
    return f"m{abs(days)}" if days < 0 else str(days)


def horizon_label(days: int) -> str:
    """화면 라벨."""
    if days < 0:
        return f"발표 전 {abs(days)}일"
    if days == 0:
        return "발표 당일"
    return f"발표 후 {days}일"

#: 수익률을 못 낸 이유. 화면에 그대로 노출해 "0%"와 구분한다.
REASON_NO_BASE = "기준일 종가 없음"
REASON_NOT_ENOUGH_DAYS = "거래일 부족(아직 이르다)"
REASON_HALTED = "거래정지 또는 상장폐지"
REASON_NO_INDEX = "지수 종가 없음"


@dataclass
class Horizon:
    """한 시점(D+N)의 결과."""

    days: int
    ret_pct: float | None = None
    index_ret_pct: float | None = None
    excess_pp: float | None = None
    reason: str | None = None

    @property
    def measured(self) -> bool:
        return self.excess_pp is not None


@dataclass
class Outcome:
    code: str
    fiscal_year: int
    fiscal_quarter: int
    announce_date: str | None = None
    #: 발표 시점의 판단. **사후 재계산 금지** — 그때 우리가 뭘 알았는지가 요점이다.
    grade_at_announce: str | None = None
    score_at_announce: float | None = None
    pri_at_announce: float | None = None
    horizons: dict[int, Horizon] = field(default_factory=dict)

    def as_db_row(self) -> dict:
        row = {
            "code": self.code,
            "fiscal_year": self.fiscal_year,
            "fiscal_quarter": self.fiscal_quarter,
            "announce_date": self.announce_date,
            "grade_at_announce": self.grade_at_announce,
            "score_at_announce": self.score_at_announce,
            "pri_at_announce": self.pri_at_announce,
        }
        for days in HORIZONS:
            h = self.horizons.get(days)
            suffix = horizon_column(days)
            row[f"ret_d{suffix}"] = h.ret_pct if h else None
            row[f"excess_d{suffix}"] = h.excess_pp if h else None
        return row


def trading_days_after(
    closes: dict[str, float], base_date: str, days: int
) -> str | None:
    """기준일로부터 `days` **거래일** 떨어진 날짜. 음수면 **발표 전**이다.

    ★ 캘린더 일수로 세면 안 된다. 휴장일이 섞여 20일이 14거래일이 되기도 하고,
      종목마다 다른 날을 비교하게 된다 — 숫자는 그럴듯하게 나온다.
    ★ 발표일이 휴장일일 수 있다(장 마감 후·주말 공시). 그러면 **그 다음 거래일**을
      기준으로 잡는다 — 그날이 시장이 처음 반응할 수 있는 날이기 때문이다.
    ★ 음수(발표 전)는 **기준일보다 앞선 거래일**에서 센다. 거래일이 모자라면
      None이다 — 있는 만큼으로 당겨 쓰면 '발표 전 5일'이 실제로는 2일이 된다.
    """
    ordered = sorted(closes)
    if days < 0:
        before = [d for d in ordered if d < base_date]
        # before[-1]이 기준일 직전 거래일. 거기서 |days|-1만큼 더 거슬러 간다.
        return before[days] if len(before) >= abs(days) else None
    after = [d for d in ordered if d >= base_date]
    if not after:
        return None
    # after[0]이 기준일(또는 그 다음 거래일). 거기서 days만큼 더 간다.
    return after[days] if len(after) > days else None


def base_trading_day(closes: dict[str, float], announce_date: str) -> str | None:
    ordered = [d for d in sorted(closes) if d >= announce_date]
    return ordered[0] if ordered else None


def pct_change(start: float | None, end: float | None) -> float | None:
    """수익률(%). 시작가가 0 이하이면 계산하지 않는다."""
    if start is None or end is None or start <= 0:
        return None
    return (end - start) / start * 100.0


def measure(
    closes: dict[str, float],
    index_closes: dict[str, float],
    announce_date: str,
    *,
    horizons: tuple[int, ...] = HORIZONS,
) -> dict[int, Horizon]:
    """발표일 기준 각 시점의 수익률과 초과수익.

    `closes` / `index_closes`는 {'YYYYMMDD': 종가}.
    ★ 종목과 지수를 **같은 날짜로** 맞춘다. 안 맞추면 며칠씩 어긋난 구간을 비교한다.
    """
    out: dict[int, Horizon] = {}
    base = base_trading_day(closes, announce_date)
    index_base = base_trading_day(index_closes, announce_date)

    for days in horizons:
        h = Horizon(days=days)
        if base is None:
            h.reason = REASON_HALTED if not closes else REASON_NO_BASE
            out[days] = h
            continue
        if index_base is None:
            h.reason = REASON_NO_INDEX
            out[days] = h
            continue

        # ★ 구간의 **방향**이 시점마다 다르다.
        #   days > 0 : 발표일 종가 → D+N 종가            (발표 후 반응)
        #   days == 0: 직전 거래일 종가 → 발표일 종가      (발표 당일 등락)
        #   days < 0 : D−N 종가 → 발표일 종가            (발표 전 선반영)
        #   이걸 뒤집으면 부호가 통째로 반대가 되는데 숫자는 그럴듯하게 나온다.
        if days > 0:
            start, index_start = base, index_base
            end = trading_days_after(closes, announce_date, days)
            index_end = trading_days_after(index_closes, announce_date, days)
        else:
            offset = days if days < 0 else -1
            start = trading_days_after(closes, announce_date, offset)
            index_start = trading_days_after(index_closes, announce_date, offset)
            end, index_end = base, index_base

        if start is None or end is None or index_start is None or index_end is None:
            h.reason = REASON_NOT_ENOUGH_DAYS
            out[days] = h
            continue

        h.ret_pct = pct_change(closes.get(start), closes.get(end))
        h.index_ret_pct = pct_change(
            index_closes.get(index_start), index_closes.get(index_end)
        )
        if h.ret_pct is None or h.index_ret_pct is None:
            h.reason = REASON_NO_BASE
        else:
            h.excess_pp = h.ret_pct - h.index_ret_pct
        out[days] = h
    return out


# ═══════════════════════════════════════════════════════════════════
# 정보계수(IC) — 어느 축이 실제로 작동하는가
# ═══════════════════════════════════════════════════════════════════
def _rank(values: list[float]) -> list[float]:
    """평균 순위(동점은 평균). 스피어만 상관에 쓴다."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list[float | None], ys: list[float | None]) -> float | None:
    """스피어만 순위상관.

    ★ **둘 다 있는 쌍만** 쓴다. 한쪽이 None인 걸 0으로 채우면 상관이 조작된다.
    ★ 표본이 3쌍 미만이면 계산하지 않는다 — 숫자가 나와도 의미가 없다.
    """
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    a = _rank([p[0] for p in pairs])
    b = _rank([p[1] for p in pairs])
    n = len(pairs)
    mean_a, mean_b = sum(a) / n, sum(b) / n
    num = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    den_a = sum((x - mean_a) ** 2 for x in a) ** 0.5
    den_b = sum((y - mean_b) ** 2 for y in b) ** 0.5
    if den_a == 0 or den_b == 0:
        return None  # 한쪽이 전부 같은 값 — 순위가 없다
    return num / (den_a * den_b)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def group_stats(
    rows: list[dict], key: str, excess_field: str
) -> dict[object, dict]:
    """그룹별 초과수익 요약. `key`가 None인 행도 하나의 그룹으로 남긴다.

    ★ 측정 못 한 행(excess=None)은 **제외하고 세되, 몇 개를 제외했는지 남긴다.**
      조용히 빼면 "표본 26개"가 실제로는 3개인 상태를 못 알아본다.
    """
    out: dict[object, dict] = {}
    for row in rows:
        bucket = out.setdefault(
            row.get(key), {"total": 0, "measured": [], "unmeasured": 0}
        )
        bucket["total"] += 1
        value = row.get(excess_field)
        if value is None:
            bucket["unmeasured"] += 1
        else:
            bucket["measured"].append(float(value))
    for bucket in out.values():
        bucket["n"] = len(bucket["measured"])
        bucket["median"] = median(bucket["measured"])
    return out
