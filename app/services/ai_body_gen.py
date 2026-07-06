"""
H1 ai_body_gen 插件 (内置, 多版本正文生成).

功能:
  - generate_body_text(project_id, num_chapters=10) -> 为项目前 N 章生成 A/B/C 3 版本正文
  - 三个版本由编排决定:
      A (平稳线): 平稳推进, 注重日常/情感/角色互动, 节奏舒缓
      B (上升线): 推进主线, 加大冲突, 节奏紧凑
      C (翻转线): 引入意外/反转, 颠覆预期, 节奏强烈
  - 每版正文约 2000-3000 字
  - 保存到 chapter_drafts 表 (source='body_gen_plugin')
  - 提供 fallback: LLM 不可用时, 用模板生成

目的:
  - 用户对比 3 版正文, 选择最符合自己风格的一版
  - 系统从选定版本中学习小说的风格指纹, 存入 style_fingerprints 表
"""
from __future__ import annotations

import json
import logging
from typing import Optional, List, Dict

from app.services import (
    project_service,
    book_service,
    chapter_service,
    setting_service,
    genre_presets,
)
from app.services import style_fingerprint as style_fp_module
from app.db import _impl as _db_conn

_logger = logging.getLogger("NovelWriter.plugin.ai_body_gen")


# --------------------------------------------------------------------- #
# 编排策略提示词
# --------------------------------------------------------------------- #

ARRANGEMENT_PROMPTS = {
    "A": (
        "【编排策略 A - 平稳线】\n"
        "节奏舒缓, 注重日常描写和角色互动. 情节平稳推进, 冲突较低.\n"
        "重点: 环境描写、角色心理、对话细节、情感铺垫.\n"
        "适合: 开篇铺垫、过渡章节、角色介绍.\n"
        "句式: 偏长句, 描写细腻, 有意象和氛围感."
    ),
    "B": (
        "【编排策略 B - 上升线】\n"
        "节奏紧凑, 主线冲突不断升级. 情节快速推进, 张力持续增强.\n"
        "重点: 矛盾冲突、信息揭露、关键决策、行动描写.\n"
        "适合: 中段高潮、剧情推进、转折点.\n"
        "句式: 短句和长句交替, 动作描写多, 节奏感强."
    ),
    "C": (
        "【编排策略 C - 翻转线】\n"
        "节奏强烈, 充满意外和反转. 颠覆读者预期, 认知被打破.\n"
        "重点: 意外事件、真相揭露、立场反转、认知颠覆.\n"
        "适合: 章节末尾钩子、关键转折点、大悬念.\n"
        "句式: 变化多端, 反转处用短句,  shock 效果强."
    ),
}


def _build_body_prompt(
    chapter_no: int,
    title: str,
    project: dict,
    version: str,
    arrangement: str,
    world: str,
    characters: str,
    chapter_outline: str,
    word_target: int,
) -> str:
    """构造生成正文的 prompt."""
    genre = project.get("genre") or "通用"
    keywords = genre_presets.genre_to_keywords(genre)
    kw_line = "、".join(keywords[:6]) if keywords else ""

    return f"""你是一位资深的小说写手, 正在创作一部{genre}小说.

# 章节信息
章号: 第 {chapter_no} 章
章名: {title}
目标字数: ~{word_target} 字

# 编排策略 (本版本的核心差异)
{arrangement}

# 项目世界观
{world[:800] if world else "(无)"}

# 角色信息
{characters[:600] if characters else "(无)"}

# 本章大纲 (仅供构思参考, 严禁直接输出)
{chapter_outline[:400] if chapter_outline else "(无大纲, 请根据世界观和角色自行创作)"}

# 写作要求 (极其重要, 严格遵守)
1. 你必须写的是【小说正文】, 不是大纲、不是提纲、不是摘要
2. 正文 = 完整的场景描写, 包含: 环境描写、人物动作、对话、心理活动、感官细节
3. 禁止输出"本章讲述…"、"本章主要…"、"主要情节是…"、"本章概要"等总结性语言
4. 禁止输出列表、编号、分条概述
5. 直接以场景描写开头, 例如: "晨雾笼罩着山峰, 远处的钟声悠悠传来…"
6. 字数控制在 {word_target} 字左右 (允许 ±200 字), 写够字数
7. 语言风格贴合{genre}题材, 自然流畅, 不要有 AI 味
8. 正文开头直接进入场景, 不要写"第X章"标题, 不要写任何元信息

现在开始写正文 (直接输出小说正文, 不要任何解释):
"""


# --------------------------------------------------------------------- #
# Fallback 模板 (LLM 不可用时)
# --------------------------------------------------------------------- #

FALLBACK_BODY = {
    "A": (
        "（平稳线模板）\n\n"
        "晨光透过窗棂洒进屋内, 一切都显得宁静而安详.\n"
        "主角缓缓睁开眼睛, 开始了一天的生活...\n"
        "[注: LLM 不可用, 此为模板占位. 请配置 LLM 后重新生成.]"
    ),
    "B": (
        "（上升线模板）\n\n"
        "急促的敲门声打破了宁静. 主角心中一紧, 知道该来的终究还是来了.\n"
        "他深吸一口气, 拉开了门...\n"
        "[注: LLM 不可用, 此为模板占位. 请配置 LLM 后重新生成.]"
    ),
    "C": (
        "（翻转线模板）\n\n"
        "一切看起来都那么正常, 直到主角在抽屉底层发现了那封信.\n"
        "信上的字迹他再熟悉不过 — 但他明明亲眼看着那个人下葬的.\n"
        "[注: LLM 不可用, 此为模板占位. 请配置 LLM 后重新生成.]"
    ),
}


# --------------------------------------------------------------------- #
# LLM 调用
# --------------------------------------------------------------------- #

def _try_llm_call(prompt: str, *, step: str = "body_gen", word_target: int = 2500) -> Optional[str]:
    """尝试调 LLM 生成正文, 失败返回 None."""
    try:
        from app.ai.engine import AIEngine
        engine = AIEngine.instance()
        resp = engine.chat(
            [{"role": "user", "content": prompt}],
            task=step,
            temperature=0.8,
            max_tokens=min(word_target * 2, 4000),
        )
    except Exception as e:
        _logger.warning("LLM 调用失败, 走 fallback: %s", e)
        return None
    content = (resp.content or "").strip()
    # 去掉可能的 ``` 包裹
    if content.startswith("```"):
        lines = content.splitlines()
        if len(lines) >= 3:
            content = "\n".join(lines[1:-1]).strip()
    return content or None


def _fallback_body(version: str) -> str:
    return FALLBACK_BODY.get(version, FALLBACK_BODY["A"])


# --------------------------------------------------------------------- #
# 风格指纹分析
# --------------------------------------------------------------------- #

def _analyze_style_fingerprint(text: str) -> dict:
    """从正文中提取作者风格指纹 (L1 6 维度, 各 1-10).

    维度说明 (描述"作者笔法", 非题材属性):
      sentence_rhythm:    句子节奏 (1=短促快节奏, 10=流水长句)
      dialogue_density:   对话密度 (1=叙述为主, 10=对话为主)
      description_style:  描写风格 (1=动作驱动, 10=氛围描写)
      emotion_expression: 情绪表达 (1=直说情绪, 10=身体暗示)
      paragraph_density:  段落密度 (1=密集长段落, 10=舒朗短段落)
      language_level:     语言层级 (1=口语/网络语, 10=文学/书面语)
    """
    if not text or len(text) < 100:
        return {
            "sentence_rhythm": 5, "dialogue_density": 5,
            "description_style": 5, "emotion_expression": 5,
            "paragraph_density": 5, "language_level": 5,
        }

    # 1) 句子节奏: 平均句长 + 短句占比
    sentences = [s.strip() for s in text.replace("！", "。").replace("？", "。").split("。") if s.strip()]
    if not sentences:
        sentences = [text]
    avg_len = sum(len(s) for s in sentences) / len(sentences)
    short_ratio = sum(1 for s in sentences if len(s) < 15) / len(sentences)
    # 短句多 + 平均短 → 低分 (短促); 长句多 → 高分 (流水)
    if avg_len < 20:
        sentence_rhythm = max(1, int(avg_len / 2))
    elif avg_len < 35:
        sentence_rhythm = 5
    elif avg_len < 50:
        sentence_rhythm = 7
    else:
        sentence_rhythm = min(10, int(avg_len / 5))
    sentence_rhythm = max(1, min(10, sentence_rhythm))

    # 2) 对话密度: 引号内文字占比
    dialogue_parts = []
    in_quote = False
    buf = []
    for ch in text:
        if ch in '"''「」':
            if in_quote:
                dialogue_parts.append("".join(buf))
                buf = []
            in_quote = not in_quote
        elif in_quote:
            buf.append(ch)
    dialogue_chars = sum(len(d) for d in dialogue_parts)
    dialogue_ratio = dialogue_chars / max(len(text), 1)
    if dialogue_ratio < 0.05:
        dialogue_density = 2
    elif dialogue_ratio < 0.15:
        dialogue_density = 4
    elif dialogue_ratio < 0.30:
        dialogue_density = 6
    elif dialogue_ratio < 0.45:
        dialogue_density = 8
    else:
        dialogue_density = 10

    # 3) 描写风格: 动作动词 vs 形容词/环境描写比例
    action_words = ["走", "跑", "打", "抓", "推", "拉", "跳", "拔", "挥", "踢",
                    "站", "坐", "转", "冲", "退", "举", "放", "拿", "扔", "砸"]
    adj_words = ["美丽", "寂静", "昏暗", "温暖", "冰冷", "柔软", "粗糙", "朦胧",
                 "清澈", "幽深", "苍茫", "浓郁", "淡薄", "沉重"]
    env_words = ["风", "光", "影", "雾", "雨", "树", "山", "云", "月", "星",
                 "路", "屋", "窗", "门", "墙"]
    action_score = sum(1 for w in action_words if w in text)
    adj_score = sum(1 for w in adj_words if w in text)
    env_score = sum(1 for w in env_words if w in text)
    describe_score = adj_score + env_score
    if describe_score == 0 and action_score == 0:
        description_style = 5
    elif action_score == 0:
        description_style = 9
    else:
        ratio = describe_score / (describe_score + action_score)
        description_style = max(1, min(10, int(1 + ratio * 9)))
    description_style = max(1, min(10, description_style))

    # 4) 情绪表达: 直接情绪词 vs 身体反应暗示
    direct_emotion = ["愤怒", "悲伤", "高兴", "恐惧", "焦虑", "激动", "失望",
                      "兴奋", "感动", "震惊", "恼怒", "欣喜", "痛苦", "忧郁"]
    body_reaction = ["攥紧拳头", "咬紧牙关", "手心出汗", "心跳加速", "脸色发白",
                     "眼眶泛红", "嘴角抽动", "眉头紧锁", "深吸一口气", "双腿发软",
                     "脊背发凉", "胸口一紧", "瞳孔收缩", "颤抖", "哽咽"]
    direct_score = sum(1 for w in direct_emotion if w in text)
    body_score = sum(1 for w in body_reaction if w in text)
    if direct_score == 0 and body_score == 0:
        emotion_expression = 5
    elif body_score == 0:
        emotion_expression = 2  # 纯直说
    elif direct_score == 0:
        emotion_expression = 9  # 纯暗示
    else:
        ratio = body_score / (direct_score + body_score)
        emotion_expression = max(1, min(10, int(1 + ratio * 9)))

    # 5) 段落密度: 每千字段落数 (段落=两个换行之间的文字)
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        paragraph_density = 5
    else:
        para_per_1k = len(paragraphs) / (len(text) / 1000)
        if para_per_1k < 3:
            paragraph_density = 2   # 极少换行, 密集
        elif para_per_1k < 8:
            paragraph_density = 4
        elif para_per_1k < 15:
            paragraph_density = 6
        elif para_per_1k < 25:
            paragraph_density = 8
        else:
            paragraph_density = 10  # 频繁换行, 舒朗

    # 6) 语言层级: 口语标记 vs 书面标记
    oral_markers = ["吧", "嘛", "啊", "哦", "哈", "啦", "呀", "呗", "卧槽",
                    "我去", "牛", "绝了", "无语", "麻了"]
    literary_markers = ["之", "乎", "者", "也", "其", "乃", "焉", "矣", "哉",
                        "若", "尔", "吾", "卿", "君", "故", "然", "殆", "盖"]
    oral_score = sum(1 for w in oral_markers if w in text)
    lit_score = sum(1 for w in literary_markers if w in text)
    # 成语密度也影响文学层级
    idiom_count = sum(1 for w in ["之势", "之道", "亦然", "何尝", "殊不知",
                                   "恰在", "如同", "仿佛", "宛若", "似是"]
                      if w in text)
    lit_score += idiom_count * 2

    if oral_score == 0 and lit_score == 0:
        language_level = 5
    elif lit_score == 0:
        language_level = max(1, 4 - min(3, oral_score))
    elif oral_score == 0:
        language_level = min(10, 6 + min(4, lit_score))
    else:
        ratio = lit_score / (oral_score + lit_score)
        language_level = max(1, min(10, int(1 + ratio * 9)))
    language_level = max(1, min(10, language_level))

    return {
        "sentence_rhythm": sentence_rhythm,
        "dialogue_density": dialogue_density,
        "description_style": description_style,
        "emotion_expression": emotion_expression,
        "paragraph_density": paragraph_density,
        "language_level": language_level,
    }


# --------------------------------------------------------------------- #
# 内部辅助
# --------------------------------------------------------------------- #

def _ensure_default_book(project_id: str) -> dict:
    """找 / 创建项目下的第一个卷."""
    books = book_service.list_for_project(project_id).get("books", [])
    if books:
        return sorted(books, key=lambda b: b.get("volume_no", 0))[0]
    return book_service.create(project_id, volume_no=1, title="默认卷")


def _get_chapter_outline(chapter_id: str) -> str:
    """获取章节的最新大纲 (从 chapter_outlines 或 chapter_brief)."""
    try:
        from app.services import outline_service
        outlines = outline_service.list_outlines(chapter_id)
        for o in outlines:
            if o.get("selected"):
                return o.get("outline", "")
        if outlines:
            return outlines[-1].get("outline", "")
    except Exception:
        pass
    # fallback: 从 chapter_brief 取
    try:
        from app.services import chapter_service
        brief = chapter_service.get_brief(chapter_id)
        if brief:
            return brief.get("core_events", "") or ""
    except Exception:
        pass
    return ""


# --------------------------------------------------------------------- #
# 插件实现
# --------------------------------------------------------------------- #

class AIBodyGenPlugin:
    """
    H1 AI 多版本正文生成服务.

    用法:
      engine = AIBodyGenPlugin()
      results = engine.generate_body_text(project_id, num_chapters=10)
      # results: list[dict]
    """

    def __init__(self):

    # ─────────────── 公开 API ───────────────

    def generate_body_text(
        self,
        project_id: str,
        num_chapters: int = 10,
        *,
        word_target: int = 2500,
        use_llm: bool = True,
    ) -> list:
        """为项目前 N 章生成 3 版本正文.

        num_chapters: 1-10 (默认 10)
        word_target:  每版正文目标字数 (默认 2500)
        use_llm:      True 走 LLM, False 强制走 fallback 模板
        """
        if not (1 <= num_chapters <= 50):
            raise ValueError(f"num_chapters 建议在 1-50 (实际 {num_chapters})")

        proj = project_service.get(project_id)
        world = setting_service.get_setting(project_id, "worldbuilding").get("data") or {}
        chars = setting_service.get_setting(project_id, "characters").get("data") or {}

        world_text = _world_to_str(world)
        chars_text = _chars_to_str(chars)

        book = _ensure_default_book(project_id)
        chapters = self._ensure_chapters(book["id"], num_chapters)

        results: List[dict] = []
        for ch in chapters:
            ch_no = ch.get("chapter_no", 0)
            ch_title = ch.get("title") or f"第 {ch_no} 章"
            chapter_outline = _get_chapter_outline(ch["id"])

            drafts_dict: Dict[str, dict] = {}
            draft_ids: Dict[str, str] = {}

            for ver in ("A", "B", "C"):
                arrangement = ARRANGEMENT_PROMPTS[ver]
                content: Optional[str] = None

                if use_llm:
                    prompt = _build_body_prompt(
                        ch_no, ch_title, proj, ver,
                        arrangement, world_text, chars_text,
                        chapter_outline, word_target,
                    )
                    content = _try_llm_call(prompt, step=f"body_{ver}", word_target=word_target)

                if not content:
                    content = _fallback_body(ver)

                fallback = (content == _fallback_body(ver))
                word_count = len(content)

                # 保存到 chapter_drafts (source='agent' 表示 AI 生成)
                draft_db = chapter_service.create_draft(
                    ch["id"], content,
                    source="agent",
                )
                draft_ids[ver] = draft_db["id"]
                drafts_dict[ver] = {
                    "version": ver,
                    "content": content,
                    "word_count": word_count,
                    "fallback": fallback,
                }

            results.append({
                "chapter_id": ch["id"],
                "chapter_no": ch_no,
                "title": ch_title,
                "draft_ids": draft_ids,
                "drafts": drafts_dict,
            })

        return results

    def learn_style_fingerprint(self, project_id: str, text: str) -> dict:
        """从用户选定的正文中学习作者风格指纹, 存入 DB (L1 作者指纹).

        返回: 风格指纹 dict (6 维度)
        """
        fp = _analyze_style_fingerprint(text)
        try:
            style_fp_module.upsert_author_fp(
                source="ai_learned",
                **fp,
            )
            _logger.info("作者风格指纹已学习并保存: fp=%s", fp)
        except Exception as e:
            _logger.warning("保存作者风格指纹失败: %s", e)
        return fp

    def _ensure_chapters(self, book_id: str, num: int) -> list:
        """确保卷内有 N 章, 不够就补."""
        with _db_conn.connection() as db:
            rows = db.execute(
                "SELECT * FROM chapters WHERE book_id=? ORDER BY chapter_no LIMIT ?",
                (book_id, num),
            ).fetchall()
        existing = [dict(r) for r in rows]
        for i in range(len(existing) + 1, num + 1):
            ch = chapter_service.create(book_id, chapter_no=i, title=f"第 {i} 章")
            existing.append(ch)
        return existing[:num]


# --------------------------------------------------------------------- #
# 辅助: 世界/角色 → 字符串
# --------------------------------------------------------------------- #

def _world_to_str(world) -> str:
    if not world:
        return ""
    if isinstance(world, dict):
        return "\n".join(f"{k}: {str(v)[:200]}" for k, v in list(world.items())[:8])
    if isinstance(world, list):
        return "\n".join(str(x)[:200] for x in world[:8])
    return str(world)


def _chars_to_str(chars) -> str:
    if not chars:
        return ""
    if isinstance(chars, list):
        out = []
        for c in chars[:8]:
            if isinstance(c, dict):
                out.append(f"【{c.get('name', '?')}】{c.get('traits', c.get('personality', ''))}")
            else:
                out.append(str(c))
        return "\n".join(out)
    if isinstance(chars, dict):
        out = []
        for k, v in list(chars.items())[:8]:
            if isinstance(v, dict):
                out.append(f"【{k}】{v.get('traits', v.get('personality', ''))}")
            else:
                out.append(f"【{k}】{v}")
        return "\n".join(out)
    return str(chars)
