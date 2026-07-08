"""
卷纲生成对话框 - AI辅助生成卷纲

用户输入卷概念，AI生成卷纲内容。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QLineEdit, QGroupBox, QFormLayout, QMessageBox,
    QProgressBar,
)
from PySide6.QtCore import Qt, Signal, QThread

from app.services import book_outline_service


class GenerateWorker(QThread):
    """AI生成工作线程"""
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, book_id: str, project_id: str, concept: str):
        super().__init__()
        self.book_id = book_id
        self.project_id = project_id
        self.concept = concept

    def run(self):
        try:
            outline = book_outline_service.generate_outline_from_concept(
                self.book_id,
                self.project_id,
                self.concept,
            )
            self.finished.success.emit({
                "id": outline.id,
                "core_theme": outline.core_theme,
                "emotion_arc": outline.emotion_arc,
                "key_events": outline.key_events,
            })
        except Exception as e:
            self.error.emit(str(e))


class VolumeOutlineDialog(QDialog):
    """卷纲生成对话框"""

    outline_generated = Signal(str)  # outline_id

    def __init__(self, book_id: str, project_id: str, parent=None):
        super().__init__(parent)
        self.book_id = book_id
        self.project_id = project_id
        self.worker = None
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("AI生成卷纲")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)

        # 概念输入
        concept_group = QGroupBox("卷概念")
        concept_layout = QVBoxLayout(concept_group)

        concept_layout.addWidget(QLabel("请描述这一卷的核心内容："))
        self.concept_edit = QTextEdit()
        self.concept_edit.setPlaceholderText(
            "例如：主角进入宗门，修炼升级，结识伙伴，参加门派大比..."
        )
        concept_layout.addWidget(concept_layout)

        layout.addWidget(concept_group)

        # 生成结果
        result_group = QGroupBox("生成结果")
        result_layout = QFormLayout(result_group)

        self.theme_edit = QTextEdit()
        self.theme_edit.setMaximumHeight(60)
        self.theme_edit.setReadOnly(True)
        result_layout.addRow("核心主题:", self.theme_edit)

        self.emotion_edit = QTextEdit()
        self.emotion_edit.setMaximumHeight(60)
        self.emotion_edit.setReadOnly(True)
        result_layout.addRow("情绪曲线:", self.emotion_edit)

        self.events_edit = QTextEdit()
        self.events_edit.setMaximumHeight(80)
        self.events_edit.setReadOnly(True)
        result_layout.addRow("关键事件:", self.events_edit)

        layout.addWidget(result_group)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # 按钮
        btn_layout = QHBoxLayout()

        self.btn_generate = QPushButton("AI 生成")
        self.btn_generate.clicked.connect(self._on_generate)
        btn_layout.addWidget(self.btn_generate)

        self.btn_apply = QPushButton("应用")
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_apply.setEnabled(False)
        btn_layout.addWidget(self.btn_apply)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def _on_generate(self):
        """开始生成"""
        concept = self.concept_edit.toPlainText().strip()
        if not concept:
            QMessageBox.warning(self, "错误", "请输入卷概念")
            return

        self.btn_generate.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)  # 无限进度

        self.worker = GenerateWorker(self.book_id, self.project_id, concept)
        self.worker.finished.connect(self._on_generated)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_generated(self, result: dict):
        """生成完成"""
        self.btn_generate.setEnabled(True)
        self.progress.setVisible(False)
        self.btn_apply.setEnabled(True)

        self.theme_edit.setText(result.get("core_theme", ""))
        self.emotion_edit.setText(result.get("emotion_arc", ""))
        events = result.get("key_events", [])
        self.events_edit.setText("\n".join(events) if isinstance(events, list) else str(events))

        self.outline_id = result.get("id")

    def _on_error(self, error_msg: str):
        """生成失败"""
        self.btn_generate.setEnabled(True)
        self.progress.setVisible(False)
        QMessageBox.critical(self, "生成失败", error_msg)

    def _on_apply(self):
        """应用生成结果"""
        if hasattr(self, "outline_id") and self.outline_id:
            self.outline_generated.emit(self.outline_id)
            self.accept()
