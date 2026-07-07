"""
引导图谱页 (v4.0)

可视化 Guide 之间的 conflict/support 关系.
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTextEdit,
)
from app.ui.theme import text_muted


class GuideGraphPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project_id: str = ""
        self._unit_id: str = ""
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("\u5f15\u5bfc\u56fe\u8c31")
        title.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: #cdd6f4;"
        )
        layout.addWidget(title)

        subtitle = QLabel("Guide \u4e4b\u95f4\u7684\u51b2\u7a81 / \u652f\u6301\u5173\u7cfb\u56fe")
        subtitle.setStyleSheet(f"color: {text_muted()}; font-size: 12px;")
        layout.addWidget(subtitle)

        self._graph_view = QTextEdit()
        self._graph_view.setReadOnly(True)
        self._graph_view.setStyleSheet(
            "QTextEdit { background: #1e1e2e; border: 1px solid #313244; "
            "border-radius: 4px; color: #cdd6f4; font-size: 13px; padding: 12px; }"
        )
        layout.addWidget(self._graph_view, 1)

    def set_project(self, project: dict) -> None:
        self._project_id = project.get("id", "")
        self._refresh()

    def set_unit(self, unit_id: str) -> None:
        self._unit_id = unit_id
        self._refresh()

    def _refresh(self) -> None:
        if not self._unit_id:
            self._graph_view.setPlainText("\u8bf7\u9009\u62e9\u5355\u5143\u4ee5\u67e5\u770b\u5f15\u5bfc\u56fe\u8c31\u3002")
            return

        try:
            from app.core.types import collect_guides
            from app.services.guide_graph import analyze, build_graph_block
            guides = collect_guides(self._unit_id, project_id=self._project_id)
            if not guides:
                self._graph_view.setPlainText("\u6b64\u5355\u5143\u6ca1\u6709\u53ef\u7528\u7684\u5f15\u5bfc\u3002")
                return

            graph = analyze(guides)
            lines = [f"## \u8282\u70b9: {len(guides)} \u6761\u5f15\u5bfc (\u6765\u81ea 9 \u4e2a\u6a21\u5757)\n"]

            for g in guides:
                conflicts_str = ", ".join(g.conflicts_with[:3] or ["\u65e0"])
                supports_str = ", ".join(g.supports[:3] or ["\u65e0"])
                lines.append(
                    f"[{g.source}] \u4f18\u5148\u7ea7={g.priority:.2f} \u7f6e\u4fe1\u5ea6={g.confidence:.2f}\n"
                    f"  \u5efa\u8bae: {g.advice[:80]}\n"
                    f"  \u51b2\u7a81: {conflicts_str}\n"
                    f"  \u652f\u6301:  {supports_str}\n"
                )

            if graph.edges:
                lines.append("\n## \u56fe\u8fb9\n")
                for e in graph.edges:
                    icon = "\u26a1" if e.is_conflict else "\u2705"
                    lines.append(f"  {icon} {e.guide_a[:8]} \u2194 {e.guide_b[:8]} ({e.relation})")

            prompt_block = build_graph_block(graph)
            if prompt_block:
                lines.append(f"\n---\n{prompt_block}")

            self._graph_view.setPlainText("\n".join(lines))
        except Exception as e:
            self._graph_view.setPlainText(f"\u9519\u8bef: {e}")
