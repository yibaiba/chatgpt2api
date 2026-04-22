from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event, Thread

from fastapi import APIRouter, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from services.account_service import account_service
from services.auth_service import auth_service
from services.chatgpt_service import ChatGPTService
from services.config import config
from services.cpa_service import cpa_config, cpa_import_service, list_remote_files
from services.image_service import ImageGenerationError
from services.system_settings import system_settings_service
from services.utils import parse_image_count
from services.version import get_app_version

BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIST_DIR = BASE_DIR / "web_dist"


class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str = "gpt-4o"
    n: int = Field(default=1, ge=1, le=4)
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


class ResponseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    input: object | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: object | None = None
    stream: bool | None = None


class CPAPoolCreateRequest(BaseModel):
    name: str = ""
    base_url: str = ""
    secret_key: str = ""


class CPAPoolUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    secret_key: str | None = None


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


class ProxySettingsUpdateRequest(BaseModel):
    proxy_url: str = ""


class ProxyPoolEntryCreateRequest(BaseModel):
    name: str = ""
    proxy_url: str = ""


class ProxyPoolEntryUpdateRequest(BaseModel):
    name: str | None = None
    proxy_url: str | None = None


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


def extract_bearer_token(authorization: str | None) -> str:
    scheme, _, value = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return ""
    return value.strip()


def require_auth_key(authorization: str | None) -> None:
    if auth_service.authenticate(extract_bearer_token(authorization)) is None:
        raise HTTPException(status_code=401, detail={"error": "authorization is invalid"})


def require_session(authorization: str | None) -> dict:
    identity = auth_service.authenticate(extract_bearer_token(authorization))
    if identity is None:
        raise HTTPException(status_code=401, detail={"error": "authorization is invalid"})
    return identity


def require_admin_session(authorization: str | None) -> dict:
    identity = require_session(authorization)
    if identity.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"error": "admin permission required"})
    return identity


def count_generated_images(payload: dict[str, object]) -> int:
    data = payload.get("data")
    if not isinstance(data, list):
        return 0
    return sum(1 for item in data if isinstance(item, dict) and str(item.get("b64_json") or "").strip())


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
        content = str(message.get("content") or "")
        count += content.count("![image_")
    return count


def count_response_images(payload: dict[str, object]) -> int:
    output = payload.get("output")
    if not isinstance(output, list):
        return 0
    return sum(1 for item in output if isinstance(item, dict) and str(item.get("type") or "").strip() == "image_generation_call")


def start_limited_account_watcher(stop_event: Event) -> Thread:
    interval_seconds = config.refresh_account_interval_minute * 60

    def worker() -> None:
        while not stop_event.is_set():
            try:
                limited_tokens = account_service.list_limited_tokens()
                if limited_tokens:
                    print(f"[account-limited-watcher] checking {len(limited_tokens)} limited accounts")
                    account_service.refresh_accounts(limited_tokens)
            except Exception as exc:
                print(f"[account-limited-watcher] fail {exc}")
            stop_event.wait(interval_seconds)

    thread = Thread(target=worker, name="limited-account-watcher", daemon=True)
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


def create_app() -> FastAPI:
    chatgpt_service = ChatGPTService(account_service)
    app_version = get_app_version()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stop_event = Event()
        thread = start_limited_account_watcher(stop_event)
        try:
            yield
        finally:
            stop_event.set()
            thread.join(timeout=1)

    app = FastAPI(title="chatgpt2api", version=app_version, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    router = APIRouter()

    @router.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [
                build_model_item("gpt-image-1"),
                build_model_item("gpt-image-2"),
            ],
        }

    @router.post("/auth/login")
    async def login(authorization: str | None = Header(default=None)):
        identity = require_session(authorization)
        return {
            "ok": True,
            "version": app_version,
            "session": auth_service.build_session(str(identity.get("auth_key") or "")),
        }

    @router.get("/auth/session")
    async def get_auth_session(authorization: str | None = Header(default=None)):
        identity = require_session(authorization)
        return {"session": auth_service.build_session(str(identity.get("auth_key") or ""))}

    @router.get("/version")
    async def get_version():
        return {"version": app_version}

    @router.get("/api/accounts")
    async def get_accounts(authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
        return {"items": account_service.list_accounts()}

    @router.post("/api/accounts")
    async def create_accounts(body: AccountCreateRequest, authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
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
    async def delete_accounts(body: AccountDeleteRequest, authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
        tokens = [str(token or "").strip() for token in body.tokens if str(token or "").strip()]
        if not tokens:
            raise HTTPException(status_code=400, detail={"error": "tokens is required"})
        return account_service.delete_accounts(tokens)

    @router.post("/api/accounts/refresh")
    async def refresh_accounts(body: AccountRefreshRequest, authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
        access_tokens = [str(token or "").strip() for token in body.access_tokens if str(token or "").strip()]
        if not access_tokens:
            access_tokens = account_service.list_tokens()
        if not access_tokens:
            raise HTTPException(status_code=400, detail={"error": "access_tokens is required"})
        return account_service.refresh_accounts(access_tokens)

    @router.post("/api/accounts/update")
    async def update_account(body: AccountUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
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
    async def list_auth_users(authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
        return {"items": auth_service.list_users()}

    @router.post("/api/auth-users")
    async def create_auth_user(body: AuthUserCreateRequest, authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
        try:
            item = auth_service.create_user(body.name, body.auth_key, body.image_quota)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item, "items": auth_service.list_users()}

    @router.post("/api/auth-users/{user_id}")
    async def update_auth_user(
            user_id: str,
            body: AuthUserUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(authorization)
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
    async def delete_auth_user(user_id: str, authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
        if not auth_service.delete_user(user_id):
            raise HTTPException(status_code=404, detail={"error": "user not found"})
        return {"items": auth_service.list_users()}

    @router.get("/api/settings/proxy")
    async def get_proxy_settings(authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
        return {"item": system_settings_service.get_proxy_settings()}

    @router.post("/api/settings/proxy")
    async def update_proxy_settings(body: ProxySettingsUpdateRequest, authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
        try:
            item = system_settings_service.update_proxy_url(body.proxy_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"item": item}

    @router.get("/api/settings/proxies")
    async def get_proxy_pool_settings(authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
        return system_settings_service.get_proxy_pool_settings()

    @router.post("/api/settings/proxies")
    async def create_proxy_entry(body: ProxyPoolEntryCreateRequest, authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
        try:
            system_settings_service.create_proxy_entry(body.name, body.proxy_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return system_settings_service.get_proxy_pool_settings()

    @router.post("/api/settings/proxies/{proxy_id}")
    async def update_proxy_entry(
            proxy_id: str,
            body: ProxyPoolEntryUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(authorization)
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
    async def delete_proxy_entry(proxy_id: str, authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
        if not system_settings_service.delete_proxy_entry(proxy_id):
            raise HTTPException(status_code=404, detail={"error": "proxy not found"})
        return system_settings_service.get_proxy_pool_settings()

    @router.post("/v1/images/generations")
    async def generate_images(body: ImageGenerationRequest, authorization: str | None = Header(default=None)):
        identity = require_session(authorization)
        reserved_count = int(body.n or 1)
        auth_key = str(identity.get("auth_key") or "")
        try:
            auth_service.reserve_images(auth_key, reserved_count)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc
        try:
            result = await run_in_threadpool(chatgpt_service.generate_with_pool, body.prompt, body.model, body.n)
        except ImageGenerationError as exc:
            auth_service.settle_images(auth_key, reserved_count, 0)
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        except Exception:
            auth_service.settle_images(auth_key, reserved_count, 0)
            raise
        auth_service.settle_images(auth_key, reserved_count, count_generated_images(result))
        return result

    @router.post("/v1/images/edits")
    async def edit_images(
            authorization: str | None = Header(default=None),
            image: list[UploadFile] = File(...),
            prompt: str = Form(...),
            model: str = Form(default="gpt-image-1"),
            n: int = Form(default=1),
    ):
        identity = require_session(authorization)
        if n < 1 or n > 4:
            raise HTTPException(status_code=400, detail={"error": "n must be between 1 and 4"})
        auth_key = str(identity.get("auth_key") or "")

        images: list[tuple[bytes, str, str]] = []
        for upload in image:
            image_data = await upload.read()
            if not image_data:
                raise HTTPException(status_code=400, detail={"error": "image file is empty"})

            file_name = upload.filename or "image.png"
            mime_type = upload.content_type or "image/png"
            images.append((image_data, file_name, mime_type))

        try:
            auth_service.reserve_images(auth_key, n)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc
        try:
            result = await run_in_threadpool(
                chatgpt_service.edit_with_pool, prompt, images, model, n
            )
        except ImageGenerationError as exc:
            auth_service.settle_images(auth_key, n, 0)
            raise HTTPException(status_code=502, detail={"error": str(exc)}) from exc
        except Exception:
            auth_service.settle_images(auth_key, n, 0)
            raise
        auth_service.settle_images(auth_key, n, count_generated_images(result))
        return result

    @router.post("/v1/chat/completions")
    async def create_chat_completion(body: ChatCompletionRequest, authorization: str | None = Header(default=None)):
        identity = require_session(authorization)
        payload = body.model_dump(mode="python")
        reserved_count = parse_image_count(payload.get("n"))
        auth_key = str(identity.get("auth_key") or "")
        try:
            auth_service.reserve_images(auth_key, reserved_count)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc
        try:
            result = await run_in_threadpool(chatgpt_service.create_image_completion, payload)
        except HTTPException:
            auth_service.settle_images(auth_key, reserved_count, 0)
            raise
        except Exception:
            auth_service.settle_images(auth_key, reserved_count, 0)
            raise
        auth_service.settle_images(auth_key, reserved_count, count_chat_completion_images(result))
        return result

    @router.post("/v1/responses")
    async def create_response(body: ResponseCreateRequest, authorization: str | None = Header(default=None)):
        identity = require_session(authorization)
        payload = body.model_dump(mode="python")
        auth_key = str(identity.get("auth_key") or "")
        try:
            auth_service.reserve_images(auth_key, 1)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail={"error": str(exc)}) from exc
        try:
            result = await run_in_threadpool(chatgpt_service.create_response, payload)
        except HTTPException:
            auth_service.settle_images(auth_key, 1, 0)
            raise
        except Exception:
            auth_service.settle_images(auth_key, 1, 0)
            raise
        auth_service.settle_images(auth_key, 1, count_response_images(result))
        return result

    # ── CPA multi-pool endpoints ────────────────────────────────────

    @router.get("/api/cpa/pools")
    async def list_cpa_pools(authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
        return {"pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.post("/api/cpa/pools")
    async def create_cpa_pool(
            body: CPAPoolCreateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(authorization)
        if not body.base_url.strip():
            raise HTTPException(status_code=400, detail={"error": "base_url is required"})
        if not body.secret_key.strip():
            raise HTTPException(status_code=400, detail={"error": "secret_key is required"})
        pool = cpa_config.add_pool(
            name=body.name,
            base_url=body.base_url,
            secret_key=body.secret_key,
        )
        return {"pool": sanitize_cpa_pool(pool), "pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.post("/api/cpa/pools/{pool_id}")
    async def update_cpa_pool(
            pool_id: str,
            body: CPAPoolUpdateRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(authorization)
        pool = cpa_config.update_pool(pool_id, body.model_dump(exclude_none=True))
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"pool": sanitize_cpa_pool(pool), "pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.delete("/api/cpa/pools/{pool_id}")
    async def delete_cpa_pool(
            pool_id: str,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(authorization)
        if not cpa_config.delete_pool(pool_id):
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"pools": sanitize_cpa_pools(cpa_config.list_pools())}

    @router.get("/api/cpa/pools/{pool_id}/files")
    async def cpa_pool_files(
            pool_id: str,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(authorization)
        pool = cpa_config.get_pool(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        files = await run_in_threadpool(list_remote_files, pool)
        return {"pool_id": pool_id, "files": files}

    @router.post("/api/cpa/pools/{pool_id}/import")
    async def cpa_pool_import(
            pool_id: str,
            body: CPAImportRequest,
            authorization: str | None = Header(default=None),
    ):
        require_admin_session(authorization)
        pool = cpa_config.get_pool(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        try:
            job = cpa_import_service.start_import(pool, body.names)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {"import_job": job}

    @router.get("/api/cpa/pools/{pool_id}/import")
    async def cpa_pool_import_progress(pool_id: str, authorization: str | None = Header(default=None)):
        require_admin_session(authorization)
        pool = cpa_config.get_pool(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail={"error": "pool not found"})
        return {"import_job": pool.get("import_job")}

    app.include_router(router)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_web(full_path: str):
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

    return app
