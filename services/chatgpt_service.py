from __future__ import annotations

from collections.abc import Iterable, Iterator
import json
from threading import Lock
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
    inpaint_image_result,
    is_rate_limited_image_error,
    is_retryable_image_output_error,
    is_token_invalid_error,
)
from services.text_backend import (
    TextBackend,
    TextBackendError,
    TextConversationExpiredError,
    fetch_available_text_model_slugs,
)
from services.text_thread_service import text_thread_service
from services.utils import (
    BLOCKED_RESPONSE_ERROR_PREFIX,
    CODEX_IMAGE_MODEL,
    IMAGE_MODELS,
    ImageRequestOptions,
    build_image_prompt,
    build_image_request_options,
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
    find_sensitive_word,
    find_sensitive_word_match,
    parse_image_count,
    strip_assistant_history_prefix,
    SUPPORTED_IMAGE_MODELS,
    SUPPORTED_API_MODELS,
)


MAX_TRANSIENT_IMAGE_EDIT_RETRIES = 1
MODEL_DISCOVERY_CACHE_TTL_SECONDS = 5 * 60


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
        self._models_cache_lock = Lock()
        self._models_cache_expires_at = 0.0
        self._models_cache: list[str] | None = None

    @staticmethod
    def _is_codex_image_model(model: str) -> bool:
        return str(model or "").strip() == CODEX_IMAGE_MODEL

    def _get_image_request_token(self, model: str, excluded_tokens: set[str] | None = None) -> str:
        if self._is_codex_image_model(model):
            getter = getattr(self.account_service, "get_codex_image_access_token", None)
            if callable(getter):
                return getter()
        return self.account_service.get_available_access_token(excluded_tokens=excluded_tokens)

    def _mark_image_request_result(self, access_token: str, success: bool, model: str) -> dict | None:
        if self._is_codex_image_model(model):
            marker = getattr(self.account_service, "mark_codex_image_result", None)
            if callable(marker):
                return marker(access_token, success=success)
        return self.account_service.mark_image_result(access_token, success=success)

    def _list_text_access_tokens(self, excluded_tokens: set[str] | None = None) -> list[str]:
        excluded = {str(token or "").strip() for token in (excluded_tokens or set()) if str(token or "").strip()}
        preferred_tokens: list[str] = []
        fallback_tokens: list[str] = []
        seen_tokens: set[str] = set()
        try:
            accounts = self.account_service.list_accounts()
        except Exception:
            accounts = []

        if isinstance(accounts, list):
            for account in accounts:
                if not isinstance(account, dict):
                    continue
                access_token = str(account.get("access_token") or "").strip()
                if not access_token or access_token in excluded or access_token in seen_tokens:
                    continue
                seen_tokens.add(access_token)
                status = str(account.get("status") or "").strip()
                if status in {"禁用", "异常"}:
                    continue
                if str(account.get("type") or "Free").strip() == "Free":
                    fallback_tokens.append(access_token)
                else:
                    preferred_tokens.append(access_token)
        return preferred_tokens or fallback_tokens

    def _get_text_access_token(self, excluded_tokens: set[str] | None = None) -> str:
        token = (self._list_text_access_tokens(excluded_tokens) or [""])[0]
        if token:
            return token
        try:
            tokens = self.account_service.list_tokens()
        except Exception:
            tokens = []
        excluded = {str(item or "").strip() for item in (excluded_tokens or set()) if str(item or "").strip()}
        seen: set[str] = set()
        for raw_token in tokens:
            token = str(raw_token or "").strip()
            if not token or token in excluded or token in seen:
                continue
            seen.add(token)
            return token
        raise HTTPException(status_code=502, detail={"error": "no available access token"})

    def _mark_text_token_invalid(self, access_token: str) -> None:
        token = str(access_token or "").strip()
        if not token:
            return
        try:
            updated = self.account_service.update_account(
                token,
                {
                    "status": "异常",
                    "quota": 0,
                },
            )
        except Exception as exc:
            print(f"[text-backend] mark invalid token={token[:12]}... failed: {exc}")
            return
        if updated is None and hasattr(self.account_service, "remove_token"):
            try:
                removed = bool(self.account_service.remove_token(token))
            except Exception as exc:
                print(f"[text-backend] remove invalid token={token[:12]}... failed: {exc}")
                return
            if removed:
                print(f"[text-backend] removed invalid token={token[:12]}...")

    def _call_text_backend(
        self,
        method: str,
        prompt: str,
        model: str,
        **backend_kwargs: object,
    ) -> object:
        attempted_tokens: set[str] = set()
        while True:
            access_token = self._get_text_access_token(excluded_tokens=attempted_tokens)
            attempted_tokens.add(access_token)
            try:
                backend = TextBackend(access_token)
                return getattr(backend, method)(prompt, model, **backend_kwargs)
            except TextConversationExpiredError:
                raise
            except (TextBackendError, ImageGenerationError) as exc:
                message = str(exc)
                if is_token_invalid_error(message):
                    self._mark_text_token_invalid(access_token)
                    print(f"[text-backend] skip invalid token={access_token[:12]}... error={message}")
                    continue
                if isinstance(exc, TextBackendError):
                    raise
                raise TextBackendError(message) from exc

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
    def _merge_instruction_text(instruction_text: str = "") -> str:
        parts = [
            str(config.global_system_prompt or "").strip(),
            str(instruction_text or "").strip(),
        ]
        return "\n\n".join(part for part in parts if part).strip()

    def _compose_text_prompt(self, prompt: str, instruction_text: str = "") -> str:
        normalized_prompt = str(prompt or "").strip()
        normalized_instruction_text = self._merge_instruction_text(instruction_text)
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
        extra: dict[str, object] | None = None,
    ) -> dict[str, object]:
        delta: dict[str, object] = {}
        if role:
            delta["role"] = role
        if content:
            delta["content"] = content
        payload = {
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
        if isinstance(extra, dict):
            payload.update(extra)
        return payload

    @staticmethod
    def _stream_sensitive_words() -> list[str]:
        if not bool(getattr(config, "sensitive_word_filter_enabled", False)):
            return []
        return [str(item or "").strip() for item in getattr(config, "sensitive_words", []) if str(item or "").strip()]

    def _save_thread_state(
        self,
        *,
        identity: dict[str, object],
        thread_id: str,
        conversation_id: str,
        parent_message_id: str,
        model: str,
        last_error: str | None = None,
    ) -> str:
        if not conversation_id or not parent_message_id:
            raise HTTPException(status_code=502, detail={"error": "thread state missing from upstream"})
        if thread_id:
            saved_thread = text_thread_service.update_thread(
                identity,
                thread_id,
                conversation_id=conversation_id,
                parent_message_id=parent_message_id,
                model=model,
                last_error=last_error,
            )
            if saved_thread is None:
                raise self._thread_error("thread not found", status_code=404)
            return str(saved_thread.get("id") or "")
        saved_thread = text_thread_service.create_thread(
            identity,
            conversation_id=conversation_id,
            parent_message_id=parent_message_id,
            model=model,
            last_error=last_error,
        )
        return str(saved_thread.get("id") or "")

    @staticmethod
    def _extract_thread_id_from_openai_chunks(chunks: list[dict[str, object]]) -> str | None:
        for chunk in chunks:
            thread_id = str(chunk.get("thread_id") or "").strip()
            if thread_id:
                return thread_id
        return None

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
    def _merge_supported_models(text_models: Iterable[str] | None) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for model in ("auto", *(text_models or []), *SUPPORTED_IMAGE_MODELS):
            slug = str(model or "").strip()
            if not slug or slug in seen:
                continue
            seen.add(slug)
            merged.append(slug)
        return merged or list(SUPPORTED_API_MODELS)

    def _discover_text_models(self) -> list[str]:
        tokens = self._list_text_access_tokens()
        if not tokens:
            raise TextBackendError("no available access token")
        return fetch_available_text_model_slugs(tokens[0])

    def list_models(self) -> list[str]:
        now = time.time()
        with self._models_cache_lock:
            if self._models_cache is not None and self._models_cache_expires_at > now:
                return list(self._models_cache)
        try:
            discovered_models = self._merge_supported_models(self._discover_text_models())
        except Exception:
            discovered_models = list(SUPPORTED_API_MODELS)
        with self._models_cache_lock:
            self._models_cache = list(discovered_models)
            self._models_cache_expires_at = now + MODEL_DISCOVERY_CACHE_TTL_SECONDS
        return list(discovered_models)

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

    @staticmethod
    def _thread_request(body: dict[str, object]) -> tuple[bool, str]:
        thread_id = str(body.get("thread_id") or "").strip()
        threaded = bool(body.get("threaded")) or bool(thread_id)
        return threaded, thread_id

    @staticmethod
    def _thread_error(message: str, *, status_code: int) -> HTTPException:
        return HTTPException(status_code=status_code, detail={"error": message})

    @staticmethod
    def _thread_state_from_result(backend_result: dict[str, object]) -> tuple[str, str]:
        conversation_id = str(backend_result.get("conversation_id") or "").strip()
        parent_message_id = str(backend_result.get("parent_message_id") or "").strip()
        if not conversation_id or not parent_message_id:
            raise HTTPException(status_code=502, detail={"error": "thread state missing from upstream"})
        return conversation_id, parent_message_id

    @staticmethod
    def _apply_thread_id(payload: dict[str, object], thread_id: str | None) -> dict[str, object]:
        if thread_id:
            payload["thread_id"] = thread_id
        return payload

    @staticmethod
    def _is_output_blocked(text: str) -> str | None:
        if not bool(getattr(config, "sensitive_word_filter_enabled", False)):
            return None
        return find_sensitive_word(text, getattr(config, "sensitive_words", []))

    def _complete_text_request(
        self,
        *,
        identity: dict[str, object],
        body: dict[str, object],
        prompt: str,
        model: str,
        history_source: object,
    ) -> tuple[dict[str, object], str | None]:
        self._enforce_sensitive_word_filter(prompt)

        threaded, thread_id = self._thread_request(body)
        existing_thread: dict[str, object] | None = None
        backend_kwargs: dict[str, object] = {}
        if threaded:
            if thread_id:
                existing_thread = text_thread_service.get_thread(identity, thread_id)
                if existing_thread is None:
                    raise self._thread_error("thread not found", status_code=404)
                backend_kwargs = {
                    "conversation_id": str(existing_thread.get("conversation_id") or ""),
                    "parent_message_id": str(existing_thread.get("parent_message_id") or ""),
                    "allow_conversation_fallback": False,
                }
        try:
            backend_result = self._call_text_backend("complete", prompt, model, **backend_kwargs)
        except TextConversationExpiredError as exc:
            raise self._thread_error(str(exc), status_code=409) from exc
        except TextBackendError as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

        backend_result = dict(backend_result)
        backend_result["text"] = self._strip_history_from_text(str(backend_result.get("text") or ""), history_source)
        if not threaded:
            return backend_result, None

        conversation_id, parent_message_id = self._thread_state_from_result(backend_result)
        blocked_word = self._is_output_blocked(str(backend_result.get("text") or ""))
        if blocked_word:
            error_message = f"{BLOCKED_RESPONSE_ERROR_PREFIX}: {blocked_word}"
            if existing_thread is not None:
                self._save_thread_state(
                    identity=identity,
                    thread_id=str(existing_thread.get("id") or ""),
                    conversation_id=conversation_id,
                    parent_message_id=parent_message_id,
                    model=model,
                    last_error=error_message,
                )
            raise self._thread_error(error_message, status_code=400)

        return (
            backend_result,
            self._save_thread_state(
                identity=identity,
                thread_id=str(existing_thread.get("id") or "") if existing_thread is not None else "",
                conversation_id=conversation_id,
                parent_message_id=parent_message_id,
                model=model,
            ),
        )

    def _create_text_completion_stream(
        self,
        *,
        body: dict[str, object],
        identity: dict[str, object],
        prompt: str,
        model: str,
    ) -> Iterator[str]:
        self._enforce_sensitive_word_filter(prompt)
        threaded, active_thread_id = self._thread_request(body)
        backend_kwargs: dict[str, object] = {}
        if active_thread_id:
            existing_thread = text_thread_service.get_thread(identity, active_thread_id)
            if existing_thread is None:
                raise self._thread_error("thread not found", status_code=404)
            backend_kwargs = {
                "conversation_id": str(existing_thread.get("conversation_id") or ""),
                "parent_message_id": str(existing_thread.get("parent_message_id") or ""),
                "allow_conversation_fallback": False,
            }
        try:
            backend_stream = self._call_text_backend("stream", prompt, model, **backend_kwargs)
        except TextConversationExpiredError as exc:
            raise self._thread_error(str(exc), status_code=409) from exc
        except TextBackendError as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc

        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created = int(time.time())
        history_messages = extract_assistant_history_messages(body.get("messages"))
        sensitive_words = self._stream_sensitive_words() if threaded else []
        hold_back_chars = max((len(word) for word in sensitive_words), default=1) - 1

        def generate() -> Iterator[str]:
            nonlocal active_thread_id
            consumed_count = 0
            sent_role = False
            role_chunk_sent_thread_id = False
            streamed_text = ""
            final_text = ""
            latest_conversation_id = str(backend_kwargs.get("conversation_id") or "")
            latest_parent_message_id = str(backend_kwargs.get("parent_message_id") or "")

            def ensure_thread_id() -> None:
                nonlocal active_thread_id
                if not threaded or active_thread_id or not latest_conversation_id or not latest_parent_message_id:
                    return
                active_thread_id = self._save_thread_state(
                    identity=identity,
                    thread_id="",
                    conversation_id=latest_conversation_id,
                    parent_message_id=latest_parent_message_id,
                    model=model,
                )

            def emit_role_chunk() -> Iterator[str]:
                nonlocal sent_role, role_chunk_sent_thread_id
                if sent_role:
                    return
                sent_role = True
                extra: dict[str, object] = {}
                if active_thread_id:
                    extra["thread_id"] = active_thread_id
                    role_chunk_sent_thread_id = True
                yield self._encode_sse_data(
                    self._build_text_completion_chunk(
                        completion_id,
                        created,
                        model,
                        role="assistant",
                        extra=extra or None,
                    )
                )

            for event in backend_stream:
                latest_conversation_id = str(event.get("conversation_id") or latest_conversation_id)
                latest_parent_message_id = str(event.get("parent_message_id") or latest_parent_message_id)
                normalized_text, consumed_count = self._normalize_stream_snapshot(
                    str(event.get("text") or ""),
                    history_messages,
                    consumed_count,
                )
                final_text = normalized_text
                ensure_thread_id()
                blocked_match = find_sensitive_word_match(normalized_text, sensitive_words)
                if blocked_match:
                    blocked_word, start_index, _end_index = blocked_match
                    safe_limit = max(len(streamed_text), start_index)
                    safe_text = normalized_text[:safe_limit]
                    if safe_text and safe_text != streamed_text:
                        yield from emit_role_chunk()
                        delta = safe_text[len(streamed_text):] if safe_text.startswith(streamed_text) else safe_text
                        streamed_text = safe_text
                        if delta:
                            yield self._encode_sse_data(
                                self._build_text_completion_chunk(completion_id, created, model, content=delta)
                            )
                    error_message = f"{BLOCKED_RESPONSE_ERROR_PREFIX}: {blocked_word}"
                    if threaded and active_thread_id:
                        active_thread_id = self._save_thread_state(
                            identity=identity,
                            thread_id=active_thread_id,
                            conversation_id=latest_conversation_id,
                            parent_message_id=latest_parent_message_id,
                            model=model,
                            last_error=error_message,
                        )
                    finish_extra: dict[str, object] = {"moderation_error": error_message}
                    if active_thread_id and not role_chunk_sent_thread_id:
                        finish_extra["thread_id"] = active_thread_id
                    yield self._encode_sse_data(
                        self._build_text_completion_chunk(
                            completion_id,
                            created,
                            model,
                            finish_reason="content_filter",
                            extra=finish_extra,
                        )
                    )
                    yield self._encode_sse_data("[DONE]")
                    return

                flush_limit = len(normalized_text)
                if hold_back_chars > 0:
                    flush_limit = max(0, len(normalized_text) - hold_back_chars)
                if flush_limit <= len(streamed_text):
                    continue
                next_safe_text = normalized_text[:flush_limit]
                if not next_safe_text:
                    continue
                yield from emit_role_chunk()
                delta = next_safe_text[len(streamed_text):] if next_safe_text.startswith(streamed_text) else next_safe_text
                streamed_text = next_safe_text
                if delta:
                    yield self._encode_sse_data(
                        self._build_text_completion_chunk(completion_id, created, model, content=delta)
                    )

            ensure_thread_id()
            if final_text and final_text != streamed_text:
                yield from emit_role_chunk()
                delta = final_text[len(streamed_text):] if final_text.startswith(streamed_text) else final_text
                streamed_text = final_text
                if delta:
                    yield self._encode_sse_data(
                        self._build_text_completion_chunk(completion_id, created, model, content=delta)
                    )
            if threaded and active_thread_id:
                active_thread_id = self._save_thread_state(
                    identity=identity,
                    thread_id=active_thread_id,
                    conversation_id=latest_conversation_id,
                    parent_message_id=latest_parent_message_id,
                    model=model,
                )
            finish_extra: dict[str, object] = {}
            if active_thread_id and not role_chunk_sent_thread_id:
                finish_extra["thread_id"] = active_thread_id
            yield self._encode_sse_data(
                self._build_text_completion_chunk(
                    completion_id,
                    created,
                    model,
                    finish_reason="stop",
                    extra=finish_extra or None,
                )
            )
            yield self._encode_sse_data("[DONE]")

        return generate()

    def create_text_completion(self, body: dict[str, object], identity: dict[str, object]) -> dict[str, object]:
        if bool(body.get("stream")):
            raise HTTPException(status_code=400, detail={"error": "stream is not supported for text completions"})

        model = str(body.get("model") or "auto").strip() or "auto"
        prompt = self._build_chat_text_prompt(body)
        if not prompt:
            raise HTTPException(status_code=400, detail={"error": "messages or prompt is required"})

        backend_result, thread_id = self._complete_text_request(
            identity=identity,
            body=body,
            prompt=prompt,
            model=model,
            history_source=body.get("messages"),
        )
        return self._apply_thread_id(self._build_text_completion_response(model, backend_result), thread_id)

    def create_text_completion_stream(self, body: dict[str, object], identity: dict[str, object]) -> Iterator[str]:
        model = str(body.get("model") or "auto").strip() or "auto"
        prompt = self._build_chat_text_prompt(body)
        if not prompt:
            raise HTTPException(status_code=400, detail={"error": "messages or prompt is required"})
        return self._create_text_completion_stream(body=body, identity=identity, prompt=prompt, model=model)

    def create_text_response(self, body: dict[str, object], identity: dict[str, object]) -> dict[str, object]:
        if bool(body.get("stream")):
            raise HTTPException(status_code=400, detail={"error": "stream is not supported"})

        model = str(body.get("model") or "auto").strip() or "auto"
        prompt = self._build_response_text_prompt(body)
        if not prompt:
            raise HTTPException(status_code=400, detail={"error": "input text is required"})
        backend_result, thread_id = self._complete_text_request(
            identity=identity,
            body=body,
            prompt=prompt,
            model=model,
            history_source=body.get("input"),
        )
        return self._apply_thread_id(self._build_text_response_payload(model, backend_result), thread_id)

    def create_message(self, body: dict[str, object], identity: dict[str, object]) -> dict[str, object]:
        model = str(body.get("model") or "auto").strip() or "auto"
        prompt = self._build_message_text_prompt(body)
        if not prompt:
            raise HTTPException(status_code=400, detail={"error": "messages are required"})
        backend_result, thread_id = self._complete_text_request(
            identity=identity,
            body=body,
            prompt=prompt,
            model=model,
            history_source=body.get("messages"),
        )
        return self._apply_thread_id(self._build_message_response(model, backend_result, tools=body.get("tools")), thread_id)

    def stream_message(self, body: dict[str, object], identity: dict[str, object]) -> Iterator[str]:
        _ = identity
        if self._thread_request(body)[0]:
            raise HTTPException(status_code=400, detail={"error": "threaded conversations are not supported for stream requests"})
        model = str(body.get("model") or "auto").strip() or "auto"
        prompt = self._build_message_text_prompt(body)
        if not prompt:
            raise HTTPException(status_code=400, detail={"error": "messages are required"})
        self._enforce_sensitive_word_filter(prompt)

        try:
            backend_stream = self._call_text_backend("stream", prompt, model)
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
        *,
        image_options: ImageRequestOptions | None = None,
    ):
        created = None
        image_items: list[dict[str, object]] = []
        last_error: str | None = None

        for index in range(1, n + 1):
            while True:
                try:
                    request_token = self._get_image_request_token(model)
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
                        image_options=image_options,
                        response_format=response_format,
                        base_url=base_url,
                    )
                    account = self._mark_image_request_result(request_token, success=True, model=model)
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
                    account = self._mark_image_request_result(request_token, success=False, model=model)
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
                    if self._is_codex_image_model(model) and is_rate_limited_image_error(message):
                        self.account_service.update_account(request_token, {"status": "限流"})
                        print(f"[image-generate] mark codex token limited={request_token[:12]}..., retry next token")
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
        *,
        image_options: ImageRequestOptions | None = None,
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
                    request_token = self._get_image_request_token(model)
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
                        image_options=image_options,
                        response_format=response_format,
                        base_url=base_url,
                    )
                    account = self._mark_image_request_result(request_token, success=True, model=model)
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
                    account = self._mark_image_request_result(request_token, success=False, model=model)
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
                    if self._is_codex_image_model(model) and is_rate_limited_image_error(message):
                        self.account_service.update_account(request_token, {"status": "限流"})
                        print(f"[image-edit] mark codex token limited={request_token[:12]}..., retry next token")
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

    def inpaint_with_pool(
        self,
        prompt: str,
        original_image: tuple[bytes, str, str],
        mask_data: bytes,
        model: str,
        response_format: str = "b64_json",
        base_url: str | None = None,
        *,
        original_gen_id: str = "",
        ref_images: list[tuple[bytes, str, str]] | None = None,
        image_options: ImageRequestOptions | None = None,
    ):
        _INPAINT_MAX_RETRIES = 3
        tried_tokens: set[str] = set()
        last_error: str = "inpaint failed"

        for attempt in range(1, _INPAINT_MAX_RETRIES + 1):
            try:
                request_token = self._get_image_request_token(model, excluded_tokens=tried_tokens)
            except RuntimeError as exc:
                raise ImageGenerationError(last_error or str(exc)) from exc

            tried_tokens.add(request_token)
            print(
                f"[image-inpaint] attempt={attempt}/{_INPAINT_MAX_RETRIES} "
                f"token={request_token[:12]}... model={model}"
            )
            try:
                result = inpaint_image_result(
                    request_token,
                    prompt,
                    original_image,
                    mask_data,
                    model,
                    response_format=response_format,
                    base_url=base_url,
                    original_gen_id=original_gen_id,
                    ref_images=ref_images,
                    image_options=image_options,
                )
                account = self._mark_image_request_result(request_token, success=True, model=model)
                print(
                    f"[image-inpaint] success attempt={attempt} token={request_token[:12]}... "
                    f"quota={account.get('quota') if account else 'unknown'}"
                )
                return result
            except ImageGenerationError as exc:
                self._mark_image_request_result(request_token, success=False, model=model)
                last_error = str(exc)
                # 「no image returned」通常表示该账号不支持编辑功能，换号重试
                if "no image returned" in last_error and attempt < _INPAINT_MAX_RETRIES:
                    print(
                        f"[image-inpaint] account doesn't support inpainting, "
                        f"retrying with different account (attempt {attempt}/{_INPAINT_MAX_RETRIES})"
                    )
                    continue
                raise

        raise ImageGenerationError(last_error)

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
        try:
            image_options = build_image_request_options(
                model=model,
                size=body.get("size"),
                quality=body.get("quality"),
                background=body.get("background"),
                output_format=body.get("output_format"),
                compression=body.get("compression"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        prompt = build_image_prompt(extract_chat_prompt(body), image_options)
        if not prompt:
            raise HTTPException(status_code=400, detail={"error": "prompt is required"})
        self._enforce_sensitive_word_filter(prompt)

        image_infos = extract_chat_image(body)
        try:
            if image_infos:
                images = [(data, f"image_{idx}.png", mime_type) for idx, (data, mime_type) in enumerate(image_infos, start=1)]
                image_result = self.edit_with_pool(prompt, images, model, n, image_options=image_options)
            else:
                image_result = self.generate_with_pool(prompt, model, n, image_options=image_options)
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
        image_model = model if model in IMAGE_MODELS else "gpt-image-2"
        try:
            image_options = build_image_request_options(
                model=image_model,
                size=body.get("size"),
                quality=body.get("quality"),
                background=body.get("background"),
                output_format=body.get("output_format"),
                compression=body.get("compression"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        prompt = build_image_prompt(prompt, image_options)
        self._enforce_sensitive_word_filter(prompt)
        try:
            if image_infos:
                images = [(data, f"image_{idx}.png", mime_type) for idx, (data, mime_type) in enumerate(image_infos, start=1)]
                image_result = self.edit_with_pool(prompt, images, image_model, 1, image_options=image_options)
            else:
                image_result = self.generate_with_pool(prompt, image_model, 1, image_options=image_options)
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
