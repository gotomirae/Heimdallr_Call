# PRD Ref: §7 전체 · ADR 3, 4 · traps.md T9, T34, T91, T96
"""기존 Anthropic 분석 동작을 보존하는 Provider Adapter."""

from __future__ import annotations

import json

from src.llm.provider import LLMRequest, LLMResponse, NormalizedUsage
from src.utils.env import require_env


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client=None, *, max_retries: int | None = None):
        self._provided_client = client
        self._max_retries = max_retries

    def _client(self):
        if self._provided_client is not None:
            return self._provided_client
        import anthropic

        kwargs = {"api_key": require_env("ANTHROPIC_API_KEY")}
        if self._max_retries is not None:
            kwargs["max_retries"] = self._max_retries
        return anthropic.Anthropic(**kwargs)

    @staticmethod
    def _section_transport(request: LLMRequest) -> bool:
        # Dashboard's mandatory value-chain schema exceeded the provider grammar
        # compiler despite having no optional fields. Keep the canonical contract.
        return "value_chain" in request.schema.get("required", [])

    @staticmethod
    def _flat_properties(request: LLMRequest) -> dict:
        properties = {}

        def walk(spec, path, repeated=False):
            if "$ref" in spec:
                spec = request.schema["$defs"][spec["$ref"].split("/")[-1]]
            if spec.get("type") == "object":
                for key, child in spec["properties"].items():
                    walk(child, (*path, key), repeated)
            elif spec.get("type") == "array":
                if repeated:
                    raise ValueError("Nested repeated transport is unsupported")
                walk(spec["items"], path, True)
            else:
                primitive = {k: v for k, v in spec.items() if k != "description"}
                properties["__".join(path)] = (
                    {"type": "array", "items": primitive} if repeated else primitive
                )

        walk(request.schema, ())
        return properties

    @staticmethod
    def _restore_flat(request: LLMRequest, payload: dict) -> dict:
        fields = AnthropicProvider._flat_properties(request)
        if not isinstance(payload, dict) or set(payload) != set(fields):
            raise ValueError("flat transport keys differ from canonical contract")

        def restore(spec, path, index=None):
            if "$ref" in spec:
                spec = request.schema["$defs"][spec["$ref"].split("/")[-1]]
            if spec.get("type") == "object":
                return {key: restore(child, (*path, key), index)
                        for key, child in spec["properties"].items()}
            if spec.get("type") == "array":
                prefix = "__".join(path)
                keys = [key for key in fields if key == prefix or key.startswith(prefix + "__")]
                if any(not isinstance(payload[key], list) for key in keys):
                    raise ValueError(f"{prefix}: expected parallel arrays")
                lengths = {len(payload[key]) for key in keys}
                if len(lengths) != 1:
                    raise ValueError(f"{prefix}: parallel array lengths differ")
                return [restore(spec["items"], path, i) for i in range(next(iter(lengths)))]
            value = payload["__".join(path)]
            return value if index is None else value[index]

        return restore(request.schema, ())

    @staticmethod
    def _restore_cells(request: LLMRequest, payload: dict) -> dict:
        names = ("paths", "indices", "texts", "numbers", "booleans")
        if not isinstance(payload, dict) or set(payload) != {"cells", "confidence"} or not isinstance(payload["cells"], list):
            raise ValueError("cell transport keys differ")
        columns = {name: [] for name in names}
        for cell in payload["cells"]:
            if not isinstance(cell, dict) or set(cell) != {"path", "index", "text", "number", "boolean"}:
                raise ValueError("cell transport field mismatch")
            for name, key in zip(names, ("path", "index", "text", "number", "boolean")):
                columns[name].append(cell[key])
        specs = AnthropicProvider._flat_properties(request)
        cells = {}
        for path, index, text, number, flag in zip(*(columns[name] for name in names)):
            if path not in specs or type(index) is not int or index < -1:
                raise ValueError(f"invalid path/index: {path}")
            spec = specs[path]
            repeated = spec["type"] == "array"
            if not repeated and index != -1:
                raise ValueError(f"{path}: scalar index must be -1")
            cell = cells.setdefault(path, {})
            if index in cell:
                raise ValueError(f"{path}: duplicate index {index}")
            if repeated and index == -1:
                cell[index] = None  # Explicit empty-list marker, never a report value.
                continue
            kind = (spec["items"] if repeated else spec)["type"]
            value = {"string": text, "boolean": flag, "number": number,
                     "integer": number}.get(kind)
            if kind == "integer":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
                    raise ValueError(f"{path}: non-integral integer")
                value = int(value)
            cell[index] = value
        # The strict top-level enum is sufficient; do not require a redundant cell.
        cells.setdefault("earnings_change__confidence", {-1: payload["confidence"]})
        if set(cells) != set(specs):
            raise ValueError("column transport omitted required paths")
        flat = {}
        for path, cell in cells.items():
            if specs[path]["type"] != "array":
                flat[path] = cell[-1]
            elif -1 in cell:
                if len(cell) != 1:
                    raise ValueError(f"{path}: empty marker mixed with values")
                flat[path] = []
            else:
                if set(cell) != set(range(len(cell))):
                    raise ValueError(f"{path}: non-contiguous indices")
                flat[path] = [cell[index] for index in range(len(cell))]
        confidence = payload["confidence"]
        if confidence not in ("high", "medium", "low"):
            raise ValueError("invalid confidence enum")
        if flat["earnings_change__confidence"] not in ("", confidence):
            raise ValueError("conflicting confidence cells")
        flat["earnings_change__confidence"] = confidence
        return AnthropicProvider._restore_flat(request, flat)

    @staticmethod
    def _analysis_tool(request: LLMRequest) -> dict:
        schema = request.schema
        description = "분석 결과를 구조화해 기록한다. 반드시 이 도구로만 응답한다."
        if AnthropicProvider._section_transport(request):
            # A repeated five-field cell avoids large object grammars and JSON strings.
            description += (
                " 필드명 __는 원래 분석의 중첩 경로이다. 예: earnings_change__cause는 "
                "실적 변화 원인이고 value_chain 경로는 산업 내 밸류체인이다. 같은 목록 경로의 배열들은 길이를 같게 하고 "
                "같은 인덱스끼리 하나의 항목으로 대응시킨다. 예: risks__risk와 "
                "risks__watch_metric의 첫 값은 같은 위험을 설명한다. 확인 가능한 "
                "글로벌 이벤트가 없으면 recent_global_events의 모든 배열을 비운다. "
                "숫자/불리언/배열은 해당 타입 그대로 작성하며 JSON 문자열로 감싸지 않는다. "
                "근거 없는 숫자나 누락 항목을 만들어 채우지 않는다."
            )
            properties = AnthropicProvider._flat_properties(request)
            properties.pop("earnings_change__confidence")
            description += (
                " 전송은 cells 배열이고 각 셀은 path/index/text/number/boolean 필드를 가진다. "
                "모든 경로를 반드시 포함한다. 스칼라 셀 index=-1, 목록은 0부터 연속 인덱스, "
                "빈 목록은 -1 셀 하나이다. 해당 타입 필드만 실제 값을 담고 사용하지 않는 "
                "필드는 text='', number=0, boolean=false로 둔다. 이는 전송용 자리표시자이며 보고서 수치가 아니다. "
                "confidence는 반드시 high/medium/low 중 하나이며 earnings_change의 신뢰도와 같다. "
                "경로별 원래 타입/허용값: "
                + json.dumps(properties, ensure_ascii=False, separators=(",", ":"))
            )
            fields = {
                "path": {"type": "string", "enum": list(properties)},
                "index": {"type": "integer"}, "text": {"type": "string"},
                "number": {"type": "number"}, "boolean": {"type": "boolean"},
            }
            schema = {
                "type": "object", "additionalProperties": False,
                "required": ["cells", "confidence"], "properties": {"confidence": {
                    "type": "string", "enum": ["high", "medium", "low"],
                }, "cells": {
                    "type": "array", "items": {"type": "object", "additionalProperties": False,
                                                "required": list(fields), "properties": fields},
                }},
            }
        return {
            "name": request.schema_name,
            "description": description,
            "input_schema": schema,
            "strict": True,
        }

    @staticmethod
    def _web_search_tool(request: LLMRequest) -> dict:
        return {
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": request.web_search_max_uses,
            "allowed_domains": list(request.web_search_allowed_domains),
        }

    def _tools(self, request: LLMRequest) -> list[dict]:
        tools = [self._analysis_tool(request)]
        if request.web_search:
            tools.append(self._web_search_tool(request))
        return tools

    def count_input_tokens(self, request: LLMRequest) -> int:
        response = self._client().messages.count_tokens(
            model=request.model,
            system=[{"type": "text", "text": request.system_prompt}],
            messages=[{"role": "user", "content": request.user_message}],
            tools=self._tools(request),
        )
        return int(response.input_tokens)

    def generate_structured(self, request: LLMRequest) -> LLMResponse:
        kwargs = {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "system": [
                {
                    "type": "text",
                    "text": request.system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": request.effort or "low"},
            "tools": self._tools(request),
            # 강제 tool_choice와 서버 웹 검색은 함께 동작하지 않는다(T96).
            "tool_choice": (
                {"type": "auto"}
                if request.web_search
                else {"type": "tool", "name": request.schema_name}
            ),
            "messages": [{"role": "user", "content": request.user_message}],
        }
        response = self._client().messages.create(**kwargs)
        payload = next(
            (
                block.input
                for block in response.content
                if getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == request.schema_name
            ),
            None,
        )
        parse_error = None
        if payload is not None and self._section_transport(request):
            try:
                payload = self._restore_cells(request, payload)
            except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
                # Never lose paid response usage when decoding fails.
                payload = None
                parse_error = f"section transport decode failed: {exc}"
        usage = response.usage
        server_tool_use = getattr(usage, "server_tool_use", None)
        if isinstance(server_tool_use, dict):
            web_search_requests = int(server_tool_use.get("web_search_requests", 0) or 0)
        else:
            web_search_requests = int(
                getattr(server_tool_use, "web_search_requests", 0) or 0
            )
        source_urls: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) != "web_search_tool_result":
                continue
            content = getattr(block, "content", None)
            # 서버 검색 오류일 때 content는 결과 배열이 아니라 오류 객체다.
            # 유료 응답을 받은 뒤 Adapter가 TypeError로 죽지 않게 결과 배열만 순회한다.
            items = content if isinstance(content, (list, tuple)) else ()
            for item in items:
                url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
                if isinstance(url, str) and url.startswith(("https://", "http://")):
                    source_urls.append(url)
        return LLMResponse(
            provider=self.name,
            model=str(getattr(response, "model", None) or request.model),
            payload=payload,
            parse_error=parse_error,
            stop_reason=getattr(response, "stop_reason", None),
            response_id=getattr(response, "id", None),
            usage=NormalizedUsage(
                input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                cache_write_tokens=int(
                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                ),
                cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                web_search_requests=web_search_requests,
            ),
            source_urls=tuple(dict.fromkeys(source_urls)),
        )
