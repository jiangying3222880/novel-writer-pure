"""
实体管理 Tab (Phase 3 M3).

展示当前项目的所有 entity (character / location / item / faction),
按 entity_name 分组, 显示该实体出现在多少章 / 多少段.

操作:
  - 重塑: 改名字, 触发 entity_manager.reshape() 扫全本 + 改 draft (受用户门卫)
  - 单段替换: 选定 entity + 段, 一键替换 (用于扫前后的微调)
"""
from __future__ import annotations
import logging
from collections import defaultdict
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget,
    QListWidgetItem, QLabel, QPushButton, QLineEdit, QInputDialog,
    QPlainTextEdit, QFormLayout, QGroupBox,
)

from app.services import chapter_service, ServiceError
from app.services.writing.entity_manager import reshape_entity, list_entities_summary
from app.ui.widgets import Dialogs

log = logging.getLogger(__name__)


ENTITY_TYPE_LABELS = {
    "character": "👤 角色",
    "location": "📍 地点",
    "item": "🗡️ 物品",
    "faction": "🏛️ 势力",
}


class EntityTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.current_project: Optional[dict] = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.title = QLabel("实体管理（未选择项目）")
        self.title.setObjectName("projectTitle")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(self.title)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # ---- 左: 实体列表 ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("实体 (按出现次数排序):"))
        self.entity_list = QListWidget()
        self.entity_list.itemSelectionChanged.connect(self._on_entity_selected)
        left_layout.addWidget(self.entity_list, 1)
        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_refresh.clicked.connect(self._reload)
        left_layout.addWidget(self.btn_refresh)
        splitter.addWidget(left)

        # ---- 右: 详情 + 操作 ----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_label = QLabel("选中左侧实体以查看详情")
        # 4.0 修复: 之前硬编码 color: #666, 亮色主题下也是暗灰, 不协调.
        # 现在用 objectName + QSS (跟主题的 QLabel#cardSub 风格一致).
        self.detail_label.setObjectName("cardSub")
        right_layout.addWidget(self.detail_label)

        # 重塑面板
        reshape_box = QGroupBox("🔧 实体重塑 (改名)")
        rb_layout = QFormLayout(reshape_box)
        self.ed_new_name = QLineEdit()
        self.ed_new_name.setPlaceholderText("新名字 (留空 = 取消)")
        rb_layout.addRow("新名字:", self.ed_new_name)
        rb_layout.addRow(
            QLabel("提示: 将扫全本 (该项目所有 draft), 替换 entity_name 字段.\n"
                   "重塑只改 entity_appearances 索引; 不改 chapter.draft 文本."
                   " 如需改正文, 用段落重写或批量重生成.")
        )
        btn_row = QHBoxLayout()
        self.btn_preview = QPushButton("👁 预览影响范围")
        self.btn_preview.clicked.connect(self._on_preview_reshape)
        self.btn_reshape = QPushButton("✅ 执行重塑")
        self.btn_reshape.clicked.connect(self._on_reshape)
        btn_row.addWidget(self.btn_preview)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_reshape)
        rb_layout.addRow(btn_row)
        right_layout.addWidget(reshape_box)

        # 出现位置列表
        right_layout.addWidget(QLabel("📍 出现位置:"))
        self.appearances_view = QPlainTextEdit()
        self.appearances_view.setReadOnly(True)
        right_layout.addWidget(self.appearances_view, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([280, 700])

    # ---- public ----

    def set_project(self, project: Optional[dict]) -> None:
        self.current_project = project
        self.entity_list.clear()
        self.appearances_view.clear()
        self.detail_label.setText("选中左侧实体以查看详情")
        if project is None:
            self.title.setText("实体管理（未选择项目）")
            return
        self.title.setText(f"实体管理 — {project.get('name', '')}")
        self._reload()

    # ---- data ----

    def _reload(self) -> None:
        if not self.current_project:
            return
        pid = self.current_project["id"]
        try:
            summary = list_entities_summary(pid)
        except ServiceError as e:
            Dialogs.warning("加载实体", str(e), parent=self)
            return
        self.entity_list.clear()
        for ent in summary:
            label = (
                f"{ENTITY_TYPE_LABELS.get(ent['entity_type'], ent['entity_type'])}  "
                f"{ent['entity_name']}  "
                f"[{ent['chapter_count']}章 / {ent['appearance_count']}次]"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ent)
            self.entity_list.addItem(item)
        if not summary:
            self.detail_label.setText("(该项目暂无实体记录)")

    def _on_entity_selected(self) -> None:
        item = self.entity_list.currentItem()
        if not item:
            return
        ent = item.data(Qt.ItemDataRole.UserRole)
        # 拉所有 appearance
        if not self.current_project:
            return
        try:
            apps = chapter_service.list_entity_appearances_for_project(
                self.current_project["id"], entity_name=ent["entity_name"],
            )
        except ServiceError as e:
            Dialogs.warning("加载出现", str(e), parent=self)
            return
        # 详情汇总
        type_label = ENTITY_TYPE_LABELS.get(ent["entity_type"], ent["entity_type"])
        self.detail_label.setText(
            f"{type_label}  {ent['entity_name']}  ·  "
            f"出现 {ent['appearance_count']} 次 / 跨 {ent['chapter_count']} 章"
        )
        self.ed_new_name.setText("")
        # 列出现位置
        lines: list[str] = []
        for a in apps.get("appearances", []):
            ch = a.get("chapter_id", "?")[:8]
            para = a.get("paragraph_index")
            para_s = f"段{para}" if para is not None else "—"
            lines.append(f"· 章节 {ch}  {para_s}  实体ID={a['id'][:8]}")
        self.appearances_view.setPlainText("\n".join(lines) if lines else "(无)")

    # ---- actions ----

    def _current_entity(self) -> Optional[dict]:
        item = self.entity_list.currentItem()
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_preview_reshape(self) -> None:
        ent = self._current_entity()
        if not ent:
            Dialogs.info("预览", "请先选中一个实体", parent=self)
            return
        new_name = self.ed_new_name.text().strip()
        if not new_name:
            Dialogs.info("预览", "请输入新名字", parent=self)
            return
        if not self.current_project:
            return
        try:
            preview = reshape_entity(
                self.current_project["id"],
                ent["entity_name"],
                new_name,
                dry_run=True,
            )
        except ServiceError as e:
            Dialogs.warning("预览失败", str(e), parent=self)
            return
        Dialogs.info(
            "预览",
            f"将重塑: {ent['entity_name']!r} -> {new_name!r}\n"
            f"影响 {preview['will_update']} 条 appearance 索引\n"
            f"(注: 只改 entity_appearances 表, 不改 chapter.draft 正文)",
            parent=self,
        )

    def _on_reshape(self) -> None:
        ent = self._current_entity()
        if not ent:
            return
        new_name = self.ed_new_name.text().strip()
        if not new_name:
            Dialogs.info("重塑", "请输入新名字", parent=self)
            return
        if new_name == ent["entity_name"]:
            Dialogs.info("重塑", "新名字与旧名字相同", parent=self)
            return
        ok, _ = Dialogs.confirm(
            "确认重塑",
            f"将重塑 {ent['entity_name']!r} -> {new_name!r}\n"
            f"这会更新该实体的全部 appearance 索引. 继续?",
            danger=True,
            confirm_text="执行重塑",
            cancel_text="取消",
            parent=self,
        )
        if not ok:
            return
        if not self.current_project:
            return
        try:
            result = reshape_entity(
                self.current_project["id"],
                ent["entity_name"],
                new_name,
                dry_run=False,
            )
        except ServiceError as e:
            Dialogs.warning("重塑失败", str(e), parent=self)
            return
        Dialogs.info(
            "重塑完成",
            f"已更新 {result['updated']} 条 appearance\n"
            f"原 {ent['entity_name']!r} -> {new_name!r}",
            parent=self,
        )
        self._reload()
