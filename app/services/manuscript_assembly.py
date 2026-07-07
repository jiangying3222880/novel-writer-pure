"""
Manuscript Assembly (v4.0 发布成稿核心)

正确领域流程 (用户确认, 纠正了旧的「1单元拆多章」方向):
  1. 选 >=2 个单元, 按时间线 (story_order / present_order) 拼接合并
     - 线性(story): 按 story_order 顺序
     - 非线性(present): 按 present_order 重排, 过渡用倒叙/插叙 标注
  2. 合并后确认目标章节字数
  3. 在字数目标附近找情绪点 (emotion_analyzer.generate_split_report)
  4. 用户确认断章点
  5. 断章后基于章节内容推荐 3 个标题 (LLM / 本地规则 fallback)
  6. 每个单元有 unit_no 唯一编号, 章节单元级溯源 (unit_spans)

溯源粒度: 段落级标签 -> 聚合为章节级单元集合 (unit_spans JSON).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

from app.services import story_unit_service_v2 as usvc
from app.services import chapter_service
from app.services.emotion_analyzer import generate_split_report, SplitReport
from app.db import connection


@dataclass
class UnitSegment:
    """拼接稿件中的一个段落, 带来源单元标签."""
    unit_id: str
    unit_no: int           # 单元唯一编号
    text: str
    char_start: int        # 在 merged_text 中的起止
    char_end: int


@dataclass
class AssembledManuscript:
    merged_text: str = ""
    segments: list[UnitSegment] = field(default_factory=list)
    units: list = field(default_factory=list)        # StoryUnitV2 列表
    book_id: str = ""
    project_id: str = ""
    timeline_mode: str = "story"
    transitions: list = field(default_factory=list)  # [{unit_id, unit_no, type, note}]


def assemble_units(
    project_id: str,
    unit_ids: list[str],
    timeline_mode: str = "story",
) -> AssembledManuscript:
    """多单元拼接合并成完整稿件 (段落级打 unit_no 标签, 双时间线决定过渡).

    timeline_mode:
      "story"  -> 按 story_order 线性拼接
      "present"-> 按 present_order 重排, 标注倒叙/插叙过渡
    """
    units = []
    for uid in unit_ids:
        try:
            u = usvc.get(uid)
            if u:
                units.append(u)
        except Exception:
            continue
    if not units:
        return AssembledManuscript(merged_text="", units=[], book_id="",
                                    project_id=project_id, timeline_mode=timeline_mode)

    if timeline_mode == "present":
        units.sort(key=lambda u: (u.present_order or 0))
    else:
        units.sort(key=lambda u: (u.story_order or 0))

    segments: list[UnitSegment] = []
    parts: list[str] = []
    pos = 0
    transitions: list[dict] = []
    prev_unit = None

    for u in units:
        draft = (u.draft or "").strip()
        if not draft:
            continue
        # 非线性: 与上一单元 story_order 比较 -> 倒叙/插叙
        if timeline_mode == "present" and prev_unit is not None:
            su, pu = (u.story_order or 0), (prev_unit.story_order or 0)
            if su < pu:
                transitions.append({"unit_id": u.id, "unit_no": u.unit_no,
                                    "type": "flashback", "note": "倒叙插入"})
            elif su > pu:
                transitions.append({"unit_id": u.id, "unit_no": u.unit_no,
                                    "type": "flashforward", "note": "插叙/预叙"})
        for p in re.split(r"\n+", draft):
            p = p.strip()
            if not p:
                continue
            if parts:
                parts.append("\n")          # 段间换行
                pos += 1
            start = pos
            parts.append(p)
            end = pos + len(p)
            segments.append(UnitSegment(unit_id=u.id, unit_no=u.unit_no,
                                        text=p, char_start=start, char_end=end))
            pos = end
        prev_unit = u

    merged = "".join(parts)
    book_id = units[0].book_id or ""
    return AssembledManuscript(
        merged_text=merged, segments=segments, units=units,
        book_id=book_id, project_id=project_id,
        timeline_mode=timeline_mode, transitions=transitions,
    )


def compute_split_points(
    merged_text: str,
    target_chars: int = 1500,
    strategy: str = "auto",
) -> SplitReport:
    """在字数目标附近找情绪点断章. 复用 emotion_analyzer."""
    return generate_split_report(merged_text, strategy, target_chars)


def split_manuscript(merged_text: str, split_points: list[int]) -> list[tuple[int, int]]:
    """按断章位置切成章节区间 [(start, end), ...] (不含首尾清理)."""
    if not merged_text:
        return []
    pts = sorted({int(p) for p in split_points if 0 < p < len(merged_text)})
    ranges: list[tuple[int, int]] = []
    prev = 0
    for p in pts:
        ranges.append((prev, p))
        prev = p
    ranges.append((prev, len(merged_text)))
    return ranges


def chapter_source_units(
    start: int, end: int, segments: list[UnitSegment]
) -> list[dict]:
    """计算某章区间内覆盖的单元集合 (单元级溯源)."""
    units: dict[str, int] = {}
    for seg in segments:
        if seg.char_end > start and seg.char_start < end:
            units[seg.unit_id] = seg.unit_no
    return [{"unit_id": uid, "unit_no": uno} for uid, uno in units.items()]


def recommend_titles(chapter_text: str, n: int = 3) -> list[str]:
    """推荐 n 个章节标题. 有 LLM key 走模型, 失败/无 key 走本地规则."""
    text = (chapter_text or "").strip()
    if not text:
        return [f"第{i+1}章" for i in range(n)]
    # 1) 尝试 LLM
    try:
        from app.ai.engine import get_engine
        eng = get_engine()
        prompt = (
            f"你是一位网文编辑。请为下面这段章节内容起 {n} 个风格不同、"
            "吸引人的章节标题（每个不超过15字）。\n"
            "只返回标题，每行一个，不要序号、不要解释、不要引号。\n\n"
            f"章节内容：\n{text[:2000]}"
        )
        resp = eng.chat([{"role": "user", "content": prompt}],
                        task="title", max_tokens=200)
        raw = resp.content
        # 清洗推理模型的 <think>...</think> 块 (部分模型会在正文前返回思考链)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
        lines = [ln.strip().lstrip("0123456789.、）).、- ") for ln in raw.splitlines()]
        titles = [ln for ln in lines if ln][:n]
        if len(titles) >= 2:
            return titles
    except Exception:
        pass
    # 2) 本地规则 fallback
    return _local_titles(text, n)


def _local_titles(chapter_text: str, n: int = 3) -> list[str]:
    first_line = chapter_text.strip().split("\n")[0][:18]
    keywords = ["觉醒", "危机", "真相", "抉择", "归来", "决战", "谜团", "重逢",
                "背叛", "血战", "伏笔", "终局"]
    found = [k for k in keywords if k in chapter_text]
    base = first_line or "未命名章节"
    candidates = [
        base,
        f"第{len(found)+1}章 · {found[0] if found else '波澜'}",
        f"暗流 · {base[:10]}",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for t in candidates:
        if t not in seen:
            seen.add(t)
            out.append(t)
    while len(out) < n:
        out.append(f"第{len(out)+1}章")
    return out[:n]


def persist_chapters(
    book_id: str,
    chapters_data: list[dict],
) -> list[str]:
    """落库章节. chapters_data: [{text, title, unit_spans, source_units}, ...].

    返回新章节 id 列表. unit_spans 为单元级溯源 JSON 数组.
    """
    ids: list[str] = []
    conn = connection.get_conn()
    for i, ch in enumerate(chapters_data, start=1):
        text = ch.get("text", "")
        title = ch.get("title") or f"第{i}章"
        spans = ch.get("unit_spans", [])
        source_units = ch.get("source_units", [])
        rec = chapter_service.create(book_id=book_id, chapter_no=i, title=title, status="draft")
        cid = rec["id"]
        chapter_service.update(cid, draft=text, final=text, word_count=len(text))
        conn.execute(
            "UPDATE chapters SET unit_spans=?, source_unit_id=? WHERE id=?",
            (json.dumps(spans, ensure_ascii=False),
             source_units[0] if source_units else "", cid),
        )
        ids.append(cid)
    return ids
