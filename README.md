# 小说写作助手 v4.0 — Story OS 架构

> 版本：4.0.0
> 日期：2026-07-06
> 架构：事件驱动 + 多智能体 + 决策编译器 + 故事状态机

---

## 一、核心理念

> **v4.0 不是"AI 写小说工具"，而是"事件驱动 + 多智能体 + 决策编译器 + 故事状态机" — 一个可运行的故事操作系统（Story OS）。**

### 三句宪法

1. **StoryState 是唯一真相源（SSOT）**：UI / Agent / Prompt 都不能存状态
2. **Guide 是"决策信号"，不是文本建议**：从"建议这样写"→ `severity + scope + evidence + instruction`
3. **Agent 是"模拟系统"，不是工具调用**：同一世界状态下的多视角思考

---

## 二、10层架构

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

## 三、模块说明

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

## 四、完整数据流

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

## 五、4种叙事策略

| 策略 | 名称 | 场景 |
|------|------|------|
| DELAY | 延后 | 不爆发冲突，继续铺垫 |
| EXPLODE | 爆发 | 强情绪释放 + 角色冲突 |
| RESOLVE | 收束 | 解决伏笔 + 回收记忆 |
| DETOUR | 偏移 | 绕开冲突，转移叙事焦点 |

---

## 六、故事单元模式

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

---

## 七、界面模块

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

## 八、测试

### 烟雾测试

```bash
cd D:\novel-writer-pure-v4.0

# 运行所有烟雾测试
python smoke/smoke_v4_state.py          # 状态系统测试
python smoke/smoke_v4_guide_decision.py  # 引导+决策测试
python smoke/smoke_v4_prompt.py          # 提示系统测试
python smoke/smoke_v4_runtime.py         # 运行循环测试
python smoke/smoke_v4_isolation.py       # 智能体隔离测试
python smoke/smoke_v4_event_store.py     # 事件存储测试
```

### 测试结果

- 6/6 烟雾测试通过
- 35+ 个断言全部通过

---

## 九、开发计划

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

## 十、版本历史

### v4.0.0 (2026-07-06)

- 从v3.4重构，保留成熟模块，重写问题模块
- 新增Story OS核心：StoryState + Event + Guide + Decision + Prompt
- 新增智能体隔离内核 + 4个Agent
- 新增因果图服务 + 情绪分析器
- 新增双模式（新/老项目自动切换）
- 界面：故事仪表盘 + 故事单元管理
- 测试：6个烟雾测试，35+断言

---

## 十一、依赖

```
PySide6 >= 6.5
numpy
scikit-learn
jieba
requests
```

---

## 十二、启动

```bash
cd D:\novel-writer-pure-v4.0
python -m app
```
