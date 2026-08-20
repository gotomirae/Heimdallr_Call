# PRD Ref: §5 · traps.md
"""`http_get` 재시도 정책. 외부 I/O 없이 돈다(httpx.get을 갈아끼운다).

왜 필요한가:
  2026-08-19 `universe_daily`가 통째로 실패했다. KIND가 잠깐 응답하지 않은 것뿐인데
  그때 정책은 **3회 · 총 4.5초**여서 남의 서버 딸꾹질과 진짜 장애를 구분하지 못했다.
  재시도 정책은 **에러 없이 잡을 죽이는** 종류의 설정이라 숫자를 테스트로 못 박는다.
"""

from __future__ import annotations

import httpx
import pytest

from src.utils import http as http_mod
from src.utils.http import http_get


class _Recorder:
    """`httpx.get` 대역. 미리 정한 응답을 순서대로 돌려준다."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, url, **kwargs):
        self.calls += 1
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        request = httpx.Request("GET", url)
        return httpx.Response(outcome, request=request, content=b"ok")


@pytest.fixture
def no_sleep(monkeypatch):
    """실제로 기다리지 않는다. 대신 **얼마나 기다리려 했는지** 기록한다."""
    slept: list[float] = []
    monkeypatch.setattr(http_mod.time, "sleep", slept.append)
    return slept


def _install(monkeypatch, outcomes) -> _Recorder:
    recorder = _Recorder(outcomes)
    monkeypatch.setattr(http_mod.httpx, "get", recorder)
    return recorder


def test_transient_failure_then_success(monkeypatch, no_sleep):
    """★ 딸꾹질 한 번에 잡이 죽으면 안 된다 — universe_daily가 이걸로 죽었다."""
    rec = _install(monkeypatch, [httpx.ConnectError("boom"), 200])
    resp = http_get("https://example.test/x")
    assert resp.status_code == 200
    assert rec.calls == 2


def test_retries_five_times_before_giving_up(monkeypatch, no_sleep):
    rec = _install(monkeypatch, [httpx.ConnectTimeout("slow")])
    with pytest.raises(RuntimeError, match="5회 재시도"):
        http_get("https://example.test/x")
    assert rec.calls == 5, "재시도 횟수가 줄면 짧은 장애에 잡이 다시 죽는다"


def test_total_wait_survives_a_short_outage(monkeypatch, no_sleep):
    """★ 예전 정책은 총 4.5초였다. 그 정도로는 KIND의 딸꾹질을 못 넘긴다."""
    _install(monkeypatch, [httpx.ConnectError("boom")])
    with pytest.raises(RuntimeError):
        http_get("https://example.test/x")
    assert sum(no_sleep) >= 20.0, f"총 대기 {sum(no_sleep):.1f}초 — 너무 짧다"
    # 백오프가 점점 길어져야 한다(같은 간격으로 때리면 회복을 방해한다).
    assert no_sleep == sorted(no_sleep)


def test_server_error_is_retried(monkeypatch, no_sleep):
    rec = _install(monkeypatch, [503, 503, 200])
    assert http_get("https://example.test/x").status_code == 200
    assert rec.calls == 3


def test_too_many_requests_is_retried(monkeypatch, no_sleep):
    rec = _install(monkeypatch, [429, 200])
    assert http_get("https://example.test/x").status_code == 200
    assert rec.calls == 2


def test_not_found_fails_immediately(monkeypatch, no_sleep):
    """★ 404에 다섯 번 매달리면 실패를 늦출 뿐이고 상대 서버만 더 때린다."""
    rec = _install(monkeypatch, [404])
    with pytest.raises(RuntimeError, match="HTTP 404"):
        http_get("https://example.test/x")
    assert rec.calls == 1
    assert no_sleep == []


def test_retry_after_header_is_honoured(monkeypatch):
    """상대가 '이만큼 기다려라'라고 하면 그걸 따른다."""
    slept: list[float] = []
    monkeypatch.setattr(http_mod.time, "sleep", slept.append)

    def fake_get(url, **kwargs):
        request = httpx.Request("GET", url)
        fake_get.calls = getattr(fake_get, "calls", 0) + 1
        if fake_get.calls == 1:
            return httpx.Response(429, request=request, headers={"Retry-After": "7"})
        return httpx.Response(200, request=request, content=b"ok")

    monkeypatch.setattr(http_mod.httpx, "get", fake_get)
    assert http_get("https://example.test/x").status_code == 200
    assert slept == [7.0]
