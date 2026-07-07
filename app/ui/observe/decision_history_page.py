"""
决策历史页 (v4.0)

显示 Decision 记录, 表格形式: 单元 / 引导 / 动作 / 原因.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QHBoxLayout, QPushButton,
)
from app.ui.theme import text_muted


class DecisionHistoryPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project_id: str = ""
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("\u51b3\u7b56\u5386\u53f2")
        title.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #cdd6f4;"
        )
        layout.addWidget(title)

        subtitle = QLabel("AI \u5bf9 Guide \u7684\u91c7\u7eb3/\u5ffd\u7565/\u4fee\u6539\u8bb0\u5f55 (\u53ef\u89e3\u91ca AI)")
        subtitle.setStyleSheet(f"color: {text_muted()}; font-size: 12px;")
        layout.addWidget(subtitle)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_row.addWidget(QLabel("\u6309\u52a8\u4f5c\u7b5b\u9009:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["\u5168\u90e8", "\u5df2\u91c7\u7eb3", "\u5df2\u5ffd\u7565", "\u5df2\u4fee\u6539"])
        self._filter_combo.currentTextChanged.connect(self._reload)
        filter_row.addWidget(self._filter_combo)
        filter_row.addStretch(1)

        refresh_btn = QPushButton("\U0001f504 \u5237\u65b0")
        refresh_btn.setStyleSheet(
            "QPushButton { background: #45475a; color: #cdd6f4; border: none; "
            "border-radius: 4px; padding: 4px 12px; }"
            "QPushButton:hover { background: #585b70; }"
        )
        refresh_btn.clicked.connect(self._reload)
        filter_row.addWidget(refresh_btn)
        layout.addLayout(filter_row)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([
            "\u5f15\u5bfc\u6765\u6e90", "\u52a8\u4f5c", "\u539f\u56e0", "\u51b3\u7b56\u65f6\u95f4", "\u5355\u5143"
        ])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setStyleSheet(
            "QTableWidget { background: #1e1e2e; border: 1px solid #313244; "
            "gridline-color: #313244; color: #cdd6f4; }"
            "QTableWidget::item:selected { background: #45475a; }"
            "QHeaderView::section { background: #11111b; color: #a6adc8; "
            "border: none; padding: 6px; font-weight: 600; }"
        )
        layout.addWidget(self._table, 1)

    def set_project(self, project: dict) -> None:
        self._project_id = project.get("id", "")
        self._reload()

    def _reload(self) -> None:
        self._table.setRowCount(0)
        if not self._project_id:
            return

        try:
            from app.services.decision_service import list_for_project
            decisions = list_for_project(self._project_id)
        except Exception:
            decisions = []

        action_map = {"\u5168\u90e8": "all", "\u5df2\u91c7\u7eb3": "adopted", "\u5df2\u5ffd\u7565": "ignored", "\u5df2\u4fee\u6539": "modified"}
        filt_text = self._filter_combo.currentText()
        filt = action_map.get(filt_text, "all")
        if filt != "all":
            decisions = [d for d in decisions if d.action == filt]

        action_labels = {"adopted": "\u2714 \u91c7\u7eb3", "ignored": "\u2716 \u5ffd\u7565", "modified": "\u270f \u4fee\u6539"}

        self._table.setRowCount(len(decisions))
        for i, d in enumerate(decisions):
            self._table.setItem(i, 0, QTableWidgetItem(d.guide_source))
            self._table.setItem(i, 1, QTableWidgetItem(action_labels.get(d.action, d.action)))
            self._table.setItem(i, 2, QTableWidgetItem(d.reason[:80] if d.reason else ""))
            self._table.setItem(i, 3, QTableWidgetItem(d.decided_at))
            self._table.setItem(i, 4, QTableWidgetItem(d.unit_id[:8]))
