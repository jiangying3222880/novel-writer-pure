"""
单元池服务 (M3: 故事单元素材库)

设计目标:
- unit_pool 是「独立于 project」的素材库, 存放大量 <= 1000 字的故事单元。
- 用户只规划灵感与主线, 用池里的单元拼装小说:
  clone_to_project() 把池单元克隆进 story_units, 进入 manuscript_assembly 成稿流程。
- 与 story_units 解耦: 池是素材, 克隆后才成为可成稿单元。

字数约束:
- UNIT_POOL_MAX_CHARS = 1000 (上限, 可配)。create / bulk_import 强制截断并告警。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from app.db import _impl as _db_conn
from app.services.exceptions import NotFoundError, ValidationError

_logger = logging.getLogger("NovelWriter.services.unit_pool")

UNIT_POOL_MAX_CHARS = 1000  # 单元池单条内容上限


# ────────────────────── 工具 ──────────────────────

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.") + \
        f"{datetime.now().microsecond // 1000:03d}"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _truncate(content: str) -> tuple[str, bool]:
    """超长截断到 UNIT_POOL_MAX_CHARS, 返回 (截断后内容, 是否截断过)."""
    if content is None:
        return "", False
    if len(content) <= UNIT_POOL_MAX_CHARS:
        return content, False
    return content[:UNIT_POOL_MAX_CHARS], True


def _tags_to_json(tags) -> str:
    if isinstance(tags, str):
        # 已是 JSON 或逗号串
        s = tags.strip()
        if s.startswith("["):
            return s
        if not s:
            return "[]"
        return json.dumps([t.strip() for t in s.split(",") if t.strip()], ensure_ascii=False)
    if isinstance(tags, (list, tuple)):
        return json.dumps(list(tags), ensure_ascii=False)
    return "[]"


def _tags_from_json(text: str) -> list:
    if not text:
        return []
    try:
        v = json.loads(text)
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError):
        # 兼容逗号串
        return [t.strip() for t in str(text).split(",") if t.strip()]


def _row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"] or "",
        "content": row["content"] or "",
        "genre": row["genre"] or "通用",
        "scene_type": row["scene_type"] or "",
        "emotion": row["emotion"] or "",
        "tags": _tags_from_json(row["tags"] or "[]"),
        "word_count": row["word_count"] or 0,
        "source": row["source"] or "manual",
        "created_at": row["created_at"] or "",
    }


# ────────────────────── CRUD ──────────────────────

def create(
    title: str,
    content: str,
    *,
    genre: str = "通用",
    scene_type: str = "",
    emotion: str = "",
    tags=None,
    source: str = "manual",
) -> dict:
    """新建一条池单元. 内容超 1000 字自动截断并告警."""
    if not title or not title.strip():
        raise ValidationError("title required")
    if content is None or content.strip() == "":
        raise ValidationError("content required")

    content, was_truncated = _truncate(content)
    if was_truncated:
        _logger.warning(
            "单元池单元「%s」内容超 %d 字, 已截断至 %d 字",
            title, UNIT_POOL_MAX_CHARS, UNIT_POOL_MAX_CHARS,
        )

    pool_id = _new_id()
    now = _now()
    word_count = len(content)

    with _db_conn.transaction() as tx:
        tx.execute(
            """
            INSERT INTO unit_pool
                (id, title, content, genre, scene_type, emotion,
                 tags, word_count, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pool_id, title.strip(), content, genre, scene_type, emotion,
             _tags_to_json(tags), word_count, source, now),
        )

    _logger.info("单元池新增: %s (%s) genre=%s", title, pool_id, genre)
    return get(pool_id)


def get(pool_id: str) -> dict:
    db = _db_conn.get_conn()
    row = db.execute("SELECT * FROM unit_pool WHERE id = ?", (pool_id,)).fetchone()
    if not row:
        raise NotFoundError("UnitPool", pool_id)
    return _row_to_dict(row)


def list_all(*, genre: str = "", limit: int = 200, offset: int = 0) -> list[dict]:
    """列出池单元. genre 为空列出全部."""
    db = _db_conn.get_conn()
    if genre:
        rows = db.execute(
            "SELECT * FROM unit_pool WHERE genre = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (genre, limit, offset),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM unit_pool ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count(*, genre: str = "") -> int:
    db = _db_conn.get_conn()
    if genre:
        row = db.execute("SELECT COUNT(*) AS c FROM unit_pool WHERE genre = ?", (genre,)).fetchone()
    else:
        row = db.execute("SELECT COUNT(*) AS c FROM unit_pool", ()).fetchone()
    return row["c"] if row else 0


def update(pool_id: str, **fields) -> dict:
    """更新池单元字段. content 也会走截断."""
    allowed = {"title", "content", "genre", "scene_type", "emotion", "tags", "source"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get(pool_id)

    # content 截断
    if "content" in updates:
        content, was_truncated = _truncate(updates["content"])
        updates["content"] = content
        updates["word_count"] = len(content)
        if was_truncated:
            _logger.warning("单元池单元 %s content 已截断至 %d 字", pool_id, UNIT_POOL_MAX_CHARS)

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [pool_id]

    with _db_conn.transaction() as tx:
        cur = tx.execute(f"UPDATE unit_pool SET {set_clause} WHERE id = ?", values)
        if cur.rowcount == 0:
            raise NotFoundError("UnitPool", pool_id)
    return get(pool_id)


def delete(pool_id: str) -> bool:
    with _db_conn.transaction() as tx:
        cur = tx.execute("DELETE FROM unit_pool WHERE id = ?", (pool_id,))
        if cur.rowcount == 0:
            raise NotFoundError("UnitPool", pool_id)
    _logger.info("单元池删除: %s", pool_id)
    return True


# ────────────────────── 检索 ──────────────────────

def search_by_tags(
    *,
    genre: str = "",
    scene_type: str = "",
    emotion: str = "",
    query: str = "",
    tags: Optional[list] = None,
    top_k: int = 20,
) -> list[dict]:
    """
    按标签/字段检索池单元.
    - genre / scene_type / emotion: 精确匹配 (为空不限)
    - query: 标题+内容模糊 (LIKE, 为空不限)
    - tags: 任意交集 (池单元 tags 含其一即命中)
    返回命中 dict 列表 (按 created_at 倒序), 上限 top_k.
    """
    db = _db_conn.get_conn()
    clauses = []
    params: list = []

    if genre:
        clauses.append("genre = ?")
        params.append(genre)
    if scene_type:
        clauses.append("scene_type = ?")
        params.append(scene_type)
    if emotion:
        clauses.append("emotion = ?")
        params.append(emotion)
    if query:
        clauses.append("(title LIKE ? OR content LIKE ?)")
        like = f"%{query}%"
        params.extend([like, like])

    sql = "SELECT * FROM unit_pool"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC"

    rows = db.execute(sql, params).fetchall()
    results = [_row_to_dict(r) for r in rows]

    # tags 交集过滤 (Python 端, 避免 JSON 函数兼容问题)
    if tags:
        tag_set = set(t for t in (tags or []) if t)
        if tag_set:
            results = [
                r for r in results
                if tag_set.intersection(set(r["tags"]))
            ]

    return results[:top_k]


# ────────────────────── 批量导入 ──────────────────────

def bulk_import(
    texts: list[str],
    *,
    genre: str = "通用",
    source: str = "import",
    default_title_prefix: str = "单元",
    titles: Optional[list] = None,
) -> list[dict]:
    """
    批量导入故事单元. 每条强制 < 1000 字 (超长截断).
    texts: 单元正文列表, 标题自动从首行/前 N 字生成; 若提供 titles 则优先用。
    返回新建 dict 列表.
    """
    created: list[dict] = []
    for idx, text in enumerate(texts, start=1):
        if not text or not text.strip():
            continue
        text = text.strip()
        # 标题: 优先 titles[idx-1], 否则取首行 (限 20 字), 否则前缀+序号
        if titles and idx - 1 < len(titles) and titles[idx - 1]:
            title = titles[idx - 1][:20]
        else:
            first_line = text.split("\n", 1)[0].strip()
            if len(first_line) > 20:
                first_line = first_line[:20]
            title = first_line if first_line else f"{default_title_prefix}{idx}"
        # 去首行作正文 (若首行即标题)
        body = text
        if title and text.startswith(title) and len(text) > len(title):
            body = text[len(title):].strip()
        created.append(create(
            title, body, genre=genre, source=source,
            tags=[f"batch-{source}"],
        ))
    _logger.info("单元池批量导入: %d 条 (genre=%s)", len(created), genre)
    return created


# ────────────────────── 克隆进项目 ──────────────────────

# scene_type 启发式 → StoryUnitV2.unit_type
_SCENE_TO_UNIT_TYPE = {
    "战斗": "battle", "打斗": "battle", "冲突": "battle",
    "感情": "romance", "暧昧": "romance", "恋爱": "romance", "情": "romance",
    "揭示": "reveal", "真相": "reveal", "伏笔揭开": "reveal",
    "过渡": "transition", "转场": "transition", "过场": "transition",
    "高潮": "climax", "爆发": "climax",
    "铺垫": "setup", "开端": "setup", "引入": "setup",
    "收束": "payoff", "收尾": "payoff", "结局": "payoff",
}


def _map_unit_type(scene_type: str, emotion: str) -> str:
    """把池单元的 scene_type/emotion 映射到 StoryUnitV2 合法 unit_type."""
    if not scene_type and not emotion:
        return "other"
    blob = f"{scene_type} {emotion}"
    for key, ut in _SCENE_TO_UNIT_TYPE.items():
        if key in blob:
            return ut
    return "other"


def clone_to_project(pool_id: str, project_id: str, *, book_id: str = "") -> str:
    """
    把池单元克隆进项目, 成为可成稿的 StoryUnitV2.
    返回新建 unit_id.
    流程:
      1. 取池单元
      2. 映射 unit_type
      3. usvc.create → 草稿态 StoryUnitV2
      4. usvc.save_draft(content) → 写入 draft 字段 + 重建段落 (manuscript_assembly 依赖 draft)
      5. 补充 emotion_basis (来自池 emotion)
    """
    from app.services import story_unit_service_v2 as usvc

    if not project_id:
        raise ValidationError("project_id required")
    pool = get(pool_id)
    unit_type = _map_unit_type(pool["scene_type"], pool["emotion"])

    synopsis = f"【{pool['genre']}·{pool['emotion'] or '无情绪'}】{pool['title']}"

    unit = usvc.create(
        project_id, pool["title"], book_id=book_id,
        unit_type=unit_type, synopsis=synopsis,
    )
    unit_id = unit.id

    # 写入正文 (draft + 段落)
    usvc.save_draft(unit_id, pool["content"])

    # 情绪基底
    if pool["emotion"]:
        try:
            usvc.update(unit_id, emotion_basis=pool["emotion"])
        except Exception as e:  # 非致命
            _logger.warning("clone 补充 emotion_basis 失败: %s", e)

    _logger.info("单元池克隆进项目: pool=%s → unit=%s @ %s", pool_id, unit_id, project_id)
    return unit_id
