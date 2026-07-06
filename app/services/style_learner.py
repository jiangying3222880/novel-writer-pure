"""
G7 风格学习器 (Style Learner) — v3.4 rev2

业务场景: AI 学前 N 章正文 → 自动算出 L1 作者指纹 6 维 → 用户看档案 → 一键应用

学习流程:
  1) 拿项目前 N 章 (默认 10)
  2) 算 6 维 (句子节奏/对话密度/描写风格/情绪表达/段落密度/语言层级)
  3) 跟当前作者指纹对比, 给出建议值
  4) 一键应用 (upsert author_fingerprints)

核心改变:
  - 旧版用 0 token 硬编码关键词 (修真度/阴谋度等题材属性)
  - 新版用启发式统计 (句长/对话比例/动作vs描写/直说vs暗示/段落/口语vs文学)
  - 这些维度描述的是"作者笔法", 跨题材迁移

3 套风格指纹 (拍板):
  - A 版: 编排策略 A (平稳线) 学 1-N 章 → 风格指纹 A
  - B 版: 编排策略 B (上升线) 学 1-N 章 → 风格指纹 B
  - C 版: 编排策略 C (翻转线) 学 1-N 章 → 风格指纹 C
  → 用户选 1 套 → upsert 到 author_fingerprints (active)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from app.db import _impl as _db_conn
from app.services import style_fingerprint, chapter_service, book_service
from app.services.exceptions import ValidationError


VERSION_A = "A"
VERSION_B = "B"
VERSION_C = "C"
ALL_VERSIONS = [VERSION_A, VERSION_B, VERSION_C]

DEFAULT_SAMPLE_SIZE = 10  # 学前 10 章


# ============================================================
# 启发式分析 (同 ai_body_gen_plugin._analyze_style_fingerprint 逻辑)
# ============================================================

def _split_sentences(text: str) -> list[str]:
    """按 。！？… 拆句."""
    if not text:
        return []
    parts = re.split(r"[。！？!?…\n]+", text)
    return [p.strip() for p in parts if p and p.strip()]


def _score_to_1_10(value: float, lo: float, hi: float) -> int:
    """线性归一化 [lo, hi] → [1, 10], 钳制."""
    if hi == lo:
        return 5
    norm = (value - lo) / (hi - lo)
    norm = max(0.0, min(1.0, norm))
    return max(1, min(10, int(round(1 + norm * 9))))


def _calc_sentence_rhythm(text: str) -> int:
    """句子节奏: 平均句长 + 短句占比."""
    sentences = _split_sentences(text)
    if not sentences:
        return 5
    avg_len = sum(len(s) for s in sentences) / len(sentences)
    if avg_len < 20:
        return max(1, int(avg_len / 2))
    elif avg_len < 35:
        return 5
    elif avg_len < 50:
        return 7
    else:
        return min(10, int(avg_len / 5))


def _calc_dialogue_density(text: str) -> int:
    """对话密度: 引号内文字占比."""
    in_quote = False
    buf: list[str] = []
    dialogue_chars = 0
    for ch in text:
        if ch in '\u201c\u2018\u300c\u300e"' or ch in '\u201d\u2019\u300d\u300f"':
            if in_quote:
                dialogue_chars += len("".join(buf))
                buf = []
            in_quote = not in_quote
        elif in_quote:
            buf.append(ch)
    if buf:
        dialogue_chars += len("".join(buf))
    ratio = dialogue_chars / max(len(text), 1)
    # 映射 ratio 到 1-10
    return max(1, min(10, int(ratio * 20) + 1))


def _calc_description_style(text: str) -> int:
    """描写风格: 动作动词 vs 形容词+环境描写."""
    action_words = ["走", "跑", "打", "抓", "推", "拉", "跳", "拔", "挥", "踢",
                    "站", "坐", "转", "冲", "退", "举", "放", "拿", "扔", "砸"]
    adj_words = ["美丽", "寂静", "昏暗", "温暖", "冰冷", "柔软", "粗糙", "朦胧",
                 "清澈", "幽深", "苍茫", "浓郁", "淡薄", "沉重"]
    env_words = ["风", "光", "影", "雾", "雨", "树", "山", "云", "月", "星",
                 "路", "屋", "窗", "门", "墙"]
    action = sum(1 for w in action_words if w in text)
    describe = sum(1 for w in adj_words if w in text) + sum(1 for w in env_words if w in text)
    total = action + describe
    if total == 0:
        return 5
    ratio = describe / total
    return max(1, min(10, int(1 + ratio * 9)))


def _calc_emotion_expression(text: str) -> int:
    """情绪表达: 直接情绪词 vs 身体暗示."""
    direct = ["愤怒", "悲伤", "高兴", "恐惧", "焦虑", "激动", "失望",
              "兴奋", "感动", "震惊", "恼怒", "欣喜", "痛苦", "忧郁"]
    body = ["攥紧拳头", "咬紧牙关", "手心出汗", "心跳加速", "脸色发白",
            "眼眶泛红", "嘴角抽动", "眉头紧锁", "深吸一口气", "双腿发软",
            "脊背发凉", "胸口一紧", "瞳孔收缩", "颤抖", "哽咽"]
    d_score = sum(1 for w in direct if w in text)
    b_score = sum(1 for w in body if w in text)
    total = d_score + b_score
    if total == 0:
        return 5
    ratio = b_score / total
    return max(1, min(10, int(1 + ratio * 9)))


def _calc_paragraph_density(text: str) -> int:
    """段落密度: 每千字段落数."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        return 5
    para_per_1k = len(paragraphs) / (len(text) / 1000)
    return max(1, min(10, int(para_per_1k / 3) + 1))


def _calc_language_level(text: str) -> int:
    """语言层级: 口语标记 vs 文学标记."""
    oral = ["吧", "嘛", "啊", "哦", "哈", "啦", "呀", "呗", "卧槽",
            "我去", "牛", "绝了", "无语", "麻了"]
    lit = ["之", "乎", "者", "也", "其", "乃", "焉", "矣", "哉",
           "若", "尔", "吾", "卿", "君", "故", "然", "殆", "盖"]
    # 成语标记
    idiom_markers = ["之势", "之道", "亦然", "何尝", "殊不知",
                     "恰在", "如同", "仿佛", "宛若", "似是"]
    o_score = sum(1 for w in oral if w in text)
    l_score = sum(1 for w in lit if w in text) + sum(1 for w in idiom_markers if w in text) * 2
    total = o_score + l_score
    if total == 0:
        return 5
    ratio = l_score / total
    return max(1, min(10, int(1 + ratio * 9)))


def _gather_chapter_texts(project_id: str, sample_size: int = DEFAULT_SAMPLE_SIZE) -> str:
    """取项目前 sample_size 章的正文 (按 book → chapter 顺序)."""
    books = book_service.list_for_project(project_id).get("books", [])
    parts: list[str] = []
    for b in books:
        chs = chapter_service.list_for_book(b["id"]).get("chapters", [])
        for ch in chs:
            draft = chapter_service.get_current_draft(ch["id"])
            if draft and draft.get("content"):
                parts.append(draft["content"])
            if len(parts) >= sample_size:
                return "\n".join(parts)
    return "\n".join(parts)


# ============================================================
# 公开 API
# ============================================================

@dataclass
class LearnedStyle:
    """学习结果: L1 作者指纹 6 维 + 统计信息."""
    sentence_rhythm: int
    dialogue_density: int
    description_style: int
    emotion_expression: int
    paragraph_density: int
    language_level: int
    sample_chapters: int
    sample_chars: int
    version: str = ""     # A/B/C, 来自编排策略标识

    def to_dict(self) -> dict:
        return {
            "sentence_rhythm": self.sentence_rhythm,
            "dialogue_density": self.dialogue_density,
            "description_style": self.description_style,
            "emotion_expression": self.emotion_expression,
            "paragraph_density": self.paragraph_density,
            "language_level": self.language_level,
        }


def learn(project_id: str, *, sample_size: int = DEFAULT_SAMPLE_SIZE,
          version: str = "", chapters_text: Optional[str] = None) -> LearnedStyle:
    """学项目前 sample_size 章, 算 L1 作者指纹 6 维.

    chapters_text: 可选外部传入 (比如从编排策略生成的 A/B/C 正文),
                    不传则从项目取实际章节正文.
    """
    if chapters_text is None:
        chapters_text = _gather_chapter_texts(project_id, sample_size)

    if not chapters_text or not chapters_text.strip():
        raise ValidationError("无可学习章节正文 (项目还没章节或前 N 章无正文)")

    return LearnedStyle(
        sentence_rhythm=_calc_sentence_rhythm(chapters_text),
        dialogue_density=_calc_dialogue_density(chapters_text),
        description_style=_calc_description_style(chapters_text),
        emotion_expression=_calc_emotion_expression(chapters_text),
        paragraph_density=_calc_paragraph_density(chapters_text),
        language_level=_calc_language_level(chapters_text),
        sample_chapters=chapters_text.count("\n") + 1,
        sample_chars=len(chapters_text),
        version=version,
    )


def apply_learned(project_id: str, learned: LearnedStyle) -> style_fingerprint.AuthorFingerprint:
    """把学习结果应用为作者风格指纹 (active, L1)."""
    return style_fingerprint.upsert_author_fp(
        source=style_fingerprint.SOURCE_AI_LEARNED,
        **learned.to_dict(),
    )


def learn_and_apply(project_id: str, *, sample_size: int = DEFAULT_SAMPLE_SIZE,
                    version: str = "") -> tuple[LearnedStyle, style_fingerprint.AuthorFingerprint]:
    """学 + 应用 (一键). 返回 (learned, fingerprint)."""
    learned = learn(project_id, sample_size=sample_size, version=version)
    fp = apply_learned(project_id, learned)
    return learned, fp
