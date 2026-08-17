# PRD Ref: §5.4, §4.3 · traps.md T15, T31
"""시세 수집 — KIS 1차 / 네이버 폴백.

★ 응답 필드명은 **실호출로 확정했다**(2026-08-13, 삼성전자). 추정이 아니다:

| 용도 | 필드 | 실측값(삼성전자) | 단위 |
|---|---|---|---|
| 현재가 | `stck_prpr` | 268000 | 원 |
| 전일대비율 | `prdy_ctrt` | 4.89 | % |
| 52주 최고/최저 | `w52_hgpr` / `w52_lwpr` | 374500 / 67500 | 원 |
| PER / PBR / EPS | `per` / `pbr` / `eps` | 40.83 / 4.19 / 6564 | 배·원 |
| 시가총액 | `hts_avls` | 15668027 | **억원** |
| 누적거래대금 | `acml_tr_pbmn` | 9517753428321 | 원 |
| 상장주식수 | `lstn_stcn` | 5846278608 | 주 |
| 관리종목 | `mang_issu_cls_code` | N | Y/N |

★ 시세 실패가 스크리닝 전체를 막으면 안 된다(PRD §5.4).
  실패는 예외가 아니라 **PRI 미측정**으로 처리하고 정규화한다.

★ 지수는 KIS 화이트리스트에 없다. PRD가 허용한 **네이버 폴백**을 쓴다 —
  화이트리스트를 넓히지 않기 위한 의도적 선택이다(주문 API 방어선을 좁게 유지).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from src.collectors.kis_client import KisClient, KisError
from src.config.constants import KIS_TR_DAILY_CHART, KIS_TR_PRICE
from src.utils.http import http_get

PRICE_PATH = "/uapi/domestic-stock/v1/quotations/inquire-price"
CHART_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
NAVER_INDEX_URL = "https://api.finance.naver.com/siseJson.naver"
NAVER_PRICE_URL = "https://m.stock.naver.com/api/stock/{code}/integration"

_EOK = 100_000_000  # 억원 → 원


@dataclass
class Quote:
    code: str
    close: float | None = None
    chg_pct: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    per: float | None = None
    pbr: float | None = None
    eps: float | None = None
    market_cap_krw: int | None = None
    acml_value: float | None = None
    shares_outstanding: int | None = None
    source: str = "kis"

    @property
    def pos_52w(self) -> float | None:
        """52주 위치(0~1). 고저가 같으면 판정 불가."""
        if self.close is None or self.high_52w is None or self.low_52w is None:
            return None
        if self.high_52w <= self.low_52w:
            return None
        return min(max((self.close - self.low_52w) / (self.high_52w - self.low_52w), 0.0), 1.0)


@dataclass
class PriceStats:
    kis_ok: int = 0
    kis_failed: int = 0
    naver_ok: int = 0
    failed: int = 0
    errors: dict[str, int] = field(default_factory=dict)


def _num(text) -> float | None:
    if text in (None, "", "-"):
        return None
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        return None


def _ratio(text) -> float | None:
    """PER·PBR·EPS 같은 **밸류에이션 지표**. `0`은 값이 아니라 결측이다 (T31).

    ★ KIS는 코스닥 종목의 per/pbr/eps/bps를 전부 `'0.00'`으로 돌려준다
      (실측 2026-08-13: 리노공업·HPSP는 0.00, 삼성전자는 40.83).
      0을 PER로 쓰면 3년 밴드 백분위에서 **최하위**가 되어 PRI P3가 0점이 되고,
      "아직 반영 안 됨"으로 잘못 읽혀 ★로 승격될 수 있다.
      PER 0인 기업은 존재하지 않는다 — 결측으로 처리하는 것이 옳다.
    """
    value = _num(text)
    if value is None or value == 0:
        return None
    return value


def fetch_quote_kis(client: KisClient, code: str) -> Quote:
    body = client.get(
        PRICE_PATH,
        tr_id=KIS_TR_PRICE,
        params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
    )
    out = body.get("output") or {}
    if not out:
        raise KisError("output 비어 있음")
    cap = _num(out.get("hts_avls"))
    shares = _num(out.get("lstn_stcn"))
    return Quote(
        code=code,
        close=_num(out.get("stck_prpr")),
        chg_pct=_num(out.get("prdy_ctrt")),
        high_52w=_num(out.get("w52_hgpr")),
        low_52w=_num(out.get("w52_lwpr")),
        per=_ratio(out.get("per")),
        pbr=_ratio(out.get("pbr")),
        eps=_ratio(out.get("eps")),
        market_cap_krw=int(cap * _EOK) if cap is not None else None,
        acml_value=_num(out.get("acml_tr_pbmn")),
        shares_outstanding=int(shares) if shares is not None else None,
        source="kis",
    )


def fetch_quote_naver(code: str) -> Quote:
    """KIS 장애 시 폴백. 필드가 적어도 PRI P2(52주 위치)는 살린다."""
    resp = http_get(NAVER_PRICE_URL.format(code=code), timeout=20.0)
    body = resp.json()
    values = {item.get("code"): item.get("value") for item in (body.get("totalInfos") or [])}
    # 종가는 최상위에 없다 — 체결 추이의 최신 항목에 있다(실측).
    trends = body.get("dealTrendInfos") or []
    close = _num(trends[0].get("closePrice")) if trends else None
    if close is None:
        close = _num(values.get("lastClosePrice"))  # 최후 수단: 전일 종가
    return Quote(
        code=code,
        close=close,
        chg_pct=_num(values.get("fluctuationsRatio")),
        high_52w=_num(values.get("highPriceOf52Weeks")),
        low_52w=_num(values.get("lowPriceOf52Weeks")),
        per=_ratio(values.get("per")),
        pbr=_ratio(values.get("pbr")),
        eps=_ratio(values.get("eps")),
        source="naver",
    )


def fetch_quote(client: KisClient | None, code: str, *, stats: PriceStats) -> Quote | None:
    """KIS → 네이버 순으로 시도. 둘 다 실패하면 None(예외를 올리지 않는다)."""
    if client is not None:
        try:
            quote = fetch_quote_kis(client, code)
            stats.kis_ok += 1
            return quote
        except Exception as exc:
            stats.kis_failed += 1
            key = type(exc).__name__
            stats.errors[key] = stats.errors.get(key, 0) + 1
    try:
        quote = fetch_quote_naver(code)
        stats.naver_ok += 1
        return quote
    except Exception:
        stats.failed += 1
        return None


def fetch_daily_closes(
    client: KisClient, code: str, begin: str, end: str
) -> dict[str, float]:
    """{'YYYYMMDD': 종가}. 수정주가(FID_ORG_ADJ_PRC=0)."""
    body = client.get(
        CHART_PATH,
        tr_id=KIS_TR_DAILY_CHART,
        params={
            "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": begin, "FID_INPUT_DATE_2": end,
            "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0",
        },
    )
    out = {}
    for row in body.get("output2") or []:
        date = row.get("stck_bsop_date")
        close = _num(row.get("stck_clpr"))
        if date and close:
            out[date] = close
    return out


def fetch_index_closes(index_name: str, begin: str, end: str) -> dict[str, float]:
    """지수 일별 종가. 네이버 `siseJson.naver`는 JS 배열이라 따옴표를 고쳐 파싱한다."""
    resp = http_get(
        NAVER_INDEX_URL,
        params={
            "symbol": index_name, "requestType": 1,
            "startTime": begin, "endTime": end, "timeframe": "day",
        },
        headers={"Referer": "https://finance.naver.com/"},
        timeout=30.0,
    )
    text = resp.text.strip().replace("'", '"')
    try:
        rows = json.loads(text)
    except json.JSONDecodeError:
        return {}
    out: dict[str, float] = {}
    for row in rows[1:]:  # 첫 행은 헤더
        if len(row) >= 5 and isinstance(row[0], str):
            close = _num(row[4])
            if close:
                out[row[0]] = close
    return out


def relative_return_pp(
    closes: dict[str, float], index_closes: dict[str, float]
) -> float | None:
    """구간 수익률 − 지수 수익률 (%p). 양끝 날짜를 **공통 거래일**로 맞춘다.

    ★ 날짜를 맞추지 않으면 휴장일 차이로 며칠씩 어긋난 구간을 비교하게 되는데
      숫자는 그럴듯하게 나온다.
    """
    common = sorted(set(closes) & set(index_closes))
    if len(common) < 2:
        return None
    first, last = common[0], common[-1]
    if closes[first] <= 0 or index_closes[first] <= 0:
        return None
    stock = (closes[last] / closes[first] - 1) * 100
    index = (index_closes[last] / index_closes[first] - 1) * 100
    return stock - index


def fetch_daily_values(
    client: KisClient, code: str, begin: str, end: str
) -> dict[str, float]:
    """{'YYYYMMDD': 거래대금(원)}. D4(20일 평균 거래대금)에 쓴다."""
    body = client.get(
        CHART_PATH,
        tr_id=KIS_TR_DAILY_CHART,
        params={
            "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
            "FID_INPUT_DATE_1": begin, "FID_INPUT_DATE_2": end,
            "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0",
        },
    )
    out = {}
    for row in body.get("output2") or []:
        date = row.get("stck_bsop_date")
        value = _num(row.get("acml_tr_pbmn"))
        if date and value is not None:
            out[date] = value
    return out


def avg_value_20d(values: dict[str, float]) -> float | None:
    """최근 20거래일 평균 거래대금.

    ★ 당일 누적거래대금을 그대로 쓰면 안 된다 — 거래가 몰린 날 하루로 D4가 통과된다.
      20거래일이 안 되면 있는 만큼으로 평균하되 5일 미만이면 판정하지 않는다.
    """
    if len(values) < 5:
        return None
    recent = [values[d] for d in sorted(values, reverse=True)[:20]]
    return sum(recent) / len(recent)


def fetch_avg_value_20d(
    client: KisClient, code: str, begin: str, end: str
) -> float | None:
    """일봉 1콜로 20일 평균 거래대금을 구한다(위 두 함수의 조합)."""
    return avg_value_20d(fetch_daily_values(client, code, begin, end))
