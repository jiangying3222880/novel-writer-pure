"""
Theme v4 — 设计令牌系统

基于令牌的颜色系统，支持深色/浅色主题切换。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class ThemeTokens:
    """主题令牌."""
    # 颜色
    primary: str = "#89b4fa"
    secondary: str = "#a6adc8"
    background: str = "#1e1e2e"
    surface: str = "#313244"
    text: str = "#cdd6f4"
    text_secondary: str = "#a6adc8"
    text_muted: str = "#585b70"
    border: str = "#45475a"
    error: str = "#f38ba8"
    warning: str = "#fab387"
    success: str = "#a6e3a1"

    # 间距
    spacing_xs: int = 4
    spacing_sm: int = 8
    spacing_md: int = 12
    spacing_lg: int = 16
    spacing_xl: int = 24

    # 字体
    font_caption: int = 11
    font_body: int = 13
    font_heading: int = 16
    font_title: int = 20


# 深色主题
DARK_TOKENS = ThemeTokens()

# 浅色主题
LIGHT_TOKENS = ThemeTokens(
    primary="#1e66f5",
    secondary="#6c6f85",
    background="#eff1f5",
    surface="#ccd0da",
    text="#4c4f69",
    text_secondary="#6c6f85",
    text_muted="#9ca0b0",
    border="#bcc0cc",
    error="#d20f39",
    warning="#df8e1d",
    success="#40a02b",
)


class ThemeManagerV4(QObject):
    """v4 主题管理器."""
    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._current = "dark"
        self._tokens = DARK_TOKENS

    @property
    def tokens(self) -> ThemeTokens:
        return self._tokens

    @property
    def current(self) -> str:
        return self._current

    def apply(self, app: QApplication, theme: str = "dark") -> None:
        """应用主题."""
        if theme not in ("dark", "light"):
            theme = "dark"

        self._current = theme
        self._tokens = DARK_TOKENS if theme == "dark" else LIGHT_TOKENS

        # 生成 QSS
        qss = self._generate_qss()
        app.setStyleSheet(qss)

        self.changed.emit(theme)

    def _generate_qss(self) -> str:
        """生成 QSS 样式表."""
        t = self._tokens
        return f"""
        QWidget {{
            background-color: {t.background};
            color: {t.text};
            font-size: {t.font_body}px;
        }}
        QLabel {{
            color: {t.text};
        }}
        QPushButton {{
            background-color: {t.primary};
            color: {t.background};
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {t.secondary};
        }}
        QPushButton:disabled {{
            background-color: {t.surface};
            color: {t.text_muted};
        }}
        QLineEdit, QTextEdit, QPlainTextEdit {{
            background-color: {t.surface};
            color: {t.text};
            border: 1px solid {t.border};
            border-radius: 4px;
            padding: 8px;
        }}
        QGroupBox {{
            border: 1px solid {t.border};
            border-radius: 6px;
            margin-top: 12px;
            padding-top: 16px;
            font-weight: bold;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
        }}
        QTabWidget::pane {{
            border: 1px solid {t.border};
            border-radius: 6px;
        }}
        QTabBar::tab {{
            background-color: {t.surface};
            color: {t.text_secondary};
            padding: 8px 16px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
        }}
        QTabBar::tab:selected {{
            background-color: {t.primary};
            color: {t.background};
        }}
        QScrollBar:vertical {{
            background-color: {t.background};
            width: 10px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {t.border};
            border-radius: 5px;
            min-height: 20px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        """


# 全局单例
_manager: Optional[ThemeManagerV4] = None


def get_theme_v4() -> ThemeManagerV4:
    global _manager
    if _manager is None:
        _manager = ThemeManagerV4()
    return _manager
