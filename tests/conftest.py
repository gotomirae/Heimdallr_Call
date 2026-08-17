# PRD Ref: §13 (검증 게이트)
"""pytest 공통 설정.

원칙 (CLAUDE.md)
- collector 테스트는 실제 외부 API를 호출한다(모킹하지 않음).
  네트워크·키가 없는 환경에서는 `needs_network` / `needs_secret` 마커로 스킵한다.
- 순수 함수(screener/, finance/quarterize.py)는 외부 I/O 없이 항상 돌아야 한다.
  손계산 대조를 주석에 남긴다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "needs_network: 실제 외부 API를 호출한다")
    config.addinivalue_line("markers", "needs_secret(name): 해당 환경변수가 있어야 실행된다")


def pytest_runtest_setup(item: pytest.Item) -> None:
    from src.utils.env import optional_env

    for marker in item.iter_markers(name="needs_secret"):
        for name in marker.args:
            if not optional_env(name):
                pytest.skip(f"{name} 미설정으로 스킵")


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT
