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

### Frontend-only image job APIs

The image workspace must use short-lived job APIs for browser-triggered generation/edit requests:

- `POST /api/image-jobs/generations`
  - Authenticated admin or normal user
  - Body: same JSON fields as `POST /v1/images/generations`
  - Response: `{ job: { id, status, createdAt, updatedAt } }`
- `POST /api/image-jobs/edits`
  - Authenticated admin or normal user
  - Multipart fields mirror `POST /v1/images/edits`
  - Response: `{ job: { id, status, createdAt, updatedAt } }`
- `GET /api/image-jobs/{job_id}`
  - Authenticated admin or normal user
  - Response while running: `{ job: { id, status: "queued" | "running", createdAt, updatedAt } }`
  - Response on success: `{ job: { id, status: "success", result, createdAt, updatedAt } }`
  - Response on failure: `{ job: { id, status: "error", error, createdAt, updatedAt } }`

These routes are for the built-in web UI only. Keep `/v1/images/generations` and `/v1/images/edits` synchronous for OpenAI-compatible clients.

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
- Empty "new conversation" drafts in the image workspace are UI-only until the first prompt is submitted:
  - `web/src/app/image/page.tsx` may create a local `ImageConversation` with `turns: []` so the history sidebar can immediately select "新对话"
  - do not call `POST /api/image-conversations` for an empty draft, because server-side history payloads require at least one normalized turn
  - when the first prompt is submitted into the draft, reuse the draft `id`, replace the title with `buildConversationTitle(prompt)`, append the first turn, then persist normally
  - deleting an empty draft should only remove it from local UI state and must not call the server delete endpoint

## Scenario: UI-only image conversation draft

### 1. Scope / Trigger
- Trigger: clicking "新建对话" in the image workspace must create and select a visible conversation shell, not only clear the composer.
- Trigger: server-side image history rejects empty-turn payloads, so blank drafts cannot be persisted through the normal history API.

### 2. Signatures
- Frontend draft shape:
  - `ImageConversation`
  - `title = "新对话"`
  - `turns = []`
  - `ownerRole`, `ownerId`, and `ownerName` are derived from the current viewer session for display only until the first save.
- First submit path:
  - existing draft id is reused
  - first `ImageConversationTurn` is appended
  - `saveConversationToCurrentStore(conversation)` persists after the conversation has at least one turn

### 3. Contracts
- Empty drafts are transient UI state.
- Empty drafts must be removed/replaced when creating another draft so the sidebar does not accumulate unsaved shells.
- Empty drafts must not be listed after page reload unless a future storage/API contract explicitly supports draft persistence.
- Once the first turn exists, the conversation follows the normal `browser` or `server` persistence mode.

### 4. Validation & Error Matrix

| Condition | Behavior |
|---|---|
| User clicks "新建对话" | Add local draft, select it, reset and focus the composer |
| User submits first prompt in a draft | Rename from prompt, append first turn, persist through current history mode |
| User deletes an empty draft | Remove local draft only; do not call `DELETE /api/image-conversations/{id}` |
| User reloads before submitting a draft | Draft disappears because it was not persisted |
| Code tries to save `turns: []` to server history | Invalid pattern; server history requires a normalized turn |

### 5. Good/Base/Bad Cases
- Good: "新建对话" immediately shows "新对话" in the sidebar and the empty state explains that sending will save it.
- Base: first prompt sent in the draft becomes the first saved turn, and the sidebar title changes to the prompt-derived title.
- Bad: creating a blank draft calls `POST /api/image-conversations` or deleting it calls the server delete endpoint.

### 6. Tests Required
- Frontend behavior:
  - assert `onCreateDraft` produces one selected local draft with `turns.length === 0`
  - assert creating a second draft replaces the previous empty draft
  - assert deleting an empty draft does not call server/browser persistence delete helpers
- Integration/manual:
  - in server history mode, click "新建对话", verify no image-history POST occurs until submitting a prompt
  - after submitting, verify the saved conversation has one turn and a prompt-derived title

### 7. Wrong vs Correct

#### Wrong
```typescript
const draft = { id: createId(), title: "新对话", turns: [] };
await saveConversationToCurrentStore(draft);
```

#### Correct
```typescript
const draft = { id: createId(), title: "新对话", turns: [] };
setConversations([draft, ...savedConversations]);

const savedConversation = {
  ...draft,
  title: buildConversationTitle(prompt),
  turns: [firstTurn],
};
await saveConversationToCurrentStore(savedConversation);
```

## Scenario: Browser image jobs avoid reverse-proxy 504

### 1. Scope / Trigger
- Trigger: image generation can take longer than common reverse-proxy read timeouts.
- Trigger: backend can finish with `200 OK` while the browser receives `504 Gateway Timeout` from an intermediate proxy.
- Trigger: the web image workspace needs a short-request flow that does not duplicate generation or lose the final image response.

### 2. Signatures
- `POST /api/image-jobs/generations`
  - Request: `ImageGenerationRequest`
  - Response: `{ job: ImageJob }`
- `POST /api/image-jobs/edits`
  - Request: multipart image edit fields
  - Response: `{ job: ImageJob }`
- `GET /api/image-jobs/{job_id}`
  - Response: `{ job: ImageJob }`
- `ImageJob`
  - `id: string`
  - `status: "queued" | "running" | "success" | "error"`
  - `createdAt: number`
  - `updatedAt: number`
  - `result?: { created: number, data: [...] }`
  - `error?: string`

### 3. Contracts
- Job creation must authenticate and reserve quota synchronously before returning a job id.
- The actual upstream image call runs in a background thread.
- Supported web/UI image models are `gpt-image-2`, `codex-gpt-image-2`, and `gpt-image-think`; edit mode must not offer `gpt-image-think`.
- Persisted conversation/job `model` values should keep the user-selected model, including `codex-gpt-image-2`; do not silently rewrite Codex requests back to `gpt-image-2`.
- The web workspace should derive one `size` request per turn from the chosen aspect ratio and output-size preset:
  - `original` keeps the lightweight aspect-ratio hint contract
  - `2K` / `4K` only resolve to exact `WIDTHxHEIGHT` requests when the selected model is `codex-gpt-image-2`
  - non-Codex models keep the existing browser-side upscale behavior after job completion
- The background worker must settle quota exactly once:
  - success: settle with `count_generated_images(result)`
  - failure: settle with `0`
- Jobs are in-memory and short-lived; they are not persisted across process restarts.
- Polling must require the same authenticated identity that created the job.
- The frontend `generateImage()` and `editImage()` helpers should call `/api/image-jobs/*` and poll `GET /api/image-jobs/{id}`.
- OpenAI-compatible `/v1/images/*` endpoints remain synchronous and should not be repurposed for the web UI polling contract.
- `codex-gpt-image-2` is a paid-only alias for upstream Codex image capacity and should stay distinct from the regular web `gpt-image-2` quota semantics.

### 4. Validation & Error Matrix

| Condition | Status / Behavior |
|---|---|
| Missing or invalid auth on job create/poll | 401 `authorization is invalid` |
| Normal user lacks image quota | 403 quota error before job creation |
| Polling an unknown or other-user job id | 404 `image job not found` |
| Upstream image generation fails | Job status becomes `error`, quota settles to `0` |
| Upstream image generation succeeds | Job status becomes `success`, result contains normal image payload |
| Process restarts before completion | Job may disappear; frontend should surface polling error |

### 5. Good/Base/Bad Cases
- Good: UI POST returns a job id quickly, then polls until success without holding one long HTTP request open.
- Base: one generated image returns through `job.result.data[0].b64_json`, and the existing frontend conversation update path handles it.
- Bad: browser UI calls `/v1/images/generations` directly and waits behind a reverse proxy for the full generation duration.

### 6. Tests Required
- API integration:
  - job creation returns a job id without waiting for the long synchronous endpoint contract
  - polling reaches `success` and includes the image result
  - upstream `ImageGenerationError` changes job status to `error`
  - quota reservation/settlement is called with success and failure counts
- Frontend build:
  - `web/src/lib/api.ts` compiles with `generateImage()` and `editImage()` returning the original image result shape after polling.

### 7. Wrong vs Correct

#### Wrong
```typescript
const result = await httpRequest("/v1/images/generations", {
  method: "POST",
  body: { prompt, model, n: 1, response_format: "b64_json" },
});
```

#### Correct
```typescript
const { job } = await httpRequest("/api/image-jobs/generations", {
  method: "POST",
  body: { prompt, model, n: 1, response_format: "b64_json" },
});
const result = await waitForImageJob(job);
```
