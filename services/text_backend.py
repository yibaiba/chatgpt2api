from __future__ import annotations

from collections.abc import Iterator
import json
import random
import time
import uuid

from services.image_service import (
    BASE_URL,
    USER_AGENT,
    _bootstrap,
    _cached_build_number,
    _cached_client_version,
    _chat_requirements,
    _conversation_init,
    _generate_proof_token,
    _new_session,
    _pow_config,
    _retry,
    is_conversation_forbidden_error,
)


class TextBackendError(Exception):
    pass


class TextConversationExpiredError(TextBackendError):
    pass


CLIENT_CREATED_ROOT = "client-created-root"
NO_CONDUIT_TOKEN = "no-token"


def _close_response(response) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


def _build_text_conversation_body(prompt: str, parent_message_id: str, model: str) -> dict[str, object]:
    return {
        "action": "next",
        "messages": [
            {
                "id": str(uuid.uuid4()),
                "author": {"role": "user"},
                "create_time": time.time(),
                "content": {"content_type": "text", "parts": [prompt]},
                "metadata": {
                    "selected_github_repos": [],
                    "selected_all_github_repos": False,
                    "serialization_metadata": {"custom_symbol_offsets": []},
                },
            }
        ],
        "parent_message_id": parent_message_id,
        "model": model,
        "timezone_offset_min": -480,
        "timezone": "Asia/Shanghai",
        "conversation_mode": {"kind": "primary_assistant"},
        "enable_message_followups": True,
        "system_hints": [],
        "supports_buffering": True,
        "supported_encodings": ["v1"],
        "client_prepare_state": "success",
        "paragen_cot_summary_display_override": "allow",
        "force_parallel_switch": "auto",
        "client_contextual_info": {
            "is_dark_mode": False,
            "time_since_loaded": random.randint(50, 500),
            "page_height": random.randint(500, 1000),
            "page_width": random.randint(1000, 2000),
            "pixel_ratio": 1,
            "screen_height": random.randint(800, 1200),
            "screen_width": random.randint(1200, 2200),
            "app_name": "chatgpt.com",
        },
    }


def _build_text_prepare_body(
    prompt: str,
    parent_message_id: str,
    model: str,
    *,
    conversation_id: str = "",
) -> dict[str, object]:
    body: dict[str, object] = {
        "action": "next",
        "fork_from_shared_post": False,
        "parent_message_id": parent_message_id,
        "model": model,
        "client_prepare_state": "none",
        "timezone_offset_min": -480,
        "timezone": "Asia/Shanghai",
        "conversation_mode": {"kind": "primary_assistant"},
        "system_hints": [],
        "supports_buffering": True,
        "supported_encodings": ["v1"],
        "client_contextual_info": {"app_name": "chatgpt.com"},
    }
    if conversation_id:
        body["conversation_id"] = conversation_id
    else:
        body["partial_query"] = {
            "id": str(uuid.uuid4()),
            "author": {"role": "user"},
            "content": {"content_type": "text", "parts": [prompt]},
        }
    return body


def _prepare_text_transport(
    session,
    access_token: str,
    device_id: str,
    prompt: str,
    model: str,
    *,
    conversation_id: str = "",
    parent_message_id: str = CLIENT_CREATED_ROOT,
    resume_conduit_token: str = "",
) -> dict[str, str]:
    chat_token, pow_info = _chat_requirements(session, access_token, device_id)
    proof_token = ""
    if pow_info.get("required"):
        proof_token = _generate_proof_token(
            seed=str(pow_info["seed"]),
            difficulty=str(pow_info["difficulty"]),
            user_agent=USER_AGENT,
            proof_config=_pow_config(USER_AGENT),
        )
    session_id = str(uuid.uuid4())
    turn_trace_id = str(uuid.uuid4())
    response = _retry(
        lambda: session.post(
            BASE_URL + "/backend-api/f/conversation/prepare",
            headers={
                "Authorization": f"Bearer {access_token}",
                "accept": "*/*",
                "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
                "content-type": "application/json",
                "oai-device-id": device_id,
                "oai-language": "zh-CN",
                "oai-session-id": session_id,
                "oai-client-build-number": _cached_build_number,
                "oai-client-version": _cached_client_version,
                "origin": BASE_URL,
                "referer": BASE_URL + "/",
                "x-conduit-token": resume_conduit_token or NO_CONDUIT_TOKEN,
                "x-oai-turn-trace-id": turn_trace_id,
                "x-openai-target-path": "/backend-api/f/conversation/prepare",
                "x-openai-target-route": "/backend-api/f/conversation/prepare",
            },
            json=_build_text_prepare_body(
                prompt,
                parent_message_id,
                model,
                conversation_id=conversation_id,
            ),
            timeout=20,
        ),
        retries=2,
    )
    conduit_token = ""
    if response.ok:
        payload = response.json() or {}
        conduit_token = payload.get("conduit_token") or ""
    if not conduit_token:
        raise TextBackendError("f/conversation/prepare returned no conduit_token")
    return {
        "chat_token": chat_token,
        "proof_token": proof_token,
        "conduit_token": str(conduit_token),
    }


def _send_text_conversation(
    session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token: str | None,
    parent_message_id: str,
    prompt: str,
    model: str,
    conversation_id: str = "",
    *,
    conduit_token: str,
):
    session_id = str(uuid.uuid4())
    turn_trace_id = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "text/event-stream",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "content-type": "application/json",
        "oai-device-id": device_id,
        "oai-language": "zh-CN",
        "oai-session-id": session_id,
        "oai-client-build-number": _cached_build_number,
        "oai-client-version": _cached_client_version,
        "origin": BASE_URL,
        "referer": BASE_URL + "/",
        "x-conduit-token": conduit_token or NO_CONDUIT_TOKEN,
        "x-oai-turn-trace-id": turn_trace_id,
        "x-openai-target-path": "/backend-api/f/conversation",
        "x-openai-target-route": "/backend-api/f/conversation",
        "openai-sentinel-chat-requirements-token": chat_token,
    }
    if proof_token:
        headers["openai-sentinel-proof-token"] = proof_token
    body = _build_text_conversation_body(prompt, parent_message_id, model)
    if conversation_id:
        body["conversation_id"] = conversation_id
    response = _retry(
        lambda: session.post(
            BASE_URL + "/backend-api/f/conversation",
            headers=headers,
            json=body,
            stream=True,
            timeout=180,
        ),
        retries=2,
    )
    if not response.ok:
        raise TextBackendError(response.text[:400] or f"f/conversation failed: {response.status_code}")
    return response


def _send_legacy_text_conversation(
    session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token: str | None,
    parent_message_id: str,
    prompt: str,
    model: str,
    conversation_id: str = "",
):
    session_id = str(uuid.uuid4())
    turn_trace_id = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "text/event-stream",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "content-type": "application/json",
        "oai-device-id": device_id,
        "oai-language": "zh-CN",
        "oai-session-id": session_id,
        "oai-client-build-number": _cached_build_number,
        "oai-client-version": _cached_client_version,
        "origin": BASE_URL,
        "referer": BASE_URL + "/",
        "x-oai-turn-trace-id": turn_trace_id,
        "openai-sentinel-chat-requirements-token": chat_token,
    }
    if proof_token:
        headers["openai-sentinel-proof-token"] = proof_token
    body = _build_text_conversation_body(prompt, parent_message_id, model)
    if conversation_id:
        body["conversation_id"] = conversation_id
    response = _retry(
        lambda: session.post(
            BASE_URL + "/backend-api/conversation",
            headers=headers,
            json=body,
            stream=True,
            timeout=180,
        ),
        retries=3,
    )
    if not response.ok:
        raise TextBackendError(response.text[:400] or f"conversation failed: {response.status_code}")
    return response


def _iter_text_sse_events(response) -> Iterator[dict[str, object]]:
    conversation_id = ""
    latest_text = ""
    latest_message_id = ""
    active_assistant_message_id = ""
    last_emitted_message_id = ""
    last_emitted_text = ""

    def emit_if_changed() -> dict[str, object] | None:
        nonlocal last_emitted_message_id, last_emitted_text
        if not latest_text:
            return None
        if latest_text == last_emitted_text and latest_message_id == last_emitted_message_id:
            return None
        last_emitted_text = latest_text
        last_emitted_message_id = latest_message_id
        return {
            "conversation_id": conversation_id,
            "parent_message_id": latest_message_id,
            "text": latest_text,
        }

    for raw_line in response.iter_lines():
        if not raw_line:
            continue
        if isinstance(raw_line, bytes):
            raw_line = raw_line.decode("utf-8", errors="replace")
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload in ("", "[DONE]"):
            break
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        conversation_id = str(obj.get("conversation_id") or conversation_id)
        data = obj.get("v")
        if isinstance(data, dict):
            conversation_id = str(data.get("conversation_id") or conversation_id)
        if obj.get("type") == "resume_conversation_token":
            continue
        if obj.get("type") == "message_marker":
            message_id = str(obj.get("message_id") or "").strip()
            if message_id:
                latest_message_id = message_id
                active_assistant_message_id = message_id
            maybe_event = emit_if_changed()
            if maybe_event is not None:
                yield maybe_event
            continue
        message = obj.get("message") or (data.get("message") if isinstance(data, dict) else {}) or {}
        if isinstance(message, dict):
            author = message.get("author") or {}
            role = str(author.get("role") or "").strip()
            content = message.get("content") or {}
            if role == "assistant" and content.get("content_type") == "text":
                active_assistant_message_id = str(message.get("id") or active_assistant_message_id)
                latest_message_id = active_assistant_message_id or latest_message_id
                parts = content.get("parts") or []
                next_text = str(parts[0] or "") if parts else ""
                if next_text and next_text != latest_text:
                    latest_text = next_text
                    maybe_event = emit_if_changed()
                    if maybe_event is not None:
                        yield maybe_event
                    continue
        appended_text = ""
        if obj.get("o") == "append" and obj.get("p") == "/message/content/parts/0":
            appended_text = str(obj.get("v") or "")
        elif obj.get("o") == "patch" and isinstance(obj.get("v"), list):
            appended_text = "".join(
                str(operation.get("v") or "")
                for operation in obj.get("v") or []
                if isinstance(operation, dict)
                and operation.get("o") == "append"
                and operation.get("p") == "/message/content/parts/0"
            )
        elif active_assistant_message_id and isinstance(obj.get("v"), str):
            appended_text = str(obj.get("v") or "")
        if not appended_text or not active_assistant_message_id:
            continue
        latest_message_id = active_assistant_message_id
        latest_text += appended_text
        maybe_event = emit_if_changed()
        if maybe_event is not None:
            yield maybe_event


class TextBackend:
    def __init__(self, access_token: str):
        self.access_token = str(access_token or "").strip()

    @staticmethod
    def _normalize_request(prompt: str, model: str) -> tuple[str, str]:
        normalized_prompt = str(prompt or "").strip()
        normalized_model = str(model or "auto").strip() or "auto"
        return normalized_prompt, normalized_model

    @staticmethod
    def _should_retry_with_auto(message: str, model: str) -> bool:
        return str(model or "").strip() != "auto" and is_conversation_forbidden_error(message)

    def _open_legacy_conversation(
        self,
        session,
        device_id: str,
        prompt: str,
        model: str,
        *,
        conversation_id: str = "",
        parent_message_id: str = "",
    ):
        chat_token, pow_info = _chat_requirements(session, self.access_token, device_id)
        proof_token = None
        if pow_info.get("required"):
            proof_token = _generate_proof_token(
                seed=str(pow_info["seed"]),
                difficulty=str(pow_info["difficulty"]),
                user_agent=USER_AGENT,
                proof_config=_pow_config(USER_AGENT),
            )
        active_conversation_id = str(conversation_id or "").strip()
        active_parent_message_id = str(parent_message_id or "").strip()
        if not active_parent_message_id or active_parent_message_id == CLIENT_CREATED_ROOT:
            active_parent_message_id = str(uuid.uuid4())
        if not active_conversation_id:
            active_conversation_id = _conversation_init(session, self.access_token, device_id)
        response = _send_legacy_text_conversation(
            session,
            self.access_token,
            device_id,
            chat_token,
            proof_token,
            active_parent_message_id,
            prompt,
            model,
            conversation_id=active_conversation_id,
        )
        return response, active_conversation_id, model

    def _open_conversation(
        self,
        prompt: str,
        model: str,
        *,
        conversation_id: str = "",
        parent_message_id: str = "",
        allow_conversation_fallback: bool = True,
    ):
        normalized_prompt, normalized_model = self._normalize_request(prompt, model)
        if not self.access_token:
            raise TextBackendError("token is required")
        if not normalized_prompt:
            raise TextBackendError("prompt is required")

        session, fp = _new_session(self.access_token)
        try:
            device_id = _bootstrap(session, fp)
            active_conversation_id = str(conversation_id or "").strip()
            raw_parent_message_id = str(parent_message_id or "").strip()
            if conversation_id and not raw_parent_message_id:
                raise TextBackendError("parent_message_id is required")
            active_parent_message_id = raw_parent_message_id or CLIENT_CREATED_ROOT
            active_model = normalized_model

            def open_f_transport(request_model: str):
                transport = _prepare_text_transport(
                    session,
                    self.access_token,
                    device_id,
                    normalized_prompt,
                    conversation_id=active_conversation_id,
                    parent_message_id=active_parent_message_id,
                    model=request_model,
                )
                return _send_text_conversation(
                    session,
                    self.access_token,
                    device_id,
                    transport["chat_token"],
                    transport["proof_token"],
                    active_parent_message_id,
                    normalized_prompt,
                    request_model,
                    conversation_id=active_conversation_id,
                    conduit_token=transport["conduit_token"],
                )

            last_error: TextBackendError | None = None
            while True:
                try:
                    response = open_f_transport(active_model)
                    return session, response, active_conversation_id, active_model
                except TextBackendError as exc:
                    last_error = exc
                    if self._should_retry_with_auto(str(exc), active_model):
                        active_model = "auto"
                        continue
                    if active_conversation_id and is_conversation_forbidden_error(str(exc)):
                        if conversation_id and not allow_conversation_fallback:
                            raise TextConversationExpiredError("thread conversation expired") from exc
                        if not allow_conversation_fallback:
                            raise
                        active_conversation_id = ""
                        active_parent_message_id = CLIENT_CREATED_ROOT
                        continue
                    break
            if allow_conversation_fallback:
                response, active_conversation_id, active_model = self._open_legacy_conversation(
                    session,
                    device_id,
                    normalized_prompt,
                    active_model,
                    conversation_id=active_conversation_id,
                    parent_message_id=active_parent_message_id,
                )
                return session, response, active_conversation_id, active_model
            if last_error is not None:
                raise last_error
            raise TextBackendError("failed to open conversation")
        except Exception:
            session.close()
            raise

    def complete(
        self,
        prompt: str,
        model: str = "auto",
        *,
        conversation_id: str = "",
        parent_message_id: str = "",
        allow_conversation_fallback: bool = True,
    ) -> dict[str, object]:
        session, response, conversation_id, normalized_model = self._open_conversation(
            prompt,
            model,
            conversation_id=conversation_id,
            parent_message_id=parent_message_id,
            allow_conversation_fallback=allow_conversation_fallback,
        )
        try:
            latest_event: dict[str, object] | None = None
            for event in _iter_text_sse_events(response):
                latest_event = event
            text = str((latest_event or {}).get("text") or "").strip()
            if not text:
                raise TextBackendError("no text returned from upstream")
            return {
                "created": time.time_ns() // 1_000_000_000,
                "model": normalized_model,
                "text": text,
                "conversation_id": str((latest_event or {}).get("conversation_id") or conversation_id),
                "parent_message_id": str((latest_event or {}).get("parent_message_id") or ""),
            }
        finally:
            _close_response(response)
            session.close()

    def stream(
        self,
        prompt: str,
        model: str = "auto",
        *,
        conversation_id: str = "",
        parent_message_id: str = "",
        allow_conversation_fallback: bool = True,
    ) -> Iterator[dict[str, object]]:
        session, response, conversation_id, normalized_model = self._open_conversation(
            prompt,
            model,
            conversation_id=conversation_id,
            parent_message_id=parent_message_id,
            allow_conversation_fallback=allow_conversation_fallback,
        )
        created = time.time_ns() // 1_000_000_000

        def generate() -> Iterator[dict[str, object]]:
            has_text = False
            latest_conversation_id = conversation_id
            latest_parent_message_id = ""
            try:
                for event in _iter_text_sse_events(response):
                    latest_conversation_id = str(event.get("conversation_id") or latest_conversation_id)
                    latest_parent_message_id = str(event.get("parent_message_id") or latest_parent_message_id)
                    has_text = True
                    yield {
                        "created": created,
                        "model": normalized_model,
                        "text": str(event.get("text") or ""),
                        "conversation_id": latest_conversation_id,
                        "parent_message_id": latest_parent_message_id,
                    }
                if not has_text:
                    raise TextBackendError("no text returned from upstream")
            finally:
                _close_response(response)
                session.close()

        return generate()
