# Novel Writer v4.0 — 完整实施计划

> 目标路径：`D:\novel-writer-pure-v4.0`
> 来源路径：`D:\novel-writer-pure-v3.4`
> 架构：Story OS 10层设计
> 日期：2026-07-06

---

## 目录

1. [项目结构](#1-项目结构)
2. [复用 vs 重写矩阵](#2-复用-vs-重写矩阵)
3. [实施阶段](#3-实施阶段)
4. [逐文件计划](#4-逐文件计划)
5. [依赖与集成](#5-依赖与集成)
6. [测试策略](#6-测试策略)
7. [迁移路径](#7-迁移路径)

---

## 1. 项目结构

```
D:\novel-writer-pure-v4.0\
├── pyproject.toml
├── requirements.txt
├── requirements-pyside6.txt
├── README.md
├── CLAUDE.md
├── .env.example
├── .gitignore
│
├── app/                          # 应用层
│   ├── __init__.py
│   ├── __main__.py
│   ├── main.py
│   ├── cli.py
│   ├── app_paths.py
│   │
│   ├── core/                     # L1: 核心基础设施 (保留)
│   │   ├── __init__.py
│   │   ├── config.py             # 保留 — 应用配置
│   │   ├── container.py          # 保留 — DI容器
│   │   ├── event_bus.py          # 保留 — 内部发布/订阅
│   │   ├── interfaces.py         # 保留 — 抽象接口
│   │   ├── types.py              # 保留 — Guide数据类 + 核心类型
│   │   ├── constants.py          # 保留 — 常量
│   │   ├── logger.py             # 保留 — 日志配置
│   │   ├── exceptions.py         # 保留 — 异常层级
│   │   └── version.py            # 重写 → v4.0.0
│   │
│   ├── db/                       # L7: 事件与状态持久化 (保留)
│   │   ├── __init__.py
│   │   ├── _impl.py              # 保留 — 数据库实现
│   │   ├── db_utils.py           # 保留 — 工具函数
│   │   ├── schema.sql            # 保留 + 扩展 — 添加events表
│   │   ├── models.py             # 保留 — ORM模型
│   │   ├── migrator.py           # 保留 — 迁移执行器
│   │   └── migrations/           # 保留 — 现有 + v4新迁移
│   │
│   ├── ai/                       # L6: 生成层提供者 (保留)
│   │   ├── engine.py             # 保留 — LLM引擎
│   │   ├── providers.py          # 保留 — 提供者注册表
│   │   ├── router.py             # 保留 — 模型路由
│   │   ├── cache.py              # 保留 — 响应缓存
│   │   ├── fallback.py           # 保留 — 降级链
│   │   ├── parallel.py           # 保留 — 并行推理
│   │   ├── mock.py               # 保留 — 测试用mock
│   │   └── utils.py              # 保留 — token估算
│   │
│   ├── knowledge/                # 保留 — RAG子系统
│   │   ├── bm25.py
│   │   ├── vector_db.py
│   │   ├── finder.py
│   │   ├── importer.py
│   │   ├── builtin/
│   │   └── index/
│   │
│   ├── validators/               # 保留 — 内容验证器
│   │   ├── base.py
│   │   ├── pov.py
│   │   ├── props.py
│   │   ├── repetition.py
│   │   ├── setting.py
│   │   ├── space.py
│   │   └── voice.py
│   │
│   ├── adapters/                 # 保留 — 平台适配器
│   │   ├── headless/
│   │   └── pyside6/
│   │
│   ├── agents/                   # L4: 智能体模拟 (重写)
│   │   ├── __init__.py
│   │   ├── base.py               # 重写 — AgentBase v4隔离内核
│   │   ├── writer.py             # 新增 — Writer智能体
│   │   ├── reader.py             # 新增 — Reader智能体
│   │   ├── critic.py             # 新增 — Critic智能体
│   │   ├── memory_agent.py       # 新增 — Memory智能体
│   │   ├── orchestrator.py       # 重写 — v4编排器
│   │   ├── report.py             # 保留 + 扩展
│   │   └── isolation.py          # 新增 — 隔离内核
│   │
│   ├── services/                 # 挑选干净的保留，混乱的重写
│   │   ├── __init__.py
│   │   ├── project_service.py    # 保留
│   │   ├── app_setting_service.py # 保留
│   │   ├── book_service.py       # 保留
│   │   ├── chapter_service.py    # 保留
│   │   ├── story_unit_service_v2.py # 保留
│   │   ├── unit_writing_service.py  # 保留
│   │   ├── knowledge_service.py  # 保留
│   │   ├── usage_analytics.py    # 保留
│   │   ├── decision_service.py   # 重写 — 集成v4决策层
│   │   ├── guide_graph.py        # 重写 — 集成v4引导引擎
│   │   ├── memory_manager.py     # 保留 + 扩展 — L4记忆
│   │   ├── pressure.py           # 保留 — 压力信号
│   │   ├── consistency.py        # 保留 — 一致性检查
│   │   ├── voice_profile.py      # 保留 — 声音指纹
│   │   ├── voice_inferrer.py     # 保留
│   │   ├── style_fingerprint.py  # 保留
│   │   ├── db.py                 # 保留 — 数据库辅助
│   │   ├── exporter.py           # 保留
│   │   └── ...                   # 其他：评估必要性
│   │
│   ├── ui/                       # L1: UI层 (完全重写)
│   │   ├── __init__.py
│   │   ├── main_window.py        # 重写 — v4模块导航
│   │   ├── pages.py              # 重写 — 页面注册表
│   │   ├── theme.py              # 重写 — v4设计令牌
│   │   ├── theme_observer.py     # 重写 — v4主题绑定
│   │   ├── screen_adapter.py     # 保留 — DPI缩放
│   │   ├── welcome.py            # 重写
│   │   │
│   │   ├── tabs/                 # 重写 — 所有标签页
│   │   │   ├── __init__.py
│   │   │   ├── hud_tab.py        # 新增 — Story HUD (概览仪表盘)
│   │   │   ├── unit_editor_tab.py # 重写 — 单元编辑器
│   │   │   ├── graph_tab.py      # 新增 — 故事图谱可视化
│   │   │   ├── inspector_tab.py  # 新增 — 角色检查器
│   │   │   ├── timeline_tab.py   # 新增 — 时间线视图
│   │   │   ├── outline_tab.py    # 重写
│   │   │   ├── worldview_tab.py  # 重写
│   │   │   ├── character_mgmt_tab.py # 重写
│   │   │   ├── generate_tab.py   # 重写
│   │   │   ├── settings_tab.py   # 重写
│   │   │   └── publish_tab.py    # 新增 — 统一发布视图
│   │   │
│   │   ├── widgets/              # 重写 — 所有组件
│   │   │   ├── __init__.py
│   │   │   ├── module_nav.py     # 重写 — v4四模块导航
│   │   │   ├── story_hud.py      # 重写 — HUD组件
│   │   │   ├── unit_editor.py    # 重写
│   │   │   ├── unit_tree.py      # 重写
│   │   │   ├── guide_panel.py    # 重写 — v4引导信号面板
│   │   │   ├── decision_panel.py # 新增 — 决策结果展示
│   │   │   ├── pressure_chart.py # 新增 — 压力曲线图
│   │   │   ├── settings_popup.py # 重写
│   │   │   ├── dialogs.py        # 重写
│   │   │   └── ...               # 其他组件按需添加
│   │   │
│   │   ├── observe/              # 重写 — 观察页面
│   │   │   ├── __init__.py
│   │   │   ├── story_health.py
│   │   │   ├── analytics.py
│   │   │   └── knowledge_page.py
│   │   │
│   │   └── workers/              # 重写 — 后台工作器
│   │       ├── __init__.py
│   │       └── generation_worker.py
│   │
│   ├── export/                   # L9: 发布层 (保留 + 扩展)
│   │   ├── __init__.py
│   │   ├── exporters.py
│   │   └── platform_adapters/
│   │
│   └── resources/                # 保留
│       ├── *.json
│       └── *.qss
│
├── story/                        # Story OS核心 (L2-L8) — 以此为中心构建
│   ├── __init__.py
│   │
│   ├── state/                    # L2: 故事状态 (SSOT) — 保留 + 扩展
│   │   ├── __init__.py
│   │   ├── story_state.py        # 保留 — 冻结数据类，不可变
│   │   ├── state_bridge.py       # 保留 — 数据库 ↔ StoryState转换
│   │   ├── apply_event.py        # 保留 — 纯归约器
│   │   └── event_store.py        # 新增 — EventStore持久化
│   │
│   ├── engine/                   # L10: 运行循环 — 保留 + 重写
│   │   ├── __init__.py
│   │   ├── story_engine.py       # 重写 — v4 StoryEngine门面
│   │   └── unit_runner.py        # 重写 — v4 UnitRunner
│   │
│   ├── guide/                    # L3: 引导引擎 — 保留 + 重写
│   │   ├── __init__.py
│   │   ├── collector.py          # 重写 — v4五源信号收集
│   │   ├── pressure_source.py    # 新增 — 压力引导源
│   │   ├── memory_source.py      # 新增 — 记忆引导源
│   │   ├── consistency_source.py # 新增 — 一致性引导源
│   │   ├── voice_source.py       # 新增 — 声音引导源
│   │   ├── hook_source.py        # 新增 — 伏笔引导源
│   │   └── sources.py            # 新增 — 源注册表
│   │
│   ├── decision/                 # L5: 决策层 — 保留 + 扩展
│   │   ├── __init__.py
│   │   ├── engine.py             # 保留 + 扩展 — 冲突检测
│   │   ├── dimension_matrix.py   # 保留 — 权重矩阵
│   │   ├── strategy.py           # 保留 — 四种策略
│   │   └── conflict.py           # 新增 — 冲突解决
│   │
│   ├── prompt/                   # L6: 提示系统 — 保留 + 重写
│   │   ├── __init__.py
│   │   ├── compiler.py           # 保留 + 扩展 — SUC编译器
│   │   ├── suc_builder.py        # 保留 — SUC片段
│   │   ├── suc_template.py       # 新增 — 模板引擎
│   │   └── token_budget.py       # 新增 — token预算优化器
│   │
│   ├── events/                   # L7: 事件系统 — 新增
│   │   ├── __init__.py
│   │   ├── types.py              # 新增 — 事件类型定义
│   │   ├── store.py              # 新增 — 事件存储接口
│   │   └── reducer.py            # 新增 — 事件归约器
│   │
│   ├── publish/                  # L9: 发布层 — 新增
│   │   ├── __init__.py
│   │   ├── assembler.py          # 新增 — 单元 → 章节组装
│   │   ├── platform_adapter.py   # 新增 — 平台导出接口
│   │   └── exporters/            # 新增 — 平台特定导出器
│   │
│   └── ui/                       # L8: 可观测性UI — 新增
│       ├── __init__.py
│       ├── story_graph.py        # 新增 — 图谱数据模型
│       ├── pressure_curve.py     # 新增 — 压力曲线数据
│       └── inspector.py          # 新增 — 检查器数据模型
│
├── smoke/                        # 测试 (保留 + 扩展)
│   ├── smoke_v4_guide_decision.py  # 保留
│   ├── smoke_v4_prompt.py          # 保留
│   ├── smoke_v4_runtime.py         # 保留
│   ├── smoke_v4_state.py           # 保留
│   ├── smoke_v4_isolation.py       # 新增
│   ├── smoke_v4_event_store.py     # 新增
│   ├── smoke_v4_publish.py         # 新增
│   └── ...                         # 其他烟雾测试
│
├── docs/                         # 文档
│   ├── ARCHITECTURE.md
│   ├── MIGRATION.md
│   └── CHANGELOG.md
│
└── tests/                        # 单元测试 (新增)
    ├── test_state.py
    ├── test_guide.py
    ├── test_decision.py
    ├── test_prompt.py
    ├── test_agents.py
    └── test_integration.py
```

---

## 2. 复用 vs 重写矩阵

### 保留（稳定，可复用）— 原样复制

| 模块 | 来源 | 行数 | 保留原因 |
|------|------|------|----------|
| `app/ai/*` | v3.4 | ~1200 | 干净的提供者抽象，无需修改 |
| `app/core/*` | v3.4 | ~1800 | DI容器、事件总线、类型 — 稳定基础 |
| `app/db/*` | v3.4 | ~2000+ | Schema + 迁移 — 向后兼容 |
| `app/knowledge/*` | v3.4 | ~1000 | BM25 + 向量数据库 — 独立、干净 |
| `app/validators/*` | v3.4 | ~800 | 内容验证器 — 独立模块 |
| `app/adapters/*` | v3.4 | ~200 | 平台适配器 — 最小化 |
| `app/services/project_service.py` | v3.4 | ~400 | 项目CRUD — 稳定 |
| `app/services/app_setting_service.py` | v3.4 | ~300 | 设置持久化 — 稳定 |
| `app/services/book_service.py` | v3.4 | ~200 | 书籍CRUD — 稳定 |
| `app/services/chapter_service.py` | v3.4 | ~200 | 章节CRUD — 稳定 |
| `app/services/story_unit_service_v2.py` | v3.4 | ~300 | 单元CRUD — 稳定 |
| `app/services/usage_analytics.py` | v3.4 | ~200 | 用量跟踪 — 稳定 |
| `app/services/memory_manager.py` | v3.4 | ~500 | L1-L4记忆 — 保留，后续扩展 |
| `app/services/pressure.py` | v3.4 | ~300 | 压力信号 — 保留 |
| `app/services/consistency.py` | v3.4 | ~400 | 一致性检查 — 保留 |
| `app/services/voice_profile.py` | v3.4 | ~200 | 声音指纹 — 保留 |
| `app/services/voice_inferrer.py` | v3.4 | ~200 | 声音推断 — 保留 |
| `app/services/style_fingerprint.py` | v3.4 | ~200 | 风格指纹 — 保留 |
| `app/services/db.py` | v3.4 | ~100 | 数据库辅助 — 保留 |
| `app/services/exporter.py` | v3.4 | ~200 | 导出 — 保留 |
| `story/state/*` | v3.4 | ~600 | 核心SSOT — 不可变、事件溯源 |
| `story/decision/strategy.py` | v3.4 | ~107 | 四种策略 — 完整 |
| `story/decision/dimension_matrix.py` | v3.4 | ~200 | 权重矩阵 — 完整 |
| `story/prompt/suc_builder.py` | v3.4 | ~268 | SUC片段 — 完整 |
| `story/prompt/compiler.py` | v3.4 | ~130 | 提示编译 — 可扩展 |
| `smoke/*` | v3.4 | ~70文件 | 现有烟雾测试 — 保留 + 添加新测试 |

### 重写（需要全新设计）

| 模块 | 来源 | 行数 | 重写原因 |
|------|------|------|----------|
| `app/ui/*` | v3.4 | ~5000+ | 完整PySide6 UI重写 — 133+内联样式，无主题绑定 |
| `app/agents/*` | v3.4 | ~500 | 简化为v4智能体模拟（4个智能体） |
| `app/services/decision_service.py` | v3.4 | ~300 | 正确集成v4决策层 |
| `app/services/guide_graph.py` | v3.4 | ~200 | 集成v4引导引擎 |
| `story/guide/collector.py` | v3.4 | ~168 | 重写为五源架构 |
| `story/engine/story_engine.py` | v3.4 | ~92 | 重写为v4门面 |
| `story/engine/unit_runner.py` | v3.4 | ~172 | 重写为v4 UnitRunner |

### 新增（v3.4中不存在）

| 模块 | 用途 | 预计行数 |
|------|------|----------|
| `story/state/event_store.py` | EventStore持久化层 | ~150 |
| `story/events/*` | 事件类型定义 + 存储 + 归约器 | ~300 |
| `story/guide/pressure_source.py` | 压力引导源 | ~80 |
| `story/guide/memory_source.py` | 记忆引导源 | ~80 |
| `story/guide/consistency_source.py` | 一致性引导源 | ~80 |
| `story/guide/voice_source.py` | 声音引导源 | ~80 |
| `story/guide/hook_source.py` | 伏笔引导源 | ~80 |
| `story/guide/sources.py` | 源注册表 | ~50 |
| `story/decision/conflict.py` | 冲突解决 | ~100 |
| `story/prompt/suc_template.py` | 模板引擎 | ~100 |
| `story/prompt/token_budget.py` | Token预算优化器 | ~80 |
| `story/publish/*` | 发布层 | ~300 |
| `story/ui/*` | 可观测性数据模型 | ~200 |
| `app/agents/writer.py` | Writer智能体 | ~100 |
| `app/agents/reader.py` | Reader智能体 | ~100 |
| `app/agents/critic.py` | Critic智能体 | ~100 |
| `app/agents/memory_agent.py` | Memory智能体 | ~100 |
| `app/agents/isolation.py` | 隔离内核 | ~150 |
| `app/ui/tabs/hud_tab.py` | Story HUD | ~200 |
| `app/ui/tabs/graph_tab.py` | 故事图谱 | ~200 |
| `app/ui/tabs/inspector_tab.py` | 角色检查器 | ~200 |
| `app/ui/tabs/timeline_tab.py` | 时间线视图 | ~200 |
| `app/ui/tabs/publish_tab.py` | 发布视图 | ~150 |
| `app/ui/widgets/decision_panel.py` | 决策展示 | ~100 |
| `app/ui/widgets/pressure_chart.py` | 压力曲线图 | ~150 |

---

## 3. 实施阶段

### 第0阶段：项目引导（第1天）
**目标**：空项目可以运行并通过基本烟雾测试。

1. 创建 `D:\novel-writer-pure-v4.0` 目录
2. 复制 `pyproject.toml` → 更新版本为 `4.0.0`
3. 复制 `app/core/`（所有文件）→ 无需修改
4. 复制 `app/db/`（所有文件）→ 无需修改
5. 复制 `app/ai/`（所有文件）→ 无需修改
6. 创建 `app/__init__.py`、`app/__main__.py`、`app/main.py`（最小化）
7. 创建 `story/__init__.py`
8. 验证：`python -c "from app.core.config import AppConfig; print('OK')"`

### 第1阶段：故事状态基础（第2-3天）
**目标**：不可变SSOT + 事件溯源。

1. 复制 `story/state/story_state.py` → 原样保留
2. 复制 `story/state/apply_event.py` → 原样保留
3. 复制 `story/state/state_bridge.py` → 原样保留
4. **新增**：创建 `story/state/event_store.py` — EventStore接口 + SQLite实现
5. **新增**：创建 `story/events/types.py` — 事件类型定义
6. **新增**：创建 `story/events/store.py` — 事件存储接口
7. **新增**：创建 `story/events/reducer.py` — 事件归约器
8. 验证：新EventStore通过烟雾测试

### 第2阶段：引导引擎（第4-5天）
**目标**：五源信号收集，正确隔离。

1. 复制 `story/guide/collector.py` → 重写为v4五源架构
2. **新增**：创建 `story/guide/pressure_source.py`
3. **新增**：创建 `story/guide/memory_source.py`
4. **新增**：创建 `story/guide/consistency_source.py`
5. **新增**：创建 `story/guide/voice_source.py`
6. **新增**：创建 `story/guide/hook_source.py`
7. **新增**：创建 `story/guide/sources.py` — 源注册表
8. 复制 `app/services/pressure.py` → 保留
9. 复制 `app/services/consistency.py` → 保留
10. 复制 `app/services/memory_manager.py` → 保留
11. 复制 `app/services/voice_profile.py` → 保留
12. 验证：引导收集器从所有五源产生信号

### 第3阶段：决策层（第6-7天）
**目标**：冲突检测 + 策略选择。

1. 复制 `story/decision/engine.py` → 保留 + 扩展
2. 复制 `story/decision/dimension_matrix.py` → 保留
3. 复制 `story/decision/strategy.py` → 保留
4. **新增**：创建 `story/decision/conflict.py` — 冲突解决
5. 验证：决策引擎从信号产生StrategyResult

### 第4阶段：提示系统（第8-9天）
**目标**：带token预算优化的SUC编译器。

1. 复制 `story/prompt/compiler.py` → 保留 + 扩展
2. 复制 `story/prompt/suc_builder.py` → 保留
3. **新增**：创建 `story/prompt/suc_template.py` — 模板引擎
4. **新增**：创建 `story/prompt/token_budget.py` — token预算优化器
5. 验证：提示编译产生有效的CompiledPrompt

### 第5阶段：智能体模拟（第10-12天）
**目标**：带隔离内核的4个智能体。

1. 重写 `app/agents/base.py` → v4 AgentBase + 隔离
2. **新增**：创建 `app/agents/writer.py`
3. **新增**：创建 `app/agents/reader.py`
4. **新增**：创建 `app/agents/critic.py`
5. **新增**：创建 `app/agents/memory_agent.py`
6. 重写 `app/agents/orchestrator.py` → v4编排器
7. 复制 `app/agents/report.py` → 保留 + 扩展
8. **新增**：创建 `app/agents/isolation.py` — 隔离内核
9. 验证：智能体在隔离中执行，产生报告

### 第6阶段：运行循环（第13-14天）
**目标**：完整的UnitRunner链。

1. 重写 `story/engine/story_engine.py` → v4门面
2. 重写 `story/engine/unit_runner.py` → v4 UnitRunner
3. 验证：全链路端到端工作

### 第7阶段：UI基础（第15-20天）
**目标**：可工作的UI外壳 + 导航。

1. 重写 `app/ui/theme.py` → v4设计令牌
2. 重写 `app/ui/theme_observer.py` → v4主题绑定
3. 重写 `app/ui/main_window.py` → v4模块导航
4. 重写 `app/ui/pages.py` → v4页面注册表
5. 重写 `app/ui/widgets/module_nav.py` → v4导航
6. 重写 `app/ui/welcome.py` → v4欢迎页
7. 验证：应用启动，导航正常

### 第8阶段：UI页面（第21-28天）
**目标**：所有功能页面。

1. 重写 `app/ui/tabs/generate_tab.py` → v4
2. 重写 `app/ui/tabs/outline_tab.py` → v4
3. 重写 `app/ui/tabs/worldview_tab.py` → v4
4. 重写 `app/ui/tabs/character_mgmt_tab.py` → v4
5. **新增**：创建 `app/ui/tabs/hud_tab.py` → Story HUD
6. **新增**：创建 `app/ui/tabs/graph_tab.py` → 故事图谱
7. **新增**：创建 `app/ui/tabs/inspector_tab.py` → 角色检查器
8. **新增**：创建 `app/ui/tabs/timeline_tab.py` → 时间线
9. **新增**：创建 `app/ui/tabs/publish_tab.py` → 发布
10. 重写 `app/ui/tabs/settings_tab.py` → v4
11. 验证：所有页面渲染和导航正常

### 第9阶段：集成与测试（第29-31天）
**目标**：完整集成 + 综合测试。

1. 复制所有现有 `smoke/` 测试 → 适配v4
2. **新增**：添加 `smoke_v4_isolation.py`
3. **新增**：添加 `smoke_v4_event_store.py`
4. **新增**：添加 `smoke_v4_publish.py`
5. 运行完整测试套件
6. 手动UI测试
7. 性能分析

---

## 4. 逐文件计划

### 4.1 核心基础设施（原样保留）

#### `app/core/config.py`
- **操作**：从v3.4复制
- **变更**：无
- **依赖**：无
- **行数**：~200

#### `app/core/container.py`
- **操作**：从v3.4复制
- **变更**：无
- **依赖**：无
- **行数**：~150

#### `app/core/event_bus.py`
- **操作**：从v3.4复制
- **变更**：无
- **依赖**：无
- **行数**：~100

#### `app/core/types.py`
- **操作**：从v3.4复制
- **变更**：无 — Guide数据类已兼容v4
- **依赖**：无
- **行数**：~331

### 4.2 故事状态（保留 + 扩展）

#### `story/state/story_state.py`
- **操作**：从v3.4复制
- **变更**：无
- **理由**：不可变冻结数据类，完美的SSOT
- **行数**：295

#### `story/state/apply_event.py`
- **操作**：从v3.4复制
- **变更**：无
- **理由**：纯归约器，无副作用
- **行数**：222

#### `story/state/state_bridge.py`
- **操作**：从v3.4复制
- **变更**：无
- **行数**：~100

#### `story/state/event_store.py`（新增）
- **操作**：创建
- **用途**：持久化事件到数据库，支持回放
- **接口**：
  ```python
  class EventStore:
      def append(self, unit_id: str, event: dict) -> None: ...
      def get_events(self, unit_id: str) -> list[dict]: ...
      def get_events_since(self, unit_id: str, since: float) -> list[dict]: ...
      def clear(self, unit_id: str) -> None: ...
  ```
- **实现**：SQLite后端，使用现有DB schema
- **行数**：~150
- **依赖**：`app/db/`, `story/events/types.py`

### 4.3 引导引擎（重写）

#### `story/guide/collector.py`（重写）
- **操作**：重写
- **用途**：从五源收集信号
- **现状**：单一 `collect_signals()` 函数
- **新设计**：
  ```python
  class GuideCollector:
      def __init__(self, sources: list[GuideSource]): ...
      def collect(self, unit_id: str, *, state: StoryState = None) -> list[DecisionSignal]: ...
  ```
- **源**：压力、记忆、一致性、声音、伏笔
- **行数**：~200
- **依赖**：所有五源模块

#### `story/guide/pressure_source.py`（新增）
- **操作**：创建
- **用途**：来自节奏分析的压力信号
- **接口**：实现 `GuideSource` 协议
- **行数**：~80
- **依赖**：`app/services/pressure.py`

#### `story/guide/memory_source.py`（新增）
- **操作**：创建
- **用途**：来自智能体记忆的记忆信号
- **接口**：实现 `GuideSource` 协议
- **行数**：~80
- **依赖**：`app/services/memory_manager.py`

#### `story/guide/consistency_source.py`（新增）
- **操作**：创建
- **用途**：来自验证器的一致性信号
- **接口**：实现 `GuideSource` 协议
- **行数**：~80
- **依赖**：`app/validators/`, `app/services/consistency.py`

#### `story/guide/voice_source.py`（新增）
- **操作**：创建
- **用途**：来自声音分析的声音信号
- **接口**：实现 `GuideSource` 协议
- **行数**：~80
- **依赖**：`app/services/voice_profile.py`

#### `story/guide/hook_source.py`（新增）
- **操作**：创建
- **用途**：来自伏笔追踪的伏笔信号
- **接口**：实现 `GuideSource` 协议
- **行数**：~80
- **依赖**：`story/state/story_state.py`

#### `story/guide/sources.py`（新增）
- **操作**：创建
- **用途**：源注册表 + 协议定义
- **接口**：
  ```python
  class GuideSource(Protocol):
      source_id: str
      def collect(self, unit_id: str, *, state: StoryState = None) -> list[DecisionSignal]: ...
  ```
- **行数**：~50

### 4.4 决策层（保留 + 扩展）

#### `story/decision/engine.py`
- **操作**：保留 + 扩展
- **变更**：添加冲突解决集成
- **行数**：256

#### `story/decision/dimension_matrix.py`
- **操作**：保留
- **变更**：无
- **行数**：~200

#### `story/decision/strategy.py`
- **操作**：保留
- **变更**：无
- **行数**：107

#### `story/decision/conflict.py`（新增）
- **操作**：创建
- **用途**：检测并解决引导之间的冲突
- **接口**：
  ```python
  def detect_conflicts(signals: list[DecisionSignal]) -> list[Conflict]: ...
  def resolve_conflicts(conflicts: list[Conflict], signals: list[DecisionSignal]) -> list[DecisionSignal]: ...
  ```
- **行数**：~100

### 4.5 提示系统（保留 + 扩展）

#### `story/prompt/compiler.py`
- **操作**：保留 + 扩展
- **变更**：添加模板支持、token预算
- **行数**：130

#### `story/prompt/suc_builder.py`
- **操作**：保留
- **变更**：无
- **行数**：268

#### `story/prompt/suc_template.py`（新增）
- **操作**：创建
- **用途**：SUC片段的模板引擎
- **行数**：~100

#### `story/prompt/token_budget.py`（新增）
- **操作**：创建
- **用途**：跨片段优化token使用
- **行数**：~80

### 4.6 智能体模拟（重写）

#### `app/agents/base.py`（重写）
- **操作**：重写
- **用途**：v4 AgentBase + 隔离内核
- **现状**：231行，复杂状态机
- **新设计**：简化，聚焦隔离
  ```python
  class AgentBase(ABC):
      role: AgentRole
      def execute(self, task: AgentTask) -> AgentReport: ...
      def _do_execute(self, task: AgentTask) -> AgentReport: ...
  ```
- **行数**：~200

#### `app/agents/isolation.py`（新增）
- **操作**：创建
- **用途**：智能体隔离内核
- **接口**：
  ```python
  class IsolationKernel:
      def __init__(self, agent: AgentBase): ...
      def run(self, task: AgentTask) -> AgentReport: ...
      def get_history(self) -> list[AgentReport]: ...
      def get_metrics(self) -> AgentMetrics: ...
  ```
- **行数**：~150

#### `app/agents/writer.py`（新增）
- **操作**：创建
- **用途**：Writer智能体 — 生成文本
- **行数**：~100

#### `app/agents/reader.py`（新增）
- **操作**：创建
- **用途**：Reader智能体 — 评估质量
- **行数**：~100

#### `app/agents/critic.py`（新增）
- **操作**：创建
- **用途**：Critic智能体 — 风格一致性
- **行数**：~100

#### `app/agents/memory_agent.py`（新增）
- **操作**：创建
- **用途**：Memory智能体 — L1-L4记忆管理
- **行数**：~100

#### `app/agents/orchestrator.py`（重写）
- **操作**：重写
- **用途**：v4编排器 + 智能体协调
- **现状**：复杂，职责过多
- **新设计**：简化，聚焦协调
- **行数**：~300

### 4.7 运行循环（重写）

#### `story/engine/story_engine.py`（重写）
- **操作**：重写
- **用途**：v4 StoryEngine门面
- **现状**：92行，基础门面
- **新设计**：完整v4集成
  ```python
  class StoryEngine:
      def __init__(self, config: AppConfig): ...
      def run_unit(self, project_id: str, unit_id: str) -> RunResult: ...
      def apply_events(self, state: StoryState, events: list[dict]) -> StoryState: ...
  ```
- **行数**：~150

#### `story/engine/unit_runner.py`（重写）
- **操作**：重写
- **用途**：v4 UnitRunner — 完整链
- **现状**：172行
- **新设计**：完整v4链 + 所有集成
  ```python
  class UnitRunner:
      def __init__(self, engine: StoryEngine): ...
      def run(self, project_id: str, unit_id: str) -> RunResult: ...
  ```
- **行数**：~200

### 4.8 UI层（完全重写）

#### `app/ui/theme.py`（重写）
- **操作**：重写
- **用途**：v4设计令牌
- **现状**：硬编码颜色，无设计系统
- **新设计**：令牌驱动的设计系统
  ```python
  # 颜色令牌
  class Theme:
      primary: str
      secondary: str
      background: str
      surface: str
      text: str
      text_secondary: str
      border: str
      error: str
      warning: str
      success: str
  
  # 间距令牌
  SPACING = {4: 4, 8: 8, 12: 12, 16: 16, 24: 24, 32: 32}
  
  # 排版令牌
  FONT_SIZES = {"caption": 11, "body": 13, "heading": 16, "title": 20}
  ```
- **行数**：~200

#### `app/ui/theme_observer.py`（重写）
- **操作**：重写
- **用途**：自动主题绑定
- **现状**：`bind_theme()`存在但未使用（133+内联样式）
- **新设计**：全面主题绑定系统
  ```python
  class ThemeObserver:
      def bind(self, widget: QWidget, property: str, token: str): ...
      def update_all(self): ...
  ```
- **行数**：~150

#### `app/ui/main_window.py`（重写）
- **操作**：重写
- **用途**：v4模块导航
- **现状**：662行，复杂
- **新设计**：简化，四模块布局
- **行数**：~400

#### `app/ui/pages.py`（重写）
- **操作**：重写
- **用途**：v4页面注册表
- **现状**：2677行，单体式
- **新设计**：干净的注册表，每页独立文件
- **行数**：~200

#### `app/ui/tabs/hud_tab.py`（新增）
- **操作**：创建
- **用途**：Story HUD — 概览仪表盘
- **行数**：~200

#### `app/ui/tabs/graph_tab.py`（新增）
- **操作**：创建
- **用途**：故事图谱可视化
- **行数**：~200

#### `app/ui/tabs/inspector_tab.py`（新增）
- **操作**：创建
- **用途**：角色检查器
- **行数**：~200

#### `app/ui/tabs/timeline_tab.py`（新增）
- **操作**：创建
- **用途**：时间线视图
- **行数**：~200

#### `app/ui/tabs/publish_tab.py`（新增）
- **操作**：创建
- **用途**：统一发布视图
- **行数**：~150

---

## 5. 依赖与集成

### 5.1 依赖图

```
                    ┌─────────────┐
                    │  app/ui/    │  L1: UI层
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ app/agents/ │  L4: 智能体模拟
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──────┐ ┌──▼─────┐ ┌───▼────┐
       │ story/guide │ │ story/ │ │ story/ │
       │   (L3)      │ │decision│ │ prompt │
       └──────┬──────┘ │  (L5)  │ │  (L6)  │
              │         └───┬────┘ └───┬────┘
              │             │          │
       ┌──────▼─────────────▼──────────▼──────┐
       │           story/state (L2)            │
       │          StoryState (SSOT)            │
       └──────────────────┬───────────────────┘
                          │
              ┌───────────▼───────────┐
              │     app/db/ (L7)      │
              │   EventStore + SQL    │
              └───────────────────────┘
```

### 5.2 集成点

1. **UI → 智能体**：UI通过工作器调用 `Orchestrator.execute(task)`
2. **智能体 → 引导**：智能体调用 `GuideCollector.collect()`
3. **引导 → 决策**：收集器产生 `DecisionSignal` → 决策引擎
4. **决策 → 提示**：`StrategyResult` → 提示编译器
5. **提示 → AI**：`CompiledPrompt` → `app/ai/engine.py`
6. **AI → 状态**：LLM输出 → 事件 → `apply_event()` → 新 `StoryState`
7. **状态 → 数据库**：`EventStore.append()` 持久化事件
8. **数据库 → UI**：UI通过服务从数据库读取

### 5.3 外部依赖

```toml
# pyproject.toml
dependencies = [
    "PySide6>=6.5",
    "numpy",
    "scikit-learn",
    "jieba",
    "requests",
]
```

无需新增外部依赖。v4完全基于现有依赖构建。

---

## 6. 测试策略

### 6.1 单元测试（新增）

| 测试文件 | 覆盖范围 |
|----------|----------|
| `tests/test_state.py` | StoryState创建、修改、事件应用 |
| `tests/test_guide.py` | 五源信号收集、冲突检测 |
| `tests/test_decision.py` | 策略选择、权重矩阵 |
| `tests/test_prompt.py` | SUC构建、提示编译 |
| `tests/test_agents.py` | 智能体隔离、报告生成 |
| `tests/test_integration.py` | 端到端链路 |

### 6.2 烟雾测试（保留 + 扩展）

| 测试文件 | 状态 |
|----------|------|
| `smoke_v4_state.py` | 保留 — 测试StoryState |
| `smoke_v4_guide_decision.py` | 保留 — 测试引导 → 决策 |
| `smoke_v4_prompt.py` | 保留 — 测试提示编译 |
| `smoke_v4_runtime.py` | 保留 — 测试运行循环 |
| `smoke_v4_isolation.py` | 新增 — 测试智能体隔离 |
| `smoke_v4_event_store.py` | 新增 — 测试事件持久化 |
| `smoke_v4_publish.py` | 新增 — 测试发布层 |

### 6.3 手动测试

1. **应用启动**：验证应用无错误启动
2. **导航**：所有四模块导航正确
3. **主题**：明暗模式切换正常
4. **生成**：完整生成流水线正常工作
5. **设置**：所有设置保存/加载正确
6. **导出**：导出TXT/DOCX正常

### 6.4 性能测试

1. **启动时间**：< 3秒
2. **生成时间**：单章节 < 30秒
3. **内存占用**：完整项目 < 500MB
4. **数据库查询**：常见操作 < 100ms

---

## 7. 迁移路径

### 7.1 数据库兼容性

v4.0与v3.4数据库**完全向后兼容**：

- 相同的 `schema.sql` 表结构
- 相同的列名和类型
- 相同的JSON blob格式
- 新增 `events` 表用于EventStore（增量，不破坏）

### 7.2 迁移步骤

1. **备份**：用户备份v3.4数据库
2. **复制数据库**：复制 `data/*.db` 到v4.0项目
3. **运行v4.0**：应用检测到v3.4数据库，运行任何待处理迁移
4. **验证**：所有现有数据可访问

### 7.3 代码迁移

1. **复制保留模块**：直接复制，无需修改
2. **复制重写模块**：复制作为参考，重新编写
3. **复制测试**：适配v4导入

### 7.4 回滚计划

- v3.4项目保持不变
- v4.0是独立目录
- 用户可通过切换工作目录在版本间切换

---

## 附录：关键设计决策

### A.1 为什么保留 `story/state/*` 原样？

`StoryState` 冻结数据类已是完美的SSOT实现：
- 不可变（frozen=True）
- 事件溯源（apply_event返回新实例）
- 可查询（to_dict(), active_hooks()等）
- 桥接模式（StateBridge用于数据库 ↔ 运行时）

无需修改。围绕它构建。

### A.2 为什么重写 `story/guide/collector.py`？

当前实现存在问题：
- 单一函数，不可扩展
- 硬编码源映射
- 无正确的源隔离

新设计：
- `GuideSource` 协议支持扩展性
- `GuideCollector` 类支持可注入源
- 每个源独立且可测试

### A.3 为什么完全重写UI？

v3.4 UI存在系统性问题：
- 133+内联 `setStyleSheet` 调用
- 无主题绑定（bind_theme存在但未使用）
- 单体式 `pages.py`（2677行）
- 复杂导航，映射不一致

v4.0 UI：
- 令牌驱动的设计系统
- 自动主题绑定
- 每页独立文件
- 简化的四模块导航

### A.4 为什么需要智能体隔离？

v3.4智能体共享上下文，可能相互干扰：
- 无上下文隔离
- 无每智能体指标跟踪
- 复杂状态机

v4.0智能体：
- 每个智能体在隔离中运行
- 每智能体指标和历史
- 简单状态机（idle → working → done/error）
- 报告作为唯一通信渠道

---

## 总结

| 指标 | v3.4 | v4.0目标 |
|------|------|----------|
| 总文件数 | ~200 | ~180（更少，更干净） |
| UI文件数 | 50+ | 30（简化） |
| 智能体文件数 | 6 | 8（更多，但更干净） |
| 故事文件数 | 15 | 25（更多，但模块化） |
| 测试文件数 | 70 | 80（更多覆盖） |
| 代码行数 | ~15,000 | ~12,000（更少，更好） |
| 外部依赖 | 5 | 5（无新增依赖） |
| 数据库兼容性 | - | 100%向后兼容 |