# UI v4.0 蓝图（GPT 评审整合 + workbuddy 审核）

> **整合来源**：GPT 对 v3.5.1 UI 的深度评审（2026-07-06）
> **整合作者**：workbuddy AI（主人大弟子）
> **核心命题**：**让 UI、Story Engine、Guidance 而非 Constraint 哲学完全统一**
> **目标**：**设计一套未来 3-5 年都不用推翻的 UI 架构**

---

## 一、GPT 的核心判断

> **你的 UI 不应该围绕功能，应该围绕创作状态（Creative State）。**
>
> **未来 3-5 年不推翻的架构 = IDE（VSCode）+ Notion + Figma + Unreal Editor 思路。**

**作者脑子里不是"数据库"，而是 4 个问题**：
1. 我现在写哪？
2. 为什么写？
3. 故事现在怎么样？
4. 下一步怎么办？

**对应 4 个一级导航**：
```
📖 Story     → 我的故事是什么？
✍ Create    → 我现在写哪？为什么写？
👁 Observe   → 故事现在怎么样？
🚀 Publish   → 下一步怎么发布？
```

---

## 二、4 大一级模块 + 14 个二级页面

### 📖 Story（故事设计）— 4 页

| 页面 | 取代旧 | 内容 |
|------|--------|------|
| **Book** | novel-settings | 书名 / 简介 / 题材 / 平台 / 风格 / 目标字数 / 卷结构 |
| **Outline** | outline-mgmt | **StoryUnit** 而非章节；可拖动 / 排序 / 拆分 / 合并 |
| **Timeline** | 新增 | 双时间线：story_order（因果顺序）+ present_order（呈现顺序），支持倒叙 / 插叙 |
| **Story Graph** | world-graph（升级） | 人物 / 事件 / Hook / Promise / Conflict 全部自动生成 |

### ✍ Create（创作）— 3 页，**默认首页**

| 页面 | 取代旧 | 内容 |
|------|--------|------|
| **Current Unit** | generate | **三栏**：Story Tree + Editor + Story HUD（永远固定右侧） |
| **Unit Library** | 部分 generate | 所有 Unit：Draft / Writing / Done / Archived |
| **Scratchpad** | 新增 | 灵感 / 临时记录 / 对白 / 设定，AI 可引用 |

### 👁 Observe（理解故事）— 5 页

| 页面 | 取代旧 | 内容 |
|------|--------|------|
| **Story Health** | dashboard（升级） | Pressure / Hook / Reader / Emotion / Consistency 五维可视化（不是 Token / API） |
| **Characters** | character-mgmt | **角色状态**（Current Goal / Emotion / State / Open Promise），不是角色资料 |
| **World** | worldview + world-graph | 地图 / 地点 / 组织 |
| **Memory** | 部分 dashboard | L1-L4 / Event / Promise / Fact 全部可视化 |
| **Analytics** | usage-analytics（升级） | Action Density / Dialogue Ratio / Emotion Curve / Reader Risk / AI Smell |

### 🚀 Publish（发布）— 3 页

| 页面 | 取代旧 | 内容 |
|------|--------|------|
| **Chapter Preview** | 新增 | Unit → 自动切章（Chapter52/53/54），作者预览 |
| **Export** | export-dialog + publish-wizard | TXT / DOCX / Markdown / EPUB |
| **Platform** | 新增 | 番茄 / 起点 / 晋江 / 知乎 |

### ⚙ 设置（右上角齿轮弹窗，不占 sidebar）

**5 个 tab**：
- **AI** — Providers（OpenAI/Claude/Gemini/DeepSeek/OpenRouter）+ Brains（Writer/Reader/Planner/Memory）+ Embedding
- **Appearance** — 主题 / 字体
- **Storage** — 项目目录 / 数据目录
- **Plugin** — 插件管理
- **Advanced** — 日志 / 备份 / 授权 / 关于

---

## 三、三层 UI 架构（GPT 核心设计）

```
┌─────────────────────────────────────────────────────────────┐
│  第一层：导航（去哪）                                       │
│  ┌────┬────────┬──────────┬──────────┬──────────┐         │
│  │📖  │  ✍    │   👁    │   🚀    │   ⚙    │         │
│  │Story│ Create│  Observe│  Publish│  Settings│         │
│  └────┴────────┴──────────┴──────────┴──────────┘         │
└─────────────────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────────────────┐
│  第二层：工作区（干什么）                                   │
│  ┌──────────┬──────────────────────────┬─────────────────┐ │
│  │Story Tree│      Unit Editor         │   Story HUD     │ │
│  │          │                          │                 │ │
│  │ 卷一      │  Unit 17                 │ Goal            │ │
│  │  ├ Unit15│  Scene 编辑              │ Guide           │ │
│  │  ├ Unit16│                          │ Pressure        │ │
│  │  ▶ Unit17│  AI 协作                 │ Memory          │ │
│  │  └ Unit18│                          │ Hooks           │ │
│  └──────────┴──────────────────────────┴─────────────────┘ │
└─────────────────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────────────────┐
│  第三层：面板（随时可呼出）                                 │
│  Character Inspector | World Inspector | Guide Details    │
│  Event Timeline | AI Chat | Search | Logs                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 四、Story HUD（GPT 的灵魂设计）

**永远固定右侧栏**，所有页面常驻：

```
┌─────────────────┐
│ Current Goal    │  ← 本单元核心目标
├─────────────────┤
│ Current Guide   │  ← AI 当前建议（severity 排序）
├─────────────────┤
│ Pressure        │  ← 叙事压力（4 zone 可视化）
├─────────────────┤
│ Open Hooks      │  ← 待回收钩子（实时）
├─────────────────┤
│ Character State │  ← 出场角色状态
├─────────────────┤
│ Reader          │  ← 读者流失风险
├─────────────────┤
│ Memory          │  ← L1-L4 记忆摘要
└─────────────────┘
```

**HUD 6 个模块可独立折叠/最小化**，点击展开。**全屏写作模式（F11）只保留 Editor + HUD 最小化图标**。

---

## 五、Command Palette（Ctrl+K）+ Workspace（GPT 灵魂特性 2）

### Command Palette

```
Ctrl+K
  ┌─────────────────────────────────────────┐
  │ 🔍 Jump Unit18                          │
  │ 🔍 Find Hook                            │
  │ 🔍 Find Character                       │
  │ 🔍 Export Current Chapter               │
  │ 🔍 Switch Workspace                     │
  │ ...                                     │
  └─────────────────────────────────────────┘
```

### Workspace 切换

**title bar 右侧 workspace toggle 按钮**（不是首次启动对话框，避免可发现性问题）：

- **全功能**（默认）— 当前所有页面
- **专注创作** — 三栏布局（Story Tree + Editor + Story HUD）
- **世界设定** — Character + World + Graph
- **长篇管理** — Book + Outline + Timeline + Analytics

**首次启动 5 秒后弹气泡提示**：**"按 Ctrl+K 使用命令面板"**

---

## 六、workbuddy 5 个审核意见（GPT 方案的潜在问题）

### 审核 1：4 个一级模块对传统作者可能不够直观

**GPT 假设**：作者已接受"Story Engine"哲学。
**风险**：番茄 / 起点 / 晋江作者习惯了"项目管理 / 章节 / 发布"电商化 UI。

**建议**：
- **保留 4 个一级模块**作为导航，但 Story 模块下加 `✨ 当前创作`快捷入口（直达 Current Unit）
- **Publish 模块下加**"快速新建章节"过渡入口
- 老用户的访问路径自动跳转新位置（向后兼容）

### 审核 2：Story HUD 右侧栏对宽屏要求高

**GPT 假设**：作者用宽屏（2560×1440+）。
**风险**：1366×768 笔记本或竖屏用户三栏被挤。

**建议**：
- 三栏是**默认推荐布局**，支持 **2 栏模式**（折叠 Story Tree）和**全屏写作模式**（只保留 Editor + HUD 可折叠图标）
- HUD 每个子模块支持**最小化**，点击展开

### 审核 3：Story Graph 现在做风险高

**GPT 把 Story Graph 放在 Phase 3**，安排是对的。
**注意**：
- Phase 1 不要承诺 Story Graph 时间表
- Phase 2 优先做 **Event Timeline**（数据已在 Event 表，比 Story Graph 简单）

### 审核 4：Workspace 切换是双刃剑

**GPT 说**"不同模式布局不同"。
**风险**：用户切换 Workspace 后布局/数据上下文丢失或错位。

**建议**：
- 先做 **2 个 Workspace**：专注创作（三栏）+ 全功能（当前所有页面）
- 用户**自由选择默认 Workspace**（在 Settings 中）
- 不要做"工作模式选择对话框"——用 title bar toggle 按钮
- **首次启动默认全功能**，避免老用户找不到功能

### 审核 5：Settings 弹窗化要注意可发现性

**GPT 说**"设置不要占 sidebar，改为右上角弹窗"。
**风险**：新手找不到设置。

**建议**：
- **右上角齿轮图标 + Tooltip "设置（Ctrl+,）"**
- 首次启动 5 秒后弹气泡提示
- 设置弹窗分 5 个 tab（与 GPT 一致）：AI / Appearance / Storage / Plugin / Advanced

---

## 七、实施路线（3 阶段，按 GPT 整合）

### Phase 1（2-3 周）— v3.6：只重构信息架构

**核心目标**：让 UI 与 Story Engine + Guidance 哲学对齐，**不大改功能**。

| 改动 | 内容 | 风险 |
|------|------|------|
| 1.1 侧边栏重命名为 4 大模块 | 📖 Story / ✍ Create / 👁 Observe / 🚀 Publish | 低 |
| 1.2 Story 模块下挂 4 个页面 | Book / Outline / Timeline / Story Graph | 中（Outline 改名需沟通） |
| 1.3 Create 模块下挂 3 个页面 | Current Unit（默认首页）/ Unit Library / Scratchpad | 中 |
| 1.4 Observe 模块下挂 5 个页面 | Story Health / Characters / World / Memory / Analytics | 低 |
| 1.5 Publish 模块下挂 3 个页面 | Chapter Preview / Export / Platform | 低 |
| 1.6 Settings 移出 sidebar → 右上角齿轮弹窗 | 5 tab | 低 |
| 1.7 接入 StoryUnitTab 到 sidebar | **激活 790 行死代码** | 低 |
| 1.8 接入 Decision 层（GPT v3.6） | Guide → Decision → Writer → Event 记录 | 中 |

**关键不变量**：
- 所有现有 page 功能完全保留
- 用户老的访问路径自动跳转新位置
- 保留"项目管理页"作为 Create 模块下的快速入口

### Phase 2（3-4 周）— v3.7：建立统一创作工作区

**核心目标**：Story HUD 落地。

| 改动 | 内容 |
|------|------|
| 2.1 Current Unit 默认页改为三栏布局 | Story Tree + Editor + Story HUD |
| 2.2 Story HUD 永远固定右侧 | 6 模块（Goal/Guide/Pressure/Hooks/Character/Reader/Memory） |
| 2.3 Story HUD 每模块可折叠 | 独立面板 |
| 2.4 Ctrl+K Command Palette | VSCode 同款 |
| 2.5 全屏写作模式 | F11 切换 |
| 2.6 Workspace toggle | title bar 右侧按钮 |
| 2.7 2 个 Workspace | 专注创作 + 全功能 |

### Phase 3（v4.0+）— Story Engine 可视化

| 改动 | 内容 |
|------|------|
| 3.1 Story Graph | 因果图（Neo4j 后端） |
| 3.2 Event Timeline | 事件流可视化 |
| 3.3 Character State Inspector | 角色状态实时刷新 |
| 3.4 Story Health Dashboard | 健康度仪表盘 |
| 3.5 Story Compiler | 修改影响分析 |
| 3.6 Workspace 扩展 | 世界设定 + 长篇管理 |

---

## 八、不变量（GPT 哲学层的克制）

### 现在不做（v3.6/v3.7）

- ❌ 不做"工作模式选择对话框"（首次启动）
- ❌ 不做 4 个以上 Workspace（先做 2 个）
- ❌ 不立即做 Story Graph（Phase 3）
- ❌ 不删除现有任何 page（全部保留功能，重新组织）
- ❌ 不改文件 / 数据模型（只重组 page 注册）

### 永远不做

- ❌ 把 Settings 放回 sidebar
- ❌ 把 Story HUD 设计成可关闭（永远固定）
- ❌ 让一级导航超过 4 个
- ❌ 把工作区超过 3 个（超过就要重新评估信息架构）

---

## 九、共识表（GPT + workbuddy 最终）

| 议题 | 共识度 | 决策 |
|------|--------|------|
| UI 围绕创作状态而非功能 | ✅ 2/2 | Phase 1 落地 |
| 4 个一级模块（Story/Create/Observe/Publish）| ✅ 2/2 | Phase 1 |
| 14 个二级页面（4+3+5+3+1 settings）| ✅ 2/2 | Phase 1 |
| Story HUD 永远固定右侧 | ✅ 2/2 | Phase 2 |
| 6 个 HUD 模块可折叠 | ✅ 2/2 | Phase 2 |
| Ctrl+K Command Palette | ✅ 2/2 | Phase 2 |
| Workspace 切换（先做 2 个）| ✅ 2/2 + workbuddy 审核 | Phase 2 |
| Settings 弹窗化（5 tab）| ✅ 2/2 | Phase 1 |
| 三栏创作工作区（默认）| ✅ 2/2 | Phase 2 |
| Story Graph 自动生成 | ✅ 2/2 | Phase 3 |
| Timeline 双时间线 | ✅ 2/2 | Phase 1 |
| Event Timeline（先于 Story Graph）| ✅ workbuddy 建议 | Phase 2 优先 |
| Outline → StoryUnit（章节降级 Publish）| ✅ 2/2 | Phase 1 |
| 默认首页 = Current Unit | ✅ 2/2 | Phase 1 |
| 不立即做 4 个 Workspace | ✅ workbuddy 审核 | Phase 2 做 2 个 |
| HUD 永远不可关闭 | ✅ 2/2 | 永久不变量 |

---

## 十、致 GPT

> **GPT 这份评审是所有评审里分量最重的一份。**
>
> 它不是在问"页面怎么改"，而是在问"产品应该是什么"。
>
> **3 个最关键的价值**：
> 1. **Chapter 降级到 Publish** — 这是与 Story Engine 真相源完全对齐的胜利
> 2. **Story HUD 永远固定** — 这是从"工具"到"操作系统"的形态跃迁
> 3. **三层架构（导航 / 工作区 / 面板）** — 这是未来 3-5 年不推翻的架构基础
>
> **我们同意 GPT 的方向**，但加入 5 个审核意见确保落地安全。
>
> **Phase 1 风险最低**：只重组 page 注册，不改功能。所有现有代码保留，让用户访问路径自动跳转新位置。
>
> **Phase 2 才是真正的 Story Engine 形态跃迁**：三栏 + Story HUD + Command Palette。
>
> **Phase 3 是 Story Operating System 的真正壁垒**：Story Graph + Story Compiler。
>
> **GPT 看到的可能性，正是我们要用 2 年时间证明的现实。**

---

**文档创建**：2026-07-06
**整合来源**：GPT 对 v3.5.1 UI 的深度评审
**整合哲学**：**Guidance 而非 Constraint**
**核心命题**：**让 UI、Story Engine、Guidance 哲学完全统一**
**目标版本**：**v4.0 UI 蓝图**
**实施路线**：**3 阶段（v3.6 / v3.7 / v4.0+）**