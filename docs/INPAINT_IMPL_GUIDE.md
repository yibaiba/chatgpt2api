# Inpaint Implementation Guide

本文档说明 inpaint（图片编辑）特性的实现细节、关键决策和故障排查指南。

## 特性概览

Inpaint 允许用户上传一张图片和编辑掩码，获得编辑后的图片。系统通过以下流程实现：

1. **上下文保持** - 尽可能复用用户的前一次生成对话
2. **Bootstrap 策略** - 如果前一次对话无效，启动新对话并上传原图建立上下文
3. **轮询等待** - 上游模型异步执行编辑任务，系统智能轮询并忽略中间澄清文本
4. **本地合成** - 编辑完成后，通过三分支启发式算法将编辑结果合成到原图

## 工作流详解

### 第一阶段：API 接收与路由

**文件**: `services/api.py` (Line 870)

```python
@router.post("/v1/images/edits")
async def edit_images(
    image: UploadFile,
    mask: UploadFile | None = None,
    prompt: str = Form(...),
    conversation_id: str | None = Form(default=None),
    parent_message_id: str | None = Form(default=None),
    ...
):
    result = await run_in_threadpool(
        chatgpt_service.inpaint_with_pool,
        ...,
        conversation_id=str(conversation_id or ""),
        parent_message_id=str(parent_message_id or "")
    )
```

**关键点**:
- 直接接受 `conversation_id` 和 `parent_message_id` 作为 Form 参数
- 转换为字符串并传给服务层，不做任何过滤或修改

### 第二阶段：账户池编排与重试

**文件**: `services/chatgpt_service.py` (Line 1006)

```python
def inpaint_with_pool(
    ...,
    conversation_id: str = "",
    parent_message_id: str = ""
):
    requested_conversation_id = str(conversation_id or "").strip()
    requested_parent_message_id = str(parent_message_id or "").strip()
    
    # 第一次尝试：用上下文进行编辑
    try:
        result = inpaint_image_result(
            account=account,
            ...,
            conversation_id=requested_conversation_id,
            parent_message_id=requested_parent_message_id
        )
        return result
    except Exception as exc:
        # 若遇到 404（对话无效），改用 bootstrap 重试
        if is_conversation_forbidden_error(str(exc)):
            result = inpaint_image_result(
                account=account,
                ...,
                conversation_id="",
                parent_message_id=""
            )
            return result
        raise
```

**关键决策**:
- **为什么不清空对话ID?** 早期实现为了避免跨账户 404 而清空 ID，但这导致模型无法理解编辑意图，倒不如主动尝试并优雅降级
- **重试策略** - 同账户、同轮询逻辑，只改变对话上下文参数
- **不涉及账户切换** - 保持同一账户在两次尝试上，避免引入额外变量

### 第三阶段：图片服务编排

**文件**: `services/image_service.py` (Line 3119)

#### 子阶段 3.1：预处理与 Bootstrap

```python
def inpaint_image_result(...):
    # 预处理：限制最大尺寸 1792px，同比例缩放原图和掩码
    max_dim = 1792
    orig_w, orig_h = original_image.size
    if orig_w > max_dim or orig_h > max_dim:
        scale = max_dim / max(orig_w, orig_h)
        ...
    
    # Bootstrap：如果没有对话，先上传原图建立对话上下文
    if not conversation_id:
        conversation_id, parent_message_id = bootstrap_with_original_image(...)
        log("[image-inpaint-bootstrap] conv=%s... last_msg=%s...", 
            conversation_id[:8], parent_message_id[:8])
```

**为什么需要 Bootstrap?**
- 纯粹的 inpaint 请求（无历史）需要上游模型知道"这是原图，这是掩码，我想编辑这个区域"
- 上传原图作为"参考"让模型建立空间理解，显著提高编辑成功率

#### 子阶段 3.2：智能轮询

```python
def poll_for_image_result(...):
    for poll_count in range(max_polls):
        response = get_next_message(conversation_id, parent_message_id)
        
        if has_image_files(response):
            # 找到图片，返回
            return extract_images(response)
        
        if is_async_task_text(response):
            # "Got it! I can help you edit this image. Could you clarify..."
            # 这表示上游有异步 DALL-E 任务在进行中
            log("[poll-image] ... async DALL-E task in progress, ignore text, keep polling...")
            continue
        
        if is_error_text(response):
            # 真实错误（如模型拒绝、模型不可用等）
            raise PollError(response)
```

**关键启发式算法**:

```python
def is_async_task_text(text):
    """检测是否是异步任务进行中的标准澄清文本"""
    return (
        "Got it!" in text and 
        "clarify" in text and
        "edits" in text
    )
```

**为什么不能直接返回澄清文本？**
- 早期实现看到这个文本就立即返回，导致 API 层面看到文本而不是图片
- 实际上这表示上游有异步 DALL-E 任务在执行，需要继续轮询
- 通过异步任务 ID 识别（`async=True` 在 SSE 流）可进一步确认

#### 子阶段 3.3：候选选择

```python
def inpaint_image_result(...):
    # 轮询完后收集候选
    candidates = poll_for_image_result(...)
    
    # 选择最接近目标尺寸的
    best = select_best_candidate(
        candidates,
        target_size=(preprocessed_w, preprocessed_h)
    )
    
    log("[image-inpaint-candidates] target=%sx%s candidates=[%s] chosen=%s",
        preprocessed_w, preprocessed_h,
        ", ".join(c.size_str for c in candidates),
        best.size_str)
```

**选择标准**:
1. 优先选择与目标尺寸完全匹配的
2. 其次选择面积最接近的
3. 避免选择过小（< 50% 目标）或过大（> 200% 目标）的候选

#### 子阶段 3.4：本地合成

```python
inpaint_img_rgba = best_candidate.convert("RGBA")
original_rgba = original_image.convert("RGBA")

# 应用掩码：创建复合掩码
composite_mask = Image.new("L", target_size, 0)
mask_pil_l = mask_image.convert("L")
composite_mask.paste(mask_pil_l, (0, 0))

# 合成
composited = Image.composite(inpaint_img_rgba, original_rgba, composite_mask)
```

**三分支合成启发式**:

见 `_composite_inpaint_onto_original()` (Line 2400)：

| 返回形状 | 条件 | 处理方式 |
|---------|------|---------|
| **同尺寸** | `inpaint_img.size == target_size` | 直接覆盖掩码区域 |
| **全幅变体** | 面积 0.72-1.45x 目标，掩码覆盖 >= 35%，外部像素差 <= 12.0 | 通过 `scale_to_fill` 等比缩放至目标，中心裁剪，再覆盖 |
| **补丁** | 其他 | 投影到透明画布指定位置 |

**为什么需要三分支？**
- ChatGPT/DALL-E 返回行为不一致：有时返回补丁、有时返回全图变体、有时返回完整尺寸
- 不同返回需要不同处理才能正确合成到原图
- 本地合成层完全屏蔽上游不一致性

### 第四阶段：响应返回

最终编辑结果返回给前端，格式为：
- `b64_json` - Base64 编码的 PNG 数据
- `url` - 下载 URL（可选）

## 故障排查

### 症状 1：返回澄清文本而非图片

**可能原因**:
1. 轮询超时 - 上游任务耗时过长，轮询次数不足
2. 没有 Bootstrap - 编辑没有上下文，模型不理解意图

**检查日志**:
```
[poll-image] ... async DALL-E task in progress, ignore text, keep polling...
[poll-image] ... found 0 image(s) after 60s (20 polls)
```
→ 超过 60s 仍未找到图片，可能需要增加轮询超时或增加轮询次数

### 症状 2：404 错误

**可能原因**:
1. 对话 ID 已过期（超过 30 天或账户刷新）
2. 账户更新后对话 ID 失效

**检查日志**:
```
[image-inpaint-upstream] conversation_id=6a012cd0... → 404 Not Found
[image-inpaint-upstream] falling back to bootstrap...
```
→ 正常，系统自动降级到 bootstrap

### 症状 3：生成速度慢

**可能原因**:
1. 轮询间隔太长（默认 3-4s）
2. 上游任务本身耗时

**优化方向**:
```python
# 当前轮询间隔
time.sleep(4)  

# 建议：前 3 次快速轮询，后续放缓
if poll_count < 3:
    time.sleep(1)
else:
    time.sleep(4)
```

## 关键参数

| 参数 | 当前值 | 说明 |
|------|--------|------|
| `max_polls` | 20 | 最多轮询次数 |
| `poll_interval` | 3-4s | 轮询间隔 |
| `max_dim` | 1792 | 上传到上游的最大尺寸 |
| `alpha_threshold` | 128 | 掩码 alpha 通道判定阈值 |
| `pixel_diff_threshold` | 12.0 | 全幅检测时的像素差阈值 |

## 测试覆盖

核心测试用例位于:

- `test/test_image_edits_api.py` - API 层
  - `test_inpaint_job_forwards_conversation_id()` - 上下文转发
  - `test_inpaint_includes_mask_in_request()` - 掩码包含

- `test/test_image_model_routing.py` - 服务层
  - `test_inpaint_with_pool_reuses_existing_conversation_context()` - 上下文复用
  - `test_inpaint_with_pool_falls_back_without_conversation_context_on_404()` - 降级重试

运行:
```bash
pytest test/test_image_edits_api.py test/test_image_model_routing.py -v
```

## 最佳实践

1. **前端应传递上下文** - 当从前一次生成继续编辑时，始终传递 `conversation_id` 和 `parent_message_id`
2. **允许充足轮询时间** - Inpaint 通常需要 20-60s，前端应设置合理超时
3. **监控日志** - 通过日志中的 `[poll-image]` 和 `[image-inpaint-]` 前缀快速定位问题
4. **缓存成功编辑** - 编辑成功后将对话 ID 缓存，允许用户快速迭代编辑

## 相关代码文件

- `services/api.py` - HTTP 接收与路由
- `services/chatgpt_service.py` - 账户池与重试编排
- `services/image_service.py` - 轮询、合成与返回处理
- `services/auth_security.py` - 认证与授权
- `test/test_image_edits_api.py` - API 层测试
- `test/test_image_model_routing.py` - 服务层测试
