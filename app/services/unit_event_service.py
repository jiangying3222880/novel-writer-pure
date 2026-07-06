"""
Unit Event Service（v3.5.1+）

State Diff 自动计算 + Event 记录 + 段级时间锚点查询.

核心 API:
  - compute_state_diff(entry, exit) -> list[dict]
  - record_events(unit_id, step_no, events)
  - list_events_as_of_unit(project_id, unit_id, as_of_step)
  - rollback_events(unit_id, after_step)
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from app.db import _impl as _db_conn
from app.services.exceptions import NotFoundError, ValidationError

_logger = logging.getLogger("NovelWriter.services.unit_event")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.") + \
        f"{datetime.now().microsecond // 1000:03d}"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ============================================================
# Event type -> entity_type 映射（与 enum 表对齐）
# ============================================================
_EVENT_TYPE_DEFAULTS = {
    "character_state":        "character",
    "character_relationship": "character",
    "character_knowledge":    "character",
    "character_location":     "character",
    "character_inventory":    "character",
    "world_state":            "world",
    "world_location":         "location",
    "world_time":             "time",
    "hook_plant":             "hook",
    "hook_payoff":            "hook",
    "promise_made":           "promise",
    "promise_broken":         "promise",
    "revelation":             "fact",
}


def _coerce_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


# ============================================================
# State Diff 计算
# ============================================================

def compute_state_diff(
    unit_id: str,
    entry_state: dict,
    exit_state: dict,
) -> list[dict]:
    """比较 entry 与 exit 状态, 生成 Event Diff 列表.

    支持的 state 结构:
      {"林凡": {"trust": 80, "realm": "筑基", "inventory": ["剑"]}}
      {"世界": {"time": "三年后", "weather": "雪"}}

    返回 list[dict]:
      {"event_type": "character_state", "entity_type": "character",
       "entity_name": "林凡", "field_name": "trust",
       "old_value": "80", "new_value": "30"}
    """
    events: list[dict] = []
    all_entities = set(entry_state.keys()) | set(exit_state.keys())

    for entity in all_entities:
        old = entry_state.get(entity) or {}
        new = exit_state.get(entity) or {}
        all_fields = set(old.keys()) | set(new.keys())

        for field in all_fields:
            old_val = old.get(field)
            new_val = new.get(field)
            if old_val == new_val:
                continue

            event_type = _guess_event_type(entity, field)
            events.append({
                "event_type": event_type,
                "entity_type": _EVENT_TYPE_DEFAULTS.get(event_type, "misc"),
                "entity_name": str(entity),
                "field_name": str(field),
                "old_value": _coerce_str(old_val),
                "new_value": _coerce_str(new_val),
            })

    return events


def _guess_event_type(entity: str, field: str) -> str:
    field_l = field.lower()
    if "trust" in field_l or "relationship" in field_l or "好感" in field:
        return "character_relationship"
    if "knowledge" in field_l or "知道" in field or "认知" in field:
        return "character_knowledge"
    if "location" in field_l or "位置" in field or "地点" in field:
        return "character_location"
    if "inventory" in field_l or "物品" in field or "装备" in field:
        return "character_inventory"
    if entity in ("世界", "world", "World"):
        return "world_state"
    return "character_state"


# ============================================================
# Event 持久化
# ============================================================

def record_events(
    unit_id: str,
    step_no: int,
    events: list[dict],
    project_id: Optional[str] = None,
) -> int:
    """写入一批 event. 返回写入数量."""
    if not events:
        return 0

    if not project_id:
        db = _db_conn.get_conn()
        row = db.execute(
            "SELECT project_id FROM story_units_v2 WHERE id = ?", (unit_id,)
        ).fetchone()
        if not row:
            raise NotFoundError("StoryUnitV2", unit_id)
        project_id = row["project_id"]

    now = _now()
    rows = []
    for ev in events:
        rows.append((
            _new_id(),
            project_id,
            unit_id,
            int(step_no),
            ev["event_type"],
            ev.get("entity_type", "misc"),
            ev["entity_name"],
            ev["field_name"],
            ev.get("old_value", ""),
            ev.get("new_value", ""),
            ev.get("description", ""),
            now,
        ))

    with _db_conn.transaction() as db:
        db.executemany(
            """INSERT INTO story_events
               (id, project_id, unit_id, step_no, event_type,
                entity_type, entity_name, field_name,
                old_value, new_value, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
    _logger.info("记录 %d 个 event: unit=%s step=%d", len(rows), unit_id, step_no)
    return len(rows)


def list_events_as_of_unit(
    project_id: str,
    *,
    unit_id: Optional[str] = None,
    as_of_step: int = 0,
) -> list[dict]:
    """段级时间锚点查询.

    - 不传 unit_id: 返回 project 所有 event (按 unit+step 升序)
    - 传 unit_id: 返回该 unit 在 step_no <= as_of_step 范围内的 event
    """
    db = _db_conn.get_conn()
    if unit_id:
        rows = db.execute(
            """SELECT * FROM story_events
               WHERE project_id = ? AND unit_id = ? AND step_no <= ?
               ORDER BY step_no ASC, created_at ASC""",
            (project_id, unit_id, int(as_of_step)),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT * FROM story_events
               WHERE project_id = ?
               ORDER BY unit_id ASC, step_no ASC, created_at ASC""",
            (project_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def rollback_events(unit_id: str, after_step: int) -> int:
    """回滚: 删除 step_no > after_step 的 event.

    返回删除数量.
    """
    with _db_conn.transaction() as db:
        cur = db.execute(
            "DELETE FROM story_events WHERE unit_id = ? AND step_no > ?",
            (unit_id, int(after_step)),
        )
    if cur.rowcount:
        _logger.info("Event 回滚: unit=%s after_step=%d 删除=%d",
                     unit_id, after_step, cur.rowcount)
    return cur.rowcount


# ============================================================
# 便捷封装: Unit 完成自动算 diff + 记录
# ============================================================

def finalize_unit_events(
    unit_id: str,
    *,
    final_state: Optional[dict] = None,
) -> int:
    """Unit 完成时调用: 读 entry_state / exit_state, 算 diff, 写 event.

    Returns: 写入的 event 数量.
    """
    from app.services import story_unit_service_v2 as _unit_svc
    unit = _unit_svc.get(unit_id)
    try:
        entry = json.loads(unit.entry_characters or "{}")
    except json.JSONDecodeError:
        entry = {}
    if final_state is not None:
        exit_state = final_state
    else:
        try:
            exit_state = json.loads(unit.exit_characters or "{}")
        except json.JSONDecodeError:
            exit_state = {}

    events = compute_state_diff(unit_id, entry, exit_state)
    return record_events(unit_id, unit.current_step or 0, events, project_id=unit.project_id)


# ============================================================
# v3.5.2: Guide 接口 (GPT 评审)
# ============================================================

def get_guides(unit_id: str, project_id: str = "") -> list:
    """返回 Story Event 流相关的 Guide 列表.

    检测内容:
      1. 角色 state 变化大 (一次 unit 多个维度剧变, 可能 OOC)
      2. 关系 trust 大幅下降 (可能铺垫背叛)
      3. 物品突然获得/消失 (可能逻辑漏洞)
    """
    from app.core.types import Guide, Action, GUIDE_SCOPE_UNIT

    if not project_id:
        from app.services import story_unit_service_v2 as _unit_svc
        try:
            unit = _unit_svc.get(unit_id)
            project_id = unit.project_id
        except Exception:
            return []

    try:
        # 查本 unit 的 events
        events = list_events_as_of_unit(
            project_id, unit_id=unit_id, as_of_step=999999,
        )

        if not events:
            return []

        guides: list[Guide] = []

        # 1. 检查 trust 大幅下降
        trust_drops = []
        for ev in events:
            if ev.get("field_name") in ("trust", "好感度", "好感", "信任"):
                try:
                    old = float(ev.get("old_value") or 0)
                    new = float(ev.get("new_value") or 0)
                    if old - new >= 30:
                        trust_drops.append((ev["entity_name"], old, new))
                except (ValueError, TypeError):
                    pass

        if trust_drops:
            desc = "; ".join(f"{n}: {o}→{n_v}" for n, o, n_v in trust_drops[:5])
            guides.append(Guide(
                source="event",
                priority=0.7,
                confidence=0.85,
                scope=GUIDE_SCOPE_UNIT,
                advice=(
                    f"本 unit 内检测到 {len(trust_drops)} 个角色信任度大幅下降 (>=30): {desc}。"
                    f"AI 写作时需注意铺垫降因, 避免角色 OOC。"
                ),
                reason=f"trust drops in events: {len(trust_drops)}",
                evidence_ids=[ev.get("id", "") for ev in events[:5] if ev.get("field_name") in ("trust", "好感")],
                possible_actions=[
                    Action(label="加铺垫", description="补充角色关系恶化的前因"),
                    Action(label="继续", description="信任度下降是剧情设计, 保持"),
                ],
                context={"trust_drops": len(trust_drops)},
            ))

        # 2. 检查物品剧变
        item_changes = [ev for ev in events if ev.get("event_type") == "character_inventory"]
        if len(item_changes) >= 2:
            guides.append(Guide(
                source="event",
                priority=0.55,
                confidence=0.7,
                scope=GUIDE_SCOPE_UNIT,
                advice=f"本 unit 物品变动 {len(item_changes)} 次, 较多。注意不要让物品突然出现/消失, AI 写作时需保持物品逻辑一致。",
                reason=f"item changes >= 2: {len(item_changes)}",
                evidence_ids=[ev.get("id", "") for ev in item_changes[:5]],
                possible_actions=[
                    Action(label="检查物品", description="review 物品表, 确认逻辑自洽"),
                ],
                context={"item_changes": len(item_changes)},
            ))

        return guides
    except Exception:
        return []