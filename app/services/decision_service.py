"""
Decision Service (v3.6)

记录 AI/作者对 Guide 的采纳/忽略/修改决策.
轻量层——不替代全流程审计, 只记录关键决策.

API:
  - record(unit_id, guide, action, reason) -> Decision
  - list_for_unit(unit_id) -> list[Decision]
  - summary(unit_id) -> dict  (adopted/ignored/modified 计数)
  - build_decisions_block(decisions) -> str  (注入 prompt)
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.core.types import Decision, Guide

_logger = logging.getLogger("NovelWriter.services.decision")

VALID_ACTIONS = {"adopted", "ignored", "modified"}


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def record(
    unit_id: str,
    guide: Guide,
    action: str,
    *,
    reason: str = "",
    project_id: str = "",
    step_no: int = 0,
    decided_by: str = "ai",
) -> Decision:
    if action not in VALID_ACTIONS:
        raise ValueError(f"action must be one of {VALID_ACTIONS}")

    from app.db import _impl as _db_conn

    dec = Decision(
        id=_new_id(),
        project_id=project_id,
        unit_id=unit_id,
        step_no=step_no,
        guide_id=guide.guide_id,
        guide_source=guide.source,
        action=action,
        reason=reason,
        decided_by=decided_by,
        decided_at=_now(),
        context={"guide_priority": guide.priority, "guide_confidence": guide.confidence},
    )

    try:
        conn = _db_conn.get_conn()
        conn.execute(
            """
            INSERT INTO unit_decisions
                (id, project_id, unit_id, step_no, guide_id, guide_source,
                 action, reason, decided_by, decided_at, context)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (dec.id, dec.project_id, dec.unit_id, dec.step_no,
             dec.guide_id, dec.guide_source,
             dec.action, dec.reason, dec.decided_by, dec.decided_at,
             json.dumps(dec.context, ensure_ascii=False)),
        )
        _logger.debug("recorded: %s %s guide=%s", dec.action, unit_id, dec.guide_id[:8])
    except Exception as e:
        _logger.error("decision record 落库失败: %s", e)
        raise

    return dec


def record_batch(
    unit_id: str,
    guides: list[Guide],
    *,
    actions: Optional[list[str]] = None,
    reasons: Optional[list[str]] = None,
    project_id: str = "",
    step_no: int = 0,
    decided_by: str = "ai",
) -> list[Decision]:
    """批量记录决策. actions 为 None 时自动推断:
    - 所有 Guide: adopted
    - 优先填 top 3, 其余 ignored
    """
    if actions is None:
        top_n = min(3, len(guides))
        actions = []
        for i, g in enumerate(guides):
            if i < top_n:
                actions.append("adopted")
            else:
                actions.append("ignored")

    if reasons is None:
        reasons = [""] * len(guides)

    decisions = []
    for guide, action, reason in zip(guides, actions, reasons):
        dec = record(unit_id, guide, action, reason=reason,
                     project_id=project_id, step_no=step_no, decided_by=decided_by)
        decisions.append(dec)

    return decisions


def list_for_unit(unit_id: str) -> list[Decision]:
    try:
        from app.db import _impl as _db_conn
        conn = _db_conn.get_conn()
        rows = conn.execute(
            """
            SELECT * FROM unit_decisions
            WHERE unit_id = ?
            ORDER BY step_no ASC
            """,
            (unit_id,),
        ).fetchall()
        return [Decision.from_row(r) for r in rows]
    except Exception:
        return []


def list_for_project(project_id: str) -> list[Decision]:
    try:
        from app.db import _impl as _db_conn
        conn = _db_conn.get_conn()
        rows = conn.execute(
            """
            SELECT * FROM unit_decisions
            WHERE project_id = ?
            ORDER BY decided_at DESC
            """,
            (project_id,),
        ).fetchall()
        return [Decision.from_row(r) for r in rows]
    except Exception:
        return []


def summary(unit_id: str) -> dict:
    decisions = list_for_unit(unit_id)
    return {
        "total": len(decisions),
        "adopted": sum(1 for d in decisions if d.action == "adopted"),
        "ignored": sum(1 for d in decisions if d.action == "ignored"),
        "modified": sum(1 for d in decisions if d.action == "modified"),
        "by_source": _count_by_source(decisions),
    }


def _count_by_source(decisions: list[Decision]) -> dict:
    out: dict[str, dict[str, int]] = {}
    for d in decisions:
        if d.guide_source not in out:
            out[d.guide_source] = {"adopted": 0, "ignored": 0, "modified": 0}
        out[d.guide_source][d.action] += 1
    return out


def build_decisions_block(decisions: list[Decision], max_lines: int = 10) -> str:
    """把 Decision 列表拼成 prompt 注入块.

    格式:
      ## Previous Decisions (上轮决策)
      1. [pressure] adopted → 已在开篇加速节奏
      2. [reader] ignored → 判断回收伏笔时机未到
    """
    if not decisions:
        return ""

    lines = ["## Previous Decisions (上轮决策)"]
    for i, d in enumerate(decisions[:max_lines]):
        action_label = {"adopted": "采纳", "ignored": "忽略", "modified": "修改"}.get(d.action, d.action)
        line = f"{i + 1}. [{d.guide_source}] {action_label}"
        if d.reason:
            line += f" (理由: {d.reason})"
        lines.append(line)
    return "\n".join(lines)


def delete_for_unit(unit_id: str) -> int:
    try:
        from app.db import _impl as _db_conn
        conn = _db_conn.get_conn()
        cur = conn.execute("DELETE FROM unit_decisions WHERE unit_id = ?", (unit_id,))
        return cur.rowcount or 0
    except Exception:
        return 0
