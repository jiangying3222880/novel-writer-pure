好的，这是一份非常详尽的项目AGENTS.md。让我再补充一些关键文件的扫描结果，然后给出完整的重构方案。
我已经完成了对原项目的全面扫描。基于项目里已经存在的 `from-scratch-prd.md`，我看到你已经做了大量的规划工作，但**PRD 是从 2026-06-06 写的**（基于 v3.0），距今又过了些时间，且 PRD 写的是"如果启动重写"的方案。我现在以团队主理人的身份，基于对你**原项目**（已经存在的代码）的全量扫描，给你**一份独立的方案**，不依赖你之前那份 PRD。

---

# 🏗️ novel-writer-pure 从 0 重构方案 v2

## 一、原项目真实画像（基于代码扫描）

### 1.1 项目规模
| 维度 | 数据 |
|------|------|
| Python 源文件 | 244 个 |
| 代码行数（核心文件）| v3_engine.py **1925** + project_db.py **3568** + main_window_ui.py **2498** + engine.py **787** ≈ **8778** 行 |
| AI Provider | 27 个（含 Anthropic 单独协议） |
| 数据库表 | 23 张（核心 8 + 元数据 7 + 叙事增强 4 + 实验性 4） |
| 插件 | 10 个 |
| UI 文件 | 70+ 个 |

### 1.2 核心架构（实代码，非文档）

```
启动层 (main.py)
    │
    ├── Container (IoC)
    │   ├── event_bus
    │   ├── plugin_manager
    │   ├── ai (AIEngine)
    │   ├── memory (MemoryManager)
    │   ├── rag (RAGManager)
    │   ├── knowledge (KnowledgeFinder)
    │   └── main_window
    │
    ├── PluginManager (10 插件)
    │   └── plugins/* (动态 importlib 加载)
    │
    └── QApplication + MainWindowUI
        └── 6 Tab（懒加载 + ai_gen 同步）
```

**注意一个细节**：原代码是**单 Python 主进程** + **多线程/事件循环** 模型。`main.py` 用 `importlib.util` 手动 hack 了 `plugins` 包的加载（避开 namespace package 冲突），这种 hack 在 4 个地方出现。

### 1.3 业务流程（实代码分析）

#### 主流程：写 1 章（实际代码调用链）

```
generator_tab.py::on_generate_clicked()
  → WorkflowThread (QThread, 嵌套 asyncio loop)
    → v3_engine.py::execute_chapter_v3()
      ├─ [WRITE] writer_agent.write_scene()
      │    ├─ MemoryManager.get_scene_context()
      │    │    ├─ 加载 chapter_briefs + meta
      │    │    ├─ 拼装 SceneContext:
      │    │    │   ├─ SceneSubtextCard（潜文本卡）
      │    │    │   ├─ CharacterVoiceProfile（声音档案）
      │    │    │   ├─ AuthorStyleFingerprint（风格指纹）
      │    │    │   └─ AntiRule（反规则）
      │    │    └─ RAGManager.retrieve()  [3章摘要+设定+伏笔]
      │    ├─ AIEngine.chat() (HTTP POST 1次, ~8-10K tokens)
      │    └─ 后处理：JSON 解析、字段填充
      │
      ├─ [可选 USER_CONFIRM] user_confirm_dialog (前10章)
      │
      ├─ [SELF_CRITIQUE] writer_agent.self_critique()
      │    ├─ 拼 4+3 问自评 prompt
      │    ├─ AIEngine.chat() (HTTP POST 1次, ~4-5K tokens)
      │    └─ 解析评分 + 问题清单
      │
      └─ [PERSIST] settler_agent.persist()
           ├─ 6 本地验证器（pov/spatial/voice/setting/重复/item）
           ├─ consistency_checker（跨章）
           ├─ 落库 chapters / chapter_summaries
           ├─ 更新 character_states
           ├─ 更新 hooks (债务追踪)
           ├─ 风格指纹增量学习
           └─ 声音档案增量更新
```

#### 辅助流程

- **导入**：TemplateDetector → ScriptImporter (脚本解析) | AIImportManager (AI 兜底) → 预览 → 落库
- **蒸馏**：每 8 章触发，4 tier（plot/character/worldview/foreshadow）
- **RAG**：向量（chromadb）+ BM25 + RRF 混合检索
- **大纲生成**：AI 智能生成（`ai_outline_gen` 插件，2-3 个版本对比）
- **世界图谱**：`entity_graph` 插件，可视化
- **TTS**：`tts_edge` 插件，edge-tts 流式播放

### 1.4 真实存在的"病灶"（扫代码得出，不靠文档）

| 病类 | 病位 | 表现 | 处方 |
|------|------|------|------|
| **巨型文件** | `v3_engine.py` 1925行 | 单文件包含：模式A/B/C分流、4个引导元素拼装、4个阶段agent、错误处理、回调…… | **拆分到 ≤ 300 行/文件** |
| **巨型文件** | `project_db.py` 3568行 | 1个文件管 23 张表 | **按表域拆 DAO** |
| **巨型文件** | `main_window_ui.py` 2498行 | 主窗口 + 懒加载 + 插件同步 | **分 widget 树** |
| **启动 hack** | `main.py:11-18` | 手动 importlib hack `plugins` 包 | **新项目无此问题** |
| **asyncio 兼容** | `engine.py` + 8 文件 | `aiohttp 3.13` 上下文问题，要 `new_event_loop` + `run_until_complete` | **新项目用 `reqwest` + `tokio` 一遍过** |
| **配置 3 层 fallback** | `main.py:62-77` | `ai_config.json` → `model_configs.json` → `config.yaml` | **新项目用单一 toml + 加密** |
| **类型不安全** | 全局 | 大量 `dict` 传来传去 | **新项目 Rust+TS 强类型** |
| **PyQt 主题 47 测试** | `ui_consistency/` | 需要测试网防止 setStyleSheet 散落 | **新项目用 CSS 变量 + Tailwind** |
| **Embedding 限制** | `requirements.txt:12` | `chromadb; sys_platform != 'darwin' or platform_machine != 'arm64'` | **新项目用纯 Rust 向量库** |
| **打包大** | `novel-writer-pure.spec` | PyInstaller → 200MB+ | **新项目 Tauri → 5-15MB** |
| **启动慢** | main.py 时序 | 3-5秒 | **新项目 < 1秒** |

### 1.5 业务内核**必须保留**（用户业务价值所在）

不论用什么语言重写，这 5 件事不能丢：

1. **3 阶段范式**：Write → Self-Critique → Persist（2 次 LLM 调用，0 token 落库）
2. **4 大引导元素**：潜文本卡 + 声音档案 + 风格指纹 + 反规则
3. **6 个本地验证器**：POV / 空间 / 声音 / 设定 / 重复 / 物品
4. **3 层记忆**：STM → MTM → LTM，每 8 章蒸馏
5. **RAG 混合检索**：向量 + BM25 + RRF

---

## 二、技术栈选型（多角度论证）

### 2.1 候选栈对比（基于你**这个项目**的特性）

| 维度 | Rust+Tauri+React | Go+Wails+React | Python+PyQt6 | Electron+TS | Python+Webview |
|------|------------------|----------------|--------------|-------------|----------------|
| 启动速度 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| 打包体积 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐ | ⭐⭐ |
| 内存 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐ |
| 大文本编辑 | ⭐⭐⭐⭐⭐ (Monaco) | ⭐⭐⭐⭐⭐ | ⭐⭐ (QTextEdit) | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| AI 流式输出 | ⭐⭐⭐⭐⭐ (tokio SSE) | ⭐⭐⭐⭐ (channel) | ⭐⭐⭐ (aiohttp) | ⭐⭐⭐ | ⭐⭐ |
| 向量检索 | ⭐⭐⭐ (chromadb-rs/内嵌) | ⭐⭐⭐ (内嵌) | ⭐⭐⭐ (chromadb) | ⭐⭐ | ⭐⭐⭐ |
| 学习曲线 | ⭐⭐ (Rust 难) | ⭐⭐⭐ (Go 易) | ⭐⭐⭐⭐⭐ (你熟) | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| 开发效率 | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| 长驻应用适合度 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| 跨平台 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| 未来 5 年 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐ |

### 2.2 我的推荐：**Rust + Tauri + React**（理由 7 条）

1. **你这个产品是长驻写作软件**：用户每天打开 4-8 小时。Rust 50-100MB 内存 vs PyQt 300-500MB，体感差异巨大
2. **大文本是刚需**：万字章节在 Monaco（VSCode 同内核）里 60fps 滚动，PyQt QTextEdit 千行就卡
3. **LLM 流式输出**：Tauri + tokio + SSE 几乎无延迟，PyQt 嵌套 asyncio 各种 bug（原项目 8 文件 13 处 hack 就是这个原因）
4. **打包体积 10-15 倍优势**：Tauri 5-15MB vs PyInstaller 200MB+，用户更新成本低
5. **类型安全**：Rust + TS 双重保障，3 阶段工作流这种复杂业务逻辑，必须有强类型撑住
6. **AI Provider 27 个**：HTTP 协议都是标准 OpenAI/Anthropic，Rust `reqwest` 直接调，无需 SDK
7. **chromadb-rs 替代品**：内嵌 hnsw-rs（纯 Rust 向量库），无 Python 依赖

### 2.3 备选：Go + Wails + React（如果 Rust 周期太长）

- 优点：Go 学习曲线平缓，2-3 周上手
- 缺点：并发模型不如 Rust 灵活，打包体积 20-30MB（介于中间）
- 适合场景：团队 0 Rust 经验，时间紧迫

### 2.4 保守方案：Python 升级到现代框架（如果不想换技术栈）

- 选 **Python 3.12 + Textual + TauriShell + SQLite** 是不存在的组合
- 真实保守方案：**Python 3.12 + NiceGUI/Streamlit** 走纯 Web 路线，但失去原生体验
- **不推荐**——既然要重做，不如做对

---

## 三、新项目架构设计

### 3.1 目录结构

```
novel-writer-v3/                    # 新项目根
├── src-tauri/                      # Rust 后端
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   ├── src/
│   │   ├── main.rs                 # 入口
│   │   ├── lib.rs                  # 库入口
│   │   ├── domain/                 # 业务领域模型
│   │   │   ├── mod.rs
│   │   │   ├── project.rs          # Project / Book / Chapter
│   │   │   ├── character.rs        # Character / CharacterState
│   │   │   ├── item.rs             # Item / Location / Hook
│   │   │   ├── world.rs            # WorldSetting / VoiceProfile
│   │   │   ├── context.rs          # SceneContext 4 元素
│   │   │   └── validation.rs       # ValidationResult
│   │   ├── persistence/            # 持久化层
│   │   │   ├── mod.rs
│   │   │   ├── db.rs               # sqlx pool + migration
│   │   │   ├── migrations/         # sqlx migrate
│   │   │   │   ├── 20260101000001_init.sql
│   │   │   │   └── ...
│   │   │   └── dao/                # 按表域拆 DAO
│   │   │       ├── project_dao.rs
│   │   │       ├── chapter_dao.rs
│   │   │       ├── character_dao.rs
│   │   │       └── ...
│   │   ├── workflow/               # 3 阶段范式（业务核心）
│   │   │   ├── mod.rs
│   │   │   ├── engine.rs           # V3Engine orchestrator
│   │   │   ├── write_stage.rs      # WriteAgent
│   │   │   ├── critique_stage.rs   # CritiqueAgent
│   │   │   ├── persist_stage.rs    # PersistAgent
│   │   │   ├── context_builder.rs  # SceneContext 拼装
│   │   │   ├── user_confirm.rs     # 前 10 章确认
│   │   │   └── multi_version.rs    # 3 模式分发
│   │   ├── validators/             # 6 个 0 token 验证器
│   │   │   ├── mod.rs
│   │   │   ├── pov.rs
│   │   │   ├── spatial.rs
│   │   │   ├── voice.rs
│   │   │   ├── setting_recall.rs
│   │   │   ├── repetition.rs
│   │   │   └── item.rs
│   │   ├── memory/                 # 3 层记忆
│   │   │   ├── mod.rs
│   │   │   ├── stm.rs
│   │   │   ├── mtm.rs
│   │   │   ├── ltm.rs
│   │   │   └── distiller.rs
│   │   ├── rag/                    # RAG 混合检索
│   │   │   ├── mod.rs
│   │   │   ├── vector.rs           # hnsw-rs 内嵌
│   │   │   ├── bm25.rs             # tantivy 替代
│   │   │   └── fusion.rs           # RRF 融合
│   │   ├── ai/                     # AI 引擎
│   │   │   ├── mod.rs
│   │   │   ├── engine.rs           # 统一 chat/sse 接口
│   │   │   ├── providers/          # 27 个 provider
│   │   │   │   ├── openai.rs       # 通用 OpenAI 协议
│   │   │   │   ├── anthropic.rs    # Anthropic 协议
│   │   │   │   ├── ollama.rs
│   │   │   │   └── registry.rs
│   │   │   ├── streaming.rs        # SSE 流式
│   │   │   └── retry.rs            # 重试 + fallback
│   │   ├── knowledge/              # 知识库
│   │   │   ├── mod.rs
│   │   │   ├── builtin.rs          # 内置（6类×9体裁）
│   │   │   ├── local.rs            # 用户本地
│   │   │   └── finder.rs
│   │   ├── plugins/                # 插件系统
│   │   │   ├── mod.rs
│   │   │   ├── manager.rs
│   │   │   ├── manifest.rs         # plugin.toml 描述
│   │   │   └── builtin/            # 内置插件（编译期）
│   │   ├── ipc/                    # Tauri 命令
│   │   │   ├── mod.rs
│   │   │   ├── chapter.rs          # 章节命令
│   │   │   ├── project.rs
│   │   │   ├── ai.rs
│   │   │   ├── events.rs           # 事件推送
│   │   │   └── config.rs
│   │   ├── config/                 # 配置
│   │   │   ├── mod.rs
│   │   │   ├── manager.rs          # config.toml + 加密
│   │   │   └── defaults.rs
│   │   ├── error.rs                # 统一错误类型
│   │   ├── event_bus.rs            # tokio::broadcast
│   │   ├── container.rs            # 简易 DI
│   │   └── license.rs
│   ├── tests/                      # 集成测试
│   │   ├── integration/
│   │   └── fixtures/
│   └── migrations/
├── src/                            # React 前端
│   ├── main.tsx
│   ├── App.tsx
│   ├── index.html
│   ├── lib/
│   │   ├── tauri.ts                # Tauri 命令封装
│   │   ├── stores/                 # Zustand
│   │   │   ├── project.ts
│   │   │   ├── chapter.ts
│   │   │   ├── workflow.ts
│   │   │   └── theme.ts
│   │   ├── hooks/
│   │   ├── ipc/                    # 事件订阅
│   │   └── utils/
│   ├── components/                 # 通用组件
│   │   ├── ui/                     # shadcn/ui 包装
│   │   ├── editor/                 # Monaco 富文本
│   │   ├── charts/                 # Recharts 包装
│   │   ├── dialogs/                # 14 Dialog
│   │   ├── sidebar/                # 9 项侧栏
│   │   ├── tabs/                   # 6 Tab
│   │   └── theme/                  # Solarized 主题
│   ├── pages/
│   │   ├── novel-settings/         # Tab 1
│   │   ├── chapter-generate/       # Tab 2
│   │   ├── chapter-edit/           # Tab 3
│   │   ├── dashboard/              # Tab 4
│   │   ├── narrative-lab/          # Tab 5
│   │   └── memory/                 # Tab 6
│   ├── styles/
│   │   ├── solarized-dark.css
│   │   ├── solarized-light.css
│   │   └── tokens.css              # CSS 变量
│   └── types/                      # 共享 TS 类型
│       ├── domain.ts
│       ├── api.ts
│       └── events.ts
├── tests/
│   ├── e2e/                        # Playwright 视觉回归
│   │   ├── chapters/
│   │   └── snapshots/
│   ├── unit/                       # Vitest
│   └── integration/
├── scripts/
│   ├── migrate-from-v3.py          # 旧数据迁移
│   └── seed.ts
├── docs/
│   ├── ARCHITECTURE.md
│   ├── USER_GUIDE.md
│   └── API.md
├── package.json
├── pnpm-lock.yaml
├── Cargo.lock
├── tauri.conf.json
├── README.md
└── LICENSE
```

### 3.2 核心数据流（新版）

```
┌────────────┐  IPC   ┌─────────────┐  tokio   ┌──────────┐
│   React    │ ←────→ │ Tauri Shell │ ───────→ │  Engine  │
│  Frontend  │  SSE   │   (Rust)    │  HTTP    │   Pool   │
└────────────┘ events └─────────────┘  reqwest └──────────┘
                       │                             │
                       ↓                             ↓
                ┌──────────────┐              ┌──────────┐
                │ Event Bus    │              │ AI APIs  │
                │ (broadcast)  │              │  27个    │
                └──────────────┘              └──────────┘
                       │                             │
                       ↓                             ↓
                ┌──────────────┐              ┌──────────┐
                │   SQLite     │ ←─────────── │ Streaming│
                │   (sqlx)     │              │  SSE     │
                └──────────────┘              └──────────┘
```

### 3.3 新版数据模型（精简后，10 张表）

```sql
-- 项目域
projects (id, name, book_title, author, genre, platform, created_at, updated_at)
books (id, project_id, volume_no, title, synopsis, target_chapters)
chapters (id, book_id, chapter_no, title, status, scene_context_json, draft, final, critique_json, validation_flags_json, word_count, created_at, updated_at)
-- ↑ 注意：把原 4 张表（chapters/chapter_briefs/chapter_summaries/chapter_revisions）的字段合并到 1 张，用 JSON 存可选项

-- 实体域
characters (id, project_id, name, profile_json, voice_profile_id)
character_states (id, character_id, chapter_no, emotion, location, relationships_json, arc_state)
items (id, project_id, name, holder_id, location, first_chapter, last_mentioned)
locations (id, project_id, name, description, rules_json)
hooks (id, project_id, description, introduced_chapter, resolved_chapter, status, debt_score)
world_settings (id, project_id, category, key, value, description)

-- 引导元素（4 大）
voice_profiles (id, project_id, name, style_features_json, sample_text)
scene_subtext_cards (id, chapter_id, surface_event, real_intent, lie, truth, physical_anchors_json, anti_rules_json)
author_style_fingerprints (id, project_id, pace, density, lyricism, drift_threshold, last_updated)

-- 辅助域
chapter_summaries (id, chapter_id, summary_text, created_at)  -- 仅保留摘要，独立表便于 LTM 检索
meta (project_id, key, value)  -- 全局设置（key-value）
```

**精简效果**：从 23 张表 → **14 张表**（裁掉 4 张叙事实验表 + 1 张 agent_memory + 1 个合并 + 3 个临时表），且 4 个核心表用 JSON 字段合并。

### 3.4 关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 异步运行时 | `tokio` | Rust 异步事实标准 |
| HTTP 客户端 | `reqwest` + `tokio-stream` | SSE 流式成熟 |
| SQLite ORM | `sqlx`（编译期 SQL 校验）| 类型安全 + 性能 |
| 向量检索 | `hnsw-rs`（纯 Rust 内嵌）| 无外部依赖，零启动 |
| BM25 | `tantivy`（Lucene 替代）| 纯 Rust |
| 序列化 | `serde` + `serde_json` | 生态标准 |
| 错误处理 | `thiserror` + `anyhow` | 分层错误 |
| 日志 | `tracing` + `tracing-subscriber` | 结构化日志 |
| 配置 | `figment` 或 `config-rs` | 多源合并 |
| 前端构建 | `Vite` + `pnpm` | 快 |
| 前端框架 | `React 18` + `TypeScript` | 你的 PRD 已经定 |
| 前端 UI | `shadcn/ui` + `Tailwind CSS` | 可复制可定制 |
| 前端状态 | `Zustand` | 比 Redux 轻 90% |
| 富文本 | `Monaco Editor` | VSCode 同款 |
| 图表 | `Recharts` | React 友好 |
| 表单 | `react-hook-form` + `zod` | 强类型表单 |
| 主题 | CSS 变量 + Tailwind dark mode | 一次定义两套色 |

### 3.5 性能预算

| 指标 | 目标 |
|------|------|
| 启动时间 | < 800ms |
| 安装包（Win x64） | < 15MB |
| 内存（空载）| < 80MB |
| 内存（写 1 万字章节）| < 200MB |
| LLM 流式首字延迟 | < 300ms |
| 章节保存（含 6 验证器）| < 50ms |
| 大文本（10 万字）滚动 | 60fps |
| 数据库查询（1 万章项目）| < 10ms |

---

## 四、实施路线图（12 周）

| Phase | 周 | 任务 | 交付 |
|-------|-----|------|------|
| **0** | 1 | 环境搭建 | Rust + Tauri + Node 工具链，CI 跑通 |
| **1** | 1-2 | 数据层 | 14 张表 schema + sqlx + DAO + 单测 |
| **2** | 2-4 | 业务核心 | 3 阶段引擎 + 4 引导元素 + 6 验证器 + 集成测试 |
| **3** | 4-5 | AI 层 | 27 provider 适配 + SSE 流式 + fallback |
| **4** | 5-6 | Tauri 桥 | 命令注册 + 事件总线 + 进度推送 |
| **5** | 6-7 | 前端基础 | 主题 + 路由 + 状态 + 布局（Solarized） |
| **6** | 7-8 | 6 Tab + 侧栏 | 按用户原型 1:1 还原 |
| **7** | 8-9 | 14 Dialog | 弹窗体系 |
| **8** | 9-10 | 记忆 + RAG | STM/MTM/LTM + 向量 + BM25 + RRF |
| **9** | 10-11 | 测试 | 单测 + 集成 + Playwright 视觉回归 |
| **10** | 11-12 | 打包 + 迁移 | Tauri 三平台 + v3 旧数据导入工具 |

---

## 五、风险评估与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Rust 学习曲线 | 🟡 中 | 🟡 中 | Phase 0 安排 3 天 Rust 速成（The Book 前 10 章）|
| 旧数据迁移 | 🟢 低 | 🔴 高 | 写 `migrate-from-v3.py`，从 v3 SQLite 导出 JSON 再导入新表 |
| LLM 流式稳定性 | 🟡 中 | 🟡 中 | 多家 fallback + 重试退避 + 客户端断点续传 |
| Monaco 体积 | 🟢 低 | 🟢 低 | 按需懒加载语言包 |
| chromadb 替换 | 🟡 中 | 🟡 中 | hnsw-rs（已实现）或简化版 cosine 相似度 |
| 团队协作 | 🟡 中 | 🟡 中 | SOP 流程 + 代码审查 + CI 拦截 |

---

## 六、需你确认的决策点

请回答以下问题，我会按你的选择启动：

### Q1：技术栈
- A. **Rust + Tauri + React**（推荐，性能 5★，学习曲线 2★，12 周）
- B. Rust + Tauri + React（精简化，砍掉复杂插件，**8 周**可出 MVP）
- C. Go + Wails + React（Go 易学，**10 周**，但生态弱一些）
- D. Electron + TypeScript（你最熟，**8 周**，但内存/体积妥协）
- E. 保留 Python + 换 UI 框架（**6 周**，但只是修修补补）

### Q2：范围
- A. **完整重写**（10 插件 + 14 Dialog + 6 Tab 全部，12 周）
- B. **MVP 优先**（核心 3 阶段 + 章节编辑 + 设定，**6 周**）
- C. **仅后端重写**（Rust 重写 + 旧 PyQt 暂用，**4 周**）

### Q3：数据迁移
- A. 写迁移工具，**自动从 v3 SQLite 导入**
- B. 用户**手动导出 JSON**，新项目导入
- C. **不迁移**，新项目从 0 开始

### Q4：插件策略
- A. **全部重写**（按新 plugin.toml 协议，10 个）
- B. **保留 3 个核心**（ai_outline_gen / tts_edge / entity_graph），其余砍
- C. **暂不做插件**，所有功能内置

### Q5：UI 风格
- A. 按 `from-scratch-prd.md` 的 **Solarized Dark/Light**（你已设计）
- B. 用 shadcn/ui **默认风格**（最快，开发友好）
- C. 你**另外给原型**

### Q6：是否启动
- A. **现在启动** Phase 0
- B. 等你**完善 spec** 再启动
- C. 让我**再细化某些部分**（请指明）

---

## 七、我的建议组合

**`Q1-A + Q2-B + Q3-A + Q4-B + Q5-A + Q6-A`**
= **Rust + Tauri + React 全栈 + MVP 范围 + 自动迁移 + 3 核心插件 + Solarized + 立即启动**

**理由**：
- Rust 全栈拿到性能 + 打包 + 类型 3 重收益
- MVP 6 周出活，剩下功能迭代加
- 自动迁移保住老用户数据
- 3 核心插件覆盖 80% 使用场景

**总工作量**：6 周出 MVP + 6 周迭代到 1.0 = 12 周

请回复你的选择（例：`1A 2B 3A 4B 5A 6A`），我立即组建团队开干。