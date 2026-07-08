"""
卷管理标签页 - 分卷编排UI

提供卷列表、卷详情编辑、卷纲管理功能。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QLineEdit,
    QComboBox, QSpinBox, QSplitter, QGroupBox, QFormLayout,
    QMessageBox, QFileDialog,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from app.services import book_service
from app.services import book_outline_service


class VolumeTab(QWidget):
    """卷管理标签页"""

    project_changed = Signal(str)

    def __init__(self, project_id: str = "", parent=None):
        super().__init__(parent)
        self.project_id = project_id
        self.current_book_id = None
        self._setup_ui()
        if project_id:
            self.load_volumes()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 左侧：卷列表
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        left_layout.addWidget(QLabel("分卷管理"))

        # 新建卷按钮
        btn_new = QPushButton("+ 新建卷")
        btn_new.clicked.connect(self._on_new_volume)
        left_layout.addWidget(btn_new)

        # 卷列表
        self.volume_list = QListWidget()
        self.volume_list.currentItemChanged.connect(self._on_volume_selected)
        left_layout.addWidget(self.volume_list)

        # 右侧：卷详情
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # 卷信息
        info_group = QGroupBox("卷信息")
        info_layout = QFormLayout(info_group)

        self.title_edit = QLineEdit()
        info_layout.addRow("卷名:", self.title_edit)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["planning", "in_progress", "completed"])
        info_layout.addRow("状态:", self.status_combo)

        self.target_words_spin = QSpinBox()
        self.target_words_spin.setRange(0, 10000000)
        self.target_words_spin.setSuffix(" 字")
        info_layout.addRow("目标字数:", self.target_words_spin)

        self.target_units_spin = QSpinBox()
        self.target_units_spin.setRange(0, 10000)
        self.target_units_spin.setSuffix(" 个")
        info_layout.addRow("目标单元:", self.target_units_spin)

        right_layout.addWidget(info_group)

        # 卷纲编辑
        outline_group = QGroupBox("卷纲")
        outline_layout = QVBoxLayout(outline_group)

        # 核心主题
        outline_layout.addWidget(QLabel("核心主题:"))
        self.theme_edit = QTextEdit()
        self.theme_edit.setMaximumHeight(60)
        outline_layout.addWidget(self.theme_edit)

        # 情绪曲线
        outline_layout.addWidget(QLabel("情绪曲线:"))
        self.emotion_edit = QTextEdit()
        self.emotion_edit.setMaximumHeight(60)
        outline_layout.addWidget(self.emotion_edit)

        # 关键事件
        outline_layout.addWidget(QLabel("关键事件:"))
        self.events_edit = QTextEdit()
        self.events_edit.setMaximumHeight(80)
        outline_layout.addWidget(self.events_edit)

        right_layout.addWidget(outline_group)

        # 操作按钮
        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("保存")
        self.btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(self.btn_save)

        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._on_delete)
        btn_layout.addWidget(self.btn_delete)

        right_layout.addLayout(btn_layout)
        right_layout.addStretch()

        # 分割器
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([300, 500])

        layout.addWidget(splitter)

    def set_project(self, project_id: str):
        """设置项目ID"""
        self.project_id = project_id
        self.load_volumes()

    def load_volumes(self):
        """加载卷列表"""
        self.volume_list.clear()
        if not self.project_id:
            return

        books = book_service.list_books(self.project_id)
        for book in books:
            item = QListWidgetItem(book.get("title", f"第 {book.get('volume_no', '?')} 卷"))
            item.setData(Qt.UserRole, book.get("id"))
            self.volume_list.addItem(item)

    def _on_volume_selected(self, current: QListWidgetItem, previous: QListWidgetItem):
        """卷选择变更"""
        if not current:
            return

        book_id = current.data(Qt.UserRole)
        if book_id:
            self.current_book_id = book_id
            self._load_volume_detail(book_id)

    def _load_volume_detail(self, book_id: str):
        """加载卷详情"""
        book = book_service.get_book(book_id)
        if not book:
            return

        self.title_edit.setText(book.get("title", ""))
        self.status_combo.setCurrentText(book.get("status", "planning"))
        self.target_words_spin.setValue(book.get("target_chapters", 0) * 2000)
        self.target_units_spin.setValue(book.get("target_chapters", 0))

        # 加载卷纲
        outline = book_outline_service.get_by_book(book_id)
        if outline:
            self.theme_edit.setText(outline.core_theme)
            self.emotion_edit.setText(outline.emotion_arc)
            self.events_edit.setText("\n".join(outline.key_events))
        else:
            self.theme_edit.clear()
            self.emotion_edit.clear()
            self.events_edit.clear()

    def _on_new_volume(self):
        """新建卷"""
        if not self.project_id:
            QMessageBox.warning(self, "错误", "请先选择项目")
            return

        # 获取当前卷数量
        books = book_service.list_books(self.project_id)
        volume_no = len(books) + 1

        # 创建新卷
        book = book_service.create(
            project_id=self.project_id,
            volume_no=volume_no,
            title=f"第 {volume_no} 卷",
            target_chapters=10,
        )

        # 创建对应的卷纲
        book_outline_service.create(
            book_id=book["id"],
            project_id=self.project_id,
        )

        self.load_volumes()
        QMessageBox.information(self, "成功", f"已创建第 {volume_no} 卷")

    def _on_save(self):
        """保存卷信息"""
        if not self.current_book_id:
            return

        # 更新卷信息
        book_service.update_book(
            self.current_book_id,
            title=self.title_edit.text(),
            status=self.status_combo.currentText(),
        )

        # 更新或创建卷纲
        outline = book_outline_service.get_by_book(self.current_book_id)
        events = [e.strip() for e in self.events_edit.toPlainText().split("\n") if e.strip()]

        if outline:
            book_outline_service.update(
                outline.id,
                core_theme=self.theme_edit.toPlainText(),
                emotion_arc=self.emotion_edit.toPlainText(),
                key_events=events,
            )
        else:
            book_outline_service.create(
                book_id=self.current_book_id,
                project_id=self.project_id,
                core_theme=self.theme_edit.toPlainText(),
                emotion_arc=self.emotion_edit.toPlainText(),
                key_events=events,
            )

        QMessageBox.information(self, "成功", "卷信息已保存")

    def _on_delete(self):
        """删除卷"""
        if not self.current_book_id:
            return

        reply = QMessageBox.question(
            self, "确认删除",
            "确定要删除这个卷吗？关联的单元将被解除关联。",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            # 删除卷纲
            outline = book_outline_service.get_by_book(self.current_book_id)
            if outline:
                book_outline_service.delete(outline.id)

            # 删除卷
            book_service.delete_book(self.current_book_id)

            self.current_book_id = None
            self.load_volumes()
            QMessageBox.information(self, "成功", "卷已删除")
