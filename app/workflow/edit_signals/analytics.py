"""
app/workflow/edit_signals/analytics.py

合并自 curator.py (Layer 3) + evolution.py (Layer 4)。

Layer 3: 聚类器 (6-pattern diff 聚类)
  - 触发: ≥5 章 / ≥50 信号 / ≥24h 冷却
  - 同 pattern ≥2 条 → 沉淀为 candidate Skill

Layer 4: 进化器 (Hermes auto-evolution 5 件)
  - 合并/去重 / 质量评分 / LLM 泛化 / 失效检测 / 反例聚合

backup + cursor 内联 (来自 backup.py / cursor.py, 合并减少文件数)。
"""
from __future__ import annotations
import difflib
import json
import logging
import tarfile
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import (
    EditSignal, SignalKind, CandidateSkill, AntiPattern, SidecarEntry,
    SKILL_CANDIDATE_STATE, SKILL_PROVEN_STATE, SKILL_BUILTIN_STATE,
    SKILL_UNCERTAIN_STATE, CursorLogEntry,
)
from .jsonl_store import JSONLStore, CandidateStore, SidecarStore, get_project_dir
from .state_machine import StateMachine, evaluate_state_static

_logger = logging.getLogger("NovelWriter.edit_signals.analytics")

# ─────────────── Layer 3 阈值 ───────────────
READY_THRESHOLD = 2                    # 同 pattern ≥ 2 → 沉淀
CURATOR_CHAPTER_THRESHOLD = 5           # 5 章触发
CURATOR_SIGNAL_THRESHOLD = 50           # 50 信号触发
CURATOR_COOLDOWN_HOURS = 24            # 24h 冷却

PATTERN_HINTS = {
    "major_shrink":  "段落大幅缩减, 写手偏好精炼",
    "major_expand":  "段落大幅扩写, 写手偏好细节",
    "reorder":       "句序调整, 写手偏好节奏",
    "dialogue":      "对话改写, 写手偏好对白风格",
    "polish":        "词级润色, 写手偏好用词",
    "other":         "其他修改, 待观察",
}

# ─────────────── Layer 4 阈值 ───────────────
EVOLVE_CANDIDATE_THRESHOLD = 3
EVOLVE_PATCH_THRESHOLD = 5
EVOLVE_COOLDOWN_HOURS = 24
LLM_GENERALIZE_INTERVAL_DAYS = 7
PROMOTE_TO_PROVEN_USE = 5
PROMOTE_TO_BUILTIN_USE = 20
UNCERTAIN_PATCH_RATIO = 0.5
READY_THRESHOLD_FOR_ANTI = 2


# ════════════════════════════════════════════════════════════════
# Layer 3: 6-pattern 分类
# ════════════════════════════════════════════════════════════════

def classify_diff(before: str, after: str) -> str:
    """6 个固定 pattern, 纯本地."""
    if not before or not after:
        return "other"
    bl, al = len(before), len(after)
    if al < bl * 0.5:
        return "major_shrink"
    if al > bl * 1.5:
        return "major_expand"
    if _is_reorder(before, after):
        return "reorder"
    if _is_dialogue(before, after):
        return "dialogue"
    if _is_word_level(before, after):
        return "polish"
    return "other"


def _is_reorder(b: str, a: str) -> bool:
    btoks = _tokenize_simple(b)
    atoks = _tokenize_simple(a)
    return sorted(btoks) == sorted(atoks) and set(btoks) == set(atoks) and btoks != atoks


def _is_dialogue(b: str, a: str) -> bool:
    def has_dialogue(t: str) -> bool:
        return any('"' in line or '"' in line or '"' in line for line in t.splitlines())
    return has_dialogue(b) and has_dialogue(a)


def _is_word_level(b: str, a: str) -> bool:
    if not b or not a:
        return False
    diff = difflib.SequenceMatcher(None, b, a)
    changed = sum(max(0, j2 - j1) for tag, i1, i2, j1, j2 in diff.get_opcodes() if tag != "equal")
    ratio = changed / len(b)
    return 0.05 <= ratio <= 0.3


def _tokenize_simple(s: str) -> list[str]:
    import re
    return [t for t in re.split(r"[\s，。！？、；：\"\"''（）()【】《》…—·\-—,.\?!;:\(\)\[\]\{\}]+", s) if t]


# ════════════════════════════════════════════════════════════════
# Layer 3: 聚类
# ════════════════════════════════════════════════════════════════

def cluster_signals(signals: list[EditSignal]) -> dict[str, list[EditSignal]]:
    """同 pattern 聚类. Returns {pattern: signals} 仅含 ≥ READY_THRESHOLD."""
    buckets: dict[str, list[EditSignal]] = defaultdict(list)
    for s in signals:
        if s.kind not in (SignalKind.REGEN, SignalKind.MANUAL_EDIT):
            continue
        b = s.payload.get("before", "")
        a = s.payload.get("after", "")
        if not b or not a:
            continue
        pattern = classify_diff(b, a)
        buckets[pattern].append(s)
    return {p: ss for p, ss in buckets.items() if len(ss) >= READY_THRESHOLD}


def promote_to_candidate(
    pattern: str,
    signals: list[EditSignal],
    *,
    name: Optional[str] = None,
) -> CandidateSkill:
    """同 pattern ≥ READY_THRESHOLD 沉淀为 candidate."""
    name = name or pattern
    examples_before: list[str] = []
    examples_after: list[str] = []
    seen_b = set()
    seen_a = set()
    for s in signals:
        b = s.payload.get("before", "")
        a = s.payload.get("after", "")
        if b and b not in seen_b and len(examples_before) < 5:
            examples_before.append(b)
            seen_b.add(b)
        if a and a not in seen_a and len(examples_after) < 5:
            examples_after.append(a)
            seen_a.add(a)
    return CandidateSkill(
        name=name,
        version=1,
        state=SKILL_CANDIDATE_STATE,
        created_at=time.time(),
        created_by="user_edit",
        agent_created=False,
        source_signals=len(signals),
        source_chapters=sorted({s.chapter_id for s in signals}),
        pattern_hint=PATTERN_HINTS.get(pattern, f"pattern: {pattern}"),
        before_examples=examples_before,
        after_examples=examples_after,
        kind="skill",
    )


# ════════════════════════════════════════════════════════════════
# 内联: backup (原 backup.py)
# ════════════════════════════════════════════════════════════════

def snapshot_candidates(project_dir: Path) -> Path:
    """聚类/进化前自动备份, 失败可回滚."""
    project_dir = Path(project_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = project_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"pre_curator_{ts}.tar.gz"
    candidates = project_dir / "candidates"
    sidecar = project_dir / "sidecar"
    with tarfile.open(backup_path, "w:gz") as tar:
        if candidates.exists():
            tar.add(candidates, arcname="candidates")
        if sidecar.exists():
            tar.add(sidecar, arcname="sidecar")
    _logger.info("备份完成: %s", backup_path)
    return backup_path


# ════════════════════════════════════════════════════════════════
# 内联: cursor (原 cursor.py)
# ════════════════════════════════════════════════════════════════

class CursorLog:
    """Append-only JSONL, 写进化审计日志."""

    def __init__(self, project_dir: Path):
        self.path = Path(project_dir) / "cursor.log"
        self._lock = threading.Lock()

    def log(
        self,
        *,
        step: str,
        candidates_before: int = 0,
        candidates_after: int = 0,
        changed: Optional[list[str]] = None,
        duration_ms: int = 0,
        note: str = "",
    ) -> None:
        entry = CursorLogEntry(
            step=step,
            candidates_before=int(candidates_before),
            candidates_after=int(candidates_after),
            changed=list(changed or []),
            duration_ms=int(duration_ms),
            ts=time.time(),
            note=str(note or ""),
        )
        line = entry.to_jsonl()
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def tail(self, n: int = 50) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            with open(self.path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 256_000))
                raw = f.read().decode("utf-8", errors="replace")
        except Exception:
            return []
        out: list[dict] = []
        for line in raw.splitlines()[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out


# ════════════════════════════════════════════════════════════════
# Layer 3: Curator 类
# ════════════════════════════════════════════════════════════════

class Curator:
    """Layer 3 聚类器."""

    def __init__(self, project_id, store: Optional[JSONLStore] = None):
        self.project_id = project_id
        self.project_dir = get_project_dir(project_id)
        self.store = store or JSONLStore(self.project_dir)
        self.cand_store = CandidateStore(self.project_dir)
        self.sidecar = SidecarStore(self.project_dir)
        self._last_run_at: float = 0.0
        meta_path = self.project_dir / "sidecar" / "last_curator_at"
        if meta_path.exists():
            try:
                self._last_run_at = float(meta_path.read_text(encoding="utf-8").strip() or 0)
            except Exception:
                pass

    def should_run(
        self,
        *,
        chapter_threshold: int = CURATOR_CHAPTER_THRESHOLD,
        signal_threshold: int = CURATOR_SIGNAL_THRESHOLD,
        cooldown_hours: int = CURATOR_COOLDOWN_HOURS,
        force: bool = False,
    ) -> bool:
        if force:
            return True
        if self._last_run_at and (time.time() - self._last_run_at) < cooldown_hours * 3600:
            return False
        chapter_ids = self.store.list_chapter_files()
        if len(chapter_ids) >= chapter_threshold:
            return True
        total = 0
        for cid in chapter_ids:
            total += len(self.store.tail_chapter(cid, n=10_000))
        if total >= signal_threshold:
            return True
        return False

    def run(
        self,
        *,
        chapter_threshold: int = CURATOR_CHAPTER_THRESHOLD,
        signal_threshold: int = CURATOR_SIGNAL_THRESHOLD,
        cooldown_hours: int = CURATOR_COOLDOWN_HOURS,
        force: bool = False,
        dry_run: bool = False,
    ) -> dict:
        if not self.should_run(
            chapter_threshold=chapter_threshold,
            signal_threshold=signal_threshold,
            cooldown_hours=cooldown_hours,
            force=force,
        ):
            return {"ran": False, "reason": "not triggered"}
        all_sigs: list[EditSignal] = []
        for cid in self.store.list_chapter_files():
            all_sigs.extend(self.store.tail_chapter(cid, n=10_000))
        clusters = cluster_signals(all_sigs)
        new_candidates: list[CandidateSkill] = []
        for pattern, sigs in clusters.items():
            cand = promote_to_candidate(pattern, sigs)
            new_candidates.append(cand)
        stats = {
            "ran": True,
            "signals": len(all_sigs),
            "patterns": {p: len(s) for p, s in clusters.items()},
            "new_candidates": [c.name for c in new_candidates],
            "dry_run": dry_run,
        }
        if dry_run:
            _logger.info("[DRY-RUN] 聚类会沉淀: %s", stats["new_candidates"])
            return stats
        try:
            snapshot_candidates(self.project_dir)
        except Exception as e:
            _logger.warning("聚类前备份失败: %s (继续)", e)
        for cand in new_candidates:
            try:
                self.cand_store.save(cand)
                existing = self.sidecar.get(cand.name)
                if existing:
                    self.sidecar.update(
                        cand.name,
                        activity_count=int(existing.get("activity_count", 0)) + 1,
                        last_activity_at=time.time(),
                    )
                else:
                    entry = SidecarEntry(
                        name=cand.name,
                        version=cand.version,
                        use_count=0,
                        patch_count=0,
                        last_activity_at=time.time(),
                        activity_count=1,
                        status=SKILL_CANDIDATE_STATE,
                        pinned=False,
                        state=SKILL_CANDIDATE_STATE,
                    )
                    self.sidecar.set(cand.name, entry.to_dict())
            except Exception as e:
                _logger.warning("写候选失败 %s: %s", cand.name, e)
        self._last_run_at = time.time()
        meta_path = self.project_dir / "sidecar" / "last_curator_at"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(str(self._last_run_at), encoding="utf-8")
        return stats


# ════════════════════════════════════════════════════════════════
# Layer 4: 合并/去重
# ════════════════════════════════════════════════════════════════

def merge_similar_candidates(
    candidates: list[dict],
    *,
    chapter_overlap_threshold: float = 0.5,
) -> list[dict]:
    by_name: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        by_name[c.get("name", "?")].append(c)
    merged_out: list[dict] = []
    for name, group in by_name.items():
        if len(group) == 1:
            merged_out.append(group[0])
            continue
        used = [False] * len(group)
        for i in range(len(group)):
            if used[i]:
                continue
            base = dict(group[i])
            base_chapters = set(base.get("source_chapters", []))
            for j in range(i + 1, len(group)):
                if used[j]:
                    continue
                other = group[j]
                other_chapters = set(other.get("source_chapters", []))
                if not (base_chapters | other_chapters):
                    continue
                overlap = len(base_chapters & other_chapters)
                union = len(base_chapters | other_chapters)
                if union > 0 and overlap / union >= chapter_overlap_threshold:
                    base["source_signals"] = int(base.get("source_signals", 0)) + int(other.get("source_signals", 0))
                    base["source_chapters"] = sorted(base_chapters | other_chapters)
                    base["version"] = int(base.get("version", 1)) + 1
                    b_list = list(base.get("before_examples", []))
                    a_list = list(base.get("after_examples", []))
                    for b in other.get("before_examples", []):
                        if b not in b_list and len(b_list) < 5:
                            b_list.append(b)
                    for a in other.get("after_examples", []):
                        if a not in a_list and len(a_list) < 5:
                            a_list.append(a)
                    base["before_examples"] = b_list
                    base["after_examples"] = a_list
                    if other.get("generalized_rule") and not base.get("generalized_rule"):
                        base["generalized_rule"] = other["generalized_rule"]
                        base["generalized_at"] = other.get("generalized_at", 0)
                    used[j] = True
            used[i] = True
            merged_out.append(base)
    return merged_out


def auto_promote(candidate: dict, usage: dict) -> str:
    return evaluate_state_static(
        use_count=int(usage.get("use_count", 0)),
        patch_count=int(usage.get("patch_count", 0)),
        promote_proven_use=PROMOTE_TO_PROVEN_USE,
        promote_builtin_use=PROMOTE_TO_BUILTIN_USE,
        uncertain_patch_ratio=UNCERTAIN_PATCH_RATIO,
    )


def detect_uncertain(usage: dict) -> bool:
    use = int(usage.get("use_count", 0))
    patch = int(usage.get("patch_count", 0))
    if (patch + use) == 0:
        return False
    return patch / float(patch + use) >= UNCERTAIN_PATCH_RATIO


def llm_generalize_async(
    candidate: dict,
    *,
    llm_client=None,
    enabled: bool = True,
) -> dict:
    if not enabled:
        return candidate
    last_at = float(candidate.get("generalized_at", 0) or 0)
    if last_at and (time.time() - last_at) < LLM_GENERALIZE_INTERVAL_DAYS * 86400:
        return candidate
    if not llm_client:
        return candidate
    examples = list(zip(
        candidate.get("before_examples", [])[:3],
        candidate.get("after_examples", [])[:3],
    ))
    examples_text = "\n".join(
        f"- before: {b[:100]}\n  after:  {a[:100]}" for b, a in examples
    )
    prompt = (
        "你是一个写作风格分析专家. 下面是写手改稿的 3 条 example:\n"
        f"{examples_text}\n\n"
        "请用 1 句话总结写手偏好 (中文, ≤ 30 字), 例:\n"
        '"避免连续用\'咬了咬嘴唇\'类动作, 换\'指尖微颤\'等具体描写"\n'
    )
    try:
        new_rule = llm_client.call(prompt)
        if new_rule and isinstance(new_rule, str) and 0 < len(new_rule) <= 200:
            candidate["generalized_rule"] = new_rule.strip()
            candidate["generalized_at"] = time.time()
            candidate["generalize_failed"] = False
        else:
            candidate["generalize_failed"] = True
    except Exception as e:
        _logger.warning("LLM 泛化失败: %s (fallback)", e)
        candidate["generalize_failed"] = True
    return candidate


def aggregate_discards(
    discards: list[EditSignal],
    *,
    name_prefix: str = "anti_",
) -> Optional[AntiPattern]:
    if len(discards) < READY_THRESHOLD_FOR_ANTI:
        return None
    examples: list[str] = []
    seen: set[str] = set()
    for s in discards:
        content = s.payload.get("content", "") or s.payload.get("before", "")
        if content and content not in seen and len(examples) < 5:
            examples.append(content[:200])
            seen.add(content)
    if not examples:
        return None
    name = _suggest_anti_name(examples)
    hint = f"❌ 写手不喜欢 (出现 {len(discards)} 次): " + name.replace("anti_", "")
    return AntiPattern(
        name=f"{name_prefix}{name}",
        version=1,
        state=SKILL_CANDIDATE_STATE,
        created_by="user_edit",
        source_signals=len(discards),
        source_chapters=sorted({s.chapter_id for s in discards}),
        pattern_hint=hint,
        discard_examples=examples,
    )


def _suggest_anti_name(examples: list[str]) -> str:
    from collections import Counter
    c: Counter = Counter()
    for ex in examples:
        for i in range(len(ex) - 1):
            w = ex[i:i + 2]
            if all("\u4e00" <= ch <= "\u9fff" for ch in w):
                c[w] += 1
    if not c:
        return "delete_pattern"
    return c.most_common(1)[0][0]


# ════════════════════════════════════════════════════════════════
# Layer 4: Evolver 类
# ════════════════════════════════════════════════════════════════

class Evolver:
    """Layer 4 进化器."""

    def __init__(
        self,
        project_id,
        store: Optional[JSONLStore] = None,
        *,
        state_machine: Optional[StateMachine] = None,
    ):
        self.project_id = project_id
        self.project_dir = get_project_dir(project_id)
        self.store = store or JSONLStore(self.project_dir)
        self.cand_store = CandidateStore(self.project_dir)
        self.sidecar = SidecarStore(self.project_dir)
        self.state_machine = state_machine or StateMachine(self.sidecar)
        self.cursor = CursorLog(self.project_dir)
        self._last_evolve_at: float = self._load_last("last_evolve_at")
        self._last_generalize_at: float = self._load_last("last_generalize_at")

    def _load_last(self, name: str) -> float:
        p = self.project_dir / "sidecar" / name
        if p.exists():
            try:
                return float(p.read_text(encoding="utf-8").strip() or 0)
            except Exception:
                return 0.0
        return 0.0

    def _save_last(self, name: str, ts: float) -> None:
        p = self.project_dir / "sidecar" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(ts), encoding="utf-8")

    def should_run(
        self,
        *,
        candidate_threshold: int = EVOLVE_CANDIDATE_THRESHOLD,
        patch_threshold: int = EVOLVE_PATCH_THRESHOLD,
        cooldown_hours: int = EVOLVE_COOLDOWN_HOURS,
        force: bool = False,
    ) -> bool:
        if force:
            return True
        if self._last_evolve_at and (time.time() - self._last_evolve_at) < cooldown_hours * 3600:
            return False
        if self.cand_store.count() >= candidate_threshold:
            return True
        total_patch = 0
        for entry in self.sidecar.get_all().values():
            total_patch += int(entry.get("patch_count", 0))
        if total_patch >= patch_threshold:
            return True
        return False

    def run(
        self,
        *,
        llm_client=None,
        llm_enabled: bool = False,
        force: bool = False,
        dry_run: bool = False,
    ) -> dict:
        if not self.should_run(force=force):
            return {"ran": False, "reason": "not triggered"}
        stats: dict = {
            "ran": True,
            "before": self.cand_store.count(),
            "merged": [],
            "promoted": [],
            "uncertain": [],
            "anti_patterns": [],
            "dry_run": dry_run,
        }
        if not dry_run:
            try:
                snapshot_candidates(self.project_dir)
            except Exception as e:
                _logger.warning("进化前备份失败: %s (继续)", e)
        all_cands = self.cand_store.list_all()
        merged = merge_similar_candidates(all_cands) if all_cands else []
        stats["after_merge"] = len(merged)
        for cand in merged:
            name = cand.get("name")
            entry = self.sidecar.get(name)
            if not entry:
                continue
            new_state = auto_promote(cand, entry)
            if detect_uncertain(entry):
                new_state = SKILL_UNCERTAIN_STATE
            old_state = cand.get("state", SKILL_CANDIDATE_STATE)
            if new_state != old_state:
                cand["state"] = new_state
                if new_state == SKILL_PROVEN_STATE:
                    stats["promoted"].append(name)
                if new_state == SKILL_UNCERTAIN_STATE:
                    stats["uncertain"].append(name)
        try:
            all_sigs: list[EditSignal] = []
            for cid in self.store.list_chapter_files():
                all_sigs.extend(self.store.tail_chapter(cid, n=10_000))
            discards = [s for s in all_sigs if s.kind == SignalKind.DISCARD]
            anti = aggregate_discards(discards)
            if anti is not None:
                stats["anti_patterns"].append(anti.name)
                if not dry_run:
                    merged.append(anti.to_candidate().to_dict())
        except Exception as e:
            _logger.warning("反例聚合失败: %s", e)
        if not dry_run:
            try:
                for f in self.cand_store.candidates_dir.glob("*.json"):
                    f.unlink()
            except Exception as e:
                _logger.warning("清空旧 candidates 失败: %s", e)
            for cand in merged:
                try:
                    if cand.get("kind") == "anti_pattern":
                        anti_obj = AntiPattern.from_dict(cand)
                        self.cand_store.save(anti_obj)
                    else:
                        cand_obj = CandidateSkill.from_dict(cand)
                        self.cand_store.save(cand_obj)
                    name = cand.get("name")
                    entry = self.sidecar.get(name)
                    if entry:
                        entry["state"] = cand.get("state", entry.get("state"))
                        entry["status"] = cand.get("state", entry.get("status"))
                        self.sidecar.set(name, entry)
                except Exception as e:
                    _logger.warning("写 candidate 失败 %s: %s", cand.get("name"), e)
        stats["after"] = len(merged)
        try:
            self.cursor.log(
                step="evolve",
                candidates_before=stats["before"],
                candidates_after=stats["after"],
                changed=stats.get("merged", []) + stats.get("promoted", []) + stats.get("uncertain", []) + stats.get("anti_patterns", []),
                duration_ms=0,
                note="auto-evolve",
            )
        except Exception as e:
            _logger.debug("cursor.log 写入失败: %s", e)
        self._last_evolve_at = time.time()
        self._save_last("last_evolve_at", self._last_evolve_at)
        return stats

    def maybe_generalize(self, *, llm_client=None, llm_enabled: bool = False) -> dict:
        if not llm_enabled or not llm_client:
            return {"ran": False, "reason": "llm disabled or no client"}
        if self._last_generalize_at and (time.time() - self._last_generalize_at) < LLM_GENERALIZE_INTERVAL_DAYS * 86400:
            return {"ran": False, "reason": "cooldown"}
        all_cands = self.cand_store.list_all()
        changed: list[str] = []
        for cand in all_cands:
            old = cand.get("generalized_rule", "")
            llm_generalize_async(cand, llm_client=llm_client, enabled=True)
            if cand.get("generalized_rule") != old:
                changed.append(cand.get("name"))
                try:
                    if cand.get("kind") == "anti_pattern":
                        self.cand_store.save(AntiPattern.from_dict(cand))
                    else:
                        self.cand_store.save(CandidateSkill.from_dict(cand))
                except Exception as e:
                    _logger.warning("写回泛化结果失败 %s: %s", cand.get("name"), e)
        self._last_generalize_at = time.time()
        self._save_last("last_generalize_at", self._last_generalize_at)
        return {"ran": True, "changed": changed}
