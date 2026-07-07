# v4.0 功能补全 · 逐条验收清单（审计/验收方）

> 对应设计文档：`D:\novel-writer-pure-v3.4\docs\故事单元模式最终设计文档-v2.md`
> 审计结论来源：三方审计（WorkBuddy 审计 + MIMO 计划 + 设计文档）
> 角色：本清单由审计/验收方持有，**不修改 v4.0 任何代码**，仅用于 MIMO 完成后逐条核对。
> 验收铁律：**能 INSERT / 能被 UI 调到 / 能在运行 app 里走通 = 真完成；仅建表/仅写函数但无调用方/无 UI 入口 = 死代码，判 MISSING。**

---

## 验收总览

| MIMO 阶段 | 设计文档章节 | 验收重点 | 假完成陷阱 |
|-----------|--------------|----------|------------|
| P0 因果图服务 | §3.4 / §3.5 / §6 | 边真写入、组可读 | 建 service 但 orchestrator 从不调用 → 死骨架 |
| P1 情绪曲线分析器 | §5 | 非 AI、6 模式、痛感、报告 | 调 LLM 做断章（违设计 §5.5）；只做字数切 |
| P2 编排师因果审查 | §6 | review_causality 真执行 | 方法存在但 run_unit 不调用 |
| P4 编排师 update_causal_graph | §6 | 写后真更新边/摘要 | 函数空实现或未被触发 |
| P3 单元 UI 接入 | §8.1 / §8.2 | StoryUnitTab 真注册、视图切换、断章报告 | 注册了点不到 / 报告不显示 |
| §9 双模式（MIMO 未覆盖） | §9 | 新老项目视图分支、auto_wrap 接线 | 完全未做 |

---

## P0 —— 因果图服务 `app/services/unit_causal_service.py`

**设计文档依据**：§3.4 `unit_causal_edges`（from_unit_id, to_unit_id, edge_type, description, strength）、§3.5 `unit_causal_groups`（name, color, unit_ids JSON, sort_order）、§6 编排师写后更新因果图。

### 验收项
- [ ] `create_edge / get_edges_for_unit / get_edges_for_project / delete_edge` 函数存在且签名合理
- [ ] `create_group / add_unit_to_group / get_groups_for_project` 函数存在
- [ ] **真写入验证**：在 v4.0 运行态下，完成一个单元生成后，`SELECT count(*) FROM unit_causal_edges` **> 0**
- [ ] **调用链验证**：`orchestrator.update_causal_graph()`（P4）内部确实调用了 `create_edge` / 组的写入（grep 确认调用方存在）
- [ ] 迁移文件存在且 `unit_causal_edges` / `unit_causal_groups` 表结构与设计 §3.4/§3.5 列一致

### 陷阱（判 MISSING 的情形）
- 表建了但全库零 INSERT（当前现状就是死骨架，必须打破）
- service 写好了但 orchestrator 没有任何调用点

---

## P1 —— 情绪曲线分析器 `app/services/emotion_analyzer.py`

**设计文档依据**：§5（关键词密度+标点密度，**不用 AI**）、§5.4 六种断章模式（揭示/危机/选择/情绪峰值/悬念前置/场景收束）、§5.5 痛感公式 `(投入度 × 紧迫度) ÷ 可得性`、§5.6 断章报告（候选位置 + 痛感评级 + 推荐理由）、§5.7 六种策略（爽文/悬疑/感情/节奏/平稳/自动）。

### 验收项
- [ ] `analyze_emotion_curve(text) → list[EmotionPoint]` 存在
- [ ] `detect_break_points(text, strategy) → list[BreakPoint]` 存在，且 `strategy` 支持至少 6 种模式
- [ ] `calculate_pain_score(point) → float` 实现 §5.5 公式
- [ ] `generate_split_report(points) → SplitReport` 返回候选位置 + 痛感评级 + 推荐理由
- [ ] **非 AI 验证**：grep `emotion_analyzer.py`，不得出现 LLM / chat / completion / requests 调用（设计 §5.5 明确不用 AI）
- [ ] **模式匹配为规则**：6 种模式匹配应基于正则/关键词/标点密度，非模型推理

### 陷阱（判 MISSING 的情形）
- 分析器调了 LLM（直接违设计，且不可复现、慢）
- 只做了"按字数/段落切分"，没有情绪曲线、没有痛感、没有报告
- `analyze_split_points / split_unit / preview_split` 仍是死代码（本次审计发现它们当前零调用）

---

## P2 —— 编排师因果审查 `app/agents/orchestrator.py`

**设计文档依据**：§6 编排师升级，`run_unit` 路径含 (a) 因果审查 (b) 上下文装配 (c) 写后因果更新。

### 验收项
- [ ] `review_causality(project_id, unit_id) → CausalReviewResult` 方法存在
- [ ] `run_unit()` 在生成前**实际调用** `review_causality`（grep 确认调用链）
- [ ] 审查覆盖三点：
  - [ ] 因果衔接：对比 `cause_summary` 与上单元 `effect_summary`
  - [ ] 伏笔履约：`_check_hook_fulfillment()` 检查待回收伏笔是否已埋
  - [ ] 时间线一致性：`_check_timeline_consistency()` 检查 present/causal 顺序
- [ ] 上下文装配使用 `story_order` 取因果上游、`present_order` 无关

### 陷阱（判 MISSING 的情形）
- `review_causality` 方法存在但 `run_unit` 从未调用（死方法）
- 方法体为空 / 只 `return None`

---

## P4 —— 写后因果更新 `app/agents/orchestrator.py::update_causal_graph`

**设计文档依据**：§6 (c) 写后因果更新：抽取实际已埋/已收伏笔、更新 cause/effect 摘要、更新因果边、生成 exit 快照、同步 L1/L2。

### 验收项
- [ ] `update_causal_graph(project_id, unit_id, draft_text)` 方法存在
- [ ] `run_unit()` 在生成后**实际调用** `update_causal_graph`
- [ ] 调用 `unit_causal_service.create_edge` 写入真实边（见 P0 真写入验证）
- [ ] 更新 `unit_briefs` 的 `cause_summary` / `effect_summary`（注意 v4.0 实际字段名已改名，见下）
- [ ] 生成并保存 exit snapshot（exit_characters / exit_world / exit_commitments）

### 字段名偏差提醒（验收时必须用 v4.0 实际 schema，非文档原名）
- `unit_briefs.hooks_planted / hooks_paid`（文档） → 实际 `hooks_planned_plant / hooks_planned_pay`
- `split_configs.auto_hook`（文档） → 实际已被 `use_ai_analysis` 取代
- 若 MIMO 按文档原名写，会触发 `column does not exist` —— 验收时 grep 实际列名确认

---

## P3 —— 单元 UI 接入 `app/ui/pages.py` + `app/ui/main_window.py`

**设计文档依据**：§8.1 单元视图 + 双时间线切换（呈现顺序/故事时间）、§8.2 断章交互（痛感报告）。

### 验收项
- [ ] `StoryUnitTab` 注册进 `pages.py` 的 `PAGE_REGISTRY`
- [ ] **同时**在 `main_window.py` 的 `MODULE_PAGE_MAP` 添加导航项（否则侧栏点不到 —— 同 DecisionHistoryPage 孤儿问题）
- [ ] 运行 app 后，导航栏确实出现"单元"页且可点击进入
- [ ] 单元列表渲染：timeline_label、unit_type 徽章、status
- [ ] **视图切换控件存在且生效**：呈现顺序 / 故事时间 两种排序可切换
- [ ] 单元详情面板含：transition_type + transition_text、cause_summary/effect_summary、brief（core_events/emotion_arc）、hook 管理、draft 编辑器
- [ ] 断章交互：选单元 → 选策略 → "分析断章点" → **显示带痛感评级的断章报告** → 确认 → 执行拆分生成章节

### 陷阱（判 MISSING 的情形）
- 只注册 `PAGE_REGISTRY` 漏了 `MODULE_PAGE_MAP` → 侧栏无入口
- 断章只走字数切（`auto_split_unit`），UI 不显示情绪曲线报告
- StoryUnitTab 实例化但内部核心子面板为空壳

---

## §9 —— 双模式（MIMO 计划未覆盖，需另排）

**设计文档依据**：§9 新项目默认单元视图、老项目默认章节视图、老项目升级包虚拟单元 `auto_wrap_all_chapters`。

### 验收项（MIMO 跑完 P0–P4 后由验收方/另一轮补齐）
- [ ] 区分新/老项目并设置默认视图的逻辑存在且生效
- [ ] `auto_wrap_all_chapters`（老项目包虚拟单元）被接线调用（当前审计为死代码，零调用）
- [ ] 老项目升级后能在单元视图看到虚拟单元

---

## 跨切面验收（贯穿所有阶段）

### 1. 死代码清理
- [ ] `story/engine/story_engine.py`（import 不存在的 `OrchestratorV4`）已删或修复
- [ ] `story.runtime.unit_runner` 与 `app/agents/orchestrator` 职责不冲突、不重复实现因果逻辑
- [ ] `check_coherence()`（当前死代码）要么接线要么删除

### 2. 主题一致性（后续 UI 阶段）
- [ ] `theme_v4.py`（Catppuccin）已删除或不再被激活
- [ ] UI 不再混用三套调色板（mockup / Catppuccin / color_palette）

### 3. 端到端验证脚本（验收时运行）
```bash
cd D:\novel-writer-pure-v4.0
python -m app
```
测试清单（逐条对照上表）：
1. 创建单元 → `SELECT count(*) FROM unit_causal_edges` 建立边 ✅
2. 生成单元 → 确认 `review_causality` 执行（日志/断点）
3. 完成单元 → 确认 `update_causal_graph` 写入边 + 更新摘要
4. 拆章 → 确认走 `emotion_analyzer`（非字数切）+ 断章报告显示痛感
5. 单元 Tab → 确认导航可达 + 视图切换生效
6. （§9）老项目升级 → 确认 `auto_wrap_all_chapters` 触发

---

## 验收结论格式
每条给出：**PASS / PARTIAL / MISSING(死代码)** + 证据（文件路径 + 行号/SQL 结果）。
PARTIAL/MISSING 必须附一句话说明"还差什么"。
