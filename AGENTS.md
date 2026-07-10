# AGENTS.md — Novel Writer Pure 项目级 Agent 指南

MiMoCode · 2026-07-09T12:00:00+08:00

## 项目身份

Novel Writer Pure v4.3 — AI 辅助长篇小说创作桌面工具。

技术栈：Python 3.10+ / PySide6 / SQLite / numpy / scikit-learn / jieba

架构：Story OS 10层（Core Infrastructure → Story State → Guide Engine → Agent Simulation → Decision Layer → Prompt OS → Event System → Observability UI → Publish Layer → Runtime Loop）

## 红线原则（必须遵守）

### 1. 首次深度分析 + 变更确认

**首次接触项目时，必须先深入全面分析项目架构、现有实现、模块关系，再动手。**

分析清单：
- 目录结构和模块职责
- 核心数据流（DB → Service → UI / DB → Service → Guide → Writer）
- 关键接口的调用方和被调用方
- 死代码和未接入的模块
- 现有实现 vs 用户需求的差距

**任何修改、删除、增加文件之前，必须：**
1. 分析影响面（哪些文件会受影响、哪些调用方会变化）
2. 列出原因和替代方案
3. 报告给用户确认后再执行

不允许：未分析就动手、未确认就提交。

### 2. 源码审查优先

**永远从项目实际代码出发分析，核实现有实现后再给结论。不受外部 AI 意见影响。**

- 不要假设功能不存在就新建
- 先 grep/glob 找到现有实现
- 对比现有实现 vs 新方案的差异
- 只有确认现有实现确实有缺陷时才提出修改

### 3. Guidance 而非 Constraint

**系统提供创作建议，不强制约束。**

- Evidence（证据）= 冷冰冰的数据事实
- Guide（建议）= 基于证据的主观建议
- Decision（决策）= 作者/系统的选择
- 不要出现第三种概念（Advice/Suggestion/Hint 等）

### 4. 文档署名

所有项目文档必须署名并加时间戳。格式：`作者 · YYYY-MM-DDTHH:MM:SS+08:00`

### 5. 一个 Feature = 三个文件

实现 + 测试 + demo。MVP 优先。

### 6. 迁移编号

增量迁移脚本编号不可复用。当前已用：005-054。新迁移从 055 开始。

## 工具使用约定

### 代码搜索

优先使用项目内建工具，不 shell out：

| 用途 | 工具 | 说明 |
|------|------|------|
| 代码探索 | `codegraph` | **首选** — 符号级查询，返回调用链+影响面+源码，一次调用替代多次 grep+read |
| 文件查找 | `glob` | 按文件名模式匹配，如 `**/*.py` |
| 内容搜索 | `grep` | 按正则搜索文件内容（codegraph 不适用时降级使用） |
| 文件读取 | `read` | 读取文件内容，支持 offset/limit |

**codegraph 使用规则：**
- 任何涉及"这个函数被谁调用""这个模块的影响面"的问题，优先用 codegraph
- codegraph 返回的源码视为已 Read，不需要再重复 Read 同一文件
- 如果项目未索引（无 `.codegraph/` 目录），先运行 `codegraph init`

**codegraph 常用命令：**

| 命令 | 用途 | 示例 |
|------|------|------|
| `codegraph init` | 初始化索引 | 首次使用时 |
| `codegraph sync` | 增量同步变更 | 修改代码后 |
| `codegraph status` | 查看索引状态 | 检查索引是否最新 |
| `codegraph explore <query>` | 符号级探索 | `codegraph explore "collect_guides"` |
| `codegraph callers <symbol>` | 查找调用方 | `codegraph callers "collect_guides"` |
| `codegraph callees <symbol>` | 查找被调用方 | `codegraph callees "orchestrator.run_unit"` |
| `codegraph impact <symbol>` | 影响面分析 | `codegraph impact "Guide"` |
| `codegraph query <search>` | 符号搜索 | `codegraph query "pressure"` |
| `codegraph install` | 安装 MCP 到 AI 工具 | 配置 Claude Code/Cursor 等 |

不要用 `bash cat / find / grep / sed`，工具层会加读状态追踪、截断处理、权限评估。

### 文档命名规范

所有 `docs/` 下的文档必须遵循：

```text
{类型}-{日期}-{作者}.md
```

类型关键词：

| 类型 | 说明 | 示例 |
|------|------|------|
| 方案 | 设计/架构决策 | `v4.3_Evidence_Library_方案-MiMoCode-2026-07-09.md` |
| 规划 | 路线图/计划 | `v4.4_路线图-MiMoCode-2026-07-10.md` |
| 修改 | 变更记录 | `v4.3_修改记录_CharacterArc-MiMoCode-2026-07-09.md` |
| 分析 | 问题分析/审查 | `模块审计-GPT意见-讨论归档.md` |
| 归档 | 历史文档 | 放 `docs/archive/` 按版本分目录 |

### 文档落库位置

```text
docs/
├── {项目名}_{类型}_{描述}.md    # 当前版本文档
├── archive/                     # 历史归档
│   ├── v2.0/                    # v2.0 时代文档
│   ├── v3.0/                    # v3.0 时代文档
│   └── v3.4/                    # v3.4 时代文档
```

### 版本同步规则

**版本号变更时，必须同步以下三处：**

1. `app/core/version.py` → `VERSION = "x.y.z"`
2. `README.md` → 标题版本号 + 版本历史
3. `AGENTS.md` → 版本历史

**不允许出现：** 代码版本号是 4.3.0 但文档还写着 4.0.0。

### 文档同步更新规则

**每次版本变更或功能交付时，必须同步更新以下文档：**

| 触发条件 | 必须更新的文档 |
|----------|---------------|
| 版本号变更 | `version.py` + `README.md` + `AGENTS.md` |
| 新增/修改功能 | `README.md` 版本历史 + 对应 `docs/` 文档 |
| 修复 bug | `docs/` 修改记录 |
| 架构变更 | `AGENTS.md` 架构约定 + `docs/` 方案文档 |
| 新增迁移 | `AGENTS.md` 迁移编号 |

**不允许：** 代码已改但文档未更新，或文档描述与代码实现不一致。

### AI 工具兼容

本项目的 Agent 指南以 `AGENTS.md` 为源文件，通过符号链接兼容所有 AI 工具：

| 工具 | 读取的文件 | 链接方式 |
|------|-----------|----------|
| MiMoCode | `AGENTS.md` | 直接读取 |
| Claude Code | `CLAUDE.md` | symlink → AGENTS.md |
| Codex CLI | `AGENTS.md` | 直接读取 |
| Cursor | `.cursorrules` | symlink → AGENTS.md |
| GitHub Copilot | `.github/copilot-instructions.md` | symlink → AGENTS.md |
| Windsurf | `.windsurfrules` | symlink → AGENTS.md |
| Trae CN / Trae Work CN | `.trae/rules` | symlink → AGENTS.md |

修改 `AGENTS.md` 一处，所有工具同步生效。

### 文档命名规范

所有 `docs/` 下的文档必须遵循：

```text
{类型}-{日期}-{作者}.md
```

类型关键词：

| 类型 | 说明 | 示例 |
|------|------|------|
| 方案 | 设计/架构决策 | `v4.3_Evidence_Library_方案-MiMoCode-2026-07-09.md` |
| 规划 | 路线图/计划 | `v4.4_路线图-MiMoCode-2026-07-10.md` |
| 修改 | 变更记录 | `v4.3_修改记录_CharacterArc-MiMoCode-2026-07-09.md` |
| 分析 | 问题分析/审查 | `模块审计-GPT意见-讨论归档.md` |
| 归档 | 历史文档 | 放 `docs/archive/` 按版本分目录 |

### 文档落库位置

```text
docs/
├── {项目名}_{类型}_{描述}.md    # 当前版本文档
├── archive/                     # 历史归档
│   ├── v2.0/                    # v2.0 时代文档
│   ├── v3.0/                    # v3.0 时代文档
│   └── v3.4/                    # v3.4 时代文档
```

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
