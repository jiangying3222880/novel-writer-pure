"""
E2 记忆系统 (L1-L4 + 承诺/世界规则)
- L1 故事弧: 主线/副线/人物弧, 始终可用
- L2 承诺: active 必履行, promise 待履行
- L2 世界规则: 不可变 (修真体系/法则)
- L3 RAG: 检索回来的 chunk (临时)
- L4 优雅遗忘: 从 L3 转移过来, 保留索引但不入上下文

DB: app.db.connection
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.db import connection
from app.core.constants import MemoryLevel

_logger = logging.getLogger("NovelWriter.services.memory")


# ────────────────────── 记忆分类 (与 DB 字段对应) ──────────────────────

# L1
CAT_ARC_MAIN = "arc_main"                 # 主线
CAT_ARC_SUB = "arc_sub"                   # 副线
CAT_ARC_CHAR = "arc_char"                 # 人物弧
# L2 commitment
CAT_COMMIT_ACTIVE = "commitment_active"   # 主角已承诺/已触发
CAT_COMMIT_PROMISE = "commitment_promise" # 主角答应过/欠下
# L2 world rule
CAT_WORLD_POWER = "world_rule_power"      # 力量体系规则
CAT_WORLD_VIEW = "world_rule_view"        # 世界观规则
# L3 RAG
CAT_RAG_CHUNK = "rag_chunk"               # 检索临时
# L4 遗忘
CAT_FADED = "faded_detail"                # 已淡忘

L1_CATEGORIES = (CAT_ARC_MAIN, CAT_ARC_SUB, CAT_ARC_CHAR)
L2_CATEGORIES = (CAT_COMMIT_ACTIVE, CAT_COMMIT_PROMISE, CAT_WORLD_POWER, CAT_WORLD_VIEW)
L3_CATEGORIES = (CAT_RAG_CHUNK,)
L4_CATEGORIES = (CAT_FADED,)

ALL_CATEGORIES = L1_CATEGORIES + L2_CATEGORIES + L3_CATEGORIES + L4_CATEGORIES

# 各级别对应的 categories (便于批量操作)
# 注: L2 含 commitment + world_rule (合并)
CATEGORIES_BY_LEVEL = {
    MemoryLevel.L1_ARC: L1_CATEGORIES,
    "L2": (CAT_COMMIT_ACTIVE, CAT_COMMIT_PROMISE, CAT_WORLD_POWER, CAT_WORLD_VIEW),
    MemoryLevel.L3_RAG: L3_CATEGORIES,
    MemoryLevel.L4_FADE: L4_CATEGORIES,
}

# 单 category → level 反查 (用于 add() 自动推断)
CATEGORY_TO_LEVEL: dict[str, str] = {}
for _lv, _cats in CATEGORIES_BY_LEVEL.items():
    for _c in _cats:
        CATEGORY_TO_LEVEL[_c] = _lv

CATEGORY_LABELS = {
    CAT_ARC_MAIN: "主线弧",
    CAT_ARC_SUB: "副线弧",
    CAT_ARC_CHAR: "人物弧",
    CAT_COMMIT_ACTIVE: "已触发承诺",
    CAT_COMMIT_PROMISE: "待履行承诺",
    CAT_WORLD_POWER: "力量规则",
    CAT_WORLD_VIEW: "世界规则",
    CAT_RAG_CHUNK: "RAG 检索",
    CAT_FADED: "已遗忘",
}

# 内容上限
MAX_CONTENT_LEN = 2000


# ────────────────────── 数据类 ──────────────────────

@dataclass
class Memory:
    """单条记忆 (一行 DB 记录)。"""
    id: str
    project_id: str
    chapter_id: Optional[str]       # None 表示与具体章无关 (如世界规则)
    level: str                       # L1/L2/L3/L4
    category: str
    content: str = ""
    token_count: int = 0
    created_at: str = ""
    # 可选关联
    ref_id: str = ""                 # 关联条目 (如承诺的 original_id, 遗忘的源)

    @property
    def label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "chapter_id": self.chapter_id,
            "level": self.level,
            "category": self.category,
            "content": self.content,
            "token_count": self.token_count,
            "created_at": self.created_at,
            "ref_id": self.ref_id,
        }

    @classmethod
    def from_row(cls, row) -> "Memory":
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            chapter_id=row["chapter_id"],
            level=row["level"],
            category=row["category"],
            content=row["content"] or "",
            token_count=row["token_count"] or 0,
            created_at=row["created_at"] or "",
            ref_id=row["ref_id"] or "",
        )


# ────────────────────── 写入 ──────────────────────

def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _validate_category(category: str) -> str:
    if category not in ALL_CATEGORIES:
        raise ValueError(f"未知 category: {category} (合法: {ALL_CATEGORIES})")
    return category


def _validate_content(content: str) -> str:
    if content is None:
        return ""
    if not isinstance(content, str):
        content = str(content)
    content = content.strip()
    if len(content) > MAX_CONTENT_LEN:
        raise ValueError(f"记忆内容过长 (上限 {MAX_CONTENT_LEN} 字符, 实际 {len(content)})")
    return content


def _estimate_tokens(text: str) -> int:
    """粗估 token 数 (中文按字数 × 1.5, 英文按词数 × 1.3)。"""
    if not text:
        return 0
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return max(1, int(cn * 1.5 + en * 0.3))


def add(
    project_id: str,
    category: str,
    content: str,
    *,
    chapter_id: Optional[str] = None,
    ref_id: str = "",
    level: Optional[str] = None,
) -> Memory:
    """
    添加一条记忆。
    - category 必须合法 (ALL_CATEGORIES)
    - chapter_id=None 表示与具体章节无关 (如世界规则)
    - level 自动根据 category 推断 (可手动指定覆盖)
    """
    if not project_id:
        raise ValueError("project_id 必填")
    category = _validate_category(category)
    content = _validate_content(content)
    if not content:
        raise ValueError("记忆内容不能为空")
    if level is None:
        level = CATEGORY_TO_LEVEL.get(category)
    if level is None:
        raise ValueError(f"无法推断 level: {category}")

    mem = Memory(
        id=_new_id(),
        project_id=project_id,
        chapter_id=chapter_id,
        level=level,
        category=category,
        content=content,
        token_count=_estimate_tokens(content),
        created_at=datetime.now().isoformat(timespec="seconds"),
        ref_id=ref_id,
    )
    conn = connection.get_conn()
    conn.execute(
        """
        INSERT INTO agent_memories
            (id, project_id, chapter_id, level, category, content, token_count, created_at, ref_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (mem.id, mem.project_id, mem.chapter_id, mem.level, mem.category,
         mem.content, mem.token_count, mem.created_at, mem.ref_id),
    )
    _logger.info("添加记忆 [%s/%s]: %s", mem.level, mem.category, content[:30])
    return mem


def add_arc(project_id: str, arc_type: str, content: str, *, chapter_id: Optional[str] = None) -> Memory:
    """便捷: 添加 L1 故事弧。arc_type ∈ {arc_main, arc_sub, arc_char}"""
    if arc_type not in L1_CATEGORIES:
        raise ValueError(f"arc_type 必须是 L1 类别: {L1_CATEGORIES}")
    return add(project_id, arc_type, content, chapter_id=chapter_id)


def add_commitment(
    project_id: str,
    content: str,
    *,
    kind: str = "promise",
    chapter_id: Optional[str] = None,
) -> Memory:
    """
    添加承诺。
    - kind='promise' (默认) - 待履行 (主角答应过/欠下)
    - kind='active' - 已触发/必履行
    """
    if kind == "active":
        cat = CAT_COMMIT_ACTIVE
    elif kind == "promise":
        cat = CAT_COMMIT_PROMISE
    else:
        raise ValueError(f"kind 必须是 'active' 或 'promise' (实际: {kind})")
    return add(project_id, cat, content, chapter_id=chapter_id)


def add_world_rule(
    project_id: str,
    content: str,
    *,
    kind: str = "view",
) -> Memory:
    """
    添加世界规则 (immutable)。
    - kind='view' (默认) - 世界观
    - kind='power' - 力量体系
    """
    if kind == "power":
        cat = CAT_WORLD_POWER
    elif kind == "view":
        cat = CAT_WORLD_VIEW
    else:
        raise ValueError(f"kind 必须是 'power' 或 'view' (实际: {kind})")
    return add(project_id, cat, content, chapter_id=None)


def add_rag_chunk(
    project_id: str,
    content: str,
    *,
    chapter_id: Optional[str] = None,
    ref_id: str = "",
) -> Memory:
    """添加 RAG 检索临时 chunk。"""
    return add(project_id, CAT_RAG_CHUNK, content, chapter_id=chapter_id, ref_id=ref_id)


def fade(project_id: str, memory_id: str) -> bool:
    """
    优雅遗忘: 把一条 L3 (RAG chunk) 移入 L4 (faded)。
    不会删除, 只标记 + 改 category。后续 get_l1_l2() 不返回。
    """
    mem = get_by_id(project_id, memory_id)
    if mem is None:
        return False
    if mem.level != MemoryLevel.L3_RAG:
        raise ValueError(f"只能遗忘 L3 记忆, 实际 level={mem.level}")
    conn = connection.get_conn()
    conn.execute(
        "UPDATE agent_memories SET level=?, category=?, ref_id=? WHERE id=?",
        (MemoryLevel.L4_FADE, CAT_FADED, mem.id, mem.id),
    )
    _logger.info("遗忘: %s", mem.id)
    return True


# ────────────────────── 读取 ──────────────────────

def get_by_id(project_id: str, memory_id: str) -> Optional[Memory]:
    conn = connection.get_conn()
    row = conn.execute(
        "SELECT * FROM agent_memories WHERE project_id=? AND id=?",
        (project_id, memory_id),
    ).fetchone()
    if row is None:
        return None
    return Memory.from_row(row)


def list_by_category(
    project_id: str,
    category: str,
    *,
    limit: int = 200,
    as_of_chapter: Optional[str] = None,
) -> list[Memory]:
    """
    按 category 列出。
    - as_of_chapter: 限定 chapter_id <= 该值 (None 表示不限定, 含 chapter_id IS NULL)
    """
    _validate_category(category)
    conn = connection.get_conn()
    if as_of_chapter is not None:
        rows = conn.execute(
            """
            SELECT * FROM agent_memories
            WHERE project_id=? AND category=?
              AND (chapter_id IS NULL OR chapter_id <= ?)
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (project_id, category, as_of_chapter, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM agent_memories
            WHERE project_id=? AND category=?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (project_id, category, limit),
        ).fetchall()
    return [Memory.from_row(r) for r in rows]


def list_by_level(
    project_id: str,
    level: str,
    *,
    as_of_chapter: Optional[str] = None,
    include_faded: bool = False,
) -> list[Memory]:
    """
    按 level 列出 (跨 category)。
    - include_faded=True 时把 L4 一并返回
    """
    cats = list(CATEGORIES_BY_LEVEL.get(level, ()))
    if include_faded and level != MemoryLevel.L4_FADE:
        cats = cats + list(L4_CATEGORIES)
    if not cats:
        return []
    placeholders = ",".join("?" for _ in cats)
    conn = connection.get_conn()
    if as_of_chapter is not None:
        rows = conn.execute(
            f"""
            SELECT * FROM agent_memories
            WHERE project_id=? AND category IN ({placeholders})
              AND (chapter_id IS NULL OR chapter_id <= ?)
            ORDER BY created_at ASC
            """,
            (project_id, *cats, as_of_chapter),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT * FROM agent_memories
            WHERE project_id=? AND category IN ({placeholders})
            ORDER BY created_at ASC
            """,
            (project_id, *cats),
        ).fetchall()
    return [Memory.from_row(r) for r in rows]


def get_l1_l2(project_id: str, *, as_of_chapter: Optional[str] = None) -> list[Memory]:
    """
    取 L1+L2 (核心常驻记忆)。
    - 写章节时, 始终要带上这批
    - 排除 L3 (RAG 临时) 和 L4 (已遗忘)
    """
    conn = connection.get_conn()
    l1_l2_cats = list(L1_CATEGORIES) + list(L2_CATEGORIES)
    placeholders = ",".join("?" for _ in l1_l2_cats)
    if as_of_chapter is not None:
        rows = conn.execute(
            f"""
            SELECT * FROM agent_memories
            WHERE project_id=? AND category IN ({placeholders})
              AND (chapter_id IS NULL OR chapter_id <= ?)
            ORDER BY level ASC, created_at ASC
            """,
            (project_id, *l1_l2_cats, as_of_chapter),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT * FROM agent_memories
            WHERE project_id=? AND category IN ({placeholders})
            ORDER BY level ASC, created_at ASC
            """,
            (project_id, *l1_l2_cats),
        ).fetchall()
    return [Memory.from_row(r) for r in rows]


def get_active_commitments(project_id: str, *, as_of_chapter: Optional[str] = None) -> list[Memory]:
    """取已触发承诺 (必履行)。"""
    return list_by_category(project_id, CAT_COMMIT_ACTIVE, as_of_chapter=as_of_chapter)


def get_open_promises(project_id: str, *, as_of_chapter: Optional[str] = None) -> list[Memory]:
    """取待履行承诺 (主角答应过/欠下)。"""
    return list_by_category(project_id, CAT_COMMIT_PROMISE, as_of_chapter=as_of_chapter)


# ────────────────────── 单元版接口 (story_order 时间线) ──────────────────────

def _get_story_order_for_unit(unit_id: str) -> int:
    """通过 unit_id 查 story_order。"""
    from app.services import story_unit_service_v2
    unit = story_unit_service_v2.get(unit_id)
    return unit.story_order


def _build_unit_time_filter(as_of_unit: Optional[str], as_of_step: int = 0) -> tuple[str, list]:
    """
    Build SQL WHERE fragment and params for unit-time filtering.

    Returns (sql_fragment, params_list).

    Filter logic:
      - No as_of_unit: no filter (all memories)
      - With as_of_unit, no step: story_order <= target (all past units + global)
      - With as_of_unit + as_of_step:
          * global memories (unit_id empty) -> always include
          * other units' memories -> story_order <= target
          * THIS unit's memories -> unit_step <= as_of_step  (段级时间锚点)
    """
    if as_of_unit is None:
        return "", []

    story_order = _get_story_order_for_unit(as_of_unit)
    params: list = []

    if as_of_step > 0:
        # Segment-level time anchor for the currently-writing unit
        sql = (
            " AND (unit_id IS NULL OR unit_id = '' "
            "   OR (unit_id != ? AND story_order <= ?) "
            "   OR (unit_id = ? AND unit_step <= ?) "
            " )"
        )
        params = [as_of_unit, story_order, as_of_unit, as_of_step]
    else:
        sql = " AND (unit_id IS NULL OR unit_id = '' OR story_order <= ?)"
        params = [story_order]

    return sql, params


def list_by_category_as_of_unit(
    project_id: str,
    category: str,
    *,
    as_of_unit: Optional[str] = None,
    as_of_step: int = 0,
    limit: int = 200,
) -> list[Memory]:
    """
    按 category 列出（单元模式版）。
    - as_of_unit: 限定 story_order <= 该单元的 story_order
      (None 表示不限定, 含 unit_id 为空/为'' 的全局记忆)
    - as_of_step: >0 时启用段级时间锚点，当前正在写的单元只返回 unit_step <= as_of_step 的记忆
      （防止回滚/重写时拿到未来步骤的"幽灵记忆"）
    """
    _validate_category(category)
    conn = connection.get_conn()

    filter_sql, filter_params = _build_unit_time_filter(as_of_unit, as_of_step)
    params = [project_id, category, *filter_params, limit]

    rows = conn.execute(
        f"""
        SELECT * FROM agent_memories
        WHERE project_id=? AND category=?
          {filter_sql}
        ORDER BY created_at ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [Memory.from_row(r) for r in rows]


def list_by_level_as_of_unit(
    project_id: str,
    level: str,
    *,
    as_of_unit: Optional[str] = None,
    as_of_step: int = 0,
    include_faded: bool = False,
) -> list[Memory]:
    """
    按 level 列出（单元模式版，跨 category）。
    - include_faded=True 时把 L4 一并返回
    - as_of_step: >0 时启用段级时间锚点
    """
    cats = list(CATEGORIES_BY_LEVEL.get(level, ()))
    if include_faded and level != MemoryLevel.L4_FADE:
        cats = cats + list(L4_CATEGORIES)
    if not cats:
        return []
    placeholders = ",".join("?" for _ in cats)
    conn = connection.get_conn()

    filter_sql, filter_params = _build_unit_time_filter(as_of_unit, as_of_step)
    params = [project_id, *cats, *filter_params]

    rows = conn.execute(
        f"""
        SELECT * FROM agent_memories
        WHERE project_id=? AND category IN ({placeholders})
          {filter_sql}
        ORDER BY created_at ASC
        """,
        params,
    ).fetchall()
    return [Memory.from_row(r) for r in rows]


def get_l1_l2_as_of_unit(
    project_id: str,
    *,
    as_of_unit: Optional[str] = None,
    as_of_step: int = 0,
) -> list[Memory]:
    """
    取 L1+L2 核心常驻记忆（单元模式版）。
    - 排除 L3 (RAG 临时) 和 L4 (已遗忘)
    - as_of_step: >0 时启用段级时间锚点
    """
    conn = connection.get_conn()
    l1_l2_cats = list(L1_CATEGORIES) + list(L2_CATEGORIES)
    placeholders = ",".join("?" for _ in l1_l2_cats)

    filter_sql, filter_params = _build_unit_time_filter(as_of_unit, as_of_step)
    params = [project_id, *l1_l2_cats, *filter_params]

    rows = conn.execute(
        f"""
        SELECT * FROM agent_memories
        WHERE project_id=? AND category IN ({placeholders})
          {filter_sql}
        ORDER BY level ASC, created_at ASC
        """,
        params,
    ).fetchall()
    return [Memory.from_row(r) for r in rows]


def get_active_commitments_as_of_unit(
    project_id: str, *, as_of_unit: Optional[str] = None
) -> list[Memory]:
    """取已触发承诺（单元模式版）。"""
    return list_by_category_as_of_unit(
        project_id, CAT_COMMIT_ACTIVE, as_of_unit=as_of_unit
    )


def get_open_promises_as_of_unit(
    project_id: str, *, as_of_unit: Optional[str] = None
) -> list[Memory]:
    """取待履行承诺（单元模式版）。"""
    return list_by_category_as_of_unit(
        project_id, CAT_COMMIT_PROMISE, as_of_unit=as_of_unit
    )


def add_unit_memory(
    project_id: str,
    unit_id: str,
    category: str,
    content: str,
    *,
    ref_id: str = "",
    level: Optional[str] = None,
) -> Memory:
    """
    添加一条锚定到单元的记忆。
    - 自动从单元获取 story_order
    """
    from app.services import story_unit_service_v2 as story_unit_service
    unit = story_unit_service.get(unit_id)
    story_order = unit.story_order

    category = _validate_category(category)
    content = _validate_content(content)
    if not content:
        raise ValueError("记忆内容不能为空")
    if level is None:
        level = CATEGORY_TO_LEVEL.get(category)
    if level is None:
        raise ValueError(f"无法推断 level: {category}")

    mem = Memory(
        id=_new_id(),
        project_id=project_id,
        chapter_id=None,
        level=level,
        category=category,
        content=content,
        token_count=_estimate_tokens(content),
        created_at=datetime.now().isoformat(timespec="seconds"),
        ref_id=ref_id,
    )
    conn = connection.get_conn()
    conn.execute(
        """
        INSERT INTO agent_memories
            (id, project_id, chapter_id, unit_id, story_order, level, category,
             content, token_count, created_at, ref_id)
        VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (mem.id, project_id, unit_id, story_order, mem.level, category,
         content, mem.token_count, mem.created_at, ref_id),
    )
    _logger.info("添加单元记忆: %s @ 单元 %s", category, unit_id)
    return mem


def list_unit_memories(unit_id: str) -> list[Memory]:
    """列出某个单元的所有专属记忆。"""
    conn = connection.get_conn()
    rows = conn.execute(
        "SELECT * FROM agent_memories WHERE unit_id=? ORDER BY created_at ASC",
        (unit_id,),
    ).fetchall()
    return [Memory.from_row(r) for r in rows]


# ────────────────────── 维护 ──────────────────────

def fulfill_promise(project_id: str, promise_id: str) -> bool:
    """
    履行一个承诺: promise → active (标志已触发, 不删)。
    实际由剧情推进时调用。
    """
    mem = get_by_id(project_id, promise_id)
    if mem is None:
        return False
    if mem.category != CAT_COMMIT_PROMISE:
        raise ValueError(f"该记忆不是 promise: {mem.category}")
    conn = connection.get_conn()
    conn.execute(
        "UPDATE agent_memories SET category=?, ref_id=? WHERE id=?",
        (CAT_COMMIT_ACTIVE, mem.ref_id or mem.id, mem.id),
    )
    return True


def delete(project_id: str, memory_id: str) -> bool:
    """删除一条记忆 (慎用, 推荐用 fade 替代)。"""
    conn = connection.get_conn()
    cur = conn.execute(
        "DELETE FROM agent_memories WHERE project_id=? AND id=?",
        (project_id, memory_id),
    )
    return (cur.rowcount or 0) > 0


def count_by_level(project_id: str) -> dict[str, int]:
    """统计各级别记忆数量。"""
    conn = connection.get_conn()
    rows = conn.execute(
        "SELECT level, COUNT(*) AS n FROM agent_memories WHERE project_id=? GROUP BY level",
        (project_id,),
    ).fetchall()
    return {r["level"]: r["n"] for r in rows}


# ────────────────────── 格式化 (prompt 拼装) ──────────────────────

def format_for_prompt(mems: list[Memory], *, max_chars: int = 1500) -> str:
    """
    把记忆列表格式化成可拼入 prompt 的字符串。
    - 按 level 分组, 同级内按 category
    - max_chars 截断 (避免超长)
    """
    if not mems:
        return "(无记忆)"
    # 分组
    grouped: dict[str, list[Memory]] = {}
    for m in mems:
        grouped.setdefault(m.level, []).append(m)
    level_order = [MemoryLevel.L1_ARC, MemoryLevel.L2_COMMITMENT, MemoryLevel.L2_WORLD_RULE]
    lines: list[str] = []
    for lv in level_order:
        if lv not in grouped:
            continue
        # 同一 level 内按 category 进一步分组
        sub: dict[str, list[Memory]] = {}
        for m in grouped[lv]:
            sub.setdefault(m.category, []).append(m)
        for cat, items in sub.items():
            label = CATEGORY_LABELS.get(cat, cat)
            lines.append(f"【{label}】")
            for m in items:
                chap = f" @ {m.chapter_id}" if m.chapter_id else ""
                lines.append(f"  - {m.content}{chap}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "…(已截断)"
    return text


# ============================================================
# v3.5.2: Guide 接口 (GPT 评审)
# ============================================================

def get_guides(unit_id: str, project_id: str = "") -> list:
    """返回 unit 内记忆相关的 Guide 列表.

    检测内容:
      1. 长期未兑现的承诺 (open_promises 数量过多)
      2. L1 重要记忆缺失 (核心设定无对应记忆)
      3. 跨 unit 记忆断层 (无 as_of_unit 时间锚点的全局记忆)

    注: 记忆本身不是 Guide, 而是 Guide 提示"故事历史中某事值得注意".
    """
    from app.core.types import Guide, Action, GUIDE_SCOPE_UNIT

    if not project_id:
        # 反查 unit 拿 project_id
        from app.services import story_unit_service_v2 as _unit_svc
        try:
            unit = _unit_svc.get(unit_id)
            project_id = unit.project_id
        except Exception:
            return []

    guides: list[Guide] = []
    evidence: list[str] = []

    # ---- 1. 未兑现承诺 ----
    try:
        open_promises = get_open_promises_as_of_unit(
            project_id, as_of_unit=unit_id, as_of_step=0
        )
        if open_promises:
            evidence = [m.id for m in open_promises[:10]]
            advice = (
                f"项目内有 {len(open_promises)} 个未兑现的承诺。"
                f"AI 写作时需注意不要让角色忽略这些承诺。"
            )
            if len(open_promises) >= 5:
                advice += "承诺过多可能导致节奏拖沓, 建议在 Story Engine 中清理过期承诺。"

            guides.append(Guide(
                source="memory",
                priority=min(0.85, 0.3 + 0.1 * len(open_promises)),
                confidence=0.85,
                scope=GUIDE_SCOPE_UNIT,
                advice=advice,
                reason=f"基于 open_promises_as_of_unit 查询, 共 {len(open_promises)} 条",
                evidence_ids=evidence,
                possible_actions=[
                    Action(label="保留", description="承诺仍重要, AI 继续推进"),
                    Action(label="Fulfill", description="当前 unit 兑现其中部分承诺"),
                    Action(label="Delete", description="手动删除过期承诺 (使用 fulfill_promise)"),
                ],
                context={
                    "open_promises_count": len(open_promises),
                    "promise_categories": list(set(m.category for m in open_promises)),
                },
            ))
    except Exception:
        pass

    # ---- 2. L1+L2 记忆缺失 ----
    try:
        l1_l2 = get_l1_l2_as_of_unit(
            project_id, as_of_unit=unit_id, as_of_step=0
        )
        if not l1_l2:
            guides.append(Guide(
                source="memory",
                priority=0.6,
                confidence=0.7,
                scope=GUIDE_SCOPE_BOOK,
                advice="L1+L2 核心记忆为空, AI 写作时缺少人物/世界观的稳定上下文。建议先在设定面板完善人物和世界观。",
                reason="get_l1_l2_as_of_unit 返回空列表",
                evidence_ids=[],
                possible_actions=[
                    Action(label="去补 L1", description="在设定面板补充人物核心信息"),
                    Action(label="继续", description="当前项目无人物, AI 自由发挥"),
                ],
                context={"l1_l2_count": 0},
            ))
    except Exception:
        pass

    return guides


# 导出
__all__ = [
    "CAT_ARC_MAIN", "CAT_ARC_SUB", "CAT_ARC_CHAR",
    "CAT_COMMIT_ACTIVE", "CAT_COMMIT_PROMISE",
    "CAT_WORLD_POWER", "CAT_WORLD_VIEW",
    "CAT_RAG_CHUNK", "CAT_FADED",
    "L1_CATEGORIES", "L2_CATEGORIES", "L3_CATEGORIES", "L4_CATEGORIES",
    "ALL_CATEGORIES", "CATEGORIES_BY_LEVEL", "CATEGORY_TO_LEVEL", "CATEGORY_LABELS",
    "Memory",
    "add", "add_arc", "add_commitment", "add_world_rule", "add_rag_chunk",
    "get_by_id", "list_by_category", "list_by_level", "get_l1_l2",
    "get_active_commitments", "get_open_promises",
    "list_by_category_as_of_unit", "list_by_level_as_of_unit",
    "get_l1_l2_as_of_unit", "get_active_commitments_as_of_unit",
    "get_open_promises_as_of_unit", "add_unit_memory", "list_unit_memories",
    "fade", "fulfill_promise", "delete", "count_by_level",
    "format_for_prompt",
    "MAX_CONTENT_LEN",
]
