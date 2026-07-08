# Story Engine 路线图（GPT 评审整合版）

> **整合来源**：GPT 对 v3.5.1 的深度评审（2026-07-06）
> **整合方**：workbuddy AI（主人大弟子）
> **整合哲学**：**Guidance 而非 Constraint**

---

## 一、定位的质变

### GPT 的核心判断

> **你的项目已经不是 AI Novel Writer，而是 Story Engine + Story Guidance System。**

### 我们同意这个判断，但需要边界

GPT 提出未来愿景——**Story Operating System（故事操作系统）**——这是一个 5 年后的目标，不在 v3.5.1 路线图内。

但 **Story Engine + Story Guidance System** 是 v3.5.1 应当承载的定位。这不是改名，而是**重新定义核心价值**：

| 旧定位（v3.5.0） | 新定位（v3.5.1） |
|---------------|----------------|
| AI 辅助长篇小说创作工具 | **故事状态、因果关系与创作建议的维护者** |
| 工具型产品 | **协作型平台（作者 + AI 共享同一故事事实）** |
| 功能导向 | **结构导向** |

---

## 二、Guide 系统的 4 大升级（GPT 评审核心）

GPT 提出 Guide 应该从当前的 5 字段升级到 **7 字段**，并新增 3 大能力。

### 升级 1：Guide dataclass 字段扩充

**当前（v3.5.1）**：
```python
@dataclass
class Guide:
    source: str              # "pressure" / "memory" / "voice" / "consistency"
    severity: float          # 0-1，越接近 1 越紧急
    advice: str              # 人话建议
    context: dict = field(default_factory=dict)
    evidence_ids: list = field(default_factory=list)
```

**未来（v4.0 / 1 年内）**：
```python
@dataclass
class Guide:
    priority: float          # 优先级 0-1：先处理谁（不是危险度）
    confidence: float        # 置信度 0-1：AI 有多确定（作者可忽略低置信）
    scope: str               # "Paragraph" / "Scene" / "Unit" / "Book"
    advice: str              # 人话建议
    reason: str              # 为什么这么建议（推理链）
    evidence_ids: list       # 可追溯证据
    possible_actions: list[Action]  # 多选项，让 AI/作者选

@dataclass
class Action:
    label: str               # "下一 Scene 解释" / "延后" / "删除伏笔"
    description: str         # 这个选项的含义
    estimated_impact: dict   # 影响范围预估
```

**这是 GPT 评价里最值钱的一点：**

> `evidence_ids` 是整个系统最值钱的一行，因为：**所有建议都是 Explainable。**
> 以前 AI 说"人物 OOC"不知道为什么；
> 以后 Guide 说"女主此时不应知道男主身份"，证据是 Paragraph 23 / 46 / Hook 18。
> **从"感觉"变成"证据"——这是 Story Engine 最需要的。**

### 升级 2：所有模块统一输出 Guide

**现状（v3.5.1）**：只有部分模块输出 Guide。

**未来（v3.5.1 → v4.0）**：

| 模块 | 当前输出 | 未来输出 |
|------|---------|---------|
| Pressure | score + zone | `list[Guide]` |
| Memory | 记忆文本 | `list[Guide]` |
| Voice | voice drift 报告 | `list[Guide]` |
| Consistency | conflict 列表 | `list[Guide]` |
| Style | 5 维评分 | `list[Guide]` |
| **Hook（新增）** | — | `list[Guide]` (e.g. "Promise 还有 2 个 Unit 应该兑现") |
| **Reader（新增）** | — | `list[Guide]` (e.g. "这里可能弃读") |
| **Style（升级）** | — | `list[Guide]` (e.g. "修真味下降") |
| **Voice（升级）** | — | `list[Guide]` (e.g. "最近对白越来越像作者") |

**Orchestrator 收到：不是十几个系统，而是 `Guide[]`。整个架构会非常漂亮。**

### 升级 3：Decision 层（Guide → Decision → Writer → Event → State）

**当前流程**：
```
Guide → Writer → Event → State
```

**未来流程（v4.0）**：
```
Guide
   ↓
Decision   ← 新增层，记录"AI 采纳/忽略/修改"了哪个 Guide
   ↓
Writer
   ↓
Event
   ↓
State
```

**意义**：
- AI 不一定 100% 采纳 Guide，可能"决定不收，继续埋"
- Decision 记录 `Guide ignored` / `Guide adopted with modification` / `Guide adopted`
- 后续如果这段崩了，**可以回溯不是 Guide 错，而是 AI 没采纳**
- 这就是 **Explainable AI**

**数据结构**：
```python
@dataclass
class Decision:
    unit_id: str
    step_no: int
    guide_id: str
    action: str              # "adopted" / "ignored" / "modified"
    reason: str              # "AI 判断此处不宜回收，因伏笔在第 6 卷才到兑现点"
    decided_by: str          # "ai" / "author"
    decided_at: str          # ISO datetime
```

### 升级 4：Guide Graph（Guide 互相讨论）

**现状**：Guide 彼此独立。

**未来**：Guide 可以 Conflict，可以互相引用。

**示例**：
```yaml
Guide A:
  source: pressure
  advice: "高潮爆发"
  confidence: 0.85

Guide B:
  source: reader
  advice: "慢一点"
  confidence: 0.72

Guide Graph:
  - A → B (conflict)
  - reason: "这是真正的创作权衡，不是 bug"

Writer 看到:
  "当前存在 Guide 冲突：
   pressure 建议高潮（conf 0.85）
   reader 建议放缓（conf 0.72）
   这是创作权衡，请基于上下文判断。"
```

**实现路径**：每个 Guide 记录 `conflicts_with: list[str]`，Orchestrator 在注入 prompt 前先构建冲突图。

---

## 三、未来 5 年的护城河（GPT 终极建议）

> **如果你的目标是建立未来五年仍然有竞争力的产品，把研发重心集中在四件事上：**

| # | 能力 | 含义 | 目标 |
|---|------|------|------|
| 1 | **Guide System** | 所有模块统一输出 Guide | 唯一的协作语言 |
| 2 | **Event / State Engine** | 故事状态成为系统事实来源 | 不是文本本身 |
| 3 | **Story Graph** | 从 Event 自动沉淀因果图 | 长期一致性 + 重构基础 |
| 4 | **Story Compiler** | 任何故事修改自动分析影响范围 + 修复建议 | 像代码一样可演化可验证 |

**最终愿景**：**面向长篇叙事创作的 Story Operating System（故事操作系统）**

---

## 四、README 第一句话的修订

### 当前（v3.5.1）
> **不是工具，是陪伴者。**

### GPT 建议（更准确）
> **Novel Writer Pure 不是 AI 写作工具，而是一套 Story Engine。它不替作者决定故事，也不替 AI 决定写法，而是持续维护故事状态、因果关系与创作建议，让 AI 与作者始终在同一个故事事实上协作。**

### 我们最终采用（整合 GPT + workbuddy）

> **Novel Writer Pure 是一套 Story Engine。**
>
> 它不替作者决定故事，也不替 AI 决定写法；
> 它持续维护故事状态、因果关系与创作建议，
> 让 AI 与作者始终在同一个故事事实上协作。

**为什么这样定稿**：
- 删掉"不是工具是陪伴者"——避免"陪伴者"被泛化为情感化口号
- 保留三层职责的清晰陈述（作者 / AI / Story Engine）
- 把"Guidance 而非 Constraint"哲学直接落到产品定位上
- "在同一个故事事实上协作"是 Story Engine 最核心的价值承诺

---

## 五、路线图（GPT 整合后）

### v3.5.1（已落地）
- ✅ Guide 接口契约（5 字段基础版）
- ✅ Orchestrator `collect_guides()` 入口
- ✅ Virtual Unit / Event Diff / Exporter preview
- ✅ A/B 灰度切换
- ✅ README 加哲学层

### v3.5.2（3 个月内，Guide 升级）
- ⏳ **Guide dataclass 升级到 7 字段**（priority/confidence/scope/advice/reason/evidence_ids/possible_actions）
- ⏳ **Hook / Reader / Style / Voice 全部返回 Guide**
- ⏳ Orchestrator 内部按 `priority` 排序（替换 severity）
- ⏳ README 第一句话按 GPT 建议重写
- ⏳ 低 `confidence` 的 Guide 在 UI 上标灰（"作者可忽略"）

### v3.6（6 个月内，Decision 层）
- ⏳ **Decision 数据层**：unit_decisions 表 + Decision dataclass
- ⏳ Writer Agent 输出 Decision 记录（采纳/忽略/修改）
- ⏳ StoryTeller 的 prompt 加上"Guide 列表 + 你的 Decision"双注入
- ⏳ UI 加 Decision 可视化（哪个 Guide 被采纳 / 哪个被忽略）

### v4.0（1 年内，Guide Graph + Story Compiler 雏形）
- ⏳ **Guide Graph**：Guide 之间的 conflict / support 关系
- ⏳ Orchestrator 在 prompt 注入前构建冲突图
- ⏳ **Story Compiler 雏形**：修改 Unit → 自动分析影响范围 → 列出需要同步修改的其它 Unit
- ⏳ 把"Guide"哲学在文档中显式化为 **Story Guidance System**

### v5.0+（3-5 年，Story Operating System）
- 🎯 **Story Graph**：从 Event 自动沉淀因果图（Neo4j 或 SQLite 图扩展）
- 🎯 State Machine 自动验证（用 Graph 替代 Critic / Consistency）
- 🎯 自动剧情重排（Event 顺序重排后正文自动重组）
- 🎯 如果届时模块稳定，统一命名 `*_guide.py`（**GPT 评价里明确警告**：过早抽象有害，**5 年后再做**）

---

## 六、明确不做（GPT 反向价值）

GPT 这条思路的真正价值，不是告诉你"要做什么"，而是告诉你"不要做什么"。

### 现在不做（v3.5.1）
- ❌ 改名为"Story Engine"产品名（保留 Novel Writer Pure，定位升级不需改名）
- ❌ 重组目录结构（保持稳定）
- ❌ 立即把所有模块改为返回 Guide（v3.5.2 才做）
- ❌ 立即做 Guide Graph（v4.0 才做）
- ❌ 立即做 Story Compiler（v4.0 雏形，v5.0 成熟）

### 永远不做
- ❌ 用硬规则约束 AI（Constraint）—— 我们选 Guidance
- ❌ 让系统替作者做决定
- ❌ 让系统替 AI 做决定
- ❌ 删 critic / consistency / character_tracker / memory_manager（GPT 警告：现在还在干活）

---

## 七、共识表（GPT + workbuddy 最终）

| 议题 | 共识度 | 决策 |
|------|--------|------|
| 定位升级为 Story Engine + Guidance System | ✅ 2/2 | v3.5.1 README 体现，**不改产品名** |
| Guide evidence_ids 是最值钱的一行 | ✅ 2/2 | 永久保留 |
| Guide 升级到 7 字段 | ✅ 2/2 | v3.5.2 |
| Decision 层（Guide → Decision → Writer → Event）| ✅ 2/2 | v3.6 |
| Guide Graph 互相 Conflict | ✅ 2/2 | v4.0 |
| 所有模块输出 Guide（Hook/Reader/Style/Voice）| ✅ 2/2 | v3.5.2 |
| Story Compiler（修改 Unit 自动分析影响）| ✅ 2/2 | v4.0 雏形 |
| Story Graph 因果图 | ✅ 2/2 | v5.0 |
| 重写 README 第一句话 | ✅ 2/2 | **v3.5.1 已落地**（采纳 GPT 建议） |
| 模块统一改名 `*_guide.py` | ❌ 反对 | **5 年后再议**（GPT 警告：过早抽象） |
| 改名为 Story OS | ❌ 反对 | 定位升级不需改名 |

---

## 八、致 GPT

> GPT 这次评审的价值不在"加什么功能"，而在"指明价值方向"。
>
> **Guide + evidence_ids 是产品灵魂**——这一行的价值超过未来 5 年所有功能加总。
>
> **Decision 层 + Guide Graph** 是从"工具"到"操作系统"的关键跃迁。
>
> **Story Compiler** 是终极形态——让故事像代码一样可演化、可验证。
>
> 我们不会一夜之间做完这些，但会按路线图逐年推进。
>
> **GPT 看到的可能性，正是我们要用 5 年证明的现实。**

---

**文档创建**：2026-07-06
**整合作者**：workbuddy AI（主人大弟子）
**整合来源**：GPT 对 v3.5.1 的深度评审
**核心命题**：**Story Engine + Story Guidance System**
**护城河**：**Guide System / Event-State Engine / Story Graph / Story Compiler**