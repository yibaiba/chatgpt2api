# Text Threading

## Scenario: Server-managed threaded text conversations

### 1. Scope / Trigger
- Trigger: text APIs now support a GPT-web-style "keep chatting in the same upstream conversation" flow.
- Trigger: this is a cross-layer contract spanning request payloads, backend persistence, upstream conversation state, and moderation behavior.
- Trigger: the implementation adds a new persisted file, new request fields, and new response/error behavior.

### 2. Signatures
- Request fields on text endpoints:
  - `POST /v1/chat/completions`
  - `POST /v1/responses`
  - `POST /v1/messages`
- New optional request fields:
  - `threaded: boolean`
  - `thread_id: string`
- New optional response field on successful threaded requests:
  - `thread_id: string`
- Persistence service:
  - `TextThreadService.create_thread(identity, *, conversation_id, parent_message_id, model, last_error=None) -> dict`
  - `TextThreadService.get_thread(identity, thread_id) -> dict | None`
  - `TextThreadService.update_thread(identity, thread_id, *, conversation_id, parent_message_id, model, last_error=None) -> dict | None`
- Backend transport:
  - `TextBackend.complete(prompt, model="auto", *, conversation_id="", parent_message_id="", allow_conversation_fallback=True) -> dict`
  - `TextBackend.stream(prompt, model="auto", *, conversation_id="", parent_message_id="", allow_conversation_fallback=True) -> Iterator[dict]`
  - Current ChatGPT web text transport:
    - obtain `chat_token + proofofwork` from the existing single-step `sentinel/chat-requirements` flow
    - call `/backend-api/f/conversation/prepare` to get `conduit_token`
    - send text via `/backend-api/f/conversation` with `openai-sentinel-chat-requirements-token`, optional `openai-sentinel-proof-token`, and `x-conduit-token`
    - do **not** require `sentinel/chat-requirements prepare/finalize` or turnstile solving for the current server-side text path

### 3. Contracts

#### Request contract
- Text requests remain stateless by default.
- `threaded=true` with no `thread_id` means:
  - send the current request as a new threaded conversation
  - if the upstream call succeeds, return a new server-managed `thread_id`
- `thread_id=<id>` means:
  - reuse an existing server-managed thread owned by the authenticated caller
  - continue from the stored upstream `conversation_id + parent_message_id`
- `thread_id` implies threaded mode even if `threaded` is absent or false.

#### Persistence contract
- Thread state is stored in `data/text_threads.json`.
- The file contains a JSON array.
- Each valid item must include:
  - `id: string`
  - `conversation_id: string`
  - `parent_message_id: string`
  - `owner_role: "admin" | "user"`
  - `owner_id: string`
  - `owner_name: string`
  - `created_at: string`
  - `updated_at: string`
  - `last_model: string | null`
  - `last_error: string | null`
- Writes must use atomic JSON persistence (`services.storage.json_utils.write_json_atomic`) and reload the latest on-disk array before mutating it.
- The thread store must take a cross-process lock before read-modify-write so one worker does not silently overwrite another worker's thread head update.
- Thread ownership is derived from the authenticated identity, never from client payload fields.
- Admin and normal users can access only their own thread records in this MVP.

#### Moderation contract
- Input moderation still happens before any upstream text call using the existing sensitive-word config.
- Threaded text requests add output moderation after the upstream text is normalized.
- Output moderation applies only on threaded requests in this MVP.
- If output moderation blocks a reused thread response:
  - the thread store must still advance to the new upstream `parent_message_id`
  - `last_error` must record the moderation error
  - the API returns `400 response contains blocked word: <word>`

#### Streaming contract
- Stateless text streaming remains supported.
- `POST /v1/chat/completions` now supports threaded streaming in addition to stateless streaming.
- Threaded stream responses may include:
  - `thread_id` on the first emitted chunk or, if no text chunk was emitted yet, on the finish chunk
  - `moderation_error` on the final chunk when output moderation stops the stream
- Threaded streaming must never silently fall back to stateless behavior.
- Output moderation on threaded streams must:
  - hold back a short suffix while streaming so blocked words are not fully leaked to the client
  - stop the stream with `finish_reason="content_filter"` once a blocked word is confirmed
  - keep the stored upstream `parent_message_id` in sync for already-created threads
- `/v1/messages` threaded streaming is still out of scope for this slice; Anthropic streaming remains stateless-only.

### 4. Validation & Error Matrix

| Condition | Status | Error |
|---|---:|---|
| Missing/invalid auth on text route | 401 | `authorization is invalid` |
| `thread_id` does not exist or is not owned by caller | 404 | `thread not found` |
| Upstream refuses a reused conversation | 409 | `thread conversation expired` |
| Threaded request gets no upstream `conversation_id` or `parent_message_id` | 502 | `thread state missing from upstream` |
| Input contains a blocked word | 400 | `prompt contains blocked word: <word>` |
| Threaded output contains a blocked word | 400 | `response contains blocked word: <word>` |
| Threaded chat stream output contains a blocked word | 200 stream | final chunk uses `finish_reason="content_filter"` and `moderation_error` |
| Threaded `/v1/messages` request uses `stream=true` | 400 | `threaded conversations are not supported for stream requests` |

### 5. Good/Base/Bad Cases
- Good:
  - `POST /v1/chat/completions` with `threaded=true` returns a normal chat completion payload plus `thread_id`, and the server persists upstream state.
  - `POST /v1/chat/completions` with `threaded=true` and `stream=true` returns SSE chunks, includes `thread_id`, and keeps the upstream thread state reusable.
- Base:
  - a later request with the returned `thread_id` reuses the stored `conversation_id + parent_message_id` and returns the same `thread_id`.
- Bad:
  - a caller sends an unknown `thread_id` and the server silently creates a new thread.
  - a reused thread hits blocked output and the server returns `400` without advancing stored upstream state.
  - a threaded chat stream leaks the entire blocked word before finishing with `content_filter`.
  - a threaded request with `stream=true` silently falls back to stateless stream behavior.

### 6. Tests Required
- API integration:
  - threaded chat completion creates a thread, returns `thread_id`, and persists upstream ids
  - reusing `thread_id` sends stored `conversation_id + parent_message_id` back into `TextBackend.complete()`
  - unknown `thread_id` returns `404 thread not found`
  - threaded output moderation returns `400 response contains blocked word: <word>` and still updates persisted `parent_message_id`
  - threaded chat completion stream returns `thread_id`, reuses stored thread state, and updates `parent_message_id` on completion
  - threaded chat completion stream stops with `finish_reason="content_filter"` without leaking the full blocked word
  - threaded `/v1/messages` stream requests still return the explicit unsupported error
  - at least one non-OpenAI text surface (currently `/v1/messages`) also returns `thread_id` on threaded success
- Unit:
  - `TextThreadService` enforces owner scoping and atomic save/load behavior
  - `TextBackend` SSE parsing extracts `parent_message_id` from assistant messages

### 7. Wrong vs Correct

#### Wrong
```python
thread = text_thread_service.get_thread(identity, thread_id)
backend_result = TextBackend(token).complete(prompt, model)
return payload_without_thread_id
```

#### Correct
```python
thread = text_thread_service.get_thread(identity, thread_id)
backend_result = TextBackend(token).complete(
    prompt,
    model,
    conversation_id=thread["conversation_id"],
    parent_message_id=thread["parent_message_id"],
    allow_conversation_fallback=False,
)
conversation_id, parent_message_id = self._thread_state_from_result(backend_result)
saved_thread = text_thread_service.update_thread(
    identity,
    thread["id"],
    conversation_id=conversation_id,
    parent_message_id=parent_message_id,
    model=model,
)
payload["thread_id"] = saved_thread["id"]
```
