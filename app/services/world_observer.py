"""
G10 世界状态观察器 (World State Observer)
业务场景:
  - 用户写到第 30 章, 想看"主角走到哪了 / 拿到啥法宝了 / 跟谁结仇了"
  - 用户在仪表盘看"世界观时间轴"
  - B3.3 实体图谱插件拿数据画人物关系图
  - "X 死了没" / "X 在哪" / "X 现在跟 Y 什么关系" 一键查

设计:
  - 数据源: world_state_snapshots (D4 已建表) + character_trackers (E1)
  - 0 tokens 费用 (纯 SQL 查询 + 简单 diff)
  - 与 world_sync 配套: sync 写, observer 读 + 分析
  - 与 B3.3 实体图谱插件联动: 导出 nodes/edges 格式

联动点:
  - world_sync.sync_after_chapter() → 写快照
  - character_tracker.record()        → 写 5 维度
  - world_observer (本模块)          → 读 + 聚合 + 导出
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.db import _impl as _db_conn
from app.services import world_sync, character_tracker, worldbuilding

_logger = logging.getLogger("NovelWriter.services.world_observer")


def _conn():
    return _db_conn.get_conn()


# ============================================================
# 数据类型
# ============================================================

@dataclass
class EntityHistory:
    """某实体在所有章节中的出现记录."""
    entity_name: str
    entity_kind: str
    first_chapter: int
    last_chapter: int
    total_chapters: int
    chapters: list[int] = field(default_factory=list)
    is_active: bool = False  # last_chapter == current_chapter


@dataclass
class ChapterChange:
    """某章的状态变化."""
    chapter_no: int
    new_entities: list[str] = field(default_factory=list)        # 本章首次出现
    returning_entities: list[str] = field(default_factory=list)  # 之前出现 + 本章又出现
    disappeared: list[str] = field(default_factory=list)         # 上一章出现但本章未出现


@dataclass
class StateSnapshot:
    """某章的完整快照 (供时间轴 UI 渲染)."""
    chapter_no: int
    entities: dict[str, list[str]] = field(default_factory=dict)  # {kind: [name1, name2, ...]}
    total_entities: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)


@dataclass
class StateDrift:
    """某实体的状态漂移 (长时间不出现 / 关键属性缺失)."""
    entity_name: str
    entity_kind: str
    last_chapter: int
    chapters_since_last: int
    drift_kind: str         # "absent" / "incomplete" / "stale_location"
    severity: str           # "high" / "medium" / "low"
    hint: str = ""          # 人类可读提示


@dataclass
class GraphData:
    """实体图谱数据 (供 B3.3 插件画节点边)."""
    nodes: list[dict] = field(default_factory=list)  # [{id, label, kind, size}, ...]
    edges: list[dict] = field(default_factory=list)  # [{source, target, kind, weight, chapters}, ...]
    chapter_no: int = 0


# ============================================================
# 1. observe_chapter - 观察一章
# ============================================================

def observe_chapter(
    project_id: str,
    chapter_id: str,
    chapter_no: int,
    draft: str,
) -> dict:
    """观察一章: 调 world_sync 写快照 + 计算本章变化.

    返回:
      {
        "snapshot_count": N,
        "new_entities": [...],
        "returning_entities": [...],
        "disappeared": [...],
      }
    """
    sync_result = world_sync.sync_after_chapter(
        project_id, chapter_id, chapter_no, draft
    )
    change = get_chapter_changes(project_id, chapter_no)
    return {
        "snapshot_count": sync_result.snapshots_recorded,
        "characters_updated": sync_result.characters_updated,
        "new_entities": change.new_entities,
        "returning_entities": change.returning_entities,
        "disappeared": change.disappeared,
        "relation_hints": sync_result.new_relations_hints,
    }


# ============================================================
# 2. get_entity_history - 实体历史
# ============================================================

def get_entity_history(project_id: str, entity_name: str) -> Optional[EntityHistory]:
    """某实体在所有章节中的出现记录 (按 chapter_no 升序)."""
    cur = _conn()
    rows = cur.execute(
        "SELECT chapter_no, entity_kind FROM world_state_snapshots "
        "WHERE project_id = ? AND entity_name = ? ORDER BY chapter_no",
        (project_id, entity_name),
    ).fetchall()
    if not rows:
        return None
    chapters = [r["chapter_no"] for r in rows]
    kind = rows[0]["entity_kind"] or "unknown"
    current_chapter = _get_current_chapter(project_id)
    return EntityHistory(
        entity_name=entity_name,
        entity_kind=kind,
        first_chapter=chapters[0],
        last_chapter=chapters[-1],
        total_chapters=len(chapters),
        chapters=chapters,
        is_active=(chapters[-1] == current_chapter),
    )


def list_tracked_entities(project_id: str) -> list[str]:
    """列出项目里所有被观察过的实体名 (去重)."""
    cur = _conn()
    rows = cur.execute(
        "SELECT DISTINCT entity_name FROM world_state_snapshots "
        "WHERE project_id = ? ORDER BY entity_name",
        (project_id,),
    ).fetchall()
    return [r["entity_name"] for r in rows]


# ============================================================
# 3. get_chapter_changes - 本章变化
# ============================================================

def get_chapter_changes(project_id: str, chapter_no: int) -> ChapterChange:
    """本章新增 / 返回 / 消失的实体.

    new:         本章出现且之前没出现过
    returning:   本章出现且之前出现过
    disappeared: 上一章出现但本章未出现 (不是最后消失 → 视为暂时离开)
    """
    cur = _conn()
    # 本章出现的实体
    cur_rows = cur.execute(
        "SELECT DISTINCT entity_name, entity_kind FROM world_state_snapshots "
        "WHERE project_id = ? AND chapter_no = ?",
        (project_id, chapter_no),
    ).fetchall()
    current_names = {r["entity_name"] for r in cur_rows}

    # 之前所有章 (本章之前) 出现过的实体
    prev_rows = cur.execute(
        "SELECT DISTINCT entity_name FROM world_state_snapshots "
        "WHERE project_id = ? AND chapter_no < ?",
        (project_id, chapter_no),
    ).fetchall()
    prev_names = {r["entity_name"] for r in prev_rows}

    # 上一章出现但本章未出现
    if chapter_no > 0:
        last_rows = cur.execute(
            "SELECT DISTINCT entity_name FROM world_state_snapshots "
            "WHERE project_id = ? AND chapter_no = ?",
            (project_id, chapter_no - 1),
        ).fetchall()
        last_names = {r["entity_name"] for r in last_rows}
    else:
        last_names = set()

    new_entities = sorted(current_names - prev_names)
    returning = sorted(current_names & prev_names)
    disappeared = sorted(last_names - current_names)

    return ChapterChange(
        chapter_no=chapter_no,
        new_entities=new_entities,
        returning_entities=returning,
        disappeared=disappeared,
    )


# ============================================================
# 4. get_project_snapshot - 完整快照
# ============================================================

def get_project_snapshot(project_id: str, chapter_no: int) -> StateSnapshot:
    """某章的完整快照 (本章所有出现的实体按 kind 分组)."""
    cur = _conn()
    rows = cur.execute(
        "SELECT entity_name, entity_kind FROM world_state_snapshots "
        "WHERE project_id = ? AND chapter_no = ? "
        "ORDER BY entity_kind, entity_name",
        (project_id, chapter_no),
    ).fetchall()
    entities: dict[str, list[str]] = {}
    by_kind: dict[str, int] = {}
    for r in rows:
        kind = r["entity_kind"] or "unknown"
        entities.setdefault(kind, []).append(r["entity_name"])
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return StateSnapshot(
        chapter_no=chapter_no,
        entities=entities,
        total_entities=sum(by_kind.values()),
        by_kind=by_kind,
    )


# ============================================================
# 5. get_chronicle - 编年史
# ============================================================

def get_chronicle(project_id: str, *, limit: int = 50) -> list[ChapterChange]:
    """编年史: 倒序返回最近 N 章的变化 (每章的 new/returning/disappeared).

    用于仪表盘 / 时间轴 UI: 让用户一眼看到"第 30 章新增了 X / 上一章的 Y 消失了"
    """
    cur = _conn()
    # 取最近 N 章
    rows = cur.execute(
        "SELECT DISTINCT chapter_no FROM world_state_snapshots "
        "WHERE project_id = ? ORDER BY chapter_no DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    chapter_nos = sorted([r["chapter_no"] for r in rows], reverse=True)
    return [get_chapter_changes(project_id, c) for c in chapter_nos]


# ============================================================
# 6. get_state_drift - 漂移检测
# ============================================================

def get_state_drift(
    project_id: str,
    entity_name: str,
    *,
    threshold_chapters: int = 5,
) -> Optional[StateDrift]:
    """检测某实体的状态漂移.

    - 主角/重要配角消失超过 N 章 → drift_kind="absent", severity=high
    - 5 维度 (location/state/power_level/equipment/relationship) 全空 → "incomplete"
    - location 在某章后未变 → "stale_location"

    返回 None 表示实体从未被观察过.
    """
    cur = _conn()
    # 找实体信息
    first_row = cur.execute(
        "SELECT entity_kind FROM world_state_snapshots "
        "WHERE project_id = ? AND entity_name = ? "
        "ORDER BY chapter_no LIMIT 1",
        (project_id, entity_name),
    ).fetchone()
    if not first_row:
        return None
    kind = first_row["entity_kind"] or "unknown"

    # 最后一次出现
    last_row = cur.execute(
        "SELECT chapter_no FROM world_state_snapshots "
        "WHERE project_id = ? AND entity_name = ? "
        "ORDER BY chapter_no DESC LIMIT 1",
        (project_id, entity_name),
    ).fetchone()
    last_chapter = last_row["chapter_no"]
    current_chapter = _get_current_chapter(project_id)
    chapters_since = current_chapter - last_chapter

    # 5 维度完整度 (如果该实体是角色)
    incomplete = False
    if kind == worldbuilding.KIND_CHARACTER:
        rows = cur.execute(
            "SELECT location, state, power_level, equipment, relationship "
            "FROM character_trackers WHERE project_id = ? AND character_name = ?",
            (project_id, entity_name),
        ).fetchall()
        # 只看最近的记录
        if rows:
            latest = rows[-1]
            filled = sum(1 for fld in ("location", "state", "power_level", "equipment", "relationship")
                         if (latest[fld] or "").strip())
            if filled == 0:
                incomplete = True

    # 判断漂移类型
    if chapters_since > threshold_chapters:
        severity = "high" if chapters_since > threshold_chapters * 2 else "medium"
        hint = f"已 {chapters_since} 章未出现, 超过阈值 {threshold_chapters} 章"
        return StateDrift(
            entity_name=entity_name,
            entity_kind=kind,
            last_chapter=last_chapter,
            chapters_since_last=chapters_since,
            drift_kind="absent",
            severity=severity,
            hint=hint,
        )
    if incomplete:
        return StateDrift(
            entity_name=entity_name,
            entity_kind=kind,
            last_chapter=last_chapter,
            chapters_since_last=chapters_since,
            drift_kind="incomplete",
            severity="low",
            hint="5 维度 (位置/状态/实力/装备/关系) 全空, 建议补充",
        )
    return None


def list_drifted_entities(
    project_id: str, *, threshold_chapters: int = 5
) -> list[StateDrift]:
    """列出所有有漂移的实体 (按 severity 降序)."""
    names = list_tracked_entities(project_id)
    drifts: list[StateDrift] = []
    for n in names:
        d = get_state_drift(project_id, n, threshold_chapters=threshold_chapters)
        if d:
            drifts.append(d)
    severity_order = {"high": 0, "medium": 1, "low": 2}
    drifts.sort(key=lambda d: (severity_order.get(d.severity, 99), -d.chapters_since_last))
    return drifts


# ============================================================
# 7. get_relations_graph - 实体图谱数据 (供 B3.3 插件)
# ============================================================

def get_relations_graph(
    project_id: str, *, chapter_no: Optional[int] = None
) -> GraphData:
    """导出图谱数据 (供 B3.3 实体图谱插件).

    节点: 实体 (按出现频次算 size)
    边: 同一章共现的两个实体 (按共现章节数算 weight)

    chapter_no = None → 全项目聚合
    chapter_no = N    → 只看 N 章 (含) 之前的所有共现
    """
    cur = _conn()
    if chapter_no is not None:
        snap_rows = cur.execute(
            "SELECT chapter_no, entity_name, entity_kind FROM world_state_snapshots "
            "WHERE project_id = ? AND chapter_no <= ? "
            "ORDER BY chapter_no, entity_name",
            (project_id, chapter_no),
        ).fetchall()
        chapter_filter = chapter_no
    else:
        snap_rows = cur.execute(
            "SELECT chapter_no, entity_name, entity_kind FROM world_state_snapshots "
            "WHERE project_id = ? ORDER BY chapter_no, entity_name",
            (project_id,),
        ).fetchall()
        chapter_filter = _get_current_chapter(project_id)

    # 统计节点: 实体名 → {kind, count}
    node_map: dict[str, dict] = {}
    # 统计边: (a, b) → {count, chapters}
    edge_map: dict[tuple[str, str], set] = {}
    # 按章分组
    chapter_entities: dict[int, set[str]] = {}
    for r in snap_rows:
        cno = r["chapter_no"]
        name = r["entity_name"]
        kind = r["entity_kind"] or "unknown"
        chapter_entities.setdefault(cno, set()).add(name)
        if name not in node_map:
            node_map[name] = {"kind": kind, "count": 0}
        node_map[name]["count"] += 1

    # 同一章共现 → 边
    for cno, names in chapter_entities.items():
        sorted_names = sorted(names)
        for i, a in enumerate(sorted_names):
            for b in sorted_names[i + 1:]:
                key = (a, b)
                edge_map.setdefault(key, set()).add(cno)

    # 序列化
    nodes = [
        {
            "id": name,
            "label": name,
            "kind": data["kind"],
            "size": data["count"],
        }
        for name, data in sorted(node_map.items(), key=lambda x: -x[1]["count"])
    ]
    edges = [
        {
            "source": a,
            "target": b,
            "kind": "co_occurrence",
            "weight": len(chapters),
            "chapters": sorted(chapters),
        }
        for (a, b), chapters in sorted(
            edge_map.items(), key=lambda x: -len(x[1])
        )
    ]
    return GraphData(nodes=nodes, edges=edges, chapter_no=chapter_filter)


# ============================================================
# 8. get_observer_stats - 仪表盘统计
# ============================================================

def get_observer_stats(project_id: str) -> dict:
    """观察器统计 (供仪表盘 / 章节管理页角标).

    {
        "total_snapshots": N,
        "total_entities": N,
        "by_kind": {"character": N, "item": M, ...},
        "active_chapters": N,    # 至少 1 个实体的章数
        "drift_count": N,        # 有漂移的实体数
    }
    """
    cur = _conn()
    total_snap = cur.execute(
        "SELECT COUNT(*) AS c FROM world_state_snapshots WHERE project_id = ?",
        (project_id,),
    ).fetchone()["c"]
    by_kind_rows = cur.execute(
        "SELECT entity_kind, COUNT(*) AS c FROM world_state_snapshots "
        "WHERE project_id = ? GROUP BY entity_kind",
        (project_id,),
    ).fetchall()
    by_kind = {r["entity_kind"] or "unknown": r["c"] for r in by_kind_rows}
    total_entities = cur.execute(
        "SELECT COUNT(DISTINCT entity_name) AS c FROM world_state_snapshots "
        "WHERE project_id = ?",
        (project_id,),
    ).fetchone()["c"]
    active_chapters = cur.execute(
        "SELECT COUNT(DISTINCT chapter_no) AS c FROM world_state_snapshots "
        "WHERE project_id = ?",
        (project_id,),
    ).fetchone()["c"]
    drift = list_drifted_entities(project_id)
    return {
        "total_snapshots": total_snap,
        "total_entities": total_entities,
        "by_kind": by_kind,
        "active_chapters": active_chapters,
        "drift_count": len(drift),
    }


# ============================================================
# 内部工具
# ============================================================

def _get_current_chapter(project_id: str) -> int:
    """项目当前写到第几章 (取 chapters 表的最大 chapter_no)."""
    cur = _conn()
    row = cur.execute(
        "SELECT MAX(chapter_no) AS c FROM chapters "
        "JOIN books ON chapters.book_id = books.id "
        "WHERE books.project_id = ?",
        (project_id,),
    ).fetchone()
    return int(row["c"] or 0)
