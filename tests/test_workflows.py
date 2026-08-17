# PRD Ref: §10 · traps.md T10
"""GitHub Actions 워크플로 정합성. 외부 I/O 없이 돈다.

★ 워크플로는 **로컬에서 절대 안 돌아본 채 배포되는 코드**다.
  YAML 오타나 없는 모듈 호출은 실제 실행 전까지 아무도 모른다 —
  여기서 잡을 수 있는 것은 전부 잡는다.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

# ★ 상대경로를 쓰면 **실행 위치에 따라 테스트가 깨진다.**
#   실측: 다른 디렉터리에서 pytest를 부르니 FileNotFoundError로 2건이 실패했다.
#   CI는 리포지토리 루트에서 돌지만, 그 가정에 기대면 언젠가 조용히 어긋난다.
WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
YAML_FILES = sorted(WORKFLOWS.glob("*.yml"))

#: P11 완료(2026-08-16)로 전부 스케줄이 붙었다. 대기 중인 워크플로는 없다.
PENDING_P11: set[str] = set()


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_workflows_exist():
    names = {f.name for f in YAML_FILES}
    assert names >= {
        "universe_daily.yml", "disclosure_poll.yml", "daily_digest.yml",
        "quarterly_backfill.yml", "outcome_update.yml", "promotion_check.yml",
    }


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda p: p.name)
def test_yaml_parses(path: Path):
    yaml = pytest.importorskip("yaml")
    body = yaml.safe_load(_text(path))
    assert body.get("jobs"), f"{path.name}에 jobs가 없다"


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda p: p.name)
def test_every_job_has_timeout(path: Path):
    """★ `timeout-minutes`가 없으면 무한 대기가 Actions 분을 태운다(PRD §10.1)."""
    yaml = pytest.importorskip("yaml")
    for name, job in (yaml.safe_load(_text(path)).get("jobs") or {}).items():
        assert "timeout-minutes" in job, f"{path.name}:{name}에 timeout-minutes가 없다"


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda p: p.name)
def test_every_workflow_has_concurrency(path: Path):
    """겹쳐 돌면 서로의 작업을 밟는다. 특히 getUpdates는 메시지를 빼앗는다(T44)."""
    yaml = pytest.importorskip("yaml")
    assert yaml.safe_load(_text(path)).get("concurrency"), f"{path.name}에 concurrency가 없다"


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda p: p.name)
def test_no_sleep_loop(path: Path):
    """★ 잡 안 sleep도 과금된다(PRD §10.1). 짧은 잡을 여러 번 띄우는 편이 싸다."""
    body = _text(path)
    assert not re.search(r"^\s*(-\s*)?sleep\s+\d", body, re.M), f"{path.name}에 sleep이 있다"


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda p: p.name)
def test_secrets_are_not_hardcoded(path: Path):
    """토큰·키가 워크플로에 그대로 박히면 public repo에서 그대로 노출된다."""
    body = _text(path)
    # 봇 토큰 형태(숫자:영숫자)나 긴 base64 같은 것이 리터럴로 있으면 안 된다
    assert not re.search(r"\d{8,}:[A-Za-z0-9_-]{20,}", body), f"{path.name}에 봇 토큰이 박혔다"
    for key in ("SUPABASE_SERVICE_KEY", "OPENDART_API_KEY", "ANTHROPIC_API_KEY"):
        for line in body.splitlines():
            if key in line and "secrets." not in line and not line.strip().startswith("#"):
                pytest.fail(f"{path.name}: {key}가 secrets 참조가 아니다 — {line.strip()}")


@pytest.mark.parametrize(
    "path", [p for p in YAML_FILES if p.name in PENDING_P11], ids=lambda p: p.name
)
def test_pending_workflows_have_no_schedule(path: Path):
    """★★ 아직 못 도는 워크플로에 스케줄을 걸면 안 된다.

    걸어두면 매일 빨간 X가 쌓이고, 빨간 X가 일상이 되면 **진짜 고장을 못 알아본다.**
    반대로 '성공했는데 아무것도 안 하는' 잡으로 만들면 더 나쁘다 —
    돌고 있다고 착각한 채 데이터가 안 쌓인다.
    (P11 완료로 현재 대기 목록은 비어 있다 — 규칙은 남겨 둔다.)
    """
    yaml = pytest.importorskip("yaml")
    on = yaml.safe_load(_text(path)).get(True) or yaml.safe_load(_text(path)).get("on")
    assert "schedule" not in (on or {})


def _module_targets() -> set[str]:
    """워크플로가 `python -m` 으로 부르는 모듈 전부."""
    found: set[str] = set()
    for path in YAML_FILES:
        found |= set(re.findall(r"python -m ([\w.]+)", _text(path)))
    return found


def test_every_invoked_module_exists():
    """★ 워크플로가 없는 모듈을 부르면 **실행 전까지 아무도 모른다.**"""
    for module in sorted(_module_targets()):
        importlib.import_module(module)


def test_kis_only_used_where_needed():
    """KIS 시크릿은 실제로 쓰는 워크플로에만 둔다 — 노출면을 넓히지 않는다."""
    yaml = pytest.importorskip("yaml")
    for path in YAML_FILES:
        body = _text(path)
        if "KIS_APP_KEY" not in body:
            continue
        # KIS를 쓰는 건 price_run(universe_daily)과 P11 결과추적뿐이다
        assert path.name in {"universe_daily.yml", "outcome_update.yml"}, (
            f"{path.name}이 KIS 시크릿을 받는데 KIS를 쓰지 않는다"
        )


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda p: p.name)
def test_sending_workflows_wire_dashboard_url(path: Path):
    """★ 발송 워크플로는 `DASHBOARD_BASE_URL`을 반드시 넘긴다.

    안 넘기면 `optional_env`가 **코드에 박힌 기본값**으로 조용히 떨어진다.
    에러도 경고도 없고, 텔레그램 메시지는 정상으로 보이는데
    **링크만 엉뚱한 도메인을 가리킨다** — 눌러보기 전까지 아무도 모른다.
    Vercel 프로젝트 이름이 기본값과 다르면 그날부터 전 메시지의 링크가 죽는다.

    저장소 변수가 비어 있어도 안전하다: `optional_env`는 빈 문자열을 default로 떨군다.

    기준을 `--send` 플래그가 아니라 **봇 토큰 보유**로 잡는다.
    `telegram_listen`은 `--send` 없이도 질의에 회신하므로 플래그로 거르면 빠진다.
    """
    body = _text(path)
    if "HEIMDALLR_TELEGRAM_BOT_TOKEN" not in body:
        return
    assert "DASHBOARD_BASE_URL" in body, (
        f"{path.name}이 텔레그램 봇 토큰을 받는데 DASHBOARD_BASE_URL을 넘기지 않는다"
    )


def test_telegram_listen_analyzes_on_schedule():
    """★★ 정기 실행에서 LLM이 불리는가.

    원래는 `${{ inputs.analyze && '--analyze' || '' }}`였다.
    `schedule` 이벤트에는 `inputs`가 없어 항상 빈 문자열이 되고,
    **cron 경로에서는 LLM이 영영 호출되지 않았다** — 에러도 경고도 없이
    해석 없는 숫자 리포트만 나간다. 실측 로그가 매번 `LLM 분석 OFF`였다.

    같은 삼항은 반대 방향으로도 틀린다: GitHub 표현식에서 `false`는 falsy라
    `inputs.x && A || B`가 x=false일 때도 **B**를 준다.
    즉 "수동으로 끄기"가 에러 없이 무시된다. 그래서 분기를 셸로 옮겼다.

    비용은 코드가 막는다 — `analyze()`가 `check_budget()`으로
    월 $8 · 일 20건 상한을 걸고, 기존 분석이 있으면 재사용해 재질의는 0원이다.
    """
    yaml = pytest.importorskip("yaml")
    path = WORKFLOWS / "telegram_listen.yml"
    body = _text(path)

    assert "inputs.analyze &&" not in body, (
        "GitHub 삼항으로 --analyze를 거는 형태로 되돌아갔다 — "
        "schedule에는 inputs가 없어 cron 경로에서 LLM이 안 불린다"
    )
    assert "--analyze" in body, "telegram_listen이 --analyze를 아예 주지 않는다"

    spec = yaml.safe_load(body)
    on = spec.get(True) or spec.get("on")
    assert on.get("workflow_dispatch", {}).get("inputs", {})["analyze"]["default"] is True, (
        "수동 실행 기본값이 켜져 있지 않다 — UI와 cron 동작이 어긋난다"
    )
