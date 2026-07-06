"""
Chapter Exporter（v3.5.1+ work-4）

Unit → Chapter 导出器 + preview() 干跑模式.

设计原则：
- 章节只是 Render，不是创作单位
- 同一 Unit 可按不同平台导出不同分章
- preview() 只看不写，让 UI 在导出前看到切章位置

API:
  - ChapterExporter.preview(unit_id, target_chars=2500) -> list[ChapterPreview]
  - ChapterExporter.export_from_unit(unit_id, book_id, strategy, target_chars)
  - ChapterExporter.export_for_platform(chapters, platform)
  - ChapterExporter.rebuild_from_unit(unit_id, book_id, target_chars, min_chars, max_chars)

v5 微调 3：preview() 干跑模式，避免 Scene 腰斩（番茄 2500 字一刀切）.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.services import story_unit_service_v2 as _unit_svc
from app.services import unit_paragraph_service as _para_svc
from app.services import chapter_service as _chap_svc
from app.services import unit_chapter_mapper as _mapper
from app.services.exceptions import NotFoundError, ValidationError

_logger = logging.getLogger("NovelWriter.exporter.chapter")


# ============================================================
# 平台字数目标
# ============================================================

PLATFORM_WORD_TARGETS = {
    "fanqie": 2500,       # 番茄
    "qidian": 4000,       # 起点
    "webnovel": 1800,     # WebNovel (海外)
    "jinjiang": 3000,     # 晋江
}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ChapterPreview:
    """预览: 一章的渲染前状态."""
    chapter_no: int
    title: str
    paragraph_range: tuple[int, int]  # (start_idx, end_idx)
    paragraph_ids: list[str]
    estimated_chars: int
    is_truncated: bool = False
    truncation_warning: str = ""

    def to_dict(self) -> dict:
        return {
            "chapter_no": self.chapter_no,
            "title": self.title,
            "start_para_idx": self.paragraph_range[0],
            "end_para_idx": self.paragraph_range[1],
            "paragraph_ids": self.paragraph_ids,
            "estimated_chars": self.estimated_chars,
            "is_truncated": self.is_truncated,
            "truncation_warning": self.truncation_warning,
        }


# ============================================================
# ChapterExporter
# ============================================================

class ChapterExporter:
    """章节导出器.

    使用:
      exporter = ChapterExporter()
      previews = exporter.preview(unit_id, target_chars=2500)
      # UI 显示 previews, 用户确认后:
      chapters = exporter.export_from_unit(unit_id, book_id, strategy="auto_split", target_chars=2500)
    """

    # 默认策略参数
    DEFAULT_TARGET_CHARS = 3000
    DEFAULT_MIN_CHARS = 2000
    DEFAULT_MAX_CHARS = 4000

    def preview(
        self,
        unit_id: str,
        *,
        target_chars: int = DEFAULT_TARGET_CHARS,
        min_chars: int = DEFAULT_MIN_CHARS,
        max_chars: Optional[int] = None,
    ) -> list[ChapterPreview]:
        """预览切章位置，不写库.

        Returns:
            list[ChapterPreview] - 每章的段落范围 + 字数估算 + truncation 警告
        """
        max_chars = max_chars or int(target_chars * 1.5)
        unit = _unit_svc.get(unit_id)
        paragraphs = _para_svc.list_for_unit(unit_id)
        if not paragraphs:
            raise ValidationError("Unit has no paragraphs")

        specs = self._compute_chapter_specs(
            paragraphs, target_chars, min_chars, max_chars,
        )

        previews = []
        for i, (s, e) in enumerate(specs):
            chapter_paras = paragraphs[s:e + 1]
            paragraph_ids = [p.id for p in chapter_paras]
            estimated_chars = sum(len(p.text) for p in chapter_paras)

            is_truncated = False
            warning = ""

            if estimated_chars < min_chars:
                is_truncated = True
                warning = (
                    f"本章仅 {estimated_chars} 字，低于 min_chars={min_chars}。"
                    f" 可能是 Unit 内容不足以填充一章，或目标字数偏大。"
                )

            if e == len(paragraphs) - 1 and i == len(specs) - 1:
                last_chars = estimated_chars
                if last_chars > max_chars:
                    is_truncated = True
                    warning = (
                        f"末章 {last_chars} 字，超过 max_chars={max_chars}。"
                        f" 建议拆分或在末段前手动切章。"
                    )

            title = unit.title if i == 0 else f"{unit.title} (续)"
            previews.append(ChapterPreview(
                chapter_no=i + 1,
                title=title,
                paragraph_range=(s, e),
                paragraph_ids=paragraph_ids,
                estimated_chars=estimated_chars,
                is_truncated=is_truncated,
                truncation_warning=warning,
            ))

        total_chars = sum(p.estimated_chars for p in previews)
        truncated_count = sum(1 for p in previews if p.is_truncated)
        _logger.info(
            "preview unit=%s: %d chapters, %d chars total, %d truncated",
            unit_id, len(previews), total_chars, truncated_count,
        )
        return previews

    def export_from_unit(
        self,
        unit_id: str,
        book_id: str,
        *,
        strategy: str = "auto_split",
        target_chars: int = DEFAULT_TARGET_CHARS,
        min_chars: Optional[int] = None,
        max_chars: Optional[int] = None,
        start_chapter_no: int = 1,
    ) -> list[dict]:
        """从 Unit 导出章节，写入 chapters 表.

        Args:
            strategy: "auto_split" | "manual" | "whole"
            - auto_split: 按 target_chars 自动拆章
            - manual: 暂未实现 (留给 UI 选段)
            - whole: 整个 Unit 作为一章

        Returns:
            list[dict] - 创建的 chapter dict 列表
        """
        min_chars = min_chars or max(1000, target_chars - 1000)
        max_chars = max_chars or int(target_chars * 1.5)

        unit = _unit_svc.get(unit_id)
        if not unit:
            raise NotFoundError("StoryUnitV2", unit_id)

        if strategy == "whole":
            paragraphs = _para_svc.list_for_unit(unit_id)
            if not paragraphs:
                raise ValidationError("Unit has no paragraphs")
            specs = [{"title": unit.title, "start_para_idx": 0, "end_para_idx": len(paragraphs) - 1}]
        else:
            paragraphs = _para_svc.list_for_unit(unit_id)
            if not paragraphs:
                raise ValidationError("Unit has no paragraphs")
            raw_specs = self._compute_chapter_specs(
                paragraphs, target_chars, min_chars, max_chars,
            )
            specs = [
                {"title": unit.title if i == 0 else f"{unit.title} (续)",
                 "start_para_idx": s, "end_para_idx": e}
                for i, (s, e) in enumerate(raw_specs)
            ]

        created = _mapper.map_unit_to_chapters(
            unit_id, specs,
            book_id=book_id,
            start_chapter_no=start_chapter_no,
        )
        _logger.info(
            "export unit=%s strategy=%s target=%d → %d chapters",
            unit_id, strategy, target_chars, len(created),
        )
        return created

    def export_for_platform(
        self,
        unit_id: str,
        book_id: str,
        platform: str,
        *,
        start_chapter_no: int = 1,
    ) -> list[dict]:
        """按平台字数要求重新分章.

        Args:
            platform: "fanqie" | "qidian" | "webnovel" | "jinjiang"
        """
        if platform not in PLATFORM_WORD_TARGETS:
            raise ValidationError(
                f"Unknown platform: {platform}. Valid: {list(PLATFORM_WORD_TARGETS.keys())}"
            )
        target = PLATFORM_WORD_TARGETS[platform]
        return self.export_from_unit(
            unit_id, book_id,
            strategy="auto_split",
            target_chars=target,
            start_chapter_no=start_chapter_no,
        )

    def rebuild_from_unit(
        self,
        unit_id: str,
        book_id: str,
        *,
        target_chars: int = DEFAULT_TARGET_CHARS,
        min_chars: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> list[dict]:
        """删除 Unit 已有章节并重新导出."""
        min_chars = min_chars or max(1000, target_chars - 1000)
        max_chars = max_chars or int(target_chars * 1.5)

        existing = _mapper.get_chapters_for_unit(unit_id)
        for chap in existing:
            try:
                _chap_svc.delete(chap["id"])
            except Exception as e:
                _logger.warning("删除 chapter %s 失败: %s", chap["id"], e)

        return _mapper.rebuild_chapters_from_unit(
            unit_id, book_id,
            target_chars=target_chars,
            min_chars=min_chars,
            max_chars=max_chars,
        )

    # ----------------- 内部：拆章算法 ----------------- #

    def _compute_chapter_specs(
        self,
        paragraphs: list,
        target_chars: int,
        min_chars: int,
        max_chars: int,
    ) -> list[tuple[int, int]]:
        """按段落边界计算拆章点 (start_idx, end_idx) 列表.

        策略：
          - 累积段落字数到 target_chars 附近 → 在段落边界断开
          - 超过 max_chars 强制断开
          - 末段单独成章（如果够 min_chars）或合并到最后一段
        """
        if not paragraphs:
            return []

        specs = []
        current_start = 0
        current_chars = 0

        for i, para in enumerate(paragraphs):
            para_len = len(para.text)
            current_chars += para_len + 2  # +2 for \n\n

            should_break = False
            if current_chars >= target_chars and i < len(paragraphs) - 1:
                should_break = True
            elif current_chars >= max_chars:
                should_break = True
            elif i == len(paragraphs) - 1 and current_chars > min_chars:
                should_break = True

            if should_break and current_chars >= min_chars:
                specs.append((current_start, i))
                current_start = i + 1
                current_chars = 0

        if current_start < len(paragraphs):
            specs.append((current_start, len(paragraphs) - 1))

        if not specs:
            specs = [(0, len(paragraphs) - 1)]

        return specs