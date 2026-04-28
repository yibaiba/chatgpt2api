from __future__ import annotations

import hashlib
import re
import time
import uuid

from fastapi import HTTPException


SUPPORTED_TEXT_MODELS = (
    "auto",
    "gpt-4.1",
    "gpt-5",
)
SUPPORTED_IMAGE_MODELS = (
    "gpt-image-1",
    "gpt-image-2",
    "gpt-image-think",
)
SUPPORTED_API_MODELS = tuple(dict.fromkeys((*SUPPORTED_TEXT_MODELS, *SUPPORTED_IMAGE_MODELS)))
IMAGE_MODELS = set(SUPPORTED_IMAGE_MODELS)
TEXT_BLOCK_TYPES = {"text", "input_text", "output_text"}
ASPECT_RATIO_PREFIX_RE = re.compile(r"^\s*Make the aspect ratio\s+\S+\s*,\s*", re.IGNORECASE)


def anonymize_token(token: object) -> str:
    value = str(token or "").strip()
    if not value:
        return "token:empty"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"token:{digest}"


def is_image_chat_request(body: dict[str, object]) -> bool:
    model = str(body.get("model") or "").strip()
    modalities = body.get("modalities")
    if model in IMAGE_MODELS:
        return True
    if isinstance(modalities, list):
        normalized = {str(item or "").strip().lower() for item in modalities}
        return "image" in normalized
    return False


def _join_text_parts(parts: list[str]) -> str:
    return "\n".join(part for part in parts if part).strip()


def _extract_text_block_text(item: dict[str, object]) -> str:
    item_type = str(item.get("type") or "").strip()
    if item_type not in TEXT_BLOCK_TYPES:
        return ""
    return str(item.get("text") or item.get(item_type) or "").strip()


def strip_assistant_history_prefix(text: object, history_text: object) -> str:
    normalized_text = str(text or "").strip()
    normalized_history = str(history_text or "").strip()
    while normalized_history and normalized_text.startswith(normalized_history):
        normalized_text = normalized_text[len(normalized_history):].lstrip()
    return normalized_text


def extract_assistant_history_messages(messages: object) -> list[str]:
    if isinstance(messages, dict):
        messages = [messages]
    if not isinstance(messages, list):
        return []
    if not any(isinstance(item, dict) and "role" in item for item in messages):
        history = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").strip() != "output_text":
                continue
            text = _extract_text_block_text(item)
            if text:
                history.append(text)
        return history

    history = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").strip().lower() != "assistant":
            continue
        text = extract_prompt_from_message_content(message.get("content"))
        if text:
            history.append(text)
    return history


def extract_assistant_history_text(messages: object) -> str:
    return "".join(extract_assistant_history_messages(messages))


def extract_response_prompt(input_value: object) -> str:
    if isinstance(input_value, str):
        return input_value.strip()

    if isinstance(input_value, dict):
        role = str(input_value.get("role") or "").strip().lower()
        if role and role != "user":
            return ""
        return extract_prompt_from_message_content(input_value.get("content"))

    if not isinstance(input_value, list):
        return ""

    prompt_parts: list[str] = []
    assistant_history_parts: list[str] = []
    for item in input_value:
        if not isinstance(item, dict):
            continue
        if "type" in item and "content" not in item and "role" not in item:
            text = _extract_text_block_text(item)
            if text:
                if str(item.get("type") or "").strip() == "output_text":
                    assistant_history_parts.append(text)
                else:
                    prompt_parts.append(
                        strip_assistant_history_prefix(text, _join_text_parts(assistant_history_parts))
                    )
            continue
        role = str(item.get("role") or "").strip().lower()
        prompt = extract_prompt_from_message_content(item.get("content"))
        if role == "assistant":
            if prompt:
                assistant_history_parts.append(prompt)
            continue
        if role and role != "user":
            continue
        prompt = strip_assistant_history_prefix(prompt, _join_text_parts(assistant_history_parts))
        if prompt:
            prompt_parts.append(prompt)
    return _join_text_parts(prompt_parts)


def has_response_image_generation_tool(body: dict[str, object]) -> bool:
    tools = body.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict) and str(tool.get("type") or "").strip() == "image_generation":
                return True

    tool_choice = body.get("tool_choice")
    if isinstance(tool_choice, dict) and str(tool_choice.get("type") or "").strip() == "image_generation":
        return True
    return False


def extract_prompt_from_message_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = _extract_text_block_text(item)
        if text:
            parts.append(text)
    return _join_text_parts(parts)


def apply_image_size_prompt(prompt: object, size: object) -> str:
    normalized_prompt = str(prompt or "").strip()
    normalized_size = str(size or "").strip()
    if not normalized_size:
        return normalized_prompt

    prefix = f"Make the aspect ratio {normalized_size} , "
    if not normalized_prompt:
        return prefix.strip()

    lines = normalized_prompt.splitlines()
    if lines and ASPECT_RATIO_PREFIX_RE.match(lines[0]):
        lines[0] = ASPECT_RATIO_PREFIX_RE.sub(prefix, lines[0], count=1)
        return "\n".join(lines).strip()
    return f"{prefix}{normalized_prompt}"


def extract_image_from_message_content(content: object) -> list[tuple[bytes, str]]:
    import base64 as b64

    if not isinstance(content, list):
        return []

    images: list[tuple[bytes, str]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip()
        if item_type == "image_url":
            url_obj = item.get("image_url") or item
            url = str(url_obj.get("url") or "") if isinstance(url_obj, dict) else str(url_obj)
            if url.startswith("data:"):
                header, _, data = url.partition(",")
                mime = header.split(";")[0].removeprefix("data:")
                images.append((b64.b64decode(data), mime or "image/png"))
        elif item_type == "input_image":
            image_url = str(item.get("image_url") or "")
            if image_url.startswith("data:"):
                header, _, data = image_url.partition(",")
                mime = header.split(";")[0].removeprefix("data:")
                images.append((b64.b64decode(data), mime or "image/png"))
    return images


def extract_chat_image(body: dict[str, object]) -> list[tuple[bytes, str]]:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return []

    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role != "user":
            continue
        images = extract_image_from_message_content(message.get("content"))
        if images:
            return images
    return []


def extract_chat_prompt(body: dict[str, object]) -> str:
    direct_prompt = str(body.get("prompt") or "").strip()
    if direct_prompt:
        return direct_prompt

    messages = body.get("messages")
    if not isinstance(messages, list):
        return ""

    prompt_parts: list[str] = []
    assistant_history_parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        prompt = extract_prompt_from_message_content(message.get("content"))
        if role == "assistant":
            if prompt:
                assistant_history_parts.append(prompt)
            continue
        if role != "user":
            continue
        prompt = strip_assistant_history_prefix(prompt, _join_text_parts(assistant_history_parts))
        if prompt:
            prompt_parts.append(prompt)

    return _join_text_parts(prompt_parts)


def parse_image_count(raw_value: object) -> int:
    try:
        value = int(raw_value or 1)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"error": "n must be an integer"}) from exc
    if value < 1 or value > 4:
        raise HTTPException(status_code=400, detail={"error": "n must be between 1 and 4"})
    return value


def build_chat_image_completion(
    model: str,
    prompt: str,
    image_result: dict[str, object],
) -> dict[str, object]:
    created = int(image_result.get("created") or time.time())
    image_items = image_result.get("data") if isinstance(image_result.get("data"), list) else []

    markdown_images = []

    for index, item in enumerate(image_items, start=1):
        if not isinstance(item, dict):
            continue
        b64_json = str(item.get("b64_json") or "").strip()
        if not b64_json:
            continue
        mime_type = str(item.get("mime_type") or "image/png").strip() or "image/png"
        image_data_url = f"data:{mime_type};base64,{b64_json}"
        markdown_images.append(f"![image_{index}]({image_data_url})")

    text_content = "\n\n".join(markdown_images) if markdown_images else "Image generation completed."

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text_content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
