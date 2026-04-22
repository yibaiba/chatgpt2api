# Auth and Permissions

> Executable contracts for role-based auth, admin-only routes, and normal-user image quota.

---

## Scenario: Role-gated image access and admin-only management

### 1. Scope / Trigger
- Trigger: this feature changed authentication from a single shared key to a role-aware contract.
- Trigger: it added a new persisted data file (`data/auth_users.json`) and new API signatures for session lookup and normal-user management.
- Trigger: it changed cross-layer behavior for web login, navigation, admin page access, and image quota settlement.

### 2. Signatures
- `POST /auth/login`
  - Header: `Authorization: Bearer <auth-key>`
  - Response: `{ ok: boolean, version: string, session: SessionPayload }`
- `GET /auth/session`
  - Header: `Authorization: Bearer <auth-key>`
  - Response: `{ session: SessionPayload }`
- `GET /api/auth-users`
  - Admin only
  - Response: `{ items: AuthUserPayload[] }`
- `POST /api/auth-users`
  - Admin only
  - Body: `{ name: string, auth_key: string, image_quota: number }`
  - Response: `{ item: AuthUserPayload, items: AuthUserPayload[] }`
- `POST /api/auth-users/{user_id}`
  - Admin only
  - Body: `{ name?: string, auth_key?: string, image_quota?: number }`
  - Response: `{ item: AuthUserPayload, items: AuthUserPayload[] }`
- `DELETE /api/auth-users/{user_id}`
  - Admin only
  - Response: `{ items: AuthUserPayload[] }`
- `AuthService`
  - `authenticate(auth_key: str) -> dict | None`
  - `build_session(auth_key: str) -> dict | None`
  - `create_user(name: str, auth_key: str, image_quota: int) -> dict`
  - `update_user(user_id: str, updates: dict[str, object]) -> dict | None`
  - `delete_user(user_id: str) -> bool`
  - `reserve_images(auth_key: str, image_count: int) -> dict | None`
  - `settle_images(auth_key: str, reserved_count: int, actual_count: int) -> dict | None`

### 3. Contracts

#### Environment and persistence
- Admin auth key remains `config.auth_key`.
- `config.auth_key` still resolves from:
  1. `CHATGPT2API_AUTH_KEY`
  2. `config.json["auth-key"]`
- Normal users are persisted in `data/auth_users.json`.
- `data/auth_users.json` must be a JSON array of objects. Each valid item uses:
  - `id: string`
  - `name: string`
  - `auth_key: string`
  - `image_quota: number`
  - `total_generated: number`
  - `last_used_at: string | null`
  - `created_at: string`
  - `updated_at: string`

#### Session payload
- `SessionPayload` fields:
  - `role: "admin" | "user"`
  - `name: string`
  - `image_quota: number | null`
  - `total_generated: number | null`
  - `last_used_at: string | null`
- Admin session contract:
  - `role = "admin"`
  - `image_quota = null`
  - `total_generated = null`
  - `last_used_at = null`
- Normal-user session contract:
  - `role = "user"`
  - `image_quota >= 0`
  - `total_generated >= 0`

#### Route access
- Admin-only routes:
  - `/api/accounts`
  - `/api/accounts/refresh`
  - `/api/accounts/update`
  - `/api/cpa/pools*`
  - `/api/auth-users*`
- Image routes remain available to both admin and normal users:
  - `/v1/images/generations`
  - `/v1/images/edits`
  - `/v1/chat/completions`
  - `/v1/responses`

#### Quota settlement
- Normal-user quota is enforced before upstream image work starts.
- Quota settlement must happen after the actual number of returned images is known.
- For normal users:
  - reserve first
  - settle with `actual_count`
  - refund `reserved_count - actual_count`
- For admins:
  - `reserve_images()` and `settle_images()` are no-ops
- Counting rules:
  - `/v1/images/generations` and `/v1/images/edits`: count non-empty `b64_json` items in `data`
  - `/v1/chat/completions`: count generated markdown image markers in the returned assistant content
  - `/v1/responses`: count `output[].type == "image_generation_call"`

### 4. Validation & Error Matrix

| Condition | Status | Error |
|---|---:|---|
| Missing or invalid bearer token | 401 | `authorization is invalid` |
| Authenticated normal user calls admin-only route | 403 | `admin permission required` |
| `POST /api/auth-users` with empty `auth_key` | 400 | `auth_key is required` |
| Normal-user key duplicates another normal-user key | 400 | `auth_key already exists` |
| Normal-user key matches admin key | 400 | `auth_key conflicts with admin auth-key` |
| `POST /api/auth-users/{user_id}` with no body fields | 400 | `no updates provided` |
| `POST /api/auth-users/{user_id}` for unknown id | 404 | `user not found` |
| Normal user quota is smaller than requested image count | 403 | `普通用户剩余可生成图片数量不足` |
| Edit request contains an empty uploaded file | 400 | `image file is empty` |
| Upstream image generation/edit fails | 502 | Upstream `ImageGenerationError` message |

### 5. Good / Base / Bad Cases
- Good:
  - Admin logs in with `config.auth_key` and receives `session.role = "admin"`.
  - Admin creates `{ auth_key: "designer-a", image_quota: 20 }`, and the new user appears in `/api/auth-users`.
- Base:
  - Normal user with `image_quota = 1` requests one image and receives one successful output.
  - Final state becomes `image_quota = 0`, `total_generated += 1`, `last_used_at` updated.
- Bad:
  - Normal user with `image_quota = 1` requests `n = 2` and gets `403`, with quota unchanged.
  - Normal user calls `/api/accounts` and gets `403 admin permission required`.
  - Create/update normal user with duplicate key and get `400 auth_key already exists`.

### 6. Tests Required
- Unit:
  - `AuthService.create_user()` rejects duplicate keys and admin-key conflicts.
  - `AuthService.reserve_images()` rejects insufficient quota and does not mutate state on failure.
  - `AuthService.settle_images()` refunds unused reservation and increments `total_generated` only by actual image count.
- API integration:
  - `POST /auth/login` returns admin session shape for admin key and user session shape for normal-user key.
  - Normal user receives `403` on `/api/accounts`, `/api/cpa/pools`, and `/api/auth-users`.
  - Admin can create, update, list, and delete normal users via `/api/auth-users*`.
  - Failed image generation path settles quota back to the pre-request value.
  - Partial-success image generation settles only the successful image count.
- Frontend integration:
  - Normal-user login redirects to `/image`.
  - Admin login redirects to `/accounts`.
  - Normal-user session hides admin navigation and direct visits to `/accounts` or `/settings` redirect away.

### 7. Wrong vs Correct

#### Wrong
```python
# Wrong: deduct only once request starts, but never refund on failure.
auth_service.reserve_images(auth_key, requested_count)
result = await run_in_threadpool(chatgpt_service.generate_with_pool, prompt, model, requested_count)
return result
```

#### Correct
```python
auth_service.reserve_images(auth_key, requested_count)
try:
    result = await run_in_threadpool(chatgpt_service.generate_with_pool, prompt, model, requested_count)
except ImageGenerationError:
    auth_service.settle_images(auth_key, requested_count, 0)
    raise

actual_count = count_generated_images(result)
auth_service.settle_images(auth_key, requested_count, actual_count)
return result
```

---

## Conventions

### Convention: Use one auth source for both login and request authorization

**What**: Every request path must derive identity from the same bearer-token lookup used by login.

**Why**: This prevents frontend-only role checks from becoming the only protection and keeps API behavior consistent for direct requests.

**Example**:
```python
def require_session(authorization: str | None) -> dict:
    identity = auth_service.authenticate(extract_bearer_token(authorization))
    if identity is None:
        raise HTTPException(status_code=401, detail={"error": "authorization is invalid"})
    return identity
```

### Convention: Gate admin routes on the backend even if the frontend hides them

**What**: Admin pages may be hidden in navigation, but backend routes still must call `require_admin_session()`.

**Why**: A normal user can still send requests directly or open pages by URL.

**Example**:
```python
@router.get("/api/accounts")
async def get_accounts(authorization: str | None = Header(default=None)):
    require_admin_session(authorization)
    return {"items": account_service.list_accounts()}
```
