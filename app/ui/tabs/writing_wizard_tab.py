"""
写作流程向导 — 项目创建→大纲→第一单元的引导页

帮助新用户完成从创建项目到开始写作的完整流程。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFormLayout, QLineEdit, QTextEdit,
    QComboBox, QSpinBox, QFrame, QGroupBox,
)


class WritingWizard(QWidget):
    """写作流程向导."""

    project_created = Signal(str)  # project_id

    STEPS = [
        ("1. 基础信息", "项目名 + 题材 + 字数目标"),
        ("2. 分卷结构", "分卷数 + 每卷章节数 + 每章字数"),
        ("3. 大纲概要", "核心主题 + 情绪曲线 + 关键事件"),
        ("4. 开始创作", "创建第一个单元并开始写作"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_step = 0
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # 标题
        title = QLabel("✍ 写作流程向导")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("跟着向导完成 4 步，即可开始创作你的小说。")
        desc.setStyleSheet("color: #888; font-size: 13px;")
        layout.addWidget(desc)

        # 步骤指示器
        self._step_labels = []
        step_row = QHBoxLayout()
        for i, (name, _) in enumerate(self.STEPS):
            lbl = QLabel(f"  {name}  ")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                "padding: 6px 12px; border-radius: 4px; font-size: 12px;"
                + ("background: #6366f1; color: white;" if i == 0 else "background: #e5e7eb; color: #666;")
            )
            self._step_labels.append(lbl)
            step_row.addWidget(lbl)
            if i < len(self.STEPS) - 1:
                arrow = QLabel("→")
                arrow.setStyleSheet("color: #999; font-size: 16px;")
                step_row.addWidget(arrow)
        layout.addLayout(step_row)

        # 内容区
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_step1())
        self._stack.addWidget(self._build_step2())
        self._stack.addWidget(self._build_step3())
        self._stack.addWidget(self._build_step4())
        layout.addWidget(self._stack, 1)

        # 导航按钮
        nav = QHBoxLayout()
        self._btn_prev = QPushButton("← 上一步")
        self._btn_prev.clicked.connect(self._prev_step)
        self._btn_prev.setEnabled(False)
        nav.addWidget(self._btn_prev)
        nav.addStretch(1)
        self._btn_next = QPushButton("下一步 →")
        self._btn_next.clicked.connect(self._next_step)
        nav.addWidget(self._btn_next)
        layout.addLayout(nav)

    def _build_step1(self) -> QWidget:
        """基础信息."""
        w = QWidget()
        form = QFormLayout(w)
        self.ed_project_name = QLineEdit()
        self.ed_project_name.setPlaceholderText("我的小说项目")
        form.addRow("项目名:", self.ed_project_name)
        self.ed_book_title = QLineEdit()
        self.ed_book_title.setPlaceholderText("书名（显示给读者）")
        form.addRow("书名:", self.ed_book_title)
        self.cmb_genre = QComboBox()
        for g in ["玄幻", "都市", "仙侠", "修真", "历史", "军事", "科幻", "游戏", "灵异", "悬疑", "言情", "武侠", "奇幻"]:
            self.cmb_genre.addItem(g)
        form.addRow("题材:", self.cmb_genre)
        self.spn_target = QSpinBox()
        self.spn_target.setRange(10_000, 10_000_000)
        self.spn_target.setValue(200_000)
        self.spn_target.setSuffix(" 字")
        form.addRow("字数目标:", self.spn_target)
        return w

    def _build_step2(self) -> QWidget:
        """分卷结构."""
        w = QWidget()
        form = QFormLayout(w)
        self.spn_volumes = QSpinBox()
        self.spn_volumes.setRange(1, 100)
        self.spn_volumes.setValue(3)
        form.addRow("分卷数:", self.spn_volumes)
        self.spn_cpv = QSpinBox()
        self.spn_cpv.setRange(1, 500)
        self.spn_cpv.setValue(100)
        form.addRow("每卷章节数:", self.spn_cpv)
        self.spn_wpc = QSpinBox()
        self.spn_wpc.setRange(500, 10_000)
        self.spn_wpc.setValue(2000)
        self.spn_wpc.setSuffix(" 字")
        form.addRow("每章字数:", self.spn_wpc)
        return w

    def _build_step3(self) -> QWidget:
        """大纲概要."""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel("核心主题（一句话概括你的故事）"))
        self.ed_theme = QLineEdit()
        self.ed_theme.setPlaceholderText("例: 废柴少年偶得上古传承，踏上逆天修仙之路")
        layout.addWidget(self.ed_theme)
        layout.addWidget(QLabel("情绪曲线（描述故事的情绪走向）"))
        self.ed_emotion = QTextEdit()
        self.ed_emotion.setPlaceholderText("例: 开篇压抑→获得机缘→逐步升温→高潮爆发→收束")
        self.ed_emotion.setMaximumHeight(100)
        layout.addWidget(self.ed_emotion)
        layout.addWidget(QLabel("关键事件（每卷的核心事件）"))
        self.ed_events = QTextEdit()
        self.ed_events.setPlaceholderText("例:\n第一卷: 主角觉醒，被逐出家族\n第二卷: 宗门大比，一战成名\n第三卷: 决战终极BOSS")
        self.ed_events.setMaximumHeight(120)
        layout.addWidget(self.ed_events)
        return w

    def _build_step4(self) -> QWidget:
        """开始创作."""
        w = QWidget()
        layout = QVBoxLayout(w)
        self._summary_label = QLabel("配置完成！")
        self._summary_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self._summary_label)
        self._summary_detail = QLabel("")
        self._summary_detail.setWordWrap(True)
        layout.addWidget(self._summary_detail)
        self._btn_start = QPushButton("🚀 创建项目并开始写作")
        self._btn_start.setStyleSheet("font-size: 14px; padding: 12px; background: #6366f1; color: white; border-radius: 6px;")
        self._btn_start.clicked.connect(self._on_start)
        layout.addWidget(self._btn_start)
        layout.addStretch(1)
        return w

    def _update_step_indicator(self) -> None:
        for i, lbl in enumerate(self._step_labels):
            if i == self._current_step:
                lbl.setStyleSheet("padding: 6px 12px; border-radius: 4px; font-size: 12px; background: #6366f1; color: white;")
            elif i < self._current_step:
                lbl.setStyleSheet("padding: 6px 12px; border-radius: 4px; font-size: 12px; background: #22c55e; color: white;")
            else:
                lbl.setStyleSheet("padding: 6px 12px; border-radius: 4px; font-size: 12px; background: #e5e7eb; color: #666;")

    def _next_step(self) -> None:
        if self._current_step < len(self.STEPS) - 1:
            if self._current_step == 2:
                self._update_summary()
            self._current_step += 1
            self._stack.setCurrentIndex(self._current_step)
            self._update_step_indicator()
            self._btn_prev.setEnabled(True)
            self._btn_next.setEnabled(self._current_step < len(self.STEPS) - 1)

    def _prev_step(self) -> None:
        if self._current_step > 0:
            self._current_step -= 1
            self._stack.setCurrentIndex(self._current_step)
            self._update_step_indicator()
            self._btn_prev.setEnabled(self._current_step > 0)
            self._btn_next.setEnabled(True)

    def _update_summary(self) -> None:
        name = self.ed_project_name.text().strip() or "未命名"
        genre = self.cmb_genre.currentText()
        volumes = self.spn_volumes.value()
        cpv = self.spn_cpv.value()
        total = volumes * cpv
        self._summary_detail.setText(
            f"项目名: {name}\n"
            f"题材: {genre}\n"
            f"分卷: {volumes} 卷 × {cpv} 章 = {total} 章\n"
            f"字数目标: {self.spn_target.value():,} 字\n"
            f"核心主题: {self.ed_theme.text().strip() or '(未填)'}"
        )

    def _on_start(self) -> None:
        """创建项目."""
        from app.services import project_service
        name = self.ed_project_name.text().strip() or "未命名项目"
        try:
            result = project_service.create(
                name=name,
                book_title=self.ed_book_title.text().strip() or None,
                genre=self.cmb_genre.currentText(),
                word_target=self.spn_target.value(),
                volumes=self.spn_volumes.value(),
                chapters_per_volume=self.spn_cpv.value(),
                words_per_chapter=self.spn_wpc.value(),
            )
            project_id = result.get("id", "")
            self._summary_label.setText("✅ 项目创建成功！")
            self._summary_detail.setText(f"项目 '{name}' 已创建，可以开始写作了。")
            self._btn_start.setEnabled(False)
            self.project_created.emit(project_id)
        except Exception as e:
            self._summary_label.setText(f"❌ 创建失败: {e}")
