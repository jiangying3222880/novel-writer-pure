# 3.0 vs 4.0 全功能对照表（待拍板）

> 用途：把 3.0 所有功能与 4.0 现状逐条对照，让用户**逐条拍板**（补 / 不补 / 简化）。
> 用户拍板后我会记到 §"已拍板"，再依此出可执行方案。

---

## §1 已拍板

见 [subtext-card-qa.md §1](file:///d:/novel-writer-pure-v4/docs/subtext-card-qa.md) 的 11 条决策。

---

## §2 业务模块对照

### A. AI 层（`app/ai/`）

| # | 3.0 模块 | 功能 | 4.0 现状 | 拍板（补/不做/简化）|
|---|---|---|---|---|
| A1 | `prompts/genres/*.yaml` (7 个) | 题材 prompt (古言/仙侠/悬疑/都市/科幻/玄幻/武侠) | ❌ 无 | ☐ |
| A2 | `engine.py` | AI 引擎 | ⚠️ `llm.py` 简化版 | ☐ |
| A3 | `models_registry.py` | 模型注册表 | ⚠️ `app_setting_service` 内嵌 | ☐ |
| A4 | `pricing.py` | 模型定价 | ❌ 无 | ☐ |
| A5 | `providers.py` | 厂商客户端封装 | ⚠️ `llm.py` 简化 | ☐ |
| A6 | `utils.py` | AI 工具 | ❌ 无 | ☐ |

### B. Core 层（`app/core/`）

| # | 3.0 模块 | 功能 | 4.0 现状 | 拍板 |
|---|---|---|---|---|
| B1 | `container.py` | IoC 容器（依赖注入）| ❌ 无 | ☐ |
| B2 | `event_bus.py` | 事件总线 | ❌ 无 | ☐ |
| B3 | `plugin_manager.py` | 插件管理 | ❌ 无 | ☐ |
| B4 | `interfaces.py` | 业务接口契约 | ❌ 无 | ☐ |
| B5 | `license.py` | 授权 / License | ❌ 无 | ☐ |
| B6 | `logger.py` | 日志 | ⚠️ 内嵌在 services | ☐ |
| B7 | `version.py` | 版本号 | ❌ 无 | ☐ |

### C. DB 层（`app/db/`）

| # | 3.0 模块 | 功能 | 4.0 现状 | 拍板 |
|---|---|---|---|---|
| C1 | `ai_import_manager.py` | AI 导入管理（外部素材智能解析）| ❌ 无 | ☐ |
| C2 | `connection.py` | DB 连接 | ⚠️ `app/services/db.py` | ☐ |
| C3 | `import_helpers.py` / `import_manager.py` / `import_script.py` | 导入/迁移工具 | ❌ 无 | ☐ |
| C4 | `models.py` | ORM 模型 | ❌ 无（手写 SQL）| ☐ |
| C5 | `project_db.py` | 多项目 DB 管理 | ❌ 无（单 DB）| ☐ |
| C6 | `utils.py` | DB 工具 | ❌ 无 | ☐ |

### D. Knowledge 知识层（`app/knowledge/`）

| # | 3.0 模块 | 功能 | 4.0 现状 | 拍板 |
|---|---|---|---|---|
| D1 | `bundle.enc` + `bundle.py` | **加密知识包**（内置素材加密压缩）| ❌ 无 | ☐ |
| D2 | `finder.py` | 知识查找器 | ❌ 无 | ☐ |
| D3 | `worldbuilding_store.py` | 世界观存储 | ❌ 无 | ☐ |
| D4 | `worldbuilding_sync.py` | 世界观与章节同步 | ❌ 无 | ☐ |

### E. Memory 记忆层（`app/memory/`）

| # | 3.0 模块 | 功能 | 4.0 现状 | 拍板 |
|---|---|---|---|---|
| E1 | `character_tracker.py` | 角色追踪（角色状态/位置动态）| ❌ 无 | ☐ |
| E2 | `distill_manager.py` | **蒸馏管理**（从历史章节提炼要点）| ❌ 无 | ☐ |
| E3 | `manager.py` | 记忆总管 | ❌ 无 | ☐ |

### F. RAG 检索层（`app/rag/`）

| # | 3.0 模块 | 功能 | 4.0 现状 | 拍板 |
|---|---|---|---|---|
| F1 | `bm25.py` | BM25 关键词检索 | ❌ 无 | ☐ |
| F2 | `vector_db.py` | 向量 DB（语义检索）| ❌ 无 | ☐ |

### G. Workflow 业务层（`app/workflow/`）

| # | 3.0 模块 | 功能 | 4.0 现状 | 拍板 |
|---|---|---|---|---|
| G1 | `v3_engine.py` | v3 写作引擎 | ⚠️ `chapter_generator` | ☐ |
| G2 | `prompts.py` | 11+ 段 prompt 组装 | ⚠️ `prompt_assembler` 6 段 | ☐ |
| G3 | `subtext_card.py` | 潜文本卡 | ❌ 无（§1 Q1-Q11 已拍）| ✅ |
| G4 | `anti_rule.py` | 反规则合并 + 占位符 | ❌ 无（§1 隐含 G3 实现）| ✅ |
| G5 | `consistency_checker.py` | 一致性检查 | ⚠️ `critic.py` 内嵌 | ☐ |
| G6 | `style_fingerprint.py` | 风格指纹 | ⚠️ `setting_service` 静态 | ☐ |
| G7 | `style_learner.py` | **风格学习器**（前 10 章 AI 学会）| ❌ 无 | ☐ |
| G8 | `voice_inferer.py` | **声音推断器**（从对话样本推断角色声音）| ❌ 无 | ☐ |
| G9 | `voice_profile.py` | 声音档案 | ⚠️ `setting_service` 静态 | ☐ |
| G10 | `world_state_observer.py` | 世界状态观察（角色关系网动态）| ❌ 无 | ☐ |
| G11 | `validators/item_validator.py` | 道具一致性 | ❌ 无 | ☐ |
| G12 | `validators/pov_validator.py` | **视角一致性** | ❌ 无 | ☐ |
| G13 | `validators/repetition_detector.py` | **重复检测**（防止"她咬了咬嘴唇"反复出现）| ❌ 无 | ☐ |
| G14 | `validators/setting_recall.py` | 设定回忆验证 | ❌ 无 | ☐ |
| G15 | `validators/spatial_validator.py` | **空间一致性**（防止"门内又门外"）| ❌ 无 | ☐ |
| G16 | `validators/voice_validator.py` | 声音一致性 | ❌ 无 | ☐ |
| G17 | `agents/base.py` | Agent 基类 | ❌ 无（`mindset.py` 是单文件）| ☐ |
| G18 | `agents/import_parse.py` | 外部素材 AI 解析 | ❌ 无 | ☐ |

### H. Plugins 插件层（`plugins/`）—— **10 个插件**

| # | 3.0 插件 | 功能 | 4.0 现状 | 拍板 |
|---|---|---|---|---|
| H1 | `ai_outline_gen` | **AI 大纲生成**（前 10 章 3 版本同步）| ❌ 无 | ☐ |
| H2 | `entity_graph` | 实体图谱（人物关系网）| ⚠️ 简化成 entity_manager | ☐ |
| H3 | `knowledge_builtin` | 内置知识库 | ❌ 无 | ☐ |
| H4 | `knowledge_local` | 本地知识库（用户上传）| ❌ 无 | ☐ |
| H5 | `plot_deduction` | 剧情推导（§1 Q9 不做）| ❌ 无 | ✅（不做）|
| H6 | `prompts_default` | 默认 prompt 包 | ❌ 无 | ☐ |
| H7 | `tts_edge` | **TTS 语音合成**（章节转语音）| ❌ 无 | ☐ |
| H8 | `usage_analytics` | 使用分析 | ❌ 无 | ☐ |
| H9 | `world_state_timeline` | **世界状态时间线**（角色关系变化轨迹）| ❌ 无 | ☐ |
| H10 | `worldbuilding_editor` | **世界观编辑器**（多人协作编辑）| ❌ 无 | ☐ |

### I. UI 界面（`app/ui/`）—— **14 个 dialog + 7 个 page + 5 个 widget**

| # | 3.0 组件 | 功能 | 4.0 现状 | 拍板 |
|---|---|---|---|---|
| I1 | `dialogs/welcome_dialog` | 首次启动欢迎页 | ❌ 无 | ☐ |
| I2 | `dialogs/model_config` | 模型配置 | ✅ `settings_tab` | ✅ |
| I3 | `dialogs/plugin_config_dialog` | 插件配置 | ❌ 无 | ☐ |
| I4 | `dialogs/style_fingerprint_dialog` | 风格指纹编辑 | ❌ 无 | ☐ |
| I5 | `dialogs/voice_profile_dialog` | 声音档案编辑 | ❌ 无 | ☐ |
| I6 | `dialogs/anti_rule_editor_dialog` | 反规则编辑 | ❌ 无 | ☐ |
| I7 | `dialogs/subtext_card_dialog` | 潜文本卡编辑 | ❌ 无（§1）| ✅ |
| I8 | `dialogs/memory_editor_dialog` | 记忆编辑 | ❌ 无 | ☐ |
| I9 | `dialogs/memory_viewer` | 记忆查看 | ❌ 无 | ☐ |
| I10 | `dialogs/knowledge_base_dialog` | 知识库 | ❌ 无 | ☐ |
| I11 | `dialogs/import_dialog` | 外部素材导入 | ❌ 无 | ☐ |
| I12 | `dialogs/self_critique_report_dialog` | 自评估报告 | ❌ 无 | ☐ |
| I13 | `dialogs/user_confirm_dialog` | 用户确认 | ❌ 无 | ☐ |
| I14 | `dialogs/version_select_dialog` | 版本选择（前 10 章 3 版本）| ❌ 无 | ☐ |
| I15 | `pages/memory/overview_panel` | 记忆总览 | ❌ 无 | ☐ |
| I16 | `pages/memory/distill_panel` | 蒸馏面板 | ❌ 无 | ☐ |
| I17 | `pages/memory/rag_panel` | RAG 面板 | ❌ 无 | ☐ |
| I18 | `pages/narrative_lab/emotion_panel` | **情感实验室**（情绪曲线）| ❌ 无 | ☐ |
| I19 | `pages/narrative_lab/pressure_panel` | **压力实验室**（情节张力）| ❌ 无 | ☐ |
| I20 | `pages/narrative_lab/panels` | 实验室其他面板 | ❌ 无 | ☐ |
| I21 | `widgets/app_header` | 顶栏 | ❌ 无 | ☐ |
| I22 | `widgets/app_footer` | 底栏 | ❌ 无 | ☐ |
| I23 | `widgets/scaled_container` | 矢量缩放 | ❌ 无（用传统 layout）| ☐ |
| I24 | `widgets/graph_view` | 图谱视图 | ❌ 无 | ☐ |
| I25 | `widgets/knowledge_control_panel` | 知识控制面板 | ❌ 无 | ☐ |

### J. 工具与脚本

| # | 3.0 文件 | 功能 | 4.0 现状 | 拍板 |
|---|---|---|---|---|
| J1 | `scripts/keygen.py` | 密钥生成（License）| ❌ 无 | ☐ |
| J2 | `scripts/package.py` | 打包 | ⚠️ PyInstaller 配置 | ☐ |

---

## §3 拍板方式

我会**按模块 A→J 顺序**，每组 3-5 个选项问一次。回答格式：
- **补** = 复制 3.0 业务到 4.0
- **不做** = 完全忽略
- **简化** = 只做核心（我会描述简化方案）

你只回答"补/不做/简化"或你自己的话，我来整理到 §1。

---

## §4 计数

- 总条目：约 **75 条**业务
- ✅ 已拍板（含 subtext card 11 条）：**15 条**
- ☐ 待拍板：**60 条**
