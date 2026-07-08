"""
因果图可视化组件

显示单元之间的因果关系，支持：
- 因果边列表展示
- 添加/删除因果边
- 因果关系过滤
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QComboBox, QLineEdit,
    QGroupBox, QFormLayout, QMessageBox, QSplitter,
)
from PySide6.QtGui import QFont

from app.services import unit_causal_service


class CausalGraphWidget(QWidget):
    """因果图可视化组件"""

    edge_changed = Signal()  # 因果边变更信号

    def __init__(self, project_id: str = "", parent=None):
        super().__init__(parent)
        self.project_id = project_id
        self._setup_ui()
        if project_id:
            self.load_edges()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 标题
        title = QLabel("🔗 因果图")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        # 过滤器
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("过滤:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["全部", "直接因果", "间接因果", "伏笔"])
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.filter_combo)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # 因果边列表
        self.edge_list = QListWidget()
        self.edge_list.itemDoubleClicked.connect(self._on_edge_selected)
        layout.addWidget(self.edge_list, 1)

        # 添加因果边
        add_group = QGroupBox("添加因果边")
        add_layout = QFormLayout(add_group)

        self.from_unit_edit = QLineEdit()
        self.from_unit_edit.setPlaceholderText("源单元ID")
        add_layout.addRow("源单元:", self.from_unit_edit)

        self.to_unit_edit = QLineEdit()
        self.to_unit_edit.setPlaceholderText("目标单元ID")
        add_layout.addRow("目标单元:", self.to_unit_edit)

        self.edge_type_combo = QComboBox()
        self.edge_type_combo.addItems(["direct", "indirect", "hook", "parallel"])
        add_layout.addRow("边类型:", self.edge_type_combo)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("因果描述")
        add_layout.addRow("描述:", self.desc_edit)

        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("添加")
        self.btn_add.clicked.connect(self._on_add_edge)
        btn_layout.addWidget(self.btn_add)

        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._on_delete_edge)
        btn_layout.addWidget(self.btn_delete)

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.load_edges)
        btn_layout.addWidget(self.btn_refresh)

        add_layout.addRow(btn_layout)

        layout.addWidget(add_group)

    def set_project(self, project_id: str):
        """设置项目ID"""
        self.project_id = project_id
        self.load_edges()

    def load_edges(self):
        """加载因果边列表"""
        self.edge_list.clear()
        if not self.project_id:
            return

        edges = unit_causal_service.get_edges_for_project(self.project_id)
        for edge in edges:
            item = QListWidgetItem()
            item.setText(
                f"{edge.get('from_unit_id', '?')[:8]} → {edge.get('to_unit_id', '?')[:8]} "
                f"[{edge.get('edge_type', '?')}] {edge.get('description', '')[:30]}"
            )
            item.setData(Qt.ItemDataRole.UserRole, edge.get('id'))
            self.edge_list.addItem(item)

    def _on_filter_changed(self, filter_text: str):
        """过滤变更"""
        # TODO: 实现过滤逻辑
        self.load_edges()

    def _on_edge_selected(self, item: QListWidgetItem):
        """选中因果边"""
        edge_id = item.data(Qt.ItemDataRole.UserRole)
        if edge_id:
            # 显示边详情
            QMessageBox.information(self, "因果边详情", f"ID: {edge_id}")

    def _on_add_edge(self):
        """添加因果边"""
        from_unit = self.from_unit_edit.text().strip()
        to_unit = self.to_unit_edit.text().strip()
        edge_type = self.edge_type_combo.currentText()
        desc = self.desc_edit.text().strip()

        if not from_unit or not to_unit:
            QMessageBox.warning(self, "错误", "请填写源单元和目标单元")
            return

        if not self.project_id:
            QMessageBox.warning(self, "错误", "请先选择项目")
            return

        try:
            unit_causal_service.create_edge(
                project_id=self.project_id,
                from_unit_id=from_unit,
                to_unit_id=to_unit,
                edge_type=edge_type,
                description=desc,
            )
            self.load_edges()
            self.edge_changed.emit()
            QMessageBox.information(self, "成功", "因果边已添加")

            # 清空输入
            self.from_unit_edit.clear()
            self.to_unit_edit.clear()
            self.desc_edit.clear()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"添加失败: {e}")

    def _on_delete_edge(self):
        """删除选中的因果边"""
        current = self.edge_list.currentItem()
        if not current:
            QMessageBox.warning(self, "错误", "请先选择要删除的因果边")
            return

        edge_id = current.data(Qt.ItemDataRole.UserRole)
        if not edge_id:
            return

        reply = QMessageBox.question(
            self, "确认删除",
            "确定要删除这条因果边吗？",
            QMessageBox.Yes | QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                unit_causal_service.delete_edge(edge_id)
                self.load_edges()
                self.edge_changed.emit()
                QMessageBox.information(self, "成功", "因果边已删除")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败: {e}")
