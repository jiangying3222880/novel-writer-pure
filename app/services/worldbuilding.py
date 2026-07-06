"""
D3 世界观存储 (5 实体 + 5 文件 store)
- 5 实体: 修炼 power / 地理 location / 法宝 item / 人物 character / 势力 faction
- 5 表 (DB): 机器查询, 0 污染检索
- 5 文件 store (JSON 备份): 人看 + 物理备份, 在 {story_dir}/world_{project_id}/{kind}.json
- 关系: world_relations (任意两个实体多对多)
- 动态 5 维度用 character_trackers 表 (D3.1 区分: 静态定义 → world_characters, 动态 5 维度 → character_trackers)

D3.2 按章节任务匹配: get_for_chapter() 只返回该章需要的子集, 0 污染
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from app.services import file_store
from app.services.exceptions import NotFoundError, ValidationError
from app.db import _impl as _db_conn


def _conn():
    """统一拿连接 (单例, 与 character_tracker / ai.registry 一致)."""
    return _db_conn.get_conn()


# ============================================================
# 5 实体类型常量
# ============================================================

KIND_POWER = "power"
KIND_LOCATION = "location"
KIND_ITEM = "item"
KIND_CHARACTER = "character"
KIND_FACTION = "faction"

ALL_KINDS = [KIND_POWER, KIND_LOCATION, KIND_ITEM, KIND_CHARACTER, KIND_FACTION]

KIND_LABELS = {
    KIND_POWER: "修炼体系",
    KIND_LOCATION: "地理位置",
    KIND_ITEM: "法宝物品",
    KIND_CHARACTER: "人物",
    KIND_FACTION: "势力组织",
}

# 中文分词 stop words (DB 查询无关字)
_STOP_CHARS = set("的了是在我你他她它们和与及或之")


# ============================================================
# 5 实体 dataclass (统一, 字段超集)
# ============================================================

@dataclass
class Entity:
    """世界实体 (5 类之一)."""
    id: str
    project_id: str
    kind: str  # power/location/item/character/faction
    name: str
    description: str = ""
    metadata: dict = field(default_factory=dict)
    # 实体特定字段
    level: int = 0           # power: 等级
    region: str = ""         # location: 区域
    owner: str = ""          # item: 持有者
    tier: str = ""           # item: 品阶
    role: str = ""           # character: 主角/配角/敌人
    faction_id: str = ""     # character: 所属势力
    birth: str = ""          # character: 出身
    personality: str = ""    # character: 性格
    created_at: str = ""


# ============================================================
# 5 文件 store 工具
# ============================================================

def _world_dir(project_id: str) -> Path:
    """单个项目的世界文件 store 目录: {story_dir}/world_{project_id}/"""
    base = file_store.BASE_DIR / f"world_{project_id}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _store_path(project_id: str, kind: str) -> Path:
    """某类实体的 JSON 文件路径."""
    if kind not in ALL_KINDS:
        raise ValidationError(f"未知实体类型: {kind}")
    return _world_dir(project_id) / f"{kind}s.json"


def _save_store(project_id: str, kind: str, entities: list[dict]) -> None:
    """把某类全部实体存到 JSON 文件 (备份, 用于人看 + 物理备份)."""
    p = _store_path(project_id, kind)
    payload = {
        "kind": kind,
        "label": KIND_LABELS[kind],
        "count": len(entities),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "entities": entities,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_store(project_id: str, kind: str) -> list[dict]:
    """从 JSON 文件读某类全部实体 (用于人工编辑后回灌)."""
    p = _store_path(project_id, kind)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("entities", [])
    except (json.JSONDecodeError, OSError):
        return []


# ============================================================
# 通用 CRUD
# ============================================================

def _entity_from_row(row: sqlite3.Row, kind: str) -> Entity:
    """sqlite3.Row → Entity (根据 kind 取不同字段)."""
    md = {}
    try:
        md = json.loads(row["metadata"] or "{}")
    except json.JSONDecodeError:
        md = {}
    return Entity(
        id=row["id"],
        project_id=row["project_id"],
        kind=kind,
        name=row["name"],
        description=row["description"] or "",
        metadata=md,
        level=row["level"] if "level" in row.keys() else 0,
        region=row["region"] if "region" in row.keys() else "",
        owner=row["owner"] if "owner" in row.keys() else "",
        tier=row["tier"] if "tier" in row.keys() else "",
        role=row["role"] if "role" in row.keys() else "",
        faction_id=row["faction_id"] if "faction_id" in row.keys() else "",
        birth=row["birth"] if "birth" in row.keys() else "",
        personality=row["personality"] if "personality" in row.keys() else "",
        created_at=row["created_at"] or "",
    )


def _table_for(kind: str) -> str:
    return {
        KIND_POWER: "world_power_systems",
        KIND_LOCATION: "world_locations",
        KIND_ITEM: "world_items",
        KIND_CHARACTER: "world_characters",
        KIND_FACTION: "world_factions",
    }[kind]


def create(project_id: str, kind: str, name: str, **kwargs) -> Entity:
    """新建 1 个实体 (CRUD 之一).

    kind: power/location/item/character/faction
    kwargs: description/level/region/owner/tier/role/faction_id/birth/personality/metadata
    """
    if kind not in ALL_KINDS:
        raise ValidationError(f"未知实体类型: {kind}")
    if not name or not name.strip():
        raise ValidationError("实体名称不能为空")

    eid = f"{kind[0]}_{uuid.uuid4().hex[:8]}"
    md = kwargs.pop("metadata", {}) or {}
    md_json = json.dumps(md, ensure_ascii=False)

    columns = ["id", "project_id", "name", "description", "metadata"]
    values: list[Union[str, int]] = [eid, project_id, name.strip(), kwargs.get("description", ""), md_json]

    if kind == KIND_POWER:
        columns += ["level"]
        values.append(int(kwargs.get("level", 0)))
    elif kind == KIND_LOCATION:
        columns += ["region"]
        values.append(kwargs.get("region", ""))
    elif kind == KIND_ITEM:
        columns += ["owner", "tier"]
        values += [kwargs.get("owner", ""), kwargs.get("tier", "")]
    elif kind == KIND_CHARACTER:
        columns += ["role", "faction_id", "birth", "personality"]
        values += [
            kwargs.get("role", ""),
            kwargs.get("faction_id", ""),
            kwargs.get("birth", ""),
            kwargs.get("personality", ""),
        ]

    placeholders = ",".join(["?"] * len(values))
    cols_sql = ",".join(columns)
    sql = f"INSERT INTO {_table_for(kind)} ({cols_sql}) VALUES ({placeholders})"
    _conn().execute(sql, values)
    _conn().commit()

    e = get(eid, kind)
    # 备份到文件 store
    _backup_kind(project_id, kind)
    return e


def get(eid: str, kind: str) -> Entity:
    """按 id 取 1 个实体."""
    row = _conn().execute(
        f"SELECT * FROM {_table_for(kind)} WHERE id = ?", (eid,)
    ).fetchone()
    if not row:
        raise NotFoundError(f"{KIND_LABELS[kind]} 不存在: {eid}")
    return _entity_from_row(row, kind)


def list_all(project_id: str, kind: str) -> list[Entity]:
    """列某项目下某类全部实体 (按名称排序)."""
    rows = _conn().execute(
        f"SELECT * FROM {_table_for(kind)} WHERE project_id = ? ORDER BY name",
        (project_id,),
    ).fetchall()
    return [_entity_from_row(r, kind) for r in rows]


def update(eid: str, kind: str, **kwargs) -> Entity:
    """更新 1 个实体 (可改 name/description/metadata/特定字段)."""
    if kind not in ALL_KINDS:
        raise ValidationError(f"未知实体类型: {kind}")
    e = get(eid, kind)  # 404 校验

    sets: list[str] = []
    values: list[Union[str, int]] = []
    for fld in ("name", "description"):
        if fld in kwargs:
            sets.append(f"{fld} = ?")
            values.append(kwargs[fld])
    if "metadata" in kwargs:
        sets.append("metadata = ?")
        values.append(json.dumps(kwargs["metadata"] or {}, ensure_ascii=False))

    # 特定字段
    extra = {
        KIND_POWER: ("level",),
        KIND_LOCATION: ("region",),
        KIND_ITEM: ("owner", "tier"),
        KIND_CHARACTER: ("role", "faction_id", "birth", "personality"),
        KIND_FACTION: (),
    }
    for fld in extra[kind]:
        if fld in kwargs:
            sets.append(f"{fld} = ?")
            values.append(kwargs[fld])

    if not sets:
        return e  # 无更新

    values.append(eid)
    sql = f"UPDATE {_table_for(kind)} SET {', '.join(sets)} WHERE id = ?"
    _conn().execute(sql, values)
    _conn().commit()

    e2 = get(eid, kind)
    _backup_kind(e.project_id, kind)
    return e2


def delete(eid: str, kind: str) -> None:
    """删除 1 个实体 (同时清掉以它为端点的关系)."""
    e = get(eid, kind)  # 404 校验
    _conn().execute(f"DELETE FROM {_table_for(kind)} WHERE id = ?", (eid,))
    # 级联清关系
    _conn().execute(
        "DELETE FROM world_relations WHERE (src_id = ? AND src_type = ?) OR (dst_id = ? AND dst_type = ?)",
        (eid, kind, eid, kind),
    )
    _conn().commit()
    _backup_kind(e.project_id, kind)


# ============================================================
# 检索 (D3.2 按章节任务取子集, 0 污染)
# ============================================================

def _tokenize(text: str) -> list[str]:
    """简单中文分词: 单字 + 2字组合 + 过滤停用字."""
    if not text:
        return []
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    tokens: list[str] = []
    for word in text.split():
        if not word:
            continue
        # 单字
        for ch in word:
            if "\u4e00" <= ch <= "\u9fff" and ch not in _STOP_CHARS:
                tokens.append(ch)
        # 2字
        for i in range(len(word) - 1):
            bi = word[i:i + 2]
            if all("\u4e00" <= c <= "\u9fff" for c in bi):
                tokens.append(bi)
    return tokens


def search(project_id: str, kind: str, query: str, top_k: int = 5) -> list[Entity]:
    """在某类实体里按 query 模糊搜索 (TF 排序)."""
    tokens = _tokenize(query)
    if not tokens:
        return list_all(project_id, kind)[:top_k]

    candidates = list_all(project_id, kind)
    scored: list[tuple[int, Entity]] = []
    for e in candidates:
        # 拼接 name + description + metadata 文本
        haystack = e.name + " " + e.description + " " + json.dumps(e.metadata, ensure_ascii=False)
        score = sum(haystack.count(t) for t in tokens)
        if score > 0:
            scored.append((score, e))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:top_k]]


def get_for_chapter(
    project_id: str,
    chapter_brief: str,
    *,
    per_kind_limit: int = 3,
) -> dict[str, list[Entity]]:
    """D3.2: 按章节任务(brief)匹配当前章节想了解的信息, 0 污染.

    返回: {kind: [relevant entities]} 每类最多 per_kind_limit 个
    调用方拼 prompt 时只塞这批实体, 其他不取
    """
    out: dict[str, list[Entity]] = {}
    for kind in ALL_KINDS:
        hits = search(project_id, kind, chapter_brief, top_k=per_kind_limit)
        out[kind] = hits
    return out


# ============================================================
# 关系类型常量 (031 增强)
# ============================================================

RELATION_TYPES = {
    "emotional": "情感",      # 爱情/友情/亲情
    "benefit": "利益",        # 合作/竞争/交易
    "hostile": "敌对",        # 仇恨/对抗/冲突
    "mentor": "师徒",         # 师徒/指导/传承
    "blood": "血缘",          # 家族/血统/传承
    "location": "位置",       # 所属/位于/毗邻
    "ownership": "拥有",      # 持有/控制
    "alliance": "联盟",       # 结盟/同盟/联合
    "neutral": "中立",        # 中立/无关/旁观
    "general": "一般",        # 其他
}

RELATION_COLORS = {
    "emotional": "#ff6b9d",   # 粉红
    "benefit": "#ffd93d",     # 金黄
    "hostile": "#ff4757",     # 红色
    "mentor": "#5f7cff",      # 蓝色
    "blood": "#a855f7",       # 紫色
    "location": "#4ec970",    # 绿色
    "ownership": "#e8a23a",   # 橙色
    "alliance": "#00d2ff",    # 青色
    "neutral": "#9ca3af",     # 灰色
    "general": "#6c7ae0",     # 默认蓝紫
}


# ============================================================
# 关系 (world_relations 表)
# ============================================================

def add_relation(
    project_id: str,
    src_id: str, src_type: str,
    dst_id: str, dst_type: str,
    relation: str,
    *,
    relation_type: str = "general",
    intensity: int = 5,
    valid_from_chapter: Optional[int] = None,
    valid_to_chapter: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> str:
    """加 1 条关系.

    Args:
        relation_type: 关系类型 (emotional/benefit/hostile/mentor/blood/location/ownership/general)
        intensity: 关系强度 1-10 (1=微弱, 10=极强)
    """
    if not relation.strip():
        raise ValidationError("关系描述不能为空")
    if relation_type not in RELATION_TYPES:
        relation_type = "general"
    if not (1 <= intensity <= 10):
        intensity = max(1, min(10, intensity))

    rid = f"r_{uuid.uuid4().hex[:8]}"
    md_json = json.dumps(metadata or {}, ensure_ascii=False)
    _conn().execute(
        "INSERT INTO world_relations (id, project_id, src_id, src_type, dst_id, dst_type, relation, relation_type, intensity, valid_from_chapter, valid_to_chapter, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rid, project_id, src_id, src_type, dst_id, dst_type, relation, relation_type, intensity, valid_from_chapter, valid_to_chapter, md_json),
    )
    _conn().commit()
    return rid


def list_relations(project_id: str, *, entity_id: Optional[str] = None, relation_type: Optional[str] = None) -> list[dict]:
    """列某项目的关系 (可选按实体/类型过滤)."""
    conditions = ["project_id = ?"]
    params: list = [project_id]

    if entity_id:
        conditions.append("(src_id = ? OR dst_id = ?)")
        params.extend([entity_id, entity_id])

    if relation_type:
        conditions.append("relation_type = ?")
        params.append(relation_type)

    where = " AND ".join(conditions)
    rows = _conn().execute(
        f"SELECT * FROM world_relations WHERE {where} ORDER BY created_at",
        params,
    ).fetchall()

    out = []
    for r in rows:
        # sqlite3.Row 没有 .get() 方法，需要用字典推导式转换
        row_dict = {key: r[key] for key in r.keys()}
        out.append({
            "id": row_dict["id"],
            "src_id": row_dict["src_id"],
            "src_type": row_dict["src_type"],
            "dst_id": row_dict["dst_id"],
            "dst_type": row_dict["dst_type"],
            "relation": row_dict["relation"],
            "relation_type": row_dict.get("relation_type", "general"),
            "intensity": row_dict.get("intensity", 5),
            "valid_from_chapter": row_dict["valid_from_chapter"],
            "valid_to_chapter": row_dict["valid_to_chapter"],
            "metadata": json.loads(row_dict["metadata"] or "{}"),
        })
    return out


def update_relation(rid: str, *, relation: Optional[str] = None,
                   relation_type: Optional[str] = None,
                   intensity: Optional[int] = None) -> None:
    """更新关系 (031 增强)."""
    sets = []
    params = []

    if relation is not None:
        sets.append("relation = ?")
        params.append(relation)

    if relation_type is not None:
        if relation_type not in RELATION_TYPES:
            relation_type = "general"
        sets.append("relation_type = ?")
        params.append(relation_type)

    if intensity is not None:
        intensity = max(1, min(10, intensity))
        sets.append("intensity = ?")
        params.append(intensity)

    if not sets:
        return

    params.append(rid)
    _conn().execute(f"UPDATE world_relations SET {', '.join(sets)} WHERE id = ?", params)
    _conn().commit()


def delete_relation(rid: str) -> None:
    """删 1 条关系."""
    _conn().execute("DELETE FROM world_relations WHERE id = ?", (rid,))
    _conn().commit()


# ============================================================
# 5 文件 store 备份
# ============================================================

def _backup_kind(project_id: str, kind: str) -> None:
    """把某类全部实体写回 JSON 文件 (CRUD 后调用)."""
    entities = [asdict(e) for e in list_all(project_id, kind)]
    # metadata 已经是 dict, asdict 不会再 json
    _save_store(project_id, kind, entities)


def backup_all(project_id: str) -> dict[str, int]:
    """把 5 类全部备份到 JSON. 返回每类数量."""
    counts = {}
    for kind in ALL_KINDS:
        _backup_kind(project_id, kind)
        counts[kind] = len(list_all(project_id, kind))
    return counts


def restore_from_store(project_id: str, kind: str) -> int:
    """从 JSON 文件回灌到 DB (覆盖式). 返回写入数量.

    适用: 人工编辑 JSON 后, 一键同步回 DB.
    警告: 这会清空该 kind 现有数据.
    """
    if kind not in ALL_KINDS:
        raise ValidationError(f"未知实体类型: {kind}")
    data = _load_store(project_id, kind)
    if not data:
        return 0

    # 过滤掉非 create 参数 (id/project_id/kind/created_at 等)
    valid_keys = {
        KIND_POWER: ("name", "description", "level", "metadata"),
        KIND_LOCATION: ("name", "description", "region", "metadata"),
        KIND_ITEM: ("name", "description", "owner", "tier", "metadata"),
        KIND_CHARACTER: ("name", "description", "role", "faction_id", "birth", "personality", "metadata"),
        KIND_FACTION: ("name", "description", "metadata"),
    }[kind]

    cur = _conn()
    cur.execute(f"DELETE FROM {_table_for(kind)} WHERE project_id = ?", (project_id,))
    inserted = 0
    for d in data:
        # name 是 create 的位置参数, 从 kwargs 剔除
        kwargs = {k: v for k, v in d.items() if k in valid_keys and k != "name"}
        kwargs.setdefault("metadata", {})
        try:
            create(project_id, kind, d.get("name", "未命名"), **kwargs)
            inserted += 1
        except ValidationError:
            continue
    cur.commit()
    return inserted


# ============================================================
# 统计 / 总览
# ============================================================

def stats(project_id: str) -> dict:
    """世界观统计 (用于 dashboard / 仪表盘)."""
    counts = {kind: len(list_all(project_id, kind)) for kind in ALL_KINDS}
    rels = list_relations(project_id)
    counts["relation"] = len(rels)
    counts["total"] = sum(v for k, v in counts.items() if k != "relation")
    return counts
