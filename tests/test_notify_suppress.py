# PRD Ref: §8.3 · traps.md T79, T80
"""발송 억제 — 이미 발표가 끝난 backlog를 **보내지 않고 이력에만** 남긴다.

★ 이 기능의 위험은 "안 보내는 것"이 아니라 **안 보냈다는 사실을 잃는 것**이다.
  중복 차단 표에 실제 발송과 똑같이 남기면 화면이 발송 건수를 부풀려 말한다.
  그래서 표식(`payload.suppressed`)과 그것을 읽는 화면을 **함께** 검사한다.

외부 I/O는 전부 스텁으로 막는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.notify import batch
from src.notify.templates import KIND_FLASH

TARGETS = [
    {"code": "417840", "fiscal_year": 2026, "fiscal_quarter": 2,
     "grade": "★", "score_flash": 100.0},
    {"code": "166090", "fiscal_year": 2026, "fiscal_quarter": 1,
     "grade": "○", "score_flash": 92.5},
    {"code": "004000", "fiscal_year": 2026, "fiscal_quarter": 2,
     "grade": "★", "score_flash": 97.6},
]


@pytest.fixture
def wired(monkeypatch):
    """`run_suppress`의 외부 의존을 전부 스텁으로 갈아끼운다.

    반환: 기록된 행 목록 (테스트가 내용을 직접 본다)
    """
    recorded: list[dict] = []

    monkeypatch.setattr(batch, "notify_targets", lambda: list(TARGETS))
    monkeypatch.setattr(
        batch, "select_all",
        lambda table, cols: [{"code": t["code"], "name": f"종목{t['code']}"} for t in TARGETS],
    )
    monkeypatch.setattr(batch, "already_sent", lambda *a, **k: False)
    monkeypatch.setattr(
        batch, "record_notification",
        lambda code, y, q, kind, payload: recorded.append(
            {"code": code, "year": y, "quarter": q, "kind": kind, "payload": payload}
        ),
    )
    # ★ 억제가 텔레그램을 건드리면 즉시 실패한다 — 이게 이 기능의 핵심 계약이다.
    def _boom(*a, **k):
        raise AssertionError("억제가 텔레그램을 호출했다")

    monkeypatch.setattr(batch, "TelegramClient", _boom)
    monkeypatch.setattr(batch, "send_once", _boom)
    return recorded


def test_dry_run_records_nothing(wired):
    """`--save` 없이는 **아무것도 쓰지 않는다.** 실수로 도는 일이 있어선 안 된다."""
    batch.run_suppress(save=False, reason="테스트")
    assert wired == []


def test_suppress_marks_every_target(wired):
    """상한을 적용하지 않는다 — 일부만 억제하면 **나머지가 다음 실행에 그대로 나간다.**"""
    batch.run_suppress(save=True, reason="이미 발표가 끝난 분기")
    assert len(wired) == len(TARGETS)
    assert {r["code"] for r in wired} == {t["code"] for t in TARGETS}


def test_suppressed_rows_are_distinguishable_from_real_sends(wired):
    """★★ 표식이 없으면 화면이 "발송 N건"으로 조용히 거짓말한다."""
    batch.run_suppress(save=True, reason="이미 발표가 끝난 분기")
    for row in wired:
        assert row["payload"]["suppressed"] is True, "억제 표식이 없다"
        assert row["payload"]["reason"], "사유가 비어 있으면 나중에 이유를 알 수 없다"


def test_suppression_uses_the_same_kind_as_a_real_flash(wired):
    """★ 종류가 다르면 `already_sent`가 못 잡아 **억제가 아무것도 막지 못한다.**

    "안 보내려고 넣었는데 그대로 나간다"가 이 기능의 최악 실패다.
    """
    batch.run_suppress(save=True, reason="x")
    assert {r["kind"] for r in wired} == {KIND_FLASH}


def test_existing_history_is_never_overwritten(monkeypatch, wired):
    """이미 **진짜 보낸** 건을 억제 표식으로 덮으면 발송 사실이 사라진다."""
    monkeypatch.setattr(batch, "already_sent", lambda code, *a, **k: code == "417840")
    batch.run_suppress(save=True, reason="x")
    assert "417840" not in {r["code"] for r in wired}
    assert len(wired) == len(TARGETS) - 1


# ═══════════════════════════════════════════════════════════════════
# 화면이 표식을 실제로 읽는가 — 파이썬만 맞으면 절반만 고친 것이다
# ═══════════════════════════════════════════════════════════════════
SETTINGS = (
    Path(__file__).resolve().parents[1] / "dashboard" / "app" / "settings" / "page.tsx"
)


def test_settings_page_splits_suppressed_from_sent():
    """★ 화면이 억제분을 발송으로 세면 **보내지도 않은 건수**가 발송 이력에 잡힌다."""
    body = SETTINGS.read_text(encoding="utf-8")
    assert "payload" in body, "설정 화면이 payload를 아예 안 읽는다 — 표식을 볼 수 없다"
    assert "suppressed" in body, "설정 화면이 억제 표식을 읽지 않는다"
    # 분류 없이 통째로 세는 옛 형태로 되돌아가지 않았는지 본다
    assert re.search(r"suppressed\s*\?", body), (
        "억제 여부로 가르는 분기가 없다 — 합쳐 세면 발송 건수가 부풀려진다"
    )
