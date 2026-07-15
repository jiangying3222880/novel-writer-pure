# 小说写作助手 v4.3 — Story OS 架构

> 版本：4.3.0
> 日期：2026-07-09
> 架构：事件驱动 + 多智能体 + 决策编译器 + 故事状态机

> ⚠️ **本项目状态**：活跃开发中。v4.3 完成 Character Arc 激活 + reverse_compile 修复，持续迭代。

> 🚀 **想用 AI Agent 跑这套方法论？** → 用 sister project [**story-engine-skill**](https://github.com/jiangying3222880/story-engine-skill)（活跃维护，每周迭代，纯 Markdown skill）

> 📚 **本项目适合**：贡献代码 / 学习架构 / 作为 Story Engine 参考实现

> 📋 **Agent 指南**：[`AGENTS.md`](./AGENTS.md) — 项目级 Agent 规范（红线原则 / 架构约定 / 工具使用 / 文档规范），所有 AI 工具通过符号链接自动读取

---

## 一、设计哲学（项目宪法）

> **Novel Writer Pure 是一套 Story Engine。**
>
> 它不替作者决定故事，也不替 AI 决定写法；
> 它持续维护故事状态、因果关系与创作建议，
> 让 AI 与作者始终在同一个故事事实上协作。

Novel Writer Pure 不是"约束 AI 的工具"，也不是"替作者决策的系统"。
它是**让 AI 和作者在充分理解故事的前提下完成创作的伙伴**。

### 三角色职责分离

| 角色 | 职责 | 不该做的事 |
|------|------|------------|
| **作者** | 创意、决策、最终判断 | 不该被系统的硬规则绑架 |
| **AI** | 生成文本、提出实现方案 | 不该在没有上下文的真空里硬写 |
| **Story Engine** | 维护故事状态、因果关系、创作建议 | **不该替任何人做决定** |

### 核心原则：Guidance 而非 Constraint

**Guidance（引导）**：系统提供完整、可解释的故事状态和创作建议，让 AI 和作者在充分理解故事目标的前提下完成创作。

**Constraint（约束）**：系统用硬规则强制 AI 必须如何写、不能如何写。

我们选择 **Guidance**。

```
旧模式（Constraint）              新模式（Guidance）
─────────────                    ─────────────
"不能写解释情绪的句子"   →       "本章基调是不安，建议用动作代替心理注解"
"不能在高压区开新钩子"   →       "目前叙事压力处于 red zone，建议先收束旧钩子"
"必须用反 AI 味清单"     →       "本章有 3 处 AI 味嫌疑（已高亮），供参考"
"一致性冲突 → 拒绝生成"   →       "一致性冲突 → 报告冲突（5 维）+ 给出 3 个处理建议"
```

**Score 是判决，Advice 是建议。**

### 接口契约（Guide）

所有模块（压力 / 记忆 / 一致性 / 声音 / 风格）统一输出 `Guide` 对象：

```python
@dataclass
class Guide:
    source: str              # "pressure" / "memory" / "voice" / "consistency"
    priority: float          # 0-1，紧急度
    confidence: float        # 0-1，置信度
    scope: str               # "unit" / "scene" / "paragraph"
    advice: str              # 人话建议（核心字段）
    reason: str              # 为什么提这个建议
    evidence_ids: list       # 证据链（Paragraph ID / Hook ID / Event ID）
    possible_actions: list   # 可选处理方案
    conflicts_with: list     # 冲突的 Guide ID
    supports: list           # 支持的 Guide ID
```

> **`evidence_ids` 是整个系统最值钱的一行。**
> 以前 AI 说"人物 OOC"不知道为什么；以后 Guide 说"女主此时不应知道男主身份"，证据是 Paragraph 23 / 46 / Hook 18。
> **从"感觉"变成"证据"——这是 Story Engine 最需要的。**

### 核心能力

> **核心价值主张：Explainable AI + 创作权衡可见**

- **每个建议都有证据**（evidence_ids）—— 不是"感觉"，是"事实"
- **每个判断都可追溯**（Guide Graph）—— 不是"判决"，是"权衡"
- **每个决策都有记录**（Decision 层）—— 不是"黑盒"，是"日志"
- **每个修改都有影响分析**（Story Compiler）—— 不是"试错"，是"编译"

---

## 二、三句宪法

1. **StoryState 是唯一真相源（SSOT）**：UI / Agent / Prompt 都不能存状态
2. **Guide 是"决策信号"，不是文本建议**：从"建议这样写"→ `severity + scope + evidence + instruction`
3. **Agent 是"模拟系统"，不是工具调用**：同一世界状态下的多视角思考

---

## 三、10层架构

```
┌────────────────────────────────────────────────────────────┐
│                        🧑 USER / AUTHOR                    │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                         🖥 UI LAYER                         │
│  Story / Create / Observe / Publish                        │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                    🧠 STORY ENGINE CORE                    │
│                 (Single Source of Truth)                   │
│  StoryState: Book / Units / Characters / Hooks            │
│            / Memory Graph / Pressure / Timeline            │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                     🎯 GUIDE ENGINE                         │
│  Sources: Pressure / Memory / Consistency / Voice / Hook   │
│  Output: list[Guide] — severity weighted + evidence linked  │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                 🧩 AGENT SIMULATION LAYER                  │
│  Writer / Reader / Critic / Memory + Voice Agents          │
│  → 每个 Agent 收 StoryState + Guides，输出 opinions        │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                ⚖️ DECISION / RESOLUTION LAYER              │
│  merge(agent_outputs, guides) → 冲突检测 → 权重矩阵        │
│  → 策略选择 (DELAY/EXPLODE/RESOLVE/DETOUR) → FINAL CMD    │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                     ✍ GENERATION LAYER                     │
│  LLM Writer: StoryState snapshot + Guides + Final CMD      │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                  🔁 EVENT & STATE SYSTEM                   │
│  Event Bus → Event Store → Reducer → StoryState            │
└────────────────────────────────────────────────────────────┘
```

---

## 四、模块说明

### story/ 包（Story OS 核心）

| 模块 | 功能 | 核心 API |
|------|------|----------|
| `story/state/` | 不可变叙事状态快照 | `StoryState`, `StateBridge`, `apply_event()` |
| `story/events/` | 事件类型 + 归约器 + 持久化 | `StoryEvent`, `reduce()`, `EventStore` |
| `story/guide/` | 5源信号收集 | `GuideCollectorV2.collect()` |
| `story/decision/` | 策略选择（4种策略） | `decide(signals)` → `StrategyResult` |
| `story/prompt/` | SUC编译 + token预算 | `build_suc()` + `compile()` |
| `story/engine/` | 全链路面貌（无状态） | `StoryEngine.run_unit()` |
| `story/runtime/` | 连接数据库的运行器 | `UnitRunner.run()` |
| `story/ui/` | UI事件桥接 | `UIStateBridge.on_state_change()` |

### app/ 包（应用层）

| 模块 | 功能 |
|------|------|
| `app/core/` | 基础设施：配置、DI容器、事件总线、类型 |
| `app/db/` | 数据库层：SQLite + 41个迁移 |
| `app/ai/` | LLM集成：提供者、路由、缓存、降级 |
| `app/agents/` | 智能体系统：编排器 + 8个辅助Agent |
| `app/services/` | 业务逻辑：56个服务文件 |
| `app/ui/` | PySide6界面：标签页、组件、主题 |

---

## 五、完整数据流

```
数据库 (StoryUnitV2)
    ↓ StateBridge.from_unit_v2()
StoryState (不可变快照)
    ↓ collect_signals() 或 GuideCollectorV2.collect()
    │  (5个源: 压力/记忆/一致性/风格/伏笔)
list[DecisionSignal]
    ↓ compute_dimension_vector() → decide()
    │  (6个维度, 4种策略, 冲突检测)
StrategyResult (策略 + 指令)
    ↓ build_suc()
StoryUnderstandingContext (4段: 角色/世界/伏笔/张力)
    ↓ compile()
CompiledPrompt (LLM可直接使用的消息)
    ↓ UIStateBridge.on_state_change()
EventBus "story.state_updated" → UI组件刷新
```

---

## 六、4种叙事策略

| 策略 | 名称 | 场景 |
|------|------|------|
| DELAY | 延后 | 不爆发冲突，继续铺垫 |
| EXPLODE | 爆发 | 强情绪释放 + 角色冲突 |
| RESOLVE | 收束 | 解决伏笔 + 回收记忆 |
| DETOUR | 偏移 | 绕开冲突，转移叙事焦点 |

---

## 七、故事单元模式

### 核心理念

> **单元是创作单位，章节是发布单位。先以单元创作完整故事，再在读者最有感觉的地方断章。**

### 双时间线

- **故事时间（story_order）**：事件在故事世界里发生的先后顺序
- **呈现时间（present_order）**：读者阅读时看到的先后顺序

### 拆章流程

1. 选中已完成的单元
2. 选择断章策略（自动/爽文/悬疑/感情/节奏/平稳）
3. 点击"分析断章点"
4. 系统呈现断章报告（候选位置 + 痛感评级）
5. 用户确认/调整断点
6. 执行拆章 → 创建章节

### 双模式（新/老项目）

- **新项目**：有 story_units，默认单元视图
- **老项目**：只有 chapters，默认章节视图，可升级到单元模式
- **自动切换**：打开项目时自动检测类型，设置默认视图

---

## 八、界面模块

### 故事模块
- 小说设定
- 世界观
- 角色管理
- 单元大纲

### 创作模块
- 当前创作（章节生成）
- 故事单元（单元管理）
- 项目管理
- 自动进化

### 观察模块
- 故事健康
- 引导图谱
- 用量分析
- 知识库

### 发布模块
- 导出
- AI模型
- 外观
- 日志

---

## 九、测试

### 烟雾测试

```bash
cd D:\novel-writer-pure-v4.0

# 运行所有烟雾测试
python smoke/smoke_v4_state.py          # 状态系统测试
python smoke/smoke_v4_guide_decision.py  # 引导+决策测试
python smoke/smoke_v4_prompt.py          # 提示系统测试
python smoke/smoke_v4_runtime.py         # 运行循环测试
python smoke/smoke_v4_isolation.py       # 智能体隔离测试
python smoke/smoke_v4_publish.py         # 发布模块测试
```

### 测试结果

- 6/6 烟雾测试通过
- 35+ 个断言全部通过

---

## 十、开发计划

### 已完成

- [x] 第0阶段：项目引导
- [x] 第1阶段：事件系统
- [x] 第2阶段：引导引擎
- [x] 第3阶段：决策层
- [x] 第4阶段：提示系统
- [x] 第5阶段：智能体模拟
- [x] 第6阶段：运行循环
- [x] 第7阶段：界面基础
- [x] 第8阶段：界面页面
- [x] 第9阶段：集成测试
- [x] 功能补全：因果图+情绪分析+因果审查
- [x] 功能补全：单元UI+记忆迁移
- [x] 功能补全：双模式（新/老项目）

### 待做

- [ ] 发布模块重写（拆章交互UI）
- [ ] 完整的情绪曲线可视化
- [ ] 性能优化

---

## 十一、版本历史

### v4.3.0 (2026-07-09)

- 源码级审查后架构收敛：项目已有80%基础设施，不新建表不造冗余系统
- Character Arc 激活：从 book_outlines.character_arcs 死数据变成活系统，接入 Guide
- reverse_compile evidence_id 修复：模式提取结果可被 Guide 检索
- 修复 unit_type 验证失败（VALID_TYPES 添加 virtual + migration 054 SQLite CHECK 约束）
- 修复 pressure.py 连接未定义（import get_conn）
- 修复导航双入口冗余（删除重复的 novel-settings 入口）
- 100 个 Chapter 全部成功包装为 Virtual Unit
- 设计文档：v4.3_Evidence_Library_设计文档.md

### v4.1.0 (计划中)

- 收口方案制定：清理死代码 → 接入story链路 → 产品化完善 → 验证验收
- 8项优化建议（DeepSeek反馈）：草稿反向导入、冲突解决日志、增量补丁、常识时间线断言、反向编译、已有内容导入、对话式项目创建、单元池+分层知识库
- 验收标准：因果图服务真写入、情绪曲线分析器非AI实现、编排师因果审查调用、写后因果更新、单元UI接入

### v4.0.0 (2026-07-06)

- 从v3.4重构，保留成熟模块，重写问题模块
- **Phase 0-9 完整开发流程**：项目引导 → 事件系统 → 引导引擎 → 决策层 → 提示系统 → 智能体模拟 → 运行循环 → 界面基础 → 界面页面 → 集成测试
- 新增Story OS核心：StoryState + Event + Guide + Decision + Prompt
- 新增智能体隔离内核 + 4个Agent（Writer/Reader/Critic/Memory）
- 新增因果图服务 + 情绪分析器 + 编排师因果审查
- 新增双模式（新/老项目自动切换）
- 界面：故事仪表盘 + 故事单元管理
- 测试：6个烟雾测试，35+断言

### v3.4 (2026-06-24)

- 全面审计报告完成
- 故事单元模式设计文档（v1~v5）
- 大纲架构重构设计文档（分卷单元章节）
- Story Engine 路线图 + UI-v4 蓝图（GPT评审整合）
- 单元驱动编排重构计划（v2/v3/v5多版本迭代）
- Story Engine + 故事引导验证报告

### v3.0 (2026-06-05+)

- v3.0功能实施
- UI同步更新
- 代码清理与重构

### v2.0 (2026-05-22)

- 6大集群架构改造
- 插件化架构重构
- 7 Agent私有记忆机制
- 5个agent统一到BaseAgent
- Ruff Lint 229个问题全量修复

### v1.0 (2026-05-17)

- 章节标题对齐大纲 + 各步汇报事实时同步到UI
- 完整项目架构重写（基于inkos改进）
- AI导入分批请求策略
- meta.outline自动写入修复

---

## 十二、依赖

```
PySide6 >= 6.5
numpy
scikit-learn
jieba
requests
```

---

## 十三、启动

```bash
cd D:\novel-writer-pure-v4.0
python -m app
```
