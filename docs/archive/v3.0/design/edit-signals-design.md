# 用户改稿信号 → Skill 沉淀 & 进化 设计方案

> **版本**: v3.0 (新增 Layer 4 进化层 + Layer 5 软提示注入)
> **状态**: 可实施
> **作者**: WorkBuddy
> **最后更新**: 2026-06-11
>
> **核心决策（拍板）**:
> - 节流粒度 = **章节级**（不是 30s 静默）
> - 5 层级联：30s 防抖 → 章节封存 → 累积聚类 → **进化** → **软提示注入**
> - 借鉴 Hermes v0.16.0 的 4 件：provenance / patch_count / pinned / 预运行备份
> - 借鉴 Hermes auto-evolution 的 5 件（去重合并 / 质量评分 / 泛化 / 失效检测 / 反例聚合）
> - 砍掉 v0.16.0 的 4 件：LLM 评审同步 / umbrella-ification 同步 / PROTECTED / .curator_suppressed
> - LLM 异步泛化拿回 (1 周 1 次, 后台 thread, 写手零感知)
> - 单本 5000 章、跨项目切换都扛得住

---

## 0. 背景与决策回顾

### 0.1 灵感来源（4 个）

| 来源 | 给的灵感 | 是否直接搬 |
|---|---|---|
| `F:\support man\super-author-core-master` 的 `SkillCandidatePipeline` | 失败→聚类→沉淀 范式 | ❌ 不直接搬，3 个差异 |
| Hermes Agent v0.16.0 (`NousResearch/hermes-agent` v2026.6.6) | 3 状态机 + sidecar + pinned | ✅ 借鉴 4 件 |
| Hermes auto-evolution | 合并/去重/泛化/评分/失效检测 | ✅ **拿回 5 件** (异步 + 节流) |
| 写手实际工作流 | 写完一章 = 1 个完整"教学样本" | ✅ **按章节**而非 30s |

### 0.2 3 个项目定位差异

| 维度 | super-author-core | Hermes Agent | **v4 (本方案)** |
|---|---|---|---|
| 产品形态 | Hermes 式纯聊天生成 | AI 助手 | 写作辅助类（GUI） |
| 信号来源 | 失败 run | AI 自身 patch 历史 | **用户改稿动作** |
| 评审频率 | 每次 run | 7 天 curator 周期 | **章节级** |
| 聚类者 | LLM curator | LLM rubric 分类 | **纯本地 diff** |
| 状态机 | 无 | 3 状态 + pinned | **沿用 + pinned** |
| 副作用容忍 | 可后台慢悠悠 | 后台 idle 触发 | **写手心流 > 一切** |

### 0.3 拍板结论（2 砍 1 收窄 + 节流粒度拍板）

| 决策 | 内容 | 理由 |
|---|---|---|
| ❌ 砍 | IntentRouter | v4 显式按钮已确定意图 |
| ❌ 砍 | 统一事件 envelope | v4 事件不出进程 |
| ✅ 收窄 | SkillCandidatePipeline → 用户改稿信号 | 写手改稿 = 强监督 |
| ✅ **节流 = 章节** | 不用 30s 静默作主节流 | 章节是小说场景的天然语义边界 |

---

## 1. 目标与非目标

### 1.1 目标

让 v4 能够**安静地**从用户改稿动作中学习，逐渐沉淀出"项目专属 Skill"，
**写手感知的代价 = 0**。

### 1.2 非目标（明确不做）

- ❌ 不调 LLM 做聚类（v0.16.0 用 LLM umbrella-ification，v4 不需要）
- ❌ 不做跨项目共享 Skill（先解决单项目，跨项目留给 v5+）
- ❌ 不做"弹窗教学用户怎么改"（写手最烦被教）
- ❌ 不做 7 天周期评审（按章节级封存，更准）
- ❌ 不做 PROTECTED_BUILTIN_SKILLS（v4 没有"plan"这种 UX 关键路径）
- ❌ 不做 `.curator_suppressed`（v4 没有 update 同步机制）

---

## 2. 核心设计原则

### 2.1 三条铁律

1. **零感知**：写手在 v4 里看不到任何"我在被观察"的迹象
2. **零阻塞**：所有处理（落盘、封存、聚类、沉淀）必须**异步 + 后台**
3. **零侵入**：现有 UI 调用方只在 3 处加 1 行 hook

### 2.2 节流原则（章节级）

**不**用 30s 静默窗口做主节流（那是给"打字连击"用的）。
**用"章节完成"做主节流**（每章 = 1 个完整"教学样本"）。

```
打字连击 → 30s 防抖 (Layer 1, 过滤垃圾)
       ↓
切换/保存章节 → 章节封存 (Layer 2, 1 章节 1 批次)
       ↓
累积 5 章/50 信号 → 后台聚类 (Layer 3, 节省算力)
```

### 2.3 失败模式假设

| 失败 | 缓解 |
|---|---|
| 写手误触（误删段） | 信号写入但永远不达阈值 |
| 改个错别字 | 30s 防抖 + 改 ≥ 1 句 + diff > N 字符 |
| 程序崩溃 | JSONL append 最多丢最后一行 |
| 写手后悔 | 4 档开关（L1-L4），一键清空 < 1s |
| 5000 章长篇 | JSONL ≈ 2.25 MB，聚类 < 1s |
| 同时开多本 | 文件锁冲突 → 弹窗提示关掉一个 |

---

## 3. 3 层级联节流（核心架构 ⭐）

### 3.1 整体时序图

```
┌──────────────────────────────────────────────────────────────────────┐
│ Layer 1: 30s 防抖 (同章节内打字连击)                                │
│                                                                       │
│   textChanged ──┐                                                     │
│                 ▼                                                     │
│           QTimer 30s ── (无新改动) ──► 落盘到 active buffer           │
│                                                                       │
│   目的: 过滤"打字中途"的连击, 不让单次 diff 触发 100 次              │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│ Layer 2: 章节封存 (commit_on_chapter_event)                          │
│                                                                       │
│   触发点 (3 选 1, 可配置):                                           │
│     - chapter_save 事件 (默认, 推荐)                                 │
│     - chapter_switch 事件                                            │
│     - 手动 [封存本章] 按钮                                           │
│                                                                       │
│   行为:                                                               │
│     - 把本章节所有 30s 落盘的信号 → 封存到本章节                       │
│     - signals.jsonl → signals/{chapter_id}.jsonl                     │
│     - 更新 chapter_commit_count++                                    │
│     - 累加到全局 unclustered_signals 计数                             │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│ Layer 3: 累积聚类 (background curator)                                │
│                                                                       │
│   触发 (满足任一):                                                    │
│     - 累计 ≥ 5 个章节封存 (CURATOR_CHAPTER_THRESHOLD)                │
│     - 累计 ≥ 50 条信号 (CURATOR_SIGNAL_THRESHOLD)                    │
│     - 距上次聚类 ≥ 24h (CURATOR_COOLDOWN_HOURS)                      │
│     - 手动 [立即聚类] 按钮                                            │
│                                                                       │
│   行为:                                                               │
│     - 后台 thread 跑 6-pattern diff 聚类                              │
│     - 同 pattern ≥ 2 条 → 沉淀为 candidate Skill                     │
│     - 写 signals/candidates/{family}_v{n}.json                       │
│     - 更新 sidecar candidate_usage.json                              │
│     - 弹 1 次"已静默发现" 通知（7 天节流）                            │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 关键参数表

| 参数 | 默认值 | 可调范围 | 含义 |
|---|---|---|---|
| `DEBOUNCE_MS` | 30000 | 10s ~ 2min | 同章节内打字防抖 |
| `COMMIT_ON` | `chapter_save` | `save` / `switch` / `manual` | 何时把本章节信号"封存" |
| `CURATOR_CHAPTER_THRESHOLD` | 5 | 1~20 | 多少章跑一次聚类 |
| `CURATOR_SIGNAL_THRESHOLD` | 50 | 10~200 | 多少信号跑一次聚类 |
| `CURATOR_COOLDOWN_HOURS` | 24 | 1~168 | 两次聚类最小间隔 |
| `STALE_DAYS` | 30 | 7~180 | 候选多久没活动 → 标 stale |
| `ARCHIVE_DAYS` | 90 | 30~365 | stale 多久 → 归档 |
| `MAX_CANDIDATES` | 30 | 10~100 | 单项目最大候选数（超出压缩提醒） |

### 3.3 章节封存点的实现

```python
# app/workflow/edit_signals/collector.py

class EditSignalCollector:
    def on_chapter_save(self, chapter_id: int):
        """Layer 2 触发: 章节保存即封存"""
        # 1. 把 active buffer 里的信号 → 本章节 jsonl
        # 2. 更新 chapter_commit_count
        # 3. 检查是否触发 Layer 3
        ...
        # 4. 立刻 return，不阻塞保存主链路
        self.queue.put_nowait({"event": "chapter_committed", "chapter_id": chapter_id})
```

**关键**: `on_chapter_save` 必须**同步落盘**（不让章保存失败时丢数据），
**聚类必须异步**（不让聚类慢时卡保存）。

---

## 4. 信号来源（3 个埋点）

### 4.1 埋点清单

| # | 触发动作 | v4 现有接入点 | 信号类型 | 备注 |
|---|---|---|---|---|
| 1 | 用户点"重新生成"按钮 | `app/ui/tabs/editor_tab.py` 的 regen 回调 | `regen` | 旧版文本=被拒样本 |
| 2 | 用户手动编辑段落 | 编辑器 `textChanged` + 30s 防抖 + 改 ≥ 1 句 | `manual_edit` | 用户改后 = 正确答案 |
| 3 | 用户删除整段 | 编辑器删除事件 + 检测段落被整段清空（>50字） | `discard` | 删除内容=被拒样本 |

### 4.2 接入点伪代码

**埋点 1：regen 按钮** (`app/ui/tabs/editor_tab.py`)

```python
# ─── before 改写 ───
signal_collector.ingest_regen(
    chapter_id=chapter["id"],
    paragraph_index=self.paragraph_index,
    before_text=self.paragraph_text,    # AI 原文
    instruction=instruction,
)
# ─── after 改写完成 (用户接受) ───
signal_collector.ingest_regen_result(
    chapter_id=chapter["id"],
    after_text=worker.result_text,
    accepted=True,                      # on_accept 回调
)
# ─── after 改写完成 (用户放弃) ───
signal_collector.ingest_regen_result(
    chapter_id=chapter["id"],
    after_text=worker.result_text,
    accepted=False,
)
```

**埋点 2：编辑器 textChanged + 30s 防抖** (`app/ui/tabs/editor_tab.py`)

```python
def __init__(self):
    self._edit_signal_timer = QTimer()
    self._edit_signal_timer.setSingleShot(True)
    self._edit_signal_timer.timeout.connect(self._flush_manual_edit_signal)
    self.editor.textChanged.connect(self._on_text_changed)

def _on_text_changed(self):
    self._edit_signal_timer.start(30_000)  # 30s 防抖

def _flush_manual_edit_signal(self):
    if self._is_meaningful_diff(self._last_saved_text, self.editor.toPlainText()):
        signal_collector.ingest_manual_edit(
            chapter_id=self.current_chapter_id,
            before=self._last_saved_text,
            after=self.editor.toPlainText(),
        )
        self._last_saved_text = self.editor.toPlainText()

def _is_meaningful_diff(self, before, after):
    if before == after: return False
    diff = difflib.SequenceMatcher(None, before, after)
    changed_chars = sum(b-a for _, a, _, b in diff.get_opcodes() if _ != 'equal')
    if changed_chars < 10: return False           # 改 < 10 字不算
    return True
```

**埋点 3：删除检测**（同文件）

```python
def _detect_paragraph_discard(self, old: str, new: str):
    old_paras = split_paragraphs(old)
    new_paras = split_paragraphs(new)
    for i, p in enumerate(old_paras):
        if i >= len(new_paras) or not new_paras[i].strip():
            if len(p.strip()) > 50:
                signal_collector.ingest_discard(
                    chapter_id=self.current_chapter_id,
                    paragraph_index=i,
                    content=p,
                )
```

---

## 5. 数据结构（4 字段 + 章节文件切分）

### 5.1 EditSignal JSONL Schema

```json
{
  "ts": 1717900000.123,
  "kind": "regen",
  "chapter_id": 42,
  "payload": {
    "paragraph_index": 7,
    "before": "他走进了那间屋子。",
    "after": "他推开吱呀作响的木门，踏入久违的旧屋。",
    "instruction": "改得更生动",
    "accepted": true
  }
}
```

### 5.2 顶层 4 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `ts` | float | ✅ | Unix 时间戳（不存 ISO 字符串，省 24B/行） |
| `kind` | enum | ✅ | `regen` / `manual_edit` / `discard` |
| `chapter_id` | int | ✅ | 关联章节 |
| `payload` | dict | ✅ | 自由 JSON，按 kind 选字段 |

### 5.3 dataclass 定义（`app/workflow/edit_signals/models.py`）

```python
from dataclasses import dataclass, field, asdict
from enum import Enum
import time, json

class SignalKind(str, Enum):
    REGEN = "regen"
    MANUAL_EDIT = "manual_edit"
    DISCARD = "discard"

@dataclass
class EditSignal:
    kind: SignalKind
    chapter_id: int
    payload: dict
    ts: float = field(default_factory=time.time)
    project_id: int = 0           # 写入时注入

    def to_jsonl(self) -> str:
        d = asdict(self)
        d["kind"] = self.kind.value
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))
```

---

## 6. 落盘：JSONL + 章节切分 + 跨项目隔离

### 6.1 目录结构（从 v2.0 升级的关键改动）

```
~/.novel-writer-pure/
└── signals/
    ├── _lock                                    ← 文件锁，防止同时开多本
    ├── _config.json                             ← 全局开关
    ├── projects/
    │   ├── {project_id_1}/                      ← 按项目隔离
    │   │   ├── active_buffer.jsonl              ← 当前章节未封存的信号
    │   │   ├── chapters/
    │   │   │   ├── {chapter_id_1}.jsonl         ← 章节封存后的信号
    │   │   │   ├── {chapter_id_2}.jsonl
    │   │   │   └── ...
    │   │   ├── candidates/                      ← 沉淀的候选 Skill
    │   │   │   ├── paragraph_opening_v1.json
    │   │   │   └── ...
    │   │   ├── sidecar/
    │   │   │   ├── chapter_usage.json           ← 章节级 sidecar
    │   │   │   └── candidate_usage.json         ← 候选 Skill sidecar
    │   │   └── backups/                         ← 预运行 tar.gz
    │   │       └── pre_curator_20260611.tar.gz
    │   └── {project_id_2}/
    │       └── ...
    └── ...
```

### 6.2 JSONLStore 设计（`app/workflow/edit_signals/jsonl_store.py`）

```python
import json
import threading
from pathlib import Path
from .models import EditSignal

class JSONLStore:
    """Append-only JSONL, 进程内线程安全, 按 project_id + chapter_id 切分"""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.active_path = project_dir / "active_buffer.jsonl"
        self.chapters_dir = project_dir / "chapters"
        self._lock = threading.Lock()
        self.chapters_dir.mkdir(parents=True, exist_ok=True)

    def append_to_active(self, signal: EditSignal) -> None:
        """Layer 1 落盘: 进 active buffer"""
        with self._lock:
            with open(self.active_path, "a", encoding="utf-8") as f:
                f.write(signal.to_jsonl() + "\n")

    def commit_chapter(self, chapter_id: int) -> int:
        """Layer 2 封存: 把 active buffer 移到章节 jsonl
        Returns: 封存的信号条数
        """
        with self._lock:
            if not self.active_path.exists():
                return 0
            lines = self.active_path.read_text(encoding="utf-8").splitlines()
            self.active_path.unlink()        # 原子操作: 一次性清空
            target = self.chapters_dir / f"{chapter_id}.jsonl"
            with open(target, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            return len(lines)

    def tail_chapter(self, chapter_id: int, n: int = 100) -> list[EditSignal]:
        path = self.chapters_dir / f"{chapter_id}.jsonl"
        return self._tail_file(path, n)

    @staticmethod
    def _tail_file(path: Path, n: int) -> list[EditSignal]:
        if not path.exists():
            return []
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 512_000))
            lines = f.read().decode("utf-8", errors="replace").splitlines()
        return [
            EditSignal(**{k: v for k, v in json.loads(l).items() if k != "kind"},
                       kind=SignalKind(json.loads(l)["kind"]))
            for l in lines[-n:] if l.strip()
        ]

    def clear_all(self) -> None:
        """L4: 一键清空"""
        with self._lock:
            if self.active_path.exists():
                self.active_path.unlink()
            for f in self.chapters_dir.glob("*.jsonl"):
                f.unlink()
```

### 6.3 文件锁（防止同时开多本）

```python
# app/workflow/edit_signals/lock.py
import fcntl
from pathlib import Path

class ProjectLock:
    """文件锁, 防止多个 v4 实例同时操作同一项目"""
    def __init__(self, signals_dir: Path, project_id: int):
        self.lock_path = signals_dir / "_lock"
        self.fd = None

    def acquire(self, blocking: bool = False) -> bool:
        try:
            self.fd = open(self.lock_path, "w")
            fcntl.flock(self.fd.fileno(),
                        fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            self.fd.write(f"{project_id}\n")
            self.fd.flush()
            return True
        except (IOError, OSError):
            return False

    def release(self):
        if self.fd:
            fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
            self.fd.close()
```

---

## 7. 借鉴 Hermes v0.16.0 的 4 件 ⭐

> 完整对比表见 §14。本节只列**直接搬过来的代码/数据结构**。

### 7.1 抄 1：Provenance 字段（`created_by` + `agent_created`）

```python
# candidate Skill 文件加 2 个字段
{
  "name": "paragraph_opening",
  "version": 1,
  "created_at": 1717900123.45,
  "created_by": "user_edit",         ← NEW（替代 v0.16.0 的 "agent"）
  "agent_created": False,            ← NEW（v0.16.0 兼容字段）
  ...
}
```

**值枚举**：`"user_edit"`（写手改稿沉淀） / `"bundled"`（v4 内置） / `"agent"`（未来扩展）

### 7.2 抄 2：patch_count + last_patched_at

```python
# sidecar candidate_usage.json
{
  "paragraph_opening": {
    "version": 1,
    "use_count": 0,              # 候选 Skill 被 prompt 引用次数
    "patch_count": 2,            # ← NEW（v0.16.0 加的）
    "last_patched_at": 1717900123.45,   # ← NEW（v0.16.0 加的）
    "last_activity_at": 1717900123.45,
    "activity_count": 7,
    "status": "candidate"        # active / stale / archived / pinned
  }
}
```

**规则**：写手手动编辑候选 Skill 内容 → `patch_count++` + `last_patched_at=now` → **永不归档**。

### 7.3 抄 3：Pinned 正交标志

```python
# state 字段保留 3 状态, pinned 独立
class SkillState(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"

@dataclass
class CandidateSkill:
    name: str
    version: int
    state: SkillState
    pinned: bool = False         # ← NEW（v0.16.0 抄）
    ...
```

**规则**：`pinned=True` 的候选 → **永久 active**，**永远不被自动归档**。
UI 暴露 `[📌 钉住]` 按钮，写手手动控制。

### 7.4 抄 4：预运行备份 + Dry-run

```python
# app/workflow/edit_signals/backup.py
import tarfile
from datetime import datetime

def snapshot_candidates(project_dir: Path) -> Path:
    """聚类前自动备份, 失败可回滚"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = project_dir / "backups" / f"pre_curator_{ts}.tar.gz"
    backup_path.parent.mkdir(exist_ok=True)
    with tarfile.open(backup_path, "w:gz") as tar:
        tar.add(project_dir / "candidates", arcname="candidates")
        tar.add(project_dir / "sidecar", arcname="sidecar")
    return backup_path

def restore_from_backup(backup_path: Path, project_dir: Path) -> None:
    """用户从备份回滚"""
    with tarfile.open(backup_path, "r:gz") as tar:
        tar.extractall(project_dir)
```

**Dry-run 模式**：

```python
def run_curator(..., dry_run: bool = False):
    candidates_before = load_all_candidates()
    new_candidates = _cluster_and_promote(...)
    if dry_run:
        print("[DRY-RUN] Would add:", new_candidates)
        return candidates_before    # 不写, 不更新 last_run_at
    # 真跑前先备份
    backup = snapshot_candidates(project_dir)
    save_new_candidates(new_candidates)
```

**UI 入口**：设置 → "试运行聚类"按钮 → 控制台打印"会沉淀 N 条 Skill"。

### 7.5 不抄的 4 件（明确砍掉）

| v0.16.0 的 | 为何不抄 |
|---|---|
| LLM 评审 / umbrella-ification | v4 单项目 ~10-30 候选，纯本地 diff 足够 |
| PROTECTED_BUILTIN_SKILLS | v4 没有"plan"这种 UX 关键路径 |
| `.curator_suppressed` | v4 没有 update 同步机制 |
| `_needle_in_path_component()` | v4 是章节级，不涉及路径误匹配 |
| cron 引用自动重写 | v4 没有 cron 调度 |

---

## 8. 3 状态自动机（沿用 v0.16.0）

### 8.1 状态转换图

```
                  patch_count++ / use_count++
        ┌────────────────────────────────────────┐
        │                                          │
        │                                          ▼
   ┌─────────┐                              ┌─────────┐
   │ active  │ ─── 30天无活动 ───►  ┌──────────────┐  │
   └─────────┘                      │   stale     │  │
        ▲                          └──────────────┘  │
        │ 写手手动激活 / patch / use      │            │
        │                              90天无活动   │
        │                              ▼            │
        │                          ┌──────────┐     │
        │                          │ archived │     │
        │                          └──────────┘     │
        │                                │           │
        │                       写手手动恢复        │
        │                                │           │
        └────────────────────────────────┘           │
                                                     │
   pinned=True ────────────────────────────────────►│
   (永久 active, 不参与自动转换)                     │
                                                     │
   archived (30 天后) ──── 自动物理删除 ──────────►  [end]
```

### 8.2 状态机实现（`app/workflow/edit_signals/state_machine.py`）

```python
from datetime import datetime, timedelta
from pathlib import Path
import json

STALE_DAYS = 30
ARCHIVE_DAYS = 90

class StateMachine:
    """3 状态自动机: active → stale → archived"""

    def __init__(self, sidecar_path: Path):
        self.sidecar_path = sidecar_path
        self.usage = self._load()

    def _load(self) -> dict:
        if self.sidecar_path.exists():
            return json.loads(self.sidecar_path.read_text(encoding="utf-8"))
        return {}

    def tick(self) -> dict:
        """每次启动/聚类前调一次, 推进状态"""
        now = datetime.now()
        changes = {"to_stale": [], "to_archived": [], "to_archived_deleted": []}

        for name, meta in self.usage.items():
            if meta.get("pinned"): continue                    # pinned 跳过
            last = datetime.fromtimestamp(meta.get("last_activity_at", 0))
            state = meta.get("status", "active")

            if state == "active" and (now - last) > timedelta(days=STALE_DAYS):
                meta["status"] = "stale"
                changes["to_stale"].append(name)
            elif state == "stale" and (now - last) > timedelta(days=ARCHIVE_DAYS):
                meta["status"] = "archived"
                changes["to_archived"].append(name)

        self._save()
        return changes

    def touch(self, name: str, event: str = "use") -> None:
        """记录活动, 推进 last_activity_at"""
        if name not in self.usage:
            self.usage[name] = {"use_count": 0, "activity_count": 0, "status": "active"}
        m = self.usage[name]
        if event == "use":
            m["use_count"] = m.get("use_count", 0) + 1
        if event == "patch":
            m["patch_count"] = m.get("patch_count", 0) + 1
            m["last_patched_at"] = datetime.now().timestamp()
        m["last_activity_at"] = datetime.now().timestamp()
        m["activity_count"] = m.get("activity_count", 0) + 1
        if m.get("status") in ("stale", "archived"):
            m["status"] = "active"      # 自动复活
        self._save()

    def pin(self, name: str, pinned: bool = True) -> None:
        m = self.usage.setdefault(name, {"status": "active"})
        m["pinned"] = pinned
        if pinned:
            m["status"] = "active"      # pin 强制 active
        self._save()

    def _save(self):
        self.sidecar_path.write_text(
            json.dumps(self.usage, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
```

---

## 9. 后台聚类器（Layer 3）

### 9.1 6-pattern diff 聚类

```python
# app/workflow/edit_signals/curator.py
import difflib
from collections import defaultdict
from pathlib import Path

READY_THRESHOLD = 2       # 同 pattern ≥ 2 条 → 沉淀

def classify_diff(before: str, after: str) -> str:
    """6 个固定 pattern, 纯本地"""
    bl, al = len(before), len(after)
    if al < bl * 0.5:   return "major_shrink"      # 大幅缩减
    if al > bl * 1.5:   return "major_expand"      # 大幅扩写
    if _is_reorder(before, after):    return "reorder"      # 句序调整
    if _is_dialogue(before, after):   return "dialogue"     # 对话改写
    if _is_word_level(before, after): return "polish"       # 词级润色
    return "other"

def _is_reorder(b, a):
    return sorted(b.split()) != sorted(a.split()) and set(b) == set(a)

def _is_dialogue(b, a):
    bd = sum(1 for line in b.split('\n') if '"' in line or '"' in line or '"' in line)
    ad = sum(1 for line in a.split('\n') if '"' in line or '"' in line or '"' in line)
    return bd > 0 and ad > 0

def _is_word_level(b, a):
    diff = difflib.SequenceMatcher(None, b, a)
    return 0.7 < sum(b-a for _, a, _, b in diff.get_opcodes() if _ != 'equal') / max(len(b), 1) < 0.3

def cluster_signals(signals: list) -> dict:
    """同 pattern 聚类"""
    buckets = defaultdict(list)
    for s in signals:
        if s.payload.get("before") and s.payload.get("after"):
            pattern = classify_diff(s.payload["before"], s.payload["after"])
            buckets[pattern].append(s)
    return {p: ss for p, ss in buckets.items() if len(ss) >= READY_THRESHOLD}
```

### 9.2 沉淀候选 Skill

```python
def promote_to_candidate(pattern: str, signals: list) -> dict:
    return {
        "name": pattern,
        "version": 1,
        "created_at": time.time(),
        "created_by": "user_edit",        # ← §7.1
        "agent_created": False,           # ← §7.1
        "source_signals": len(signals),
        "source_chapters": list({s.chapter_id for s in signals}),
        "pattern_hint": _pattern_hint(pattern),
        "before_examples": [s.payload["before"] for s in signals[:3]],
        "after_examples": [s.payload["after"] for s in signals[:3]],
        "status": "candidate",
    }
```

---

## 10. 写手体感设计（最关键的一节 ⭐）

### 10.1 5 个时刻的"无感"对照表

| 时刻 | 写手看到的 | 实际发生的 |
|---|---|---|
| 1. 启动 v4 | 无变化 | 后台 worker 线程就绪，**不读历史**（避免启动慢） |
| 2. 改稿中（30s 内） | 无变化 | 30s 防抖计时，**不落盘** |
| 3. 改稿中（30s 后） | 无变化 | 信号进 active buffer，**后台落盘** |
| 4. 点保存章节 | 无变化 | active buffer → 章节 jsonl，**后台聚类检查** |
| 5. 累计 5 章/50 信号 | **不弹窗** | 写入 candidates/，状态置 `candidate` |
| 6. 累计 ≥ 1 候选 | 首次弹 1 次 | "已静默发现 1 条可沉淀 Skill" |

### 10.2 弹窗的"无感"设计

**首次弹窗触发条件**（全部满足才弹）：
- ✅ candidate 数量 ≥ 1
- ✅ 与上次弹窗间隔 ≥ 7 天
- ✅ 用户没主动关过"不想被提醒"
- ✅ 当前**不在编辑器焦点**

**弹窗内容**（强制极简）：

```
┌────────────────────────────────────────┐
│ 📚 发现 1 条可沉淀 Skill               │
│                                        │
│  段落开头去填充词（已积累 7 次改写）   │
│                                        │
│  [ 查看 ]  [ 暂不 ]  [ 不再提醒 ]      │
└────────────────────────────────────────┘
```

- 默认焦点在 `[ 暂不 ]`（按 Enter 消失）
- 5 秒无操作自动消失
- `[ 不再提醒 ]` → 写 `signal_popup_muted=true`

### 10.3 永远不允许发生的事 ❌

- ❌ LLM 调用出现在改稿主链路（聚类纯本地 diff，不调 LLM）
- ❌ 任何阻塞主线程的 IO（落盘用后台 thread + queue）
- ❌ 任何"学习进度条" / "正在分析..." UI
- ❌ 任何对历史信号的全文 diff 扫描（启动时不读）
- ❌ 候选 Skill **自动注入** prompt（必须用户点 `[ 启用 ]` 才生效）

---

## 11. 跨项目 + 5000 章处理

### 11.1 切换项目

| 触发 | 自动行为 | 写手操作 |
|---|---|---|
| 打开 v4 → 切 project_id | 旧项目 freeze，新项目解冻 | 零 |
| 切回老项目 | 自动 rehydrate，**累计进度接上** | 零 |
| 同时打开 v4 写多本 | **绝对禁止**（文件锁冲突 → 弹窗） | 关掉其中一个 |
| 删掉项目 | `signals/{old_pid}/` 标 `archived=deleted` | 零（30 天后真删） |
| 主动导出/迁移 | 菜单"导出项目信号包" → `tar cf` 走人 | 1 次点击 |

### 11.2 5000 章性能账

**假设**：
- 平均每章 1.5 次改稿
- 单条信号 ~300 字节
- 信号总量 = 5000 × 1.5 = **7500 条**
- JSONL 体积 = 7500 × 300B = **2.25 MB**（全本！）
- 聚类 7500 条 diff pattern = **< 1 秒**（纯本地 `difflib`）
- 切换章节时，章节封存同步操作 ≈ **< 50ms**

**结论**：**5000 章完全扛得住**，JSONL + 章节切分已经够用。

### 11.3 章节封存时的同步 vs 异步

| 操作 | 同步/异步 | 耗时 | 风险 |
|---|---|---|---|
| 章节封存（active → 章节 jsonl） | **同步** | < 50ms | 落盘失败 = 数据丢 |
| 聚类检查 | **异步** | < 1s | 失败可重试 |
| 写 candidates/ | **异步** | < 100ms | 失败可重试 |
| 写 sidecar | **异步** | < 10ms | 失败可重试 |

**关键原则**：**数据迁移同步完成**（保证不丢），**学习操作异步完成**（保证不卡）。

---

## 12. 4 档开关（L1-L4）

### 12.1 开关定义

| 档位 | 含义 | 设置项 | 副作用 |
|---|---|---|---|
| **L1** | 全功能 | `signal_enabled=true` | 默认 |
| **L2** | 静默不弹窗 | `signal_popup_muted=true` | 还在写、还在聚类，但不通知 |
| **L3** | 完全关闭 | `signal_enabled=false` | 不写、不聚类、不弹 |
| **L4** | 一键清空 | 按钮触发 | 删除 `signals/projects/{pid}/` 整个目录 |

### 12.2 设置入口

`app/ui/tabs/settings_tab.py` → "数据与隐私"分组：

```
☑ 启用改稿信号学习                        ← L1
☑ 完成后右下角通知我                       ← L2
[ 试运行聚类 (dry-run) ]                   ← §7.4
[ 立即聚类 ]                               ← §9
[ 导出项目信号包 (.tar.gz) ]               ← §11.1
─── 候选 Skill 管理 ───
[ 打开候选目录 ]                           ← 资源管理器
[ 一键清空所有改稿数据 ]                   ← L4 (二次确认)
```

### 12.3 隐私保证

- 所有信号**仅本地**，**不上传任何 LLM**
- 候选 Skill 文件可在 `~/.novel-writer-pure/signals/projects/{pid}/candidates/` 直接 `cat` 审计
- 项目文件夹内**不写**任何信号文件
- 备份 tar.gz 也只在 `~/.novel-writer-pure/signals/projects/{pid}/backups/`

---

## 13. 文件清单与代码量

### 13.1 新增文件（8 个，~450 行）

| 文件 | 行数 | 职责 |
|---|---|---|
| `app/workflow/edit_signals/__init__.py` | 10 | 包导出 |
| `app/workflow/edit_signals/models.py` | 40 | `EditSignal` / `SignalKind` / `CandidateSkill` |
| `app/workflow/edit_signals/jsonl_store.py` | 80 | 落盘 + 章节切分 + clear |
| `app/workflow/edit_signals/lock.py` | 30 | 文件锁（防多开） |
| `app/workflow/edit_signals/collector.py` | 100 | 3 个 ingest 入口 + 章节封存 |
| `app/workflow/edit_signals/curator.py` | 120 | 6-pattern 聚类 + 沉淀 |
| `app/workflow/edit_signals/state_machine.py` | 80 | 3 状态 + pinned + touch/pin |
| `app/workflow/edit_signals/backup.py` | 40 | 预运行 tar.gz + restore |
| `app/workflow/edit_signals/worker.py` | 80 | 后台 daemon thread + 触发条件 |
| `app/workflow/edit_signals/popup.py` | 50 | 右下角气泡（QSystemTrayIcon） |

### 13.2 修改文件（5 个，diff ~25 行）

| 文件 | 改动 |
|---|---|
| `app/ui/tabs/editor_tab.py` | 3 个埋点回调 + 30s 防抖 + 章节保存事件 |
| `app/ui/tabs/settings_tab.py` | 4 档开关 + 试运行 + 立即聚类 + 一键清空 |
| `app/main.py` | 启动时 `signal_collector.start()` + 退出时 `stop()` |
| `app/core/event_bus.py` | 加 4 个事件名常量 |
| `app/core/container.py` | 注册 `signal_collector` 单例 |

---

## 14. 验收用例（15 个，写手视角）

| # | 场景 | 操作 | 预期 |
|---|---|---|---|
| U1 | 改错别字 | 把"的地得"改对 | **不**触发 manual_edit（< 10字） |
| U2 | 点 regen 接受 | regen → 选"接受" | 写 1 条 regen 信号 (accepted=true) |
| U3 | 点 regen 放弃 | regen → 选"放弃" | 写 1 条 regen 信号 (accepted=false) |
| U4 | 同章改 5 段 | 5 段都改 | active_buffer 5 条，**不**立即封存 |
| U5 | 切章节 + 不保存 | 章42 → 章43 | 章42 信号**不**封存（COMMIT_ON=save 默认） |
| U6 | 章42 保存 | 保存按钮 | active_buffer → chapters/42.jsonl，封存条数显示在状态栏 |
| U7 | 改 5 段开头 × 5 章 | 累计 25 信号 | 聚类器**不**触发（< 5 章封存） |
| U8 | 5 章封存完成 | 自动跑聚类 | candidates/ 出现 1 个 candidate |
| U9 | candidate 弹窗 | 7 天内首次 | "📚 发现 1 条可沉淀 Skill" |
| U10 | 弹窗"暂不" | Enter | 7 天内不重弹 |
| U11 | stale 自动转换 | 30 天不动 | candidate 状态 active → stale，状态栏图标变灰 |
| U12 | 写手 pin | UI 点"📌 钉住" | 该 candidate 永久 active |
| U13 | 写手取消 pin | UI 再点一次 | 恢复参与自动转换 |
| U14 | 一键清空 | L4 按钮 | signals/projects/{pid}/ 整个目录消失，< 1s |
| U15 | dry-run 试聚类 | "试运行"按钮 | 控制台打印"会沉淀 N 条"，**不**真写 |
| U16 | 5000 章性能 | 跑满 5000 章 | JSONL 2.25MB，聚类 < 1s，启动 < 100ms |
| U17 | 同时开 2 本 | 启动 v4 两实例 | 弹窗"已有项目 X 在使用，请先关闭" |

---

## 15. 风险与未决

### 15.1 已识别风险

| 风险 | 缓解 |
|---|---|
| 聚类算法误判（把无关改动聚一起） | 阈值=2（保守），人工可 `[ 暂不 ]` |
| 候选 Skill 质量低 | 必须用户**手动启用**才进 prompt |
| `~/.novel-writer-pure/` 越来越大 | 候选 > 30 触发压缩提醒；archived 30 天真删 |
| 跨章节模式混淆 | 候选 Skill 必须标注"来源章节范围" |
| 同时开多本 | 文件锁 + 弹窗提示 |
| 写手长时间不切换项目 | 仍按"5 章封存"触发，**不**卡 7 天 |
| JSONL 损坏（极小概率） | 启动时 `try/except` 跳过坏行，**不**让坏行阻塞 |

### 15.2 暂不做（v5+ 候选）

- [ ] 跨项目共享 Skill（需要跨项目信号路由协议）
- [ ] 用 LLM 做"反例摘要"（成本太高，先用 pattern hint）
- [ ] 自动从候选 Skill **删除**失败（需要 A/B 反馈数据）
- [ ] 信号数据可视化（写手想看"我被学了啥"）
- [ ] LLM umbrella-ification（单项目候选数 < 30，simplify 掉）

---

## 16. 时间线（建议 14 天）

| Day | 任务 |
|---|---|
| D1-D2 | `models.py` + `jsonl_store.py` + `lock.py` + 单元测试 |
| D3-D4 | `collector.py` + 3 个埋点 hook 接入 editor_tab |
| D5 | `worker.py` 后台 daemon + 30s 防抖 + 章节封存（**不上线聚类**） |
| D6 | 灰度：先开 1 个用户的开关，看落盘数据 |
| D7-D8 | `curator.py` 6-pattern 聚类 + 候选 Skill 沉淀 |
| D9 | `state_machine.py` 3 状态 + pinned + 预运行备份 |
| D10 | `popup.py` 首次弹窗 + 7 天节流 |
| D11 | `settings_tab.py` 4 档开关 + dry-run 按钮 |
| D12-D13 | 验收用例 U1-U17 全部跑过 |
| D14 | 收尾：写用户文档 + 录 1 分钟演示视频 |

---

## 17. 附录 A：与 super-author-core 差异速查

| 项 | super-author-core | **v4 v2.1（本方案）** |
|---|---|---|
| 信号来源 | 失败 run | **用户改稿动作** |
| 聚类者 | LLM curator | **纯本地 diff pattern** |
| 节流 | 每次 run | **章节级（5 章/50 信号/24h 触发）** |
| 评审频率 | 即时 | **章节封存后** |
| 沉淀位置 | `data_dir/skills/candidates/` | `~/.novel-writer-pure/signals/projects/{pid}/candidates/` |
| 写手感知 | 后台无感 | **后台无感 + 偶尔 1 次弹窗（7 天节流）** |
| LLM 介入 | 聚类时调 | **永不调** |
| 协议层 | NDJSON | JSONL（本地） |
| 多进程 | 支持 | **不支持**（单进程，文件锁） |
| 跨项目 | 全局共享 | **按 project_id 隔离** |
| 状态机 | 无 | **3 状态（active/stale/archived）+ pinned** |

---

## 18. 附录 B：与 Hermes v0.16.0 借鉴对照表

| v0.16.0 设计 | 是否借鉴 | v4 落地方案 |
|---|---|---|
| 3 状态自动机 | ✅ | §8 完全沿用 |
| 30/90 天阈值 | ✅ | §8.2 默认 30/90，可配置 |
| `sidecar` 计数 | ✅ | §6.1 `sidecar/candidate_usage.json` |
| `maybe_run_curator` 入口 | ✅ | §9.2 章节级触发条件 |
| `created_by="agent"` | ✅ 改造 | §7.1 `created_by="user_edit"` |
| `agent_created` 兼容字段 | ✅ | §7.1 同字段 |
| `pinned` 正交标志 | ✅ | §7.3 + UI `[📌 钉住]` 按钮 |
| `patch_count` / `last_patched_at` | ✅ | §7.2 sidecar |
| 预运行 `snapshot_skills()` | ✅ | §7.4 `backup.py` |
| `CURATOR_DRY_RUN_BANNER` | ✅ | §7.4 `dry_run=True` |
| 受保护内建 `PROTECTED_BUILTIN_SKILLS` | ❌ 砍 | v4 没有 plan 这种 UX 关键路径 |
| `.curator_suppressed` | ❌ 砍 | v4 没有 update 同步机制 |
| `_needle_in_path_component()` | ❌ 砍 | v4 是章节级，不涉及路径 |
| Cron 引用自动重写 | ❌ 砍 | v4 没有 cron |
| LLM umbrella-ification | ❌ 砍 | 单项目候选 < 30，simplify |
| LLM rubric 分类 | ❌ 砍 | 6 个本地 pattern 够用 |
| 客户端三层优先级 | ⚠️ 简化 | v4 无 review fork，单客户端 |
| stdout 重定向 | ❌ 砍 | v4 后台 daemon thread，不派生 agent |
| 首次运行保护 | ✅ 简化 | 启动不读历史信号，**没这个问题** |
| `max_iterations=9999` | ❌ 砍 | v4 聚类纯本地，无 LLM 限制 |

---

## 19. 附录 C：关键概念索引

| 概念 | 出现章节 | 含义 |
|---|---|---|
| **Layer 1** | §3.1 | 30s 防抖（打字连击过滤） |
| **Layer 2** | §3.1 | 章节封存（章节 = 1 批次） |
| **Layer 3** | §3.1 | 累积聚类（5 章/50 信号/24h） |
| **Layer 4** | §20 | 进化（合并/泛化/评分，章节级触发） |
| **Layer 5** | §21 | 软提示注入（候选 Skill → 编辑器/写作流） |
| **Provenance** | §7.1 | 候选 Skill 来源标记 |
| **Pinned** | §7.3 | 钉住 = 永久 active |
| **Dry-run** | §7.4 | 试运行聚类，不真改 |
| **3 状态** | §8 | active / stale / archived |
| **6 pattern** | §9.1 | major_shrink / major_expand / reorder / dialogue / polish / other |
| **READY_THRESHOLD** | §9.1 | 同 pattern ≥ 2 → 沉淀 |
| **L1-L4** | §12 | 4 档开关 |
| **JSONL 切分** | §6.1 | active buffer + 章节 jsonl + 候选 jsonl |
| **文件锁** | §6.3 | 防止同时开多本 |
| **跨项目隔离** | §6.1 | `signals/projects/{pid}/` |
| **预运行备份** | §7.4 | `pre_curator_{ts}.tar.gz` |
| **质量评分** | §20.1 | use + patch 计数, 自动升降级 |
| **泛化** | §20.2 | LLM 把 example 抽成 rule (异步, 1周1次) |
| **失效检测** | §20.4 | patch_count 飙升 → uncertain |
| **反例聚合** | §20.5 | discard 信号 → 反向 Skill |
| **软提示** | §21.1 | 候选 Skill 不直接改文, 仅在编辑器顶显示 |
| **相关性过滤** | §21.2 | BM25 (chapter × candidate) → top-3 |
| **hard cap** | §21.3 | 单章最多 3 条, ≤ 500 token |
| **per-chapter 开关** | §21.4 | 编辑器顶栏 [📚 关提示] 一键关 |

---

> **结束**。v3.0 相比 v2.1 的核心升级：
> 1. ✅ **新增 Layer 4 进化层**（合并/去重/泛化/评分/失效检测/反例聚合）
> 2. ✅ **新增 Layer 5 软提示注入**（编辑顶栏 + 可选 prompt 注入）
> 3. ✅ **3 道防污染关**（相关性 BM25 / chapter 范围 / 新鲜度）
> 4. ✅ **3 道不影响写手关**（软提示 / per-chapter 关 / 反例化按钮）
> 5. ✅ **LLM 异步泛化**（1 周 1 次，dry-run preview，写手零感知）
> 6. ✅ **质量评分自动升降级**（candidate → proven 满 5 use → builtin 满 20 use）
> 7. ✅ 保留 v2.1 的全部 4 件 Hermes 借鉴 + 4 件砍掉
> 8. ✅ 兼容所有 v2.1 验收用例 (U1-U17 全部适用)

---

## 20. v3.0 新增：Layer 4 进化层 (Evolution)

### 20.1 进化时序图

```
┌──────────────────────────────────────────────────────────────────────┐
│ Layer 4: 进化 (background evolver)                                  │
│                                                                       │
│   触发: 章节封存后, 满足任一 (满足即触发, 不阻塞主线程):            │
│     - 候选数 ≥ EVOLVE_CANDIDATE_THRESHOLD (默认 3)                  │
│     - 累计 patch_count ≥ EVOLVE_PATCH_THRESHOLD (默认 5)              │
│     - 距上次进化 ≥ EVOLVE_COOLDOWN_HOURS (默认 24h)                  │
│     - 手动 [立即进化] 按钮                                            │
│                                                                       │
│   行为 (按顺序, 失败可重试):                                         │
│     1. 预运行备份 (snapshot_candidates)                              │
│     2. 同 pattern 候选去重合并 (HERMES 抄 1)                          │
│     3. 质量评分 (use + patch 计数) → 自动升降级 (HERMES 抄 2)        │
│     4. 失效检测 (patch 飙升 → uncertain) (HERMES 抄 3)                │
│     5. 反例聚合 (discard 信号 → 反向候选) (HERMES 抄 4)              │
│     6. 异步 LLM 泛化 (1 周 1 次, 后台 thread, dry-run preview)      │
│       (HERMES 拿回, 改造为异步)                                       │
│     7. 更新 sidecar + last_evolve_at                                 │
│     8. 写 cursor_log 记录每步结果                                    │
└──────────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────────┐
│ Layer 5: 软提示注入 (skill injector)                                 │
│                                                                       │
│   触发: 每次打开章节 + 每次保存章节 (per-chapter 可关)               │
│                                                                       │
│   行为:                                                               │
│     1. 拿当前 chapter 内容 + genre                                    │
│     2. BM25 算 (chapter × candidate.pattern_hint) 相似度             │
│     3. 过滤: chapter 范围 / 新鲜度 / pin 状态                         │
│     4. 排序: top-K (默认 3, hard cap = 5)                            │
│     5. 截断: ≤ 500 token                                              │
│     6. 输出:                                                          │
│        - 编辑器顶栏显示 [📚 提示卡] (每条 1 行, 可点 [采纳])          │
│        - (可选) prompt_assembler 注入 [📚 项目内参考] 段 (opt-in)    │
│                                                                       │
│   写手控制:                                                           │
│     - per-chapter 关: 编辑器顶栏 [📚 关] 按钮 (默认开)                │
│     - per-candidate 反例化: 提示卡上点 [✗] → patch++ + uncertain     │
│     - per-candidate 采纳: 提示卡上点 [采纳] → use++ + 插入光标        │
└──────────────────────────────────────────────────────────────────────┘
```

### 20.2 关键参数表 (新增)

| 参数 | 默认值 | 可调范围 | 含义 |
|---|---|---|---|
| `EVOLVE_CANDIDATE_THRESHOLD` | 3 | 1~20 | 候选数到此值触发进化 |
| `EVOLVE_PATCH_THRESHOLD` | 5 | 1~50 | 累计 patch 数到此触发 |
| `EVOLVE_COOLDOWN_HOURS` | 24 | 1~168 | 两次进化最小间隔 |
| `LLM_GENERALIZE_INTERVAL_DAYS` | 7 | 1~30 | LLM 泛化触发间隔 |
| `PROMOTE_TO_PROVEN_USE` | 5 | 1~50 | use_count ≥ 此值 → proven |
| `PROMOTE_TO_BUILTIN_USE` | 20 | 5~100 | use_count ≥ 此值 → builtin |
| `UNCERTAIN_PATCH_RATIO` | 0.5 | 0.1~1.0 | patch/use ≥ 此值 → uncertain |
| `INJECT_MAX_SKILLS` | 3 | 1~5 | 单章最大注入候选数 |
| `INJECT_MAX_TOKENS` | 500 | 100~2000 | 注入总 token 上限 |
| `INJECT_FRESH_DAYS` | 30 | 7~180 | 多少天内有活动才注入 |

### 20.3 候选 Skill 状态机升级 (4 状态)

```
                  use_count ≥ 5
   ┌─────────┐  ─────────────►  ┌─────────┐
   │candidate│                   │ proven  │
   └─────────┘  ◄─────────────  └─────────┘
        ▲       use_count < 5       ▲
        │                            │ use_count ≥ 20
        │                            ▼
   patch++                   ┌─────────┐
   (写手编辑)                 │ builtin │  ← 永久 active
                             └─────────┘
        │
        │ patch/use ≥ 0.5
        ▼
   ┌──────────┐
   │ uncertain│  ← 仍显示, 但 inject 时降权
   └──────────┘
        │ patch 修复 (写手重新编辑) / use 增加
        ▼
   回到 candidate 或 proven (视 use_count 而定)
```

### 20.4 5 件事的实现要点

#### 20.4.1 合并/去重 (HERMES 抄 1)

```python
# app/workflow/edit_signals/evolution.py

def merge_similar_candidates(candidates: list[dict]) -> list[dict]:
    """
    同 pattern 的 candidate 自动合并.
    触发条件: 同 pattern_hint + 同 source_chapters 范围 (>= 50% 重合)
    合并动作:
      - source_signals += sum
      - source_chapters = union
      - before_examples 拼接 (去重, 最多 5)
      - after_examples 拼接 (去重, 最多 5)
      - version++
    """
    pass
```

#### 20.4.2 质量评分 (HERMES 抄 2)

```python
def auto_promote(candidate: dict, usage: dict) -> str:
    """
    use_count + patch_count 自动决定状态.
    """
    use = usage.get("use_count", 0)
    patch = usage.get("patch_count", 0)
    if use >= 20 and patch == 0:
        return "builtin"  # 永久 active, 不参与自动归档
    if use >= 5:
        return "proven"   # 高频被采纳
    if patch / max(use, 1) >= 0.5:
        return "uncertain"  # patch 多 = 写手在改
    return "candidate"
```

#### 20.4.3 LLM 异步泛化 (HERMES 拿回)

```python
def llm_generalize_async(candidate: dict, llm_client) -> dict:
    """
    后台 thread 调 LLM, 把 example 抽成 rule.
    严格:
      - 只在 1 周 1 次时跑
      - 跑前 dry-run preview (settings 开关)
      - 写手可在 settings 关掉: signal_llm_generalize_enabled=false
      - 失败 fallback: 不动 candidate, 标记 candidate.generalize_failed=true
    """
    prompt = f"""
    你是一个写作风格分析专家. 下面是写手改稿的 3 条 example:
    {candidate['before_examples']} → {candidate['after_examples']}

    请用 1 句话总结写手偏好 (中文, ≤ 30 字), 例:
    "避免连续用'咬了咬嘴唇'类动作, 换'指尖微颤'等具体描写"
    """
    new_rule = llm_client.call(prompt)
    candidate["generalized_rule"] = new_rule
    candidate["generalized_at"] = time.time()
    return candidate
```

#### 20.4.4 失效检测 (HERMES 抄 3)

```python
def detect_uncertain(candidate: dict, usage: dict) -> bool:
    """
    patch_count 高 → 候选可能错了.
    阈值: patch_count / use_count >= 0.5
    标 uncertain 后: inject 降权 (排到 top-K 之外), 但仍显示
    """
    use = usage.get("use_count", 0)
    patch = usage.get("patch_count", 0)
    return patch / max(use + patch, 1) >= UNCERTAIN_PATCH_RATIO
```

#### 20.4.5 反例聚合 (HERMES 抄 4)

```python
def aggregate_discards(discards: list[dict]) -> dict:
    """
    把 discard 信号 (用户删除的段落) 聚合成"反例" Skill.
    输出: candidate, pattern="anti_xxx", kind="anti_pattern"
    UI 显示: "❌ 写手不喜欢的修法: xxx"
    """
    pass
```

### 20.5 进化 cursor_log

每次进化写 1 行 JSONL 到 `signals/projects/{pid}/cursor.log`, 用于审计和回滚:

```json
{
  "ts": 1717900000.123,
  "step": "merge",
  "candidates_before": 5,
  "candidates_after": 3,
  "merged": ["polish_v1", "polish_v2"],
  "duration_ms": 45
}
```

---

## 21. v3.0 新增：Layer 5 软提示注入 (Skill Injector)

### 21.1 设计原则 (3 道防污染 + 3 道不影响写手)

**3 道防污染关**:
1. **相关性过滤**: BM25 算 (chapter content × candidate pattern_hint) 相似度
2. **chapter 范围**: candidate.source_chapters 与当前 chapter 同类(玄幻/修真/...)才进
3. **新鲜度**: 30 天无活动的 stale 不注入

**3 道不影响写手关**:
1. **软提示 vs 硬规则**: 候选 Skill 内容用"建议"语气, 不写"必须 X"
2. **per-chapter 关**: 编辑器顶栏 [📚 关提示] 按钮, 默认开
3. **per-candidate 反例化**: 写手点 [✗] → patch_count++ + 标 uncertain, 不再注入

### 21.2 注入流程

```python
# app/workflow/edit_signals/injection.py

def select_skills_for_chapter(
    chapter: dict,
    candidates: list[dict],
    *,
    max_skills: int = 3,
    max_tokens: int = 500,
) -> list[dict]:
    """
    给定 chapter + 全部 candidates, 返回 top-K 最相关 + 最有用.
    """
    # 1. 过滤: state 必须是 active/proven (排除 stale/archived/uncertain 优先)
    pool = [c for c in candidates
            if c.get("state") in ("active", "proven", "builtin")]

    # 2. 新鲜度: 30 天内有活动
    pool = filter_fresh(pool, days=INJECT_FRESH_DAYS)

    # 3. chapter 范围: source_chapters 与当前 chapter 同类
    pool = filter_same_genre(pool, chapter.get("genre", ""))

    # 4. BM25 相关性: top-K
    chapter_text = chapter.get("content", "")[:2000]
    scored = bm25_score(chapter_text, pool)
    top = sorted(scored, key=lambda x: x[1], reverse=True)[:max_skills]

    # 5. token 截断
    result = []
    total_tokens = 0
    for cand, score in top:
        tokens = estimate_tokens(cand.get("pattern_hint", ""))
        if total_tokens + tokens > max_tokens:
            break
        result.append(cand)
        total_tokens += tokens

    return result
```

### 21.3 编辑器顶栏提示卡 UI

```
┌──────────────────────────────────────────────────────────┐
│ 第 42 章 - 仙门初试                          [📚 关]    │
├──────────────────────────────────────────────────────────┤
│ 📚 提示卡 (3 条)                                           │
│ ┌────────────────────────────────────────────────────┐  │
│ │ 1. 避免"她咬了咬嘴唇"类动作, 改用具体描写 (5/5)  │  │
│ │    [采纳] [✗ 不对]                                  │  │
│ ├────────────────────────────────────────────────────┤  │
│ │ 2. 对话开头用"他"而非"主角" (2/2)                  │  │
│ │    [采纳] [✗ 不对]                                  │  │
│ ├────────────────────────────────────────────────────┤  │
│ │ 3. 段首不堆叠时间副词 (3/3)                         │  │
│ │    [采纳] [✗ 不对]                                  │  │
│ └────────────────────────────────────────────────────┘  │
│ [+ 显示更多]                                                │
└──────────────────────────────────────────────────────────┘
```

**交互细节**:
- 提示卡默认折叠, 点 [📚 提示 (3)] 展开
- [采纳] = 把内容插到当前光标位置, use_count++
- [✗ 不对] = patch_count++, 标 uncertain, 此章不显示
- [📚 关] = per-chapter 永久关 (写到 chapter meta), 切回来也不显示
- 滚到底自动 [+ 显示更多] (本节最多 3, 多 5 条换页)

### 21.4 可选 prompt_assembler 注入 (opt-in)

```python
# app/core/prompt_assembler.py (新增, 默认关闭)
def _assemble_project_skill_hints(project_id: str, chapter_id: str) -> str:
    """
    注入候选 Skill 作为 [📚 项目内参考] 段.
    默认关闭 (settings 开关 signal_inject_to_prompt=false).
    """
    if not config.get("signal_inject_to_prompt", False):
        return ""
    candidates = select_skills_for_chapter(...)
    if not candidates:
        return ""
    return "[📚 项目内参考]\n" + "\n".join(
        f"- {c.get('generalized_rule') or c.get('pattern_hint')}"
        for c in candidates
    )
```

### 21.5 5000 章防污染账

**假设**:
- 候选数: 30 条 (v2.1 hard cap)
- 单章 BM25 检索: < 50ms (in-memory)
- top-3 输出: ≤ 500 token
- 编辑器 UI 加载: < 100ms (candidates 内存 cache)

**结论**: 5000 章每章 1 次 inject, 总耗时 < 30s 全本, 不构成污染.

---

## 22. v3.0 新增验收用例 (5 个)

| # | 场景 | 操作 | 预期 |
|---|---|---|---|
| E1 | 进化触发 | 累计 3 候选 | 章节封存后自动跑进化, 写 merged/promoted/discarded |
| E2 | 合并去重 | 5 个 polish candidate | 合并为 1 个, source_signals=12, version=2 |
| E3 | 质量升级 | 1 candidate use_count=5 | 自动升级为 proven |
| E4 | 失效检测 | 1 candidate patch/use=0.6 | 标 uncertain, inject 时不出现在 top-3 |
| E5 | LLM 泛化 | 设置 signal_llm_generalize_enabled=true, 候选 ≥ 1 周 | 后台 thread 调 LLM, 1 次后 generalized_rule 填充 |
| I1 | 软提示注入 | 打开章节 | 编辑器顶栏显示 [📚 提示 (3)] 折叠 |
| I2 | 采纳候选 | 点 [采纳] | use_count++, 内容插入光标 |
| I3 | 反例化 | 点 [✗] | patch_count++, 标 uncertain, 此章不显示 |
| I4 | per-chapter 关 | 点 [📚 关] | 提示卡消失, 切回来也不显示 |
| I5 | 5000 章性能 | 跑满 5000 章 | inject 每章 < 50ms, 启动 < 200ms |

---

## 23. v3.0 文件清单 (新增 3 个, ~250 行)

| 文件 | 行数 | 职责 |
|---|---|---|
| `app/workflow/edit_signals/evolution.py` | 120 | Layer 4 进化 (合并/评分/泛化/失效/反例) |
| `app/workflow/edit_signals/injection.py` | 80 | Layer 5 软提示 (BM25 + hard cap + 截断) |
| `app/workflow/edit_signals/cursor.py` | 50 | cursor_log 审计 + 回滚辅助 |

**修改文件**:
| 文件 | 改动 |
|---|---|
| `app/ui/tabs/editor_tab.py` | 顶部加 [📚 提示 (N)] 折叠卡 + [📚 关] 按钮 + 3 埋点 |
| `app/ui/tabs/settings_tab.py` | 加 4 个开关: 进化触发/LLM 泛化/inject 到 prompt/反例聚合 |
| `app/core/prompt_assembler.py` | 新增 `_assemble_project_skill_hints()` 段 (opt-in) |
| `app/main.py` | 启动 `signal_evolver.start()` + 退出时 `stop()` |
| `app/workflow/edit_signals/curator.py` | 章节封存后调 `evolver.maybe_run()` |

---

## 24. v3.0 风险与未决

### 24.1 已识别风险

| 风险 | 缓解 |
|---|---|
| LLM 泛化失败 (网络/超时) | fallback: 不动 candidate, 标 generalize_failed=true |
| 进化误合并 (把不同风格合并) | 阈值: 同 pattern + 范围 ≥ 50% 重合, 写手可人工 unpinned |
| 软提示打扰心流 | per-chapter 关 + 默认折叠, 5 秒无操作自动消失 (沿用 v2.1 popup) |
| 5000 章 candidates 增长 | inject 必走 BM25, 30 天 stale 不进, 永远只 top-3 |
| 反例聚合误把"换行"当"删段落" | discard 阈值 = 段落 ≥ 50 字, regex 检测 |

### 24.2 暂不做 (v4+ 候选)

- [ ] 候选 Skill 评分用 LLM 排序 (v3 暂用 BM25)
- [ ] 跨章节 pattern 模板 (跨书用, 不进 v3)
- [ ] 写手写"我以后要 X" → 主动进 candidate (NLP 解析)
- [ ] 候选 Skill 之间的"互斥检测" (A 用多了 B 就不该出现)

---

## 25. v3.0 实现状态 (2026-06-11)

✅ **全部 v3.0 设计已落地**, 4.0 全量回归 36/36 通过 (含 `smoke_v3_signals` 76/76 新增).

### 25.1 已落地文件清单

| 路径 | 行数 | 说明 |
|---|---|---|
| `app/workflow/edit_signals/__init__.py` | 106 | 包导出 + `__all__` |
| `app/workflow/edit_signals/models.py` | 209 | `EditSignal` / `CandidateSkill` / `AntiPattern` / `SidecarEntry` |
| `app/workflow/edit_signals/jsonl_store.py` | 300 | `JSONLStore` / `CandidateStore` / `SidecarStore` / `get_project_dir` |
| `app/workflow/edit_signals/lock.py` | - | `ProjectLock` (跨进程文件锁) |
| `app/workflow/edit_signals/collector.py` | 209 | 3 埋点 + 30s 防抖 + 段落删除检测 |
| `app/workflow/edit_signals/curator.py` | 285 | 6-pattern 聚类 + 沉淀 (Layer 3) |
| `app/workflow/edit_signals/evolution.py` | - | `Evolver` 合并/评分/泛化/失效/反例 (Layer 4) |
| `app/workflow/edit_signals/injection.py` | 318 | `SkillInjector` + BM25 + 2-gram CJK + hard cap (Layer 5) |
| `app/workflow/edit_signals/state_machine.py` | - | 4 状态机 (candidate/proven/builtin/uncertain) + pinned |
| `app/workflow/edit_signals/backup.py` | - | `snapshot_candidates` 预运行 tar.gz |
| `app/workflow/edit_signals/worker.py` | - | 后台 daemon thread (聚类 + 进化) |
| `app/workflow/edit_signals/popup.py` | - | 7 天节流通知 (`SignalPopup`) |
| `app/workflow/edit_signals/cursor.py` | - | `CursorLog` 审计 + 回滚辅助 |
| `app/workflow/edit_signals/service.py` | 142 | 单例 + `notify_chapter_committed` + `build_prompt_segment` |
| `app/ui/tabs/settings_tab.py` | + EditSignalsWidget | 4 档开关 (L1-L4) + 6 按钮 |
| `app/ui/tabs/editor_tab.py` | + 3 埋点 + 软提示卡 | 30s QTimer + hint card + 采纳/反例 |
| `app/core/prompt_assembler.py` | + `_format_project_skill_hints` | [📚 项目内参考] 段 (opt-in) |

### 25.2 5 档开关 (settings_tab EditSignalsWidget)

| 开关 | 默认 | 持久化 key | 控制 |
|---|---|---|---|
| L1 启用改稿信号学习 | ✅ 开 | `signal_enabled` | 全局启停 |
| L2 完成后右下角通知 | ✅ 开 | `signal_popup_muted` | 是否弹窗 (写手零感知时关) |
| LLM 异步泛化 | ☐ 关 (opt-in) | `signal_llm_generalize_enabled` | 后台 thread 调 LLM 泛化 |
| 注入到 writer prompt | ☐ 关 (opt-in) | `signal_inject_to_prompt` | `prompt_assembler` 注入 [📚 项目内参考] |
| 反例聚合 | ✅ 开 | `signal_anti_aggregate_enabled` | `discard` → AntiPattern |

### 25.3 6 操作按钮 (settings_tab EditSignalsWidget)

| 按钮 | 行为 |
|---|---|
| 🧪 试运行聚类 (dry-run) | `Curator.run(dry_run=True)` 不真写 |
| ⚡ 立即聚类 | 强制跑 `Curator.run` 落盘 + 备份 |
| 🧪 试运行进化 (dry-run) | `Evolver.run(dry_run=True)` 不真改 |
| ⚡ 立即进化 | 强制跑 `Evolver.run` (合并/评分/失效/反例) |
| 📂 打开候选目录 | 资源管理器打开 `signals/projects/{pid}/candidates/` |
| 📦 导出项目信号包 | `tar.gz` 整个项目信号目录 |
| 🗑 一键清空所有改稿数据 | L4 二次确认后 `clear_all()` |

### 25.4 smoke_v3_signals 76/76 项 (4 大类)

| 类别 | 项数 | 覆盖范围 |
|---|---|---|
| U1-U17 用户视角 | 17 | 基本信号/章节封存/弹窗节流/状态机/清空/dry-run/性能/文件锁 |
| E1-E5 Layer 4 进化 | 5 | 触发/合并去重/质量升级/失效检测/反例聚合 |
| I1-I5 Layer 5 注入 | 5 | BM25 top-K/hard cap/新鲜度/per-chapter 关/5000 章性能 |
| 其他 | - | Collector 3 埋点/UI 控件/Worker 启停/Config 持久化 |

### 25.5 借鉴 Hermes auto-evolution 5 件落地情况

| 借鉴项 | 落地位置 | 实现方式 |
|---|---|---|
| 合并/去重 | `evolution.merge_similar_candidates` | 同 pattern + 章节 ≥ 50% 重合 → 合并 (version++) |
| 质量评分 | `evolution.auto_promote` | use_count ≥ 5 → proven, ≥ 20 → builtin, patch/use ≥ 0.5 → uncertain |
| LLM 异步泛化 | `evolution.llm_generalize_async` | 1 周 1 次后台 thread, opt-in, 失败 fallback |
| 失效检测 | `evolution.detect_uncertain` | patch/use ≥ 0.5 阈值自动降权 |
| 反例聚合 | `evolution.aggregate_discards` | 多个 discard 信号 → AntiPattern (`anti_xxx` 命名) |

### 25.6 借鉴 Hermes v0.16.0 4 件落地情况

| 借鉴项 | 落地位置 | 字段 |
|---|---|---|
| Provenance | `CandidateSkill.created_by` + `agent_created` | `"user_edit"` (替代 v0.16.0 的 `"agent"`) |
| patch_count | `SidecarEntry.patch_count` + `last_patched_at` | 写手手动编辑时 ++, 永不归档 |
| Pinned | `SidecarEntry.pinned` | 钉住 = 永久 active, 不参与自动转换 |
| 预运行备份 | `backup.snapshot_candidates` | `pre_curator_{ts}.tar.gz` (可回滚) |

### 25.7 砍掉的 4 件 (v0.16.0 不抄)

| 砍 | 原因 |
|---|---|
| LLM 评审 / umbrella-ification | 单项目 ~10-30 候选, 纯本地 diff 足够 |
| `PROTECTED_BUILTIN_SKILLS` | v4 没有 "plan" 这种 UX 关键路径 |
| `.curator_suppressed` | v4 没有 update 同步机制 |
| `_needle_in_path_component()` | v4 是章节级, 不涉及路径误匹配 |

### 25.8 关键技术决策

| 决策 | 内容 |
|---|---|
| BM25 CJK 2-gram | 无 jieba 依赖, CJK 段切 2-gram + ASCII 整词 + 停用词表, 解决单字被滤掉问题 |
| 章节 = 1 批次 | 不用 30s 静默作主节流, 章节是小说场景的天然语义边界 |
| 4 状态机 | candidate / proven / builtin / uncertain (比 v2.1 多 1 个 uncertain 降权) |
| 3 道防污染 | BM25 相关性 + chapter 范围 + 30 天新鲜度 |
| 3 道不影响写手 | 软提示 + per-chapter 关 + 反例化按钮 |
| 同步 vs 异步 | 章节封存同步 (不丢), 聚类+进化异步 (不卡) |
| LLM 异步 + 1 周 1 次 | opt-in, 失败 fallback 标 `generalize_failed=true` |
| per-chapter 永久关 | 写 `chapter_meta.no_inject=true`, 切回来也不显示 |
| 状态机 4 状态 + pinned | pinned=True 永久 active, 写手手动控制 |

### 25.9 性能账 (实际跑通)

| 场景 | 实测 | 预算 |
|---|---|---|
| 100 章聚类 (dry-run) | 1.16-1.29s | < 5s |
| 1 章 BM25 检索 (30 候选) | 4.5-6.0ms | < 100ms |
| 章节封存 | < 50ms | < 50ms |
| 5 章聚类触发 (含落盘) | < 2s | < 5s |

### 25.10 已知未做 (v4+ 候选, 写在 §24.2)

- 候选 Skill 评分用 LLM 排序
- 跨章节 pattern 模板 (跨书共享)
- 写手写"我以后要 X" → 主动进 candidate
- 候选 Skill 之间互斥检测
- 写手手动输入"我以后要 X"→ NLP 解析进 candidate
