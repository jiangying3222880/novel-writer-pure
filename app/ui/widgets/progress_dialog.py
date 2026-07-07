"""
I22 ProgressDialog - 进度条弹窗.

设计参考 docs/widgets-mockup.html I22 (2026-06-10 批准).

特性:
- 标题 + 当前步骤名 + 进度条
- 步骤切换: set_step(index) / set_step_name(name)
- 进度: 0..1
- 统计: tokens_used, elapsed_ms, eta_ms (可只填部分)
- 取消按钮 (可选)
- finish(success) / fail(message) 终止

使用:
    dlg = ProgressDialog("生成章节", steps=["拼装记忆", "反AI", "压力", "检索", "写手", "评估", "落库"])
    dlg.set_step(0)
    dlg.set_progress(0.05)
    ...
    dlg.finish(True)
    dlg.exec()
"""
from __future__ import annotations

import time
from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from app.ui.theme import text_muted


class ProgressDialog(QDialog):
    """进度条弹窗 (非模态: 默认 show, 不阻塞调用)."""

    cancelled = Signal()
    finished_with_result = Signal(bool)  # True=成功, False=失败

    def __init__(
        self,
        title: str,
        steps: Optional[List[str]] = None,
        *,
        cancellable: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)  # 非模态, 调用方可继续更新
        self.setMinimumWidth(480)
        self._steps = steps or []
        self._step_index = 0
        self._progress = 0.0
        self._cancellable = cancellable
        self._cancelled = False
        self._finished = False
        self._t0 = time.time()
        self._auto_close_timer: Optional[QTimer] = None

        self.setStyleSheet(
            "QDialog { background: #0f1011; }"
            "QFrame#pdHeader { background: #0a0b0d; border-bottom: 1px solid #2a2b2f; }"
            "QFrame#pdFooter { background: #0a0b0d; border-top: 1px solid #2a2b2f; }"
            "QLabel#pdTitle { color: #f0f1f2; font-size: 14px; font-weight: 600; }"
            "QLabel#pdStep { color: #6c7ae0; font-weight: 600; }"
            "QLabel#pdStats { color: #8a8f98; font-size: 11px; }"
            "QLabel#pdStats .label { color: #6c7ae0; }"
            "QProgressBar { background: #191a1b; border: 1px solid #2a2b2f; border-radius: 4px; height: 16px; text-align: center; color: #c8cdd4; }"
            "QProgressBar::chunk { background: #6c7ae0; border-radius: 3px; }"
            "QPushButton { background: #191a1b; color: #f0f1f2; border: 1px solid #2a2b2f; border-radius: 4px; padding: 6px 14px; font-size: 13px; }"
            "QPushButton:hover { background: #222326; }"
        )

        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame(self)
        header.setObjectName("pdHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 12, 16, 12)
        self._title_label = QLabel("⚙ 处理中...", header)
        self._title_label.setObjectName("pdTitle")
        h.addWidget(self._title_label)
        layout.addWidget(header)

        # Body
        body = QWidget(self)
        b = QVBoxLayout(body)
        b.setContentsMargins(16, 14, 16, 14)
        b.setSpacing(8)

        step_row = QHBoxLayout()
        step_row.setSpacing(8)
        self._current_step = QLabel("—", body)
        self._current_step.setObjectName("pdStep")
        self._step_total = QLabel("", body)
        self._step_total.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        step_row.addWidget(self._current_step)
        step_row.addWidget(self._step_total)
        step_row.addStretch(1)
        b.addLayout(step_row)

        self._bar = QProgressBar(body)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        b.addWidget(self._bar)

        # 统计行
        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)
        self._elapsed_label = QLabel("用时: 0.0s", body)
        self._elapsed_label.setObjectName("pdStats")
        self._eta_label = QLabel("剩余: —", body)
        self._eta_label.setObjectName("pdStats")
        self._tokens_label = QLabel("Tokens: 0", body)
        self._tokens_label.setObjectName("pdStats")
        stats_row.addWidget(self._elapsed_label)
        stats_row.addWidget(self._eta_label)
        stats_row.addWidget(self._tokens_label)
        stats_row.addStretch(1)
        b.addLayout(stats_row)

        layout.addWidget(body, 1)

        # Footer
        footer = QFrame(self)
        footer.setObjectName("pdFooter")
        footer.setAttribute(Qt.WA_StyledBackground, True)
        f = QHBoxLayout(footer)
        f.setContentsMargins(16, 10, 16, 10)
        f.addStretch(1)
        self._cancel_btn = QPushButton("取消", footer)
        self._cancel_btn.setEnabled(self._cancellable)
        self._cancel_btn.clicked.connect(self._on_cancel)
        f.addWidget(self._cancel_btn)
        self._close_btn = QPushButton("关闭", footer)
        self._close_btn.setVisible(False)
        self._close_btn.clicked.connect(self.accept)
        f.addWidget(self._close_btn)
        layout.addWidget(footer)

        # 定时刷新 elapsed
        self._tick = QTimer(self)
        self._tick.setInterval(200)
        self._tick.timeout.connect(self._refresh_elapsed)
        self._tick.start()

    # ---- 公开 API ----
    def set_step(self, index: int) -> None:
        if 0 <= index < len(self._steps):
            self._step_index = index
        elif index >= len(self._steps) and self._steps:
            self._step_index = len(self._steps) - 1
        self._refresh()

    def set_step_name(self, name: str) -> None:
        # 临时覆盖: 推入到自定义
        if not hasattr(self, "_custom_name"):
            self._custom_name = None
        self._custom_name = name
        self._current_step.setText(name or "—")

    def set_progress(self, ratio: float) -> None:
        self._progress = max(0.0, min(1.0, ratio))
        self._bar.setValue(int(self._progress * 100))
        self._refresh_eta()

    def set_tokens_used(self, n: int) -> None:
        self._tokens_label.setText(f"Tokens: {n:,}")

    def set_eta_ms(self, ms: int) -> None:
        if ms is None or ms < 0:
            self._eta_label.setText("剩余: —")
        else:
            self._eta_label.setText(f"剩余: {ms / 1000:.1f}s")

    def finish(self, success: bool = True, message: str = "") -> None:
        if self._finished:
            return
        self._finished = True
        self._tick.stop()
        if success:
            self._title_label.setText("✓ 完成")
            self._bar.setValue(100)
            self._current_step.setText(message or "已完成")
        else:
            self._title_label.setText("✗ 失败")
            self._current_step.setText(message or "处理失败")
        self._cancel_btn.setVisible(False)
        self._close_btn.setVisible(True)
        self.finished_with_result.emit(success)
        # 2.5s 后自动关闭 (不强制)
        self._auto_close_timer = QTimer(self)
        self._auto_close_timer.setSingleShot(True)
        self._auto_close_timer.timeout.connect(self.accept)
        self._auto_close_timer.start(2500)

    def is_cancelled(self) -> bool:
        return self._cancelled

    def elapsed_ms(self) -> int:
        return int((time.time() - self._t0) * 1000)

    # ---- 内部 ----
    def _refresh(self) -> None:
        if self._steps and 0 <= self._step_index < len(self._steps):
            self._current_step.setText(self._steps[self._step_index])
        elif not self._steps:
            self._current_step.setText("—")
        if self._steps:
            self._step_total.setText(f"步骤 {self._step_index + 1} / {len(self._steps)}")
        else:
            self._step_total.setText("")
        if len(self._steps) > 0:
            step_ratio = (self._step_index + 0.5) / len(self._steps)
            auto_progress = max(self._progress, step_ratio)
            self._bar.setValue(int(auto_progress * 100))
            self._progress = auto_progress

    def _refresh_elapsed(self) -> None:
        self._elapsed_label.setText(f"用时: {self.elapsed_ms() / 1000:.1f}s")
        self._refresh_eta()

    def _refresh_eta(self) -> None:
        if self._progress < 0.01:
            return
        elapsed = self.elapsed_ms()
        total_est = int(elapsed / self._progress)
        eta = max(total_est - elapsed, 0)
        self._eta_label.setText(f"剩余: {eta / 1000:.1f}s")

    def _on_cancel(self) -> None:
        if self._finished:
            return
        self._cancelled = True
        self._tick.stop()
        self._title_label.setText("⏸ 已取消")
        self._cancel_btn.setEnabled(False)
        self._close_btn.setVisible(True)
        self.cancelled.emit()
        self.finished_with_result.emit(False)
