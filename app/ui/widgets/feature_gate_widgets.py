"""
M10-C: Feature Gate UI 组件 (M9-C 后端 UI 接入).

提供:
  1. `FeatureGateBadge` (QLabel) — 紫色 💎 PRO 角标
  2. `apply_feature_gate(widget, feature_id, on_locked=None)` — 把 badge 附到任意 widget
  3. `assert_feature_or_dialog(feature_id, parent=None)` — 检查 + 弹锁提示

设计:
  - L4 UI 组件, 只调 app.services.feature_gate (L2)
  - 软依赖: feature_gate 不可用时全部 disabled, 不崩
  - 锁提示走 Dialogs.warning (不阻断, 引导去激活)
  - 弹"💎 升级 PRO" 含 feature 名称 + 解锁后能干啥
"""
from __future__ import annotations

import logging
from typing import Optional, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QWidget

from app.ui.widgets import Dialogs

log = logging.getLogger(__name__)

# 软依赖导入
try:
    from app.services.feature_gate import (
        check_feature, get_tier, FEATURE_TIERS, Tier,
        FeatureLockedError, assert_feature,
    )
    _HAS_FEATURE_GATE = True
except Exception as e:  # pragma: no cover
    _HAS_FEATURE_GATE = False
    log.warning("feature_gate_widgets: 加载 feature_gate 失败 (%s)", e)


class FeatureGateBadge(QLabel):
    """紫色 💎 PRO 角标 — 贴在按钮/菜单项旁边.

    用法:
        btn = QPushButton("AI 评分")
        badge = FeatureGateBadge("ai.critic")
        # 父级 layout 放 btn + badge 水平排

    自动根据当前 tier 显示/隐藏:
      - 当前已解锁 → hide
      - 当前未解锁 → show("💎 PRO")
    """

    def __init__(self, feature_id: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.feature_id = feature_id
        self.setObjectName("feature_gate_badge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 紫色加粗
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        self.setFont(font)
        self.setStyleSheet(
            "QLabel { color: #7b1fa2; background: #f3e5f5; "
            "border: 1px solid #7b1fa2; border-radius: 6px; "
            "padding: 1px 6px; }"
        )
        self.setText("💎 PRO")
        self.setToolTip("需要 PRO 等级才能用")
        self.setVisible(False)
        self.refresh()

    def refresh(self) -> None:
        """根据当前 tier 决定显示/隐藏."""
        if not _HAS_FEATURE_GATE:
            self.setVisible(False)
            return
        try:
            unlocked = check_feature(self.feature_id)
        except Exception as e:
            log.warning("check_feature(%s) failed: %s", self.feature_id, e)
            unlocked = False
        self.setVisible(not unlocked)


# --------------------------------------------------------------------- 辅助
def apply_feature_gate(
    widget: QWidget,
    feature_id: str,
    *,
    on_locked: Optional[Callable[[], None]] = None,
) -> FeatureGateBadge:
    """在 widget 旁加 PRO 角标 + click 时检查.

    用法:
        badge = apply_feature_gate(btn_ai_critic, "ai.critic")
        # btn 显示时会带 💎 角标 (在父 layout 里)

    Args:
        widget: 任意 QWidget (按钮/菜单项)
        feature_id: FEATURE_TIERS 注册的 id
        on_locked: 锁住时的额外回调 (比如调父级的提示逻辑)

    Returns:
        FeatureGateBadge 实例 (供父级 layout addWidget)
    """
    badge = FeatureGateBadge(feature_id, parent=widget.parent())
    badge.refresh()
    # 监听 feature 状态变化 (M10-B 切换 tier 后可调 badge.refresh())
    return badge


def refresh_all_badges(parent: QWidget) -> int:
    """遍历 parent 下所有 FeatureGateBadge, 调 refresh()."""
    count = 0
    for badge in parent.findChildren(FeatureGateBadge):
        badge.refresh()
        count += 1
    return count


def assert_feature_or_dialog(
    feature_id: str,
    parent: Optional[QWidget] = None,
) -> bool:
    """检查 feature 是否解锁, 锁了弹 Dialogs.warning 引导激活.

    Returns:
        True  = 已解锁, 可继续
        False = 锁了 (已弹提示)
    """
    if not _HAS_FEATURE_GATE:
        Dialogs.warning(
            "不可用",
            "feature_gate 服务不可用, 业务功能被锁定. 请检查 app.services.feature_gate 模块.",
            parent=parent,
        )
        return False
    try:
        assert_feature(feature_id)  # 内部已 throw
        return True
    except FeatureLockedError as e:
        # 找 feature 中文名
        from app.services.feature_gate import FEATURE_TIERS
        info = FEATURE_TIERS.get(feature_id)
        if info:
            name = info.name
            extra = ""
            if info.tier == Tier.PRO:
                extra = "\n\n解锁 PRO 后可用: \n" + (
                    "✓ 一键出版 4 格式 + 5 封面\n"
                    "✓ AI Critic 自动评分\n"
                    "✓ AI 调度优化 (并行 + 缓存)\n"
                    "✓ 高级插件发布"
                )
            Dialogs.warning(
                "🔒 功能未解锁",
                f"'{name}' 需要 {info.tier.value.upper()} 等级\n"
                f"当前等级: {get_tier().value.upper()}\n\n"
                f"💡 前往 设置 → 🔐 License 激活 key 解锁{extra}",
                parent=parent,
            )
        else:
            Dialogs.warning(
                "🔒 未知功能",
                f"功能 '{feature_id}' 未在 FEATURE_TIERS 注册.\n"
                f"可能是 typo, 请联系开发者.\n\nerr: {e}",
                parent=parent,
            )
        return False


def is_feature_available(feature_id: str) -> bool:
    """简单查询 (不弹窗)."""
    if not _HAS_FEATURE_GATE:
        return False
    try:
        return check_feature(feature_id)
    except Exception:
        return False


def get_current_tier_label() -> str:
    """返回当前 tier 中文 (FREE / STANDARD / PRO)."""
    if not _HAS_FEATURE_GATE:
        return "未知"
    try:
        t = get_tier()
        return {"free": "🆓 FREE", "standard": "⭐ STANDARD", "pro": "💎 PRO"}.get(
            t.value, t.value
        )
    except Exception:
        return "未知"
