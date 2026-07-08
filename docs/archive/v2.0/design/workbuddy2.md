收到。用户的反馈精准命中了我的方案的两个核心缺陷：①没列全功能清单让你确认；②砍功能时没区分"业务真实存在"vs"过度设计"。我立刻按你的"两阶段"流程重新做。
我已经读完了项目里两个最权威的功能盘点文档（`3.0-features-inventory.md` + `AGENTS.md`），加上你刚才的精准反馈。**你说的对**：我之前的方案**跳过了"列功能让你选"的第一步**。我重新按你的两阶段流程做。

---

# 🎯 novel-writer-pure 重构方案 v3（按"列功能 → 你选 UI"流程）

## 阶段 1：完整功能清单（不砍任何功能）

我把 3.0 全部 11 类功能 + 4 张叙事工坊表 + 全部 10 个插件 + 6 Tab + 14 Dialog **全部列出来**。共 **46 项业务功能 + 14 项技术债**。

### 📦 A. 核心业务功能（5 大类，共 17 项）

| 编号 | 功能 | 描述 | 数据源 | 重要度 |
|------|------|------|--------|--------|
| A01 | **WRITE 阶段** | 1 次 LLM 调用，输出章节正文 | v3_engine + WriterAgent | ★★★★★ |
| A02 | **SELF_CRITIQUE 阶段** | 1 次 LLM 自评，4 问 → 7 问（技术 4 + 品味 3）| v3_engine | ★★★★★ |
| A03 | **PERSIST 阶段** | 0 token 落库 + 6 验证器 + 风格学习 | v3_engine + SettlerAgent | ★★★★★ |
| A04 | **3.1 USER_CONFIRM** | 前 10 章写前确认 SceneContext | 流程配置 | ★★★★★ |
| A05 | **3.1 SELECT_VERSION** | 多版本生成 + 用户选 1 | 流程配置 | ★★★★ |
| A06 | **自评阻断** | technical_score<60 阻断重写 | v3_engine | ★★★★★ |
| A07 | **3 模式自动调度** | A(11章后) / B(前10章) / C(多版本) | v3_engine | ★★★★★ |
| A08 | **checkpoint 断点恢复** | 失败可恢复 | v3_engine | ★★★★ |
| A09 | **跨章一致性检查** | 时序/物品/对话/情绪 | consistency_checker | ★★★★ |
| A10 | **世界状态观察** | 跨章数值/事件追踪 | world_state_observer | ★★★★ |
| A11 | **潜文本卡构造** | 5 字段：表面/真实/谎/真/物理锚点 | subtext_card | ★★★★★ |
| A12 | **角色声音档案构造** | 句法/词汇/决策/关系指纹 | voice_profile | ★★★★★ |
| A13 | **作者风格指纹构造** | pace/density/lyricism 三轴 | style_fingerprint | ★★★★★ |
| A14 | **反规则系统** | "在 Y 内允许打破 X" | anti_rule | ★★★★★ |
| A15 | **POV 验证器** | 人称占比，0 token | pov_validator | ★★★★★ |
| A16 | **空间验证器** | 方向/位置一致 | spatial_validator | ★★★★★ |
| A17 | **声音验证器** | 角色风格漂移 | voice_validator | ★★★★★ |

### 🧠 B. 记忆与 RAG（5 项）

| 编号 | 功能 | 描述 | 数据源 | 重要度 |
|------|------|------|--------|--------|
| B01 | **STM 短期记忆** | 最近 1-3 章 | memory/manager | ★★★★★ |
| B02 | **MTM 中期记忆** | 最近 5-10 章 | memory/manager | ★★★★★ |
| B03 | **LTM 长期记忆** | 全书 + 蒸馏摘要 | memory/manager | ★★★★★ |
| B04 | **4 tier 增量蒸馏** | main_plot/romance/character/worldview/foreshadow | distill_manager | ★★★★★ |
| B05 | **RAG 混合检索** | 向量 + BM25 + RRF | rag/vector_db + bm25 | ★★★★ |
| B06 | **跨章角色状态追踪** | emotion/location/relationships/inventory | character_tracker | ★★★★ |

### 🤖 C. AI 引擎能力（6 项）

| 编号 | 功能 | 描述 | 数据源 | 重要度 |
|------|------|------|--------|--------|
| C01 | **27 个 AI Provider** | OpenAI/Anthropic/DeepSeek/智谱/火山/硅基/百度/腾讯/讯飞/小米/无问/... | providers.py | ★★★★★ |
| C02 | **流式输出（SSE）** | on_chunk 回调 | engine.py | ★★★★★ |
| C03 | **JSON 模式** | response_format | engine.py | ★★★★★ |
| C04 | **4 家 fallback 链** | DeepSeek→智谱→硅基→OpenAI | engine.py | ★★★★★ |
| C05 | **7+ 题材模板** | fantasy/mystery/romance/sci-fi/urban/wuxia/horror/... | genre_loader | ★★★★ |
| C06 | **定价/费用估算** | token 成本 | pricing.py | ★★★ |
| C07 | **dry_run 模式** | 测试用 | engine.py | ★★★★ |

### 📥 D. 导入系统（5 项）

| 编号 | 功能 | 描述 | 数据源 | 重要度 |
|------|------|------|--------|--------|
| D01 | **单文件模板检测** | TemplateDetector | import_script | ★★★★ |
| D02 | **角色文件解析** | 4 种格式：标题+列表/表格/... | import_script | ★★★★ |
| D03 | **世界观文件解析** | 3 种格式 | import_script | ★★★★ |
| D04 | **章节大纲解析** | 含多卷结构 | import_script | ★★★★ |
| D05 | **AI 兜底解析** | 4 种格式识别指南 | ai_import_manager | ★★★★ |
| D06 | **AI 导语精炼** | 平台风格结合 | import_helpers | ★★★ |

### 🔌 E. 10 个插件（全部保留候选）

| 编号 | 插件 | 能力描述 | 原 UI 位置 | 重要度 |
|------|------|---------|-----------|--------|
| E01 | **ai_outline_gen** | AI 一键生成世界观/角色/大纲/伏笔 | 小说设定 → AI 生成按钮 | ★★★★★ |
| E02 | **plot_deduction** | 剧情推演（多轮 AI 推演）| 章节生成 → 剧情推演按钮 | ★★★★ |
| E03 | **prompts_default** | 标准提示词模板 | 章节生成 → Agent 配置 | ★★★★★ |
| E04 | **tts_edge** | Edge TTS 语音朗读 | 章节编辑 → 顶栏 | ★★★ |
| E05 | **entity_graph** | 实体关系图谱 | 世界图谱 Tab | ★★★★ |
| E06 | **world_state_timeline** | 世界状态时间线（数值曲线） | 嵌入世界图谱 | ★★★ |
| E07 | **worldbuilding_editor** | JSON/MD 编辑器 + Diff + 校验 + 备份 | 嵌入小说设定 | ★★★ |
| E08 | **usage_analytics** | Token/API/成本/章节分布 | 嵌入仪表盘 | ★★★ |
| E09 | **knowledge_builtin** | 内置写作知识库（6类×9体裁）| 后台 + 设置 | ★★★ |
| E10 | **knowledge_local** | 用户本地知识库（指定文件夹）| 设置 → 知识库管理 | ★★★ |

### 📊 F. 叙事工坊 7 Panel（被原方案砍掉的部分，必须列）

| 编号 | Panel | 数据源 | 重要度 |
|------|-------|--------|--------|
| F01 | **叙事压力** | narrative_pressure 表 | ★★★ |
| F02 | **情感事件** | emotional_events 表 | ★★★ |
| F03 | **节奏记录** | rhythm_records 表 | ★★★ |
| F04 | **信息差/知识状态** | knowledge_states 表 | ★★★ |
| F05 | **叙事模式识别** | plot_patterns 表 | ★★★ |
| F06 | **去重分析** | repetition_detector 输出 | ★★★★ |
| F07 | **留白与一致性** | 跨章一致性检查 + 反规则 | ★★★★ |

### 🏗️ G. 仪表盘 6 Metric

| 编号 | Metric | 数据源 | 重要度 |
|------|--------|--------|--------|
| G01 | **总章节数** | chapters | ★★★★★ |
| G02 | **已完成章节** | chapters.status | ★★★★★ |
| G03 | **平均追读力** | self_critique.taste_score 平均 | ★★★★ |
| G04 | **实体总数** | 角色+物品+地点+伏笔 | ★★★★ |
| G05 | **待兑现债务** | hooks.debt 总和 | ★★★ |
| G06 | **总字数** | SUM(word_count) | ★★★★★ |
| G07 | **追读力趋势** | chapters.taste_score 折线 | ★★★ |

### 💬 H. 14+ Dialog（重写方案给的是 14，我列实际全部）

| 编号 | Dialog | 触发场景 | 模式 | 重要度 |
|------|--------|---------|------|--------|
| H01 | **WelcomeDialog** | 首次启动 | modeless | ★★★★ |
| H02 | **ProjectDialog** | 新建/打开项目 | modal | ★★★★★ |
| H03 | **ModelConfigDialog** | 设置 | modal | ★★★★★ |
| H04 | **UserConfirmDialog** | 写作前 10 章确认 | modal | ★★★★★ |
| H05 | **VersionSelectDialog** | 多版本生成 | modal | ★★★★ |
| H06 | **SelfCritiqueReportDialog** | 自评报告 | modal | ★★★★★ |
| H07 | **SubtextCardDialog** | 潜文本任务卡 | modal | ★★★★ |
| H08 | **StyleFingerprintDialog** | 风格指纹 | modal | ★★★ |
| H09 | **VoiceProfileDialog** | 声音档案编辑器 | modal | ★★★★ |
| H10 | **AntiRuleEditorDialog** | 反规则编辑器 | modal | ★★★★ |
| H11 | **PluginConfigDialog** | 插件管理 | modal | ★★★ |
| H12 | **LicenseDialog** | 许可证激活 | modal | ★★ |
| H13 | **KnowledgeBaseDialog** | 知识库管理 | modal | ★★★ |
| H14 | **LogViewerDialog** | 日志查看 | modeless | ★★ |

### 🔧 I. 系统级能力（5 项）

| 编号 | 功能 | 描述 | 重要度 |
|------|------|------|--------|
| I01 | **微内核 + 插件架构** | Container + EventBus + PluginManager | ★★★★★ |
| I02 | **懒加载 Tab** | 首点击再加载 | ★★★★ |
| I03 | **Solarized 双主题** | Dark/Light | ★★★★ |
| I04 | **UI 一致性 token** | 35 token + 47 测试 | ★★★★★ |
| I05 | **SQLite WAL 持久化** | 备份/恢复 | ★★★★★ |
| I06 | **跨平台** | Win/macOS/Linux | ★★★★★ |
| I07 | **license 安全** | 启动检查 | ★★ |

### 📚 J. 数据模型（19+4=23 张表，必须保留）

| 域 | 表 | 关键字段 |
|----|-----|----------|
| **项目域** | projects / chapters / chapter_briefs / chapter_summaries | 章节四件套（合并建议：chapters + 4 字段 JSON 化）|
| **角色域** | characters / character_voice_profiles / character_states / character_events | |
| **世界域** | world_settings / world_state / locations | |
| **剧情域** | hooks / items / romance_lines | |
| **引导元素** | scene_subtext_cards / author_style_fingerprints | |
| **Agent** | agent_memory | |
| **元数据** | meta | |
| **叙事工坊 4 表** | narrative_pressure / emotional_events / rhythm_records / knowledge_states / plot_patterns | **重要：原方案漏了这 4 张** |

---

## 阶段 2：请你决定「哪些进 UI，哪些只后台跑」

**关键问题**：46 项业务功能 + 14 Dialog，**不能全塞进 6 Tab**。你必须**选择**哪些功能需要 UI 入口，哪些只在后台跑。

### 📊 我把功能按"UI 必要性"分类

#### 🟢 强 UI 必要（必须给用户看 + 操作）
- A01-A03（写作主流程）、A04-A07（3.1 模式）
- B01-B06（记忆/RAG 全要 UI 入口）
- C01-C04（AI 配置）
- E01（AI 大纲生成）、E02（剧情推演）、E04（TTS 朗读）
- E05（实体图谱）、E08（用量分析）
- F06、F07（去重 + 一致性，复用验证器）
- G01-G07（全部 6 metric + 趋势）
- H01-H14（全部 Dialog）

#### 🟡 弱 UI 必要（可后台跑 + 偶尔露面）
- A08（checkpoint）：失败时弹提示，平时不露面
- A09-A10（一致性 + 状态观察）：仪表盘/叙事工坊 Tab
- E06（世界状态时间线）：可独立 Tab 或嵌入仪表盘
- E07（世界观编辑器）：可独立 Tab 或嵌入小说设定
- E09-E10（知识库）：后台 + 设置 Dialog
- F01-F05（叙事工坊 5 个）：叙事工坊 Tab 7 panel

#### 🔴 可纯后台（不需要 UI）
- C05（题材模板）、C06（定价）、C07（dry_run）
- D01-D06（导入系统用 Dialog 触发就行）
- I01-I07（系统能力都是基础设施）

### 🎯 请你做 3 个决策

#### 决策 1：UI 入口策略

**方案 α - 6 Tab + 14 Dialog（沿用原 PRD）**
```
侧栏 9 项：小说设定 / 章节生成 / 章节编辑 / 仪表盘 / 叙事工坊 / 记忆管理 / 日志 / 世界图谱 / 设置
6 Tab 内容：
  - 小说设定 = 4 子页（全局/世界/角色/大纲） + E01(AI生成) + E07(编辑器)
  - 章节生成 = 流程控制 + A01-A07 + E02(剧情推演) + E03(提示词)
  - 章节编辑 = Monaco + A02自评 + E04(TTS)
  - 仪表盘 = G01-G07 + E08(用量)
  - 叙事工坊 = F01-F07（7 panel）
  - 记忆管理 = B01-B06（3 子页）
世界图谱（独立 Tab）= E05 + E06
设置（独立 Tab）= E09-E10 + license
```

**方案 β - 8 Tab（拆分更细，把叙事工坊拆 2）**
```
侧栏 11 项：6 + 拆分（压力/情感/节奏/信息差/模式/去重/留白）= 7 + 日志 + 设置 + 世界图谱
```

**方案 γ - 自定义（你画）**
```
你按"主流程自然顺序"告诉我：写小说时你想从左到右看到哪些面板？
```

**我的建议**：先选 α（成熟方案），如果觉得 9 项侧栏太挤再调。

#### 决策 2：技术栈（在 4 选 1）

| 选项 | 启动 | 体积 | 内存 | 学习曲线 | 工时 |
|------|------|------|------|---------|------|
| **A. Rust + Tauri + React** | <1s | 5-15MB | 50-100MB | 2 周 | 12 周 |
| **B. Rust + Tauri + React（精简）** | <1s | 5-15MB | 50-100MB | 2 周 | 8 周 |
| **C. Go + Wails + React** | <1s | 20-30MB | 100-150MB | 1 周 | 10 周 |
| **D. Electron + TypeScript** | 2-3s | 100MB+ | 200-400MB | 1 周 | 8 周 |

**我的建议**：A（完整 12 周）/ B（精简 8 周）

#### 决策 3：数据模型策略

**方案 ① 全部 23 张表保留**（你 PRD 写的）
- 优点：迁移无压力，业务稳定
- 缺点：表多，关系复杂

**方案 ② 合并到 14 张表**（我原方案）
- chapters 合并 chapter_briefs/summaries/revisions 用 JSON
- 优点：清晰简洁
- 缺点：迁移工具复杂

**方案 ③ 全部 23 张表，UI 层封装成领域模型**
- 优点：DB 稳定，代码用领域模型
- 缺点：DTO/DAO 转换层

**我的建议**：① 保留 23 张表，UI 层封装成领域模型

---

## 我的推荐组合

```
决策 1：α（6 Tab + 14 Dialog + 9 侧栏，叙事工坊 7 panel 全保留）
决策 2：B（Rust + Tauri + React 精简版，8 周出 MVP）
决策 3：①（23 张表全保留）
```

**额外建议**（你可能想动）：
- 叙事工坊 7 panel 要不要拆成独立 Tab？还是都进 1 个 Tab 用 7 子页？
- TTS 朗读要不要？还是先砍？
- world_state_timeline 嵌入世界图谱还是独立？

---

## 等待你的确认

请回复格式（任选一种）：

**A. 接受推荐组合**（回复 `1α 2B 3①` 或"接受推荐"）

**B. 部分调整**（例：`1α，但 TTS 砍掉；2B；3①`）

**C. 重新设计**（告诉我你的"主流程"从左到右看哪些面板，我重新设计侧栏/Tab）

---

**重要说明**：在我收到你的选择之前，**我不会启动任何编码工作**。本轮只做"功能列出来 + UI 让你选"，等你点头才进入设计。