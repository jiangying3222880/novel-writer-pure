# 故事单元模式 Phase 0 完整设计文档（最终版）

> 版本：Phase 0 Final
> 日期：2026-07-06
> 状态：设计完成，可进入实施
> 前置评审：
> - v1.0 基础设计（tare）
> - v1.1 补充设计（tare，覆盖盲区）
> - v2.0 整合版（tare，双时间线+情绪断章+因果编排）
> - 第一轮评审（workbuddy，4个稳定性问题）
> - tare 回应（4个问题的方案）
> - 第二轮评审（workbuddy，5个补充点 + 标签系统修正）
> - 最终确认（标签系统不进 Phase 0，仅占位）

---

## 0. 文档说明

### 0.1 设计范围

本文档覆盖 **Phase 0 设计阶段**的全部内容。所有经过两轮评审确认的设计都在此文档中。

**已确认，纳入本文档**：
- 三层架构（创作层/聚合层/发布层）
- 双时间线（story_order + present_order）
- 8 种衔接类型
- 数据模型精确字段（含 5 条补充）
- `run_unit()` 分段生成完整流程
- 级联清理规则
- 钩子段落锚点机制
- 拆章器三层结构
- 状态映射独立模块

**未确认，仅占位**：
- 单元标签系统（见附录 A）

---

## 一、核心设计理念

### 1.1 一句话总结

> **单元是创作单位，章节是发布单位。先以单元创作完整故事，再在读者最有感觉的地方断章。**

### 1.2 三个核心洞察

1. **创作与发布解耦**：单元负责创作质量，章节负责发布体验
2. **双时间线分离**：故事时间（因果顺序）≠ 呈现时间（读者顺序），支持非线性叙事
3. **断章是设计出来的**：站在全局情绪曲线视角，精确选择每一刀下在哪里最痛

### 1.3 与现有系统的关系

- 现有章节系统 **100% 保留**，作为下游发布层
- 现有编排师 `run_chapter()` **完全保留**，老项目不受影响
- 单元模式是**新增的上游创作层**，不破坏任何现有功能
- 老项目零迁移成本（空单元法，见 7.1）

---

## 二、整体架构

### 2.1 三层架构

```
┌─────────────────────────────────────────────────────────┐
│                    创作层（上游）                         │
│  分卷(Book) → 故事单元(Unit) → 单元大纲(UnitBrief)       │
│                     ↑                                    │
│              编排师：因果编排 + 单元写作                   │
│         （双时间线 + 衔接类型 + 分段生成）                │
└──────────────────────────┬──────────────────────────────┘
                           │ 拆章（情绪曲线断章）
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    聚合层（桥梁）                          │
│         分章规则配置 + 断章点分析 + 衔接打磨               │
└──────────────────────────┬──────────────────────────────┘
                           │ 导出
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    发布层（下游）                         │
│        分卷(Book) → 章节(Chapter) → 章节大纲             │
│              现有系统完全不变                              │
│    （编辑 / 潜文本 / 一致性 / TTS / 导出）               │
└─────────────────────────────────────────────────────────┘
```

---

## 三、数据模型设计

### 3.1 总览

| 表名 | 状态 | 说明 |
|------|------|------|
| `story_units` | **修改**（v2.0 新增的表，本次加字段） | 故事单元主表 |
| `unit_briefs` | **新增** | 单元大纲表 |
| `unit_writing_snapshots` | **新增** | 写作断点快照表 |
| `unit_paragraphs` | **新增** | 单元段落表（段落 ID 锚点） |
| `unit_causal_edges` | **新增** | 因果边表 |
| `unit_causal_groups` | **新增** | 剧情线表 |
| `split_configs` | **新增** | 分章规则配置表 |
| `unit_hook_map` | **修改**（v2.0 已有，加 paragraph_id） | 单元-钩子映射 |
| `agent_memory` | **修改**（加 unit_id + unit_step + manual_locked） | 记忆表 |
| `chapters` | **修改**（加 source_unit_id + split_version + is_current_version） | 章节表 |
| 其他 10 张表 | **修改**（仅加 unit_id 字段，v2.0 迁移 035 已做） | 各表加单元锚点 |

### 3.2 story_units 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | 单元 ID |
| `project_id` | TEXT | NOT NULL, INDEX | 项目 ID |
| `book_id` | TEXT | NOT NULL, DEFAULT '' | 分卷 ID |
| `unit_no` | INTEGER | NOT NULL, DEFAULT 0 | 卷内单元序号（按 present_order） |
| `title` | TEXT | NOT NULL, DEFAULT '' | 单元标题 |
| `unit_type` | TEXT | NOT NULL, DEFAULT 'other' | 单元类型：battle/romance/reveal/transition/climax/setup/payoff/other |
| `story_order` | INTEGER | NOT NULL, DEFAULT 0 | 故事时间顺序（因果顺序） |
| `present_order` | INTEGER | NOT NULL, DEFAULT 0 | 呈现时间顺序（读者顺序） |
| `status` | TEXT | NOT NULL, DEFAULT 'draft' | 状态：draft/outlining/writing/completed/split |
| `synopsis` | TEXT | DEFAULT '' | 单元简介 |
| `draft` | TEXT | DEFAULT '' | 单元正文草稿 |
| `word_count` | INTEGER | DEFAULT 0 | 字数 |
| `emotion_basis` | TEXT | DEFAULT '' | 情绪基调 |
| `transition_type` | TEXT | NOT NULL, DEFAULT 'direct' | 衔接类型：见 3.7 |
| `transition_text` | TEXT | DEFAULT '' | 衔接文本（过渡句） |
| `pov_character` | TEXT | DEFAULT '' | 视角角色 |
| `timeline_label` | TEXT | DEFAULT '现在' | 时间线标签：现在/三年前/回忆/... |
| `entry_characters` | TEXT | DEFAULT '{}' | 入口角色状态（JSON） |
| `entry_world` | TEXT | DEFAULT '{}' | 入口世界观状态（JSON） |
| `entry_commitments` | TEXT | DEFAULT '[]' | 入口承诺状态（JSON 数组） |
| `exit_characters` | TEXT | DEFAULT '{}' | 出口角色状态（JSON） |
| `exit_world` | TEXT | DEFAULT '{}' | 出口世界观状态（JSON） |
| `exit_commitments` | TEXT | DEFAULT '[]' | 出口承诺状态（JSON 数组） |
| `unit_memories` | TEXT | DEFAULT '[]' | 单元专属记忆（JSON 数组） |
| `target_chars` | INTEGER | DEFAULT 5000 | 目标字数 |
| `target_chapter_count` | INTEGER | DEFAULT 2 | 预计拆成几章 |
| `current_step` | INTEGER | DEFAULT 0 | 当前写作步数（0=未开始） |
| `total_steps` | INTEGER | DEFAULT 0 | 总步数估算 |
| `created_at` | TEXT | NOT NULL | |
| `updated_at` | TEXT | NOT NULL | |

**索引**：
- `idx_units_project` (project_id)
- `idx_units_book` (project_id, book_id)
- `idx_units_story_order` (project_id, story_order)
- `idx_units_present_order` (project_id, present_order)

### 3.3 unit_briefs 表（单元大纲）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | ID |
| `unit_id` | TEXT | NOT NULL, UNIQUE | 单元 ID |
| `project_id` | TEXT | NOT NULL, INDEX | 项目 ID |
| `brief` | TEXT | DEFAULT '' | 单元大纲文本 |
| `core_events` | TEXT | DEFAULT '[]' | 核心事件（JSON 数组） |
| `emotion_arc` | TEXT | DEFAULT '' | 情绪弧线描述 |
| `cause_summary` | TEXT | DEFAULT '' | 前因总结（承接上一单元的什么） |
| `effect_summary` | TEXT | DEFAULT '' | 后果总结（引出下一单元的什么） |
| `hooks_planned_plant` | TEXT | DEFAULT '[]' | 计划埋设的伏笔（JSON 数组） |
| `hooks_planned_pay` | TEXT | DEFAULT '[]' | 计划回收的伏笔（JSON 数组） |
| `created_at` | TEXT | NOT NULL | |
| `updated_at` | TEXT | NOT NULL | |

### 3.4 unit_writing_snapshots 表（写作断点快照）

**核心设计**：每步完成后存一个快照，重写第 N 步时从第 N-1 步快照恢复。
摘要跟着快照走，不做独立单条记录。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | 快照 ID |
| `unit_id` | TEXT | NOT NULL, INDEX | 单元 ID |
| `project_id` | TEXT | NOT NULL, INDEX | 项目 ID |
| `step_no` | INTEGER | NOT NULL | 步数（从 1 开始） |
| `draft_text` | TEXT | NOT NULL | 截至该步的完整正文 |
| `unit_summary` | TEXT | NOT NULL | 截至该步的单元摘要（300-500 字） |
| `word_count` | INTEGER | NOT NULL, DEFAULT 0 | 截至该步的总字数 |
| `character_state` | TEXT | DEFAULT '{}' | 截至该步的角色状态快照（JSON） |
| `world_state` | TEXT | DEFAULT '{}' | 截至该步的世界观状态快照（JSON） |
| `active_hooks` | TEXT | DEFAULT '[]' | 截至该步的活跃伏笔（JSON 数组） |
| `step_prompt` | TEXT | DEFAULT '' | 该步的写作指令（用于重放） |
| `model_used` | TEXT | DEFAULT '' | 该步用的模型 |
| `tokens_used` | INTEGER | DEFAULT 0 | 该步消耗 token 数 |
| `created_at` | TEXT | NOT NULL | |

**唯一约束**：`(unit_id, step_no)` — 每个单元每步只有一个快照

### 3.5 unit_paragraphs 表（段落锚点）

**核心设计**：单元正文按段落切分，每段一个稳定 ID。钩子、记忆、一致性问题都挂在段落 ID 上。
段落 ID 稳定不回收，增删段落不影响其他段落的 ID。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | 段落 ID（UUID） |
| `unit_id` | TEXT | NOT NULL, INDEX | 单元 ID |
| `project_id` | TEXT | NOT NULL, INDEX | 项目 ID |
| `sort_order` | INTEGER | NOT NULL | 段落顺序号（可重排） |
| `text` | TEXT | NOT NULL | 段落正文 |
| `char_start` | INTEGER | DEFAULT -1 | 在全文中的起始偏移（缓存，编辑后需刷新） |
| `char_end` | INTEGER | DEFAULT -1 | 在全文中的结束偏移 |
| `paragraph_type` | TEXT | DEFAULT 'normal' | normal/dialogue/description/narration/transition |
| `created_at` | TEXT | NOT NULL | |
| `updated_at` | TEXT | NOT NULL | |

**索引**：
- `idx_paragraphs_unit` (unit_id, sort_order)

### 3.6 unit_hook_map 表（单元-钩子映射）

v2.0 已有，加 `paragraph_id` 字段做锚点。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | ID |
| `unit_id` | TEXT | NOT NULL, INDEX | 单元 ID |
| `project_id` | TEXT | NOT NULL, INDEX | 项目 ID |
| `hook_id` | TEXT | NOT NULL, INDEX | 钩子 ID |
| `hook_type` | TEXT | NOT NULL | plant/pay（埋设/回收） |
| `paragraph_id` | TEXT | DEFAULT '' | **锚点段落 ID**（新增） |
| `step_no` | INTEGER | DEFAULT 0 | 写作步数（在第几步出现） |
| `description` | TEXT | DEFAULT '' | 描述 |
| `manual_locked` | INTEGER | DEFAULT 0 | **手动锁定，重写时不清理**（新增） |
| `created_at` | TEXT | NOT NULL | |

### 3.7 agent_memory 表（记忆，加字段）

v2.0 迁移 035 已加 `unit_id`，本次加 `unit_step` + `manual_locked`。

| 字段 | 状态 | 说明 |
|------|------|------|
| `unit_id` | 已有（035） | 单元 ID |
| `unit_step` | **新增** | 单元内步数（第几步产生的） |
| `manual_locked` | **新增** | 手动锁定，重写时不清理 |

### 3.8 chapters 表（章节，加字段）

| 字段 | 类型 | 说明 |
|------|------|------|
| `source_unit_id` | TEXT | 来源单元 ID（拆章产生的章节填这个） |
| `split_version` | INTEGER | 拆章版本号（第几次拆出来的） |
| `is_current_version` | INTEGER | 是否当前版本（1=当前，0=历史） |

**设计说明**：
- 每次重新拆章生成新版本，`is_current_version = 1` 的是当前版本
- 旧版本保留，用户可以回退
- 导出/TTS/一致性检查只看 `is_current_version = 1` 的章节
- 定期清理：用户可归档旧版本到 `chapter_history`（后续优化，MVP 不做）

### 3.9 unit_causal_edges 表（因果边）

按 **故事时间**（story_order）建因果边。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | 边 ID |
| `project_id` | TEXT | NOT NULL, INDEX | 项目 ID |
| `from_unit_id` | TEXT | NOT NULL | 因单元（故事时间在前） |
| `to_unit_id` | TEXT | NOT NULL | 果单元（故事时间在后） |
| `edge_type` | TEXT | NOT NULL, DEFAULT 'direct' | 边类型 |
| `description` | TEXT | DEFAULT '' | 因果关系描述 |
| `strength` | REAL | DEFAULT 1.0 | 因果强度 0-1 |
| `created_at` | TEXT | NOT NULL | |

**边类型**：
- `direct`：直接因果
- `setup_payoff`：铺垫-回收
- `character_change`：人物变化
- `world_change`：世界观变化
- `parallel`：并行线
- `flashback`：倒叙关联
- `chekhov`：契诃夫之枪

### 3.10 unit_causal_groups 表（剧情线）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | 群 ID |
| `project_id` | TEXT | NOT NULL, INDEX | 项目 ID |
| `name` | TEXT | NOT NULL | 剧情线名称（主线/感情线/副线A） |
| `color` | TEXT | DEFAULT '#4A90D9' | 标记颜色 |
| `description` | TEXT | DEFAULT '' | 描述 |
| `unit_ids` | TEXT | DEFAULT '[]' | 包含的单元 ID（JSON 数组） |
| `sort_order` | INTEGER | DEFAULT 0 | 排序 |
| `created_at` | TEXT | NOT NULL | |

### 3.11 split_configs 表（分章规则配置）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | TEXT | PK | ID |
| `project_id` | TEXT | NOT NULL, INDEX | 项目 ID |
| `book_id` | TEXT | DEFAULT '' | 分卷 ID（空=全局默认） |
| `name` | TEXT | DEFAULT '默认' | 配置名称 |
| `target_chars` | INTEGER | DEFAULT 3000 | 目标章字数 |
| `min_chars` | INTEGER | DEFAULT 2000 | 最小章字数 |
| `max_chars` | INTEGER | DEFAULT 5000 | 最大章字数 |
| `split_strategy` | TEXT | DEFAULT 'auto' | 断章策略：见 5.4 |
| `use_ai_analysis` | INTEGER | DEFAULT 1 | 是否用 AI 做第二层情绪分析 |
| `created_at` | TEXT | NOT NULL | |

### 3.12 衔接类型（transition_type）

| 类型代码 | 中文名 | 说明 |
|---------|--------|------|
| `direct` | 直接衔接 | 时间连续，场景接续 |
| `time_jump` | 时间跳接 | 有时间间隔，一句话带过 |
| `pov_switch` | 视角切换 | 换 POV 角色 |
| `flashback` | 倒叙/回想 | 故事时间在前，呈现时间在后 |
| `parallel` | 并行线 | 双线同时发生，交替呈现 |
| `chekhov` | 伏笔衔接 | 前面出现的细节后面回收 |
| `contrast` | 反差衔接 | 强烈反差/反转 |
| `suspense_front` | 悬念前置 | 把后面的高潮提前 |

---

## 四、双时间线设计

### 4.1 核心概念

```
故事时间（story_order）：事件在故事世界里发生的先后顺序
    → 用于：因果网络、写作时上下文组装、伏笔管理、记忆查询

呈现时间（present_order）：读者阅读时看到的先后顺序
    → 用于：单元列表排序、拆章、章节编号、UI 默认视图
```

### 4.2 系统行为总表

| 操作/查询 | 按 story_order | 按 present_order |
|----------|---------------|-----------------|
| 单元列表默认排序 | ❌ | ✅ 默认视图 |
| 写作时上下文组装 | ✅ 拉取因果上游 | ❌ |
| 因果边建立 | ✅ 按故事时间 | ❌ |
| 伏笔埋设/回收检查 | ✅ 故事时间里埋设必须在回收前 | ❌ |
| 记忆查询（as_of_unit） | ✅ 截至某步的故事顺序 | ❌ |
| 拆章顺序 | ❌ | ✅ 按呈现顺序拆 |
| 章节编号 | ❌ | ✅ 按呈现顺序编 |
| UI 故事时间视图 | ✅ 可切换 | ❌ |

### 4.3 非线性叙事连贯性检查

调整呈现顺序后，自动检查：
- ⚠️ **倒叙检测**：呈现顺序在因果下游之前 → 自动标记为 flashback 衔接
- ⚠️ **伏笔倒置**：呈现上回收在埋设之前 → 提示用户确认（可能是故意的倒叙揭秘）
- ✅ **因果链完整**：故事时间的因果链没有断裂

### 4.4 写作时的上下文组装

写第 N 个单元时（按 story_order），上下文包含：
1. **因果上游**：所有 story_order < 当前单元的单元的关键信息（摘要级，不是全文）
2. **全局 L1/L2**：故事弧、活跃承诺、世界规则
3. **入口状态快照**：角色状态、世界观状态、已激活伏笔
4. **单元大纲**：cause_summary + effect_summary + 核心事件
5. **本单元专属记忆**（unit_memories）

**注意**：上下文组装永远按 story_order，不按 present_order。

---

## 五、`run_unit()` 分段生成设计

### 5.1 核心架构

```
单元生成 = 多个"写作步"（writing step）串联
每步生成 1500-2500 字（AI 单次生成质量最好的区间）
每步完成后 → 存断点快照 → 更新记忆 → 同步状态
```

### 5.2 写作步的工作流

```
第 N 步开始
    │
    ├─ 从第 N-1 步快照加载：
    │   ├─ 单元摘要（截至 N-1 步）
    │   ├─ 角色状态快照
    │   ├─ 活跃伏笔列表
    │   └─ 世界观状态
    │
    ├─ 计算 token 预算：
    │   可用token = 模型上下文上限
    │               - 系统提示词
    │               - 单元摘要
    │               - 角色状态
    │               - 伏笔列表
    │               - 世界观
    │               - 生成预留（通常 2000-3000）
    │   回灌原文 token = 可用 token（从最近一步往回取，取满为止）
    │
    ├─ 组装写作上下文：
    │   系统提示 + 单元摘要 + 回灌原文 + 角色状态 + 伏笔 + 世界观 + 本步指令
    │
    ├─ AI 生成正文（1500-2500 字）
    │
    ├─ 写后处理：
    │   ├─ 段落切分（写入 unit_paragraphs）
    │   ├─ 钩子检测（埋设/回收，挂到段落 ID）
    │   ├─ 记忆提取（L1/L2/L3，带 unit_step）
    │   ├─ 角色状态更新
    │   └─ 更新单元摘要（AI 生成/更新整单元摘要）
    │
    └─ 存第 N 步快照（unit_writing_snapshots）
         包含：完整正文 + 单元摘要 + 角色状态 + 活跃伏笔 + 世界观
```

### 5.3 中断续写机制

- 每个快照都是完整的恢复点
- 中断后重新开始，从 `current_step` 对应的快照恢复
- 支持"从第 N 步重新生成"：
  - 删除第 N 步及之后的所有快照
  - 删除第 N 步及之后的所有段落（unit_paragraphs）
  - 删除第 N 步及之后的**非锁定**记忆（agent_memory，manual_locked=0）
  - 删除第 N 步及之后的**非锁定**钩子（unit_hook_map，manual_locked=0）
  - 从第 N-1 步快照开始重写

### 5.4 重写的级联清理规则

**重写第 N 步 = 丢弃第 N 步及之后所有自动生成的衍生数据，但保留手动锁定的。**

| 数据类型 | 清理方式 | 备注 |
|---------|---------|------|
| 正文快照 | 第 N 步及之后全部删 | |
| 段落（unit_paragraphs） | 第 N 步及之后全部删 | |
| 记忆（agent_memory） | 第 N 步及之后，`manual_locked = 0` 的删 | 锁定的保留 |
| 钩子（unit_hook_map） | 第 N 步及之后，`manual_locked = 0` 的删 | 锁定的保留 |
| 角色状态变化 | 从第 N-1 步快照恢复 | |
| 单元摘要 | 从第 N-1 步快照恢复 | |

**手动锁定（manual_locked）**：用户手动添加或手动确认过的记忆/钩子，重写时不清理。
AI 自动生成的记忆/钩子默认 `manual_locked = 0`，用户确认后可设为 1。

### 5.5 token 预算算法

```python
def calculate_context_budget(model_context_size: int, system_prompt_len: int) -> dict:
    """计算各部分的 token 预算。"""
    total = model_context_size
    remaining = total - system_prompt_len
    
    # 预留生成空间
    generation_reserve = min(3000, remaining * 0.3)
    remaining -= generation_reserve
    
    # 固定开销
    summary_budget = min(800, remaining * 0.15)
    remaining -= summary_budget
    
    char_state_budget = min(500, remaining * 0.1)
    remaining -= char_state_budget
    
    hooks_budget = min(300, remaining * 0.08)
    remaining -= hooks_budget
    
    world_budget = min(400, remaining * 0.1)
    remaining -= world_budget
    
    # 剩余全给回灌原文
    context_text_budget = remaining
    
    return {
        'generation': generation_reserve,
        'summary': summary_budget,
        'char_state': char_state_budget,
        'hooks': hooks_budget,
        'world': world_budget,
        'context_text': context_text_budget,
    }
```

回灌原文时，从最近一步的末尾往回取，取满 `context_text_budget` 为止。
不是固定 N 步，是按 token 预算自适应。

---

## 六、钩子与段落锚点设计

### 6.1 核心机制

**钩子挂在段落 ID 上，不是挂在字符偏移上。**

```
单元正文 → 切分成段落 → 每段一个稳定 paragraph_id
                                    ↓
                        钩子挂在 paragraph_id 上
                                    ↓
                          拆章时看段落落在哪一章
                                    ↓
                           钩子就跟着迁移到哪一章
```

### 6.2 段落 ID 的稳定性

- 段落 ID 是 UUID，生成后永久不变
- 新增段落：生成新 ID，不影响已有段落
- 删除段落：ID 不回收，其他段落 ID 不变
- 修改段落内容：ID 不变，只改 text
- 移动段落：改 sort_order，ID 不变

**好处**：钩子、记忆、一致性问题等所有挂在段落上的东西，都不会因为文本编辑而错位。

### 6.3 钩子的双轨制

| 阶段 | 钩子挂在哪 | 触发时机 | 检查依据 |
|------|-----------|---------|---------|
| 单元写作阶段 | `unit_id` + `paragraph_id` + `step_no` | 每步写作前，拉取截至上一步的钩子 | `story_order` |
| 拆章后 | 同时挂 `unit_id` + `chapter_id` + `chapter_paragraph_id` | 章节写作时按章节触发 | `chapter_no` |

**拆章时的钩子迁移**：
1. 单元钩子保留（不删除，保留原始归属）
2. 拆章时，根据段落 → 章节的对应关系
3. 在章节侧创建钩子记录，带 `from_unit_hook_id` 指向源单元钩子
4. 两个钩子并行存在，各管各的阶段

### 6.4 伏笔检查的时间基准

永远按 **story_order**（故事时间）检查，不按 present_order：
- 非线性叙事下，呈现上回收可能在埋设前面（倒叙揭秘）
- 但故事时间里，埋设一定在回收前面
- 检查"伏笔是否已埋设"永远按故事时间

---

## 七、级联规则

### 7.1 删除单元

弹窗让用户选（**不自动留孤儿**）：

| 选项 | 操作 |
|------|------|
| (a) 连章节一起删（彻底清理） | 删除单元 + 级联删除所有关联数据 + 删除该单元拆出的所有章节（所有版本） |
| (b) 章节转正（脱离单元，变独立章节） | 删除单元 + 级联删除单元侧数据，但章节保留，`source_unit_id` 置空，变成独立章节 |
| (c) 取消删除 | 什么都不做 |

选 (a) 或 (b) 时，级联清理的单元侧数据包括：
- ✅ unit_briefs
- ✅ unit_writing_snapshots（所有步）
- ✅ unit_paragraphs（所有段落）
- ✅ unit_causal_edges（所有关联的边）
- ✅ unit_hook_map（所有钩子映射）
- ✅ agent_memory 里 unit_id = 该单元且 manual_locked = 0 的记忆（锁定的保留，移到全局）
- ✅ character_trackers 里 unit_id = 该单元的记录（最新快照升级到章节级）
- ✅ narrative_pressures 里 unit_id = 该单元的记录
- ✅ world_state_snapshots 里 unit_id = 该单元的记录

### 7.2 重排单元（调整 present_order）

- 因果边 **不动**（因果边按 story_order，跟呈现顺序无关）
- 已拆出的章节 **不动**（提示用户"已拆章的章节顺序不会自动更新，需要重新拆章"）
- 单元序号（unit_no）重新编号
- 自动检查连贯性（倒叙检测、伏笔倒置提示）

### 7.3 调整 story_order

- 因果边还是那些边，但因果链的顺序变了
- **不自动重连因果边**，提示用户检查因果链是否合理
- 钩子的埋设/回收顺序重新检查，如果 story_order 下回收在埋设前面，告警
- 记忆的 story_order 查询结果会变（正常）

### 7.4 重新拆章

- 每次重新拆章生成新版本（split_version + 1）
- 新版本的 `is_current_version = 1`
- 旧版本的 `is_current_version` 置 0
- 旧版本保留，可回退
- 所有下游功能（导出/TTS/一致性）只看 is_current_version = 1 的
- 操作包在事务里，中途失败整次回滚

---

## 八、拆章器设计

### 8.1 三层结构

| 层 | 方法 | 作用 | 速度 |
|----|------|------|------|
| 第一层 | 正则 + 情绪词典 | 初筛，缩小候选范围 | 快（毫秒级） |
| 第二层 | AI 情绪分析 | 精准评分 + 断章模式判定 | 慢（秒级） |
| 第三层 | 人工确认 | 用户看报告拍板 | 人说了算 |

### 8.2 六种断章模式

| 模式 | 读者心理 | 痛感等级 | 基础分 |
|------|---------|---------|--------|
| 揭示型 | "竟然是？！" | ⭐⭐⭐⭐⭐ | 100 |
| 危机型 | "别！危险！" | ⭐⭐⭐⭐ | 90 |
| 选择型 | "选A还是B？" | ⭐⭐⭐⭐ | 85 |
| 情绪峰值 | "太燃了！" | ⭐⭐⭐⭐ | 80 |
| 悬念前置 | "然后呢？" | ⭐⭐⭐ | 70 |
| 场景收束 | "下一个场景？" | ⭐⭐ | 50 |

### 8.3 断章痛感公式

```
综合得分 = 模式基础分 × 位置系数 × 情绪强度系数

位置系数：
  - 在目标字数 ±20% 范围内：×1.0
  - 超出 ±20% 但在 ±40%：×0.7
  - 超出 ±40%：×0.4

情绪强度系数：
  - 候选位置的情绪强度 / 单元平均情绪强度
  - 范围 0.5 ~ 1.5
```

### 8.4 断章策略（split_strategy）

| 策略 | 适用 | 权重调整 |
|------|------|---------|
| `auto` | 通用（默认） | 按痛感评分排序 |
| `cool` | 升级流/爽文 | 高潮后断（情绪峰值型权重+20%） |
| `suspense` | 悬疑/推理 | 揭秘前断（揭示型权重+20%） |
| `romance` | 言情/感情线 | 情感爆发前断（情绪峰值权重+20%，揭示型权重+10%） |
| `fast` | 快节奏文 | 小高潮密集断，降低目标字数 |
| `steady` | 文青/慢热 | 场景收束权重+30%，降低痛感权重 |

### 8.5 情绪曲线分析（第一层，正则）

用关键词密度 + 标点密度估算情绪强度：

| 信号 | 情绪方向 |
|------|---------|
| 感叹号密度 | 正向（激动/愤怒/惊讶） |
| 问号密度 | 正向（疑惑/悬念） |
| 强烈情绪词（怒吼/狂喜/崩溃/绝望...） | 正向 |
| 对话占比高 | 偏正向（冲突多） |
| 环境描写占比高 | 偏负向（平缓） |
| 短句占比高 | 偏正向（节奏快） |
| 长句占比高 | 偏负向（节奏慢） |

情绪词典按题材分（玄幻/言情/悬疑各一套），不通用。

### 8.6 断章报告（呈现给用户）

每个候选断章点给一份报告：

```
📍 候选断章点 #1（位置: 3200字，痛感: ★★★★★）
  类型：揭示型断章
  原文片段：
    他猛地抬头，看向墙上的那幅画。
    画里的人，竟然和他长得一模一样。
  推荐理由：身份揭秘，好奇心拉满，读者会立刻点下一章
  风险提示：下一章开头需要接住这个揭秘，不能拖
```

---

## 九、单元-章节状态映射

### 9.1 独立模块

**unit_chapter_mapper.py**，独立模块，不混在 story_unit_service 里。

### 9.2 映射策略总表

| 数据类型 | 映射策略 | 说明 |
|---------|---------|------|
| 世界规则（L1） | 全量复制到每章 | 不变的东西直接搬 |
| 故事弧（L1） | 全量复制 | 全局不变 |
| 承诺/伏笔（L2） | 按段落锚点分配，不能定位的分到第一章 | 有 paragraph_id 的精确分配 |
| RAG 临时（L3） | 不迁移 | L3 是临时的，章节级重新生成 |
| 已遗忘（L4） | 不迁移 | 不需要 |
| 单元专属记忆 | 保留在单元上，不迁移 | 只在单元写作时用 |
| 角色状态 | 入口复制法（MVP） | 每章入口状态 = 单元入口状态，后续支持插值 |
| 压力曲线 | 单元压力作为基压，平均分配到每章 | MVP 简化，后续支持按情绪曲线分布 |
| 潜文本卡 | 单元级保留，拆章后每章可新建章节级卡 | 两个层级各管各的 |

---

## 十、编排师升级

### 10.1 接口

```python
class Orchestrator:
    # 旧接口（保留）
    def run_chapter(self, project_id, chapter_id, ...) -> OrchestratorResult

    # 新接口（单元模式）
    def run_unit(self, project_id, unit_id, step_no=None) -> UnitOrchestratorResult
    def continue_unit(self, project_id, unit_id) -> UnitOrchestratorResult
    def rewrite_from_step(self, project_id, unit_id, from_step) -> UnitOrchestratorResult
    def review_causality(self, project_id, unit_id) -> CausalReviewResult
```

### 10.2 单元写作工作流

```
1. 因果审查（Causal Review）
   ├─ 检查 cause_summary 与前一单元 effect_summary 衔接
   ├─ 检查要回收的伏笔是否已埋设（按 story_order）
   ├─ 检查要埋设的伏笔是否合理
   └─ 检查呈现顺序与因果顺序的一致性（提示倒叙）

2. 上下文组装（Context Assembly）
   ├─ 计算 token 预算
   ├─ 加载单元摘要（从最近快照）
   ├─ 回灌最近原文（按 token 预算从后往前取）
   ├─ 拉取因果上游单元的关键信息（按 story_order）
   ├─ 加载入口状态快照
   ├─ 加载全局 L1/L2 记忆
   └─ 组装成写作上下文

3. AI 生成

4. 写后处理
   ├─ 切分段落，写入 unit_paragraphs
   ├─ 提取实际埋设/回收的伏笔（挂到 paragraph_id）
   ├─ 提取记忆（带 unit_step）
   ├─ 更新角色状态
   ├─ 更新单元摘要
   └─ 写入断点快照

5. 完成检测
   ├─ 达到目标字数？→ 标记 completed
   └─ 没达到？→ 继续下一步
```

---

## 十一、数据迁移与兼容

### 11.1 老项目零迁移成本（空单元法）

- 所有新增表和字段，老项目自动为空 / 零值
- 查询时 `unit_id IS NULL OR unit_id = ''` 视为全局
- 老项目继续用章节模式，完全不受影响
- 老项目的 UI 默认显示章节视图

### 11.2 新项目默认单元模式

- 新项目默认用单元视图
- 大纲默认创建分卷 + 空单元列表
- 用户可以随时切换到章节视图（但建议用单元）

### 11.3 老项目升级工具（可选，后期做）

- 给老项目的每章包一个"虚拟单元"
- 1 章 = 1 单元，自动填充基本信息
- 用户可以在此基础上合并/拆分单元

---

## 十二、实施路径

### Phase 0：设计阶段 ✅ 本文档

### Phase 1：数据模型落地
- 数据库迁移脚本（036 / 037 / 038...）
- 所有表结构 + 索引 + 约束
- 数据模型 dataclass

### Phase 2：核心服务
- story_unit_service.py（CRUD + 双时间线 + 级联规则）
- unit_brief_service.py（单元大纲）
- unit_causal_service.py（因果边 + 剧情线）

### Phase 3：run_unit() 分段生成
- unit_writing_snapshots 管理
- 段落切分与 paragraph_id
- token 预算计算
- 写后处理（钩子/记忆/状态）
- 中断续写 + 重写机制
- 编排师 run_unit() 接口

### Phase 4：钩子单元适配
- unit_hook_map 的段落锚点机制
- 钩子双轨制（单元侧 + 章节侧）
- manual_locked 机制
- 伏笔检查（按 story_order）

### Phase 5：拆章器
- 第一层：正则 + 情绪词典
- 第二层：AI 情绪分析（可选）
- 断章模式匹配 + 痛感评分
- 断章报告生成
- 拆章执行 + 版本管理

### Phase 6：状态映射
- unit_chapter_mapper.py
- 各数据类型的映射策略
- 拆章事务保证

### Phase 7：UI
- 大纲 Tab 单元视图
- 视图切换（呈现顺序 / 故事时间）
- 单元详情面板
- 拆章交互（断章报告）
- 主窗口集成

### Phase 8：非线性叙事（高级功能）
- 因果边可视化
- 剧情线管理
- 衔接类型编辑
- 倒叙/并行线支持

---

## 十三、关键决策清单（已确认）

- [x] 架构定位：单元是上游创作层，章节是下游发布层
- [x] 记忆核心：L1-L4 分层不变，扩展双时间锚点
- [x] 双时间线：story_order（因果）+ present_order（呈现）
- [x] 衔接类型：8 种（direct/time_jump/pov_switch/flashback/parallel/chekhov/contrast/suspense_front）
- [x] 分段生成：多步 + 断点快照 + 摘要跟着快照走
- [x] 回原文：token 预算反推，不是固定 N 步
- [x] 重写级联：全量清理自动生成数据 + manual_locked 保留手动项
- [x] 钩子锚点：段落 ID，不是字符偏移
- [x] 钩子双轨制：单元侧 + 章节侧并行存在
- [x] 拆章器：三层结构（正则+AI+人工）
- [x] 断章模式：6 种 + 痛感评分
- [x] 重新拆章：版本管理 + is_current_version
- [x] 删除单元：弹窗三选一，不自动留孤儿
- [x] 状态映射：独立 unit_chapter_mapper 模块
- [x] 数据迁移：空单元法，老项目零成本
- [x] 编排师：双模式（run_chapter + run_unit）
- [x] 标签系统：Phase 0 不做，仅占位（见附录 A）

---

## 附录 A：待设计项

### A.1 单元标签系统（待设计，不进 Phase 0）

**方向**：单元多维标签化检索，提升单元的可重组性和素材库价值。

**待解决的问题**：
- 标签与现有表字段的边界（哪些走查询、哪些存标签）
- 标签质量保证机制（如何避免标签不准）
- 索引层设计（可重建的倒排索引）
- AI 辅助提取的准确率验证

**计划**：Phase 1-4 核心流程跑稳后，单独设计、单独实施。
