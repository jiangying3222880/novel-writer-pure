# GPT + Gemini 产品层分析 — 合并意见归档

> **归档日期**：2026-07-09  
> **来源**：GPT × 3（产品层诊断 + 收敛诊断 + UI 方案）+ Gemini（诊断白皮书+代码方案）  
> **前置文档**：`统一检索方案-讨论归档.md`、`知识组织方案-讨论归档.md`、`开发规范-RFC-讨论归档.md`  

---

## 共识（两份分析高度一致）

### 核心诊断

> **Story OS（Runtime）已经成熟，Product OS（工作流）尚未建立。**
> 继续给底层加能力，不如给用户加流程。

### P0 优先级达成一致

| 问题 | GPT | Gemini |
|------|-----|--------|
| 工作流断裂 | ✅ P0 | ✅ P0 |
| UI 数据未闭环 | ✅ P0 — 页面各自维护状态 | ✅ P0 — 数据孤岛化，无 SSOT |
| Observe/Publish 占位 | ✅ P0 | ✅ P0 |
| Finder 统一检索 | ✅ P1 | ✅ P1 |
| 分卷编排 | ✅ 必做 | ✅ 纵深结构 |
| 单元池 | ✅ 必做，MVP 简单版 | ✅ 物��目录组织 |

### 路线节奏达成一致

| 阶段 | 共识 |
|------|------|
| 第一 | 产品可用 — 打通全流程 |
| 第二 | 创作能力 — Volume + Unit Pool |
| 第三 | 知识能力 — Finder + Index |
| 第四 | 高级能力（图谱/分析） |

---

## 差异点（Gemini 多给的）

### 1. 具体代码方案

Gemini 给出了 `MainWindow` 重构骨架，核心机制：

```
ProjectContext（全局唯一事实源）
    ↓ 注入所有 Stage
每个 Stage 必须实现：
    activate_and_refresh()  — 进入时刷盘
    deactivate_and_save()   — 离开时落库
handle_stage_transition()   — 强制数据单向流
```

### 2. 概念升级：Page → Stage

不是单纯切页，而是"状态机关卡转换"。

### 3. Finder 具体实现

给出了第一版 `Finder` 代码（Facade 门面模式），直接读文件系统，不需要数据库 / Embedding。

### 4. 物理目录组织

分卷和单元池的第一版采用 `project.json + volume_001/unit_001.md` 的目录结构，不上数据库。

---

## Gemini 版本路线

| 版本 | 迭代核心 | 交付标准 |
|------|---------|---------|
| **v4.1** | 工作流生命线 | 重构 main_window，Stage 打通，数据单向闭环 |
| **v4.2** | 纵深结构 | ProjectContext 引入 Volume/Unit 层级 |
| **v4.3** | 检索管线 | Finder + IndexService 全面铺设 |
| **v4.4** | 能力抽象 | 从 Agent 角色 → Capability 插件 |

---

## 综合建议（合并 GPT + Gemini）

### 立即冻结
- ❌ 不再新增任何 Runtime 能力（Guide/Decision/Compiler/Graph 等）
- ❌ 不再新增任何数据库迁移

### 立即推进
- ✅ 重构 `main_window.py` — Stage 机制 + ProjectContext
- ✅ 修复 Observe/Publish 占位
- ✅ 打通项目创建 → 设定 → 写作 → 检查 → 发布全流程
- ✅ Finder 作为唯一检索入口（第一版：文件读操作收拢）

### 后续
- Volume + Unit 层级 → 物理目录结构
- Unit Pool → 简单模板
- Capability → 能力插件化

## ⚠️ 实际代码审计补充（2026-07-09 代码核实）

Gemini 的代码方案方向正确，但实现假设与当前代码库存在差异：

| Gemini 假设 | 实际代码 | 调整方向 |
|------------|---------|---------|
| PyQt6 | **PySide6** | 所有 import 需改为 `PySide6` |
| QListWidget 侧边栏 | **TreeNav**（`app/ui/widgets/tree_nav.py`） | 生命周期绑定 TreeNav 的 `page_selected` 信号 |
| 页面名 StoryPage/CreatePage 等 | **PAGE_REGISTRY 模式**，20+ 页面，page_id 驱动 | 在现有 `_select_page` 基础上加 activate/deactivate 钩子 |
| 无现有上下文 | **已有** `self.current_project: Optional[dict]` + `_notify_project_changed()` | ProjectContext 是在此基础上的增强，不是替代 |
| observe/publish 全占位 | PublishPage **真实存在**，Observe 页（story-health/guide-graph 等）有 UI 但集成深度不足 | 修复方向：注入 Context + 生命周期，而非重写 |

### 实际改动方案（最小化）

核心思路：**在现有架构上加两个钩子，不重写任何现有页面。**

1. `app/core/project_context.py` — 新建，包裹 `current_project` + `save_to_disk()`
2. `app/ui/main_window.py` — `_select_page` 加 deactivate/activate 生命周期调用
3. 逐个给 Page 加 `set_project` 增强（已有 `set_project` 方法的大多存在）

---

## 第三份分析：概念膨胀与架构收敛（2026-07-09 补充）

> **来源**：第二位 GPT（全面代码检查 5000+ 文件后）
> **核心判断**：**项目已进入"第二阶段"——Consolidation（收敛期），不是 Expansion（扩张期）。**

### 与前两份差异

前两份（GPT + Gemini）聚焦于：**"什么没做好"（工作流断裂/产品闭环缺失）**
这份聚焦于：**"什么东西已经太多了"（概念膨胀/Runtime 过重）**

两者不矛盾，是互补——一个说"做"，一个说"收"。

### 核心警告

#### 1. Runtime 过重（最大风险）
State / Guide / Memory / Compiler / Decision / Context / Session 都有 Runtime 的影子。继续下去会演变成 **God Object（万能 Runtime）**。

建议：Runtime 只负责 **生命周期、事件流、依赖、调度**，不要负责业务。

#### 2. Guide 膨胀
Advice / Suggestion / Report / Result / Issue / Recommendation 等概念接近 Guide，容易重复。

建议：**所有建议统一为 Guide**，不再出现 `Advice` / `Suggestion` / `Hint` / `Opinion` 等变体。

#### 3. Agent 有膨胀趋势
README 写的是 Agent 最后一层，但代码里 Agent 越来越多。

建议：Agent 永远只保留 Writer / Reader / Critic / Planner（可选），**其他能力以 Guide Source 形式存在**（Pressure / Memory / Consistency 等输出 Guide，不创建独立 Agent）。

#### 4. UI 落后于架构
UI 还是"功能菜单→页面→按钮"，但 Story OS 是"Observe→Think→Write→Review"的生命周期。

建议：**UI 应该围绕 Story 生命周期，而不是功能列表。**

### 最大隐患：概念越来越多

> Guide / Decision / Compiler / Memory / Pressure / Voice / Context / Runtime / Planner / Observer / Story / Session / State / Graph / Hook / Event…

**以后新模块必须回答：它属于哪一层？否则不能增加。**

### 优先级排序

| 优先级 | 建议 | 原因 |
|--------|------|------|
| ⭐⭐⭐⭐⭐ | **重新设计 UI** | 当前最影响体验，无法体现 Story OS 价值 |
| ⭐⭐⭐⭐⭐ | **收敛 Runtime 职责** | 防止演变为 God Object |
| ⭐⭐⭐⭐☆ | **统一 Guide 数据流** | 保证所有建议来源一致 |
| ⭐⭐⭐⭐☆ | **梳理 Story 生命周期** | 让 Observe→Think→Write→Review 成为主流程 |
| ⭐⭐⭐☆☆ | **删除重复概念** | 减少维护成本，降低学习曲线 |
| ⭐⭐☆☆☆ | **继续优化性能** | 后期工程，非核心问题 |
| ⭐☆☆☆☆ | **继续新增架构层** | 当前投入产出比最低 |

### 最终评分

| 维度 | 评分 |
|------|------|
| 架构理念 | 95/100 |
| 领域建模 | 90/100 |
| 模块边界 | 82/100 |
| 代码可维护性 | 85/100 |
| UI 与交互 | 60/100 |
| **整体成熟度** | **88/100** |

### 一条最重要的建议

> **从现在开始，把每一次设计决策都优先用于减少概念、明确边界、改善用户体验，而不是增加新的抽象。**

## 第四份分析：StoryWorkspace 概念与 UI 整合方案（2026-07-09 补充）

> **来源**：第四位 GPT
> **核心判断**：**主控权在人类作者，AI 只是高阶笔助。不删页面，整合而非重写。**

### 与前三份的关系

前三份分别说"做"、"改"、"收"。这份说"**合**"——给出了第四份的具体落地方式：
- 把 20 个散落的 Page 收束为**两个大工作区**（StoryWorkspace + ManagementWorkspace）
- 写作时不离开编辑器，右侧面板内嵌现有 Character/World 页面

### 核心设计

```
StoryWorkspace（写作工作区）
├── 左侧：CreatePage（正文编辑器，60%）
└── 右侧：QTabWidget（设定面板，40%）
    ├── 🦸 角色手动修改 ← 内嵌 CharacterPage
    ├── 🌍 世界观手动修改 ← 内嵌 WorldPage
    └── 🤖 AI 灵感/逻辑检查 ← 内嵌 GuidePage

ManagementWorkspace（管理大盘）
└── 独立管理页面（批量增删改设定时使用）
```

所有组件共享同一个 `ProjectContext`。

### 代码假设差异

| 假设 | 实际代码 | 调整 |
|------|---------|------|
| PyQt6 | PySide6 | 需改 import |
| `CreatePage`/`CharacterPage`/`WorldPage`/`GuidePage` 为独立文件 | 实际在 `pages.py` 中：`GeneratePage`、`CharacterMgmtPage`、`WorldviewPage` 等 | 类名需对应实际 PAGE_ID |
| sidebar QListWidget | TreeNav | 信号绑定 TreeNav.page_selected |

### 核心价值

1. **绝对主控权**：不退出编辑器，右侧面板直接改角色设定
2. **数据不断代**：所有组件共享同一个 context
3. **老代码零损耗**：现有 Page 逻辑不变，只是搬家到 QTabWidget
4. **测试直接闭环**：手动修改后，底层检查引擎拿到的是最新数据

---

*本归档已完成四轮意见综合，待决策形成 v4.3 正式路线图*
