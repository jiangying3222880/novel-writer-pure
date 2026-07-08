# Subtext Card 引入方案：3.0 → 4.0 详细对比与评审

> **生成时间**: 2026-06-09
> **目的**: 把 3.0 已验证的 subtext card 业务逻辑搬回 4.0，按"逐条折板"评审
> **核心原则**: 4.0 不直接搬 3.0 代码（带 bug），但业务设计可照搬
> **关联文件**:
> - 3.0 原始实现: `D:\novel-writer-pure\app\workflow\subtext_card.py` (455 行)
> - 3.0 反规则合并: `D:\novel-writer-pure\app\workflow\anti_rule.py`
> - 3.0 prompt 注入: `D:\novel-writer-pure\app\workflow\prompts.py`
> - 3.0 UI dialog: `D:\novel-writer-pure\app\ui\dialogs\subtext_card_dialog.py`
> - 3.0 测试: `D:\novel-writer-pure\tests\backend\test_subtext_card_v3.py` (7 用例)
> - 3.0 已知 bug: `D:\novel-writer-pure\.workbuddy\memory\MEMORY.md` 第 36-46 行
> - 4.0 现状架构: `d:\novel-writer-pure-v4\app\core\prompt_assembler.py` + `chapter_generator.py`

---

## 1. 整体概览

### 1.1 业务目的

subtext card（潜文本卡）解决的是 **AI 写作"嘴和心不匹配"** 问题 —— 角色嘴上说一套、心里想另一套时，AI 容易写成"AI 腔对话"。给 LLM 一份**显式结构化的"潜台词清单"**，AI 才有素材让对话留白、让动作反向走。

### 1.2 与现有 6 问的关系（核心消歧）

| 维度 | 6 问（4.0 已有） | Subtext Card（3.0 有/4.0 缺） |
|---|---|---|
| 何时生成 | 写作前动态答 | 写作前由用户/AI/插件生成并**显式存盘** |
| 颗粒度 | 一段戏一个问题 | 一整章一张或多张卡（≤3 张） |
| 持久化 | ❌ 写完即丢 | ✅ 入 `scene_subtext_cards` 表 |
| 可复盘 | ❌ 翻不回去 | ✅ 跨章比对、批量重写 context |
| 字段数 | 6 问文字 | 13 字段结构化 |
| 解决痛点 | 4 大规律（解释太多/氛围断裂/动作冗余/情感不到位） | **嘴心不匹配** / 潜台词断裂 / 空间错乱 |

**结论**: 不重合，互补。6 问是"临场纠偏"，subtext card 是"显式结构"。

### 1.3 数据流对比

**3.0 数据流**:
```
Brief  ──┐
          ├─→ AI generate ─→ JSON 容错 ─→ 用户采纳 ─→ DB
上章摘要 ─┘                                          ↓
RAG 预拉取                                     prompt 注入（≤3 张）
                                                  ↓
                                            Writer 写正文
                                                  ↓
                                            Self-Critique
                                                  ↓
                                            Persist
```

**4.0 现状数据流**:
```
Brief  ─→ 6 问（临场）─→ Writer prompt
Setting ────────────────→ Writer prompt
                                ↓
                              写正文
                                ↓
                          Critic/Hook 评估
                                ↓
                              Persist
```

**缺什么**: brief 和 setting 之间，**没有"显式结构化的潜台词素材"** 这一层。

---

## 2. 字段逐条对比（3.0 vs 4.0 现状）

### 2.1 数据结构（核心 5+8 字段）

| # | 字段 | 3.0 类型 | 3.0 用途 | 4.0 现状 |
|---|---|---|---|---|
| 1 | `surface_event` | str | 表面发生什么 | ❌ 无 |
| 2 | `real_intent_protagonist` | str | 主角真实意图 | ❌ 无 |
| 3 | `lie` | str | 主角的谎 | ❌ 无 |
| 4 | `truth` | str | 主角的真 | ❌ 无 |
| 5 | `physical_anchor` | str | 身体信号 | ❌ 无 |
| 6 | `real_intent_others` | dict | 其他人真实意图 | ❌ 无 |
| 7 | `emotional_undercurrent` | str | 情绪底层 | ❌ 无 |
| 8 | `pacing` | str | 节奏 | ❌ 无 |
| 9 | `viewpoint` | str | 视角 | ❌ 无 |
| 10 | `scene_map` | `[(人,位置,朝向)]` | 场景地图 | ❌ 无 |
| 11 | `ending_scene_state` | str | 结尾场景状态 | ❌ 无 |
| 12 | `callback_to` | str | 呼应的前文 | ❌ 无 |
| 13 | `anti_rules` | list[str] | 单章反规则（override） | ⚠️ 只在 `setting_service.anti_rules` 有项目级 |
| 14 | `source` | enum | manual/ai/plot_deduction | ❌ 无 |
| 15 | `created_at/updated_at` | datetime | 时间戳 | ❌ 无 |

### 2.2 字段功能详评

#### ⭐ 字段 1-5（核心 5 字段）- **建议必入**

**subtext card 的灵魂**。

- `surface_event` + `real_intent_protagonist` 形成"嘴心对比"对子 → 直接喂给 LLM「表面说 A，实际想 B」模板
- `lie` + `truth` 形成"角色自欺"对子 → 推进角色弧光
- `physical_anchor` 解决 4.0 6 问里"身体先于语言"的痛点，但**显式可编辑**（6 问是临场口述）

**4.0 现状等价物**:
- 6 问中"3. 身体先于语言"是临场答的 → **subtext card 把这个临场答案固化**

#### 字段 6 `real_intent_others` - **建议入**

多人场景必备。3.0 写 dialog 时常用：
```json
"real_intent_others": {
  "林婉": "试探主角是否记得她",
  "王医生": "掩盖手术失误"
}
```
不存的话，多角色对话容易写成"各说各话"。

#### 字段 7 `emotional_undercurrent` - **建议入**

"紧张 / 暗流 / 压抑 / 表面平静"等情绪词。**直接对应 4.0 6 问中"1. 不变氛围"** → 把临场氛围词也固化。

#### 字段 8-9 `pacing` / `viewpoint` - **可选**

3.0 这俩字段用得不多（默认填"第三称限知/中速"），多为复制粘贴。**可省**。

#### ⭐ 字段 10 `scene_map` - **强烈建议入**

3.0 解决"空间错乱"的杀手锏。比如：
```json
"scene_map": [
  ["林婉", "门内", "面朝门"],
  ["主角", "门外", "背对林婉"]
]
```
Writer 写「她转过身」时直接用，不凭空想象。

**4.0 现状无对应字段** → 空间错乱完全靠 LLM 自我约束。

#### 字段 11-12 `ending_scene_state` / `callback_to` - **建议入**

- `ending_scene_state`: 章末定格画面（强 hook 设计）
- `callback_to`: 呼应的前文伏笔/道具（"老怀表"第一次出现 vs 第二次出现）

**4.0 现状**: 6 问中"5. 呼应的前文"是临场答，**subtext card 把它存盘**，跨章时可批量看哪些章用了哪些呼应收束。

#### ⭐ 字段 13 `anti_rules`（章节级 override）- **强烈建议入**

3.0 业务核心设计：`get_full_anti_rules` = **项目级** + **章节级** 合并

- 项目级：永久反规则（来自 `meta.global_anti_rules`）
- 章节级：本章临时反规则（来自 `scene_subtext_cards.anti_rules`）
- 都先解析 `{GENRE}` / `{HOOK}` 等占位符

**4.0 现状**:
- `setting_service.anti_rules` 存项目级 ✅
- **章节级 override 完全没有** → 本章想临时加"不要写血腥"，要么改项目级（污染全局），要么靠 6 问里"4. 不写什么"（临场口述，AI 可能忘）

**强烈建议补这一条**。

#### 字段 14 `source` - **必入**

D2 决策：AI 生成**不直写 DB**，用户点"采纳"才入库 → `source='manual'`

不加这个字段就分不清"AI 提的草稿" vs "用户最终用的"，无法做版本管理。

#### 字段 15 `created_at/updated_at` - **必入**

调试 / 排序 / 评测都需要。

---

## 3. 业务流程逐条对比

### 3.1 卡的生成（3 来源）

3.0 三模式:
1. **手填** (`save_manual_card`): 用户编辑表单
2. **AI 生成** (`generate_subtext_card_via_ai`): 读 brief + 上章摘要 + RAG 预拉取 → prompt → JSON 容错 → **不直写 DB** → 用户采纳后入库
3. **plot_deduction 插件** (`plot_deduction_plugin.py`): 推测用剧情推导

| 维度 | 3.0 | 4.0 建议 |
|---|---|---|
| 手填 | ✅ | ✅ 必入 |
| AI 生成 | ✅ | ⚠️ 4.0 RAG 暂未接（建议先做"手填+AI mock"） |
| plot_deduction | ✅ | ❌ 暂不补（4.0 无插件架构） |

### 3.2 JSON 容错（3 重回退）

3.0 `_safe_json_loads` 设计:
```python
def _safe_json_loads(text, default=None, field_name="field"):
    # 1. 直 json.loads
    # 2. 提取 ```json ... ``` 块
    # 3. 找第一个 { 到最后一个 } 区间
```

**3.0 已知 bug**: Self-Critique 解析脆弱（靠正则提 JSON）→ 已用 `_safe_json_loads` 修（6 个测试覆盖）

**4.0 建议**: 直接复用 3.0 的 `_safe_json_loads` 实现 + 7 个测试用例搬运

### 3.3 反规则合并（核心业务）

3.0 `get_full_anti_rules` 流程:
```
项目级 anti_rules (永久)
    ↓ 占位符解析 ({GENRE} → "悬疑")
章节级 anti_rules (本章临时)
    ↓ 占位符解析
合并去重
    ↓
注入 Writer prompt
```

**4.0 现状**:
- 项目级 ✅（在 `setting_service.anti_rules`）
- 章节级 ❌（无 subtext card 自然就没）
- 占位符解析 ❌（`prompt_assembler` 直接拼字符串）
- 合并去重 ❌

**建议补全这整套**：占位符解析 + 合并去重是**通用工具**，应该抽到 `app/core/prompt_utils.py`。

### 3.4 prompt 注入位置

3.0 Writer v3 prompt 结构（11+ 段）:
```
[SYSTEM]
  1. 世界观 (worldbuilding)
  2. 角色 (characters)
  3. 风格指纹 (style_fingerprint)
  4. 声音档案 (voice_profiles)
  5. 反规则 (anti_rules, 含占位符解析)
  6. 全局提示

[USER]
  7. brief
  8. 上章摘要 / RAG 上下文
  9. 6 问答案
  10. 潜文本卡 (≤3 张)
  11. scene_map / ending_scene_state
  12. 章节 anti_rules override
```

4.0 现状（[prompt_assembler.py](file:///d:/novel-writer-pure-v4/app/core/prompt_assembler.py)）:
```
[SYSTEM]
  1. worldbuilding
  2. characters
  3. style_fingerprint
  4. voice_profiles
  5. anti_rules
  6. hooks

[USER]
  7. brief
  8. mindset 6 问
  (❌ 无潜文本卡)
  (❌ 无 scene_map)
  (❌ 无章节级 anti_rules override)
```

**差距**: 4.0 缺 3 段（10/11/12）。

### 3.5 UI 层

3.0 入口: `ui/dialogs/subtext_card_dialog.py` (在章节编辑 Tab 里点按钮打开)

4.0 现状:
- EditorTab 已经有 EvaluationPanel（Critic 6 维 + Hook 5 维）✅
- 没有 subtext card 子面板 ❌

**建议**: EditorTab EvaluationPanel **下方加一个 GroupBox「🎭 潜文本卡」**，内嵌一个 sub-card 列表 + 「+ 新建 / 🤖 AI 生成 / 💾 保存」按钮。

---

## 4. 引入功能优劣矩阵

### 4.1 优势（补回后 4.0 获得什么）

| # | 优势 | 量化 | 对应痛点 |
|---|---|---|---|
| A | **结构化潜台词** | 13 字段固化，可跨章比对 | AI 腔对话 |
| B | **嘴心对比显式** | surface/lie/truth 3 对子直接喂 LLM | 角色无弧光 |
| C | **场景地图** | `[(人,位置,朝向)]` 显式定位 | 空间错乱 |
| D | **章节级反规则 override** | 临时加"本章不要血腥"不污染全局 | 项目级反规则太死 |
| E | **章末定格 + 呼应收束** | ending_scene_state + callback_to | 追读率弱 |
| F | **3 模式生成** | 手动/AI/插件，AI 不直写 DB | 信任与可控 |
| G | **跨章复盘** | 显式存盘后仪表盘可统计"哪些章用了哪些 subtext" | 调优黑盒 |
| H | **段落重写 context** | `paragraph_rewriter` 注入 subtext_card section | 重写时丢失潜台词 |

### 4.2 劣势 / 风险（引入后 4.0 多出什么负担）

| # | 风险 | 量化 | 缓解 |
|---|---|---|---|
| α | **代码量 +** | 估算 +600~900 行（dataclass + service + UI + prompt + 测试） | 拆 P1/P2 折板 |
| β | **LLM 调用次数 +** | AI 生成卡每次调 1 次 LLM（生草稿不直写），用户可不用 | 默认不开启 AI 模式 |
| γ | **3 重 JSON 容错** | 3.0 已修 6 个测试，4.0 复用即可 | 搬运 `_safe_json_loads` |
| δ | **UI 复杂度 +** | EditorTab 多一个子面板（不重，可折叠） | GroupBox 默认折叠 |
| ε | **DB 写 +** | subtext 1 章可挂 3 张卡，写 1 次即可 | 不写则零负担 |
| ζ | **3.0 已知 bug 复现** | Self-Critique 解析脆弱（_safe_json_loads 已修）+ RAG 无 API 精度低 | 不复用 3.0 代码，按 4.0 干净架构重写 |

### 4.2.1 Tokens 消耗估算（按"写一本书 = 100 章"基准）

**计价基准**（按 4.0 当前活跃模型，gpt-4o-mini / qwen-turbo 量级）：
- input ≈ ¥1.0 / 1M tokens
- output ≈ ¥4.0 / 1M tokens

| 折板 | 触发时机 | input 增量/次 | output 增量/次 | 100 章累计 input | 100 章累计 output | 折算 ¥ |
|---|---|---|---|---|---|---|
| **P1-1** dataclass 13 字段 | 0 | 0 | 0 | 0 | 0 | 0 |
| **P1-2** CRUD service | 0 | 0 | 0 | 0 | 0 | 0 |
| **P1-3** EditorTab 子面板 | 0 | 0 | 0 | 0 | 0 | 0 |
| **P1-4** 注入 3 段（subtext+scene_map+anti_override）| 写每章 1 次 | +1500 | 0 | 150K | 0 | ¥0.15 |
| **P1-5** smoke 测试 | 0 | 0 | 0 | 0 | 0 | 0 |
| **P2-1** prompt_utils 占位符解析 | 0 | 0 | 0 | 0 | 0 | 0 |
| **P2-2** AI 生成 subtext 卡 | 用户在 30% 章启用 | +2500 | +800 | 75K | 24K | ¥0.17 |
| **P2-3** 段落重写 context 注入 | 假设全书 50 次重写 | +600 | 0 | 30K | 0 | ¥0.03 |
| **P2-4** 仪表盘聚合 | 0 | 0 | 0 | 0 | 0 | 0 |
| **P3-1** source 字段 | 0 | 0 | 0 | 0 | 0 | 0 |
| **P3-2** plot_deduction 插件 | 不做 | 0 | 0 | 0 | 0 | 0 |
| **P3-3** 跨章检索 | 0 | 0 | 0 | 0 | 0 | 0 |
| **全选合计** | | | | **255K** | **24K** | **≈ ¥0.35** |

**单次写作开销**（P1 全做后的硬性 baseline）：
- input: +1500 tokens（写每章都付）
- output: 0
- 折算: **¥0.0015 / 章** ≈ **每 666 章才 1 块钱**

**对比现有 baseline**（4.0 现状每章 LLM 调用）：
- 6 问 (mindset): input ~800 + output ~600 tokens ≈ ¥0.004 / 章
- 写正文: input ~3000 + output ~3000 tokens ≈ ¥0.015 / 章
- critic 6 维: input ~2000 + output ~500 tokens ≈ ¥0.004 / 章
- hook 5 维: input ~2000 + output ~400 tokens ≈ ¥0.004 / 章
- **小计: ~¥0.027 / 章**

**结论**:
- P1 全做后每章 +¥0.0015（**占比 5.5%**），可接受
- P2-2 AI 生成卡：30% 章启用 = 每本 +¥0.17
- P2-3 段落重写：每本 +¥0.03
- **写一本 100 章书总开销增加 ¥0.35**（约 0.5 角）

**性价比**:
- 拿 0.5 角换「嘴心不匹配 / 空间错乱 / 反规则 override / 章末定格」4 大痛点的显式解决方案
- **性价比极高**

### 4.2.2 Tokens 风险（用贵模型时）

**如果切到 gpt-4 / claude-3.5-sonnet 量级**（input ¥30/1M, output ¥120/1M）：
- 100 章 P1-4 注入: 150K × 30 = **¥4.5**
- 100 章 P2-2 AI 生成: 75K × 30 + 24K × 120 = **¥5.13**
- 100 章 P2-3 重写: 30K × 30 = **¥0.9**
- **合计 ¥10.53 / 100 章书**

> 仍然可控（写本书 10 块），但用户应有知情权。建议在 UI 里加一个"当前章已用 tokens"小指示器。

### 4.3 依赖关系

```
subtext card 引入所需前置:
  - schema.sql 已有 scene_subtext_cards 表 ✅
  - 需新建 app/services/subtext_card_service.py
  - 需新建 app/core/subtext_generator.py (AI 生成可选)
  - 需新建 app/ui/panels/subtext_panel.py (EditorTab 子面板)
  - 需新建 app/core/prompt_utils.py (占位符解析 + 反规则合并)
  - 需修改 app/core/prompt_assembler.py (注入新 3 段)
  - 需修改 app/core/chapter_generator.py (编排调用)
  - 需新建 tests/m3_subtext_smoke.py
  - 需扩展 tests/m3_ui_smoke.py (EditorTab 子面板)
```

---

## 5. 折板清单（请逐条 ☐/☑）

> **P1 必入（最小可用）** —— 没有这层，subtext card 形同虚设
> **P2 强推** —— 直接对应 4.0 现有痛点
> **P3 可选** —— 锦上添花

### P1: 必入项（5 条）

- [ ] **P1-1**: 新建 `SceneSubtextCard` dataclass（13 字段），落到 `app/core/models/subtext_card.py`
- [ ] **P1-2**: 新建 `subtext_card_service`（CRUD + 章节关联），落到 `app/services/`
- [ ] **P1-3**: **小说设定 Tab** 加子面板「🎭 潜文本卡」(**项目级行为开关**: AI 自动 / 手动 / 关闭), 见 §10
- [ ] **P1-4**: `prompt_assembler` 注入 3 段（subtext card / scene_map / chapter anti_rules override）
- [ ] **P1-5**: 写 `tests/m3_subtext_smoke.py`（CRUD + 占位符解析 + 反规则合并 + prompt 注入断言）

### P2: 强推项（4 条）

- [ ] **P2-1**: 加 `app/core/prompt_utils.py`（占位符 `{GENRE}` / `{HOOK}` 解析 + 列表合并去重），3.0 已有实现搬运
- [ ] **P2-2**: ~~AI 生成模式~~ —— **已并入 P1-3 主流程（默认入口）**
- [ ] **P2-3**: 段落重写 (`paragraph_rewriter`) 注入 subtext_card section 作为 context
- [ ] **P2-4**: 仪表盘聚合 "subtext 使用统计"（每章 subtext 卡数 / 字段填充率）

### P3: 可选项（3 条）

- [ ] **P3-1**: `source` 字段区分 manual/ai/plot_deduction
- [ ] **P3-2**: plot_deduction 插件（4.0 无插件架构，暂跳过）
- [ ] **P3-3**: 跨章 subtext 检索（"全书所有 surface_event 提到'老怀表'的卡"）

---

## 6. 折板验收后产出预估

| 阶段 | 折板 | 新增代码行 | 新增测试 | 落地时间（参考） |
|---|---|---|---|---|
| P1 | 5 条 | ~500 | 1 套 smoke | 短 |
| P2 | 4 条 | ~400 | 扩展 m3 | 中 |
| P3 | 3 条 | ~200 | 1 套 smoke | 长 |
| **合计** | 12 条 | **~1100** | **+2 套 smoke** | 跨 Phase 3-4 |

---

## 7. 替代方案对比

| 方案 | 描述 | 优劣 |
|---|---|---|
| **A. 完整 13 字段移植** | 把 3.0 业务 1:1 搬到 4.0 | ✅ 业务最全; ❌ 代码量最大, 风险最高(3.0 已知 bug) |
| **B. 5 字段最小可用** | 只做 surface/lie/truth/intent/anchor,其他 P3 | ✅ 见效快; ❌ 后续仍要补 8 字段 + 反规则 override |
| **C. 不补** | 用 6 问继续代偿 | ✅ 0 成本; ❌ 持久化/复盘/反规则 override 全无 |
| **D. 复用 3.0 代码** | 复制 3.0 `subtext_card.py` + `anti_rule.py` 直接 import | ❌ 必然带 3.0 已知 bug(MemoryManager 断裂、Self-Critique 脆弱) |

**推荐**: **方案 B → 后续滚动到 A**（先 P1 + P2-1 反规则合并，再逐步 P2/P3）。

---

## 8. 决策记录

- [ ] **决策 1**: 走哪条方案？(A/B/C/D)
- [ ] **决策 2**: 一次性全做 P1+P2 还是分两次？
- [ ] **决策 3**: P3 哪些要做？
- [ ] **决策 4**: 4.0 是否要保留 3.0 业务注释（"原 3.0 设计参考"）？
- [ ] **决策 5**（新增）: tokens 消耗策略 — 默认走 gpt-4o-mini 廉价模型还是允许用户切 gpt-4 高质量？
- [ ] **决策 6**（新增）: 是否在 UI 加"当前章已用 tokens"小指示器？

---

## 10. P1-3 子面板设计：小说设定 Tab 子面板（项目级行为开关）

### 10.1 位置 & 性质

- **位置**：[小说设定 Tab](file:///d:/novel-writer-pure-v4/app/ui/tabs/settings_tab.py) 子面板
- **性质**：**项目级行为开关**（不是章节级表单）
- **决策一次 → 影响全书每章**

### 10.2 痛点（再确认）

13 字段手填对新人门槛高、容易填歪。
3.0 业务中 3 模式并存（手填/AI/插件），但**手填是默认** → 新人同样吃瘪。
且 3.0 模式选择**分散在每章写时**（每章都要选一次）→ 决策疲劳。

### 10.3 设计原则

- **项目级一次性决策**：在 settings 里选好模式，每章自动按规则走
- **默认 AI 自动**（零门槛，新人无需懂 subtext 是什么）
- **首次进入时弹框提示每章 tokens 消耗**（知情同意）
- **手动模式**（高级）+ **关闭**（不用）都保留选项

### 10.4 UI 流程

#### 10.4.1 小说设定 Tab 全貌

```
┌─────────────────────────────────────────────┐
│ 小说设定                                    │
├─────────────────────────────────────────────┤
│  [世界观]  [角色]  [钩子]  [风格指纹]        │
│  [声音档案]  [反规则]  [🎭 潜文本卡]        │  ← 新增子 tab
├─────────────────────────────────────────────┤
│  ... (各子面板内容)                          │
└─────────────────────────────────────────────┘
```

#### 10.4.2 「🎭 潜文本卡」子面板

```
┌─────────────────────────────────────────────┐
│ 🎭 潜文本卡                                 │
│ 决定每章写作时, AI 如何处理"潜台词层"        │
├─────────────────────────────────────────────┤
│                                             │
│  ○ 🪄 AI 自动生成和填写（推荐）              │  ← 默认选中
│     • 每章写作前 AI 自动生成 subtext 卡      │
│     • 自动套用到 Writer prompt               │
│     • 预计消耗: ~3300 tokens/章              │
│       (~¥0.004 / 章, ~¥0.4 / 100 章书)      │
│     • 新人友好: 无需懂 subtext 是什么         │
│                                             │
│  ○ ✏️ 手动模式                              │
│     • 你在下面填写项目级 subtext 模板        │
│     • 每章写作时套用同一份模板               │
│     • 0 tokens 消耗, 但需手动维护            │
│     • 适合: 资深作者, 极特殊题材             │
│                                             │
│  ○ 🚫 关闭                                  │
│     • 不使用 subtext 卡                      │
│     • Writer prompt 不含潜文本段落           │
│     • 0 tokens 消耗, 0 干扰                  │
│                                             │
│  [💾 保存设定]                              │
└─────────────────────────────────────────────┘
```

#### 10.4.3 选「🪄 AI 自动」模式（默认）→ 首次进入弹框

**关键：第一次进 subtext 面板时弹一次性提示**（不重复打扰）：

```
┌──────────────────────────────────────┐
│ 🪄 AI 自动生成潜文本卡                │
├──────────────────────────────────────┤
│                                      │
│  开启后, 每章写作时 AI 会自动:         │
│  1. 根据 brief + 上章摘要生成         │
│     一张 subtext 卡                    │
│  2. 套用到 Writer prompt              │
│                                      │
│  📊 预计每章消耗:                      │
│     • 输入  ~2500 tokens              │
│     • 输出  ~800 tokens               │
│     • 费用  ~¥0.004 (gpt-4o-mini)     │
│            ~¥0.10  (gpt-4 / sonnet)   │
│                                      │
│  💡 你可以随时回这里切换到「手动模式」   │
│     或「关闭」.                        │
│                                      │
│  [我知道了]                  [好的]    │
└──────────────────────────────────────┘
```

#### 10.4.4 选「✏️ 手动模式」→ 显示项目级 subtext 表单

**关键区别**：
- 手动模式 = **项目级模板**（不是每章填，是整个项目共用一份）
- 填写一次 → 每章写时套用 → 0 tokens

```
┌─────────────────────────────────────────────┐
│ ✏️ 手动模式 (项目级 subtext 模板)            │
├─────────────────────────────────────────────┤
│  模板名:  [主角对林婉的复杂情感]              │
│                                             │
│  表面事件:  [____________]  ?                │
│  真实意图:  [____________]  ?                │
│  谎:       [____________]  ?                │
│  真:       [____________]  ?                │
│  身体:      [____________]  ?                │
│  场景:      [____________]  ?                │
│  结尾状态:  [____________]  ?                │
│  呼应收束:  [____________]  ?                │
│  反规则:    [____________]  ?                │
│                                             │
│  [� 保存模板]                              │
└─────────────────────────────────────────────┘
```

**注意**：
- 这是**项目级**模板（一份）→ 不是每章一张
- 适合"我这本书的核心情感就这一种"（如"主角对林婉的复杂情感"贯穿全书）
- 高级用户专属

#### 10.4.5 选「🚫 关闭」→ 简单确认

```
┌──────────────────────────────────────┐
│ 🚫 关闭潜文本卡                       │
├──────────────────────────────────────┤
│  关闭后 Writer prompt 不会包含        │
│  潜文本段落, AI 写时无显式 subtext     │
│  引导.                                │
│                                      │
│  [取消]                  [确认关闭]   │
└──────────────────────────────────────┘
```

### 10.5 行为影响（按选定模式分）

| 模式 | 章节级 subtext 卡 | Writer prompt 注入 | tokens/章 | 用户操作 |
|---|---|---|---|---|
| 🪄 **AI 自动** (推荐) | ✅ 自动生成 + 自动存 (`source='ai_auto'`) | ✅ 注入 3 段 | +¥0.004 | 0 干预 |
| ✏️ **手动** | ❌ 不存卡 | ✅ 注入项目级模板 | 0 | 一次性填模板 |
| 🚫 **关闭** | ❌ | ❌ 跳过 | 0 | 0 |

### 10.6 优势

| 维度 | 旧设计（章节级 3 tab） | 新设计（项目级 3 选 1） |
|---|---|---|
| 决策时机 | 每章都要选 | **一次决定，永久生效** |
| 新人上手 | ❌ 13 字段 / 章 | ✅ 默认 AI 自动, 零干预 |
| tokens 知情 | ❌ 默默扣 | ✅ **首次弹框明示** |
| 项目一致性 | ❌ 每章填得不一样 | ✅ **AI 自动模式 = 全书一致** |
| 关闭选项 | ❌ 没法完全关 | ✅ **3 选 1 干净切换** |
| 代码复杂度 | 高（章节级 UI）| **低**（settings 一次性配置）|
| 测试用例 | 12 个 | **5 个**（3 模式 + 弹框 + 注入）|

### 10.7 实现位置

- `app/core/models/subtext_card.py` — 13 字段 dataclass
- `app/services/subtext_card_service.py` — CRUD + project_id 关联
- `app/core/subtext_generator.py` — AI 自动生成逻辑（3 重 JSON 容错）
- `app/core/subtext_mode.py` — 模式解析（ai_auto / manual / disabled）
- `app/ui/panels/subtext_settings_panel.py` — settings_tab 子面板（3 选 1 单选）
- `app/ui/dialogs/subtext_welcome.py` — 首次进入一次性提示
- `app/core/prompt_assembler.py` — 根据 mode 决定是否注入
- `app/core/chapter_generator.py` — ai_auto 模式自动调用 generator
- `app/tests/test_subtext_modes.py` — 3 模式 + 弹框 + 注入 5 组测试

### 10.8 决策项

- [ ] **决策 7**（修正）: AI 自动模式是否每章**都**自动生成，还是用户每章可点「跳过本章节省 tokens」？
  - 推荐: 每章必生成（项目一致性 > 省 ¥0.004/章）
- [ ] **决策 8**: 手动模式是 1 个项目模板，还是允许 N 个模板（按场景切换）？
  - 推荐: 1 个（简单）；N 个放 P3
- [ ] **决策 9**（修正）: 弹框是否只在「第一次进 subtext 面板」显示，还是「每次切到 AI 自动」都显示？
  - 推荐: 仅首次（避免打扰）
- [ ] **决策 10**（修正）: 弹框双模型报价 vs 仅当前模型 → **推荐双模型**（用户随时要切）
- [ ] **决策 11**（新增）: 关闭模式下，旧章节的 subtext 卡数据保留还是清空？
  - 推荐: **保留**（用户切回 AI 自动时可恢复查看）

---

## 9. 参考资料

- 3.0 完整 subtext_card 实现: `D:\novel-writer-pure\app\workflow\subtext_card.py` (455 行)
- 3.0 注入 prompt: `D:\novel-writer-pure\app\workflow\prompts.py:470-600`
- 3.0 UI dialog: `D:\novel-writer-pure\app\ui\dialogs\subtext_card_dialog.py`
- 3.0 测试: `D:\novel-writer-pure\tests\backend\test_subtext_card_v3.py` (7 用例)
- 3.0 已知 bug: `D:\novel-writer-pure\.workbuddy\memory\MEMORY.md`
- 4.0 现状架构: `d:\novel-writer-pure-v4\app\core\chapter_generator.py` + `prompt_assembler.py`
- 4.0 6 问: `d:\novel-writer-pure-v4\docs\phase3-design.md` §3 心智清单
- 4.0 表结构: `d:\novel-writer-pure-v4\app\db\schema.sql` (`scene_subtext_cards` 已存在)
