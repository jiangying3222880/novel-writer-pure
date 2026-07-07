"""
I15 欢迎页 - 一次性 dialog (新用户第一次启动时显示).

内容:
  - 欢迎语
  - 各花钱功能费用清单 (一次性说清, 用户知情)
  - 创建第一本书引导
  - 不再显示 (默认勾选, 写 ui.welcome_shown=true 到 app settings)
"""
from __future__ import annotations
import logging
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QFrame, QScrollArea, QWidget, QSizePolicy,
)
from app.ui.theme import text_muted, text_warn

from app.core.version import VERSION
from app.services import app_setting_service
from app.services.pricing import USD_TO_CNY

log = logging.getLogger(__name__)

WELCOME_KEY = "ui.welcome_shown"


# 费用清单 (功能 + 单价 CNY + 说明 + 对比不用)
# 价位按"一章 3000 字 + 一次评估"为基准粗算. 实际依模型价 + 章节长度变化.
COST_TABLE = [
    {
        "icon": "✨",
        "name": "章节生成 (G1 写作引擎)",
        "per_use": "约 ¥0.10 - 0.30 / 章",
        "compare": "vs 不用: 0 tokens 消耗, 但写出来像 AI 翻译腔, 没人物声音没矛盾自洽",
        "note": "DeepSeek 默认; 可切 GPT-4o / Claude 提升质量, 价也涨",
    },
    {
        "icon": "🧠",
        "name": "风格学习器 (G7, 写前 10 章时跑 1 次)",
        "per_use": "约 ¥0.05 / 次 (一次性)",
        "compare": "vs 不用: AI 按通用模板写, 不会学你的语感, 长篇会越写越 AI",
        "note": "0 token 风险可控, 默认开",
    },
    {
        "icon": "🎙️",
        "name": "声音推断 (G8, 给每角色做 1 次)",
        "per_use": "约 ¥0.02 / 角色",
        "compare": "vs 不用: 多个角色说话一个味, 读者分不清谁是谁",
        "note": "可手动调, 调过的不再扣",
    },
    {
        "icon": "🔍",
        "name": "一致性检测 (G5, 每章自动跑)",
        "per_use": "约 ¥0.01 / 章",
        "compare": "vs 不用: 写多了会人物乱入 / 物品穿越 / 时间线错",
        "note": "0 误报时静默, 只在有问题时弹",
    },
    {
        "icon": "📥",
        "name": "AI 导入解析 (C1, txt / md 文件)",
        "per_use": "约 ¥0.05 - 0.20 / 文件 (按大小)",
        "compare": "vs 不用: 手动复制粘贴设定, 100 项要半小时",
        "note": "首次导入某书时跑 1 次",
    },
    {
        "icon": "🎭",
        "name": "潜文本卡 (subtext, 每章自动跑)",
        "per_use": "约 ¥0.02 / 章 (AI 模式)",
        "compare": "vs 不用: 章节直白没潜台词, 像流水账",
        "note": "可关闭, 0 消耗",
    },
]


class WelcomeDialog(QDialog):
    """一次性欢迎 dialog."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"欢迎使用 Novel Writer Pure v{VERSION}")
        self.setMinimumSize(640, 560)
        self.setModal(True)

        self._build_ui()
        self._apply_default_checkbox()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)

        # 标题
        title = QLabel(f"📖 欢迎使用 Novel Writer Pure v{VERSION}")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        root.addWidget(title)

        # 副标题
        subtitle = QLabel(
            "AI 辅助小说写作桌面应用 · 单进程 Python + PySide6 + SQLite\n"
            "所有模型调用走你本地的 API key, 数据全部存在你的电脑上, 不上云。"
        )
        subtitle.setStyleSheet(f"color: {text_muted()};")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        # 分隔线
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep1)

        # 费用标题
        fee_title = QLabel("💰 花钱功能费用一览 (一次性说清)")
        fee_font = QFont()
        fee_font.setPointSize(13)
        fee_font.setBold(True)
        fee_title.setFont(fee_font)
        root.addWidget(fee_title)

        # 费用滚动区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(280)
        fee_widget = QWidget()
        fee_layout = QVBoxLayout(fee_widget)
        fee_layout.setContentsMargins(0, 0, 0, 0)
        fee_layout.setSpacing(8)

        for item in COST_TABLE:
            fee_layout.addWidget(self._build_cost_card(item))
        fee_layout.addStretch(1)
        scroll.setWidget(fee_widget)
        root.addWidget(scroll, 1)

        # 分隔线
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep2)

        # 底部 checkbox + 按钮
        bottom = QHBoxLayout()
        self.chk_dont_show = QCheckBox("✅ 我已知悉, 启动时不再显示此页")
        self.chk_dont_show.setChecked(True)
        bottom.addWidget(self.chk_dont_show)
        bottom.addStretch(1)
        self.btn_create = QPushButton(" 创建第一本书")
        self.btn_create.setObjectName("primaryAction")
        self.btn_create.clicked.connect(self._on_create_first)
        bottom.addWidget(self.btn_create)
        self.btn_close = QPushButton("稍后再说")
        self.btn_close.clicked.connect(self.reject)
        bottom.addWidget(self.btn_close)
        root.addLayout(bottom)

    def _build_cost_card(self, item: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("costCard")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)

        # 名称行
        name_row = QHBoxLayout()
        lbl_name = QLabel(f"{item['icon']} <b>{item['name']}</b>")
        lbl_name.setTextFormat(Qt.TextFormat.RichText)
        name_row.addWidget(lbl_name)
        name_row.addStretch(1)
        lbl_price = QLabel(f"<b>{item['per_use']}</b>")
        lbl_price.setTextFormat(Qt.TextFormat.RichText)
        lbl_price.setStyleSheet(f"color: {text_warn()};")
        name_row.addWidget(lbl_price)
        lay.addLayout(name_row)

        # 对比
        cmp_label = QLabel(f"<span style='color:#8a8f98'>vs 不用: </span>"
                           f"{item['compare']}")
        cmp_label.setTextFormat(Qt.TextFormat.RichText)
        cmp_label.setWordWrap(True)
        lay.addWidget(cmp_label)

        # 备注
        note = QLabel(f"<i>💡 {item['note']}</i>")
        note.setTextFormat(Qt.TextFormat.RichText)
        note.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        note.setWordWrap(True)
        lay.addWidget(note)
        return card

    def _apply_default_checkbox(self) -> None:
        """默认勾上"不再显示". 但若 db 已设 welcome_shown=true, 不勾选? 这里反着: 不管 db, 用户没勾就不存."""
        pass

    def _on_create_first(self) -> None:
        # 关闭欢迎页, 接受
        self.accept_create = True
        self.accept()

    # ---- 公开 API ----
    accept_create: bool = False  # 用户是否点 "创建第一本书"

    def accept(self) -> None:  # type: ignore[override]
        # 记录"已显示"标志
        if self.chk_dont_show.isChecked():
            try:
                app_setting_service.set(WELCOME_KEY, True)
                log.info("Welcome page: 已标记不再显示")
            except Exception as e:
                log.warning("写 welcome_shown 失败: %s", e)
        super().accept()


# --------------------------------------------------------------------- #
# 启动钩子: 第一次启动时弹出欢迎页
# --------------------------------------------------------------------- #

def is_welcome_shown() -> bool:
    """是否已显示过欢迎页 (从 app settings 读)."""
    try:
        return bool(app_setting_service.get(WELCOME_KEY, False))
    except Exception:
        return False


def show_welcome_if_first_time(parent: Optional[QWidget] = None) -> Optional[WelcomeDialog]:
    """首次启动弹欢迎页. 已显示过返回 None."""
    if is_welcome_shown():
        return None
    dlg = WelcomeDialog(parent)
    dlg.exec()
    return dlg
