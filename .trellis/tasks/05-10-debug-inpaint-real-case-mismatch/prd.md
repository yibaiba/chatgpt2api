# debug inpaint real-case mismatch

## Goal

修复 inpaint 在用户真实案例中的错误合成结果。当前已经完成“多候选输出择优下载”修复，但用户反馈最新一次真实出图仍然不对，因此需要基于真实页面结果和后端日志继续定位根因，确认问题是候选选择仍不足、还是上游只返回了单张但内容本身已经偏离原图。

## What I already know

* 主要逻辑位于 services/image_service.py。
* 当前实现会对多个 output file candidate 按 exact size、aspect ratio、area、dimension 误差排序后择优。
* 已有回归测试覆盖 candidate score 与 selection。
* 真实控制实验中，遮罩外区域保持原图不变。
* 用户最新反馈是：在真实问题图上结果“还是不对”。
* 浏览器当前已登录并停留在 /image/ 页面，可直接查看真实结果。

## Assumptions (temporary)

* 当前问题更可能出在“真实案例的上游返回内容”而不是前端遮罩导出。
* 若日志显示只有一个候选输出，则 file selection 不是这次错误的主因。
* 若日志显示有多个候选输出但选中的尺寸或比例不合理，则仍需调整 candidate selection 规则。

## Open Questions

* 这次真实案例的最新日志里，image-inpaint-candidates 实际有哪些候选，最终选中了哪一个？
* 如果只返回单个候选，返回图本身是 full-frame variant 还是局部 patch？

## Requirements (evolving)

* 基于真实页面结果和服务日志定位当前错误路径。
* 修复逻辑必须尽量限制在控制实际行为的代码路径上。
* 保持遮罩外区域与原图一致。
* 若修复涉及行为变化，补充回归测试。

## Acceptance Criteria (evolving)

* [ ] 能说明本次真实案例为什么仍然错误。
* [ ] 修复后，真实案例结果不再出现明显比例/位置错误。
* [ ] 针对新增根因补充最小回归测试。
* [ ] 至少完成一项可执行验证（测试、真实探针或真实页面复现）。

## Definition of Done (team quality bar)

* Tests added or updated for changed behavior.
* Relevant validation command executed and reported honestly.
* Notes updated if a new non-obvious rule is discovered.

## Out of Scope (explicit)

* 不重做整套前端遮罩编辑器。
* 不处理与当前 inpaint 真实案例无关的历史脏工作树改动。

## Technical Notes

* 目标文件：services/image_service.py
* 相关测试：test/test_image_model_routing.py
* 调试产物目录：data/debug_inpaint_probe/
* 浏览器页面：/image/