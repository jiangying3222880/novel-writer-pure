"""
伏笔追踪组件

显示和管理故事中的伏笔，支持：
- 伏笔列表（埋设/回收状态）
- 添加新伏笔
- 标记伏笔回收
- 伏笔状态过滤
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QComboBox, QLineEdit,
    QGroupBox, QFormLayout, QMessageBox, QTextEdit,
)
from PySide6.QtGui import QFont

from app.services import unit_hook_service


class HookTrackerWidget(QWidget):
    """伏笔追踪组件"""

    hook_changed = Signal()  # 伏笔变更信号

    def __init__(self, project_id: str = "", parent=None):
        super().__init__(parent)
        self.project_id = project_id
        self._setup_ui()
        if project_id:
            self.load_hooks()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 标题
        title = QLabel("🎣 伏笔追踪")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        # 统计
        self.stats_label = QLabel("埋设: 0 | 回收: 0 | 待回收: 0")
        self.stats_label.setObjectName("statsLabel")
        layout.addWidget(self.stats_label)

        # 过滤器
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("状态:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["全部", "待回收", "已回收", "已废弃"])
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.filter_combo)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # 伏笔列表
        self.hook_list = QListWidget()
        self.hook_list.itemDoubleClicked.connect(self._on_hook_selected)
        layout.addWidget(self.hook_list, 1)

        # 添加伏笔
        add_group = QGroupBox("添加伏笔")
        add_layout = QVBoxLayout(add_group)

        # 伏笔描述
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("伏笔描述（例如：主角体内藏着上古神器碎片）")
        self.desc_edit.setMaximumHeight(60)
        add_layout.addWidget(self.desc_edit)

        # 伏笔类型和关联单元
        form_layout = QFormLayout()

        self.hook_type_combo = QComboBox()
        self.hook_type_combo.addItems(["plant", "payoff", "reference"])
        form_layout.addRow("类型:", self.hook_type_combo)

        self.unit_id_edit = QLineEdit()
        self.unit_id_edit.setPlaceholderText("关联单元ID（可选）")
        form_layout.addRow("关联单元:", self.unit_id_edit)

        add_layout.addLayout(form_layout)

        # 按钮
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("添加伏笔")
        self.btn_add.clicked.connect(self._on_add_hook)
        btn_layout.addWidget(self.btn_add)

        self.btn_mark_payoff = QPushButton("标记回收")
        self.btn_mark_payoff.clicked.connect(self._on_mark_payoff)
        btn_layout.addWidget(self.btn_mark_payoff)

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.load_hooks)
        btn_layout.addWidget(self.btn_refresh)

        add_layout.addLayout(btn_layout)

        layout.addWidget(add_group)

    def set_project(self, project_id: str):
        """设置项目ID"""
        self.project_id = project_id
        self.load_hooks()

    def load_hooks(self):
        """加载伏笔列表"""
        self.hook_list.clear()
        if not self.project_id:
            return

        try:
            hooks = unit_hook_service.list_for_project(self.project_id)
            plant_count = 0
            payoff_count = 0

            for hook in hooks:
                hook_type = getattr(hook, "hook_type", "plant")
                status = getattr(hook, "status", "active")

                if hook_type == "plant":
                    plant_count += 1
                elif hook_type == "payoff":
                    payoff_count += 1

                item = QListWidgetItem()
                icon = "🟢" if status == "active" else "✅" if status == "resolved" else "⚫"
                item.setText(
                    f"{icon} [{hook_type}] {getattr(hook, 'description', '')[:50]}"
                )
                item.setData(Qt.ItemDataRole.UserRole, getattr(hook, "id", ""))
                self.hook_list.addItem(item)

            # 更新统计
            pending = plant_count - payoff_count
            self.stats_label.setText(
                f"埋设: {plant_count} | 回收: {payoff_count} | 待回收: {max(0, pending)}"
            )
        except Exception as e:
            self.stats_label.setText(f"加载失败: {e}")

    def _on_filter_changed(self, filter_text: str):
        """过滤变更"""
        # TODO: 实现过滤逻辑
        self.load_hooks()

    def _on_hook_selected(self, item: QListWidgetItem):
        """选中伏笔"""
        hook_id = item.data(Qt.ItemDataRole.UserRole)
        if hook_id:
            QMessageBox.information(self, "伏笔详情", f"ID: {hook_id}")

    def _on_add_hook(self):
        """添加伏笔"""
        desc = self.desc_edit.toPlainText().strip()
        hook_type = self.hook_type_combo.currentText()
        unit_id = self.unit_id_edit.text().strip()

        if not desc:
            QMessageBox.warning(self, "错误", "请填写伏笔描述")
            return

        if not self.project_id:
            QMessageBox.warning(self, "错误", "请先选择项目")
            return

        try:
            unit_hook_service.create(
                project_id=self.project_id,
                unit_id=unit_id or "",
                hook_type=hook_type,
                description=desc,
            )
            self.load_hooks()
            self.hook_changed.emit()
            QMessageBox.information(self, "成功", "伏笔已添加")

            # 清空输入
            self.desc_edit.clear()
            self.unit_id_edit.clear()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"添加失败: {e}")

    def _on_mark_payoff(self):
        """标记伏笔回收"""
        current = self.hook_list.currentItem()
        if not current:
            QMessageBox.warning(self, "错误", "请先选择要标记的伏笔")
            return

        hook_id = current.data(Qt.ItemDataRole.UserRole)
        if not hook_id:
            return

        try:
            unit_hook_service.resolve(hook_id)
            self.load_hooks()
            self.hook_changed.emit()
            QMessageBox.information(self, "成功", "伏笔已标记为回收")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"标记失败: {e}")
