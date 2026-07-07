"""
Unit Editor Widget (v4.0)

显示/编辑 StoryUnit 的核心信息 + 生成按钮.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QGroupBox, QProgressBar, QCheckBox,
)


class UnitEditor(QWidget):
    generate_requested = Signal(str, bool)  # unit_id, use_v4_pipeline
    export_requested = Signal(str)         # unit_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._unit_id: str = ""
        self._unit: Optional[object] = None
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._title_label = QLabel("\u8bf7\u9009\u62e9\u5355\u5143")
        self._title_label.setStyleSheet(
            "font-size: 18px; font-weight: 700; color: #cdd6f4; padding: 4px 0;"
        )
        layout.addWidget(self._title_label)

        info = QGroupBox("\u5355\u5143\u4fe1\u606f")
        il = QVBoxLayout(info)
        il.setSpacing(4)
        self._goal_label = QLabel("")
        self._goal_label.setWordWrap(True)
        from app.ui.theme import text_meta
        self._goal_label.setStyleSheet(f"color: {text_meta()}; font-size: 12px;")
        il.addWidget(self._goal_label)
        from app.ui.theme import text_meta
        self._conflict_label = QLabel("")
        self._conflict_label.setWordWrap(True)
        self._conflict_label.setStyleSheet(f"color: {text_meta()}; font-size: 12px;")
        il.addWidget(self._conflict_label)
        self._twist_label = QLabel("")
        self._twist_label.setWordWrap(True)
        self._twist_label.setStyleSheet(f"color: {text_meta()}; font-size: 12px;")
        il.addWidget(self._twist_label)
        self._exit_label = QLabel("")
        self._exit_label.setWordWrap(True)
        self._exit_label.setStyleSheet(f"color: {text_meta()}; font-size: 12px;")
        il.addWidget(self._exit_label)
        layout.addWidget(info)

        self._content_editor = QPlainTextEdit()
        self._content_editor.setPlaceholderText("\u5355\u5143\u5185\u5bb9\u5c06\u663e\u793a\u5728\u8fd9\u91cc...")
        self._content_editor.setStyleSheet(
            "QPlainTextEdit { background: #1e1e2e; color: #cdd6f4; "
            "border: 1px solid #313244; border-radius: 4px; padding: 8px; "
            "font-size: 14px; }"
        )
        layout.addWidget(self._content_editor, 1)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._gen_btn = QPushButton("\u270d \u751f\u6210")
        self._gen_btn.setMinimumHeight(36)
        self._gen_btn.setStyleSheet(
            "QPushButton { background: #89b4fa; color: #1e1e2e; border: none; "
            "border-radius: 6px; font-size: 13px; font-weight: 700; padding: 0 24px; }"
            "QPushButton:hover { background: #b4d0fb; }"
            "QPushButton:disabled { background: #45475a; color: #585b70; }"
        )
        self._gen_btn.clicked.connect(self._on_generate)
        btn_row.addWidget(self._gen_btn)

        self._v4_chk = QCheckBox("v4")
        self._v4_chk.setToolTip("v4 Story OS 全链路 (State→Signals→Decision→Prompt)")
        self._v4_chk.setStyleSheet("QCheckBox { color: #a6adc8; font-size: 11px; }")
        btn_row.addWidget(self._v4_chk)

        self._export_btn = QPushButton("\U0001f4e4 \u5bfc\u51fa\u7ae0\u8282")
        self._export_btn.setMinimumHeight(36)
        self._export_btn.setStyleSheet(
            "QPushButton { background: #45475a; color: #cdd6f4; border: none; "
            "border-radius: 6px; font-size: 13px; padding: 0 16px; }"
            "QPushButton:hover { background: #585b70; }"
        )
        self._export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(self._export_btn)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def set_unit(self, unit_id: str) -> None:
        self._unit_id = unit_id
        try:
            from app.services import story_unit_service_v2 as _unit_svc
            self._unit = _unit_svc.get(unit_id)
        except Exception:
            self._unit = None

        if self._unit is None:
            self._title_label.setText("\u672a\u627e\u5230\u5355\u5143")
            self._goal_label.setText("")
            self._conflict_label.setText("")
            self._twist_label.setText("")
            self._exit_label.setText("")
            self._content_editor.setPlainText("")
            self._gen_btn.setEnabled(False)
            self._export_btn.setEnabled(False)
            return

        u = self._unit
        self._title_label.setText(
            f"\u5355\u5143 {getattr(u, 'unit_no', '?')}  {getattr(u, 'title', '')}"
        )
        self._goal_label.setText(
            f"\U0001f3af \u76ee\u6807: {getattr(u, 'unit_goal', '') or '(\u65e0)'}"
        )
        self._conflict_label.setText(
            f"\u26a1 \u51b2\u7a81: {getattr(u, 'unit_conflict', '') or '(\u65e0)'}"
        )
        self._twist_label.setText(
            f"\U0001f500 \u8f6c\u6298: {getattr(u, 'narrative_twist', '') or '(\u65e0)'}"
        )
        self._exit_label.setText(
            f"\U0001f6aa \u51fa\u53e3: {getattr(u, 'exit_summary', '') or '(\u65e0)'}"
        )

        try:
            from app.services import story_unit_service_v2 as _unit_svc
            draft = _unit_svc.get_draft(unit_id)
            self._content_editor.setPlainText(draft or "")
        except Exception:
            self._content_editor.setPlainText("")

        self._gen_btn.setEnabled(True)
        self._export_btn.setEnabled(True)

    def set_content(self, text: str) -> None:
        self._content_editor.setPlainText(text)

    def set_progress(self, value: int, visible: bool = True) -> None:
        self._progress.setValue(value)
        self._progress.setVisible(visible)

    def _on_generate(self) -> None:
        if self._unit_id:
            self.generate_requested.emit(self._unit_id, self._v4_chk.isChecked())

    def _on_export(self) -> None:
        if self._unit_id:
            self.export_requested.emit(self._unit_id)
