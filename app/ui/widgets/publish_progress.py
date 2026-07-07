"""
M11-D: 出版进度小部件 (PublishProgressWidget).

设计:
  - 输出路径选择 + 📁 浏览
  - 进度条 + 步骤标签
  - 启动 / 取消 按钮
  - 结果展示
  - 后台 QThread 调 BookExporter (M9-B), UI 不卡

公开 API:
    PublishProgressWidget(parent) -> QFrame
    set_project_id(pid) / set_book_id(bid) / set_format(fmt)
    set_cover_template(tpl) / set_with_cover(b) / set_author(a) / set_description(d)
    set_suggested_filename(name)
    start() -> 启动后台 export
    is_running() / is_success()
信号:
    finished_ok(ExportResult) / finished_err(str) / cancelled()

复用: 可单独嵌入其他 dialog (e.g., EditorTab 直接用, 不走 4 步向导)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from app.ui.theme import text_muted

from app.ui.widgets import Dialogs

log = logging.getLogger(__name__)

# 复用 M9-B 的常量
try:
    from app.services.exporter import (
        BookExporter,
        CoverGenerator,
        CoverRequest,
    )
    _HAS_EXPORTER = True
except Exception as e:  # pragma: no cover
    _HAS_EXPORTER = False
    log.warning("publish_progress: 加载 exporter 失败 (%s)", e)

# 格式后缀默认
FORMAT_EXT = {
    "md":   ".md",
    "txt":  ".txt",
    "epub": ".epub",
    "docx": ".docx",
}


class PublishProgressWidget(QFrame):
    """M11-D: 出版进度小部件 (Step 4 of PublishWizard)."""

    finished_ok = Signal(object)   # ExportResult
    finished_err = Signal(str)
    cancelled = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("publishProgress")
        self._project_id: Optional[str] = None
        self._book_id: Optional[str] = None
        self._format: str = "epub"
        self._cover_template: str = "default"
        self._with_cover: bool = True
        self._author: str = "佚名"
        self._description: str = ""
        self._worker: Optional[QThread] = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # 标题
        title = QLabel("💾 输出 + 进度")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(12)
        title.setFont(title_font)
        outer.addWidget(title)

        # 路径行
        path_box = QGroupBox("📁 输出路径")
        path_layout = QHBoxLayout(path_box)
        self.ed_path = QLineEdit()
        self.ed_path.setPlaceholderText("选保存路径...")
        path_layout.addWidget(self.ed_path, 1)
        self.btn_browse = QPushButton("📁 浏览…")
        self.btn_browse.clicked.connect(self._on_browse)
        path_layout.addWidget(self.btn_browse)
        outer.addWidget(path_box)

        # 进度
        prog_box = QGroupBox("⏳ 进度")
        prog_layout = QVBoxLayout(prog_box)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        prog_layout.addWidget(self.progress)
        self.lbl_step = QLabel("就绪")
        self.lbl_step.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        prog_layout.addWidget(self.lbl_step)
        outer.addWidget(prog_box)

        # 操作按钮
        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("🚀 开始导出")
        self.btn_start.setObjectName("primaryAction")
        self.btn_start.clicked.connect(self.start)
        self.btn_start.setDefault(True)
        btn_row.addWidget(self.btn_start)
        self.btn_cancel = QPushButton("⏹ 取消")
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_cancel.setEnabled(False)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        # 结果区
        result_box = QGroupBox("📊 结果")
        result_layout = QVBoxLayout(result_box)
        self.lbl_result = QLabel("未运行")
        self.lbl_result.setStyleSheet(f"color: {text_muted()}; font-size: 11px; font-family: Consolas, monospace;")
        self.lbl_result.setWordWrap(True)
        result_layout.addWidget(self.lbl_result)
        outer.addWidget(result_box, 1)

    # ---- 配置 ----

    def set_project_id(self, pid: Optional[str]) -> None:
        self._project_id = pid

    def set_book_id(self, bid: Optional[str]) -> None:
        self._book_id = bid

    def set_format(self, fmt: str) -> None:
        self._format = fmt

    def set_cover_template(self, tpl: str) -> None:
        self._cover_template = tpl

    def set_with_cover(self, b: bool) -> None:
        self._with_cover = b

    def set_author(self, author: str) -> None:
        self._author = author

    def set_description(self, desc: str) -> None:
        self._description = desc

    def set_suggested_filename(self, name: str) -> None:
        """预填默认文件名 (扩展名按当前 format)."""
        if not self.ed_path.text():
            ext = FORMAT_EXT.get(self._format, ".bin")
            self.ed_path.setText(str(Path(name).with_suffix(ext)))

    # ---- 行为 ----

    def _on_browse(self) -> None:
        ext = FORMAT_EXT.get(self._format, ".bin")
        default_name = f"book{ext}"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存导出文件", default_name, f"{self._format.upper()} (*{ext})"
        )
        if path:
            if not Path(path).suffix:
                path = path + ext
            self.ed_path.setText(path)

    def start(self) -> None:
        out_path = self.ed_path.text().strip()
        if not out_path:
            Dialogs.error("提示", "请先选输出路径", parent=self)
            return
        if not self._project_id:
            Dialogs.error("提示", "未选择项目, 无法导出", parent=self)
            return
        if not _HAS_EXPORTER:
            Dialogs.error("不可用", "exporter 模块未加载", parent=self)
            return

        # 启动后台线程
        self._set_running(True)
        self.progress.setValue(5)
        self.lbl_step.setText("⏳ 正在准备导出...")
        self.lbl_result.setText("⏳ 运行中...")

        self._worker = _PublishWorker(
            project_id=self._project_id,
            book_id=self._book_id,
            fmt=self._format,
            output_path=out_path,
            with_cover=self._with_cover,
            cover_template=self._cover_template,
            author=self._author,
            description=self._description,
        )
        self._worker.progress_step.connect(self._on_step)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.finished_err.connect(self._on_err)
        self._worker.start()

    def _set_running(self, running: bool) -> None:
        self.btn_start.setEnabled(not running)
        self.btn_cancel.setEnabled(running)
        self.ed_path.setEnabled(not running)
        self.btn_browse.setEnabled(not running)

    def _on_step(self, pct: int, msg: str) -> None:
        self.progress.setValue(pct)
        self.lbl_step.setText(msg)

    def _on_ok(self, result) -> None:
        self._set_running(False)
        self.progress.setValue(100)
        size_mb = result.file_size / (1024 * 1024) if result.file_size else 0
        msg = (
            f"✅ 已生成: {Path(result.output_path).name}\n"
            f"格式: {result.format}  章节: {result.chapter_count}  "
            f"大小: {size_mb:.2f} MB\n"
            f"用时: {result.duration_ms} ms"
        )
        if result.cover_path:
            msg += f"\n封面: {Path(result.cover_path).name}"
        self.lbl_step.setText("✓ 完成")
        self.lbl_result.setText(msg)
        self.finished_ok.emit(result)

    def _on_err(self, err: str) -> None:
        self._set_running(False)
        self.lbl_step.setText("✗ 失败")
        self.lbl_result.setText(f"❌ 失败: {err}")
        self.finished_err.emit(err)

    def _on_cancel(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
            self.lbl_step.setText("⏸ 正在取消...")
        self.cancelled.emit()

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def is_success(self) -> bool:
        return self.lbl_step.text() == "✓ 完成"


class _PublishWorker(QThread):
    """后台跑 BookExporter, 派发 step 信号."""

    progress_step = Signal(int, str)
    finished_ok = Signal(object)
    finished_err = Signal(str)

    def __init__(
        self,
        project_id: str,
        book_id: Optional[str],
        fmt: str,
        output_path: str,
        with_cover: bool,
        cover_template: str,
        author: str = "佚名",
        description: str = "",
    ) -> None:
        super().__init__()
        self.project_id = project_id
        self.book_id = book_id
        self.fmt = fmt
        self.output_path = output_path
        self.with_cover = with_cover
        self.cover_template = cover_template
        self.author = author
        self.description = description

    def run(self) -> None:  # pragma: no cover (smoke 间接测)
        try:
            self.progress_step.emit(15, "📚 加载章节数据...")
            exporter = BookExporter(self.project_id, self.book_id)
            self.progress_step.emit(35, "🎨 准备封面...")

            result = exporter.export(
                self.fmt,
                self.output_path,
                with_cover=self.with_cover,
                cover_template=self.cover_template,
            )
            self.progress_step.emit(100, "✓ 完成")
            self.finished_ok.emit(result)
        except Exception as e:
            log.exception("publish worker 失败: %s", e)
            self.finished_err.emit(str(e))
