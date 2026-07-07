"""
I16 SplitterHelper - 分割条 + 比例保存.

设计参考 docs/widgets-mockup.html I16 (2026-06-10 批准).

特性:
- 包装 QSplitter, 自动记录/恢复各面板比例
- 比例基于 total width 实时计算, 与绝对像素无关
- 持久化键: 提供 save/load 接口 (与 app_setting_service 配合)
- 移动信号 splitterMoved 触发比例重算
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSplitter, QWidget


class SplitterHelper:
    """分割条比例助手. 不直接继承 QSplitter, 持有 splitter 实例."""

    ratioChanged = Signal(list)  # List[float], 各面板比例 (和=1)

    def __init__(
        self,
        splitter: QSplitter,
        *,
        key: Optional[str] = None,
        min_ratio: float = 0.05,
    ) -> None:
        self._splitter = splitter
        self._key = key
        self._min_ratio = min_ratio
        self._suppress = False
        splitter.splitterMoved.connect(self._on_moved)
        # 监听子 widget 增删 (不能直接监听, 但 addWidget / setSizes 是手工入口)

    # ---- 公开 API ----
    def key(self) -> Optional[str]:
        return self._key

    def set_key(self, key: str) -> None:
        self._key = key

    def current_ratios(self) -> List[float]:
        """返回各面板比例 (和=1)."""
        sizes = self._splitter.sizes()
        total = sum(sizes) or 1
        return [s / total for s in sizes]

    def apply_ratios(self, ratios: Sequence[float]) -> None:
        """应用比例. 总和不必为 1, 自动归一化."""
        if not ratios:
            return
        total_widget = self._splitter.width() or 1
        # 归一化
        s = sum(ratios) or 1
        norm = [r / s for r in ratios]
        sizes = [max(int(total_widget * r), int(self._splitter.handleWidth() or 4)) for r in norm]
        # 修正: 最后一个 = total - sum(前n-1) 避免舍入误差
        if len(sizes) >= 2:
            sizes[-1] = max(total_widget - sum(sizes[:-1]), int(self._splitter.handleWidth() or 4))
        self._suppress = True
        try:
            self._splitter.setSizes(sizes)
        finally:
            self._suppress = False

    def save_ratios(self) -> str:
        """导出当前比例为 JSON 字符串 (供设置服务持久化)."""
        import json
        return json.dumps(self.current_ratios(), ensure_ascii=False)

    def load_ratios(self, blob: str) -> bool:
        """从 JSON 字符串恢复比例."""
        import json
        try:
            ratios = json.loads(blob)
            if not isinstance(ratios, list) or not ratios:
                return False
            self.apply_ratios([float(r) for r in ratios])
            return True
        except (ValueError, TypeError):
            return False

    def splitter(self) -> QSplitter:
        return self._splitter

    # ---- 内部 ----
    def _on_moved(self, _pos: int, _index: int) -> None:
        if self._suppress:
            return
        self.ratioChanged.emit(self.current_ratios())
