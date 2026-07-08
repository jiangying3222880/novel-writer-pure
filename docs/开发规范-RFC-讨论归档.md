# 开发规范 & RFC 机制 — 讨论归档

> **作者**：GPT（分析方）→ 大弟子（执行方）  
> **归档时间**：2026-07-08 18:21 (GMT+8)  
> **状态**：采用，纳入后续开发流程  

---

## 一、核心判断

> **项目已进入"维护成本 ≥ 开发成本"阶段。**

以前加一个 Guide 很轻松。现在加一个 Knowledge，UI / Finder / Planner / Writer / Compiler / Migration / Export 全可能改。

**设计新模块时，不要问"功能是不是很强"，而是问：半年后我要改它，会影响几个模块？**

---

## 二、一个 Feature = 三个文件

每新增一个功能模块，必须同时产出：

```
xxx.py          # 实现
xxx_test.py     # 测试
xxx_demo.py     # 可跑通的 demo
```

Demo 的价值：半年后回来，跑一遍 demo 就知道当初的设计意图。

---

## 三、MVP 优先，拒绝过度设计

### 例子：剧情单元池

❌ 第一版就做（研究项目）：

```
├── 分类 / 标签 / 前置条件 / 后置状态
├── 冲突检测 / 可组合性 / AI评分
├── 推荐系统 / 图谱 / 权重
```

✅ 第一版只做（产品）：

```python
StoryUnitTemplate:
  id, title, description
  inputs, outputs
  tags, genre
  example
```

Planner 的用法只剩一个查询：`"成长" → 返回成长模板`。没有图搜索、没有 AI 排序、没有自动学习——这些以后都能加。

### 例子：Finder

❌ 第一版：Entity + Relation + Graph + Timeline + Compiler + Embedding + BM25

✅ **第一版：**
```python
finder.search("苏雪")
# → SearchResult(entity, score, references)
```

**第二版：** 加 `finder.related()`
**第三版：** 加 `finder.context()`
**Graph 最后。**

### 铁律

> **任何新功能，如果不能在两周内完成 MVP、不能独立测试、不能独立回滚，就暂时不进入主干。**

---

## 四、Knowledge Package 先于 Capability Library

不做巨大的 Capability Library。先做可安装的 Knowledge Package：

```
history_pack/
├── guide.md
├── prompt.md
├── facts.json
└── examples.md
```

Planner 加载。Writer 加载。Critic 加载。

以后 Capability 只是多个 Package 的组合。

---

## 五、Story OS ≠ Knowledge OS（强制分离）

```
Story OS                    Knowledge OS
Runtime:                    Capability Library:
  Guide                       Narrative / Dialogue / Character
  Decision                    Plot / Emotion / Publishing
  Event / Hook / Unit
  Memory / Finder / Compiler Domain Library:
                              历史 / 法律 / 医疗 / 军事

Unit Pool:                   Agents（最底层，只做组合调用）
  剧情模板 / 节奏模板           Writer / Planner / Critic
```

Guide 不保存技巧，只引用 Capability Knowledge。

Agent 在架构最底层——只是调用者，真正沉淀的是上层的 Runtime + Knowledge。

---

## 六、RFC 机制（我起草，主人拍板）

每新增一个功能，先写 RFC。

**RFC 模板（我写，主人审）：**

```markdown
# RFC-NNN: 功能名称

## 为什么需要？
一句话。

## 用户怎么看？
一张图 / 一个界面描述。

## Runtime 改什么？
不超过三条。

## UI 改什么？
不超过两条。

## 数据库改什么？
不超过一张表。

## 怎么测试？
不超过五条。
```

**流程：** 我想做 → 我写 RFC → 主人审 → 拍板 → 我实现。

---

## 七、长期原则

| 维度 | 原则 |
|------|------|
| 功能范围 | MVP 优先，两周交付 |
| 测试 | 新增功能必须有测试 |
| 可回滚 | 每个新功能必须能独立回滚 |
| 影响面 | 半年后改它，不能超过 3 个模块 |
| 知识 | 按 Capability 组织，不按 Agent 组织 |
| 范式 | 实现 + 测试 + demo 三个文件 |

---

*本规范即日起生效，作为后续所有新功能的准入标准。*
