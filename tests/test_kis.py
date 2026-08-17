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
