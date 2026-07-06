"""
app/workflow/edit_signals/jsonl_store.py

JSONLStore - 落盘 + 章节切分 + 跨项目隔离 (§6).

目录结构:
  ~/.novel-writer-pure/signals/
  ├── _lock                              ← 防止同时开多本
  ├── _config.json                       ← 全局开关
  ├── projects/
  │   ├── {project_id}/
  │   │   ├── active_buffer.jsonl        ← 当前章节未封存的信号 (Layer 1 落盘)
  │   │   ├── chapters/
  │   │   │   └── {chapter_id}.jsonl     ← 章节封存后的信号
  │   │   ├── candidates/                ← 沉淀的候选 Skill
  │   │   ├── sidecar/
  │   │   │   ├── candidate_usage.json
  │   │   │   └── chapter_usage.json
  │   │   └── backups/                   ← 预运行 tar.gz
  │   └── {project_id_2}/
  │       └── ...

进程内线程安全 (用 threading.Lock).
跨进程安全: 由 ProjectLock (lock.py) 负责.
"""
from __future__ import annotations
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from app.app_paths import get_signals_dir, get_signals_projects_dir
from .models import EditSignal

_logger = logging.getLogger("NovelWriter.edit_signals.jsonl")

# 全局 signals 目录 (v4.0-P0-新: 跟随数据目录 override)
SIGNALS_DIR = get_signals_dir()
PROJECTS_DIR = get_signals_projects_dir()


def get_project_dir(project_id) -> Path:
    """拿单项目目录, 不存在则建.

    project_id 可为 int (legacy) 或 str (UUID, v4.0 默认).
    """
    p = PROJECTS_DIR / str(project_id)
    p.mkdir(parents=True, exist_ok=True)
    (p / "chapters").mkdir(parents=True, exist_ok=True)
    (p / "candidates").mkdir(parents=True, exist_ok=True)
    (p / "sidecar").mkdir(parents=True, exist_ok=True)
    (p / "backups").mkdir(parents=True, exist_ok=True)
    return p


# ────────────────────── JSONLStore ──────────────────────

class JSONLStore:
    """Append-only JSONL, 进程内线程安全, 按 project_id + chapter_id 切分 (§6.2)."""

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.active_path = self.project_dir / "active_buffer.jsonl"
        self.chapters_dir = self.project_dir / "chapters"
        self.candidates_dir = self.project_dir / "candidates"
        self.sidecar_dir = self.project_dir / "sidecar"
        self.backups_dir = self.project_dir / "backups"
        for d in (self.chapters_dir, self.candidates_dir, self.sidecar_dir, self.backups_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ── Layer 1: 落盘到 active buffer ──

    def append_to_active(self, signal: EditSignal) -> None:
        """30s 防抖落盘 (§6.2)."""
        line = signal.to_jsonl()
        with self._lock:
            with open(self.active_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    # ── Layer 2: 章节封存 ──

    def commit_chapter(self, chapter_id) -> int:
        """把 active buffer 移到 chapters/{id}.jsonl. Returns 封存条数."""
        with self._lock:
            if not self.active_path.exists() or self.active_path.stat().st_size == 0:
                return 0
            content = self.active_path.read_text(encoding="utf-8")
            self.active_path.unlink()  # 原子清空
            target = self.chapters_dir / f"{chapter_id}.jsonl"
            with open(target, "a", encoding="utf-8") as f:
                f.write(content)
                if not content.endswith("\n"):
                    f.write("\n")
            lines = [l for l in content.splitlines() if l.strip()]
            return len(lines)

    def has_active_content(self) -> bool:
        return self.active_path.exists() and self.active_path.stat().st_size > 0

    def active_count(self) -> int:
        if not self.active_path.exists():
            return 0
        return sum(1 for l in self.active_path.read_text(encoding="utf-8").splitlines() if l.strip())

    # ── 读 ──

    def tail_chapter(self, chapter_id, n: int = 100) -> list[EditSignal]:
        path = self.chapters_dir / f"{chapter_id}.jsonl"
        return self._tail_file(path, n)

    def tail_active(self, n: int = 100) -> list[EditSignal]:
        return self._tail_file(self.active_path, n)

    def list_chapter_files(self) -> list[int]:
        """所有已封存章节 ID."""
        out = []
        for f in self.chapters_dir.glob("*.jsonl"):
            try:
                out.append(int(f.stem))
            except ValueError:
                continue
        return sorted(out)

    def read_all_chapters(self) -> dict[int, list[EditSignal]]:
        out: dict[int, list[EditSignal]] = {}
        for cid in self.list_chapter_files():
            sigs = self.tail_chapter(cid, n=10_000)
            if sigs:
                out[cid] = sigs
        return out

    @staticmethod
    def _tail_file(path: Path, n: int) -> list[EditSignal]:
        if not path.exists():
            return []
        try:
            with open(path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 512_000))
                raw = f.read().decode("utf-8", errors="replace")
        except Exception as e:
            _logger.warning("读 jsonl 失败 %s: %s", path, e)
            return []
        out: list[EditSignal] = []
        for line in raw.splitlines()[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(EditSignal.from_jsonl(line))
            except Exception as e:
                # 坏行跳过 (§15.1 风险缓解)
                _logger.debug("跳过坏 jsonl 行: %s (err=%s)", line[:80], e)
                continue
        return out

    # ── 清空 (L4) ──

    def clear_all(self) -> int:
        """一键清空 (L4 开关). Returns 删除文件数."""
        with self._lock:
            count = 0
            if self.active_path.exists():
                self.active_path.unlink()
                count += 1
            for f in self.chapters_dir.glob("*.jsonl"):
                f.unlink()
                count += 1
            for f in self.candidates_dir.glob("*.json"):
                f.unlink()
                count += 1
            for f in self.sidecar_dir.glob("*.json"):
                f.unlink()
                count += 1
            return count

    def clear_active(self) -> int:
        """只清空 active buffer (章节切走时)."""
        with self._lock:
            if not self.active_path.exists():
                return 0
            lines = self.active_path.read_text(encoding="utf-8").splitlines()
            self.active_path.unlink()
            return len(lines)


# ────────────────────── CandidateStore (候选 Skill 持久化) ──────────────────────

class CandidateStore:
    """候选 Skill 文件 (candidates/{name}_v{n}.json) 管理."""

    def __init__(self, project_dir: Path):
        self.candidates_dir = (Path(project_dir) / "candidates")
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, name: str, version: int) -> Path:
        safe_name = name.replace("/", "_").replace("\\", "_")
        return self.candidates_dir / f"{safe_name}_v{int(version)}.json"

    def save(self, candidate) -> Path:
        """存候选 (CandidateSkill 或 AntiPattern)."""
        with self._lock:
            path = self._path(candidate.name, candidate.version)
            path.write_text(candidate.to_json(), encoding="utf-8")
            return path

    def load(self, name: str, version: int):
        path = self._path(name, version)
        if not path.exists():
            return None
        try:
            from .models import CandidateSkill, AntiPattern
            d = json.loads(path.read_text(encoding="utf-8"))
            if d.get("kind") == "anti_pattern":
                return AntiPattern.from_dict(d)
            return CandidateSkill.from_dict(d)
        except Exception as e:
            _logger.warning("读 candidate 失败 %s: %s", path, e)
            return None

    def list_all(self) -> list[dict]:
        """所有候选 (按文件 glob, 返回 dict 列表, 容错)."""
        out = []
        for f in sorted(self.candidates_dir.glob("*.json")):
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception as e:
                _logger.debug("跳过坏 candidate %s: %s", f.name, e)
        return out

    def delete(self, name: str, version: int) -> bool:
        path = self._path(name, version)
        if path.exists():
            path.unlink()
            return True
        return False

    def count(self) -> int:
        return len(list(self.candidates_dir.glob("*.json")))


# ────────────────────── SidecarStore (candidate_usage.json) ──────────────────────

class SidecarStore:
    """candidate_usage.json (sidecar) 管理 (§7.2)."""

    def __init__(self, project_dir: Path):
        self.path = Path(project_dir) / "sidecar" / "candidate_usage.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, name: str) -> Optional[dict]:
        return self._data.get(name)

    def get_all(self) -> dict:
        return dict(self._data)

    def set(self, name: str, entry: dict) -> None:
        with self._lock:
            self._data[name] = entry
            self._save()

    def update(self, name: str, **kwargs) -> dict:
        """增量更新 (如 use_count++)."""
        with self._lock:
            entry = self._data.setdefault(name, {})
            entry.update(kwargs)
            self._save()
            return entry

    def remove(self, name: str) -> None:
        with self._lock:
            self._data.pop(name, None)
            self._save()

    def list_active(self) -> list[str]:
        """返回 status=active 的候选名."""
        return [n for n, m in self._data.items() if m.get("status") == "active"]

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._save()
