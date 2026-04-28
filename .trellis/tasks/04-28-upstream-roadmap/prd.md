# absorb upstream text-and-management capabilities

## Goal

在不直接合并 `upstream/main` 大重构的前提下，把 5 组高价值能力逐步吸收进当前分支：注册 runner UI、图片管理/日志管理/敏感词相关能力、可插拔存储后端、Anthropic / Claude 文本链路，以及文本流修复。目标是通过 Trellis 风格的小步迭代，把“可独立落地、可验证、可回滚”的能力分批引入，而不是一次性迁移整套 upstream 架构。

## What I already know

* 当前分支已经手工吸收了一批 upstream 的低风险更新：图生图空结果恢复、限流账号自动移除配置、compose 可写配置、东八区时间显示。
* 当前分支与 `upstream/main` 仍然高度分叉，不适合直接 merge；必须按能力切片做手工移植或局部 cherry-pick。
* 用户明确希望后续继续吸收以下 5 组能力：
  * `77ee63d` 注册 runner UI
  * `69f0a0e` 图片管理/日志管理/敏感词
  * `48c40e6` 可插拔存储后端
  * `740b306` / `69e3446` Anthropic / Claude 文本链路
  * `aaab38f` 文本流修复
* 这些改动的体量和风险并不均衡：
  * `77ee63d`: 13 files / 1890 insertions，属于新功能垂直切片
  * `69f0a0e`: 40 files / 2060 insertions / 2384 deletions，明显带协议层重构
  * `48c40e6`: 16 files / 869 insertions，属于基础设施级变更
  * `740b306`: 3 files / 68 insertions，适合做 Anthropic MVP 起点
  * `69e3446`: 4 files / 299 insertions，依赖文本链路
  * `aaab38f`: 2 files / 49 insertions，依赖 `services/protocol/conversation.py`

## Assumptions (temporary)

* 优先级不是“最快把 upstream 合并完”，而是“先把最有价值、可独立验收的能力吸收到当前 fork”。
* 允许把 upstream 的一个大提交拆成当前分支更适合的小 PR 序列，而不是保留上游提交边界。
* 当前 fork 仍以现有图片链路和 API 结构为主，不会为了吸收单项能力立即切换到 upstream 的完整 protocol 架构。

## Open Questions

* 后续实现阶段需要确认：Anthropic / Claude 文本链路是只做 `/v1/messages` MVP，还是顺带统一文本流式协议抽象。

## Requirements

* 为上述 5 组能力制定逐步吸收计划，按依赖关系拆成可单独提交、单独验证的小阶段。
* 每个阶段都要明确：
  * 目标能力
  * 主要影响文件/层
  * 风险点
  * 验证方式
  * 是否需要 feature flag / 配置开关
* 优先采用“当前分支等价移植”而不是“大量对齐 upstream 目录结构”。
* 对明显带基础设施重构的部分（尤其 `48c40e6` 和 `69f0a0e`），需要先做前置抽象/适配层计划，再决定是否整体移植。

## Acceptance Criteria

* [ ] 形成一份按阶段拆分的 roadmap，覆盖 5 组目标能力
* [ ] 每个阶段都标注依赖关系与推荐顺序
* [ ] 明确哪些能力可直接提、哪些能力必须先做适配
* [ ] 明确哪些内容暂不纳入首轮吸收
* [ ] 计划能直接转化为 Trellis 执行阶段的 todo / PR 序列

## Definition of Done

* PRD 完整记录目标、边界、顺序、风险与验证方式
* 路线图可拆成多个小 PR
* 每个阶段都有对应测试/构建/回滚考虑
* 不要求本次直接实现所有阶段，只完成规划收敛

## Technical Approach

采用 **“三轨并行、按风险递增收敛”** 的吸收策略：

### Track A: 文本链路能力

先处理最容易独立验证的文本能力，再决定是否进一步引入 protocol 层。

1. **Phase A0 — Text backend bridge MVP**
   * 目标：先在当前 fork 中建立最小可用的非图片文本桥接层，让 `/v1/chat/completions`、`/v1/responses` 不再只是 image shim
   * 影响层：`services/api.py`、`services/chatgpt_service.py`、`services/image_service.py` 的可复用 transport、以及新的 `services/text_backend.py`（或等价模块）
   * 风险：需要把图片 quota 逻辑与文本路由正确拆开，避免影响现有图片路径
   * 验证：非图片 chat completions / responses、assistant-history 去重、最小文本流式 smoke test
   * 当前进展：已完成首个 MVP——新增 `services/text_backend.py`，将 `/v1/chat/completions` 与 `/v1/responses` 按 image/text 分流，新增最小文本 token 选择与 assistant-history 去重；当前先支持非图片非流式文本路径，streaming 与 `/v1/messages` 仍留给后续阶段

2. **Phase A1 — 文本链路基线对齐**
   * 目标：补齐 `8f1c666` 里仍对当前分支有价值的文本对话修正（避免 assistant 历史重复、文本 access token 获取策略等）
   * 影响层：`services/chatgpt_service.py`、文本后端桥接层、相关测试
   * 风险：可能影响现有非图片文本 API 行为
   * 验证：文本 completions / responses 非流式 + 流式回归测试
   * 当前进展：已完成首个 baseline 对齐——`/v1/chat/completions` 非图片文本路径新增最小 SSE stream，`/v1/models` 不再是 image-only 列表，相关文本流回归测试已补齐；`/v1/responses` 仍保持非流式最小文本返回，`/v1/messages` 继续留给 A2

3. **Phase A2 — Anthropic messages MVP**
   * 目标：吸收 `740b306`，先提供最小可用 `/v1/messages` 或等价 Anthropic 入口
   * 影响层：API 路由、`chatgpt_service`、helper / SSE 适配
   * 风险：协议映射与错误模型不一致
   * 验证：最小请求/响应测试、错误路径测试、流式兼容测试
   * 当前进展：已完成首个 MVP——新增 `/v1/messages`，支持最小非流式文本返回与 Anthropic 风格 SSE 事件流（`message_start` / `content_block_*` / `message_delta` / `message_stop`）；当前仍只覆盖纯文本消息，不含 tool use、thinking 或更完整协议细节

4. **Phase A3 — Claude 文本流修复**
   * 目标：在 MVP Anthropic 能跑通后，再吸收 `69e3446`
   * 影响层：Anthropic 协议层、SSE 输出、文本后端桥接
   * 风险：与当前文本流事件格式冲突
   * 验证：流式分块顺序、delta 合并、tool / content block 边界测试
   * 当前进展：已完成首个 Claude streaming fix——新增轻量 `services/anthropic_protocol.py`，让 `/v1/messages` 在工具场景下可把 tool markup 收敛成 `tool_use` content blocks，并在流式模式下输出 `input_json_delta`；仍未覆盖 thinking 与更完整协议分支

5. **Phase A4 — 文本流回归修复**
   * 目标：评估 `aaab38f` 是否需要在当前分支建立轻量 conversation/protocol 适配层后再吸收
   * 风险：它依赖 upstream `services/protocol/conversation.py`，不能生搬硬套
   * 建议：先做“最小等价修复”，仅移植具体 bug 逻辑，不完整搬 protocol 目录
   * 当前进展：已完成最小等价修复——assistant-history 前缀剥离改为循环处理，并补到 chat/messages 的非流式与流式 snapshot 归一化中，避免 replay 旧 assistant 文本导致重复 delta；仍未引入 upstream `services/protocol/conversation.py`

### Track B: 管理与运营能力

优先引入垂直切片的新页面/新服务，再评估是否接入更重的管理后台能力。

1. **Phase B1 — 注册 runner UI**
   * 来源：`77ee63d`
   * 目标：引入注册页 + 注册服务 + 必要的设置页入口
   * 风险：邮件/外部服务依赖、账号创建流程复杂
   * 建议：先做后端 service stub + API contract + UI 骨架，再逐步填充 provider 细节
   * 验证：页面访问、配置保存、关键服务单测
   * 当前进展：已完成首个可用闭环——`/api/register*` 控制面、`/register` 管理页、顶部导航入口、后端回归测试，以及 `tempmail_lol` 的最小真实执行链路；其余 provider 后续再扩展

2. **Phase B2 — 日志管理**
   * 来源：`69f0a0e` 的子集
   * 目标：只吸收日志查看/筛选能力，不同时引入整套 protocol 重构
   * 风险：日志结构和现有 `services/log_service.py` 差异
   * 建议：先抽取日志读取 API + `/logs` 页面；敏感词、图片管理延后
   * 验证：日志 API、页面加载、筛选展示
   * 当前进展：已完成当前 fork 的低风险切片——新增 `services/log_service.py` 聚合 `logs/uvicorn.log` 与 register runner 日志，新增 admin-only `/api/logs`、`/logs` 页面、顶部导航入口，以及后端/API 回归测试；暂未引入 upstream 的 protocol 层埋点与结构化 JSONL 调用日志

3. **Phase B3 — 图片管理**
   * 来源：`69f0a0e` 的子集
   * 目标：在当前图片历史/图片文件结构上补一个只读管理页
   * 风险：需要协调 `image_history`、文件落盘、权限隔离
   * 验证：管理员访问、列表加载、删除/清理行为
   * 当前进展：已完成首个低风险 UI 管理切片——在现有 `/image` 工作台上补齐删除确认、结果图尺寸/体积展示、侧边栏滚动体验优化，复用现有 `image_history` 与权限边界；独立 admin-only 图片后台页暂不引入

4. **Phase B4 — 敏感词/高级运营能力**
   * 目标：先落一个低风险、管理员可配的敏感词拦截能力，不引入更重的运营后台
   * 当前进展：已完成首个可用切片——`config.json` / `/api/settings` / 设置页新增敏感词开关与词表，图片直连、`/api/image-jobs/*`、`/v1/chat/completions`、`/v1/responses`、`/v1/messages` 都会在调用上游前拦截命中 prompt，并补齐后端回归测试与前端 build 验证

### Track C: 基础设施能力

1. **Phase C1 — 存储抽象设计评审**
   * 来源：`48c40e6`
   * 目标：先评估当前 `AccountService`、`auth_service`、image history 是否都需要进入统一 storage abstraction
   * 产出：抽象边界、迁移策略、兼容矩阵
   * 风险：这是基础设施大改，容易拖累所有业务能力
   * 当前进展：已完成设计评审。结论是 upstream `48c40e6` 实际上只抽象了 **accounts persistence**，不应被解释成全仓统一存储层；当前 fork 的首选路线应是 `accounts only`，而 `auth_service`、`image_history_service`、`register_service`、`config/system_settings`、`cpa/sub2api` 继续保持 direct-file-backed

2. **Phase C2 — JSON backend 抽象化**
   * 目标：先保留现有 JSON 存储行为，只把接口抽象出来
   * 好处：不引入数据库/Git 依赖，也能为后续 SQLite/Postgres 铺路
   * 推荐拆分：
     * C2a：先抽公共原子 JSON 读写 helper
     * C2b：只为 `AccountService` 引入 `AccountStore` / `JsonAccountStore`
     * C2c：补 accounts persistence seam 的回归测试
   * 当前进展：已完成 C2a/C2b/C2c 的首个实现切片——新增 `services/storage/base.py`、`services/storage/json_storage.py`、`services/storage/json_utils.py`，将 `AccountService` 改为依赖 accounts-only store seam，并补齐 store-backed 回归测试；其余域仍保持 direct-file-backed

3. **Phase C3 — SQLite/Postgres/Git backend**
   * 仅在 C2 稳定后再逐项引入
   * 每种 backend 单独作为一阶段，不打包一起上
   * 当前进展：已完成四个低风险切片——先新增 `services/storage/factory.py` 统一 accounts store 构建，并补充 admin-only `GET /api/storage/info` 用于查看当前 backend、存储路径与可写状态；随后新增基于标准库 `sqlite3` 的 `SqliteAccountStore`，支持通过 `storage_backend=sqlite` + `storage_sqlite_path` 切换 accounts 存储后端；再补充 `scripts/migrate_storage.py`，支持当前 `json` 与 `sqlite` 后端之间的 accounts 数据迁移；最后新增 `scripts/test_storage.py` 作为 `json/sqlite` backend 的隔离式 round-trip 自检工具。当前 fork 按 SQLite-only 路线收口，Postgres/Git 具体实现与新增依赖不再继续推进

## Research Notes

### Why not merge upstream directly

* `69f0a0e` 已经包含 protocol 层重构、`chatgpt_service.py` 删除重写、前后端多模块联动，直接 merge 风险极高。
* `48c40e6` 是基础设施级变更，需要先明确当前 fork 是否真的要接受多后端存储复杂度。
* `aaab38f` 依赖 upstream protocol/conversation 抽象，不能脱离上下文直接 cherry-pick。
* `48c40e6` 的 upstream storage abstraction 作用域比标题窄：它只覆盖 `AccountService`，并没有同时抽象 auth users、image history、register runner、settings、CPA 或 sub2api。
* 当前 fork 的高风险点不是“没有统一 storage layer”，而是不同域有不同不变量：
  * `auth_service` 有 secret hash/migration/redaction 合同
  * `image_history_service` 有 owner scope + legacy payload normalization
  * `register_service` 有后台线程高频写入
  * `config.py` 和 `system_settings.py` 共享 `config.json`，这是单独的耦合问题
* 因此 Track C 的安全起点应是 `accounts-only abstraction`，并复用/抽取原子 JSON 持久化 helper，而不是直接吞入 SQLite/Postgres/Git backend 与依赖膨胀

### Feasible approaches here

**Approach A: 直接 merge upstream 相关提交**

* Pros: 看起来快
* Cons: 冲突大、回归风险高、与当前 fork 结构不兼容

**Approach B: 功能切片手工移植** (Recommended)

* Pros: 可按当前分支结构落地，可拆小 PR，可独立验收
* Cons: 需要人工比对，前期规划成本更高

**Approach C: 先新建兼容层，再批量复用 upstream protocol**

* Pros: 适合后续继续大量跟 upstream 对齐
* Cons: 初期投入大，更像一次局部架构迁移

## Decision (ADR-lite)

**Context**: 需要吸收多组 upstream 能力，但当前 fork 与 upstream 已高度分叉。  
**Decision**: 采用 Approach B，以当前分支为基线，按文本链路、管理能力、基础设施三条轨道分阶段手工移植。  
**Consequences**: 初期速度略慢，但能显著降低冲突和回归风险；未来若文本/protocol 继续扩展，再考虑为 protocol 层建立兼容抽象。

## Out of Scope

* 直接 merge `upstream/main`
* 首轮就完整引入 `69f0a0e` 的所有 protocol 重构
* 首轮就同时上线 SQLite / Postgres / Git 三种存储后端
* 未经拆分直接引入所有注册/敏感词/日志/图片管理能力

## Technical Notes

* Current repo root: `/Users/yibai/Code/PycharmProjects/chatgpt2api`
* Task dir: `.trellis/tasks/04-28-upstream-roadmap`
* Relevant upstream commits:
  * `77ee63d` registration runner UI
  * `69f0a0e` image manager / logs / sensitive-word-related management
  * `48c40e6` pluggable storage backend
  * `740b306` anthropic messages endpoint
  * `69e3446` claude message tool streaming
  * `aaab38f` text streaming regressions
* Already absorbed separately in current branch:
  * image edit empty-result retry
  * rate-limited account auto-removal setting
  * writable config mount in compose
  * timezone display fix to Asia/Shanghai
