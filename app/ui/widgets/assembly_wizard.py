"""
Assembly Wizard (v4.0 发布成稿向导)

正确领域流程 (用户确认):
  选 >=2 单元 -> 拼接合并 (双时间线决定过渡) -> 确认目标字数 ->
  检测断章点 (字数附近情绪点) -> 用户确认 -> 断章 ->
  每章推荐 3 标题 (3选1) -> 落库 (含单元级溯源 unit_spans).

由 publish 模块打开.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QTextBrowser, QComboBox, QSpinBox, QDialog,
    QFrame, QMessageBox,
)

from app.services import story_unit_service_v2 as usvc
from app.services import manuscript_assembly as ma


class AssemblyWizard(QDialog):
    chapters_created = Signal()   # 落库成功后通知外部刷新章节树

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("成稿向导 · 多单元拼接断章")
        self.resize(900, 640)
        self._pid: str = ""
        self._manuscript: Optional[ma.AssembledManuscript] = None
        self._split_ranges: list[tuple[int, int]] = []
        self._chapters_data: list[dict] = []
        self._title_combos: list[QComboBox] = []
        self._build()

    # -------------------------------------------------------------- #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        head = QHBoxLayout()
        head.addWidget(QLabel("成稿向导：多单元拼接 → 断章 → 标题"))
        head.addStretch(1)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.reject)
        head.addWidget(btn_close)
        root.addLayout(head)

        body = QHBoxLayout()
        root.addLayout(body)

        # 左: 单元多选
        left = QVBoxLayout()
        left.addWidget(QLabel("① 选择单元 (>=2)"))
        self._unit_list = QListWidget()
        self._unit_list.setSelectionMode(QListWidget.NoSelection)
        left.addWidget(self._unit_list, 1)
        body.addLayout(left, 1)

        # 右: 操作流
        right = QVBoxLayout()
        body.addLayout(right, 2)

        # 拼接
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("时间线:"))
        self._timeline = QComboBox()
        self._timeline.addItems(["线性 (story_order)", "非线性 (present_order)"])
        row1.addWidget(self._timeline)
        self._btn_assemble = QPushButton("① 拼接合并")
        self._btn_assemble.clicked.connect(self._on_assemble)
        row1.addWidget(self._btn_assemble)
        right.addLayout(row1)

        self._preview = QTextBrowser()
        self._preview.setMaximumHeight(160)
        right.addWidget(self._preview)

        # 断章
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("目标字数:"))
        self._target = QSpinBox()
        self._target.setRange(300, 6000)
        self._target.setValue(1500)
        self._target.setSingleStep(100)
        row2.addWidget(self._target)
        row2.addWidget(QLabel("策略:"))
        self._strategy = QComboBox()
        self._strategy.addItems(["auto", "suspense", "climax", "reveal", "crisis"])
        row2.addWidget(self._strategy)
        self._btn_detect = QPushButton("② 检测断章点")
        self._btn_detect.clicked.connect(self._on_detect_splits)
        row2.addWidget(self._btn_detect)
        right.addLayout(row2)

        self._split_list = QListWidget()
        self._split_list.setMaximumHeight(90)
        right.addWidget(self._split_list)

        self._btn_split_titles = QPushButton("③ 断章并推荐标题 (3选1)")
        self._btn_split_titles.clicked.connect(self._on_split_and_titles)
        right.addWidget(self._btn_split_titles)

        # 标题选择区 (动态)
        self._title_zone = QVBoxLayout()
        right.addLayout(self._title_zone)

        self._btn_persist = QPushButton("④ 生成章节并落库")
        self._btn_persist.clicked.connect(self._on_persist)
        self._btn_persist.setEnabled(False)
        right.addWidget(self._btn_persist)

        self._status = QLabel("")
        right.addWidget(self._status)

    # -------------------------------------------------------------- #
    def set_project(self, pid: str) -> None:
        self._pid = pid
        self._unit_list.clear()
        try:
            units = usvc.list_for_project(pid, order_by="story")
        except Exception as e:
            self._status.setText(f"加载单元失败: {e}")
            return
        for u in units:
            item = QListWidgetItem(f"[U{u.unit_no:03d}] {u.title}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, u.id)
            self._unit_list.addItem(item)

    def _checked_unit_ids(self) -> list[str]:
        ids = []
        for i in range(self._unit_list.count()):
            it = self._unit_list.item(i)
            if it.checkState() == Qt.Checked:
                ids.append(it.data(Qt.UserRole))
        return ids

    # -------------------------------------------------------------- #
    def _on_assemble(self) -> None:
        ids = self._checked_unit_ids()
        if len(ids) < 2:
            self._status.setText("请至少勾选 2 个单元")
            return
        mode = "present" if self._timeline.currentIndex() == 1 else "story"
        try:
            self._manuscript = ma.assemble_units(self._pid, ids, timeline_mode=mode)
        except Exception as e:
            self._status.setText(f"拼接失败: {e}")
            return
        if not self._manuscript.merged_text.strip():
            self._status.setText("所选单元无正文内容，无法拼接")
            return
        txt = self._manuscript.merged_text
        if self._manuscript.transitions:
            tr = "\n".join(f"  · {t['note']} (U{t['unit_no']:03d})" for t in self._manuscript.transitions)
            txt += f"\n\n— 过渡标注 —\n{tr}"
        self._preview.setPlainText(txt)
        self._status.setText(
            f"已拼接 {len(ids)} 个单元，共 {len(self._manuscript.merged_text)} 字，"
            f"{len(self._manuscript.segments)} 个段落"
        )

    def _on_detect_splits(self) -> None:
        if not self._manuscript or not self._manuscript.merged_text.strip():
            self._status.setText("请先拼接合并")
            return
        try:
            rep = ma.compute_split_points(
                self._manuscript.merged_text,
                self._target.value(),
                self._strategy.currentText(),
            )
        except Exception as e:
            self._status.setText(f"断章检测失败: {e}")
            return
        self._split_list.clear()
        if not rep.recommended_splits:
            self._status.setText(
                f"未找到合适断章点（总 {rep.total_chars} 字，目标 {self._target.value()}）。"
                "可减小目标字数或调整策略。"
            )
            return
        for pos in rep.recommended_splits:
            item = QListWidgetItem(f"第 {pos} 字处断章")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self._split_list.addItem(item)
        self._status.setText(f"检测到 {len(rep.recommended_splits)} 个断章点（已全选，可取消）")

    def _on_split_and_titles(self) -> None:
        if not self._manuscript:
            self._status.setText("请先拼接合并")
            return
        points = []
        for i in range(self._split_list.count()):
            it = self._split_list.item(i)
            if it.checkState() == Qt.Checked:
                try:
                    points.append(int(it.text().split("第")[1].split("字")[0].strip()))
                except Exception:
                    pass
        if not points:
            self._status.setText("请至少勾选 1 个断章点")
            return
        try:
            ranges = ma.split_manuscript(self._manuscript.merged_text, points)
            self._split_ranges = ranges
            chapters_text = [self._manuscript.merged_text[s:e].strip() for s, e in ranges]
            self._chapters_data = []
            for (s, e), txt in zip(ranges, chapters_text):
                spans = ma.chapter_source_units(s, e, self._manuscript.segments)
                source_units = [sp["unit_id"] for sp in spans]
                titles = ma.recommend_titles(txt, n=3)
                self._chapters_data.append({
                    "text": txt, "unit_spans": spans,
                    "source_units": source_units, "titles": titles,
                })
        except Exception as e:
            self._status.setText(f"断章失败: {e}")
            return
        self._build_title_zone()
        self._btn_persist.setEnabled(True)
        self._status.setText(f"已断为 {len(self._chapters_data)} 章，请为每章选择标题")

    def _build_title_zone(self) -> None:
        # 清空旧
        while self._title_zone.count():
            w = self._title_zone.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._title_combos = []
        for i, ch in enumerate(self._chapters_data, start=1):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"第{i}章"))
            cb = QComboBox()
            cb.addItems(ch["titles"])
            row.addWidget(cb, 1)
            row.addWidget(QLabel(f"{len(ch['text'])}字 · 源U:"
                                 f"{','.join('U%d'%sp['unit_no'] for sp in ch['unit_spans'])}"))
            self._title_zone.addLayout(row)
            self._title_combos.append(cb)

    def _on_persist(self) -> None:
        if not self._manuscript or not self._chapters_data:
            self._status.setText("没有可生成的章节")
            return
        book_id = self._manuscript.book_id
        if not book_id:
            self._status.setText("拼接稿件无归属分卷，无法落库")
            return
        data = []
        for i, ch in enumerate(self._chapters_data):
            title = self._title_combos[i].currentText() if i < len(self._title_combos) else f"第{i+1}章"
            data.append({
                "text": ch["text"], "title": title,
                "unit_spans": ch["unit_spans"], "source_units": ch["source_units"],
            })
        try:
            ids = ma.persist_chapters(book_id, data)
        except Exception as e:
            self._status.setText(f"落库失败: {e}")
            return
        self._status.setText(f"已生成 {len(ids)} 章并写入单元溯源")
        self.chapters_created.emit()
        QMessageBox.information(self, "成稿完成", f"已生成 {len(ids)} 章，可在章节树查看。")
