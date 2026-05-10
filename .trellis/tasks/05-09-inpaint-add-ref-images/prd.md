# PRD: 遮罩编辑对话框支持上传参考图

## 背景

遮罩编辑（inpaint）功能已经正常工作。后端 `createImageInpaintJob` API 已支持 `refImages: File[]` 参数，后端服务 `_build_inpaint_picture_v2_body` 有参考图时会把原图 + 参考图 + prompt 一起放进 content。但前端 `MaskEditorDialog` 没有参考图上传入口，导致该能力无法被用户使用。

## 目标

在遮罩编辑对话框中增加"参考图"上传功能，让用户能在涂抹遮罩 + 输入 prompt 的同时，附上一张或多张参考图来指导生成风格。

## 影响范围

| 文件 | 改动 |
|------|------|
| `web/src/app/image/components/mask-editor-dialog.tsx` | 添加参考图上传 UI，onSubmit 类型增加 refImages |
| `web/src/app/image/page.tsx` | handleMaskEditorSubmit 接收 refImages 并传给 createImageInpaintJob |

后端不需要改动。

## 功能需求

1. **参考图上传区**
   - 位置：prompt 输入框上方（或工具栏下方单独一行）
   - 支持点击选择文件（accept image/*）
   - 支持多张（最多 4 张，和图像编辑一致）
   - 已选参考图以缩略图形式展示，支持单独删除

2. **回调签名变更**
   - `onSubmit: (maskFile: File, prompt: string, refImages: File[]) => void | Promise<void>`
   - refImages 为空数组时表示无参考图

3. **page.tsx 侧**
   - `handleMaskEditorSubmit` 解构新参数 `refImages`
   - 调用 `createImageInpaintJob` 时传入 `{ refImages }` options

## 验收标准

- [ ] 对话框中能选择并预览参考图
- [ ] 不选参考图时行为与现在相同
- [ ] 选参考图后请求中包含 ref_image 字段（后端已处理）
- [ ] 参考图可单张删除
