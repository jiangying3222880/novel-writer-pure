"""
I5 ColorPalette - 颜色面板 + 主题切换辅助.

设计参考 docs/widgets-mockup.html I5 (2026-06-10 批准).

特性:
- 8 主色色板, 单选
- 选中态视觉强调 (双层边框)
- 悬停时显示 hex 提示
- colorSelected 信号
- 配套 ThemeToggle (暗/亮切换) - 直接调用 ThemeManager
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import ThemeManager, ThemeName, text_muted


@dataclass(frozen=True)
class PaletteEntry:
    hex: str
    name: str


# 主色 8 色 + 名称. 与 mockup 完全一致.
DEFAULT_PALETTE: List[PaletteEntry] = [
    PaletteEntry("#6c7ae0", "主蓝"),
    PaletteEntry("#4ec970", "成功绿"),
    PaletteEntry("#e8a23a", "警告黄"),
    PaletteEntry("#d6443c", "危险红"),
    PaletteEntry("#a855f7", "强调紫"),
    PaletteEntry("#06b6d4", "信息青"),
    PaletteEntry("#ec4899", "点缀粉"),
    PaletteEntry("#8a8f98", "中性灰"),
]


class _SwatchButton(QToolButton):
    """单个颜色块. 渲染: 圆角方块 + 选中态双层边框."""

    def __init__(self, entry: PaletteEntry, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._entry = entry
        self._selected = False
        self.setToolTip(f"{entry.name}  {entry.hex}")
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFixedSize(28, 28)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, False)

    def set_selected(self, selected: bool) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self.update()

    def is_selected(self) -> bool:
        return self._selected

    def entry(self) -> PaletteEntry:
        return self._entry

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(2, 2, -2, -2)
        p.setBrush(QColor(self._entry.hex))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(rect, 4, 4)
        if self._selected:
            # 外白边
            pen_outer = QPen(QColor("#f0f1f2"))
            pen_outer.setWidth(2)
            p.setPen(pen_outer)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect, 4, 4)
            # 内蓝边
            pen_inner = QPen(QColor("#6c7ae0"))
            pen_inner.setWidth(1)
            p.setPen(pen_inner)
            inset = rect.adjusted(2, 2, -2, -2)
            p.drawRoundedRect(inset, 3, 3)
        p.end()


class ColorPalette(QWidget):
    """颜色选择面板. 一行 8 色."""

    colorSelected = Signal(str)  # hex

    def __init__(
        self,
        palette: Optional[List[PaletteEntry]] = None,
        *,
        initial: Optional[str] = None,
        columns: int = 8,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette or DEFAULT_PALETTE
        self._buttons: List[_SwatchButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 标题
        if initial is not None:
            self._title = QLabel(f"已选: {initial}", self)
            self._title.setObjectName("paletteTitle")
            self._title.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
            layout.addWidget(self._title)

        grid = QHBoxLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        for entry in self._palette:
            btn = _SwatchButton(entry, self)
            btn.clicked.connect(lambda _checked=False, e=entry: self._on_clicked(e))
            self._group.addButton(btn)
            self._buttons.append(btn)
            grid.addWidget(btn)
        grid.addStretch(1)
        layout.addLayout(grid)

        # 初始选中
        if initial:
            self.set_selected(initial)

    # ---- 公开 API ----
    def palette(self) -> List[PaletteEntry]:
        return list(self._palette)

    def selected_color(self) -> Optional[str]:
        for b in self._buttons:
            if b.is_selected():
                return b.entry().hex
        return None

    def set_selected(self, hex_color: str) -> None:
        target = hex_color.lower()
        for b in self._buttons:
            ok = b.entry().hex.lower() == target
            b.set_selected(ok)
        if hasattr(self, "_title"):
            self._title.setText(f"已选: {hex_color}")

    # ---- 内部 ----
    def _on_clicked(self, entry: PaletteEntry) -> None:
        for b in self._buttons:
            b.set_selected(b.entry().hex == entry.hex)
        if hasattr(self, "_title"):
            self._title.setText(f"已选: {entry.hex}")
        self.colorSelected.emit(entry.hex)


class ThemeToggle(QWidget):
    """暗/亮主题切换按钮组. 直接对接 ThemeManager."""

    themeChanged = Signal(str)  # "dark" | "light"

    def __init__(
        self,
        *,
        manager: Optional[ThemeManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        # 4.0 修复: 自身 setObjectName, 让 QWidget#themeToggle 在主题 QSS 中始终生效
        self.setObjectName("themeToggle")
        self._manager = manager or ThemeManager.instance()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._dark_btn = QPushButton("🌙 暗色", self)
        self._dark_btn.setObjectName("themeBtn")
        self._light_btn = QPushButton("☀️ 亮色", self)
        self._light_btn.setObjectName("themeBtn")
        for b in (self._dark_btn, self._light_btn):
            b.setCheckable(True)
            b.setFixedHeight(26)
            b.setMinimumWidth(72)
            b.setCursor(QCursor(Qt.PointingHandCursor))
        self._dark_btn.clicked.connect(lambda: self._apply("dark"))
        self._light_btn.clicked.connect(lambda: self._apply("light"))
        layout.addWidget(self._dark_btn)
        layout.addWidget(self._light_btn)

        # 4.0 修复: 之前 setStyleSheet 硬编码 #191a1b 暗色, 切到亮色下整个切换器还是黑块.
        # 现在删除 inline setStyleSheet, 全部由 theme.py 的 QWidget#themeToggle / QPushButton#themeBtn 节点管.

        # 监听管理器的主题变化 (兼容外部触发: 菜单/快捷键/toggle())
        try:
            self._manager.changed.connect(self._apply_state)
        except Exception:
            pass

        self._apply_state()

    def current_theme(self) -> ThemeName:
        return self._manager.current()

    def _apply(self, name: ThemeName) -> None:
        if self._manager.current() == name:
            return
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        assert app is not None
        self._manager.apply(app, name)
        self._apply_state()
        self.themeChanged.emit(name)
        # 4.0 修复: 持久化到 app_settings, 下次启动恢复用户偏好
        try:
            from app.services import app_setting_service
            app_setting_service.set("ui.theme", name)
        except Exception:
            pass

    def _apply_state(self) -> None:
        cur = self._manager.current()
        self._dark_btn.setChecked(cur == "dark")
        self._light_btn.setChecked(cur == "light")
