"""
Publish Tab (v4.0 发布模块重写)

组成:
  - 左: ChapterTree 章节树 (卷 → 章节)
  - 中: 章节编辑 (草稿 QTextEdit)，保存时回写章节并同步回所属单元
  - 右: 情绪曲线 (EmotionCurveWidget) + 断章报告

对接:
  - app.services.chapter_service     章节 CRUD
  - app.services.story_unit_service_v2  (save_draft 编辑同步回单元)
  - app.services.emotion_analyzer    情绪曲线 / 断章报告
  - app.ui.widgets.chapter_tree      章节树
  - app.ui.widgets.emotion_curve     情绪曲线图
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLabel, QTextEdit,
    QPushButton, QTextBrowser, QComboBox, QSpinBox, QFrame,
)
from app.ui.widgets.debouncer import Debouncer
from app.ui.widgets.assembly_wizard import AssemblyWizard


class PublishTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project_id: str = ""
        self._current_chapter_id: Optional[str] = None
        self._current_unit_id: Optional[str] = None
        self._build()

    # -------------------------------------------------------------- #
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        from PySide6.QtCore import Qt as _Qt
        splitter = QSplitter(_Qt.Horizontal)

        # 左: 章节树
        from app.ui.widgets.chapter_tree import ChapterTree
        self._tree = ChapterTree()
        self._tree.chapter_selected.connect(self._on_chapter_selected)
        splitter.addWidget(self._tree)

        # 中: 章节编辑
        mid = QWidget()
        mid_lay = QVBoxLayout(mid)
        mid_lay.setContentsMargins(0, 0, 0, 0)
        mid_lay.setSpacing(6)

        head = QHBoxLayout()
        self._chapter_title = QLabel("未选择章节")
        self._chapter_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #cdd6f4;")
        head.addWidget(self._chapter_title)
        head.addStretch(1)
        self._save_btn = QPushButton("保存并同步单元")
        self._save_btn.setStyleSheet(
            "QPushButton { background: #45475a; border: none; border-radius: 4px; "
            "color: #cdd6f4; padding: 5px 12px; }"
            "QPushButton:hover { background: #585b70; }"
        )
        self._save_btn.clicked.connect(self._on_save)
        head.addWidget(self._save_btn)
        self._assembly_btn = QPushButton("成稿向导")
        self._assembly_btn.setStyleSheet(
            "QPushButton { background: #89b4fa; border: none; border-radius: 4px; "
            "color: #1e1e2e; padding: 5px 12px; font-weight: 700; }"
            "QPushButton:hover { background: #74a0e0; }"
        )
        self._assembly_btn.clicked.connect(self._open_assembly)
        head.addWidget(self._assembly_btn)
        mid_lay.addLayout(head)

        self._editor = QTextEdit()
        self._editor.setStyleSheet(
            "QTextEdit { background: #1e1e2e; border: 1px solid #313244; "
            "border-radius: 4px; color: #cdd6f4; font-size: 13px; }"
        )
        self._editor.setPlaceholderText("在左侧选择章节以编辑其草稿…")
        self._editor.textChanged.connect(self._schedule_curve_update)
        mid_lay.addWidget(self._editor, 1)

        # 文本输入防抖: 编辑时实时刷新情绪曲线, 但合并连续按键避免每键重算卡顿
        self._curve_debouncer = Debouncer(300, self)
        self._curve_debouncer.triggered.connect(self._refresh_curve_live)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #a6e3a1; font-size: 11px;")
        mid_lay.addWidget(self._status)
        splitter.addWidget(mid)

        # 右: 情绪曲线 + 断章
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(6)

        # 断章工具栏
        tool = QHBoxLayout()
        tool.addWidget(QLabel("拆章策略:"))
        self._strategy = QComboBox()
        self._strategy.addItems(["auto", "suspense", "climax", "reveal", "crisis"])
        tool.addWidget(self._strategy)
        tool.addWidget(QLabel("目标字数:"))
        self._target = QSpinBox()
        self._target.setRange(300, 6000)
        self._target.setValue(1500)
        self._target.setSingleStep(100)
        tool.addWidget(self._target)
        self._split_btn = QPushButton("检测断章点")
        self._split_btn.setStyleSheet(
            "QPushButton { background: #45475a; border: none; border-radius: 4px; "
            "color: #cdd6f4; padding: 5px 12px; }"
            "QPushButton:hover { background: #585b70; }"
        )
        self._split_btn.clicked.connect(self._on_detect_split)
        tool.addWidget(self._split_btn)
        tool.addStretch(1)
        right_lay.addLayout(tool)

        from app.ui.widgets.emotion_curve import EmotionCurveWidget
        self._curve = EmotionCurveWidget()
        right_lay.addWidget(self._curve, 1)

        self._split_report = QTextBrowser()
        self._split_report.setStyleSheet(
            "QTextBrowser { background: #1e1e2e; border: 1px solid #313244; "
            "border-radius: 4px; color: #cdd6f4; font-size: 12px; }"
        )
        self._split_report.setMaximumHeight(200)
        right_lay.addWidget(self._split_report)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 2)
        root.addWidget(splitter)

    # -------------------------------------------------------------- #
    def set_project(self, project) -> None:
        if isinstance(project, dict):
            pid = project.get("id") or ""
        else:
            pid = getattr(project, "id", project) or ""
        self._project_id = pid
        self._tree.set_project(self._project_id)
        self._clear_editor()

    def _clear_editor(self) -> None:
        self._current_chapter_id = None
        self._current_unit_id = None
        self._chapter_title.setText("未选择章节")
        self._editor.clear()
        self._curve.set_text("")
        self._split_report.setPlainText("")

    # -------------------------------------------------------------- #
    def _on_chapter_selected(self, chapter_id: str) -> None:
        from app.services import chapter_service
        try:
            ch = chapter_service.get(chapter_id)
        except Exception:
            self._status.setText("无法加载章节")
            return
        self._current_chapter_id = chapter_id
        self._current_unit_id = ch.get("source_unit_id") or None
        title = ch.get("title") or "未命名"
        no = ch.get("chapter_no", "?")
        self._chapter_title.setText(f"第{no}章  {title}")
        text = ch.get("final") or ch.get("draft") or ""
        self._editor.setPlainText(text)
        self._curve.set_text(text)
        self._status.setText(
            f"已加载 · 关联单元: {self._current_unit_id[:8] if self._current_unit_id else '无'}"
        )

    # -------------------------------------------------------------- #
    def _schedule_curve_update(self) -> None:
        """编辑框文本变化 → 推迟刷新曲线 (防抖)."""
        self._curve_debouncer.call()

    def _refresh_curve_live(self) -> None:
        """防抖静默后执行: 用编辑器当前文本刷新情绪曲线 (实时反馈, 不阻塞输入)."""
        self._curve.set_text(self._editor.toPlainText())

    # -------------------------------------------------------------- #
    def _on_save(self) -> None:
        if not self._current_chapter_id:
            self._status.setText("请先选择章节")
            return
        text = self._editor.toPlainText()
        from app.services import chapter_service
        try:
            # 发布/编辑页: 保存应同时刷新 draft 与 final, 否则 final(发布正文) 会停留在旧内容
            chapter_service.update(self._current_chapter_id, draft=text, final=text,
                                   word_count=len(text))
        except Exception as e:
            self._status.setText(f"保存失败: {e}")
            return

        # 同步回所属单元
        synced = ""
        if self._current_unit_id:
            try:
                from app.services import story_unit_service_v2
                story_unit_service_v2.save_draft(self._current_unit_id, text)
                synced = " · 已同步单元草稿"
            except Exception:
                synced = " · 单元同步跳过"
        self._status.setText(f"已保存{synced}")

    def _open_assembly(self) -> None:
        if not self._project_id:
            self._status.setText("请先打开项目")
            return
        wiz = AssemblyWizard(self)
        wiz.set_project(self._project_id)
        wiz.chapters_created.connect(lambda: self._tree.set_project(self._project_id))
        wiz.exec()

    def _on_detect_split(self) -> None:
        text = self._editor.toPlainText()
        if not text.strip():
            self._split_report.setPlainText("（无文本可分析）")
            return
        from app.services.emotion_analyzer import generate_split_report
        try:
            rep = generate_split_report(text, self._strategy.currentText(),
                                        self._target.value())
        except Exception as e:
            self._split_report.setPlainText(f"断章分析失败: {e}")
            return

        lines = [f"断章报告 · 策略={rep.strategy} · 总字数={rep.total_chars}"]
        lines.append(f"推荐断章位置: {rep.recommended_splits}")
        lines.append("—" * 30)
        for bp in rep.break_points:
            lines.append(
                f"[{bp.position}] 痛感={bp.pain_score:.2f} 模式={bp.pattern}\n"
                f"  理由: {bp.reason}\n"
                f"  原文: {bp.text_preview[:40]}"
            )
        self._split_report.setPlainText("\n".join(lines))
