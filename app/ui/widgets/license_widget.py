"""
M10-B: License 设置面板 (M9-C 后端 UI 接入).

显示内容:
  - 当前 license 状态 (PREMIUM / STANDARD / EXPIRED / INVALID / MACHINE_MISMATCH)
  - 当前 tier (FREE / STANDARD / PRO) 彩色徽章
  - 已解锁功能数 / 总功能数 (N/M 形式)
  - 主机码 (8 位哈希)
  - 到期日 + 剩余天数
  - 4 个操作按钮:
    1) 激活 License (弹 InputDialog 输入 NV-XXXX-...)
    2) 降级 (清掉 key 回 STANDARD)
    3) 复制机器码
    4) 刷新状态

设计:
  - L4 UI 组件, 不破坏分层 (只调 app.services.license / feature_gate)
  - 复用 Dialogs.confirm / .input / .info
  - tokens_hint 注册 settings_license (0 元, 配置类)
  - 失败/成功都走 Dialogs 弹窗, 不静默
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget, QApplication,
)
from app.ui.theme import text_chip

from app.ui.widgets import Dialogs

log = logging.getLogger(__name__)

# 软依赖导入 (M9-C 必备)
try:
    from app.services.license import (
        get_license, activate, deactivate, get_machine_code,
        LicenseStatus, reset_cache,
    )
    from app.services.feature_gate import (
        get_tier, FEATURE_TIERS, check_feature, Tier, tier_rank,
    )
    _HAS_LICENSE = True
except Exception as e:  # pragma: no cover
    _HAS_LICENSE = False
    log.warning("license_widget: 加载 license / feature_gate 失败 (%s)", e)


# Tier 颜色 + 中文
_TIER_INFO = {
    Tier.FREE:     ("🆓", "FREE",     "#9e9e9e", "永久免费层"),
    Tier.STANDARD: ("⭐", "STANDARD", "#1976d2", "标准版 (默认)"),
    Tier.PRO:      ("💎", "PRO",      "#7b1fa2", "专业版 (付费)"),
}

# Status 颜色 + 中文
_STATUS_INFO = {
    LicenseStatus.PREMIUM:          ("✅", "已激活",       "#388e3c"),
    LicenseStatus.STANDARD:         ("🆓", "标准版",       "#1976d2"),
    LicenseStatus.INVALID:          ("❌", "无效 key",     "#c62828"),
    LicenseStatus.EXPIRED:          ("⏰", "已过期",       "#ef6c00"),
    LicenseStatus.MACHINE_MISMATCH: ("🔒", "机器码不匹配", "#c62828"),
}


class LicenseWidget(QGroupBox):
    """License 设置面板.

    用法:
        from app.ui.widgets.license_widget import LicenseWidget
        self.license_widget = LicenseWidget()
        # 嵌进任意 layout / tab
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("🔐 License 授权", parent)
        self.setObjectName("license_widget")
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 16, 12, 12)
        outer.setSpacing(8)

        # Tier 徽章 (大字)
        self.lbl_tier = QLabel("—")
        tier_font = QFont()
        tier_font.setBold(True)
        tier_font.setPointSize(14)
        self.lbl_tier.setFont(tier_font)
        outer.addWidget(self.lbl_tier)

        # 状态行
        self.lbl_status = QLabel("—")
        status_font = QFont()
        status_font.setPointSize(11)
        self.lbl_status.setFont(status_font)
        outer.addWidget(self.lbl_status)

        # 详细 info (机器码 / 到期日 / 已解锁)
        info_box = QGroupBox("详细信息")
        info_form = QFormLayout(info_box)
        info_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_machine = QLabel("—")
        self.lbl_expire = QLabel("—")
        self.lbl_unlocked = QLabel("—")
        info_form.addRow("主机码:", self.lbl_machine)
        info_form.addRow("到期日:", self.lbl_expire)
        info_form.addRow("已解锁:", self.lbl_unlocked)
        outer.addWidget(info_box)

        # 按钮行
        btn_row = QHBoxLayout()
        self.btn_activate = QPushButton("🔑 激活 License")
        self.btn_activate.setToolTip("粘贴 NV-XXXX-XXXX-XXXX-XXXX 格式的 key")
        self.btn_activate.clicked.connect(self._on_activate)
        btn_row.addWidget(self.btn_activate)

        self.btn_deactivate = QPushButton("⬇ 降级到标准版")
        self.btn_deactivate.setToolTip("清掉激活的 key, 回到 STANDARD 默认等级")
        self.btn_deactivate.clicked.connect(self._on_deactivate)
        btn_row.addWidget(self.btn_deactivate)

        outer.addLayout(btn_row)

        # 第二行: 机器码 / 刷新
        btn_row2 = QHBoxLayout()
        self.btn_copy_machine = QPushButton("📋 复制机器码")
        self.btn_copy_machine.setToolTip("把当前主机的 8 位哈希复制到剪贴板")
        self.btn_copy_machine.clicked.connect(self._on_copy_machine)
        btn_row2.addWidget(self.btn_copy_machine)

        self.btn_refresh = QPushButton("🔄 刷新状态")
        self.btn_refresh.clicked.connect(self.refresh)
        btn_row2.addWidget(self.btn_refresh)

        outer.addLayout(btn_row2)

        # 说明区
        note = QLabel(
            "💡 离线校验: 激活后断网也能用, key 存 app_settings 表.\n"
            "万能 key (NV-UNIV-...) 任何机器可用, 团队/演示场景.\n"
            "机器绑定 key 错机器会提示 '机器码不匹配'."
        )
        note.setStyleSheet(f"color: {text_chip()}; font-size: 11px;")
        note.setWordWrap(True)
        outer.addWidget(note)

        outer.addStretch(1)

    # ------------------------------------------------------------------ 数据
    def refresh(self) -> None:
        """从 license / feature_gate 服务读最新状态, 刷新 UI."""
        if not _HAS_LICENSE:
            self.lbl_tier.setText("❌ 模块未加载")
            self.lbl_status.setText("license / feature_gate 服务不可用")
            self._set_actions_enabled(False)
            return
        try:
            reset_cache()  # 强制重读 (测试场景需要)
            info = get_license()
            tier = get_tier()
            machine = get_machine_code()
        except Exception as e:
            log.exception("refresh license failed: %s", e)
            self.lbl_tier.setText("❌ 读取失败")
            self.lbl_status.setText(f"err: {e}")
            self._set_actions_enabled(False)
            return

        # Tier
        emoji, label, color, desc = _TIER_INFO.get(tier, ("?", "?", "#000", ""))
        self.lbl_tier.setText(f"{emoji} {label} <span style='color:{color}; font-size:11px;'>({desc})</span>")
        self.lbl_tier.setTextFormat(Qt.TextFormat.RichText)

        # Status
        s_emoji, s_label, s_color = _STATUS_INFO.get(
            info.status, ("?", "?", "#000")
        )
        self.lbl_status.setText(
            f"{s_emoji} 状态: <b style='color:{s_color};'>{s_label}</b>"
            f"  (v{info.version or '?'})"
        )
        self.lbl_status.setTextFormat(Qt.TextFormat.RichText)

        # 机器码
        self.lbl_machine.setText(machine or "(未生成)")

        # 到期日 + 剩余
        if info.expire_date:
            remaining = info.remaining_days
            if remaining is not None and remaining >= 0:
                remain_text = f" (剩余 <b style='color:#1976d2;'>{remaining}</b> 天)"
            elif remaining is not None:
                remain_text = " (已过期)"
            else:
                remain_text = ""
            self.lbl_expire.setText(f"{info.expire_date}{remain_text}")
            self.lbl_expire.setTextFormat(Qt.TextFormat.RichText)
        else:
            self.lbl_expire.setText("(永久 / 未激活)")

        # 已解锁 N / 总 M
        total = len(FEATURE_TIERS)
        unlocked = sum(1 for fid, fi in FEATURE_TIERS.items() if check_feature(fid))
        self.lbl_unlocked.setText(
            f"<b style='color:#388e3c;'>{unlocked}</b> / {total} 个功能 "
            f"(当前 tier={label})"
        )
        self.lbl_unlocked.setTextFormat(Qt.TextFormat.RichText)

        # 按钮启用状态: PREMIUM 时显示"降级", 其他时显示"激活"
        if info.status == LicenseStatus.PREMIUM:
            self.btn_activate.setEnabled(False)
            self.btn_deactivate.setEnabled(True)
        else:
            self.btn_activate.setEnabled(True)
            self.btn_deactivate.setEnabled(False)

    def _set_actions_enabled(self, enabled: bool) -> None:
        for btn in (
            self.btn_activate, self.btn_deactivate,
            self.btn_copy_machine, self.btn_refresh,
        ):
            btn.setEnabled(enabled)

    # ------------------------------------------------------------------ 行为
    def _on_activate(self) -> None:
        if not _HAS_LICENSE:
            return
        # 弹 InputDialog 输入 key
        ok, key = Dialogs.input(
            "激活 License",
            "粘贴 license key (NV-XXXX-XXXX-XXXX-XXXX 格式):\n万能 key 以 NV-UNIV- 开头",
            placeholder="NV-XXXX-XXXX-XXXX-XXXX",
            parent=self,
        )
        if not ok or not key:
            return
        key = key.strip()
        # 调 activate
        try:
            info = activate(key)
        except Exception as e:
            log.exception("activate failed: %s", e)
            Dialogs.error("激活失败", str(e), parent=self)
            return
        if info.status == LicenseStatus.PREMIUM and not info.error_msg:
            # 成功
            expire = info.expire_date or "永久"
            Dialogs.info(
                "激活成功",
                f"✅ 已升级到 PRO!\n到期日: {expire}\n版本: v{info.version or '?'}",
                parent=self,
            )
            self.refresh()
            self._notify_parent_refresh()
        else:
            # 失败
            Dialogs.error(
                "激活失败",
                f"原因: {info.error_msg or info.status.value}\n"
                f"状态: {info.status.value}",
                parent=self,
            )
            self.refresh()

    def _on_deactivate(self) -> None:
        if not _HAS_LICENSE:
            return
        ok = Dialogs.confirm(
            "降级到标准版",
            "确定要降级吗? 激活的 license key 会被清掉, 回到 STANDARD 默认等级.\n"
            "可以之后再激活别的 key.",
            confirm_text="确定降级",
            cancel_text="取消",
            parent=self,
        )
        if not ok:
            return
        try:
            info = deactivate()
            if info.status == LicenseStatus.STANDARD:
                Dialogs.info("已降级", "已回到 STANDARD 标准版", parent=self)
            else:
                Dialogs.info("已降级", f"当前状态: {info.status.value}", parent=self)
            self.refresh()
            self._notify_parent_refresh()
        except Exception as e:
            log.exception("deactivate failed: %s", e)
            Dialogs.error("降级失败", str(e), parent=self)

    def _on_copy_machine(self) -> None:
        if not _HAS_LICENSE:
            return
        try:
            machine = get_machine_code()
            cb = QApplication.clipboard()
            if cb is not None and machine:
                cb.setText(machine)
                Dialogs.info(
                    "已复制",
                    f"机器码: {machine}\n\n把这个发给发 key 的人, 让他生成机器绑定的 key.",
                    parent=self,
                )
        except Exception as e:
            log.exception("copy machine failed: %s", e)
            Dialogs.error("复制失败", str(e), parent=self)

    # ------------------------------------------------------------------ 通知
    def _notify_parent_refresh(self) -> None:
        """M10-C: 沿 parent 链找 refresh_tier_indicator() 并调.

        用途: 激活/降级成功后, 通知 EditorTab 刷新 PRO 角标 + tier 指示器.
        找不到时静默 (LicenseWidget 可能没嵌进 MainWindow, 例如测试场景).
        """
        p = self.parent()
        while p is not None:
            if hasattr(p, "refresh_tier_indicator") and callable(
                getattr(p, "refresh_tier_indicator", None)
            ):
                try:
                    p.refresh_tier_indicator()  # type: ignore[attr-defined]
                except Exception as e:  # pragma: no cover
                    log.warning("parent.refresh_tier_indicator() 失败: %s", e)
                return
            p = p.parent()
