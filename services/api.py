from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event, Lock, Thread
import time
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, FastAPI, File, Form, Header, Request, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from services.auth_security import build_signed_token, read_signed_token
from services.account_service import account_service
from services.auth_service import auth_service
from services.chatgpt_service import ChatGPTService
from services.config import config
from services.cpa_service import cpa_config, cpa_import_service, list_remote_files
from services.image_history_service import image_history_service
from services.log_service import LOG_LEVEL_ALL, LOG_SOURCE_ALL, log_service
from services.proxy_service import test_proxy
from services.register_service import register_service
from services.storage.factory import build_account_store, build_account_store_for_backend, get_account_storage_info
from services.storage.migrate import migrate_accounts
from services.sub2api_service import (
    list_remote_accounts as sub2api_list_remote_accounts,
    list_remote_groups as sub2api_list_remote_groups,
    sub2api_config,
    sub2api_import_service,
)
from services.image_service import ImageGenerationError
from services.system_settings import system_settings_service
from services.utils import (
    ImageRequestOptions,
    build_image_prompt,
    build_image_request_options,
    ensure_prompt_not_blocked,
    extract_chat_prompt,
    has_response_image_generation_tool,
    is_image_chat_request,
    parse_image_count,
    extract_response_prompt,
)
from services.version import get_app_version

BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIST_DIR = BASE_DIR / "web_dist"
SESSION_COOKIE_NAME = "chatgpt2api_session"
SESSION_COOKIE_MAX_AGE_SECONDS = 12 * 60 * 60
MAX_EDIT_UPLOAD_FILES = 4
MAX_EDIT_UPLOAD_BYTES_PER_FILE = 10 * 1024 * 1024
MAX_EDIT_UPLOAD_BYTES_TOTAL = 20 * 1024 * 1024
IMAGE_JOB_TTL_SECONDS = 30 * 60
IMAGE_JOB_MAX_ITEMS = 200
ALLOWED_EDIT_UPLOAD_MIME_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str = "auto"
    n: int = Field(default=1, ge=1, le=4)
    size: str | None = None
    quality: str | None = None
    background: str | None = None
    output_format: str | None = None
    compression: int | None = None
    response_format: str = "b64_json"
    history_disabled: bool = True


class AccountCreateRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)


class AccountDeleteRequest(BaseModel):
    tokens: list[str] = Field(default_factory=list)


class AccountRefreshRequest(BaseModel):
    access_tokens: list[str] = Field(default_factory=list)


class AccountUpdateRequest(BaseModel):
    access_token: str = Field(default="")
    type: str | None = None
    status: str | None = None
    quota: int | None = None


class ChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    prompt: str | None = None
    n: int | None = None
    stream: bool | None = None
    modalities: list[str] | None = None
    messages: list[dict[str, object]] | None = None
    thread_id: str | None = None
    threaded: bool | None = None


class ResponseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    input: object | None = None
    instructions: object | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: object | None = None
    stream: bool | None = None
    thread_id: str | None = None
    threaded: bool | None = None


class AnthropicMessageRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    messages: list[dict[str, object]] | None = None
    system: object | None = None
    stream: bool | None = None
    thread_id: str | None = None
    threaded: bool | None = None


class CPAPoolCreateRequest(BaseModel):
    name: str = ""
    base_url: str = ""
    secret_key: str = ""
    auto_sync_enabled: bool = False


class CPAPoolUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    secret_key: str | None = None
    auto_sync_enabled: bool | None = None


class CPAImportRequest(BaseModel):
    names: list[str] = Field(default_factory=list)


class AuthUserCreateRequest(BaseModel):
    name: str = ""
    auth_key: str = Field(default="")
    image_quota: int = Field(default=0, ge=0)


class AuthUserUpdateRequest(BaseModel):
    name: str | None = None
    auth_key: str | None = None
    image_quota: int | None = Field(default=None, ge=0)


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")


class RegisterProviderPayload(BaseModel):
    id: str | None = None
    type: str = ""
    enabled: bool = True
    api_key: str | None = None
    api_base: str | None = None
    default_domain: str | None = None
    expiry_time: int | None = Field(default=None, ge=0)
    domains: list[str] = Field(default_factory=list)


class RegisterMailPayload(BaseModel):
    request_timeout: int | None = Field(default=None, ge=1)
    wait_timeout: int | None = Field(default=None, ge=1)
    wait_interval: int | None = Field(default=None, ge=1)
    providers: list[RegisterProviderPayload] | None = None


class RegisterConfigUpdateRequest(BaseModel):
    mail: RegisterMailPayload | None = None
    proxy: str | None = None
    total: int | None = Field(default=None, ge=1)
    threads: int | None = Field(default=None, ge=1)
    mode: str | None = None
    target_quota: int | None = Field(default=None, ge=1)
    target_available: int | None = Field(default=None, ge=1)
    check_interval: int | None = Field(default=None, ge=1)


class ProxySettingsUpdateRequest(BaseModel):
    proxy_url: str = ""


class ProxyPoolEntryCreateRequest(BaseModel):
    name: str = ""
    proxy_url: str = ""


class ProxyPoolEntryUpdateRequest(BaseModel):
    name: str | None = None
    proxy_url: str | None = None


def _sanitize_storage_settings_update(body: dict[str, object]) -> dict[str, object]:
    payload = dict(body)
    storage_keys = ("storage_backend", "storage_sqlite_path")
    if not any(key in payload for key in storage_keys):
        return payload
    if not config.has_storage_env_override():
        return payload
    if config.storage_backend_env_override() is not None:
        requested_backend = str(payload.get("storage_backend") or "").strip().lower()
        if requested_backend == config.storage_backend:
            payload.pop("storage_backend", None)
    if config.storage_sqlite_path_env_override() is not None:
        requested_path = str(payload.get("storage_sqlite_path") or "").strip()
        if requested_path == str(config.storage_sqlite_path):
            payload.pop("storage_sqlite_path", None)
    if not any(key in payload for key in storage_keys):
        return payload
    current_backend, current_path = config.effective_account_storage_target()
    next_data = dict(config.data)
    next_data.update(payload)
    next_backend, next_path = config.effective_account_storage_target(next_data)
    if (next_backend, str(next_path)) != (current_backend, str(current_path)):
        active_overrides = config.active_storage_override_env_vars()
        raise HTTPException(
            status_code=400,
            detail={
                "error": (
                    "storage settings are controlled by environment overrides: "
                    + ", ".join(active_overrides)
                )
            },
        )
    return payload


def _build_account_store_for_target(target: tuple[str, Path]):
    backend, path = target
    return build_account_store_for_backend(backend, path=path)


def _apply_account_storage_change(previous_config: dict[str, object]) -> list[dict]:
    previous_target = config.effective_account_storage_target(previous_config)
    next_target = config.effective_account_storage_target(config.data)
    next_store = _build_account_store_for_target(next_target)
    if next_target == previous_target:
        return account_service.rebind_store(next_store)
    previous_store = _build_account_store_for_target(previous_target)
    destination_backup = next_store.load_accounts()
    try:
        migrate_accounts(previous_store, next_store)
        return account_service.rebind_store(next_store)
    except Exception as exc:
        restore_error: Exception | None = None
        try:
            next_store.save_accounts(destination_backup)
        except Exception as restore_exc:
            restore_error = restore_exc
        if restore_error is not None:
            raise RuntimeError(
                f"destination rollback failed after storage migration error: {restore_error}"
            ) from exc
        raise


class StoredReferenceImagePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = ""
    type: str = ""
    data_url: str = Field(default="", alias="dataUrl")


class StoredImagePayload(BaseModel):
    id: str = Field(default="")
    status: str | None = None
    b64_json: str | None = None
    mime_type: str | None = None
    error: str | None = None
    generation_route: str | None = None
    conversation_id: str | None = None
    last_message_id: str | None = None


class ImageTurnPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default="")
    prompt: str = ""
    model: str = ""
    mode: str | None = None
    aspect_ratio: str | None = Field(default=None, alias="aspectRatio")
    output_quality: str | None = Field(default=None, alias="outputQuality")
    render_quality: str | None = Field(default=None, alias="renderQuality")
    background: str | None = None
    output_format: str | None = Field(default=None, alias="outputFormat")
    compression: int | None = None
    reference_images: list[StoredReferenceImagePayload] = Field(default_factory=list, alias="referenceImages")
    count: int = Field(default=1)
    images: list[StoredImagePayload] = Field(default_factory=list)
    created_at: str = Field(default="", alias="createdAt")
    status: str = "success"
    error: str | None = None


class ImageConversationPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default="")
    title: str = ""
    created_at: str = Field(default="", alias="createdAt")
    updated_at: str = Field(default="", alias="updatedAt")
    turns: list[ImageTurnPayload] = Field(default_factory=list)
    prompt: str = ""
    model: str = ""
    mode: str | None = None
    aspect_ratio: str | None = Field(default=None, alias="aspectRatio")
    output_quality: str | None = Field(default=None, alias="outputQuality")
    render_quality: str | None = Field(default=None, alias="renderQuality")
    background: str | None = None
    output_format: str | None = Field(default=None, alias="outputFormat")
    compression: int | None = None
    reference_images: list[StoredReferenceImagePayload] = Field(default_factory=list, alias="referenceImages")
    count: int = Field(default=1)
    images: list[StoredImagePayload] = Field(default_factory=list)
    status: str = "success"
    error: str | None = None


class Sub2APIServerCreateRequest(BaseModel):
    name: str = ""
    base_url: str = ""
    email: str = ""
    password: str = ""
    api_key: str = ""
    group_id: str = ""
    auto_sync_enabled: bool = False


class Sub2APIServerUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    email: str | None = None
    password: str | None = None
    api_key: str | None = None
    group_id: str | None = None
    auto_sync_enabled: bool | None = None


class Sub2APIImportRequest(BaseModel):
    account_ids: list[str] = Field(default_factory=list)


class ProxyUpdateRequest(BaseModel):
    enabled: bool | None = None
    url: str | None = None


class ProxyTestRequest(BaseModel):
    url: str = ""


def build_model_item(model_id: str) -> dict[str, object]:
    return {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": "chatgpt2api",
    }


def sanitize_cpa_pool(pool: dict | None) -> dict | None:
    if not isinstance(pool, dict):
        return None
    return {
        key: value
        for key, value in pool.items()
        if key != "secret_key"
    }


def sanitize_cpa_pools(pools: list[dict]) -> list[dict]:
    return [sanitized for pool in pools if (sanitized := sanitize_cpa_pool(pool)) is not None]


_SUB2API_HIDDEN_FIELDS = {"password", "api_key"}


def sanitize_sub2api_server(server: dict | None) -> dict | None:
    if not isinstance(server, dict):
        return None
    sanitized = {key: value for key, value in server.items() if key not in _SUB2API_HIDDEN_FIELDS}
    sanitized["has_api_key"] = bool(str(server.get("api_key") or "").strip())
    return sanitized


def sanitize_sub2api_servers(servers: list[dict]) -> list[dict]:
    return [sanitized for server in servers if (sanitized := sanitize_sub2api_server(server)) is not None]


def extract_bearer_token(authorization: str | None) -> str:
    scheme, _, value = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return ""
    return value.strip()


def require_auth_key(authorization: str | None) -> None:
    if not config.verify_admin_auth_key(extract_bearer_token(authorization)):
        raise HTTPException(status_code=401, detail={"error": "authorization is invalid"})


def build_session_cookie_payload(identity: dict) -> dict[str, object]:
    payload = {
        "role": str(identity.get("role") or "").strip(),
    }
    if payload["role"] == "user":
        payload["user_id"] = str(identity.get("id") or "").strip()
        payload["auth_key_hash"] = str(identity.get("auth_key_hash") or "").strip()
    return payload


def set_session_cookie(response: Response, identity: dict, request: Request) -> None:
    secret = str(config.session_signing_secret or "").strip()
    if not secret:
        raise HTTPException(status_code=500, detail={"error": "session secret is not configured"})
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=build_signed_token(build_session_cookie_payload(identity), secret),
        httponly=True,
        max_age=SESSION_COOKIE_MAX_AGE_SECONDS,
        path="/",
        samesite="lax",
        secure=request.url.scheme == "https",
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        samesite="lax",
        secure=request.url.scheme == "https",
    )


def authenticate_session_cookie(request: Request) -> dict | None:
    token = str(request.cookies.get(SESSION_COOKIE_NAME) or "").strip()
    secret = str(config.session_signing_secret or "").strip()
    if not token or not secret:
        return None
    payload = read_signed_token(token, secret)
    if payload is None:
        return None
    if payload.get("role") == "admin":
        return auth_service.admin_identity()
    if payload.get("role") != "user":
        return None
    user = auth_service.get_user_by_id(str(payload.get("user_id") or ""))
    if user is None:
        return None
    if str(payload.get("auth_key_hash") or "") != str(user.get("auth_key_hash") or ""):
        return None
    return user


def require_session(request: Request, authorization: str | None) -> dict:
    identity = auth_service.authenticate(extract_bearer_token(authorization))
    if identity is None:
        identity = authenticate_session_cookie(request)
    if identity is None:
        raise HTTPException(status_code=401, detail={"error": "authorization is invalid"})
    return identity


def require_admin_session(request: Request, authorization: str | None) -> dict:
    identity = require_session(request, authorization)
    if identity.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"error": "admin permission required"})
    return identity


def count_generated_images(payload: dict[str, object]) -> int:
    data = payload.get("data")
    if not isinstance(data, list):
        return 0
    return sum(
        1
        for item in data
        if isinstance(item, dict)
        and (
            str(item.get("b64_json") or "").strip()
            or str(item.get("url") or "").strip()
        )
    )


def count_chat_completion_images(payload: dict[str, object]) -> int:
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return 0
    count = 0
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        count += str(message.get("content") or "").count("![image_")
    return count


def count_response_images(payload: dict[str, object]) -> int:
    output = payload.get("output")
    if not isinstance(output, list):
        return 0
    return sum(
        1
        for item in output
        if isinstance(item, dict) and str(item.get("type") or "").strip() == "image_generation_call"
    )


def normalize_image_response_format(value: object) -> str:
    normalized = str(value or "b64_json").strip().lower() or "b64_json"
    if normalized not in {"b64_json", "url"}:
        raise ValueError("response_format must be one of b64_json, url")
    return normalized


def build_image_job_owner(identity: dict) -> dict[str, str]:
    role = str(identity.get("role") or "").strip()
    owner_id = str(identity.get("id") or ("admin" if role == "admin" else "")).strip()
    return {
        "ownerRole": role,
        "ownerId": owner_id,
    }


def resolve_image_base_url(_request: Request | None = None) -> str:
    return str(config.base_url or "").strip().rstrip("/")


def require_image_base_url() -> str:
    base_url = resolve_image_base_url()
    if base_url:
        return base_url
    raise HTTPException(status_code=400, detail={"error": "base_url is required when response_format=url"})


async def load_validated_edit_uploads(uploads: list[UploadFile]) -> list[tuple[bytes, str, str]]:
    if len(uploads) > MAX_EDIT_UPLOAD_FILES:
        raise HTTPException(
            status_code=400,
            detail={"error": f"at most {MAX_EDIT_UPLOAD_FILES} image files are allowed"},
        )

    images: list[tuple[bytes, str, str]] = []
    total_bytes = 0
    for upload in uploads:
        mime_type = str(upload.content_type or "").strip().lower()
        if mime_type not in ALLOWED_EDIT_UPLOAD_MIME_TYPES:
            raise HTTPException(status_code=400, detail={"error": "unsupported image file type"})

        image_data = await upload.read(MAX_EDIT_UPLOAD_BYTES_PER_FILE + 1)
        if not image_data:
            raise HTTPException(status_code=400, detail={"error": "image file is empty"})
        if len(image_data) > MAX_EDIT_UPLOAD_BYTES_PER_FILE:
            raise HTTPException(
                status_code=413,
                detail={"error": f"image file exceeds {MAX_EDIT_UPLOAD_BYTES_PER_FILE // (1024 * 1024)}MB limit"},
            )

        total_bytes += len(image_data)
        if total_bytes > MAX_EDIT_UPLOAD_BYTES_TOTAL:
            raise HTTPException(
                status_code=413,
                detail={"error": f"total image upload size exceeds {MAX_EDIT_UPLOAD_BYTES_TOTAL // (1024 * 1024)}MB limit"},
            )

        file_name = upload.filename or "image.png"
        images.append((image_data, file_name, mime_type))
    return images


def resolve_cors_origins() -> list[str]:
    origins = {
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    }
    parsed = urlparse(str(config.base_url or "").strip())
    if parsed.scheme and parsed.netloc:
        origins.add(f"{parsed.scheme}://{parsed.netloc}")
    return sorted(origins)


def refresh_all_accounts_once() -> int:
    access_tokens = account_service.list_tokens()
    if not access_tokens:
        return 0
    print(f"[account-refresh-watcher] refreshing {len(access_tokens)} accounts")
    account_service.refresh_accounts(access_tokens)
    return len(access_tokens)


def start_limited_account_watcher(stop_event: Event) -> Thread:
    def worker() -> None:
        while not stop_event.is_set():
            try:
                refresh_all_accounts_once()
            except Exception as exc:
                print(f"[account-refresh-watcher] fail {exc}")
            stop_event.wait(config.refresh_account_interval_minute * 60)

    thread = Thread(target=worker, name="account-refresh-watcher", daemon=True)
    thread.start()
    return thread


def sync_remote_account_sources_once() -> None:
    for pool in cpa_config.list_pools():
        if not bool(pool.get("auto_sync_enabled")):
            continue
        pool_id = str(pool.get("id") or "").strip()
        try:
            job = cpa_import_service.start_auto_import(pool)
            if job is not None:
                print(f"[remote-account-sync] started cpa auto sync pool={pool_id} total={job.get('total')}")
        except Exception as exc:
            print(f"[remote-account-sync] cpa pool={pool_id or 'unknown'} fail {exc}")

    for server in sub2api_config.list_servers():
        if not bool(server.get("auto_sync_enabled")):
            continue
        server_id = str(server.get("id") or "").strip()
        try:
            job = sub2api_import_service.start_auto_import(server)
            if job is not None:
                print(f"[remote-account-sync] started sub2api auto sync server={server_id} total={job.get('total')}")
        except Exception as exc:
            print(f"[remote-account-sync] sub2api server={server_id or 'unknown'} fail {exc}")


def start_remote_account_sync_watcher(stop_event: Event) -> Thread:
    def worker() -> None:
        while not stop_event.wait(config.remote_account_sync_interval_minute * 60):
            try:
                sync_remote_account_sources_once()
            except Exception as exc:
                print(f"[remote-account-sync] watcher fail {exc}")

    thread = Thread(target=worker, name="remote-account-sync-watcher", daemon=True)
    thread.start()
    return thread


def resolve_web_asset(requested_path: str) -> Path | None:
    if not WEB_DIST_DIR.exists():
        return None

    clean_path = requested_path.strip("/")
    if not clean_path:
        candidates = [WEB_DIST_DIR / "index.html"]
    else:
        relative_path = Path(clean_path)
        candidates = [
            WEB_DIST_DIR / relative_path,
            WEB_DIST_DIR / relative_path / "index.html",
            WEB_DIST_DIR / f"{clean_path}.html",
        ]

    for candidate in candidates:
        try:
            candidate.relative_to(WEB_DIST_DIR)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate

    return None


def serve_web_asset(full_path: str) -> FileResponse:
    asset = resolve_web_asset(full_path)
    if asset is not None:
        return FileResponse(asset)

    # Static assets (_next/*) must not fallback to HTML — return 404
    if full_path.strip("/").startswith("_next/"):
        raise HTTPException(status_code=404, detail="Not Found")

    fallback = resolve_web_asset("")
    if fallback is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(fallback)


def create_app() -> FastAPI:
    chatgpt_service = ChatGPTService(account_service)
    app_version = get_app_version()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stop_event = Event()
        limited_thread = start_limited_account_watcher(stop_event)
        remote_sync_thread = start_remote_account_sync_watcher(stop_event)
        try:
            yield
        finally:
            stop_event.set()
            limited_thread.join(timeout=1)
            remote_sync_thread.join(timeout=1)

    app = FastAPI(title="chatgpt2api", version=app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolve_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    router = APIRouter()
    image_jobs: dict[str, dict[str, object]] = {}
    image_jobs_lock = Lock()

    def cleanup_image_jobs_locked(now: float | None = None) -> None:
        current_time = now if now is not None else time.time()
        expired_ids = [
            job_id
            for job_id, job in image_jobs.items()
            if current_time - float(job.get("updatedAt") or job.get("createdAt") or 0) > IMAGE_JOB_TTL_SECONDS
        ]
        for job_id in expired_ids:
            image_jobs.pop(job_id, None)

        if len(image_jobs) <= IMAGE_JOB_MAX_ITEMS:
            return
        sorted_jobs = sorted(image_jobs.items(), key=lambda item: float(item[1].get("updatedAt") or 0))
        for job_id, _job in sorted_jobs[: len(image_jobs) - IMAGE_JOB_MAX_ITEMS]:
            image_jobs.pop(job_id, None)

    def serialize_image_job(job: dict[str, object]) -> dict[str, object]:
        payload = {
            "id": job["id"],
            "status": job["status"],
            "createdAt": job["createdAt"],
            "updatedAt": job["updatedAt"],
        }
        if job.get("result") is not None:
            payload["result"] = job["result"]
        if job.get("error"):
            payload["error"] = job["error"]
        return payload

    def create_image_job(identity: dict) -> dict[str, object]:
        now = time.time()
        owner = build_image_job_owner(identity)
        job = {
            "id": uuid.uuid4().hex,
            "status": "queued",
            "createdAt": now,
            "updatedAt": now,
            **owner,
        }
        with image_jobs_lock:
            cleanup_image_jobs_locked(now)
            image_jobs[str(job["id"])] = job
            return dict(job)

    def get_image_job_for_identity(job_id: str, identity: dict) -> dict[str, object]:
        owner = build_image_job_owner(identity)
        with image_jobs_lock:
            cleanup_image_jobs_locked()
            job = image_jobs.get(job_id)
            if (
                job is None
                or job.get("ownerRole") != owner["ownerRole"]
                or job.get("ownerId") != owner["ownerId"]
            ):
                raise HTTPException(status_code=404, detail={"error": "image job not found"})
            return dict(job)

    def update_image_job(job_id: str, **updates: object) -> None:
        with image_jobs_lock:
            job = image_jobs.get(job_id)
            if job is None:
                return
            job.update(updates)
            job["updatedAt"] = time.time()

    def run_generation_image_job(
            job_id: str,
            identity: dict,
            reserved_count: int,
            prompt: str,
            model: str,
            n: int,
            image_options: ImageRequestOptions,
            response_format: str,
            base_url: str | None,
    ) -> None:
        try:
            update_image_job(job_id, status="running")
            result = chatgpt_service.generate_with_pool(
                prompt,
                model,
                n,
                image_options=image_options,
                response_format=response_format,
                base_url=base_url,
            )
            auth_service.settle_images_for_identity(identity, reserved_count, count_generated_images(result))
            update_image_job(job_id, status="success", result=result)
        except ImageGenerationError as exc:
            auth_service.settle_images_for_identity(identity, reserved_count, 0)
            update_image_job(job_id, status="error", error=str(exc))
        except Exception as exc:
            auth_service.settle_images_for_identity(identity, reserved_count, 0)
            print(f"[image-job] generation failed job={job_id} error={exc}")
            update_image_job(job_id, status="error", error=str(exc) or "生成图片失败")

    def run_edit_image_job(
            job_id: str,
            identity: dict,
            reserved_count: int,
            prompt: str,
            images: list[tuple[bytes, str, str]],
            model: str,
            n: int,
            image_options: ImageRequestOptions,
            response_format: str,
            base_url: str | None,
    ) -> None:
        try:
            update_image_job(job_id, status="running")
            result = chatgpt_service.edit_with_pool(
                prompt,
                images,
                model,
                n,
                image_options=image_options,
                response_format=response_format,
                base_url=base_url,
            )
            auth_service.settle_images_for_identity(identity, reserved_count, count_generated_images(result))
            update_image_job(job_id, status="success", result=result)
        except ImageGenerationError as exc:
            auth_service.settle_images_for_identity(identity, reserved_count, 0)
            update_image_job(job_id, status="error", error=str(exc))
        except Exception as exc:
            auth_service.settle_images_for_identity(identity, reserved_count, 0)
            print(f"[image-job] edit failed job={job_id} error={exc}")
            update_image_job(job_id, status="error", error=str(exc) or "编辑图片失败")

    def run_inpaint_image_job(
            job_id: str,
            identity: dict,
            reserved_count: int,
            prompt: str,
            original_image: tuple[bytes, str, str],
            mask_data: bytes,
            model: str,
            image_options: ImageRequestOptions,
            response_format: str,
            base_url: str | None,
            original_gen_id: str,
            ref_images: list[tuple[bytes, str, str]] | None,
            conversation_id: str = "",
            parent_message_id: str = "",
    ) -> None:
        try:
            update_image_job(job_id, status="running")
            result = chatgpt_service.inpaint_with_pool(
                prompt,
                original_image,
                mask_data,
                model,
                response_format=response_format,
                base_url=base_url,
                original_gen_id=original_gen_id,
                ref_images=ref_images,
                image_options=image_options,
                conversation_id=conversation_id,
                parent_message_id=parent_message_id,
            )
            auth_service.settle_images_for_identity(identity, reserved_count, count_generated_images(result))
            update_image_job(job_id, status="success", result=result)
        except ImageGenerationError as exc:
            auth_service.settle_images_for_identity(identity, reserved_count, 0)
            update_image_job(job_id, status="error", error=str(exc))
        except Exception as exc:
            auth_service.settle_images_for_identity(identity, reserved_count, 0)
            print(f"[image-job] inpaint failed job={job_id} error={exc}")
            update_image_job(job_id, status="error", error=str(exc) or "遮罩编辑失败")

    @router.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [build_model_item(model) for model in chatgpt_service.list_models()],
        }

    @router.post("/auth/login")
    async def login(
            request: Request,
            response: Response,
            authorization: str | None = Header(default=None),
    ):
        identity = auth_service.authenticate(extract_bearer_token(authorization))
        if identity is None:
            raise HTTPException(status_code=401, detail={"error": "authorization is invalid"})
        set_session_cookie(response, identity, request)
        return {
            "ok": True,
            "version": app_version,
            "session": auth_service.build_session_from_identity(identity),
        }

    @router.get("/auth/session")
    async def get_auth_session(request: Request, authorization: str | None = Header(default=None)):
        identity = require_session(request, authorization)
        return {"session": auth_service.build_session_from_identity(identity)}

    @router.post("/auth/logout")
    async def logout(request: Request, response: Response):
        clear_session_cookie(response, request)
        return {"ok": True}

    @router.get("/version")
    async def get_version():
        return {"version": app_version}

    @router.get("/api/settings")
    async def get_settings(request: Request, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        return {"config": config.get()}

    @router.get("/api/storage/info")
    async def get_storage_info(request: Request, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        return {"storage": get_account_storage_info(config)}

    @router.post("/api/settings")
    async def save_settings(
            request: Request,
            body: SettingsUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        previous_config = dict(config.data)
        try:
            incoming = _sanitize_storage_settings_update(
                body.model_dump(mode="python", exclude_unset=True),
            )
            updated_config = config.update(incoming)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        try:
            _apply_account_storage_change(previous_config)
        except Exception as exc:
            if dict(config.data) != previous_config:
                config.data = previous_config
                config._save()
                try:
                    account_service.rebind_store(build_account_store(config))
                except Exception:
                    pass
            raise HTTPException(status_code=400, detail={"error": f"failed to apply storage settings: {exc}"}) from exc
        return {"config": updated_config}

    @router.get("/api/register")
    async def get_register(request: Request, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        return {"register": register_service.get()}

    @router.post("/api/register")
    async def update_register(
            request: Request,
            body: RegisterConfigUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        payload = body.model_dump(mode="python", exclude_none=True)
        return {"register": register_service.update(payload)}

    @router.post("/api/register/start")
    async def start_register(request: Request, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        try:
            return {"register": register_service.start()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.post("/api/register/stop")
    async def stop_register(request: Request, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        return {"register": register_service.stop()}

    @router.post("/api/register/reset")
    async def reset_register(request: Request, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        try:
            return {"register": register_service.reset()}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @router.get("/api/logs")
    async def get_logs(
            request: Request,
            authorization: str | None = Header(default=None),
            source: str = LOG_SOURCE_ALL,
            query: str = "",
            level: str = LOG_LEVEL_ALL,
            limit: int = 200,
    ):
        require_admin_session(request, authorization)
        items = log_service.list(source=source, query=query, level=level, limit=limit)
        return {
            "items": items,
            "query": {
                "source": source,
                "query": query,
                "level": level,
                "limit": limit,
            },
        }

    @router.get("/api/accounts")
    async def get_accounts(request: Request, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        return {"items": account_service.list_accounts()}

    @router.post("/api/accounts")
    async def create_accounts(request: Request, body: AccountCreateRequest, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        tokens = [str(token or "").strip() for token in body.tokens if str(token or "").strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens is required"})
        result = account_service.add_accounts(tokens)
        refresh_result = account_service.refresh_accounts(tokens)
        return {
            **result,
            "refreshed": refresh_result.get("refreshed", 0),
            "errors": refresh_result.get("errors", []),
            "items": refresh_result.get("items", result.get("items", [])),
        }

    @router.delete("/api/accounts")
    async def delete_accounts(request: Request, body: AccountDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        tokens = [str(token or "").strip() for token in body.tokens if str(token or "").strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens is required"})
        return account_service.delete_accounts(tokens)

    @router.post("/api/accounts/refresh")
    async def refresh_accounts(request: Request, body: AccountRefreshRequest, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        access_tokens = [str(token or "").strip() for token in body.access_tokens if str(token or "").strip()]
        if not access_tokens:
            access_tokens = account_service.list_tokens()
        if not access_tokens:
            raise HTTPException(status_code=400, detail={"error": "access_tokens is required"})
        return account_service.refresh_accounts(access_tokens)

    @router.post("/api/accounts/update")
    async def update_account(request: Request, body: AccountUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        access_token = str(body.access_token or "").strip()
        if not access_token:
            raise HTTPException(status_code=400, detail={"error": "access_token is required"})

        updates = {
            key: value
            for key, value in {
                "type": body.type,
                "status": body.status,
                "quota": body.quota,
            }.items()
            if value is not None
        }
        if not updates:
            raise HTTPException(status_code=400, detail={"error": "no updates provided"})

        account = account_service.update_account(access_token, updates)
        if account is None:
            raise HTTPException(status_code=404, detail={"error": "account not found"})
        return {"item": account, "items": account_service.list_accounts()}

    @router.get("/api/auth-users")
    async def list_auth_users(request: Request, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        return {"items": auth_service.list_users()}

    @router.post("/api/auth-users")
    async def create_auth_user(request: Request, body: AuthUserCreateRequest, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        try:
            item = auth_service.create_user(body.name, body.auth_key, body.image_quota)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, "items": auth_service.list_users()}

    @router.post("/api/auth-users/{user_id}")
    async def update_auth_user(
            request: Request,
            user_id: str,
            body: AuthUserUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        updates = {
            key: value
            for key, value in {
                "name": body.name,
                "auth_key": body.auth_key,
                "image_quota": body.image_quota,
            }.items()
            if value is not None
        }
        if not updates:
            raise HTTPException(status_code=400, detail={"error": "no updates provided"})
        try:
            item = auth_service.update_user(user_id, updates)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "user not found"})
        return {"item": item, "items": auth_service.list_users()}

    @router.delete("/api/auth-users/{user_id}")
    async def delete_auth_user(request: Request, user_id: str, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        if not auth_service.delete_user(user_id):
            raise HTTPException(status_code=404, detail={"error": "user not found"})
        return {"items": auth_service.list_users()}

    @router.get("/api/image-conversations")
    async def list_image_conversations(request: Request, authorization: str | None = Header(default=None)):
        identity = require_session(request, authorization)
        return {"items": image_history_service.list_conversations(identity)}

    @router.post("/api/image-conversations")
    async def save_image_conversation(request: Request, body: ImageConversationPayload, authorization: str | None = Header(default=None)):
        identity = require_session(request, authorization)
        try:
            item = image_history_service.save_conversation(identity, body.model_dump(mode="python", by_alias=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc
        return {"item": item}

    @router.delete("/api/image-conversations")
    async def clear_image_conversations(request: Request, authorization: str | None = Header(default=None)):
        identity = require_session(request, authorization)
        return {"removed": image_history_service.clear_conversations(identity)}

    @router.delete("/api/image-conversations/{conversation_id}")
    async def delete_image_conversation(request: Request, conversation_id: str, authorization: str | None = Header(default=None)):
        identity = require_session(request, authorization)
        if not image_history_service.delete_conversation(identity, conversation_id):
            raise HTTPException(status_code=404, detail={"error": "conversation not found"})
        return {"ok": True}

    @router.get("/api/settings/proxy")
    async def get_proxy_settings(request: Request, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        return {"item": system_settings_service.get_proxy_settings()}

    @router.post("/api/settings/proxy")
    async def update_proxy_settings(request: Request, body: ProxySettingsUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        try:
            item = system_settings_service.update_proxy_url(body.proxy_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item}

    @router.get("/api/settings/proxies")
    async def get_proxy_pool_settings(request: Request, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        return system_settings_service.get_proxy_pool_settings()

    @router.post("/api/settings/proxies")
    async def create_proxy_entry(request: Request, body: ProxyPoolEntryCreateRequest, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        try:
            system_settings_service.create_proxy_entry(body.name, body.proxy_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return system_settings_service.get_proxy_pool_settings()

    @router.post("/api/settings/proxies/{proxy_id}")
    async def update_proxy_entry(
            request: Request,
            proxy_id: str,
            body: ProxyPoolEntryUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        updates = {
            key: value
            for key, value in {
                "name": body.name,
                "proxy_url": body.proxy_url,
            }.items()
            if value is not None
        }
        if not updates:
            raise HTTPException(status_code=400, detail={"error": "no updates provided"})
        try:
            item = system_settings_service.update_proxy_entry(proxy_id, updates)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "proxy not found"})
        return system_settings_service.get_proxy_pool_settings()

    @router.delete("/api/settings/proxies/{proxy_id}")
    async def delete_proxy_entry(request: Request, proxy_id: str, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        if not system_settings_service.delete_proxy_entry(proxy_id):
            raise HTTPException(status_code=404, detail={"error": "proxy not found"})
        return system_settings_service.get_proxy_pool_settings()

    @router.post("/api/image-jobs/generations")
    async def create_image_generation_job(
            body: ImageGenerationRequest,
            request: Request,
            authorization: str | None = Header(default=None),
    ):
        identity = require_session(request, authorization)
        reserved_count = int(body.n or 1)
        try:
            image_options = build_image_request_options(
                model=body.model,
                size=body.size,
                quality=body.quality,
                background=body.background,
                output_format=body.output_format,
                compression=body.compression,
            )
            normalized_response_format = normalize_image_response_format(body.response_format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        base_url = require_image_base_url() if normalized_response_format == "url" else None
        prompt = build_image_prompt(body.prompt, image_options)
        ensure_prompt_not_blocked(
            prompt,
            enabled=bool(getattr(config, "sensitive_word_filter_enabled", False)),
            sensitive_words=getattr(config, "sensitive_words", []),
        )
        try:
            auth_service.reserve_images_for_identity(identity, reserved_count)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc

        job = create_image_job(identity)
        Thread(
            target=run_generation_image_job,
            args=(
                job["id"],
                dict(identity),
                reserved_count,
                prompt,
                body.model,
                body.n,
                image_options,
                normalized_response_format,
                base_url,
            ),
            name=f"image-generation-job-{job['id']}",
            daemon=True,
        ).start()
        return {"job": serialize_image_job(job)}

    @router.post("/api/image-jobs/edits")
    async def create_image_edit_job(
            request: Request,
            authorization: str | None = Header(default=None),
            image: list[UploadFile] | None = File(default=None),
            image_list: list[UploadFile] | None = File(default=None, alias="image[]"),
            prompt: str = Form(...),
            model: str = Form(default="gpt-image-2"),
            n: int = Form(default=1),
            size: str | None = Form(default=None),
            quality: str | None = Form(default=None),
            background: str | None = Form(default=None),
            output_format: str | None = Form(default=None),
            compression: int | None = Form(default=None),
            response_format: str = Form(default="b64_json"),
    ):
        identity = require_session(request, authorization)
        if n < 1 or n > 4:
            raise HTTPException(status_code=400, detail={"error": "n must be between 1 and 4"})

        uploads = [*(image or []), *(image_list or [])]
        if not uploads:
            raise HTTPException(status_code=400, detail={"error": "image file is required"})

        try:
            image_options = build_image_request_options(
                model=model,
                size=size,
                quality=quality,
                background=background,
                output_format=output_format,
                compression=compression,
            )
            normalized_response_format = normalize_image_response_format(response_format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        base_url = require_image_base_url() if normalized_response_format == "url" else None
        images = await load_validated_edit_uploads(uploads)
        normalized_prompt = build_image_prompt(prompt, image_options)
        ensure_prompt_not_blocked(
            normalized_prompt,
            enabled=bool(getattr(config, "sensitive_word_filter_enabled", False)),
            sensitive_words=getattr(config, "sensitive_words", []),
        )
        try:
            auth_service.reserve_images_for_identity(identity, n)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc

        job = create_image_job(identity)
        Thread(
            target=run_edit_image_job,
            args=(
                job["id"],
                dict(identity),
                n,
                normalized_prompt,
                images,
                model,
                n,
                image_options,
                normalized_response_format,
                base_url,
            ),
            name=f"image-edit-job-{job['id']}",
            daemon=True,
        ).start()
        return {"job": serialize_image_job(job)}

    @router.post("/api/image-jobs/inpaint")
    async def create_image_inpaint_job(
            request: Request,
            authorization: str | None = Header(default=None),
            image: UploadFile = File(...),
            mask: UploadFile = File(...),
            prompt: str = Form(...),
            model: str = Form(default="gpt-image-2"),
            size: str | None = Form(default=None),
            quality: str | None = Form(default=None),
            background: str | None = Form(default=None),
            output_format: str | None = Form(default=None),
            compression: int | None = Form(default=None),
            response_format: str = Form(default="b64_json"),
            original_gen_id: str | None = Form(default=None),
            ref_image: list[UploadFile] | None = File(default=None),
            conversation_id: str | None = Form(default=None),
            parent_message_id: str | None = Form(default=None),
    ):
        identity = require_session(request, authorization)

        try:
            image_options = build_image_request_options(
                model=model,
                size=size,
                quality=quality,
                background=background,
                output_format=output_format,
                compression=compression,
            )
            normalized_response_format = normalize_image_response_format(response_format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

        base_url = require_image_base_url() if normalized_response_format == "url" else None
        original_data = await image.read()
        if not original_data:
            raise HTTPException(status_code=400, detail={"error": "image file is empty"})
        mask_data = await mask.read()
        if not mask_data:
            raise HTTPException(status_code=400, detail={"error": "mask file is empty"})

        original_image_tuple = (original_data, image.filename or "image.png", image.content_type or "image/png")
        ref_images: list[tuple[bytes, str, str]] | None = None
        if ref_image:
            ref_images = []
            for rf in ref_image:
                rf_data = await rf.read()
                if rf_data:
                    ref_images.append((rf_data, rf.filename or "ref.png", rf.content_type or "image/png"))
            if not ref_images:
                ref_images = None

        normalized_prompt = build_image_prompt(prompt, image_options)
        ensure_prompt_not_blocked(
            normalized_prompt,
            enabled=bool(getattr(config, "sensitive_word_filter_enabled", False)),
            sensitive_words=getattr(config, "sensitive_words", []),
        )
        try:
            auth_service.reserve_images_for_identity(identity, 1)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc

        job = create_image_job(identity)
        Thread(
            target=run_inpaint_image_job,
            args=(
                job["id"],
                dict(identity),
                1,
                normalized_prompt,
                original_image_tuple,
                mask_data,
                model,
                image_options,
                normalized_response_format,
                base_url,
                str(original_gen_id or ""),
                ref_images,
                str(conversation_id or ""),
                str(parent_message_id or ""),
            ),
            name=f"image-inpaint-job-{job['id']}",
            daemon=True,
        ).start()
        return {"job": serialize_image_job(job)}

    @router.get("/api/image-jobs/{job_id}")
    async def get_image_job(job_id: str, request: Request, authorization: str | None = Header(default=None)):
        identity = require_session(request, authorization)
        return {"job": serialize_image_job(get_image_job_for_identity(job_id, identity))}

    @router.post("/v1/images/generations")
    async def generate_images(
            body: ImageGenerationRequest,
            request: Request,
            authorization: str | None = Header(default=None)
    ):
        identity = require_session(request, authorization)
        reserved_count = int(body.n or 1)
        try:
            image_options = build_image_request_options(
                model=body.model,
                size=body.size,
                quality=body.quality,
                background=body.background,
                output_format=body.output_format,
                compression=body.compression,
            )
            normalized_response_format = normalize_image_response_format(body.response_format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        base_url = require_image_base_url() if normalized_response_format == "url" else None
        prompt = build_image_prompt(body.prompt, image_options)
        ensure_prompt_not_blocked(
            prompt,
            enabled=bool(getattr(config, "sensitive_word_filter_enabled", False)),
            sensitive_words=getattr(config, "sensitive_words", []),
        )
        try:
            auth_service.reserve_images_for_identity(identity, reserved_count)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc
        try:
            result = await run_in_threadpool(
                chatgpt_service.generate_with_pool,
                prompt,
                body.model,
                body.n,
                image_options=image_options,
                response_format=normalized_response_format,
                base_url=base_url,
            )
        except ImageGenerationError as exc:
            auth_service.settle_images_for_identity(identity, reserved_count, 0)
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        except Exception:
            auth_service.settle_images_for_identity(identity, reserved_count, 0)
            raise
        auth_service.settle_images_for_identity(identity, reserved_count, count_generated_images(result))
        return result

    @router.post("/v1/images/edits")
    async def edit_images(
            request: Request,
            authorization: str | None = Header(default=None),
            image: list[UploadFile] | None = File(default=None),
            image_list: list[UploadFile] | None = File(default=None, alias="image[]"),
            mask: UploadFile | None = File(default=None),
            prompt: str = Form(...),
            model: str = Form(default="gpt-image-2"),
            n: int = Form(default=1),
            size: str | None = Form(default=None),
            quality: str | None = Form(default=None),
            background: str | None = Form(default=None),
            output_format: str | None = Form(default=None),
            compression: int | None = Form(default=None),
            response_format: str = Form(default="b64_json"),
            original_gen_id: str | None = Form(default=None),
    ):
        identity = require_session(request, authorization)
        if n < 1 or n > 4:
            raise HTTPException(status_code=400, detail={"error": "n must be between 1 and 4"})

        uploads = [*(image or []), *(image_list or [])]
        if not uploads:
            raise HTTPException(status_code=400, detail={"error": "image file is required"})

        try:
            image_options = build_image_request_options(
                model=model,
                size=size,
                quality=quality,
                background=background,
                output_format=output_format,
                compression=compression,
            )
            normalized_response_format = normalize_image_response_format(response_format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        base_url = require_image_base_url() if normalized_response_format == "url" else None
        images = await load_validated_edit_uploads(uploads)
        normalized_prompt = build_image_prompt(prompt, image_options)
        ensure_prompt_not_blocked(
            normalized_prompt,
            enabled=bool(getattr(config, "sensitive_word_filter_enabled", False)),
            sensitive_words=getattr(config, "sensitive_words", []),
        )
        try:
            auth_service.reserve_images_for_identity(identity, n)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc

        # inpainting 模式：当提供 mask 且 n=1 时走 inpaint 流程
        if mask is not None:
            if n != 1:
                auth_service.settle_images_for_identity(identity, n, 0)
                raise HTTPException(status_code=400, detail={"error": "inpainting only supports n=1"})
            mask_data = await mask.read()
            if not mask_data:
                auth_service.settle_images_for_identity(identity, n, 0)
                raise HTTPException(status_code=400, detail={"error": "mask file is empty"})
            original_image = images[0]  # (bytes, file_name, mime_type)
            ref_images = images[1:] if len(images) > 1 else None
            try:
                result = await run_in_threadpool(
                    chatgpt_service.inpaint_with_pool,
                    normalized_prompt,
                    original_image,
                    mask_data,
                    model,
                    normalized_response_format,
                    base_url,
                    original_gen_id=str(original_gen_id or ""),
                    ref_images=ref_images,
                    image_options=image_options,
                )
            except ImageGenerationError as exc:
                auth_service.settle_images_for_identity(identity, n, 0)
                raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
            except Exception:
                auth_service.settle_images_for_identity(identity, n, 0)
                raise
            auth_service.settle_images_for_identity(identity, n, count_generated_images(result))
            return result

        try:
            result = await run_in_threadpool(
                chatgpt_service.edit_with_pool,
                normalized_prompt,
                images,
                model,
                n,
                image_options=image_options,
                response_format=normalized_response_format,
                base_url=base_url,
            )
        except ImageGenerationError as exc:
            auth_service.settle_images_for_identity(identity, n, 0)
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        except Exception:
            auth_service.settle_images_for_identity(identity, n, 0)
            raise
        auth_service.settle_images_for_identity(identity, n, count_generated_images(result))
        return result

    @router.post("/v1/chat/completions")
    async def create_chat_completion(request: Request, body: ChatCompletionRequest, authorization: str | None = Header(default=None)):
        identity = require_session(request, authorization)
        payload = body.model_dump(mode="python")
        if not is_image_chat_request(payload):
            if bool(payload.get("stream")):
                return StreamingResponse(
                    chatgpt_service.create_text_completion_stream(payload, identity),
                    media_type="text/event-stream",
                )
            return await run_in_threadpool(chatgpt_service.create_text_completion, payload, identity)
        ensure_prompt_not_blocked(
            extract_chat_prompt(payload),
            enabled=bool(getattr(config, "sensitive_word_filter_enabled", False)),
            sensitive_words=getattr(config, "sensitive_words", []),
        )
        reserved_count = parse_image_count(payload.get("n"))
        try:
            auth_service.reserve_images_for_identity(identity, reserved_count)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc
        try:
            result = await run_in_threadpool(chatgpt_service.create_image_completion, payload)
        except HTTPException:
            auth_service.settle_images_for_identity(identity, reserved_count, 0)
            raise
        except Exception:
            auth_service.settle_images_for_identity(identity, reserved_count, 0)
            raise
        auth_service.settle_images_for_identity(identity, reserved_count, count_chat_completion_images(result))
        return result

    @router.post("/v1/responses")
    async def create_response(request: Request, body: ResponseCreateRequest, authorization: str | None = Header(default=None)):
        identity = require_session(request, authorization)
        payload = body.model_dump(mode="python")
        if not has_response_image_generation_tool(payload):
            return await run_in_threadpool(chatgpt_service.create_text_response, payload, identity)
        ensure_prompt_not_blocked(
            extract_response_prompt(payload.get("input")),
            enabled=bool(getattr(config, "sensitive_word_filter_enabled", False)),
            sensitive_words=getattr(config, "sensitive_words", []),
        )
        try:
            auth_service.reserve_images_for_identity(identity, 1)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc
        try:
            result = await run_in_threadpool(chatgpt_service.create_response, payload)
        except HTTPException:
            auth_service.settle_images_for_identity(identity, 1, 0)
            raise
        except Exception:
            auth_service.settle_images_for_identity(identity, 1, 0)
            raise
        auth_service.settle_images_for_identity(identity, 1, count_response_images(result))
        return result

    @router.post("/v1/messages")
    async def create_message(
        request: Request,
        body: AnthropicMessageRequest,
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None, alias="x-api-key"),
        anthropic_version: str | None = Header(default=None, alias="anthropic-version"),
    ):
        _ = anthropic_version
        auth_header = authorization or (f"Bearer {x_api_key}" if x_api_key else None)
        identity = require_session(request, auth_header)
        payload = body.model_dump(mode="python")
        if bool(payload.get("stream")):
            return StreamingResponse(
                chatgpt_service.stream_message(payload, identity),
                media_type="text/event-stream",
            )
        return await run_in_threadpool(chatgpt_service.create_message, payload, identity)

    # ── CPA multi-pool endpoints ────────────────────────────────────

    @router.get("/api/cpa/pools")
    async def list_cpa_pools(request: Request, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        return {"pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.post("/api/cpa/pools")
    async def create_cpa_pool(
            request: Request,
            body: CPAPoolCreateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        if not body.base_url.strip():
            raise HTTPException(status_code=400, detail={"error": "base_url is required"})
        if not body.secret_key.strip():
            raise HTTPException(status_code=400, detail={"error": "secret_key is required"})
        pool = cpa_config.add_pool(
            name=body.name,
            base_url=body.base_url,
            secret_key=body.secret_key,
            auto_sync_enabled=body.auto_sync_enabled,
        )
        return {"pool": sanitize_cpa_pool(pool), "pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.post("/api/cpa/pools/{pool_id}")
    async def update_cpa_pool(
            request: Request,
            pool_id: str,
            body: CPAPoolUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        pool = cpa_config.update_pool(pool_id, body.model_dump(exclude_none=True))
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"pool": sanitize_cpa_pool(pool), "pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.delete("/api/cpa/pools/{pool_id}")
    async def delete_cpa_pool(
            request: Request,
            pool_id: str,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        if not cpa_config.delete_pool(pool_id):
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.get("/api/cpa/pools/{pool_id}/files")
    async def cpa_pool_files(
            request: Request,
            pool_id: str,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        pool = cpa_config.get_pool(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        files = await run_in_threadpool(list_remote_files, pool)
        return {"pool_id": pool_id, "files": files}

    @router.post("/api/cpa/pools/{pool_id}/import")
    async def cpa_pool_import(
            request: Request,
            pool_id: str,
            body: CPAImportRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        pool = cpa_config.get_pool(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        try:
            job = cpa_import_service.start_import(pool, body.names)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"import_job": job}

    @router.get("/api/cpa/pools/{pool_id}/import")
    async def cpa_pool_import_progress(request: Request, pool_id: str, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        pool = cpa_config.get_pool(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"import_job": pool.get("import_job")}

    # ── Sub2API endpoints ─────────────────────────────────────────────

    @router.get("/api/sub2api/servers")
    async def list_sub2api_servers(request: Request, authorization: str | None = Header(default=None)):
        require_admin_session(request, authorization)
        return {"servers": sanitize_sub2api_servers(sub2api_config.list_servers())}

    @router.post("/api/sub2api/servers")
    async def create_sub2api_server(
            request: Request,
            body: Sub2APIServerCreateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        if not body.base_url.strip():
            raise HTTPException(status_code=400, detail={"error": "base_url is required"})
        has_login = body.email.strip() and body.password.strip()
        has_api_key = bool(body.api_key.strip())
        if not has_login and not has_api_key:
            raise HTTPException(
                status_code=400,
                detail={"error": "email+password or api_key is required"},
            )
        server = sub2api_config.add_server(
            name=body.name,
            base_url=body.base_url,
            email=body.email,
            password=body.password,
            api_key=body.api_key,
            group_id=body.group_id,
            auto_sync_enabled=body.auto_sync_enabled,
        )
        return {
            "server": sanitize_sub2api_server(server),
            "servers": sanitize_sub2api_servers(sub2api_config.list_servers()),
        }

    @router.post("/api/sub2api/servers/{server_id}")
    async def update_sub2api_server(
            request: Request,
            server_id: str,
            body: Sub2APIServerUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        server = sub2api_config.update_server(server_id, body.model_dump(exclude_none=True))
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        return {
            "server": sanitize_sub2api_server(server),
            "servers": sanitize_sub2api_servers(sub2api_config.list_servers()),
        }

    @router.delete("/api/sub2api/servers/{server_id}")
    async def delete_sub2api_server(
            request: Request,
            server_id: str,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        if not sub2api_config.delete_server(server_id):
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        return {"servers": sanitize_sub2api_servers(sub2api_config.list_servers())}

    @router.get("/api/sub2api/servers/{server_id}/groups")
    async def sub2api_server_groups(
            request: Request,
            server_id: str,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        server = sub2api_config.get_server(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        try:
            groups = await run_in_threadpool(sub2api_list_remote_groups, server)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        return {"server_id": server_id, "groups": groups}

    @router.get("/api/sub2api/servers/{server_id}/accounts")
    async def sub2api_server_accounts(
            request: Request,
            server_id: str,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        server = sub2api_config.get_server(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        try:
            accounts = await run_in_threadpool(sub2api_list_remote_accounts, server)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        return {"server_id": server_id, "accounts": accounts}

    @router.post("/api/sub2api/servers/{server_id}/import")
    async def sub2api_server_import(
            request: Request,
            server_id: str,
            body: Sub2APIImportRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        server = sub2api_config.get_server(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        try:
            job = sub2api_import_service.start_import(server, body.account_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"import_job": job}

    @router.get("/api/sub2api/servers/{server_id}/import")
    async def sub2api_server_import_progress(
            request: Request,
            server_id: str,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        server = sub2api_config.get_server(server_id)
        if server is None:
            raise HTTPException(status_code=404, detail={"error": "server not found"})
        return {"import_job": server.get("import_job")}

    # ── Upstream proxy endpoints ─────────────────────────────────────

    @router.post("/api/proxy/test")
    async def test_proxy_endpoint(
            request: Request,
            body: ProxyTestRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(request, authorization)
        candidate = (body.url or "").strip()
        if not candidate:
            candidate = config.get_proxy_settings()
        if not candidate:
            raise HTTPException(status_code=400, detail={"error": "proxy url is required"})
        result = await run_in_threadpool(test_proxy, candidate)
        return {"result": result}

    app.include_router(router)

    # 挂载静态图片目录
    if config.images_dir.exists():
        app.mount("/images", StaticFiles(directory=str(config.images_dir)), name="images")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_web(full_path: str):
        return serve_web_asset(full_path)

    @app.head("/{full_path:path}", include_in_schema=False)
    async def serve_web_head(full_path: str):
        return serve_web_asset(full_path)

    return app
