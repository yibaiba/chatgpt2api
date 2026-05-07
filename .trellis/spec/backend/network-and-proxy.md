# Network and Proxy

## Scope

This project supports a **SOCKS5 proxy pool** for selected outbound backend traffic.

Current covered call sites:

- `services/image_service.py` image generation and image edit traffic
- `services/account_service.py` account refresh traffic to `chatgpt.com`
- `services/register/openai_register.py` registration traffic when the register-specific `proxy` field is empty

Current excluded call sites:

- `services/cpa_service.py` CPA remote file listing and token download traffic

## Config Contract

`config.json` may contain:

```json
{
  "proxy_pool": [
    {
      "id": "abc123def456",
      "name": "WARP-1",
      "proxy_url": "socks5h://user:pass@127.0.0.1:1080",
      "scheme": "socks5h",
      "last_checked_at": "2026-04-22T07:00:00+00:00",
      "last_check_ok": true,
      "last_check_status": 403,
      "last_check_error": null,
      "created_at": "2026-04-22T07:00:00+00:00",
      "updated_at": "2026-04-22T07:00:00+00:00"
    }
  ]
}
```

Rules:

- Empty or missing `proxy_pool` means proxying is disabled
- Accepted schemes: `socks5`, `socks5h`
- `proxy_url` values must be unique within the pool
- Legacy `config.json["proxy_url"]` may be read as a one-item migration source, but new writes persist only `proxy_pool`

## Runtime Selection Contract

- Strategy is fixed to `round_robin`
- Every new outbound `Session` for covered call sites selects the next proxy entry using IPv6-first round robin:
  - If the pool contains one or more literal IPv6 proxy hosts, only those entries participate in selection
  - If the pool has no IPv6 entries, selection falls back to the full pool
- Selection is global across the covered call sites; it is not per-endpoint, per-user, or per-account
- Existing open sessions keep the proxy they started with; only new sessions participate in round-robin rotation
- Register traffic resolves one proxy entry per registration attempt and reuses that same proxy for the follow-up token exchange session

## Validation Contract

- Proxy validation runs on every create/update save
- Validation performs a live request through the candidate proxy to `https://chatgpt.com/`
- A response is considered a successful connectivity check even if the returned status is `403` because Cloudflare challenge responses still prove the proxy can reach the target
- Validation failures must reject the save with `400`
- Stored validation metadata:
  - `last_checked_at: string | null`
  - `last_check_ok: boolean | null`
  - `last_check_status: number | null`
  - `last_check_error: string | null`
- Validation errors must not expose plaintext proxy passwords

## Admin API Contract

### `GET /api/settings/proxies`

- Admin only
- Returns:

```json
{
  "items": [
    {
      "id": "abc123def456",
      "name": "WARP-1",
      "proxy_url": "socks5h://user:pass@127.0.0.1:1080",
      "scheme": "socks5h",
      "last_checked_at": "2026-04-22T07:00:00+00:00",
      "last_check_ok": true,
      "last_check_status": 403,
      "last_check_error": null,
      "created_at": "2026-04-22T07:00:00+00:00",
      "updated_at": "2026-04-22T07:00:00+00:00"
    }
  ],
  "enabled": true,
  "selection_strategy": "round_robin",
  "validate_on_save": true
}
```

### `POST /api/settings/proxies`

- Admin only
- Request body:

```json
{
  "name": "WARP-2",
  "proxy_url": "socks5://user:pass@127.0.0.1:1081"
}
```

- Response shape matches `GET /api/settings/proxies`

### `POST /api/settings/proxies/{proxy_id}`

- Admin only
- Request body:

```json
{
  "name": "WARP-2 backup",
  "proxy_url": "socks5h://user:pass@127.0.0.1:1081"
}
```

- `400 no updates provided` when request body is empty
- `404 proxy not found` when `proxy_id` does not exist
- Response shape matches `GET /api/settings/proxies`

### `DELETE /api/settings/proxies/{proxy_id}`

- Admin only
- `404 proxy not found` when `proxy_id` does not exist
- Response shape matches `GET /api/settings/proxies`

## Implementation Rules

- Reuse `services/system_settings.py` as the runtime source of truth for proxy pool state
- Preserve unrelated `config.json` keys when saving
- Do not duplicate proxy rotation logic in `image_service.py` or `account_service.py`; they should only ask the settings service to apply the next proxy
- Do not route CPA traffic through the proxy pool unless the scope is explicitly expanded
- Frontend must mask proxy passwords when rendering pool entries or surfacing validation failures
