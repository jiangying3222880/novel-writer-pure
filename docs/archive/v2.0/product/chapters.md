# Chapters Plan: novel-writer-pure 项目介绍 PPT

---

## Page 1: 封面
- **Page Type**: Cover
- **Page Title**: novel-writer-pure
- **Page Subtitle**: AI 驱动的网文写作桌面工具 · v3.1.0
- **Selected Template**: (留空)

- **Content Structure**:
  - 主标题：novel-writer-pure
  - 副标题：AI 驱动的网文写作桌面工具
  - 版本标签：v3.1.0 · MIT License
  - 技术标签：Python 3.12 · PyQt6 · 微内核架构

- **Content Density**: Light
- **Narrative Role**: 建立产品品牌形象，传达技术专业感
- **Image Requirements**: 无
- **Page Weight**: Core page

---

## Page 2: 目录
- **Page Type**: TOC
- **Page Title**: 目录
- **Selected Template**: (留空)

- **Content Structure**:
  1. 项目概览
  2. 核心范式 — 引导性写作
  3. 三阶段工作流
  4. 四大引导元素
  5. 技术架构
  6. 插件生态
  7. 演化路径 & 未来规划

- **Content Density**: Light
- **Narrative Role**: 导航全篇章节，建立认知框架
- **Image Requirements**: 无
- **Page Weight**: Secondary page

---

## Page 3: 章节转换 — 项目概览
- **Page Type**: Transition
- **Page Title**: 01 · 项目概览
- **Selected Template**: (留空)

- **Content Structure**:
  - 章节编号：01
  - 章节标题：项目概览
  - 副标题：What is novel-writer-pure?

- **Content Density**: Light
- **Narrative Role**: 引入第一章节，建立认知锚点
- **Image Requirements**: 无
- **Page Weight**: Secondary page

---

## Page 4: 项目概览
- **Page Type**: Content
- **Page Title**: 这是什么？
- **Selected Template**: (留空)

- **Content Structure**:
  - 核心定位：AI 驱动的网文写作桌面工具，把传统"防御性 Prompt 工程"升级为"引导性写作范式"
  - 关键指标四格：
    - ~39K 行代码（app 22K + ui 17K）
    - 84 个源文件 · 727 个测试
    - 9 个内置插件（热插拔）
    - MIT 开源 · Windows 桌面端
  - 技术栈：Python 3.12 + PyQt6 + SQLite + OpenAI-compatible API
  - 核心理念：让 AI 写出"有文学质感"的作品，而不是符合规则却毫无灵气的文字

- **Content Density**: Medium
- **Narrative Role**: 快速建立产品认知，数据增强可信度
- **Image Requirements**: 无
- **Page Weight**: Core page

---

## Page 5: 章节转换 — 核心范式
- **Page Type**: Transition
- **Page Title**: 02 · 核心范式
- **Selected Template**: (留空)

- **Content Structure**:
  - 章节编号：02
  - 章节标题：引导性写作范式
  - 副标题：从"防御"到"引导"的范式革命

- **Content Density**: Light
- **Narrative Role**: 引入最核心的设计哲学差异
- **Image Requirements**: 无
- **Page Weight**: Secondary page

---

## Page 6: 防御性 vs 引导性范式对比
- **Page Type**: Content
- **Page Title**: 范式革命：防御 → 引导
- **Selected Template**: (留空)

- **Content Structure**:
  - 左侧（2.0 防御性）：
    - 禁止项清单 + 20 维度扣分
    - LLM 修补 LLM
    - ~50K token/章
    - 5-7 次 AI 调用
    - 结果：AI 阻力大、质量不稳定
  - 右侧（3.0 引导性）：
    - 潜文本卡 + 声音档案 + 风格指纹 + 反规则
    - 自评 + 作者决定
    - ~12-15K token/章（节省 70%）
    - 仅 2 次 AI 调用
    - 结果：AI 更自由、质量更稳定

- **Content Density**: Medium
- **Narrative Role**: 核心差异化优势，是整个 PPT 最有说服力的对比
- **Image Requirements**: 无
- **Page Weight**: Core page

---

## Page 7: 章节转换 — 三阶段工作流
- **Page Type**: Transition
- **Page Title**: 03 · 三阶段工作流
- **Selected Template**: (留空)

- **Content Structure**:
  - 章节编号：03
  - 章节标题：三阶段工作流
  - 副标题：Write → Self-Critique → Persist

- **Content Density**: Light
- **Narrative Role**: 承接范式对比，进入具体实现
- **Image Requirements**: 无
- **Page Weight**: Secondary page

---

## Page 8: 三阶段工作流详解
- **Page Type**: Content
- **Page Title**: Write → Self-Critique → Persist
- **Selected Template**: (留空)

- **Content Structure**:
  - 三步流程卡片：
    - Step 1 Write（1 次 LLM，~8-10K token）：接收 SceneContext 四大引导元素，生成章节正文初稿
    - Step 2 Self-Critique（1 次 LLM，~4-5K token）：7 问自评（技术 4 问 + 品味 3 问），不调修补 LLM
    - Step 3 Persist（0 token，本地）：6 个确定性验证器 + 跨章一致性检查 + 落库
  - 底部数据对比：
    - 总 token：~12-15K/章（vs 旧版 ~50K）
    - 总 AI 调用：2 次（vs 旧版 5-7 次）
    - 效率提升：70%

- **Content Density**: Medium
- **Narrative Role**: 核心实现路径，展示技术深度
- **Image Requirements**: 无
- **Page Weight**: Core page

---

## Page 9: 3.1 增强 — 动态阶段模式
- **Page Type**: Content
- **Page Title**: v3.1 动态阶段模式
- **Selected Template**: (留空)

- **Content Structure**:
  - 副标题：根据章节号 & 配置动态调整，3 到 5 个阶段
  - 三种模式：
    - 模式 A（第 11 章后）：Write → Self-Critique → Persist（3 槽位）
    - 模式 B（前 10 章）：Write → USER_CONFIRM → Self-Critique → Persist（4 槽位）
    - 模式 C（多版本）：Write → SELECT_VERSION → USER_CONFIRM → Self-Critique → Persist（5 槽位）
  - Self-Critique 升级：原 4 问技术合规 → 扩展为 7 问（+3 品味：吸引力/不出戏/情绪共鸣）
  - 技术分 < 60 阻断重写，品味分 < 60 黄色提示

- **Content Density**: Medium
- **Narrative Role**: 展示 3.1 版本的智能化升级，差异化卖点
- **Image Requirements**: 无
- **Page Weight**: Core page

---

## Page 10: 章节转换 — 四大引导元素
- **Page Type**: Transition
- **Page Title**: 04 · 四大引导元素
- **Selected Template**: (留空)

- **Content Structure**:
  - 章节编号：04
  - 章节标题：四大引导元素
  - 副标题：SceneContext 的核心构成

- **Content Density**: Light
- **Narrative Role**: 引入 SceneContext 的具体构成
- **Image Requirements**: 无
- **Page Weight**: Secondary page

---

## Page 11: 四大引导元素
- **Page Type**: Content
- **Page Title**: SceneContext 四大引导元素
- **Selected Template**: (留空)

- **Content Structure**:
  - 四格卡片布局：
    - 🎭 潜文本卡（subtext_card.py）：表面事件 / 真实意图 / 谎 / 真 / 物理锚点。引导 AI 写出有深度的潜台词与肢体语言，而非空洞对话
    - 🎤 角色声音档案（voice_profile.py）：句法 + 词汇 + 决策 + 关系指纹。彻底解决"性格：怂"关键词导致的 AI 脸谱化角色问题
    - ✍️ 作者风格指纹（style_fingerprint.py）：pace / density / lyricism 三轴评估 + 自动增量学习器 + 漂移检测，保持全篇风格统一
    - ⚡ 反规则系统（anti_rule.py）："在 Y 范围内允许打破 X"，赋予 AI 创作自由度，避免写作僵化

- **Content Density**: Medium
- **Narrative Role**: 核心技术创新点，PPT 中最有深度的内容
- **Image Requirements**: 无
- **Page Weight**: Core page

---

## Page 12: 章节转换 — 技术架构
- **Page Type**: Transition
- **Page Title**: 05 · 技术架构
- **Selected Template**: (留空)

- **Content Structure**:
  - 章节编号：05
  - 章节标题：技术架构
  - 副标题：微内核 + 插件化 · 企业级设计

- **Content Density**: Light
- **Narrative Role**: 引入架构章节，建立技术可信度
- **Image Requirements**: 无
- **Page Weight**: Secondary page

---

## Page 13: 微内核架构
- **Page Type**: Content
- **Page Title**: 微内核 + 插件化架构
- **Selected Template**: (留空)

- **Content Structure**:
  - 三层架构说明：
    - 微内核层（Container IoC + EventBus + PluginManager）：依赖注入容器，插件间通过事件总线通信，禁止直接导入
    - 业务层（AI 引擎 + 工作流 + 记忆 + RAG + 知识库）：核心写作逻辑，接收微内核服务注入
    - 插件层（9 个热插拔插件）：独立开发、独立部署，通过 EventBus 与系统通信
  - 关键设计原则：
    - 插件间禁止直接导入，全部通过 EventBus 通信
    - 服务通过 Container 注入，禁止硬编码实例化
    - 配置优先级：环境变量 > 用户 YAML > 默认配置
  - 安全特性：API Key / License 均 Fernet 加密存储，HMAC 签名验证

- **Content Density**: Medium
- **Narrative Role**: 展示工程化深度，区别于简单脚本工具
- **Image Requirements**: 无
- **Page Weight**: Core page

---

## Page 14: 6 个本地验证器
- **Page Type**: Content
- **Page Title**: 6 个本地验证器（0 Token）
- **Selected Template**: (留空)

- **Content Structure**:
  - 副标题：0 token 消耗，纯确定性逻辑，保证写作质量底线
  - 六格列表：
    - 👁️ POV 验证器：人称占比检测，防止视角漂移（默认第一人称 > 90%）
    - 🗺️ 空间验证器：方向/位置一致性校验，防止场景描述矛盾
    - 🎤 声音验证器：角色说话风格一致性，防止角色声音漂移
    - 📚 设定覆盖率：核心设定 + 活跃伏笔不丢失（10 章后遗忘检测）
    - 🔁 重复检测：句首词频/整句重复/三连短句检测
    - 📦 物品/承诺校验：物品一致性 + 承诺追踪（Chekhov's Gun）
  - 统一接口：ValidationResult（passed/flags/details），仅警告不阻断

- **Content Density**: Heavy
- **Narrative Role**: 展示质量保证体系，0 token 是核心卖点
- **Image Requirements**: 无
- **Page Weight**: Core page

---

## Page 15: 章节转换 — 插件生态
- **Page Type**: Transition
- **Page Title**: 06 · 插件生态
- **Selected Template**: (留空)

- **Content Structure**:
  - 章节编号：06
  - 章节标题：插件生态
  - 副标题：9 个内置插件 · 热插拔设计

- **Content Density**: Light
- **Narrative Role**: 引入插件章节，展示系统的可扩展性
- **Image Requirements**: 无
- **Page Weight**: Secondary page

---

## Page 16: 插件生态全景
- **Page Type**: Content
- **Page Title**: 9 个内置插件
- **Selected Template**: (留空)

- **Content Structure**:
  - 网格布局，9 个插件卡片：
    - 🕸️ 实体图谱：角色/伏笔/地点关系图谱可视化
    - 📖 内置知识库：6 类别 × 9 题材矩阵写作知识文档
    - 📁 用户知识库：自定义知识库导入与管理
    - 📝 默认提示词：Prompt 模板管理
    - 🔊 Edge TTS：微软 Edge 语音朗读
    - 📊 用量分析：AI 调用统计与月限额追踪
    - 🗂️ AI 大纲生成：AI 智能生成大纲（零文档启动基础）
    - 🤖 AI 导入：智能解析导入各种格式文档（角色/章节/世界观/伏笔）
    - 🎭 剧情推演：AI 辅助推演剧情走向

- **Content Density**: Heavy
- **Narrative Role**: 展示生态完整性和功能覆盖广度
- **Image Requirements**: 无
- **Page Weight**: Core page

---

## Page 17: 章节转换 — 演化路径 & 未来
- **Page Type**: Transition
- **Page Title**: 07 · 演化路径 & 未来规划
- **Selected Template**: (留空)

- **Content Structure**:
  - 章节编号：07
  - 章节标题：演化路径 & 未来规划
  - 副标题：从技能脚本到企业级写作工具

- **Content Density**: Light
- **Narrative Role**: 引入历史与未来，展示项目生命力
- **Image Requirements**: 无
- **Page Weight**: Secondary page

---

## Page 18: 演化时间轴
- **Page Type**: Content
- **Page Title**: 演化路径
- **Selected Template**: (留空)

- **Content Structure**:
  - 横向时间轴（5 节点）：
    - v0.x：写作技能 jy-v5.4，探索期，单文件脚本
    - v1.0（05-17）：8 步单步工作流，~50K token/章，5-7 次 AI 调用
    - v2.0（05-22）：7 步插件化，引入微内核架构，防御性范式
    - v3.0（06-05）：三阶段引导范式，token -70%，AI 调用 -60%
    - v3.1（06-05）：品味评分 + 多版本 + 用户确认，3-5 动态阶段
  - 关键转折点说明：v2.0→v3.0 是最大范式革命（防御→引导）

- **Content Density**: Medium
- **Narrative Role**: 展示项目快速迭代能力和技术演进决心
- **Image Requirements**: 无
- **Page Weight**: Core page

---

## Page 19: 未来规划
- **Page Type**: Content
- **Page Title**: 未来规划
- **Selected Template**: (留空)

- **Content Structure**:
  - 近期（v3.2，进行中）：
    - UI 全面重构：1:1 复刻 Web 端设计，ScaledContainer 矢量缩放，全平台自适应
    - 零文档启动：3 轮渐进对话引导替代 6 字段表单，用户门槛大幅降低
  - 中期（E1-E12 增强全落地）：
    - 情感衰减（E7）、节奏呼吸（E8）、信息差管理（E9）等高级叙事技巧
    - E12 跨章一致性补全（ROI 最高优先级）
  - 长期：
    - RAG 精度持续提升
    - 实际 token 用量追踪服务
    - 长篇处理能力优化（超长上下文管理）

- **Content Density**: Medium
- **Narrative Role**: 展示项目的长期价值和持续演进路线图
- **Image Requirements**: 无
- **Page Weight**: Core page

---

## Page 20: 结束页
- **Page Type**: Ending
- **Page Title**: novel-writer-pure
- **Selected Template**: (留空)

- **Content Structure**:
  - 主标题：novel-writer-pure
  - 副标题：让 AI 写出有文学质感的作品
  - GitHub 标签：MIT License · Python 3.12 + PyQt6
  - 底部标语：引导性写作范式 · 微内核 + 插件架构 · 0 token 验证器
  - 版本：v3.1.0

- **Content Density**: Light
- **Narrative Role**: 结束收尾，强化品牌记忆
- **Image Requirements**: 无
- **Page Weight**: Secondary page
