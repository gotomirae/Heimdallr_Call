# PRD Ref: §5.4, §4.3 · traps.md T15, T31
"""P6 KIS 클라이언트·시세 테스트. 외부 I/O 없이 돈다."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from src.collectors.kis_client import KisClient, KisPathNotAllowed, TokenBucket
from src.collectors.kis_prices import (
    Quote,
    _ratio,
    relative_return_pp,
    trailing_return_pct,
    window_relative_return_pp,
    window_return_pct,
)
from src.collectors.quarter_prices import quarter_end_closes, quarter_of
from src.collectors.price_run import build_return_fields
from src.db.supabase_client import (
    missing_column_of,
    upsert_tolerating_missing_columns,
)
from src.config.constants import KIS_ALLOWED_PATHS


# ═══════════════════════════════════════════════════════════════════
# ★ 주문 API 차단 — 이 프로젝트의 안전 장치
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "path",
    [
        "/uapi/domestic-stock/v1/trading/order-cash",
        "/uapi/domestic-stock/v1/trading/order-credit",
        "/uapi/domestic-stock/v1/trading/inquire-balance",
        "/uapi/domestic-stock/v1/trading/order-rvsecncl",
    ],
)
def test_order_paths_are_blocked(path):
    """호출부가 실수해도 주문 API에 닿지 않아야 한다."""
    with pytest.raises(KisPathNotAllowed):
        KisClient._ensure_allowed(path)


def test_allowed_paths_are_quotations_only():
    for path in KIS_ALLOWED_PATHS:
        assert path.startswith("/oauth2/") or "/quotations/" in path
        assert "order" not in path.lower()
        assert "trading" not in path.lower()


def test_whitelisted_paths_pass():
    for path in KIS_ALLOWED_PATHS:
        KisClient._ensure_allowed(path)  # 예외가 없어야 한다


# ═══════════════════════════════════════════════════════════════════
# 토큰 캐시 (T15) — 매 실행 재발급하면 발급 자체가 막힌다
# ═══════════════════════════════════════════════════════════════════
def test_token_is_reused_from_cache(tmp_path, monkeypatch):
    cache = tmp_path / "kis_token.json"
    expires = datetime.now(timezone.utc) + timedelta(hours=12)
    cache.write_text(
        json.dumps({"access_token": "CACHED", "expires_at": expires.isoformat()}),
        encoding="utf-8",
    )
    client = KisClient()
    client.cache_path = cache
    assert client.token() == "CACHED"
    assert client.token_issue_count == 0  # ★ 발급하지 않았다


def test_expired_cache_is_not_reused(tmp_path):
    cache = tmp_path / "kis_token.json"
    expired = datetime.now(timezone.utc) - timedelta(hours=1)
    cache.write_text(
        json.dumps({"access_token": "OLD", "expires_at": expired.isoformat()}),
        encoding="utf-8",
    )
    client = KisClient()
    client.cache_path = cache
    assert client._load_cached_token()[0] == "OLD"
    # 만료됐으므로 token()은 재발급을 시도한다(네트워크 없이 확인하기 위해 캐시만 검사)
    assert client._load_cached_token()[1] < datetime.now(timezone.utc)


def test_corrupt_cache_is_ignored(tmp_path):
    cache = tmp_path / "kis_token.json"
    cache.write_text("not json", encoding="utf-8")
    client = KisClient()
    client.cache_path = cache
    assert client._load_cached_token() is None


# ═══════════════════════════════════════════════════════════════════
# 스로틀 (T15) — 초당 20건 초과 시 EGW00201
# ═══════════════════════════════════════════════════════════════════
def test_token_bucket_limits_rate():
    bucket = TokenBucket(10)
    started = time.monotonic()
    for _ in range(20):  # 버킷 10개 소진 후 10개는 대기해야 한다
        bucket.acquire()
    elapsed = time.monotonic() - started
    assert elapsed >= 0.8, f"스로틀이 걸리지 않았다: {elapsed:.2f}초"


def test_token_bucket_allows_initial_burst():
    bucket = TokenBucket(18)
    started = time.monotonic()
    for _ in range(18):
        bucket.acquire()
    assert time.monotonic() - started < 0.3


# ═══════════════════════════════════════════════════════════════════
# T31 — 밸류에이션 0은 값이 아니라 결측
# ═══════════════════════════════════════════════════════════════════
def test_zero_per_is_missing_not_zero():
    """★ KIS는 코스닥 종목의 per/pbr/eps를 '0.00'으로 돌려준다(실측).

    0을 PER로 쓰면 3년 밴드 백분위 최하위 → PRI P3 0점 → '미반영'으로
    잘못 읽혀 ★로 승격된다. PER 0인 기업은 없다.
    """
    assert _ratio("0.00") is None
    assert _ratio(0) is None
    assert _ratio("40.83") == pytest.approx(40.83)
    assert _ratio(None) is None
    assert _ratio("-") is None


def test_negative_per_is_kept():
    """적자 기업의 음수 PER은 의미가 있다 — 0과 다르다."""
    assert _ratio("-12.5") == pytest.approx(-12.5)


# ═══════════════════════════════════════════════════════════════════
# 52주 위치
# ═══════════════════════════════════════════════════════════════════
def test_pos_52w():
    q = Quote(code="A", close=7000, high_52w=10000, low_52w=5000)
    assert q.pos_52w == pytest.approx(0.4)


def test_pos_52w_none_when_no_range():
    assert Quote(code="A", close=100, high_52w=100, low_52w=100).pos_52w is None


def test_pos_52w_clamped():
    """장중 갱신 지연으로 종가가 52주 범위를 벗어날 수 있다."""
    assert Quote(code="A", close=12000, high_52w=10000, low_52w=5000).pos_52w == 1.0


# ═══════════════════════════════════════════════════════════════════
# 상대수익률 — 공통 거래일로 맞춘다
# ═══════════════════════════════════════════════════════════════════
def test_relative_return_uses_common_dates():
    closes = {"20260501": 100.0, "20260601": 110.0, "20260701": 120.0}
    index = {"20260501": 1000.0, "20260701": 1050.0}  # 6월이 없다
    # 공통일: 05-01, 07-01 → 종목 +20%, 지수 +5% → +15%p
    assert relative_return_pp(closes, index) == pytest.approx(15.0)


def test_relative_return_none_without_overlap():
    assert relative_return_pp({"20260501": 100.0}, {"20260601": 1000.0}) is None


def test_relative_return_none_with_single_day():
    assert relative_return_pp({"20260501": 100.0}, {"20260501": 1000.0}) is None


def test_window_returns_use_the_same_cutoff_and_common_market_days():
    """6M/12M도 종목과 지수의 양끝 거래일을 맞춘다.

    2026-01-01 이후 공통일은 01-02와 08-03.
    종목 100→130 = +30%, 지수 1000→1100 = +10%, 초과 = +20%p.
    """
    closes = {
        "20251230": 50.0,
        "20260102": 100.0,
        "20260803": 130.0,
    }
    index = {
        "20260101": 900.0,
        "20260102": 1000.0,
        "20260803": 1100.0,
    }
    assert window_return_pct(closes, "20260101") == pytest.approx(30.0)
    assert window_relative_return_pp(closes, index, "20260101") == pytest.approx(20.0)


def test_window_returns_do_not_shorten_an_unmeasurable_period():
    """cutoff 뒤 거래일이 하나뿐이면 짧은 구간을 6M처럼 표시하지 않는다."""
    closes = {"20251230": 100.0, "20260803": 110.0}
    index = {"20251230": 1000.0, "20260803": 1050.0}
    assert window_return_pct(closes, "20260101") is None
    assert window_relative_return_pp(closes, index, "20260101") is None


def test_window_returns_reject_a_new_listing_with_many_short_history_rows():
    """거래일이 많아도 첫 행이 cutoff보다 수개월 늦으면 12M가 아니다."""
    closes = {
        "20260401": 100.0,
        "20260501": 105.0,
        "20260601": 110.0,
        "20260801": 120.0,
    }
    index = {
        "20260102": 1000.0,
        "20260401": 1050.0,
        "20260501": 1070.0,
        "20260601": 1090.0,
        "20260801": 1120.0,
    }
    assert window_return_pct(closes, "20260101") is None
    assert window_relative_return_pp(closes, index, "20260101") is None


def test_price_snapshot_builds_absolute_and_index_relative_windows():
    closes = {
        "20250801": 100.0,
        "20260201": 110.0,
        "20260501": 120.0,
        "20260701": 125.0,
        "20260801": 130.0,
    }
    index = {
        "20250801": 1000.0,
        "20260201": 1050.0,
        "20260501": 1100.0,
        "20260701": 1150.0,
        "20260801": 1200.0,
    }
    fields = build_return_fields(
        closes,
        index,
        {"1m": "20260701", "3m": "20260501", "6m": "20260201", "12m": "20250801"},
    )
    assert fields["ret_1m"] == pytest.approx(4.0)
    assert fields["ret_3m"] == pytest.approx(130 / 120 * 100 - 100)
    assert fields["ret_6m"] == pytest.approx(130 / 110 * 100 - 100)
    assert fields["ret_12m"] == pytest.approx(30.0)
    assert fields["rel_ret_3m"] == pytest.approx(
        (130 / 120 - 1) * 100 - (1200 / 1100 - 1) * 100
    )
    assert fields["rel_ret_6m"] == pytest.approx(
        (130 / 110 - 1) * 100 - (1200 / 1050 - 1) * 100
    )
    assert fields["rel_ret_12m"] == pytest.approx(10.0)


# ═══════════════════════════════════════════════════════════════════
# 최근 5거래일 상승률 — 발굴 목록의 마지막 열
# ═══════════════════════════════════════════════════════════════════
def test_trailing_return_counts_sessions_not_calendar_days():
    """5**거래일** 전과 비교한다. 손계산: 100 → 110 = +10.0%"""
    closes = {
        "20260803": 100.0, "20260804": 101.0, "20260805": 102.0,
        "20260806": 103.0, "20260807": 104.0, "20260810": 110.0,
    }
    assert trailing_return_pct(closes, 5) == pytest.approx(10.0)


def test_trailing_return_ignores_calendar_gaps():
    """연휴로 캘린더 간격이 벌어져도 거래일 수만 센다.

    ★ 캘린더 기준이면 이 구간은 '5일'이 아니지만 숫자는 그럴듯하게 나온다 —
      틀린 걸 알아채지 못하는 종류의 오류다.
    """
    closes = {
        "20260925": 100.0, "20260926": 101.0,   # 추석 연휴로 5일 공백
        "20261005": 102.0, "20261006": 103.0,
        "20261007": 104.0, "20261008": 110.0,
    }
    assert trailing_return_pct(closes, 5) == pytest.approx(10.0)


def test_trailing_return_none_when_not_enough_sessions():
    """★ 거래일이 모자라면 None이다. 있는 만큼으로 계산하지 않는다 —
    상장 직후 종목이 3거래일치를 '5일 상승률'로 표시하게 된다."""
    closes = {f"2026080{i}": 100.0 + i for i in range(1, 6)}  # 5봉 = 4구간
    assert trailing_return_pct(closes, 5) is None


def test_trailing_return_none_when_base_is_zero():
    closes = {"20260803": 0.0, "20260804": 1.0, "20260805": 1.0,
              "20260806": 1.0, "20260807": 1.0, "20260810": 1.0}
    assert trailing_return_pct(closes, 5) is None


def test_trailing_return_uses_latest_window_only():
    """봉이 많아도 **최근** 5거래일만 본다."""
    closes = {f"202608{d:02d}": v for d, v in
              [(3, 1.0), (4, 2.0), (5, 3.0), (6, 100.0), (7, 101.0),
               (10, 102.0), (11, 103.0), (12, 104.0), (13, 110.0)]}
    # 5거래일 전 = 08-06(100.0) · 최신 = 08-13(110.0) → +10%
    assert trailing_return_pct(closes, 5) == pytest.approx(10.0)


# ═══════════════════════════════════════════════════════════════════
# 분기말 종가 — 9분기 차트의 주가 라인
# ═══════════════════════════════════════════════════════════════════
def test_quarter_of_maps_calendar_quarters():
    assert quarter_of("20260101") == (2026, 1)
    assert quarter_of("20260331") == (2026, 1)
    assert quarter_of("20260401") == (2026, 2)
    assert quarter_of("20261231") == (2026, 4)


def test_quarter_end_close_picks_last_trading_day():
    """분기의 **마지막 거래일**을 고른다. 손계산 대조."""
    closes = {"20260330": 100.0, "20260331": 110.0, "20260401": 120.0}
    out = quarter_end_closes(closes)
    assert out[(2026, 1)] == ("20260331", 110.0)
    assert out[(2026, 2)] == ("20260401", 120.0)


def test_quarter_end_close_when_last_day_is_holiday():
    """★ 분기 말일이 휴장이면 그 앞 거래일이어야 한다.

    말일 날짜로 직접 찍으면 그 분기 값이 통째로 빈다 — 실측으로
    2024.4Q는 12/31이 휴장이라 12/30이 마지막 거래일이었다.
    """
    closes = {"20241227": 90.0, "20241230": 95.0, "20250102": 99.0}
    out = quarter_end_closes(closes)
    assert out[(2024, 4)] == ("20241230", 95.0)
    assert (2025, 1) in out


# ═══════════════════════════════════════════════════════════════════
# ★ 마이그레이션 미적용 구간 방어 (T18)
#
# DDL은 REST로 실행할 수 없어 사람이 SQL Editor에 적용하기 전까지 공백이 생긴다.
# 그 사이 **새 컬럼 하나 때문에 수집기가 통째로 죽으면** 같은 잡에서 이어 도는
# 스크리닝까지 함께 멈춘다 — 실측으로 겪었다(ret_5d · 2026-08-17).
# ═══════════════════════════════════════════════════════════════════
class _FakeAPIError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class _FakeTable:
    """지정한 컬럼이 payload에 있으면 PGRST204를 던지는 가짜 테이블."""

    def __init__(self, forbidden: set[str], sink: list[dict]):
        self.forbidden = forbidden
        self.sink = sink
        self._rows: list[dict] = []

    def upsert(self, rows, on_conflict=None):
        self._rows = rows
        return self

    def execute(self):
        for row in self._rows:
            for key in row:
                if key in self.forbidden:
                    raise _FakeAPIError(
                        "PGRST204",
                        f"Could not find the '{key}' column of 'x' in the schema cache",
                    )
        self.sink.extend(self._rows)
        return self


class _FakeClient:
    def __init__(self, forbidden: set[str]):
        self.forbidden = forbidden
        self.saved: list[dict] = []

    def table(self, _name):
        return _FakeTable(self.forbidden, self.saved)


def test_upsert_drops_missing_column_and_keeps_going():
    """없는 컬럼은 걷어내고 **나머지는 저장한다.** 통째로 죽지 않는다."""
    client = _FakeClient({"ret_5d"})
    rows = [{"code": "005930", "close": 100.0, "ret_5d": 1.5}]
    saved, dropped = upsert_tolerating_missing_columns(
        client, "price_snapshots", rows, on_conflict="code"
    )
    assert saved == 1
    assert dropped == ["ret_5d"]
    assert client.saved == [{"code": "005930", "close": 100.0}]


def test_upsert_drops_multiple_missing_columns():
    """★ PostgREST는 **한 번에 하나씩만** 알려준다 — 한 번 폴백하고 마는
    패턴은 컬럼이 둘 이상 빠지면 여전히 죽는다. 반드시 루프여야 한다."""
    client = _FakeClient({"ret_5d", "fwd_per"})
    rows = [{"code": "A", "close": 1.0, "ret_5d": 1.0, "fwd_per": 2.0}]
    saved, dropped = upsert_tolerating_missing_columns(
        client, "price_snapshots", rows, on_conflict="code"
    )
    assert saved == 1
    assert sorted(dropped) == ["fwd_per", "ret_5d"]
    assert client.saved == [{"code": "A", "close": 1.0}]


def test_upsert_reraises_unrelated_errors():
    """★ 아무 에러나 삼키면 진짜 고장을 '컬럼 없음'으로 착각하게 된다."""
    class _Boom:
        def table(self, _n):
            raise _FakeAPIError("PGRST301", "인증 실패")

    with pytest.raises(_FakeAPIError):
        upsert_tolerating_missing_columns(
            _Boom(), "price_snapshots", [{"code": "A"}], on_conflict="code"
        )


def test_missing_column_of_ignores_other_codes():
    assert missing_column_of(_FakeAPIError("PGRST204", "Could not find the 'x' column")) == "x"
    assert missing_column_of(_FakeAPIError("42703", "Could not find the 'x' column")) is None
