"""
Story HUD Widget (v4.0)

右侧固定面板, 永远显示 Unit 的实时状态:
  - 当前目标
  - 活跃引导 (collect_guides)
  - 叙事压力 (narrative_pressure)
  - 钩子 (open hooks)
  - 记忆快照
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QScrollArea,
)

HUD_SECTIONS = [
    ("goal", "\U0001f3af \u5f53\u524d\u76ee\u6807"),
    ("guides", "\U0001f9ed \u6d3b\u8dc3\u5f15\u5bfc"),
    ("pressure", "\U0001f4ca \u53d9\u4e8b\u538b\u529b"),
    ("hooks", "\U0001f3a3 \u94a9\u5b50"),
    ("memory", "\U0001f9e0 \u8bb0\u5fc6"),
]


class StoryHUD(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._unit_id: str = ""
        self._project_id: str = ""
        self._build()

    def _build(self) -> None:
        self.setMinimumWidth(240)
        self.setMaximumWidth(320)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        title = QLabel("  Story HUD")
        title.setStyleSheet(
            "font-size: 13px; font-weight: 700; color: #cdd6f4; padding: 8px 0 4px 0;"
        )
        outer.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )

        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(6, 4, 6, 4)
        self._content_layout.setSpacing(6)

        self._section_widgets: dict[str, QGroupBox] = {}
        self._section_labels: dict[str, QLabel] = {}

        for sec_id, sec_title in HUD_SECTIONS:
            gb = QGroupBox(sec_title)
            gb.setStyleSheet(
                "QGroupBox { background: #1e1e2e; border: 1px solid #313244; "
                "border-radius: 4px; margin-top: 8px; padding-top: 12px; "
                "color: #a6adc8; font-weight: 600; }"
                "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
            )
            gl = QVBoxLayout(gb)
            gl.setContentsMargins(8, 4, 8, 8)
            label = QLabel("\u2014")
            label.setWordWrap(True)
            from app.ui.theme import text_muted
            label.setStyleSheet(f"color: {text_muted()}; font-size: 11px; border: none;")
            gl.addWidget(label)
            self._section_widgets[sec_id] = gb
            self._section_labels[sec_id] = label
            self._content_layout.addWidget(gb)

        self._content_layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    def set_unit(self, unit_id: str, project_id: str = "") -> None:
        self._unit_id = unit_id
        self._project_id = project_id
        self._refresh()

    def _refresh(self) -> None:
        if not self._unit_id:
            for label in self._section_labels.values():
                label.setText("\u2014")
            return

        self._refresh_goal()
        self._refresh_guides()
        self._refresh_pressure()
        self._refresh_hooks()
        self._refresh_memory()

    def _refresh_goal(self) -> None:
        try:
            from app.services import story_unit_service_v2 as _unit_svc
            u = _unit_svc.get(self._unit_id)
            goal = getattr(u, "unit_goal", "") or ""
            pov = getattr(u, "pov_character", "") or "(\u4efb\u610f)"
            if goal:
                self._section_labels["goal"].setText(f"\u76ee\u6807: {goal}\n\u89c6\u89d2: {pov}")
                from app.ui.theme import score_value
                self._section_labels["goal"].setStyleSheet(f"color: {score_value()}; font-size: 11px; border: none;")
            else:
                self._section_labels["goal"].setText("(\u672a\u8bbe\u7f6e\u76ee\u6807)")
        except Exception:
            self._section_labels["goal"].setText("\u2014")

    def _refresh_guides(self) -> None:
        try:
            from app.core.types import collect_guides
            guides = collect_guides(self._unit_id, project_id=self._project_id)
            if not guides:
                self._section_labels["guides"].setText("(\u65e0\u5f15\u5bfc)")
                return
            top3 = sorted(guides, key=lambda g: -g.priority)[:3]
            lines = []
            for g in top3:
                src = g.source if hasattr(g, "source") else "?"
                adv = (g.advice if hasattr(g, "advice") else "")[:60]
                pri = g.priority if hasattr(g, "priority") else 0.5
                lines.append(f"[{src}] p={pri:.2f} {adv}")
            self._section_labels["guides"].setText("\n".join(lines) if lines else "(\u65e0\u5f15\u5bfc)")
            from app.ui.theme import text_meta
            self._section_labels["guides"].setStyleSheet(f"color: {text_meta()}; font-size: 11px; border: none;")
        except Exception as e:
            self._section_labels["guides"].setText(f"(\u9519\u8bef: {e})")

    def _refresh_pressure(self) -> None:
        try:
            from app.services.pressure import get_pressure
            pres = get_pressure(self._unit_id)
            if pres:
                zone = pres.get("zone", "green")
                val = pres.get("pressure", 0)
                zone_labels = {"green": "\u5b89\u5168", "yellow": "\u8b66\u89c9", "orange": "\u5371\u9669", "red": "\u7d27\u6025"}
                color = {"green": "#72b86a", "yellow": "#d4a157", "orange": "#d4845a", "red": "#c06060"}.get(zone, "#6c7086")
                self._section_labels["pressure"].setText(
                    f"<span style='color:{color};font-weight:700;'>"
                    f"{zone_labels.get(zone, zone.upper())}</span> ({val})"
                )
            else:
                self._section_labels["pressure"].setText("(\u65e0\u6570\u636e)")
        except Exception:
            self._section_labels["pressure"].setText("\u2014")

    def _refresh_hooks(self) -> None:
        try:
            from app.services import unit_hook_service as _hook_svc
            hooks = _hook_svc.list_for_unit(self._unit_id)
            open_hooks = [h for h in hooks if getattr(h, "hook_type", "") == "plant"]
            if open_hooks:
                lines = []
                for h in open_hooks[:5]:
                    desc = getattr(h, "description", "")[:50]
                    lines.append(f"\u2022 {desc}")
                self._section_labels["hooks"].setText("\n".join(lines))
                from app.ui.theme import text_meta
                self._section_labels["hooks"].setStyleSheet(f"color: {text_meta()}; font-size: 11px; border: none;")
            else:
                self._section_labels["hooks"].setText("(\u65e0\u672a\u56de\u6536\u94a9\u5b50)")
        except Exception:
            self._section_labels["hooks"].setText("\u2014")

    def _refresh_memory(self) -> None:
        self._section_labels["memory"].setText("(\u8bb0\u5fc6\u5feb\u7167)")
        from app.ui.theme import text_muted
        self._section_labels["memory"].setStyleSheet(f"color: {text_muted()}; font-size: 11px; border: none;")
