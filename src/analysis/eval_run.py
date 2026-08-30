# PRD Ref: §7.4
"""저장된 Provider 결과 offline eval 실행.

    python -m src.analysis.eval_run path/to/suite.json
    python -m src.analysis.eval_run path/to/suite.json --output report.json

외부 API·DB·LLM을 호출하지 않는다.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from src.analysis.evaluation import evaluate_suite
from src.utils.console import enable_utf8_stdout


def suite_with_canary_result(
    suite: dict[str, Any],
    canary_result: dict[str, Any],
    *,
    candidate_id: str,
) -> dict[str, Any]:
    """유료 응답 payload를 같은 replay case에만 주입한다.

    저장 gate에서 실패해도 비용이 발생한 raw payload는 품질 진단 대상이다. 다만 실행
    상태를 candidate에 보존해 canary 적격이나 Provider 비교로 오인하지 않는다.
    """
    execution_status = canary_result.get("status")
    if execution_status not in {"completed", "failed"}:
        raise ValueError("완료되거나 raw payload가 보존된 실패만 평가할 수 있다")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("canary 결과를 주입할 suite case가 없다")
    result_input = canary_result.get("input")
    # JSON의 28000과 28000.0은 Python에서 같은 수치다. 이 표현 차이는 허용하되,
    # 실제 평가는 저장된 request/input hash와 맞는 canary 직렬화를 사용한다.
    matching_indexes = [
        index
        for index, case in enumerate(cases)
        if case.get("input") == result_input
    ]
    if len(matching_indexes) != 1:
        raise ValueError("canary 결과와 eval suite의 replay 입력이 다르다")
    candidate = canary_result.get("candidate")
    if not isinstance(candidate, dict) or not isinstance(candidate.get("payload"), dict):
        raise ValueError("canary candidate.payload는 object여야 한다")

    injected = deepcopy(suite)
    case_index = matching_indexes[0]
    injected["cases"][case_index]["input"] = deepcopy(result_input)
    injected_candidate = deepcopy(candidate)
    injected_candidate["id"] = candidate_id
    injected_candidate["execution_status"] = execution_status
    existing = injected["cases"][case_index].get("candidates", [])
    # 첫 canary는 suite에 들어 있던 fixture/과거 후보를 대체한다. 이후 이 helper가
    # 주입한 실행 결과는 execution_status를 가지므로 같은 case의 다른 Provider를 보존한다.
    injected_candidates = [
        item
        for item in existing
        if item.get("execution_status") in {"completed", "failed"}
    ]
    injected["cases"][case_index]["candidates"] = [
        *injected_candidates,
        injected_candidate,
    ]
    return injected


def main() -> None:
    parser = argparse.ArgumentParser(description="Heimdallr LLM offline replay eval")
    parser.add_argument("suite", type=Path, help="replay input과 저장된 후보 payload JSON")
    parser.add_argument("--output", type=Path, help="평가 결과 JSON 저장 경로")
    parser.add_argument(
        "--canary-result",
        type=Path,
        action="append",
        help="같은 replay 입력의 canary 결과를 suite 후보로 사용(여러 번 지정 가능)",
    )
    parser.add_argument(
        "--candidate-id",
        default="canary-result",
        help="--canary-result 후보 식별자",
    )
    args = parser.parse_args()

    raw = json.loads(args.suite.read_text(encoding="utf-8"))
    if args.canary_result:
        for index, result_path in enumerate(args.canary_result, start=1):
            result = json.loads(result_path.read_text(encoding="utf-8"))
            candidate_id = args.candidate_id
            if len(args.canary_result) > 1:
                candidate_id = f"{candidate_id}-{index}"
            raw = suite_with_canary_result(
                raw,
                result,
                candidate_id=candidate_id,
            )
    report = evaluate_suite(raw)
    body = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(body, encoding="utf-8")
    print(body, end="")


if __name__ == "__main__":
    enable_utf8_stdout()
    main()
