# Changelog

本文件记录项目的所有重要变更。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased] - 2026-06-06

> UI 一致性全量重构（change-id: `ui-consistency-overhaul-2026-06-06`）。
> 详见 [UI 一致性全量重构方案](../../.trae/documents/ui-consistency-overhaul-2026-06-06.md) 和 [实施报告](../../docs/BUG修复记录/2026-06-06-ui-consistency-overhaul.md)。

### Added

- **UI 一致性专项测试**（`tests/ui_consistency/`，47 个用例）：硬编码颜色扫描、setStyleSheet 限额、按钮 token 分布、主题切换有效性、插件 capability 同步一致性
- **`tests/run_ui_consistency.py`**：UI 一致性测试独立入口（与 `run_backend.py` / `run_e2e.py` 一致模式）
- **`PluginUISync` 中间件**（`ui/main_window/plugin_ui_sync.py`）：插件 capability → Tab UI 统一同步层，支持懒加载回放、错误隔离
- **`make_btn_style(semantic)` 主题感知**：7 类按钮语义（`primary` / `important` / `warning` / `auxiliary` / `tool` / `ai_auto` / `default`），按钮高度统一 32px
- **`ui/utils/theme.py` 35 个新 token**：状态色 hover/active（8）、Flat UI 调色板（13）、Bootstrap 软色（14），统一 DARK/LIGHT 双主题

### Changed

- **按钮样式统一化**：73 UI 文件的 506 处 setStyleSheet 散落 → 157 处 make_btn_style 统一入口
- **硬编码颜色清理**：31 UI 文件 332 处硬编码 hex 颜色 → 284 处 Theme.color() 调用（剩余 30+ 处于 docstring 手工补全）
- **插件 capability 集中注册**：原 main_window + 3 Tab 散落的 5 个 capability 处理逻辑 → `PluginUISync.register()` 单一入口
- **`button_styles.py` 重构**：删除 7 个静态常量（PRIMARY/IMPORTANT/WARNING/AUXILIARY/TOOL/AI_AUTO/DEFAULT），文件从 181 行 → 141 行
- **危险按钮样式**：17 个 delete/reset/clear 操作统一走 `make_btn_style('warning')` + QMessageBox.question 二次确认

### Fixed

- **`ui/widgets/knowledge_control_panel.py:172` 嵌套双引号 SyntaxError**（Phase A.9 验证时发现，阻塞 `test_top_k_clamped_to_max`）
- **主题切换时 setStyleSheet 设置的按钮不跟随**：Phase A+B 走 make_btn_style/Theme.color() 后自动跟随

### Removed

- 物理删除 7 个 `button_styles.py` 静态常量（PRIMARY/IMPORTANT/WARNING/AUXILIARY/TOOL/AI_AUTO/DEFAULT）
- 删除原 `_on_plugin_activated` 中 capability 硬编码分支（已统一走中间件）

### Stats

| 维度 | 数字 |
|------|------|
| 涉及 UI .py 文件 | 73 |
| `make_btn_style` 调用 | 157（覆盖 29 文件） |
| 硬编码颜色清理 | 332 → 0（除 token 定义） |
| setStyleSheet 限额 | per-file ≤ 60，total ≤ 500 |
| UI 一致性测试 | 47 用例（0.7 秒） |
| Commit 数 | 16（Phase A: 7 / B: 4 / C: 2 / D: 1 / E+F: 2） |
| 净代码变更 | +500（中间件 + 测试）/ -1500（硬编码样式清理） |

## [3.1.0] - 2026-06-05

> 增强版本：在 3.0 三阶段范式基础上增加品味标准、用户确认和多版本选择。

### Added

- **7 问品味 Self-Critique**（Task 1）：在原 4 问技术合规基础上追加 3 问品味标准（吸引力 / 不出戏 / 情绪共鸣）
  - `taste_score` / `taste_issues` / `taste_passed` 字段落库
  - `technical_score < 60` 阻断，`taste_score < 60` 仅黄色提示（非阻断）
  - `SelfCritiqueReportDialog` UI 展示品味问题详情
  - 旧 4 问格式自动 fallback（兼容性保证）
- **用户确认步骤**（Task 2）：Write 后进入 USER_CONFIRM 交互步骤
  - 前 10 章默认开启（4 槽位流程）
  - 3 个操作：[继续] / [重写 + 反馈] / [跳过]
  - 重写反馈上限 200 token，防过度补偿
  - 重写次数上限 3 次（防死循环）
  - 风格学习触发点（前 10 章用户确认后）
  - `UserConfirmDialog` + `_ConfirmBridge` 跨线程信号桥接
- **多版本 Write 选择**（Task 3）：Write 阶段可生成 3 个不同风格/节奏的版本
  - 配置项 `workflow.multi_version` / `workflow.multi_version_chapter_limit`
  - 5 槽位流程：WRITE → SELECT_VERSION → USER_CONFIRM → SELF_CRITIQUE → PERSIST
  - `VersionSelectDialog` 3 版本并排展示 + 字数统计 + 选定按钮
  - `_VersionSelectBridge` 跨线程信号桥接
  - `parse_multi_version_output()` 解析 + 单版本 fallback
  - `StepIndicatorV3` 支持 3/4/5 槽位动态切换

### Changed

- **StepIndicatorV3**：clamping 范围 [3,4] → [3,5]，支持 5 槽位模式
- **WorkflowThread**：新增 `version_select_dialog_factory` 参数，动态 3/4/5 槽位
- **execute_chapter_v3**：新增 `on_version_select` / `force_multi_version` 参数

### Fixed

- **测试环境污染**（Windows）：`test_config_manager.py` 中 `patch.dict(os.environ)` 恢复时超长环境变量（>32K）导致后续测试 `Could not determine home directory`，改用 `monkeypatch.setenv/delenv` 修复

## [3.0.0] - 2026-06-05

> 范式版本：从"防御性 7 步工作流"全面重构为"引导性 3 阶段写作范式"。
> 详见 [演化路径.md](演化路径.md)。

### Added

- **3 阶段工作流**：Write（1 次 LLM，~8-10K）→ Self-Critique（1 次 LLM，~4-5K）→ Persist（0 token）
- **4 大引导元素**（替代 2.0 的"约束清单 + 禁止项"）：
  - **潜文本卡**（`SceneSubtextCard`，`app/workflow/subtext_card.py`）：表面事件 / 真实意图 / 谎 / 真 / 物理锚点
  - **角色声音档案**（`CharacterVoiceProfile`，`app/workflow/voice_profile.py`）：句法 + 词汇 + 决策 + 关系指纹
  - **作者风格指纹**（`AuthorStyleFingerprint`，`app/workflow/style_fingerprint.py`）：pace / density / lyricism 三轴 + 漂移检测
  - **反规则系统**（`Anti-rule Allowance`，`app/workflow/anti_rule.py`）："在 Y 范围内允许打破 X"
- **6 个 0 token 本地验证器**（`app/workflow/validators/`）：
  - POV 验证器 / 空间验证器 / 声音验证器 / 设定覆盖率 / 重复检测 / 物品/承诺校验
- **跨章一致性检查器**（`app/workflow/consistency_checker.py`）：跨章设定 / 物品 / 对话 / 时序 / 情绪
- **风格增量学习器**（`app/workflow/style_learner.py`）：Persist 阶段末根据本次输出微调三轴
- **声音档案冷启动推断**（`app/workflow/voice_inferer.py`）：2-3 段对话样本 → LLM 提取指纹
- **3 个新表**：`scene_subtext_cards` / `character_voice_profiles` / `author_style_fingerprints`
- **`chapter_summaries.validation_flags`** 字段：记录 6 验证器 Flag 模式输出
- **5 个里程碑（M1-M5）** 实施报告：M1 潜文本卡 → M2 RAG 预取 + 6 验证器 → M3 3 阶段范式 → M4 E2E → M5 50 章连贯
- **演化路径文档**（`docs/版本管理/演化路径.md`）：基于 git 历史的 4 阶段真实节点

### Changed

- **架构层**：从 7 步工作流（Planner→Writer→Auditor↔Reviser→Polisher→Verify→Settler）→ 3 阶段范式
- **流程入口**：`app/workflow/engine.py`（2.0 WorkflowEngine）物理删除，3.0 流程由 `app/workflow/v3_engine.py` 统一编排
- **Token 消耗**：~50K/章 → **~12-15K/章**（**-70%**）
- **AI 调用次数**：5-7 次/章 → 2 次/章（Write + Self-Critique）
- **agents/ 目录**：4 个旧 Agent（`planner` / `auditor` / `reviser` / `polisher`）物理删除，仅保留 `base` / `writer` / `settler` / `import_parse`
- **9 个 2.0 旧 prompt .md** 文件物理删除（已被 `app/workflow/prompts.py` 函数取代）
- **`app/ai/prompts/loader.py`** 物理删除
- **`app/core/security.py`** 物理删除（已合并到 `license.py`），全项目 import 替换
- **prompts.py 旧函数**：`get_auditor_prompt()` / `get_reviser_prompt()` / `get_polisher_prompt()` / `get_planner_prompt()` 2.0 版本物理删除
- **UI 同步到 3.0**：
  - 生成 Tab 步骤指示器改为 3 步（Write 紫 → Self-Critique 粉 → Persist 蓝）+ `ValidatorCardPanel`
  - 大纲 Tab 工具栏新增 4 个 3.0 元素入口（潜文本卡 / 反规则 / 风格指纹 / 声音档案）
  - 仪表盘新增"3.0 Token 节省"展示
  - 欢迎页强化 3.0 三大特性 + 4 大引导元素
- **主题令牌补全**：`ui/utils/theme.py` 新增 `SIZE_TYPOGRAPHY` 字典，字体尺寸统一令牌化
- **版本号**：2.0.0 → 3.0.0，CODENAME `FUSION` → `ASCENSION`，BUILD `20260521` → `20260605`
- **README / AGENTS.md** 重写反映 3.0 范式，移除所有 2.0 相关文案（7 步工作流、Planner/Writer/Auditor/Reviser/Polisher/Settler 7 agent 等）

### Removed

- 物理删除 `app/workflow/engine.py`（2.0 WorkflowEngine）
- 物理删除 4 个旧 Agent（`planner` / `auditor` / `reviser` / `polisher`）
- 物理删除 9 个 2.0 workflow 专有文件（`rule_engine` / `contract` / `story_system` / `reading_pull` / `reading_pull_prompts` / `event_audit` / `strand_tracker` / `chapter_summary` / `constants`）
- 物理删除 9 个旧 prompt .md（`auditor` / `reviser` / `polisher` / `planner` / `deepeditor` / `deepreader` / `settler` / `writer` / `shared`）
- 物理删除 `app/ai/prompts/loader.py`
- 物理删除 `app/core/security.py`（合并到 `license.py`）
- 物理删除 2.0 旧测试（`tests/test_ai_workflow.py` / `tests/test_e2e_workflow.py`）
- 物理删除 2.0 旧文档（`docs/开发说明和手册/` 下 5 个 + `docs/重构规划报告/` + `docs/TODO/` + `docs/BUG修复记录/2026-05-19.md` ~ `2026-05-30.md`）
- 移除任何"2.0/3.0 兼容"相关 UI 提示

## [2.2.0] - 2026-06-02

### Fixed

- 7步工作流端到端数据流修复：Auditor使用全局word_target导致章节级字数目标失效，fast-fail误杀合法章节
- Writer将planner_result整个dict转字符串作为约束清单，AI无法正确理解约束，改为使用raw_content
- core_events和characters未注入Planner prompt，用户大纲中的核心事件和出场角色对工作流完全不可见
- Auditor完全不知道禁止项列表，D19维度（禁止项合规）形同虚设，现从DB读取并注入prompt
- 两套auditor prompt不一致（字数容差、视角阈值、快速失败行为），统一到prompts.py版本
- Planner视角硬编码为"第一人称>90%"，无论数据库实际配置，现从DB读取动态传入
- PLANNER输出显示原始JSON带引号截断，新增格式化方法转为可读约束清单
- SHARED_RULES硬编码字数标准"2500-3500字"，改为动态占位符替换
- Polisher缺少字数和视角约束，润色时可能偏离目标字数或引入视角违规

### Changed

- `get_user_constraints()` 扩展：新增core_events、characters、ending字段提取，用户大纲信息完整注入
- `get_auditor_20d_prompt()` 新增prohibitions参数，Auditor可审核禁止项合规
- `get_planner_prompt()` 新增narrative_perspective和perspective_percent参数
- `get_polisher_prompt()` 新增word_target、narrative_perspective、perspective_percent参数
- `reading_pull_prompts.py` 的重复auditor prompt委托给prompts.py统一版本

## [2.1.1] - 2026-05-30

### Fixed

- 已完成7步的章节点击生成时错误提示"从第8步继续"，现在正确提示"已完成全部工作流，是否重新生成"
- 部分完成的章节提示信息不明确，现在明确提示从第几步继续执行
- 选择"否"重新开始时步骤指示器状态未清除的问题
- `get_character_list_str` 只输出name/role/description三个字段，角色设定中性格、身份、体香、梦境设定等关键信息全部丢失，导致AI生成内容与设定严重不符
- `get_user_constraints` 函数不存在，Planner中调用后始终返回空字符串，全局禁止项和章节禁止项从未注入到prompt中
- aiohttp ClientSession绑定旧事件循环导致"Event loop is closed"崩溃，第二次运行工作流时必现

### Refactored

- Agent checkpoint保存和私有记忆持久化逻辑统一化：在BaseAgent中提取`save_checkpoint()`和`persist_private_batch()`通用方法，消除6个Agent子类中重复的checkpoint构建和记忆持久化代码
- AI痕迹检测新增dim24维度：检测"不是X，是Y"否定反转句式（≥3次/章为AI特征），并提供自动修复

## [2.1.0] - 2026-05-26

### Added

- 全局爽点密集度设置：`cool_point_density`（中/高/非常高），参数化硬编码的密集度规则
- 全局禁止项设置：`global_prohibitions`，与章节级 prohibitions 双层合并
- 作者要求字段：`author_requirements`（原 `notes`），注入 Planner prompt 作为硬约束
- 密集度规则动态生成：`get_density_rules()` 和 `get_creative_constitution()` 根据级别返回不同规则
- 导入预览AI解析补全按钮：脚本解析不完整时可使用AI补全缺失内容
- `_parse_character_table()` 方法：支持"每行一个角色"的扁平 Markdown 表格解析
- `TemplateDetector.is_single_file_template()` 类方法
- `_ensure_tab_loaded` 懒加载后同步已激活插件 UI 状态

### Changed

- Planner 自主规划伏笔和爽点：不再从章节大纲的 hooks_plant/hooks_reap/cool_points 字段读取
- 禁止项双层设计：全局禁止项（所有章节生效）+ 章节级覆盖（可选）
- `chat()` 方法恢复完整逻辑：检测运行中loop → 线程池提交 → run_until_complete
- `_on_plugin_activated/deactivated` 添加 `ai_gen` capability 处理分支
- 单文件导入检测关键词扩展：新增"核心设定"、"设定"、"时代背景"、"人物表"
- `import_characters` 支持"人物表"标题和扁平表格格式

### Removed

- 章节大纲死字段：`hook_design`、`cool_points`、`cognitive_boundary`（工作流中从未消费）
- 章节大纲伏笔字段：`hooks_plant`、`hooks_reap`（改为 Planner 自主规划）
- `_sync_hooks_from_chapter()` 方法（不再从 chapter_briefs 同步伏笔到 hooks 表）

## [2.0.0] - 2026-05-23

### Added

- 微内核+插件架构：Container(DI容器) + EventBus(事件总线) + PluginManager(插件管理器)
- 7步工作流完整实现：Planner → Writer → Auditor(增强版) ↔ Reviser → Polisher → Verify → Settler
- 合同与规则引擎体系：BookContract + RuleEngine + Planner.verify 双层验收
- 三视角合一审核：Auditor增强版合并读者视角+编辑视角+六维量化评分
- 混合检索RAG：向量检索 + BM25关键词检索，RRF融合排序
- 长篇记忆系统：LTM+STM滑动窗口+蒸馏联动
- 实体图谱：角色/伏笔/地点关系图谱，图形化可视化
- 双知识库：内置知识库（6类别×9题材矩阵）+ 用户知识库（支持任意位置文件夹）
- 反AI味机制：29种AI去味模式 + 后写验证流水线
- Agent记忆持久化：私有记忆跨会话保存，支持断点恢复
- 多模型支持：MiniMax/DeepSeek/Claude/Kimi/混元/OpenAI等，按步骤配置模型
- 伏笔追踪：支持多章节回收，高亮本章节应回收的伏笔
- 视角配置：支持动态视角切换
- TTS语音朗读：Edge TTS，支持多种中文方言，逐句高亮跟踪
- 7个热插拔插件：entity_graph/knowledge_builtin/knowledge_local/prompts_default/tts_edge/usage_analytics/version_history
- 用量分析：Token统计、API调用统计、成本估算（基于模型定价）、步骤分布、日期趋势
- 确定性后写验证器：11+条零LLM调用规则
- 结构化AI痕迹检测：4维度检测
- Reviser智能路由：patch/rewrite/anti-detect三种模式
- 独立Polisher Agent
- 跨章重复检测、段落漂移检测、标题去重
- 读者心理曲线
- 多级降级：正常→简化prompt→最小prompt
- 世界图谱图形化可视化（力导向布局）
- 插件管理对话框：非模态独立窗口，即时启用/停用
- 记忆配置展示7Agent记忆：共享记忆 + Agent记忆视角 + Agent私有记忆三层展示（方案C）

### Changed

- 项目目录整合：删除23+重复/死代码文件
- AI引擎核心化：ProviderConfig/ModelCard合并到app/ai/providers.py
- TTS插件化：TTSManager实现ITTSPlayer接口
- 存储核心化：删除plugins/storage_sqlite/，UI直接用project_db
- 记忆模块合并：删除重复的memory_manager.py
- 题材模板合并：YAML模板迁移到app/ai/prompts/genres/
- 主窗口整合：删除main_window.py，功能合并到main_window_ui.py
- 知识库异步动态加载：启动时创建占位符，首次切换Tab时加载
- Tab切换防抖：3秒内不重复刷新
- 插件启用/停用后UI动态变化：Tab/按钮/菜单实时增删

### Removed

- CLI模块：整体删除app/cli/目录
- 重复/死代码：23+个文件
- 硬编码用量分析对话框：由插件动态管理

### Fixed

- Unclosed client session：aiohttp session复用
- Token截断警告：自适应超时
- 知识库管理无内容显示
- 记忆管理报错 UnboundLocalError
- 一键生成全部内容时软件无响应并闪退
- 配置LLM时卡顿
- 插件启用失败（EventBus双实例问题）
- 插件停用后Tab/按钮不自动隐藏
- 用量分析数据全部显示为0（字段名不匹配）
- 用量分析工具栏按钮无法添加（查找条件错误）
- 用量分析Tab切换崩溃（属性名错误）
- knowledge_local插件加载失败（Path未导入）
- 导入设定时FOREIGN KEY constraint failed崩溃
- 世界图谱可视化崩溃（scenePosition→scenePos）
- 全局设置字数未同步到章节大纲
- TTS朗读后自动退出（线程安全问题）
- 窗口关闭时TTS未停止
- 写作视角未正确传导
- CI全平台测试失败：修复7个测试文件中的过时导入路径和API引用（test_workflow.py/test_workflow_utils.py/test_ai_workflow.py/test_db.py/test_plugins.py/test_integration.py/test_core.py）
- ruff lint 27个未使用导入警告
- Ruff Lint 229个问题全量修复：F821未定义名称(19个)、F601字典key重复(1个)、F401未使用导入(115个)、F541无占位符f-string(42个)、F841未使用变量(24个)、E402导入不在顶部(16个)、E741模糊变量名(6个)、F811重复定义(3个)、E401多导入写一行(2个)、E713(1个)

### Refactored

- Agent模型配置获取统一化：在BaseAgent中提取`_get_step_model_config()`通用方法，消除6个Agent子类中9处重复的模型配置获取逻辑
- Ruff问题全量修复：涉及约30个文件，包括自动修复182个、手动添加缺失导入、代码重构、TYPE_CHECKING模式、noqa标记可选依赖
