# v4 Story OS GPT 评审全量整合

> **评审日期**: 2026-07-06  
> **评审来源**: GPT 对 Novel Writer Pure v3.4 的深度系统级评审  
> **文档定位**: v4 系统宪法 + 工程蓝图 + 开发路线图  
> **核心理念**: Guidance 而非 Constraint  
> **核心命题**: 从 AI 写作工具 → Story Operating System（故事操作系统）

---

## 目录

- [一、系统诊断](#一系统诊断)
- [二、v4 核心定义](#二v4-核心定义)
- [三、10 层全链路架构](#三十层全链路架构)
- [四、三大子系统详解](#四三大子系统详解)
  - [StoryState 唯一真相源](#1-storystate唯一真相源)
  - [Guide Engine 决策信号](#2-guide-engine决策信号)
  - [Agent Simulation 多视角模拟](#3-agent-simulation多视角模拟)
- [五、Decision Layer 最终裁决器](#五decision-layer-最终裁决器)
- [六、Prompt OS 编译器](#六prompt-os-编译器)
- [七、Agent 防污染体系](#七agent-防污染体系)
- [八、UI × Story OS 绑定](#八ui--story-os-绑定)
- [九、UI Runtime Event System](#九ui-runtime-event-system)
- [十、工业级可部署架构](#十工业级可部署架构)
- [十一、完整工程目录](#十一完整工程目录)
- [十二、6 周可落地开发路线](#十二6-周可落地开发路线)
- [十三、文件级施工图](#十三文件级施工图)
- [十四、实现优先级 Checklist](#十四实现优先级-checklist)
- [十五、与当前系统对照](#十五与当前系统对照)

---

## 一、系统诊断

### 当前真实状态

> 当前项目**不是 v3.4**，而是**"半 v4.0 形态"**。

**已经具备的**：

- `app/agents/orchestrator.py` — 编排中枢
- `app/ai/router.py` — LLM 路由系统
- `app/core/event_bus.py` — 事件系统
- `app/core/types.py` — 类型统一层
- `app/core/container.py` — DI 容器
- `app/db/migrator.py` — 状态持久化

→ **一个"事件驱动 + Agent 编排 + LLM 路由"的 Story Engine 原型**

**缺失的**：

- ❌ Story State Machine（单一真相源）
- ❌ Guide System 未进入执行层（只是 prompt 附加，不是决策输入）
- ❌ Agent 之间没有博弈（顺序调用，不是并行辩论→收敛）
- ❌ UI 停留在章节软件时代（Engine 已升级，UI 未跟上）

### 最大结构性问题

| 问题 | 现状 | v4 需求 |
|------|------|------|
| Orchestrator 定位 | 流程中心 | 状态中心（State Driven） |
| AI Router | 选模型 | 理解故事状态 |
| Event Bus | UI 通信 / 状态通知 | Story Event Graph（故事因果链）|
| Prompt | 拼接式 | 编译式（编译器，非拼接器）|

---

## 二、v4 核心定义

### 一句定性

> **v4 不是"AI 写小说工具"，而是"事件驱动 + 多智能体 + 决策编译器 + 故事状态机"** — 一个可运行的故事操作系统（Story OS）。

### 三句宪法

| # | 层 | 定义 |
|:--:|------|------|
| 1 | **StoryState** | 世界事实 — 所有模块不存状态，只有它是真相 |
| 2 | **Guide** | 决策信号 — 不是规则，是带 severity 的可排序影响力 |
| 3 | **Agent** | 多视角思考模拟 — 不是多个 AI，是同一世界的不同思维角度 |

### 五个结构原则

1. **StoryState 是唯一真相源（SSOT）**：UI / Agent / Prompt 都不能存状态
2. **Guide 是"决策信号"，不是文本建议**：从"建议这样写"→ `severity + scope + evidence + instruction`
3. **Agent 是"模拟系统"，不是工具调用**：同一世界状态下的多视角模拟
4. **Prompt = 编译器，不是拼接器**：`StoryState → Guide → Agent → Decision → Instruction → LLM`
5. **UI = Story State 可视化器**：UI 不是功能集合，而是 Story State Renderer

---

## 三、10 层全链路架构

```
┌────────────────────────────────────────────────────────────┐
│                        🧑 USER / AUTHOR                    │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                         🖥 UI LAYER                         │
│                                                            │
│  Story / Create / Observe / Publish                        │
│  - Story HUD (always-on state panel)                      │
│  - Unit Editor (primary workspace)                         │
│  - Graph / Timeline / Inspector (side panels)             │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                    🧠 STORY ENGINE CORE                    │
│                 (Single Source of Truth)                   │
│                                                            │
│  StoryState: Book / Units / Characters / Hooks            │
│            / Memory Graph / Pressure / Timeline            │
│  → state is immutable + event-sourced                      │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                     🎯 GUIDE ENGINE                         │
│          (From "rules" → "decision signals")              │
│                                                            │
│  Sources: Pressure / Memory / Consistency / Voice / Hook   │
│  Output: list[Guide] — severity weighted + evidence linked  │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                 🧩 AGENT SIMULATION LAYER                  │
│          (internal "story committee", not one AI)          │
│                                                            │
│  Writer Agent / Reader Agent / Critic Agent               │
│  + Memory Agent + Style Agent                              │
│  → 每个 Agent 收 StoryState + Guides，输出 opinions        │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                ⚖️ DECISION / RESOLUTION LAYER              │
│                                                            │
│  merge(agent_outputs, guides) → 冲突检测 → 权重矩阵        │
│  → 策略选择 (DELAY/EXPLODE/RESOLVE/DETOUR) → FINAL CMD    │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                     ✍ GENERATION LAYER                     │
│  LLM Writer: StoryState snapshot + Guides + Final CMD      │
│  → Story Unit Text + Paragraph UUIDs                       │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                  🔁 EVENT & STATE SYSTEM                   │
│  Event Bus → Event Store                                  │
│  UnitCompleted / CharacterStateChanged / HookPlanted       │
│  → updates StoryState (event-sourced rebuild)            │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                     📊 OBSERVABILITY LAYER                │
│  Story Graph / Character Inspector / Pressure Curve       │
│  Memory Heatmap / Hook Lifecycle（→ "Observe" UI）        │
└────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────┐
│                     📦 PUBLISH LAYER                       │
│  Unit → Chapter Compiler → Chapter Splitter               │
│  → Platform Adapter → Exporter (TXT/EPUB/Web)             │
└────────────────────────────────────────────────────────────┘
```

### 完整闭环数据流

```
User selects Unit
  ↓
StoryEngine.get_state()
  ↓
GuideCollector.collect(state, unit)
  ↓
GuideResolver.resolve()
  ↓
Agent Simulation (Writer / Reader / Critic)
  ↓
Decision Layer（冲突检测 → 权重矩阵 → 策略选择 → 最终裁决）
  ↓
Prompt OS Compiler (SUC: Structural → Dynamic → Causal → Guidance)
  ↓
LLM Generation
  ↓
Event Store append → Reducer → StoryState 更新
  ↓
UIStateBridge diff push → UI 刷新
```

---

## 四、三大子系统详解

### 1. StoryState——唯一真相源

**本质**：所有故事信息的"唯一真实内存"。

**结构**：

```python
@dataclass
class StoryState:
    book: BookState           # 书名/题材/风格/字数
    units: dict[str, UnitState]       # StoryUnit 状态
    characters: dict[str, CharacterState]  # 角色状态
    hooks: dict[str, HookState]        # 伏笔系统
    memory: MemoryState               # L1-L4 记忆
    pressure: PressureState           # 叙事压力
    timeline: TimelineState           # 双时间线
    events: list                      # Event Store pointer
    version: int
```

**各类子状态**：

| 子状态 | 核心字段 |
|--------|------|
| UnitState | id / goal / status / story_order / present_order / paragraph_ids / open_hooks / resolved_hooks |
| CharacterState | id / name / position / emotion / goal / relations / last_seen_unit |
| HookState | id / type(plant/payoff/reminder) / source_unit / target_unit / status(active/resolved/expired) / importance |
| MemoryState | facts / events / l1 / l2 / l3 / l4 |
| PressureState | narrative / character / tension / reader |
| TimelineState | story_order_index / present_order_index / current_time_pointer |

**铁律**：

- ❌ UI 不能存状态
- ❌ Agent 不能存状态
- ❌ Prompt 不能存状态
- ✔ 只有 StoryState 是真相
- ✔ State = Event replay 的结果，不可直接修改

### 2. Guide Engine——决策信号

**本质**：把"规则"变成"可排序的建议信号"。

**Guide 统一结构**：

```python
@dataclass
class Guide:
    source: str           # pressure / memory / consistency / voice / hook
    severity: float       # 0~1
    advice: str           # 人话建议
    scope: str            # unit / character / global
    evidence_ids: list[str]  # 证据链
    conflicts_with: list[str]
    supports: list[str]
```

**5 个 Guide Source**：

| Source | 产出 |
|--------|------|
| PressureGuide | 叙事压力信号（红区应回收钩子 / 绿区可铺垫） |
| MemoryGuide | 历史一致性信号（N 章前承诺未回收） |
| ConsistencyGuide | 逻辑一致性信号（角色不应知道某信息） |
| VoiceGuide | 风格一致性信号 |
| HookGuide | 伏笔管理信号 |

**收集流程**：`StoryState → Pressure/Memory/Consistency/Voice/Hook → list[Guide]`

**核心原则**：

- Guide 不是规则，是"影响写作的信号"
- 必须按 severity 排序
- 必须允许冲突，冲突由 Resolver 决定

### 3. Agent Simulation——多视角模拟

**本质**：不是多个 AI，而是"同一故事状态的不同思维视角"。

**Agent 清单**：

| Agent | 角色 | 输出 |
|-------|------|------|
| WriterAgent | 写作倾向 | 创作建议 |
| ReaderAgent | 感受反馈 | 情感反应、流失风险 |
| CriticAgent | 逻辑检查 | 一致性检查 |
| MemoryAgent | 历史一致性 | 伏笔/承诺状态 |
| VoiceAgent | 风格一致性 | 风格建议 |

**输入统一**：`StoryState + Guides`  
**输出**：`opinions + conflicts + risks`  
**本质作用**：不是生成文本，而是"模拟读者 + 作者 + 编辑的脑内会议"

**防污染铁律**：

- 每个 Agent 只能看到自己的输入，看不到其他 Agent 的输出
- Agent ↔ Agent 禁止（单向流 Agnets → Aggregator）
- 输出必须结构化，不允许自由文本
- 只有 Aggregator 能理解冲突并决定最终路径

---

## 五、Decision Layer——最终裁决器

**本质**：把多个脑的冲突压缩成唯一可执行写作指令。

**输入 / 输出**：

```python
class DecisionContext:
    story_state: StoryState
    guides: list[Guide]
    agent_outputs: dict[str, AgentOutput]

class WritingDecision:
    final_instruction: str         # 最终指令
    selected_guides: list[Guide]    # 被采纳的 Guide
    overridden_agents: list[str]    # 被覆盖的 Agent
    narrative_strategy: str         # 叙事策略
    risk_notes: list[str]           # 风险标注
```

**核心流程 4 步**：

```
冲突检测 → 权重矩阵 → 策略选择 → 指令压缩
```

**权重计算**：

```python
final_score = (
    guide.severity * 0.5 +
    pressure.weight * 0.3 +
    narrative_phase.weight * 0.2
)
```

**4 类叙事策略**：

| 策略 | 名称 | 场景 |
|------|------|------|
| DELAY | 延迟策略 | 不爆发冲突，继续铺垫 |
| EXPLODE | 爆发策略 | 强情绪释放 + 角色冲突 |
| RESOLVE | 收束策略 | 解决伏笔 + 回收记忆 |
| DETOUR | 偏移策略 | 绕开冲突，转移叙事焦点 |

**核心原则**：

- Decision Layer 不是"选择内容"，而是"选择叙事路径"
- Agent 不能决定剧情，只能提建议
- Guide 是权重信号，不是规则
- 最终只有一个输出：ONE instruction → ONE LLM call

---

## 六、Prompt OS 编译器

**本质**：把 StoryState 编译成"故事理解上下文（SUC）"，告诉 LLM **"故事世界现在是什么状态"**。

**核心洞察**：

> 你不应该把 StoryState 喂给 LLM。  
> 你应该编译成 SUC（Story Understanding Context）——结构化、分层、人类可读 + 机器可落地的叙事状态表示。  
> 不是数据，不是 prompt，而是"故事的压缩心智模型"。

**4 层编译管道**：

```
StoryState
   ↓
1. Structural Layer (WHAT EXISTS)     → [STRUCTURE] Book / Characters / Units
   ↓
2. Dynamic Layer (WHAT IS HAPPENING)  → [DYNAMIC STATE] Active Unit / Open Hooks / Pressure
   ↓
3. Causal Layer (WHY IT MATTERS)      → [CAUSAL CONTEXT] Recent Events / Consequences / Unresolved
   ↓
4. Instruction Layer (WHAT TO DO)     → [WRITING GUIDANCE] Priority rules + Writer focus
   ↓
LLM Input Context (SUC)
```

**Prompt DSL**：

```python
@dataclass
class PromptDSL:
    context: str           # story snapshot
    state: str             # dynamic state
    causality: str         # reasoning layer
    instructions: str      # guide layer
    constraints: list[str]
    priorities: list[tuple[str, float]]
```

**编译流程**：`SUC → Section Builder → Weight Assigner → Conflict Resolver → Instruction Stabilizer → Prompt Renderer → LLM Input`

**Prompt OS 三项核心能力**：

1. **权重系统**：Guide A (0.9) overrides Guide B (0.4) — 控制信号优先级
2. **冲突消解**：Memory 说必须揭露 / Consistency 说不能揭露 → 输出 delayed reveal strategy
3. **幻觉压制**：`Only use provided state. Do not invent new characters. Do not extend timeline.`

**禁止做法**：

- ❌ 灌 StoryState JSON
- ❌ 40 个字段同时丢进去
- ❌ 各模块各自 append prompt text

---

## 七、Agent 防污染体系

**核心机制 —— Agent Isolation Kernel**：

```python
class AgentContext:
    story_state: StoryState
    guides: list[Guide]
    agent_role: str
    # ❌ 禁止: other_agents_outputs
```

**执行流程**：

```
StoryState → Parallel Agent Execution (isolated)
  → Each outputs: opinion + risk + suggestion
  → NO CROSS TALK
  → Aggregator (ONLY HERE merge)
  → Decision Layer
```

**三个污染控制规则**：

1. **单向流**：Agents → Aggregator，NOT Agents ↔ Agents
2. **输出结构化**：不允许自由文本，必须是 AgentOutput dataclass
3. **Aggregator 独裁**：只有 Aggregator 能理解冲突并决定最终路径

**Prompt OS 与 Agent Simulation 的关系**：

> Prompt OS 负责"让 AI 看懂故事"  
> Agent Simulation 负责"让 AI 不互相污染"

---

## 八、UI × Story OS 绑定

**定义**：UI 不再"控制写作"，UI = Story OS 的"可视化投影 + 操作入口"。

**核心架构**：

```
Story Engine (SSOT)
  ↓
UI State Bridge Layer  ← ⭐ 关键层
  ↓
HUD View / Unit Editor / Graph View
```

**UI State Bridge**：

```python
class UIStateBridge:
    def subscribe(self, ui_component): ...
    def push_state_update(self):
        state = self.engine.state
        diff = self.compute_diff(state)
        for sub in self.subscribers:
            sub.on_state_update(state, diff)
```

→ UI 不读取 state，而是**订阅 state diff**

**三大 UI 模块绑定**：

| 模块 | 定位 | 绑定 | 禁止 |
|------|------|------|------|
| HUD | 故事状态仪表盘 | `StoryState.pressure / active_units / open_hooks / character_state` | 不能修改 state |
| Unit Editor | Decision Layer 交互终端 | `UnitState → Guide → Decision → Prompt Preview → LLM Output` | 不控制逻辑 |
| Graph View | 因果可视化 | `EventStore → Node(event) → Edge(causality)` | — |

**四条 UI 铁律**：

1. UI 不能持有状态：`❌ UI.state = local cache`，`✔ UI = projection`
2. 所有变化来自 Event：`UI change → emits UIEvent → StoryEngine`
3. UI 只能"建议"，不能"决定"：`UI → suggest`，`DecisionLayer → decide`
4. UI 必须可重建：`UI = function(StoryState)`

**v3 UI 与 v4 UI 的对比**：

| v3 UI | v4 UI |
|------|------|
| UI = 操作工具 | UI = Story Runtime Inspector |
| 页面 = 功能入口 | 页面 = 状态的多视图投影 |
| Tab = 工具集合 | Tab = Decision Layer 交互终端 |

---

## 九、UI Runtime Event System

**核心定义**：UIEvent System = 把"人类操作"翻译成"故事因果事件"的编译器。

**完整闭环**：

```
UI Action
  ↓ UIEvent
UIEventTranslator         ← 把 UI 操作 → 语义意图
  ↓ SemanticIntent
StoryEventFactory         ← 收敛为结构化 StoryEvent
  ↓ StoryEvent
EventValidator            ← 防 UI 乱改 Story State
  ↓
EventStore.append()
  ↓
StoryReducer.apply()      ← Event → State
  ↓
StoryState updated
  ↓
UIStateBridge diff push
  ↓
UI refresh
```

**核心三层**：

| 层 | 类 | 输入 | 输出 |
|----|-----|------|------|
| UI 事件 | `UIEvent` | 原始 UI 操作 | `{source, action, target, payload}` |
| 语义意图 | `SemanticIntent` | UIEvent | `{type, scope, unit_id, data}` |
| 故事事件 | `StoryEvent` | SemanticIntent | `{id, type, payload, causality}` |

**StoryEvent 必须带 `causality`**：

```json
{
  "caused_by": "UI:UnitEditor",
  "linked_hook": "hook_17",
  "affects": ["character_3", "timeline"]
}
```

**三大原则**：

1. UI 不能直接影响 StoryState：`UI → Event → State`，不是 `UI → State`
2. 所有修改必须走 Event：没有 Event 管线之外的 mutation
3. Event 必须可回放：`Story = replay(EventStore)`

**这一层的战略意义**：

- UI 完全解耦：UI 可以随便改，不影响故事逻辑
- 多编辑器冲突消失：所有操作都变成 Event
- 支持回放 / 撤销 / 分支剧情：Event replay → 生成 alternate timeline
- Story OS 真正"可运行"：不是编辑器，是可执行叙事机器

---

## 十、工业级可部署架构

### 四层三流

```
UI LAYER (HUD / Unit Editor / Graph / Inspector / Timeline)
  ↓ UIEvent Stream
EVENT INTERPRETATION LAYER (UIEvent → Intent → StoryEvent → Validation → Store)
  ↓ Event Stream
STORY INTELLIGENCE LAYER
  ├─ Story State Engine (SSOT)
  ├─ Guide Engine (Pressure / Memory / Voice / Hook / Consistency)
  ├─ Agent Simulation (Writer / Reader / Critic / Memory)
  ├─ Decision Layer (Conflict → Strategy → Collapse)
  ├─ Story Graph (Causal DAG)
  └─ Memory System (L1-L4 + Event-backed retrieval)
  ↓ Instruction Stream
GENERATION LAYER
  ├─ Prompt Compiler (SUC → Instruction Set)
  ├─ Prompt Stabilizer (anti-drift / anti-hallucination)
  ├─ LLM Router (OpenAI / Claude / Local)
  ├─ Streaming Writer
  └─ Output Validator
  ↓ Event Write-back
RUNTIME LOOP LAYER (Reducer → Snapshot → Diff Engine → UI Bridge)
```

### 三大循环系统

| Loop | 名称 | 链路 | 职责 |
|------|------|------|------|
| 🔵 | Writing Loop | State → Guides → Decision → Prompt → LLM → Event → State | 写出内容 |
| 🟡 | Agent Loop | State → Writer/Reader/Critic → Conflict → Decision | 理解故事 |
| 🔴 | Evolution Loop | EventStore → Reducer → Graph → Memory Compression → Pressure Recalc → Guide Rebalance | 故事成长 |

### 工业部署结构

```
story-os/
  services/
    ui-service/
    event-service/
    story-engine-service/
    guide-service/
    decision-service/
    prompt-service/
    llm-service/
    graph-service/
    memory-service/
  infra/
    redis/
    kafka (event stream)
    postgres (state snapshot)
```

### Kafka 事件驱动

```
UIEvent → Kafka:UI
Intent → Kafka:Intent
StoryEvent → Kafka:Event
StateUpdate → Kafka:State
GuideUpdate → Kafka:Guide
Decision → Kafka:Decision
LLMOutput → Kafka:Output
```

---

## 十一、完整工程目录

```
novel_writer_v4/
├── app/
│   ├── story/                    # 🧠 Story OS 核心（唯一真相源）
│   │   ├── state/
│   │   │   ├── story_state.py
│   │   │   ├── book_state.py / unit_state.py / character_state.py
│   │   │   ├── hook_state.py / memory_state.py / pressure_state.py
│   │   │   └── timeline_state.py
│   │   ├── events/
│   │   │   ├── base_event.py / unit_events.py / character_events.py
│   │   │   ├── hook_events.py / event_store.py
│   │   │   └── event_factory.py / event_validator.py
│   │   ├── engine/
│   │   │   ├── story_engine.py (⭐ Facade入口)
│   │   │   ├── reducer.py / snapshot.py
│   │   └── graph/ -> story_graph.py
│   │
│   ├── guide/                    # 🎯 Guide Engine
│   │   ├── guide.py / collector.py / resolver.py / ranking.py
│   │   └── sources/
│   │       ├── pressure.py / memory.py / consistency.py
│   │       └── voice.py / hook.py
│   │
│   ├── agents/                   # 🤖 Agent Simulation
│   │   ├── base_agent.py / writer_agent.py / reader_agent.py
│   │   ├── critic_agent.py / memory_agent.py / voice_agent.py
│   │   ├── orchestrator.py / isolation.py (🔥 防污染核心)
│   │
│   ├── decision/                 # ⚖️ 决策层
│   │   ├── decision_engine.py / conflict_detector.py
│   │   ├── strategy_selector.py / priority_matrix.py
│   │   └── narrative_policy.py
│   │
│   ├── prompt/                   # 🧠 Prompt OS
│   │   ├── compiler.py / renderer.py / schema.py / stabilizer.py
│   │   └── sections/
│   │       ├── structure.py / dynamic.py / causal.py / guidance.py
│   │
│   ├── llm/
│   │   ├── router.py / providers/openai.py / providers/claude.py
│   │
│   ├── runtime/
│   │   ├── unit_runner.py (⭐ run_unit)
│   │   ├── chapter_compiler.py / pipeline.py
│   │
│   ├── ui/
│   │   ├── bridge/
│   │   │   ├── ui_state_bridge.py / ui_event_mapper.py
│   │   │   ├── subscription_manager.py / diff_stream.py
│   │   ├── story_hud/ / unit_editor/ / graph_view/ / inspector/
│   │
│   ├── db/
│   │   ├── sqlite.py / migrations/
│   │
│   └── main.py (🚀 启动入口)
```

---

## 十二、6 周可落地开发路线

### 总体策略：必须按依赖顺序构建

```
Event 系统 → State 系统 → Guide 系统 → Decision 系统 → Prompt 系统 → UI 系统 → Agent 系统
```

### Week 1 — Event OS（系统地基）

**目标**：让系统"能记录一切"

- `StoryEvent` + `EventStore` (append-only) + `EventValidator` + `EventReplay`
- UIEvent → StoryEvent pipeline
- 验收：能记录 UI 操作、能回放事件

### Week 2 — StoryState Engine（世界）

**目标**：让系统"有世界"

- `StoryState` + `Reducer` (Event → State) + `Snapshot`
- Unit / Character / Hook 状态结构
- 验收：删除 state 仍可从 event 重建

### Week 3 — Guide Engine（信号系统）

**目标**：系统开始"会思考"

- `Guide` + `GuideCollector` + 5 个 Guide Source
- severity 体系建立
- 验收：每个 Unit 能生成 Guides，可排序，可解释

### Week 4 — Decision Layer（大脑）

**目标**：系统"开始做选择"

- `DecisionEngine` + `ConflictDetector` + `StrategySelector` + `PriorityMatrix`
- 4 类策略：DELAY / EXPLODE / RESOLVE / DETOUR
- 验收：多 Agent 冲突可检测，有唯一 Strategy 输出

### Week 5 — Prompt OS + LLM（表达层）

**目标**：系统"能写小说"

- `PromptCompiler` + `SUCBuilder` + `Stabilizer`
- StoryState → SUC → Instruction
- 验收：能生成完整章节，不跑偏，Instruction 可影响输出

### Week 6 — UI × Story OS 绑定（闭环）

**目标**：系统"变成产品"

- `UIStateBridge` + `UIEventSystem` + HUD + Unit Editor + Graph View
- UIEvent → StoryEvent 全链路
- 验收：UI 操作能驱动写作，写作结果实时回流 UI

### Week 7（增强层）— Agent Simulation

**目标**：系统"开始有意识"

- WriterAgent / ReaderAgent / CriticAgent / AgentOrchestrator
- 多 Agent 并行思考 + 防污染隔离
- 验收：有冲突输出，Decision 层能收敛

### 优先级矩阵

| 优先级 | 阶段 | 模块 |
|:--:|------|------|
| 🥇 P0 | 必须最先 | Event System / StoryState + Reducer |
| 🥇 P1 | 开始智能 | Guide Engine / Decision Layer |
| 🥈 P2 | 开始写小说 | Prompt OS / LLM Layer |
| 🥉 P3 | 产品化 | UI Bridge / Runtime Pipeline |
| 🧪 P4 | 高级智能 | Agent Simulation / Memory evolution |

---

## 十三、文件级施工图

> 每个 .py 文件明确列出类名 + 核心方法签名，开 IDE 就能写。

### Story 核心层

```python
# story/state/story_state.py
class StoryState:
    units: dict[str, UnitState]
    characters: dict[str, CharacterState]
    hooks: dict[str, HookState]
    memory: MemoryState
    pressure: PressureState
    timeline: TimelineState
    graph: StoryGraph
    def get_unit(unit_id) -> UnitState
    def snapshot() -> dict

# story/state/unit_state.py
class UnitState:
    unit_id / paragraphs / status / story_order / present_order / hooks
    def add_paragraph(text)
    def update_paragraph(pid, text)

# story/state/character_state.py
class CharacterState:
    id / name / position / emotion / goal / relations / last_seen_unit

# story/state/hook_state.py
class HookState:
    id / type(plant/payoff) / source_unit / target_unit / status / importance

# story/state/memory_state.py
class MemoryState:
    facts / events / l1 / l2 / l3 / l4

# story/state/pressure_state.py
class PressureState:
    narrative / character / tension / reader

# story/events/base_event.py
class StoryEvent:
    id / type / payload / causality / timestamp

# story/events/event_store.py
class EventStore:
    def append(event) -> None
    def replay() -> list[StoryEvent]
    def query(filters) -> list[StoryEvent]

# story/engine/reducer.py
class StoryReducer:
    def apply(state, event) -> StoryState
    def rebuild(events) -> StoryState

# story/engine/story_engine.py ⭐
class StoryEngine:
    def run_unit(unit_id) -> str
    def apply_event(event) -> None
    def rebuild_state() -> StoryState
```

### Event 解释层

```python
# event/ui_event.py
class UIEvent:
    source / action / target / payload

# event/intent.py
class SemanticIntent:
    type / scope / unit_id / data

# event/translator.py
class UIEventTranslator:
    def translate(ui_event) -> SemanticIntent

# event/factory.py
class StoryEventFactory:
    def from_intent(intent) -> StoryEvent

# event/validator.py
class EventValidator:
    def validate(event) -> bool
```

### Guide Engine

```python
# guide/guide.py
class Guide:
    source / severity / advice / evidence / conflicts_with / supports

# guide/collector.py
class GuideCollector:
    def collect(state, unit_id) -> list[Guide]

# guide/resolver.py
class GuideResolver:
    def resolve(guides) -> list[Guide]

# guide/sources/pressure.py
class PressureGuide:
    def analyze(state, unit_id) -> list[Guide]
# 同上: memory.py / consistency.py / hook.py / voice.py
```

### Decision Layer

```python
# decision/decision_engine.py
class DecisionEngine:
    def decide(state, guides, agent_outputs) -> Decision

# decision/conflict_detector.py
class ConflictDetector:
    def detect(agent_outputs) -> list[Conflict]

# decision/strategy_selector.py
class StrategySelector:
    def select(guides, conflicts) -> str

# decision/priority_matrix.py
class PriorityMatrix:
    def score(guide, state) -> float

# decision/narrative_policy.py
class NarrativePolicy:
    STRATEGIES = ["DELAY", "EXPLODE", "RESOLVE", "DETOUR"]
```

### Agent Simulation

```python
# agents/orchestrator.py
class AgentOrchestrator:
    def run(state, guides) -> dict

# agents/base_agent.py
class BaseAgent:
    def run(state, guides) -> AgentOutput

# agents/writer_agent.py / reader_agent.py / critic_agent.py
class WriterAgent(BaseAgent): ...
class ReaderAgent(BaseAgent): ...
class CriticAgent(BaseAgent): ...

# agents/isolation.py
class AgentIsolation:
    def sanitize(output) -> dict
```

### Prompt OS

```python
# prompt/compiler.py
class PromptCompiler:
    def compile(state, guides, decision) -> str

# prompt/suc_builder.py
class SUCBuilder:
    def build(state) -> dict

# prompt/stabilizer.py
class PromptStabilizer:
    def stabilize(prompt) -> str
```

### Runtime

```python
# runtime/unit_runner.py ⭐
class UnitRunner:
    def run(unit_id) -> str

# runtime/pipeline.py
class Pipeline:
    def execute(unit_id) -> str

# runtime/chapter_compiler.py
class ChapterCompiler:
    def compile(unit_outputs) -> str
```

### UI Bridge

```python
# ui/bridge/ui_state_bridge.py
class UIStateBridge:
    def subscribe(ui_component)
    def push(state_diff)

# ui/bridge/ui_event_mapper.py
class UIEventMapper:
    def to_ui_event(raw) -> UIEvent
    def to_story_event(ui_event) -> StoryEvent
```

---

## 十四、实现优先级 Checklist

### 🥇 P0 — 必须最先做（否则全是空架构）

- [ ] **Event OS**
  - [ ] StoryEvent 数据结构
  - [ ] EventStore (append-only 存储)
  - [ ] EventValidator (基础校验)
  - [ ] EventReplay (重建日志)
  - [ ] UIEvent → StoryEvent pipeline（先假数据）
- [ ] **StoryState**
  - [ ] StoryState / UnitState / CharacterState / HookState 定义
  - [ ] State 可完整表达故事（Unit / Character / Hook 全覆盖）
- [ ] **Reducer**
  - [ ] Event → State reducer
  - [ ] `rebuild_state()` 从事件完全重建状态
  - [ ] `apply_event()` 单事件降低状态
  - [ ] `story_engine.run_unit()` 启动全流程

### 🥇 P1 — 开始有智能

- [ ] **Guide Engine**
  - [ ] Guide 数据结构
  - [ ] 5 个 Guide Source（Pressure / Memory / Consistency / Hook / Voice）
  - [ ] GuideCollector.collect(state, unit_id)
  - [ ] GuideResolver.resolve(guides)
  - [ ] Guide 可排序、可解释
- [ ] **Decision Layer**
  - [ ] ConflictDetector.detect(agent_outputs)
  - [ ] StrategySelector 支持 4 策略
  - [ ] PriorityMatrix.score(guide, state)
  - [ ] DecisionEngine.decide() → 唯一路径

### 🥈 P2 — 开始写小说

- [ ] **Prompt OS**
  - [ ] SUCBuilder.build(state)
  - [ ] 4 个 Section Builder（Structural / Dynamic / Causal / Guidance）
  - [ ] PromptCompiler.compile(state, guides, decision)
  - [ ] Prompt 结构稳定，不跑偏
- [ ] **LLM**
  - [ ] LLMRouter 支持流式输出
  - [ ] Provider abstraction（OpenAI / Claude / Local）
  - [ ] Retry / fallback 机制

### 🥉 P3 — 产品化

- [ ] **UI Bridge**
  - [ ] UIEventMapper（UI 操作 → StoryEvent）
  - [ ] UIStateBridge（state diff push UI）
  - [ ] HUD 实时更新
  - [ ] Unit Editor 接入 run_unit()
- [ ] **Runtime Pipeline**
  - [ ] UnitRunner.run(unit_id)
  - [ ] Pipeline.execute(unit_id)
  - [ ] ChapterCompiler.compile(unit_outputs)

### 🧪 P4 — 高级智能

- [ ] **Agent Simulation**
  - [ ] 5 个 Agent 并行执行
  - [ ] Agent Isolation 防污染
  - [ ] Conflict detection between agents
  - [ ] Decision Layer 能收敛多 Agent 冲突

---

## 十五、与当前系统对照

| v4 需求 | 当前状态 | Gap |
|------|:--:|------|
| StoryState SSOT | ❌ | 需从零建 |
| EventStore + Reducer | ⚠️ event_bus 有但未作因果链 | 需重构 |
| Guide Engine | ✅ 9 模块输出 + 冲突检测 | 已有，需升级 Resolver |
| Guide Resolver 策略选择 | ⚠️ 有冲突检测但无叙事策略 | 需 4 策略模型 |
| Agent Simulation 防污染 | ❌ | 需从零建 |
| Decision Layer | ❌ | 需从零建 |
| Prompt OS SUC 编译器 | ❌ 拼接式 prompt | 需从零建 |
| UI State Bridge | ❌ | 需从零建 |
| UI Event Translator | ❌ | 需从零建 |
| Story Compiler 集成 | ✅ 模块有且已连 Orchestrator | 已完成 |
| run_unit 默认 Guide | ✅ 已改为 True | 已完成 |
| _dispatch_persist 单元化 | ✅ store_as_unit | 已完成 |
| UI 4 模块导航 | ✅ 已完成 | 已完成 |

---

## 附录：GPT 原始评审结构

| # | 主题 | 核心产出 |
|:--:|------|------|
| 1 | 系统诊断 | 当前是半 v4.0 形态，最大缺口是 StoryState Core，UI/Engine/Prompt 须收敛 |
| 2 | 10 层架构图 | UI → StoryState → Guide → Agent → Decision → Generation → Event → Observe → Publish |
| 3 | 工程级拆解 | StoryState 8 子状态 + EventStore + Reducer + Snapshot |
| 4 | 三层压缩版 | StoryState = 世界事实 / Guide = 决策信号 / Agent = 多视角思考 |
| 5 | Prompt OS / SUC | 4 层编译器：Structural → Dynamic → Causal → Guidance |
| 6 | 防污染 + DSL | Agent Isolation Kernel + Prompt DSL 结构化 |
| 7 | Decision Layer | 4 步：冲突图 → 权重矩阵 → 策略 4 选 1 → 指令压缩 |
| 8 | 工程骨架 | 完整目录 + 6 核心类 + StoryEngine.run_unit() 全链路 |
| 9 | UI × Story OS | UIStateBridge + 四条铁律 |
| 10 | 工业部署架构 | 四层三流 + Kafka 事件驱动 + 微服务化 |
| 11 | 6 周开发路线 | Event → State → Guide → Decision → Prompt → UI → Agent |
| 12 | 文件级施工图 | 每个 .py 的类 + 方法签名 |
| 13 | 初始化顺序 + 优先级 | P0→P4 Checklist |
