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
    ("goal", "🎯 当前目标"),
    ("guides", "📋 活跃引导"),
    ("pressure", "📊 叙事压力"),
    ("hooks", "🎣 钩子"),
    ("memory", "🧠 记忆"),
]


class StoryHUD(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._unit_id: str = ""
        self._project_id: str = ""
        self._build()
        self._subscribe_events()

    def _subscribe_events(self) -> None:
        """订阅 EventBus 事件，实现响应式刷新."""
        try:
            from app.core.event_bus import get_bus, Events
            bus = get_bus()
            bus.subscribe(Events.STORY_STATE_UPDATED, self._on_state_updated)
        except Exception:
            pass

    def _on_state_updated(self, event) -> None:
        """收到状态更新事件， marshal 到主线程刷新."""
        data = event.data if hasattr(event, "data") else event
        event_unit_id = data.get("unit_id", "") if isinstance(data, dict) else ""
        if event_unit_id == self._unit_id:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._refresh)

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
            label = QLabel("—")
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
                label.setText("—")
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
            pov = getattr(u, "pov_character", "") or "(任意)"
            if goal:
                self._section_labels["goal"].setText(f"目标: {goal}\n视角: {pov}")
                from app.ui.theme import score_value
                self._section_labels["goal"].setStyleSheet(f"color: {score_value()}; font-size: 11px; border: none;")
            else:
                self._section_labels["goal"].setText("(未设置目标)")
        except Exception:
            self._section_labels["goal"].setText("—")

    def _refresh_guides(self) -> None:
        try:
            from app.core.types import collect_guides
            guides = collect_guides(self._unit_id, project_id=self._project_id)
            if not guides:
                self._section_labels["guides"].setText("(无引导)")
                return
            top3 = sorted(guides, key=lambda g: -g.priority)[:3]
            lines = []
            for g in top3:
                src = g.source if hasattr(g, "source") else "?"
                adv = (g.advice if hasattr(g, "advice") else "")[:60]
                pri = g.priority if hasattr(g, "priority") else 0.5
                lines.append(f"[{src}] p={pri:.2f} {adv}")
            self._section_labels["guides"].setText("\n".join(lines) if lines else "(无引导)")
            from app.ui.theme import text_meta
            self._section_labels["guides"].setStyleSheet(f"color: {text_meta()}; font-size: 11px; border: none;")
        except Exception as e:
            self._section_labels["guides"].setText(f"(错误: {e})")

    def _refresh_pressure(self) -> None:
        try:
            from app.services import pressure
            # 尝试获取最新的压力数据
            latest = pressure.get_latest(self._project_id) if self._project_id else None
            if latest:
                zone = getattr(latest, "zone", "green")
                val = getattr(latest, "pressure", 0)
                zone_labels = {"green": "安全", "yellow": "警觉", "orange": "危险", "red": "紧急"}
                color = {"green": "#72b86a", "yellow": "#d4a157", "orange": "#d4845a", "red": "#c06060"}.get(zone, "#6c7086")
                self._section_labels["pressure"].setText(
                    f"<span style='color:{color};font-weight:700;'>"
                    f"{zone_labels.get(zone, zone.upper())}</span> ({val})"
                )
            else:
                # 如果没有数据，计算当前单元的压力
                if self._unit_id and self._project_id:
                    pressure_val = pressure.compute_pressure(
                        self._project_id,
                        self._unit_id,
                        active_hooks=0,
                        open_promises=0,
                        unresolved_subplots=0,
                    )
                    zone = pressure.compute_zone(pressure_val)
                    zone_labels = {"green": "安全", "yellow": "警觉", "orange": "危险", "red": "紧急"}
                    color = {"green": "#72b86a", "yellow": "#d4a157", "orange": "#d4845a", "red": "#c06060"}.get(zone, "#6c7086")
                    self._section_labels["pressure"].setText(
                        f"<span style='color:{color};font-weight:700;'>"
                        f"{zone_labels.get(zone, zone.upper())}</span> ({pressure_val})"
                    )
                else:
                    self._section_labels["pressure"].setText("(无数据)")
        except Exception as e:
            self._section_labels["pressure"].setText(f"(错误: {e})")

    def _refresh_hooks(self) -> None:
        try:
            from app.services import unit_hook_service as _hook_svc
            hooks = _hook_svc.list_for_unit(self._unit_id)
            open_hooks = [h for h in hooks if getattr(h, "hook_type", "") == "plant"]
            if open_hooks:
                lines = []
                for h in open_hooks[:5]:
                    desc = getattr(h, "description", "")[:50]
                    lines.append(f"• {desc}")
                self._section_labels["hooks"].setText("\n".join(lines))
                from app.ui.theme import text_meta
                self._section_labels["hooks"].setStyleSheet(f"color: {text_meta()}; font-size: 11px; border: none;")
            else:
                self._section_labels["hooks"].setText("(无未回收钩子)")
        except Exception:
            self._section_labels["hooks"].setText("—")

    def _refresh_memory(self) -> None:
        self._section_labels["memory"].setText("(记忆快照)")
        from app.ui.theme import text_muted
        self._section_labels["memory"].setStyleSheet(f"color: {text_muted()}; font-size: 11px; border: none;")
