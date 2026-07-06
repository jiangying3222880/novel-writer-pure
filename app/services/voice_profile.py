"""
G9 声音档案 (Voice Profile)
业务场景: 让 AI 写对白时知道"这人说话是啥样", 避免千人一面
  - 性格 personality:   1=内敛, 10=张扬
  - 句长 sentence_length: 1=惜字如金, 10=滔滔不绝
  - 语气词 tone_words:  "啊/呀/呢/吧" / "嗯/哼/哈" 等 (用 / 分隔)
  - 口头禅 catchphrases: "岂有此理" / "有意思" 等 (用 / 分隔)
  - 隐喻偏好 metaphor_pref: 1=不用, 10=善用类比/典故

每项目每角色 1 张表 (UPSERT)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.db import _impl as _db_conn
from app.services.exceptions import NotFoundError, ValidationError


SOURCE_MANUAL = "manual"
SOURCE_AI_INFERRED = "ai_inferred"
SOURCE_HYBRID = "hybrid"
ALL_SOURCES = [SOURCE_MANUAL, SOURCE_AI_INFERRED, SOURCE_HYBRID]

DIMENSIONS: list[str] = [
    "personality", "sentence_length", "tone_words", "catchphrases", "metaphor_pref",
]

DIMENSION_LABELS = {
    "personality": "性格",
    "sentence_length": "句长",
    "tone_words": "语气词",
    "catchphrases": "口头禅",
    "metaphor_pref": "隐喻偏好",
}


@dataclass
class VoiceProfile:
    id: str
    project_id: str
    character_name: str
    personality: int
    sentence_length: int
    tone_words: str       # / 分隔
    catchphrases: str     # / 分隔
    metaphor_pref: int
    source: str
    created_at: str = ""


def _conn():
    return _db_conn.get_conn()


def _validate_dim(v, name: str) -> int:
    if not isinstance(v, int) or not (1 <= v <= 10):
        raise ValidationError(f"{name} 必须是 1-10, 收到: {v}")
    return v


def get(project_id: str, character_name: str) -> VoiceProfile:
    """取项目 + 角色的声音档案. 无则返回默认 (5/5/空/空/5)."""
    if not character_name or not character_name.strip():
        raise ValidationError("character_name 不能为空")
    r = _conn().execute(
        "SELECT * FROM voice_profiles WHERE project_id = ? AND character_name = ?",
        (project_id, character_name),
    ).fetchone()
    if not r:
        return VoiceProfile(
            id="", project_id=project_id, character_name=character_name,
            personality=5, sentence_length=5,
            tone_words="", catchphrases="", metaphor_pref=5,
            source=SOURCE_MANUAL,
        )
    return VoiceProfile(
        id=r["id"], project_id=r["project_id"], character_name=r["character_name"],
        personality=r["personality"], sentence_length=r["sentence_length"],
        tone_words=r["tone_words"] or "", catchphrases=r["catchphrases"] or "",
        metaphor_pref=r["metaphor_pref"], source=r["source"], created_at=r["created_at"] or "",
    )


def upsert(project_id: str, character_name: str, *, source: str = SOURCE_MANUAL, **dims) -> VoiceProfile:
    """新建或更新某角色的声音档案."""
    if source not in ALL_SOURCES:
        raise ValidationError(f"source 必须是 {ALL_SOURCES}, 收到: {source}")
    if not character_name or not character_name.strip():
        raise ValidationError("character_name 不能为空")

    # 校验 5 维 (tone_words / catchphrases 是字符串, 不校验范围)
    for d in ("personality", "sentence_length", "metaphor_pref"):
        if d in dims:
            dims[d] = _validate_dim(int(dims[d]), DIMENSION_LABELS[d])

    cur = _conn()
    existing = cur.execute(
        "SELECT id FROM voice_profiles WHERE project_id = ? AND character_name = ?",
        (project_id, character_name),
    ).fetchone()

    if existing:
        sets, vals = [], []
        for d in DIMENSIONS:
            if d in dims:
                sets.append(f"{d} = ?")
                vals.append(dims[d])
        # source 永远更新 (从位置参数 source 拿, 不从 dims)
        sets.append("source = ?")
        vals.append(source)
        vals.append(existing["id"])
        cur.execute(
            f"UPDATE voice_profiles SET {', '.join(sets)} WHERE id = ?", vals
        )
    else:
        vid = f"vp_{uuid.uuid4().hex[:10]}"
        cols = ["id", "project_id", "character_name"] + DIMENSIONS + ["source"]
        vals = [vid, project_id, character_name]
        for d in DIMENSIONS:
            if d in ("tone_words", "catchphrases"):
                vals.append(dims.get(d, ""))
            else:
                vals.append(dims.get(d, 5))
        vals.append(source)
        placeholders = ",".join(["?"] * len(vals))
        cur.execute(
            f"INSERT INTO voice_profiles ({','.join(cols)}) VALUES ({placeholders})", vals
        )
    cur.commit()
    return get(project_id, character_name)


def delete(project_id: str, character_name: str) -> bool:
    """删某角色的声音档案."""
    cur = _conn()
    cur.execute(
        "DELETE FROM voice_profiles WHERE project_id = ? AND character_name = ?",
        (project_id, character_name),
    )
    cur.commit()
    return cur.total_changes > 0


def list_for_project(project_id: str) -> list[VoiceProfile]:
    """列项目所有声音档案."""
    rows = _conn().execute(
        "SELECT * FROM voice_profiles WHERE project_id = ? ORDER BY character_name",
        (project_id,),
    ).fetchall()
    out = []
    for r in rows:
        out.append(VoiceProfile(
            id=r["id"], project_id=r["project_id"], character_name=r["character_name"],
            personality=r["personality"], sentence_length=r["sentence_length"],
            tone_words=r["tone_words"] or "", catchphrases=r["catchphrases"] or "",
            metaphor_pref=r["metaphor_pref"], source=r["source"], created_at=r["created_at"] or "",
        ))
    return out


def to_prompt_block(profile: VoiceProfile) -> str:
    """转成注入 prompt 的文本块 (G1 引擎对白生成用)."""
    lines = [f"[声音档案: {profile.character_name}]"]
    lines.append(f"  性格 {profile.personality}/10  句长 {profile.sentence_length}/10  隐喻 {profile.metaphor_pref}/10")
    if profile.tone_words.strip():
        lines.append(f"  语气词: {profile.tone_words}")
    if profile.catchphrases.strip():
        lines.append(f"  口头禅: {profile.catchphrases}")
    return "\n".join(lines)


# ============================================================
# v3.5.2: Guide 接口 (GPT 评审)
# ============================================================

def get_guides(unit_id: str, project_id: str = "") -> list:
    """返回声音档案相关的 Guide 列表.

    检测内容:
      1. 角色声音档案缺失 (核心角色无 voice profile)
      2. 声音维度极端 (例如 personality=1, 可能太刻板)
      3. 多角色声音档案冲突 (隐喻偏好差异巨大)

    注: v3.5.2 暂不实现对话级 voice drift 检测 (需 AI 调用),
    先做 profile 配置级的 Guide.
    """
    from app.core.types import Guide, Action, GUIDE_SCOPE_UNIT

    if not project_id:
        from app.services import story_unit_service_v2 as _unit_svc
        try:
            unit = _unit_svc.get(unit_id)
            project_id = unit.project_id
        except Exception:
            return []

    guides: list[Guide] = []

    try:
        profiles = list_for_project(project_id)

        if not profiles:
            guides.append(Guide(
                source="voice",
                priority=0.5,
                confidence=0.8,
                scope=GUIDE_SCOPE_UNIT,
                advice="项目内无任何角色声音档案。AI 写作时所有角色对白可能风格雷同, 建议在设定面板为至少 2 个核心角色补充声音档案。",
                reason="list_for_project 返回空",
                evidence_ids=[],
                possible_actions=[
                    Action(label="补声音档案", description="为主角和主要配角建立 voice profile"),
                    Action(label="继续", description="暂不补充, AI 用通用对白"),
                ],
                context={"profile_count": 0},
            ))
            return guides

        # 检查声音极端
        extreme_chars = []
        for p in profiles:
            if p.personality and p.personality <= 2:
                extreme_chars.append((p.character_name, "personality 太低, 对白可能单调"))
            if p.personality and p.personality >= 9:
                extreme_chars.append((p.character_name, "personality 过高, 对白可能过于戏剧化"))

        if extreme_chars:
            desc = "; ".join(f"{n}({r})" for n, r in extreme_chars[:5])
            guides.append(Guide(
                source="voice",
                priority=0.45,
                confidence=0.6,
                scope=GUIDE_SCOPE_UNIT,
                advice=f"检测到 {len(extreme_chars)} 个角色声音维度极端: {desc}",
                reason="profile 维度值 < 3 或 > 8",
                evidence_ids=[p.id for p in profiles[:5] if hasattr(p, "id")],
                possible_actions=[
                    Action(label="调整维度", description="将极端值调到 3-8 区间"),
                    Action(label="保留", description="如果设计意图就是极端, 保留"),
                ],
                context={"extreme_count": len(extreme_chars)},
            ))

        return guides
    except Exception:
        return []
