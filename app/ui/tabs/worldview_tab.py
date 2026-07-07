"""
WorldviewTab — 世界观管理 (独立tab).

功能:
  - 世界观内容编辑器
  - 导入世界观设定 (从 .md / .json 文件)
  - 保存/修改世界观内容
  - 支持结构化编辑 (地理/历史/文化/势力等)

数据层: setting_service (project_settings 表, key="worldbuilding")
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QGroupBox, QSplitter, QFrame,
    QFileDialog, QComboBox,
)
from app.ui.theme import text_chip

from app.services import setting_service, ServiceError
from app.ui.widgets import Dialogs

log = logging.getLogger(__name__)

# 世界观在 project_settings 中的 key
WORLDVIEW_KEY = "worldbuilding"


# --------------------------------------------------------------------- #
# 世界观管理主组件
# --------------------------------------------------------------------- #

class WorldviewTab(QWidget):
    """世界观管理 (独立tab)."""

    def __init__(self) -> None:
        super().__init__()
        self.current_project: Optional[dict] = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        # 标题
        self.title = QLabel("🌍 世界观管理")
        self.title.setObjectName("projectTitle")
        outer.addWidget(self.title)

        # 说明
        desc = QLabel(
            "管理小说的世界观设定，包括地理环境、历史背景、文化体系、势力分布等。\n"
            "支持从 Markdown / JSON 文件导入，或直接在此编辑。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {text_chip()}; font-size: 12px; padding: 4px 0;")
        outer.addWidget(desc)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: rgba(127,127,127,0.2);")
        sep.setFixedHeight(1)
        outer.addWidget(sep)

        # 主编辑区
        editor_box = QGroupBox("📝 世界观内容")
        editor_lay = QVBoxLayout(editor_box)
        editor_lay.setContentsMargins(8, 8, 8, 8)

        self.ed_worldview = QPlainTextEdit()
        self.ed_worldview.setPlaceholderText(
            "在此编辑世界观设定...\n\n"
            "建议结构:\n"
            "## 地理环境\n"
            "## 历史背景\n"
            "## 文化体系\n"
            "## 势力分布\n"
            "## 特殊设定"
        )
        self.ed_worldview.setMinimumHeight(300)
        editor_lay.addWidget(self.ed_worldview, 1)

        outer.addWidget(editor_box, 1)

        # 操作按钮行
        btn_row = QHBoxLayout()
        
        self.btn_save = QPushButton("💾 保存")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setEnabled(False)
        btn_row.addWidget(self.btn_save)

        self.btn_import = QPushButton("📥 导入")
        self.btn_import.setObjectName("btnImportWorldview")
        self.btn_import.setToolTip("从 .md / .json 文件导入世界观设定")
        self.btn_import.clicked.connect(self._on_import)
        self.btn_import.setEnabled(False)
        btn_row.addWidget(self.btn_import)

        self.btn_export = QPushButton("📤 导出")
        self.btn_export.setToolTip("导出世界观为 Markdown 文件")
        self.btn_export.clicked.connect(self._on_export)
        self.btn_export.setEnabled(False)
        btn_row.addWidget(self.btn_export)

        btn_row.addStretch(1)
        outer.addLayout(btn_row)

    # ---- public ----

    def set_project(self, project: Optional[dict]) -> None:
        """设置当前项目并加载世界观数据."""
        self.current_project = project
        if project is None:
            self.title.setText("🌍 世界观管理（未选择项目）")
            self.ed_worldview.clear()
            self.btn_save.setEnabled(False)
            self.btn_import.setEnabled(False)
            self.btn_export.setEnabled(False)
            return
        
        self.title.setText(f"🌍 世界观管理 — {project.get('name', '')}")
        self.btn_import.setEnabled(True)
        self.btn_export.setEnabled(True)
        self._load_worldview()

    # ---- 加载/保存 ----

    def _load_worldview(self) -> None:
        """从数据库加载世界观数据."""
        if not self.current_project:
            return
        
        try:
            data = setting_service.get_setting(self.current_project["id"], WORLDVIEW_KEY)
            content = data.get("data")
            
            if content is None:
                self.ed_worldview.clear()
            elif isinstance(content, str):
                self.ed_worldview.setPlainText(content)
            else:
                # dict/list 类型转为 JSON 字符串显示
                self.ed_worldview.setPlainText(
                    json.dumps(content, ensure_ascii=False, indent=2)
                )
            
            self.btn_save.setEnabled(True)
        except ServiceError as e:
            log.warning("加载世界观失败: %s", e)
            self.ed_worldview.clear()

    def _on_save(self) -> None:
        """保存世界观内容."""
        if not self.current_project:
            Dialogs.warning("保存失败", "未选择项目", parent=self)
            return
        
        raw = self.ed_worldview.toPlainText().strip()
        
        # 尝试解析为 JSON，如果失败则作为纯文本保存
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            # 不是 JSON，作为字符串保存
            data = raw
        
        try:
            setting_service.set_setting(self.current_project["id"], WORLDVIEW_KEY, data)
            Dialogs.info("保存成功", "世界观设定已保存。", parent=self)
        except ServiceError as e:
            Dialogs.warning("保存失败", str(e), parent=self)

    # ---- 导入/导出 ----

    def _on_import(self) -> None:
        """从文件导入世界观."""
        if not self.current_project:
            return
        
        path, _ = QFileDialog.getOpenFileName(
            self, "选择世界观文件 (md / json)",
            "", "Markdown / JSON (*.md *.markdown *.json);;All files (*.*)",
        )
        if not path:
            return
        
        try:
            from app.services import setting_io
            result = setting_io.import_setting(
                self.current_project["id"], WORLDVIEW_KEY, path
            )
            
            # 重新加载显示
            self._load_worldview()
            
            Dialogs.info(
                "导入完成",
                f"已导入世界观设定\n"
                f"文件大小: {result.get('size_chars', 0):,} 字符\n"
                f"格式: {result.get('format', '?')}",
                parent=self,
            )
        except Exception as e:
            Dialogs.warning("导入失败", str(e), parent=self)

    def _on_export(self) -> None:
        """导出世界观为 Markdown 文件."""
        if not self.current_project:
            return
        
        content = self.ed_worldview.toPlainText().strip()
        if not content:
            Dialogs.warning("导出失败", "世界观内容为空", parent=self)
            return
        
        project_name = self.current_project.get("name", "novel")
        default_filename = f"{project_name}_世界观.md"
        
        path, _ = QFileDialog.getSaveFileName(
            self, "导出世界观",
            default_filename,
            "Markdown (*.md);;JSON (*.json);;All files (*.*)",
        )
        if not path:
            return
        
        try:
            with open(path, "w", encoding="utf-8") as f:
                # 如果是 JSON 格式，尝试美化输出
                if path.endswith(".json"):
                    try:
                        data = json.loads(content)
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    except json.JSONDecodeError:
                        # 不是 JSON，直接写入
                        f.write(content)
                else:
                    f.write(content)
            
            Dialogs.info("导出成功", f"世界观已导出到:\n{path}", parent=self)
        except Exception as e:
            Dialogs.warning("导出失败", str(e), parent=self)
