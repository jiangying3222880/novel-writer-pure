"""
Story HUD Tab — 故事仪表盘

显示故事状态概览：角色、伏笔、压力、进度。
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGroupBox,
    QGridLayout, QProgressBar,
)
from PySide6.QtCore import Qt
from app.ui.theme_v4 import get_theme_v4


class HUDTab(QWidget):
    """故事 HUD 仪表盘."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        tokens = get_theme_v4().tokens

        # 标题
        title = QLabel("故事仪表盘")
        title.setStyleSheet(f"font-size: {tokens.font_title}px; font-weight: bold;")
        layout.addWidget(title)

        # 状态网格
        grid = QGridLayout()
        grid.setSpacing(12)

        # 进度卡片
        progress_group = QGroupBox("写作进度")
        pg_layout = QVBoxLayout(progress_group)
        self._progress_bar = QProgressBar()
        self._progress_bar.setValue(60)
        self._progress_label = QLabel("3/5 步骤 (60%)")
        pg_layout.addWidget(self._progress_bar)
        pg_layout.addWidget(self._progress_label)
        grid.addWidget(progress_group, 0, 0)

        # 角色卡片
        chars_group = QGroupBox("角色状态")
        cg_layout = QVBoxLayout(chars_group)
        self._chars_label = QLabel("林凡: 金丹初期\\n韩枫: 金丹后期\\n慕容雪: 筑基期")
        self._chars_label.setStyleSheet(f"color: {tokens.text_secondary};")
        cg_layout.addWidget(self._chars_label)
        grid.addWidget(chars_group, 0, 1)

        # 伏笔卡片
        hooks_group = QGroupBox("活跃伏笔")
        hg_layout = QVBoxLayout(hooks_group)
        self._hooks_label = QLabel("2 个活跃伏笔\\n1 个待履行承诺")
        self._hooks_label.setStyleSheet(f"color: {tokens.warning};")
        hg_layout.addWidget(self._hooks_label)
        grid.addWidget(hooks_group, 1, 0)

        # 压力卡片
        pressure_group = QGroupBox("叙事压力")
        prg_layout = QVBoxLayout(pressure_group)
        self._pressure_label = QLabel("压力等级: 橙色\\n建议: 加速节奏")
        self._pressure_label.setStyleSheet(f"color: {tokens.error};")
        prg_layout.addWidget(self._pressure_label)
        grid.addWidget(pressure_group, 1, 1)

        layout.addLayout(grid)
        layout.addStretch()

    def update_state(self, state):
        """更新 HUD 显示."""
        if state is None:
            return

        # 更新进度
        if state.total_steps > 0:
            pct = int(state.current_step / state.total_steps * 100)
            self._progress_bar.setValue(pct)
            self._progress_label.setText(f"{state.current_step}/{state.total_steps} 步骤 ({pct}%)")

        # 更新角色
        chars_text = "\\n".join([
            f"{name}: {', '.join(f'{k}={v}' for k, v in char.traits.items()[:2])}"
            for name, char in list(state.characters.items())[:5]
        ])
        self._chars_label.setText(chars_text or "无角色")

        # 更新伏笔
        active = state.active_hooks()
        pending = state.pending_commitments()
        hooks_text = f"{len(active)} 个活跃伏笔\\n{len(pending)} 个待履行承诺"
        self._hooks_label.setText(hooks_text)
