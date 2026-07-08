# PPT Outline

## Overview
本 PPT 面向技术评审与产品展示场景，介绍 novel-writer-pure —— 一款 AI 驱动的网文写作桌面工具（v3.1.0）。PPT 以"范式革命"为主线，从产品概览出发，深入核心技术（引导性写作范式 → 三阶段工作流 → 四大引导元素），再到架构设计与插件生态，最后以演化路径和未来规划收尾。整体采用科技风（Tech Style），呈现工程深度与产品创新。

## Outline Content

## Page 1: 封面
- **Page Type**: Cover
- **Page Title**: novel-writer-pure
- **Page Subtitle**: AI 驱动的网文写作桌面工具 · v3.1.0
- **Content Structure**:
  - 主标题：novel-writer-pure
  - 副标题：AI 驱动的网文写作桌面工具
  - 版本标签：v3.1.0 · MIT License
  - 技术标签：Python 3.12 · PyQt6 · 微内核架构

## Page 2: 目录
- **Page Type**: TOC
- **Page Title**: 目录
- **Content Structure**:
  1. 项目概览
  2. 核心范式 — 引导性写作
  3. 三阶段工作流
  4. 四大引导元素
  5. 技术架构
  6. 插件生态
  7. 演化路径 & 未来规划

## Page 3: 章节转换 — 项目概览
- **Page Type**: Transition
- **Page Title**: 01 · 项目概览
- **Content Structure**: 章节编号：01，章节标题：项目概览，副标题：What is novel-writer-pure?

## Page 4: 项目概览
- **Page Type**: Content
- **Page Title**: 这是什么？
- **Content Structure**:
  - 核心定位：AI 驱动的网文写作桌面工具
  - 四格数据：~39K 行代码 / 84 源文件 727 测试 / 9 个内置插件 / MIT 开源
  - 技术栈：Python 3.12 + PyQt6 + SQLite + OpenAI-compatible API
  - 核心理念：让 AI 写出有文学质感的作品

## Page 5: 章节转换 — 核心范式
- **Page Type**: Transition
- **Page Title**: 02 · 核心范式
- **Content Structure**: 章节编号：02，章节标题：引导性写作范式，副标题：从"防御"到"引导"的范式革命

## Page 6: 防御性 vs 引导性范式对比
- **Page Type**: Content
- **Page Title**: 范式革命：防御 → 引导
- **Content Structure**:
  - 左侧（2.0 防御性）：禁止项清单 / LLM 修补 LLM / ~50K token/章 / 5-7 次 AI 调用
  - 右侧（3.0 引导性）：潜文本卡+声音档案+风格指纹+反规则 / 自评+作者决定 / ~12-15K token/章 / 2 次 AI 调用

## Page 7: 章节转换 — 三阶段工作流
- **Page Type**: Transition
- **Page Title**: 03 · 三阶段工作流
- **Content Structure**: 章节编号：03，章节标题：三阶段工作流，副标题：Write → Self-Critique → Persist

## Page 8: 三阶段工作流详解
- **Page Type**: Content
- **Page Title**: Write → Self-Critique → Persist
- **Content Structure**:
  - Step 1 Write（1 次 LLM，~8-10K token）
  - Step 2 Self-Critique（1 次 LLM，~4-5K token，7 问自评）
  - Step 3 Persist（0 token，6 个验证器）
  - 对比：总 token ~12-15K / 总 AI 调用 2 次 / 效率提升 70%

## Page 9: v3.1 动态阶段模式
- **Page Type**: Content
- **Page Title**: v3.1 动态阶段模式
- **Content Structure**:
  - 模式 A（11章后）：Write → Self-Critique → Persist（3 槽位）
  - 模式 B（前10章）：Write → USER_CONFIRM → Self-Critique → Persist（4 槽位）
  - 模式 C（多版本）：Write → SELECT_VERSION → USER_CONFIRM → Self-Critique → Persist（5 槽位）
  - Self-Critique 升级：4 问 → 7 问（+3 品味维度）

## Page 10: 章节转换 — 四大引导元素
- **Page Type**: Transition
- **Page Title**: 04 · 四大引导元素
- **Content Structure**: 章节编号：04，章节标题：四大引导元素，副标题：SceneContext 的核心构成

## Page 11: SceneContext 四大引导元素
- **Page Type**: Content
- **Page Title**: SceneContext 四大引导元素
- **Content Structure**:
  - 潜文本卡：表面事件/真实意图/谎/真/物理锚点
  - 角色声音档案：句法+词汇+决策+关系指纹
  - 作者风格指纹：pace/density/lyricism 三轴 + 自动学习器
  - 反规则系统：在 Y 范围内允许打破 X

## Page 12: 章节转换 — 技术架构
- **Page Type**: Transition
- **Page Title**: 05 · 技术架构
- **Content Structure**: 章节编号：05，章节标题：技术架构，副标题：微内核 + 插件化 · 企业级设计

## Page 13: 微内核 + 插件化架构
- **Page Type**: Content
- **Page Title**: 微内核 + 插件化架构
- **Content Structure**:
  - 微内核层：Container IoC + EventBus + PluginManager
  - 业务层：AI 引擎 + 工作流 + 记忆 + RAG + 知识库
  - 插件层：9 个热插拔插件
  - 安全特性：API Key / License Fernet 加密，HMAC 签名

## Page 14: 6 个本地验证器（0 Token）
- **Page Type**: Content
- **Page Title**: 6 个本地验证器（0 Token）
- **Content Structure**:
  - POV 验证器 / 空间验证器 / 声音验证器 / 设定覆盖率 / 重复检测 / 物品承诺校验
  - 统一接口：ValidationResult（passed/flags/details）

## Page 15: 章节转换 — 插件生态
- **Page Type**: Transition
- **Page Title**: 06 · 插件生态
- **Content Structure**: 章节编号：06，章节标题：插件生态，副标题：9 个内置插件 · 热插拔设计

## Page 16: 9 个内置插件
- **Page Type**: Content
- **Page Title**: 9 个内置插件
- **Content Structure**:
  - 实体图谱 / 内置知识库 / 用户知识库 / 默认提示词 / Edge TTS / 用量分析 / AI 大纲生成 / AI 导入 / 剧情推演

## Page 17: 章节转换 — 演化路径
- **Page Type**: Transition
- **Page Title**: 07 · 演化路径 & 未来规划
- **Content Structure**: 章节编号：07，章节标题：演化路径 & 未来规划，副标题：从技能脚本到企业级写作工具

## Page 18: 演化路径
- **Page Type**: Content
- **Page Title**: 演化路径
- **Content Structure**:
  - 时间轴：v0.x → v1.0（05-17）→ v2.0（05-22）→ v3.0（06-05）→ v3.1（06-05）
  - 关键指标变化：token -70%，AI调用 -60%

## Page 19: 未来规划
- **Page Type**: Content
- **Page Title**: 未来规划
- **Content Structure**:
  - 近期 v3.2：UI 全面重构 + 零文档启动
  - 中期 E1-E12：高级叙事技巧全落地
  - 长期：RAG 精度提升 + 长篇处理优化

## Page 20: 结束页
- **Page Type**: Ending
- **Page Title**: novel-writer-pure
- **Content Structure**:
  - 主标题：novel-writer-pure
  - 副标题：让 AI 写出有文学质感的作品
  - MIT License · Python 3.12 + PyQt6 · v3.1.0

## Design Style
科技风（Tech Style）。主色调：深蓝 + 紫色渐变，体现 AI 科技感。字体：Noto Sans SC（中文）+ Montserrat（英文/数字）。背景：深色调（#0f0f1a），卡片使用半透明深色底，强调色：#6366f1（紫蓝渐变）和 #06b6d4（青色）。整体风格参考现代 AI 开发工具 UI 设计，简洁、有技术感、无过度装饰。
