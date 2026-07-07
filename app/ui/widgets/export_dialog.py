"""
M10-A: 一键出版 ExportDialog.

弹窗让用户选:
- 卷 (book_id, 默认当前选中; 没项目/没卷时禁用)
- 格式 (md / txt / epub / docx)
- 封面模板 (default / minimal / wuxia / romance / scifi)
- 是否生成封面 (默认开)
- 输出路径 (QFileDialog)

调 app.services.exporter.BookExporter.export() 完成, 返回 ExportResult.
完成后弹"已生成 / 大小 / 章节数", 选"打开所在文件夹"可调资源管理器打开.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout, QWidget,
)
from app.ui.theme import text_danger_strong, text_muted

from app.ui.widgets import Dialogs  # 复用现有的弹窗协议

log = logging.getLogger(__name__)

# 复用 exporter 的常量 (单一来源)
try:
    from app.services.exporter import (
        BookExporter, SUPPORTED_FORMATS, CoverRequest, CoverGenerator,
    )
    _HAS_EXPORTER = True
except Exception as e:  # pragma: no cover
    _HAS_EXPORTER = False
    log.warning("export_dialog: 加载 exporter 失败 (%s)", e)
    SUPPORTED_FORMATS = ("md", "txt", "epub", "docx")


# 5 封面模板
COVER_TEMPLATES: List[Tuple[str, str]] = [
    ("default",  "经典 (米色 + 暖棕)"),
    ("minimal",  "极简 (白底 + 衬线)"),
    ("wuxia",    "武侠 (深红 + 山)"),
    ("romance",  "言情 (粉 + 心)"),
    ("scifi",    "科幻 (深蓝 + 网格)"),
]

# 格式后缀默认
FORMAT_EXT = {
    "md":   ".md",
    "txt":  ".txt",
    "epub": ".epub",
    "docx": ".docx",
}


class _ExportWorker(QThread):
    """后台线程跑 BookExporter.export(), 避免 UI 阻塞."""

    finished_ok = Signal(object)   # ExportResult
    finished_err = Signal(str)

    def __init__(
        self,
        project_id: str,
        book_id: Optional[str],
        fmt: str,
        output_path: str,
        with_cover: bool,
        cover_template: str,
    ) -> None:
        super().__init__()
        self.project_id = project_id
        self.book_id = book_id
        self.fmt = fmt
        self.output_path = output_path
        self.with_cover = with_cover
        self.cover_template = cover_template

    def run(self) -> None:  # pragma: no cover (在 smoke 里间接测)
        try:
            exporter = BookExporter(self.project_id, self.book_id)
            result = exporter.export(
                self.fmt,
                self.output_path,
                with_cover=self.with_cover,
                cover_template=self.cover_template,
            )
            self.finished_ok.emit(result)
        except Exception as e:
            log.exception("export failed: %s", e)
            self.finished_err.emit(str(e))


class ExportDialog(QDialog):
    """一键出版对话框.

    入口:  EditorTab / 工具栏 / 📦 导出全书
    出口:  accept() 之后用户调 .result 拿 ExportResult
    """

    def __init__(
        self,
        project_id: Optional[str],
        books: List[Tuple[str, str]],   # [(book_id, title), ...]
        current_book_id: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("📦 一键出版")
        self.setMinimumWidth(480)
        self.result = None
        self._worker: Optional[_ExportWorker] = None
        self._build_ui(project_id, books, current_book_id)

    # ------------------------------------------------------------------ UI
    def _build_ui(
        self,
        project_id: Optional[str],
        books: List[Tuple[str, str]],
        current_book_id: Optional[str],
    ) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        title = QLabel("📦 一键出版 (M9-B)")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(13)
        title.setFont(title_font)
        outer.addWidget(title)

        hint = QLabel("导出全书 (含目录 + 可选封面), 4 格式 + 5 模板, 0 第三方依赖.")
        hint.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        # ---- 无项目时降级 ----
        if not project_id or not books:
            warn = QLabel(
                "⚠ 当前没有打开项目或没有卷册, 无法导出."
                if not project_id else
                "⚠ 当前项目没有卷册, 无法导出."
            )
            warn.setStyleSheet(f"color: {text_danger_strong()}; font-size: 12px; padding: 8px;")
            warn.setWordWrap(True)
            outer.addWidget(warn)
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            bb.rejected.connect(self.reject)
            outer.addWidget(bb)
            return

        # ---- 表单 ----
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        # 卷 (book_id)
        self.cmb_book = QComboBox()
        for bid, btitle in books:
            label = btitle if btitle else f"(无标题 {bid[:8]})"
            self.cmb_book.addItem(label, userData=bid)
        if current_book_id:
            for i in range(self.cmb_book.count()):
                if self.cmb_book.itemData(i) == current_book_id:
                    self.cmb_book.setCurrentIndex(i)
                    break
        form.addRow("卷册:", self.cmb_book)

        # 格式
        self.cmb_format = QComboBox()
        for f in SUPPORTED_FORMATS:
            self.cmb_format.addItem(f"{f} ({_format_desc(f)})", userData=f)
        form.addRow("格式:", self.cmb_format)

        # 封面模板
        self.cmb_cover = QComboBox()
        for tid, tname in COVER_TEMPLATES:
            self.cmb_cover.addItem(tname, userData=tid)
        form.addRow("封面模板:", self.cmb_cover)

        # 是否生成封面
        self.chk_cover = QCheckBox("生成封面图片 (EPUB/DOCX 嵌入)")
        self.chk_cover.setChecked(True)
        form.addRow("", self.chk_cover)

        # 输出路径
        out_row = QHBoxLayout()
        self.edt_path = QLineEdit()
        self.edt_path.setPlaceholderText("选保存路径...")
        out_row.addWidget(self.edt_path, 1)
        self.btn_browse = QPushButton("📁 浏览")
        self.btn_browse.clicked.connect(self._on_browse)
        out_row.addWidget(self.btn_browse)
        form.addRow("输出路径:", _wrap(out_row))

        outer.addLayout(form)

        # ---- 进度条 (运行时显示) ----
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)
        self.progress.setFormat("⏳ 正在导出...")
        outer.addWidget(self.progress)

        # ---- 状态标签 ----
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        self.lbl_status.setWordWrap(True)
        outer.addWidget(self.lbl_status)

        # ---- 按钮 ----
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("开始导出")
        bb.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(project_id))
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)

    # ------------------------------------------------------------------ 行为
    def _on_browse(self) -> None:
        fmt = self.cmb_format.currentData() or "epub"
        ext = FORMAT_EXT.get(fmt, ".bin")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存导出文件", f"book{ext}", f"{fmt.upper()} (*{ext})"
        )
        if path:
            # 自动补后缀 (用户没写时)
            if not Path(path).suffix:
                path = path + ext
            self.edt_path.setText(path)

    def _on_accept(self) -> None:
        # 校验
        out_path = self.edt_path.text().strip()
        if not out_path:
            Dialogs.error("提示", "请先选输出路径", parent=self)
            return
        if not _HAS_EXPORTER:
            Dialogs.error(
                "不可用", "exporter 模块未加载, 请检查 app.services.exporter 是否正常", parent=self,
            )
            return
        # 启动后台线程
        self._set_running(True)
        self.lbl_status.setText(f"⏳ 正在导出 {Path(out_path).name} ...")
        self._worker = _ExportWorker(
            project_id=self.parent().current_project["id"] if hasattr(self.parent(), "current_project") and self.parent().current_project else "",
            book_id=self.cmb_book.currentData(),
            fmt=self.cmb_format.currentData() or "epub",
            output_path=out_path,
            with_cover=self.chk_cover.isChecked(),
            cover_template=self.cmb_cover.currentData() or "default",
        )
        self._worker.finished_ok.connect(self._on_export_ok)
        self._worker.finished_err.connect(self._on_export_err)
        self._worker.start()

    def _set_running(self, running: bool) -> None:
        self.progress.setVisible(running)
        # disable OK during run
        for btn in self.findChildren(QPushButton):
            if btn.text() == "开始导出":
                btn.setEnabled(not running)

    def _on_export_ok(self, result) -> None:
        self.result = result
        self._set_running(False)
        size_mb = result.file_size / (1024 * 1024) if result.file_size else 0
        msg = (
            f"✅ 已生成: {Path(result.file_path).name}\n"
            f"格式: {result.format}  章节: {result.chapter_count}  "
            f"大小: {size_mb:.2f} MB"
            + (f"\n封面: {Path(result.cover_path).name}" if result.cover_path else "")
        )
        self.lbl_status.setText(msg)
        # 弹"是否打开所在文件夹"
        if Dialogs.confirm("导出完成", msg, confirm_text="打开所在文件夹", cancel_text="关闭", parent=self):
            self._open_in_explorer(Path(result.file_path).parent)
        self.accept()

    def _on_export_err(self, err: str) -> None:
        self._set_running(False)
        self.lbl_status.setText(f"❌ 失败: {err}")
        Dialogs.error("导出失败", err, parent=self)

    @staticmethod
    def _open_in_explorer(folder: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                os.system(f'open "{folder}"')
            else:
                os.system(f'xdg-open "{folder}"')
        except Exception as e:
            log.warning("open folder failed: %s", e)


# --------------------------------------------------------------------- utils
def _format_desc(fmt: str) -> str:
    return {
        "md":   "Markdown 纯文本",
        "txt":  "TXT 纯文本",
        "epub": "EPUB 电子书 (iBooks/Kindle)",
        "docx": "Word 文档 (Office/WPS)",
    }.get(fmt, fmt)


def _wrap(layout) -> QWidget:
    """把 layout 包成 QWidget 给 QFormLayout.addRow 用."""
    w = QFrame()
    w.setLayout(layout)
    w.setContentsMargins(0, 0, 0, 0)
    return w
