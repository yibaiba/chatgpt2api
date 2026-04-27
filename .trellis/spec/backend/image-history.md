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
