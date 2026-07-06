"""
app/workflow/edit_signals/state_machine.py

StateMachine - 3 状态自动机 + pinned + 复用 SidecarStore (§8).

状态转换 (Hermes v0.16.0 借鉴):
  active → stale (30 天无活动, pinned 跳过)
  stale → archived (再 90 天无活动)
  active ← 任何活动 / patch / use / 手动恢复

v3.0 进化层 (4 状态 - candidate/proven/builtin/uncertain):
  use_count >= 5 → proven
  use_count >= 20 && patch==0 → builtin (永久 active)
  patch/use >= 0.5 → uncertain
"""
from __future__ import annotations
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .models import (
    SKILL_CANDIDATE_STATE, SKILL_PROVEN_STATE, SKILL_BUILTIN_STATE,
    SKILL_UNCERTAIN_STATE, SkillState,
)
from .jsonl_store import SidecarStore

_logger = logging.getLogger("NovelWriter.edit_signals.state")

# 阈值 (与 v3.0 文档 §20.2 保持一致, 可由 config 覆盖)
STALE_DAYS_DEFAULT = 30
ARCHIVE_DAYS_DEFAULT = 90
PROMOTE_TO_PROVEN_USE_DEFAULT = 5
PROMOTE_TO_BUILTIN_USE_DEFAULT = 20
UNCERTAIN_PATCH_RATIO_DEFAULT = 0.5


class StateMachine:
    """3 状态自动机 + pinned + 4 状态候选评估 (§8)."""

    def __init__(
        self,
        sidecar: SidecarStore,
        *,
        stale_days: int = STALE_DAYS_DEFAULT,
        archive_days: int = ARCHIVE_DAYS_DEFAULT,
        promote_proven_use: int = PROMOTE_TO_PROVEN_USE_DEFAULT,
        promote_builtin_use: int = PROMOTE_TO_BUILTIN_USE_DEFAULT,
        uncertain_patch_ratio: float = UNCERTAIN_PATCH_RATIO_DEFAULT,
    ):
        self.sidecar = sidecar
        self.stale_days = int(stale_days)
        self.archive_days = int(archive_days)
        self.promote_proven_use = int(promote_proven_use)
        self.promote_builtin_use = int(promote_builtin_use)
        self.uncertain_patch_ratio = float(uncertain_patch_ratio)

    # ── §8.2 tick: 推进 3 状态 ──

    def tick(self, *, now: Optional[datetime] = None) -> dict:
        """推进 stale/archived 状态. Returns 变更统计."""
        now = now or datetime.now()
        changes = {"to_stale": [], "to_archived": [], "to_active": []}
        for name, entry in self.sidecar.get_all().items():
            # pinned 跳过
            if entry.get("pinned"):
                continue
            last = entry.get("last_activity_at", 0)
            if not last:
                continue
            last_dt = datetime.fromtimestamp(float(last))
            state = entry.get("status", SkillState.ACTIVE)
            if state == SkillState.ACTIVE and (now - last_dt) > timedelta(days=self.stale_days):
                entry["status"] = SkillState.STALE
                entry["state"] = SkillState.STALE
                self.sidecar.set(name, entry)
                changes["to_stale"].append(name)
            elif state == SkillState.STALE and (now - last_dt) > timedelta(days=self.archive_days):
                entry["status"] = SkillState.ARCHIVED
                entry["state"] = SkillState.ARCHIVED
                self.sidecar.set(name, entry)
                changes["to_archived"].append(name)
        return changes

    # ── §8.2 touch: 记录活动 ──

    def touch(self, name: str, event: str = "use", *, now: Optional[float] = None) -> dict:
        """记录活动 (use/patch/active). 推进 last_activity_at, 自动复活."""
        now = now if now is not None else time.time()
        entry = self.sidecar.get(name) or {"name": name}
        # 计数
        if event == "use":
            entry["use_count"] = int(entry.get("use_count", 0)) + 1
        elif event == "patch":
            entry["patch_count"] = int(entry.get("patch_count", 0)) + 1
            entry["last_patched_at"] = now
        entry["last_activity_at"] = now
        entry["activity_count"] = int(entry.get("activity_count", 0)) + 1
        # 自动复活
        cur_state = entry.get("status", SkillState.ACTIVE)
        if cur_state in (SkillState.STALE, SkillState.ARCHIVED):
            entry["status"] = SkillState.ACTIVE
            entry["state"] = SkillState.ACTIVE
            changes = "复活"
        else:
            changes = ""
        # 4 状态评估 (v3.0 §20.4.2)
        new_state = self._evaluate_state(entry)
        if new_state != entry.get("state"):
            entry["state"] = new_state
            if not changes:
                changes = f"->{new_state}"
        self.sidecar.set(name, entry)
        return {"entry": entry, "change": changes, "state": new_state}

    def _evaluate_state(self, entry: dict) -> str:
        """根据 use_count / patch_count 决定 4 状态 (v3.0 §20.3)."""
        use = int(entry.get("use_count", 0))
        patch = int(entry.get("patch_count", 0))
        # builtin: 高 use + 无 patch
        if use >= self.promote_builtin_use and patch == 0:
            return SKILL_BUILTIN_STATE
        # proven: 中等 use
        if use >= self.promote_proven_use:
            return SKILL_PROVEN_STATE
        # uncertain: patch 多 = 写手在改
        if (patch + use) > 0 and patch / float(patch + use) >= self.uncertain_patch_ratio:
            return SKILL_UNCERTAIN_STATE
        return SKILL_CANDIDATE_STATE

    # ── §7.3 pin: 钉住 ──

    def pin(self, name: str, pinned: bool = True) -> None:
        """pinned=True → 永久 active, 不参与自动转换."""
        entry = self.sidecar.get(name) or {"name": name}
        entry["pinned"] = bool(pinned)
        if pinned:
            entry["status"] = SkillState.ACTIVE
            entry["state"] = SkillState.ACTIVE
        self.sidecar.set(name, entry)

    # ── 兼容 v2.1 API ──

    def restore(self, name: str) -> None:
        """archived → active (写手手动恢复)."""
        entry = self.sidecar.get(name) or {"name": name}
        entry["status"] = SkillState.ACTIVE
        entry["state"] = SkillState.ACTIVE
        self.sidecar.set(name, entry)

    def archive(self, name: str) -> None:
        """active → archived (写手手动)."""
        entry = self.sidecar.get(name) or {"name": name}
        entry["status"] = SkillState.ARCHIVED
        entry["state"] = SkillState.ARCHIVED
        self.sidecar.set(name, entry)


# ────────────────────── 便捷全局函数 (不依赖实例) ──────────────────────

def evaluate_state_static(
    use_count: int,
    patch_count: int,
    *,
    promote_proven_use: int = PROMOTE_TO_PROVEN_USE_DEFAULT,
    promote_builtin_use: int = PROMOTE_TO_BUILTIN_USE_DEFAULT,
    uncertain_patch_ratio: float = UNCERTAIN_PATCH_RATIO_DEFAULT,
) -> str:
    """无副作用的状态计算 (供 evolution.py / injection.py 复用)."""
    use = int(use_count)
    patch = int(patch_count)
    if use >= promote_builtin_use and patch == 0:
        return SKILL_BUILTIN_STATE
    if use >= promote_proven_use:
        return SKILL_PROVEN_STATE
    if (patch + use) > 0 and patch / float(patch + use) >= uncertain_patch_ratio:
        return SKILL_UNCERTAIN_STATE
    return SKILL_CANDIDATE_STATE
