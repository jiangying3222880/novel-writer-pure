# v4.0 文档归档说明

**归档日期**: 2026-07-06  
**归档人**: workbuddy AI  

---

## 一、归档内容

### 1.1 设计文档（.trae → docs/design/）

| 原路径 | 新路径 | 说明 |
|--------|--------|------|
| `.trae/documents/单元驱动编排重构计划-v5-最终版.md` | `docs/design/` | v5 计划（v3.5.1-v4.0 路线图） |
| `.trae/documents/UI-v4-蓝图-GPT评审整合.md` | `docs/design/` | UI v4.0 蓝图（4 大模块） |
| `.trae/documents/Story-Engine-路线图-GPT评审.md` | `docs/design/` | GPT 三轮评审整合 |
| `.trae/documents/单元驱动编排重构计划-v2.md` | `docs/design/` | v2 计划（历史） |
| `.trae/documents/单元驱动编排重构计划-v3.md` | `docs/design/` | v3 计划（历史） |
| `.trae/documents/单元驱动编排重构计划.md` | `docs/design/` | v1 计划（历史） |

### 1.2 完成报告（新增）

| 文件 | 说明 |
|------|------|
| `docs/v4_0_completion_report.md` | v4.0 完成报告（44/44 验证通过） |
| `docs/v3_6_completion_report.md` | v3.6 完成报告（Decision 层） |

### 1.3 验证脚本（smoke/）

| 文件 | 说明 |
|------|------|
| `smoke/v4_0_validation.py` | v4.0 验证脚本（44 测试项） |
| `smoke/story_engine_validation.py` | v3.5.1 验证脚本（42 测试项） |

---

## 二、版本更新

| 文件 | 变更 |
|------|------|
| `app/core/version.py` | `VERSION = "4.0"` |
| `README.md` | 标题、v4.0 章节、版本演进表、未来路线图、文档链接 |

---

## 三、已知限制

### 3.1 Story Compiler 未集成

**状态**: 模块实现，但未集成到 Orchestrator

**影响**: 用户修改 Unit 后不会自动提示影响范围

**后续**: v5.0 集成到 Orchestrator + UI 展示

### 3.2 Guide Graph 冲突检测精度

**状态**: 关键字匹配，不调 LLM

**优点**: 快速，不增加 API 成本  
**缺点**: 可能漏检语义冲突

**后续**: v5.0 可选 LLM 增强（用户开启"深度冲突检测"）

---

## 四、下一步建议

1. **集成 Story Compiler** - 在 Orchestrator 的 `run_unit()` 完成后调用 `analyze_impact()`
2. **UI 展示** - 在 GuidePanel 中展示 Impact Report（受影响 Unit 列表）
3. **验证脚本 CI** - 将 `smoke/v4_0_validation.py` 加入 CI 流程
4. **文档清理** - 删除 `docs/design/` 中的历史版本（v1-v3），只保留最新版

---

**归档完成**
