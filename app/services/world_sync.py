"""
D4 世界观同步
- sync_after_chapter(pid, cid, draft): 写完章节后
  1. 用本地实体库做 name 提取 (无需 AI, 0 tokens)
  2. 跟 DB 中实体名对比, 记录 world_state_snapshots
  3. 触发 character_trackers 状态更新 (如果简述中提到)
- detect_contradictions(pid, draft): 矛盾检测
  1. 提取出现的实体
  2. 对比 character_trackers 上一章状态
  3. 报告"某实体位置/状态/装备在不同章矛盾"

简化版: 不调 AI, 用正则扫实体名 + 关键词匹配矛盾
0 tokens 费用
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from app.services import worldbuilding, character_tracker
from app.db import _impl as _db_conn
from app.services.exceptions import ValidationError


def _conn():
    return _db_conn.get_conn()


# ============================================================
# 实体名提取 (本地, 0 tokens)
# ============================================================

def _extract_entity_names(project_id: str) -> dict[str, list[str]]:
    """从世界库取所有实体名, 按 kind 归类. 用于正文扫描."""
    out: dict[str, list[str]] = defaultdict(list)
    for kind in worldbuilding.ALL_KINDS:
        for e in worldbuilding.list_all(project_id, kind):
            if e.name and e.name.strip():
                out[kind].append(e.name.strip())
    return out


def _names_in_text(text: str, names: list[str]) -> list[str]:
    """文本里出现了哪些实体名 (按长度降序, 防止短名误匹配)."""
    if not text or not names:
        return []
    found: list[str] = []
    text_lower = text
    for n in sorted(names, key=lambda x: -len(x)):
        if n in text_lower and n not in found:
            found.append(n)
    return found


# ============================================================
# 写后同步
# ============================================================

@dataclass
class SyncResult:
    """sync_after_chapter 返回值."""
    chapter_id: str
    entities_mentioned: dict[str, list[str]]  # {kind: [name1, name2, ...]}
    snapshots_recorded: int                    # world_state_snapshots 新增数
    characters_updated: int                   # character_trackers 新增/更新数
    new_relations_hints: list[str] = field(default_factory=list)  # 提示用户手动确认


def sync_after_chapter(
    project_id: str,
    chapter_id: str,
    chapter_no: int,
    draft: str,
) -> SyncResult:
    """写完一章后调一次.

    1. 扫正文里出现了哪些实体 (5 类 + 关系)
    2. 给 world_state_snapshots 记快照 (用于 G10 时间轴)
    3. 提取本章出现的角色, 给 character_trackers 加一条 (无变化则跳过)
    4. 检测"X 用 Y 法宝"类关系提示, 给用户确认
    """
    if not draft or not draft.strip():
        raise ValidationError("章节正文不能为空")

    entities_mentioned = _scan_mentions(project_id, draft)
    snapshots = 0
    characters = 0
    relation_hints: list[str] = []

    with _db_conn.transaction() as cur:
        # 1) world_state_snapshots: 每出现一个实体就记一条
        for kind, names in entities_mentioned.items():
            for n in names:
                snap_id = f"s_{uuid.uuid4().hex[:10]}"
                try:
                    cur.execute(
                        "INSERT INTO world_state_snapshots (id, project_id, chapter_no, entity_name, entity_kind, source) "
                        "VALUES (?, ?, ?, ?, ?, 'observer')",
                        (snap_id, project_id, chapter_no, n, kind),
                    )
                    snapshots += 1
                except Exception:
                    # UNIQUE 冲突 (同章同实体只记一次)
                    pass

        # 2) character_trackers: 角色出现 = 加一条 (只记出现, 不改 5 维)
        for name in entities_mentioned.get(worldbuilding.KIND_CHARACTER, []):
            existing = cur.execute(
                "SELECT id FROM character_trackers WHERE project_id = ? AND chapter_id = ? AND character_name = ?",
                (project_id, chapter_id, name),
            ).fetchone()
            if not existing:
                try:
                    cur.execute(
                        """
                        INSERT INTO character_trackers
                            (id, project_id, chapter_id, character_name,
                             location, state, power_level, equipment, relationship, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
                        """,
                        (f"ct_{uuid.uuid4().hex[:10]}", project_id, chapter_id, name,
                         "", "出现", "", "", ""),
                    )
                    characters += 1
                except Exception:
                    pass

    # 3) 关系提示: 扫"X 用 Y"/"X 持 Y" 类短语, 提示用户加关系
    relation_hints = _detect_relation_hints(draft, entities_mentioned)

    # 派发事件
    try:
        from app.core.event_bus import get_bus, Events
        bus = get_bus()
        bus.publish(Events.WORLD_SYNCED, {
            "project_id": project_id,
            "chapter_id": chapter_id,
            "chapter_no": chapter_no,
            "snapshots": snapshots,
            "characters": characters,
            "mentions": entities_mentioned,
        })
    except Exception:
        pass

    return SyncResult(
        chapter_id=chapter_id,
        entities_mentioned=entities_mentioned,
        snapshots_recorded=snapshots,
        characters_updated=characters,
        new_relations_hints=relation_hints,
    )


def _scan_mentions(project_id: str, draft: str) -> dict[str, list[str]]:
    """扫正文, 找出出现的 5 类实体."""
    names = _extract_entity_names(project_id)
    out: dict[str, list[str]] = {}
    for kind, name_list in names.items():
        hits = _names_in_text(draft, name_list)
        if hits:
            out[kind] = hits
    return out


# 关系提示的简单正则: "X 持 Y" / "X 用 Y" / "X 赠 Y 给 Z" / "X 拜 Z 为师"
_RELATION_PATTERNS = [
    (re.compile(r"(\S{1,8}?)\s*持(?:有)?\s*(\S{1,8})"), "持有"),
    (re.compile(r"(\S{1,8}?)\s*使用\s*(\S{1,8})"), "使用"),
    (re.compile(r"(\S{1,8}?)\s*拜\s*(\S{1,8}?)\s*为师"), "拜师"),
    (re.compile(r"(\S{1,8}?)\s*赠[与]?\s*(\S{1,8}?)\s*给\s*(\S{1,8})"), "赠予"),
    (re.compile(r"(\S{1,8}?)\s*属于\s*(\S{1,8})"), "属于"),
]


def _detect_relation_hints(draft: str, entities: dict[str, list[str]]) -> list[str]:
    """扫正文里"X 持 Y"/"X 拜 Y 为师" 类关系描述, 返回提示列表."""
    all_names = set()
    for names in entities.values():
        all_names.update(names)
    if not all_names:
        return []

    hints: list[str] = []
    for pat, rel in _RELATION_PATTERNS:
        for m in pat.finditer(draft):
            parts = [g for g in m.groups() if g]
            # 只保留至少 1 个匹配到实体名的提示
            if any(p in all_names for p in parts):
                hints.append(f"  · {rel}: " + " → ".join(parts))
    return hints


# ============================================================
# 矛盾检测
# ============================================================

@dataclass
class Contradiction:
    """单个矛盾."""
    character: str
    chapter_id: str
    field: str        # location/state/power_level/equipment/relationship
    old_value: str
    new_value: str
    severity: str     # "high"/"medium"/"low"


def detect_contradictions(
    project_id: str,
    chapter_id: str,
    chapter_no: int,
    draft: str,
) -> list[Contradiction]:
    """对比本章角色新状态与上一章, 找矛盾.

    简化版: 本章 character_trackers 已记的 5 维度 vs 上一章同角色同维度
    比如: 第 5 章记 location="破庙", 第 8 章又记 location="皇城", 没有中间移动描述
    → 报矛盾 (medium)

    暂不解析正文(需要 AI), 只比 DB
    """
    cur = _conn()
    rows = cur.execute(
        "SELECT * FROM character_trackers WHERE project_id = ? AND chapter_id = ?",
        (project_id, chapter_id),
    ).fetchall()

    issues: list[Contradiction] = []
    for r in rows:
        cname = r["character_name"]
        # 找上一章 (chapter_no 小的最近一条)
        prev = cur.execute(
            "SELECT * FROM character_trackers WHERE project_id = ? AND character_name = ? AND id != ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (project_id, cname, r["id"]),
        ).fetchone()
        if not prev:
            continue

        for fld in ("location", "state", "power_level", "equipment", "relationship"):
            old = (prev[fld] or "").strip()
            new = (r[fld] or "").strip()
            if not old or not new:
                continue
            if old == new:
                continue
            # 同章多次记录 = 忽略 (幂等)
            # 不同值 = 矛盾 (严重度: 修真类 location 跳变 = high)
            severity = "medium"
            if fld == "location" and old != new:
                severity = "high"  # 位置跳变最严重
            elif fld == "power_level" and old != new:
                severity = "high"  # 实力跳变也严重
            issues.append(Contradiction(
                character=cname,
                chapter_id=chapter_id,
                field=fld,
                old_value=old,
                new_value=new,
                severity=severity,
            ))
    return issues


# ============================================================
# 时间轴查询 (供 G10 / 仪表盘用)
# ============================================================

def timeline(project_id: str, entity_name: str) -> list[dict]:
    """某实体出现过的章节 (按 chapter_no 升序)."""
    rows = _conn().execute(
        "SELECT chapter_no, entity_kind, source, created_at FROM world_state_snapshots "
        "WHERE project_id = ? AND entity_name = ? ORDER BY chapter_no",
        (project_id, entity_name),
    ).fetchall()
    return [dict(r) for r in rows]


def snapshot_stats(project_id: str) -> dict:
    """快照统计 (仪表盘)."""
    cur = _conn()
    total = cur.execute(
        "SELECT COUNT(*) AS c FROM world_state_snapshots WHERE project_id = ?",
        (project_id,),
    ).fetchone()["c"]
    by_kind: dict[str, int] = {}
    for r in cur.execute(
        "SELECT entity_kind, COUNT(*) AS c FROM world_state_snapshots WHERE project_id = ? GROUP BY entity_kind",
        (project_id,),
    ).fetchall():
        by_kind[r["entity_kind"] or "unknown"] = r["c"]
    return {"total": total, "by_kind": by_kind}
