# PRD: 移除 inpaint 合成层，仅做等比缩放

## 背景

当前 `inpaint_image_result` 存在以下逻辑：
1. 上传前：`_preprocess_inpaint_inputs` 将原图+mask 等比缩小至 1792px
2. 下载后：`_composite_inpaint_onto_original` 用 mask alpha 将 AI 结果手动叠合到原图
3. 然后：若缩小过，LANCZOS 放大回原始分辨率

**假设验证**：ChatGPT inpaint API 在输入图正确缩放后（≤ 1792px），应该直接返回完整合成图（AI 重绘区 + 原图其他区域），不需要我们在后端做合成。我们现有的手动合成步骤反而可能切断 AI 在遮罩边缘做的平滑过渡，导致边缘割裂感。

**前端确认**：mask-editor-dialog.tsx 中 canvas.width = img.naturalWidth，说明 mask 与原图分辨率完全一致，无 Canvas 缩放问题。

## 目标

移除 `_composite_inpaint_onto_original` 调用，改为：
1. 上传前：等比缩小原图+mask 至 1792px（已实现，保留）
2. 下载后：直接拿 API 返回结果
3. 若原图被缩小过：LANCZOS 等比放大回原始分辨率

## 验收标准

- [ ] 测试：小图（≤ 1792px）inpaint 正常，非遮罩区完整
- [ ] 测试：大图（> 1792px，如海贼王图）inpaint 正常，非遮罩区完整
- [ ] 对比：边缘融合效果优于或等于手动合成版本

## 风险

如果 API 确实只返回遮罩区（非完整图），移除合成后会出现"只剩被涂抹部分"问题。需要有回滚方案。

## 实现方案

1. 在 `inpaint_image_result` 中，下载 `raw_inpaint_bytes` 后直接用，不调用 `_composite_inpaint_onto_original`
2. 保留 `_preprocess_inpaint_inputs`（等比缩放逻辑）
3. 保留放大回原始分辨率逻辑
4. `_composite_inpaint_onto_original` 函数保留但注释掉（方便回滚）

## 范围外

- 不修改前端 mask 导出格式
- 不修改 API 请求格式
