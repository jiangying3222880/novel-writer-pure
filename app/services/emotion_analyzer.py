"""
Emotion Analyzer — 情绪曲线分析 + 断章点检测

实现设计文档第5章: 情绪曲线断章设计。
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EmotionPoint:
    """情绪曲线上的一个点."""
    position: int        # 字符位置
    intensity: float     # 情绪强度 0-1
    emotion_type: str    # 情绪类型: tension/release/climax/dip/rise
    context: str = ""    # 上下文片段


@dataclass
class BreakPoint:
    """候选断章点."""
    position: int        # 字符位置
    pain_score: float    # 痛感评分 0-1
    pattern: str         # 匹配的断章模式
    reason: str          # 推荐理由
    risk: str = ""       # 风险提示
    text_preview: str = ""  # 原文片段


@dataclass
class SplitReport:
    """断章报告."""
    break_points: list[BreakPoint] = field(default_factory=list)
    strategy: str = "auto"
    total_chars: int = 0
    recommended_splits: list[int] = field(default_factory=list)


# ============================================================
# 断章模式（设计文档5.2）
# ============================================================

BREAK_PATTERNS = {
    "reveal": {
        "name": "揭示型",
        "pain": 5,
        "keywords": ["竟然", "原来", "真相", "发现", "揭示", "没想到", "居然是", "竟然是"],
        "patterns": [r"[？！]{2,}", r"竟然是.{2,10}[。！]", r"原来.{2,10}[。！]"],
    },
    "crisis": {
        "name": "危机型",
        "pain": 4,
        "keywords": ["危险", "紧急", "突发", "袭击", "爆炸", "崩溃", "死亡"],
        "patterns": [r"突然.{2,20}[！。]", r"不好.{2,10}[！。]", r"快跑|逃|救命"],
    },
    "choice": {
        "name": "选择型",
        "pain": 4,
        "keywords": ["选择", "决定", "犹豫", "要么", "还是", "两条路"],
        "patterns": [r"[AB]还是[AB]", r"选.{2,10}还是.{2,10}[？。]", r"决定.{2,20}[。]"],
    },
    "emotional_peak": {
        "name": "情绪峰值",
        "pain": 4,
        "keywords": ["太燃", "震撼", "感动", "热血", "泪目", "激动"],
        "patterns": [r"[！]{3,}", r"[。！]{2,}.*[！]{2,}"],
    },
    "suspense_forward": {
        "name": "悬念前置",
        "pain": 3,
        "keywords": ["然后呢", "接下来", "但是", "然而", "就在这时"],
        "patterns": [r"但是.{2,20}[。]", r"然而.{2,20}[。]", r"就在这时.{2,20}[。]"],
    },
    "scene_close": {
        "name": "场景收束",
        "pain": 2,
        "keywords": ["离开", "结束", "完成", "收尾", "告一段落"],
        "patterns": [r"离开.{2,10}[。]", r"结束.{2,10}[。]", r"走出.{2,10}[。]"],
    },
}


def analyze_emotion_curve(text: str) -> list[EmotionPoint]:
    """分析文本的情绪曲线."""
    if not text:
        return []

    points = []
    # 按段落分析
    paragraphs = text.split("\n")
    pos = 0

    for para in paragraphs:
        if not para.strip():
            pos += len(para) + 1
            continue

        intensity = _calc_paragraph_intensity(para)
        emotion_type = _classify_emotion(para, intensity)

        points.append(EmotionPoint(
            position=pos,
            intensity=intensity,
            emotion_type=emotion_type,
            context=para[:100],
        ))
        pos += len(para) + 1

    return points


def _calc_paragraph_intensity(text: str) -> float:
    """计算段落情绪强度."""
    score = 0.0

    # 感叹号密度
    excl_count = text.count("！") + text.count("!")
    score += min(0.3, excl_count * 0.05)

    # 问号密度
    quest_count = text.count("？") + text.count("?")
    score += min(0.2, quest_count * 0.05)

    # 情感词
    emotion_words = ["震撼", "感动", "热血", "泪目", "激动", "愤怒", "恐惧", "绝望", "希望"]
    for w in emotion_words:
        if w in text:
            score += 0.1

    # 动作词
    action_words = ["冲", "杀", "逃", "追", "打", "击", "爆", "炸"]
    for w in action_words:
        if w in text:
            score += 0.05

    # 对话密度
    dialogue_count = text.count('"') // 2 + text.count('"') // 2
    score += min(0.2, dialogue_count * 0.05)

    return min(1.0, score)


def _classify_emotion(text: str, intensity: float) -> str:
    """分类情绪类型."""
    if intensity > 0.7:
        if any(w in text for w in ["危险", "紧急", "袭击", "死亡"]):
            return "tension"
        if any(w in text for w in ["震撼", "感动", "热血"]):
            return "climax"
    if intensity < 0.3:
        return "dip"
    if intensity > 0.5:
        return "rise"
    return "release"


def detect_break_points(
    text: str,
    strategy: str = "auto",
    min_pain: float = 0.3,
) -> list[BreakPoint]:
    """检测候选断章点."""
    if not text:
        return []

    break_points = []
    paragraphs = text.split("\n")
    pos = 0

    for para in paragraphs:
        if not para.strip():
            pos += len(para) + 1
            continue

        # 检查每种断章模式
        for pattern_id, pattern_info in BREAK_PATTERNS.items():
            if _matches_pattern(para, pattern_info):
                pain = _calculate_pain(para, pattern_info, strategy)
                if pain >= min_pain:
                    break_points.append(BreakPoint(
                        position=pos,
                        pain_score=pain,
                        pattern=pattern_info["name"],
                        reason=f"匹配{pattern_info['name']}模式",
                        risk=_assess_risk(para, pattern_id),
                        text_preview=para[:200],
                    ))

        pos += len(para) + 1

    # 按痛感排序
    break_points.sort(key=lambda bp: -bp.pain_score)

    return break_points


def _matches_pattern(text: str, pattern_info: dict) -> bool:
    """检查文本是否匹配断章模式."""
    # 关键词匹配
    for kw in pattern_info.get("keywords", []):
        if kw in text:
            return True

    # 正则匹配
    for regex in pattern_info.get("patterns", []):
        if re.search(regex, text):
            return True

    return False


def _calculate_pain(text: str, pattern_info: dict, strategy: str) -> float:
    """计算断章痛感 (设计文档5.3)."""
    base = pattern_info["pain"] / 5.0  # 归一化到 0-1

    # 读者投入度 (基于对话和情感词)
    engagement = 0.5
    if text.count('"') > 2 or text.count('"') > 2:
        engagement += 0.2
    if any(w in text for w in ["他", "她", "我", "你"]):
        engagement += 0.1

    # 问题紧迫度 (基于问号和悬念词)
    urgency = 0.5
    if "？" in text or "?" in text:
        urgency += 0.2
    if any(w in text for w in ["然后", "接下来", "但是", "然而"]):
        urgency += 0.2

    # 策略调整
    strategy_mod = {
        "auto": 1.0,
        "爽文": 1.2 if pattern_info["name"] in ["情绪峰值", "危机型"] else 0.8,
        "悬疑": 1.2 if pattern_info["name"] in ["揭示型", "悬念前置"] else 0.8,
        "感情": 1.2 if pattern_info["name"] == "情绪峰值" else 0.9,
        "节奏": 1.1,
        "平稳": 0.8,
    }.get(strategy, 1.0)

    pain = base * engagement * urgency * strategy_mod
    return min(1.0, pain)


def _assess_risk(text: str, pattern_id: str) -> str:
    """评估断章风险."""
    risks = {
        "reveal": "下一章开头需要接住这个揭秘",
        "crisis": "需要在下一章解决危机",
        "choice": "需要在下一章展示选择结果",
        "emotional_peak": "情绪高点后需要合理回落",
        "suspense_forward": "悬念不能拖太久",
        "scene_close": "痛感较低，可能不够吸引读者",
    }
    return risks.get(pattern_id, "")


def generate_split_report(
    text: str,
    strategy: str = "auto",
    target_chars: int = 3000,
) -> SplitReport:
    """生成完整断章报告."""
    break_points = detect_break_points(text, strategy)

    # 选择最优断点 (基于痛感和间距)
    recommended = _select_optimal_breaks(break_points, len(text), target_chars)

    return SplitReport(
        break_points=break_points,
        strategy=strategy,
        total_chars=len(text),
        recommended_splits=recommended,
    )


def _select_optimal_breaks(
    break_points: list[BreakPoint],
    total_chars: int,
    target_chars: int,
) -> list[int]:
    """选择最优断点组合."""
    if not break_points:
        return []

    selected = []
    last_pos = 0

    for bp in break_points:
        # 确保断点间距合理
        if bp.position - last_pos >= target_chars * 0.5:
            selected.append(bp.position)
            last_pos = bp.position

    return sorted(selected)
