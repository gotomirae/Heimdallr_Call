# PRD Ref: §7.2, §7.4 · traps.md T109, T110, T114, T120, T123
"""LLM 사실 서술의 숫자가 실제 요청에 근거하는지 결정론적으로 검사한다.

미래 시나리오·watch metric의 목표값은 투자 판단이므로 대상에서 제외한다. 과거/현재
실적·주가·공시를 사실처럼 말하는 필드만 검사해 LLM의 재무 계산·단위 환산을 차단한다.
"""

from __future__ import annotations

from copy import deepcopy
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from src.config.constants import LLM_NUMERIC_WHOLE_ROUNDING_MIN_PERCENT


NUMBER_WITH_UNIT_RE = re.compile(
    r"(?<![\w.])([+\-−]?\d[\d,]*(?:\.\d+)?)\s*"
    r"(백만원|억원|억|조원|조|원|%p|%|배)"
)
_COMPOUND_JO_EOK = re.compile(
    r"(?<![\w.])([+\-−]?)(\d[\d,]*(?:\.\d+)?)\s*조(?:원)?\s*"
    r"(\d[\d,]*(?:\.\d+)?)\s*(?:억원|억)"
)
_COMPOUND_MAN_WON = re.compile(
    r"(?<![\w.])([+\-−]?)(\d[\d,]*(?:\.\d+)?)\s*만\s*"
    r"(\d[\d,]*(?:\.\d+)?)\s*원"
)
_BARE_NUMBER = re.compile(r"^[+\-−]?\d[\d,]*(?:\.\d+)?$")
_FACT_SOURCE_RE = re.compile(r"\[\[(F\d{3}):([^\]\r\n]+)\]\]")
_FACT_OUTPUT_RE = re.compile(r"\[\[(F\d{3})\]\]")
_ANY_FACT_OUTPUT_RE = re.compile(r"\[\[(F\d+)\]\]")

# 시나리오·리스크 감시값은 미래 판단이다. 아래 경로만 과거/현재 사실 주장이다.
FACTUAL_PATHS = (
    "one_line_thesis",
    "why_now",
    "earnings_change.cause",
    "earnings_change.effect",
    "growth_engine.evidence",
    "acceleration_quality.base_effect_assessment",
    "price_position.reason",
    "price_position.price_history",
    "price_position.priced_in",
    "price_position.not_priced_in",
)
_QUARTER_UNIT_FIELDS = {
    "revenue": "억",
    "op": "억",
    "ttm_revenue": "억",
    "revenue_yoy": "%",
    "op_yoy": "%",
    "opm": "%",
    "ttm_opm": "%",
    "opm_yoy_delta": "%p",
}
_PRICE_UNIT_FIELDS = {
    "close": "원",
    "current_price": "원",
    "high_52w": "원",
    "low_52w": "원",
    "chg_pct": "%",
    "pos_52w": "%",
    "rel_ret_3m": "%p",
    "relative_return_3m": "%p",
    "pbr": "배",
    "per_pctile_3y": "%",
}
_CONSENSUS_UNIT_FIELDS = {
    "revenue_est": "억",
    "op_est": "억",
    "np_est": "억",
    "eps_est": "원",
}


def strings_in(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in strings_in(item)]
    if isinstance(value, list):
        return [text for item in value for text in strings_in(item)]
    return []


def _at_path(value: dict[str, Any], path: str) -> Any:
    node: Any = value
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _canonical_number(raw: str) -> str:
    try:
        value = Decimal(raw.replace(",", "").replace("−", "-"))
    except InvalidOperation:
        return raw
    if value == 0:
        value = abs(value)
    return format(value.normalize(), "f")


def _canonical_unit(unit: str) -> str:
    return {"억원": "억", "조원": "조"}.get(unit, unit)


def _header_unit(cell: str) -> str | None:
    """분기 파이프 표 헤더의 단위를 셀 값에 복원한다."""
    if "%p" in cell:
        return "%p"
    if "%" in cell:
        return "%"
    for label, unit in (
        ("(억원)", "억"),
        ("(억)", "억"),
        ("(백만원)", "백만원"),
        ("(원)", "원"),
        ("(배)", "배"),
    ):
        if label in cell:
            return unit
    return None


def annotate_factual_numbers(user_message: str) -> str:
    """입력의 사실 숫자를 인라인 참조로 바꿔 모델의 숫자 재타이핑을 없앤다.

    ``[[F001:+595.1억원]]``처럼 원값을 바로 옆에 둬 별도 카탈로그를 중복하지 않는다.
    모델은 사실 서술에서 ``[[F001]]``만 반환하고, 저장 전 프로그램이 원값을 복원한다.
    """
    if _FACT_SOURCE_RE.search(user_message):
        return user_message

    next_id = 1

    def marker(display: str) -> str:
        nonlocal next_id
        if next_id > 999:
            raise ValueError("사실 숫자 참조가 999개를 초과했다")
        result = f"[[F{next_id:03d}:{display}]]"
        next_id += 1
        return result

    def annotate_explicit(line: str) -> str:
        compound_spans = [
            (match.start(), match.end(), match.group(0).strip())
            for pattern in (_COMPOUND_JO_EOK, _COMPOUND_MAN_WON)
            for match in pattern.finditer(line)
        ]
        occupied = [(start, end) for start, end, _ in compound_spans]
        spans = list(compound_spans)
        for match in NUMBER_WITH_UNIT_RE.finditer(line):
            if any(start < match.end() and match.start() < end for start, end in occupied):
                continue
            spans.append((match.start(), match.end(), match.group(0).strip()))
        if not spans:
            return line
        pieces: list[str] = []
        cursor = 0
        for start, end, display in sorted(spans):
            pieces.append(line[cursor:start])
            pieces.append(marker(display))
            cursor = end
        pieces.append(line[cursor:])
        return "".join(pieces)

    header_units: list[str | None] = []
    declared_unit: str | None = None
    output: list[str] = []
    for raw_line in user_message.splitlines():
        if raw_line.startswith("###"):
            header_units = []
            declared_unit = None
        declaration = re.search(r"\(단위\s*:\s*(억원|원|백만원)\)", raw_line)
        if declaration:
            declared_unit = {
                "억원": "억",
                "원": "원",
                "백만원": "백만원",
            }[declaration.group(1)]
        if "|" in raw_line:
            raw_cells = [cell.strip() for cell in raw_line.split("|")]
            inferred = [_header_unit(cell) for cell in raw_cells]
            if any(inferred):
                header_units = inferred

        line = annotate_explicit(raw_line)
        if "|" in line:
            cells = line.split("|")
            for index, cell in enumerate(cells):
                stripped = cell.strip()
                if not _BARE_NUMBER.fullmatch(stripped):
                    continue
                unit = header_units[index] if index < len(header_units) else None
                unit = unit or declared_unit
                if unit is None:
                    continue
                leading = cell[: len(cell) - len(cell.lstrip())]
                trailing = cell[len(cell.rstrip()):]
                cells[index] = f"{leading}{marker(stripped + unit)}{trailing}"
            line = "|".join(cells)
        output.append(line)
    return "\n".join(output)


def _replace_references(value: Any, references: dict[str, str]) -> Any:
    if isinstance(value, str):
        def replace_source(match: re.Match[str]) -> str:
            ref, display = match.groups()
            expected = references.get(ref)
            if expected is None:
                raise ValueError(f"입력에 없는 숫자 참조: {ref}")
            if display != expected:
                raise ValueError(
                    f"숫자 참조 원문 불일치: {ref} "
                    f"(입력={expected}, 출력={display})"
                )
            return expected

        value = _FACT_SOURCE_RE.sub(replace_source, value)
        unknown = sorted(
            ref for ref in _ANY_FACT_OUTPUT_RE.findall(value) if ref not in references
        )
        if unknown:
            raise ValueError(f"입력에 없는 숫자 참조: {', '.join(unknown)}")
        return _FACT_OUTPUT_RE.sub(lambda match: references[match.group(1)], value)
    if isinstance(value, dict):
        return {key: _replace_references(item, references) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_references(item, references) for item in value]
    return value


def _set_path(value: dict[str, Any], path: str, replacement: Any) -> None:
    node: Any = value
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return
        node = node[part]
    if isinstance(node, dict) and parts[-1] in node:
        node[parts[-1]] = replacement


def resolve_factual_references(
    payload: dict[str, Any],
    *,
    user_message: str,
) -> dict[str, Any]:
    """사실 필드의 참조를 원문 숫자로 복원한다.

    과거 request snapshot에는 참조 표시가 없으므로 그대로 반환한다. 이 호환 경계 덕분에
    기존 paid replay를 최신 builder로 소급 변경하지 않는다(T111). 모델이 입력의 전체
    ``[[F001:원문값]]``을 복사해도 정확히 일치할 때만 받는다. 직접 쓴 숫자는 이 함수 뒤의
    기존 동일 단위 grounding gate가 검사한다.
    """
    references = {
        ref: display for ref, display in _FACT_SOURCE_RE.findall(user_message)
    }
    if not references:
        return payload

    resolved = deepcopy(payload)
    for path in FACTUAL_PATHS:
        original = _at_path(payload, path)
        if original is None:
            continue
        _set_path(resolved, path, _replace_references(original, references))
    return resolved


def _number_claims(texts: list[str]) -> set[tuple[str, str]]:
    claims: set[tuple[str, str]] = set()
    for text in texts:
        remaining = text

        def add_compound(match: re.Match[str], multiplier: Decimal, unit: str) -> str:
            sign = Decimal("-1") if match.group(1) in {"-", "−"} else Decimal("1")
            major = Decimal(match.group(2).replace(",", ""))
            minor = Decimal(match.group(3).replace(",", ""))
            claims.add((_canonical_number(str(sign * (major * multiplier + minor))), unit))
            return " " * len(match.group(0))

        remaining = _COMPOUND_JO_EOK.sub(
            lambda match: add_compound(match, Decimal("10000"), "억"), remaining
        )
        remaining = _COMPOUND_MAN_WON.sub(
            lambda match: add_compound(match, Decimal("10000"), "원"), remaining
        )
        for match in NUMBER_WITH_UNIT_RE.finditer(remaining):
            number = match.group(1)
            unit = _canonical_unit(match.group(2))
            following = remaining[match.end():match.end() + 8]
            if (
                unit in {"%", "%p"}
                and not number.startswith(("+", "-", "−"))
                and re.match(r"\s*(?:하락|감소)", following)
            ):
                number = f"-{number}"
            claims.add((_canonical_number(number), unit))
    return claims


def _add_source_claim(
    claims: set[tuple[str, str]],
    value: Any,
    unit: str,
    *,
    display_decimals: int | None = None,
) -> None:
    if value is None or isinstance(value, bool):
        return
    number = Decimal(str(value).replace(",", "").replace("−", "-"))
    claims.add((_canonical_number(str(number)), unit))
    if display_decimals is not None:
        quantum = Decimal("1").scaleb(-display_decimals)
        rounded = number.quantize(quantum, rounding=ROUND_HALF_UP)
        claims.add((_canonical_number(str(rounded)), unit))


def _pipe_table_claims(text: str) -> set[tuple[str, str]]:
    """파이프 표의 단위 헤더를 셀 숫자에 복원한다."""
    claims: set[tuple[str, str]] = set()
    declared_unit: str | None = None
    header_units: list[str | None] = []
    for line in text.splitlines():
        if line.startswith("###"):
            declared_unit = None
            header_units = []
        declaration = re.search(r"\(단위\s*:\s*(억원|원|백만원)\)", line)
        if declaration:
            declared_unit = {
                "억원": "억",
                "원": "원",
                "백만원": "백만원",
            }[declaration.group(1)]
        if "|" not in line:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        inferred = ["%" if "(%)" in cell else None for cell in cells]
        if any(inferred):
            header_units = inferred
        for index, cell in enumerate(cells):
            if not _BARE_NUMBER.fullmatch(cell):
                continue
            unit = header_units[index] if index < len(header_units) else None
            unit = unit or declared_unit
            if unit:
                _add_source_claim(claims, cell.replace("−", "-"), unit)
    return claims


def _input_number_claims(data: Any, *, user_message: str) -> set[tuple[str, str]]:
    claims = _number_claims([user_message])
    claims.update(_pipe_table_claims(user_message))
    for quarter in data.quarters:
        for field, unit in _QUARTER_UNIT_FIELDS.items():
            value = quarter.get(field)
            if value is None:
                continue
            if unit == "억":
                value = Decimal(str(value)) / Decimal("100000000")
            _add_source_claim(
                claims,
                value,
                unit,
                display_decimals=0 if unit == "억" else 1,
            )
    for values, units in (
        (data.price or {}, _PRICE_UNIT_FIELDS),
        (data.consensus or {}, _CONSENSUS_UNIT_FIELDS),
    ):
        for field, unit in units.items():
            value = values.get(field)
            if value is None or isinstance(value, bool):
                continue
            if unit == "억":
                value = Decimal(str(value)) / Decimal("100000000")
            if field == "pos_52w":
                value = Decimal(str(value)) * Decimal("100")
            decimals = 1 if unit in {"%", "%p"} else None
            _add_source_claim(claims, value, unit, display_decimals=decimals)
            if unit in {"%", "%p"}:
                # 시세 JSON 원자료는 메시지에 full precision으로도 실린다. 모델이 이를
                # 소수 둘째 자리로 정상 반올림한 표기는 새 계산값이 아니다(T120).
                _add_source_claim(claims, value, unit, display_decimals=2)
            if field in {"rel_ret_3m", "relative_return_3m"}:
                alternate = "%" if unit == "%p" else "%p"
                _add_source_claim(
                    claims,
                    value,
                    alternate,
                    display_decimals=decimals,
                )
                _add_source_claim(
                    claims,
                    value,
                    alternate,
                    display_decimals=2,
                )
    # 큰 성장률과 금액은 한국어 투자 문장에서 한 자리 소수 입력을 정수로 정상
    # 표시 반올림하기도 한다. 메시지·표·구조화 입력을 모두 모은 뒤 적용해야 bare 표 셀도
    # 빠지지 않는다. 같은 단위 ROUND_HALF_UP만 허용하고, OPM처럼 100 미만인 비율은
    # 0.1%p도 판정을 바꿀 수 있으므로 그대로 유지한다(T87).
    for number, unit in tuple(claims):
        value = Decimal(number)
        if value == value.to_integral_value():
            continue
        if unit in {"원", "억", "백만원"} or (
            unit in {"%", "%p"}
            and abs(value) >= Decimal(LLM_NUMERIC_WHOLE_ROUNDING_MIN_PERCENT)
        ):
            rounded = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            claims.add((_canonical_number(str(rounded)), unit))
    return claims


def unsupported_factual_numbers(
    data: Any,
    payload: dict[str, Any],
    *,
    user_message: str,
) -> list[str]:
    """입력에 같은 단위로 존재하지 않는 과거/현재 사실 숫자를 반환한다."""
    allowed = _input_number_claims(data, user_message=user_message)
    factual_text = [
        text
        for path in FACTUAL_PATHS
        for text in strings_in(_at_path(payload, path))
    ]
    unsupported = sorted(_number_claims(factual_text) - allowed)
    return [f"{number}{unit}" for number, unit in unsupported]
