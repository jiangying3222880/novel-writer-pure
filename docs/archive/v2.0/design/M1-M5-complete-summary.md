# M1-M5 完成汇总（novel-writer 3.0 引导性写作范式）

> 实施时间：2026-05-22 ~ 2026-06-05
> 实施阶段：novel-writer-3.0-architecture.md 全部 5 个里程碑
> 实施人：AI 辅助

## 一、里程碑全景

| 里程碑 | 时间 | 核心内容 | 关键模块 | 状态 |
|--------|------|---------|---------|------|
| M1 | 2026-05-22 ~ 2026-05-26 | 潜文本卡三模式入口 | `app/workflow/subtext_card.py` + UI 入口 | ✅ |
| M2 | 2026-06-02 ~ 2026-06-04 | RAG 预取 + 6 个本地验证器 | `app/workflow/validators/*.py` + RAG | ✅ |
| M3 | 2026-06-04 | 3 阶段范式（Write → Self-Critique → Persist） | `app/workflow/v3_engine.py` | ✅ |
| M4 | 2026-06-04 ~ 2026-06-05 | 完整章节 E2E（含 4 大引导元素 + 6 验证器 + 跨章一致性） | `consistency_checker.py` + E2E 测试 | ✅ |
| M5 | 2026-06-05 | 50 章连贯生成 + 打包验证 | 长程测试 + PyInstaller | ✅ |

---

## 二、M1：潜文本卡三模式入口

### 2.1 目标
- 提供 3 种"潜文本卡"创建入口：用户手填 / AI 生成（plot_deduction 插件） / Writer 自推（第 1 章）
- 注入 Writer prompt 作为最优先级的"这次写什么+怎么写"指引
- 替代 2.0 的"约束清单"（Planner 输出）

### 2.2 实施内容
- **数据结构**：`SceneSubtextCard` dataclass（5 个核心字段 + 2 个场景字段 + 1 个反规则字段 + 元数据）
- **核心字段**：surface_event / real_intent_protagonist / lie / truth / physical_anchor
- **场景字段**：scene_map（场景空间）/ ending_scene_state（结尾状态）
- **反规则字段**：anti_rules（单章临时）
- **三模式入口**：
  - 用户手填：`SubtextCardDialog`（UI）
  - AI 生成：`plugins/plot_deduction/` 插件
  - Writer 自推：第 1 章默认初始化

### 2.3 关键文件
- `app/workflow/subtext_card.py` — 核心数据结构 + 持久化
- `ui/tabs/outline/dialogs/subtext_card_dialog.py` — UI 对话框
- `plugins/plot_deduction/` — AI 生成模式

### 2.4 验证
- 单元测试：`test_subtext_card.py`
- 数据库表新增：`scene_subtext_cards`

---

## 三、M2：RAG 预取 + 6 个本地验证器

### 2.5 目标
- 实施 6 个 0 token 本地验证器，**对抗 4 大问题**（视角乱 / 方向错乱 / 角色风格漂移 / 10 章后遗忘）
- RAG 预取章节上下文（前 3 章 + 核心设定 + 活跃伏笔 + 角色状态）
- 验证器统一接口 + Flag 模式（不阻断）

### 2.6 6 个本地验证器

| 验证器 | 解决问题 | 关键检查 |
|--------|---------|---------|
| `pov_validator.py` | 视角乱 | 第一人称占比 ≥ `perspective_percent%`，无上帝视角泄露 |
| `spatial_validator.py` | 方向错乱 | 方向/位置一致性（房间/物品/人物相对位置） |
| `voice_validator.py` | 角色风格漂移 | 角色句法/词汇/决策模式与 `CharacterVoiceProfile` 匹配 |
| `setting_recall.py` | 10 章后遗忘 | 核心设定 + 活跃伏笔在章节中体现 |
| `repetition_detector.py` | AI 重复句式 | 句首词频/整句重复/三连短句 |
| `item_validator.py` | 物品不一致 + 承诺追踪 | 物品/承诺跨章一致性 |

### 2.7 RAG 预取

```
M2 RAG 预取流程：
  ├─ 查询前 3 章 chapter_summaries
  ├─ 查询 meta 表核心设定（genre / perspective / word_target）
  ├─ 查询活跃伏笔（hooks 表，status='active'）
  ├─ 查询出场角色 character_states
  └─ 拼接为 SceneContext，注入 Writer prompt
```

### 2.8 关键文件
- `app/workflow/validators/base.py` — 统一接口（`ValidationResult`）
- `app/workflow/validators/pov_validator.py`
- `app/workflow/validators/spatial_validator.py`
- `app/workflow/validators/voice_validator.py`
- `app/workflow/validators/setting_recall.py`
- `app/workflow/validators/repetition_detector.py`
- `app/workflow/validators/item_validator.py`
- `app/workflow/validators/__init__.py` — 统一导出
- `app/rag/vector_db.py` — RAG 混合检索（向量 + BM25 + RRF）

### 2.9 验证
- 单元测试：`test_validators.py`
- 对比实验报告：[M2-comparison-report.md](M2-comparison-report.md)（2.0 vs 3.0 POV 验证器对比）
- M2 概念验证：POV 验证器先于其余 5 个实施，作为概念验证

---

## 四、M3：3 阶段范式

### 4.1 目标
- 实施 3 阶段工作流：Write → Self-Critique → Persist
- 总 token 消耗 ~12-15K/章（2.0 是 ~50K/章，节省 70%）
- 砍 Planner / Auditor / Reviser / Polisher 4 个旧 Agent

### 4.2 三阶段

```
┌────────────────────────────────────────────────────────────────┐
│ Write (1 次 LLM, ~8-10K)                                         │
│   输入：潜文本卡 + 角色声音档案 + 作者风格指纹 + 反规则           │
│   输出：章节正文初稿                                              │
└────────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────────┐
│ Self-Critique (1 次 LLM, ~4-5K)                                  │
│   输入：Write 输出 + 4 问自评模板                                 │
│   输出：自评分 + 问题清单                                         │
└────────────────────────────────────────────────────────────────┘
                            ↓
┌────────────────────────────────────────────────────────────────┐
│ Persist (0 token, 本地)                                          │
│   6 个本地验证器 + 跨章一致性检查器 + 落库                        │
└────────────────────────────────────────────────────────────────┘
```

### 4.3 关键文件
- `app/workflow/v3_engine.py` — 3 阶段流程引擎

### 4.4 对比 2.0

| 指标 | 2.0 | 3.0 | 变化 |
|------|-----|-----|------|
| Token/章 | ~50K | ~12-15K | **-70%** |
| AI 调用次数/章 | 5-7 次 | 2 次 | **-60%~70%** |
| 失败处理 | LLM 修补循环 | Self-Critique 自评 + 作者决定 | 质变 |

### 4.5 验证
- 单元测试：`test_v3_engine.py`
- Prompt 函数：`app/workflow/prompts.py:get_v3_writer_prompt()` / `get_self_critique_prompt()`

---

## 五、M4：完整章节 E2E

### 5.1 目标
- 端到端测试：完整章节生成流程（含 4 大引导元素 + 6 验证器 + 跨章一致性）
- 实施跨章一致性检查器
- 验证器 Flag 模式生效（记录到 `chapter_summaries.validation_flags`）

### 5.2 跨章一致性检查器

`app/workflow/consistency_checker.py`：
- 跨章设定一致性（关键设定不丢失）
- 物品一致性（物品持有/使用/失去跨章追踪）
- 对话一致性（同一角色跨章对话风格一致）
- 时序一致性（时间线无矛盾）
- 情绪一致性（角色情绪曲线连贯）

### 5.3 E2E 流程

```
M4 E2E：
  1. 创建项目 + 角色 + 大纲
  2. 创建潜文本卡（第 1 模式：手填）
  3. 触发章节生成
     ├─ Write 阶段（接收 4 大引导元素）
     ├─ Self-Critique 阶段
     └─ Persist 阶段
        ├─ 6 个本地验证器
        ├─ 跨章一致性检查器
        ├─ 风格指纹增量学习
        └─ 落库
  4. 验证 chapter_summaries.validation_flags 字段
```

### 5.4 验证
- E2E 测试：`test_v3_e2e.py`
- 跨章一致性：`test_consistency_checker.py`
- 风格学习：`test_style_learner.py`

---

## 六、M5：50 章连贯生成 + 打包验证

### 6.1 目标
- 50 章连贯生成测试（验证长程一致性）
- PyInstaller 打包验证（目录模式 + 单文件模式）
- 760+ 测试通过

### 6.2 50 章连贯测试

```
M5 50 章连贯：
  1. 创建项目（含 3 个角色 + 50 章大纲 + 5 个活跃伏笔）
  2. 循环生成 50 章
  3. 统计：
     ├─ 总 token 消耗
     ├─ 总耗时
     ├─ 6 验证器通过率
     ├─ 跨章一致性通过率
     ├─ 风格漂移检测触发次数
     └─ 声音档案增量更新次数
  4. 验证：
     ├─ 无崩溃
     ├─ 数据库无错误
     └─ 风格指纹漂移在阈值内
```

### 6.3 打包验证

```bash
python scripts/package.py          # 目录模式（推荐）
python scripts/package.py --onefile # 单文件模式
python scripts/package.py --check   # 检查环境
```

打包产物：
- `dist/novel-writer-pure-{版本号}/novel-writer-pure-{版本号}.exe`
- `dist/novel-writer-pure-{版本号}/`（依赖目录）

### 6.4 验证
- 长程一致性测试：`test_long_chapter_generation.py`
- 打包测试：手动启动 exe 验证

---

## 七、关键指标汇总（M1-M5 累计）

| 指标 | 2.0（基线） | 3.0（M5 收尾） | 变化 |
|------|------------|---------------|------|
| Token/章 | ~50K | **~12-15K** | **-70%** |
| AI 调用次数/章 | 5-7 次 | **2 次** | -60%~70% |
| Token/50 章 | ~2500K | **~600-750K** | **-70%** |
| 视角合规率 | 80-90% | **>95%** | +5~15% |
| 角色风格一致 | 关键词匹配 | **句法+词汇指纹** | 质变 |
| 风格漂移检测 | 无 | **0.3 阈值告警** | 新增 |
| 跨章一致性 | LTM/STM | **+ 一致性检查器** | 增强 |
| 0 token 验证 | 无 | **6 个本地验证器** | 新增 |
| Agent 数量 | 7 个 | **3 个**（base/writer/settler/import_parse） | -57% |
| 物理删除代码行数 | — | ~10000+ | 收尾 |

---

## 八、3.0 收尾

3.0 范式（M1-M5）已完整落地。后续工作（post-3.0-ui-sync-cleanup）：

- 物理删除 2.0 残留（`engine.py` / 4 个旧 Agent / 9 个旧 prompt .md / `security.py`）
- UI 同步到 3.0（生成 Tab 3 步指示器 / 大纲 Tab 4 元素入口 / 仪表盘 3.0 节省展示）
- 主题令牌补全（`SIZE_TYPOGRAPHY` + 硬编码颜色 / 字体替换）
- 版本号同步：`2.0.0` → `3.0.0`，codename `FUSION` → `ASCENSION`

详见 [演化路径.md](../版本管理/演化路径.md) 和 [CHANGELOG.md](../版本管理/CHANGELOG.md)。
