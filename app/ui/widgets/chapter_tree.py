"""
Unit Tree Widget (v4.3 重构)

以「卷(书) → 单元」的层级展示全书单元结构，供发布模块浏览/选择。
点击单元时通过 chapter_selected 信号上抛 unit_id。
章节是单元的窗口，最终展示时才生成。
"""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem,
)


class ChapterTree(QWidget):
    chapter_selected = Signal(str)       # chapter_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._project_id: str = ""
        self._build()

    def _build(self) -> None:
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        title = QLabel("📚 单元结构")
        title.setStyleSheet("font-size: 13px; font-weight: 700; color: #cdd6f4;")
        layout.addWidget(title)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(16)
        self._tree.setStyleSheet(
            "QTreeWidget { background: #1e1e2e; border: 1px solid #313244; "
            "border-radius: 4px; }"
            "QTreeWidget::item { padding: 3px 6px; color: #a6adc8; }"
            "QTreeWidget::item:selected { background: #45475a; color: #cdd6f4; }"
        )
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree, 1)

    # -------------------------------------------------------------- #
    def set_project(self, project_id: str) -> None:
        self._project_id = project_id
        self._reload()

    def _reload(self) -> None:
        self._tree.clear()
        if not self._project_id:
            self._empty("(无项目)")
            return
        try:
            from app.services import book_service
            from app.services import chapter_service

            books = book_service.list_for_project(self._project_id) or []
            # list_for_project 返回 list[dict] 或 {"books": [...]}
            if isinstance(books, dict):
                books = books.get("books", [])
        except Exception:
            books = []

        if not books:
            self._empty("(无单元)")
            return

        for book in books:
            book_id = book.get("id")
            vol_no = book.get("volume_no", 0)
            book_title = book.get("title") or f"卷{vol_no}"
            book_item = QTreeWidgetItem(self._tree)
            book_item.setText(0, f"📖 卷{vol_no} · {book_title}")
            book_item.setFlags(Qt.ItemFlag.ItemIsEnabled)

            try:
                res = chapter_service.list_for_book(book_id) or {}
                chapters = res.get("chapters", []) or []
            except Exception:
                chapters = []

            if not chapters:
                sub = QTreeWidgetItem(book_item)
                sub.setText(0, "  (暂无单元)")
                sub.setFlags(Qt.ItemFlag.NoItemFlags)
                continue

            for ch in chapters:
                cid = ch.get("id")
                ch_no = ch.get("chapter_no", "?")
                ch_title = ch.get("title") or "未命名"
                item = QTreeWidgetItem(book_item)
                item.setText(0, f"单元 {ch_no}  {ch_title}")
                item.setData(0, Qt.ItemDataRole.UserRole, cid)
                item.setToolTip(0, f"单元 {ch_no}: {ch_title}")
            book_item.setExpanded(True)

    def _empty(self, text: str) -> None:
        item = QTreeWidgetItem(self._tree)
        item.setText(0, text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)

    def _on_item_clicked(self, item: QTreeWidgetItem, col: int) -> None:
        cid = item.data(0, Qt.ItemDataRole.UserRole)
        if cid:
            self.chapter_selected.emit(cid)
