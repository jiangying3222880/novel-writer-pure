# v4.0 功能补全 · 逐条验收清单（审计/验收方）

> 对应设计文档：`D:\novel-writer-pure-v3.4\docs\故事单元模式最终设计文档-v2.md`
> 审计结论来源：三方审计（WorkBuddy 审计 + MIMO 计划 + 设计文档）
> 角色：本清单由审计/验收方持有，**不修改 v4.0 任何代码**，仅用于 MIMO 完成后逐条核对。
> 验收铁律：**能 INSERT / 能被 UI 调到 / 能在运行 app 里走通 = 真完成；仅建表/仅写函数但无调用方/无 UI 入口 = 死代码，判 MISSING。**

---

## 验收总览

| MIMO 阶段 | 设计文档章节 | 验收重点 | 状态 |
|-----------|--------------|----------|------|
| P0 因果图服务 | §3.4 / §3.5 / §6 | 边真写入、组可读 | ✅ PASS |
| P1 情绪曲线分析器 | §5 | 非 AI、6 模式、痛感、报告 | ✅ PASS |
| P2 编排师因果审查 | §6 | review_causality 真执行 | ✅ PASS |
| P4 编排师 update_causal_graph | §6 | 写后真更新边/摘要 | ✅ PASS |
| P3 单元 UI 接入 | §8.1 / §8.2 | StoryUnitTab 真注册、视图切换、断章报告 | ✅ PASS |
| §9 双模式 | §9 | 新老项目视图分支、auto_wrap 接线 | ✅ PASS |

---

## P0 —— 因果图服务 `app/services/unit_causal_service.py`

### 验收项
- [x] `create_edge / get_edges_for_unit / get_edges_for_project / delete_edge` 函数存在且签名合理
- [x] `create_group / add_unit_to_group / get_groups_for_project` 函数存在
- [x] **真写入验证**：`unit_causal_edges` 表存在，orchestrator.update_causal_graph() 真调用 create_edge
- [x] **调用链验证**：orchestrator → update_causal_graph → unit_causal_service.create_edge
- [x] 迁移文件存在且表结构正确

---

## P1 —— 情绪曲线分析器 `app/services/emotion_analyzer.py`

### 验收项
- [x] `analyze_emotion_curve(text) → list[EmotionPoint]` 存在
- [x] `detect_break_points(text, strategy) → list[BreakPoint]` 存在
- [x] 6 种模式支持（reveal/crisis/choice/climax/rise/dip）
- [x] **非 AI 验证**：无 LLM/chat/completion 调用
- [x] **模式匹配为规则**：基于正则/关键词/标点密度

---

## P2 —— 编排师因果审查 `app/agents/orchestrator.py`

### 验收项
- [x] `review_causality(project_id, unit_id)` 方法存在
- [x] `run_unit()` 在生成前实际调用 `review_causality`
- [x] 审查覆盖：因果衔接 + 伏笔履约 + 时间线一致性
- [x] 上下文装配使用 `story_order`

---

## P4 —— 写后因果更新 `app/agents/orchestrator.py::update_causal_graph`

### 验收项
- [x] `update_causal_graph(project_id, unit_id, draft_text)` 方法存在
- [x] `run_unit()` 在生成后实际调用 `update_causal_graph`
- [x] 调用 `unit_causal_service.create_edge` 写入真实边
- [x] 更新 `unit_briefs` 的 `cause_summary` / `effect_summary`
- [x] 生成并保存 exit snapshot

---

## P3 —— 单元 UI 接入

### 验收项
- [x] `StoryUnitTab` 注册进 `PAGE_REGISTRY`
- [x] `main_window.py` 的 `MODULE_PAGE_MAP` 添加导航项
- [x] 导航栏"故事单元"可点击进入
- [x] 单元列表渲染：title/unit_type/status
- [x] 单元详情面板含 transition/hook/draft 管理
- [x] 上移/下移按钮可用

---

## §9 —— 双模式

### 验收项
- [x] `detect_project_type()` 区分 new/old/mixed 项目
- [x] `get_default_view()` 设置默认视图
- [x] `main_window._detect_and_set_project_mode()` 自动切换
- [x] `auto_wrap_all_chapters()` 老项目升级包装虚拟单元

---

## 跨切面验收

### 1. 死代码清理
- [x] 13 个死文件已删除（~935 行）
- [x] story/events/ 归约器已重建（reducer.py）
- [x] story/events/event_store.py 独立持久化

### 2. 检索统一
- [x] zvec 替换 BM25+Vector（FTS+Vector+RRF 混合检索）
- [x] 三接口就绪：find/related/context
- [x] knowledge_service 通过 build_finder() → zvec

### 3. 端到端验证
- [x] 6/6 smoke tests 通过
- [x] 5/5 unit tests 通过
- [x] D2 smoke (知识检索) 22 assertions 通过
