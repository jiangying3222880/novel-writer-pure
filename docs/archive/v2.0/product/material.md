# Material: novel-writer-pure 项目介绍

## 1. Overview
- novel-writer-pure 是一款 AI 驱动的网文写作桌面工具，当前版本 v3.1.0（v3.2 开发中）
- 核心定位：用"引导性写作范式"替代传统"防御性 Prompt 工程"，让 AI 写出有文学质感的作品
- 技术栈：Python 3.12 + PyQt6（桌面端）+ SQLite（本地存储）+ OpenAI-compatible API
- 架构：微内核（Container IoC + EventBus + PluginManager）+ 热插拔插件体系
- 代码规模：~39K 行（app 22K + ui 17K），84 个 .py 源文件，727 个测试用例
- 开源协议：MIT License

## 2. Background（演化路径）
- v0.x：基础写作技能 jy-v5.4，探索期
- v1.0（2026-05-17）：8 步单步工作流，~50K token/章，5-7 次 AI 调用
- v2.0（2026-05-22）：7 步插件化，引入插件架构，仍以防御性 Prompt 为主
- v3.0（2026-06-05）：3 阶段引导范式，Write → Self-Critique → Persist，token 降至 12-15K（-70%），AI 调用降至 2 次
- v3.1（2026-06-05）：增加品味评分 + 用户确认 + 多版本选择，3-5 阶段动态模式
- v3.2（开发中）：UI 全面重构，1:1 复刻 Web 端设计，引入 ScaledContainer 矢量缩放

## 3. Key Info（核心数据与特性）
- Token 节省：从 ~50K/章 降至 ~12-15K/章（节省 70%）
- AI 调用次数：从 5-7 次降至 2 次/章
- 本地验证器：6 个，0 token 消耗，纯确定性逻辑
- 插件数量：9 个内置插件（实体图谱、知识库、TTS、AI 大纲生成、AI 导入、剧情推演等）
- 测试覆盖：62 个测试文件，727 个测试用例
- 代码总量：~39K 行 Python
- 支持：Windows 单文件打包（PyInstaller）+ 源码运行

## 4. Evidence（核心技术亮点）
- Case: Write 阶段 — 接收完整 SceneContext（潜文本卡 + 声音档案 + 风格指纹 + 反规则），一次 LLM 调用生成高质量章节
- Case: Self-Critique 阶段 — 7 问自评（技术合规 4 问 + 品味 3 问），不调修补 LLM
- Case: Persist 阶段 — 0 token 6 个本地验证器（POV/空间/声音/设定/重复/物品），跨章一致性检查
- Case: RAG 混合检索 — vector_db + BM25 双路检索，保障长篇上下文连贯性
- Case: 分层记忆 — MemoryManager + DistillManager + CharacterTracker，角色状态持久追踪
- Case: 微内核架构 — Container IoC + EventBus + PluginManager，插件热插拔，解耦彻底

## 5. Analysis（技术对比）
- 2.0 防御性范式：禁止项 + 20 维度扣分 + LLM 修补 LLM → AI 阻力大、质量不稳定
- 3.0 引导性范式：潜文本卡 + 声音档案 + 风格指纹 + 反规则 → AI 更自由、质量更稳定
- 潜文本卡：从"告诉 AI 不许做什么"变为"告诉 AI 场景背后的真实意图"，写出有深度的对话与动作
- 角色声音档案：句法 + 词汇 + 决策 + 关系指纹，彻底解决"性格：怂"关键词描述带来的 AI 脸谱化问题
- 作者风格指纹：pace/density/lyricism 三轴评估 + 自动增量学习器，保持全篇风格一致
- 反规则系统："在 Y 范围内允许打破 X"，给 AI 灵性空间，避免写作僵化

## 6. Outlook（未来规划）
- 零文档启动：3 轮渐进对话引导替代传统 6 字段表单，用户门槛进一步降低
- v3.2 UI 重构：完成 Web 端 1:1 复刻，引入 ScaledContainer 矢量缩放，全平台自适应
- E1-E12 增强方案全落地：情感衰减（E7）、节奏呼吸（E8）、信息差管理（E9）等高级叙事技巧
- RAG 精度提升：在无 API 环境下提高语义召回精度
- 实际 tracker 服务实现：完整的 token 用量监控、月限额管理

## Summary
- 高权威信源：README.md, AGENTS.md, MEMORY.md（项目自文档）
- 数据支撑充分：-70% token、-60% AI调用、62测试文件、727测试用例、39K行代码
- 缺口：暂无用户实际使用数据/案例
