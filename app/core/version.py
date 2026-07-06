"""
版本号管理 (B7: 完整做)
- 4.0 重写版本 = 3.2 (从 3.0 重写过来)
- 顶部菜单 / 关于页面 / 数据库版本

变更历史:
  3.0 → 3.2  (4.0 重写版)
  - 改用 PySide6 (4.0 UI 框架基线)
  - 集成 92 条决策 (subtext/L1-L4/编排/插件等)
  - DB 27 表
  3.2 → 3.3  (4.0 增量)
  - A1 题材 prompt UI: 1-5 题材多选 + 平台 + 字数目标, 注入 writer prompt
  - H1 ai_outline_gen 插件: 前 10 章 A/B/C 3 版本大纲
  - H7 tts_edge 插件: 章节转语音 (mock)
  - H8 usage_analytics 插件: 使用统计
  - Dialogs 库 + ThemeToggle widget 替换 QMessageBox / 旧主题按钮
  - Tokens 提示系统 (welcome / PriceBar / FirstUsePopup) 3 位置
  - Subtext 子面板 + 章节标注 + 模板帮助按钮
  - 屏幕适配 (ScreenAdapter)
  3.3 → 3.4  (M11: 设置 tab 完善 + AI Router 真接通 + 一键出版)
  - M10: Feature Gate UI (PRO 角标) + AI Router Status Bar (Dashboard 顶部)
  - M10-B: License 设置面板 UI (Pro/Free 切换 + 激活码)
  - M11-A: 修 6 个 pre-existing smoke (500/500)
  - M11-B: AI Router 业务事件层 (signals.py) + L2 RealLLMClient + RouterStatusBar 实时刷新
  - M11-C: 设置 tab 增 🤖 AI 路由 (strategy/cache 阈值) + ℹ️ 关于 (版本/更新日志)
  - M11-D: 一键出版 4 步向导 (打包/封面/导出 ZIP+XML)
  3.5.0 → 3.5.1  (Story Engine 落地：Guidance 而非 Constraint)
  - 设计哲学：项目宪法化，三角色职责分离（作者/AI/Story Engine）
  - Guide 接口契约：所有模块统一输出 list[Guide] 对象（source/severity/advice/evidence_ids）
  - collect_guides(unit_id)：Orchestrator 统一收集所有模块的引导建议
  - Virtual Unit 适配层：Chapter 自动包装为 Virtual Unit，消灭双轨架构
  - Event 表 + State Diff：Unit 完成自动记录因果流（40 号迁移新增 story_events 表）
  - event_type_enum 表：13 类事件类型枚举，防拼写错误
  - Chapter Exporter 独立模块：preview() 干跑模式 + truncation_warning
  - Orchestrator A/B 灰度切换：use_guide_system=False/True 双路径并存
  - run_unit() 成为推荐入口，run_chapter() 加 DeprecationWarning
  - Agent 适配 Unit 接口：memory_keeper / pressure_watcher / context_builder / editor / critic
  - UI 切换单元选择器 + "使用新 Guide 系统" 隐藏 checkbox
  - 8 份外部意见整合（3 GPT + 4 workbuddy + 1 全面诊断）
  3.4 → 3.5.0  (故事单元模式 + 段落锚点 + 双向同步)
  - 故事单元核心架构: 单元是创作单位，章节是发布单位
  - 双时间线: story_order (因果顺序) + present_order (呈现顺序)，支持非线性叙事
  - 段落锚点机制: 每段稳定 UUID，钩子/记忆锚定到段落 ID
  - 单元-章节双向同步: 单元=真相源，章节=视图，修改任意一端自动同步
  - run_unit() 分段生成 + 断点快照，支持随时中断恢复
  - 钩子/伏笔服务: plant/payoff/reminder 生命周期，手动锁定保护
  - 入出口状态: 每个单元独立的角色/世界/承诺状态，支持从前单元继承
  - 数据库迁移: 35-39 号迁移，新增 story_units / unit_paragraphs / unit_briefs 等 8 张表
"""
from __future__ import annotations
from pathlib import Path

VERSION = "4.0.0"
APP_NAME = "NovelWriter"
APP_DISPLAY_NAME = "小说写作助手"
APP_DESCRIPTION = "AI 辅助长篇小说创作工具"

# 构建信息 (CI/CD 注入)
BUILD_DATE = "2026-07-06"
GIT_COMMIT = "dev"

CHANGELOG = """
4.0 (2026-07-06) - Guide Graph + Story Compiler + 单元化完成
  - Guide Graph：冲突检测 + 冲突图构建 + prompt 注入
  - Story Compiler：四维度影响分析（exit_inherit/hook_depend/event_cascade/character_state）
  - _dispatch_persist 单元化：Unit 写完不再自动创建 Chapter，改为调 Chapter Exporter
  - 验证：147/147 通过，后端架构全部就绪

3.6 (2026-07-06) - Decision 层：可解释 AI
  - Decision dataclass：记录 Guide 采纳/忽略决策
  - unit_decisions 表（41 号迁移）
  - decision_service：record/batch/list/summary/build_decisions_block
  - Orchestrator 双注入：Guide 列表 + Decision 记录 + Decision 历史
  - GuidePanel 展示 Decision History
  - 验证：59/59 通过

3.5.2 (2026-07-06) - Guide 7 字段 + 9 模块输出
  - Guide dataclass：5 字段 → 9 字段（新增 priority/confidence/scope/reason/possible_actions）
  - 9 个模块实现 get_guides()：consistency/memory/pressure/style/voice/hook/unit_event/reader/character_state
  - collect_guides() 统一收集所有模块的 Guide
  - GuidePanel UI 面板（超前落地）
  - 验证：42/42 通过

3.5.1 (2026-07-06) - Story Engine 落地：Guidance 而非 Constraint
  - 设计哲学：项目宪法化，三角色职责分离（作者/AI/Story Engine）
  - Guide 接口契约：所有模块统一输出 list[Guide] 对象
  - collect_guides(unit_id)：Orchestrator 统一收集所有模块的引导建议
  - Virtual Unit 适配层：Chapter 自动包装为 Virtual Unit
  - Event 表 + State Diff：Unit 完成自动记录因果流（40 号迁移）
  - event_type_enum 表：13 类事件类型枚举
  - Chapter Exporter 独立模块：preview() 干跑模式 + truncation_warning
  - Orchestrator A/B 灰度切换：use_guide_system=False/True 双路径并存
  - 8 份外部意见整合（3 GPT + 4 workbuddy + 1 全面诊断）

3.5.0 (2026-07-06) - 故事单元模式
  - 故事单元核心架构：单元是创作单位，章节是发布单位
  - 双时间线：story_order（因果顺序）+ present_order（呈现顺序），支持非线性叙事
  - 段落锚点机制：每段稳定 UUID，钩子/记忆锚定到段落 ID
  - 单元-章节双向同步：单元=真相源，章节=视图，修改任意一端自动同步
  - run_unit() 分段生成 + 断点快照，支持随时中断恢复
  - 钩子/伏笔服务：plant/payoff/reminder 生命周期，手动锁定保护
  - 入出口状态：每个单元独立的角色/世界/承诺状态，支持从前单元继承
  - 数据库迁移：35-39 号迁移，新增 8 张单元模式表

3.4.0 (2026-06-15) - M11 增量
  - M10: Feature Gate UI (PRO 角标) + AI Router Status Bar (Dashboard 顶部)
  - M10-B: License 设置面板 UI (Pro/Free 切换 + 激活码)
  - M11-A: 修 6 个 pre-existing smoke (500/500)
  - M11-B: AI Router 业务事件层 (signals.py) + L2 RealLLMClient + RouterStatusBar 实时刷新
  - M11-C: 设置 tab 增 🤖 AI 路由 (strategy/cache 阈值) + ℹ️ 关于 (版本/更新日志)
  - M11-D: 一键出版 4 步向导 (打包/封面/导出 ZIP+XML)

3.3.0 (2026-06-10) - 4.0 增量
  - A1 题材 prompt UI: 1-5 题材多选 + 平台 + 字数目标
  - H1 ai_outline_gen 插件: 前 10 章 A/B/C 3 版本大纲
  - H7 tts_edge 插件: 章节转语音 (mock)
  - H8 usage_analytics 插件: 使用统计
  - Dialogs 库 + ThemeToggle 替换 QMessageBox / 旧主题按钮
  - Tokens 提示系统 (welcome / PriceBar / FirstUsePopup) 3 位置
  - Subtext 子面板 + 章节标注 + 模板帮助按钮
  - 屏幕适配 (ScreenAdapter)

3.2.0 (2026-06-09) - 4.0 重写版
  - 改用 PySide6 (UI 框架基线)
  - 集成 92 条决策
  - DB 27 表 (5.0 8 + 9.0 19)
  - subtext card 13 字段
  - L1-L4 记忆系统
  - 世界观 5 表 + 5 文件 store
  - 编排 Agent 隔离写手
  - 插件 4 件套 (manager/loader/install)
  - 授权系统 (机器码 + 网络时间)
  - 日志 (项目文件夹 + 7天清理)
""".strip()


def get_version() -> str:
    return VERSION


def get_version_tuple() -> tuple[int, int, int]:
    return tuple(int(x) for x in VERSION.split("."))[:3]  # type: ignore


def get_full_info() -> dict:
    return {
        "name": APP_NAME,
        "display_name": APP_DISPLAY_NAME,
        "description": APP_DESCRIPTION,
        "version": VERSION,
        "build_date": BUILD_DATE,
        "git_commit": GIT_COMMIT,
        "changelog": CHANGELOG,
    }


def format_about_text() -> str:
    """关于页面文本。"""
    return f"""
{APP_DISPLAY_NAME} v{VERSION}

{APP_DESCRIPTION}

构建日期: {BUILD_DATE}
Git: {GIT_COMMIT}

─── 更新日志 ───

{CHANGELOG}
""".strip()
