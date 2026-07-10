# GPT 产品层分析 — 讨论归档

> **归档日期**：2026-07-09  
> **来源**：GPT 分析（基于主人上传的代码和截图，用户/架构师双视角）  
> **上下文**：此前已归档 3 份讨论（统一检索方案、知识组织方案、开发规范 RFC），此为第 4 份  

---

## 核心判断

> **Runtime 比 Workflow 完整，产品层没有完成。**

Story OS 底层（Guide/Decision/Memory/Hook/Compiler/Finder）已开始成熟，但用户面对的是"创建项目 → ？？？ → 写作"的断链。**用户体验的是 Workflow，不是 Runtime。**

---

## P0 — 必须先解决

### 1. 工作流断裂（当前最大问题）

```
项目设置 → ？？？ → 写作
```

各页面之间缺乏自然流转：
- 设定不能自然进入 Outline
- Outline 不能自然进入 Character  
- Character 不能自然进入 Create
- Create 不能自动获得 Context

用户感受：**"我不知道下一步应该点哪里。"**

### 2. UI/数据未形成闭环

- ✅ Story 页面保存了
- ❌ Create 页面没有
- ❌ Observe 页面没有
- ❌ Publish 页面没有

当前架构是 `Page → Page`（页面间跳转），而不是 `Project State → Page → Project State → Page`（统一状态驱动）。

所有页面应该：**只读 Project、只写 Project。**

### 3. Observe / Publish 占位

按钮能切换，但 Stack 没有接入。模块已设计，没有真正接进去。

---

## P1 — 下一阶段

### 4. Finder（统一检索）

是整个 v4.x 最大基础设施。Planner / Writer / Compiler / UI / Observe 都会用。应尽快统一入口。

### 5. 分卷编排

从 `Project → Chapter` 升级为 `Project → Volume → StoryUnit → Paragraph`。Story OS 需要这个层级。

### 6. 单元池（MVP）

第一版必须简单：id / title / description / inputs / outputs / tags / genre / example。**不要**图谱、推荐、学习、AI 排序。

---

## P2 — 以后

### Capability Library

坚持按能力（Capability）组织知识，而不是按 Agent。

### Domain Library

第一版用 Markdown + JSON 即可，不上数据库、不上 Embedding。

---

## 路线重新排序（GPT 建议）

| 阶段 | 目标 | 包含 |
|------|------|------|
| **第一** | 产品可用 | ✅ Story / Create / Observe / Publish 全部打通 |
| **第二** | 创作能力 | Volume / Unit Pool / Planner / Capability |
| **第三** | 知识能力 | Finder / Index / Domain Library / Recipe |
| **第四** | 高级能力 | Graph / Observe 增强 / Stress / G20 / G21 |

---

## 最终评分

| 维度 | 评分 | 依据 |
|------|------|------|
| 架构 | 9.5/10 | Runtime 成熟，模块边界清晰 |
| 工程 | 8.5/10 | 基础扎实，Finder 需统一 |
| 产品 | 6.5/10 | UI 有框架，但核心工作流未贯通 |

## 核心建议

> **不要再给 Story OS 加能力了，开始给用户加流程。**

如果一个用户第一次打开软件就能走通：
```
① 创建项目 → ② 导入设定 → ③ 自动生成卷规划
→ ④ 查看 Unit Pool → ⑤ 开始写 Unit
→ ⑥ Observe 检查 → ⑦ Publish 导出
```

项目完成度会一下子提升一个档次。

---

## 待合并

本归档待主人提供 **Gemini 意见** 后与其他来源综合，形成 v4.3 正式路线规划。
