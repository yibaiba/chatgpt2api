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
from PIL import Image, ImageChops, ImageFilter

from services.account_service import account_service
from services import proof_of_work
from services.system_settings import system_settings_service
from services.utils import CODEX_IMAGE_MODEL, ImageRequestOptions, parse_exact_image_size
from services.config import config


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
    "curl: (56)",
    "curl: (35)",
    "connection closed abruptly",
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
PLACEHOLDER_CANVAS_LIGHTNESS_MIN = 185
PLACEHOLDER_CANVAS_NEUTRAL_DELTA_MAX = 8
PLACEHOLDER_CANVAS_OUTSIDE_RATIO_MIN = 0.85
PLACEHOLDER_CANVAS_INSIDE_RATIO_MAX = 0.8
PLACEHOLDER_CANVAS_OUTSIDE_INSIDE_DELTA_MIN = 0.2
PLACEHOLDER_CANVAS_TONE_RANGE_MIN = 24
SAME_SIZE_PATCH_CANVAS_BBOX_AREA_RATIO_MAX = 0.5
SAME_SIZE_FULL_FRAME_MASK_EXPANSION_RATIO = 0.12
SAME_SIZE_FULL_FRAME_MASK_EXPANSION_MAX = 24
SAME_SIZE_FULL_FRAME_MASK_BLUR_MULTIPLIER = 1.5
SAME_SIZE_FULL_FRAME_MASK_ALPHA_FLOOR = 8
SAME_SIZE_FULL_FRAME_OUTSIDE_MASK_MEAN_DIFF_MAX = 24.0
FULL_FRAME_VARIANT_AREA_RATIO_MIN = 0.72
FULL_FRAME_VARIANT_AREA_RATIO_MAX = 1.45
FULL_FRAME_VARIANT_MASK_COVERAGE_MIN = 0.35
FULL_FRAME_VARIANT_OUTSIDE_MASK_ALPHA_MAX = 16
FULL_FRAME_VARIANT_OUTSIDE_MASK_MEAN_DIFF_MAX = 12.0

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
    attachment_mime_types: Optional[list[str]] = None,
    conversation_id: str = "",
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
    if conversation_id:
        body["conversation_id"] = conversation_id
    if attachment_mime_types:
        body["attachment_mime_types"] = attachment_mime_types
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
        print(f"[prepare-picture] failed status={response.status_code} conv_id={conversation_id[:8] if conversation_id else 'new'} body={response.text[:200]!r}")
    except Exception as exc:
        print(f"[prepare-picture] exception conv_id={conversation_id[:8] if conversation_id else 'new'}: {exc}")
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


def _upload_image_for_dalle(session: Session, access_token: str, device_id: str, image_data: bytes, file_name: str, mime_type: str) -> str:
    """上传图片用于 inpaint original_file_id，使用 dalle_agent use_case（与遮罩相同）"""
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
                "use_case": "dalle_agent",
                "timezone_offset_min": -480,
                "reset_rate_limits": False,
            },
            timeout=30,
        ),
        retries=3,
    )
    if not response.ok:
        raise ImageGenerationError(f"dalle image upload init failed: {response.status_code} {response.text[:200]}")
    payload = response.json()
    upload_url = payload.get("upload_url") or ""
    file_id = payload.get("file_id") or ""
    if not upload_url or not file_id:
        raise ImageGenerationError("dalle image upload init returned no upload_url or file_id")

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
        raise ImageGenerationError(f"dalle image upload PUT failed: {put_resp.status_code}")

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
                "use_case": "dalle_agent",
                "index_for_retrieval": False,
                "file_name": file_name,
            },
            timeout=30,
        ),
        retries=3,
    )
    if not process_resp.ok:
        raise ImageGenerationError(f"dalle image process failed: {process_resp.status_code}")
    return file_id


def _upload_mask(session: Session, access_token: str, device_id: str, mask_data: bytes) -> str:
    """上传遮罩 PNG，使用 dalle_agent use_case（与普通图片上传不同）"""
    response = _retry(
        lambda: session.post(
            BASE_URL + "/backend-api/files",
            headers={
                "Authorization": f"Bearer {access_token}",
                "oai-device-id": device_id,
                "content-type": "application/json",
            },
            json={
                "file_name": "mask.png",
                "file_size": len(mask_data),
                "use_case": "dalle_agent",
                "timezone_offset_min": -480,
                "reset_rate_limits": False,
            },
            timeout=30,
        ),
        retries=3,
    )
    if not response.ok:
        raise ImageGenerationError(f"mask upload init failed: {response.status_code} {response.text[:200]}")
    payload = response.json()
    upload_url = payload.get("upload_url") or ""
    file_id = payload.get("file_id") or ""
    if not upload_url or not file_id:
        raise ImageGenerationError("mask upload init returned no upload_url or file_id")

    put_resp = _retry(
        lambda: session.put(
            upload_url,
            headers={
                "Content-Type": "image/png",
                "x-ms-blob-type": "BlockBlob",
                "x-ms-version": "2020-04-08",
            },
            data=mask_data,
            timeout=60,
        ),
        retries=3,
    )
    if not (200 <= put_resp.status_code < 300):
        raise ImageGenerationError(f"mask upload PUT failed: {put_resp.status_code}")

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
                "use_case": "dalle_agent",
                "index_for_retrieval": False,
                "file_name": "mask.png",
            },
            timeout=30,
        ),
        retries=3,
    )
    if not process_resp.ok:
        raise ImageGenerationError(f"mask process failed: {process_resp.status_code}")
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


def _build_inpaint_picture_v2_body(
    prompt: str,
    parent_message_id: str,
    model: str,
    original_file_id: str,
    mask_file_id: str,
    original_gen_id: str,
    ref_images: Optional[list[EditInputImage]] = None,
    conversation_id: str = "",
    original_image: Optional["EditInputImage"] = None,
) -> dict:
    """构建 inpainting 对话 payload。
    HAR 验证结论：
    - 纯遮罩（无参考图，有 conversation_id）：content_type="text"，parts=[prompt]，client_prepare_state="sent"
    - 有参考图：content_type="multimodal_text"，parts=[ref_parts, prompt]，client_prepare_state="success"
    - 独立模式（无 conversation_id，无参考图）：将原图加入 content parts 以提供视觉上下文
    原图通过 dalle_operation.original_file_id 传递；有 conversation_id 时不加入 content（HAR-1/HAR-2 验证）。
    """
    dalle_operation = {
        "type": "inpainting",
        "original_file_id": original_file_id,
        "mask_file_id": mask_file_id,
        "original_gen_id": original_gen_id,
    }
    metadata: dict = {
        "selected_github_repos": [],
        "selected_all_github_repos": False,
        "system_hints": ["picture_v2"],
        "serialization_metadata": {"custom_symbol_offsets": []},
        "dalle": {"from_client": {"operation": dalle_operation}},
    }

    if ref_images:
        # 有参考图：multimodal_text，parts=[ref_parts, prompt]，加 attachments（仅参考图，不含原图）
        image_parts, ref_attachments = _build_picture_v2_edit_input_payload(ref_images)
        content: dict = {
            "content_type": "multimodal_text",
            "parts": [*image_parts, prompt],
        }
        metadata["attachments"] = ref_attachments
        client_prepare_state = "success"
    elif not conversation_id and original_image is not None:
        # 独立模式（无 conversation_id，无参考图）：将原图加入 content parts 提供视觉上下文
        orig_parts, orig_attachments = _build_picture_v2_edit_input_payload([original_image])
        content = {
            "content_type": "multimodal_text",
            "parts": [*orig_parts, prompt],
        }
        metadata["attachments"] = orig_attachments
        client_prepare_state = "success"
    else:
        # 纯遮罩（无参考图，有 conversation_id）：text，client_prepare_state="sent"（HAR-1 验证）
        content = {"content_type": "text", "parts": [prompt]}
        client_prepare_state = "sent"

    body: dict = {
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
        "client_prepare_state": client_prepare_state,
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
    return body


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


def _send_inpaint_conversation(
    session: Session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token: Optional[str],
    parent_message_id: str,
    prompt: str,
    model: str,
    original_file_id: str,
    mask_file_id: str,
    original_gen_id: str,
    conduit_token: str,
    ref_images: Optional[list[EditInputImage]] = None,
    conversation_id: str = "",
    original_image: Optional[EditInputImage] = None,
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
    body = _build_inpaint_picture_v2_body(
        prompt, parent_message_id, model, original_file_id, mask_file_id, original_gen_id,
        ref_images=ref_images, conversation_id=conversation_id, original_image=original_image,
    )
    return _request_image_stream(
        lambda: session.post(
            BASE_URL + "/backend-api/f/conversation",
            headers=headers,
            json=body,
            stream=True,
            timeout=180,
        ),
        retries=2,
        fallback_error="inpaint f/conversation failed",
    )


def _bootstrap_image_conversation(
    session: Session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token: Optional[str],
    original_image: "EditInputImage",
    model: str,
) -> tuple[str, str]:
    """两步法 inpaint 的第一步：上传原图，建立对话上下文。
    返回 (conversation_id, last_message_id)，供后续 inpaint 请求使用。
    不含 dalle_operation / picture_v2 提示，避免模型触发 DALL-E 生成；
    模型只需简短文字响应确认图片即可，速度快（通常 2-5s）。
    """
    # 使用 _prepare_picture_conversation 获取 conduit_token（已验证能正常返回）
    # prepare 端点用于路由，不影响实际对话中的 system_hints 行为
    bootstrap_parent_id = "client-created-root"
    conduit_token = _prepare_picture_conversation(
        session, access_token, device_id,
        bootstrap_parent_id, "I need to edit this image.", model,
    )
    if not conduit_token:
        raise ImageGenerationError("bootstrap: failed to get conduit_token from prepare")

    user_msg_id = str(uuid.uuid4())
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

    # 构建包含原图的多模态消息，不含 dalle_operation / system_hints picture_v2
    # 目的：仅建立对话上下文，让后续 inpaint 能访问原图
    image_parts, attachments = _build_picture_v2_edit_input_payload([original_image])
    content = {
        "content_type": "multimodal_text",
        "parts": [*image_parts, "I need to edit this image."],
    }
    metadata = {
        "selected_github_repos": [],
        "selected_all_github_repos": False,
        "system_hints": [],
        "serialization_metadata": {"custom_symbol_offsets": []},
        "attachments": attachments,
    }
    body = {
        "action": "next",
        "messages": [
            {
                "id": user_msg_id,
                "author": {"role": "user"},
                "create_time": time.time(),
                "content": content,
                "metadata": metadata,
            }
        ],
        "parent_message_id": bootstrap_parent_id,
        "model": model,
        "timezone_offset_min": -480,
        "timezone": "Asia/Shanghai",
        "conversation_mode": {"kind": "primary_assistant"},
        "enable_message_followups": False,
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
    response = _request_image_stream(
        lambda: session.post(
            BASE_URL + "/backend-api/f/conversation",
            headers=headers,
            json=body,
            stream=True,
            timeout=60,
        ),
        retries=1,
        fallback_error="bootstrap inpaint conversation failed",
    )
    parsed = _parse_sse(response)
    conv_id = str(parsed.get("conversation_id") or "")
    last_msg_id = str(parsed.get("last_message_id") or user_msg_id)
    if not conv_id:
        raise ImageGenerationError("bootstrap: SSE returned no conversation_id")
    print(f"[image-inpaint-bootstrap] conv={conv_id[:8]}... last_msg={last_msg_id[:8] if last_msg_id else '?'}...")
    return conv_id, last_msg_id


def _run_inpaint_mode(
    session,
    access_token: str,
    device_id: str,
    chat_token: str,
    proof_token,
    parent_message_id: str,
    prompt: str,
    upstream_model: str,
    original_file_id: str,
    mask_file_id: str,
    original_gen_id: str,
    ref_images: Optional[list[EditInputImage]] = None,
    attachment_mime_types: Optional[list[str]] = None,
    conversation_id: str = "",
    original_image: Optional[EditInputImage] = None,
) -> dict:
    # 纯遮罩时 prepare 不传 attachment_mime_types（HAR-1 entry 73 验证）
    # 有参考图时需传 attachment_mime_types（HAR-2 entry 22/23 验证）
    # 续接已有对话（bootstrap 模式）时需传 conversation_id
    conduit_token = _prepare_picture_conversation(
        session,
        access_token,
        device_id,
        parent_message_id,
        prompt,
        upstream_model,
        attachment_mime_types=attachment_mime_types if attachment_mime_types else None,
        conversation_id=conversation_id,
    )
    if not conduit_token:
        raise ImageGenerationError("inpaint mode: f/conversation/prepare returned no conduit_token")

    response = _send_inpaint_conversation(
        session,
        access_token,
        device_id,
        chat_token,
        proof_token,
        parent_message_id,
        prompt,
        upstream_model,
        original_file_id,
        mask_file_id,
        original_gen_id,
        conduit_token,
        ref_images=ref_images,
        conversation_id=conversation_id,
        original_image=original_image,
    )
    return _parse_sse(response)


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
    image_gen_task_id = ""
    async_status_seen = False
    last_message_id = ""
    for raw_line in response.iter_lines():
        if not raw_line:
            continue
        if isinstance(raw_line, bytes):
            raw_line = raw_line.decode("utf-8", errors="replace")
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        if not payload:
            continue
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
            # 从 tool message metadata 中提取 image_gen_task_id
            msg = data.get("message") or {}
            msg_meta = msg.get("metadata") or {}
            task_id = str(msg_meta.get("image_gen_task_id") or "")
            if task_id and not image_gen_task_id:
                image_gen_task_id = task_id
            # 捕获最新的消息 ID（用于后续 inpaint 的 parent_message_id）
            msg_id = str(msg.get("id") or "")
            if msg_id:
                last_message_id = msg_id
        # 检测异步状态
        if obj.get("type") == "conversation_async_status":
            async_status_seen = True
        message = obj.get("message") or {}
        content = message.get("content") or {}
        if content.get("content_type") == "text":
            parts = content.get("parts") or []
            if parts:
                part_text = str(parts[0] or "").strip()
                if part_text:
                    latest_text = part_text
    if image_gen_task_id or async_status_seen:
        print(f"[parse-sse] conv={conversation_id[:8] if conversation_id else '?'}... async=True task_id={image_gen_task_id or 'n/a'} file_ids_in_stream={len(file_ids)}")
    return {
        "conversation_id": conversation_id,
        "file_ids": file_ids,
        "text": latest_text,
        "resume_conduit_token": resume_conduit_token,
        "image_gen_task_id": image_gen_task_id,
        "async_mode": async_status_seen,
        "last_message_id": last_message_id,
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


def _extract_conversation_text(mapping: dict) -> str:
    """从对话 mapping 中提取 assistant 的最新文字响应。"""
    for node in mapping.values():
        msg = (node or {}).get("message") or {}
        role = (msg.get("author") or {}).get("role", "")
        if role != "assistant":
            continue
        content = msg.get("content") or {}
        if content.get("content_type") == "text":
            parts = content.get("parts") or []
            for part in parts:
                if isinstance(part, str) and part.strip():
                    return part.strip()
    return ""


def _poll_image_ids(
    session: Session,
    access_token: str,
    device_id: str,
    conversation_id: str,
    input_file_ids: set[str] | None = None,
    timeout: float = 360,
    force_poll_past_text: bool = False,
) -> list[str]:
    started = time.time()
    normalized_input_file_ids = input_file_ids or set()
    poll_count = 0
    while time.time() - started < timeout:
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
        poll_count += 1
        if response.status_code != 200:
            if poll_count % 10 == 0:
                elapsed = int(time.time() - started)
                print(f"[poll-image] conv={conversation_id[:8]}... poll={poll_count} elapsed={elapsed}s status={response.status_code}")
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
            elapsed = int(time.time() - started)
            print(f"[poll-image] conv={conversation_id[:8]}... found {len(output_file_ids)} image(s) after {elapsed}s ({poll_count} polls)")
            return output_file_ids
        # 检查对话是否已完成但返回文字（错误/拒绝）而非图片
        final_text = _extract_conversation_text(payload.get("mapping") or {})
        if final_text:
            elapsed = int(time.time() - started)
            print(f"[poll-image] conv={conversation_id[:8]}... text_response after {elapsed}s: {final_text[:200]!r}")
            # 若文字看起来是 DALL-E 工具调用 JSON（中间步骤），则继续等待异步图片
            # 格式: {"prompt":..., "referenced_image_ids":[...], ...}
            is_dalle_tool_call = (
                final_text.startswith("{")
                and ("referenced_image_ids" in final_text or ('"prompt"' in final_text and '"n"' in final_text))
            )
            if is_dalle_tool_call:
                if poll_count % 5 == 1:
                    print(f"[poll-image] conv={conversation_id[:8]}... detected dalle tool call, waiting for async image...")
                time.sleep(3)
                continue
            if force_poll_past_text:
                # 已知有异步 DALL-E 任务（image_gen_task_id 存在），模型文字回复不代表任务失败
                if poll_count % 5 == 1:
                    print(f"[poll-image] conv={conversation_id[:8]}... async DALL-E task in progress, ignoring text response, keep polling...")
                time.sleep(3)
                continue
            # 对话有真实文字响应但没有图片，说明生成失败
            return []
        if poll_count % 10 == 0:
            elapsed = int(time.time() - started)
            print(f"[poll-image] conv={conversation_id[:8]}... still waiting, elapsed={elapsed}s polls={poll_count}")
        time.sleep(3)
    elapsed = int(time.time() - started)
    print(f"[poll-image] conv={conversation_id[:8]}... timeout after {elapsed}s ({poll_count} polls), no image found")
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
        # 若 SSE 流中捕获到 image_gen_task_id，说明有异步 DALL-E 任务正在运行
        # 此时即使模型返回了对话式文字也不代表失败，应继续轮询直到图片出现
        has_async_task = bool(parsed.get("image_gen_task_id"))
        file_ids = _poll_image_ids(
            session,
            access_token,
            device_id,
            actual_conversation_id,
            input_file_ids,
            force_poll_past_text=has_async_task,
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


def _build_output_candidate_score(
    candidate_size: tuple[int, int],
    target_size: tuple[int, int],
) -> tuple[int, float, float, int]:
    candidate_w, candidate_h = candidate_size
    target_w, target_h = target_size
    if candidate_w <= 0 or candidate_h <= 0 or target_w <= 0 or target_h <= 0:
        return 1, float("inf"), float("inf"), 2**31 - 1
    exact_size_penalty = 0 if candidate_size == target_size else 1
    aspect_ratio_error = abs((candidate_w / candidate_h) - (target_w / target_h))
    area_error = abs((candidate_w * candidate_h) - (target_w * target_h)) / max(target_w * target_h, 1)
    dimension_error = abs(candidate_w - target_w) + abs(candidate_h - target_h)
    return exact_size_penalty, aspect_ratio_error, area_error, dimension_error


def _select_best_output_candidate(
    output_candidates: list[tuple[str, bytes, tuple[int, int]]],
    target_size: tuple[int, int],
) -> tuple[str, bytes, tuple[int, int]]:
    if not output_candidates:
        raise ImageGenerationError("no inpaint output candidates available")
    return min(
        enumerate(output_candidates),
        key=lambda item: (_build_output_candidate_score(item[1][2], target_size), item[0]),
    )[1]


def _download_best_output_candidate(
    session: Session,
    access_token: str,
    device_id: str,
    conversation_id: str,
    file_ids: list[str],
    target_size: tuple[int, int],
) -> tuple[str, bytes]:
    output_candidates: list[tuple[str, bytes, tuple[int, int]]] = []
    download_failures: list[str] = []
    for file_id in file_ids:
        download_url = _fetch_download_url(session, access_token, device_id, conversation_id, file_id)
        if not download_url:
            download_failures.append(f"{file_id}:missing-download-url")
            continue
        try:
            image_bytes = _fetch_image_bytes(session, download_url)
            image_size = _get_image_dimensions(image_bytes)
        except ImageGenerationError as exc:
            download_failures.append(f"{file_id}:{exc}")
            continue
        output_candidates.append((file_id, image_bytes, image_size))

    if not output_candidates:
        failure_text = "; ".join(download_failures[:3])
        if failure_text:
            raise ImageGenerationError(f"failed to download inpaint output candidates: {failure_text}")
        raise ImageGenerationError("failed to download inpaint output candidates")

    selected_file_id, selected_bytes, selected_size = _select_best_output_candidate(output_candidates, target_size)
    candidate_summary = ", ".join(
        f"{str(file_id)[:12]}...={size[0]}x{size[1]}"
        for file_id, _image_bytes, size in output_candidates
    )
    print(
        f"[image-inpaint-candidates] target={target_size[0]}x{target_size[1]} "
        f"candidates=[{candidate_summary}] chosen={str(selected_file_id)[:12]}...={selected_size[0]}x{selected_size[1]}"
    )
    return selected_file_id, selected_bytes


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
    try:
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
    except ImageGenerationError:
        raise
    except Exception as exc:
        raise ImageGenerationError(image_stream_error_message(exc)) from exc


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
    try:
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
    except Exception as exc:
        raise ImageGenerationError(image_stream_error_message(exc)) from exc
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


_INPAINT_MAX_UPLOAD_SIZE = 1792  # ChatGPT API 支持的最大边长（px）


def _preprocess_inpaint_inputs(orig_bytes: bytes, mask_bytes: bytes) -> tuple[bytes, bytes]:
    """上传 inpaint 原图和遮罩前的预处理：
    1. 若最大边 > 1792px，按比例缩小两者，防止 API 内部坐标错位。
    2. 原图保持 RGBA（若有透明通道）或 RGB。
    返回 (处理后的 orig_bytes, 处理后的 mask_bytes)。
    """
    with Image.open(io.BytesIO(orig_bytes)) as orig_img, \
         Image.open(io.BytesIO(mask_bytes)) as mask_img:
        max_dim = max(orig_img.size)
        if max_dim <= _INPAINT_MAX_UPLOAD_SIZE:
            return orig_bytes, mask_bytes
        ratio = _INPAINT_MAX_UPLOAD_SIZE / max_dim
        new_size = (max(1, int(orig_img.width * ratio)), max(1, int(orig_img.height * ratio)))
        resized_orig = orig_img.resize(new_size, Image.LANCZOS)
        resized_mask = mask_img.resize(new_size, Image.LANCZOS)
        orig_buf = io.BytesIO()
        resized_orig.save(orig_buf, format="PNG")
        mask_buf = io.BytesIO()
        resized_mask.save(mask_buf, format="PNG")
        return orig_buf.getvalue(), mask_buf.getvalue()


def _scale_to_fill(image: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    target_w, target_h = target_size
    src_w, src_h = image.size
    if (src_w, src_h) == (target_w, target_h):
        return image.copy()
    scale = max(target_w / src_w, target_h / src_h)
    new_w = max(target_w, round(src_w * scale))
    new_h = max(target_h, round(src_h * scale))
    resized = image.resize((new_w, new_h), Image.LANCZOS)
    left = max(0, (new_w - target_w) // 2)
    top = max(0, (new_h - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _expand_box_to_aspect_ratio(
    box: tuple[int, int, int, int],
    target_aspect: float,
    bounds_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    bounds_w, bounds_h = bounds_size
    left, top, right, bottom = box
    box_w = max(1.0, float(right - left))
    box_h = max(1.0, float(bottom - top))
    center_x = (left + right) / 2.0
    center_y = (top + bottom) / 2.0
    current_aspect = box_w / box_h

    target_w = box_w
    target_h = box_h
    if current_aspect < target_aspect:
        target_w = box_h * target_aspect
    else:
        target_h = box_w / target_aspect

    if target_w > bounds_w:
        target_w = float(bounds_w)
        target_h = target_w / target_aspect
    if target_h > bounds_h:
        target_h = float(bounds_h)
        target_w = target_h * target_aspect

    target_w = min(float(bounds_w), max(1.0, target_w))
    target_h = min(float(bounds_h), max(1.0, target_h))

    new_left = round(center_x - target_w / 2.0)
    new_top = round(center_y - target_h / 2.0)
    new_right = new_left + round(target_w)
    new_bottom = new_top + round(target_h)

    if new_left < 0:
        new_right -= new_left
        new_left = 0
    if new_right > bounds_w:
        overflow = new_right - bounds_w
        new_left -= overflow
        new_right = bounds_w
    if new_top < 0:
        new_bottom -= new_top
        new_top = 0
    if new_bottom > bounds_h:
        overflow = new_bottom - bounds_h
        new_top -= overflow
        new_bottom = bounds_h

    new_left = max(0, new_left)
    new_top = max(0, new_top)
    new_right = min(bounds_w, max(new_left + 1, new_right))
    new_bottom = min(bounds_h, max(new_top + 1, new_bottom))
    return new_left, new_top, new_right, new_bottom


def _project_inpaint_onto_canvas(
    inpaint_img: Image.Image,
    mask_alpha: Image.Image,
    canvas_size: tuple[int, int],
) -> tuple[Image.Image, str, tuple[int, int, int, int] | None]:
    canvas_w, canvas_h = canvas_size
    mask_bbox = mask_alpha.getbbox()
    if mask_bbox is None:
        return Image.new("RGBA", canvas_size, (0, 0, 0, 0)), "empty-mask", None

    if mask_bbox == (0, 0, canvas_w, canvas_h):
        return _scale_to_fill(inpaint_img, canvas_size).convert("RGBA"), "full-frame", mask_bbox

    raw_aspect = inpaint_img.width / max(1, inpaint_img.height)
    target_box = _expand_box_to_aspect_ratio(mask_bbox, raw_aspect, canvas_size)
    target_w = max(1, target_box[2] - target_box[0])
    target_h = max(1, target_box[3] - target_box[1])

    projected = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    projected_patch = _scale_to_fill(inpaint_img, (target_w, target_h)).convert("RGBA")
    projected.paste(projected_patch, (target_box[0], target_box[1]))
    return projected, "mask-bbox", target_box


def _looks_like_full_frame_variant(
    inpaint_img: Image.Image,
    orig_img: Image.Image,
    mask_alpha: Image.Image,
) -> bool:
    raw_w, raw_h = inpaint_img.size
    target_w, target_h = orig_img.size
    raw_area = raw_w * raw_h
    target_area = target_w * target_h
    if target_area <= 0:
        return False
    area_ratio = raw_area / target_area
    if not (FULL_FRAME_VARIANT_AREA_RATIO_MIN <= area_ratio <= FULL_FRAME_VARIANT_AREA_RATIO_MAX):
        return False

    histogram = mask_alpha.histogram()
    # 前端生成的 mask 包含 alpha 梯度（羽化），从 0（保留区）到 255（核心编辑区）。
    # 仅计算 alpha >= 128 的像素（半透明以上），避免把整个柔和边缘都算作"全图编辑"。
    significant_alpha_pixels = sum(histogram[128:])
    mask_coverage_ratio = significant_alpha_pixels / target_area
    if mask_coverage_ratio >= FULL_FRAME_VARIANT_MASK_COVERAGE_MIN:
        return True

    scaled_rgb = _scale_to_fill(inpaint_img, (target_w, target_h)).convert("RGB")
    original_rgb = orig_img.convert("RGB")
    mean_diff = _measure_outside_mask_mean_diff(
        scaled_rgb,
        original_rgb,
        mask_alpha,
        FULL_FRAME_VARIANT_OUTSIDE_MASK_ALPHA_MAX,
    )
    if mean_diff is None:
        return False
    return mean_diff <= FULL_FRAME_VARIANT_OUTSIDE_MASK_MEAN_DIFF_MAX


def _measure_outside_mask_mean_diff(
    candidate_rgb: Image.Image,
    original_rgb: Image.Image,
    mask_alpha: Image.Image,
    outside_mask_alpha_max: int,
) -> float | None:
    candidate_pixels = candidate_rgb.load()
    original_pixels = original_rgb.load()
    mask_pixels = mask_alpha.load()

    total_diff = 0
    sample_count = 0
    sample_step = max(1, min(candidate_rgb.width, candidate_rgb.height) // 200)
    for y in range(0, candidate_rgb.height, sample_step):
        for x in range(0, candidate_rgb.width, sample_step):
            if mask_pixels[x, y] > outside_mask_alpha_max:
                continue
            candidate_pixel = candidate_pixels[x, y]
            original_pixel = original_pixels[x, y]
            total_diff += (
                abs(candidate_pixel[0] - original_pixel[0])
                + abs(candidate_pixel[1] - original_pixel[1])
                + abs(candidate_pixel[2] - original_pixel[2])
            )
            sample_count += 1

    if sample_count == 0:
        return None
    return total_diff / (sample_count * 3)


def _is_placeholder_canvas_pixel(pixel: tuple[int, int, int] | tuple[int, int, int, int]) -> bool:
    red, green, blue = pixel[:3]
    mean = (red + green + blue) / 3.0
    spread = max(abs(red - green), abs(red - blue), abs(green - blue))
    return mean >= PLACEHOLDER_CANVAS_LIGHTNESS_MIN and spread <= PLACEHOLDER_CANVAS_NEUTRAL_DELTA_MAX


def _measure_placeholder_canvas_ratios(
    raw_rgb: Image.Image,
    mask_alpha: Image.Image,
) -> tuple[float, float, int] | None:
    raw_pixels = raw_rgb.load()
    mask_pixels = mask_alpha.load()
    outside_total = 0
    outside_placeholder = 0
    inside_total = 0
    inside_placeholder = 0
    outside_placeholder_min = 255
    outside_placeholder_max = 0

    for y in range(raw_rgb.height):
        for x in range(raw_rgb.width):
            pixel = raw_pixels[x, y]
            pixel_is_placeholder = _is_placeholder_canvas_pixel(pixel)
            if mask_pixels[x, y] > 0:
                inside_total += 1
                inside_placeholder += int(pixel_is_placeholder)
            else:
                outside_total += 1
                outside_placeholder += int(pixel_is_placeholder)
                if pixel_is_placeholder:
                    mean = round((pixel[0] + pixel[1] + pixel[2]) / 3.0)
                    outside_placeholder_min = min(outside_placeholder_min, mean)
                    outside_placeholder_max = max(outside_placeholder_max, mean)

    if outside_total == 0 or inside_total == 0:
        return None
    outside_tone_range = max(0, outside_placeholder_max - outside_placeholder_min)
    return outside_placeholder / outside_total, inside_placeholder / inside_total, outside_tone_range


def _filter_mask_by_placeholder_pixels(
    raw_rgb: Image.Image,
    mask_alpha: Image.Image,
) -> Image.Image:
    raw_pixels = raw_rgb.load()
    mask_pixels = mask_alpha.load()
    effective_mask = Image.new("L", mask_alpha.size, 0)
    effective_pixels = effective_mask.load()

    for y in range(raw_rgb.height):
        for x in range(raw_rgb.width):
            alpha_value = mask_pixels[x, y]
            if alpha_value <= 0:
                continue
            if _is_placeholder_canvas_pixel(raw_pixels[x, y]):
                continue
            effective_pixels[x, y] = alpha_value
    return effective_mask


def _box_area(box: tuple[int, int, int, int]) -> int:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _build_same_size_full_frame_mask(mask_alpha: Image.Image) -> Image.Image:
    mask_bbox = mask_alpha.getbbox()
    if mask_bbox is None or mask_bbox == (0, 0, mask_alpha.width, mask_alpha.height):
        return mask_alpha

    box_w = max(1, mask_bbox[2] - mask_bbox[0])
    box_h = max(1, mask_bbox[3] - mask_bbox[1])
    expansion = round(min(box_w, box_h) * SAME_SIZE_FULL_FRAME_MASK_EXPANSION_RATIO)
    expansion = min(SAME_SIZE_FULL_FRAME_MASK_EXPANSION_MAX, max(1, expansion))
    expanded = mask_alpha.filter(ImageFilter.MaxFilter(expansion * 2 + 1))
    feathered = expanded.filter(ImageFilter.GaussianBlur(radius=max(1, expansion * SAME_SIZE_FULL_FRAME_MASK_BLUR_MULTIPLIER)))
    feathered = feathered.point(lambda value: 0 if value < SAME_SIZE_FULL_FRAME_MASK_ALPHA_FLOOR else value)
    return ImageChops.lighter(mask_alpha, feathered)


def _build_same_size_effective_mask(
    inpaint_img: Image.Image,
    mask_alpha: Image.Image,
) -> tuple[Image.Image, bool]:
    mask_bbox = mask_alpha.getbbox()
    if mask_bbox is None or mask_bbox == (0, 0, mask_alpha.width, mask_alpha.height):
        return mask_alpha, False

    raw_rgb = inpaint_img.convert("RGB")
    ratios = _measure_placeholder_canvas_ratios(raw_rgb, mask_alpha)
    if ratios is None:
        return mask_alpha, False

    outside_ratio, inside_ratio, outside_tone_range = ratios
    if outside_ratio < PLACEHOLDER_CANVAS_OUTSIDE_RATIO_MIN:
        return mask_alpha, False
    if inside_ratio > PLACEHOLDER_CANVAS_INSIDE_RATIO_MAX:
        return mask_alpha, False
    if outside_ratio - inside_ratio < PLACEHOLDER_CANVAS_OUTSIDE_INSIDE_DELTA_MIN:
        return mask_alpha, False
    if outside_tone_range < PLACEHOLDER_CANVAS_TONE_RANGE_MIN:
        return mask_alpha, False

    effective_mask = _filter_mask_by_placeholder_pixels(raw_rgb, mask_alpha)

    effective_bbox = effective_mask.getbbox()
    if effective_bbox is None:
        return mask_alpha, False
    if _box_area(effective_bbox) / max(1, _box_area(mask_bbox)) > SAME_SIZE_PATCH_CANVAS_BBOX_AREA_RATIO_MAX:
        return mask_alpha, False
    return effective_mask, True


def _composite_inpaint_onto_original(inpaint_bytes: bytes, orig_bytes: bytes, mask_bytes: bytes) -> bytes:
    """合成兜底：用 mask 将 inpaint 结果叠合到原图。
    mask A=255（遮罩区）→ 使用 inpaint 结果像素（AI 修改的区域）。
    mask A=0   （保留区）→ 使用原图像素（严格保留，不受 API 任何影响）。
    中间值 → alpha 混合过渡。
    若 inpaint 结果与原图尺寸不同，优先按 mask 外接框进行局部回贴，
    避免把局部编辑画布错误映射到整张原图坐标系。
    """
    with Image.open(io.BytesIO(inpaint_bytes)) as inpaint_img, \
         Image.open(io.BytesIO(orig_bytes)) as orig_img, \
         Image.open(io.BytesIO(mask_bytes)) as mask_img:
        target_w, target_h = orig_img.size
        if mask_img.size != (target_w, target_h):
            mask_img = mask_img.resize((target_w, target_h), Image.LANCZOS)
        mask_alpha = mask_img.split()[3] if mask_img.mode == "RGBA" else mask_img.convert("L")
        orig_rgba = orig_img.convert("RGBA")
        composite_mask = mask_alpha
        if inpaint_img.size == (target_w, target_h):
            inpaint_rgba = inpaint_img.convert("RGBA")
            composite_mask, placeholder_filtered = _build_same_size_effective_mask(inpaint_img, mask_alpha)
            if placeholder_filtered:
                projection_mode = "same-size-patch-canvas"
            else:
                outside_mask_mean_diff = _measure_outside_mask_mean_diff(
                    inpaint_img.convert("RGB"),
                    orig_img.convert("RGB"),
                    mask_alpha,
                    FULL_FRAME_VARIANT_OUTSIDE_MASK_ALPHA_MAX,
                )
                if (
                    outside_mask_mean_diff is not None
                    and outside_mask_mean_diff > SAME_SIZE_FULL_FRAME_OUTSIDE_MASK_MEAN_DIFF_MAX
                ):
                    composite_mask = Image.new("L", (target_w, target_h), 255)
                    projection_mode = "full-frame-generated"
                else:
                    composite_mask = _build_same_size_full_frame_mask(mask_alpha)
                    projection_mode = "full-frame"
            projection_box = composite_mask.getbbox() or (0, 0, target_w, target_h)
        elif _looks_like_full_frame_variant(inpaint_img, orig_img, mask_alpha):
            inpaint_rgba = _scale_to_fill(inpaint_img, (target_w, target_h)).convert("RGBA")
            projection_mode = "full-frame-variant"
            projection_box = (0, 0, target_w, target_h)
        else:
            inpaint_rgba, projection_mode, projection_box = _project_inpaint_onto_canvas(
                inpaint_img,
                mask_alpha,
                (target_w, target_h),
            )
        print(
            f"[image-inpaint-compose] raw={inpaint_img.width}x{inpaint_img.height} "
            f"target={target_w}x{target_h} mode={projection_mode} box={projection_box}"
        )
        composited = Image.composite(inpaint_rgba, orig_rgba, composite_mask)
        buf = io.BytesIO()
        composited.save(buf, format="PNG")
        return buf.getvalue()


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


def _get_configured_upstream_model() -> str:
    """从 config 中读取 image_upstream_model，默认 auto"""
    return str(config.data.get("image_upstream_model") or "auto").strip() or "auto"


def _resolve_upstream_model(access_token: str, requested_model: str) -> tuple[str, bool]:
    """返回 (upstream_model, use_thinking_mode)"""
    requested_model = str(requested_model or "").strip() or "gpt-image-1"
    is_free_account = _is_free_account(access_token)
    configured = _get_configured_upstream_model()

    if requested_model == CODEX_IMAGE_MODEL:
        return CODEX_IMAGE_MODEL, False
    if requested_model == "gpt-image-think":
        # 带思考的图片生成：付费账户使用配置模型，免费账户强制 auto
        upstream = "auto" if is_free_account else configured
        return upstream, True
    if requested_model in {"gpt-image-1", "gpt-image-2", "gpt-image"}:
        return configured, False
    return (str(requested_model or DEFAULT_MODEL).strip() or DEFAULT_MODEL), False


def _resolve_upstream_edit_model(requested_model: str) -> str:
    requested_model = str(requested_model or "").strip() or "gpt-image-2"
    if requested_model == CODEX_IMAGE_MODEL:
        return CODEX_IMAGE_MODEL
    if requested_model in {"gpt-image-1", "gpt-image-2", "gpt-image-think", "gpt-image"}:
        return _get_configured_upstream_model()
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
    attachment_mime_types = list(dict.fromkeys(img.mime_type for img in images))
    conduit_token = _prepare_picture_conversation(
        session,
        access_token,
        device_id,
        parent_message_id,
        prompt,
        upstream_model,
        attachment_mime_types=attachment_mime_types,
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
                    "client-created-root",
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
                        "client-created-root",
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
        result_data["conversation_id"] = actual_conversation_id
        result_data["last_message_id"] = str(parsed.get("last_message_id") or "")

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
        parent_message_id = "client-created-root"
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


def inpaint_image_result(
    access_token: str,
    prompt: str,
    original_image: tuple[bytes, str, str],
    mask_data: bytes,
    model: str = DEFAULT_MODEL,
    response_format: str = "b64_json",
    base_url: str = None,
    *,
    original_gen_id: str = "",
    ref_images: list[tuple[bytes, str, str]] | None = None,
    image_options: ImageRequestOptions | None = None,
    conversation_id: str = "",
    parent_message_id: str = "",
) -> dict:
    """图片局部重绘（inpainting）。
    original_image: (bytes, file_name, mime_type) 原始图片
    mask_data: PNG 格式遮罩（白色=编辑区域，黑色=保留区域）
    original_gen_id: 可选，原图生成 UUID；不提供则自动生成
    ref_images: 可选参考图列表
    conversation_id: 原图生成时的对话 ID（HAR 验证必须续接原对话，否则模型无上下文会返回文字）
    parent_message_id: 原图生成后最后一条消息 ID（续接时的 parent）
    """
    prompt = str(prompt or "").strip()
    access_token = str(access_token or "").strip()
    if not prompt:
        raise ImageGenerationError("prompt is required")
    if not access_token:
        raise ImageGenerationError("token is required")
    if not original_image or not original_image[0]:
        raise ImageGenerationError("original image is required")
    if not mask_data:
        raise ImageGenerationError("mask is required")

    upstream_model = _resolve_upstream_edit_model(model)
    print(
        f"[image-inpaint-upstream] start token={access_token[:12]}... "
        f"requested_model={model} upstream_model={upstream_model}"
    )

    session, fp = _new_session(access_token)
    try:
        device_id = _bootstrap(session, fp)

        # 上传原始图片（multimodal）→ 产生 file_0000000073cc... 格式，HAR 验证 original_file_id 必须为此格式
        orig_bytes, orig_name, orig_mime = original_image

        # 记录用户原始分辨率，合成后恢复用
        orig_native_w, orig_native_h = _get_image_dimensions(orig_bytes)

        # 预处理：大图缩小至 1792px 以内，防止 API 内部坐标错位；mask 同步缩放。
        # 保留预处理后的字节，用于最终合成兜底。
        upload_orig_bytes, upload_mask_bytes = _preprocess_inpaint_inputs(orig_bytes, mask_data)

        orig_width, orig_height = _get_image_dimensions(upload_orig_bytes)
        original_file_id = _upload_image(session, access_token, device_id, upload_orig_bytes, orig_name, orig_mime)
        print(f"[image-inpaint-upstream] uploaded original_file_id={original_file_id} size={orig_width}x{orig_height}")
        original_edit_image = EditInputImage(
            file_id=original_file_id, data=upload_orig_bytes, file_name=orig_name,
            mime_type=orig_mime, width=orig_width, height=orig_height,
        )

        # 上传遮罩（dalle_agent）
        # 官方 ChatGPT 上传 RGBA PNG，alpha 通道承载 mask 权重：
        #   A=255 → 编辑区，A=0 → 保留区，中间值 → 羽化过渡区
        # 前端已按此格式导出（R=G=B=255, A=edit_weight），直接上传，不做转换。
        # 旧逻辑 convert("L") 会忽略 alpha，导致全图变白再反转为全黑，笔刷信息丢失。
        mask_file_id = _upload_mask(session, access_token, device_id, upload_mask_bytes)
        print(f"[image-inpaint-upstream] uploaded mask_file_id={mask_file_id}")

        # 上传参考图（可选，multimodal）
        uploaded_ref_images: list[EditInputImage] = []
        if ref_images:
            for ref_bytes, ref_name, ref_mime in ref_images:
                ref_id = _upload_image(session, access_token, device_id, ref_bytes, ref_name, ref_mime)
                ref_w, ref_h = _get_image_dimensions(ref_bytes)
                uploaded_ref_images.append(EditInputImage(
                    file_id=ref_id, data=ref_bytes, file_name=ref_name, mime_type=ref_mime,
                    width=ref_w, height=ref_h,
                ))
                print(f"[image-inpaint-upstream] uploaded ref_file_id={ref_id}")

        gen_id = str(original_gen_id or "").strip() or str(uuid.uuid4())

        chat_token, pow_info = _chat_requirements(session, access_token, device_id)
        proof_token = None
        if pow_info.get("required"):
            proof_token = _generate_proof_token(
                seed=str(pow_info["seed"]),
                difficulty=str(pow_info["difficulty"]),
                user_agent=USER_AGENT,
                proof_config=_pow_config(USER_AGENT),
            )

        # HAR 验证：inpaint 必须属于原始图片所在对话。在新对话中发起会导致模型无上下文返回文字而非图片。
        actual_parent_message_id = str(parent_message_id or "").strip() or "client-created-root"
        actual_conversation_id_for_inpaint = str(conversation_id or "").strip()
        if actual_conversation_id_for_inpaint:
            print(f"[image-inpaint-upstream] using existing conv={actual_conversation_id_for_inpaint[:8]}... parent={actual_parent_message_id[:8]}...")
        else:
            # 两步法：先建立包含原图的对话（bootstrap），再在该对话中发 inpaint 请求。
            # 完全模拟 ChatGPT web UI 的遮罩编辑流程，确保 DALL-E 能正确使用 mask。
            print(f"[image-inpaint-upstream] no conversation_id, bootstrapping conversation with original image...")
            actual_conversation_id_for_inpaint, actual_parent_message_id = _bootstrap_image_conversation(
                session, access_token, device_id,
                chat_token, proof_token,
                original_edit_image, upstream_model,
            )
            # 获取新的 chat_token / proof_token 用于后续 inpaint 请求
            chat_token, pow_info = _chat_requirements(session, access_token, device_id)
            proof_token = None
            if pow_info.get("required"):
                proof_token = _generate_proof_token(
                    seed=str(pow_info["seed"]),
                    difficulty=str(pow_info["difficulty"]),
                    user_agent=USER_AGENT,
                    proof_config=_pow_config(USER_AGENT),
                )
            print(
                f"[image-inpaint-upstream] bootstrap done, "
                f"conv={actual_conversation_id_for_inpaint[:8]}... parent={actual_parent_message_id[:8] if actual_parent_message_id else '?'}..."
            )

        input_file_ids = {original_file_id, mask_file_id}
        if uploaded_ref_images:
            input_file_ids.update(img.file_id for img in uploaded_ref_images)

        # 收集附件 MIME 类型传递给 prepare
        # HAR 验证：纯遮罩（有 conv_id）prepare 无此字段（entry 73），有参考图时只传参考图 MIME（entry 22/23）
        # 两步法（bootstrap + inpaint）：inpaint 请求有 conv_id，无需传原图 MIME
        if uploaded_ref_images:
            inpaint_attachment_mime_types: Optional[list[str]] = list(dict.fromkeys(
                [img.mime_type for img in uploaded_ref_images]
            )) or None
        else:
            inpaint_attachment_mime_types = None

        parsed = _run_inpaint_mode(
            session,
            access_token,
            device_id,
            chat_token,
            proof_token,
            actual_parent_message_id,
            prompt,
            upstream_model,
            original_file_id,
            mask_file_id,
            gen_id,
            ref_images=uploaded_ref_images if uploaded_ref_images else None,
            attachment_mime_types=inpaint_attachment_mime_types,
            conversation_id=actual_conversation_id_for_inpaint,
            original_image=None,  # 两步法：原图已在 bootstrap 对话中，inpaint 请求不再重复附带
        )

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
            raise ImageGenerationError("no image returned from inpaint upstream")

        upload_w, upload_h = _get_image_dimensions(upload_orig_bytes)
        # ChatGPT API 同一次 inpaint 可能返回多个输出候选；不能盲取第一个。
        # 优先选与上传尺寸完全一致的候选，其次选宽高比/面积最接近上传图的结果。
        _selected_file_id, raw_inpaint_bytes = _download_best_output_candidate(
            session,
            access_token,
            device_id,
            actual_conversation_id,
            file_ids,
            (upload_w, upload_h),
        )

        # 下载 inpaint 结果。
        # ChatGPT API 有时返回完整合成图（同尺寸），有时仅返回 patch（小尺寸）。
        # 实测发现即使同尺寸，API 也可能只填充遮罩区而其余区域为黑/透明，
        # 因此不能用尺寸判断是否已完整合成——始终手动合成回原图。
        # 合成使用羽化 mask（A 值渐变），边缘平滑，不产生割裂感。
        raw_w, raw_h = _get_image_dimensions(raw_inpaint_bytes)
        print(f"[image-inpaint-upstream] API returned {raw_w}x{raw_h} (upload={upload_w}x{upload_h}), compositing with original")
        composited_bytes = _composite_inpaint_onto_original(raw_inpaint_bytes, upload_orig_bytes, upload_mask_bytes)

        # 若原图被缩小过（> 1792px），API 结果也是缩小后的尺寸，等比放大回原始分辨率。
        if (orig_native_w, orig_native_h) != (upload_w, upload_h):
            with Image.open(io.BytesIO(composited_bytes)) as comp_img:
                restored = comp_img.resize((orig_native_w, orig_native_h), Image.LANCZOS)
                buf = io.BytesIO()
                restored.save(buf, format="PNG")
                composited_bytes = buf.getvalue()

        image_bytes, mime_type = _process_output_image(composited_bytes, image_options)
        output_format = str(
            (image_options.output_format if image_options is not None else "png") or "png"
        ).strip().lower() or "png"
        result_data: dict = {"revised_prompt": prompt, "generation_route": "inpaint", "mime_type": mime_type}
        if response_format == "url":
            result_data["url"] = _save_processed_image(image_bytes, output_format, base_url)
        else:
            result_data["b64_json"] = base64.b64encode(image_bytes).decode("ascii")
        result_data["conversation_id"] = actual_conversation_id
        result_data["last_message_id"] = str(parsed.get("last_message_id") or "")
        print(
            f"[image-inpaint-upstream] success token={access_token[:12]}... format={response_format}"
        )
        return {
            "created": time.time_ns() // 1_000_000_000,
            "data": [result_data],
        }
    except Exception as exc:
        print(f"[image-inpaint-upstream] fail token={access_token[:12]}... error={exc}")
        raise
    finally:
        session.close()

