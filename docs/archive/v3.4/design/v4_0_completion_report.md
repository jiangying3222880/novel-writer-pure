# v4.0 Guide Graph + Story Compiler 完成报告

**日期**: 2026-07-06  
**作者**: trae AI  
**审核**: workbuddy AI  

---

## 一、v4.0 目标（来自 v5 计划）

> **v4.0（1 年内）— Guide Graph + Story Compiler 雏形**
> 
> | 组件 | 功能 |
> |------|------|
> | **Guide Graph 雏形** | Guide 之间的 conflict/support 关系，构建冲突图 |
> | **Story Compiler 雏形** | 修改 Unit → 自动分析影响范围 → 列出需同步修改的 Unit |

---

## 二、完成清单

### ✅ 2.1 Guide Graph 完整实现

| 组件 | 文件 | 状态 | 说明 |
|------|------|------|------|
| Guide 字段扩展 | `app/core/types.py` | ✅ | `conflicts_with` + `supports` 字段 |
| 冲突检测算法 | `app/services/guide_graph.py` | ✅ | 关键字匹配，O(n²)，不调 LLM |
| 冲突图构建 | `app/services/guide_graph.py` | ✅ | `analyze()` → `GuideGraphResult` |
| Prompt 注入 | `app/services/guide_graph.py` | ✅ | `build_graph_block()` 格式化 |
| Orchestrator 集成 | `app/agents/orchestrator.py` | ✅ | `graph_block` 注入 `_refine()` |

**数据流**:
```
collect_guides(unit_id)
  → Guide[] (含 conflicts_with/supports)
  → analyze(current_guides)
  → GuideGraphResult
  → build_graph_block(result)
  → 注入 prompt (extra_block)
```

### ✅ 2.2 Story Compiler 实现（未集成）

| 组件 | 文件 | 状态 | 说明 |
|------|------|------|------|
| ImpactedUnit dataclass | `app/services/story_compiler.py` | ✅ | 含 `impact_type` + `severity` |
| ImpactReport dataclass | `app/services/story_compiler.py` | ✅ | 含 `to_prompt_block()` |
| 四维度影响分析 | `app/services/story_compiler.py` | ✅ | `analyze_impact()` 实现 |
| Prompt 注入格式 | `app/services/story_compiler.py` | ✅ | `to_prompt_block()` 格式化 |
| Orchestrator 集成 | - | ⚠️ | **未集成**，模块可用但未调用 |

**Story Compiler 四维度**:
1. **exit_inherit** - 后继 Unit 的 entry 继承当前 Unit 的 exit
2. **hook_depend** - 其他 Unit 的 hook plant/payoff 依赖当前 Unit 的 hook
3. **event_cascade** - 其他 Unit 有事件引用当前 Unit 涉及的角色/世界状态
4. **character_state** - 角色 tracker 最新记录的章节与当前 Unit 重叠

---

## 三、验证结果

**验证脚本**: `smoke/v4_0_validation.py`  
**执行时间**: 2026-07-06  
**结果**: **44/44 通过**

### 验证项明细

| # | 验证项 | 结果 |
|---|--------|------|
| 1 | Guide `conflicts_with` / `supports` 字段 | ✅ 6/6 |
| 2 | `guide_graph` 冲突检测 | ✅ 11/11 |
| 3 | `collect_guides` 集成冲突图 | ✅ 11/11 |
| 4 | Orchestrator 冲突图注入 | ✅ 3/3 |
| 5 | Story Compiler 模块 | ✅ 9/9 |
| 6 | Story Compiler 集成（真实 DB） | ✅ 4/4 |

---

## 四、已知限制与后续工作

### 4.1 Story Compiler 未集成

**现状**: `analyze_impact()` 实现了，但 Orchestrator 未调用

**影响**: 
- 用户修改 Unit 后，不会自动提示影响范围
- 需要手动调用 `analyze_impact()` API

**后续工作**:
- 在 Orchestrator 的 `run_unit()` 完成后调用 `analyze_impact()`
- 把 `ImpactReport.to_prompt_block()` 注入下轮 prompt
- 或在 UI 层展示影响列表（v5.0 UI 重写时做）

### 4.2 Guide Graph 的冲突检测精度

**现状**: 用关键字匹配检测冲突，不调 LLM

**优点**: 快速，不增加 API 成本  
**缺点**: 可能漏检语义冲突

**后续工作**:
- v5.0 可考虑可选 LLM 增强（用户开启"深度冲突检测"时）
- 或增加更多关键字规则

### 4.3 collect_guides 重复调用 analyze

**现状**: 
- `collect_guides()` 内部调用 `analyze()` 标记 `conflicts_with/supports`
- Orchestrator 又调用一次 `analyze(current_guides)`

**影响**: 重复计算，但结果正确（幂等）

**后续工作**:
- 缓存 `analyze()` 结果
- 或 Orchestrator 直接使用 `collect_guides()` 已标记的冲突

---

## 五、架构影响

### 5.1 新增文件

| 文件 | 用途 |
|------|------|
| `app/core/types.py` | Guide 新增 `conflicts_with` + `supports` 字段 |
| `app/services/guide_graph.py` | Guide 冲突检测 + 冲突图构建 |
| `app/services/story_compiler.py` | Unit 修改影响分析 |
| `app/db/migrations/041_unit_decisions.sql` | Decision 表（v3.6 遗留） |

### 5.2 修改文件

| 文件 | 改动 |
|------|------|
| `app/agents/orchestrator.py` | 集成 `guide_graph`，注入 `graph_block` |
| `app/core/types.py` | Guide dataclass 升级（7 字段 → 9 字段） |

### 5.3 依赖关系

```
Orchestrator.run_unit()
  ↓
collect_guides(unit_id)  →  Guide[] (含 conflicts_with/supports)
  ↓
analyze(current_guides)  →  GuideGraphResult
  ↓
build_graph_block(result)  →  graph_block (str)
  ↓
_refine(..., extra_block=graph_block)
  ↓
record_batch()  →  unit_decisions 表
```

---

## 六、与 v5 计划的对比

| v5 计划项 | 状态 | 说明 |
|-----------|------|------|
| Guide Graph 雏形 | ✅ | 完整实现并集成 |
| Story Compiler 雏形 | ⚠️ | 实现但未集成 |
| Decision 层（v3.6） | ✅ | 已完成（见 v3.6 报告） |

---

## 七、结论

**v4.0 核心功能已完成**：
- ✅ Guide Graph 冲突检测 - 完整实现并集成
- ✅ Story Compiler 影响分析 - 模块实现，API 可用
- ✅ 验证通过 - 44/44

**待后续集成**：
- ⚠️ Story Compiler 集成到 Orchestrator
- ⚠️ Story Compiler 结果展示（UI）

**建议版本号**: v4.0（核心功能完成，集成可后续迭代）

---

**报告结束**
