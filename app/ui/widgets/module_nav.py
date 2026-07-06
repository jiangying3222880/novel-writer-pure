"""
Module Navigation Widget (v4.0)

4 个一级模块按钮, 对应 Story / Create / Observe / Publish.
支持键盘快捷键 Ctrl+1/2/3/4.

v4.0 patch: 移除硬编码暗色 QSS, 改用 objectName 走全局主题 QSS.
v4.0 patch: 移除死代码 _update_styles().
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QSizePolicy, QLabel,
)


MODULES = [
    ("story", "📖 故事", "故事设计", "Ctrl+1"),
    ("create", "✍ 创作", "创作", "Ctrl+2"),
    ("observe", "👁 观察", "理解故事", "Ctrl+3"),
    ("publish", "🚀 发布", "发布", "Ctrl+4"),
]

PAGE_MAP = {
    "story": {
        "book": ("小说设定", "novel-settings"),
        "outline": ("大纲管理", "outline-mgmt"),
        "characters": ("角色管理", "character-mgmt"),
        "world": ("世界观", "worldview"),
    },
    "create": {
        "current": ("当前创作", "generate"),
        "unit": ("故事单元", "story-unit"),
        "editor": ("项目管理", "projects"),
        "signals": ("自动进化", "edit-signals"),
    },
    "observe": {
        "health": ("故事健康", "dashboard"),
        "graph": ("世界图谱", "world-graph"),
        "analytics": ("用量分析", "usage-analytics"),
        "knowledge": ("知识库", "knowledge"),
    },
    "publish": {
        "export": ("导出", "export"),
        "model": ("模型配置", "model"),
        "appearance": ("外观", "appearance"),
    },
}

SUB_PAGE_LABELS = {
    "story": {
        "book": "小说设定",
        "outline": "大纲管理",
        "characters": "角色管理",
        "world": "世界观",
    },
    "create": {
        "current": "当前创作",
        "unit": "故事单元",
        "editor": "单元库",
        "signals": "自动进化",
    },
    "observe": {
        "health": "故事健康",
        "graph": "世界图谱",
        "analytics": "用量分析",
        "knowledge": "知识库",
    },
    "publish": {
        "export": "章节预览",
        "model": "AI 模型",
        "appearance": "外观",
    },
}


class ModuleNav(QWidget):
    module_selected = Signal(str)           # module_id
    page_selected = Signal(str)             # page_id
    sub_page_selected = Signal(str, str)    # (module_id, sub_page_id)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._current_module: str = "create"
        self._expanded = True
        self._active_sub: str = "current"
        self._build()

    def _build(self) -> None:
        self.setFixedWidth(220)
        # v4.0 patch: 移除硬编码暗色 QSS, 背景由 parent #sidebar QSS 管理.
        self.setObjectName("moduleNav")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # v4.0 patch: title 文字色走 objectName (sidebarHeader 由全局 QSS 定义).
        title = QLabel("  Novel Writer Pure")
        title.setObjectName("sidebarHeader")
        outer.addWidget(title)

        version = QLabel("  v4.0  故事引擎")
        version.setObjectName("sidebarFooter")
        outer.addWidget(version)

        self._btn_layout = QVBoxLayout()
        self._btn_layout.setContentsMargins(6, 4, 6, 4)
        self._btn_layout.setSpacing(3)
        outer.addLayout(self._btn_layout)

        self._module_btns: dict[str, QPushButton] = {}
        btn_font = QFont()
        btn_font.setPointSize(11)

        for mod_id, icon_text, hint, shortcut in MODULES:
            btn = QPushButton(f"  {icon_text}")
            btn.setFont(btn_font)
            # v4.0 patch: objectName 走全局主题 QSS (theme.py #navBtn).
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIconSize(QSize(20, 20))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setMinimumHeight(38)
            # v4.0 patch: 确保事件不被吞
            btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            btn.setToolTip(f"{hint} ({shortcut})")
            btn.clicked.connect(lambda checked, mid=mod_id: self.select_module(mid))
            self._btn_layout.addWidget(btn)
            self._module_btns[mod_id] = btn

        outer.addStretch(1)

    def select_module(self, module_id: str) -> None:
        if module_id in self._module_btns:
            for mid, btn in self._module_btns.items():
                btn.setChecked(mid == module_id)
            self._current_module = module_id
            self.module_selected.emit(module_id)
            first_sub = list(PAGE_MAP[module_id].keys())[0]
            self.sub_page_selected.emit(module_id, first_sub)

    def set_active_sub(self, module_id: str, sub_id: str) -> None:
        self._active_sub = sub_id
        self._current_module = module_id
        if module_id in self._module_btns:
            for mid, btn in self._module_btns.items():
                btn.setChecked(mid == module_id)
            self.module_selected.emit(module_id)

    def get_page_id(self, module_id: str, sub_id: str) -> str:
        pages = PAGE_MAP.get(module_id, {})
        for sid, (label, page_id) in pages.items():
            if sid == sub_id:
                return page_id
        for sid, (label, page_id) in pages.items():
            return page_id
        return "generate"

    @property
    def current_module(self) -> str:
        return self._current_module
