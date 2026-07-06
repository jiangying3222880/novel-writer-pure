"""
Unit Writing Service - run_unit() 分段生成 + 断点快照

核心设计:
- 单元是创作单位，按段落逐步生成
- 每完成一段/一批落一次断点快照，支持随时中断和恢复
- 快照记录: 已写文本 + 单元摘要 + 角色状态 + 世界状态 + 活跃钩子
- 生成策略: 先写开头 -> 中段推进 -> 结尾收束，每段都基于前序上下文
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from app.db import _impl as _db_conn
from app.db.models import UnitWritingSnapshot
from app.services import story_unit_service_v2 as _unit_svc
from app.services import unit_paragraph_service as _para_svc
from app.services.exceptions import NotFoundError, ValidationError

_logger = logging.getLogger("NovelWriter.services.unit_writing")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.") + \
        f"{datetime.now().microsecond // 1000:03d}"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ============================================================
# Snapshot management
# ============================================================

def _row_to_snapshot(row) -> UnitWritingSnapshot:
    return UnitWritingSnapshot(
        id=row["id"],
        unit_id=row["unit_id"],
        project_id=row["project_id"],
        step_no=row["step_no"],
        draft_text=row["draft_text"] or "",
        unit_summary=row["unit_summary"] or "",
        word_count=row["word_count"] or 0,
        character_state=row["character_state"] or "{}",
        world_state=row["world_state"] or "{}",
        active_hooks=row["active_hooks"] or "[]",
        step_prompt=row["step_prompt"] or "",
        model_used=row["model_used"] or "",
        tokens_used=row["tokens_used"] or 0,
        created_at=row["created_at"] or "",
    )


def create_snapshot(
    unit_id: str,
    step_no: int,
    draft_text: str,
    *,
    unit_summary: str = "",
    character_state: Optional[dict] = None,
    world_state: Optional[dict] = None,
    active_hooks: Optional[list] = None,
    step_prompt: str = "",
    model_used: str = "",
    tokens_used: int = 0,
) -> UnitWritingSnapshot:
    """Create a writing snapshot at a given step."""
    unit = _unit_svc.get(unit_id)
    snap_id = _new_id()
    now = _now()

    char_state_json = json.dumps(character_state or {}, ensure_ascii=False)
    world_state_json = json.dumps(world_state or {}, ensure_ascii=False)
    hooks_json = json.dumps(active_hooks or [], ensure_ascii=False)
    wc = len(draft_text)

    with _db_conn.transaction() as tx:
        tx.execute(
            """
            INSERT INTO unit_writing_snapshots
                (id, unit_id, project_id, step_no, draft_text, unit_summary,
                 word_count, character_state, world_state, active_hooks,
                 step_prompt, model_used, tokens_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (snap_id, unit_id, unit.project_id, step_no, draft_text,
             unit_summary, wc, char_state_json, world_state_json, hooks_json,
             step_prompt, model_used, tokens_used, now),
        )

    # Update unit progress
    _unit_svc.update(unit_id, current_step=step_no, draft=draft_text, word_count=wc)

    _logger.debug(
        "Created snapshot unit=%s step=%d words=%d",
        unit_id, step_no, wc,
    )
    return get_snapshot(snap_id)


def get_snapshot(snapshot_id: str) -> UnitWritingSnapshot:
    db = _db_conn.get_conn()
    row = db.execute(
        "SELECT * FROM unit_writing_snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()
    if not row:
        raise NotFoundError("UnitWritingSnapshot", snapshot_id)
    return _row_to_snapshot(row)


def get_latest_snapshot(unit_id: str) -> Optional[UnitWritingSnapshot]:
    """Get the latest snapshot for a unit (highest step_no)."""
    db = _db_conn.get_conn()
    row = db.execute(
        """
        SELECT * FROM unit_writing_snapshots
        WHERE unit_id = ?
        ORDER BY step_no DESC LIMIT 1
        """,
        (unit_id,),
    ).fetchone()
    return _row_to_snapshot(row) if row else None


def list_snapshots(unit_id: str) -> list[UnitWritingSnapshot]:
    """List all snapshots for a unit, ordered by step_no ascending."""
    db = _db_conn.get_conn()
    rows = db.execute(
        "SELECT * FROM unit_writing_snapshots WHERE unit_id = ? ORDER BY step_no ASC",
        (unit_id,),
    ).fetchall()
    return [_row_to_snapshot(r) for r in rows]


def rollback_to_snapshot(unit_id: str, snapshot_id: str) -> bool:
    """
    Rollback unit draft to a previous snapshot.

    Cleanup order (all within one transaction):
      1. Delete auto-generated hooks after this step (manual_locked = 0)
      2. Delete auto-generated memories after this step (manual_locked = 0)
      3. Delete writing snapshots after this step
      4. Rebuild paragraphs from snapshot text
      5. Restore unit state + exit states from snapshot
    """
    snap = get_snapshot(snapshot_id)
    if snap.unit_id != unit_id:
        raise ValidationError("Snapshot does not belong to unit")

    unit = _unit_svc.get(unit_id)
    step = snap.step_no

    with _db_conn.transaction() as tx:
        # 1. Delete auto hooks planted/paid after this step
        tx.execute(
            "DELETE FROM unit_hook_map WHERE unit_id = ? AND step_no > ? AND manual_locked = 0",
            (unit_id, step),
        )
        hooks_deleted = tx.rowcount if hasattr(tx, "rowcount") else 0

        # 2. Delete auto memories generated after this step
        #    agent_memories uses unit_step column (added in migration 038)
        for tbl in ("agent_memories", "agent_memory"):
            try:
                cur = tx.execute(
                    f"DELETE FROM {tbl} WHERE project_id = ? AND unit_id = ? AND unit_step > ? AND manual_locked = 0",
                    (unit.project_id, unit_id, step),
                )
                if hasattr(cur, "rowcount") and cur.rowcount > 0:
                    pass
            except Exception:
                pass

        # 3. Delete snapshots after this step
        tx.execute(
            "DELETE FROM unit_writing_snapshots WHERE unit_id = ? AND step_no > ?",
            (unit_id, step),
        )

        # 4. Delete story_events after this step (v3.5.1 work-3, 段级时间锚点)
        tx.execute(
            "DELETE FROM story_events WHERE unit_id = ? AND step_no > ?",
            (unit_id, step),
        )

    # 5. Rebuild paragraphs from snapshot text
    _para_svc.replace_full_text(unit_id, unit.project_id, snap.draft_text)

    # 6. Update unit: status back to writing + restore exit states from snapshot
    _unit_svc.update(
        unit_id,
        status="writing",
        current_step=step,
        draft=snap.draft_text,
        word_count=snap.word_count,
        exit_characters=json.dumps(snap.character_state, ensure_ascii=False),
        exit_world=json.dumps(snap.world_state, ensure_ascii=False),
    )

    _logger.info(
        "Rolled back unit=%s to snapshot=%s step=%d (hooks_cleaned=%d, events_cleaned=auto)",
        unit_id, snapshot_id, step, hooks_deleted,
    )
    return True


def delete_snapshots(unit_id: str) -> int:
    """Delete all snapshots for a unit."""
    with _db_conn.transaction() as tx:
        cur = tx.execute(
            "DELETE FROM unit_writing_snapshots WHERE unit_id = ?", (unit_id,)
        )
        count = cur.rowcount
    _logger.info("Deleted %d snapshots for unit %s", count, unit_id)
    return count


# ============================================================
# Progress tracking helpers
# ============================================================

def estimate_total_steps(unit_id: str, chars_per_step: int = 1500) -> int:
    """
    Estimate how many steps are needed based on target_chars.
    Default: ~1500 chars per generation step.
    """
    unit = _unit_svc.get(unit_id)
    target = max(unit.target_chars, 1000)
    steps = max(1, (target + chars_per_step - 1) // chars_per_step)
    return int(steps)


def get_progress(unit_id: str) -> dict:
    """Get current writing progress for a unit."""
    unit = _unit_svc.get(unit_id)
    latest = get_latest_snapshot(unit_id)

    current = latest.step_no if latest else unit.current_step
    total = unit.total_steps if unit.total_steps > 0 else estimate_total_steps(unit_id)
    percent = (current / total * 100) if total > 0 else 0

    return {
        "unit_id": unit_id,
        "status": unit.status,
        "current_step": current,
        "total_steps": total,
        "word_count": latest.word_count if latest else unit.word_count,
        "target_chars": unit.target_chars,
        "progress_percent": round(percent, 1),
        "has_snapshot": latest is not None,
        "latest_snapshot_at": latest.created_at if latest else "",
    }


# ============================================================
# Context building (token-budget-aware)
# ============================================================

def build_context_for_step(
    unit_id: str,
    current_draft: str,
    current_summary: str,
    *,
    recent_chars: int = 3000,
    summary_chars: int = 800,
) -> str:
    """
    Build context text for the next writing step.

    Strategy: unit_summary + recent paragraphs, to stay within token budget.
    - Short draft (< recent_chars): return full text
    - Long draft: return [summary + "\n\n---\n\n" + recent N chars]

    This avoids passing the entire draft to the writer at step 10+
    (which would blow the token budget for long units).
    """
    if len(current_draft) <= recent_chars:
        return current_draft

    # Trim summary to budget
    summary = current_summary
    if len(summary) > summary_chars:
        summary = summary[:summary_chars] + "..."

    # Take recent chars from the end
    recent = current_draft[-recent_chars:]

    return f"[单元摘要]\n{summary}\n\n[最近文本]\n{recent}"


# ============================================================
# Step generation (pluggable writer function)
# ============================================================

@dataclass
class StepResult:
    """Result of a single writing step."""
    ok: bool
    text_added: str = ""
    unit_summary: str = ""
    character_state: dict = field(default_factory=dict)
    world_state: dict = field(default_factory=dict)
    active_hooks: list = field(default_factory=list)
    model_used: str = ""
    tokens_used: int = 0
    step_prompt: str = ""
    error: str = ""


StepWriterFn = Callable[[
    str,          # unit_id
    int,          # step_no
    str,          # current_draft (full text so far)
    str,          # unit_summary
    dict,         # character_state
    dict,         # world_state
    list,         # active_hooks
], StepResult]


def run_unit(
    unit_id: str,
    writer_fn: StepWriterFn,
    *,
    max_steps: int = 0,
    resume: bool = True,
    chars_per_step: int = 1500,
    recent_chars: int = 3000,
    summary_chars: int = 800,
    on_step_complete: Optional[Callable[[int, StepResult], None]] = None,
) -> dict:
    """
    Run the full unit writing process using a pluggable writer function.

    Args:
        unit_id: The unit to write
        writer_fn: Function that generates text for each step
        max_steps: Max steps to run (0 = until complete)
        resume: If True, resume from latest snapshot; if False, start fresh
        chars_per_step: Approximate chars per generation step (for total estimate)
        recent_chars: How many chars of recent text to include in context
            (prevents token blowup on long units)
        summary_chars: How many chars of unit summary to include in context
        on_step_complete: Optional callback after each step

    Returns:
        dict with: ok, unit_id, final_word_count, steps_run, snapshots_count

    Context strategy (token-budget-aware):
      - Short draft (< recent_chars): pass full text to writer
      - Long draft: pass [unit_summary + recent N chars] instead of full draft
        This keeps context size stable regardless of unit length.
    """
    unit = _unit_svc.get(unit_id)
    project_id = unit.project_id

    # Determine starting point
    if resume:
        latest = get_latest_snapshot(unit_id)
        if latest:
            current_draft = latest.draft_text
            current_summary = latest.unit_summary
            char_state = json.loads(latest.character_state or "{}")
            world_state = json.loads(latest.world_state or "{}")
            active_hooks = json.loads(latest.active_hooks or "[]")
            start_step = latest.step_no + 1
            _logger.info("Resuming unit %s from step %d", unit_id, start_step)
        else:
            current_draft = ""
            current_summary = unit.synopsis or ""
            char_state = _unit_svc.get_entry_characters(unit_id)
            world_state = _unit_svc.get_entry_world(unit_id)
            active_hooks = []
            start_step = 1
            _logger.info("Starting unit %s from scratch", unit_id)
    else:
        # Fresh start - clear old snapshots
        delete_snapshots(unit_id)
        current_draft = ""
        current_summary = unit.synopsis or ""
        char_state = _unit_svc.get_entry_characters(unit_id)
        world_state = _unit_svc.get_entry_world(unit_id)
        active_hooks = []
        start_step = 1
        _logger.info("Fresh start for unit %s", unit_id)

    # Estimate total steps
    total_steps = estimate_total_steps(unit_id, chars_per_step)
    _unit_svc.update(unit_id, total_steps=total_steps, status="writing")

    target_chars = unit.target_chars
    steps_run = 0
    completed = False

    # Step loop
    for step_no in range(start_step, total_steps + 1):
        if max_steps > 0 and steps_run >= max_steps:
            break

        _logger.info("Step %d/%d - writing...", step_no, total_steps)

        # Build context text (summary + recent chars) to stay within token budget
        context_text = build_context_for_step(
            unit_id, current_draft, current_summary,
            recent_chars=recent_chars,
            summary_chars=summary_chars,
        )

        # Call the writer function
        try:
            result = writer_fn(
                unit_id, step_no, context_text, current_summary,
                char_state, world_state, active_hooks,
            )
        except Exception as e:
            _logger.error("Step %d failed: %s", step_no, e)
            # Save what we have before failing
            if current_draft:
                create_snapshot(
                    unit_id, step_no - 1, current_draft,
                    unit_summary=current_summary,
                    character_state=char_state,
                    world_state=world_state,
                    active_hooks=active_hooks,
                    step_prompt=f"[interrupted: {e}]",
                )
            return {
                "ok": False,
                "unit_id": unit_id,
                "error": str(e),
                "steps_run": steps_run,
                "final_word_count": len(current_draft),
                "snapshots_count": len(list_snapshots(unit_id)),
                "status": "error",
            }

        if not result.ok:
            _logger.warning("Step %d not ok: %s", step_no, result.error)
            return {
                "ok": False,
                "unit_id": unit_id,
                "error": result.error,
                "steps_run": steps_run,
                "final_word_count": len(current_draft),
                "snapshots_count": len(list_snapshots(unit_id)),
                "status": "failed_step",
            }

        # Append new text
        if current_draft and result.text_added:
            if not current_draft.endswith("\n"):
                current_draft += "\n\n"
            current_draft += result.text_added
        elif result.text_added:
            current_draft = result.text_added

        # Update state from result
        if result.unit_summary:
            current_summary = result.unit_summary
        if result.character_state:
            char_state.update(result.character_state)
        if result.world_state:
            world_state.update(result.world_state)
        if result.active_hooks is not None:
            active_hooks = result.active_hooks

        # Create snapshot
        create_snapshot(
            unit_id, step_no, current_draft,
            unit_summary=current_summary,
            character_state=char_state,
            world_state=world_state,
            active_hooks=active_hooks,
            step_prompt=result.step_prompt,
            model_used=result.model_used,
            tokens_used=result.tokens_used,
        )

        steps_run += 1

        # Check if we've reached target
        if len(current_draft) >= target_chars * 0.9:
            completed = True
            _logger.info("Unit %s reached target word count", unit_id)
            break

        # Callback
        if on_step_complete:
            try:
                on_step_complete(step_no, result)
            except Exception:
                pass

    # Finalize
    if completed:
        # Save final state as exit state
        _unit_svc.set_exit_characters(unit_id, char_state)
        _unit_svc.set_exit_world(unit_id, world_state)
        _unit_svc.set_exit_commitments(unit_id, active_hooks)

        # Rebuild paragraphs from final draft
        _para_svc.replace_full_text(unit_id, project_id, current_draft)

        # Auto-record State Diff events (v3.5.1 work-3)
        try:
            from app.services import unit_event_service as _ev_svc
            _ev_svc.finalize_unit_events(unit_id, final_state=char_state)
        except Exception as e:
            _logger.warning("Unit %s event 写入失败 (不影响主流程): %s", unit_id, e)

        # Mark completed
        _unit_svc.mark_completed(unit_id)
        _logger.info("Unit %s writing completed", unit_id)

    snap_count = len(list_snapshots(unit_id))

    return {
        "ok": completed,
        "unit_id": unit_id,
        "final_word_count": len(current_draft),
        "steps_run": steps_run,
        "snapshots_count": snap_count,
        "status": "completed" if completed else "interrupted",
    }


# ============================================================
# Simple test writer (for testing without LLM)
# ============================================================

def test_writer(
    unit_id: str,
    step_no: int,
    current_draft: str,
    unit_summary: str,
    character_state: dict,
    world_state: dict,
    active_hooks: list,
) -> StepResult:
    """
    Simple test writer that generates placeholder text.
    For testing the run_unit framework without an actual LLM.
    """
    import random

    templates = [
        f"Step {step_no}: The story continues with more events unfolding.",
        f"Step {step_no}: Characters interact and the plot thickens.",
        f"Step {step_no}: A new development changes the course of events.",
        f"Step {step_no}: Tension builds as the situation becomes more complex.",
        f"Step {step_no}: The protagonist faces a new challenge.",
    ]

    text = random.choice(templates)
    text += "\n\n"
    text += "    " + f"This is paragraph one of step {step_no}. " * 5
    text += "\n\n"
    text += "    " + f"This is paragraph two of step {step_no}. " * 4
    text += "\n"

    # Update some state
    character_state["_step"] = step_no
    world_state["_step"] = step_no

    return StepResult(
        ok=True,
        text_added=text,
        unit_summary=unit_summary + f" [step{step_no}]",
        character_state=character_state,
        world_state=world_state,
        active_hooks=active_hooks,
        model_used="test-writer",
        tokens_used=len(text) // 2,
        step_prompt=f"Test step {step_no}",
    )
