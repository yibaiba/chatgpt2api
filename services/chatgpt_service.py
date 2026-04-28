from __future__ import annotations

from collections.abc import Iterable, Iterator
import json
import time
import uuid

from fastapi import HTTPException

from services.account_service import AccountService
from services.anthropic_protocol import message_response, stream_events
from services.config import config
from services.image_service import (
    ImageGenerationError,
    edit_image_result,
    generate_image_result,
    is_retryable_image_output_error,
    is_token_invalid_error,
)
from services.text_backend import TextBackend, TextBackendError
from services.utils import (
    build_chat_image_completion,
    ensure_prompt_not_blocked,
    extract_assistant_history_messages,
    extract_assistant_history_text,
    extract_chat_image,
    extract_chat_prompt,
    extract_prompt_from_message_content,
    extract_image_from_message_content,
    extract_response_prompt,
    has_response_image_generation_tool,
    is_image_chat_request,
    parse_image_count,
    strip_assistant_history_prefix,
    SUPPORTED_API_MODELS,
)


MAX_TRANSIENT_IMAGE_EDIT_RETRIES = 1


def _extract_response_images(input_value: object) -> list[tuple[bytes, str]]:
    if isinstance(input_value, dict):
        return extract_image_from_message_content(input_value.get("content"))
    if not isinstance(input_value, list):
        return []
    if not any(isinstance(item, dict) and "role" in item for item in input_value):
        return extract_image_from_message_content(input_value)
    for item in reversed(input_value):
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "").strip().lower() != "user":
            continue
        images = extract_image_from_message_content(item.get("content"))
        if images:
            return images
    return []


class ChatGPTService:
    def __init__(self, account_service: AccountService):
        self.account_service = account_service

    def _get_text_access_token(self) -> str:
        preferred_tokens: list[str] = []
        fallback_tokens: list[str] = []
        try:
            accounts = self.account_service.list_accounts()
        except Exception:
            accounts = []

        if isinstance(accounts, list):
            for account in accounts:
                if not isinstance(account, dict):
                    continue
                access_token = str(account.get("access_token") or "").strip()
                if not access_token:
                    continue
                status = str(account.get("status") or "").strip()
                if status in {"禁用", "异常"}:
                    continue
                if str(account.get("type") or "Free").strip() == "Free":
                    fallback_tokens.append(access_token)
                else:
                    preferred_tokens.append(access_token)
        token = (preferred_tokens or fallback_tokens or [""])[0]
        if token:
            return token
        try:
            tokens = self.account_service.list_tokens()
        except Exception:
            tokens = []
        token = str(tokens[0] if tokens else "").strip()
        if token:
            return token
        raise HTTPException(status_code=502, detail={"error": "no available access token"})

    @staticmethod
    def _collect_role_text(messages: object, roles: set[str]) -> str:
        if isinstance(messages, dict):
            messages = [messages]
        if not isinstance(messages, list):
            return ""
        parts: list[str] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "").strip().lower()
            if role not in roles:
                continue
            text = extract_prompt_from_message_content(message.get("content"))
            if text:
                parts.append(text)
        return "\n\n".join(parts).strip()

    @staticmethod
    def _compose_text_prompt(prompt: str, instruction_text: str = "") -> str:
        normalized_prompt = str(prompt or "").strip()
        normalized_instruction_text = str(instruction_text or "").strip()
        if not normalized_instruction_text:
            return normalized_prompt
        if not normalized_prompt:
            return ""
        return f"{normalized_instruction_text}\n\n{normalized_prompt}".strip()

    def _build_chat_text_prompt(self, body: dict[str, object]) -> str:
        prompt = extract_chat_prompt(body)
        instruction_text = self._collect_role_text(body.get("messages"), {"system", "developer"})
        return self._compose_text_prompt(prompt, instruction_text)

    def _build_response_text_prompt(self, body: dict[str, object]) -> str:
        instruction_parts = [str(body.get("instructions") or "").strip()]
        instruction_parts.append(self._collect_role_text(body.get("input"), {"system", "developer"}))
        instruction_text = "\n\n".join(part for part in instruction_parts if part).strip()
        prompt = extract_response_prompt(body.get("input"))
        return self._compose_text_prompt(prompt, instruction_text)

    def _build_message_text_prompt(self, body: dict[str, object]) -> str:
        instruction_text = extract_prompt_from_message_content(body.get("system"))
        prompt = extract_response_prompt(body.get("messages"))
        return self._compose_text_prompt(prompt, instruction_text)

    @staticmethod
    def _strip_history_from_text(text: str, history_source: object) -> str:
        return strip_assistant_history_prefix(text, extract_assistant_history_text(history_source))

    @staticmethod
    def _normalize_stream_snapshot(
        text: str,
        history_messages: list[str],
        consumed_count: int,
    ) -> tuple[str, int]:
        normalized_text = str(text or "")
        history_prefix = "".join(history_messages[:consumed_count])
        while consumed_count < len(history_messages):
            next_prefix = history_prefix + history_messages[consumed_count]
            if not normalized_text.startswith(next_prefix):
                break
            history_prefix = next_prefix
            consumed_count += 1
            if normalized_text == history_prefix:
                normalized_text = ""
                break
        if history_prefix:
            normalized_text = strip_assistant_history_prefix(normalized_text, history_prefix)
        return normalized_text, consumed_count

    def _normalized_stream_snapshots(
        self,
        backend_stream: Iterator[dict[str, object]],
        history_source: object,
    ) -> Iterator[str]:
        history_messages = extract_assistant_history_messages(history_source)
        consumed_count = 0
        for event in backend_stream:
            normalized_text, consumed_count = self._normalize_stream_snapshot(
                str(event.get("text") or ""),
                history_messages,
                consumed_count,
            )
            yield normalized_text

    @staticmethod
    def _build_text_completion_response(model: str, backend_result: dict[str, object]) -> dict[str, object]:
        created = int(backend_result.get("created") or 0)
        text = str(backend_result.get("text") or "").strip()
        payload = {
            "id": f"chatcmpl-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": text,
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        usage = backend_result.get("usage")
        if isinstance(usage, dict):
            payload["usage"] = usage
        return payload

    @staticmethod
    def _build_text_response_payload(model: str, backend_result: dict[str, object]) -> dict[str, object]:
        created = int(backend_result.get("created") or 0)
        text = str(backend_result.get("text") or "").strip()
        payload = {
            "id": f"resp_{uuid.uuid4().hex}",
            "object": "response",
            "created_at": created,
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "model": model,
            "output": [
                {
                    "id": f"msg_{uuid.uuid4().hex}",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": text,
                            "annotations": [],
                        }
                    ],
                }
            ],
            "parallel_tool_calls": False,
        }
        usage = backend_result.get("usage")
        if isinstance(usage, dict):
            payload["usage"] = usage
        return payload

    @staticmethod
    def _build_text_completion_chunk(
        completion_id: str,
        created: int,
        model: str,
        *,
        role: str | None = None,
        content: str | None = None,
        finish_reason: str | None = None,
    ) -> dict[str, object]:
        delta: dict[str, object] = {}
        if role:
            delta["role"] = role
        if content:
            delta["content"] = content
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": finish_reason,
                }
            ],
        }

    @staticmethod
    def _encode_sse_data(payload: dict[str, object] | str) -> str:
        if isinstance(payload, str):
            return f"data: {payload}\n\n"
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _encode_named_sse(event: str, payload: dict[str, object]) -> str:
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _normalize_anthropic_usage(usage: object) -> dict[str, int]:
        if not isinstance(usage, dict):
            return {"input_tokens": 0, "output_tokens": 0}
        return {
            "input_tokens": int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
        }

    @staticmethod
    def list_models() -> list[str]:
        return list(SUPPORTED_API_MODELS)

    def _build_message_response(
        self,
        model: str,
        backend_result: dict[str, object],
        tools: object = None,
    ) -> dict[str, object]:
        text = str(backend_result.get("text") or "").strip()
        return message_response(
            model=model,
            text=text,
            usage=self._normalize_anthropic_usage(backend_result.get("usage")),
            tools=tools,
        )

    @staticmethod
    def _enforce_sensitive_word_filter(prompt: str) -> None:
        ensure_prompt_not_blocked(
            prompt,
            enabled=bool(getattr(config, "sensitive_word_filter_enabled", False)),
            sensitive_words=getattr(config, "sensitive_words", []),
        )

    def create_text_completion(self, body: dict[str, object]) -> dict[str, object]:
        if bool(body.get("stream")):
            raise HTTPException(status_code=400, detail={"error": "stream is not supported for text completions"})

        model = str(body.get("model") or "auto").strip() or "auto"
        prompt = self._build_chat_text_prompt(body)
        if not prompt:
            raise HTTPException(status_code=400, detail={"error": "messages or prompt is required"})
        self._enforce_sensitive_word_filter(prompt)

        try:
            backend_result = TextBackend(self._get_text_access_token()).complete(prompt, model)
        except TextBackendError as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        backend_result = dict(backend_result)
        backend_result["text"] = self._strip_history_from_text(str(backend_result.get("text") or ""), body.get("messages"))
        return self._build_text_completion_response(model, backend_result)

    def create_text_completion_stream(self, body: dict[str, object]) -> Iterator[str]:
        model = str(body.get("model") or "auto").strip() or "auto"
        prompt = self._build_chat_text_prompt(body)
        if not prompt:
            raise HTTPException(status_code=400, detail={"error": "messages or prompt is required"})
        self._enforce_sensitive_word_filter(prompt)

        try:
            backend_stream = TextBackend(self._get_text_access_token()).stream(prompt, model)
        except TextBackendError as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        normalized_snapshots = self._normalized_stream_snapshots(backend_stream, body.get("messages"))

        def generate() -> Iterator[str]:
            current_text = ""
            sent_role = False
            for next_text in normalized_snapshots:
                if not next_text or next_text == current_text:
                    continue
                if not sent_role:
                    sent_role = True
                    yield self._encode_sse_data(
                        self._build_text_completion_chunk(completion_id, created, model, role="assistant")
                    )
                delta = next_text[len(current_text):] if next_text.startswith(current_text) else next_text
                current_text = next_text
                if not delta:
                    continue
                yield self._encode_sse_data(
                    self._build_text_completion_chunk(completion_id, created, model, content=delta)
                )
            yield self._encode_sse_data(
                self._build_text_completion_chunk(completion_id, created, model, finish_reason="stop")
            )
            yield self._encode_sse_data("[DONE]")

        return generate()

    def create_text_response(self, body: dict[str, object]) -> dict[str, object]:
        if bool(body.get("stream")):
            raise HTTPException(status_code=400, detail={"error": "stream is not supported"})

        model = str(body.get("model") or "auto").strip() or "auto"
        prompt = self._build_response_text_prompt(body)
        if not prompt:
            raise HTTPException(status_code=400, detail={"error": "input text is required"})
        self._enforce_sensitive_word_filter(prompt)

        try:
            backend_result = TextBackend(self._get_text_access_token()).complete(prompt, model)
        except TextBackendError as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        backend_result = dict(backend_result)
        backend_result["text"] = self._strip_history_from_text(str(backend_result.get("text") or ""), body.get("input"))
        return self._build_text_response_payload(model, backend_result)

    def create_message(self, body: dict[str, object]) -> dict[str, object]:
        model = str(body.get("model") or "auto").strip() or "auto"
        prompt = self._build_message_text_prompt(body)
        if not prompt:
            raise HTTPException(status_code=400, detail={"error": "messages are required"})
        self._enforce_sensitive_word_filter(prompt)

        try:
            backend_result = TextBackend(self._get_text_access_token()).complete(prompt, model)
        except TextBackendError as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        backend_result = dict(backend_result)
        backend_result["text"] = self._strip_history_from_text(str(backend_result.get("text") or ""), body.get("messages"))
        return self._build_message_response(model, backend_result, tools=body.get("tools"))

    def stream_message(self, body: dict[str, object]) -> Iterator[str]:
        model = str(body.get("model") or "auto").strip() or "auto"
        prompt = self._build_message_text_prompt(body)
        if not prompt:
            raise HTTPException(status_code=400, detail={"error": "messages are required"})
        self._enforce_sensitive_word_filter(prompt)

        try:
            backend_stream = TextBackend(self._get_text_access_token()).stream(prompt, model)
        except TextBackendError as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

        usage = {"input_tokens": 0, "output_tokens": 0}
        normalized_snapshots = self._normalized_stream_snapshots(backend_stream, body.get("messages"))

        def generate() -> Iterator[str]:
            for event_name, payload in stream_events(normalized_snapshots, model, usage, tools=body.get("tools")):
                yield self._encode_named_sse(event_name, payload)

        return generate()

    def generate_with_pool(
        self,
        prompt: str,
        model: str,
        n: int,
        response_format: str = "b64_json",
        base_url: str | None = None,
    ):
        created = None
        image_items: list[dict[str, object]] = []
        last_error: str | None = None

        for index in range(1, n + 1):
            while True:
                try:
                    request_token = self.account_service.get_available_access_token()
                except RuntimeError as exc:
                    last_error = str(exc)
                    print(f"[image-generate] stop index={index}/{n} error={exc}")
                    break

                print(f"[image-generate] start pooled token={request_token[:12]}... model={model} index={index}/{n}")
                try:
                    result = generate_image_result(
                        request_token,
                        prompt,
                        model,
                        response_format,
                        base_url,
                    )
                    account = self.account_service.mark_image_result(request_token, success=True)
                    if created is None:
                        created = result.get("created")
                    data = result.get("data")
                    if isinstance(data, list):
                        image_items.extend(item for item in data if isinstance(item, dict))
                    print(
                        f"[image-generate] success pooled token={request_token[:12]}... "
                        f"quota={account.get('quota') if account else 'unknown'} status={account.get('status') if account else 'unknown'}"
                    )
                    break
                except ImageGenerationError as exc:
                    account = self.account_service.mark_image_result(request_token, success=False)
                    message = str(exc)
                    last_error = message
                    print(
                        f"[image-generate] fail pooled token={request_token[:12]}... "
                        f"error={message} quota={account.get('quota') if account else 'unknown'} status={account.get('status') if account else 'unknown'}"
                    )
                    if is_token_invalid_error(message):
                        self.account_service.remove_token(request_token)
                        print(f"[image-generate] remove invalid token={request_token[:12]}...")
                        continue
                    break

        if not image_items:
            raise ImageGenerationError(last_error or "image generation failed")

        return {
            "created": created,
            "data": image_items,
        }

    def edit_with_pool(
        self,
        prompt: str,
        images: Iterable[tuple[bytes, str, str]],
        model: str,
        n: int,
        response_format: str = "b64_json",
        base_url: str | None = None,
    ):
        created = None
        image_items: list[dict[str, object]] = []
        last_error: str | None = None
        normalized_images = list(images)
        if not normalized_images:
            raise ImageGenerationError("image is required")

        for index in range(1, n + 1):
            transient_retry_count = 0
            while True:
                try:
                    request_token = self.account_service.get_available_access_token()
                except RuntimeError as exc:
                    last_error = str(exc)
                    print(f"[image-edit] stop index={index}/{n} error={exc}")
                    break

                print(
                    f"[image-edit] start pooled token={request_token[:12]}... "
                    f"model={model} index={index}/{n} images={len(normalized_images)}"
                )
                try:
                    result = edit_image_result(
                        request_token,
                        prompt,
                        normalized_images,
                        model,
                        response_format,
                        base_url,
                    )
                    account = self.account_service.mark_image_result(request_token, success=True)
                    if created is None:
                        created = result.get("created")
                    data = result.get("data")
                    if isinstance(data, list):
                        image_items.extend(item for item in data if isinstance(item, dict))
                    print(
                        f"[image-edit] success pooled token={request_token[:12]}... "
                        f"quota={account.get('quota') if account else 'unknown'} status={account.get('status') if account else 'unknown'}"
                    )
                    break
                except ImageGenerationError as exc:
                    account = self.account_service.mark_image_result(request_token, success=False)
                    message = str(exc)
                    last_error = message
                    print(
                        f"[image-edit] fail pooled token={request_token[:12]}... "
                        f"error={message} quota={account.get('quota') if account else 'unknown'} status={account.get('status') if account else 'unknown'}"
                    )
                    if is_token_invalid_error(message):
                        self.account_service.remove_token(request_token)
                        print(f"[image-edit] remove invalid token={request_token[:12]}...")
                        continue
                    if (
                        is_retryable_image_output_error(message)
                        and transient_retry_count < MAX_TRANSIENT_IMAGE_EDIT_RETRIES
                    ):
                        transient_retry_count += 1
                        print(
                            f"[image-edit] retry transient upstream failure token={request_token[:12]}... "
                            f"attempt={transient_retry_count}/{MAX_TRANSIENT_IMAGE_EDIT_RETRIES} error={message}"
                        )
                        continue
                    break

        if not image_items:
            raise ImageGenerationError(last_error or "image edit failed")

        return {
            "created": created,
            "data": image_items,
        }

    def create_image_completion(self, body: dict[str, object]) -> dict[str, object]:
        if not is_image_chat_request(body):
            raise HTTPException(
                status_code=400,
                detail={"error": "only image generation requests are supported on this endpoint"},
            )

        if bool(body.get("stream")):
            raise HTTPException(status_code=400, detail={"error": "stream is not supported for image generation"})

        model = str(body.get("model") or "gpt-image-2").strip() or "gpt-image-2"
        n = parse_image_count(body.get("n"))
        prompt = extract_chat_prompt(body)
        if not prompt:
            raise HTTPException(status_code=400, detail={"error": "prompt is required"})
        self._enforce_sensitive_word_filter(prompt)

        image_infos = extract_chat_image(body)
        try:
            if image_infos:
                images = [(data, f"image_{idx}.png", mime_type) for idx, (data, mime_type) in enumerate(image_infos, start=1)]
                image_result = self.edit_with_pool(prompt, images, model, n)
            else:
                image_result = self.generate_with_pool(prompt, model, n)
        except ImageGenerationError as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

        return build_chat_image_completion(model, prompt, image_result)

    def create_response(self, body: dict[str, object]) -> dict[str, object]:
        if bool(body.get("stream")):
            raise HTTPException(status_code=400, detail={"error": "stream is not supported"})

        if not has_response_image_generation_tool(body):
            raise HTTPException(
                status_code=400,
                detail={"error": "only image_generation tool requests are supported on this endpoint"},
            )

        prompt = extract_response_prompt(body.get("input"))
        if not prompt:
            raise HTTPException(status_code=400, detail={"error": "input text is required"})
        self._enforce_sensitive_word_filter(prompt)

        image_infos = _extract_response_images(body.get("input"))
        model = str(body.get("model") or "gpt-5").strip() or "gpt-5"
        try:
            if image_infos:
                images = [(data, f"image_{idx}.png", mime_type) for idx, (data, mime_type) in enumerate(image_infos, start=1)]
                image_result = self.edit_with_pool(prompt, images, "gpt-image-2", 1)
            else:
                image_result = self.generate_with_pool(prompt, "gpt-image-2", 1)
        except ImageGenerationError as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

        image_items = image_result.get("data") if isinstance(image_result.get("data"), list) else []
        output = []
        for item in image_items:
            if not isinstance(item, dict):
                continue
            b64_json = str(item.get("b64_json") or "").strip()
            if not b64_json:
                continue
            output.append(
                {
                    "id": f"ig_{len(output) + 1}",
                    "type": "image_generation_call",
                    "status": "completed",
                    "result": b64_json,
                    "mime_type": str(item.get("mime_type") or "image/png").strip() or "image/png",
                    "revised_prompt": str(item.get("revised_prompt") or prompt).strip(),
                }
            )

        if not output:
            raise HTTPException(status_code=502, detail={"error": "image generation failed"})

        created = int(image_result.get("created") or 0)
        return {
            "id": f"resp_{created}",
            "object": "response",
            "created_at": created,
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "model": model,
            "output": output,
            "parallel_tool_calls": False,
        }
