# Image History

## Scope

This project supports two image-history persistence modes:

- `browser`: only read/write history in the current browser
- `server`: persist history on the backend and scope visibility by authenticated identity

The feature covers:

- the image workspace history list in `web/src/app/image/page.tsx`
- the persistence service in `services/image_history_service.py`
- the API surface in `services/api.py`
- the global settings value in `config.json`
- the authenticated session payload that exposes the effective mode to the image workspace

## Persistence Contract

- `browser` mode stores history only in browser-local storage (via IndexedDB/localforage) and must not call image-history APIs
- `server` mode stores history in `data/image_history.json`
- The file contains a JSON array
- Every item must include:
  - `id: string`
  - `title: string`
  - `prompt: string`
  - `model: string`
  - `mode: "generate" | "edit"`
  - `referenceImages: Array<{ name: string, type: string, dataUrl: string }>`
  - `count: number`
  - `images: Array<{ id: string, status: "loading" | "success" | "error", b64_json?: string | null, error?: string | null, generation_route?: "regular" | "thinking" | "fallback" | null }>`
  - `createdAt: string`
  - `updatedAt: string`
  - `status: "generating" | "success" | "error"`
  - `error: string | null`
  - `ownerRole: "admin" | "user"`
  - `ownerId: string`
  - `ownerName: string`

Rules:

- invalid or incomplete items are dropped while loading
- unknown conversation/image status values are normalized to the nearest allowed value
- new records always derive ownership from the authenticated session, never from the frontend payload
- the effective mode defaults to `browser` unless config explicitly sets `image_history_persistence_mode = "server"`

## Visibility Contract

- Admin sessions can list, delete, and clear all saved conversations
- Normal-user sessions can list, delete, and clear only their own conversations
- Normal users must never be able to overwrite or delete another user's conversation even if they guess the id
- Admin UI should show owner information when viewing the shared history list
- Browser-local mode should partition history by authenticated session identity so different users on the same device do not reuse one list

## API Contract

### `GET /api/image-conversations`

- Authenticated admin or normal user
- Response:

```json
{
  "items": [
    {
      "id": "conv_123",
      "title": "海边日落",
      "prompt": "a sunset over the sea",
      "model": "gpt-image-2",
      "mode": "generate",
      "referenceImages": [],
      "count": 1,
      "images": [
        {
          "id": "conv_123-0",
          "status": "success",
          "b64_json": "..."
        }
      ],
      "createdAt": "2026-04-22T08:00:00+00:00",
      "updatedAt": "2026-04-22T08:00:05+00:00",
      "status": "success",
      "error": null,
      "ownerRole": "user",
      "ownerId": "user_abc",
      "ownerName": "Designer A"
    }
  ]
}
```

### `POST /api/image-conversations`

- Authenticated admin or normal user
- Request body matches one history item except ownership fields
- Ownership fields in the request body must be ignored
- If `id` already exists:
  - owner may update it
  - non-owner normal users get `403 conversation not found`
- Response:

```json
{
  "item": {
    "...": "saved conversation payload including owner metadata"
  }
}
```

### `DELETE /api/image-conversations/{conversation_id}`

- Authenticated admin or normal user
- Deletes one visible/managable conversation
- `404 conversation not found` when the record does not exist or is not owned by the caller

### `DELETE /api/image-conversations`

- Authenticated admin or normal user
- Admin clears all conversations
- Normal users clear only their own conversations
- Response:

```json
{
  "removed": 3
}
```

## Frontend Rules

- `web/src/store/image-conversations.ts` owns shared history normalization and storage adapters:
  - server mode uses the image-history API
  - browser mode uses IndexedDB/localforage, not raw `localStorage`
- Do not auto-convert all `generating` conversations to `error` when loading history, because admins can view other users' active jobs
- Admin-only owner labels should appear in both the history sidebar and the selected conversation details
