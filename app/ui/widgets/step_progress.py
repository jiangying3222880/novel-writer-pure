"""
StepProgressWidget — 写作管线进度面板

展示每个步骤的执行状态，支持手动/自动模式切换。
手动模式: 每步可编辑文本，用户确认后继续。
自动模式: 自动执行，仅关键问题暂停。
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFrame, QScrollArea, QProgressBar,
)

log = logging.getLogger(__name__)


class StepItem(QFrame):
    """单个步骤的展示项."""

    def __init__(self, step_no: int, label: str, parent=None) -> None:
        super().__init__(parent)
        self.step_no = step_no
        self.setObjectName("stepItem")
        self.setStyleSheet(
            "QFrame#stepItem { background: #1e293b; border: 1px solid #334155; "
            "border-radius: 6px; padding: 8px; margin: 2px 0; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # 标题行
        header = QHBoxLayout()
        self.status_label = QLabel("⏳")
        self.status_label.setFixedWidth(20)
        header.addWidget(self.status_label)

        self.title_label = QLabel(f"Step {step_no}: {label}")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        header.addWidget(self.title_label, 1)

        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        header.addWidget(self.detail_label)
        layout.addLayout(header)

        # 可编辑文本区
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setMaximumHeight(120)
        self.text_edit.setStyleSheet(
            "QTextEdit { background: #0f172a; border: 1px solid #1e293b; "
            "border-radius: 4px; color: #e2e8f0; font-size: 12px; padding: 6px; }"
        )
        self.text_edit.setVisible(False)
        layout.addWidget(self.text_edit)

    def set_running(self) -> None:
        self.status_label.setText("⏳")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #eab308;")

    def set_done(self, detail: str = "") -> None:
        self.status_label.setText("✅")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #22c55e;")
        self.detail_label.setText(detail)

    def set_error(self, detail: str = "") -> None:
        self.status_label.setText("❌")
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #ef4444;")
        self.detail_label.setText(detail)

    def set_content(self, text: str, editable: bool = False) -> None:
        self.text_edit.setPlainText(text)
        self.text_edit.setVisible(bool(text))
        self.text_edit.setReadOnly(not editable)

    def get_content(self) -> str:
        return self.text_edit.toPlainText()


class StepProgressWidget(QWidget):
    """写作管线进度面板.

    手动模式: 每步展示文本，可编辑，用户确认后继续。
    自动模式: 自动执行，仅关键问题暂停。

    Signals:
        step_confirmed(int, str)  — 用户确认某步，传 (step_no, edited_text)
        step_paused()             — 用户暂停
        pipeline_finished()       — 管线完成
    """

    step_confirmed = Signal(int, str)
    step_paused = Signal()
    pipeline_finished = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mode: str = "auto"  # "auto" or "manual"
        self._items: dict[int, StepItem] = {}
        self._build_ui()
        self._subscribe_events()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 模式切换
        mode_frame = QFrame()
        mode_frame.setStyleSheet(
            "QFrame { background: #1e293b; border-bottom: 1px solid #334155; padding: 8px; }"
        )
        mode_layout = QHBoxLayout(mode_frame)
        mode_layout.setContentsMargins(12, 8, 12, 8)

        mode_label = QLabel("创作模式:")
        mode_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        mode_layout.addWidget(mode_label)

        self.btn_auto = QPushButton("⚡ 自动")
        self.btn_auto.setCheckable(True)
        self.btn_auto.setChecked(True)
        self.btn_auto.clicked.connect(lambda: self._set_mode("auto"))
        mode_layout.addWidget(self.btn_auto)

        self.btn_manual = QPushButton("✋ 手动")
        self.btn_manual.setCheckable(True)
        self.btn_manual.clicked.connect(lambda: self._set_mode("manual"))
        mode_layout.addWidget(self.btn_manual)

        mode_layout.addStretch(1)
        layout.addWidget(mode_frame)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background: #1e293b; border: none; height: 4px; }"
            "QProgressBar::chunk { background: #6366f1; }"
        )
        layout.addWidget(self.progress_bar)

        # 步骤列表 (可滚动)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.steps_widget = QWidget()
        self.steps_layout = QVBoxLayout(self.steps_widget)
        self.steps_layout.setContentsMargins(0, 0, 0, 0)
        self.steps_layout.setSpacing(0)
        self.steps_layout.addStretch()
        scroll.setWidget(self.steps_widget)
        layout.addWidget(scroll, 1)

        # 底部操作按钮
        btn_frame = QFrame()
        btn_frame.setStyleSheet(
            "QFrame { background: #1e293b; border-top: 1px solid #334155; padding: 8px; }"
        )
        btn_layout = QHBoxLayout(btn_frame)
        btn_layout.setContentsMargins(12, 8, 12, 8)

        self.btn_continue = QPushButton("继续")
        self.btn_continue.setStyleSheet(
            "QPushButton { background: #6366f1; color: white; padding: 8px 16px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #818cf8; }"
        )
        self.btn_continue.clicked.connect(self._on_continue)
        btn_layout.addWidget(self.btn_continue)

        self.btn_save_continue = QPushButton("保存并继续")
        self.btn_save_continue.setStyleSheet(
            "QPushButton { background: #22c55e; color: white; padding: 8px 16px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #4ade80; }"
        )
        self.btn_save_continue.clicked.connect(self._on_save_continue)
        btn_layout.addWidget(self.btn_save_continue)

        self.btn_pause = QPushButton("暂停")
        self.btn_pause.clicked.connect(self._on_pause)
        btn_layout.addWidget(self.btn_pause)

        self.btn_retry = QPushButton("重做这步")
        self.btn_retry.clicked.connect(self._on_retry)
        btn_layout.addWidget(self.btn_retry)

        btn_layout.addStretch(1)
        layout.addWidget(btn_frame)

        # 初始状态: 自动模式下隐藏操作按钮
        self._update_buttons()

    def _subscribe_events(self) -> None:
        """订阅 EventBus 的 story.step.completed 事件."""
        try:
            from app.core.event_bus import get_bus, Events
            bus = get_bus()
            bus.subscribe(Events.STORY_STEP_COMPLETED, self._on_step_event)
        except Exception:
            pass

    def _on_step_event(self, event) -> None:
        """收到步骤完成事件."""
        data = event.data if hasattr(event, "data") else event
        step = data.get("step", 0)
        label = data.get("label", "")
        detail = data.get("detail", "")

        self._add_step(step, label, detail)
        self._update_progress(step)

    def _add_step(self, step_no: int, label: str, detail: str = "") -> None:
        """添加一个步骤到列表."""
        item = StepItem(step_no, label)
        item.set_done(detail)
        self._items[step_no] = item

        # 插入到 stretch 之前
        self.steps_layout.insertWidget(self.steps_layout.count() - 1, item)

        # 自动模式下显示内容
        if self._mode == "auto" and detail:
            item.set_content(detail, editable=False)

        # 滚动到最新
        self.steps_layout.parentWidget().parentWidget().ensureWidgetVisible(item)

    def _update_progress(self, current_step: int) -> None:
        """更新进度条."""
        total = max(len(self._items), 1)
        pct = int(current_step / total * 100) if total > 0 else 0
        self.progress_bar.setValue(min(pct, 100))

    def _set_mode(self, mode: str) -> None:
        """切换模式."""
        self._mode = mode
        self.btn_auto.setChecked(mode == "auto")
        self.btn_manual.setChecked(mode == "manual")
        self._update_buttons()

    def _update_buttons(self) -> None:
        """根据模式更新按钮状态."""
        is_manual = self._mode == "manual"
        self.btn_continue.setVisible(is_manual)
        self.btn_save_continue.setVisible(is_manual)
        self.btn_pause.setVisible(True)
        self.btn_retry.setVisible(is_manual)

    def _on_continue(self) -> None:
        """继续: 用当前内容."""
        last_step = max(self._items.keys()) if self._items else 0
        item = self._items.get(last_step)
        text = item.get_content() if item else ""
        self.step_confirmed.emit(last_step, text)

    def _on_save_continue(self) -> None:
        """保存并继续: 保存编辑内容后继续."""
        last_step = max(self._items.keys()) if self._items else 0
        item = self._items.get(last_step)
        text = item.get_content() if item else ""
        self.step_confirmed.emit(last_step, text)

    def _on_pause(self) -> None:
        """暂停."""
        self.step_paused.emit()

    def _on_retry(self) -> None:
        """重做当前步骤."""
        last_step = max(self._items.keys()) if self._items else 0
        item = self._items.get(last_step)
        if item:
            item.set_running()
            item.set_content("", editable=False)

    def clear(self) -> None:
        """清空所有步骤."""
        while self.steps_layout.count() > 1:
            child = self.steps_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._items.clear()
        self.progress_bar.setValue(0)
