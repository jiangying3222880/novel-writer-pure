"""
单元池 Tab (M5 / WS5)
- 容纳 UnitPoolWidget, 转发 set_project。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout

from app.ui.widgets.unit_pool_widget import UnitPoolWidget


class UnitPoolTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._widget = UnitPoolWidget()
        outer.addWidget(self._widget)

    def set_project(self, project) -> None:
        self._widget.set_project(project)

    @property
    def widget(self) -> UnitPoolWidget:
        return self._widget
