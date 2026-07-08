# Project Context - novel-writer-pure-v3.4

This document serves as the conversation context for continuing development in TRAE Work CN. It contains all hard constraints, engineering conventions, lessons learned, and current project status.

---

## Hard Constraints

- 单元是唯一真相源，章节作为单元的视图，修改章节需同步回单元对应段落，单元变更触发下游同步
- 单元写作采用分段生成模式，每步生成1500-2500字，通过断点快照机制支持中断恢复
- 单元删除时提供三种处理章节的方式：连章节一起删、章节转正为独立章节、取消删除
- 钩子通过段落UUID锚定，而非字符偏移量，确保拆章时钩子能准确迁移到对应章节
- 单元分段生成时，已生成内容回灌采用token预算反推机制，从最近步骤往回取满可用token
- 重写单元第N步时，丢弃第N步及之后所有自动生成的衍生数据（正文/记忆/钩子/状态变化），保留用户手动锁定条目
- 单元摘要作为断点快照的一部分，重写步骤时从对应快照恢复，避免污染
- 拆章器采用三层结构：正则关键词初筛→AI情绪分析→人工确认，提升断章准确性
- 单元与章节双向同步：修改单元自动重新拆章，修改章节自动回写单元段落
- 单元写作服务需处理段级时间锚点，确保记忆查询准确性
- 单元拆章操作包在事务中，中途失败整次拆章回滚，确保数据一致性
- 单元钩子迁移时，单元钩子不删除，章节钩子指向源单元钩子，确保钩子可追溯
- 单元时间线标签与故事时间点分离，支持时间线分类和跨度标记
- 单元数据模型变更需通过数据库迁移实现，确保数据结构升级兼容性
- 单元写作流程需包含记忆更新、状态同步、断点保存等步骤，确保写作过程可靠
- 插件使用必须在所有层（UI/CLI/HTTP API/Dashboard）检查插件状态，依赖禁用插件的功能必须禁用
- AI调用前必须检查API key是否存在，防止调用失败
- 插件必须通过 `get_manager().get_instance()` 实例化，而非直接实例化，确保状态同步

---

## Engineering Conventions

- 主题颜色应通过 QSS 中的主题 token 引用，而非在 widget stylesheet 中硬编码值
- UI 组件必须使用 objectName 来应用 DARK_QSS 和 LIGHT_QSS 中主题特定的样式
- 项目管理页面遵循主从视图布局，左侧项目列表 + 右侧详情面板
- 项目操作（导出/删除）优先级：①左侧列表选中项 ②current_project ③仅存在的项目
- 项目题材设置采用「1主题材 + N副题材」双轨设计，主题材单选，副题材多选
- 副题材预设包含93个元素标签（穿越/重生/系统/无限流/脑洞/爽文/甜文/虐文/机甲/克苏鲁/快穿/空间/种田/经营等），与16个主题材（玄幻/都市/仙侠/修真/历史/军事/科幻/游戏/灵异/悬疑/轻小说/言情/武侠/奇幻/二次元/同人）完全不重叠
- 项目详情面板显示题材格式为「主题材 + (副题材1/副题材2/... +N)」
- 项目导出格式为*.novel.zip，内含project.json（payload）和README.txt（导出元信息），采用zipfile.ZIP_DEFLATED压缩
- 项目导出时自动补全.novel.zip后缀，即使选择.zip也会强制修改
- 项目导入支持向后兼容，可识别旧的.nwp.json格式和新的.zip/.novel.zip格式
- 仪表盘进度环使用自绘QPainter圆环，显示中心百分比和底部「已写/目标」数值
- 多项目对比表包含6列（项目/体裁/结构/已写/目标/完成度条），按完成度降序排列，使用文字条「████░░░░」展示进度
- 章节管理卷结构小卡位于编辑器左侧顶部，高度不超过80px，显示全书结构和字数进度
- 新建项目时采集的volumes/chapters_per_volume/words_per_chapter/主题材/副题材信息双写到projects表和structure.json
- AI写作prompt注入包含「题材与元素标签」和「字数控制」两个独立段落，分别提供题材分类+风格关键词和本章/全书字数目标
- 跨页面数据同步采用「事件总线 + showEvent 兜底」双保险：page 在 __init__ 订阅 project_event_bus，事件触发后 refresh；同时 override showEvent，每次页面切到可见时再 reload 一次，保证「绕过 event 直接改 DB」的场景也能同步
- 新建项目对话框中的分卷数/章节数/章节字数 spinbox 需隐藏上下箭头，仅支持手动输入数字
- 设定导入时采用4层自动识别机制：文件名hint→JSON顶层key→MD标题层级→内容结构，识别结果显示置信度和原因，支持手动选择「👥 角色」等key覆盖
- 章节管理页「✨ 开始写作」按钮初始禁用，选择章节后启用，取消选择后禁用；点击触发WritingFlowDialog，自动锁定当前book/chapter
- 写作流程7步编排器按顺序调用memory_manager/anti_ai/pressure/RAG finder/subtext/prompt_assembler/writer_agent/critic_agent/chapter_service/world_sync/consistency组件
- WritingFlowDialog显示WORKFLOW_STEPS，每步状态实时更新为「⏳→🔄→✅」，底部显示实时字数统计
- 写作完成后通过「📝 写入章节」按钮调用chapter_service落库，触发written_back信号同步刷新EditorTab主编辑器
- 导航菜单和页面注册表已更新：移除「潜文本卡」和「章节管理」，新增「大纲管理」、「世界观」、「角色管理」、「风格指纹」
- 大纲管理页面(OutlineMgmtPage)使用单版本直接编辑模式，支持大纲修改、保存、新增和删除功能
- 潜文本卡嵌入大纲编辑器下方，支持手写/AI自由规划模式切换（默认AI）
- 原章节管理中的编辑/评估/段落重写功能已合并到章节生成(GenerateTab)
- 潜文本卡功能由AI自动维护，不再在前端导航菜单中展示
- AI路由配置已合并进模型配置页面，导航菜单中移除「AI路由」项
- 潜文本卡面板作为right_splitter的子控件固定显示，初始尺寸600:400，支持拖拽分割条调整宽度比例
- 移除潜文本卡的收起/展开切换按钮(btn_toggle_subtext)和_on_toggle_subtext方法
- 章节生成(GenerateTab)在进度条下方添加可滚动的process_log面板（QPlainTextEdit），显示7步工作流详细日志（启动信息、每步状态及元数据、流式输出预览、信息提示），使用等宽字体和深色背景
- EngineContext.to_dict()需包含content字段传递实际生成内容，_on_done()方法必须将content写入编辑器
- 大纲管理页面(outline_tab.py)包含「+ 新建卷册」按钮，位于卷册列表下方，项目加载后自动启用
- 章节生成页面(generate_tab.py)不包含「+ 新建卷册」和「+ 新建章节」按钮，相关方法已删除
- 多版本正文生成(A/B/C3版)功能通过QCheckBox实现，与"✨ 生成 (7 步)"按钮并排显示；勾选后点击"生成"打开多版本对话框，未勾选时执行单版本7步生成
- 多版本生成对话框(BodyGenDialog)尺寸固定为900x600，避免超出屏幕
- 右侧评估面板初始尺寸从180缩小到90，为章节编辑器留出更多空间
- 风格变体生成器(style_variant.py)实现发散→收敛算法：第1轮spread=±4，第2+轮基于选定版本锚点按×0.5衰减，最终收敛到±1波动区间；5维风格指纹每维独立随机偏移
- 多版本生成对话框需显示轮次标签、风格指纹摘要及每版本指纹标签，提供「再生成一轮 (收敛)」按钮
- 多版本生成时每条线通过StyleVariant注入system prompt，使用system_prompt_override参数确保线程安全
- 段落重写功能需增强_parse_rewrite()函数，支持处理``标签（除原有``）
- 多版本正文生成(A/B/C3版)前10章选项应与生成7步选项并排显示
- 多版本生成完成时，若编辑器仍为空（流式输出未触发），自动填充完整内容到编辑器
- 章节列表刷新触发_on_chapter_selected时，仅当编辑器为空或数据库有草稿时才加载内容，避免覆盖已生成内容
- 生成过程中流式输出内容直接显示在章节编辑框，点击「保存草稿」时才将正文保存到章节文件
- 移除7步进度条和流程日志面板，简化界面，编辑器直接流式输出内容
- 生成过程不再自动落库，仅在点击「保存草稿」时才持久化到数据库
- 多版本生成改为复选框，与生成按钮并排
- 并行写作窗口缩小（1100x700→900x600）
- 「按序号重写」功能修改为「全部重写」，可一次性重写整个章节的所有段落
- 章节名识别正则需支持「第X章」「第X阶段」「第X卷」「第X幕」格式，包含阿拉伯数字和中文数字（一/二/.../十/百/千/万/零）
- detect_setting_key函数中的章节/卷识别正则需支持阿拉伯数字和中文数字（一/二/.../十/百/千/万/零）
- 大纲导入应使用outline_service.save_outline()写入chapter_outlines表（version="A"），而非chapter_service.update()
- world_relations表包含relation_type（10种：情感/利益/敌对/师徒/血缘/位置/拥有/联盟/中立/一般）和intensity（1-10）字段
- WorldGraphPage实现关系类型着色、强度宽度变化可视化及关系类型图例
- 反AI味三遍法实现Pass1去泛化→Pass2去书面化→Pass3回自然感，包含误杀防护机制（文学性表达豁免、角色化表达豁免）
- 题材特化写法指导在GENRE_WRITING_GUIDES中包含5大题材（玄幻/都市/仙侠/悬疑/言情）的AI病句正反例、写法要点、禁忌
- 长篇节奏报告分析最近10章的压力分布、钩子密度、情绪曲线，在仪表盘「长篇节奏报告」面板显示
- 风格进化端到端闭环包含style_learner.py（从用户修订章节学习风格）、style_variant.py（生成多版本风格变体）、style_fingerprint.py（存储和应用风格指纹）
- 世界观tab独立，新增worldview_tab.py，支持导入/修改/保存
- 角色管理tab独立，新增character_mgmt_tab.py，卡片式展示，点击弹窗查看详情
- 角色详情弹窗中包含声音档案配置（性格/句长/语气词/口头禅/隐喻偏好）
- 风格指纹tab重构，新增style_fingerprint_tab.py，滑动条控制5个维度 + 预设风格下拉
- 全文反规则优化，改名为"全文反规则"，添加使用提示和示例
- 导入大纲按钮从小说设定移到大纲管理tab
- 导航菜单包含19个页面，一级菜单项包括「小说管理」下的「项目管理」「小说设定」「世界观」「角色管理」「风格指纹」「大纲管理」「章节生成」「自动进化」

---

## Lessons Learned

- Hard-coded background colors in widgets (e.g., #191a1b, #0a0b0d) cause theme switching failures
- QSS styles for theme-dependent components need to be defined in both DARK_QSS and LIGHT_QSS to ensure proper color adaptation
- Hiding delete/export functions in card corners with selection prerequisites violates user intuition; direct header buttons with state-dependent enablement are preferred
- koa-connect wrapper caused ctx leaks, so native rewrite is required
- page 用 showEvent 兜底 reload 时不要 self.window().current_project 拿数据（测试场景无 parent 窗口会失败），应在 page 自己跟踪 _current_pid / _current_project，showEvent 内用 service.get 拉最新
- 写涉及 QDialog 弹窗的 UI 测试时，务必 mock Dialogs.info/warning/confirm，否则 offscreen 模式会卡死主线程
- _build_user_prompt()函数参数不匹配会导致TypeError；修改函数调用时必须同步更新函数定义，同时清理__pycache__缓存避免旧字节码干扰
- 多版本对话框关闭后，章节列表刷新触发_on_chapter_selected，从数据库加载空草稿覆盖了编辑器内容（因为skip_persist跳过了落库）
- Plugin usage was scattered across 4 layers (UI/CLI/HTTP API/Dashboard) with independent development, lacking a unified 'plugin status gatekeeping' pattern; testing only covered 'whether the plugin itself runs' without verifying 'whether usage parties intercept when plugins are disabled'
- 正文与追踪文件严重脱节时需及时同步，追踪文件声称已完成的章节数应与正文实际章节数一致
- 设定一致性检查需覆盖数量计算（如干饼数量）、伏笔编号等细节，避免逻辑错误
- 章节逻辑断裂问题（如方向决策、理论与行为割裂）需通过审查报告及时发现和修复
- 套话和模式化表达（如"他心里动了一下""他以前在现代……"）会影响小说质量，需在写作过程中识别和替换
- custom agent需在新会话启动时才会注册为subagent_type，可通过特定命令判断agent是否注册成功

---

## Current Project Status (v3.5.0)

### Core Services Implemented
- story_unit_service_v2.py (dual timelines, state machine)
- unit_paragraph_service.py (stable UUID anchors)
- unit_writing_service.py (run_unit() segmented generation)
- unit_hook_service.py (lifecycle management)
- unit_chapter_mapper.py (bidirectional sync)
- 8 new unit mode database tables via migrations 035-039

### UI Updates
- story_unit_tab.py upgraded to v2 service
- DeleteUnitDialog with 3 options (delete with chapters, keep chapters unlinked, cancel)
- Writing progress panel with step count and target_chars
- Snapshot management section with rollback functionality

### Recent Bug Fixes
- AI provider selection issue: configured Agnes/agnes-2.0-flash wasn't being used due to disconnected systems (app_setting_service JSON vs ModelRegistry database)
- Fix: Modified app/ai/registry.py to prioritize active provider from app_setting_service in get_primary()

---

## 10 Core Module Alignment Check Results

| Module | Status | Key Issues |
|--------|--------|-----------|
| 多版本正文生成 | 风格变体（5维指纹±spread） | 不是内容变体，只是风格微调 |
| 风格进化闭环 | 词频统计→5维指纹 | 不是AI学习，只是简单统计；不能跨项目继承 |
| 反AI味三遍法 | 9项检查（检测+建议） | 不自动修改，Pass3规则太少 |
| 7步写作工作流 | 7步编排 | Step 2（反AI味）是占位，未实际执行 |
| 潜文本卡 | 13字段+3模式 | 不自动维护，需手动触发；部分字段未使用 |
| 自动进化 | 4层处理+5步进化 | 无UI展示，LLM泛化默认关闭 |
| 题材特化写法指导 | 5题材正反例 | 只有5/16题材，不自动注入 |
| 长篇节奏报告 | 压力统计+5条警告 | 无图表，只看最近10章 |
| 角色管理 | 卡片CRUD+声音档案 | 声音不自动应用，无关系图 |
| 世界观管理 | 单文本编辑器+导入导出 | 非结构化，无关联检测 |

---

## User's Key Requirements

1. **文风指纹重构**: 
   - Current: 全书写作风格预设（5维滑块）
   - Desired: 文风指纹（从正文3选1提炼 + 修改后自动进化 + 可跨项目继承）
   - 全书风格预设可保留，但应放到小说设定中以下拉方式设置（不设置则AI自由判断）

2. **声音档案生效**: 角色声音档案应自动影响AI生成的对话风格

3. **自动进化可视化**: 用户希望看到"系统学到了什么"并有管理界面

4. **世界观结构化**: 希望有结构化的知识图谱而非单文本框

---

## Todo List

1. ✅ 大纲导入按钮移到大纲管理tab
2. ✅ 角色管理tab独立（卡片展示+声音档案关联）
3. ✅ 世界观tab独立（导入/修改/保存）
4. ✅ 全文反规则添加使用提示
5. ✅ 风格指纹tab重构（滑动条+预设风格下拉）— 后因用户需求变更删除
6. ❌ 文风指纹重构（正文学习+跨项目继承）
7. ❌ 声音档案自动注入prompt
8. ❌ 自动进化UI展示
9. ❌ 世界观结构化编辑
10. ❌ 插件状态检查全局化
11. ❌ AI路由配置合并到模型配置页面
12. ❌ 多版本生成优化（内容变体而非仅风格变体）

---

## User Preferences

- Writing focus: realistic, human-like novel content with consistent character settings and plot
- Writing approach: guiding AI agents through scripted planning and prompting
- Visual output: self-contained HTML files (CDN loaded), no HTTP server
- Architecture: clear layered skeletons → infrastructure → business logic
- Development workflow: new isolated directory, assistant implements + automated testing, user does manual acceptance
- Story review: thorough reader-style reviews identifying inconsistencies, AI patterns, clichés
- Skill integration: interested in external writing skills but requires careful adaptation
