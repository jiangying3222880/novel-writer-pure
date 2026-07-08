"""
单元池 Widget (M5 / WS5)

功能:
- 浏览 / 按 genre·scene_type·emotion·tags·query 检索池单元
- 新增 / 编辑 / 删除 单元 (<=1000 字)
- 批量导入 (多段文本)
- 「发送到项目」: clone_to_project 克隆进当前项目的 story_units

服务于用户核心目标: 规划灵感与主线后, 用池里的 1000 字内故事单元拼装小说。
"""
from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QLineEdit, QComboBox, QTextEdit, QDialog,
    QFormLayout, QDialogButtonBox, QMessageBox, QFrame, QPlainTextEdit,
    QSpinBox,
)


def _fmt_item(d: dict) -> str:
    meta = []
    if d.get("genre") and d["genre"] != "通用":
        meta.append(d["genre"])
    if d.get("emotion"):
        meta.append(d["emotion"])
    if d.get("scene_type"):
        meta.append(d["scene_type"])
    tag = f"  #{','.join(d.get('tags', [])[:3])}" if d.get("tags") else ""
    head = f"[{meta}] " if meta else ""
    return f"{head}{d['title']}  ({d.get('word_count', 0)}字){tag}"


class UnitPoolWidget(QWidget):
    units_changed = Signal()          # 池内容变化
    units_cloned = Signal(str)        # 克隆到项目 pid

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._project_id: str = ""
        self._build()

    # ---------------------------------------------------------------- #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # 过滤区
        filt = QHBoxLayout()
        filt.addWidget(QLabel("题材"))
        self._genre = QLineEdit()
        self._genre.setPlaceholderText("如 仙侠 / 留空=全部")
        filt.addWidget(self._genre)
        filt.addWidget(QLabel("场景"))
        self._scene = QLineEdit()
        filt.addWidget(self._scene)
        filt.addWidget(QLabel("情绪"))
        self._emotion = QLineEdit()
        filt.addWidget(self._emotion)
        filt.addWidget(QLabel("标签"))
        self._tags = QLineEdit()
        self._tags.setPlaceholderText("逗号分隔")
        filt.addWidget(self._tags)
        self._btn_search = QPushButton("检索")
        self._btn_search.clicked.connect(self.refresh)
        filt.addWidget(self._btn_search)
        root.addLayout(filt)

        filt2 = QHBoxLayout()
        filt2.addWidget(QLabel("关键词"))
        self._query = QLineEdit()
        self._query.setPlaceholderText("标题/正文模糊")
        filt2.addWidget(self._query)
        self._btn_reset = QPushButton("清空")
        self._btn_reset.clicked.connect(self._on_reset)
        filt2.addWidget(self._btn_reset)
        filt2.addStretch(1)
        root.addLayout(filt2)

        # 主区: 列表 + 详情
        body = QHBoxLayout()
        root.addLayout(body)

        left = QVBoxLayout()
        left.addWidget(QLabel("单元池（<=1000字）"))
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_select)
        left.addWidget(self._list, 1)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("预览 / 编辑"))
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        right.addWidget(self._detail, 1)

        row = QHBoxLayout()
        self._btn_add = QPushButton("＋新增")
        self._btn_add.clicked.connect(self._on_add)
        self._btn_edit = QPushButton("✎编辑")
        self._btn_edit.clicked.connect(self._on_edit)
        self._btn_del = QPushButton("🗑删除")
        self._btn_del.clicked.connect(self._on_delete)
        self._btn_bulk = QPushButton("⤓批量导入")
        self._btn_bulk.clicked.connect(self._on_bulk)
        self._btn_send = QPushButton("➡发送到项目")
        self._btn_send.clicked.connect(self._on_send)
        for b in (self._btn_add, self._btn_edit, self._btn_del, self._btn_bulk, self._btn_send):
            row.addWidget(b)
        right.addLayout(row)
        body.addLayout(right, 2)

        self._status = QLabel("")
        root.addWidget(self._status)

        self.refresh()

    # ---------------------------------------------------------------- #
    def set_project(self, project) -> None:
        pid = getattr(project, "id", None) or (project if isinstance(project, str) else "")
        self._project_id = pid or ""
        self._btn_send.setEnabled(bool(self._project_id))

    def _search_kwargs(self) -> dict:
        tags = [t.strip() for t in self._tags.text().split(",") if t.strip()] or None
        return dict(
            genre=self._genre.text().strip(),
            scene_type=self._scene.text().strip(),
            emotion=self._emotion.text().strip(),
            query=self._query.text().strip(),
            tags=tags,
        )

    def refresh(self) -> None:
        from app.services import unit_pool_service as ups
        try:
            rows = ups.search_by_tags(**self._search_kwargs(), top_k=200)
        except Exception as e:
            self._status.setText(f"检索失败: {e}")
            return
        self._list.blockSignals(True)
        self._list.clear()
        for d in rows:
            item = QListWidgetItem(_fmt_item(d))
            item.setData(Qt.UserRole, d["id"])
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._status.setText(f"共 {len(rows)} 条")

    def _on_reset(self) -> None:
        self._genre.clear(); self._scene.clear(); self._emotion.clear()
        self._tags.clear(); self._query.clear()
        self.refresh()

    def _on_select(self, cur, _prev) -> None:
        if cur is None:
            self._detail.clear()
            return
        pid = cur.data(Qt.UserRole)
        from app.services import unit_pool_service as ups
        try:
            d = ups.get(pid)
        except Exception:
            self._detail.clear()
            return
        self._detail.setPlainText(d["content"])

    # ---------------------------------------------------------------- #
    def _on_add(self) -> None:
        dlg = _UnitEditDialog(self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            from app.services import unit_pool_service as ups
            ups.create(**data)
            self.refresh()
            self.units_changed.emit()
            self._status.setText("已新增单元")

    def _on_edit(self) -> None:
        cur = self._list.currentItem()
        if cur is None:
            return
        pid = cur.data(Qt.UserRole)
        from app.services import unit_pool_service as ups
        d = ups.get(pid)
        dlg = _UnitEditDialog(self, d)
        if dlg.exec() == QDialog.Accepted:
            ups.update(pid, **dlg.get_data())
            self.refresh()
            self.units_changed.emit()
            self._status.setText("已保存修改")

    def _on_delete(self) -> None:
        cur = self._list.currentItem()
        if cur is None:
            return
        pid = cur.data(Qt.UserRole)
        if QMessageBox.question(self, "删除", "确认删除该单元？") != QMessageBox.Yes:
            return
        from app.services import unit_pool_service as ups
        ups.delete(pid)
        self.refresh()
        self.units_changed.emit()
        self._status.setText("已删除")

    def _on_bulk(self) -> None:
        dlg = _BulkImportDialog(self)
        if dlg.exec() == QDialog.Accepted:
            texts = dlg.get_texts()
            genre = dlg.genre()
            if not texts:
                return
            from app.services import unit_pool_service as ups
            created = ups.bulk_import(texts, genre=genre, source="manual")
            self.refresh()
            self.units_changed.emit()
            self._status.setText(f"批量导入 {len(created)} 条")

    def _on_send(self) -> None:
        sel = [self._list.item(i) for i in range(self._list.count())
               if self._list.item(i).isSelected()]
        if not sel:
            # 未多选则发当前选中
            cur = self._list.currentItem()
            sel = [cur] if cur else []
        if not sel:
            QMessageBox.information(self, "提示", "请先选中要发送的单元")
            return
        if not self._project_id:
            QMessageBox.information(self, "提示", "请先打开一个项目")
            return
        from app.services import unit_pool_service as ups
        n = 0
        for it in sel:
            pid = it.data(Qt.UserRole)
            try:
                ups.clone_to_project(pid, self._project_id)
                n += 1
            except Exception as e:
                self._status.setText(f"克隆失败 {pid}: {e}")
        self._status.setText(f"已克隆 {n} 个单元到当前项目")
        self.units_cloned.emit(self._project_id)


# ────────────────────── 编辑对话框 ──────────────────────

class _UnitEditDialog(QDialog):
    def __init__(self, parent, data: Optional[dict] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑单元" if data else "新增单元")
        self.resize(520, 460)
        self._data = data
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self._title = QLineEdit(data["title"] if data else "")
        self._content = QPlainTextEdit(data["content"] if data else "")
        self._content.setMaximumHeight(220)
        self._genre = QLineEdit(data.get("genre", "通用") if data else "通用")
        self._scene = QLineEdit(data.get("scene_type", "") if data else "")
        self._emotion = QLineEdit(data.get("emotion", "") if data else "")
        self._tags = QLineEdit(",".join(data.get("tags", [])) if data else "")
        form.addRow("标题", self._title)
        form.addRow("正文(≤1000)", self._content)
        form.addRow("题材", self._genre)
        form.addRow("场景类型", self._scene)
        form.addRow("情绪", self._emotion)
        form.addRow("标签(逗号)", self._tags)
        lay.addLayout(form)
        self._warn = QLabel("")
        lay.addWidget(self._warn)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_ok)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _on_ok(self) -> None:
        c = self._content.toPlainText()
        if len(c) > 1000:
            self._warn.setText(f"正文 {len(c)} 字，超过 1000 字上限（将截断）")
        self.accept()

    def get_data(self) -> dict:
        return dict(
            title=self._title.text().strip(),
            content=self._content.toPlainText(),
            genre=self._genre.text().strip() or "通用",
            scene_type=self._scene.text().strip(),
            emotion=self._emotion.text().strip(),
            tags=[t.strip() for t in self._tags.text().split(",") if t.strip()],
        )


class _BulkImportDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("批量导入单元")
        self.resize(560, 480)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("每段之间用空行分隔（或 --- 分隔），每段 ≤1000字"))
        self._edit = QPlainTextEdit()
        lay.addWidget(self._edit, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("题材"))
        self._genre = QLineEdit("通用")
        row.addWidget(self._genre)
        lay.addLayout(row)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def genre(self) -> str:
        return self._genre.text().strip() or "通用"

    def get_texts(self) -> list:
        raw = self._edit.toPlainText()
        blocks = re.split(r"\n\s*---\s*\n|\n{2,}", raw)
        return [b.strip() for b in blocks if b.strip()]
