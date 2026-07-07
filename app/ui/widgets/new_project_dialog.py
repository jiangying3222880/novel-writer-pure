"""综合新建项目弹窗 (替换原两次 Dialogs.input).

一次弹窗收集 7 字段:
  - 项目名 (必填)
  - 书名 (可空, 预填项目名)
  - 主题材 (单选, QComboBox, 16 类大分类: 玄幻/都市/仙侠/...)
  - 副题材 (多选, 元素标签: 脑洞/爽文/穿越/重生/系统/无限流/...) 0~N 个
  - 平台 (多选, 复用 PLATFORM_PRESETS 9 个)
  - 分卷数 (QSpinBox, 1-20, 默认 1)
  - 章节数 (每卷, QSpinBox, 1-5000, 默认 100)
  - 章节字数 (QSpinBox, 500-50000, 默认 2000)
  - 总章节数 = 分卷数 × 章节数 (只读, 自动算)
  - 总字数 = 总章节数 × 章节字数 (只读, 自动算, 写到 project.word_target)

V4.0-P2-新: 「1 主题材 + N 副题材」双轨. 主题材 QComboBox 单选, 副题材 chip
风格多选弹窗. 主题材写到 project.genre, 副题材写到 structure.json 的 sub_genres.

设计动机:
  - 之前只有 word_target 一个聚合数, 用户分不清「计划多少字 / 已经写多少 / 还差多少」.
  - 引入分卷数 + 章节数 + 章节字数, 自动算总章节数 / 总字数.
  - 总字数 = 计划目标, 写入 project.word_target, 与原 API 兼容.
  - 主题材/副题材拆分: 主题材决定 prompt 的「主世界基调」, 副题材是 prompt 的
    「元素标签」, 两者注入到 prompt_assembler 时, 主选 genre, 副叠加到 keywords.
"""
from __future__ import annotations
from typing import Optional, Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton,
    QWidget, QFrame, QComboBox,
)
from app.ui.theme import text_muted

from app.services.genre_presets import GENRE_PRESETS, PLATFORM_PRESETS
from app.ui.widgets._number_input import NumberInput


class NewProjectDialog(QDialog):
    """新建/编辑项目综合弹窗.

    Usage:
        # 新建
        dlg = NewProjectDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.result()  # dict | None
            if data:
                project_service.create(**data)

        # 编辑 (V4.0-P3-新)
        existing = project_service.get(pid)
        dlg = NewProjectDialog(parent=self, mode="edit", initial=existing)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.result()
            if data:
                project_service.update(pid, **data)

    V4.0-P3-新:
      - 加 `author` 字段 (作者), 写到 projects.author + structure.json
      - 支持 mode="new" / mode="edit"
        · new 模式: 全部字段可写
        · edit 模式: 预填已有数据, 标题/按钮改成「编辑/保存」, 分卷数/章节数/章节
          字数 3 个字段**灰掉** (改它们会破坏 books 与已写章节的一致性, 需独立
          「重建结构」流程, 不在本次范围).
    """

    DEFAULT_VOLUMES = 1                 # 1 卷
    DEFAULT_CHAPTERS_PER_VOLUME = 100   # 100 章
    DEFAULT_WORDS_PER_CHAPTER = 2_000   # 2000 字/章
    DEFAULT_WORD_TARGET = 200_000       # 兜底 (覆盖到 sum 计算后的值)

    MIN_VOLUMES = 1
    MAX_VOLUMES = 20
    MIN_CHAPTERS = 1
    MAX_CHAPTERS = 5_000
    MIN_WORDS_PER_CHAPTER = 500
    MAX_WORDS_PER_CHAPTER = 50_000

    def __init__(self, parent: Optional[QWidget] = None,
                 *, mode: str = "new",
                 initial: Optional[Dict] = None) -> None:
        super().__init__(parent)
        self._mode = mode if mode in ("new", "edit") else "new"
        self._initial: Dict = dict(initial or {})

        if self._mode == "edit":
            self.setWindowTitle("编辑项目")
        else:
            self.setWindowTitle("新建项目")
        self.setModal(True)
        self.resize(640, 760)

        self._result: Optional[Dict] = None
        # V4.0-P2-新: 主题材 (单, 显示名) + 副题材 (多, 显示名列表)
        self._main_genre: Optional[str] = None
        self._sub_genres: List[str] = []
        self._platform_list: List[str] = []

        self._build_ui()
        self._prefill_from_initial()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Hint
        if self._mode == "edit":
            hint_text = "✏️ 修改项目基础信息（分卷数/章节数/章节字数一旦建好 books 不可改）"
        else:
            hint_text = "🆕 填写项目基础信息（题材/平台可后续在「小说设定」调整）"
        hint = QLabel(hint_text)
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Form
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # 1) 项目名
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("例如: M2 重构测试")
        self.ed_name.setMaxLength(64)
        form.addRow("项目名 *", self.ed_name)

        # 2) 书名
        self.ed_book = QLineEdit()
        self.ed_book.setPlaceholderText("例如: 仙路独行 (可空)")
        self.ed_book.setMaxLength(128)
        form.addRow("书名", self.ed_book)

        # 3) 作者 (V4.0-P3-新)
        self.ed_author = QLineEdit()
        self.ed_author.setPlaceholderText("例如: 树下野狐 (可空, 匿名创作可不填)")
        self.ed_author.setMaxLength(64)
        form.addRow("作者", self.ed_author)

        # 3) 主题材 (单选, QComboBox)
        self.cmb_genre = QComboBox()
        self.cmb_genre.setObjectName("cmbMainGenre")
        self.cmb_genre.addItem("（请选择 1 个主题材）", userData=None)
        for _gid, name, _desc, _kw in GENRE_PRESETS:
            self.cmb_genre.addItem(name, userData=name)
        self.cmb_genre.setCurrentIndex(0)
        self.cmb_genre.currentIndexChanged.connect(self._on_main_genre_changed)
        form.addRow("主题材 *", self.cmb_genre)

        # 4) 副题材 (多选 chip + 弹窗)
        sub_row = QHBoxLayout()
        sub_row.setSpacing(6)
        self.lbl_sub = QLabel("（未选）")
        self.lbl_sub.setObjectName("valueLabel")
        self.lbl_sub.setWordWrap(True)
        sub_row.addWidget(self.lbl_sub, 1)
        btn_sub = QPushButton("🏷️ 选择…")
        btn_sub.setObjectName("btnPickSubGenre")
        btn_sub.setToolTip("选 0~N 个元素标签: 脑洞/爽文/穿越/重生/系统/无限流/...")
        btn_sub.clicked.connect(self._pick_subgenre)
        sub_row.addWidget(btn_sub)
        form.addRow("副题材 (可多选)", sub_row)

        # 5) 平台 (多选)
        plat_row = QHBoxLayout()
        plat_row.setSpacing(6)
        self.lbl_plat = QLabel("（未选）")
        self.lbl_plat.setObjectName("valueLabel")
        self.lbl_plat.setWordWrap(True)
        plat_row.addWidget(self.lbl_plat, 1)
        btn_plat = QPushButton("🏷️ 选择…")
        btn_plat.setObjectName("btnPickPlatform")
        btn_plat.clicked.connect(self._pick_platform)
        plat_row.addWidget(btn_plat)
        form.addRow("平台", plat_row)

        # 6) 分卷数 + 章节数 (一行两列, 紧贴, 单位「卷 / 章/卷」)
        structure_row = QHBoxLayout()
        structure_row.setSpacing(8)
        self.spin_volumes = NumberInput(lo=self.MIN_VOLUMES, hi=self.MAX_VOLUMES, default=self.DEFAULT_VOLUMES, suffix=" 卷")
        self.spin_volumes.setMinimumWidth(110)
        self.spin_volumes.valueChanged.connect(self._recompute_totals)
        structure_row.addWidget(self.spin_volumes)
        structure_row.addWidget(QLabel("×"))
        self.spin_chapters = NumberInput(lo=self.MIN_CHAPTERS, hi=self.MAX_CHAPTERS, default=self.DEFAULT_CHAPTERS_PER_VOLUME, suffix=" 章/卷")
        self.spin_chapters.setMinimumWidth(140)
        self.spin_chapters.valueChanged.connect(self._recompute_totals)
        structure_row.addWidget(self.spin_chapters)
        structure_row.addStretch(1)
        form.addRow("分卷数 / 章节数", structure_row)

        # 7) 章节字数
        self.spin_words_per_chapter = NumberInput(lo=self.MIN_WORDS_PER_CHAPTER, hi=self.MAX_WORDS_PER_CHAPTER, default=self.DEFAULT_WORDS_PER_CHAPTER, suffix=" 字/章")
        self.spin_words_per_chapter.setMinimumWidth(140)
        self.spin_words_per_chapter.valueChanged.connect(self._recompute_totals)
        form.addRow("章节字数", self.spin_words_per_chapter)

        # 8) 统计条 (只读) — 实时显示总章节数 / 总字数
        stats_frame = QFrame()
        stats_frame.setObjectName("statsFrame")
        stats_frame.setStyleSheet(
            "QFrame#statsFrame {"
            "  background: rgba(99, 102, 241, 0.08);"
            "  border: 1px solid rgba(99, 102, 241, 0.25);"
            "  border-radius: 6px;"
            "  padding: 10px;"
            "}"
            "QLabel#statsLabel { color: #6b727c; font-size: 11px; }"
            "QLabel#statsValue { color: #5a68c9; font-size: 14px; font-weight: 700; }"
        )
        stats_grid = QGridLayout(stats_frame)
        stats_grid.setContentsMargins(0, 0, 0, 0)
        stats_grid.setHorizontalSpacing(16)
        stats_grid.setVerticalSpacing(2)

        # 总章节数
        lbl_total_chap_label = QLabel("📚 总章节数")
        lbl_total_chap_label.setObjectName("statsLabel")
        self.lbl_total_chap = QLabel("100")
        self.lbl_total_chap.setObjectName("statsValue")
        stats_grid.addWidget(lbl_total_chap_label, 0, 0)
        stats_grid.addWidget(self.lbl_total_chap, 1, 0)

        # 总字数
        lbl_total_words_label = QLabel("✍️ 总字数")
        lbl_total_words_label.setObjectName("statsLabel")
        self.lbl_total_words = QLabel("200,000")
        self.lbl_total_words.setObjectName("statsValue")
        stats_grid.addWidget(lbl_total_words_label, 0, 1)
        stats_grid.addWidget(self.lbl_total_words, 1, 1)

        # 说明
        lbl_note = QLabel("= 分卷数 × 章节数 × 章节字数")
        lbl_note.setObjectName("statsLabel")
        lbl_note.setStyleSheet(f"color: {text_muted()}; font-size: 10px; font-style: italic;")
        stats_grid.addWidget(lbl_note, 0, 2, 2, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        form.addRow("", stats_frame)

        layout.addLayout(form)
        layout.addStretch(1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("btnCancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        if self._mode == "edit":
            btn_ok = QPushButton("💾 保存")
        else:
            btn_ok = QPushButton("✅ 创建")
        btn_ok.setObjectName("btnCreate")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._on_ok)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        # 初始化计算一次
        self._recompute_totals()

        # V4.0-P3-新: edit 模式把分卷数/章节数/章节字数 灰掉 (不能改, 怕破坏 books)
        if self._mode == "edit":
            for spin in (self.spin_volumes, self.spin_chapters, self.spin_words_per_chapter):
                spin.setEnabled(False)
                spin.setToolTip("编辑模式不可改 — 已建 books 的项目改分卷数/章节数/章节字数会破坏数据一致性, 需独立「重建结构」流程")

    # ------------------------------------------------------------------
    # Prefill (V4.0-P3-新)
    # ------------------------------------------------------------------
    def _prefill_from_initial(self) -> None:
        """edit 模式: 把已有项目数据填到表单. new 模式什么都不做."""
        if self._mode != "edit" or not self._initial:
            return
        ini = self._initial
        # 文本字段
        if ini.get("name"):
            self.ed_name.setText(str(ini["name"]))
        if ini.get("book_title"):
            self.ed_book.setText(str(ini["book_title"]))
        if ini.get("author"):
            self.ed_author.setText(str(ini["author"]))
        # 主题材: 找到对应 index
        genre = ini.get("genre")
        if genre:
            for i in range(self.cmb_genre.count()):
                if self.cmb_genre.itemData(i) == genre:
                    self.cmb_genre.setCurrentIndex(i)
                    break
        # 副题材: 转成 list (兼容 string 老数据)
        subs = ini.get("sub_genres") or []
        if isinstance(subs, str):
            from app.services.genre_presets import parse_subgenre_string
            subs = parse_subgenre_string(subs)
        self._sub_genres = list(subs)
        self._update_sub_label()
        # 平台: 转成 list
        plat = ini.get("platform") or ""
        if isinstance(plat, str) and plat:
            from app.services.genre_presets import PLATFORM_PRESETS
            self._platform_list = [p for p in plat.replace("、", ",").split(",") if p.strip() and p in PLATFORM_PRESETS]
        self._update_platform_label()
        # 分卷数 / 章节数 / 章节字数 (虽然 spinbox 被 disable, 仍要填上正确值)
        v = int(ini.get("volumes") or 1)
        c = int(ini.get("chapters_per_volume") or 100)
        w = int(ini.get("words_per_chapter") or 2000)
        self.spin_volumes.setValue(v)
        self.spin_chapters.setValue(c)
        self.spin_words_per_chapter.setValue(w)
        # 总字数用 word_target (因为编辑不改 sum, 直接拿原值)
        target = int(ini.get("word_target") or 0)
        if target > 0:
            self.lbl_total_chap.setText(f"{int(ini.get('total_chapters') or v * c):,}")
            self.lbl_total_words.setText(f"{target:,}")

    # ------------------------------------------------------------------
    # Recompute
    # ------------------------------------------------------------------
    def _recompute_totals(self) -> None:
        volumes = int(self.spin_volumes.value())
        chapters = int(self.spin_chapters.value())
        wpc = int(self.spin_words_per_chapter.value())
        total_chap = volumes * chapters
        total_words = total_chap * wpc
        self.lbl_total_chap.setText(f"{total_chap:,}")
        self.lbl_total_words.setText(f"{total_words:,}")

    # ------------------------------------------------------------------
    # Picker handlers
    # ------------------------------------------------------------------
    def _on_main_genre_changed(self, idx: int) -> None:
        # userData 存的是显示名 (None 表示没选)
        self._main_genre = self.cmb_genre.itemData(idx)

    def _pick_subgenre(self) -> None:
        # 副题材数量多 (~50 个), 用 MultiSelectDialog
        from app.services.genre_presets import SUBGENRE_PRESETS
        from app.ui.widgets import MultiSelectDialog

        options: List[tuple] = [
            (name, name in self._sub_genres, "") for name in SUBGENRE_PRESETS
        ]
        dlg = MultiSelectDialog(
            "选择副题材（可多选, 0~N 个元素标签）",
            options,
            parent=self,
        )
        if dlg.exec():
            self._sub_genres = dlg.selected_labels()
            self._update_sub_label()

    def _pick_platform(self) -> None:
        from app.ui.widgets import MultiSelectDialog
        options: List[tuple] = [(p, p in self._platform_list, "") for p in PLATFORM_PRESETS]
        dlg = MultiSelectDialog(
            "选择平台（可多选）",
            options,
            parent=self,
        )
        if dlg.exec():
            self._platform_list = dlg.selected_labels()
            self._update_platform_label()

    def _update_sub_label(self) -> None:
        if not self._sub_genres:
            self.lbl_sub.setText("（未选）")
            return
        # 选中数 > 3 个就显示「前 3 个 + N」式
        if len(self._sub_genres) > 3:
            shown = "、".join(self._sub_genres[:3]) + f"… 等 {len(self._sub_genres)} 个"
        else:
            shown = "、".join(self._sub_genres)
        self.lbl_sub.setText(shown)
        self.lbl_sub.setToolTip("、".join(self._sub_genres))

    def _update_platform_label(self) -> None:
        if not self._platform_list:
            self.lbl_plat.setText("（未选）")
            return
        self.lbl_plat.setText("、".join(self._platform_list))

    # ------------------------------------------------------------------
    # Confirm
    # ------------------------------------------------------------------
    def _on_ok(self) -> None:
        name = self.ed_name.text().strip()
        if not name:
            from app.ui.widgets import Dialogs
            Dialogs.warning("新建项目" if self._mode == "new" else "编辑项目",
                            "项目名不能为空", parent=self)
            self.ed_name.setFocus()
            return
        if not self._main_genre and self._mode == "new":
            # new 模式必选主题材; edit 模式允许沿用原题材
            from app.ui.widgets import Dialogs
            Dialogs.warning("新建项目", "请选择 1 个主题材（如: 玄幻/都市/仙侠…）", parent=self)
            self.cmb_genre.setFocus()
            return
        book_title = self.ed_book.text().strip() or name  # 书名空时默认用项目名
        volumes = int(self.spin_volumes.value())
        chapters = int(self.spin_chapters.value())
        wpc = int(self.spin_words_per_chapter.value())
        total_chap = volumes * chapters
        total_words = total_chap * wpc
        author = self.ed_author.text().strip() or None  # V4.0-P3-新
        # edit 模式: word_target 用原值 (不重算, 因为分卷数等已锁定, sum 一致但保险起见保留原值)
        if self._mode == "edit" and self._initial.get("word_target"):
            word_target = int(self._initial["word_target"])
        else:
            word_target = total_words
        self._result = {
            "name": name,
            "book_title": book_title,
            # 4.0 兼容: genre 字段 (单) 写主题材
            "genre": self._main_genre,
            "platform": ",".join(self._platform_list) if self._platform_list else None,
            # 4.0 修复: 总字数作为 word_target 写到 project (与原 API 兼容)
            "word_target": word_target,
            # V4.0-P2-新: 结构化字段写到 project.json (供业务层使用)
            "volumes": volumes,
            "chapters_per_volume": chapters,
            "words_per_chapter": wpc,
            "total_chapters": total_chap,
            # V4.0-P2-新: 副题材 0~N 个
            "sub_genres": list(self._sub_genres),
            # V4.0-P3-新: 作者
            "author": author,
        }
        # edit 模式: 删掉 update 不接受的字段 (volumes/cpw/wpc/total_chap), 不让它们触发 "未知字段" 警告
        if self._mode == "edit":
            for k in ("volumes", "chapters_per_volume", "words_per_chapter", "total_chapters"):
                self._result.pop(k, None)
        self.accept()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def result(self) -> Optional[Dict]:
        """Return project data dict after accepted(), or None on cancel."""
        return self._result
