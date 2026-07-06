"""
app/workflow/edit_signals/collector.py

EditSignalCollector - 3 埋点入口 (§4.1).

埋点 1: ingest_regen / ingest_regen_result  (regen 按钮回调)
埋点 2: ingest_manual_edit  (textChanged 30s 防抖后)
埋点 3: ingest_discard  (段落删除检测)

所有入口都是**同步**落盘 (Layer 1), 不阻塞主线程
(Layer 2 封存 + Layer 3 聚类 + Layer 4 进化 由 worker.py 后台 thread 处理).
"""
from __future__ import annotations
import logging
import threading
import time
from typing import Optional

from .models import EditSignal, SignalKind
from .jsonl_store import JSONLStore, get_project_dir

_logger = logging.getLogger("NovelWriter.edit_signals.collector")


class EditSignalCollector:
    """3 埋点 + 章节封存 (§3.3 / §4)."""

    def __init__(self, project_id, store: Optional[JSONLStore] = None):
        self.project_id = project_id
        self.project_dir = get_project_dir(project_id)
        self.store = store or JSONLStore(self.project_dir)
        self._current_chapter_id: Optional[str] = None
        self._pending_chapter: Optional[str] = None
        self._lock = threading.Lock()

    # ── 埋点 1: regen 按钮 ──

    def ingest_regen(
        self,
        chapter_id,
        paragraph_index: int,
        before_text: str,
        instruction: str = "",
    ) -> None:
        """regen 前调用: 旧文本=被拒样本 (accepted=False 暂存)."""
        sig = EditSignal(
            kind=SignalKind.REGEN,
            chapter_id=chapter_id,
            payload={
                "paragraph_index": int(paragraph_index),
                "before": before_text or "",
                "after": "",          # regen 完成后会 patch
                "instruction": instruction or "",
                "accepted": False,     # 暂存
            },
            project_id=self.project_id,
        )
        try:
            self.store.append_to_active(sig)
        except Exception as e:
            _logger.warning("ingest_regen 落盘失败: %s", e)

    def ingest_regen_result(
        self,
        chapter_id,
        paragraph_index: int,
        after_text: str,
        accepted: bool,
    ) -> None:
        """regen 后调用: 标记接受/放弃 (改写 before 的 accepted 字段)."""
        sig = EditSignal(
            kind=SignalKind.REGEN,
            chapter_id=chapter_id,
            payload={
                "paragraph_index": int(paragraph_index),
                "before": "",         # 不重复 before
                "after": after_text or "",
                "accepted": bool(accepted),
                "is_result": True,     # 标记: 这是 result, 不是 initial
            },
            project_id=self.project_id,
        )
        try:
            self.store.append_to_active(sig)
        except Exception as e:
            _logger.warning("ingest_regen_result 落盘失败: %s", e)

    # ── 埋点 2: 手动编辑 ──

    def ingest_manual_edit(
        self,
        chapter_id,
        before: str,
        after: str,
    ) -> None:
        """textChanged 30s 防抖后调用 (§4.1 埋点 2)."""
        if before == after:
            return
        sig = EditSignal(
            kind=SignalKind.MANUAL_EDIT,
            chapter_id=chapter_id,
            payload={
                "before": before or "",
                "after": after or "",
            },
            project_id=self.project_id,
        )
        try:
            self.store.append_to_active(sig)
        except Exception as e:
            _logger.warning("ingest_manual_edit 落盘失败: %s", e)

    # ── 埋点 3: 段落删除 ──

    def ingest_discard(
        self,
        chapter_id,
        paragraph_index: int,
        content: str,
    ) -> None:
        """段落删除检测后调用 (段落 ≥ 50 字)."""
        if not content or len(content.strip()) < 50:
            return
        sig = EditSignal(
            kind=SignalKind.DISCARD,
            chapter_id=chapter_id,
            payload={
                "paragraph_index": int(paragraph_index),
                "content": content,
                "before": content,    # 反例聚合用
            },
            project_id=self.project_id,
        )
        try:
            self.store.append_to_active(sig)
        except Exception as e:
            _logger.warning("ingest_discard 落盘失败: %s", e)

    # ── Layer 2: 章节封存 ──

    def on_chapter_save(self, chapter_id) -> int:
        """章节保存即封存 (§3.3).

        Returns: 封存的信号条数
        """
        with self._lock:
            self._current_chapter_id = chapter_id
        try:
            count = self.store.commit_chapter(chapter_id)
        except Exception as e:
            _logger.warning("章节封存失败: %s", e)
            return 0
        return count

    def on_chapter_switch(self, new_chapter_id) -> int:
        """章节切换: 不封存 (COMMIT_ON=save 默认), 仅切 current."""
        with self._lock:
            self._current_chapter_id = str(new_chapter_id)
        return 0

    def manual_commit(self, chapter_id) -> int:
        """手动 [封存本章] 按钮."""
        return self.on_chapter_save(chapter_id)

    # ── 便捷 ──

    def is_meaningful_diff(self, before: str, after: str, *, min_chars: int = 10) -> bool:
        """判断 diff 是否值得记录 (改 ≥ 10 字, 防 typo 噪声)."""
        if not before or not after or before == after:
            return False
        diff_chars = sum(b - a for _, a, b, _ in _diff_opcodes(before, after) if _ != "equal")
        return diff_chars >= min_chars

    def detect_paragraph_discard(self, old: str, new: str) -> list[tuple[int, str]]:
        """检测哪些段落被整段清空 (返回 [(paragraph_index, content)]).

        调用方拿到后调 ingest_discard.
        """
        out: list[tuple[int, str]] = []
        old_paras = _split_paragraphs(old)
        new_paras = _split_paragraphs(new)
        for i, p in enumerate(old_paras):
            if i >= len(new_paras) or not new_paras[i].strip():
                if len(p.strip()) > 50:
                    out.append((i, p))
        return out


# ────────────────────── 工具函数 ──────────────────────

import difflib


def _diff_opcodes(before: str, after: str) -> list[tuple]:
    return list(difflib.SequenceMatcher(None, before, after).get_opcodes())


def _split_paragraphs(text: str) -> list[str]:
    """按空行 / \n 切段落."""
    if not text:
        return []
    out: list[str] = []
    for chunk in text.split("\n\n"):
        if not chunk.strip():
            continue
        for line in chunk.split("\n"):
            if line.strip():
                out.append(line)
    return out
