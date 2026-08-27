# PRD Ref: §12 T9 · traps.md T9
"""환경변수 접근 단일 창구.

★ 프로젝트 어디에서도 os.environ을 직접 읽지 않는다.

참고 프로젝트에서 시크릿 값에 개행이 섞여
    httpcore.LocalProtocolError: Illegal header value b'***\\n'
가 발생하고, anthropic SDK가 이를 APIConnectionError("Connection error.")로
감싸는 바람에 **모든 LLM 호출이 6일간 조용히 실패**한 사고가 있었다.
여기서 반드시 .strip()하고, 값 내부에 개행이 섞여 있으면 즉시 실패시킨다
(조용히 자르면 잘못된 키로 호출이 계속 나간다).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 이 파일: <root>/src/utils/env.py → parents[2] == <root>
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 로컬 개발용 후보 파일. 앞의 것이 우선하며 하나만 로드한다.
# (.env.txt는 이 프로젝트 폴더에 실제로 존재하는 파일명이다 — .gitignore에 반드시 포함)
_DOTENV_CANDIDATES = (".env", ".env.txt")

_loaded = False


class MissingEnvError(RuntimeError):
    """필수 환경변수가 없거나 비어 있다."""


class DirtyEnvError(RuntimeError):
    """환경변수 값이 오염됐다(내부 개행 등). 조용히 자르지 않고 실패시킨다."""


def _load_dotenv_once() -> None:
    global _loaded
    if _loaded:
        return
    # 이미 프로세스 환경(GitHub Actions Secrets 등)에 있는 값이 항상 우선한다.
    for name in _DOTENV_CANDIDATES:
        path = _PROJECT_ROOT / name
        if path.exists():
            load_dotenv(path, override=False)
            break
    _loaded = True


def dotenv_path() -> Path | None:
    """실제로 로드된 dotenv 파일 경로(없으면 None). 진단·체크리스트용."""
    _load_dotenv_once()
    for name in _DOTENV_CANDIDATES:
        path = _PROJECT_ROOT / name
        if path.exists():
            return path
    return None


def _clean(name: str, raw: str) -> str:
    value = raw.strip()
    # 양끝 공백/개행은 제거하지만, 값 "내부"의 개행은 오염이다. 추측해서 고치지 않는다.
    if "\n" in value or "\r" in value:
        raise DirtyEnvError(
            f"{name} 값 내부에 개행이 섞여 있다. .env를 확인하라. "
            f"(조용히 자르면 잘못된 값으로 호출이 계속 나간다 — traps.md T9)"
        )
    return value


def optional_env(name: str, default: str | None = None) -> str | None:
    """없거나 빈 문자열이면 default. 있으면 .strip()한 값."""
    _load_dotenv_once()
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = _clean(name, raw)
    return value if value else default


def require_env(name: str) -> str:
    """없거나 비어 있으면 MissingEnvError. 절대 빈 문자열을 돌려주지 않는다."""
    value = optional_env(name)
    if value is None:
        raise MissingEnvError(
            f"필수 환경변수 {name}가 없다. .env.example을 참고해 .env에 채워라."
        )
    return value


def optional_env_int(name: str, default: int) -> int:
    value = optional_env(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise DirtyEnvError(f"{name}는 정수여야 한다: {value!r}") from exc


def optional_env_float(name: str, default: float | None = None) -> float | None:
    """선택 실수 설정. 단가를 잘못 읽으면 비용 가드가 조용히 틀리므로 즉시 실패한다."""
    value = optional_env(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise DirtyEnvError(f"{name}는 실수여야 한다: {value!r}") from exc


def optional_env_bool(name: str, default: bool) -> bool:
    """'true'/'1'/'yes'/'on' → True, 'false'/'0'/'no'/'off' → False.

    그 밖의 값은 추측하지 않고 실패시킨다. 결측(None)과 False를 구분해야 하는
    프로젝트이므로 파싱 실패를 조용히 False로 떨구지 않는다.
    """
    value = optional_env(name)
    if value is None:
        return default
    lowered = value.lower()
    if lowered in ("true", "1", "yes", "on"):
        return True
    if lowered in ("false", "0", "no", "off"):
        return False
    raise DirtyEnvError(f"{name}는 boolean이어야 한다: {value!r}")
