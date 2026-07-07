"""
Guide Panel Widget (v3.5.2 + v3.6)

显示 Story Engine 收集的所有 Guide, 按 priority 倒序排列.
v3.6: 增加 Decision History 区块——显示上轮哪些 Guide 被采纳/忽略.

设计:
- 低 confidence (< 0.5) 的 Guide 标灰, 提示"作者可忽略"
- 高 priority 用颜色强调
- 每条 Guide 可折叠/展开, 默认展开
- 显示 reason 和 evidence_ids 让 AI 决策可追溯
- v3.6: 底部展示 Decision 历史 (adopted/ignored/modified)
"""
from __future__ import annotations
from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QPalette
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QSizePolicy,
)


def _priority_color(priority: float) -> str:
    """priority → 颜色 (0-1)."""
    if priority >= 0.75:
        return "#d97757"  # orange-red (高)
    if priority >= 0.5:
        return "#d4a157"  # amber (中)
    return "#8a8a8a"  # gray (低)


def _confidence_alpha(confidence: float) -> float:
    """confidence → 透明度 0.3-1.0."""
    if confidence >= 0.7:
        return 1.0
    if confidence >= 0.5:
        return 0.85
    return 0.55  # 低置信, 标灰


class GuidePanel(QWidget):
    """Story Guidance 面板.

    使用:
        panel = GuidePanel()
        panel.set_guides(collect_guides_dict(unit_id))
        panel.set_decisions(decision_service.summary(unit_id))
        layout.addWidget(panel)
    """
    guide_accepted = Signal(int, str)     # (index, action_label)
    guide_dismissed = Signal(int)         # index

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._guides: list[dict] = []
        self._decisions_info: dict = {}   # v3.6
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # 标题
        title = QLabel("🧭 Story Guidance")
        title.setStyleSheet("font-size: 14px; font-weight: 700; padding: 4px 0;")
        outer.addWidget(title)

        # 内容容器 (Guide 卡片)
        self._content = QVBoxLayout()
        self._content.setSpacing(6)
        outer.addLayout(self._content)

        # 空状态
        self._empty_label = QLabel("暂无 Guide。collect_guides() 将返回各模块建议。")
        from app.ui.theme import text_chip
        self._empty_label.setStyleSheet(f"color: {text_chip()}; font-style: italic; padding: 16px;")
        self._content.addWidget(self._empty_label)

        # v3.6: Decision History 区块
        self._decision_section = QFrame()
        self._decision_section.setFrameShape(QFrame.Shape.StyledPanel)
        self._decision_section.setStyleSheet(
            "QFrame { background: rgba(50, 50, 60, 0.8); "
            "border: 1px solid #444; border-radius: 4px; padding: 8px; }"
        )
        self._decision_layout = QVBoxLayout(self._decision_section)
        self._decision_layout.setContentsMargins(8, 6, 8, 6)
        self._decision_layout.setSpacing(4)
        self._decision_section.hide()
        outer.addWidget(self._decision_section)

        outer.addStretch(1)

    def set_guides(self, guides: list[dict], *, decisions: dict | None = None) -> None:
        """设置 Guide 列表 (来自 collect_guides_dict)."""
        self._guides = list(guides)
        if decisions is not None:
            self._decisions_info = decisions
        self._rebuild()

    def set_decisions(self, summary: dict) -> None:
        """v3.6: 设置上轮 Decision 汇总 (来自 decision_service.summary)."""
        self._decisions_info = summary
        self._rebuild_decision_section()

    def _rebuild_decision_section(self) -> None:
        while self._decision_layout.count():
            item = self._decision_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self._decisions_info or not self._decisions_info.get("total"):
            self._decision_section.hide()
            return

        info = self._decisions_info
        total = info.get("total", 0)
        adopted = info.get("adopted", 0)
        ignored = info.get("ignored", 0)
        modified = info.get("modified", 0)

        title = QLabel("📋 Decision History (上轮决策)")
        from app.ui.theme import text_card_label
        title.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {text_card_label()};")
        self._decision_layout.addWidget(title)

        # 汇总条
        summary_line = QLabel(
            f"共 {total} 条 Guide: "
            f"<span style='color:#72b86a;font-weight:600;'>采纳 {adopted}</span> / "
            f"<span style='color:#d4a157;font-weight:600;'>修改 {modified}</span> / "
            f"<span style='color:#c06060;font-weight:600;'>忽略 {ignored}</span>"
        )
        from app.ui.theme import text_chip
        summary_line.setStyleSheet(f"font-size: 11px; color: {text_chip()}; padding: 2px 0;")
        self._decision_layout.addWidget(summary_line)

        # 按 source 细分
        by_source = info.get("by_source", {})
        if by_source:
            src_lines = []
            for src, counts in sorted(by_source.items()):
                a, i, m = counts.get("adopted", 0), counts.get("ignored", 0), counts.get("modified", 0)
                src_lines.append(f"[{src}] 采纳{a} 忽略{i} 修改{m}")
            if src_lines:
                detail = QLabel("  " + "  |  ".join(src_lines))
                from app.ui.theme import text_chip_dim
                detail.setStyleSheet(f"font-size: 10px; color: {text_chip_dim()};")
                detail.setWordWrap(True)
                self._decision_layout.addWidget(detail)

        self._decision_section.show()

    def _rebuild(self) -> None:
        # 清理旧 widgets
        while self._content.count():
            item = self._content.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self._guides:
            self._content.addWidget(self._empty_label)
            return

        # 按 priority 倒序显示 (collect_guides 已排序, 这里再排一次保证 UI 顺序)
        sorted_guides = sorted(self._guides, key=lambda g: -g.get("priority", 0))

        for idx, g in enumerate(sorted_guides):
            card = self._build_guide_card(idx, g)
            self._content.addWidget(card)

        # v3.6: 刷新 Decision 区块
        self._rebuild_decision_section()

    def _build_guide_card(self, idx: int, g: dict) -> QFrame:
        """构建单条 Guide 卡片."""
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)

        priority = float(g.get("priority", 0.5))
        confidence = float(g.get("confidence", 0.7))
        scope = g.get("scope", "Unit")
        source = g.get("source", "?")
        advice = g.get("advice", "")
        reason = g.get("reason", "")
        evidence = g.get("evidence_ids", [])
        actions = g.get("possible_actions", [])

        # 颜色 + 透明度
        color = _priority_color(priority)
        alpha = _confidence_alpha(confidence)
        card.setStyleSheet(
            f"QFrame {{ "
            f"  background: rgba(60, 60, 70, {alpha}); "
            f"  border-left: 4px solid {color}; "
            f"  border-radius: 4px; "
            f"  padding: 8px; "
            f"}}"
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # 头部: source + priority + confidence
        header = QHBoxLayout()
        src_label = QLabel(f"[{source}]")
        src_label.setStyleSheet(f"color: {color}; font-weight: 700; font-size: 12px;")
        header.addWidget(src_label)

        scope_label = QLabel(f"scope={scope}")
        from app.ui.theme import text_chip
        scope_label.setStyleSheet(f"color: {text_chip()}; font-size: 11px;")
        header.addWidget(scope_label)

        conf_label = QLabel(f"confidence={confidence:.2f}")
        conf_color = "#aaa"
        if confidence < 0.5:
            conf_color = "#888"
            conf_label.setText(f"confidence={confidence:.2f} ⚠️ AI 不太确定, 可忽略")
        conf_label.setStyleSheet(f"color: {conf_color}; font-size: 11px;")
        header.addWidget(conf_label)

        header.addStretch(1)

        pri_label = QLabel(f"priority {priority:.2f}")
        pri_label.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600;")
        header.addWidget(pri_label)

        layout.addLayout(header)

        # advice
        advice_label = QLabel(advice)
        advice_label.setWordWrap(True)
        from app.ui.theme import text_card_emphasis
        advice_label.setStyleSheet(f"color: {text_card_emphasis()}; font-size: 13px; padding: 4px 0;")
        layout.addWidget(advice_label)

        # reason (如存在)
        if reason:
            reason_label = QLabel(f"💭 {reason}")
            reason_label.setWordWrap(True)
            from app.ui.theme import text_card_label
            reason_label.setStyleSheet(f"color: {text_card_label()}; font-size: 11px; padding: 2px 0;")
            layout.addWidget(reason_label)

        # evidence (如存在)
        if evidence:
            ev_text = "🔗 " + ", ".join(str(e) for e in evidence[:5])
            if len(evidence) > 5:
                ev_text += f" (+{len(evidence) - 5} more)"
            ev_label = QLabel(ev_text)
            from app.ui.theme import text_chip_secondary
            ev_label.setStyleSheet(f"color: {text_chip_secondary()}; font-size: 10px; padding: 2px 0;")
            ev_label.setWordWrap(True)
            ev_label.setWordWrap(True)
            layout.addWidget(ev_label)

        # actions
        if actions:
            action_row = QHBoxLayout()
            action_row.setSpacing(4)
            for action in actions:
                if isinstance(action, dict):
                    label = action.get("label", "?")
                else:
                    label = str(action)
                btn = QPushButton(label)
                btn.setStyleSheet(
                    "QPushButton { "
                    "  background: #444; "
                    "  color: #ddd; "
                    "  border: 1px solid #666; "
                    "  border-radius: 3px; "
                    "  padding: 2px 8px; "
                    "  font-size: 11px; "
                    "} "
                    "QPushButton:hover { background: #555; }"
                )
                btn.clicked.connect(
                    lambda _checked=False, i=idx, lbl=label: self.guide_accepted.emit(i, lbl)
                )
                action_row.addWidget(btn)
            action_row.addStretch(1)
            layout.addLayout(action_row)

        # Dismiss 按钮
        dismiss_row = QHBoxLayout()
        dismiss_row.addStretch(1)
        dismiss_btn = QPushButton("忽略此 Guide")
        dismiss_btn.setStyleSheet(
            "QPushButton { "
            "  color: #888; "
            "  border: none; "
            "  font-size: 10px; "
            "  padding: 2px 8px; "
            "} "
            "QPushButton:hover { color: #ccc; }"
        )
        dismiss_btn.clicked.connect(lambda _checked=False, i=idx: self.guide_dismissed.emit(i))
        dismiss_row.addWidget(dismiss_btn)
        layout.addLayout(dismiss_row)

        return card