"""
Story HUD Tab — 故事仪表盘

从真实 StoryState 读取数据，动态显示。
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QGridLayout, QProgressBar, QScrollArea,
)
from PySide6.QtCore import Qt
from app.ui.theme import (
    text_primary,
    text_secondary,
    border_color,
    surface_bg,
    text_accent,
    text_warn,
)

# hud_tab 原稿通篇用 tokens.X，但 theme 并未导出 tokens。
# 这里用真实 theme 函数补一个轻量 shim，避免实例化时 NameError。
class _Tokens:
    font_title = 18
    text = text_primary()
    text_secondary = text_secondary()
    border = border_color()
    surface = surface_bg()
    primary = text_accent()
    warning = text_warn()


tokens = _Tokens()


class HUDTab(QWidget):
    """故事 HUD 仪表盘 — 从 StoryState 动态读取."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = None
        self._build()

    def _build(self):
        # 滚动区域
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # 标题
        title = QLabel("故事仪表盘")
        title.setStyleSheet(f"font-size: {tokens.font_title}px; font-weight: bold; color: {tokens.text};")
        layout.addWidget(title)

        # 状态网格
        grid = QGridLayout()
        grid.setSpacing(12)

        # 进度卡片
        progress_group = QGroupBox("写作进度")
        progress_group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {tokens.border};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 16px;
                font-weight: bold;
                color: {tokens.text};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
        """)
        pg_layout = QVBoxLayout(progress_group)
        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(0)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {tokens.surface};
                border: none;
                border-radius: 4px;
                height: 8px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {tokens.primary};
                border-radius: 4px;
            }}
        """)
        self._progress_label = QLabel("未加载")
        self._progress_label.setStyleSheet(f"color: {tokens.text_secondary};")
        pg_layout.addWidget(self._progress_bar)
        pg_layout.addWidget(self._progress_label)
        grid.addWidget(progress_group, 0, 0)

        # 角色卡片
        chars_group = QGroupBox("角色状态")
        chars_group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {tokens.border};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 16px;
                font-weight: bold;
                color: {tokens.text};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
        """)
        cg_layout = QVBoxLayout(chars_group)
        self._chars_label = QLabel("无角色数据")
        self._chars_label.setStyleSheet(f"color: {tokens.text_secondary};")
        self._chars_label.setWordWrap(True)
        cg_layout.addWidget(self._chars_label)
        grid.addWidget(chars_group, 0, 1)

        # 伏笔卡片
        hooks_group = QGroupBox("伏笔管理")
        hooks_group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {tokens.border};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 16px;
                font-weight: bold;
                color: {tokens.text};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
        """)
        hg_layout = QVBoxLayout(hooks_group)
        self._hooks_label = QLabel("无伏笔数据")
        self._hooks_label.setStyleSheet(f"color: {tokens.warning};")
        self._hooks_label.setWordWrap(True)
        hg_layout.addWidget(self._hooks_label)
        grid.addWidget(hooks_group, 1, 0)

        # 压力卡片
        pressure_group = QGroupBox("叙事压力")
        pressure_group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {tokens.border};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 16px;
                font-weight: bold;
                color: {tokens.text};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
        """)
        prg_layout = QVBoxLayout(pressure_group)
        self._pressure_label = QLabel("无压力数据")
        self._pressure_label.setStyleSheet(f"color: {tokens.text_secondary};")
        self._pressure_label.setWordWrap(True)
        prg_layout.addWidget(self._pressure_label)
        grid.addWidget(pressure_group, 1, 1)

        # 世界状态卡片
        world_group = QGroupBox("世界状态")
        world_group.setStyleSheet(f"""
            QGroupBox {{
                border: 1px solid {tokens.border};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 16px;
                font-weight: bold;
                color: {tokens.text};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }}
        """)
        wg_layout = QVBoxLayout(world_group)
        self._world_label = QLabel("无世界数据")
        self._world_label.setStyleSheet(f"color: {tokens.text_secondary};")
        self._world_label.setWordWrap(True)
        wg_layout.addWidget(self._world_label)
        grid.addWidget(world_group, 2, 0, 1, 2)

        layout.addLayout(grid)
        layout.addStretch()

        scroll.setWidget(container)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def set_state(self, state):
        """从 StoryState 动态更新 HUD."""
        self._state = state
        if state is None:
            return
        self._update_progress(state)
        self._update_characters(state)
        self._update_hooks(state)
        self._update_world(state)

    def _update_progress(self, state):
        if state.total_steps > 0:
            pct = int(state.current_step / state.total_steps * 100)
            self._progress_bar.setValue(pct)
            self._progress_label.setText(
                f"步骤 {state.current_step}/{state.total_steps} ({pct}%)"
            )
        else:
            self._progress_bar.setValue(0)
            self._progress_label.setText("未设定步骤")

    def _update_characters(self, state):
        if not state.characters:
            self._chars_label.setText("无角色数据")
            return
        lines = []
        for name, char in state.characters.items():
            traits = ", ".join(f"{k}={v}" for k, v in list(char.traits.items())[:3])
            lines.append(f"{name}: {traits}")
            if char.location:
                lines.append(f"  位置: {char.location}")
        self._chars_label.setText("\n".join(lines))

    def _update_hooks(self, state):
        active = state.active_hooks()
        pending = state.pending_commitments()
        resolved = [h for h in state.hooks if h.is_resolved]

        lines = []
        if active:
            lines.append(f"活跃伏笔: {len(active)}")
            for h in active[:5]:
                lines.append(f"  · {h.description[:40]}")
        if pending:
            lines.append(f"\n待履行承诺: {len(pending)}")
            for c in pending[:3]:
                lines.append(f"  · {c.description[:40]}")
        if resolved:
            lines.append(f"\n已解决: {len(resolved)}")

        self._hooks_label.setText("\n".join(lines) if lines else "无伏笔数据")

    def _update_world(self, state):
        w = state.world
        lines = []
        if w.time_label:
            lines.append(f"时间: {w.time_label}")
        if w.location:
            lines.append(f"地点: {w.location}")
        if w.weather:
            lines.append(f"天气: {w.weather}")
        if w.active_factions:
            lines.append(f"势力: {', '.join(w.active_factions[:3])}")
        if w.custom:
            for k, v in list(w.custom.items())[:3]:
                lines.append(f"{k}: {v}")
        self._world_label.setText("\n".join(lines) if lines else "无世界数据")
