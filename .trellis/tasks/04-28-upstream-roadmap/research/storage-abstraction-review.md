# Research: storage-abstraction-review

- **Query**: Assess whether and how to absorb upstream commit `48c40e6` (pluggable storage backend system) into the current fork for Track C1, without implementing the abstraction yet unless needed to explain the design.
- **Scope**: mixed
- **Date**: 2026-04-28

## Findings

### Files Found

| File Path | Description |
|---|---|
| `services/account_service.py` | Current fork account-pool persistence and highest-leverage first abstraction target |
| `services/auth_service.py` | Auth-user persistence; hash migration, session contract, atomic writes |
| `services/image_history_service.py` | Server-side image conversation persistence with owner scoping and legacy payload normalization |
| `services/register_service.py` | Register runner state/log persistence with background-thread frequent saves |
| `services/config.py` | Core settings store, admin auth hash migration, env overlay |
| `services/system_settings.py` | Proxy-pool persistence into the same `config.json` file as `ConfigStore` |
| `services/cpa_service.py` | CPA remote-pool config + import-job persistence |
| `services/sub2api_service.py` | sub2api server config + import-job persistence |
| `services/api.py` | Current fork route surface for settings/accounts/auth-users/image-history/register/cpa/sub2api |
| `upstream 48c40e6: services/storage/base.py` | New upstream account-storage interface |
| `upstream 48c40e6: services/storage/factory.py` | Env-driven backend selector (`json/sqlite/postgres/git`) |
| `upstream 48c40e6: services/storage/json_storage.py` | JSON accounts backend |
| `upstream 48c40e6: services/storage/database_storage.py` | SQLAlchemy full-rewrite accounts backend |
| `upstream 48c40e6: services/storage/git_storage.py` | Git-backed accounts backend with clone/pull/push cycle |
| `upstream 48c40e6: services/config.py` | Lazy singleton backend factory on config |
| `upstream 48c40e6: api/system.py` | `/api/storage/info` endpoint |
| `upstream 48c40e6: scripts/migrate_storage.py` | Accounts-only migration/export/import script |

### Code Patterns

#### 1. Upstream commit `48c40e6` is narrower than its label: it abstracts **accounts only**

- Upstream `StorageBackend` exposes only `load_accounts`, `save_accounts`, `health_check`, and `get_backend_info` (`48c40e6:services/storage/base.py:9-29`).
- `AccountService` is the only business service moved onto the backend (`48c40e6:services/account_service.py:654-660`, instantiated at `:1010`).
- Upstream `ConfigStore` only adds lazy backend creation (`48c40e6:services/config.py:1083-1085`, `1153-1158`).
- No upstream changes were made to auth users, image history, register runner, CPA config, sub2api config, or settings persistence in this commit.

**Implication:** upstream did **not** solve “repo-wide pluggable storage”; it solved “pluggable account-pool persistence”.

#### 2. Current fork persistence is split across multiple distinct domains

**Accounts domain**
- `services/account_service.py` loads/saves `accounts.json` directly (`165-181`) and is consumed by routes/importers/runner code (`services/api.py:853-913`, `services/cpa_service.py:361-363`, `services/sub2api_service.py:564-566`, `services/register_service.py:382-383`).

**Auth users domain**
- `services/auth_service.py` persists `auth_users.json` (`15`, `101-127`) using atomic temp-file replacement (`22-39`).
- It embeds contract-critical behavior: plaintext-to-hash migration on load (`62-81`, `114-123`), admin auth-key conflict checks (`141-150`), and quota accounting/session shaping (`167-187`, `302-350`).
- Tests lock in these behaviors (`test/test_auth_security.py:79-121`).

**Image history domain**
- `services/image_history_service.py` persists `image_history.json` (`11`, `234-247`).
- It also owns owner scoping and payload normalization/legacy compatibility (`160-172`, `174-243`, `262-321`).
- This is not a generic KV store; it is a domain-specific conversation ledger.

**Register runner domain**
- `services/register_service.py` persists `register.json` (`17`, `206-216`), frequently saving from a live background thread (`291-341`, `343-408`).
- It reuses `auth_service._write_text_atomically` rather than plain `write_text` (`12`, `213-216`).
- Tests assert normalized persisted state across reloads (`test/test_register_service.py:33-69`).

**Settings domain**
- `services/config.py` persists `config.json` (`13`, `88-89`) and performs admin auth-key hashing migration (`91-97`), env override logic (`116-143`), and public redaction (`201-208`).
- `services/system_settings.py` independently reads/writes the **same file** for proxy-pool state (`174-207`).

**Integration config domains**
- `services/cpa_service.py` persists `cpa_config.json` (`19`, `91-107`).
- `services/sub2api_service.py` persists `sub2api_config.json` (`20`, `94-110`).
- Both include long-lived secrets plus background import-job status.

#### 3. Current fork already has domain-specific contracts that a “single storage backend” would blur

- `auth_service` is security-sensitive: hashed secrets must remain hashed at rest; `list_users()` and sessions intentionally hide secrets while preserving `image_history_persistence_mode` (`153-187`).
- `image_history_service` stores per-owner conversation trees and still accepts legacy shapes (`73-97`, `188-243`).
- `register_service` is high-churn operational state, not just configuration.
- `config.py` and `system_settings.py` share one physical JSON file but different access patterns; this is already a coupling hotspot.

#### 4. Upstream backends are risky/premature for this fork right now

**JSON backend**
- Upstream JSON backend writes with plain `write_text` (`48c40e6:services/storage/json_storage.py:160-166`), which is weaker than current atomic write behavior already used in auth/register.

**Database backend**
- Upstream database backend deletes all account rows and re-inserts everything on each save (`48c40e6:services/storage/database_storage.py:248-269`).
- That is acceptable only for the current account-list shape, not for higher-churn or larger domains.

**Git backend**
- Upstream Git backend clones/pulls, writes, commits, and pushes during save (`48c40e6:services/storage/git_storage.py:391-454`).
- This is high-latency and operationally fragile for a service that may update account stats frequently.

**Health endpoint**
- Upstream `/api/storage/info` assumes the backend abstraction is worth exposing now (`48c40e6:api/system.py:1212-1219`).
- Current fork has no `api/system.py`; equivalent admin routes live in `services/api.py`.

**Migration/test scripts**
- Upstream `scripts/migrate_storage.py` and `scripts/test_storage.py` are accounts-only tooling (`48c40e6:scripts/migrate_storage.py:1248-1379`) and assume env-driven backend switching.

**Dependency/runtime changes**
- Upstream adds `sqlalchemy`, `psycopg2-binary`, `gitpython` plus Docker OS packages `git`, `libpq-dev`, `gcc` (`48c40e6` diff for `pyproject.toml` and `Dockerfile`).
- None of these are present in the current fork today (`pyproject.toml:7-14`).

### External References

- No external web research was required; the review is based on the repository state and the upstream commit contents.

### Related Specs

- `.trellis/tasks/04-28-upstream-roadmap/prd.md` — roadmap with Track C1/C2/C3 placeholders and non-merge constraint.

## Recommendation

### Bottom line

Do **not** adopt a repo-wide “single unified storage backend” in the first pass.

For this fork, the low-risk interpretation of upstream `48c40e6` is:

1. Treat it as an **account-pool storage abstraction** blueprint, not a whole-app storage framework.
2. Keep **auth users**, **image history**, **register runner**, **settings**, **CPA**, and **sub2api** direct-file-backed for now.
3. If Phase C2 proceeds, introduce the abstraction for **accounts only**, while extracting a small reusable atomic JSON helper for future domains.

### Why only accounts should enter first

- It matches upstream’s actual scope.
- `AccountService` already has a clean load/save seam (`165-181`) and many callers that would benefit from implementation swapping without changing contracts.
- Accounts are the only domain that plausibly benefits soon from future SQLite/Postgres exploration.
- Other domains each carry extra invariants that would be easy to regress if forced through one generic interface.

### Domains that should stay out of the initial abstraction

**Stay direct-file-backed for now**

- `services/auth_service.py`
  - security-sensitive hashing and migration-on-read
  - contract tests already exist
- `services/image_history_service.py`
  - owner-scoped, legacy-compatible, potentially large payloads
  - default product mode still advertises browser persistence via `image_history_persistence_mode`
- `services/register_service.py`
  - background-thread, frequent-save operational state/logs
- `services/config.py` + `services/system_settings.py`
  - shared-file coupling should be untangled before any backend work
- `services/cpa_service.py`
- `services/sub2api_service.py`
  - mostly admin integration config + secrets + job state, not worth backend complexity yet

### Minimal Phase C2 shape for this fork

Recommended shape:

```python
class AccountStore(Protocol):
    def load_accounts(self) -> list[dict[str, Any]]: ...
    def save_accounts(self, accounts: list[dict[str, Any]]) -> None: ...
```

Implementation plan:

1. Add `services/storage/base.py` with `AccountStore`-style interface only.
2. Add `services/storage/json_storage.py` implementing current `accounts.json` behavior.
3. Prefer an extracted atomic JSON writer helper (do **not** copy upstream plain `write_text` behavior).
4. Change `AccountService.__init__` to accept the store/backend.
5. Keep singleton wiring local and simple; either:
   - instantiate in `services/account_service.py`, or
   - add a narrowly named `config.get_account_store()`.

Optional internal helper for future use:

```python
def read_json(path: Path, *, default: object) -> object: ...
def write_json_atomic(path: Path, value: object) -> None: ...
```

That helper can later support auth/register/image-history work **without** pretending the business interfaces are the same.

### Phased migration order

1. **C2a — shared persistence utility**
   - Extract atomic JSON read/write helper out of `auth_service` private utility usage.
2. **C2b — accounts-only abstraction**
   - Add `AccountStore` + `JsonAccountStore`.
   - Refactor `AccountService` constructor/singleton only.
3. **C2c — account regression coverage**
   - Add focused tests around add/update/delete/refresh persistence through the new store seam.
4. **Later only if needed**
   - Evaluate `AuthUserStore` as a separate domain abstraction, not as part of `StorageBackend`.
   - Revisit image-history only if server-side persistence becomes a primary product mode.
   - Revisit settings after consolidating `config.py` and `system_settings.py` ownership.

### Concrete file-level impact in the current repo

**Likely touched in a cautious C2 implementation**

| File Path | Expected impact |
|---|---|
| `services/account_service.py` | Constructor changes from `Path` to account store/backend; `_load_accounts/_save_accounts` delegate to backend |
| `services/config.py` | Optional narrow factory such as `get_account_store()`; avoid introducing global “all storage” language |
| `services/storage/base.py` | New accounts-only interface |
| `services/storage/json_storage.py` | New JSON implementation, ideally atomic |
| `test/` new or existing account tests | Regression tests for account persistence seam |

**Should not be in first implementation PR**

| File Path | Why not yet |
|---|---|
| `services/auth_service.py` | Security and contract-sensitive |
| `services/image_history_service.py` | Distinct owner/payload semantics |
| `services/register_service.py` | Frequent background writes |
| `services/cpa_service.py` | Config/secret storage, low payoff |
| `services/sub2api_service.py` | Config/secret storage, low payoff |
| `services/api.py` | No route changes required unless adding optional diagnostics |
| `services/system_settings.py` | Separate settings cleanup issue |

### Compatibility risks

- **Auth regressions** if secret hashing/redaction/migration behavior is generalized away.
- **Image-history regressions** if owner scoping or legacy alias normalization is forced through a generic backend.
- **Crash-safety regressions** if upstream plain `write_text` replaces current atomic write usage patterns.
- **Config clobbering** remains a separate risk because `ConfigStore` and `SystemSettingsService` both write `config.json`.
- **Dependency/ops creep** from SQLAlchemy/Postgres/Git support would expand runtime complexity before the fork has proven need.

## Caveats / Not Found

- Current fork has **no** `api/system.py`; the nearest equivalent route surface is `services/api.py`.
- Upstream `docker-compose-example.yml` for this commit path was not present; only `docker-compose.yml` changed.
- I did not find existing current-fork tests dedicated to a storage abstraction seam for accounts; C2 will need new coverage there.
