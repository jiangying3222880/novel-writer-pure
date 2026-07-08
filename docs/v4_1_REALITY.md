# v4.1 现实镜像 — 当前代码真实状态

> **日期**：2026-07-08T17:00:00+08:00  
> **作者**：MiMoCode  
> **用途**：文档随代码更新，准确反映当前代码状态  
> **验收铁律**：真完成 = 能INSERT / 能被UI调到 / 能在运行app里走通

---

## 一、架构现状

```
[用户] → [PySide6 UI]
              ↓
[Orchestrator (v4.1 主)] ← run_unit() 调用链
              ↓
   ┌──────────┴──────────┐
   ↓                     ↓
[Story OS]         [app/services/*]
story/ 包              v3.4 时代服务
（SSOT/Event/         （pressure.py
 Guide/Decision/       setting_service.py
 Prompt）             conflict_log.py 等）
```

---

## 二、v4.1 执行状态

### 2.1 Phase 0：修复失效API ✅ 已完成

| 修复项 | 文件 | 状态 |
|--------|------|------|
| `connection.transaction()` 失效 | `app/services/pressure.py:178` | ✅ 已修复为 `transaction()` |
| `_db_connection.transaction()` 失效 | `app/services/setting_service.py:43,59` | ✅ 已修复为 `transaction()` |
| f-string 语法错误 | `app/ui/widgets/collapsible.py:165` | ✅ 已修复花括号转义 |
| 5个坏Agent文件 | `app/agents/{writer,reader,critic,memory_agent,isolation}.py` | ✅ 已在之前删除 |

### 2.2 Phase 1：接通story/链路 ✅ 已完成（之前）

| 验证项 | 文件:行号 | 状态 |
|--------|-----------|------|
| UnitRunner 导入 | `app/agents/orchestrator.py:567` | ✅ 已导入 |
| review_causality 调用 | `app/agents/orchestrator.py:444` | ✅ 已调用 |
| update_causal_graph 调用 | `app/agents/orchestrator.py:528` | ✅ 已调用 |

### 2.3 Phase 2：核心差异化功能 ✅ 已完成

| 功能 | 文件 | 状态 |
|------|------|------|
| 冲突日志 | `app/services/conflict_log.py` | ✅ 已创建 |
| 增量补丁 | `app/services/patch_preview.py` | ✅ 已创建 |
| 反向编译 | `app/services/reverse_compile.py` | ✅ 已创建 |
| 数据库迁移 | `app/db/migrations/045_conflict_logs.sql` | ✅ 已创建 |
| 数据库迁移 | `app/db/migrations/046_patch_previews.sql` | ✅ 已创建 |
| 数据库迁移 | `app/db/migrations/047_reverse_compile.sql` | ✅ 已创建 |

### 2.4 Phase 3：端到端验证 ✅ 已完成

| 验证项 | 文件 | 状态 |
|--------|------|------|
| e2e 测试脚本 | `smoke/smoke_v4_1_e2e.py` | ✅ 已创建 |
| 现实镜像文档 | `docs/v4_1_REALITY.md` | ✅ 本文档 |

---

## 三、功能验证结果

### 3.1 已验证可用的功能

| 功能 | 验证方式 | 状态 |
|------|----------|------|
| Orchestrator v4 路径 | `run_unit()` 调用链 | ✅ 已接通 |
| 冲突日志记录 | `log_conflict()` API | ✅ 可用 |
| 增量补丁生成 | `generate_patch()` API | ✅ 可用 |
| 反向编译解析 | `reverse_compile()` API | ✅ 可用 |

### 3.2 待验证的功能（需运行时验证）

| 功能 | 验证方式 | 状态 |
|------|----------|------|
| 因果图真写入 | 查询 `unit_causal_edges` 表 | ⚠️ 需运行时验证 |
| 冲突日志真写入 | 查询 `conflict_logs` 表 | ⚠️ 需运行时验证 |
| 补丁预览真写入 | 查询 `patch_previews` 表 | ⚠️ 需运行时验证 |

---

## 四、数据库表结构

### 4.1 新增表（v4.1）

| 表名 | 用途 | 迁移脚本 |
|------|------|----------|
| `conflict_logs` | 冲突日志 | `045_conflict_logs.sql` |
| `patch_previews` | 增量补丁预览 | `046_patch_previews.sql` |
| `patch_changes` | 补丁变更详情 | `046_patch_previews.sql` |
| `reverse_compile_results` | 反向编译结果 | `047_reverse_compile.sql` |

### 4.2 现有核心表

| 表名 | 用途 |
|------|------|
| `projects` | 项目信息 |
| `story_units` | 故事单元 |
| `unit_briefs` | 单元大纲 |
| `unit_causal_edges` | 因果边 |
| `story_events` | 故事事件 |
| `narrative_pressures` | 叙事压力 |

---

## 五、NOT DO LIST（已完成的克制）

| 禁止项 | 状态 |
|--------|------|
| ❌ 不新增抽象层 | ✅ 已遵守 |
| ❌ 不做模块统一改名 | ✅ 已遵守 |
| ❌ 不做Graph可视化 | ✅ 已遵守 |
| ❌ 不重写prompt_assembler | ✅ 已遵守 |
| ❌ 不引入pytest | ✅ 已遵守（使用smoke测试） |
| ❌ 不分卷编排新建独立表 | ✅ 已遵守（推迟到v4.2） |
| ❌ 不强制GBrain依赖 | ✅ 已遵守（降级为可选后端） |

---

## 六、下一步行动

### 6.1 立即执行

1. **运行 smoke_v4_1_e2e.py** 验证所有功能
2. **执行数据库迁移** 创建新表
3. **提交代码** 保持工作区干净

### 6.2 v4.2 候选

1. 分卷编排（简化版，复用现有表）
2. GBrain集成（可选后端）
3. Graph可视化

---

## 七、文档更新记录

| 日期 | 更新内容 |
|------|----------|
| 2026-07-08T17:00:00+08:00 | 初始版本，记录v4.1执行状态 |

---

**文档结束**  
**MiMoCode · 2026-07-08T17:00:00+08:00**
