"""
单元拆章器 (Unit Splitter)
- 把一个故事单元拆分成多个章节
- 自动检测断章点（场景转换、情绪高点、悬念处）
- 支持交互式确认和调整
- 拆章后自动创建章节并迁移数据

DB: app.db._impl
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.db import _impl as _db_conn
from app.services import story_unit_service_v2 as story_unit_service
from app.services.chapter_service import create as create_chapter
from app.services.exceptions import ValidationError

_logger = logging.getLogger("NovelWriter.services.unit_splitter")


# ────────────────────── 数据类 ──────────────────────

@dataclass
class SplitPoint:
    """一个断章点。"""
    position: int               # 在原文中的字符位置
    suggested_title: str = ""   # 建议的章节标题
    reason: str = ""            # 断章理由
    confidence: float = 0.0     # 置信度 0-1
    end_of_paragraph: bool = False  # 是否在段落结尾


@dataclass
class SplitResult:
    """拆章结果。"""
    unit_id: str
    chapters: list[dict] = field(default_factory=list)  # 创建的章节列表
    total_chapters: int = 0
    migrated_memories: int = 0
    migrated_characters: int = 0


# ────────────────────── 断章点分析 ──────────────────────

# 常见的场景转换标记
_SCENE_BREAK_PATTERNS = [
    (r"\n\s*\*\s*\*\s*\*\s*\n", "场景分隔线", 0.9),
    (r"\n\s*—+\s*\n", "场景分隔线", 0.8),
    (r"\n\s*第.+[章节卷]\b", "章节标题", 0.7),
    (r"\n\s*【.+】\s*\n", "场景标记", 0.6),
]

# 悬念/钩子结尾模式
_HOOK_END_PATTERNS = [
    (r"[，。！？]\s*$", "陈述句结尾", 0.3),
    (r"[？?!！]\s*$", "疑问/感叹结尾", 0.5),
    (r"(竟然|居然|没想到|难道|怎么会)\s*.{0,10}[。！？]\s*$", "惊讶句式", 0.6),
    (r"(是你|原来是|竟然是|这是)\s*.{0,10}[。！？]\s*$", "揭示句式", 0.7),
    (r"(不敢相信|难以置信|惊呆了|愣住了|怔住了)\s*.{0,10}[。！？]?\s*$", "震惊结尾", 0.6),
    (r"(转身|回头|抬头|低头看去?|望向|看去?)\s*.{0,15}[。！？]?\s*$", "动作悬念", 0.5),
    (r"(话音未落|话音刚落|话一出口|话刚说完)", "话刚说完", 0.5),
    (r"(突然|忽然|就在这时|恰在此时|下一刻|紧接着)", "突发转折", 0.6),
]

# 情绪强烈的句子（情绪高点）
_EMOTION_HIGH_PATTERNS = [
    (r"(怒吼|咆哮|嘶吼|尖叫|大喊|大叫)", "强烈情绪", 0.6),
    (r"(心碎|崩溃|绝望|狂喜|愤怒)", "极致情绪", 0.7),
    (r"(轰！|砰！|唰！|锵！)", "拟声词高潮", 0.5),
]


def analyze_split_points(
    unit_id: str,
    *,
    target_chars: int = 3000,
    min_chars: int = 2000,
    max_chars: int = 4000,
    use_ai_analysis: bool = False,
) -> list[SplitPoint]:
    """
    分析一个单元的断章点。
    - target_chars: 目标章节字数（默认 3000）
    - min_chars: 最小章节字数
    - max_chars: 最大章节字数
    - use_ai_analysis: [TODO 待实现] 是否启用 AI 情绪曲线分析
        目前仅实现第一层（正则+段落边界+字数），
        AI 情绪分析层和六种断章模式判定尚未接入。

    返回按位置排序的断章点列表（含建议标题和置信度）

    断章三层设计 (当前已实现第一层):
      Layer 1: 正则模式匹配 + 字数约束 + 段落边界 (已实现)
      Layer 2: AI 情绪曲线分析 + 痛感评分 + 断章模式判定 (TODO)
      Layer 3: 人工调整 (UI 层面)
    """
    unit = story_unit_service.get(unit_id)
    if not unit.draft:
        raise ValidationError("单元草稿为空，无法拆章")

    text = unit.draft
    total_len = len(text)

    if total_len <= min_chars:
        return []  # 太短了，不用拆

    # 第一步：找出所有段落结尾
    para_ends = []
    for m in re.finditer(r"\n\n+", text):
        pos = m.start()
        if pos > 0:
            para_ends.append(pos)

    if not para_ends:
        # 没有明显分段，按换行拆
        for m in re.finditer(r"\n", text):
            para_ends.append(m.start())

    # 第二步：在每个目标位置附近找最佳断章点
    split_points: list[SplitPoint] = []
    current_pos = 0
    target_pos = target_chars

    while target_pos < total_len - min_chars // 2:
        # 在 target_pos 前后找最近的段落结尾
        best_pos = None
        best_dist = float('inf')

        for pe in para_ends:
            if pe < current_pos + min_chars:
                continue
            if pe > current_pos + max_chars:
                break
            dist = abs(pe - target_pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = pe

        if best_pos is None:
            # 没找到合适的段落结尾，强制在 max_chars 处断
            best_pos = min(current_pos + max_chars, total_len)
            # 回溯到最近的句号/感叹号/问号
            search_end = best_pos
            search_start = max(current_pos + min_chars, best_pos - 500)
            segment = text[search_start:search_end]
            # 找最后一个句末标点
            last_punc = -1
            for m in re.finditer(r"[。！？!?]", segment):
                last_punc = m.end()
            if last_punc > 0:
                best_pos = search_start + last_punc

        # 计算置信度和理由
        confidence = 0.5
        reasons = []

        # 检查是否是段落结尾
        is_para_end = best_pos in para_ends or (
            best_pos < len(text) and text[best_pos] == '\n'
        )
        if is_para_end:
            confidence += 0.2
            reasons.append("段落结尾")

        # 检查结尾句式（悬念）
        end_segment = text[max(0, best_pos - 100):best_pos].strip()
        for pattern, desc, weight in _HOOK_END_PATTERNS:
            if re.search(pattern, end_segment):
                confidence += weight
                reasons.append(desc)
                break

        # 检查场景转换
        next_segment = text[best_pos:min(best_pos + 100, len(text))]
        for pattern, desc, weight in _SCENE_BREAK_PATTERNS:
            if re.search(pattern, next_segment):
                confidence += weight
                reasons.append(f"下一段是{desc}")
                break

        # 生成建议标题（取第一句或用序号）
        suggested_title = _suggest_title(text, current_pos, best_pos, len(split_points) + 1)

        split_points.append(SplitPoint(
            position=best_pos,
            suggested_title=suggested_title,
            reason="、".join(reasons) if reasons else "字数分段",
            confidence=min(confidence, 1.0),
            end_of_paragraph=is_para_end,
        ))

        current_pos = best_pos
        target_pos = current_pos + target_chars

    return split_points


def _suggest_title(text: str, start: int, end: int, chapter_num: int) -> str:
    """根据内容生成建议章节标题。"""
    segment = text[start:end].strip()
    # 取第一句话（前 30 字）
    first_line = segment.split('\n', 1)[0].strip()
    if len(first_line) > 30:
        first_line = first_line[:30] + "…"
    if first_line:
        return f"第{chapter_num}章 {first_line}"
    return f"第{chapter_num}章"


# ────────────────────── 执行拆章 ──────────────────────

def split_unit(
    unit_id: str,
    split_points: list[SplitPoint],
    *,
    book_id: str,
    start_chapter_no: int = 1,
    custom_titles: Optional[list[str]] = None,
) -> SplitResult:
    """
    执行拆章，创建章节并迁移数据。

    - unit_id: 单元 ID
    - split_points: 断章点列表
    - book_id: 拆到哪本书
    - start_chapter_no: 起始章节号
    - custom_titles: 自定义标题列表（可选）

    返回 SplitResult
    """
    unit = story_unit_service.get(unit_id)
    if not unit.draft:
        raise ValidationError("单元草稿为空")
    if unit.status == "split":
        raise ValidationError("该单元已经拆过了")

    text = unit.draft
    total_len = len(text)

    # 生成章节切片
    segments: list[tuple[int, int]] = []
    prev_pos = 0
    for sp in split_points:
        segments.append((prev_pos, sp.position))
        prev_pos = sp.position
    if prev_pos < total_len:
        segments.append((prev_pos, total_len))

    # 创建章节
    result = SplitResult(unit_id=unit_id)

    for i, (seg_start, seg_end) in enumerate(segments):
        chap_num = start_chapter_no + i
        content = text[seg_start:seg_end].strip()
        if not content:
            continue

        # 取标题
        if custom_titles and i < len(custom_titles) and custom_titles[i]:
            title = custom_titles[i]
        elif i < len(split_points):
            title = split_points[i].suggested_title
        else:
            title = f"第{chap_num}章"

        # 创建章节（绑定来源单元）
        chap_dict = create_chapter(
            book_id=book_id,
            chapter_no=chap_num,
            title=title,
            status="draft",
            source_unit_id=unit_id,
            split_version=1,
            is_current_version=1,
        )

        # 创建章节草稿（内容）
        from app.services.chapter_service import create_draft
        draft_dict = create_draft(
            chapter_id=chap_dict["id"],
            content=content,
            source="manual",
        )

        result.chapters.append({
            "id": chap_dict["id"],
            "title": chap_dict.get("title", ""),
            "chapter_no": chap_dict.get("chapter_no", chap_num),
            "word_count": len(content),
        })

    # 标记单元为已拆章
    story_unit_service.update(unit_id, status="split")

    result.total_chapters = len(result.chapters)

    _logger.info(
        "拆章完成: 单元 %s → %d 章, 起始章号 %d",
        unit_id, result.total_chapters, start_chapter_no,
    )
    return result


# ────────────────────── 预览 ──────────────────────

def preview_split(
    unit_id: str,
    split_points: list[SplitPoint],
) -> list[dict]:
    """
    预览拆章效果，不实际创建章节。
    返回每章的标题、字数、开头、结尾。
    """
    unit = story_unit_service.get(unit_id)
    if not unit.draft:
        raise ValidationError("单元草稿为空")

    text = unit.draft
    total_len = len(text)

    segments: list[tuple[int, int]] = []
    prev_pos = 0
    for sp in split_points:
        segments.append((prev_pos, sp.position))
        prev_pos = sp.position
    if prev_pos < total_len:
        segments.append((prev_pos, total_len))

    result = []
    for i, (seg_start, seg_end) in enumerate(segments):
        content = text[seg_start:seg_end].strip()
        word_count = len(content)
        preview_start = content[:80].replace('\n', ' ')
        preview_end = content[-80:].replace('\n', ' ')

        sp_info = {}
        if i < len(split_points):
            sp = split_points[i]
            sp_info = {
                "confidence": sp.confidence,
                "reason": sp.reason,
            }

        result.append({
            "index": i + 1,
            "suggested_title": split_points[i].suggested_title if i < len(split_points) else f"第{i+1}章",
            "word_count": word_count,
            "preview_start": preview_start + ("…" if len(content) > 80 else ""),
            "preview_end": ("…" if len(content) > 80 else "") + preview_end,
            "split_point": sp_info,
        })

    return result


# ────────────────────── 导出 ──────────────────────

__all__ = [
    "SplitPoint", "SplitResult",
    "analyze_split_points", "split_unit", "preview_split",
]
