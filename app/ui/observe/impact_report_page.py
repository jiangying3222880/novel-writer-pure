"""
影响分析页 (v4.0)

显示 Story Compiler 影响分析结果.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea, QGroupBox,
    QPushButton,
)
from app.ui.theme import score_value, text_danger, text_muted, text_warn_ok


class ImpactReportPage(QWidget):
    unit_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project_id: str = ""
        self._unit_id: str = ""
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("\u5f71\u54cd\u5206\u6790")
        title.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #cdd6f4;"
        )
        layout.addWidget(title)

        subtitle = QLabel(
            "\u4fee\u6539 Unit \u2192 \u5f71\u54cd\u5206\u6790 "
            "(4 \u7ef4\u5ea6: \u5165\u53e3\u7ee7\u627f / \u94a9\u5b50\u4f9d\u8d56 / \u4e8b\u4ef6\u7ea7\u8054 / \u89d2\u8272\u72b6\u6001)"
        )
        subtitle.setStyleSheet(f"color: {text_muted()}; font-size: 12px; word-wrap: true;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(8)

        scroll.setWidget(self._content)
        layout.addWidget(scroll, 1)

    def set_project(self, project: dict) -> None:
        self._project_id = project.get("id", "")

    def set_unit(self, unit_id: str) -> None:
        self._unit_id = unit_id
        self._refresh()

    def _refresh(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self._unit_id:
            empty = QLabel("\u8bf7\u9009\u62e9\u5355\u5143\u4ee5\u67e5\u770b\u5f71\u54cd\u5206\u6790\u3002")
            empty.setStyleSheet(f"color: {text_muted()}; font-style: italic; padding: 20px;")
            self._content_layout.addWidget(empty)
            return

        try:
            from app.services.story_compiler import analyze_impact
            report = analyze_impact(self._unit_id)
        except Exception as e:
            err = QLabel(f"\u9519\u8bef: {e}")
            err.setStyleSheet(f"color: {text_danger()}; padding: 20px;")
            self._content_layout.addWidget(err)
            return

        if not report.has_impact:
            ok = QLabel("\u672a\u68c0\u6d4b\u5230\u53d7\u5f71\u54cd\u7684\u5355\u5143\u3002 \u2705")
            ok.setStyleSheet(f"color: {text_warn_ok()}; font-weight: 600; padding: 20px;")
            self._content_layout.addWidget(ok)
            self._content_layout.addStretch(1)
            return

        summary = QLabel(
            f"\u4fee\u6539 {report.unit_title or self._unit_id[:8]} "
            f"\u2192 {len(report.impacted_units)} \u4e2a\u5355\u5143\u53ef\u80fd\u53d7\u5f71\u54cd"
        )
        summary.setStyleSheet(f"color: {score_value()}; font-weight: 600; padding: 8px 0;")
        self._content_layout.addWidget(summary)

        type_labels = {
            "exit_inherit": "\U0001f4e4 \u5165\u53e3\u72b6\u6001\u7ee7\u627f",
            "hook_depend": "\U0001f3a3 \u94a9\u5b50\u4f9d\u8d56",
            "event_cascade": "\U0001f4cb \u4e8b\u4ef6\u7ea7\u8054",
            "character_state": "\U0001f464 \u89d2\u8272\u72b6\u6001\u540c\u6b65",
        }

        for impact_type, units in sorted(report.by_type.items()):
            gb = QGroupBox(type_labels.get(impact_type, impact_type))
            gb.setStyleSheet(
                "QGroupBox { background: #1e1e2e; border: 1px solid #313244; "
                "border-radius: 4px; margin-top: 8px; padding-top: 14px; "
                "color: #a6adc8; font-weight: 600; }"
            )
            gl = QVBoxLayout(gb)
            gl.setContentsMargins(10, 6, 10, 8)
            gl.setSpacing(4)

            for u in units:
                label_text = f"\u5355\u5143 {u.unit_id[:8]} {u.title}"
                if u.reason:
                    label_text += f" \u2014 {u.reason}"
                row = QPushButton(label_text)
                row.setFlat(True)
                row.setStyleSheet(
                    "QPushButton { text-align: left; color: #a6adc8; font-size: 12px; "
                    "border: none; padding: 4px 8px; border-radius: 4px; }"
                    "QPushButton:hover { background: #313244; color: #cdd6f4; }"
                )
                row.clicked.connect(lambda checked, uid=u.unit_id: self.unit_selected.emit(uid))
                gl.addWidget(row)

            self._content_layout.addWidget(gb)

        self._content_layout.addStretch(1)
