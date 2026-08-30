# PRD Ref: §7.2, §7.3, §7.4
"""LLM 분석 payload의 결정론적 재귀 스키마·내용 검증."""

from __future__ import annotations

from typing import Any

from src.analysis.prompts import ANALYSIS_SCHEMA


_PLACEHOLDER_LITERALS = frozenset({"placeholder"})


def _resolve_ref(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not ref.startswith("#/"):
        raise ValueError(f"지원하지 않는 schema ref: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def schema_problems(
    value: Any,
    schema: dict[str, Any] | None = None,
    *,
    root: dict[str, Any] | None = None,
    path: str = "$",
) -> list[str]:
    """타입·required·enum·추가 필드와 명백한 filler를 재귀 검증한다."""
    root = root or ANALYSIS_SCHEMA
    schema = _resolve_ref(schema or root, root)
    expected = schema.get("type")
    valid_type = {
        "object": lambda v: isinstance(v, dict),
        "array": lambda v: isinstance(v, list),
        "string": lambda v: isinstance(v, str),
        "boolean": lambda v: isinstance(v, bool),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    }.get(expected)
    if valid_type and not valid_type(value):
        return [f"{path}: expected {expected}, got {type(value).__name__}"]

    problems: list[str] = []
    if isinstance(value, str) and value.strip().casefold() in _PLACEHOLDER_LITERALS:
        problems.append(f"placeholder:{path}")
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} not in enum")

    if expected == "object" and isinstance(value, dict):
        properties = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value:
                problems.append(f"{path}.{key}: missing")
            elif value[key] in (None, "", [], {}):
                problems.append(f"{path}.{key}: empty")
        if schema.get("additionalProperties") is False:
            for key in value.keys() - properties.keys():
                problems.append(f"{path}.{key}: additional property")
        for key, child in value.items():
            if key in properties:
                problems.extend(
                    schema_problems(child, properties[key], root=root, path=f"{path}.{key}")
                )
    elif expected == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                problems.extend(
                    schema_problems(item, item_schema, root=root, path=f"{path}[{index}]")
                )
    return problems
