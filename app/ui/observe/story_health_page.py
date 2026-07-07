"""
故事健康页 (v4.0)

五维可视化: 压力 / 钩子 / 读者 / 情绪 / 一致性.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QHBoxLayout,
)
from app.ui.theme import score_value, text_hint, text_meta, text_muted


class StoryHealthPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project_id: str = ""
        self._unit_id: str = ""
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("\u6545\u4e8b\u5065\u5eb7")
        title.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #cdd6f4;"
        )
        layout.addWidget(title)

        subtitle = QLabel("\u4e94\u7ef4\u5065\u5eb7\u5ea6: \u538b\u529b \u00b7 \u94a9\u5b50 \u00b7 \u8bfb\u8005 \u00b7 \u60c5\u7eea \u00b7 \u4e00\u81f4\u6027")
        subtitle.setStyleSheet(f"color: {text_muted()}; font-size: 12px;")
        layout.addWidget(subtitle)

        cards = QHBoxLayout()
        cards.setSpacing(12)

        dims = [
            ("pressure", "\U0001f4ca \u538b\u529b", "\u53d9\u4e8b\u7d27\u8feb\u7a0b\u5ea6"),
            ("hook", "\U0001f3a3 \u94a9\u5b50", "\u5f00\u653e / \u5df2\u56de\u6536\u94a9\u5b50\u6bd4\u4f8b"),
            ("reader", "\U0001f441 \u8bfb\u8005", "\u6d41\u5931\u98ce\u9669\u533a\u57df"),
            ("emotion", "\U0001f4a2 \u60c5\u7eea", "\u60c5\u7eea\u66f2\u7ebf\u5e73\u8861"),
            ("consistency", "\U0001f517 \u4e00\u81f4\u6027", "\u4e16\u754c/\u903b\u8f91\u4e00\u81f4\u6027"),
        ]

        self._dim_labels: dict[str, QLabel] = {}
        for dim_id, dim_title, dim_hint in dims:
            gb = QGroupBox()
            gl = QVBoxLayout(gb)
            gl.setContentsMargins(10, 10, 10, 10)
            gl.setSpacing(4)

            header = QLabel(dim_title)
            header.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {score_value()};")
            gl.addWidget(header)

            hint = QLabel(dim_hint)
            hint.setStyleSheet(f"color: {text_hint()}; font-size: 10px;")
            gl.addWidget(hint)

            val = QLabel("\u2014")
            val.setStyleSheet(f"color: {text_meta()}; font-size: 14px; padding: 8px 0;")
            gl.addWidget(val)
            self._dim_labels[dim_id] = val

            gb.setStyleSheet(
                "QGroupBox { background: #1e1e2e; border: 1px solid #313244; "
                "border-radius: 6px; }"
            )
            cards.addWidget(gb)

        layout.addLayout(cards)
        layout.addStretch(1)

    def set_project(self, project: dict) -> None:
        self._project_id = project.get("id", "")
        self._refresh()

    def set_unit(self, unit_id: str) -> None:
        self._unit_id = unit_id
        self._refresh()

    def _refresh(self) -> None:
        pid = self._project_id or ""

        try:
            from app.services.pressure import get_pressure
            pres = get_pressure(self._unit_id) if self._unit_id else {}
            zone = pres.get("zone", "green")
            val = pres.get("pressure", 0)
            zone_labels = {"green": "\u5b89\u5168", "yellow": "\u8b66\u89c9", "orange": "\u5371\u9669", "red": "\u7d27\u6025"}
            color = {"green": "#72b86a", "yellow": "#d4a157", "orange": "#d4845a", "red": "#c06060"}.get(zone, "#6c7086")
            self._dim_labels["pressure"].setText(
                f"<span style='color:{color};font-weight:700;font-size:24px;'>{val}</span> \u2014 {zone_labels.get(zone, zone.upper())}"
            )
        except Exception:
            self._dim_labels["pressure"].setText("\u2014")

        try:
            from app.services import unit_hook_service as _hook_svc
            hooks = _hook_svc.list_for_project(pid) if pid else []
            plants = sum(1 for h in hooks if getattr(h, "hook_type", "") == "plant")
            payoffs = sum(1 for h in hooks if getattr(h, "hook_type", "") == "payoff")
            self._dim_labels["hook"].setText(f"\u57cb\u8bbe: {plants} \u00b7 \u56de\u6536: {payoffs}")
        except Exception:
            self._dim_labels["hook"].setText("\u2014")

        try:
            self._dim_labels["reader"].setText("\u2014 (\u4fdd\u7559\u6570\u636e)")
        except Exception:
            self._dim_labels["reader"].setText("\u2014")

        try:
            self._dim_labels["emotion"].setText("\u2014 (\u60c5\u7eea\u66f2\u7ebf)")
        except Exception:
            self._dim_labels["emotion"].setText("\u2014")

        try:
            self._dim_labels["consistency"].setText("\u2014 (\u4e00\u81f4\u6027\u626b\u63cf)")
        except Exception:
            self._dim_labels["consistency"].setText("\u2014")
