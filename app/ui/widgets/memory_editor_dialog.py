"""
I8 MemoryEditorDialog - 记忆编辑器 (v3.3.0 新增).

设计参考 docs/widgets-mockup.html I8 (2026-06-10 批准).

UI 结构 (按 level 分 tab):
  +----------------------------------+
  | [L1 弧] [L2 承诺/规则] [L4 遗忘] |
  +----------------------------------+
  | 列表 (主类别)        | 详情/新增  |
  | + 主线弧            | 类别: [v]  |
  |   - 主线1           | 章节: [__] |
  | + 副线弧            | 内容: [__] |
  |   - 副线1           |             |
  | + 人物弧            | [新] [删]  |
  |   - 人物弧1         |             |
  +----------------------------------+
  |         [保存] [取消]            |
  +----------------------------------+

数据通过 app.services.memory 读写, 不直接碰 DB.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets import Dialogs
from app.services import memory as memory_svc
from app.services.memory import (
    L1_CATEGORIES,
    L2_CATEGORIES,
    L4_CATEGORIES,
    CATEGORY_LABELS,
)

log = logging.getLogger(__name__)


# Tab → 关注的 category 子集
_TAB_CATEGORIES = {
    "L1": L1_CATEGORIES,
    "L2": L2_CATEGORIES,
    "L4": L4_CATEGORIES,
}
_TAB_LABELS = {
    "L1": "L1 故事弧",
    "L2": "L2 承诺/世界规则",
    "L4": "L4 已遗忘",
}


class _TabContent(QWidget):
    """单个 tab 页: 左列表 + 右编辑."""

    def __init__(self, project_id: str, categories: tuple, parent_dialog) -> None:
        super().__init__()
        self._project_id = project_id
        self._categories = categories
        self._dlg = parent_dialog
        self._memories: List[dict] = []   # in-memory cache
        self._current_id: Optional[str] = None
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # ---- 左: 列表 ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel(f"记忆列表 ({len(self._categories)} 类):"))

        self.list_mems = QListWidget()
        self.list_mems.currentItemChanged.connect(self._on_select)
        left_layout.addWidget(self.list_mems, 1)

        btn_row = QHBoxLayout()
        self.btn_new = QPushButton("新记忆")
        self.btn_new.clicked.connect(self._on_new)
        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(self.btn_new)
        btn_row.addWidget(self.btn_delete)
        btn_row.addStretch(1)
        left_layout.addLayout(btn_row)
        splitter.addWidget(left)

        # ---- 右: 编辑 ----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.cb_category = QComboBox()
        for cat in self._categories:
            self.cb_category.addItem(CATEGORY_LABELS.get(cat, cat), cat)
        form.addRow("类别:", self.cb_category)

        self.ed_chapter = QLineEdit()
        self.ed_chapter.setPlaceholderText("(可选) 关联 chapter id")
        form.addRow("关联章节:", self.ed_chapter)

        self.ed_content = QPlainTextEdit()
        self.ed_content.setPlaceholderText(
            "记忆内容 (≤ 2000 字)\n例: 主角承诺三年内登上金丹期, 否则被逐出师门"
        )
        form.addRow("内容:", self.ed_content)
        right_layout.addLayout(form)
        right_layout.addStretch(1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([260, 540])

    def reload(self) -> None:
        """从 memory_svc 重新拉数据."""
        # L1/L2/L4 用 list_by_level 拉
        if all(c in L1_CATEGORIES for c in self._categories):
            level = "L1"
        elif all(c in L2_CATEGORIES for c in self._categories):
            level = "L2"
        else:
            level = "L4"
        try:
            self._memories = [m.to_dict() for m in memory_svc.list_by_level(
                self._project_id, level)]
        except Exception as e:
            log.exception("memory list failed")
            self._memories = []
            Dialogs.warning("加载失败", str(e), parent=self._dlg)
        # 过滤掉不在本 tab 类别的 (防御性)
        self._memories = [m for m in self._memories if m["category"] in self._categories]
        self._reload_list()

    def _reload_list(self) -> None:
        self.list_mems.blockSignals(True)
        try:
            self.list_mems.clear()
            for m in self._memories:
                cat = m.get("category", "")
                cat_label = CATEGORY_LABELS.get(cat, cat)
                content_preview = (m.get("content", "") or "")[:40].replace("\n", " ")
                item = QListWidgetItem(f"[{cat_label}] {content_preview}…")
                item.setData(Qt.ItemDataRole.UserRole, m.get("id"))
                tip = (
                    f"id: {m.get('id', '')}\n"
                    f"类别: {cat_label}\n"
                    f"章节: {m.get('chapter_id', '') or '(无)'}\n"
                    f"token: {m.get('token_count', 0)}\n"
                    f"\n{m.get('content', '')}"
                )
                item.setToolTip(tip)
                self.list_mems.addItem(item)
        finally:
            self.list_mems.blockSignals(False)
        if self.list_mems.count() > 0 and self.list_mems.currentRow() < 0:
            self.list_mems.setCurrentRow(0)

    def _on_select(self, current: Optional[QListWidgetItem], _prev) -> None:
        if current is None:
            self._current_id = None
            self._clear_edit()
            return
        rid = current.data(Qt.ItemDataRole.UserRole)
        self._current_id = rid
        mem = self._find_by_id(rid)
        if mem is not None:
            self.cb_category.blockSignals(True)
            self.ed_chapter.blockSignals(True)
            self.ed_content.blockSignals(True)
            try:
                # 类别
                for i in range(self.cb_category.count()):
                    if self.cb_category.itemData(i) == mem.get("category"):
                        self.cb_category.setCurrentIndex(i)
                        break
                self.ed_chapter.setText(mem.get("chapter_id", "") or "")
                self.ed_content.setPlainText(mem.get("content", ""))
            finally:
                self.cb_category.blockSignals(False)
                self.ed_chapter.blockSignals(False)
                self.ed_content.blockSignals(False)

    def _on_new(self) -> None:
        cat = self._categories[0]
        content = "新记忆 - 请编辑"
        try:
            new_mem = memory_svc.add(
                project_id=self._project_id,
                category=cat,
                content=content,
            )
        except Exception as e:
            log.exception("memory add failed")
            Dialogs.error("新建失败", str(e), parent=self._dlg)
            return
        self._dlg._dirty = True
        self.reload()
        # 选中新加
        for i in range(self.list_mems.count()):
            it = self.list_mems.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == new_mem.id:
                self.list_mems.setCurrentRow(i)
                break

    def _on_delete(self) -> None:
        if not self._current_id:
            return
        mem = self._find_by_id(self._current_id)
        if mem is None:
            return
        if not Dialogs.confirm(
            "删除记忆",
            f"确认删除记忆? ({CATEGORY_LABELS.get(mem['category'], '')}: "
            f"{(mem.get('content') or '')[:30]}…)",
            parent=self._dlg,
        ):
            return
        try:
            memory_svc.delete(self._project_id, self._current_id)
        except Exception as e:
            log.exception("memory delete failed")
            Dialogs.error("删除失败", str(e), parent=self._dlg)
            return
        self._dlg._dirty = True
        self._current_id = None
        self.reload()
        self._clear_edit()

    def apply_pending_edit(self) -> None:
        """若当前选中行被编辑过, 保存回 DB.

        触发时机: tab 切换 / 保存按钮点击.
        行为: 把当前表单值通过 add() 写回 (upsert 语义).
        """
        if not self._current_id:
            return
        # 检查内容是否被改
        mem = self._find_by_id(self._current_id)
        if mem is None:
            return
        new_content = self.ed_content.toPlainText().strip()
        new_cat = self.cb_category.currentData()
        new_chap = self.ed_chapter.text().strip() or None
        if (
            new_content == (mem.get("content") or "").strip()
            and new_cat == mem.get("category")
            and (new_chap or "") == (mem.get("chapter_id") or "")
        ):
            return  # 无变化
        if not new_content:
            return  # 不允许空
        try:
            # 先删旧的, 再 add 新的 (memory_svc 没有 update)
            memory_svc.delete(self._project_id, self._current_id)
            new_mem = memory_svc.add(
                project_id=self._project_id,
                category=new_cat,
                content=new_content,
                chapter_id=new_chap,
            )
            self._current_id = new_mem.id
            self._dlg._dirty = True
        except Exception as e:
            log.exception("memory update failed")
            Dialogs.error("保存失败", str(e), parent=self._dlg)

    def _clear_edit(self) -> None:
        self.ed_chapter.setText("")
        self.ed_content.setPlainText("")

    def _find_by_id(self, rid: str) -> Optional[dict]:
        for m in self._memories:
            if m.get("id") == rid:
                return m
        return None


class MemoryEditorDialog(QDialog):
    """记忆编辑器 (L1/L2/L4 tabs)."""

    def __init__(self, project_id: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("🧠 记忆编辑")
        self.resize(960, 600)
        self._project_id = project_id
        self._dirty: bool = False
        self._tabs: dict = {}
        self._build()
        self._reload_all()

    def _build(self) -> None:
        outer = QVBoxLayout(self)

        header = QLabel(
            "记忆分 3 层: L1 故事弧 (always), L2 承诺/世界规则 (必须履行), L4 已遗忘 (仅索引)."
            "改完点'保存'统一落 DB."
        )
        header.setObjectName("dlgHint")
        header.setWordWrap(True)
        outer.addWidget(header)

        self.tabs = QTabWidget()
        for tab_key, cats in _TAB_CATEGORIES.items():
            content = _TabContent(self._project_id, cats, self)
            self.tabs.addTab(content, _TAB_LABELS[tab_key])
            self._tabs[tab_key] = content
        self.tabs.currentChanged.connect(self._on_tab_changed)
        outer.addWidget(self.tabs, 1)

        # 底部按钮
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_save = QPushButton("保存")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self._on_save)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self.btn_save)
        bottom.addWidget(self.btn_cancel)
        outer.addLayout(bottom)

    def _reload_all(self) -> None:
        for content in self._tabs.values():
            content.reload()

    def _on_tab_changed(self, index: int) -> None:
        # 切换前: 把当前 tab 的暂存编辑写回
        prev_key = self._current_tab_key()
        if prev_key and prev_key in self._tabs:
            self._tabs[prev_key].apply_pending_edit()
        # 重载新 tab
        new_key = self._tab_key_at(index)
        if new_key and new_key in self._tabs:
            self._tabs[new_key].reload()

    def _current_tab_key(self) -> Optional[str]:
        return self._tab_key_at(self.tabs.currentIndex())

    def _tab_key_at(self, index: int) -> Optional[str]:
        keys = list(self._tabs.keys())
        if 0 <= index < len(keys):
            return keys[index]
        return None

    def _on_save(self) -> None:
        # 把当前 tab 的编辑先写回
        cur_key = self._current_tab_key()
        if cur_key and cur_key in self._tabs:
            self._tabs[cur_key].apply_pending_edit()
        self._dirty = False
        self.accept()
