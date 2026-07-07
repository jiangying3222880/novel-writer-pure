"""
Tokens 提示系统 (3 位置: 欢迎页 / tab 顶 PriceBar / 首次开启 FirstUsePopup).

业务目标:
  - 用户每次接触花钱功能, 都能看到"花多少 + 对比不用会怎样"
  - 避免月底账单吓一跳, 也避免因为不知情而不敢用
  - 所有价格显示加"约"字, 必带"价格更新于 YYYY-MM-DD + 可能与实际有偏差"

设计:
  - FEATURE_REGISTRY: 中央功能表, 决定 PriceBar / Popup 渲染内容
  - PriceBar: 顶栏小横条, 显示图标 + 功能名 + 单次费用 + 更新时间 + [可能过期]
  - FirstUsePopup: 一次性 dialog, 首次切到该 tab / 首次点"启用"时弹
  - mark_shown / is_shown: 持久化在 app_setting_service 的 kv, key = "ui.tokens_hint.shown.<feature_id>"

注意事项:
  - 0 价格的模型 (mock / 本地) → 显示 "免费" 而非 "约 ¥0"
  - 超过 30 天未更新的价格 → 标黄 + [可能过期]
  - 不强行阻塞用户: Popup 关闭即继续, 仅记录
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QFrame, QScrollArea, QWidget, QSizePolicy,
)
from app.ui.theme import text_muted, text_secondary, text_warn

from app.services import app_setting_service
from app.services.pricing import get_warning_text

log = logging.getLogger(__name__)


# ============================================================
# 中央功能注册表
# ============================================================

@dataclass
class FeatureInfo:
    """一个花钱功能的信息. 用于 PriceBar + FirstUsePopup."""
    feature_id: str          # 全局唯一, e.g. "generate" / "editor_rewrite"
    icon: str                # 1-2 字 emoji
    name: str                # 功能名 (tab 顶部显示)
    short_desc: str          # 1 句话, PriceBar 副标题
    per_use_cny: str         # "约 ¥0.10 - 0.30 / 章"
    compare_with: str        # "vs 不用: 写出来像 AI 翻译腔, ..."
    detail_note: str         # 备注 (含价格提示)

    # 持久化 key (首次开启标志)
    shown_key: str = field(init=False)

    def __post_init__(self) -> None:
        self.shown_key = f"ui.tokens_hint.shown.{self.feature_id}"


# 与 docs/project_memory.md / welcome.py 的 COST_TABLE 保持一致
FEATURE_REGISTRY: dict[str, FeatureInfo] = {
    "generate": FeatureInfo(
        feature_id="generate",
        icon="✨",
        name="章节生成",
        short_desc="AI 写整章正文",
        per_use_cny="约 ¥0.10 - 0.30 / 章",
        compare_with=(
            "vs 不用: 0 tokens 消耗, 但写出来像 AI 翻译腔, "
            "没人物声音没矛盾自洽"
        ),
        detail_note=(
            "💡 DeepSeek 默认; 可切 GPT-4o / Claude 提升质量, 价也涨。"
            "首次切到 AI 自动模式会弹此提示, 之后可放心用。"
        ),
    ),
    "editor_rewrite": FeatureInfo(
        feature_id="editor_rewrite",
        icon="✏️",
        name="段落重写",
        short_desc="AI 重写指定段",
        per_use_cny="约 ¥0.02 - 0.05 / 段",
        compare_with=(
            "vs 不用: 自己手动改, 一段可能要 10 分钟;"
            "AI 改可马上看 3 个版本挑一个"
        ),
        detail_note=(
            "💡 短段(50-200字)费用低, 长段费用按 token 比例涨。"
            "调好的版本会自动落库 + 写 change_log。"
        ),
    ),
    "consistency": FeatureInfo(
        feature_id="consistency",
        icon="🔍",
        name="一致性检测",
        short_desc="每章自动跑",
        per_use_cny="约 ¥0.01 / 章",
        compare_with=(
            "vs 不用: 写多了会人物乱入 / 物品穿越 / 时间线错,"
            "读者一眼出戏"
        ),
        detail_note=(
            "💡 0 误报时静默, 只在有问题时弹。"
            "可在「小说设定 - 风格」里关掉。"
        ),
    ),
    "voice_inference": FeatureInfo(
        feature_id="voice_inference",
        icon="🎙️",
        name="声音推断",
        short_desc="给每角色做 1 次",
        per_use_cny="约 ¥0.02 / 角色",
        compare_with=(
            "vs 不用: 多个角色说话一个味, 读者分不清谁是谁"
        ),
        detail_note=(
            "💡 跑 1 次即可, 后续 AI 按档案写。可手动调, "
            "调过的不再扣 tokens。"
        ),
    ),
    "editor_tts": FeatureInfo(
        feature_id="editor_tts",
        icon="🔊",
        name="章节朗读 (TTS)",
        short_desc="章节转语音",
        per_use_cny="0 元 (edge-tts 免费 + 需联网)",
        compare_with=(
            "vs 不用: 自己默读一遍可能要 20 分钟, "
            "听一遍 5 分钟就能抓出节奏问题"
        ),
        detail_note=(
            "💡 mock 模式秒生成空 wav 占位; 装 edge-tts 即可用真实语音 "
            "(zh-CN-XiaoxiaoNeural 等微软音色)。"
            "听一遍比看一遍更易发现 AI 腔。"
        ),
    ),
    "editor_export": FeatureInfo(
        feature_id="editor_export",
        icon="📦",
        name="一键出版 (导出全书)",
        short_desc="导出 EPUB/DOCX/MD/TXT + 5 封面模板",
        per_use_cny="0 元 (本地导出, 0 第三方依赖)",
        compare_with=(
            "vs 不用: 自己用 Word / 排版工具排一本书可能要 4-8 小时; "
            "一键导出 EPUB/DOCX 几秒出, 含目录和封面"
        ),
        detail_note=(
            "💡 4 格式 (EPUB / DOCX / Markdown / TXT) 0 第三方依赖, zip+XML 自实现; "
            "5 封面模板 (default / minimal / wuxia / romance / scifi) 用 PIL 本地渲染。"
            "导出后可去编辑/平台/自己存档, 不丢任何章节。"
        ),
    ),
    "settings_license": FeatureInfo(
        feature_id="settings_license",
        icon="🔐",
        name="License 管理 (激活/降级)",
        short_desc="3 等级 (FREE/STANDARD/PRO) + 23 功能分级 + 离线 key",
        per_use_cny="0 元 (本地离线校验)",
        compare_with=(
            "vs 不用: 不激活就锁住 PRO 功能 (一键出版 / AI critic / 高级缓存); "
            "激活后 PRO 全部解锁, 离线也能用"
        ),
        detail_note=(
            "💡 NV-XXXX-XXXX-XXXX-XXXX 格式 key, 16 字节随机 + 机器码绑定. "
            "万能 key (NV-UNIV-...) 团队/演示场景, 任何机器可用. "
            "激活后存 app_settings 表, 卸装/重装软件不丢."
        ),
    ),
}


# ============================================================
# 持久化 (kv 存在 app_setting_service 里)
# ============================================================

def is_shown(feature_id: str) -> bool:
    """是否已对用户显示过该功能的首次提醒."""
    info = FEATURE_REGISTRY.get(feature_id)
    if info is None:
        return False
    try:
        return bool(app_setting_service.get(info.shown_key, False))
    except Exception:
        return False


def mark_shown(feature_id: str) -> None:
    """标记该功能首次提醒已显示."""
    info = FEATURE_REGISTRY.get(feature_id)
    if info is None:
        return
    try:
        app_setting_service.set(info.shown_key, True)
        log.info(f"[TokensHint] marked shown: {feature_id}")
    except Exception as e:
        log.warning(f"[TokensHint] mark_shown failed for {feature_id}: {e}")


def reset_shown(feature_id: Optional[str] = None) -> None:
    """重置首次提醒标志 (供测试 / 用户手动重置)."""
    targets = [feature_id] if feature_id else list(FEATURE_REGISTRY.keys())
    for fid in targets:
        info = FEATURE_REGISTRY.get(fid)
        if info is None:
            continue
        try:
            app_setting_service.set(info.shown_key, False)
        except Exception as e:
            log.warning(f"[TokensHint] reset_shown failed for {fid}: {e}")


# ============================================================
# PriceBar: tab 顶部价格条
# ============================================================

class PriceBar(QFrame):
    """tab 顶部横向小条. 显示: 图标 + 功能名 + 单次费用 + 更新时间 + [可能过期] 警告.

    视觉:
      ┌────────────────────────────────────────────────────────┐
      │ ✨ 章节生成  约 ¥0.10 - 0.30 / 章  · 更新于 2026-06-01 │
      │       AI 写整章正文                                       │
      └────────────────────────────────────────────────────────┘

    用法:
      bar = PriceBar("generate")
      layout.insertWidget(0, bar)  # 插到 tab 顶部
    """

    def __init__(self, feature_id: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.feature_id = feature_id
        self._info: Optional[FeatureInfo] = FEATURE_REGISTRY.get(feature_id)
        if self._info is None:
            log.warning(f"[PriceBar] unknown feature_id: {feature_id}")
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.setObjectName("priceBar")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # 外层: vertical, 装主行 + 副行
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 6, 12, 6)
        outer.setSpacing(2)

        # 主行: icon + name + price + updated
        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(8)

        # 左侧: icon + name
        self._icon = QLabel("")
        self._icon.setObjectName("priceBarIcon")
        main_row.addWidget(self._icon)
        self._name = QLabel("")
        self._name.setObjectName("priceBarName")
        f = QFont()
        f.setBold(True)
        f.setPointSize(12)
        self._name.setFont(f)
        main_row.addWidget(self._name)

        self._price = QLabel("")
        self._price.setObjectName("priceBarPrice")
        main_row.addWidget(self._price)

        main_row.addStretch(1)

        # 右侧: 更新时间
        self._updated = QLabel("")
        self._updated.setObjectName("priceBarUpdated")
        main_row.addWidget(self._updated)

        outer.addLayout(main_row)

        # 副标题行: 短描述 + 警告
        self._sub = QLabel("")
        self._sub.setObjectName("priceBarSub")
        self._sub.setWordWrap(True)
        outer.addWidget(self._sub)

    def refresh(self) -> None:
        """根据当前 FeatureInfo 刷新显示."""
        if self._info is None:
            self._icon.setText("⚠️")
            self._name.setText("(未知功能)")
            self._price.setText("")
            self._sub.setText("")
            return
        info = self._info
        self._icon.setText(info.icon)
        self._name.setText(info.name)
        self._price.setText(info.per_use_cny)
        # 价格更新时间 (来自 pricing 模块)
        try:
            from app.services.pricing import list_stale_models, get_enabled_prices
            stale = list_stale_models()
            if stale:
                self._updated.setText("⚠️ 价格可能过期 (30 天未更新)")
                self._updated.setStyleSheet(f"color: {text_warn()}; font-size: 11px;")
            else:
                latest = ""
                for p in get_enabled_prices():
                    if p.price_updated_at:
                        latest = p.price_updated_at[:10]
                        break
                if latest:
                    self._updated.setText(f"价格更新于 {latest}")
                else:
                    self._updated.setText("价格更新于 未知")
                self._updated.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        except Exception as e:
            log.debug(f"[PriceBar] update info failed: {e}")
            self._updated.setText("价格更新于 未知")
            self._updated.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        # 副标题
        self._sub.setText(f"<span style='color:#8a8f98'>{info.short_desc}</span> · "
                          f"<span style='color:#8a8f98;font-size:11px'>"
                          f"价格仅供参考, 以模型厂商账单为准</span>")


# ============================================================
# FirstUsePopup: 首次开启花钱功能弹窗
# ============================================================

class FirstUsePopup(QDialog):
    """首次开启某花钱功能时弹, 详细说费用 + 对比用与不用.

    关闭后写 ui.tokens_hint.shown.<feature_id>=True 到 app settings.
    """

    def __init__(self, feature_id: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.feature_id = feature_id
        self._info: Optional[FeatureInfo] = FEATURE_REGISTRY.get(feature_id)
        if self._info is None:
            log.warning(f"[FirstUsePopup] unknown feature_id: {feature_id}")
        self._build_ui()

    def _build_ui(self) -> None:
        if self._info is None:
            self.setWindowTitle("未知功能")
            v = QVBoxLayout(self)
            v.addWidget(QLabel(f"⚠️ 未知功能: {self.feature_id}"))
            return
        info = self._info
        self.setWindowTitle(f"{info.icon} {info.name} - 首次使用提醒")
        self.setMinimumSize(540, 360)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(12)

        # 标题
        title = QLabel(f"{info.icon} <b>{info.name}</b> - 首次使用提醒")
        title_font = QFont()
        title_font.setPointSize(15)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(title)

        # 副标题
        sub = QLabel(info.short_desc)
        sub.setStyleSheet(f"color: {text_muted()};")
        root.addWidget(sub)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # 单次费用 (显眼)
        fee_box = QFrame()
        fee_box.setObjectName("popupFeeBox")
        fee_lay = QHBoxLayout(fee_box)
        fee_lay.setContentsMargins(12, 10, 12, 10)
        lbl_fee_caption = QLabel("💰 单次费用")
        lbl_fee_caption.setStyleSheet(f"color: {text_secondary()};")
        fee_lay.addWidget(lbl_fee_caption)
        fee_lay.addStretch(1)
        lbl_fee = QLabel(f"<b>{info.per_use_cny}</b>")
        lbl_fee.setTextFormat(Qt.TextFormat.RichText)
        lbl_fee.setStyleSheet(f"color: {text_warn()}; font-size: 18px; font-weight: 600;")
        fee_lay.addWidget(lbl_fee)
        root.addWidget(fee_box)

        # 对比用与不用
        cmp_label = QLabel(
            f"<b>vs 不用</b><br>"
            f"<span style='color:#c8cdd4'>{info.compare_with}</span>"
        )
        cmp_label.setTextFormat(Qt.TextFormat.RichText)
        cmp_label.setWordWrap(True)
        root.addWidget(cmp_label)

        # 备注
        note_label = QLabel(info.detail_note)
        note_label.setStyleSheet(
            "color: #6b727c; font-size: 11px; font-style: italic;"
        )
        note_label.setWordWrap(True)
        root.addWidget(note_label)

        # 偏差警告 (沿用 pricing 公共文案)
        warn_label = QLabel(get_warning_text())
        warn_label.setStyleSheet(
            "color: #888; font-size: 10px; background: rgba(232,162,58,0.05);"
            "padding: 6px; border-radius: 3px;"
        )
        warn_label.setWordWrap(True)
        root.addWidget(warn_label)

        root.addStretch(1)

        # 底部
        bottom = QHBoxLayout()
        self.chk_dont_show = QCheckBox("✅ 我已知悉, 以后不再弹此提示")
        self.chk_dont_show.setChecked(True)
        bottom.addWidget(self.chk_dont_show)
        bottom.addStretch(1)
        self.btn_ok = QPushButton("好的, 继续")
        self.btn_ok.setObjectName("primaryAction")
        self.btn_ok.clicked.connect(self._on_ok)
        bottom.addWidget(self.btn_ok)
        root.addLayout(bottom)

    def _on_ok(self) -> None:
        if self.chk_dont_show.isChecked() and self._info is not None:
            mark_shown(self.feature_id)
        self.accept()

    def accept(self) -> None:  # type: ignore[override]
        # 用户点 X / 关闭按钮时, 也按 checkbox 决定是否标记
        if self.chk_dont_show.isChecked() and self._info is not None:
            mark_shown(self.feature_id)
        super().accept()


def show_first_use_if_needed(
    feature_id: str, parent: Optional[QWidget] = None,
) -> Optional[FirstUsePopup]:
    """首次开启该功能时弹, 已弹过返回 None."""
    if feature_id not in FEATURE_REGISTRY:
        return None
    if is_shown(feature_id):
        return None
    dlg = FirstUsePopup(feature_id, parent)
    dlg.exec()
    return dlg


# ============================================================
# 自我测试 (直接 python app/ui/tokens_hint.py 跑)
# ============================================================

if __name__ == "__main__":
    print("FEATURE_REGISTRY keys:", list(FEATURE_REGISTRY.keys()))
    for fid, info in FEATURE_REGISTRY.items():
        print(f"  {fid}: {info.icon} {info.name} ({info.per_use_cny})")
    print(f"\nKEYS:")
    for fid, info in FEATURE_REGISTRY.items():
        print(f"  {info.shown_key}")
