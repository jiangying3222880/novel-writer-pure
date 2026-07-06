"""
G8 声音推断 (Voice Inferrer)
业务场景: 读某角色前 10 句对话 → 自动算出 5 维声音 → 你看档案 → 调一下 → 后续按这个声音写
  - 性格 personality:    对话中 "我"/"吾" 等称谓 + 决断词频次
  - 句长 sentence_length: 角色所有对白的平均字数
  - 语气词 tone_words:   统计句尾词 (啊/呀/呢/吧/嗯/哼...)
  - 口头禅 catchphrases: 出现 ≥ 2 次的固定短语
  - 隐喻偏好 metaphor_pref: 含 "如"/"似"/"像" 类比喻

简化: 0 tokens, 用本地规则, 至少 3 句才推断 (不足用默认)
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from app.db import _impl as _db_conn
from app.services import voice_profile
from app.services.exceptions import ValidationError


DEFAULT_SAMPLE_SIZE = 10

# 语气词候选 (句尾)
TONE_CANDIDATES = [
    "啊", "呀", "呢", "吧", "嘛", "哦", "噢", "嗯", "哼", "哈",
    "啦", "咧", "嘞", "哟", "啧", "嗨", "嘿", "呜", "唉", "啊哈",
    "嘿嘿", "呵呵", "哈哈", "嘻嘻",
]

# 隐喻标记
METAPHOR_MARKERS = ["如", "似", "像", "仿佛", "宛如", "好比", "恰似", "犹如"]


@dataclass
class InferredVoice:
    """推断结果: 5 维 + 来源统计."""
    personality: int
    sentence_length: int
    tone_words: str
    catchphrases: str
    metaphor_pref: int
    sample_lines: int
    sample_chars: int


# ============================================================
# 工具
# ============================================================

def _extract_dialogue(text: str, character_name: str) -> list[str]:
    """从章节正文抽角色的对话 (引号内 / "XX道" / "XX说" 后的句子).

    简化版: 抽所有 "..." 之间的内容, 然后筛出"含角色名指代"或"长度合理的"
    """
    if not text or not character_name:
        return []
    dialogues: list[str] = []
    # 1) 中文引号对话
    for m in re.finditer(r'["""]([^"""]+)["""]', text):
        line = m.group(1).strip()
        if line and len(line) >= 2:
            dialogues.append(line)
    # 2) "XX道" / "XX说" / "XX问" / "XX答" 后的内容 (简化: 标到下一个句号)
    for verb in ["道", "说", "问", "答", "叹", "笑", "喝", "喊", "叫"]:
        for m in re.finditer(rf"{re.escape(character_name)}{verb}[，,：:]?\s*([^。！？!?]+[。！？!?])", text):
            line = m.group(1).strip()
            if line and len(line) >= 2 and line not in dialogues:
                dialogues.append(line)
    return dialogues


def _score_to_1_10(value: float, lo: float, hi: float) -> int:
    if hi == lo:
        return 5
    norm = (value - lo) / (hi - lo)
    norm = max(0.0, min(1.0, norm))
    return int(round(1 + norm * 9))


# ============================================================
# 5 维计算
# ============================================================

def _calc_personality(lines: list[str]) -> int:
    """性格: 决断词/短促句频次  → 外向张扬.
    决断词: '老子' '本座' '我' '一定' '绝不' '必须'
    """
    decisive = ["老子", "本座", "本尊", "一定", "绝不", "必须", "敢", "哼", "哼"]
    cnt = sum(1 for line in lines for d in decisive if d in line)
    # 决断句占总句的比例
    if not lines:
        return 5
    ratio = cnt / len(lines)
    return _score_to_1_10(ratio, 0.0, 0.4)


def _calc_sentence_length(lines: list[str]) -> int:
    """句长: 平均字数 短→1 长→10."""
    if not lines:
        return 5
    avg = sum(len(l) for l in lines) / len(lines)
    return _score_to_1_10(avg, 5, 30)


def _calc_tone_words(lines: list[str]) -> str:
    """语气词: 找出现 ≥ 2 次的语气词 (行尾 / 行内 + 标点 / 重复笑声)."""
    if not lines:
        return ""
    PUNCT_AFTER = "。！？!?，,；;…"
    counter: Counter = Counter()
    for line in lines:
        for tone in TONE_CANDIDATES:
            # 1) 行尾 (tone 或 tone+标点)
            if line.endswith(tone) or (len(line) >= 2 and line[-1] in PUNCT_AFTER
                                        and line[-2:].startswith(tone)):
                counter[tone] += 1
            # 2) 行内: tone + 标点
            for p in PUNCT_AFTER:
                counter[tone] += line.count(f"{tone}{p}")
            # 3) 重复笑声 (哈哈哈 / 嘻嘻嘻): tone*2 子串算 1 次
            if len(tone) == 1:
                counter[tone] += line.count(tone * 2) - line.count(tone * 3)
    # 取出现 ≥ 2 次的
    common = [t for t, c in counter.most_common() if c >= 2]
    return " / ".join(common[:5])  # 最多 5 个


def _calc_catchphrases(lines: list[str]) -> str:
    """口头禅: 出现 ≥ 2 次的短语 (2-4 字, 长词优先)."""
    if not lines:
        return ""
    # 过滤: 句首标点 + 标点 / 数字 / 字母 / 太短
    banned = {"的", "了", "是", "我", "你", "他", "她", "它", "在", "有", "和", "与", "不", "也", "都", "就",
              "这", "那", "一个", "什么", "怎么", "这样", "那样", "他们", "我们", "你们",
              "没有", "但是", "因为", "所以", "如果", "可以", "自己"}
    # 按长度分别统计: 4 字 > 3 字 > 2 字
    by_len: dict[int, Counter] = {2: Counter(), 3: Counter(), 4: Counter()}
    for line in lines:
        for n in (2, 3, 4):
            for i in range(len(line) - n + 1):
                phrase = line[i:i + n]
                if all("\u4e00" <= c <= "\u9fff" for c in phrase) and phrase not in banned:
                    by_len[n][phrase] += 1
    # 收集候选: 长词优先
    candidates: list[tuple[str, int]] = []  # (phrase, count)
    seen: set[str] = set()
    for n in (4, 3, 2):
        for phrase, cnt in by_len[n].most_common(30):
            if cnt >= 2 and phrase not in seen:
                # 避免短词是长词的子串 (已通过"长词先入 seen"避免)
                if not any(phrase in p for p in seen):
                    candidates.append((phrase, cnt))
                    seen.add(phrase)
    return " / ".join(p for p, _ in candidates[:5])  # 最多 5 个


def _calc_metaphor(lines: list[str]) -> int:
    """隐喻偏好: 比喻句比例 0=不用 10=善用."""
    if not lines:
        return 5
    metaphoric = sum(1 for line in lines for m in METAPHOR_MARKERS if m in line)
    ratio = metaphoric / len(lines)
    return _score_to_1_10(ratio, 0.0, 0.3)


# ============================================================
# 公开 API
# ============================================================

def _gather_character_dialogue(project_id: str, character_name: str,
                                sample_size: int = DEFAULT_SAMPLE_SIZE) -> list[str]:
    """从项目前 sample_size 章抽取某角色的对话."""
    from app.services import chapter_service, book_service
    books = book_service.list_for_project(project_id).get("books", [])
    all_lines: list[str] = []
    for b in books:
        chs = chapter_service.list_for_book(b["id"]).get("chapters", [])
        for ch in chs:
            draft = chapter_service.get_current_draft(ch["id"])
            if draft and draft.get("content"):
                all_lines.extend(_extract_dialogue(draft["content"], character_name))
            if len(all_lines) >= sample_size:
                return all_lines[:sample_size]
    return all_lines[:sample_size]


def infer(project_id: str, character_name: str, *, sample_size: int = DEFAULT_SAMPLE_SIZE,
          dialogues: Optional[list[str]] = None) -> InferredVoice:
    """推断某角色的 5 维声音.

    dialogues: 可选外部传入 (比如从 A/B/C 大纲的对话片段),
                不传则从项目取实际章节的对话.
    """
    if not character_name or not character_name.strip():
        raise ValidationError("character_name 不能为空")
    if dialogues is None:
        dialogues = _gather_character_dialogue(project_id, character_name, sample_size)

    if not dialogues or len(dialogues) < 3:
        # 不足 3 句 → 用默认
        return InferredVoice(
            personality=5, sentence_length=5,
            tone_words="", catchphrases="", metaphor_pref=5,
            sample_lines=len(dialogues),
            sample_chars=sum(len(d) for d in dialogues),
        )

    return InferredVoice(
        personality=_calc_personality(dialogues),
        sentence_length=_calc_sentence_length(dialogues),
        tone_words=_calc_tone_words(dialogues),
        catchphrases=_calc_catchphrases(dialogues),
        metaphor_pref=_calc_metaphor(dialogues),
        sample_lines=len(dialogues),
        sample_chars=sum(len(d) for d in dialogues),
    )


def apply_inferred(project_id: str, character_name: str, inferred: InferredVoice
                    ) -> voice_profile.VoiceProfile:
    """把推断结果应用为某角色的声音档案."""
    return voice_profile.upsert(
        project_id, character_name,
        source=voice_profile.SOURCE_AI_INFERRED,
        personality=inferred.personality,
        sentence_length=inferred.sentence_length,
        tone_words=inferred.tone_words,
        catchphrases=inferred.catchphrases,
        metaphor_pref=inferred.metaphor_pref,
    )


def infer_and_apply(project_id: str, character_name: str, *,
                    sample_size: int = DEFAULT_SAMPLE_SIZE,
                    dialogues: Optional[list[str]] = None
                    ) -> tuple[InferredVoice, voice_profile.VoiceProfile]:
    """推断 + 应用 (一键)."""
    inferred = infer(project_id, character_name, sample_size=sample_size, dialogues=dialogues)
    vp = apply_inferred(project_id, character_name, inferred)
    return inferred, vp
