"""
树状导航组件 - 替代旧的ModuleNav

左侧树状结构导航，支持：
- 项目管理（可管理多个项目）
- 故事设定
- 开始写作
- 仪表盘
- 设置
"""
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QHeaderView, QSizePolicy,
)


# 导航结构定义
NAV_TREE = {
    "project": {
        "label": "📁 项目管理",
        "pages": [
            ("projects", "项目列表"),
            ("novel-settings", "项目设置"),
        ],
    },
    "story": {
        "label": "📖 故事设定",
        "pages": [
            ("novel-settings", "小说设定"),
            ("outline-mgmt", "大纲管理"),  # 分卷大纲
            ("character-mgmt", "角色管理"),
            ("worldview", "世界观"),
        ],
    },
    "write": {
        "label": "✍ 开始写作",
        "pages": [
            ("generate", "当前创作"),
            ("story-unit", "故事单元"),  # 可调整分卷内单元顺序
            ("unit-pool", "单元池管理"),
            ("publish", "章节管理"),  # 原发布总览+导出预览
        ],
    },
    "dashboard": {
        "label": "📊 仪表盘",
        "pages": [
            ("dashboard", "综合仪表盘"),  # 合并故事健康/世界图谱/用量分析
        ],
    },
    "settings": {
        "label": "⚙ 设置",
        "pages": [
            ("knowledge", "知识库"),
            ("model", "AI 模型"),
            ("edit-signals", "自动进化"),
            ("storage-backup", "项目目录"),
            ("appearance", "外观"),
            ("logs", "日志"),
            ("about", "关于"),
        ],
    },
}


class TreeNav(QWidget):
    """树状导航组件"""

    page_selected = Signal(str)  # page_id
    project_changed = Signal(str)  # project_id

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._current_page: str = "generate"
        self._current_project: Optional[str] = None
        self._build_ui()
        self._populate_tree()

    def _build_ui(self):
        self.setFixedWidth(240)
        self.setObjectName("treeNav")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题
        title = QLabel("  Novel Writer Pure")
        title.setObjectName("sidebarHeader")
        layout.addWidget(title)

        # 版本
        from app.core.version import VERSION
        version = QLabel(f"  v{VERSION}  故事引擎")
        version.setObjectName("sidebarFooter")
        layout.addWidget(version)

        # 当前项目指示
        self.project_label = QLabel("  📂 未选择项目")
        self.project_label.setObjectName("projectLabel")
        self.project_label.setFixedHeight(32)
        layout.addWidget(self.project_label)

        # 树状导航
        self.tree = QTreeWidget()
        self.tree.setObjectName("navTree")
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(20)
        self.tree.setRootIsDecorated(True)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree, 1)

        # 底部按钮
        from PySide6.QtWidgets import QPushButton
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(12, 6, 12, 8)
        footer_layout.setSpacing(4)

        # 新建项目按钮
        new_project_btn = QPushButton("+ 新建项目")
        new_project_btn.setObjectName("newProjectBtn")
        new_project_btn.clicked.connect(self._on_new_project)
        footer_layout.addWidget(new_project_btn)

        layout.addWidget(footer)

    def _populate_tree(self):
        """填充树状导航"""
        self.tree.clear()
        self._page_items: dict[str, QTreeWidgetItem] = {}

        for section_id, section in NAV_TREE.items():
            # 创建顶级节点
            section_item = QTreeWidgetItem(self.tree)
            section_item.setText(0, section["label"])
            section_item.setFlags(section_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            section_item.setExpanded(True)

            # 设置字体
            font = section_item.font(0)
            font.setBold(True)
            section_item.setFont(0, font)

            # 创建子节点
            for page_id, page_label in section["pages"]:
                page_item = QTreeWidgetItem(section_item)
                page_item.setText(0, f"  {page_label}")
                page_item.setData(0, Qt.ItemDataRole.UserRole, page_id)
                self._page_items[page_id] = page_item

        # 默认选中当前创作
        self.select_page("generate")

    def select_page(self, page_id: str):
        """选中指定页面"""
        if page_id in self._page_items:
            item = self._page_items[page_id]
            self.tree.setCurrentItem(item)
            self._current_page = page_id
            self.page_selected.emit(page_id)

    def set_project(self, project_id: str, project_name: str = ""):
        """设置当前项目"""
        self._current_project = project_id
        display_name = project_name or project_id[:8] + "..."
        self.project_label.setText(f"  📂 {display_name}")
        self.project_changed.emit(project_id)

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """处理项目点击"""
        page_id = item.data(0, Qt.ItemDataRole.UserRole)
        if page_id:
            self._current_page = page_id
            self.page_selected.emit(page_id)

    def _on_new_project(self):
        """新建项目"""
        from PySide6.QtWidgets import QApplication
        # 发送信号让主窗口处理
        QApplication.instance().main_window._on_new_project() if hasattr(QApplication.instance(), 'main_window') else None
