# Research: track-a-text-prerequisites

- **Query**: Identify the minimum prerequisite work needed in the current fork to unblock the text roadmap before absorbing upstream commits `8f1c666`, `740b306`, `69e3446`, and `aaab38f`.
- **Scope**: mixed
- **Date**: 2026-04-28

## Findings

### Files Found

| File Path | Description |
|---|---|
| `services/api.py` | Current `/v1/chat/completions`, `/v1/responses`, and `/v1/models` routes; all are wired for image use cases only. |
| `services/chatgpt_service.py` | Current service layer only implements image generation/edit flows plus image-shaped chat/responses adapters. |
| `services/utils.py` | Current helper layer contains prompt extraction/history stripping helpers, but only for image-facing request normalization. |
| `services/image_service.py` | Only place with reusable upstream ChatGPT web transport primitives today: session/bootstrap, chat-requirements, conversation senders, and SSE parsing. |
| `services/account_service.py` | Account refresh/account-type detection logic; current fork already contains the account-type recursion fix equivalent to upstream `8f1c666`. |
| `services/log_service.py` | Current log reader is unrelated to upstream text-stream/log-wrapper code in `aaab38f`. |
| `.trellis/tasks/04-28-upstream-roadmap/prd.md` | Existing roadmap already notes Track A is blocked on missing text infrastructure. |
| `upstream 8f1c666: services/chatgpt_service.py` | Assumes an existing text backend with `list_models`, `chat_completions`, and text-streaming methods. |
| `upstream 8f1c666: services/openai_backend_api.py` | Assumes a reusable text conversation backend and fixes assistant-history stripping inside that layer. |
| `upstream 740b306: api/ai.py` | Adds `/v1/messages` as a thin route over existing text backend APIs. |
| `upstream 69e3446: services/anthropic_protocol.py` | Adds Anthropic/Claude tool-message preprocessing and event shaping on top of an already-working text backend. |
| `upstream aaab38f: services/protocol/conversation.py` | Fixes text streaming regressions inside an existing conversation/protocol abstraction that does not exist in this fork. |

### Current fork text request flow today

**Bottom line:** the fork does **not** have a general text request path yet; the “text-shaped” endpoints are image shims.

- `POST /v1/chat/completions` in `services/api.py:1212-1230`:
  - always reserves image quota via `reserve_images_for_identity`
  - always dispatches to `chatgpt_service.create_image_completion`
  - settles quota by counting markdown image markers in the result (`services/api.py:398-410`)
- `POST /v1/responses` in `services/api.py:1232-1249`:
  - always reserves 1 image quota
  - always dispatches to `chatgpt_service.create_response`
  - settles quota by counting `image_generation_call` items (`services/api.py:413-421`)
- `GET /v1/models` in `services/api.py:745-750` returns only `SUPPORTED_IMAGE_MODELS`.

Inside `services/chatgpt_service.py`:

- `create_image_completion` rejects non-image requests (`services/chatgpt_service.py:197-205`).
- `create_response` rejects non-image-tool requests and rejects all streaming (`services/chatgpt_service.py:225-247`).
- The file contains **no** text completions, no text responses bridge, no streaming generator, no Anthropic messages methods, and no backend abstraction comparable to upstream `OpenAIBackendAPI`.

Inside `services/utils.py`:

- there is useful prompt/history normalization already:
  - `strip_assistant_history_prefix` (`51-56`)
  - `extract_response_prompt` (`59-98`)
  - `extract_chat_prompt` (`191-217`)
- but these helpers are only used to extract **image prompts** from chat/responses payloads before calling image generation.

### How much reusable text backend/protocol layer exists right now

There is **some reusable transport logic**, but it is trapped inside the image stack and is not exposed as a text backend.

Reusable pieces already present in `services/image_service.py`:

- session/bootstrap/fingerprint handling: `_new_session` (`104-132`), `_bootstrap` (`223-237`)
- auth requirements / proof-of-work: `_chat_requirements` (`267-285`)
- conversation init / prepare: `_conversation_init` (`240-265`), `_conversation_prepare` (`288-353`)
- conversation senders for ChatGPT web endpoints:
  - legacy `/backend-api/conversation`: `_send_conversation` (`786-869`)
  - `f/conversation`: `_send_thinking_conversation` (`872-956`)
- SSE parsing/state extraction: `_parse_sse` (`960-1028`)

What is missing:

- no standalone text backend object/module
- no normalized message translator from OpenAI/Responses payloads into ChatGPT web conversation payloads
- no text streaming state machine that yields OpenAI-compatible or Anthropic-compatible chunks
- no `/v1/messages` route or Anthropic SSE adapter
- no separation between image quota logic and text request logic in `services/api.py`
- no local equivalent of upstream `services/protocol/conversation.py`

### What each upstream commit assumes exists

#### `8f1c666` — text conversation handling fixes

This commit assumes:

- a `services/openai_backend_api.py` text backend already exists
- `services/chatgpt_service.py` already exposes text methods like `list_models`, `chat_completions`, and text streaming
- model listing is text-backend-driven, not hard-coded image-only

What it actually changes:

- chooses a real text access token before calling backend text APIs (`upstream 8f1c666: services/chatgpt_service.py:51-54`, `61-99`)
- strips assistant-history prefix inside backend text completion/stream logic (`upstream 8f1c666: services/openai_backend_api.py:111-188`)
- fixes account-type recursion (`upstream 8f1c666: services/account_service.py:13-39`)

Current-fork status:

- the **account-type recursion fix is already present** in `services/account_service.py:98-116`
- the **assistant-history stripping idea is partially present** in `services/utils.py:51-56`, `59-98`, `191-217`
- the **actual text backend changes are not applicable yet** because this fork has no `OpenAIBackendAPI` or equivalent text path

#### `740b306` — Anthropic messages endpoint

This commit assumes:

- there is already a working text backend method `messages(...)`
- `ChatGPTService` already has `create_message` / `stream_message`
- the route layer only needs to expose `/v1/messages` and wrap a stream with `anthropic_sse_stream`

In the current fork, none of those prerequisites exist. The commit is a thin API surface over a missing backend.

#### `69e3446` — Claude tool streaming fixes

This commit assumes:

- `/v1/messages` already exists and works
- a text backend already streams OpenAI-style text chunks
- tool-call parsing/content-block shaping can be layered on top via `services/anthropic_protocol.py`

It also still depends on upstream `services/openai_backend_api.py`; it is not a standalone fix.

#### `aaab38f` — text streaming regressions

This commit assumes:

- a local protocol layer exists at `services/protocol/conversation.py`
- text streaming already goes through that abstraction
- route/log wrapping already treats streaming text calls as first-class operations

The current fork has none of that:

- no `services/protocol/` directory
- current `services/log_service.py` is only a log reader (`1-174`), not a request wrapper/stream mediator

### Whether `8f1c666` can be partially absorbed now

**Yes, but only in a very limited “logic extraction” sense.**

Can absorb now with low risk:

- keep the already-landed account-type recursion behavior in `services/account_service.py:98-116`
- reuse the same assistant-history stripping rule already covered by:
  - `services/utils.py:51-56`
  - `test/test_text_prompt_normalization.py:20-65`

Cannot absorb yet without prerequisite work:

- the commit’s real text fix path, because it lives inside missing backend methods (`chat_completions`, streaming text chunk generation, model listing)

So the blocker is **not** the string-manipulation logic itself; the blocker is the absence of a text bridge where that logic can run.

### Concrete explanation of the current blocker

Track A is blocked because the current fork has **only image-compatible wrappers**, not a reusable text conversation stack.

More specifically:

1. `services/api.py` treats `/v1/chat/completions` and `/v1/responses` as image endpoints with quota accounting baked in.
2. `services/chatgpt_service.py` only knows how to turn those requests into image generation/edit calls.
3. The only upstream ChatGPT web transport code lives in `services/image_service.py`, but it is coupled to image-specific system hints, image result extraction, and image error semantics.
4. Every target upstream commit assumes a missing text layer (`OpenAIBackendAPI`, `messages`, or `protocol/conversation`) already exists.

That is why upstream text commits can inform the design, but cannot be directly transplanted into this fork today.

### Smallest realistic roadmap change to unblock Track A

The roadmap should insert a **new prerequisite phase before current A1**.

Suggested rewrite:

#### **Phase A0 — Text backend bridge MVP (new)**

Goal: create the smallest fork-native text path that is good enough for later A1/A2 work, without adopting the whole upstream architecture.

Suggested todos:

1. **A0.1 Extract a fork-native text transport/backend**
   - New file, likely `services/text_backend.py` or equivalent.
   - Reuse current `services/image_service.py` transport primitives (`_new_session`, `_bootstrap`, `_chat_requirements`, conversation senders, SSE parsing ideas).
   - Keep it text-only; do not drag image polling/download logic into it.

2. **A0.2 Split image vs text routing in `services/api.py`**
   - `/v1/chat/completions` should branch:
     - image requests -> current image path
     - non-image requests -> new text backend path
   - `/v1/responses` should branch similarly instead of always requiring `image_generation`
   - image quota reservation/settlement should only happen on image flows

3. **A0.3 Add `ChatGPTService` text entrypoints**
   - minimal non-stream `chat_completions`
   - minimal stream `chat_completions`
   - minimal `responses` adapter if needed for roadmap sequencing
   - text token selection helper equivalent to upstream `_get_text_access_token`

4. **A0.4 Add regression tests**
   - non-image `/v1/chat/completions`
   - non-image `/v1/responses`
   - assistant-history de-dup behavior
   - basic streaming smoke test before Anthropic work

Then:

- **A1** becomes “apply `8f1c666`-equivalent fixes on the new bridge”
- **A2** becomes feasible (`/v1/messages`)
- **A3/A4** stay later

### Clear roadmap classification

#### Can do now with low risk

- Add a new prerequisite roadmap phase: **A0 Text backend bridge MVP**
- Reuse current transport primitives from `services/image_service.py` rather than porting upstream directory structure
- Carry forward already-compatible logic from `8f1c666`:
  - account-type recursion behavior
  - assistant-history stripping rule
  - “pick a usable text token” helper when the text bridge is introduced

#### Requires prerequisite text infrastructure

- The remaining useful part of `8f1c666`
- `740b306` `/v1/messages`
- any non-image `/v1/chat/completions` and `/v1/responses` implementation

#### Should stay deferred

- `69e3446` Claude tool streaming fixes
- `aaab38f` full text streaming regression patchset

Reason: both assume an already-stable text stream protocol layer; this fork should only attempt them after A0/A1 prove the text bridge is correct.

### File-level impact in the current repo

Likely current-fork impact for the minimal unblock plan:

| File Path | Why it would change |
|---|---|
| `services/api.py` | Split text vs image routing; add streaming/text branches; later add `/v1/messages`. |
| `services/chatgpt_service.py` | Add text access-token selection and text entrypoints; stop being image-only. |
| `services/utils.py` | Share/request normalization helpers and possibly SSE helper additions. |
| `services/image_service.py` | Extract or share transport primitives instead of leaving all ChatGPT web conversation logic image-private. |
| `services/text_backend.py` (new, suggested) | Smallest realistic home for the fork-native text bridge. |
| `services/anthropic_protocol.py` (later, new) | Only needed once `/v1/messages` exists. |
| `test/test_text_prompt_normalization.py` | Extend existing history-strip coverage to real text request/stream behavior. |
| new text API tests | Needed for chat completions, responses, and later messages/streaming. |

### Related Specs

- `.trellis/tasks/04-28-upstream-roadmap/prd.md` — Track A roadmap currently marked blocked by missing text infrastructure.
- `.trellis/tasks/04-28-upstream-roadmap/research/storage-abstraction-review.md` — example of the same roadmap task using “fork-native equivalent” rather than direct upstream transplant.

## Caveats / Not Found

- Current fork has **no** `services/openai_backend_api.py`, `services/anthropic_protocol.py`, or `services/protocol/conversation.py`.
- Current fork also has **no** `utils/helper.py`; the nearest local equivalent is `services/utils.py`.
- I did not find an existing general-purpose text streaming implementation in this fork; only image conversation SSE parsing exists.
- Upstream commit diffs were inspected locally from git history; no direct upstream merge is recommended by this research.
