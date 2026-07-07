"""
Debouncer — UI 线程防抖工具 (性能优化通用件)

用于合并高频连续触发的事件 (如 QTextEdit.textChanged 每键一次),
仅在静默 interval_ms 后执行最后一次回调, 避免每次输入都做重算导致 UI 卡顿。

典型用法:
    self._d = Debouncer(300, self)
    self._d.triggered.connect(self._on_settled)
    self._editor.textChanged.connect(self._d.call)
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal


class Debouncer(QObject):
    """合并连续触发的回调, 仅在静默 interval_ms 后执行最后一次."""

    triggered = Signal()

    def __init__(self, interval_ms: int = 300, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._interval = max(0, int(interval_ms))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)

    def call(self, *args, **kwargs) -> None:
        """记录一次触发意图 (参数忽略, 由消费方在 fired 时自取最新状态)."""
        self._timer.stop()
        self._timer.start(self._interval)

    def _fire(self) -> None:
        self.triggered.emit()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def active(self) -> bool:
        return self._timer.isActive()
