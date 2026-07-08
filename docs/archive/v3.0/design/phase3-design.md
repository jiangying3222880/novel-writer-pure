# Phase 3 设计文档

> 章节生成（mindset → writer → critic）+ 段落级编辑 + 扫描/重生成工具集

---

## 1. 目标

把章节生成从"占位"推到"可批量、可定点、可审计"。

核心场景：
- 一晚自动生成 50 章
- 第二天读到第 2 章不好，**只改一段**
- 看到 ch30 有连续性 bug，**扫前后找源头**
- 改主角目标，**保留 5 章重生成 35 章**
- ch3 引入"老王"想改成"老李"，**逐章决定改不改**

---

## 2. 核心架构

```
[Generate 按钮]
    ↓
ChapterGenerator (app/core/chapter_generator.py)  ← 纯 Python，确定性
    ↓
  1. 拉上下文 (brief + 上章 + 风格指纹 + 项目 anti_rules)
  2. MindsetAgent    → 6 问答案
  3. WriterAgent     → 流式正文
  4. CriticAgent     → 文学质量分 (0-100) + 6 维评语
  5. HookAnalyzer    → 追读潜力分 (0-100) + 5 维诊断  ← 独立 agent
  6. 落库:
     status = critiqued
     score < 60 ? review_flag='problem' : 'pending'
    ↓
[UI]  ✅/⚠️ 徽章 + 评语折叠面板
    ↓
[User 介入]  ← 用户是门卫
```

**4 agents 边界**：
| Agent | 职责 | 不做什么 |
|---|---|---|
| Mindset | 答 6 问 | 不写正文、不评分 |
| Writer | 写正文 | 不评分、不答 6 问 |
| Critic | 评文学质量（情节/人物/文笔/节奏/风格/伏笔） | 不修改、不评追读 |
| HookAnalyzer | 评追读潜力（5 维） | 不评文学质量、不修改 |
| ChapterGenerator | 调 agent + 落库 + 决策 | 不调 LLM 决策（用 if-else） |

**Critic vs HookAnalyzer**：
- Critic 视角 = 文学编辑（"这章写得好不好"）
- HookAnalyzer 视角 = 模拟读者（"读完想不想读下一章"）
- 两者不冲突，可独立输出，结果都进 `chapters.critique` JSON
- 理想状态 = 两者都高；可能冲突（高质量低追读 = 文艺腔；低质量高追读 = 套路爽点）

---

## 3. 心智清单（写作前必答，按优先级）

| # | 问题 | 优先级 | 对应规律 |
|---|---|---|---|
| 4 | 这场戏我**不**写什么？（列 2-3 项，允许"无"） | ★★★★★ 总锚点 | 解释太多 |
| 1 | 这一场从头到尾**不变**的那个东西是什么？ | ★★★★☆ 氛围锚点 | 氛围断裂 |
| 2 | 这个角色此刻**最不显眼但最真实**的身体细节是什么？ | ★★★☆☆ | 动作冗余 |
| 3 | 事发瞬间，角色**身体先于语言**的反应是什么？ | ★★★☆☆ | 情感反应不到位 |
| 5 | 开场第一个**进入**的是什么？结尾停在哪**未完成**的画面上？ | ★★★☆☆ | 解释太多 |
| 6 | 角色嘴上说的和心里想的，**差距最大**的一次是什么？ | ★★★☆☆ | 对话 AI 味 |

**答案质量门**：
- 每问 ≤ 50 字
- 至少 1 个具体名词
- Q4 允许回答"无"（防止凑数）
- 单轮生成（不为 AI 加复杂度）

**Critic 固定检查项**：
> 本场是否存在纯动作/纯留白段落，且没有附加解释？
> 无则扣分。

---

## 4. 数据层（3 张新表 + 1 列扩展）

### 4.1 新表

```sql
-- 1. 多版本快照（支持"回到前一版"）
CREATE TABLE chapter_drafts (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,           -- 1, 2, 3, ...
    content TEXT NOT NULL,
    source TEXT NOT NULL                   -- 'agent' | 'user' | 'paragraph_rewrite'
        CHECK(source IN ('agent', 'user', 'paragraph_rewrite', 'merge')),
    parent_draft_id TEXT REFERENCES chapter_drafts(id) ON DELETE SET NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(chapter_id, version_no)
);

CREATE INDEX idx_chapter_drafts_chapter ON chapter_drafts(chapter_id);

-- 2. 修改流水（审计/撤销/回溯）
CREATE TABLE chapter_change_log (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    change_type TEXT NOT NULL              -- 'regen' | 'paragraph_rewrite' | 'manual_edit' | 'entity_reshape'
        CHECK(change_type IN ('regen', 'paragraph_rewrite', 'manual_edit', 'entity_reshape')),
    scope TEXT NOT NULL                     -- 'chapter' | 'paragraph'
        CHECK(scope IN ('chapter', 'paragraph')),
    target_draft_id TEXT REFERENCES chapter_drafts(id) ON DELETE SET NULL,
    note TEXT,                              -- 用户反馈 / critic 评语
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX idx_change_log_chapter ON chapter_change_log(chapter_id, created_at DESC);

-- 3. 实体引用索引（实体重塑 / 扫前后用）
CREATE TABLE entity_appearances (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,              -- 'character' | 'location' | 'item' | 'faction'
    entity_name TEXT NOT NULL,
    chapter_id TEXT NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    draft_id TEXT REFERENCES chapter_drafts(id) ON DELETE CASCADE,
    paragraph_index INTEGER,                -- 段落序号（用于段落级定位）
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX idx_entity_appearances_entity ON entity_appearances(project_id, entity_name);
CREATE INDEX idx_entity_appearances_chapter ON entity_appearances(chapter_id);
```

### 4.2 `chapters` 表扩展

```sql
ALTER TABLE chapters ADD COLUMN current_draft_id TEXT REFERENCES chapter_drafts(id) ON DELETE SET NULL;
```

`chapters.draft` 保留作为"最新文本的快读字段"，`current_draft_id` 指向 `chapter_drafts` 的当前活跃版本。

### 4.3 复用现有

- `chapters.review_flag`（已存在：`pending` / `accepted` / `problem`）直接用
- `chapters.critique`（已存在：TEXT）存 critic 的 JSON
- `chapters.final`（已存在：TEXT）存用户采纳后的最终稿
- `agent_memory`（已存在：L1-L4）存 L1 风格指纹 / L2 潜文本卡注入

---

## 5. 6 个工具与 UI 设计

### 5.1 工具清单

| # | 工具 | 触发 | 粒度 | LLM | 文件 |
|---|---|---|---|---|---|
| 1 | ✏️ 段落重写 | 编辑器段落右击 | paragraph | 1×writer-mini | `app/core/paragraph_rewriter.py` |
| 2 | ✅ 全文采纳 | 生成面板按钮 | chapter | 0 | `chapter_generator.py` |
| 3 | 🔍 扫前后 N 章 | 章列表右击 | chapter list | 1×scanner | `app/core/scanner.py` |
| 4 | 📝 实体重塑 | 实体卡片面板 | entity → chapters | N×writer（用户确认后逐章） | `app/core/entity_manager.py` |
| 5 | 🔄 批量重生成 | 顶部工具栏 | multi-chapter | N×chapter_gen（后台任务） | `app/core/batch_regenerator.py` |
| 6 | 📊 编辑器评估面板 | 编辑页顶部静态栏 | chapter | 手动触发 | `editor_tab.py` |

**UI 约束**：
- 每个 AI 输出都标 `⚠️ AI 判断仅供参考`
- 每个工具都明示作用域（"扫前后"还是"仅后续"？，"本段"还是"全文"？）

### 5.2 HookAnalyzer 5 维评估

| 维度 | 权重 | 评估什么 |
|---|---|---|
| 末段钩子 | 0-25 | 最后 200 字是否"未完成"——画面/动作/对话/沉默，不是总结 |
| 下章衔接 | 0-25 | 是否给下章留了"必须读下去"的问题/期待/缺口 |
| 章中微钩子密度 | 0-20 | 中段每 500-800 字是否有小钩子（悬念/反常/暗示/未说出口的话） |
| 承诺兑现 | 0-15 | 本章是否兑现上一章的期待？兑现方式是否出乎意料 |
| 信息密度曲线 | 0-15 | 密度是否递增（开头低 → 中段升 → 末段峰值）；平线 = 拖 |

5 维独立打分，加权得总分。HookAnalyzer 的 prompt 比 Critic 简单——只问"读完想不想读下一章"。

**6 问 ↔ HookAnalyzer 闭环**：
- Q5"结尾停在哪未完成的画面上" = writer 的**意图**
- HookAnalyzer 末段钩子分 = **实际结果**
- UI 上对照展示"意图 vs 实际"（详见 5.3）

### 5.3 编辑器评估面板（顶部静态栏）

```
┌───────────────────────────────────────────────┐
│ 第三章 · 巷子里的脚步声              [评估 ▼] │
│ ─────────────────────────────────────────────  │
│ 📖 75     🎯 60     [🔄 重新评估]              │
│ ─────────────────────────────────────────────  │
│ ▼ 详情（点击展开）                              │
│   质量 6 维：节奏 12/15  风格 10/15  ...       │
│   追读 5 维：末段钩子 8/25  下章衔接 12/25 ... │
│   🎯 意图 vs 实际：                            │
│      Q5 意图：停在主角回头那一刻               │
│      实际评估：末段动作是"叹了口气" → 完成动作 │
└───────────────────────────────────────────────┘

  [编辑区 - 干净，无干扰]
```

**3 条边界（卡死，防 2.0）**：
1. ❌ **不按键重算**——每次打字不重跑
2. ❌ **不保存重算**——用户 ctrl+s 不触发
3. ❌ **不按段落染色**——不把段落标红标绿

**重算按钮组（按轴评估，省 tokens）**：

| 按钮 | 行为 | 预估 tokens |
|---|---|---|
| 📖 75（点此） | 只重算 Critic 6 维 | ~9k |
| 🎯 60（点此） | 只重算 Hook 5 维 | ~6.5k |
| 📊 全部重算 | 跑两个（**显式**） | ~15k ⚠️ |

**成本护栏**：
- 每章每会话 5 次上限，按钮 badge 显示 `(3/5)`
- 达到上限灰掉，弹"已用完额度，下次会话重置"
- 按钮 label 明码标价 token 预估
- **不让"评估方便"变成"评估上瘾"**

**状态样式**：
- `review_flag='pending'` → 评分栏正常色
- `review_flag='problem'` → 评分栏**浅红高亮**（眼缘提示，不喊）

### 5.4 仪表盘布局

```
┌──────────────────────────────────────────────────────┐
│ 📊 仪表盘 — 《XXX》                                   │
│                                                       │
│ ┌────────┐ ┌────────┐ ┌────────┐                    │
│ │ 章节   │ │ 质量   │ │ 追读   │                    │
│ │  50   │ │  72   │ │  58   │                    │
│ │ 待修 3│ │ 中位数 │ │ 中位数 │                    │
│ └────────┘ └────────┘ └────────┘                    │
│                                                       │
│ 趋势 (50 章, sparkline):                              │
│ 📖 ▁▂▂▃▃▄▅▅▆▆▇▇██▆▇▇████▇▆▆▇▇█▇▇                   │
│ 🎯 ▁▁▂▂▃▃▂▂▃▃▄▄▅▅▆▆▇▇█▇▆▆▇▇▇█▇▇                   │
│                                                       │
│ ⚠️ 建议关注 (低分章节):                                 │
│  ch12  📖60 🎯45  [→ 编辑] [→ 扫前后]                │
│  ch23  📖65 🎯40  [→ 编辑] [→ 扫前后]                │
│  ch31  📖70 🎯50  [→ 编辑] [→ 扫前后]                │
└──────────────────────────────────────────────────────┘
```

**仪表盘只展示分数，不展示**：
- ❌ 11 维细分（属 editor 页）
- ❌ 6 问答案（属 generate 页）
- ❌ 改写建议、批量操作按钮（属工具栏）
- ❌ 预测追读率、预估收入等 AI 幻觉

**Top 5 弱章列表**：按综合分排序（质量 60% + 追读 40%），每行只 2 个数字 + 跳转按钮。**不做加权总分**——避免用户"为总分优化"心态。

**实施节奏**：
- M2 完成后可接 M3 之前先把 dashboard 的"3 大数字 + sparkline"接上（M2.5 性质）
- "Top 5 弱章列表"等 M3 段落重写工具就位后再加（不然没跳转目标）

---

## 6. 文件结构（新增）

```
app/core/
  chapter_generator.py      # 编排器（M1）
  mindset.py                # 6 问 agent（M2）
  writer.py                 # writer agent（M2）
  critic.py                 # critic agent（M2）
  hook_analyzer.py          # 追读率 agent（M2.5）
  paragraph_rewriter.py     # 工具 1（M3）
  scanner.py                # 工具 3（M4）
  entity_manager.py         # 工具 4（M5）
  batch_regenerator.py      # 工具 5（M6）

app/ui/tabs/
  generate_tab.py           # 改造: 接入 ChapterGenerator + 流式（M1-M2）
  editor_tab.py             # 改造: 段落右击 + 评估面板（工具 1, 工具 6）（M2.5, M3）
  dashboard_tab.py          # 改造: 3 大数字 + sparkline + Top5 弱章（M2.5 + M3）
  entity_tab.py             # 新: 实体管理面板（M5）
  settings_tab.py           # 维持现状（已有）

app/db/migrations/
  005_chapter_drafts.sql
  006_chapter_change_log.sql
  007_entity_appearances.sql
  008_chapters_current_draft_id.sql
```

`app/core/__init__.py` 已存在（空），加模块后保持不变。

---

## 7. 实施顺序（M0 → M6）

| 步骤 | 内容 | 验证方式 | 依赖 |
|---|---|---|---|
| **M0** | 4 张迁移 SQL + chapter_service 扩 draft API | smoke test: 多版本 draft 创建/查询/回滚 | 无 |
| **M1** | ChapterGenerator 骨架 + mock agents | UI 跑流程，不接 LLM，看状态机正确 | M0 |
| **M2** | 3 agents 接真 LLM（顺序：mindset → writer → critic） | 离屏跑 1 章，看完整 6 问答案 + 正文 + 评分 | M1 |
| **M2.5** | HookAnalyzer 接 LLM + 编辑器评估面板 + dashboard 3 大数字 + sparkline | 离屏跑 1 章看 hook 5 维；UI 顶部静态栏可见；dashboard 有数字 | M0, M2 |
| **M3** | 段落重写 + 编辑器右击菜单 + dashboard Top5 弱章 | 选中段落 → 输入反馈 → 重写 → 替换；旧段进 history；dashboard 跳转可用 | M0, M2.5 |
| **M4** | 扫前后 N 章（scanner） | 给定修改 → 列出受影响章节 + 理由 | M0, M2 |
| **M5** | 实体管理面板 + 实体索引（生成时自动建） | 改实体卡片 → 列出影响章节 → 用户逐章决定 | M0, M2 |
| **M6** | 批量重生成（后台 QThread） | 选 3 章 → 进度条 → 完成通知 | M2 |

每步独立可验证，**前一步不通过不进下一步**。

**M2.5 的存在理由**：HookAnalyzer 和 editor 评估面板有强耦合（评分是 UI 静态栏的输入），dashboard 的大数字也是评分聚合。三者一起做比拆开做更省集成时间。M2.5 严格小于 M3 范围（不包含段落重写和 Top5 跳转）。

---

## 8. 7 条反 2.0 原则

1. **用户始终是创作主体** — AI 是顾问/工具，不替用户决定
2. **没有自动级联** — 改 ch2 不自动改 ch3+
3. **没有 AI 决策门** — critic 是 advisor，不是 gatekeeper
4. **作用域明示** — 项目级/场景级、全文/从今往后，UI 必须标注
5. **AI 输出标"⚠️ 仅供参考"** — 不让用户产生"AI 一定对"的错觉
6. **不为 AI 服务加复杂度** — 砍掉"两轮生成"等为 AI 兜底的设计
7. **不能让"评估方便"变"评估上瘾"** — 每次重算上限 5 次/章/会话，按轴评估为默认，明码标价 token

## 9. 4 个"不做"边界（防膨胀）

- ❌ 多 phase 模式（旧 engine 3/4/5 phase）
- ❌ 自动级联同步
- ❌ 双版本选择（version_a/b）
- ❌ 段落级染色标红/标绿（避免"为分数写"心态）

---

## 10. 与项目既有机制的衔接

| 既有 | 本期如何用 |
|---|---|
| `anti_rules`（项目级，settings） | 注入 L1，作为"前瞻约束" |
| 场景级"不写清单"（Q4 答出） | 注入 writer prompt，本章临时禁区 |
| `agent_memory` L1/L2 | 风格指纹 + 潜文本卡注入 |
| `chapters.review_flag` | 直接复用，值映射：pending / accepted / problem |
| `chapters.critique` | 直接复用，存 critic JSON |
| 旧版 `de_ai.py`（archived） | 不直接复用，但思路可借鉴：E7 情感衰减、E8 节奏、E5 对话归属——可作为 critic 评分子项 |
| 旧版 `writer_agent.py`（archived） | 不直接复用，旧 prompt 的"文笔优美、描写细腻"反向示例要避免 |

---

## 11. 开放问题

### 数据 / 流程
- **Q1**: 批量重生成（M6）失败回滚策略？整批回滚 / 按章回滚 / 不回滚？
- **Q2**: `entity_appearances` 实体识别用 NER 还是规则？NER 准但慢，规则快但漏
- **Q3**: 段落重写时是否向 writer 暴露上一稿？默认不暴露，但允许用户主动"基于上稿改"（多一开关）
- **Q4**: 项目级 `anti_rules` 的"作用域明示"——是设置项（`apply_to: future|all`）还是默认"future"且不可改？

### 仪表盘（M2.5）
- **Q5**: 仪表盘"质量均分"用**平均**还是**中位数**？我倾向中位数（单章异常不拉低整体感）
- **Q6**: 趋势线显示**全部**章还是**最近 N 章**？我倾向全部可缩放
- **Q7**: "建议关注"的**阈值**？我倾向追读 < 50 **或** 质量 < 60（用户可调设置项）
- **Q8**: 是否显示**"上次会话"对比**（▲+5 之类）？我倾向显示"最近 7 天 vs 之前"

### 成本控制（M2.5）
- **Q9**: 重新评估按钮的 token 预估（9k / 6.5k / 15k）怎么算？按章节字数**动态算**还是**写死**？我倾向动态算（章节长就预估高）
- **Q10**: "5 次/章/会话"上限到点之后，是**灰按钮**还是**弹付费升级**？我倾向灰按钮（单机场景不搞付费）

---

## 12. 验收总目标

**M6 完成后**，用户能完成以下工作流：
1. 创建项目 → 走完引导对话 → 生成第 1 章 → 流式看到正文 → 评分（质量+追读） → 采纳/段落修改
2. 一晚批量生成 ch1-ch20 → 第二天逐章检查 → 段落级修改 → 扫前后找冲突 → 手动修复
3. 改主角目标 → 实体卡片更新 → 实体管理列出影响章 → 逐章决定
4. 项目设置中加 anti_rule → 后续章节自动遵守
5. 任何修改可追溯（drafts + change_log），可回滚
6. **仪表盘**一眼看全书质量/追读中位数 + sparkline + Top 5 弱章跳转
7. **编辑器评估面板**显示静态分数 + 按轴重算（带 token 标价）+ 5 次/章上限
8. 6 问意图 vs HookAnalyzer 实际结果对照可见

**核心质量门**：用户读 AI 写的章节，**不会被 4 条 AI 规律（解释太多/氛围断裂/动作冗余/反应不到位）显著打扰**。

**核心成本门**：50 章项目单轮评估总开销 ≤ ¥100；每章重算 ≤ 5 次/会话不被突破。

---

## 13. M2 前置子任务：模型配置

> 用户原话：之前 2.0 项目有很多 prompt 可以选择的 → 实指**模型配置**（不是 prompt 模板）。
> 状态：**待办**（用户 2026-06-08 关机前登记，下次回来做）

### 13.1 2.0 已有的能力（参考点）

参考文件 [`_archived/backend-2026-06-08-tauri-era/workflow/ai_client.py`](file:///d:/novel-writer-pure-v4/_archived/backend-2026-06-08-tauri-era/workflow/ai_client.py)：

- **27 个厂商预设**：`PROVIDER_PRESETS` dict（openai / anthropic / google / deepseek / moonshot / 智谱 / 百度千帆 / 阿里通义 / 腾讯混元 / groq / openrouter / siliconflow / ollama / custom 等）
- **Provider 链**：primary + fallback，按 `priority` 顺序自动切换
- **每 provider 字段**：`name` / `provider_type` / `api_base` / `api_key` / `model` / `max_tokens` / `temperature` / `timeout` / `is_stream` / `priority`
- **调用方式**：`chat()`（非流式）+ `chat_stream()`（SSE 流式）
- **UsageRecord**：记录每次调用的 `tokens_in` / `tokens_out` / `cost` / `duration_ms` / `provider` / `model` / `step`

### 13.2 v4 现状（差距）

- `app/core/` 没有 LLM 客户端
- `setting_service.py` 只管 6 个**项目级** key（`worldbuilding` / `characters` / `hooks` / `voice_profiles` / `anti_rules` / `style_fingerprint`），**没有全局 app settings**（无 api_key、无 provider 配置）
- `settings_tab.py` 是项目级设定 UI，**没有"🤖 模型"入口**
- `ChapterGenerator` 3 个 agent 全是 mock，等 M2 替换

### 13.3 实施子任务（4 步）

| 步 | 动作 | 文件 |
|---|---|---|
| 1 | 新建 `LLMClient`：**同步版**（不用 asyncio，PyQt6 主线程用 QThread 包装即可），继承 27 厂商预设，支持 OpenAI 兼容 + Anthropic + Ollama 三种请求格式，分支用 `provider_type` 判断 | `app/core/llm.py` |
| 2 | 新建全局 app settings 服务：JSON 文件存 `%APPDATA%/NovelWriterPure/app_settings.json`，结构 `{providers: [...], active_provider: <name>}` | `app/services/app_setting_service.py` |
| 3 | `SettingsTab` 加 `🤖 模型` 子页：provider 列表（左）+ 选预设/填 api_key/api_base/model/max_tokens/temperature/timeout 表单（右）+ 保存/测试连接按钮 + 切换 active | `app/ui/tabs/settings_tab.py`（改造） |
| 4 | `ChapterGenerator` 接受 `llm_client` 注入参数；新建 `MindsetAgent` / `WriterAgent` / `CriticAgent` 三个真 LLM 实现，替换 mock，**保留 callback 接口**（on_mindset / on_chunk / on_critic / should_cancel）不变 | `app/core/chapter_generator.py`（改造） + 新建 `app/core/mindset.py` / `app/core/writer.py` / `app/core/critic.py` |

### 13.4 设计原则（与 7 条反 2.0 原则对齐）

1. **配置项不绑项目** — 全局，跨项目复用（用户一台机器可能用同一个 deepseek key 写多本书）
2. **fallback 链用户可控** — 简单场景：1 个 active provider 即可；高级：支持 priority 排序
3. **API key 加密存？** — 先明文存 JSON（单机桌面场景可接受），后续再说加密
4. **测试连接按钮** — UI 调 `chat()` 一次，发 "hi"，返回成功 → 标绿
5. **不预设厂商** — 第一次启动 SettingsTab 模型页是空的，用户主动加

### 13.5 验收标准

- [ ] `LLMClient` 单元测试覆盖：OpenAI 协议解析 / Anthropic 协议解析 / 流式 SSE chunk 解析 / provider fallback 切换 / 超时
- [ ] `app_setting_service` 单元测试：get / set / list / delete provider / set_active
- [ ] `SettingsTab` UI 测试：加载 / 保存 / 测试连接 / 切换 active
- [ ] `ChapterGenerator` 真 LLM smoke：离屏跑 1 章，3 个 agent 都调 LLM，完整 6 问 + 正文 + 评分落库
- [ ] `m2_smoke.py` 跑通，**M2 步骤可推进**

### 13.6 与原计划的差异

- **新增步骤 1-3 是 M2 真正能跑通的前置**（M2 行原描述"接真 LLM"暗含了这件事，但没拆出来）
- **步骤 4 的 3 个 agent 文件**与第 6 节"文件结构（新增）"中的 `mindset.py` / `writer.py` / `critic.py` 对应（不是新增文件，是从 M2 步骤里前置到 13.3）
- **未引入 asyncio**：v4 是同步 + QThread 模型，与 2.0 的 asyncio 不一致

