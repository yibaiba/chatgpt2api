from __future__ import annotations

from dataclasses import dataclass
import hashlib
from math import gcd
import re
import time
import uuid

from fastapi import HTTPException


SUPPORTED_TEXT_MODELS = (
    "auto",
    "gpt-4.1",
    "gpt-5",
)
CODEX_IMAGE_MODEL = "codex-gpt-image-2"
SUPPORTED_IMAGE_MODELS = (
    "gpt-image-1",
    "gpt-image-2",
    CODEX_IMAGE_MODEL,
    "gpt-image-think",
)
SUPPORTED_API_MODELS = tuple(dict.fromkeys((*SUPPORTED_TEXT_MODELS, *SUPPORTED_IMAGE_MODELS)))
IMAGE_MODELS = set(SUPPORTED_IMAGE_MODELS)
TEXT_BLOCK_TYPES = {"text", "input_text", "output_text"}
ASPECT_RATIO_PREFIX_RE = re.compile(r"^\s*Make the aspect ratio\s+\S+\s*,\s*", re.IGNORECASE)
IMAGE_SIZE_RE = re.compile(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$")
IMAGE_RATIO_RE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")
BLOCKED_PROMPT_ERROR_PREFIX = "prompt contains blocked word"
BLOCKED_RESPONSE_ERROR_PREFIX = "response contains blocked word"
SUPPORTED_IMAGE_QUALITIES = {"auto", "low", "medium", "high"}
SUPPORTED_IMAGE_BACKGROUNDS = {"auto", "transparent", "opaque"}
SUPPORTED_IMAGE_OUTPUT_FORMATS = {"png", "jpeg", "webp"}
MAX_IMAGE_EDGE = 3840
MIN_IMAGE_PIXELS = 655_360
MAX_IMAGE_PIXELS = 8_294_400
MAX_IMAGE_ASPECT_RATIO = 3.0


@dataclass(frozen=True)
class ImageRequestOptions:
    size: str | None = None
    quality: str = "auto"
    background: str = "auto"
    output_format: str = "png"
    compression: int | None = None


def anonymize_token(token: object) -> str:
    value = str(token or "").strip()
    if not value:
        return "token:empty"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"token:{digest}"


def is_codex_image_model(model: object) -> bool:
    return str(model or "").strip() == CODEX_IMAGE_MODEL


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


def _validate_ratio(width: int, height: int, *, field_name: str) -> None:
    if width <= 0 or height <= 0:
        raise ValueError(f"{field_name} values must be positive")
    ratio = max(width / height, height / width)
    if ratio > MAX_IMAGE_ASPECT_RATIO:
        raise ValueError(f"{field_name} aspect ratio must be at most 3:1")


def simplify_image_ratio(width: int, height: int) -> str:
    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def normalize_image_size(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized == "auto":
        return "auto"

    ratio_match = IMAGE_RATIO_RE.match(normalized)
    if ratio_match:
        width = int(ratio_match.group(1))
        height = int(ratio_match.group(2))
        _validate_ratio(width, height, field_name="size")
        return simplify_image_ratio(width, height)

    size_match = IMAGE_SIZE_RE.match(normalized)
    if not size_match:
        raise ValueError("size must be auto, WIDTHxHEIGHT, or WIDTH:HEIGHT")

    width = int(size_match.group(1))
    height = int(size_match.group(2))
    if width % 16 != 0 or height % 16 != 0:
        raise ValueError("size width and height must both be multiples of 16")
    if width > MAX_IMAGE_EDGE or height > MAX_IMAGE_EDGE:
        raise ValueError(f"size width and height must be at most {MAX_IMAGE_EDGE}")
    _validate_ratio(width, height, field_name="size")
    pixels = width * height
    if pixels < MIN_IMAGE_PIXELS or pixels > MAX_IMAGE_PIXELS:
        raise ValueError(
            f"size pixel count must be between {MIN_IMAGE_PIXELS} and {MAX_IMAGE_PIXELS}"
        )
    return f"{width}x{height}"


def parse_exact_image_size(size: object) -> tuple[int, int] | None:
    normalized = normalize_image_size(size)
    if not normalized or normalized == "auto" or ":" in normalized:
        return None
    matched = IMAGE_SIZE_RE.match(normalized)
    if not matched:
        return None
    return int(matched.group(1)), int(matched.group(2))


def normalize_image_quality(value: object) -> str:
    normalized = str(value or "auto").strip().lower() or "auto"
    if normalized not in SUPPORTED_IMAGE_QUALITIES:
        raise ValueError("quality must be one of auto, low, medium, high")
    return normalized


def normalize_image_background(value: object, model: object) -> str:
    normalized = str(value or "auto").strip().lower() or "auto"
    if normalized not in SUPPORTED_IMAGE_BACKGROUNDS:
        raise ValueError("background must be one of auto, transparent, opaque")
    normalized_model = str(model or "").strip()
    if normalized == "transparent" and normalized_model in {"gpt-image-2", "gpt-image-think", CODEX_IMAGE_MODEL, "gpt-image"}:
        raise ValueError(f"{normalized_model or 'this model'} does not support transparent background")
    return normalized


def normalize_image_output_format(value: object) -> str:
    normalized = str(value or "png").strip().lower() or "png"
    if normalized not in SUPPORTED_IMAGE_OUTPUT_FORMATS:
        raise ValueError("output_format must be one of png, jpeg, webp")
    return normalized


def normalize_image_compression(value: object, *, output_format: str) -> int | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        compression = int(normalized)
    except (TypeError, ValueError) as exc:
        raise ValueError("compression must be an integer between 0 and 100") from exc
    if output_format == "png":
        raise ValueError("compression is only supported for jpeg and webp output")
    if compression < 0 or compression > 100:
        raise ValueError("compression must be an integer between 0 and 100")
    return compression


def build_image_request_options(
    *,
    model: object,
    size: object = None,
    quality: object = None,
    background: object = None,
    output_format: object = None,
    compression: object = None,
) -> ImageRequestOptions:
    codex_model = is_codex_image_model(model)
    normalized_size = normalize_image_size(size)
    normalized_quality = normalize_image_quality(quality)
    normalized_background = normalize_image_background(background, model)
    normalized_output_format = normalize_image_output_format(output_format)
    normalized_compression = normalize_image_compression(compression, output_format=normalized_output_format)
    if not codex_model:
        if normalized_size and "x" in normalized_size:
            raise ValueError(f"exact WIDTHxHEIGHT size is only supported for {CODEX_IMAGE_MODEL}")
        if normalized_quality != "auto":
            raise ValueError(f"quality is only supported for {CODEX_IMAGE_MODEL}")
        if normalized_background != "auto":
            raise ValueError(f"background is only supported for {CODEX_IMAGE_MODEL}")
        if normalized_output_format != "png":
            raise ValueError(f"output_format is only supported for {CODEX_IMAGE_MODEL}")
        if normalized_compression is not None:
            raise ValueError(f"compression is only supported for {CODEX_IMAGE_MODEL}")
    return ImageRequestOptions(
        size=normalized_size,
        quality=normalized_quality,
        background=normalized_background,
        output_format=normalized_output_format,
        compression=normalized_compression,
    )


def build_image_prompt(prompt: object, options: ImageRequestOptions | None = None) -> str:
    normalized_prompt = str(prompt or "").strip()
    if options is None:
        return normalized_prompt

    next_prompt = normalized_prompt
    exact_size = parse_exact_image_size(options.size)
    if exact_size is not None:
        width, height = exact_size
        next_prompt = apply_image_size_prompt(next_prompt, simplify_image_ratio(width, height))
        resolution_hint = f"Render at {width}x{height} resolution."
        next_prompt = f"{resolution_hint}\n{next_prompt}".strip()
    elif options.size and options.size != "auto":
        next_prompt = apply_image_size_prompt(next_prompt, options.size)

    hints: list[str] = []
    if options.quality != "auto":
        hints.append(f"Use {options.quality} image quality.")
    if options.background == "transparent":
        hints.append("Use a transparent background.")
    elif options.background == "opaque":
        hints.append("Use an opaque background.")

    if not hints:
        return next_prompt
    if not next_prompt:
        return "\n".join(hints)
    return "\n".join([*hints, next_prompt]).strip()


def find_sensitive_word(text: object, sensitive_words: object) -> str | None:
    normalized_text = str(text or "").casefold()
    if not normalized_text or not isinstance(sensitive_words, (list, tuple, set)):
        return None
    for item in sensitive_words:
        word = str(item or "").strip()
        if word and word.casefold() in normalized_text:
            return word
    return None


def find_sensitive_word_match(text: object, sensitive_words: object) -> tuple[str, int, int] | None:
    normalized_text = str(text or "")
    if not normalized_text or not isinstance(sensitive_words, (list, tuple, set)):
        return None
    best_match: tuple[str, int, int] | None = None
    for item in sensitive_words:
        word = str(item or "").strip()
        if not word:
            continue
        match = re.search(re.escape(word), normalized_text, flags=re.IGNORECASE)
        if not match:
            continue
        start, end = match.span()
        if best_match is None or start < best_match[1]:
            best_match = (word, start, end)
    return best_match


def ensure_text_not_blocked(
    text: object,
    *,
    enabled: bool,
    sensitive_words: object,
    error_prefix: str = BLOCKED_PROMPT_ERROR_PREFIX,
) -> None:
    if not enabled:
        return
    blocked_word = find_sensitive_word(text, sensitive_words)
    if not blocked_word:
        return
    raise HTTPException(
        status_code=400,
        detail={"error": f"{error_prefix}: {blocked_word}"},
    )


def ensure_prompt_not_blocked(prompt: object, *, enabled: bool, sensitive_words: object) -> None:
    ensure_text_not_blocked(
        prompt,
        enabled=enabled,
        sensitive_words=sensitive_words,
        error_prefix=BLOCKED_PROMPT_ERROR_PREFIX,
    )


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

    all_images: list[tuple[bytes, str]] = []
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role != "user":
            continue
        images = extract_image_from_message_content(message.get("content"))
        if images:
            all_images.extend(images)
    return all_images


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
