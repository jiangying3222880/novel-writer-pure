"""
E1 人物追踪 (Character Tracker, 5 维度)
- 每个 (project, character, chapter) 1 行快照
- 5 维度: location / state / power_level / equipment / relationship
- 通过 chapter_id 排序, 最新一条代表当前状态
- 提供: record / get_latest / get_history / diff / search / list_characters

DB: app.db.connection (与 smoke 测试一致)
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Iterable

from app.db import connection
from app.db.models import CharacterTracker as _Model

_logger = logging.getLogger("NovelWriter.services.character_tracker")

# 5 个维度 (与 DB 字段一一对应)
DIM_LOCATION = "location"         # 位置: 主角在哪
DIM_STATE = "state"               # 状态: 身体/精神 (伤/疲惫/清醒)
DIM_POWER = "power_level"         # 实力: 境界/战力
DIM_EQUIPMENT = "equipment"       # 装备: 当前持有
DIM_RELATIONSHIP = "relationship" # 关系: 关键人际关系快照

ALL_DIMS = (
    DIM_LOCATION, DIM_STATE, DIM_POWER, DIM_EQUIPMENT, DIM_RELATIONSHIP,
)
DIM_LABELS = {
    DIM_LOCATION: "位置",
    DIM_STATE: "状态",
    DIM_POWER: "实力",
    DIM_EQUIPMENT: "装备",
    DIM_RELATIONSHIP: "关系",
}

# 维度值最大长度 (防误写长内容)
MAX_DIM_LEN = 500


# ────────────────────── 数据类 ──────────────────────

@dataclass
class TrackerSnapshot:
    """单条快照 (一行 DB 记录)。"""
    id: str
    project_id: str
    chapter_id: str
    character_name: str
    location: str = ""
    state: str = ""
    power_level: str = ""
    equipment: str = ""
    relationship: str = ""
    updated_at: str = ""

    @property
    def dims(self) -> dict:
        """返回 {dim_name: value} (过滤空值)。"""
        return {
            d: getattr(self, d)
            for d in ALL_DIMS
            if getattr(self, d, "")
        }

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "chapter_id": self.chapter_id,
            "character_name": self.character_name,
            **self.dims,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row) -> "TrackerSnapshot":
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            chapter_id=row["chapter_id"],
            character_name=row["character_name"],
            location=row["location"] or "",
            state=row["state"] or "",
            power_level=row["power_level"] or "",
            equipment=row["equipment"] or "",
            relationship=row["relationship"] or "",
            updated_at=row["updated_at"] or "",
        )


@dataclass
class DiffEntry:
    """diff 结果中的一条变化。"""
    dim: str
    dim_label: str
    before: str
    after: str

    @property
    def changed(self) -> bool:
        return self.before != self.after

    def to_dict(self) -> dict:
        return {
            "dim": self.dim,
            "label": self.dim_label,
            "before": self.before,
            "after": self.after,
            "changed": self.changed,
        }


# ────────────────────── 写入 ──────────────────────

def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _validate_dim_value(value: str) -> str:
    """校验维度值。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if len(value) > MAX_DIM_LEN:
        raise ValueError(f"维度值过长 (上限 {MAX_DIM_LEN} 字符, 实际 {len(value)})")
    return value


def record(
    project_id: str,
    chapter_id: str,
    character_name: str,
    *,
    location: str = "",
    state: str = "",
    power_level: str = "",
    equipment: str = "",
    relationship: str = "",
) -> TrackerSnapshot:
    """
    记录一个快照 (1 行, 5 维度可全空)。
    - 通常用法: 写完一章后, 记录主要人物当时的状态
    - 写入后会与之前的快照共存 (历史)
    """
    if not project_id or not chapter_id or not character_name:
        raise ValueError("project_id / chapter_id / character_name 必填")

    snap = TrackerSnapshot(
        id=_new_id(),
        project_id=project_id,
        chapter_id=chapter_id,
        character_name=character_name.strip(),
        location=_validate_dim_value(location),
        state=_validate_dim_value(state),
        power_level=_validate_dim_value(power_level),
        equipment=_validate_dim_value(equipment),
        relationship=_validate_dim_value(relationship),
    )
    conn = connection.get_conn()
    conn.execute(
        """
        INSERT INTO character_trackers
            (id, project_id, chapter_id, character_name,
             location, state, power_level, equipment, relationship, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (snap.id, snap.project_id, snap.chapter_id, snap.character_name,
         snap.location, snap.state, snap.power_level, snap.equipment,
         snap.relationship, datetime.now().isoformat(timespec="seconds")),
    )
    _logger.info("记录快照: %s @ %s (5 维度)", character_name, chapter_id)
    return snap


def record_dimension(
    project_id: str,
    chapter_id: str,
    character_name: str,
    dim: str,
    value: str,
) -> TrackerSnapshot:
    """
    只更新一个维度 (其他 4 维留空)。
    用途: 写章节过程中, 临时补一条 'position=xxx' 的轻量记录。
    """
    if dim not in ALL_DIMS:
        raise ValueError(f"未知维度: {dim} (合法: {ALL_DIMS})")
    kwargs = {dim: value}
    return record(project_id, chapter_id, character_name, **kwargs)


# ────────────────────── 读取 ──────────────────────

def get_latest(
    project_id: str,
    character_name: str,
    *,
    as_of_chapter: Optional[str] = None,
) -> Optional[TrackerSnapshot]:
    """
    取最新一条快照 (或 as_of_chapter 之前最后一条)。
    - as_of_chapter=None → 整个项目内最新
    - as_of_chapter="ch_X" → 第 X 章之前最后一条
    返回 None 表示无记录。
    """
    conn = connection.get_conn()
    if as_of_chapter is not None:
        row = conn.execute(
            """
            SELECT * FROM character_trackers
            WHERE project_id=? AND character_name=? AND chapter_id <= ?
            ORDER BY chapter_id DESC, updated_at DESC
            LIMIT 1
            """,
            (project_id, character_name, as_of_chapter),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT * FROM character_trackers
            WHERE project_id=? AND character_name=?
            ORDER BY chapter_id DESC, updated_at DESC
            LIMIT 1
            """,
            (project_id, character_name),
        ).fetchone()
    if row is None:
        return None
    return TrackerSnapshot.from_row(row)


def get_history(
    project_id: str,
    character_name: str,
    *,
    dim: Optional[str] = None,
    limit: int = 100,
) -> list[TrackerSnapshot]:
    """
    取历史快照 (按 chapter_id 升序)。
    - dim 指定时: 只返回该 dim 非空的行
    - limit: 最多返回 N 条 (默认 100)
    """
    if dim is not None and dim not in ALL_DIMS:
        raise ValueError(f"未知维度: {dim} (合法: {ALL_DIMS})")
    conn = connection.get_conn()
    if dim is not None:
        rows = conn.execute(
            f"""
            SELECT * FROM character_trackers
            WHERE project_id=? AND character_name=? AND {dim} != ''
            ORDER BY chapter_id ASC, updated_at ASC
            LIMIT ?
            """,
            (project_id, character_name, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM character_trackers
            WHERE project_id=? AND character_name=?
            ORDER BY chapter_id ASC, updated_at ASC
            LIMIT ?
            """,
            (project_id, character_name, limit),
        ).fetchall()
    return [TrackerSnapshot.from_row(r) for r in rows]


def list_characters(project_id: str) -> list[str]:
    """
    列出项目内所有出现过的角色 (去重, 按首次出现顺序)。
    """
    conn = connection.get_conn()
    rows = conn.execute(
        """
        SELECT character_name, MIN(chapter_id) AS first_chap
        FROM character_trackers
        WHERE project_id=?
        GROUP BY character_name
        ORDER BY first_chap ASC
        """,
        (project_id,),
    ).fetchall()
    return [r["character_name"] for r in rows]


def get_all_latest(project_id: str) -> dict[str, TrackerSnapshot]:
    """
    取所有角色的最新快照 → {character_name: snapshot}
    优化: 单条 SQL 替代 N+1 查询。
    """
    conn = connection.get_conn()
    rows = conn.execute(
        """
        SELECT ct.* FROM character_trackers ct
        INNER JOIN (
            SELECT character_name, MAX(chapter_id) AS max_chap
            FROM character_trackers
            WHERE project_id=?
            GROUP BY character_name
        ) latest ON ct.character_name = latest.character_name
                AND ct.chapter_id = latest.max_chap
                AND ct.project_id = ?
        ORDER BY ct.character_name
        """,
        (project_id, project_id),
    ).fetchall()
    return {r["character_name"]: TrackerSnapshot.from_row(r) for r in rows}


# ────────────────────── Diff / 搜索 ──────────────────────

def diff(
    project_id: str,
    character_name: str,
    from_chapter: str,
    to_chapter: str,
) -> list[DiffEntry]:
    """
    对比 from_chapter 和 to_chapter 时点的 5 维度差异。
    - 都用 as_of_chapter 查"该章之前最后一条"
    - 返回 5 个 DiffEntry, changed=True 的为真有变化
    """
    from_snap = get_latest(project_id, character_name, as_of_chapter=from_chapter)
    to_snap = get_latest(project_id, character_name, as_of_chapter=to_chapter)
    out: list[DiffEntry] = []
    for d in ALL_DIMS:
        before = getattr(from_snap, d, "") if from_snap else ""
        after = getattr(to_snap, d, "") if to_snap else ""
        out.append(DiffEntry(dim=d, dim_label=DIM_LABELS[d], before=before, after=after))
    return out


def search_dimension(
    project_id: str,
    query: str,
    *,
    dim: Optional[str] = None,
    limit: int = 50,
) -> list[TrackerSnapshot]:
    """
    在维度值中搜关键词 (LIKE 匹配, 不区分大小写)。
    - dim 指定时: 只搜该维度
    - dim=None: 搜全部 5 个维度
    """
    if not query or not query.strip():
        return []
    if dim is not None and dim not in ALL_DIMS:
        raise ValueError(f"未知维度: {dim} (合法: {ALL_DIMS})")
    pat = f"%{query.strip()}%"
    conn = connection.get_conn()
    if dim is not None:
        rows = conn.execute(
            f"""
            SELECT * FROM character_trackers
            WHERE project_id=? AND {dim} LIKE ?
            ORDER BY chapter_id DESC
            LIMIT ?
            """,
            (project_id, pat, limit),
        ).fetchall()
    else:
        # 5 个维度 OR
        rows = conn.execute(
            """
            SELECT * FROM character_trackers
            WHERE project_id=? AND (
                location LIKE ? OR state LIKE ? OR power_level LIKE ? OR
                equipment LIKE ? OR relationship LIKE ?
            )
            ORDER BY chapter_id DESC
            LIMIT ?
            """,
            (project_id, pat, pat, pat, pat, pat, limit),
        ).fetchall()
    return [TrackerSnapshot.from_row(r) for r in rows]


# ────────────────────── 维护 ──────────────────────

def delete_for_chapter(project_id: str, chapter_id: str) -> int:
    """
    删除某章所有角色的快照 (章节重写/删除时用)。
    返回删除条数。
    """
    conn = connection.get_conn()
    cur = conn.execute(
        "DELETE FROM character_trackers WHERE project_id=? AND chapter_id=?",
        (project_id, chapter_id),
    )
    return cur.rowcount or 0


def delete_for_character(project_id: str, character_name: str) -> int:
    """删除某角色的全部快照 (慎用)。"""
    conn = connection.get_conn()
    cur = conn.execute(
        "DELETE FROM character_trackers WHERE project_id=? AND character_name=?",
        (project_id, character_name),
    )
    return cur.rowcount or 0


# ────────────────────── 格式化输出 ──────────────────────

def format_snapshot(snap: TrackerSnapshot, *, include_empty: bool = False) -> str:
    """
    把快照格式化成可读字符串 (用于 prompt 拼装 / UI 展示)。
    - include_empty=False (默认): 跳过空维度
    """
    if snap is None:
        return "(无记录)"
    lines = [f"【{snap.character_name} @ {snap.chapter_id}】"]
    for d in ALL_DIMS:
        val = getattr(snap, d, "")
        if val or include_empty:
            lines.append(f"  - {DIM_LABELS[d]}: {val or '(空)'}")
    return "\n".join(lines)


def format_all_latest(project_id: str) -> str:
    """
    拼装所有角色最新状态 (供 prompt 拼装, ~200 字内)。
    """
    all_latest = get_all_latest(project_id)
    if not all_latest:
        return "(无角色记录)"
    chunks = []
    for name, snap in list(all_latest.items())[:10]:  # 最多 10 个角色
        non_empty = [
            f"{DIM_LABELS[d]}={getattr(snap, d, '')}"
            for d in ALL_DIMS
            if getattr(snap, d, "")
        ]
        if non_empty:
            chunks.append(f"{name}: " + "; ".join(non_empty))
    return "\n".join(chunks)


# 导出
__all__ = [
    "DIM_LOCATION", "DIM_STATE", "DIM_POWER", "DIM_EQUIPMENT", "DIM_RELATIONSHIP",
    "ALL_DIMS", "DIM_LABELS",
    "TrackerSnapshot", "DiffEntry",
    "record", "record_dimension",
    "get_latest", "get_history", "list_characters", "get_all_latest",
    "diff", "search_dimension",
    "delete_for_chapter", "delete_for_character",
    "format_snapshot", "format_all_latest",
    "MAX_DIM_LEN",
]
