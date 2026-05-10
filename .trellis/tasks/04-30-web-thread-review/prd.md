# 网页式持续对话与敏感审查

## Goal

为当前仓库的文本链路补齐“类似 GPT 网页”的持续对话能力：同一个客户端线程可以持续复用同一条上游对话，而不是每次重新开聊；同时在这条线程里加入敏感内容审查能力，满足最小可用的对话安全控制。

## What I already know

* 用户目标不是导入 GPT 网页已有历史，而是提供“像网页一样一直对话”的能力。
* 用户还希望系统能“审查对话里面是否有敏感的”，至少覆盖对话过程中的敏感内容控制。
* 当前仓库的文本后端位于 `services/text_backend.py`，会为每次请求新建 `parent_message_id`，并通过 `_conversation_init()` 获取新的 `conversation_id`。
* 当前 `TextBackend.complete()` / `stream()` 只向上层返回 `conversation_id`，没有提取或持久化下一轮继续所需的 assistant message/head id。
* 当前 `services/chatgpt_service.py` 的 `/v1/chat/completions`、`/v1/responses`、`/v1/messages` 都是“无状态 prompt 调上游”，没有面向客户端暴露可复用线程。
* 当前仓库已经有统一敏感词拦截能力：`ensure_prompt_not_blocked()` + `config.sensitive_word_filter_enabled/sensitive_words`，并且已接到文本/图片入口。
* 当前仓库已有一个适合参考的持久化模式：`services/image_history_service.py` 使用 JSON 文件 + 进程内缓存 + `Lock` 做线程安全读写。
* 对照参考项目 `432539/gpt2api`，其“网页式持续对话”关键不是拼接历史 prompt，而是维护上游 `ConvID + ParentMsgID`，并走更贴近网页的 `f/conversation/prepare` + `f/conversation` 流程。

## Assumptions (temporary)

* MVP 继续沿用当前仓库已有的敏感词配置入口，而不是新建一套独立审查规则系统。
* 若当前上游 `/backend-api/conversation` 能稳定支持线程复用，则先最小改造；只有当它无法满足持续对话时，才升级到 `f/conversation` 新协议。
* 前端工作台先做管理员专用页，普通用户暂不开放单独的 prompt review 入口。

## Requirements (evolving)

* 提供服务端维护的文本线程能力，使客户端可以通过稳定的线程标识继续对话。
* 同一线程的后续请求应复用同一条上游会话，而不是每次新建空会话。
* 在线程对话入口接入敏感内容审查，至少保持与现有敏感词配置兼容。
* 线程路径中的用户输入与模型输出都应经过敏感审查；命中时要有明确、可区分的错误或拦截结果。
* 新能力不能破坏当前无状态文本接口的兼容性；不带线程标识时，现有调用方式仍可继续工作。
* 出错时应明确区分：线程不存在、线程失效、上游拒绝复用、敏感词命中。
* 设置页敏感词区域附近要提供一个入口，跳转到单独的 Prompt 审查工作台。
* Prompt 审查工作台需要支持流式输出、独立线程列表，以及面向长对话的上下文策略提醒/自动新开线程能力。
* 页面右侧需要汇总当前线程中命中的已配置敏感词，便于持续审查。

## Acceptance Criteria (evolving)

* [ ] 客户端可以创建或自动获得一个线程标识，并用它在多轮请求中保持连续对话。
* [ ] 至少一条文本接口（OpenAI chat/completions）支持线程复用和 threaded stream。
* [ ] 敏感词命中时会在线程路径中被稳定拦截，且输入审查与输出审查都能覆盖线程路径。
* [ ] 不带线程标识的普通文本请求仍保持兼容。
* [ ] 设置页可进入单独的 Prompt 审查工作台，且管理员导航也能访问该页面。
* [ ] Prompt 审查工作台支持流式增量展示、线程复用，以及当前线程的敏感词命中总结。
* [ ] 增加针对线程创建、线程续聊、threaded stream、敏感词命中、线程失效/不存在的回归测试。

## Definition of Done (team quality bar)

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* Docs/notes updated if behavior changes
* Rollout/rollback considered if risky

## Technical Approach

* 先在现有 `/backend-api/conversation` 文本链路上叠加 thread store，而不是立刻切换到 `f/conversation`。
* 对外先保持现有 OpenAI/Anthropic 兼容接口，按最小增量新增可选线程字段（例如请求可带 `thread_id`，响应返回可继续使用的 `thread_id`）。
* 新增一个服务端 thread store，保存：
  * `thread_id`
  * `conversation_id`
  * `parent_message_id`
  * 基础元数据（owner/updated_at/last_model/last_error 等最小字段）
* `services/text_backend.py` 需要补齐“从上游响应中提取下一轮继续所需 head/message id”的能力。
* `services/chatgpt_service.py` 负责：
  * 根据请求决定新建线程 / 复用线程
  * 在线程请求发上游前做输入敏感审查
  * 在线程响应回客户端前做输出敏感审查
  * 在线程成功后更新 store 中的 head 状态
* 线程路径失败时应避免把坏状态写回 store；若上游明确拒绝旧 conversation，则向上层返回可区分错误，必要时允许客户端新开线程重试。

## Decision (ADR-lite)

**Context**: 需要实现“像 GPT 网页一样持续对话”的能力，同时把改动风险控制在当前文本链路可承受范围内。仓库当前还没有完整 thread store，也未切到 `f/conversation` 文本协议。  
**Decision**: MVP 选择“最小线程层”方案：保留当前 `/backend-api/conversation` 文本调用方式，新增服务端 thread store，并在线程路径中增加输入/输出双向敏感审查。  
**Consequences**: 实现速度更快、兼容性风险更低；但若后续发现旧 conversation 端点在线程复用上不稳定，第二阶段仍需升级到 `f/conversation/prepare + f/conversation`。

## Research Notes

### What similar tools do

* `432539/gpt2api` 的持续对话通过保存上游 `ConvID + ParentMsgID` 实现，而不是只拼接历史文本。
* 该项目的更完整文本链路已切到 `f/conversation/prepare` + `f/conversation`，以贴近真实网页文本请求。

### Constraints from our repo/project

* 当前文本链路已在线上使用，不能直接破坏 `/v1/chat/completions`、`/v1/responses`、`/v1/messages` 的现有合同。
* 当前仓库已有敏感词配置和拦截 helper，优先复用，避免并行两套规则。
* 当前仓库有 JSON 文件持久化先例，但尚未存在通用 conversation/thread store。

### Feasible approaches here

**Approach A: 最小线程层**（Recommended）

* How it works:
  * 保持现有 `/backend-api/conversation` 文本调用方式。
  * 新增 thread store，保存 `thread_id -> conversation_id + parent_message_id(+ metadata)`。
  * 请求带 `thread_id` 时复用线程；不带时保持当前无状态模式。
* Pros:
  * 改动最小，能快速验证“持续对话 + 审查”这条主链路。
  * 风险主要局限在文本后端与新 store。
* Cons:
  * 如果旧 conversation 端点对复用支持不稳定，后续还要再升级协议。

**Approach B: 直接升级为网页式 f/conversation 线程**

* How it works:
  * 参考 `gpt2api`，切到 `f/conversation/prepare` + `f/conversation`，同时维护 `conversation_id + parent_message_id`。
* Pros:
  * 更贴近网页真实行为，长期更稳，后续扩展性更好。
* Cons:
  * 一次性改动更大，需要补更多 transport / SSE / retry 测试。

**Approach C: 仅在服务层拼接历史文本**

* How it works:
  * 不维护上游会话，只在服务层保存历史消息并每轮重拼 prompt。
* Pros:
  * 实现最简单。
* Cons:
  * 不符合“像网页一样一直对话”的目标，也最容易引入历史漂移和提示词膨胀问题。

## Out of Scope (explicit)

* 导入 GPT 网页已有历史对话
* 新建完整聊天前端页面或管理后台 UI
* 首次迭代就把完整对话历史持久化为可审计档案或后端线程列表 API
* 首次迭代就支持工具调用、附件、富媒体审计
* 首次迭代就替换全部文本链路到全新的上游协议

## Technical Notes

* 相关实现文件：
  * `services/text_backend.py`
  * `services/chatgpt_service.py`
  * `services/api.py`
  * `services/image_history_service.py`
  * `services/config.py`
* 现有敏感词入口：
  * `services/chatgpt_service.py:_enforce_sensitive_word_filter`
  * `services/api.py` 图片入口也会走 `ensure_prompt_not_blocked`
* 当前缺口：
  * SSE 解析没有提取 assistant message id / next parent id
  * 响应未向客户端暴露 thread 概念
  * 无 thread store / thread lifecycle 管理
