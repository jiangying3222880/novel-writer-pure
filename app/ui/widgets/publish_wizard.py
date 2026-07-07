"""
M11-D: 4 步出版向导 (PublishWizard + PublishProgressWidget).

设计:
  - 用 MultiPageInput (I20) 做横向步骤条 + 翻页
  - 4 步:
      1. 📚 选卷册 (book 列表 + "全部" 选项)
      2. 📄 选格式 (md/txt/epub/docx 单选)
      3. 🎨 封面 + 元信息 (模板 + with_cover + 作者 + 简介)
      4. 💾 输出路径 + 进度 + 结果

  - 包装在 QDialog 里, 用 SubWindowDialog 风格 (无 SubWindow 头, 自由 toolbar)

  - 调 BookExporter (M9-B) 走 QThread 后台, UI 不卡

  - tokens_hint 复用 editor_export (一键出版功能, 0 元本地导出)

公开 API:
    PublishWizard(project_id, books, current_book_id, parent=None) -> QDialog
    PublishProgressWidget(...) -> QWidget
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from app.ui.theme import text_muted

from app.ui.widgets import Dialogs
from app.ui.widgets.multi_page import MultiPageInput
from app.ui.widgets.publish_progress import PublishProgressWidget  # M11-D 独立

log = logging.getLogger(__name__)

# 复用 M9-B 的常量
try:
    from app.services.exporter import (
        BookExporter,
        BookExportData,
        ChapterExport,
        CoverGenerator,
        CoverRequest,
        SUPPORTED_FORMATS,
    )
    _HAS_EXPORTER = True
except Exception as e:  # pragma: no cover
    _HAS_EXPORTER = False
    log.warning("publish_wizard: 加载 exporter 失败 (%s)", e)
    SUPPORTED_FORMATS = ("md", "txt", "epub", "docx")

# 5 封面模板
COVER_TEMPLATES: List[Tuple[str, str, str]] = [
    ("default",  "📘 经典",    "米色 + 暖棕"),
    ("minimal",  "⬜ 极简",    "白底 + 衬线"),
    ("wuxia",    "🗡️ 武侠",    "深红 + 山"),
    ("romance",  "💗 言情",    "粉 + 心"),
    ("scifi",    "🚀 科幻",    "深蓝 + 网格"),
]

FORMAT_EXT = {
    "md":   ".md",
    "txt":  ".txt",
    "epub": ".epub",
    "docx": ".docx",
}

FORMAT_DESC = {
    "md":   ("Markdown 纯文本", "适合 git 追踪 / 笔记 / 二次编辑"),
    "txt":  ("TXT 纯文本",      "无格式纯文本, 通用性最强"),
    "epub": ("EPUB 电子书",     "iBooks / Kindle / Calibre 通用"),
    "docx": ("Word 文档",       "Office / WPS 通用, 方便编辑"),
}


# ===================================================================== #
# 1. Step 1: 选卷册
# ===================================================================== #

class _BookSelectWidget(QWidget):
    """Step 1: 选卷册 (单选: "全部" / 某一卷)."""

    def __init__(self, books: List[Tuple[str, str]], current_book_id: Optional[str]) -> None:
        super().__init__()
        self._books = books
        self._build_ui(current_book_id)

    def _build_ui(self, current_book_id: Optional[str]) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        title = QLabel("📚 选择要导出的卷册")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)
        title.setFont(title_font)
        outer.addWidget(title)

        desc = QLabel("导出一整本书 (含目录), 或仅导某一卷.")
        desc.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        desc.setWordWrap(True)
        outer.addWidget(desc)

        # 列表
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

        all_item = QListWidgetItem("📦 全部卷册 (含所有章节)")
        all_item.setData(Qt.ItemDataRole.UserRole, None)  # None = 全部
        self.list_widget.addItem(all_item)

        for bid, btitle in self._books:
            label = btitle if btitle else f"(无标题 {bid[:8]})"
            item = QListWidgetItem(f"📖 {label}")
            item.setData(Qt.ItemDataRole.UserRole, bid)
            self.list_widget.addItem(item)

        # 预选: 优先 current_book_id, 否则 "全部"
        target_row = 0
        if current_book_id:
            for i in range(self.list_widget.count()):
                if self.list_widget.item(i).data(Qt.ItemDataRole.UserRole) == current_book_id:
                    target_row = i
                    break
        self.list_widget.setCurrentRow(target_row)

        outer.addWidget(self.list_widget, 1)

        # 状态
        self.lbl_status = QLabel(f"已选: {self.list_widget.currentItem().text() if self.list_widget.currentItem() else '(无)'}")
        self.lbl_status.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        self.list_widget.currentItemChanged.connect(self._on_changed)
        outer.addWidget(self.lbl_status)

    def _on_changed(self, current, _previous) -> None:
        if current:
            self.lbl_status.setText(f"已选: {current.text()}")

    def get_selected(self) -> Optional[str]:
        """返回选中的 book_id; None = 全部."""
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)


# ===================================================================== #
# 2. Step 2: 选格式
# ===================================================================== #

class _FormatSelectWidget(QWidget):
    """Step 2: 选格式 (4 单选 + 描述)."""

    def __init__(self) -> None:
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        title = QLabel("📄 选择导出格式")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)
        title.setFont(title_font)
        outer.addWidget(title)

        desc = QLabel("4 种格式, 0 第三方依赖. 推荐 EPUB (iBooks/Kindle) 或 DOCX (Word 二次编辑).")
        desc.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        desc.setWordWrap(True)
        outer.addWidget(desc)

        # 4 个 radio, 2x2 网格
        grid = QGridLayout()
        grid.setSpacing(8)

        self._btn_group = QButtonGroup(self)
        for i, fmt in enumerate(SUPPORTED_FORMATS):
            title_text, subtitle = FORMAT_DESC[fmt]
            radio = QRadioButton(f"{fmt.upper()}")
            radio.setObjectName("formatRadio")
            radio.setProperty("format_key", fmt)
            self._btn_group.addButton(radio, i)

            card = QFrame()
            # 4.0 修复: 之前 setStyleSheet 硬编码 #191a1b/#f0f1f2, 切到亮色下整张卡还是黑底.
            # 现在用 objectName="formatCard", 颜色走 theme.py 的 QFrame#formatCard / QRadioButton#formatRadio.
            card.setFrameShape(QFrame.Shape.StyledPanel)
            card.setObjectName("formatCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 8, 8, 8)
            card_layout.addWidget(radio)
            sub = QLabel(f"{title_text}\n{subtitle}")
            sub.setObjectName("formatSub")
            sub.setWordWrap(True)
            card_layout.addWidget(sub)
            # 单击卡片也选中
            def _select(checked=False, r=radio):
                r.setChecked(True)
            card.mousePressEvent = lambda ev, r=radio: r.setChecked(True)

            grid.addWidget(card, i // 2, i % 2)
        outer.addLayout(grid)

        # 默认选 epub (推荐)
        if self._btn_group.button(2):  # epub index=2
            self._btn_group.button(2).setChecked(True)
        else:
            self._btn_group.button(0).setChecked(True)

    def get_selected(self) -> str:
        btn = self._btn_group.checkedButton()
        if btn is None:
            return "epub"
        return btn.property("format_key") or "epub"


# ===================================================================== #
# 3. Step 3: 封面 + 元信息
# ===================================================================== #

class _CoverMetaWidget(QWidget):
    """Step 3: 封面模板 + with_cover + 作者 + 简介."""

    def __init__(self) -> None:
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        title = QLabel("🎨 封面 + 元信息")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)
        title.setFont(title_font)
        outer.addWidget(title)

        # 封面模板
        template_box = QGroupBox("📘 封面模板")
        t_layout = QFormLayout(template_box)

        self.cmb_template = QComboBox()
        for tid, tname, tdesc in COVER_TEMPLATES:
            self.cmb_template.addItem(f"{tname}  -  {tdesc}", userData=tid)
        t_layout.addRow("模板:", self.cmb_template)

        self.chk_with_cover = QCheckBox("生成封面图片 (EPUB/DOCX 嵌入)")
        self.chk_with_cover.setChecked(True)
        t_layout.addRow("", self.chk_with_cover)

        outer.addWidget(template_box)

        # 元信息
        meta_box = QGroupBox("✍️ 元信息 (可选)")
        m_layout = QFormLayout(meta_box)

        self.ed_author = QLineEdit()
        self.ed_author.setPlaceholderText("默认: 佚名")
        self.ed_author.setMaxLength(64)
        m_layout.addRow("作者:", self.ed_author)

        self.ed_description = QPlainTextEdit()
        self.ed_description.setPlaceholderText("书的简介 (会出现在封面后的扉页 / MD/TXT 头部)")
        self.ed_description.setMaximumHeight(80)
        m_layout.addRow("简介:", self.ed_description)

        outer.addWidget(meta_box)

        outer.addStretch(1)

    def get_cover_template(self) -> str:
        return self.cmb_template.currentData() or "default"

    def get_with_cover(self) -> bool:
        return self.chk_with_cover.isChecked()

    def get_author(self) -> str:
        return self.ed_author.text().strip() or "佚名"

    def get_description(self) -> str:
        return self.ed_description.toPlainText().strip()


# ===================================================================== #
# 4. Step 4: 输出 + 进度 (PublishProgressWidget 在 publish_progress.py)
# ===================================================================== #


# ===================================================================== #
# PublishWizard (QDialog 包装)
# ===================================================================== #

class PublishWizard(QDialog):
    """M11-D 4 步出版向导 (QDialog).

    入口: EditorTab.btn_publish_wizard (M11-D 新) / 命令行 CLI / 任意想要 4 步引导的入口
    出口: accept() 之后可读 .result (ExportResult) / .summary (dict)
    """

    def __init__(
        self,
        project_id: Optional[str],
        project_name: str = "",
        books: List[Tuple[str, str]] = None,  # [(book_id, title), ...]
        current_book_id: Optional[str] = None,
        author_name: str = "",
        description: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("📦 一键出版向导 (M11-D)")
        self.setModal(True)
        self.resize(720, 560)
        self.result_data = None  # ExportResult
        self.summary: dict = {}
        self._project_id = project_id
        self._project_name = project_name
        self._books = books or []
        self._current_book_id = current_book_id
        self._author_name = author_name
        self._description = description

        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # header
        header = QFrame(self)
        header.setObjectName("pwHeader")
        # 4.0 修复: 之前 setStyleSheet 硬编码 #0a0b0d/#f0f1f2, 切到亮色下整个头部还是黑底.
        # 现在用 objectName="pwHeader" + 主题 QSS 中的 QFrame#pwHeader / QLabel#pwTitle / QLabel#pwSubtitle.
        h = QHBoxLayout(header)
        h.setContentsMargins(16, 12, 16, 12)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel(f"📦 一键出版 — {self._project_name or '(未选项目)'}")
        title.setObjectName("pwTitle")
        title_box.addWidget(title)
        subtitle = QLabel("M11-D: 4 步引导, 0 第三方依赖, 含封面和目录")
        subtitle.setObjectName("pwSubtitle")
        title_box.addWidget(subtitle)
        h.addLayout(title_box)
        h.addStretch(1)
        outer.addWidget(header)

        # body: MultiPageInput
        self._book_w = _BookSelectWidget(self._books, self._current_book_id)
        self._fmt_w = _FormatSelectWidget()
        self._cover_w = _CoverMetaWidget()
        if self._author_name:
            self._cover_w.ed_author.setText(self._author_name)
        if self._description:
            self._cover_w.ed_description.setPlainText(self._description)
        self._progress_w = PublishProgressWidget()
        self._progress_w.set_project_id(self._project_id)
        if self._project_name:
            safe = "".join(c for c in self._project_name if c.isalnum() or c in " _-")
            self._progress_w.set_suggested_filename(safe or "book")

        self._mp = MultiPageInput(
            pages=[
                ("book",    "📚 选卷册",      self._book_w),
                ("format",  "📄 选格式",      self._fmt_w),
                ("cover",   "🎨 封面/元信息", self._cover_w),
                ("output",  "💾 输出+进度",   self._progress_w),
            ],
            finish_text="完成",
        )
        outer.addWidget(self._mp, 1)

        # 监听 page change → 把 Step 1-3 数据喂给 Step 4
        self._mp.pageChanged.connect(self._on_page_changed)

        # 监听 Step 4 完成 → 自动 accept
        self._progress_w.finished_ok.connect(self._on_export_ok)
        self._progress_w.finished_err.connect(self._on_export_err)

        # 4.0 修复: 之前 setStyleSheet 硬编码 QDialog { background: #0f1011; } 导致切到亮色下整 dialog 还是黑底.
        # QDialog 背景由主题 QSS 的 QDialog 节点管, 这里不再 inline 覆盖.

    def _on_page_changed(self, idx: int) -> None:
        if idx == 3:
            # 进入 Step 4 时, 把前面数据塞进去
            self._progress_w.set_book_id(self._book_w.get_selected())
            self._progress_w.set_format(self._fmt_w.get_selected())
            self._progress_w.set_cover_template(self._cover_w.get_cover_template())
            self._progress_w.set_with_cover(self._cover_w.get_with_cover())
            self._progress_w.set_author(self._cover_w.get_author() or self._author_name or "佚名")
            self._progress_w.set_description(self._cover_w.get_description() or self._description)

    def _on_export_ok(self, result) -> None:
        self.result_data = result
        self.summary = {
            "book_id": self._book_w.get_selected(),
            "format": self._fmt_w.get_selected(),
            "cover_template": self._cover_w.get_cover_template(),
            "with_cover": self._cover_w.get_with_cover(),
            "author": self._cover_w.get_author(),
            "description": self._cover_w.get_description(),
            "output_path": result.output_path,
            "chapter_count": result.chapter_count,
            "file_size": result.file_size,
        }
        # 2.5s 后自动关闭
        QTimer.singleShot(2500, self.accept)

    def _on_export_err(self, err: str) -> None:
        Dialogs.error("导出失败", err, parent=self)
