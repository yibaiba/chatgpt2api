# 核心可靠性优化 1-3

## Goal

围绕当前项目最值得优先处理的三项高收益问题做一轮可靠性加固：稳定会话签名 secret、恢复前端 TypeScript 为构建门禁、以及梳理 accounts 存储切换时的迁移策略，避免登录态随机失效、前端带类型错误上线，以及管理员切换 storage backend 时出现“像丢号一样”的体验。

## What I already know

* 当前 `ConfigStore.auth_key_hash` 在管理员 auth key 来自环境变量时会重新走 `hash_auth_secret()`，而 `session_signing_secret` 依赖它。
* `GET /api/settings` / `POST /api/settings` 当前已经对 storage env override 做了 runtime target 保护，但切换到新 backend/path 时仍只是 `rebind_store()`，不会迁移旧 accounts。
* 前端 `web/next.config.ts` 仍然设置了 `typescript.ignoreBuildErrors = true`。
* `web/src/lib/request.ts` 里当前还有 `@ts-expect-error` 来绕过 axios headers 的类型问题。
* 仓库已经有现成的 `services/storage/migrate.py` 和 `scripts/migrate_storage.py`，说明 json/sqlite 之间的 accounts 迁移能力已经存在基础设施。
* 当前 fork 的既定约束仍保持不变：
  * 不引入 upstream 那套更宽的 storage/auth 抽象
  * 继续维持 accounts-only `json|sqlite`
  * 继续保留现有 `/api/image-jobs/*`、图片历史合同和权限边界

## Assumptions (temporary)

* 这轮工作先按一个组合任务规划，但实施时更适合拆成 3 个小 PR/小切片。
* 第 1、2 项（session secret、前端 TS 门禁）方案空间较小，主要是实现顺序问题，不需要额外产品决策。
* 第 3 项（storage backend 切换）存在真实方案分歧，需要先确认偏好的迁移方式。

## Open Questions

* storage backend/path 切换时，应该选择哪种迁移策略作为默认行为？

## Requirements

* 修复管理员 auth key 来自环境变量时的 session signing secret 不稳定问题。
* 前端构建不能再默认忽略 TypeScript 错误。
* 清理 `request.ts` 中依赖 `@ts-expect-error` 的请求头类型绕过。
* `json <-> sqlite` 的 accounts backend 切换采用“设置页自动迁移并在失败时回滚”的默认行为。
* storage 切换方案必须兼容现有 `/api/settings`、`/api/storage/info`、storage script 与测试结构。
* 三项工作按独立小切片推进，避免一次性混成大重构。

## Acceptance Criteria

* [x] 当管理员 auth key 来自环境变量时，session cookie 在同一进程内不会因 secret 漂移而失效。
* [x] 若未显式配置 `CHATGPT2API_SESSION_SECRET`，系统仍能生成稳定且可验证的 session signing secret。
* [x] 前端构建流程在存在 TypeScript 错误时会失败，而不是继续产出构建结果。
* [x] `web/src/lib/request.ts` 不再依赖 `@ts-expect-error` 规避 headers 类型问题。
* [x] 管理员切换 accounts storage backend/path 时，旧 store 的 accounts 会迁移到新 store 后再切 runtime binding。
* [x] 若迁移或 runtime rebind 失败，config、runtime binding 与目标端数据状态会回滚到安全状态。
* [x] 相关后端/前端回归测试补齐并保持现有合同不回退。

## Definition of Done (team quality bar)

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* Docs/notes updated if behavior changes
* Rollout/rollback considered if risky

## Research Notes

### Constraints from our repo/project

* storage factory 与 `/api/settings` 当前已经允许 runtime 切换 `json|sqlite`，所以继续保留“可从设置页切换”的方向更符合当前 fork 的产品形态。
* 迁移 helper 已存在，但目前没有接到设置页切换链路中。
* 如果直接禁止切换，需要同时调整 UI/接口提示，否则会与当前 `/api/storage/info` + settings 暗示的能力不一致。

### Feasible approaches here

**Approach A: 自动迁移并回滚**（Chosen）

* How it works:
  * `/api/settings` 发现 backend/path 变化时，先把旧 store 数据迁移到新 store，再 `rebind_store()`。
  * 任一步失败都回滚 config 与 runtime binding，必要时清理目标端的半成品。
* Pros:
  * 最符合管理员从设置页直接切换 storage 的直觉。
  * 复用现有 migration helper，整体体验最好。
* Cons:
  * 需要把“迁移 + 回滚 + 幂等”做扎实，测试面更大。

**Approach B: 设置页只允许切换空目标，非空源一律阻止**

* How it works:
  * 只要检测到源 store 有 accounts，就拒绝切换，并提示用户先运行迁移脚本。
* Pros:
  * 实现简单，风险低。
* Cons:
  * 和当前“设置页可切换 backend”的心智不一致，用户体验一般。
  * 实际运维会更依赖脚本和人工步骤。

**Approach C: Hybrid**

* How it works:
  * 后端切换（json ↔ sqlite）时自动迁移；仅路径变化时做更保守的检查/提示。
* Pros:
  * 兼顾一部分体验与风险。
* Cons:
  * 规则更复杂，后续更难解释。

## Technical Approach

### 1. Session secret 稳定化

* 保持现有 auth contract，不引入新的 auth storage 抽象。
* 让 `ConfigStore` 在 env auth key 场景下也能返回稳定的 signing secret：
  * 优先继续使用 `CHATGPT2API_SESSION_SECRET`
  * 否则从 env auth key 派生稳定 secret，而不是每次重新加随机 salt 哈希
* 为 cookie 生成/校验补一条真实回归测试，确保 login -> session 读取链路不漂移。

### 2. 前端 TypeScript 门禁恢复

* 去掉 `web/next.config.ts` 中 `ignoreBuildErrors`。
* 先修 `web/src/lib/request.ts` 的 axios headers 类型问题，再看 build 暴露出的真实错误。
* 保持现有前端构建命令不变，避免引入新的构建工具或脚本体系。

### 3. Storage 切换自动迁移

* 当 `/api/settings` 检测到 accounts backend/path 变化时：
  1. 构建 old store / new store
  2. 迁移 old -> new
  3. rebind runtime store 到新目标
  4. 任一步失败则回滚 config/runtime，并清理目标端半成品
* 继续保留 env override 对 runtime target 的保护逻辑。
* 优先复用现有 `services/storage/migrate.py`，不要新造第二套迁移逻辑。

## Decision (ADR-lite)

**Context**: Top 3 优化里，只有 storage 切换策略存在明确方案分歧；session secret 和 TS gate 基本是直接修复型任务。  
**Decision**: 采用 **Approach A：设置页自动迁移并在失败时回滚**。  
**Consequences**:

* 优点：管理员体验最好，和当前 settings/storage UI 心智一致。
* 代价：需要更严格的迁移/回滚测试，避免部分成功造成脏状态。
* 后续：如果未来支持更多 storage backend，再评估是否把迁移能力独立成更明确的 service layer。

## Out of Scope

* 不处理 `/image` 页面大组件拆分。
* 不处理 register runner、image history blob 拆分、settings store/page 重构等后续优化项。
* 不引入新的数据库后端、队列系统或 upstream 风格的大抽象重构。

## Technical Notes

* 关键文件：
  * `services/config.py`
  * `services/api.py`
  * `services/account_service.py`
  * `services/storage/factory.py`
  * `services/storage/migrate.py`
  * `web/next.config.ts`
  * `web/src/lib/request.ts`
* 相关现有测试：
  * `test/test_storage_api.py`
  * `test/test_config.py`
  * `test/test_auth_security.py`
* 当前 build/test 基线：
  * backend: `python3 -m unittest discover -s test`
  * frontend: `cd web && npm run build`
* Trellis subtasks:
  * `.trellis/tasks/04-29-session-secret-stability`
  * `.trellis/tasks/04-29-frontend-type-gate`
  * `.trellis/tasks/04-29-storage-switch-migration`
* 实际落地文件：
  * `services/auth_security.py`
  * `services/config.py`
  * `services/api.py`
  * `web/next.config.ts`
  * `web/src/lib/request.ts`
  * `web/src/app/accounts/page.tsx`
  * `web/src/app/settings/store.ts`
  * `web/src/lib/image-prompt-gallery.ts`
  * `test/test_config.py`
  * `test/test_auth_security.py`
  * `test/test_storage_api.py`

## Implementation Plan (small PRs)

* PR1: `session secret 稳定化`
  * 修复 signing secret 派生逻辑
  * 补 login/session 回归测试
* PR2: `前端类型门禁恢复`
  * 去掉 `ignoreBuildErrors`
  * 修复 `request.ts` 类型问题，并清理 build 暴露的最小必要 TS 错误
* PR3: `storage 切换自动迁移`
  * 接通 migration helper
  * 补迁移成功 / 回滚失败 / env override 共存的回归测试
