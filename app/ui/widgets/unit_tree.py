"""
Unit Tree Widget (v4.0)

显示 Story Unit 列表 (卷 → Unit), 替代旧章节树.
"""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, QPushButton,
    QHBoxLayout,
)


class UnitTree(QWidget):
    unit_selected = Signal(str)       # unit_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project_id: str = ""
        self._units: list = []
        self._build()

    def _build(self) -> None:
        self.setMinimumWidth(200)
        self.setMaximumWidth(300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("\U0001f4d6 \u6545\u4e8b\u5355\u5143")
        from app.ui.theme import score_value
        title.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {score_value()};")
        header.addWidget(title)
        header.addStretch(1)
        new_btn = QPushButton("+")
        new_btn.setFixedSize(24, 24)
        new_btn.setToolTip("\u65b0\u5efa\u5355\u5143")
        new_btn.setStyleSheet(
            "QPushButton { background: #45475a; border: none; border-radius: 4px; "
            "color: #cdd6f4; font-size: 14px; }"
            "QPushButton:hover { background: #585b70; }"
        )
        header.addWidget(new_btn)
        layout.addLayout(header)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(16)
        self._tree.setStyleSheet(
            "QTreeWidget { background: #1e1e2e; border: 1px solid #313244; "
            "border-radius: 4px; }"
            "QTreeWidget::item { padding: 3px 6px; color: #a6adc8; }"
            "QTreeWidget::item:selected { background: #45475a; color: #cdd6f4; }"
        )
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree, 1)

    def set_project(self, project_id: str) -> None:
        self._project_id = project_id
        self._reload()

    def _reload(self) -> None:
        self._tree.clear()
        if not self._project_id:
            empty = QTreeWidgetItem(self._tree)
            empty.setText(0, "(\u65e0\u9879\u76ee)")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            return

        try:
            from app.services import story_unit_service_v2 as _unit_svc
            self._units = _unit_svc.list_for_project(self._project_id) or []
        except Exception:
            self._units = []

        if not self._units:
            empty = QTreeWidgetItem(self._tree)
            empty.setText(0, "(\u65e0\u5355\u5143)")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            return

        for u in self._units:
            item = QTreeWidgetItem(self._tree)
            title = getattr(u, "title", "") or u.id[:8]
            item.setText(0, f"U{getattr(u, 'unit_no', '?')}  {title}")
            item.setData(0, Qt.ItemDataRole.UserRole, u.id)
            item.setToolTip(0, f"\u5355\u5143 {getattr(u, 'unit_no', '?')}: {title}")

    def _on_item_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        uid = item.data(0, Qt.ItemDataRole.UserRole)
        if uid:
            self.unit_selected.emit(uid)
