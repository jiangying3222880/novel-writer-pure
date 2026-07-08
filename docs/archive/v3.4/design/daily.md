# 开发日志

2026-07-06: 完成 v4.0 Guide Graph + Story Compiler + UI 四模块重构, 147/147 验证通过
2026-07-06: fix app.ui.pages→app/ui/observe 模块/包冲突改名 (DecisionHistoryPage/ImpactReportPage 遗漏修复)
2026-07-06: i18n UI 全面中文化 — 导航/设置/编辑器/HUD/observe四页
2026-07-06: v4 Story OS 四周建设完成 — story/ 包14文件, Event→State→Signal→Decision→Language→UI 链路, 35/35 smoke全绿
2026-07-06: v4 code review: 6 bug fixes (B1-B6) + 3 design fixes (D1-D3), 4 smoke tests all green
2026-07-06: v4 integration: Orchestrator.run_unit(use_v4_pipeline=True) 走 UnitRunner 全链路
2026-07-06: v4 UI integration: UnitEditor 添加 v4 Pipeline 复选框, 信号传递 use_v4 标志
2026-07-06: fix: generate_tab.py 多余括号导致 SyntaxError
2026-07-06: fix: Observe/Publish tabs 不显示, Create tab 缺少导航 — 4处映射对齐
2026-07-06: fix: 设置窗口关闭按钮灰色、模型配置不弹窗、主题切换不完全 — 3处修复
