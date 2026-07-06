"""
MainWindow v4 — 主窗口

简化版主窗口，包含基本导航和 HUD 页面。
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QSplitter,
)
from PySide6.QtCore import Qt
from app.ui.theme_v4 import get_theme_v4


class MainWindow(QMainWindow):
    """v4 主窗口."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("小说写作助手 v4.0")
        self.resize(1440, 900)
        self._build()

    def _build(self):
        tokens = get_theme_v4().tokens

        central = QWidget()
        central.setStyleSheet(f"background-color: {tokens.background};")
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 左侧导航
        nav = QWidget()
        nav.setFixedWidth(200)
        nav.setStyleSheet(f"background-color: #181825;")
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(12, 12, 12, 12)

        # 导航标题
        title = QLabel("小说写作助手")
        title.setStyleSheet(f"color: {tokens.text}; font-size: 16px; font-weight: bold; padding: 8px;")
        nav_layout.addWidget(title)

        # 导航按钮
        self._nav_buttons = []
        pages = [("dashboard", "仪表盘"), ("hud", "故事HUD"), ("settings", "设置")]
        self._page_stack = QStackedWidget()

        for page_id, label in pages:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(f"""
                QPushButton {{
                    color: {tokens.text_secondary}; background: transparent; border: none;
                    text-align: left; padding: 10px 12px; font-size: 13px;
                    border-radius: 6px;
                }}
                QPushButton:hover {{ background: {tokens.surface}; color: {tokens.text}; }}
                QPushButton:checked {{ background: {tokens.primary}; color: {tokens.background}; font-weight: bold; }}
            """)
            btn.clicked.connect(lambda checked, pid=page_id: self._select_page(pid))
            nav_layout.addWidget(btn)
            self._nav_buttons.append((page_id, btn))

        nav_layout.addStretch()
        layout.addWidget(nav)

        # 右侧内容
        content = QWidget()
        content.setStyleSheet(f"background-color: {tokens.background};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # 页面栈
        self._pages = {}

        # 仪表盘页面
        dashboard = QWidget()
        dashboard.setStyleSheet(f"background-color: {tokens.background};")
        dash_layout = QVBoxLayout(dashboard)
        dash_label = QLabel("仪表盘 — 项目概览")
        dash_label.setStyleSheet(f"color: {tokens.text}; font-size: 20px; font-weight: bold; padding: 20px;")
        dash_layout.addWidget(dash_label)
        dash_layout.addStretch()
        self._pages["dashboard"] = dashboard
        self._page_stack.addWidget(dashboard)

        # HUD 页面
        try:
            from app.ui.tabs.hud_tab import HUDTab
            hud = HUDTab()
            self._pages["hud"] = hud
            self._page_stack.addWidget(hud)
        except Exception:
            hud_placeholder = QLabel("HUD 页面加载中...")
            hud_placeholder.setStyleSheet(f"color: {tokens.text}; padding: 20px;")
            self._pages["hud"] = hud_placeholder
            self._page_stack.addWidget(hud_placeholder)

        # 设置页面
        settings = QLabel("设置页面")
        settings.setStyleSheet(f"color: {tokens.text}; padding: 20px;")
        self._pages["settings"] = settings
        self._page_stack.addWidget(settings)

        content_layout.addWidget(self._page_stack)
        layout.addWidget(content, 1)

        # 默认选中仪表盘
        self._select_page("dashboard")

    def _select_page(self, page_id: str):
        if page_id in self._pages:
            self._page_stack.setCurrentWidget(self._pages[page_id])
            for pid, btn in self._nav_buttons:
                btn.setChecked(pid == page_id)
