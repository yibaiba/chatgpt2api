from __future__ import annotations

import base64
import hashlib
import io
import json
import random
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from curl_cffi.requests import Session
from PIL import Image

from services.account_service import account_service
from services import proof_of_work
from services.system_settings import system_settings_service
from services.utils import CODEX_IMAGE_MODEL, ImageRequestOptions, parse_exact_image_size


BASE_URL = "https://chatgpt.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)
OAI_CLIENT_BUILD_NUMBER = "6263762"
OAI_CLIENT_VERSION = "prod-bb85d27e6e8ee4f71f4c78dbdd215e997ff394d6"
CODEX_RESPONSE_MODEL = "gpt-5.4"
CODEX_RESPONSE_VERSION = "0.122.0"
CODEX_RESPONSE_INSTRUCTIONS = "you are a helpful assistant"
CODEX_RESPONSE_TOOL_CHOICE = "auto"
CODEX_RESPONSE_SESSION_ID = "test-session"
CODEX_RESPONSE_USER_AGENT = (
    "codex-tui/0.122.0 (Darwin; x86_64) "
    "vscode/3.0.12 (codex-tui; 0.122.0)"
)
MAX_CODEX_INLINE_REQUEST_BYTES = 28 * 1024 * 1024

# 动态提取的 build info，随首页 HTML 刷新，默认使用上方硬编码值兜底
_cached_build_number: str = OAI_CLIENT_BUILD_NUMBER
_cached_client_version: str = OAI_CLIENT_VERSION
_build_info_cache_time: float = 0.0
_BUILD_INFO_TTL = 900  # 15 分钟

DEFAULT_MODEL = "auto"
MAX_POW_ATTEMPTS = 500000
IMAGE_DOWNLOAD_RETRY_STATUSES = (408, 409, 425, 429, 500, 502, 503, 504)
IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 180
IMAGE_UPSTREAM_CONNECTION_ERROR_MARKERS = (
    "curl: (28)",
    "curl: (35)",
    "tls connect error",
    "openssl_internal",
)
IMAGE_OUTPUT_MIME_TYPES = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}
IMAGE_OUTPUT_EXTENSIONS = {
    "png": "png",
    "jpeg": "jpg",
    "webp": "webp",
}

_CORES = [16, 24, 32]
_SCREENS = [3000, 4000, 6000]
_NAV_KEYS = [
    "webdriver−false",
    "vendor−Google Inc.",
    "cookieEnabled−true",
    "pdfViewerEnabled−true",
    "hardwareConcurrency−32",
    "language−zh-CN",
    "mimeTypes−[object MimeTypeArray]",
    "userAgentData−[object NavigatorUAData]",
]
_WIN_KEYS = [
    "innerWidth",
    "innerHeight",
    "devicePixelRatio",
    "screen",
    "chrome",
    "location",
    "history",
    "navigator",
]


class ImageGenerationError(Exception):
    pass


@dataclass
class EditInputImage:
    file_id: str
    data: bytes
    file_name: str
    mime_type: str
    width: int
    height: int


def _build_fp(access_token: str) -> dict:
    account = account_service.get_account(access_token) or {}
    fp = {}
    raw_fp = account.get("fp")
    if isinstance(raw_fp, dict):
        fp.update({str(k).lower(): v for k, v in raw_fp.items()})
    for key in (
        "user-agent",
        "impersonate",
        "oai-device-id",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
    ):
        if key in account:
            fp[key] = account[key]
    if "user-agent" not in fp:
        fp["user-agent"] = USER_AGENT
    if "impersonate" not in fp:
        fp["impersonate"] = "edge101"
    if "oai-device-id" not in fp:
        fp["oai-device-id"] = str(uuid.uuid4())
    return fp


def _new_session(access_token: str) -> tuple[Session, dict]:
    fp = _build_fp(access_token)
    session = system_settings_service.apply_next_proxy(Session(
        impersonate=fp.get("impersonate") or "edge101",
        verify=True,
    ))
    session.headers.update(
        {
            "Authorization": f"Bearer {access_token}",
            "user-agent": fp.get("user-agent") or USER_AGENT,
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,zh-TW;q=0.7",
            "origin": BASE_URL,
            "referer": BASE_URL + "/",
            "accept": "*/*",
            "dnt": "1",
            "sec-ch-ua": fp.get("sec-ch-ua") or '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
            "sec-ch-ua-mobile": fp.get("sec-ch-ua-mobile") or "?0",
            "sec-ch-ua-platform": fp.get("sec-ch-ua-platform") or '"macOS"',
            "sec-ch-ua-arch": fp.get("sec-ch-ua-arch") or '"x86"',
            "sec-ch-ua-bitness": fp.get("sec-ch-ua-bitness") or '"64"',
            "sec-ch-ua-full-version": fp.get("sec-ch-ua-full-version") or '"147.0.0.0"',
            "sec-ch-ua-model": fp.get("sec-ch-ua-model") or '""',
            "sec-ch-ua-platform-version": fp.get("sec-ch-ua-platform-version") or '"12.7.0"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "oai-device-id": fp.get("oai-device-id"),
        }
    )
    return session, fp


def _retry(fn, retries: int = 4, delay: float = 2.0, retry_on_status: tuple[int, ...] = ()) -> object:
    last_error = None
    last_response = None
    for attempt in range(retries):
        try:
            response = fn()
        except Exception as exc:
            last_error = exc
            time.sleep(delay)
            continue
        if retry_on_status and getattr(response, "status_code", 0) in retry_on_status:
            last_response = response
            time.sleep(delay * (attempt + 1))
            continue
        return response
    if last_response is not None:
        return last_response
    if last_error is not None:
        raise last_error
    raise ImageGenerationError("request failed")


def _pow_config(user_agent: str) -> list:
    return proof_of_work.get_config(user_agent)


def _generate_requirements_answer(seed: str, difficulty: str, config: list) -> tuple[str, bool]:
    diff_len = len(difficulty)
    seed_bytes = seed.encode()
    prefix1 = (json.dumps(config[:3], separators=(",", ":"), ensure_ascii=False)[:-1] + ",").encode()
    prefix2 = ("," + json.dumps(config[4:9], separators=(",", ":"), ensure_ascii=False)[1:-1] + ",").encode()
    prefix3 = ("," + json.dumps(config[10:], separators=(",", ":"), ensure_ascii=False)[1:]).encode()
    target = bytes.fromhex(difficulty)
    for attempt in range(MAX_POW_ATTEMPTS):
        left = str(attempt).encode()
        right = str(attempt >> 1).encode()
        encoded = base64.b64encode(prefix1 + left + prefix2 + right + prefix3)
        digest = hashlib.sha3_512(seed_bytes + encoded).digest()
        if digest[:diff_len] <= target:
            return encoded.decode(), True
    fallback = "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D" + base64.b64encode(f'"{seed}"'.encode()).decode()
    return fallback, False


def _get_requirements_token(config: list) -> str:
    seed = format(random.random())
    answer, _ = _generate_requirements_answer(seed, "0fffff", config)
    return "gAAAAAC" + answer


def _generate_proof_token(seed: str, difficulty: str, user_agent: str, proof_config: Optional[list] = None) -> str:
    answer, _ = proof_of_work.get_answer_token(seed, difficulty, proof_config or _pow_config(user_agent))
    return answer


def _update_build_info_from_html(html: str) -> None:
    """从首页 HTML 动态提取 oai-client-build-number 和 oai-client-version，带 TTL 缓存"""
    global _cached_build_number, _cached_client_version, _build_info_cache_time
    if time.time() - _build_info_cache_time < _BUILD_INFO_TTL:
        return
    build_number = None
    client_version = None
    for pattern in (
        r'"buildNumber"\s*:\s*"(\d+)"',
        r'"build_number"\s*:\s*"(\d+)"',
        r'"oai-client-build-number"\s*:\s*"(\d+)"',
        r'buildNumber[\s":\x27,]+?(\d{6,})',
    ):
        m = re.search(pattern, html)
        if m:
            build_number = m.group(1)
            break
    for pattern in (
        r'"clientVersion"\s*:\s*"(prod-[0-9a-f]{30,})"',
        r'"client_version"\s*:\s*"(prod-[0-9a-f]{30,})"',
        r'"oai-client-version"\s*:\s*"(prod-[0-9a-f]{30,})"',
    ):
        m = re.search(pattern, html)
        if m:
            client_version = m.group(1)
            break
    if build_number:
        _cached_build_number = build_number
    if client_version:
        _cached_client_version = client_version
    _build_info_cache_time = time.time()


def _bootstrap(session: Session, fp: dict) -> str:
    response = _retry(lambda: session.get(BASE_URL + "/", timeout=30))
    try:
        proof_of_work.get_data_build_from_html(response.text)
    except Exception:
        pass
    _update_build_info_from_html(response.text)
    device_id = response.cookies.get("oai-did")
    if device_id:
        return device_id
    for cookie in session.cookies.jar if hasattr(session.cookies, "jar") else []:
        name = getattr(cookie, "name", getattr(cookie, "key", ""))
        if name == "oai-did":
            return cookie.value
    return str(fp.get("oai-device-id") or uuid.uuid4())


def _conversation_init(session: Session, access_token: str, device_id: str) -> str:
    try:
        response = _retry(
            lambda: session.post(
                BASE_URL + "/backend-api/conversation/init",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "oai-device-id": device_id,
                    "content-type": "application/json",
                    "oai-client-build-number": _cached_build_number,
                    "oai-client-version": _cached_client_version,
                },
                json={},
                timeout=20,
            ),
            retries=2,
        )
        if response.ok:
            payload = response.json() or {}
            cid = str(payload.get("conversation_id") or payload.get("id") or "")
            if cid:
                return cid
    except Exception:
        pass
    return str(uuid.uuid4())


def _chat_requirements(session: Session, access_token: str, device_id: str) -> tuple[str, Optional[dict]]:
    config = _pow_config(USER_AGENT)
    response = _retry(
        lambda: session.post(
            BASE_URL + "/backend-api/sentinel/chat-requirements",
            headers={
                "Authorization": f"Bearer {access_token}",
                "oai-device-id": device_id,
                "content-type": "application/json",
            },
            json={"p": _get_requirements_token(config)},
            timeout=30,
        ),
        retries=4,
    )
    if not response.ok:
        raise ImageGenerationError(response.text[:400] or f"chat-requirements failed: {response.status_code}")
    payload = response.json()
    return payload["token"], payload.get("proofofwork") or {}


def _conversation_prepare(
    session: Session,
    access_token: str,
    device_id: str,
    conversation_id: str,
    parent_message_id: str,
    model: str,
    conduit_token: Optional[str] = None,
    client_prepare_state: str = "none",
) -> Optional[str]:
    """Call f/conversation/prepare to obtain a conduit_token for routing.

    Returns the conduit_token string, or None on failure.
    """
    session_id = str(uuid.uuid4())
    turn_trace_id = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "*/*",
        "content-type": "application/json",
        "oai-device-id": device_id,
        "oai-language": "zh-CN",
        "oai-session-id": session_id,
        "oai-client-build-number": _cached_build_number,
        "oai-client-version": _cached_client_version,
        "origin": BASE_URL,
        "referer": BASE_URL + "/",
        "x-oai-turn-trace-id": turn_trace_id,
        "x-openai-target-path": "/backend-api/f/conversation/prepare",
        "x-openai-target-route": "/backend-api/f/conversation/prepare",
    }
    if conduit_token:
        headers["x-conduit-token"] = conduit_token
    body = {
        "action": "next",
        "fork_from_shared_post": False,
        "conversation_id": conversation_id,
        "parent_message_id": parent_message_id,
        "model": model,
        "client_prepare_state": client_prepare_state,
        "timezone_offset_min": -480,
        "timezone": "Asia/Shanghai",
        "conversation_mode": {"kind": "primary_assistant"},
        "system_hints": ["reason"],
        "supports_buffering": True,
        "supported_encodings": ["v1"],
        "client_contextual_info": {"app_name": "chatgpt.com"},
    }
    try:
        response = _retry(
            lambda: session.post(
                BASE_URL + "/backend-api/f/conversation/prepare",
                headers=headers,
                json=body,
                timeout=20,
            ),
            retries=2,
        )
        if response.ok:
            payload = response.json() or {}
            return payload.get("conduit_token") or None
    except Exception:
        pass
    return None


def _prepare_picture_conversation(
    session: Session,
    access_token: str,
    device_id: str,
    parent_message_id: str,
    prompt: str,
    model: str,
) -> Optional[str]:
    session_id = str(uuid.uuid4())
    turn_trace_id = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "*/*",
        "content-type": "application/json",
        "oai-device-id": device_id,
        "oai-language": "zh-CN",
        "oai-session-id": session_id,
        "oai-client-build-number": _cached_build_number,
        "oai-client-version": _cached_client_version,
        "origin": BASE_URL,
        "referer": BASE_URL + "/",
        "x-oai-turn-trace-id": turn_trace_id,
        "x-openai-target-path": "/backend-api/f/conversation/prepare",
        "x-openai-target-route": "/backend-api/f/conversation/prepare",
    }
    body = {
        "action": "next",
        "fork_from_shared_post": False,
        "parent_message_id": parent_message_id,
        "model": model,
        "client_prepare_state": "success",
        "timezone_offset_min": -480,
        "timezone": "Asia/Shanghai",
        "conversation_mode": {"kind": "primary_assistant"},
        "system_hints": ["picture_v2"],
        "partial_query": {
            "id": str(uuid.uuid4()),
            "author": {"role": "user"},
            "content": {"content_type": "text", "parts": [prompt]},
        },
        "supports_buffering": True,
        "supported_encodings": ["v1"],
        "client_contextual_info": {"app_name": "chatgpt.com"},
    }
    try:
        response = _retry(
            lambda: session.post(
                BASE_URL + "/backend-api/f/conversation/prepare",
                headers=headers,
                json=body,
                timeout=20,
            ),
            retries=2,
        )
        if response.ok:
            payload = response.json() or {}
            return payload.get("conduit_token") or None
    except Exception:
        pass
    return None


def is_token_invalid_error(message: str) -> bool:
    text = str(message or "").lower()
    return (
        "token_invalidated" in text
        or "token_revoked" in text
        or "authentication token has been invalidated" in text
        or "invalidated oauth token" in text
    )


def image_stream_error_message(message: object) -> str:
    text = str(message or "").strip()
    lower = text.lower()
    if any(marker in lower for marker in IMAGE_UPSTREAM_CONNECTION_ERROR_MARKERS):
        return "upstream image connection failed, please retry later"
    return text or "image generation failed"


def is_retryable_image_output_error(message: str) -> bool:
    text = str(message or "").strip().lower()
    return text in {
        "no image returned from upstream",
        "failed to get download url",
    }


def is_rate_limited_image_error(message: str) -> bool:
    text = str(message or "").strip().lower()
    return (
        "429" in text
        or "rate limit" in text
        or "too many requests" in text
        or "too many retries" in text
    )


def is_conversation_forbidden_error(message: str) -> bool:
    text = str(message or "").lower()
    return (
        "conversation failed: 403" in text
        or "f/conversation failed: 403" in text
        or "conversation failed: 404" in text
        or "f/conversation failed: 404" in text
    )


def _is_free_account(access_token: str) -> bool:
    account = account_service.get_account(access_token) or {}
    return str(account.get("type") or "Free").strip() == "Free"


def _is_codex_image_account(access_token: str) -> bool:
    account = account_service.get_account(access_token) or {}
    account_type = str(account.get("type") or "").strip()
    return account_type in {"Plus", "Team", "Pro"}


def _ensure_codex_image_account(access_token: str, requested_model: str) -> None:
    if str(requested_model or "").strip() != CODEX_IMAGE_MODEL:
        return
    if not _is_codex_image_account(access_token):
        raise ImageGenerationError("codex-gpt-image-2 requires a Plus, Team, or Pro account")


def _upload_image(session: Session, access_token: str, device_id: str, image_data: bytes, file_name: str, mime_type: str) -> str:
    response = _retry(
        lambda: session.post(
            BASE_URL + "/backend-api/files",
            headers={
                "Authorization": f"Bearer {access_token}",
                "oai-device-id": device_id,
                "content-type": "application/json",
            },
            json={
                "file_name": file_name,
                "file_size": len(image_data),
                "use_case": "multimodal",
                "timezone_offset_min": -480,
                "reset_rate_limits": False,
            },
            timeout=30,
        ),
        retries=3,
    )
    if not response.ok:
        raise ImageGenerationError(f"file upload init failed: {response.status_code} {response.text[:200]}")
    payload = response.json()
    upload_url = payload.get("upload_url") or ""
    file_id = payload.get("file_id") or ""
    if not upload_url or not file_id:
        raise ImageGenerationError("file upload init returned no upload_url or file_id")

    put_resp = _retry(
        lambda: session.put(
            upload_url,
            headers={
                "Content-Type": mime_type,
                "x-ms-blob-type": "BlockBlob",
                "x-ms-version": "2020-04-08",
            },
            data=image_data,
            timeout=60,
        ),
        retries=3,
    )
    if not (200 <= put_resp.status_code < 300):
        raise ImageGenerationError(f"file upload PUT failed: {put_resp.status_code}")

    process_resp = _retry(
        lambda: session.post(
            BASE_URL + "/backend-api/files/process_upload_stream",
            headers={
                "Authorization": f"Bearer {access_token}",
                "oai-device-id": device_id,
                "content-type": "application/json",
            },
            json={
                "file_id": file_id,
                "use_case": "multimodal",
                "index_for_retrieval": False,
                "file_name": file_name,
                "entry_surface": "chat_composer",
            },
            timeout=30,
        ),
        retries=3,
    )
    if not process_resp.ok:
        raise ImageGenerationError(f"file process failed: {process_resp.status_code}")
    return file_id


def _send_edit_conversation(
    session: Session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token: Optional[str],
    parent_message_id: str,
    prompt: str,
    model: str,
    images: list[EditInputImage],
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
    image_parts, attachments = _build_edit_input_payload(images)
    body: dict = {
        "action": "next",
        "messages": [
            {
                "id": str(uuid.uuid4()),
                "author": {"role": "user"},
                "create_time": time.time(),
                "content": {
                    "content_type": "multimodal_text",
                    "parts": [*image_parts, prompt],
                },
                "metadata": {
                    "attachments": attachments,
                    "selected_github_repos": [],
                    "selected_all_github_repos": False,
                    "system_hints": ["picture_v2"],
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
        "system_hints": ["picture_v2"],
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
    if conversation_id:
        body["conversation_id"] = conversation_id
    return _request_image_stream(
        lambda: session.post(
            BASE_URL + "/backend-api/conversation",
            headers=headers,
            json=body,
            stream=True,
            timeout=180,
        ),
        retries=3,
        fallback_error="conversation failed",
    )


def _build_picture_v2_edit_input_payload(images: list[EditInputImage]) -> tuple[list[dict], list[dict]]:
    image_parts = [
        {
            "content_type": "image_asset_pointer",
            "asset_pointer": f"file-service://{image.file_id}",
            "size_bytes": len(image.data),
            "width": image.width,
            "height": image.height,
        }
        for image in images
    ]
    attachments = [
        {
            "id": image.file_id,
            "size": len(image.data),
            "name": image.file_name,
            "mimeType": image.mime_type,
            "mime_type": image.mime_type,
            "width": image.width,
            "height": image.height,
        }
        for image in images
    ]
    return image_parts, attachments


def _request_image_stream(request_fn, *, retries: int, fallback_error: str):
    try:
        response = _retry(request_fn, retries=retries)
    except Exception as exc:
        raise ImageGenerationError(image_stream_error_message(exc)) from exc
    if not response.ok:
        error_text = str(response.text[:400] or "").strip()
        if not error_text:
            error_text = f"{fallback_error}: {getattr(response, 'status_code', 'unknown')}"
        raise ImageGenerationError(
            image_stream_error_message(error_text),
        )
    return response


def _build_regular_picture_v2_body(
    prompt: str,
    parent_message_id: str,
    model: str,
    images: Optional[list[EditInputImage]] = None,
) -> dict:
    content: dict = {"content_type": "text", "parts": [prompt]}
    metadata: dict = {
        "selected_github_repos": [],
        "selected_all_github_repos": False,
        "system_hints": ["picture_v2"],
        "serialization_metadata": {"custom_symbol_offsets": []},
    }
    if images:
        image_parts, attachments = _build_picture_v2_edit_input_payload(images)
        content = {
            "content_type": "multimodal_text",
            "parts": [*image_parts, prompt],
        }
        metadata["attachments"] = attachments

    return {
        "action": "next",
        "messages": [
            {
                "id": str(uuid.uuid4()),
                "author": {"role": "user"},
                "create_time": time.time(),
                "content": content,
                "metadata": metadata,
            }
        ],
        "parent_message_id": parent_message_id,
        "model": model,
        "timezone_offset_min": -480,
        "timezone": "Asia/Shanghai",
        "conversation_mode": {"kind": "primary_assistant"},
        "enable_message_followups": True,
        "system_hints": ["picture_v2"],
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


def _send_regular_generation_conversation(
    session: Session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token: Optional[str],
    parent_message_id: str,
    prompt: str,
    model: str,
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
        "x-oai-turn-trace-id": turn_trace_id,
        "openai-sentinel-chat-requirements-token": chat_token,
        "x-conduit-token": conduit_token,
    }
    if proof_token:
        headers["openai-sentinel-proof-token"] = proof_token
    body = _build_regular_picture_v2_body(prompt, parent_message_id, model)
    return _request_image_stream(
        lambda: session.post(
            BASE_URL + "/backend-api/f/conversation",
            headers=headers,
            json=body,
            stream=True,
            timeout=180,
        ),
        retries=2,
        fallback_error="f/conversation failed",
    )


def _send_regular_edit_conversation(
    session: Session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token: Optional[str],
    parent_message_id: str,
    prompt: str,
    model: str,
    images: list[EditInputImage],
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
        "x-oai-turn-trace-id": turn_trace_id,
        "openai-sentinel-chat-requirements-token": chat_token,
        "x-conduit-token": conduit_token,
    }
    if proof_token:
        headers["openai-sentinel-proof-token"] = proof_token
    body = _build_regular_picture_v2_body(prompt, parent_message_id, model, images)
    return _request_image_stream(
        lambda: session.post(
            BASE_URL + "/backend-api/f/conversation",
            headers=headers,
            json=body,
            stream=True,
            timeout=180,
        ),
        retries=2,
        fallback_error="f/conversation failed",
    )


def _send_conversation(
    session: Session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token: Optional[str],
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
    body: dict = {
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
                    "system_hints": ["picture_v2"],
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
        "system_hints": ["picture_v2"],
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
    if conversation_id:
        body["conversation_id"] = conversation_id
    return _request_image_stream(
        lambda: session.post(
            BASE_URL + "/backend-api/conversation",
            headers=headers,
            json=body,
            stream=True,
            timeout=180,
        ),
        retries=3,
        fallback_error="conversation failed",
    )


def _send_thinking_conversation(
    session: Session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token: Optional[str],
    parent_message_id: str,
    prompt: str,
    model: str,
    conduit_token: str,
    conversation_id: str = "",
):
    """Send a conversation request via f/conversation for thinking (reason) mode."""
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
        "x-conduit-token": conduit_token,
    }
    if proof_token:
        headers["openai-sentinel-proof-token"] = proof_token
    body: dict = {
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
                    "system_hints": ["reason"],
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
        "system_hints": ["reason"],
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
    # f/conversation 首次请求不传 conversation_id，让服务端自己创建
    return _request_image_stream(
        lambda: session.post(
            BASE_URL + "/backend-api/f/conversation",
            headers=headers,
            json=body,
            stream=True,
            timeout=180,
        ),
        retries=2,
        fallback_error="f/conversation failed",
    )


def _parse_sse(response) -> dict:
    file_ids: list[str] = []
    conversation_id = ""
    latest_text = ""
    resume_conduit_token = ""
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
        if not conversation_id:
            matched_conversation_id = re.search(r'"conversation_id"\s*:\s*"([^"]+)"', payload)
            if matched_conversation_id:
                conversation_id = matched_conversation_id.group(1)
        for prefix, stored_prefix in (("file-service://", ""), ("sediment://", "sed:")):
            start = 0
            while True:
                index = payload.find(prefix, start)
                if index < 0:
                    break
                start = index + len(prefix)
                tail = payload[start:]
                file_id = []
                for char in tail:
                    if char.isalnum() or char in "_-":
                        file_id.append(char)
                    else:
                        break
                if file_id:
                    value = stored_prefix + "".join(file_id)
                    if value not in file_ids:
                        file_ids.append(value)
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        conversation_id = str(obj.get("conversation_id") or conversation_id)
        if obj.get("type") == "resume_conversation_token":
            conversation_id = str(obj.get("conversation_id") or conversation_id)
            token_val = obj.get("token")
            if token_val and isinstance(token_val, str):
                resume_conduit_token = token_val
        elif obj.get("type") in {"message_marker", "message_stream_complete"}:
            conversation_id = str(obj.get("conversation_id") or conversation_id)
        data = obj.get("v")
        if isinstance(data, dict):
            conversation_id = str(data.get("conversation_id") or conversation_id)
        message = obj.get("message") or {}
        content = message.get("content") or {}
        if content.get("content_type") == "text":
            parts = content.get("parts") or []
            if parts:
                part_text = str(parts[0] or "").strip()
                if part_text:
                    latest_text = part_text
    return {
        "conversation_id": conversation_id,
        "file_ids": file_ids,
        "text": latest_text,
        "resume_conduit_token": resume_conduit_token,
    }


def _collect_asset_pointers(value: object, file_ids: list[str]) -> None:
    if isinstance(value, str):
        for hit in re.findall(r"file-service://([A-Za-z0-9_-]+)", value):
            if hit not in file_ids:
                file_ids.append(hit)
        for hit in re.findall(r"sediment://([A-Za-z0-9_-]+)", value):
            sediment_id = "sed:" + hit
            if sediment_id not in file_ids:
                file_ids.append(sediment_id)
        return
    if isinstance(value, dict):
        pointer = str(value.get("asset_pointer") or "")
        if pointer:
            _collect_asset_pointers(pointer, file_ids)
        for nested_value in value.values():
            _collect_asset_pointers(nested_value, file_ids)
        return
    if isinstance(value, list):
        for item in value:
            _collect_asset_pointers(item, file_ids)


def _extract_image_ids(mapping: dict) -> list[str]:
    file_ids: list[str] = []
    for node in mapping.values():
        message = (node or {}).get("message") or {}
        _collect_asset_pointers(message, file_ids)
    return file_ids


def _poll_image_ids(
    session: Session,
    access_token: str,
    device_id: str,
    conversation_id: str,
    input_file_ids: set[str] | None = None,
) -> list[str]:
    started = time.time()
    normalized_input_file_ids = input_file_ids or set()
    while time.time() - started < 180:
        response = _retry(
            lambda: session.get(
                f"{BASE_URL}/backend-api/conversation/{conversation_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "oai-device-id": device_id,
                    "accept": "*/*",
                },
                timeout=30,
            ),
            retries=2,
            retry_on_status=(429, 502, 503, 504),
        )
        if response.status_code != 200:
            time.sleep(3)
            continue
        try:
            payload = response.json()
        except Exception:
            time.sleep(3)
            continue
        file_ids = _extract_image_ids(payload.get("mapping") or {})
        output_file_ids = _filter_output_file_ids(file_ids, normalized_input_file_ids)
        if output_file_ids:
            return output_file_ids
        time.sleep(3)
    return []


def _canonicalize_file_id(file_id: str) -> str:
    value = str(file_id or "")
    return value[4:] if value.startswith("sed:") else value


def _is_invalid_output_file_id(file_id: str) -> bool:
    return _canonicalize_file_id(file_id).strip().lower() == "file_upload"


def _filter_output_file_ids(file_ids: list[str], input_file_ids: set[str]) -> list[str]:
    canonical_input_ids = {_canonicalize_file_id(file_id) for file_id in input_file_ids}
    return [
        file_id
        for file_id in file_ids
        if not _is_invalid_output_file_id(file_id) and _canonicalize_file_id(file_id) not in canonical_input_ids
    ]


def _collect_edit_output(
    session: Session,
    access_token: str,
    device_id: str,
    parsed: dict,
    input_file_ids: set[str],
) -> tuple[str, list[str], str]:
    actual_conversation_id = str(parsed.get("conversation_id") or "")
    file_ids = _filter_output_file_ids(parsed.get("file_ids") or [], input_file_ids)
    response_text = str(parsed.get("text") or "").strip()
    if actual_conversation_id and not file_ids:
        file_ids = _poll_image_ids(
            session,
            access_token,
            device_id,
            actual_conversation_id,
            input_file_ids,
        )
    return actual_conversation_id, file_ids, response_text


def _fetch_download_url(session: Session, access_token: str, device_id: str, conversation_id: str, file_id: str) -> str:
    is_sediment = file_id.startswith("sed:")
    raw_id = file_id[4:] if is_sediment else file_id
    # All generated/edited output files use /files/download/ regardless of sed: prefix
    # (HAR confirms: both sediment:// and file-service:// outputs use /files/download/{id}?conversation_id=...)
    endpoint = f"{BASE_URL}/backend-api/files/download/{raw_id}"
    if conversation_id:
        endpoint += f"?conversation_id={conversation_id}&inline=false"
    response = session.get(
        endpoint,
        headers={
            "Authorization": f"Bearer {access_token}",
            "oai-device-id": device_id,
        },
        timeout=30,
    )
    if not response.ok:
        return ""
    return str((response.json() or {}).get("download_url") or "")


def _format_download_failure(response) -> str:
    status_code = getattr(response, "status_code", 0)
    response_text = str(getattr(response, "text", "") or "").strip()
    if response_text:
        return f"download image failed: HTTP {status_code}: {response_text[:200]}"
    return f"download image failed: HTTP {status_code}"


def _fetch_image_bytes(session: Session, download_url: str) -> bytes:
    last_response = None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.get(download_url, timeout=IMAGE_DOWNLOAD_TIMEOUT_SECONDS)
        except Exception as exc:
            last_error = exc
            if attempt == 2:
                break
            time.sleep(attempt + 1)
            continue
        last_response = response
        if response.ok and response.content:
            return response.content
        should_retry = (
            response.ok and not response.content
        ) or response.status_code in IMAGE_DOWNLOAD_RETRY_STATUSES
        if not should_retry or attempt == 2:
            break
        time.sleep(attempt + 1)
    if last_response is not None:
        raise ImageGenerationError(_format_download_failure(last_response))
    if last_error is not None:
        raise ImageGenerationError(image_stream_error_message(last_error)) from last_error
    raise ImageGenerationError(_format_download_failure(last_response))


def _download_as_base64(session: Session, download_url: str) -> str:
    return base64.b64encode(_fetch_image_bytes(session, download_url)).decode("ascii")


def _guess_mime_type_from_format(output_format: str | None) -> str:
    normalized = str(output_format or "png").strip().lower() or "png"
    return IMAGE_OUTPUT_MIME_TYPES.get(normalized, "image/png")


def _encode_image_data_url(image_data: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(image_data).decode("ascii")
    return f"data:{mime_type or 'image/png'};base64,{encoded}"


def _build_codex_response_input(prompt: str, images: list[tuple[bytes, str, str]] | None = None) -> list[dict[str, object]]:
    if not images:
        return [{"role": "user", "content": prompt}]
    content: list[dict[str, str]] = [{"type": "input_text", "text": prompt}]
    for image_data, _, mime_type in images:
        content.append(
            {
                "type": "input_image",
                "image_url": _encode_image_data_url(image_data, mime_type),
            }
        )
    return [{"role": "user", "content": content}]


def _estimate_codex_inline_request_bytes(prompt: str, images: list[tuple[bytes, str, str]] | None = None) -> int:
    input_items = _build_codex_response_input(prompt, images)
    payload = json.dumps(input_items, ensure_ascii=False, separators=(",", ":"))
    return len(payload.encode("utf-8"))


def _build_codex_image_tool(image_options: ImageRequestOptions | None) -> dict[str, object]:
    output_format = str((image_options.output_format if image_options is not None else "png") or "png").strip().lower() or "png"
    tool: dict[str, object] = {
        "type": "image_generation",
        "output_format": output_format,
    }
    exact_size = parse_exact_image_size(image_options.size if image_options is not None else None)
    if exact_size is not None:
        tool["size"] = f"{exact_size[0]}x{exact_size[1]}"
    return tool


def _build_codex_response_payload(
    prompt: str,
    *,
    image_options: ImageRequestOptions | None,
    images: list[tuple[bytes, str, str]] | None = None,
) -> dict[str, object]:
    return {
        "model": CODEX_RESPONSE_MODEL,
        "input": _build_codex_response_input(prompt, images),
        "tools": [_build_codex_image_tool(image_options)],
        "instructions": CODEX_RESPONSE_INSTRUCTIONS,
        "tool_choice": CODEX_RESPONSE_TOOL_CHOICE,
        "stream": True,
        "store": False,
    }


def _build_codex_response_headers(access_token: str) -> dict[str, str]:
    account = account_service.get_account(access_token) or {}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "accept": "text/event-stream",
        "content-type": "application/json",
        "user-agent": CODEX_RESPONSE_USER_AGENT,
        "version": CODEX_RESPONSE_VERSION,
        "originator": "codex_cli_rs",
        "session_id": CODEX_RESPONSE_SESSION_ID,
    }
    chatgpt_account_id = str(
        account.get("chatgpt_account_id")
        or account.get("account_id")
        or account.get("user_id")
        or ""
    ).strip()
    if chatgpt_account_id:
        headers["chatgpt-account-id"] = chatgpt_account_id
    return headers


def _iter_codex_response_events(response) -> Iterator[dict[str, Any]]:
    for raw_line in response.iter_lines():
        if not raw_line:
            continue
        line = raw_line.decode("utf-8", errors="ignore") if isinstance(raw_line, bytes) else str(raw_line)
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ImageGenerationError("invalid SSE payload from codex responses") from exc
        if isinstance(event, dict):
            yield event


def _extract_codex_response_error(event: dict[str, Any]) -> str:
    for candidate in (
        event.get("error"),
        (event.get("response") or {}).get("error") if isinstance(event.get("response"), dict) else None,
        (event.get("item") or {}).get("error") if isinstance(event.get("item"), dict) else None,
    ):
        if isinstance(candidate, dict):
            message = str(candidate.get("message") or candidate.get("code") or "").strip()
            if message:
                return message
        elif candidate:
            message = str(candidate).strip()
            if message:
                return message
    return "codex image generation failed"


def _parse_codex_response_events(events: Iterator[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    image_item: dict[str, Any] = {}
    response_payload: dict[str, Any] = {}
    for event in events:
        event_type = str(event.get("type") or "").strip()
        if event_type == "response.output_item.done":
            item = event.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "image_generation_call" and item.get("result"):
                image_item = item
        elif event_type == "response.completed":
            payload = event.get("response") or {}
            if isinstance(payload, dict):
                response_payload = payload
                for item in payload.get("output") or []:
                    if isinstance(item, dict) and item.get("type") == "image_generation_call" and item.get("result"):
                        image_item = item
        elif event_type in {"response.failed", "response.incomplete", "error"}:
            raise ImageGenerationError(_extract_codex_response_error(event))

    if not image_item:
        raise ImageGenerationError("codex responses did not return image output")
    return image_item, response_payload


def _request_codex_response_stream(
    session: Session,
    access_token: str,
    payload: dict[str, object],
    *,
    allow_fallback: bool = True,
):
    response = _retry(
        lambda: session.post(
            BASE_URL + "/backend-api/codex/responses",
            headers=_build_codex_response_headers(access_token),
            json=payload,
            timeout=300,
            stream=True,
        ),
        retries=2,
    )
    if response.ok:
        return response
    fallback_tools = payload.get("tools") if isinstance(payload.get("tools"), list) else []
    should_retry_with_minimal_tool = (
        allow_fallback
        and response.status_code in {400, 422}
        and any(
            isinstance(tool, dict)
            and (
                tool.get("size")
                or str(tool.get("output_format") or "").strip().lower() not in {"", "png"}
            )
            for tool in fallback_tools
        )
    )
    if should_retry_with_minimal_tool:
        minimal_payload = dict(payload)
        minimal_payload["tools"] = [{"type": "image_generation", "output_format": "png"}]
        print("[image-codex] native tool payload rejected, retry with minimal image_generation tool")
        return _request_codex_response_stream(
            session,
            access_token,
            minimal_payload,
            allow_fallback=False,
        )
    if response.status_code >= 400:
        print(f"[image-codex] responses failed status={response.status_code} body={response.text[:400]}")
    raise ImageGenerationError(response.text[:400] or f"codex responses failed: {response.status_code}")


def _build_codex_result_data(
    prompt: str,
    response_format: str,
    *,
    image_item: dict[str, Any],
    response_payload: dict[str, Any],
    image_options: ImageRequestOptions | None,
    base_url: str | None,
) -> tuple[int, dict[str, object]]:
    image_b64 = str(image_item.get("result") or "").strip()
    if not image_b64:
        raise ImageGenerationError("codex responses did not return image base64 result")
    try:
        original_bytes = base64.b64decode(image_b64)
    except Exception as exc:
        raise ImageGenerationError("codex responses returned invalid image data") from exc
    image_bytes, mime_type = _process_output_image(original_bytes, image_options)
    output_format = str((image_options.output_format if image_options is not None else "png") or "png").strip().lower() or "png"
    result_data: dict[str, object] = {
        "revised_prompt": str(image_item.get("revised_prompt") or prompt).strip() or prompt,
        "generation_route": "regular",
        "mime_type": mime_type or _guess_mime_type_from_format(str(image_item.get("output_format") or "")),
    }
    if response_format == "url":
        result_data["url"] = _save_processed_image(image_bytes, output_format, base_url)
    else:
        result_data["b64_json"] = base64.b64encode(image_bytes).decode("ascii")
    created = int(response_payload.get("created_at") or time.time())
    return created, result_data


def _run_codex_image_task(
    session: Session,
    access_token: str,
    prompt: str,
    *,
    response_format: str,
    image_options: ImageRequestOptions | None,
    base_url: str | None,
    images: list[tuple[bytes, str, str]] | None = None,
) -> dict[str, object]:
    if images and _estimate_codex_inline_request_bytes(prompt, images) > MAX_CODEX_INLINE_REQUEST_BYTES:
        raise ImageGenerationError("codex inline edit payload is too large, please use smaller reference images")
    payload = _build_codex_response_payload(
        prompt,
        image_options=image_options,
        images=images,
    )
    response = _request_codex_response_stream(session, access_token, payload)
    image_item, response_payload = _parse_codex_response_events(_iter_codex_response_events(response))
    created, result_data = _build_codex_result_data(
        prompt,
        response_format,
        image_item=image_item,
        response_payload=response_payload,
        image_options=image_options,
        base_url=base_url,
    )
    return {
        "created": created,
        "data": [result_data],
        "response": response_payload,
    }


def _normalize_image_for_output(image: Image.Image, output_format: str) -> Image.Image:
    normalized_format = str(output_format or "png").strip().lower() or "png"
    if normalized_format == "jpeg":
        if image.mode not in {"RGB", "L"}:
            rgba_image = image.convert("RGBA")
            background = Image.new("RGB", rgba_image.size, (255, 255, 255))
            background.paste(rgba_image, mask=rgba_image.getchannel("A"))
            return background
        return image.convert("RGB") if image.mode != "RGB" else image
    if normalized_format == "webp":
        return image.convert("RGBA" if "A" in image.getbands() else "RGB")
    if image.mode in {"P", "LA"}:
        return image.convert("RGBA")
    return image


def _process_output_image(image_bytes: bytes, image_options: ImageRequestOptions | None) -> tuple[bytes, str]:
    if image_options is None:
        return image_bytes, "image/png"

    output_format = str(image_options.output_format or "png").strip().lower() or "png"
    requested_size = parse_exact_image_size(image_options.size)
    if requested_size is None and output_format == "png":
        return image_bytes, IMAGE_OUTPUT_MIME_TYPES["png"]

    with Image.open(io.BytesIO(image_bytes)) as source_image:
        working_image = source_image.copy()
    if requested_size is not None and working_image.size != requested_size:
        working_image = working_image.resize(requested_size, Image.Resampling.LANCZOS)
    working_image = _normalize_image_for_output(working_image, output_format)

    buffer = io.BytesIO()
    save_kwargs: dict[str, object] = {}
    if output_format in {"jpeg", "webp"}:
        compression = image_options.compression
        save_kwargs["quality"] = max(1, 100 - compression) if compression is not None else 95
    if output_format == "webp":
        save_kwargs["method"] = 6
    working_image.save(buffer, format=output_format.upper(), **save_kwargs)
    return buffer.getvalue(), IMAGE_OUTPUT_MIME_TYPES[output_format]


def _save_processed_image(image_bytes: bytes, output_format: str, base_url: str | None = None) -> str:
    file_hash = hashlib.md5(image_bytes).hexdigest()
    timestamp = int(time.time())
    extension = IMAGE_OUTPUT_EXTENSIONS[output_format]
    filename = f"{timestamp}_{file_hash}.{extension}"
    relative_dir = Path(time.strftime("%Y"), time.strftime("%m"), time.strftime("%d"))

    file_path = config.images_dir / relative_dir / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(image_bytes)

    return f"{(base_url or config.base_url)}/images/{relative_dir.as_posix()}/{filename}"


def _resolve_upstream_model(access_token: str, requested_model: str) -> tuple[str, bool]:
    """返回 (upstream_model, use_thinking_mode)"""
    requested_model = str(requested_model or "").strip() or "gpt-image-1"
    is_free_account = _is_free_account(access_token)

    if requested_model == CODEX_IMAGE_MODEL:
        return CODEX_IMAGE_MODEL, False
    if requested_model == "gpt-image-think":
        # 带思考的图片生成：使用 gpt-5-3（付费账户）或 auto（免费）
        upstream = "auto" if is_free_account else "gpt-5-3"
        return upstream, True
    if requested_model in {"gpt-image-1", "gpt-image-2", "gpt-image"}:
        return "gpt-5-3", False
    return (str(requested_model or DEFAULT_MODEL).strip() or DEFAULT_MODEL), False


def _resolve_upstream_edit_model(requested_model: str) -> str:
    requested_model = str(requested_model or "").strip() or "gpt-image-2"
    if requested_model == CODEX_IMAGE_MODEL:
        return CODEX_IMAGE_MODEL
    if requested_model in {"gpt-image-1", "gpt-image-2", "gpt-image-think", "gpt-image"}:
        return "gpt-5-3"
    return requested_model or DEFAULT_MODEL


def _build_edit_input_payload(images: list[EditInputImage]) -> tuple[list[dict], list[dict]]:
    image_parts = [
        {
            "content_type": "image_asset_pointer",
            "asset_pointer": f"sediment://{image.file_id}",
            "size_bytes": len(image.data),
            "width": image.width,
            "height": image.height,
        }
        for image in images
    ]
    attachments = [
        {
            "id": image.file_id,
            "size": len(image.data),
            "name": image.file_name,
            "mime_type": image.mime_type,
            "width": image.width,
            "height": image.height,
            "source": "local",
            "is_big_paste": False,
        }
        for image in images
    ]
    return image_parts, attachments


def _build_image_result_data(
    prompt: str,
    response_format: str,
    route: str,
    *,
    image_options: ImageRequestOptions | None,
    session: Session,
    download_url: str,
    base_url: str | None,
) -> dict:
    original_bytes = _fetch_image_bytes(session, download_url)
    image_bytes, mime_type = _process_output_image(original_bytes, image_options)
    output_format = str((image_options.output_format if image_options is not None else "png") or "png").strip().lower() or "png"
    result_data = {"revised_prompt": prompt, "generation_route": route, "mime_type": mime_type}
    if response_format == "url":
        result_data["url"] = _save_processed_image(image_bytes, output_format, base_url)
    else:
        result_data["b64_json"] = base64.b64encode(image_bytes).decode("ascii")
    return result_data


def _run_thinking_mode(
    session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token,
    parent_message_id: str,
    prompt: str,
    upstream_model: str,
    conversation_id: str,
) -> dict:
    """执行 thinking 模式图片生成（f/conversation + conduit）；失败时抛出异常，由调用方回退。"""
    # 第一步：获取初始 conduit_token
    conduit_token = _conversation_prepare(
        session,
        access_token,
        device_id,
        conversation_id=conversation_id,
        parent_message_id=parent_message_id,
        model=upstream_model,
        conduit_token=None,
        client_prepare_state="none",
    )
    if not conduit_token:
        raise ImageGenerationError("thinking mode: f/conversation/prepare returned no conduit_token")

    response = _send_thinking_conversation(
        session,
        access_token,
        device_id,
        chat_token,
        proof_token,
        parent_message_id,
        prompt,
        upstream_model,
        conduit_token=conduit_token,
        # f/conversation 首次不传 conversation_id，服务端自己创建
    )
    return _parse_sse(response)


def _run_regular_generation_mode(
    session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token,
    parent_message_id: str,
    prompt: str,
    upstream_model: str,
) -> dict:
    conduit_token = _prepare_picture_conversation(
        session,
        access_token,
        device_id,
        parent_message_id,
        prompt,
        upstream_model,
    )
    if not conduit_token:
        raise ImageGenerationError("regular image mode: f/conversation/prepare returned no conduit_token")

    response = _send_regular_generation_conversation(
        session,
        access_token,
        device_id,
        chat_token,
        proof_token,
        parent_message_id,
        prompt,
        upstream_model,
        conduit_token=conduit_token,
    )
    return _parse_sse(response)


def _run_legacy_regular_generation_mode(
    session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token,
    parent_message_id: str,
    prompt: str,
    upstream_model: str,
    conversation_id: str,
) -> dict:
    try:
        response = _send_conversation(
            session,
            access_token,
            device_id,
            chat_token,
            proof_token,
            parent_message_id,
            prompt,
            upstream_model,
            conversation_id=conversation_id,
        )
    except ImageGenerationError as exc:
        if conversation_id and is_conversation_forbidden_error(str(exc)):
            print("[image-upstream] legacy regular generation rejected existing conversation, retry without conversation_id")
            response = _send_conversation(
                session,
                access_token,
                device_id,
                chat_token,
                proof_token,
                parent_message_id,
                prompt,
                upstream_model,
                conversation_id="",
            )
        else:
            raise
    return _parse_sse(response)


def _run_regular_edit_mode(
    session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token,
    parent_message_id: str,
    prompt: str,
    upstream_model: str,
    images: list[EditInputImage],
) -> dict:
    conduit_token = _prepare_picture_conversation(
        session,
        access_token,
        device_id,
        parent_message_id,
        prompt,
        upstream_model,
    )
    if not conduit_token:
        raise ImageGenerationError("regular image mode: f/conversation/prepare returned no conduit_token")

    response = _send_regular_edit_conversation(
        session,
        access_token,
        device_id,
        chat_token,
        proof_token,
        parent_message_id,
        prompt,
        upstream_model,
        images,
        conduit_token=conduit_token,
    )
    return _parse_sse(response)


def _run_legacy_regular_edit_mode(
    session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token,
    parent_message_id: str,
    prompt: str,
    upstream_model: str,
    images: list[EditInputImage],
    conversation_id: str,
) -> dict:
    try:
        response = _send_edit_conversation(
            session,
            access_token,
            device_id,
            chat_token,
            proof_token,
            parent_message_id,
            prompt,
            upstream_model,
            images,
            conversation_id=conversation_id,
        )
    except ImageGenerationError as exc:
        if conversation_id and is_conversation_forbidden_error(str(exc)):
            print("[image-edit-upstream] legacy regular edit rejected existing conversation, retry without conversation_id")
            response = _send_edit_conversation(
                session,
                access_token,
                device_id,
                chat_token,
                proof_token,
                parent_message_id,
                prompt,
                upstream_model,
                images,
                conversation_id="",
            )
        else:
            raise
    return _parse_sse(response)


def generate_image_result(
    access_token: str,
    prompt: str,
    model: str = DEFAULT_MODEL,
    response_format: str = "b64_json",
    base_url: str = None,
    *,
    image_options: ImageRequestOptions | None = None,
) -> dict:
    prompt = str(prompt or "").strip()
    access_token = str(access_token or "").strip()
    if not prompt:
        raise ImageGenerationError("prompt is required")
    if not access_token:
        raise ImageGenerationError("token is required")
    _ensure_codex_image_account(access_token, model)

    session, fp = _new_session(access_token)
    try:
        if model == CODEX_IMAGE_MODEL:
            print(
                f"[image-upstream] start token={access_token[:12]}... "
                f"requested_model={model} upstream_model={CODEX_RESPONSE_MODEL} thinking=False"
            )
            _bootstrap(session, fp)
            result = _run_codex_image_task(
                session,
                access_token,
                prompt,
                response_format=response_format,
                image_options=image_options,
                base_url=base_url,
            )
            print(f"[image-upstream] success token={access_token[:12]}... images=1 format={response_format}")
            return {
                "created": result["created"],
                "data": result["data"],
            }
        upstream_model, use_thinking = _resolve_upstream_model(access_token, model)
        actual_route = "regular"
        print(
            f"[image-upstream] start token={access_token[:12]}... "
            f"requested_model={model} upstream_model={upstream_model} thinking={use_thinking}"
        )
        device_id = _bootstrap(session, fp)
        chat_token, pow_info = _chat_requirements(session, access_token, device_id)
        proof_token = None
        if pow_info.get("required"):
            proof_token = _generate_proof_token(
                seed=str(pow_info["seed"]),
                difficulty=str(pow_info["difficulty"]),
                user_agent=USER_AGENT,
                proof_config=_pow_config(USER_AGENT),
            )
        parent_message_id = str(uuid.uuid4())

        parsed = None
        conversation_id = ""
        if use_thinking:
            conversation_id = _conversation_init(session, access_token, device_id)
            try:
                parsed = _run_thinking_mode(
                    session,
                    access_token,
                    device_id,
                    chat_token,
                    proof_token,
                    parent_message_id,
                    prompt,
                    upstream_model,
                    conversation_id,
                )
                actual_route = "thinking"
                print(f"[image-upstream] thinking mode OK, conduit resume token={'yes' if parsed.get('resume_conduit_token') else 'no'}")
            except Exception as exc:
                actual_route = "fallback"
                print(f"[image-upstream] thinking mode failed ({exc}), fallback to regular mode")
                parsed = None

        if parsed is None:
            try:
                parsed = _run_regular_generation_mode(
                    session,
                    access_token,
                    device_id,
                    chat_token,
                    proof_token,
                    parent_message_id,
                    prompt,
                    upstream_model,
                )
            except ImageGenerationError as exc:
                if is_conversation_forbidden_error(str(exc)):
                    actual_route = "fallback"
                    print("[image-upstream] regular picture pipeline rejected request, fallback to legacy conversation route")
                    conversation_id = _conversation_init(session, access_token, device_id)
                    parsed = _run_legacy_regular_generation_mode(
                        session,
                        access_token,
                        device_id,
                        chat_token,
                        proof_token,
                        parent_message_id,
                        prompt,
                        upstream_model,
                        conversation_id,
                    )
                else:
                    raise

        actual_conversation_id = parsed.get("conversation_id") or ""
        file_ids = [file_id for file_id in (parsed.get("file_ids") or []) if not _is_invalid_output_file_id(file_id)]
        response_text = str(parsed.get("text") or "").strip()
        if actual_conversation_id and not file_ids:
            file_ids = _poll_image_ids(session, access_token, device_id, actual_conversation_id)
        if not file_ids:
            if response_text:
                raise ImageGenerationError(image_stream_error_message(response_text))
            raise ImageGenerationError("no image returned from upstream")
        first_file_id = str(file_ids[0])
        download_url = _fetch_download_url(session, access_token, device_id, actual_conversation_id, first_file_id)
        if not download_url:
            raise ImageGenerationError("failed to get download url")

        result_data = _build_image_result_data(
            prompt,
            response_format,
            actual_route,
            image_options=image_options,
            session=session,
            download_url=download_url,
            base_url=base_url,
        )

        print(f"[image-upstream] success token={access_token[:12]}... images=1 format={response_format}")
        return {
            "created": time.time_ns() // 1_000_000_000,
            "data": [result_data],
        }
    except Exception as exc:
        print(f"[image-upstream] fail token={access_token[:12]}... error={exc}")
        raise
    finally:
        session.close()


def _get_image_dimensions(image_data: bytes) -> tuple[int, int]:
    if image_data[:8] == b"\x89PNG\r\n\x1a\n" and len(image_data) >= 24:
        import struct
        w, h = struct.unpack(">II", image_data[16:24])
        return w, h
    if image_data[:2] in (b"\xff\xd8",):
        import io
        data = io.BytesIO(image_data)
        data.read(2)
        while True:
            marker = data.read(2)
            if len(marker) < 2:
                break
            if marker[0] != 0xFF:
                break
            if marker[1] in (0xC0, 0xC1, 0xC2):
                data.read(3)
                h_bytes = data.read(2)
                w_bytes = data.read(2)
                if len(h_bytes) == 2 and len(w_bytes) == 2:
                    import struct
                    h = struct.unpack(">H", h_bytes)[0]
                    w = struct.unpack(">H", w_bytes)[0]
                    return w, h
                break
            else:
                length_bytes = data.read(2)
                if len(length_bytes) < 2:
                    break
                import struct
                length = struct.unpack(">H", length_bytes)[0]
                data.read(length - 2)
    return 1024, 1024


def edit_image_result(
    access_token: str,
    prompt: str,
    images: list[tuple[bytes, str, str]],
    model: str = DEFAULT_MODEL,
    response_format: str = "b64_json",
    base_url: str = None,
    *,
    image_options: ImageRequestOptions | None = None,
) -> dict:
    prompt = str(prompt or "").strip()
    access_token = str(access_token or "").strip()
    if not prompt:
        raise ImageGenerationError("prompt is required")
    if not access_token:
        raise ImageGenerationError("token is required")
    if not images:
        raise ImageGenerationError("image is required")
    _ensure_codex_image_account(access_token, model)

    session, fp = _new_session(access_token)
    try:
        if model == CODEX_IMAGE_MODEL:
            print(
                f"[image-edit-upstream] start token={access_token[:12]}... "
                f"requested_model={model} upstream_model={CODEX_RESPONSE_MODEL} thinking=False images={len(images)}"
            )
            _bootstrap(session, fp)
            result = _run_codex_image_task(
                session,
                access_token,
                prompt,
                response_format=response_format,
                image_options=image_options,
                base_url=base_url,
                images=images,
            )
            print(
                f"[image-edit-upstream] success token={access_token[:12]}... "
                f"inputs={len(images)} format={response_format}"
            )
            return {
                "created": result["created"],
                "data": result["data"],
            }
        upstream_model = _resolve_upstream_edit_model(model)
        actual_route = "regular"
        print(
            f"[image-edit-upstream] start token={access_token[:12]}... "
            f"requested_model={model} upstream_model={upstream_model} thinking=False images={len(images)}"
        )
        device_id = _bootstrap(session, fp)

        uploaded_images: list[EditInputImage] = []
        for image_data, file_name, mime_type in images:
            if not image_data:
                raise ImageGenerationError("image is required")

            file_id = _upload_image(session, access_token, device_id, image_data, file_name, mime_type)
            print(f"[image-edit-upstream] uploaded file_id={file_id}")
            image_width, image_height = _get_image_dimensions(image_data)
            uploaded_images.append(
                EditInputImage(
                    file_id=file_id,
                    data=image_data,
                    file_name=file_name,
                    mime_type=mime_type,
                    width=image_width,
                    height=image_height,
                )
            )

        chat_token, pow_info = _chat_requirements(session, access_token, device_id)
        proof_token = None
        if pow_info.get("required"):
            proof_token = _generate_proof_token(
                seed=str(pow_info["seed"]),
                difficulty=str(pow_info["difficulty"]),
                user_agent=USER_AGENT,
                proof_config=_pow_config(USER_AGENT),
            )
        conversation_id = _conversation_init(session, access_token, device_id)
        parent_message_id = str(uuid.uuid4())
        parsed = None
        actual_conversation_id = ""
        file_ids: list[str] = []
        response_text = ""
        input_file_ids = {image.file_id for image in uploaded_images}
        try:
            parsed = _run_regular_edit_mode(
                session,
                access_token,
                device_id,
                chat_token,
                proof_token,
                parent_message_id,
                prompt,
                upstream_model,
                uploaded_images,
            )
        except ImageGenerationError as exc:
            if is_conversation_forbidden_error(str(exc)):
                print("[image-edit-upstream] unified regular image path rejected edit, fallback to legacy regular edit model=auto")
                parsed = _run_legacy_regular_edit_mode(
                    session,
                    access_token,
                    device_id,
                    chat_token,
                    proof_token,
                    parent_message_id,
                    prompt,
                    "auto",
                    uploaded_images,
                    conversation_id,
                )
            else:
                raise
        actual_conversation_id, file_ids, response_text = _collect_edit_output(
            session,
            access_token,
            device_id,
            parsed,
            input_file_ids,
        )
        if not file_ids:
            if response_text:
                raise ImageGenerationError(image_stream_error_message(response_text))
            raise ImageGenerationError("no image returned from upstream")
        first_file_id = str(file_ids[0])
        download_url = _fetch_download_url(session, access_token, device_id, actual_conversation_id, first_file_id)
        if not download_url:
            raise ImageGenerationError("failed to get download url")

        result_data = _build_image_result_data(
            prompt,
            response_format,
            actual_route,
            image_options=image_options,
            session=session,
            download_url=download_url,
            base_url=base_url,
        )
        print(
            f"[image-edit-upstream] success token={access_token[:12]}... "
            f"inputs={len(uploaded_images)} format={response_format}"
        )
        return {
            "created": time.time_ns() // 1_000_000_000,
            "data": [result_data],
        }
    except Exception as exc:
        print(f"[image-edit-upstream] fail token={access_token[:12]}... error={exc}")
        raise
    finally:
        session.close()
