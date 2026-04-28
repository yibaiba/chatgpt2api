from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Iterator

TOOL_MARKUP_RE = re.compile(r"(?is)<tool_calls\b|<tool_call\b|<function_call\b|<invoke\b")


def strip_tool_markup(text: str) -> str:
    return re.sub(
        r"(?is)<tool_calls\b[^>]*>.*?</tool_calls>|<tool_call\b[^>]*>.*?</tool_call>|<function_call\b[^>]*>.*?</function_call>|<invoke\b[^>]*>.*?</invoke>",
        "",
        text or "",
    ).strip()


def streamable_text(text: str) -> str:
    normalized_text = str(text or "")
    match = TOOL_MARKUP_RE.search(normalized_text)
    if not match:
        return normalized_text
    return normalized_text[: match.start()].rstrip()


def _xml_value(text: str, tag: str) -> str:
    match = re.search(rf"(?is)<{tag}\b[^>]*>(.*?)</{tag}>", text)
    if not match:
        return ""
    return str(match.group(1) or "").strip()


def _parse_tool_params(raw: str) -> dict[str, object]:
    normalized_raw = str(raw or "").strip()
    if not normalized_raw:
        return {}
    try:
        parsed = json.loads(normalized_raw)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_tool_calls(text: str) -> list[tuple[str, dict[str, object]]]:
    matches = re.finditer(r"(?is)<tool_call\b[^>]*>(.*?)</tool_call>", text or "")
    calls: list[tuple[str, dict[str, object]]] = []
    for match in matches:
        block = str(match.group(1) or "")
        name = _xml_value(block, "tool_name") or _xml_value(block, "name")
        if not name:
            continue
        params = _parse_tool_params(_xml_value(block, "parameters") or _xml_value(block, "input"))
        calls.append((name, params))
    return calls


def content_blocks(text: str, tools: object = None) -> tuple[list[dict[str, object]], str]:
    normalized_text = str(text or "").strip()
    calls = parse_tool_calls(normalized_text) if isinstance(tools, list) and tools else []
    visible_text = strip_tool_markup(normalized_text)
    content: list[dict[str, object]] = []
    if visible_text:
        content.append({"type": "text", "text": visible_text})
    if calls:
        content.extend(
            {
                "type": "tool_use",
                "id": f"toolu_{uuid.uuid4().hex}",
                "name": name,
                "input": params,
            }
            for name, params in calls
        )
        return content, "tool_use"
    return content or [{"type": "text", "text": visible_text}], "end_turn"


def message_response(
    model: str,
    text: str,
    usage: dict[str, int],
    tools: object = None,
) -> dict[str, object]:
    content, stop_reason = content_blocks(text, tools)
    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage,
    }


def stream_events(
    text_snapshots: Iterable[str],
    model: str,
    usage: dict[str, int],
    tools: object = None,
) -> Iterator[tuple[str, dict[str, object]]]:
    message_id = f"msg_{uuid.uuid4().hex}"
    current_text = ""
    streamed_text = ""
    tool_mode = isinstance(tools, list) and bool(tools)
    text_open = not tool_mode
    yield (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": usage,
            },
        },
    )
    if text_open:
        yield (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        )
    for snapshot in text_snapshots:
        next_text = str(snapshot or "")
        if not next_text or next_text == current_text:
            continue
        visible_text = streamable_text(next_text) if tool_mode else next_text
        delta = visible_text[len(streamed_text):] if visible_text.startswith(streamed_text) else visible_text
        current_text = next_text
        if not delta:
            continue
        if not text_open:
            text_open = True
            yield (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            )
        streamed_text = visible_text
        yield (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": delta},
            },
        )
    content, stop_reason = content_blocks(current_text, tools)
    text_block = content[0] if content and content[0].get("type") == "text" else None
    if text_block and len(str(text_block.get("text") or "")) > len(streamed_text):
        remaining = str(text_block.get("text") or "")[len(streamed_text):]
        if remaining:
            if not text_open:
                text_open = True
                yield (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
            yield (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": remaining},
                },
            )
    if text_open:
        yield (
            "content_block_stop",
            {
                "type": "content_block_stop",
                "index": 0,
            },
        )
    buffered_blocks = content[1:] if text_block else content
    start_index = 1 if text_open and text_block else 0
    for offset, block in enumerate(buffered_blocks):
        if block.get("type") != "tool_use":
            continue
        index = start_index + offset
        yield (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": {
                    "type": "tool_use",
                    "id": str(block.get("id") or ""),
                    "name": str(block.get("name") or ""),
                    "input": {},
                },
            },
        )
        yield (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": index,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": json.dumps(block.get("input") or {}, ensure_ascii=False),
                },
            },
        )
        yield (
            "content_block_stop",
            {
                "type": "content_block_stop",
                "index": index,
            },
        )
    yield (
        "message_delta",
        {
            "type": "message_delta",
            "delta": {
                "stop_reason": stop_reason,
                "stop_sequence": None,
            },
            "usage": usage,
        },
    )
    yield (
        "message_stop",
        {
            "type": "message_stop",
        },
    )
