# PRD Ref: §5.1(L2), §5.2, §5.3 · traps.md T1, T2, T3
"""DART 정기보고서 분기 재무 배치 수집.

`fnlttMultiAcnt.json`은 corp_code를 쉼표로 **최대 100개**까지 받는다.
1,300종목 ÷ 100 = 13콜 × (연도 × 보고서코드) 조합.

fs_div는 **종목별로 하나를 고정**한다(T2). 분기마다 CFS↔OFS가 바뀌면
성장률이 조작된 것처럼 보이는데 에러는 나지 않는다.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from src.config.constants import (
    DART_BASE_URL,
    DART_MULTI_ACNT_BATCH_SIZE,
    DART_MULTI_ACNT_MAX_CORP_CODES,
    REPRT_CODE,
)
from src.finance.quarterize import ReportFigure, QuarterValue, quarterize
from src.utils.env import require_env
from src.utils.http import http_get

MULTI_ACNT_URL = f"{DART_BASE_URL}/fnlttMultiAcnt.json"
#: 단일회사 **전체** 재무제표. 주요계정(multi)에 매출이 아예 없을 때만 쓴다(T39).
SINGLE_ALL_URL = f"{DART_BASE_URL}/fnlttSinglAcntAll.json"

#: DART 계정명 → 내부 필드명. 계정명은 회사마다 표기가 흔들리므로 후보를 둔다.
ACCOUNT_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("매출액", "수익(매출액)", "영업수익", "매출", "영업수익(매출액)"),
    "op": ("영업이익", "영업이익(손실)"),
    "np": ("당기순이익", "당기순이익(손실)"),
}

REQUEST_INTERVAL_SEC = 0.4  # DART 부하 배려
JSON_RETRIES = 3


@dataclass
class FetchStats:
    calls: int = 0
    records: int = 0
    single_all_calls: int = 0  # 매출 결측 폴백(T39) 호출 수
    single_all_recovered: int = 0  # 폴백으로 실제 매출을 되찾은 (회사·보고서) 수
    status_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    fs_div_fixed: dict[str, str] = field(default_factory=dict)  # corp_code → 'CFS'|'OFS'
    account_misses: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    #: 고정된 fs_div가 그 연도에 없어 건너뛴 회사 (T2 — 기준을 바꾸느니 결측으로 둔다)
    fs_div_unavailable: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    #: 재시도까지 실패한 배치. **비어 있지 않으면 그 배치의 종목은 통째로 빠진 것이다.**
    #: 조용히 넘어가면 "수집됐지만 실적이 없는 종목"과 구분되지 않는다.
    failed_batches: list[tuple[int, int, int]] = field(default_factory=list)


def _to_int(text: str | None) -> int | None:
    """'112,522,064,123' → int. 빈 값·'-'는 None (0이 아니다)."""
    if text is None:
        return None
    cleaned = str(text).strip().replace(",", "")
    if cleaned in ("", "-"):
        return None
    try:
        return int(cleaned)
    except ValueError:
        # 소수점이 섞여 오는 계정이 있다. 추측해서 반올림하지 않고 버린다.
        try:
            return int(float(cleaned))
        except ValueError:
            return None


def fetch_multi_account(
    corp_codes: list[str], year: int, quarter: int, *, stats: FetchStats | None = None
) -> list[dict]:
    """corp_code 최대 100개를 1콜로 조회한다."""
    if len(corp_codes) > DART_MULTI_ACNT_MAX_CORP_CODES:
        raise ValueError(
            f"corp_code는 한 콜에 최대 {DART_MULTI_ACNT_MAX_CORP_CODES}개다: {len(corp_codes)}개"
        )
    params = {
        "crtfc_key": require_env("OPENDART_API_KEY"),
        "corp_code": ",".join(corp_codes),
        "bsns_year": str(year),
        "reprt_code": REPRT_CODE[quarter],
    }

    resp = http_get(MULTI_ACNT_URL, params=params, timeout=90.0)
    if stats is not None:
        stats.calls += 1

    # ★ 응답이 커지면 DART는 302로 error1.html에 보낸다(traps.md T24).
    #   follow_redirects 상태에서는 **HTTP 200 + text/html**이라 상태코드로는 못 잡는다.
    #   여기서 잡지 않으면 그 배치의 종목이 통째로, 에러 없이 사라진다.
    if "json" not in (resp.headers.get("content-type") or ""):
        if len(corp_codes) > 1:
            # 절반으로 쪼개 재수집한다 — 버리지 않고 되찾는 게 핵심이다.
            if stats is not None:
                stats.status_counts["oversize_split"] += 1
            mid = len(corp_codes) // 2
            time.sleep(REQUEST_INTERVAL_SEC)
            left = fetch_multi_account(corp_codes[:mid], year, quarter, stats=stats)
            time.sleep(REQUEST_INTERVAL_SEC)
            right = fetch_multi_account(corp_codes[mid:], year, quarter, stats=stats)
            return left + right
        if stats is not None:
            stats.status_counts["oversize_single"] += 1
            stats.failed_batches.append((year, quarter, len(corp_codes)))
        return []

    body: dict | None = None
    for attempt in range(JSON_RETRIES):
        try:
            body = resp.json()
            break
        except ValueError:
            if attempt < JSON_RETRIES - 1:
                time.sleep(2.0 * (attempt + 1))
                resp = http_get(MULTI_ACNT_URL, params=params, timeout=90.0)
                if stats is not None:
                    stats.calls += 1

    if body is None:
        if stats is not None:
            stats.status_counts["non_json"] += 1
            stats.failed_batches.append((year, quarter, len(corp_codes)))
        return []

    status = body.get("status")
    if stats is not None:
        stats.status_counts[status] += 1
    # '013' = 조회된 데이터 없음. 정상 케이스다(아직 미제출 등) — 예외로 올리지 않는다.
    if status != "000":
        return []
    rows = body.get("list") or []
    if stats is not None:
        stats.records += len(rows)
    return rows


def choose_fs_div(rows: list[dict]) -> str | None:
    """CFS 우선, 없으면 OFS (T2). 종목별로 한 번 정하면 계속 그것만 쓴다."""
    divs = {r.get("fs_div") for r in rows}
    if "CFS" in divs:
        return "CFS"
    if "OFS" in divs:
        return "OFS"
    return None


def fetch_single_all(
    corp_code: str, year: int, quarter: int, fs_div: str, *, stats: FetchStats | None = None
) -> list[dict]:
    """단일회사 **전체** 재무제표. `fnlttMultiAcnt`가 매출을 안 줄 때의 폴백이다(T39).

    ★ 주요계정 API는 회사에 따라 **매출 계정 자체를 반환하지 않는다.**
      자산·부채·영업이익·순이익만 오고 매출 줄이 통째로 없다. 에러가 아니라 그냥 없다.
      실측: 한국경제TV·슈어소프트테크 등 29종목이 이 경우였고, 매출이 None이라
      게이트가 전부 판정 불가로 빠져 **발굴 대상에서 조용히 사라졌다.**
    ★ 전체 재무제표에는 `영업수익`으로 들어 있다(한국경제TV 2025년 759억).
      한 콜에 한 회사·한 보고서뿐이라 비싸므로 **결측 종목에만** 쓴다.
    ★ 이 응답은 `sj_div=CIS`이고, 사업보고서는 `thstrm_add_amount`가 비고
      `thstrm_amount`가 연간 누적이다 — `quarterize._cumulative()`가 이미 그 형태를 처리한다.
    """
    params = {
        "crtfc_key": require_env("OPENDART_API_KEY"),
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": REPRT_CODE[quarter],
        "fs_div": fs_div,
    }
    resp = http_get(SINGLE_ALL_URL, params=params, timeout=90.0)
    if stats is not None:
        stats.calls += 1
        stats.single_all_calls += 1
    if "json" not in (resp.headers.get("content-type") or ""):
        return []
    try:
        body = resp.json()
    except ValueError:
        return []
    if body.get("status") != "000":
        return []
    rows = body.get("list") or []
    # ★ 단일회사 응답에는 `fs_div` 필드가 **없다** — 요청 파라미터로 이미 정해졌기 때문이다.
    #   그대로 `extract_figures`에 넘기면 fs_div 필터가 전 행을 걸러내 빈손이 된다.
    #   에러도 경고도 없이 "폴백했는데 못 찾았다"로 보인다(실측: 2종목 20행 전부 매출 None).
    for row in rows:
        row.setdefault("fs_div", fs_div)
    return rows


def extract_figures(
    rows: list[dict], fs_div: str, *, stats: FetchStats | None = None
) -> dict[str, ReportFigure]:
    """한 회사·한 보고서의 손익 행에서 계정별 값을 뽑는다."""
    figures: dict[str, ReportFigure] = {}
    income_rows = [r for r in rows if r.get("sj_div") == "IS" and r.get("fs_div") == fs_div]
    # 일부 회사는 손익계산서를 'CIS'(포괄손익)로만 낸다.
    if not income_rows:
        income_rows = [
            r for r in rows if r.get("sj_div") == "CIS" and r.get("fs_div") == fs_div
        ]

    for field_name, aliases in ACCOUNT_ALIASES.items():
        match = next((r for r in income_rows if r.get("account_nm") in aliases), None)
        if match is None:
            if stats is not None and income_rows:
                stats.account_misses[field_name] += 1
            continue
        figures[field_name] = ReportFigure(
            amount=_to_int(match.get("thstrm_amount")),
            add_amount=_to_int(match.get("thstrm_add_amount")),
        )
    return figures


@dataclass
class CompanyQuarters:
    """한 회사·한 회계연도의 분기 분해 결과."""

    corp_code: str
    code: str | None
    fiscal_year: int
    fs_div: str | None
    quarters: dict[str, dict[int, QuarterValue]]  # 필드명 → {분기: 값}
    prior_year_reported: dict[str, dict[int, int | None]]  # 재작성 감지용(T3)


def collect_year(
    corp_codes: list[str],
    year: int,
    *,
    stats: FetchStats | None = None,
    fs_div_by_corp: dict[str, str] | None = None,
) -> dict[str, CompanyQuarters]:
    """한 회계연도의 4개 보고서를 훑어 회사별 분기값을 만든다.

    ★ `fs_div_by_corp`를 주면 그 기준을 **강제**한다 (T2).
      연도마다 독립적으로 CFS/OFS를 고르면 같은 종목에 두 기준이 섞여 저장되고,
      YoY가 조작된 것처럼 보이는데 에러는 나지 않는다.
      해당 연도에 그 기준의 재무제표가 없으면 **그 연도를 건너뛴다** —
      기준을 몰래 바꾸느니 결측으로 두는 편이 옳다.
    """
    stats = stats or FetchStats()

    # corp_code → 분기 → 그 회사의 행들
    by_company: dict[str, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for quarter in (1, 2, 3, 4):
        for i in range(0, len(corp_codes), DART_MULTI_ACNT_BATCH_SIZE):
            chunk = corp_codes[i : i + DART_MULTI_ACNT_BATCH_SIZE]
            for row in fetch_multi_account(chunk, year, quarter, stats=stats):
                by_company[row["corp_code"]][quarter].append(row)
            time.sleep(REQUEST_INTERVAL_SEC)

    results: dict[str, CompanyQuarters] = {}
    for corp_code, per_quarter in by_company.items():
        all_rows = [r for rows in per_quarter.values() for r in rows]

        pinned = (fs_div_by_corp or {}).get(corp_code)
        if pinned is not None:
            if not any(r.get("fs_div") == pinned for r in all_rows):
                # 고정된 기준의 재무제표가 이 연도에 없다 — 다른 기준으로 갈아타지 않는다.
                stats.fs_div_unavailable[corp_code] += 1
                continue
            fs_div = pinned
        else:
            fs_div = choose_fs_div(all_rows)
            if fs_div is None:
                continue
        stats.fs_div_fixed[corp_code] = fs_div

        # 필드 → reprt_code → ReportFigure
        per_field: dict[str, dict[str, ReportFigure]] = defaultdict(dict)
        prior: dict[str, dict[int, int | None]] = defaultdict(dict)
        for quarter, rows in per_quarter.items():
            figures = extract_figures(rows, fs_div, stats=stats)

            # ★ 주요계정 API가 **매출 계정을 통째로 안 주는** 회사가 있다(T39).
            #   영업이익·순이익은 멀쩡히 오므로 수집이 성공한 것처럼 보이고,
            #   매출만 None이라 게이트가 조용히 판정 불가로 빠진다.
            #   영업이익이 있는데 매출만 없으면 '이 회사는 매출이 없다'가 아니라
            #   '이 API가 안 준다'는 뜻이다 — 전체 재무제표로 되찾는다.
            if "revenue" not in figures and "op" in figures:
                fallback = fetch_single_all(corp_code, year, quarter, fs_div, stats=stats)
                if fallback:
                    recovered = extract_figures(fallback, fs_div, stats=stats)
                    if "revenue" in recovered:
                        figures["revenue"] = recovered["revenue"]
                        stats.single_all_recovered += 1
                        rows = rows + fallback  # 아래 전년동기 추출도 같은 행을 보게 한다
                time.sleep(REQUEST_INTERVAL_SEC)

            for field_name, figure in figures.items():
                per_field[field_name][REPRT_CODE[quarter]] = figure
            # 공시에 실린 전년동기 누적값을 함께 보관한다 (T3 재작성 감지)
            income = [r for r in rows if r.get("fs_div") == fs_div]
            for field_name, aliases in ACCOUNT_ALIASES.items():
                match = next((r for r in income if r.get("account_nm") in aliases), None)
                if match is not None:
                    prior[field_name][quarter] = _to_int(
                        match.get("frmtrm_add_amount") or match.get("frmtrm_amount")
                    )

        results[corp_code] = CompanyQuarters(
            corp_code=corp_code,
            code=(all_rows[0].get("stock_code") or "").strip() or None,
            fiscal_year=year,
            fs_div=fs_div,
            quarters={f: quarterize(figs) for f, figs in per_field.items()},
            prior_year_reported=dict(prior),
        )
    return results


def detect_restatement(
    reported_prior: int | None, stored_prior: int | None, *, tolerance: float = 0.001
) -> bool:
    """전년동기가 재작성됐는지 (T3).

    분할·합병·중단영업·회계기준 변경 시 전년동기가 재작성된다.
    **공시에 실린 값을 우선**하고, DB 저장값과 다르면 restated=True.
    한쪽이라도 없으면 판정하지 않는다(False가 아니라 판정 안 함 → False 반환하되
    호출부에서 결측을 먼저 거른다).
    """
    if reported_prior is None or stored_prior is None:
        return False
    if stored_prior == 0:
        return reported_prior != 0
    return abs(reported_prior - stored_prior) / abs(stored_prior) > tolerance
