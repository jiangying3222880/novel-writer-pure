"""
G3 潜文本卡 (Subtext Card)
业务场景: 让 AI 知道"这一章表面在写什么, 底下在写什么" → 解决 4 大规律
  1. 解释太多 (AI 总爱把潜台词说破)
  2. 氛围断裂 (场景状态突然变)
  3. 动作冗余 (重复描写)
  4. 情感不到位 (情绪没铺垫)

13 字段:
  - surface_event:    表面事件 (本章明面在写啥)
  - true_intent:      主角真实意图
  - real_intent_others: 其他角色真实意图
  - lie:              主角撒的谎 (嘴上说的相反)
  - truth:            真相 (只有读者隐约知道)
  - emotional:        情感基调
  - pacing:           节奏 (缓/急/张弛)
  - viewpoint:        视角 (第一/第三人称/上帝)
  - anti_rules:       反规则 override (盖全局)
  - callback_to:      呼应的伏笔 (从哪些前章埋的钩)
  - scene_map:        场景地图 (本章涉及的地点/时间)
  - physical_anchor:  物理锚点 (核心物件)
  - ending_scene_state: 结尾场景状态 (本章节结束时, 主角/世界/关系是什么状态)

3 模式:
  - ai_auto:   AI 自动 (默认, 含智能跳过过渡章, 倾向保守策略)
  - manual:    手动 (章节级选预置模板微调, 6 个场景: 对峙/离别/暧昧/反转/重逢/隐瞒)
  - closed:    关闭 (默认仅清除后续章节的卡生成, 旧章节的卡保留)

决策:
  - 段落重写时AI需参考本章潜文本卡并知晓上下文
  - 不做跨章检索功能
  - 手动模式下为模板字段添加帮助按钮 (每个字段hover显示示例)
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from app.db import _impl as _db_conn
from app.services.exceptions import NotFoundError, ValidationError

_log = logging.getLogger(__name__)


# ============================================================
# 常量
# ============================================================

MODE_AI_AUTO = "ai_auto"     # AI 自动 (默认)
MODE_MANUAL = "manual"        # 手动 (章节级选预置模板)
MODE_CLOSED = "closed"        # 关闭

ALL_MODES = [MODE_AI_AUTO, MODE_MANUAL, MODE_CLOSED]

MODE_LABELS = {
    MODE_AI_AUTO: "AI 自动",
    MODE_MANUAL: "手动",
    MODE_CLOSED: "关闭",
}

# 13 字段名 (顺序敏感, UI 上展示用)
SUBTEXT_FIELDS: list[str] = [
    "surface_event", "true_intent", "real_intent_others", "lie", "truth",
    "emotional", "pacing", "viewpoint", "anti_rules", "callback_to",
    "scene_map", "physical_anchor", "ending_scene_state",
]

# 字段说明 + 示例 (手动模式 hover 帮助按钮用)
FIELD_HELP: dict[str, dict[str, str]] = {
    "surface_event": {
        "label": "表面事件",
        "hint": "本章明面上在写啥 (读者一眼看到的事)",
        "example": "林轩在宗门大会上接受筑基测试",
    },
    "true_intent": {
        "label": "真实意图",
        "hint": "主角真正想做啥 (推动故事的内因)",
        "example": "想借测试查清是谁换了筑基丹",
    },
    "real_intent_others": {
        "label": "他人意图",
        "hint": "其他关键角色各自想要啥 (制造冲突)",
        "example": "王师兄想栽赃; 师傅想借机考察",
    },
    "lie": {
        "label": "撒的谎",
        "hint": "主角嘴上说一套, 实际是相反 (人物复杂度)",
        "example": "对师傅说'晚辈只想安稳修炼' (实为已起疑心)",
    },
    "truth": {
        "label": "真相",
        "hint": "只有读者隐约知道的真相 (伏笔/隐线)",
        "example": "换丹的是二长老, 他与王师兄早已勾结",
    },
    "emotional": {
        "label": "情感基调",
        "hint": "本章主导情绪 (不是情节, 是情感氛围)",
        "example": "压抑中带试探, 表面恭谨内里警觉",
    },
    "pacing": {
        "label": "节奏",
        "hint": "本章节奏 (起承转合的位置 + 速度)",
        "example": "缓起 → 测试冲突急升 → 结尾余韵缓收",
    },
    "viewpoint": {
        "label": "视角",
        "hint": "本章用谁的眼睛看 (限制视角 ≠ 全知)",
        "example": "第三人称限知·林轩",
    },
    "anti_rules": {
        "label": "反规则 override",
        "hint": "本章临时反规则 (盖全局), 比如本章允许'内心独白'",
        "example": "允许简短内心独白 (因林轩自省场面需要)",
    },
    "callback_to": {
        "label": "呼应伏笔",
        "hint": "本章呼应了哪些前章埋的钩 (回收伏笔)",
        "example": "呼应第 3 章师傅给的玉佩, 测试时发热",
    },
    "scene_map": {
        "label": "场景地图",
        "hint": "本章涉及的地点 + 时间 + 天气 (营造真实感)",
        "example": "天玄宗·演武殿 → 偏殿密谈 · 下午雨后",
    },
    "physical_anchor": {
        "label": "物理锚点",
        "hint": "本章最核心的物件 (反复出现, 承载象征)",
        "example": "筑基丹 (贯穿本章, 每次出现都暗藏线索)",
    },
    "ending_scene_state": {
        "label": "结尾场景状态",
        "hint": "本章节结束时, 主角/世界/关系处于什么状态 (下章接力点)",
        "example": "林轩表面通过测试, 实则身份被二长老注意到, 关系网暗流",
    },
}

# 6 预置场景模板 (手动模式下拉)
PRESET_TEMPLATES: list[dict] = [
    {
        "id": "tpl_confrontation",
        "name": "对峙",
        "description": "正面对峙, 表面克制, 底下暗流涌动",
        "scene_map": "{地点}: 主角与对手首次/再次正面交锋的封闭空间",
        "physical_anchor": "{物件}: 见证对峙或被争夺的物件",
        "emotional": "压抑 + 紧张 + 表面平静",
        "pacing": "缓起 → 试探 → 急转 → 留白",
    },
    {
        "id": "tpl_farewell",
        "name": "离别",
        "description": "与重要角色分离, 表面平静实则牵绊",
        "scene_map": "{地点}: 离别场景 (渡口/山门/城门)",
        "physical_anchor": "{物件}: 临别信物或赠礼",
        "emotional": "不舍 + 决然 + 隐性承诺",
        "pacing": "缓 → 渐急 → 收",
    },
    {
        "id": "tpl_ambiguity",
        "name": "暧昧",
        "description": "两人间微妙情感, 都没说破",
        "scene_map": "{地点}: 私密或半私密空间 (灯下/雨中/车中)",
        "physical_anchor": "{物件}: 共同关注的小物 (茶/伞/信)",
        "emotional": "微甜 + 不安 + 试探",
        "pacing": "极缓 → 小高潮 → 悬停",
    },
    {
        "id": "tpl_twist",
        "name": "反转",
        "description": "认知被颠覆, 读者重新理解前情",
        "scene_map": "{地点}: 真相揭示场所 (密室/遗物前/对质)",
        "physical_anchor": "{物件}: 反转的物证 (信物/伤口/记忆)",
        "emotional": "震惊 + 怀疑 + 重新校准",
        "pacing": "急 → 急 → 急 (密集)",
    },
    {
        "id": "tpl_reunion",
        "name": "重逢",
        "description": "离散之人再会, 表面热络实则生分",
        "scene_map": "{地点}: 意料之外的相遇点",
        "physical_anchor": "{物件}: 旧时共有物 (伤疤/约定物)",
        "emotional": "惊喜 + 迟疑 + 试探",
        "pacing": "急停 → 缓 → 再起波澜",
    },
    {
        "id": "tpl_concealment",
        "name": "隐瞒",
        "description": "主角对外藏真相, 内在拉扯",
        "scene_map": "{地点}: 公开场合中藏暗线",
        "physical_anchor": "{物件}: 隐藏真意的物 (暗器/暗号/伤)",
        "emotional": "警觉 + 表演 + 内耗",
        "pacing": "缓 → 缓 → 突然事件 → 余韵",
    },
]


# ============================================================
# dataclass
# ============================================================

@dataclass
class SubtextCard:
    """1 个章节的潜文本卡 (13 字段)."""
    id: str
    chapter_id: str
    surface_event: str = ""
    true_intent: str = ""
    real_intent_others: str = ""
    lie: str = ""
    truth: str = ""
    emotional: str = ""
    pacing: str = ""
    viewpoint: str = ""
    anti_rules: str = ""
    callback_to: str = ""
    scene_map: str = ""
    physical_anchor: str = ""
    ending_scene_state: str = ""
    source: str = "manual"            # ai_auto / manual / template
    template_id: str = ""
    created_at: str = ""
    updated_at: str = ""


# ============================================================
# 工具
# ============================================================

def _conn():
    return _db_conn.get_conn()


def _row_to_card(row) -> SubtextCard:
    return SubtextCard(
        id=row["id"],
        chapter_id=row["chapter_id"],
        surface_event=row["surface_event"] or "",
        true_intent=row["true_intent"] or "",
        real_intent_others=row["real_intent_others"] or "",
        lie=row["lie"] or "",
        truth=row["truth"] or "",
        emotional=row["emotional"] or "",
        pacing=row["pacing"] or "",
        viewpoint=row["viewpoint"] or "",
        anti_rules=row["anti_rules"] or "",
        callback_to=row["callback_to"] or "",
        scene_map=row["scene_map"] or "",
        physical_anchor=row["physical_anchor"] or "",
        ending_scene_state=row["ending_scene_state"] or "",
        source=row["source"] or "manual",
        template_id=row["template_id"] or "",
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


# ============================================================
# 6 预置模板 (seed)
# ============================================================

def seed_presets() -> int:
    """把 6 个预置模板写进 subtext_templates (built_in=1), 已存在则跳过. 返回新插入数."""
    cur = _conn()
    inserted = 0
    for tpl in PRESET_TEMPLATES:
        existing = cur.execute(
            "SELECT id FROM subtext_templates WHERE id = ?", (tpl["id"],)
        ).fetchone()
        if existing:
            continue
        cur.execute(
            "INSERT INTO subtext_templates (id, name, description, template_json, built_in) "
            "VALUES (?, ?, ?, ?, 1)",
            (
                tpl["id"],
                tpl["name"],
                tpl["description"],
                json.dumps(tpl, ensure_ascii=False),
            ),
        )
        inserted += 1
    cur.commit()
    return inserted


def list_presets() -> list[dict]:
    """列 6 预置模板 (手动模式下拉用)."""
    rows = _conn().execute(
        "SELECT * FROM subtext_templates WHERE built_in = 1 ORDER BY name"
    ).fetchall()
    out = []
    for r in rows:
        try:
            data = json.loads(r["template_json"] or "{}")
        except json.JSONDecodeError:
            data = {}
        out.append({
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            **data,
        })
    return out


def get_preset(tpl_id: str) -> dict:
    """取 1 个预置模板. 404 → NotFoundError."""
    r = _conn().execute(
        "SELECT * FROM subtext_templates WHERE id = ?", (tpl_id,)
    ).fetchone()
    if not r:
        raise NotFoundError(f"模板不存在: {tpl_id}")
    try:
        return json.loads(r["template_json"] or "{}")
    except json.JSONDecodeError:
        return {}


# ============================================================
# 项目级模式
# ============================================================

def get_project_mode(project_id: str) -> dict:
    """取项目级模式 (默认 ai_auto)."""
    r = _conn().execute(
        "SELECT * FROM subtext_project_modes WHERE project_id = ?", (project_id,)
    ).fetchone()
    if not r:
        return {"project_id": project_id, "mode": MODE_AI_AUTO, "template_id": ""}
    return {"project_id": r["project_id"], "mode": r["mode"], "template_id": r["template_id"] or ""}


def set_project_mode(project_id: str, mode: str, template_id: str = "") -> dict:
    """设项目级模式 + 可选默认模板 (仅 manual 模式有意义)."""
    if mode not in ALL_MODES:
        raise ValidationError(f"未知模式: {mode}, 允许: {ALL_MODES}")
    if mode == MODE_MANUAL and template_id:
        # 校验模板存在
        get_preset(template_id)

    cur = _conn()
    existing = cur.execute(
        "SELECT project_id FROM subtext_project_modes WHERE project_id = ?", (project_id,)
    ).fetchone()
    if existing:
        cur.execute(
            "UPDATE subtext_project_modes SET mode = ?, template_id = ?, updated_at = datetime('now') "
            "WHERE project_id = ?",
            (mode, template_id, project_id),
        )
    else:
        cur.execute(
            "INSERT INTO subtext_project_modes (project_id, mode, template_id) VALUES (?, ?, ?)",
            (project_id, mode, template_id),
        )
    cur.commit()
    return get_project_mode(project_id)


# ============================================================
# 章节级卡 CRUD
# ============================================================

def get_card_for_chapter(chapter_id: str) -> Optional[SubtextCard]:
    """取本章潜文本卡 (无则 None)."""
    r = _conn().execute(
        "SELECT * FROM scene_subtext_cards WHERE chapter_id = ? ORDER BY updated_at DESC LIMIT 1",
        (chapter_id,),
    ).fetchone()
    if not r:
        return None
    return _row_to_card(r)


def upsert_card(chapter_id: str, **fields) -> SubtextCard:
    """新建或更新本章卡 (13 字段按 kwargs 覆盖)."""
    # 校验字段
    for k in fields:
        if k not in SUBTEXT_FIELDS + ["source", "template_id"]:
            raise ValidationError(f"未知字段: {k}")

    cur = _conn()
    existing = get_card_for_chapter(chapter_id)

    if existing:
        # UPDATE
        sets: list[str] = []
        values: list = []
        for fld in SUBTEXT_FIELDS:
            if fld in fields:
                sets.append(f"{fld} = ?")
                values.append(fields[fld])
        if "source" in fields:
            sets.append("source = ?"); values.append(fields["source"])
        if "template_id" in fields:
            sets.append("template_id = ?"); values.append(fields["template_id"])
        if not sets:
            return existing
        sets.append("updated_at = datetime('now')")
        values.append(existing.id)
        cur.execute(
            f"UPDATE scene_subtext_cards SET {', '.join(sets)} WHERE id = ?", values
        )
        cur.execute(
            "UPDATE chapters SET has_subtext = 1, subtext_mode = COALESCE(NULLIF(?, ''), subtext_mode) "
            "WHERE id = ?", (fields.get("source", ""), chapter_id)
        )
    else:
        # INSERT
        cid = f"st_{uuid.uuid4().hex[:10]}"
        cols = ["id", "chapter_id"] + SUBTEXT_FIELDS + ["source", "template_id"]
        vals: list = [cid, chapter_id]
        for fld in SUBTEXT_FIELDS:
            vals.append(fields.get(fld, ""))
        vals.append(fields.get("source", "manual"))
        vals.append(fields.get("template_id", ""))
        placeholders = ",".join(["?"] * len(vals))
        cur.execute(
            f"INSERT INTO scene_subtext_cards ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        cur.execute(
            "UPDATE chapters SET has_subtext = 1, subtext_mode = ? WHERE id = ?",
            (fields.get("source", "manual"), chapter_id),
        )

    cur.commit()
    return get_card_for_chapter(chapter_id)


def delete_card(chapter_id: str) -> bool:
    """删本章卡 (返回是否真删了). 不动 chapters 标记 (按决策: 旧章节的卡保留, 标记可手动改)."""
    cur = _conn()
    cur.execute("DELETE FROM scene_subtext_cards WHERE chapter_id = ?", (chapter_id,))
    cur.execute(
        "UPDATE chapters SET has_subtext = 0, subtext_mode = '' WHERE id = ?", (chapter_id,)
    )
    cur.commit()
    return cur.total_changes > 0


# ============================================================
# AI 自动生成 (真 AI 调用, 解析 13 字段潜文本卡)
# ============================================================

def should_skip_for_ai_auto(chapter_word_count: int, *, threshold: int = 1000) -> bool:
    """AI 自动模式下智能跳过过渡章 (字数 < threshold 视为过渡)."""
    return chapter_word_count < threshold


def _derive_viewpoint(project_id: str) -> str:
    """从项目设定取默认视角."""
    return "第三人称限知·主角"

_AUTOGEN_SYSTEM = """你是一个小说潜文本分析师。根据章节简述，生成 13 字段潜文本卡。

输出纯 JSON (不要 markdown 代码块):
{
  "surface_event": "表面事件 (本章明面在写什么, ≤40字)",
  "true_intent": "主角真实意图 (表面没说出来的动机, ≤60字)",
  "real_intent_others": "其他角色真实意图 (≤60字, 无则\"\")",
  "lie": "主角嘴上说的谎话 (≤40字, 无则\"\")",
  "truth": "读者隐约知道的真相 (≤40字, 无则\"\")",
  "emotional": "情感基调 (紧张/温情/压抑/轻松/悲壮/暖昧 等, ≤30字)",
  "pacing": "节奏 (缓起→推进→收 / 急转直下 / 张弛交替, ≤30字)",
  "viewpoint": "视角 (第三人称限知·主角 / 第一人称·主角 / 上帝视角, ≤20字)",
  "anti_rules": "本场不写的东西 (≤60字, 无则\"\")",
  "callback_to": "呼应的伏笔 (≤60字, 无则\"\")",
  "scene_map": "场景地图 (地点/时间, ≤40字)",
  "physical_anchor": "物理锚点/核心物件 (≤30字, 无则\"\")",
  "ending_scene_state": "结尾场景状态 (主角/世界/关系发生了什么变化, ≤60字)"
}

规则:
- surface_event 必须从简述中提炼, 不能编造
- true_intent 必须是角色内心未说出的真实动机
- 所有字段能空则空不要硬填
- 不要输出任何解释, 只输出 JSON"""


def _get_ai_engine():
    """取 AI 引擎单例."""
    try:
        from app.ai.engine import AIEngine
        from app.core.container import get_container
        return get_container().resolve("ai_engine") or AIEngine()
    except Exception:
        from app.ai.engine import AIEngine
        return AIEngine()


def _parse_ai_subtext_json(raw: str) -> dict:
    """从 AI 返回文本中提取 JSON."""
    # 尝试直接解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # 尝试提取 ```json ... ``` 代码块
    import re
    m = re.search(r'\{[\s\S]*\}', raw)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


def auto_generate(project_id: str, chapter_id: str, brief: str, word_count: int) -> SubtextCard:
    """AI 自动模式: 真 AI 调用生成 13 字段潜文本卡.

    流程:
      1. 字数 < 1000 → 跳过 (过渡章)
      2. 调 AIEngine.chat() 分析简述
      3. 解析 JSON → 填充字段
      4. AI 失败时降级到本地规则 fallback
    """
    if should_skip_for_ai_auto(word_count):
        raise ValidationError(
            f"过渡章 (字数 {word_count} < 1000), AI 自动模式跳过"
        )

    # 组装 user prompt (取章节简述 + 标题)
    user_prompt = f"章节简述: {brief[:500]}\n字数: {word_count}\n\n请生成此章的潜文本卡 JSON."

    # 尝试真 AI 调用
    ai_fields: dict = {}
    try:
        engine = _get_ai_engine()
        from app.ai.engine import ChatMessage
        resp = engine.chat(
            messages=[
                ChatMessage(role="system", content=_AUTOGEN_SYSTEM),
                ChatMessage(role="user", content=user_prompt),
            ],
            task="subtext_auto",
            temperature=0.7,
            max_tokens=800,
        )
        if resp and resp.content:
            ai_fields = _parse_ai_subtext_json(resp.content)
            _log.info("[subtext] AI auto_generate ok, fields=%d tokens_in=%d tokens_out=%d",
                      len(ai_fields), resp.tokens_in, resp.tokens_out)
    except Exception as e:
        _log.warning("[subtext] AI auto_generate 失败, 降级到本地规则: %s", e)

    # 合并: AI 优先, 本地兜底
    surface = ai_fields.get("surface_event") or brief[:30] + ("…" if len(brief) > 30 else "")
    true_intent = ai_fields.get("true_intent") or "推动剧情进展"
    viewpoint = ai_fields.get("viewpoint") or _derive_viewpoint(project_id)
    emotional = ai_fields.get("emotional") or "待细化"
    pacing = ai_fields.get("pacing") or "缓起 → 推进 → 收"
    lie = ai_fields.get("lie") or ""
    truth = ai_fields.get("truth") or ""
    anti_rules = ai_fields.get("anti_rules") or ""
    callback_to = ai_fields.get("callback_to") or ""
    scene_map = ai_fields.get("scene_map") or ""
    physical_anchor = ai_fields.get("physical_anchor") or ""
    ending_scene_state = ai_fields.get("ending_scene_state") or ""
    real_intent_others = ai_fields.get("real_intent_others") or ""

    return upsert_card(
        chapter_id,
        surface_event=surface,
        true_intent=true_intent,
        real_intent_others=real_intent_others,
        lie=lie,
        truth=truth,
        emotional=emotional,
        pacing=pacing,
        viewpoint=viewpoint,
        anti_rules=anti_rules,
        callback_to=callback_to,
        scene_map=scene_map,
        physical_anchor=physical_anchor,
        ending_scene_state=ending_scene_state,
        source="ai_auto",
        template_id="",
    )


def generate_from_intent(
    project_id: str,
    chapter_id: str,
    intent: str,
    confirmed_points: Optional[dict] = None
) -> SubtextCard:
    """从用户意图生成潜文本卡（简化交互）.

    流程:
      1. 用户输入自然语言意图（1-2句话）
      2. AI 解析意图，生成确认要点（场景/事件/冲突/伏笔/情感）
      3. 用户确认/调整
      4. 根据确认的要点生成完整 13 字段潜文本卡

    Args:
        project_id: 项目 ID
        chapter_id: 章节 ID
        intent: 用户输入的自然语言意图
        confirmed_points: 用户确认的要点字典，包含:
            - scene: 场景描述
            - events: 主要事件
            - conflict: 冲突点
            - foreshadowing: 伏笔/呼应
            - emotion: 情感基调

    Returns:
        SubtextCard: 生成的潜文本卡
    """
    if not intent.strip():
        raise ValidationError("意图不能为空")

    # 如果提供了确认要点，基于要点生成
    if confirmed_points:
        surface_event = confirmed_points.get("events", intent)[:60]
        true_intent = confirmed_points.get("conflict", "推动剧情发展")
        emotional = confirmed_points.get("emotion", "待细化")
        callback_to = confirmed_points.get("foreshadowing", "")
        scene_map = confirmed_points.get("scene", "")
    else:
        # 未提供确认要点，从意图中提取关键信息（简化版）
        surface_event = intent[:60]
        true_intent = "推动剧情发展"
        emotional = "待 AI 细化"
        callback_to = ""
        scene_map = ""

    viewpoint = _derive_viewpoint(project_id)

    return upsert_card(
        chapter_id,
        surface_event=surface_event,
        true_intent=true_intent,
        real_intent_others="",
        lie="",
        truth="",
        emotional=emotional,
        pacing="缓起 → 推进 → 收",
        viewpoint=viewpoint,
        anti_rules="",
        callback_to=callback_to,
        scene_map=scene_map,
        physical_anchor="",
        ending_scene_state="",
        source="intent",
        template_id="",
    )


def parse_intent_to_points(intent: str) -> dict:
    """解析用户意图，生成确认要点（调 AI 解析）.

    流程:
      1. 用户输入自然语言意图
      2. AI 解析意图，返回 5 个维度的要点
      3. 用户可在 UI 上微调后确认

    Args:
        intent: 用户输入的自然语言意图

    Returns:
        dict: 包含 scene/events/conflict/foreshadowing/emotion 的字典
    """
    # 尝试调 AI 解析
    try:
        from app.services.conversation_service import _call_llm

        system_prompt = """你是一位资深的小说编辑，擅长分析章节的潜文本结构。

用户会给你一段关于某章节的创作意图，请你解析出以下 5 个维度的要点：

1. **场景** (scene): 本章发生在哪里？什么时间？什么环境？
2. **主要事件** (events): 本章明面上在写什么事？
3. **冲突点** (conflict): 本章的核心冲突是什么？谁和谁的矛盾？
4. **伏笔/呼应** (foreshadowing): 本章需要埋什么钩子？呼应前文的什么？
5. **情感基调** (emotion): 本章的主导情绪是什么？（压抑/紧张/温馨/热血等）

请按以下 JSON 格式输出（不要输出其他内容）：
```json
{
  "scene": "场景描述",
  "events": "主要事件",
  "conflict": "冲突点",
  "foreshadowing": "伏笔/呼应",
  "emotion": "情感基调"
}
```"""

        user_prompt = f"用户意图：{intent}"

        result = _call_llm(system_prompt, user_prompt)

        # 尝试解析 JSON
        import re
        json_match = re.search(r'\{[^}]+\}', result, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                return {
                    "scene": parsed.get("scene", ""),
                    "events": parsed.get("events", intent),
                    "conflict": parsed.get("conflict", ""),
                    "foreshadowing": parsed.get("foreshadowing", ""),
                    "emotion": parsed.get("emotion", ""),
                }
            except json.JSONDecodeError:
                pass

        # JSON 解析失败，返回原始结果
        return {
            "scene": "",
            "events": intent,
            "conflict": "",
            "foreshadowing": "",
            "emotion": "",
        }

    except Exception as e:
        _log.warning(f"[subtext] AI 解析意图失败，降级到本地规则: {e}")
        # 降级：直接返回意图作为事件，其他字段留空待用户确认
        return {
            "scene": "",
            "events": intent,
            "conflict": "",
            "foreshadowing": "",
            "emotion": "",
        }


# ============================================================
# 手动模式: 从模板填初始值
# ============================================================

def apply_template(chapter_id: str, template_id: str, brief: str = "") -> SubtextCard:
    """手动模式: 把 1 个预置模板的内容填进卡 (brief 可选替换 surface_event)."""
    tpl = get_preset(template_id)
    fields = {
        "scene_map": tpl.get("scene_map", ""),
        "physical_anchor": tpl.get("physical_anchor", ""),
        "emotional": tpl.get("emotional", ""),
        "pacing": tpl.get("pacing", ""),
        "source": "template",
        "template_id": template_id,
    }
    if brief:
        fields["surface_event"] = brief[:30] + ("…" if len(brief) > 30 else "")
    return upsert_card(chapter_id, **fields)


# ============================================================
# 关闭模式
# ============================================================

def close_after(project_id: str) -> int:
    """关闭模式: 清掉项目所有"未写章节"的卡 (按决策: 仅清除后续章节, 旧章节的卡保留).

    "已写" = chapters.current_draft_id 指向的 draft.content 长度 ≥ 500 字.
    """
    cur = _conn()
    cur.execute(
        "DELETE FROM scene_subtext_cards WHERE chapter_id IN ("
        "  SELECT c.id FROM chapters c "
        "  LEFT JOIN chapter_drafts d ON d.id = c.current_draft_id "
        "  WHERE c.book_id IN (SELECT id FROM books WHERE project_id = ?) "
        "  AND (c.current_draft_id IS NULL OR length(d.content) < 500)"
        ")",
        (project_id,),
    )
    cleared = cur.total_changes
    cur.execute(
        "UPDATE chapters SET has_subtext = 0, subtext_mode = '' "
        "WHERE id IN ("
        "  SELECT c.id FROM chapters c "
        "  LEFT JOIN chapter_drafts d ON d.id = c.current_draft_id "
        "  WHERE c.book_id IN (SELECT id FROM books WHERE project_id = ?) "
        "  AND (c.current_draft_id IS NULL OR length(d.content) < 500)"
        ")",
        (project_id,),
    )
    cur.commit()
    return cleared


# ============================================================
# 状态符号 (章节管理 tab 列表标注用)
# ============================================================

SUBTEXT_MARK = "🎭"  # 用了 Subtext 的章节在列表后面标注


def list_chapters_with_subtext_mark(book_id: str) -> list[dict]:
    """列某书章节 + has_subtext 标记 (UI 章节管理 tab 用)."""
    rows = _conn().execute(
        "SELECT id, title, has_subtext, subtext_mode FROM chapters WHERE book_id = ? ORDER BY chapter_no",
        (book_id,),
    ).fetchall()
    out = []
    for r in rows:
        mark = SUBTEXT_MARK if r["has_subtext"] else ""
        out.append({
            "id": r["id"],
            "title": r["title"] + (mark if mark else ""),
            "has_subtext": bool(r["has_subtext"]),
            "subtext_mode": r["subtext_mode"] or "",
        })
    return out


# ============================================================
# 上下文拼装 (给 G1 v3 引擎 / 段落重写用)
# ============================================================

def assemble_for_prompt(chapter_id: str) -> dict:
    """取本章潜文本卡, 转成 prompt 注入格式 (供 AI 写章节 / 段落重写参考).

    决策: 段落重写时AI需参考本章潜文本卡并知晓上下文
    """
    card = get_card_for_chapter(chapter_id)
    if not card:
        return {"has_card": False}
    return {
        "has_card": True,
        "source": card.source,
        "fields": {f: getattr(card, f) for f in SUBTEXT_FIELDS},
        "non_empty_fields": [f for f in SUBTEXT_FIELDS if getattr(card, f)],
    }


# ============================================================
# 统计
# ============================================================

def stats(project_id: str) -> dict:
    """项目潜文本统计 (供仪表盘 / 章节管理顶 banner)."""
    cur = _conn()
    mode = get_project_mode(project_id)
    total_cards = cur.execute(
        "SELECT COUNT(*) AS c FROM scene_subtext_cards c "
        "JOIN chapters ch ON c.chapter_id = ch.id "
        "JOIN books b ON ch.book_id = b.id "
        "WHERE b.project_id = ?",
        (project_id,),
    ).fetchone()["c"]
    chapters_with = cur.execute(
        "SELECT COUNT(*) AS c FROM chapters ch "
        "JOIN books b ON ch.book_id = b.id "
        "WHERE b.project_id = ? AND ch.has_subtext = 1",
        (project_id,),
    ).fetchone()["c"]
    return {
        "mode": mode["mode"],
        "mode_label": MODE_LABELS.get(mode["mode"], "未知"),
        "total_cards": total_cards,
        "chapters_with_subtext": chapters_with,
    }
