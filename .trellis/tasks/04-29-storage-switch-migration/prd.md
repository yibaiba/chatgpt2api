# storage 切换自动迁移 PRD

## 背景

系统支持 `json` 和 `sqlite` 两种 accounts storage backend。管理员可通过设置页（`POST /api/settings`）切换后端。切换时需保证数据完整性，失败时需回滚，避免数据丢失。

## 目标

管理员切换 accounts storage backend/path 时：
1. 旧 store 的 accounts 自动迁移到新 store，再切 runtime binding
2. 若迁移或 runtime rebind 失败，config、runtime binding 与目标端数据状态回滚到安全状态
3. env 变量 override 时，拒绝冲突的 storage 变更请求

## 实现状态（已完成）

### 核心逻辑

- `services/api.py` → `_apply_account_storage_change(previous_config)`
  - 比较切换前后的 `(backend, path)` target
  - 无变化：直接 `rebind_store`
  - 有变化：备份目标端现有数据 → `migrate_accounts(src, dst)` → `rebind_store(dst)`
  - 失败时：恢复目标端备份数据，重新 raise 原异常
  - 目标端 rollback 也失败时：raise `RuntimeError` 带两层错误信息

- `services/api.py` → `_sanitize_storage_settings_update(body)`
  - env override 活跃时，拒绝与 override 冲突的 storage 字段变更（HTTP 400）
  - 允许"无效变更"（设的值与当前生效值相同）静默通过

- `POST /api/settings` 已接入以上逻辑（`settings_update` endpoint 约第 882-908 行）

### 存储层

- `services/storage/migrate.py` → `migrate_accounts(source, destination)` — 简单三行
- `services/storage/factory.py` → `build_account_store_for_backend()`, `get_account_storage_info()`
- `services/storage/json_storage.py`, `sqlite_storage.py` — backends

## 验收标准（全部通过）

| 测试 | 状态 |
|------|------|
| 管理员可获取 storage info | ✅ |
| 非管理员无权获取 storage info | ✅ |
| 切换 backend 自动迁移数据 + rebind | ✅ |
| 不支持的 backend 返回 400 | ✅ |
| rebind 失败时回滚目标端数据 + 回滚 config | ✅ |
| env path override 活跃时拒绝切换 | ✅ |
| env backend override 活跃时允许写无冲突字段 | ✅ |
| 仅 backend override 活跃时允许写 sqlite_path | ✅ |
| destination rollback 失败时 surface 双层错误 | ✅ |

测试文件：`test/test_storage_api.py`（9 passed）
