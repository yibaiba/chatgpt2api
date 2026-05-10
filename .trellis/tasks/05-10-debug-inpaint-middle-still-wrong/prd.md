# debug inpaint middle still wrong

## Goal

继续定位并修复用户最新一次 inpaint 结果里“中间还是不对”的问题。已知最新结果不再命中 same-size patch-canvas 分支，而是命中 same-size full-frame，因此本轮需要验证：是上游 raw 图本身在遮罩区内容就已经错位/放大，还是当前 same-size full-frame 的合成判定仍把一种“伪 full-frame”结果误当成整图结果处理。

## What I already know

* 关键控制路径在 [services/image_service.py](services/image_service.py) 的 `_composite_inpaint_onto_original(...)` 与 `_build_same_size_effective_mask(...)`。
* 上一轮已经修复 same-size patch-canvas + 占位底误合成问题，并完成窄测试验证。
* 本轮最新日志显示：
  * `uploaded original_file_id=file_00000000ed38720cb5d890501f18c625 size=941x1672`
  * `uploaded mask_file_id=file-BWk5UE2yT2Ayci4iJnBKZE`
  * `found 1 image(s) after 42s`
  * `target=941x1672 candidates=[sed:file_000...=941x1672] chosen=sed:file_000...=941x1672`
  * `[image-inpaint-compose] raw=941x1672 target=941x1672 mode=full-frame box=(323, 92, 644, 416)`
* 服务重启后，内存态 `/api/image-jobs/<id>` 已失效，当前不能直接从 job API 读取该次结果详情。
* 浏览器本地 localStorage 目前没有保存这次历史；`data/image_history.json` 里只有一条 inpaint 持久化验证样例，不包含这次真实 case。

## Assumptions (temporary)

* 当前问题更可能出在 same-size full-frame 判定过宽，而不是上一轮修复的 patch-canvas 过滤逻辑回退。
* 如果最新 raw 输出在遮罩外仍保留大量原图结构，但遮罩内主体形变明显，则可能需要为 same-size 返回新增“局部 patch 但非浅灰占位底”的识别逻辑。
* 如果 raw 输出本身就是完整重绘整图，则当前合成仅按 mask 贴回，中心不对更接近上游生成结果本身，而不是回贴几何错误。

## Open Questions

* 这次 latest raw output 在遮罩外区域与原图的差异比例是多少？
* same-size raw output 是否存在另一类非 placeholder 的 patch-canvas / framed canvas，需要在 full-frame 之前分流？
* 用户所说“中间不对”在视觉上更像位置/尺度错误，还是模型内容生成错误？

## Requirements (evolving)

* 基于最新真实 case 的日志与图像证据定位 same-size full-frame 分支中的剩余问题。
* 修改必须从实际控制行为的 helper 或分流条件入手，不重新大改整个 inpaint 流程。
* 保持上一轮 same-size patch-canvas 修复与已有 candidate-selection 行为不回退。
* 若新增判断逻辑，补最小回归测试覆盖该类 same-size case。

## Acceptance Criteria (evolving)

* [ ] 能说明这次“中间不对”对应的是哪一种 same-size 返回类型。
* [ ] 修复后，最新 same-size case 不再错误走 full-frame 或错误缩放回贴。
* [ ] 增加或更新针对该 same-size 分支的最小回归测试。
* [ ] 至少完成一项可执行验证：真实探针、针对性 pytest、或本地复现日志验证。

## Definition of Done (team quality bar)

* Tests added or updated for changed behavior.
* Relevant validation command executed and reported honestly.
* New non-obvious same-size inpaint rule captured in repo notes/spec if confirmed.

## Out of Scope (explicit)

* 不重做前端 mask 编辑器。
* 不处理和本次 same-size inpaint 误判无关的历史静态告警。
* 不顺手修 image history 的独立产品问题，除非它直接阻断本次定位。

## Technical Notes

* 目标文件：`services/image_service.py`
* 相关测试：`test/test_image_model_routing.py`
* 最新真实日志锚点：`logs/uvicorn.log` 中 job `5484ca5d5d5b438db56f426635325259`
* 当前已知 upstream conversation 前缀：`69ffe211...`