# Bug Fix Record: unit_type 验证失败 + connection 未定义 + 导航冗余

MiMoCode · 2026-07-08T19:30:00+08:00

## 问题描述

启动应用时控制台输出大量 WARNING：

1. `name 'connection' is not defined` — dashboard 加载节奏报告时触发
2. `unit_type must be one of {'reveal', 'transition', ...}` — 90+ 个 Chapter 包装为 Virtual Unit 全部失败
3. 侧边栏"项目设置"和"小说设定"指向同一页面（冗余入口）

## 根因分析

### Bug 1: pressure.py 连接未定义

`app/services/pressure.py` 中 6 处调用 `connection.get_conn()`（lines 198/210/220/232/262/272），但模块仅 import 了 `transaction`，未 import `connection` 或 `get_conn`。

### Bug 2: unit_type 双层验证失败

问题有 **两层**：

- **Python 层**：`story_unit_service_v2.py` 的 `VALID_TYPES` 集合不含 `"virtual"`，`create()` 函数校验拒绝
- **SQLite 层**：`story_units` 表的 CHECK 约束 `unit_type IN ('battle','romance',...,'other')` 也不含 `"virtual"`，即使绕过 Python 校验，DB 层也会拒绝 INSERT

`virtual_unit_adapter.py` 的 `wrap_chapter_as_virtual_unit()` 传 `unit_type="virtual"`，两层都拦截，导致 100 个 Chapter 全部包装失败。

### Bug 3: 导航双入口

`tree_nav.py` 的 `NAV_TREE` 中：
- `"project"` 分组有 `("novel-settings", "项目设置")`
- `"story"` 分组有 `("novel-settings", "小说设定")`

两个入口指向同一个 `page_id`，功能完全相同。

## 修复方案

### Fix 1: pressure.py

```python
# 修改前
from app.db._impl import transaction

# 修改后
from app.db._impl import transaction, get_conn
```

替换所有 `connection.get_conn()` → `get_conn()`（6 处）。

### Fix 2: unit_type（双层修复）

**Python 层** — `app/services/story_unit_service_v2.py`：

```python
VALID_TYPES = {
    "battle", "romance", "reveal", "transition",
    "climax", "setup", "payoff", "filler", "other",
    "virtual",  # 新增
}
```

**SQLite 层** — 新建迁移 `app/db/migrations/054_add_virtual_unit_type.sql`：

SQLite 不支持 `ALTER TABLE ... ALTER COLUMN` 修改 CHECK 约束，必须重建表：
1. CREATE TABLE story_units_new（含更新后的 CHECK）
2. INSERT ... SELECT 从旧表复制数据
3. DROP TABLE story_units
4. ALTER TABLE story_units_new RENAME TO story_units
5. 重建索引

**数据修复**：迁移后运行 `auto_wrap_all_chapters(project_id)` 包装 100 个 Chapter。

### Fix 3: 导航冗余

`tree_nav.py` — 删除 `NAV_TREE["project"]["pages"]` 中的 `("novel-settings", "项目设置")`。

## 变更文件

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `app/services/pressure.py` | 修改 | import get_conn + 替换 6 处调用 |
| `app/services/story_unit_service_v2.py` | 修改 | VALID_TYPES 添加 "virtual" |
| `app/ui/widgets/tree_nav.py` | 修改 | 删除冗余导航入口 |
| `app/db/migrations/054_add_virtual_unit_type.sql` | 新建 | SQLite CHECK 约束重建迁移 |

## 验证结果

```
rhythm_report: OK (无 NameError)
auto_wrap: 100/100 chapters wrapped
所有 WARNING 消失
```

## 经验教训

- **SQLite CHECK 约束是隐性约束**：修改 `unit_type` 合法值时，必须同时修改 Python 验证和 DB CHECK 约束，后者需要重建表
- **迁移编号**：054 已用，后续迁移需用 055+
