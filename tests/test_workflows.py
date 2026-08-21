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


# ═══════════════════════════════════════════════════════════════════
# T79 — `schedule` 워크플로의 `if:`는 inputs를 보면 안 된다
# ═══════════════════════════════════════════════════════════════════
#: `inputs.x` 와 `github.event.inputs.x` 를 모두 잡는다.
INPUTS_REF = re.compile(r"\binputs\s*\.")


def _trigger_map(spec: dict) -> dict:
    """`on:` 블록. PyYAML이 `on`을 **불리언 True로 파싱**하는 것에 주의한다."""
    return spec.get(True) or spec.get("on") or {}


def _if_conditions(spec: dict) -> list[tuple[str, str]]:
    """워크플로 안의 모든 `if:` 조건식을 (위치, 식)으로 모은다.

    잡 수준과 스텝 수준을 **둘 다** 본다 — 어느 쪽이든 같은 방식으로 틀린다.
    """
    found: list[tuple[str, str]] = []
    for job_name, job in (spec.get("jobs") or {}).items():
        if "if" in job:
            found.append((job_name, str(job["if"])))
        for index, step in enumerate(job.get("steps") or []):
            if "if" in step:
                label = step.get("name") or f"step[{index}]"
                found.append((f"{job_name} · {label}", str(step["if"])))
    return found


@pytest.mark.parametrize("path", YAML_FILES, ids=lambda p: p.name)
def test_scheduled_workflow_never_gates_on_inputs(path: Path):
    """★★★ T79 — `schedule`이 붙은 워크플로의 `if:`에서 `inputs`를 보면 안 된다.

    `disclosure_poll`의 `⚡ 즉시 알림`이 `inputs.notify != false`로 걸려 있었다.
    schedule 이벤트에는 `inputs`가 **아예 없어** `inputs.notify`는 null인데,
    GitHub 표현식은 타입이 다르면 숫자로 캐스팅한다 — null도 0, false도 0이라
    `null != false`가 **false**가 된다. 즉 cron 경로에서 그 스텝은 **영영 skipped**였다.

    이게 왜 안 보였나: 발송 대상(68종목)을 계산하는 앞 스텝들은 전부 성공하고,
    `skipped`는 Actions UI에서 **초록색**이라 잡 성공만 보면 정상으로 읽힌다.
    스텝 단위(`gh api …/jobs --jq '.jobs[].steps[]'`)를 봐야 드러난다.

    **T55의 재발이다.** 그때는 `telegram_listen` 한 곳만 고치고 개별 테스트를 달았는데,
    같은 실수가 다른 파일에서 그대로 다시 났다 — 그래서 검사를 **클래스 전체**로 올린다.
    분기가 필요하면 `if:`가 아니라 **셸에서** 한다(빈 문자열을 기본값으로 떨군다).
    """
    yaml = pytest.importorskip("yaml")
    spec = yaml.safe_load(_text(path))
    if "schedule" not in _trigger_map(spec):
        return

    offenders = [
        f"{where}: {cond}" for where, cond in _if_conditions(spec) if INPUTS_REF.search(cond)
    ]
    assert not offenders, (
        f"{path.name}은 schedule로도 도는데 `if:`가 inputs를 본다 — "
        "cron 경로에서 그 스텝은 영영 skipped다(T79). 분기는 셸로 옮겨라:\n"
        + "\n".join(offenders)
    )


def test_inputs_in_if_guard_actually_catches_it():
    """★ 검사기를 **반드시 걸려야 하는 입력**으로 먼저 검증한다(T54).

    이 검사기는 `_if_conditions`가 스텝을 못 찾거나 `_trigger_map`이 `on:`을
    놓치면 **조용히 0건을 검사하고 통과**한다 — 가장 위험한 실패 모양이다.
    """
    yaml = pytest.importorskip("yaml")
    buggy = yaml.safe_load(
        "on:\n"
        "  schedule:\n"
        "    - cron: '0 0 * * *'\n"
        "  workflow_dispatch:\n"
        "    inputs:\n"
        "      notify:\n"
        "        type: boolean\n"
        "jobs:\n"
        "  poll:\n"
        "    steps:\n"
        "      - name: 알림\n"
        "        if: inputs.notify != false\n"
        "        run: echo hi\n"
    )
    # ① `on:`을 True 키로 읽어내는가 (PyYAML의 함정)
    assert "schedule" in _trigger_map(buggy), "on: 블록을 못 읽으면 전 파일이 통과한다"
    # ② 스텝의 if를 실제로 수집하는가
    conditions = _if_conditions(buggy)
    assert conditions and any(INPUTS_REF.search(c) for _, c in conditions), (
        "걸려야 할 조건식을 못 잡았다 — 검사기가 무력화됐다"
    )
    # ③ 고친 형태(셸 분기)는 통과하는가 — 과잉 차단도 버그다
    fixed = yaml.safe_load(
        "on:\n"
        "  schedule:\n"
        "    - cron: '0 0 * * *'\n"
        "jobs:\n"
        "  poll:\n"
        "    steps:\n"
        "      - name: 알림\n"
        "        if: steps.season.outputs.run == 'true'\n"
        "        env:\n"
        "          NOTIFY_INPUT: x\n"
        "        run: echo hi\n"
    )
    assert not [c for _, c in _if_conditions(fixed) if INPUTS_REF.search(c)]


def test_flash_notification_is_wired_on_schedule():
    """★★ T79 — 즉시 알림이 **실제로 발송까지** 가는가.

    위 검사는 "`if:`가 inputs를 안 본다"만 본다. 스텝이 통째로 사라져도 통과한다 —
    그래서 발송 명령이 살아 있는지를 따로 못박는다.
    11월 시즌에 이 한 줄이 없으면 알림이 통째로 안 나간다.
    """
    body = _text(WORKFLOWS / "disclosure_poll.yml")
    assert "src.notify.batch --flash --send" in body, (
        "disclosure_poll이 즉시 알림을 발송하지 않는다 — 시즌에 알림이 통째로 죽는다"
    )


# ═══════════════════════════════════════════════════════════════════
# 대시보드 정합성 — 화면은 CI에서 안 돌아보므로 소스로 검사한다
# ═══════════════════════════════════════════════════════════════════
DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"


def _strip_ts_comments(source: str) -> str:
    """`//` 줄주석과 `/* */` 블록주석을 걷어낸다.

    ★ 문자열 리터럴 안의 `//`(예: `https://…`)를 지우면 안 된다 —
      URL이 통째로 사라져 검사기가 조용히 무력화된다. 그래서 줄주석은
      **줄 맨 앞(공백 뒤)에서 시작할 때만** 지운다. 이 저장소의 주석은 전부 그 형태다.
    """
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return "\n".join(
        line for line in without_block.splitlines() if not line.lstrip().startswith(("//", "*"))
    )


def _dashboard_sources() -> list[Path]:
    """`node_modules`·`.next`를 제외한 대시보드 소스."""
    out: list[Path] = []
    for pattern in ("app/**/*.ts", "app/**/*.tsx", "lib/**/*.ts", "components/**/*.tsx"):
        out += [p for p in DASHBOARD.glob(pattern)
                if "node_modules" not in p.parts and ".next" not in p.parts]
    return sorted(out)


def test_every_supabase_client_disables_fetch_cache():
    """★★ T59 — `createClient`는 **반드시** `NO_STORE_OPTIONS`를 받아야 한다.

    `export const dynamic = "force-dynamic"`는 페이지 렌더만 매번 다시 할 뿐,
    supabase-js가 부르는 `fetch`까지 막지 않는다. Next는 그 응답을
    `.next/cache/fetch-cache`에 디스크로 남기고 Vercel은 배포 사이에 복원한다.

    실측(2026-08-17): 게이트를 고쳐 DB가 발송대상 67이 된 뒤에도
    로컬·배포 화면이 모두 **80**을 보여줬다. HTTP 200에 화면도 멀쩡하고
    `X-Vercel-Cache: MISS`였다 — **에러 없이 숫자만 낡는다.**
    """
    offenders = []
    for path in _dashboard_sources():
        body = path.read_text(encoding="utf-8")
        for match in re.finditer(r"createClient\((.*?)\);", body, re.S):
            if "NO_STORE_OPTIONS" not in match.group(1):
                offenders.append(f"{path.name}: {match.group(1)[:60]}")
    assert not offenders, (
        "NO_STORE_OPTIONS 없이 만든 Supabase 클라이언트가 있다 — "
        "화면이 며칠 전 숫자를 조용히 보여준다(T59):\n" + "\n".join(offenders)
    )


def test_dashboard_never_links_dart_search_page():
    """★ T58 — 회사명으로 DART를 검색하는 주소는 쓰지 않는다.

    `dsab007/main.do?textCrpNm=…`은 200을 주고 검색창에 이름까지 채워 주지만
    **검색을 실행하지 않아 빈 화면**이 뜬다. 공시 원문은 접수번호로만 열린다.
    """
    # ★ 주석은 걷어낸다 — `links.ts`는 그 주소를 **쓰지 말라고 설명하는** 곳이라
    #   본문 검사에 그대로 걸린다. 검사기가 자기 문서에 걸려 무력화되면 안 된다.
    offenders = []
    for path in _dashboard_sources():
        code = _strip_ts_comments(path.read_text(encoding="utf-8"))
        if "textCrpNm" in code or "dsab007" in code:
            offenders.append(path.name)
    assert not offenders, f"DART 검색 URL이 되살아났다(T58): {offenders}"


def test_dart_search_guard_actually_catches_it():
    """★ 검사기를 **반드시 걸려야 하는 입력**으로 먼저 검증한다(T54와 같은 실패 모양).

    주석 제거를 넣으면서 검사기가 통째로 무력화될 수 있다 — 실제로 잡는지 본다.
    """
    bad = 'const u = `https://dart.fss.or.kr/dsab007/main.do?textCrpNm=${name}`;'
    assert "dsab007" in _strip_ts_comments(bad)
    assert "dsab007" not in _strip_ts_comments("// dsab007 은 쓰지 마라\nconst x = 1;")
    assert "dsab007" not in _strip_ts_comments("/* dsab007 금지 */\nconst x = 1;")


def test_dashboard_and_python_agree_on_external_urls():
    """★ 링크 규칙이 갈라지면 텔레그램과 화면이 다른 곳을 가리키는데 **둘 다 200**이다."""
    from src.notify import links

    ts = (DASHBOARD / "lib" / "links.ts").read_text(encoding="utf-8")
    assert "dsaf001/main.do?rcpNo=" in ts and "dsaf001/main.do?rcpNo=" in links.DART_REPORT
    assert "finance.naver.com/item/main.naver" in ts
    assert "finance.naver.com/item/main.naver" in links.NAVER_STOCK
    assert "m.stock.naver.com/domestic/stock/" in ts
    assert "m.stock.naver.com/domestic/stock/" in links.NAVER_STOCK_MOBILE


def test_quarter_prices_collector_is_wired_into_a_workflow():
    """수집기를 만들어 놓고 어디서도 안 부르면 차트의 주가 라인이 영영 비어 있다."""
    called = [p.name for p in YAML_FILES
              if "collectors.quarter_prices" in _text(p)]
    assert called, "quarter_prices 수집기를 부르는 워크플로가 없다"


def test_no_stale_chart_color_names_in_ui_text():
    """★ T65 — 차트 색 이름을 본문에 손으로 적으면 조용히 어긋난다.

    실측(2026-08-17): 색을 바꾼 뒤에도 카드 제목 note에 `초록 = 영업이익 YoY`가
    남아 있었다. 화면은 노란 선인데 설명은 초록이라 **둘 다 정상으로 보인다.**
    검사기가 자기 주석에 걸리지 않게 주석은 걷어낸다.
    """
    STALE = ("초록 실선", "주황 실선", "보라 점선", "회색 점선", "초록 =", "주황 =")
    offenders = []
    for path in _dashboard_sources():
        code = _strip_ts_comments(path.read_text(encoding="utf-8"))
        for word in STALE:
            if word in code:
                offenders.append(f"{path.name}: {word}")
    assert not offenders, (
        "차트 색이 바뀌었는데 설명 글이 안 따라왔다(T65) — "
        f"`SERIES_COLOR`를 style로 쓰라: {offenders}"
    )


def test_chart_color_guard_actually_catches_it():
    """검사기를 **반드시 걸려야 하는 입력**으로 먼저 검증한다(T54)."""
    assert "초록 실선" in _strip_ts_comments('note="초록 실선은 영업이익"')
    assert "초록 실선" not in _strip_ts_comments("// 초록 실선은 쓰지 마라\nconst x=1;")
