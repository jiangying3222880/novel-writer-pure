# v3.5.2 Story Guidance System 验证报告

**日期**：2026-07-06
**验证脚本**：[v3_5_2_validation.py](../../smoke/v3_5_2_validation.py)
**结果**：✅ **50/50 全部通过**

---

## 验证范围

按 v5 计划的 v3.5.2 任务：

| # | 任务 | 文件 | 状态 |
|---|------|------|------|
| 1 | Guide dataclass 升级到 7 字段 | [types.py](../../app/core/types.py) | ✅ |
| 2 | Hook 模块返回 Guide | [unit_hook_service.py](../../app/services/unit_hook_service.py) | ✅ |
| 3 | Memory 模块返回 Guide | [memory.py](../../app/services/memory.py) | ✅ |
| 4 | Pressure 模块返回 Guide（4 维度）| [pressure.py](../../app/services/pressure.py) | ✅ |
| 5 | Voice 模块返回 Guide | [voice_profile.py](../../app/services/voice_profile.py) | ✅ |
| 6 | Style 模块返回 Guide | [style_fingerprint.py](../../app/services/style_fingerprint.py) | ✅ |
| 7 | Orchestrator 按 priority 排序 | [orchestrator.py](../../app/agents/orchestrator.py)（已自动排序）| ✅ |
| 8 | 低 confidence Guide UI 标灰 | [_guide_panel.py](../../app/ui/widgets/_guide_panel.py) | ✅ |
| 9 | collect_guides() 接入所有模块 | [types.py](../../app/core/types.py) | ✅ |

---

## 详细验证结果

### 1. Guide 7 字段（17/17 ✅）

**字段完整性**：
- [OK] 7 字段全部可设
- [OK] priority=0.85
- [OK] confidence=0.9
- [OK] scope=Unit
- [OK] reason="已埋 30 章"
- [OK] evidence_ids 含 2 条
- [OK] possible_actions 含 2 个 Action
- [OK] to_prompt_block 含 scope=Unit
- [OK] to_prompt_block 含 confidence=0.90
- [OK] to_prompt_block 含"理由"

**向后兼容**：
- [OK] severity→priority 自动同步
- [OK] priority→severity 自动同步
- [OK] 无效 scope 自动降级为 Unit
- [OK] priority > 1.0 裁剪到 1.0
- [OK] confidence < 0.0 裁剪到 0.0
- [OK] 低 confidence 自动加 `[AI 不太确定, 可忽略]` 标记
- [OK] to_dict 含 7 字段

### 2. 各模块 get_guides() 接入（14/14 ✅）

7 个模块全部接入 `get_guides(unit_id, project_id="")`：

| 模块 | 函数存在 | 返回 list |
|------|---------|----------|
| consistency | ✅ | ✅ |
| unit_hook_service | ✅ | ✅ |
| memory | ✅ | ✅ |
| pressure | ✅ | ✅ |
| style_fingerprint | ✅ | ✅ |
| voice_profile | ✅ | ✅ |
| unit_event_service | ✅ | ✅ |

### 3. collect_guides() 统一收集（4/4 ✅）

- [OK] collect_guides 返回 list
- [OK] collect_guides_dict 返回 list[dict]
- [OK] 按 priority 倒序排序后第一个 priority=0.9
- [OK] 排序后最后一个 priority=0.3

### 4. GuidePanel UI 颜色映射（7/7 ✅）

**priority → 颜色**：
- 0.8 → `#d97757`（orange-red，高优先级）
- 0.6 → `#d4a157`（amber，中优先级）
- 0.3 → `#8a8a8a`（gray，低优先级）

**confidence → 透明度**：
- 0.9 → 1.0（完全不透明）
- 0.6 → 0.85
- 0.3 → 0.55（标灰）

### 5. collect_guides 集成（真实 DB）（8/8 ✅）

测试场景：创建项目 + unit + 注入 narrative_pressure(orange zone) + 1 个未兑现 hook + 1 个 trust 大幅下降 event

- [OK] collect_guides 返回 6 个 Guide
- [OK] 所有项均为 Guide 实例
- [OK] 含 pressure / hook / event Guide
- [OK] 最高 priority Guide：source=event, priority=0.7
- [OK] collect_guides_dict 序列化成功
- [OK] dict 含 7 字段

---

## v3.5.2 新增 / 修改文件

### 新增

| 文件 | 行数 | 用途 |
|------|------|------|
| `app/ui/widgets/_guide_panel.py` | 240 | Story Guidance 面板（UI）|
| `smoke/v3_5_2_validation.py` | 320 | 验证脚本（50 项断言）|

### 修改

| 文件 | 改动 |
|------|------|
| `app/core/types.py` | Guide 7 字段升级 + Action/Scope 枚举 + collect_guides 接 7 模块 |
| `app/services/unit_hook_service.py` | 新增 `get_guides()` + `_has_payoff()` |
| `app/services/memory.py` | 新增 `get_guides()`（未兑现承诺 + L1+L2 缺失）|
| `app/services/pressure.py` | 新增 `get_guides()`（4 维度：Narrative/Character/Timeline/Reader）|
| `app/services/voice_profile.py` | 新增 `get_guides()`（档案缺失 + 维度极端）|
| `app/services/style_fingerprint.py` | 新增 `get_guides()`（Book FP 默认 + Author/Book 冲突）|
| `app/services/consistency.py` | 新增 `get_guides()`（错误过多）|
| `app/services/unit_event_service.py` | 新增 `get_guides()`（trust 暴跌 + 物品剧变）|
| `app/ui/widgets/__init__.py` | 导出 `GuidePanel` |

---

## v3.5.2 设计要点

### Guide 7 字段哲学

| 字段 | 含义 | 与 v3.5.1 的差异 |
|------|------|------------------|
| `source` | 模块来源 | 保留 |
| `priority` | 处理顺序（0-1）| **替换 severity**（语义升级：先处理谁，不是危险度）|
| `confidence` | 置信度（0-1）| **新增**（低置信 → "作者可忽略"）|
| `scope` | 作用范围 | **新增**（Paragraph/Scene/Unit/Book）|
| `advice` | 人话建议 | 保留（核心字段）|
| `reason` | 推理链 | **新增**（GPT 评价里最值钱的一行）|
| `evidence_ids` | 可追溯证据 | 保留（**最重要的字段**——让建议 Explainable）|
| `possible_actions` | 多选项 | **新增**（让 AI/作者选，不替决策）|
| `context` | 机器可读数据 | 保留（向后兼容）|
| `severity` | 旧字段 | 保留（向后兼容，自动同步 priority）|

### 4 维度压力（pressure.py）

| 维度 | 数据来源 | Guide 触发条件 |
|------|---------|---------------|
| **Narrative Pressure** | `narrative_pressures` 表 | zone=orange/red 时高优先级 |
| **Character Pressure** | `open_promises` 数量 | 角色目标压力 |
| **Timeline Pressure** | `word_count / target_chars` | 进度 < 30% 时提示 |
| **Reader Pressure** | trend 连续 green zone | 提示需要转折 |

### UI 颜色映射哲学

- **priority 高 → 暖色（orange-red）**：让作者一眼看到最重要的建议
- **confidence 低 → 标灰（0.55 alpha）+ "⚠️ AI 不太确定, 可忽略"**：让作者知道可以忽略
- **每条 Guide 都有 reason + evidence_ids**：作者可以理解"AI 为什么这么建议"

---

## 验证方法

执行：
```bash
cd d:/novel-writer-pure-v3.4
python smoke/v3_5_2_validation.py
```

输出：
```
✅ v3.5.2 Story Guidance System 验证全部通过
Result: 50/50 passed (0 failed)
```

---

## 下一步（v3.6 / 6 个月内）

按 v5 计划进入第三层：
- [ ] `unit_decisions` 表 + Decision dataclass
- [ ] Writer Agent 输出 Decision 记录（采纳/忽略/修改 + reason）
- [ ] StoryTeller prompt 双注入（"Guide 列表 + 你的 Decision"）
- [ ] UI Decision 可视化（哪个 Guide 被采纳 / 哪个被忽略）
- [ ] Guide Graph 雏形（Guide 之间的 conflict / support 关系）

---

**报告完成时间**：2026-07-06
**报告作者**：AI Agent
**核心理念**：**Guidance 而非 Constraint**
**目标达成**：✅ **v3.5.2 Story Guidance System 完整落地**