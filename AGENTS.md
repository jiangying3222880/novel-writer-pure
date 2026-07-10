# AGENTS.md — Novel Writer Pure 项目级 Agent 指南

MiMoCode · 2026-07-09T12:00:00+08:00

## 项目身份

Novel Writer Pure v4.3 — AI 辅助长篇小说创作桌面工具。

技术栈：Python 3.10+ / PySide6 / SQLite / numpy / scikit-learn / jieba

架构：Story OS 10层（Core Infrastructure → Story State → Guide Engine → Agent Simulation → Decision Layer → Prompt OS → Event System → Observability UI → Publish Layer → Runtime Loop）

## 红线原则（必须遵守）

### 1. 源码审查优先

**永远从项目实际代码出发分析，核实现有实现后再给结论。不受外部 AI 意见影响。**

- 不要假设功能不存在就新建
- 先 grep/glob 找到现有实现
- 对比现有实现 vs 新方案的差异
- 只有确认现有实现确实有缺陷时才提出修改

### 2. Guidance 而非 Constraint

**系统提供创作建议，不强制约束。**

- Evidence（证据）= 冷冰冰的数据事实
- Guide（建议）= 基于证据的主观建议
- Decision（决策）= 作者/系统的选择
- 不要出现第三种概念（Advice/Suggestion/Hint 等）

### 3. 文档署名

所有项目文档必须署名并加时间戳。格式：`作者 · YYYY-MM-DDTHH:MM:SS+08:00`

### 4. 一个 Feature = 三个文件

实现 + 测试 + demo。MVP 优先。

### 5. 迁移编号

增量迁移脚本编号不可复用。当前已用：005-054。新迁移从 055 开始。

## 架构约定

### 数据库

- SQLite，增量迁移（`app/db/migrations/`）
- 修改 CHECK 约束必须重建表（CREATE new → INSERT SELECT → DROP old → RENAME）
- 仅修改 Python 层验证不够，DB 层也会拒绝

### Guide 系统

- `app/core/types.py::collect_guides()` 是唯一入口（9 源，16 个调用方）
- 返回 `list[Guide]` 对象，下游依赖此类型
- Guide 数据类字段：source / priority / confidence / scope / advice / reason / evidence_ids / conflicts_with / supports

### 事件系统

- `app/services/unit_event_service.py` 承担事件持久化
- `story/events/` 是未接入的事件溯源实现（Reducer + EventStore），保留但不在生产路径

### 角色系统

- 3 个独立表示：`world_characters`（静态人设）、`character_trackers`（5维快照）、`project_settings`（UI 卡片）
- Voice Profile：`voice_profiles.py`（5维 + inferrer + validator）
- Character Arc：`character_arc_service.py`（从 book_outlines.character_arcs 激活）

### Style 系统

- `style_fingerprint.py`：L1 作者指纹（6维）+ L2 作品指纹（4维）
- `voice_profile.py`：角色声线 5 维
- `anti_ai.py`：6 类检查 + 三遍系统 + 7 门控

### 知识库

- 文件系统（builtin/local 目录），不是数据库
- BM25 + Vector 混合检索（`knowledge/finder.py`）
- 11 类能力索引

## 目录结构

```text
app/
├── core/           # 基础设施：配置、DI容器、事件总线、类型
├── db/             # 数据库层：SQLite + 迁移
├── ai/             # LLM集成：提供者、路由、缓存
├── agents/         # 智能体：orchestrator (1161行)
├── services/       # 业务逻辑：56+ 服务文件
├── ui/             # PySide6 界面
└── knowledge/      # 知识库：BM25+Vector

story/
├── state/          # StoryState 不可变快照
├── events/         # 事件类型+归约器（未接入生产）
├── guide/          # 收集器+5源适配器（collector.py在用，v2未接入）
├── decision/       # 冲突检测+策略选择
├── prompt/         # SUC编译+token预算
├── engine/         # 全链路门面
└── runtime/        # 连接DB的运行器

smoke/              # 烟雾测试
docs/               # 设计文档+归档
```

## 当前待做项

1. **conflict_log 参数修复**：`collect_guides()` 调 `analyze()` 时未传 `project_id`/`unit_id`，导致冲突日志永远不写入
2. **collect_guides() 适配器模式重构**：9 个 try/except → 10 个适配器 + 循环
3. **死代码清理**：13 个文件（~854 行）无生产调用

## 测试

```bash
python smoke/smoke_v4_state.py
python smoke/smoke_v4_guide_decision.py
python smoke/smoke_v4_prompt.py
python smoke/smoke_v4_runtime.py
python smoke/smoke_v4_isolation.py
python smoke/smoke_v4_event_store.py
```

## 版本历史

- v4.3.0 (2026-07-09): Character Arc 激活 + reverse_compile 修复 + 单元包装修复
- v4.2.0: Finder 收口 + 分卷编排 + 单元池增强 + Capability + Agent 装配
- v4.1.0: 收口方案 + 冲突日志/补丁预览/反向编译
- v4.0.0: Story OS 核心（State/Event/Guide/Decision/Prompt）
