"""
双层风格指纹 (Dual-Layer Fingerprint) — v3.4 G-rev2

核心理念:
  L1 作者指纹 (6 维): 描述"这个人怎么写" — 跨书迁移, 换题材不变
  L2 作品指纹 (4 维): 描述"这本小说的调性" — 随书而定, 新书重新初始化

L1 作者指纹 (1-10):
  1. 句子节奏 sentence_rhythm:     1=短促快节奏 10=流水长句
  2. 对话密度 dialogue_density:    1=叙述为主 10=对话为主
  3. 描写风格 description_style:   1=动作驱动 10=氛围描写
  4. 情绪表达 emotion_expression:  1=直说情绪 10=身体暗示
  5. 段落密度 paragraph_density:   1=密集长段落 10=舒朗短段落
  6. 语言层级 language_level:      1=口语/网络语 10=文学/书面语

L2 作品指纹 (1-10):
  1. 题材基调 genre_tone:          1=轻快明亮 10=厚重暗沉
  2. 氛围取向 atmosphere_tendency: 1=温情日常 10=紧张压迫
  3. 叙事复杂度 narrative_complexity: 1=单线简单 10=多线交织
  4. 节奏偏好 pacing_preference:  1=快节奏 10=慢热铺垫

用法:
  from app.services.style_fingerprint import (
      get_author_fp, upsert_author_fp,
      get_book_fp, upsert_book_fp,
      to_author_prompt_block, to_book_prompt_block,
      AuthorFingerprint, BookFingerprint,
  )
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.db import _impl as _db_conn
from app.services.exceptions import ValidationError


# —————————————————————————————————————————— 常量 ——————————————————————————————————————————

SOURCE_MANUAL = "manual"
SOURCE_AI_LEARNED = "ai_learned"
SOURCE_HYBRID = "hybrid"
ALL_SOURCES = [SOURCE_MANUAL, SOURCE_AI_LEARNED, SOURCE_HYBRID]

# L1 作者指纹 6 维
AUTHOR_DIMS: list[str] = [
    "sentence_rhythm",
    "dialogue_density",
    "description_style",
    "emotion_expression",
    "paragraph_density",
    "language_level",
]

AUTHOR_DIM_LABELS: dict[str, str] = {
    "sentence_rhythm": "句子节奏",
    "dialogue_density": "对话密度",
    "description_style": "描写风格",
    "emotion_expression": "情绪表达",
    "paragraph_density": "段落密度",
    "language_level": "语言层级",
}

AUTHOR_DIM_HINTS: dict[str, tuple[str, str]] = {
    "sentence_rhythm": ("1=短促快节奏", "10=流水长句"),
    "dialogue_density": ("1=叙述为主", "10=对话为主"),
    "description_style": ("1=动作驱动", "10=氛围描写"),
    "emotion_expression": ("1=直说情绪", "10=身体暗示"),
    "paragraph_density": ("1=密集长段落", "10=舒朗短段落"),
    "language_level": ("1=口语/网络语", "10=文学/书面语"),
}

# L2 作品指纹 4 维
BOOK_DIMS: list[str] = [
    "genre_tone",
    "atmosphere_tendency",
    "narrative_complexity",
    "pacing_preference",
]

BOOK_DIM_LABELS: dict[str, str] = {
    "genre_tone": "题材基调",
    "atmosphere_tendency": "氛围取向",
    "narrative_complexity": "叙事复杂度",
    "pacing_preference": "节奏偏好",
}

BOOK_DIM_HINTS: dict[str, tuple[str, str]] = {
    "genre_tone": ("1=轻快明亮", "10=厚重暗沉"),
    "atmosphere_tendency": ("1=温情日常", "10=紧张压迫"),
    "narrative_complexity": ("1=单线简单", "10=多线交织"),
    "pacing_preference": ("1=快节奏", "10=慢热铺垫"),
}

# —— 向后兼容 ————————————————————————————————
# 旧 5 维 (已废弃, 仅保留常量供平滑过渡)
DIMENSIONS: list[str] = [
    "cultivation_level", "intrigue_level", "tone",
    "sentence_length", "vocabulary",
]
DIMENSION_LABELS = {
    "cultivation_level": "修真度",
    "intrigue_level": "阴谋度",
    "tone": "色调",
    "sentence_length": "句长",
    "vocabulary": "词汇",
}
DIMENSION_HINTS = {
    "cultivation_level": ("1=纯日常", "10=高武/高魔"),
    "intrigue_level": ("1=直白", "10=权谋心机"),
    "tone": ("1=明亮", "10=暗黑"),
    "sentence_length": ("1=短句快节奏", "10=长句慢节奏"),
    "vocabulary": ("1=白话", "10=古典/华丽"),
}


# —————————————————————————————————————————— 数据类 ——————————————————————————————————————————

@dataclass
class AuthorFingerprint:
    """L1 作者指纹: 跨书迁移, 描述笔法."""
    id: str = ""
    user_id: str = "default"
    sentence_rhythm: int = 5
    dialogue_density: int = 5
    description_style: int = 5
    emotion_expression: int = 5
    paragraph_density: int = 5
    language_level: int = 5
    source: str = SOURCE_MANUAL
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "sentence_rhythm": self.sentence_rhythm,
            "dialogue_density": self.dialogue_density,
            "description_style": self.description_style,
            "emotion_expression": self.emotion_expression,
            "paragraph_density": self.paragraph_density,
            "language_level": self.language_level,
        }

    def diff_from(self, other: "AuthorFingerprint") -> dict:
        """返回与另一个指纹的逐维差值 (可用于学习偏好)."""
        diffs = {}
        for d in AUTHOR_DIMS:
            diffs[d] = getattr(self, d) - getattr(other, d)
        return diffs


@dataclass
class BookFingerprint:
    """L2 作品指纹: 随书而定, 描述调性."""
    id: str = ""
    project_id: str = ""
    genre_tone: int = 5
    atmosphere_tendency: int = 5
    narrative_complexity: int = 5
    pacing_preference: int = 5
    source: str = SOURCE_MANUAL
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "genre_tone": self.genre_tone,
            "atmosphere_tendency": self.atmosphere_tendency,
            "narrative_complexity": self.narrative_complexity,
            "pacing_preference": self.pacing_preference,
        }


# ———————————————————————————————————— 内部工具 ————————————————————————————————————

def _conn():
    return _db_conn.get_conn()


def _validate_dim(v, name: str) -> int:
    if not isinstance(v, int) or not (1 <= v <= 10):
        raise ValidationError(f"{name} 必须是 1-10 的整数, 收到: {v}")
    return v


def _validate_source(source: str) -> str:
    if source not in ALL_SOURCES:
        raise ValidationError(f"source 必须是 {ALL_SOURCES}, 收到: {source}")
    return source


def _row_to_author_fp(row: dict) -> AuthorFingerprint:
    return AuthorFingerprint(
        id=row["id"],
        user_id=row.get("user_id", "default"),
        sentence_rhythm=row.get("sentence_rhythm", 5),
        dialogue_density=row.get("dialogue_density", 5),
        description_style=row.get("description_style", 5),
        emotion_expression=row.get("emotion_expression", 5),
        paragraph_density=row.get("paragraph_density", 5),
        language_level=row.get("language_level", 5),
        source=row.get("source", SOURCE_MANUAL),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
    )


def _row_to_book_fp(row: dict) -> BookFingerprint:
    return BookFingerprint(
        id=row["id"],
        project_id=row.get("project_id", ""),
        genre_tone=row.get("genre_tone", 5),
        atmosphere_tendency=row.get("atmosphere_tendency", 5),
        narrative_complexity=row.get("narrative_complexity", 5),
        pacing_preference=row.get("pacing_preference", 5),
        source=row.get("source", SOURCE_MANUAL),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at", ""),
    )


def _default_author_fp(user_id: str = "default") -> AuthorFingerprint:
    return AuthorFingerprint(user_id=user_id)


def _default_book_fp(project_id: str) -> BookFingerprint:
    return BookFingerprint(project_id=project_id)


# ——————————————————————————————— L1 作者指纹 CRUD ———————————————————————————————

def get_author_fp(user_id: str = "default") -> AuthorFingerprint:
    """取作者指纹. 无则返回默认 (全 5, source=manual)."""
    r = _conn().execute(
        "SELECT * FROM author_fingerprints WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not r:
        return _default_author_fp(user_id)
    return _row_to_author_fp(dict(r))


def upsert_author_fp(
    user_id: str = "default",
    *,
    source: str = SOURCE_MANUAL,
    **dims,
) -> AuthorFingerprint:
    """新建或更新作者指纹.

    dims 关键字: sentence_rhythm, dialogue_density, description_style,
                  emotion_expression, paragraph_density, language_level
    """
    source = _validate_source(source)
    for d in AUTHOR_DIMS:
        if d in dims:
            dims[d] = _validate_dim(int(dims[d]), AUTHOR_DIM_LABELS[d])

    cur = _conn()
    existing = cur.execute(
        "SELECT id FROM author_fingerprints WHERE user_id = ?", (user_id,)
    ).fetchone()

    if existing:
        sets, vals = [], []
        for d in AUTHOR_DIMS + ["source"]:
            if d in dims:
                sets.append(f"{d} = ?")
                vals.append(dims[d])
        if not sets:
            return get_author_fp(user_id)
        sets.append("updated_at = datetime('now')")
        vals.append(existing["id"])
        cur.execute(
            f"UPDATE author_fingerprints SET {', '.join(sets)} WHERE id = ?", vals
        )
    else:
        fid = f"af_{uuid.uuid4().hex[:10]}"
        cols = ["id", "user_id"] + AUTHOR_DIMS + ["source"]
        vals = [fid, user_id]
        for d in AUTHOR_DIMS:
            vals.append(dims.get(d, 5))
        vals.append(source)
        placeholders = ",".join(["?"] * len(vals))
        cur.execute(
            f"INSERT INTO author_fingerprints ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )
    cur.commit()
    return get_author_fp(user_id)


def delete_author_fp(user_id: str = "default") -> bool:
    """删除作者指纹 (重置为默认)."""
    cur = _conn()
    cur.execute("DELETE FROM author_fingerprints WHERE user_id = ?", (user_id,))
    cur.commit()
    return cur.total_changes > 0


def to_author_prompt_block(fp: AuthorFingerprint) -> str:
    """转为注入 prompt 的作者指纹文本块.

    例子:
      [作者笔法 6 维]
        句子节奏 5/10 (短促↔流水)  对话密度 6/10 (叙述↔对话)
        描写风格 4/10 (动作↔氛围)  情绪表达 7/10 (直说↔暗示)
        段落密度 8/10 (密集↔舒朗)  语言层级 5/10 (口语↔文学)
    """
    lines = ["[作者笔法 6 维]"]
    for d in AUTHOR_DIMS:
        v = getattr(fp, d)
        hi = AUTHOR_DIM_HINTS[d]
        lines.append(f"  {AUTHOR_DIM_LABELS[d]} {v}/10 ({hi[0][3:]} ↔ {hi[1][3:]})")
    return "\n".join(lines)


# ——————————————————————————————— L2 作品指纹 CRUD ———————————————————————————————

def get_book_fp(project_id: str) -> BookFingerprint:
    """取项目作品指纹. 无则返回默认 (全 5, source=manual)."""
    r = _conn().execute(
        "SELECT * FROM book_fingerprints WHERE project_id = ?", (project_id,)
    ).fetchone()
    if not r:
        return _default_book_fp(project_id)
    return _row_to_book_fp(dict(r))


def upsert_book_fp(
    project_id: str,
    *,
    source: str = SOURCE_MANUAL,
    **dims,
) -> BookFingerprint:
    """新建或更新作品指纹.

    dims 关键字: genre_tone, atmosphere_tendency,
                  narrative_complexity, pacing_preference
    """
    source = _validate_source(source)
    for d in BOOK_DIMS:
        if d in dims:
            dims[d] = _validate_dim(int(dims[d]), BOOK_DIM_LABELS[d])

    cur = _conn()
    existing = cur.execute(
        "SELECT id FROM book_fingerprints WHERE project_id = ?", (project_id,)
    ).fetchone()

    if existing:
        sets, vals = [], []
        for d in BOOK_DIMS + ["source"]:
            if d in dims:
                sets.append(f"{d} = ?")
                vals.append(dims[d])
        if not sets:
            return get_book_fp(project_id)
        sets.append("updated_at = datetime('now')")
        vals.append(existing["id"])
        cur.execute(
            f"UPDATE book_fingerprints SET {', '.join(sets)} WHERE id = ?", vals
        )
    else:
        fid = f"bf_{uuid.uuid4().hex[:10]}"
        cols = ["id", "project_id"] + BOOK_DIMS + ["source"]
        vals = [fid, project_id]
        for d in BOOK_DIMS:
            vals.append(dims.get(d, 5))
        vals.append(source)
        placeholders = ",".join(["?"] * len(vals))
        cur.execute(
            f"INSERT INTO book_fingerprints ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )
    cur.commit()
    return get_book_fp(project_id)


def delete_book_fp(project_id: str) -> bool:
    """删除项目作品指纹 (重置为默认)."""
    cur = _conn()
    cur.execute("DELETE FROM book_fingerprints WHERE project_id = ?", (project_id,))
    cur.commit()
    return cur.total_changes > 0


def to_book_prompt_block(fp: BookFingerprint) -> str:
    """转为注入 prompt 的作品指纹文本块.

    例子:
      [作品调性 4 维]
        题材基调 5/10 (轻快↔厚重)  氛围取向 5/10 (温情↔紧张)
        叙事复杂度 5/10 (简单↔复杂)  节奏偏好 5/10 (快节奏↔慢热)
    """
    lines = ["[作品调性 4 维]"]
    for d in BOOK_DIMS:
        v = getattr(fp, d)
        hi = BOOK_DIM_HINTS[d]
        lines.append(f"  {BOOK_DIM_LABELS[d]} {v}/10 ({hi[0][3:]} ↔ {hi[1][3:]})")
    return "\n".join(lines)


# —————————————————————————— 向后兼容适配器 (平滑过渡) ——————————————————————————

@dataclass
class StyleFingerprint:
    """[DEPRECATED] 旧版风格指纹兼容适配器.

    内部自动映射到新 L1+L2 体系.
    仅保留以支持旧调用方, 新代码应直接使用 AuthorFingerprint / BookFingerprint.
    """
    id: str = ""
    project_id: str = ""
    cultivation_level: int = 5
    intrigue_level: int = 5
    tone: int = 5
    sentence_length: int = 5
    vocabulary: int = 5
    source: str = SOURCE_MANUAL
    created_at: str = ""


def get(project_id: str) -> StyleFingerprint:
    """[DEPRECATED] 返回旧版指纹适配器. 从 L1 作者指纹映射.

    映射规则:
      cultivation_level  → (废弃, 固定 5) — 这不是作者笔法
      intrigue_level     → (废弃, 固定 5) — 这不是作者笔法
      tone               → (废弃, 固定 5) — 用 L2 genre_tone 替代
      sentence_length    → sentence_rhythm (句子节奏)
      vocabulary         → language_level (语言层级)
    """
    af = get_author_fp()
    return StyleFingerprint(
        id=af.id,
        project_id=project_id,
        cultivation_level=5,
        intrigue_level=5,
        tone=5,
        sentence_length=af.sentence_rhythm,
        vocabulary=af.language_level,
        source=af.source,
        created_at=af.created_at,
    )


def upsert(project_id: str, *, source: str = SOURCE_MANUAL, **dims) -> StyleFingerprint:
    """[DEPRECATED] 更新作者指纹 (映射旧维度到新维度)."""
    af_dims = {}
    # 映射旧维度 → 新维度
    if "sentence_length" in dims:
        af_dims["sentence_rhythm"] = dims.pop("sentence_length")
    if "vocabulary" in dims:
        af_dims["language_level"] = dims.pop("vocabulary")
    # 废弃维度忽略
    for _k in ["cultivation_level", "intrigue_level", "tone"]:
        dims.pop(_k, None)
    # 合并
    af_dims.update(dims)
    if af_dims:
        upsert_author_fp(source=source, **af_dims)
    return get(project_id)


def delete(project_id: str) -> bool:
    """[DEPRECATED] 删除作品指纹."""
    return delete_book_fp(project_id)


def to_prompt_block(fp: StyleFingerprint) -> str:
    """[DEPRECATED] 旧版 prompt 文本块 → 改为去调新的双层."""
    af = get_author_fp()
    return to_author_prompt_block(af)


# ============================================================
# v3.5.2: Guide 接口 (GPT 评审)
# ============================================================

def get_guides(unit_id: str, project_id: str = "") -> list:
    """返回风格指纹相关的 Guide 列表.

    检测内容:
      1. 风格指纹缺失 (book_fp 未设置, AI 无风格引导)
      2. 风格维度极端 (修真度=10, 风格过于单一)
      3. Author/Book 风格冲突 (修真度差距 > 5)

    注: v3.5.2 暂不实现风格漂移检测 (需 AI 调用比较多 unit 文本),
    先做 fp 配置级的 Guide.
    """
    from app.core.types import Guide, Action, GUIDE_SCOPE_BOOK

    if not project_id:
        from app.services import story_unit_service_v2 as _unit_svc
        try:
            unit = _unit_svc.get(unit_id)
            project_id = unit.project_id
        except Exception:
            return []

    guides: list[Guide] = []

    try:
        af = get_author_fp()
        bf = get_book_fp(project_id)

        # ---- 检查 Book FP 是否为默认 (未设置) ----
        is_default_book_fp = (
            bf.genre_tone == 5 and bf.atmosphere_tendency == 5
            and bf.narrative_complexity == 5 and bf.pacing_preference == 5
        )

        if is_default_book_fp:
            guides.append(Guide(
                source="style",
                priority=0.5,
                confidence=0.85,
                scope=GUIDE_SCOPE_BOOK,
                advice="本作品风格指纹为默认值 (5/5/5/5), AI 写作时无风格引导。建议在设定面板为 Book FP 调整至少 2 个维度。",
                reason="book_fp 为默认, 维度全为 5",
                evidence_ids=[],
                possible_actions=[
                    Action(label="设风格", description="在设定面板为 book_fp 调整维度"),
                    Action(label="继续", description="保持默认, AI 自由发挥"),
                ],
                context={"is_default": True},
            ))

        # ---- 检查 Author/Book 风格冲突 ----
        if af and bf:
            # Author FP 用 sentence_rhythm + language_level 体现
            # Book FP 用 genre_tone + narrative_complexity 体现
            # 简化冲突检测: 检查 book 的 narrative_complexity 与 author 的 language_level 是否差距过大
            author_lang = af.language_level  # 0-10
            book_complex = bf.narrative_complexity  # 0-10
            if abs(author_lang - book_complex) >= 5:
                guides.append(Guide(
                    source="style",
                    priority=0.45,
                    confidence=0.7,
                    scope=GUIDE_SCOPE_BOOK,
                    advice=(
                        f"作者风格 (language_level={author_lang}) 与作品风格 "
                        f"(narrative_complexity={book_complex}) 差距过大 ({abs(author_lang - book_complex)})。"
                        f"AI 写作时可能风格不一致, 建议调整其中之一。"
                    ),
                    reason=f"|{author_lang} - {book_complex}| = {abs(author_lang - book_complex)} >= 5",
                    evidence_ids=[],
                    possible_actions=[
                        Action(label="调作者", description="调整 author_fp.language_level"),
                        Action(label="调作品", description="调整 book_fp.narrative_complexity"),
                        Action(label="忽略", description="如有意的对比设计 (如讽刺), 保留"),
                    ],
                    context={
                        "author_language_level": author_lang,
                        "book_narrative_complexity": book_complex,
                    },
                ))

        return guides
    except Exception:
        return []
