"""
Subtext UI (🎭 潜文本卡) - 仅在小说设定 tab 内显示.

子面板内容:
  1. 项目级只读配置 (模式 + 模板 + 默认示例)
  2. 章节级卡管理:
     - 章节列表 (含状态符号: ✏️/🧠/❌/⏳/🔄/⚠️)
     - 13 字段编辑表单
     - 手动模式下: 模板下拉 + 每个字段 hover 帮助
     - AI 自动模式: 一键 AI 生成
     - 关闭模式: 仅可读 / 删除

设计原则:
  - 跟 ProjectSettingsWidget / ModelSettingsWidget 风格一致
  - 项目级配置只读示例 (项目模式实际是 set_project 时显示当前项目状态, 但不允许改)
  - 13 字段: label + QPlainTextEdit + (?) 帮助按钮 (hover 显示示例)
  - 字段序号: 按 SUBTEXT_FIELDS 顺序
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget,
    QListWidgetItem, QLabel, QPushButton, QPlainTextEdit,
    QInputDialog, QGroupBox, QFormLayout, QComboBox, QFrame,
    QScrollArea, QToolButton, QSizePolicy,
)

from app.services import (
    book_service, chapter_service, subtext as subtext_svc,
    ServiceError,
)
from app.services.subtext import (
    MODE_AI_AUTO, MODE_MANUAL, MODE_CLOSED, ALL_MODES, MODE_LABELS,
    SUBTEXT_FIELDS, FIELD_HELP,
    get_project_mode, set_project_mode, get_card_for_chapter, upsert_card,
    delete_card, auto_generate, list_presets, apply_template, get_preset,
)
from app.ui.widgets import Dialogs

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# 帮助按钮 (hover 显示 FIELD_HELP[field].example)
# --------------------------------------------------------------------- #

class FieldHelpButton(QToolButton):
    """小 ? 按钮, hover 显示字段帮助 + 示例."""

    def __init__(self, field_name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.field_name = field_name
        self.setText("?")
        self.setObjectName("fieldHelpBtn")
        self.setFixedSize(18, 18)
        self.setToolTip(self._build_tooltip())
        self.setCursor(Qt.CursorShape.WhatsThisCursor)

    def _build_tooltip(self) -> str:
        info = FIELD_HELP.get(self.field_name, {})
        if not info:
            return f"字段: {self.field_name}"
        return (
            f"📌 {info.get('label', self.field_name)}\n\n"
            f"💡 {info.get('hint', '')}\n\n"
            f"📝 示例: {info.get('example', '(无)')}"
        )


# --------------------------------------------------------------------- #
# 字段行: label + QPlainTextEdit + (?) 帮助按钮
# --------------------------------------------------------------------- #

class FieldRow(QWidget):
    """1 个字段的编辑行."""

    def __init__(self, field_name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.field_name = field_name
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # 左侧: label + help btn
        label_box = QVBoxLayout()
        label_box.setContentsMargins(0, 0, 0, 0)
        label_box.setSpacing(0)
        info = FIELD_HELP.get(self.field_name, {})
        lbl = QLabel(f"<b>{info.get('label', self.field_name)}</b>")
        lbl.setObjectName("fieldLabel")
        lbl.setFixedWidth(110)
        lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        label_box.addWidget(lbl)

        help_btn = FieldHelpButton(self.field_name)
        label_box.addWidget(help_btn, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addLayout(label_box)

        # 右侧: 编辑框
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("fieldEditor")
        self.editor.setPlaceholderText(f"留空 = 不设置")
        # 限高: 3 行 + 滚动
        self.editor.setMinimumHeight(60)
        self.editor.setMaximumHeight(100)
        self.editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.editor, 1)

    def text(self) -> str:
        return self.editor.toPlainText().strip()

    def setText(self, value: str) -> None:
        self.editor.setPlainText(value or "")


# --------------------------------------------------------------------- #
# 项目级只读配置 (顶部小条)
# --------------------------------------------------------------------- #

class ProjectModeHeader(QFrame):
    """项目级模式头部 (只读 + 切换 + 模板下拉)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("subtextModeHeader")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()
        self.current_project_id: Optional[str] = None

    def _build_ui(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        # 标题
        title = QLabel("🎭 潜文本卡 · 项目级配置")
        title.setObjectName("subtextHeaderTitle")
        lay.addWidget(title)

        lay.addStretch(1)

        # 模式标签
        self.lbl_mode = QLabel("模式: -")
        self.lbl_mode.setObjectName("subtextModeLabel")
        lay.addWidget(self.lbl_mode)

        # 模式切换按钮
        self.cmb_mode = QComboBox()
        for m in ALL_MODES:
            self.cmb_mode.addItem(f"{m} ({MODE_LABELS[m]})", m)
        self.cmb_mode.currentIndexChanged.connect(self._on_mode_changed)
        lay.addWidget(self.cmb_mode)

        # 模板下拉 (manual 模式时才显示)
        self.cmb_template = QComboBox()
        self.cmb_template.setMinimumWidth(140)
        self.cmb_template.currentIndexChanged.connect(self._on_template_changed)
        lay.addWidget(self.cmb_template)

    def set_project(self, project: Optional[dict]) -> None:
        self.current_project_id = project["id"] if project else None
        # 重新加载模板列表 (内置模板)
        self.cmb_template.blockSignals(True)
        self.cmb_template.clear()
        self.cmb_template.addItem("— 选默认模板 —", "")
        for tpl in list_presets():
            self.cmb_template.addItem(f"📋 {tpl['name']} - {tpl.get('description', '')[:24]}", tpl["id"])
        self.cmb_template.blockSignals(False)

        if project is None:
            self.lbl_mode.setText("模式: (无项目)")
            self.cmb_mode.setEnabled(False)
            self.cmb_template.setVisible(False)
            return

        # 取当前模式
        self.cmb_mode.blockSignals(True)
        try:
            mode_info = get_project_mode(project["id"])
            idx = ALL_MODES.index(mode_info["mode"]) if mode_info["mode"] in ALL_MODES else 0
            self.cmb_mode.setCurrentIndex(idx)
            tpl_idx = self.cmb_template.findData(mode_info.get("template_id") or "")
            self.cmb_template.setCurrentIndex(max(0, tpl_idx))
            self._refresh_mode_label(mode_info["mode"], mode_info.get("template_id") or "")
            # manual 模式才显示模板
            self.cmb_template.setVisible(mode_info["mode"] == MODE_MANUAL)
        except Exception as e:
            log.warning(f"[Subtext] 加载项目模式失败: {e}")
            self.lbl_mode.setText(f"模式: 加载失败 ({e})")
        finally:
            self.cmb_mode.blockSignals(False)
        self.cmb_mode.setEnabled(True)

    def _refresh_mode_label(self, mode: str, tpl_id: str = "") -> None:
        if mode == MODE_AI_AUTO:
            self.lbl_mode.setText("模式: 🧠 AI 自动 (含智能跳过过渡章)")
        elif mode == MODE_MANUAL:
            tpl_name = ""
            if tpl_id:
                try:
                    tpl = get_preset(tpl_id)
                    tpl_name = f"  · 默认模板: {tpl.get('name', tpl_id)}"
                except Exception:
                    tpl_name = f"  · 默认模板: {tpl_id}"
            self.lbl_mode.setText(f"模式: ✏️ 手动{tpl_name}")
        else:
            self.lbl_mode.setText("模式: 🚫 关闭 (不生成潜文本卡)")

    def _on_mode_changed(self, _idx: int) -> None:
        if not self.current_project_id:
            return
        mode = self.cmb_mode.currentData()
        if not mode:
            return
        # 保留当前模板 (manual 时才用)
        cur_tpl = self.cmb_template.currentData() or ""
        if mode != MODE_MANUAL:
            cur_tpl = ""  # 非 manual 不存模板
        try:
            set_project_mode(self.current_project_id, mode, cur_tpl)
            self._refresh_mode_label(mode, cur_tpl)
            self.cmb_template.setVisible(mode == MODE_MANUAL)
            log.info(f"[Subtext] 项目 {self.current_project_id} 模式 → {mode}")
        except ServiceError as e:
            Dialogs.warning("切换模式", str(e), parent=self)

    def _on_template_changed(self, _idx: int) -> None:
        if not self.current_project_id:
            return
        tpl_id = self.cmb_template.currentData() or ""
        try:
            cur_mode = self.cmb_mode.currentData()
            if cur_mode == MODE_MANUAL:
                set_project_mode(self.current_project_id, cur_mode, tpl_id)
                self._refresh_mode_label(cur_mode, tpl_id)
                log.info(f"[Subtext] 默认模板 → {tpl_id or '(无)'}")
        except ServiceError as e:
            Dialogs.warning("切换模板", str(e), parent=self)


# --------------------------------------------------------------------- #
# 13 字段表单 (右侧滚动区)
# --------------------------------------------------------------------- #

class CardFormWidget(QWidget):
    """13 字段编辑表单."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.rows: dict[str, FieldRow] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        # 外层 vertical
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        # 滚动区 (字段多时滚)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        inner = QWidget()
        scroll.setWidget(inner)
        form = QVBoxLayout(inner)
        form.setContentsMargins(4, 4, 4, 4)
        form.setSpacing(8)

        for fld in SUBTEXT_FIELDS:
            row = FieldRow(fld)
            self.rows[fld] = row
            form.addWidget(row)

        form.addStretch(1)

    def set_card(self, card: Optional[dict]) -> None:
        """从 card dict 填充. None = 清空."""
        for fld, row in self.rows.items():
            if card is not None:
                row.setText(str(card.get(fld) or ""))
            else:
                row.setText("")

    def collect(self) -> dict:
        """从 UI 收集 13 字段值."""
        out: dict = {}
        for fld, row in self.rows.items():
            out[fld] = row.text()
        return out

    def set_enabled(self, enabled: bool) -> None:
        for row in self.rows.values():
            row.editor.setReadOnly(not enabled)


# --------------------------------------------------------------------- #
# SubtextTab 主面板
# --------------------------------------------------------------------- #

class SubtextTab(QWidget):
    """潜文本卡管理子页. 嵌在小说设定 tab 内."""

    def __init__(self) -> None:
        super().__init__()
        self.current_project: Optional[dict] = None
        self.current_chapter_id: Optional[str] = None
        # chapter_id -> book_id 反向缓存
        self._chapter_to_book: dict[str, str] = {}
        # chapter_id -> card status ("manual" / "ai_auto" / None)
        self._chapter_card_status: dict[str, Optional[str]] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        # 1. 顶部: 项目级模式配置
        self.mode_header = ProjectModeHeader()
        outer.addWidget(self.mode_header)

        # 2. 中部: 章节列表 (左) + 字段表单 (右)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # ---- 左: 章节列表 ----
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(4)
        lbl_chap = QLabel("📑 章节 (状态: ✏️ 手动 / 🧠 AI / ❌ 无卡)")
        lbl_chap.setObjectName("subtextListLabel")
        left_lay.addWidget(lbl_chap)

        self.chapter_list = QListWidget()
        self.chapter_list.itemSelectionChanged.connect(self._on_chapter_selected)
        left_lay.addWidget(self.chapter_list, 1)

        btn_row = QHBoxLayout()
        self.btn_ai_gen = QPushButton("🧠 AI 自动生成")
        self.btn_ai_gen.setToolTip("按项目模式生成 / 重生本章潜文本卡")
        self.btn_ai_gen.clicked.connect(self._on_ai_generate)
        self.btn_ai_gen.setEnabled(False)
        btn_row.addWidget(self.btn_ai_gen)
        self.btn_delete = QPushButton("🗑️ 删除卡")
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_delete.setEnabled(False)
        btn_row.addWidget(self.btn_delete)
        left_lay.addLayout(btn_row)

        splitter.addWidget(left)

        # ---- 右: 字段表单 + 模板下拉 (manual 时) ----
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(6)

        # 模板下拉 (手动模式才显示, 章节级选模板)
        tpl_row = QHBoxLayout()
        tpl_row.addWidget(QLabel("📋 章节模板 (手动模式):"))
        self.cmb_chapter_tpl = QComboBox()
        self.cmb_chapter_tpl.addItem("— 不套模板 —", "")
        # 模板列表在 set_project 时填充 (避免 _build_ui 强依赖 DB)
        tpl_row.addWidget(self.cmb_chapter_tpl, 1)
        self.btn_save = QPushButton("💾 保存")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setEnabled(False)
        tpl_row.addWidget(self.btn_save)
        right_lay.addLayout(tpl_row)

        # 状态提示
        self.lbl_chapter_status = QLabel("(未选章节)")
        self.lbl_chapter_status.setObjectName("subtextChapterStatus")
        right_lay.addWidget(self.lbl_chapter_status)

        # 13 字段表单
        self.form = CardFormWidget()
        right_lay.addWidget(self.form, 1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([280, 700])

    def set_project(self, project: Optional[dict]) -> None:
        self.current_project = project
        self.current_chapter_id = None
        self.chapter_list.clear()
        self.form.set_card(None)
        self._chapter_to_book.clear()
        self._chapter_card_status.clear()
        self._update_action_states()
        self.mode_header.set_project(project)
        if project is None:
            self.lbl_chapter_status.setText("(未选项目)")
            return
        self._populate_chapter_templates()
        self._reload_chapters()

    def _populate_chapter_templates(self) -> None:
        """填充章节级模板下拉 (手动模式用). DB 不可用时静默."""
        try:
            tpls = list_presets()
        except Exception as e:
            log.warning(f"[Subtext] 加载模板列表失败: {e}")
            return
        # 断开信号 (避免 setCurrentIndex 误触 apply_template)
        # 用 suppression flag 避免 PySide6 "Failed to disconnect" 警告
        if getattr(self, "_tpl_signal_connected", False):
            try:
                self.cmb_chapter_tpl.currentIndexChanged.disconnect(self._on_apply_chapter_template)
            except (TypeError, RuntimeError):
                pass
        self.cmb_chapter_tpl.blockSignals(True)
        self.cmb_chapter_tpl.clear()
        self.cmb_chapter_tpl.addItem("— 不套模板 —", "")
        for tpl in tpls:
            self.cmb_chapter_tpl.addItem(
                f"{tpl['name']} - {tpl.get('description', '')[:24]}",
                tpl["id"],
            )
        self.cmb_chapter_tpl.blockSignals(False)
        self.cmb_chapter_tpl.currentIndexChanged.connect(self._on_apply_chapter_template)
        self._tpl_signal_connected = True

    # ---- 章节列表 ----

    def _reload_chapters(self) -> None:
        if not self.current_project:
            return
        # 遍历项目下所有 books → chapters
        self._chapter_to_book.clear()
        self._chapter_card_status.clear()
        try:
            books_data = book_service.list_for_project(self.current_project["id"])
        except ServiceError as e:
            Dialogs.warning("加载卷册", str(e), parent=self)
            return
        for book in books_data.get("books", []):
            try:
                chap_data = chapter_service.list_for_book(book["id"])
            except ServiceError as e:
                log.warning(f"[Subtext] 加载章节失败 (book={book['id']}): {e}")
                continue
            for c in chap_data.get("chapters", []):
                cid = c["id"]
                self._chapter_to_book[cid] = book["id"]
                # 查卡状态
                card = get_card_for_chapter(cid)
                status = card.source if card else None
                self._chapter_card_status[cid] = status
                # 状态符号
                if status == "ai_auto":
                    icon = "🧠"
                elif status == "manual":
                    icon = "✏️"
                elif status == "template":
                    icon = "📋"
                else:
                    icon = "❌"
                label = f"{icon} 第{c.get('chapter_no', '?')}章  {c.get('title') or '(无题)'}"
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, c)
                self.chapter_list.addItem(item)

    def _on_chapter_selected(self) -> None:
        item = self.chapter_list.currentItem()
        if not item:
            self.current_chapter_id = None
            self.form.set_card(None)
            self.lbl_chapter_status.setText("(未选章节)")
            self._update_action_states()
            return
        c = item.data(Qt.ItemDataRole.UserRole)
        self.current_chapter_id = c["id"]
        card = get_card_for_chapter(c["id"])
        if card is not None:
            self.form.set_card({
                "surface_event": card.surface_event,
                "true_intent": card.true_intent,
                "real_intent_others": card.real_intent_others,
                "lie": card.lie,
                "truth": card.truth,
                "emotional": card.emotional,
                "pacing": card.pacing,
                "viewpoint": card.viewpoint,
                "anti_rules": card.anti_rules,
                "callback_to": card.callback_to,
                "scene_map": card.scene_map,
                "physical_anchor": card.physical_anchor,
                "ending_scene_state": card.ending_scene_state,
            })
            self.lbl_chapter_status.setText(
                f"📝 已有卡 (source={card.source}, tpl={card.template_id or '—'}, "
                f"updated={card.updated_at[:19]})"
            )
        else:
            self.form.set_card(None)
            self.lbl_chapter_status.setText("❌ 本章无潜文本卡 (点「AI 自动生成」或选模板填充)")
        # 模式决定是否可编辑
        if self.current_project:
            try:
                mode_info = get_project_mode(self.current_project["id"])
                editable = mode_info["mode"] != MODE_CLOSED
            except Exception:
                editable = True
        else:
            editable = False
        self.form.set_enabled(editable)
        self._update_action_states()

    def _update_action_states(self) -> None:
        has_chap = self.current_chapter_id is not None
        has_project = self.current_project is not None
        self.btn_ai_gen.setEnabled(has_chap and has_project)
        self.btn_delete.setEnabled(has_chap and has_project)
        self.btn_save.setEnabled(has_chap and has_project)
        self.cmb_chapter_tpl.setEnabled(has_chap and has_project)

    # ---- 按钮 ----

    def _on_save(self) -> None:
        if not self.current_chapter_id:
            return
        fields = self.form.collect()
        try:
            card = upsert_card(
                self.current_chapter_id, source="manual", **fields,
            )
        except ServiceError as e:
            Dialogs.warning("保存", str(e), parent=self)
            return
        except Exception as e:
            Dialogs.warning("保存", f"异常: {e}", parent=self)
            return
        Dialogs.info("保存", "潜文本卡已保存。", parent=self)
        # 刷新列表状态
        self._reload_chapters()
        # 重新选回当前章节 (位置保持)
        for i in range(self.chapter_list.count()):
            it = self.chapter_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole)["id"] == self.current_chapter_id:
                self.chapter_list.setCurrentItem(it)
                break

    def _on_delete(self) -> None:
        if not self.current_chapter_id:
            return
        ok, _ = Dialogs.confirm(
            "确认删除",
            "删除本章潜文本卡?",
            danger=True,
            confirm_text="删除",
            parent=self,
        )
        if not ok:
            return
        try:
            delete_card(self.current_chapter_id)
        except ServiceError as e:
            Dialogs.warning("删除", str(e), parent=self)
            return
        self.form.set_card(None)
        self.lbl_chapter_status.setText("❌ 本章无潜文本卡")
        self._reload_chapters()

    def _on_ai_generate(self) -> None:
        if not self.current_chapter_id or not self.current_project:
            return
        # 取章节字数 + brief
        book_id = self._chapter_to_book.get(self.current_chapter_id)
        if book_id is None:
            Dialogs.warning("AI 生成", "找不到所属卷册", parent=self)
            return
        try:
            chap = chapter_service.get(self.current_chapter_id)
        except ServiceError as e:
            Dialogs.warning("AI 生成", str(e), parent=self)
            return
        wc = (chap.get("draft") or chap.get("final") or "").__len__()
        # 简述: 取章节标题 + draft 前 60 字
        brief = (chap.get("title") or "") + " " + (chap.get("draft") or chap.get("final") or "")[:60]
        try:
            card = auto_generate(
                self.current_project["id"],
                self.current_chapter_id,
                brief,
                wc,
            )
        except ServiceError as e:
            # 过渡章 < 1000 字会抛 → 提示用户
            Dialogs.info("AI 自动生成", str(e), parent=self)
            return
        except Exception as e:
            Dialogs.warning("AI 自动生成", f"异常: {e}", parent=self)
            return
        # 重新加载
        self._reload_chapters()
        for i in range(self.chapter_list.count()):
            it = self.chapter_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole)["id"] == self.current_chapter_id:
                self.chapter_list.setCurrentItem(it)
                break
        Dialogs.info("AI 自动生成", "已生成潜文本卡 (AI 解析 + 本地兜底)。", parent=self)

    def _on_apply_chapter_template(self, _idx: int) -> None:
        if not self.current_chapter_id:
            return
        tpl_id = self.cmb_chapter_tpl.currentData() or ""
        if not tpl_id:
            return
        # 取章节简述
        try:
            chap = chapter_service.get(self.current_chapter_id)
        except ServiceError as e:
            Dialogs.warning("套模板", str(e), parent=self)
            return
        brief = (chap.get("title") or "") + " " + (chap.get("draft") or chap.get("final") or "")[:60]
        try:
            card = apply_template(self.current_chapter_id, tpl_id, brief)
        except ServiceError as e:
            Dialogs.warning("套模板", str(e), parent=self)
            return
        self.form.set_card({
            "surface_event": card.surface_event,
            "true_intent": card.true_intent,
            "real_intent_others": card.real_intent_others,
            "lie": card.lie,
            "truth": card.truth,
            "emotional": card.emotional,
            "pacing": card.pacing,
            "viewpoint": card.viewpoint,
            "anti_rules": card.anti_rules,
            "callback_to": card.callback_to,
            "scene_map": card.scene_map,
            "physical_anchor": card.physical_anchor,
            "ending_scene_state": card.ending_scene_state,
        })
        self.lbl_chapter_status.setText(f"📋 已套模板 {tpl_id} (未保存, 点「保存」生效)")
