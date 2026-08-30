# PRD Ref: §7.4 · traps.md T7, T107, T112, T115, T117
"""승인된 Stage B 세 종목 replay를 bounded Supabase read로 준비한다."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.analysis.analyze import AnalysisInput, build_user_message
from src.analysis.run import build_input
from src.db.supabase_client import PostgrestReadBudget, get_client
from src.utils.console import enable_utf8_stdout


_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"sb_secret_[A-Za-z0-9_-]{10,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),
)


class ReplayValidationError(ValueError):
    """실제 replay가 Stage A 메타데이터·필수 입력 계약과 다름."""


@dataclass(frozen=True)
class CandidateExpectation:
    code: str
    grade: str
    has_consensus: bool
    turnaround: bool
    industry: str


@dataclass(frozen=True)
class ReplayMetrics:
    code: str
    name: str
    grade: str
    has_consensus: bool
    turnaround: bool
    industry: str
    quarter_count: int
    latest_period: str
    excerpt_chars: int
    as_of: str
    consensus_snapshot_at: str | None
    price_snap_date: str | None
    current_price: float | None
    pri: float
    user_message_chars: int
    secret_matches: int


def _period(row: dict[str, Any]) -> tuple[int, int]:
    return int(row["fiscal_year"]), int(row["fiscal_quarter"])


def validate_casebook_replay(
    data: AnalysisInput,
    expected: CandidateExpectation,
) -> ReplayMetrics:
    """Stage A 셀과 replay 필수 DATA/VALIDATION 계약을 대조한다."""
    problems: list[str] = []
    target = (data.fiscal_year, data.fiscal_quarter)
    periods = [_period(row) for row in data.quarters]
    score = data.score or {}
    gate = data.gate or {}
    actual_consensus = data.consensus is not None

    if data.code != expected.code:
        problems.append(f"code={data.code!r}, expected={expected.code!r}")
    if data.industry != expected.industry:
        problems.append(f"industry={data.industry!r}, expected={expected.industry!r}")
    if score.get("grade") != expected.grade:
        problems.append(f"grade={score.get('grade')!r}, expected={expected.grade!r}")
    if score.get("has_consensus") is not expected.has_consensus:
        problems.append(
            f"screen has_consensus={score.get('has_consensus')!r}, "
            f"expected={expected.has_consensus!r}"
        )
    if actual_consensus is not expected.has_consensus:
        problems.append(
            f"replay has_consensus={actual_consensus!r}, expected={expected.has_consensus!r}"
        )
    if gate.get("turnaround") is not expected.turnaround:
        problems.append(
            f"turnaround={gate.get('turnaround')!r}, expected={expected.turnaround!r}"
        )
    if gate.get("passed") is not True:
        problems.append(f"gate.passed={gate.get('passed')!r}")
    if not 5 <= len(periods) <= 8:
        problems.append(f"quarters={len(periods)}, expected 5~8")
    if not periods or periods[-1] != target:
        problems.append(f"latest_period={periods[-1] if periods else None}, expected={target}")
    if any(period > target for period in periods):
        problems.append("요청 분기 뒤 미래 재무가 포함됐다")
    expected_excerpt_head = f"[출처: {target[0]}년 {target[1]}분기 정기보고서]"
    if not data.excerpt or not data.excerpt.startswith(expected_excerpt_head):
        problems.append("같은 분기 발췌가 없다")
    if not data.as_of:
        problems.append("as_of가 없다")
    pri = (data.pri or {}).get("pri")
    if not isinstance(pri, (int, float)) or isinstance(pri, bool):
        problems.append("pri.pri가 없다")
    consensus_snapshot = (
        (data.consensus or {}).get("snapshot_at") if actual_consensus else None
    )
    if actual_consensus and not consensus_snapshot:
        problems.append("consensus.snapshot_at이 없다")
    if problems:
        raise ReplayValidationError(f"{expected.code}: " + "; ".join(problems))

    # canonical current price 충돌과 prompt 조립 오류까지 Provider 호출 전에 검사한다.
    user_message = build_user_message(data)
    serialized = json.dumps(asdict(data), ensure_ascii=False) + user_message
    secret_matches = sum(len(pattern.findall(serialized)) for pattern in _SECRET_PATTERNS)
    if secret_matches:
        raise ReplayValidationError(f"{expected.code}: 시크릿 패턴 {secret_matches}건")

    price = data.price or {}
    return ReplayMetrics(
        code=data.code,
        name=data.name,
        grade=expected.grade,
        has_consensus=expected.has_consensus,
        turnaround=expected.turnaround,
        industry=expected.industry,
        quarter_count=len(periods),
        latest_period=f"{target[0]}.{target[1]}Q",
        excerpt_chars=len(data.excerpt or ""),
        as_of=str(data.as_of),
        consensus_snapshot_at=(
            str(consensus_snapshot) if consensus_snapshot is not None else None
        ),
        price_snap_date=(
            str(price.get("snap_date")) if price.get("snap_date") is not None else None
        ),
        current_price=(
            float(price["close"])
            if isinstance(price.get("close"), (int, float))
            and not isinstance(price.get("close"), bool)
            else None
        ),
        pri=float(pri),
        user_message_chars=len(user_message),
        secret_matches=secret_matches,
    )


def _expectations(path: Path) -> tuple[int, int, list[CandidateExpectation]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return (
        int(raw["fiscal_year"]),
        int(raw["fiscal_quarter"]),
        [
            CandidateExpectation(
                code=str(item["code"]),
                grade=str(item["grade"]),
                has_consensus=item["has_consensus"],
                turnaround=item["turnaround"],
                industry=str(item["industry"]),
            )
            for item in raw["selected"]
        ],
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def commit_json_artifacts(items: list[tuple[Path, dict[str, Any]]]) -> None:
    """각 대상과 같은 디렉터리에 임시 파일을 만들어 부모 ACL을 그대로 상속한다."""
    staged: list[tuple[Path, Path]] = []
    try:
        for target, payload in items:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise FileExistsError(f"기존 artifact를 덮어쓰지 않는다: {target}")
            source = target.with_name(target.name + ".tmp-stage-b")
            if source.exists():
                raise FileExistsError(f"이전 임시 artifact가 남아 있다: {source}")
            _write_json(source, payload)
            staged.append((source, target))
        for source, target in staged:
            source.replace(target)
    finally:
        for source, _target in staged:
            if source.exists():
                source.unlink()


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="사례집 Stage B bounded replay read")
    parser.add_argument(
        "--stage-a",
        type=Path,
        default=Path("docs/evals/results/casebook-stage-a-2026q2.json"),
    )
    parser.add_argument(
        "--replay-dir", type=Path, default=Path("docs/evals/replays")
    )
    parser.add_argument(
        "--result",
        type=Path,
        default=Path("docs/evals/results/casebook-stage-b-2026q2.json"),
    )
    parser.add_argument("--max-gets", type=int, default=30)
    parser.add_argument("--execute-approved-read", action="store_true")
    args = parser.parse_args()
    if not args.execute_approved_read:
        parser.error("Stage B 승인 뒤 --execute-approved-read를 명시해야 한다")
    if args.max_gets != 30:
        parser.error("승인된 Stage B GET 안전 상한은 정확히 30이다")
    if args.result.exists():
        parser.error(f"기존 Stage B 결과를 덮어쓰지 않는다: {args.result}")

    year, quarter, expected_items = _expectations(args.stage_a)
    budget = PostgrestReadBudget(max_requests=args.max_gets)
    client = get_client()
    valid: list[tuple[CandidateExpectation, AnalysisInput, ReplayMetrics]] = []
    failures: list[dict[str, str]] = []
    for expected in expected_items:
        try:
            data = build_input(
                expected.code,
                year=year,
                quarter=quarter,
                allow_fetch=False,
                read_budget=budget,
            )
            metrics = validate_casebook_replay(data, expected)
            valid.append((expected, data, metrics))
        except ReplayValidationError as exc:
            failures.append({"code": expected.code, "error": str(exc)})

    final_paths = [
        args.replay_dir / f"{expected.code}-{year}q{quarter}.json"
        for expected, _data, _metrics in valid
    ]
    if any(path.exists() for path in final_paths):
        existing = [str(path) for path in final_paths if path.exists()]
        parser.error("기존 replay를 덮어쓰지 않는다: " + ", ".join(existing))

    summary = {
        "status": "completed" if not failures else "partial",
        "stage": "casebook_replay_read",
        "fiscal_year": year,
        "fiscal_quarter": quarter,
        "approved_max_gets": args.max_gets,
        "actual_http_gets": budget.used_requests,
        "requests": budget.requests,
        "external_writes": 0,
        "provider_calls": 0,
        "dart_calls": 0,
        "valid_count": len(valid),
        "failure_count": len(failures),
        "replays": [asdict(metrics) for _expected, _data, metrics in valid],
        "failures": failures,
    }

    artifacts: list[tuple[Path, dict[str, Any]]] = []
    for expected, data, _metrics in valid:
        target = args.replay_dir / f"{expected.code}-{year}q{quarter}.json"
        artifacts.append((target, {
                "synthetic": False,
                "source": "Heimdallr Supabase read-only casebook Stage B export",
                "input": asdict(data),
        }))
    artifacts.append((args.result, summary))
    commit_json_artifacts(artifacts)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
