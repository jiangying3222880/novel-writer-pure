"""
v4.0 按钮规范补丁 — 统一工厂 + 布局 + 事件诊断.

三个职责:
1. make_button()   — 标准化按钮创建 (iconSize/minHeight/sizePolicy/padding)
2. standardize_layout() — 标准化布局 spacing/margins
3. diagnose_button_click() — 诊断"点击无效"根因

用法:
    from app.ui.widgets.button_utils import make_button, standardize_layout

    btn = make_button("✨ 开始写作", primary=True, parent=self)
    standardize_layout(layout)
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QPushButton, QToolButton, QLayout,
    QSizePolicy, QWidget,
)

log = logging.getLogger(__name__)

# ---- 设计规范常量 ----
ICON_SIZE = QSize(18, 18)
MIN_HEIGHT = 36
BUTTON_PADDING = "padding: 6px 10px 6px 12px;"
LAYOUT_SPACING = 8
LAYOUT_MARGINS = (8, 8, 8, 8)


# ------------------------------------------------------------------ #
# 1. 标准化按钮工厂
# ------------------------------------------------------------------ #

def make_button(
    text: str = "",
    *,
    parent: Optional[QWidget] = None,
    primary: bool = False,
    ghost: bool = False,
    danger: bool = False,
    small: bool = False,
    icon_only: bool = False,
    checkable: bool = False,
    tooltip: str = "",
    fixed_width: Optional[int] = None,
    fixed_height: Optional[int] = None,
    min_width: Optional[int] = None,
    min_height: Optional[int] = MIN_HEIGHT,
    icon_size: QSize = ICON_SIZE,
) -> QPushButton:
    """创建符合 v4.0 规范的 QPushButton.

    解决三大问题:
    - Event: 确保正确的 sizePolicy, 按钮始终可点击
    - Layout: 统一 iconSize + minHeight, 防止 emoji/图标被裁剪
    - Theme: 使用 objectName 走全局 QSS, 不写 inline stylesheet

    objectName 映射:
    - primary=True  → "btnPrimary"
    - ghost=True    → "btnGhost"
    - danger=True   → "btnDanger"
    - small=True    → "btnSm"
    - icon_only=True → "btnIcon"
    - (默认)        → "" (走 QPushButton 默认样式)
    """
    btn = QPushButton(text, parent)
    btn.setIconSize(icon_size)
    btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    btn.setMinimumHeight(min_height or MIN_HEIGHT)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)

    # objectName → QSS selector
    if primary:
        btn.setObjectName("btnPrimary")
    elif ghost:
        btn.setObjectName("btnGhost")
    elif danger:
        btn.setObjectName("btnDanger")
    elif small:
        btn.setObjectName("btnSm")
    elif icon_only:
        btn.setObjectName("btnIcon")
    # 默认: 不设 objectName, 走 QPushButton 通用样式

    if checkable:
        btn.setCheckable(True)

    if fixed_width:
        btn.setFixedWidth(fixed_width)
    if fixed_height:
        btn.setFixedHeight(fixed_height)
    if min_width:
        btn.setMinimumWidth(min_width)

    if tooltip:
        btn.setToolTip(tooltip)

    # 确保事件不会被吞
    btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
    btn.raise_()

    return btn


# ------------------------------------------------------------------ #
# 2. 布局标准化
# ------------------------------------------------------------------ #

def standardize_layout(
    layout: QLayout,
    spacing: int = LAYOUT_SPACING,
    margins: tuple[int, int, int, int] = LAYOUT_MARGINS,
) -> None:
    """标准化布局参数, 解决图标裁剪和间距不一致.

    spacing: 控件间距, 默认 8px
    margins: (left, top, right, bottom), 默认 (8, 8, 8, 8)
    """
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)


# ------------------------------------------------------------------ #
# 3. 事件诊断工具
# ------------------------------------------------------------------ #

def diagnose_button_click(button: QPushButton) -> str:
    """诊断按钮点击失败的原因.

    返回诊断报告字符串.

    常见问题 + 修复:
    - isVisible()=False           → show() / 父容器 layout 未 addWidget
    - isEnabled()=False           → setEnabled(True)
    - WA_TransparentForMouseEvents  → setAttribute(WA_TransparentForMouseEvents, False)
    - 被 sibling 遮挡              → raise_() / 检查 z-order
    - sizePolicy 不对             → setSizePolicy(Expanding, Fixed)
    - 父容器 size=0               → 检查 layout
    """
    lines = [f"=== 按钮诊断: {button.text() or '(no text)'} ==="]

    # 1. 可见性
    lines.append(f"  visible:     {button.isVisible()}")
    if not button.isVisible():
        lines.append("  → 修复: button.show() 或父容器 layout.addWidget(button)")

    # 2. 启用状态
    lines.append(f"  enabled:     {button.isEnabled()}")
    if not button.isEnabled():
        lines.append("  → 修复: button.setEnabled(True)")

    # 3. 鼠标穿透
    mouse_transparent = button.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    lines.append(f"  mouse_transparent: {mouse_transparent}")
    if mouse_transparent:
        lines.append("  → 修复: button.setAttribute(Qt.WA_TransparentForMouseEvents, False)")

    # 4. 尺寸
    lines.append(f"  size:        {button.size().width()}x{button.size().height()}")
    if button.size().width() < 20 or button.size().height() < 20:
        lines.append("  → 修复: button.setMinimumHeight(36) + setIconSize(QSize(18,18))")

    # 5. sizePolicy
    sp = button.sizePolicy()
    lines.append(f"  sizePolicy:  H={sp.horizontalPolicy()}, V={sp.verticalPolicy()}")
    if sp.verticalPolicy() != QSizePolicy.Policy.Fixed:
        lines.append("  → 修复: setSizePolicy(Expanding, Fixed)")

    # 6. 父容器
    parent = button.parent()
    lines.append(f"  parent:      {type(parent).__name__ if parent else 'None'}")
    if parent:
        lines.append(f"  parent.size: {parent.size().width()}x{parent.size().height()}")
        if parent.size().width() == 0 or parent.size().height() == 0:
            lines.append("  → 修复: 父容器 layout 未正确设置或未 addWidget")

    # 7. z-order (同级中是否被遮挡)
    if parent:
        children = parent.findChildren(QWidget)
        siblings = [c for c in children if c is not button and c.isVisible()
                    and c.geometry().intersects(button.geometry())]
        if siblings:
            lines.append(f"  overlapped_by: {len(siblings)} sibling(s)")
            for sib in siblings[:3]:
                sib_pos = sib.geometry()
                btn_pos = button.geometry()
                lines.append(f"    {type(sib).__name__} at ({sib_pos.x()},{sib_pos.y()}) "
                           f"{sib_pos.width()}x{sib_pos.height()}")
            lines.append("  → 修复: button.raise_()")

    # 8. 信号检查 (receivers 需要 SIGNAL 宏, 跳过)
    lines.append("  connections:  检查 clicked 信号接线 (运行时日志)")

    lines.append("=== 诊断结束 ===")
    report = "\n".join(lines)
    log.info(report)
    return report


def ensure_button_clickable(button: QPushButton) -> QPushButton:
    """一键修复按钮可点击性 (返回 button 方便链式调用).

    自动修复:
    - WA_TransparentForMouseEvents → False
    - 如果 size < 20px → setMinimumHeight(36)
    - raise_() 确保不被遮挡
    """
    button.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
    button.raise_()
    if button.size().width() < 20 or button.size().height() < 20:
        button.setMinimumHeight(MIN_HEIGHT)
    return button
