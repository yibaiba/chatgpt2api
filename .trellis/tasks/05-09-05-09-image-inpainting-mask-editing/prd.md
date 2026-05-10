# PRD — 图片遮罩局部编辑 (Inpainting)

## 背景

用户在生成图片后，希望对图片特定区域进行局部修改（例如换背景、改人物、去除元素），而不是重新生成整张图。

通过 HAR 分析，ChatGPT 官方实现了基于 `picture_v2` conversation 的 inpainting 流程，关键是在 conversation metadata 中传递 `dalle.from_client.operation`。

---

## HAR 分析结论

### 流程（纯遮罩模式）

1. `POST /backend-api/files`  
   ```json
   { "file_name": "mask.png", "file_size": 36079, "use_case": "dalle_agent" }
   ```
   → 返回 `file_id`（`file-xxx` 格式）和 `upload_url`

2. `PUT <upload_url>` — 上传 mask PNG 二进制

3. `POST /backend-api/files/process_upload_stream`  
   ```json
   { "file_id": "file-xxx", "use_case": "dalle_agent", "index_for_retrieval": false, "file_name": "mask.png" }
   ```
   ⚠️ 无 `entry_surface` 字段（与 multimodal 上传不同）

4. `POST /backend-api/f/conversation`  
   ```json
   {
     "model": "auto",
     "system_hints": ["picture_v2"],
     "messages": [{
       "content": { "content_type": "text", "parts": ["这里的人改成票"] },
       "metadata": {
         "system_hints": ["picture_v2"],
         "dalle": {
           "from_client": {
             "operation": {
               "type": "inpainting",
               "original_file_id": "file_000...",   // 原始生成图的 file_id
               "mask_file_id": "file-NQcM...",        // dalle_agent 上传的 mask file_id
               "original_gen_id": "42db3ad5-..."       // 原图的生成 UUID
             }
           }
         }
       }
     }]
   }
   ```

### 流程（遮罩 + 参考图模式）

与上面一致，但 conversation content 为 `multimodal_text`，包含参考图的 `image_asset_pointer` part，且参考图用 `use_case: "multimodal"` 上传。

---

## 功能需求

### 后端

| 需求 | 描述 |
|------|------|
| B1 | 新增 `_upload_mask()` 函数，使用 `use_case: "dalle_agent"`，无 `entry_surface` |
| B2 | 新增 `_build_inpaint_conversation_payload()` 构建含 `dalle.from_client.operation` 的对话 payload |
| B3 | 新增 `inpaint_image_result()` 主流程函数：上传原图 + 上传 mask → 发对话 → 拉取结果 |
| B4 | 在 `/v1/images/edits` 或新增 `/v1/images/edits/inpaint` 端点，接受 `mask` 文件和可选 `original_gen_id` |
| B5 | 若调用方未提供 `original_gen_id`，后端自动生成 UUID 填充 |

### 前端

| 需求 | 描述 |
|------|------|
| F1 | 新增 `MaskEditorDialog` 组件：显示原始图片 + Canvas 画布叠加层 |
| F2 | 画笔工具：白色笔刷（可调大小）绘制遮罩区域，橡皮擦清除 |
| F3 | Canvas 导出为 mask PNG（遮罩区白色，其余黑色） |
| F4 | 在图片结果卡片（`image-results.tsx`）上添加"遮罩编辑"按钮/图标 |
| F5 | 遮罩确认后弹出 prompt 输入，组合调用 `/v1/images/edits` 接口（含 mask 文件） |
| F6 | 支持可选参考图上传（在 MaskEditorDialog 内） |

---

## API 设计

### 方案：扩展 `/v1/images/edits`

在现有 `/v1/images/edits` 端点中新增可选 `mask` 字段：

```
POST /v1/images/edits
Content-Type: multipart/form-data

image:           <original image file>
mask:            <mask PNG file, optional>
prompt:          <string>
model:           <string>
response_format: <string>
original_gen_id: <string, optional, UUID>
```

当 `mask` 存在时，走 inpainting 流程；否则走现有编辑流程。

---

## 数据流

```
前端用户
  │
  ├─ 点击图片上的"遮罩编辑"图标
  ├─ MaskEditorDialog 打开（显示原图 + canvas 叠层）
  ├─ 用白色笔刷绘制遮罩
  ├─ 输入 prompt
  ├─ 点击"生成"
  │
  └─ POST /v1/images/edits
       ├─ image=原始图片
       ├─ mask=canvas导出PNG
       └─ prompt=...
           │
           └─ [backend] inpaint_image_result()
                ├─ _upload_image(原图, multimodal) → original_file_id
                ├─ _upload_mask(mask, dalle_agent)  → mask_file_id
                ├─ original_gen_id = uuid4()
                ├─ _build_inpaint_conversation_payload(...)
                └─ _send_conversation() → 拉取生成图 → 返回
```

---

## 关键实现细节

### mask 上传的差异

| 字段 | 普通图片上传 | mask 上传 |
|------|------------|----------|
| `use_case` | `multimodal` | `dalle_agent` |
| `entry_surface` | `chat_composer` | **不传** |
| 返回 file_id 格式 | `file_000...`（长） | `file-xxx`（短） |

### conversation payload 关键字段

```python
{
    "content_type": "text",   # 纯遮罩时用 text
    "parts": [prompt],
}
# metadata 中:
"dalle": {
    "from_client": {
        "operation": {
            "type": "inpainting",
            "original_file_id": original_file_id,  # 原图上传后的 file_id
            "mask_file_id": mask_file_id,           # dalle_agent 上传的 mask file_id
            "original_gen_id": str(uuid.uuid4()),   # 可任意 UUID
        }
    }
}
```

---

## 验收标准

- [ ] 用户能在图片结果上进入遮罩画笔模式
- [ ] 白色笔刷绘制区域 → 后端收到正确格式的 mask PNG
- [ ] 后端成功调用 inpainting 流程并返回编辑后图片
- [ ] 支持调整笔刷大小、清除遮罩
- [ ] 可选参考图上传正常工作

---

## 受影响文件

**后端**
- `services/image_service.py` — 核心改动
- `services/api.py` — `/v1/images/edits` 端点扩展

**前端**
- `web/src/app/image/components/image-results.tsx` — 添加遮罩入口
- `web/src/app/image/components/` — 新增 `mask-editor-dialog.tsx`
- `web/src/app/image/page.tsx` — 集成 MaskEditor 状态
- `web/src/lib/api.ts` — 可能需要新增 inpaint 调用函数
