# novel-writer-pure 重写规划文档

## 文档结构

### 1. 功能盘点（已完成）
[3.0-features-inventory.md](file:///d:/novel-writer-pure/docs/rewrite/3.0-features-inventory.md) — **3.0 已实现的全部功能**
- 11 类核心功能（业务/AI/记忆/数据/插件/UI/系统）
- 19 张核心表 + 4 张叙事工坊表
- 10 个核心插件
- 重写时必含项（★★★★★）vs 建议改进项

### 2. 从 0 重写 PRD（待用户审阅）
[from-scratch-prd.md](file:///d:/novel-writer-pure/docs/rewrite/from-scratch-prd.md) — **从 0 重写完整 PRD**
- 9 大章节：业务内核 / 语言选型 / UI 设计 / 数据模型 / 业务流程 / 实施分阶段 / 风险 / 决策
- 业务保留：3 阶段范式
- 代码从 0 重写
- 语言不限：推荐 Rust + Tauri + React
- UI 按用户原型重做
- 10 周实施分阶段

### 3. 早期版本（作废）
~~3.0-v2-redesign.md~~ — 修补方案（作废）
~~language-selection.md~~ — Rust/Tauri 提议独立版（作废）
~~v4-architecture.md~~ — 4.0 提议（作废）

## 当前进度

✅ **3.0 全部功能已盘点** — 用户确认后开始重写规划
⏳ **从 0 重写 PRD** — 待用户回复语言选型（Rust+React / Python+PyQt / Go+Wails）
⏳ **决策点** — 数据迁移 / 插件策略 / 启动时机

## 待用户回复

请回复：
1. **技术栈** A. Rust+Tauri+React（推荐） / B. Python+PyQt（保守） / C. Go+Wails？
2. **数据迁移** A. 全量迁移旧 SQLite / B. 只迁移用户主动导出 / C. 不迁移？
3. **插件策略** A. 旧 10 个插件全部重写 / B. 挑保留 + 重写 / C. 暂时无插件？
4. **是否启动** A. 现在启动重写 / B. 先写完整 spec 再说？

你回复"1A 2A 3A 4A"或"全 A"，立即开干。
