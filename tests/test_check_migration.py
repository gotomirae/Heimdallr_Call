# PRD Ref: §6 · traps.md T18
from src.db.check_migration import MISSING_COLUMN, MISSING_TABLE, probe


class _Query:
    def __init__(self, exc=None):
        self.exc = exc

    def select(self, _column):
        return self

    def limit(self, _count):
        return self

    def execute(self):
        if self.exc:
            raise self.exc
        return object()


class _Client:
    def __init__(self, exc=None):
        self.exc = exc

    def table(self, _name):
        return _Query(self.exc)


class _ApiError(Exception):
    def __init__(self, code):
        self.code = code


def test_probe_distinguishes_absence_from_connection_failure():
    assert probe(_Client(), "t", "c") == (True, "")
    assert probe(_Client(_ApiError(MISSING_COLUMN)), "t", "c") == (False, "컬럼 없음")
    assert probe(_Client(_ApiError(MISSING_TABLE)), "t", "c") == (False, "테이블 없음")

    status, reason = probe(_Client(ConnectionError("offline")), "t", "c")
    assert status is None
    assert "판정 불가" in reason
