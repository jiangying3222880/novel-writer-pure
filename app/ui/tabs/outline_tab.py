"""
OutlineTab — 大纲管理 (单版本直接编辑).

功能:
  - 左侧: 卷册 + 章节列表
  - 右侧: 大纲编辑器 (单版本, 直接修改保存)
  - 大纲编辑器下方: 潜文本卡 (可选手写 / AI自由规划, 默认AI)
  - 操作: 保存 / 删除 / AI 生成大纲

数据层: outline_service (chapter_outlines 表, 固定 version="A")
       subtext_service (潜文本卡)
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTreeWidget, QTreeWidgetItem, QLabel, QPushButton,
    QPlainTextEdit, QGroupBox, QFormLayout,
    QFrame, QSizePolicy, QComboBox, QScrollArea,
    QToolButton, QDialog, QDialogButtonBox, QStackedWidget,
    QTabWidget, QFileDialog,
)
from app.ui.theme import text_chip, text_subtle

from app.services import (
    book_service, chapter_service, outline_service,
    subtext as subtext_svc,
    setting_service,
    ServiceError,
)
from app.services.subtext import (
    MODE_AI_AUTO, MODE_MANUAL, MODE_CLOSED, ALL_MODES, MODE_LABELS,
    SUBTEXT_FIELDS, FIELD_HELP,
    get_project_mode, set_project_mode, get_card_for_chapter, upsert_card,
    delete_card, auto_generate, list_presets, apply_template, get_preset,
    generate_from_intent, parse_intent_to_points,
)
from app.ui.widgets import Dialogs
from app.ui.widgets._number_input import NumberInput

log = logging.getLogger(__name__)

# 单版本模式固定使用 version "A"
SINGLE_VERSION = "A"


# --------------------------------------------------------------------- #
# 帮助按钮
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
# 潜文本字段行
# --------------------------------------------------------------------- #

class SubtextFieldRow(QWidget):
    """1 个潜文本字段的编辑行."""

    def __init__(self, field_name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.field_name = field_name
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

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

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("fieldEditor")
        self.editor.setPlaceholderText("留空 = 不设置")
        self.editor.setMinimumHeight(50)
        self.editor.setMaximumHeight(80)
        self.editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.editor, 1)

    def text(self) -> str:
        return self.editor.toPlainText().strip()

    def setText(self, value: str) -> None:
        self.editor.setPlainText(value or "")


# --------------------------------------------------------------------- #
# 潜文本卡面板 (嵌入大纲编辑器下方)
# --------------------------------------------------------------------- #

class IntentConfirmDialog(QDialog):
    """意图确认弹窗: 显示 AI 解析的要点，用户可微调后确认."""

    def __init__(self, points: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("确认意图要点")
        self.setMinimumSize(480, 360)
        self._points = points
        self._editors: dict[str, QPlainTextEdit] = {}
        self._result: Optional[dict] = None
        self._build_ui()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)

        lay.addWidget(QLabel("AI 从您的意图中解析出以下要点，可微调后确认："))

        labels = {
            "scene": "📍 场景",
            "events": "🎬 主要事件",
            "conflict": "⚔️ 冲突点",
            "foreshadowing": "🪝 伏笔/呼应",
            "emotion": "💫 情感基调",
        }
        for key, label_text in labels.items():
            row_lay = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(90)
            row_lay.addWidget(lbl, 0, Qt.AlignmentFlag.AlignTop)
            ed = QPlainTextEdit()
            ed.setPlainText(self._points.get(key, ""))
            ed.setPlaceholderText("可编辑…")
            ed.setMaximumHeight(60)
            row_lay.addWidget(ed, 1)
            lay.addLayout(row_lay)
            self._editors[key] = ed

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setText("✅ 确认并生成")
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        lay.addWidget(btn_box)

    def _on_accept(self) -> None:
        self._result = {k: ed.toPlainText().strip() for k, ed in self._editors.items()}
        self.accept()

    def get_confirmed_points(self) -> Optional[dict]:
        return self._result


class SubtextPanel(QWidget):
    """潜文本卡面板: 意图输入 → AI确认 → 生成13字段 / 手写模式 / AI自动."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.current_project_id: Optional[str] = None
        self.current_chapter_id: Optional[str] = None
        self._chapter_to_book: dict[str, str] = {}
        self._rows: dict[str, SubtextFieldRow] = {}
        self._build_ui()

    # 页面索引常量
    PAGE_INTENT = 0       # 意图输入 (AI模式, 无卡)
    PAGE_CARD_VIEW = 1    # 已生成卡查看 (AI模式, 有卡)
    PAGE_MANUAL = 2       # 手写13字段 (手写模式)
    PAGE_CLOSED = 3       # 已关闭提示

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # 标题行 + 模式切换
        header = QHBoxLayout()
        header.addWidget(QLabel("🎭 潜文本卡"))
        header.addStretch(1)
        self.lbl_mode = QLabel("模式: AI 自由规划")
        self.lbl_mode.setStyleSheet(f"color: {text_chip()}; font-size: 11px;")
        header.addWidget(self.lbl_mode)

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("🧠 AI 自由规划 (默认)", MODE_AI_AUTO)
        self.cmb_mode.addItem("✏️ 手写", MODE_MANUAL)
        self.cmb_mode.addItem("🚫 关闭", MODE_CLOSED)
        self.cmb_mode.currentIndexChanged.connect(self._on_mode_changed)
        header.addWidget(self.cmb_mode)
        v.addLayout(header)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: rgba(127,127,127,0.2);")
        sep.setFixedHeight(1)
        v.addWidget(sep)

        # ---- 状态行 (始终显示) ----
        self.ai_status_label = QLabel("(未选章节)")
        self.ai_status_label.setWordWrap(True)
        self.ai_status_label.setStyleSheet(f"color: {text_chip()}; font-size: 12px;")
        v.addWidget(self.ai_status_label)

        # ---- 互斥页面栈 ----
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)

        # PAGE 0: 意图输入区
        page_intent = QWidget()
        pi_lay = QVBoxLayout(page_intent)
        pi_lay.setContentsMargins(0, 0, 0, 0)
        pi_lay.setSpacing(4)

        self.intent_box = QGroupBox("💡 输入你的意图")
        intent_lay = QVBoxLayout(self.intent_box)
        intent_lay.setContentsMargins(8, 8, 8, 8)
        intent_lay.setSpacing(4)

        self.ed_intent = QPlainTextEdit()
        self.ed_intent.setPlaceholderText(
            "用 1-2 句话描述本章你想表达的核心意图…\n"
            "例：主角表面接受宗门考验，实则暗中调查筑基丹被换的真相"
        )
        self.ed_intent.setMaximumHeight(70)
        self.ed_intent.setStyleSheet("font-size: 12px;")
        intent_lay.addWidget(self.ed_intent)

        intent_btn_row = QHBoxLayout()
        self.btn_parse_intent = QPushButton("🔍 AI 解析意图")
        self.btn_parse_intent.clicked.connect(self._on_parse_intent)
        self.btn_parse_intent.setEnabled(False)
        intent_btn_row.addWidget(self.btn_parse_intent)

        self.btn_direct_gen = QPushButton("⚡ 直接生成")
        self.btn_direct_gen.clicked.connect(self._on_direct_generate)
        self.btn_direct_gen.setEnabled(False)
        intent_btn_row.addWidget(self.btn_direct_gen)

        self.btn_ai_gen = QPushButton("🧠 手动触发 AI 生成")
        self.btn_ai_gen.clicked.connect(self._on_ai_generate)
        self.btn_ai_gen.setEnabled(False)
        intent_btn_row.addWidget(self.btn_ai_gen)

        intent_btn_row.addStretch(1)
        intent_lay.addLayout(intent_btn_row)
        pi_lay.addWidget(self.intent_box)
        pi_lay.addStretch(1)
        self.stack.addWidget(page_intent)  # index 0

        # PAGE 1: 已生成卡查看区
        page_view = QWidget()
        pv_lay = QVBoxLayout(page_view)
        pv_lay.setContentsMargins(0, 0, 0, 0)
        pv_lay.setSpacing(4)

        self.card_view_scroll = QScrollArea()
        self.card_view_scroll.setWidgetResizable(True)
        self.card_view_scroll.setFrameShape(QFrame.Shape.NoFrame)
        pv_lay.addWidget(self.card_view_scroll, 1)

        card_view_inner = QWidget()
        self.card_view_scroll.setWidget(card_view_inner)
        card_view_lay = QVBoxLayout(card_view_inner)
        card_view_lay.setContentsMargins(4, 4, 4, 4)
        card_view_lay.setSpacing(6)

        self.card_view_rows: dict[str, SubtextFieldRow] = {}
        for fld in SUBTEXT_FIELDS:
            row = SubtextFieldRow(fld)
            self.card_view_rows[fld] = row
            card_view_lay.addWidget(row)
        card_view_lay.addStretch(1)

        # 查看区按钮
        view_btn_row = QHBoxLayout()
        self.btn_edit_card = QPushButton("✏️ 编辑潜文本卡")
        self.btn_edit_card.clicked.connect(self._on_edit_card)
        view_btn_row.addWidget(self.btn_edit_card)
        self.btn_delete_card_view = QPushButton("🗑 删除")
        self.btn_delete_card_view.clicked.connect(self._on_delete_subtext)
        view_btn_row.addWidget(self.btn_delete_card_view)
        view_btn_row.addStretch(1)
        card_view_lay.addLayout(view_btn_row)
        self.stack.addWidget(page_view)  # index 1

        # PAGE 2: 手写13字段
        page_manual = QWidget()
        pm_lay = QVBoxLayout(page_manual)
        pm_lay.setContentsMargins(0, 0, 0, 0)
        pm_lay.setSpacing(4)

        self.manual_scroll = QScrollArea()
        self.manual_scroll.setWidgetResizable(True)
        self.manual_scroll.setFrameShape(QFrame.Shape.NoFrame)
        pm_lay.addWidget(self.manual_scroll, 1)

        manual_inner = QWidget()
        self.manual_scroll.setWidget(manual_inner)
        manual_lay = QVBoxLayout(manual_inner)
        manual_lay.setContentsMargins(4, 4, 4, 4)
        manual_lay.setSpacing(6)

        self._rows: dict[str, SubtextFieldRow] = {}
        for fld in SUBTEXT_FIELDS:
            row = SubtextFieldRow(fld)
            self._rows[fld] = row
            manual_lay.addWidget(row)

        manual_lay.addStretch(1)

        # 手写模式按钮行
        manual_btn_row = QHBoxLayout()
        self.btn_save_subtext = QPushButton("💾 保存潜文本卡")
        self.btn_save_subtext.clicked.connect(self._on_save_subtext)
        self.btn_save_subtext.setEnabled(False)
        manual_btn_row.addWidget(self.btn_save_subtext)

        self.btn_delete_subtext = QPushButton("🗑 删除潜文本卡")
        self.btn_delete_subtext.clicked.connect(self._on_delete_subtext)
        self.btn_delete_subtext.setEnabled(False)
        manual_btn_row.addWidget(self.btn_delete_subtext)

        manual_btn_row.addStretch(1)
        manual_lay.addLayout(manual_btn_row)
        self.stack.addWidget(page_manual)  # index 2

        # PAGE 3: 已关闭提示
        page_closed = QWidget()
        pc_lay = QVBoxLayout(page_closed)
        self.lbl_closed = QLabel("🚫 潜文本卡已关闭")
        self.lbl_closed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_closed.setStyleSheet(f"color: {text_chip()}; font-size: 13px; padding: 40px;")
        pc_lay.addWidget(self.lbl_closed)
        self.stack.addWidget(page_closed)  # index 3

    # ---- public ----

    def set_project(self, project: Optional[dict]) -> None:
        self.current_project_id = project["id"] if project else None
        self.current_chapter_id = None
        self._chapter_to_book.clear()
        self._clear_form()
        self._update_action_states()

        if project is None:
            self.cmb_mode.setEnabled(False)
            self.lbl_mode.setText("模式: (无项目)")
            return

        self.cmb_mode.setEnabled(True)
        try:
            mode_info = get_project_mode(project["id"])
            mode = mode_info["mode"]
            idx = [MODE_AI_AUTO, MODE_MANUAL, MODE_CLOSED].index(mode) if mode in [MODE_AI_AUTO, MODE_MANUAL, MODE_CLOSED] else 0
            self.cmb_mode.blockSignals(True)
            self.cmb_mode.setCurrentIndex(idx)
            self.cmb_mode.blockSignals(False)
            self._refresh_mode_label(mode)
        except Exception as e:
            log.warning(f"[SubtextPanel] 加载模式失败: {e}")

    def set_chapter(self, chapter: Optional[dict], book_id: Optional[str] = None) -> None:
        """选中章节时加载潜文本卡."""
        if chapter:
            self.current_chapter_id = chapter["id"]
            if book_id:
                self._chapter_to_book[self.current_chapter_id] = book_id
        else:
            self.current_chapter_id = None

        self._clear_form()
        self._update_action_states()

        if not self.current_chapter_id:
            self.ai_status_label.setText("(未选章节)")
            self._switch_page(self.PAGE_INTENT)
            return

        # 加载当前章节的潜文本卡
        card = get_card_for_chapter(self.current_chapter_id)
        mode = self.cmb_mode.currentData() or MODE_AI_AUTO

        if mode == MODE_AI_AUTO:
            if card:
                self.ai_status_label.setText(
                    f"✅ 已生成 (来源: {card.source}, 更新: {card.updated_at[:19]})"
                )
                self._fill_card_view(card)
                self._switch_page(self.PAGE_CARD_VIEW)
            else:
                self.ai_status_label.setText("⏳ 尚未生成，请在上方输入意图")
                self._switch_page(self.PAGE_INTENT)
        elif mode == MODE_MANUAL:
            if card:
                self._fill_form(card)
                self.ai_status_label.setText(f"📝 已有手写卡 (updated={card.updated_at[:19]})")
            else:
                self.ai_status_label.setText("❌ 本章无潜文本卡 (请在下方填写)")
            self._switch_page(self.PAGE_MANUAL)
        else:
            self.ai_status_label.setText("🚫 潜文本卡已关闭")
            self._switch_page(self.PAGE_CLOSED)

    def set_mode_visible(self, visible: bool) -> None:
        """控制整个潜文本面板的可见性."""
        self.setVisible(visible)

    # ---- internals ----

    def _switch_page(self, page_idx: int) -> None:
        """切换页面栈."""
        self.stack.setCurrentIndex(page_idx)

    def _reset_visibility_for_mode(self) -> None:
        """根据当前模式重置页面栈."""
        mode = self.cmb_mode.currentData() or MODE_AI_AUTO
        if mode == MODE_AI_AUTO:
            self._switch_page(self.PAGE_INTENT)
        elif mode == MODE_MANUAL:
            self._switch_page(self.PAGE_MANUAL)
        else:
            self._switch_page(self.PAGE_CLOSED)

    def _refresh_mode_label(self, mode: str) -> None:
        if mode == MODE_AI_AUTO:
            self.lbl_mode.setText("模式: 🧠 AI 自由规划")
        elif mode == MODE_MANUAL:
            self.lbl_mode.setText("模式: ✏️ 手写")
        else:
            self.lbl_mode.setText("模式: 🚫 关闭")

    def _on_mode_changed(self, _idx: int) -> None:
        if not self.current_project_id:
            return
        mode = self.cmb_mode.currentData()
        if not mode:
            return
        try:
            set_project_mode(self.current_project_id, mode, "")
            self._refresh_mode_label(mode)
            log.info(f"[SubtextPanel] 项目 {self.current_project_id} 模式 → {mode}")
        except ServiceError as e:
            Dialogs.warning("切换模式", str(e), parent=self)
            return

        # 重新加载当前章节数据
        if self.current_chapter_id:
            self.set_chapter(
                {"id": self.current_chapter_id},
                self._chapter_to_book.get(self.current_chapter_id),
            )
        else:
            self._reset_visibility_for_mode()

    def _fill_form(self, card) -> None:
        for fld, row in self._rows.items():
            val = getattr(card, fld, None) or ""
            row.setText(str(val))

    def _fill_card_view(self, card) -> None:
        for fld, row in self.card_view_rows.items():
            val = getattr(card, fld, None) or ""
            row.setText(str(val))

    def _clear_form(self) -> None:
        for row in self._rows.values():
            row.setText("")
        for row in self.card_view_rows.values():
            row.setText("")

    def _update_action_states(self) -> None:
        has_chap = self.current_chapter_id is not None
        has_project = self.current_project_id is not None
        enabled = has_chap and has_project
        self.btn_ai_gen.setEnabled(enabled)
        self.btn_save_subtext.setEnabled(enabled)
        self.btn_delete_subtext.setEnabled(enabled)
        self.btn_parse_intent.setEnabled(enabled)
        self.btn_direct_gen.setEnabled(enabled)
        self.btn_edit_card.setEnabled(has_chap)
        self.btn_delete_card_view.setEnabled(has_chap)

    # ---- 意图流程 ----

    def _on_parse_intent(self) -> None:
        """AI 解析意图 → 弹出确认对话框 → 生成潜文本卡."""
        if not self.current_chapter_id or not self.current_project_id:
            return
        intent = self.ed_intent.toPlainText().strip()
        if not intent:
            Dialogs.warning("意图解析", "请先输入意图", parent=self)
            return

        # 解析意图为要点
        points = parse_intent_to_points(intent)

        # 弹出确认对话框
        dlg = IntentConfirmDialog(points, parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        confirmed = dlg.get_confirmed_points()
        if not confirmed:
            return

        # 基于确认的要点生成潜文本卡
        book_id = self._chapter_to_book.get(self.current_chapter_id)
        if not book_id:
            Dialogs.warning("生成", "找不到所属卷册", parent=self)
            return
        try:
            generate_from_intent(
                self.current_project_id,
                self.current_chapter_id,
                intent,
                confirmed_points=confirmed,
            )
        except Exception as e:
            Dialogs.warning("生成潜文本卡", f"异常: {e}", parent=self)
            return

        Dialogs.info("生成潜文本卡", "✅ 已根据意图生成潜文本卡", parent=self)
        self.ed_intent.clear()
        self.set_chapter({"id": self.current_chapter_id}, book_id)

    def _on_direct_generate(self) -> None:
        """跳过确认，直接用意图生成潜文本卡."""
        if not self.current_chapter_id or not self.current_project_id:
            return
        intent = self.ed_intent.toPlainText().strip()
        if not intent:
            Dialogs.warning("直接生成", "请先输入意图", parent=self)
            return

        book_id = self._chapter_to_book.get(self.current_chapter_id)
        if not book_id:
            Dialogs.warning("生成", "找不到所属卷册", parent=self)
            return
        try:
            generate_from_intent(
                self.current_project_id,
                self.current_chapter_id,
                intent,
            )
        except Exception as e:
            Dialogs.warning("生成潜文本卡", f"异常: {e}", parent=self)
            return

        Dialogs.info("直接生成", "✅ 已生成潜文本卡", parent=self)
        self.ed_intent.clear()
        self.set_chapter({"id": self.current_chapter_id}, book_id)

    def _on_edit_card(self) -> None:
        """从查看模式切换到手动编辑模式."""
        self._switch_page(self.PAGE_MANUAL)
        # 填充当前卡数据到编辑表单
        if self.current_chapter_id:
            card = get_card_for_chapter(self.current_chapter_id)
            if card:
                self._fill_form(card)

    def _on_ai_generate(self) -> None:
        if not self.current_chapter_id or not self.current_project_id:
            return
        book_id = self._chapter_to_book.get(self.current_chapter_id)
        if not book_id:
            Dialogs.warning("AI 生成", "找不到所属卷册", parent=self)
            return
        try:
            chap = chapter_service.get(self.current_chapter_id)
        except ServiceError as e:
            Dialogs.warning("AI 生成", str(e), parent=self)
            return
        wc = len((chap.get("draft") or chap.get("final") or ""))
        brief = (chap.get("title") or "") + " " + (chap.get("draft") or chap.get("final") or "")[:60]
        try:
            card = auto_generate(self.current_project_id, self.current_chapter_id, brief, wc)
        except ServiceError as e:
            Dialogs.info("AI 自动生成", str(e), parent=self)
            return
        except Exception as e:
            Dialogs.warning("AI 自动生成", f"异常: {e}", parent=self)
            return
        self.set_chapter({"id": self.current_chapter_id}, book_id)
        Dialogs.info("AI 自动生成", "已生成潜文本卡。", parent=self)

    def _on_save_subtext(self) -> None:
        if not self.current_chapter_id:
            return
        fields = {fld: row.text() for fld, row in self._rows.items()}
        try:
            upsert_card(self.current_chapter_id, source="manual", **fields)
        except ServiceError as e:
            Dialogs.warning("保存", str(e), parent=self)
            return
        except Exception as e:
            Dialogs.warning("保存", f"异常: {e}", parent=self)
            return
        Dialogs.info("保存", "潜文本卡已保存。", parent=self)
        self.set_chapter({"id": self.current_chapter_id},
                         self._chapter_to_book.get(self.current_chapter_id))

    def _on_delete_subtext(self) -> None:
        if not self.current_chapter_id:
            return
        ok, _ = Dialogs.confirm("确认删除", "删除本章潜文本卡?", danger=True,
                                confirm_text="删除", parent=self)
        if not ok:
            return
        try:
            delete_card(self.current_chapter_id)
        except ServiceError as e:
            Dialogs.warning("删除", str(e), parent=self)
            return
        self._clear_form()
        self.set_chapter({"id": self.current_chapter_id},
                         self._chapter_to_book.get(self.current_chapter_id))


# --------------------------------------------------------------------- #
# 伏笔管理面板 (集成到大纲管理tab)
# --------------------------------------------------------------------- #

class HooksPanel(QWidget):
    """伏笔管理面板: 显示/编辑全书伏笔列表."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.current_project_id: Optional[str] = None
        self._build_ui()

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # 标题行
        header = QHBoxLayout()
        header.addWidget(QLabel("🪝 伏笔管理"))
        header.addStretch(1)
        v.addLayout(header)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: rgba(127,127,127,0.2);")
        sep.setFixedHeight(1)
        v.addWidget(sep)

        # 伏笔编辑器
        self.ed_hooks = QPlainTextEdit()
        self.ed_hooks.setPlaceholderText(
            "在此管理全书伏笔，每行一条，格式：\n\n"
            "伏笔名称 | 埋设章节 | 回收章节 | 状态\n\n"
            "示例：\n"
            "筑基丹被换 | 第3章 | 第15章 | 已回收\n"
            "神秘玉佩 | 第1章 | 待定 | 未回收"
        )
        self.ed_hooks.setMinimumHeight(200)
        v.addWidget(self.ed_hooks, 1)

        # 按钮行
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存伏笔")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setEnabled(False)
        btn_row.addWidget(self.btn_save)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

    def set_project(self, project: Optional[dict]) -> None:
        self.current_project_id = project.get("id") if project else None
        self.ed_hooks.clear()
        self.btn_save.setEnabled(False)
        if project:
            self._load_hooks()

    def _load_hooks(self) -> None:
        if not self.current_project_id:
            return
        try:
            data = setting_service.get_setting(self.current_project_id, "hooks")
        except ServiceError as e:
            log.warning(f"[HooksPanel] load hooks failed: {e}")
            return
        if data and data.get("data"):
            if isinstance(data["data"], str):
                self.ed_hooks.setPlainText(data["data"])
            else:
                import json
                self.ed_hooks.setPlainText(json.dumps(data["data"], ensure_ascii=False, indent=2))
        else:
            self.ed_hooks.clear()

    def _on_save(self) -> None:
        if not self.current_project_id:
            return
        raw = self.ed_hooks.toPlainText().strip()
        if not raw:
            try:
                setting_service.set_setting(self.current_project_id, "hooks", None)
            except ServiceError as e:
                Dialogs.warning("保存", str(e), parent=self)
                return
            Dialogs.info("保存", "伏笔已清空", parent=self)
            return
        # 尝试解析为JSON，失败则存为纯文本
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = raw
        try:
            setting_service.set_setting(self.current_project_id, "hooks", data)
        except ServiceError as e:
            Dialogs.warning("保存", str(e), parent=self)
            return
        Dialogs.info("保存", "伏笔已保存", parent=self)


# --------------------------------------------------------------------- #
# OutlineTab 主组件
# --------------------------------------------------------------------- #

class OutlineTab(QWidget):
    """大纲管理主组件 (树状结构 + 潜文本卡)."""

    # 结构变更信号: 通知外部(如 editor_tab)刷新章节结构
    structure_changed = Signal()
    # 请求跳转到故事单元: (unit_id)
    goto_unit_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.current_project: Optional[dict] = None
        self.current_project_id: Optional[str] = None
        self.current_book_id: Optional[str] = None
        self.current_chapter_id: Optional[str] = None
        self.current_chapter: Optional[dict] = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)

        self.title = QLabel("大纲管理")
        self.title.setObjectName("projectTitle")
        outer.addWidget(self.title)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # ---- 左侧: 树状章节目录 ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        left_layout.addWidget(QLabel("📂 章节目录"))

        self.outline_tree = QTreeWidget()
        self.outline_tree.setHeaderHidden(True)
        self.outline_tree.setRootIsDecorated(True)
        self.outline_tree.setAnimated(True)
        self.outline_tree.setIndentation(18)
        self.outline_tree.itemSelectionChanged.connect(self._on_tree_selection)
        left_layout.addWidget(self.outline_tree, 1)


        splitter.addWidget(left)

        # ---- 右侧: 全局容器 (TabWidget + 全局按钮行) ----
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.right_tabs = QTabWidget()
        self.right_tabs.setObjectName("outlineRightTabs")

        # Tab 1: 大纲编辑器
        outline_area = QWidget()
        outline_layout = QVBoxLayout(outline_area)
        outline_layout.setContentsMargins(0, 0, 0, 0)
        outline_layout.setSpacing(8)

        self.status_label = QLabel("选中章节后编辑大纲…")
        self.status_label.setStyleSheet(f"color: {text_chip()}; font-size: 12px;")
        outline_layout.addWidget(self.status_label)

        # 大纲编辑器
        outline_box = QGroupBox(" 章节大纲")
        outline_lay = QVBoxLayout(outline_box)
        outline_lay.setContentsMargins(8, 8, 8, 8)

        self.ed_outline = QPlainTextEdit()
        self.ed_outline.setPlaceholderText("章节大纲内容… (直接编辑, 自动保存)")
        self.ed_outline.setMinimumHeight(150)
        outline_lay.addWidget(self.ed_outline, 1)

        # 核心事件 + 情感弧线 (并排)
        mid = QHBoxLayout()
        self.ed_core = QPlainTextEdit()
        self.ed_core.setPlaceholderText("核心事件…")
        self.ed_core.setMaximumHeight(70)
        mid.addWidget(self.ed_core, 1)
        self.ed_emotion = QPlainTextEdit()
        self.ed_emotion.setPlaceholderText("情感弧线…")
        self.ed_emotion.setMaximumHeight(70)
        mid.addWidget(self.ed_emotion, 1)
        outline_lay.addLayout(mid)

        # 字数目标
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("字数目标:"))
        self.spn_words = NumberInput(lo=0, hi=100000, default=2500)
        bottom.addWidget(self.spn_words)
        bottom.addStretch(1)
        outline_lay.addLayout(bottom)

        outline_layout.addWidget(outline_box, 1)

        self.right_tabs.addTab(outline_area, "📝 大纲编辑")

        # Tab 2: 伏笔管理
        self.hooks_panel = HooksPanel()
        self.right_tabs.addTab(self.hooks_panel, "🪝 伏笔管理")

        # Tab 3: 潜文本卡 (和伏笔管理一样, 作为子页切换)
        self.subtext_panel = SubtextPanel()
        self.right_tabs.addTab(self.subtext_panel, "🎭 潜文本卡")

        right_layout.addWidget(self.right_tabs, 1)

        # tab 切换时更新按钮状态
        self.right_tabs.currentChanged.connect(self._on_tab_changed)

        # ---- 全局操作按钮行 (对所有 tab 生效) ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)

        self.btn_new_volume = QPushButton("📚 新增卷")
        self.btn_new_volume.setObjectName("btnSm")
        self.btn_new_volume.setToolTip("新建卷册")
        self.btn_new_volume.clicked.connect(self._on_new_book)
        self.btn_new_volume.setEnabled(False)
        btn_row.addWidget(self.btn_new_volume)

        self.btn_new_chapter = QPushButton("➕ 新增章")
        self.btn_new_chapter.setObjectName("btnSm")
        self.btn_new_chapter.setToolTip("新建章节")
        self.btn_new_chapter.clicked.connect(self._on_new_chapter)
        self.btn_new_chapter.setEnabled(False)
        btn_row.addWidget(self.btn_new_chapter)

        self.btn_rename = QPushButton("✏️ 重命名")
        self.btn_rename.setObjectName("btnSm")
        self.btn_rename.setToolTip("重命名选中项")
        self.btn_rename.clicked.connect(self._on_rename)
        self.btn_rename.setEnabled(False)
        btn_row.addWidget(self.btn_rename)

        self.btn_save = QPushButton("💾 保存")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setEnabled(False)
        btn_row.addWidget(self.btn_save)

        self.btn_delete = QPushButton("🗑 删除")
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_delete.setEnabled(False)
        btn_row.addWidget(self.btn_delete)

        self.btn_import_outline = QPushButton("📥 导入大纲")
        self.btn_import_outline.setObjectName("btnImportOutline")
        self.btn_import_outline.setToolTip("从 .md (按 ## 第N章 切分) 或 .json (list[chapter]) 导入章节大纲")
        self.btn_import_outline.clicked.connect(self._on_import_outline)
        self.btn_import_outline.setEnabled(False)
        btn_row.addWidget(self.btn_import_outline)

        self.btn_export_tree = QPushButton("📤 导出")
        self.btn_export_tree.setObjectName("btnSm")
        self.btn_export_tree.setToolTip("导出章节大纲为 .md / .json")
        self.btn_export_tree.clicked.connect(self._on_export_chapters)
        self.btn_export_tree.setEnabled(False)
        btn_row.addWidget(self.btn_export_tree)

        # 分隔
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet(f"color: {text_subtle()};")
        btn_row.addWidget(sep2)

        # 单元同步按钮
        self.btn_sync_from_unit = QPushButton("⬇️  从单元同步")
        self.btn_sync_from_unit.setObjectName("btnSm")
        self.btn_sync_from_unit.setToolTip("当前章节有关联单元时，用单元内容更新章节")
        self.btn_sync_from_unit.clicked.connect(self._on_sync_from_unit)
        self.btn_sync_from_unit.setEnabled(False)
        btn_row.addWidget(self.btn_sync_from_unit)

        self.btn_sync_to_unit = QPushButton("⬆️  推送到单元")
        self.btn_sync_to_unit.setObjectName("btnSm")
        self.btn_sync_to_unit.setToolTip("把当前章节的修改回写到关联单元")
        self.btn_sync_to_unit.clicked.connect(self._on_sync_to_unit)
        self.btn_sync_to_unit.setEnabled(False)
        btn_row.addWidget(self.btn_sync_to_unit)

        self.btn_goto_unit = QPushButton("🔗  跳转单元")
        self.btn_goto_unit.setObjectName("btnSm")
        self.btn_goto_unit.setToolTip("跳转到该章节关联的故事单元")
        self.btn_goto_unit.clicked.connect(self._on_goto_unit)
        self.btn_goto_unit.setEnabled(False)
        btn_row.addWidget(self.btn_goto_unit)

        btn_row.addStretch(1)
        right_layout.addLayout(btn_row)

        splitter.addWidget(right_widget)
        # 左侧目录窄宽，右侧编辑区撑满
        left.setMaximumWidth(200)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([180, 1100])

    # ---- public ----

    def set_project(self, project: Optional[dict]) -> None:
        self.current_project = project
        self.current_project_id = project.get("id") if project else None
        self.current_book_id = None
        self.current_chapter_id = None
        self.current_chapter = None
        if project is None:
            self.title.setText("大纲管理（未选择项目）")
            self.outline_tree.clear()
            self._clear_editor()
            self._set_buttons_enabled(False)
            self.btn_new_volume.setEnabled(False)
            self.btn_new_chapter.setEnabled(False)
            self.btn_rename.setEnabled(False)
            self.btn_export_tree.setEnabled(False)
            self.btn_import_outline.setEnabled(False)
            self.subtext_panel.set_project(None)
            self.hooks_panel.set_project(None)
            return
        self.title.setText(f"大纲管理 — {project.get('name', '')}")
        self.btn_new_volume.setEnabled(True)
        self.btn_export_tree.setEnabled(True)
        self.btn_import_outline.setEnabled(True)
        self.subtext_panel.set_project(project)
        self.hooks_panel.set_project(project)
        self._reload_books()
        self._on_tab_changed(self.right_tabs.currentIndex())

    # ---- 树状结构加载 ----

    def _reload_books(self) -> None:
        """从数据源重新构建整个树状结构."""
        if not self.current_project_id:
            return
        # 记住展开状态
        expanded_ids: set[str] = set()
        for i in range(self.outline_tree.topLevelItemCount()):
            vol_item = self.outline_tree.topLevelItem(i)
            if vol_item.isExpanded():
                d = vol_item.data(0, Qt.ItemDataRole.UserRole)
                if d:
                    expanded_ids.add(d.get("id", ""))
        # 记住当前选中
        selected_items = self.outline_tree.selectedItems()
        prev_selected_id = None
        prev_selected_type = None
        if selected_items:
            d = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
            if d:
                prev_selected_id = d.get("id")
                prev_selected_type = d.get("type")

        self.outline_tree.clear()

        try:
            data = book_service.list_for_project(self.current_project_id)
        except ServiceError as e:
            Dialogs.warning("加载卷册", str(e), parent=self)
            return

        matched_item = None
        for b in data.get("books", []):
            vol_label = f"第{b.get('volume_no', '?')}卷  {b.get('title') or ''}"
            vol_item = QTreeWidgetItem([vol_label])
            vol_data = {"type": "volume", **b}
            vol_item.setData(0, Qt.ItemDataRole.UserRole, vol_data)
            vol_item.setFlags(vol_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            self.outline_tree.addTopLevelItem(vol_item)

            # 恢复展开
            if b.get("id") in expanded_ids:
                vol_item.setExpanded(True)

            # 加载章节
            try:
                ch_data = chapter_service.list_for_book(b["id"])
            except ServiceError:
                ch_data = {"chapters": []}
            for c in ch_data.get("chapters", []):
                unit_marker = " 🔗" if c.get("source_unit_id") else ""
                ch_label = f"第{c.get('chapter_no', '?')}章  {c.get('title') or '(无题)'}{unit_marker}"
                ch_item = QTreeWidgetItem([ch_label])
                ch_data_full = {"type": "chapter", "book_id": b["id"],
                                "volume_no": b.get("volume_no"), **c}
                ch_item.setData(0, Qt.ItemDataRole.UserRole, ch_data_full)
                vol_item.addChild(ch_item)
                # 匹配上次选中
                if prev_selected_id == c.get("id") and prev_selected_type == "chapter":
                    matched_item = ch_item

            # 匹配上次选中的卷册
            if prev_selected_id == b.get("id") and prev_selected_type == "volume":
                matched_item = vol_item

        # 自动展开第一个卷册（如果没有展开记录）
        if not expanded_ids and self.outline_tree.topLevelItemCount() > 0:
            first = self.outline_tree.topLevelItem(0)
            first.setExpanded(True)
            # 如果之前没有选中项，自动选中第一个卷册
            if matched_item is None:
                matched_item = first

        # 恢复选中
        if matched_item:
            self.outline_tree.setCurrentItem(matched_item)
        else:
            self.outline_tree.clearSelection()
            self._on_tree_selection()  # 触发清空状态

    def _on_tree_selection(self) -> None:
        """树节点选中: 卷册 → 展开/收起 + 启用卷册操作; 章节 → 加载大纲 + 启用章节操作."""
        items = self.outline_tree.selectedItems()
        if not items:
            self.current_book_id = None
            self.current_chapter_id = None
            self.current_chapter = None
            self._clear_editor()
            self.btn_rename.setEnabled(False)
            self.btn_new_chapter.setEnabled(False)
            self._on_tab_changed(self.right_tabs.currentIndex())
            self.status_label.setText("选中章节后编辑大纲…")
            self.subtext_panel.set_chapter(None)
            return

        item = items[0]
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        node_type = data.get("type")

        if node_type == "volume":
            self.current_book_id = data["id"]
            self.current_chapter_id = None
            self.current_chapter = None
            self._clear_editor()
            self.btn_rename.setEnabled(True)
            self.btn_new_chapter.setEnabled(True)
            self._on_tab_changed(self.right_tabs.currentIndex())
            vol_title = data.get("title", "") or f"第{data.get('volume_no', '?')}卷"
            self.status_label.setText(f"选中卷册「{vol_title}」，点击章节查看大纲…")
            self.subtext_panel.set_chapter(None)
        elif node_type == "chapter":
            self.current_book_id = data.get("book_id")
            self.current_chapter_id = data["id"]
            self.current_chapter = {
                "id": data["id"],
                "title": data.get("title", ""),
                "chapter_no": data.get("chapter_no", "?"),
            }
            self.btn_rename.setEnabled(True)
            self.btn_new_chapter.setEnabled(self.current_book_id is not None)
            # 单元同步按钮：有关联单元才启用
            has_unit = bool(data.get("source_unit_id"))
            self.btn_sync_from_unit.setEnabled(has_unit)
            self.btn_sync_to_unit.setEnabled(has_unit)
            self.btn_goto_unit.setEnabled(has_unit)
            self._load_outline()
            self._on_tab_changed(self.right_tabs.currentIndex())
            self.subtext_panel.set_chapter(self.current_chapter, self.current_book_id)

    def _on_new_book(self) -> None:
        if not self.current_project_id:
            Dialogs.warning("新建卷册", "请先选择项目", parent=self)
            return
        ok, title = Dialogs.input("新建卷册", "卷册标题:", parent=self)
        if not ok or not title.strip():
            return
        try:
            books = book_service.list_for_project(self.current_project_id)
            next_vol = len(books.get("books", [])) + 1
            book_service.create(self.current_project_id, next_vol, title=title.strip())
        except ServiceError as e:
            Dialogs.warning("新建卷册", str(e), parent=self)
            return
        self._reload_books()
        self.structure_changed.emit()

    def _on_new_chapter(self) -> None:
        """在当前选中卷册下新建章节."""
        if not self.current_book_id:
            # 如果没有选中卷册，尝试用第一个卷册
            if self.outline_tree.topLevelItemCount() > 0:
                first_item = self.outline_tree.topLevelItem(0)
                first_data = first_item.data(0, Qt.ItemDataRole.UserRole)
                if first_data and first_data.get("type") == "volume":
                    self.current_book_id = first_data["id"]
                else:
                    Dialogs.warning("新建章节", "请先选择卷册", parent=self)
                    return
            else:
                Dialogs.warning("新建章节", "请先创建卷册", parent=self)
                return
        ok, title = Dialogs.input("新建章节", "章节标题:", parent=self)
        if not ok or not title.strip():
            return
        try:
            chapters = chapter_service.list_for_book(self.current_book_id)
            next_no = len(chapters.get("chapters", [])) + 1
            chapter_service.create(self.current_book_id, next_no, title=title.strip())
        except ServiceError as e:
            Dialogs.warning("新建章节", str(e), parent=self)
            return
        self._reload_books()
        self.structure_changed.emit()

    def _on_rename(self) -> None:
        """重命名选中的卷册或章节."""
        items = self.outline_tree.selectedItems()
        if not items:
            return
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        node_type = data.get("type")
        if node_type == "volume":
            old_title = data.get("title", "")
            ok, new_title = Dialogs.input(
                "重命名卷册",
                f"卷册标题 (第{data.get('volume_no', '?')}卷):",
                initial=old_title,
                parent=self,
            )
            if not ok or not new_title.strip():
                return
            try:
                book_service.update(data["id"], title=new_title.strip())
            except ServiceError as e:
                Dialogs.warning("重命名卷册", str(e), parent=self)
                return
        elif node_type == "chapter":
            old_title = data.get("title", "")
            ok, new_title = Dialogs.input(
                "重命名章节",
                f"章节标题 (第{data.get('chapter_no', '?')}章):",
                initial=old_title,
                parent=self,
            )
            if not ok or not new_title.strip():
                return
            try:
                chapter_service.update(data["id"], title=new_title.strip())
            except ServiceError as e:
                Dialogs.warning("重命名章节", str(e), parent=self)
                return
        else:
            return
        self._reload_books()
        self.structure_changed.emit()

    def _on_import_chapters(self) -> None:
        """从文件导入章节大纲 (.md / .json)"""
        if not self.current_project:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择章节大纲文件 (.md / .json)",
            "", "Markdown / JSON (*.md *.markdown *.json);;All files (*.*)",
        )
        if not path:
            return
        try:
            from app.services import setting_io
            result = setting_io.import_outlines(self.current_project["id"], path)
        except Exception as e:
            Dialogs.warning("导入失败", str(e), parent=self)
            return
        Dialogs.info(
            "导入完成",
            f"已导入章节大纲: {result.get('imported', 0)} 章\n"
            f"新建分卷: {result.get('created_volumes', 0)} 卷\n"
            f"新建章节: {result.get('created_chapters', 0)} 章",
            parent=self,
        )
        self._reload_books()
        self.structure_changed.emit()

    # ── 单元同步 ──

    def _get_current_unit_id(self) -> Optional[str]:
        """获取当前选中章节关联的单元 ID。"""
        if not self.current_chapter_id or not self.outline_tree.currentItem():
            return None
        data = self.outline_tree.currentItem().data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return None
        uid = data.get("source_unit_id")
        return uid if uid else None

    def _on_sync_from_unit(self) -> None:
        """从单元同步到章节（单元 → 章节）。"""
        unit_id = self._get_current_unit_id()
        if not unit_id:
            Dialogs.warning("同步", "当前章节没有关联的故事单元", parent=self)
            return

        reply = QMessageBox.question(
            self, "确认同步",
            "将用关联单元的内容覆盖当前章节。\n"
            "章节的正文、大纲等会被单元内容替换。\n\n"
            "确定执行同步吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from app.services import unit_chapter_mapper
            result = unit_chapter_mapper.sync_unit_to_chapters(unit_id)
            ok_count = sum(1 for r in result if r.ok)
            self._reload_books()
            self.structure_changed.emit()
            Dialogs.info(
                "同步完成",
                f"已从单元同步到 {ok_count} 个章节。\n"
                f"（共 {len(result)} 个关联章节）",
                parent=self,
            )
        except Exception as e:
            Dialogs.warning("同步失败", str(e), parent=self)

    def _on_sync_to_unit(self) -> None:
        """从章节推送到单元（章节 → 单元）。"""
        if not self.current_chapter_id:
            return

        unit_id = self._get_current_unit_id()
        if not unit_id:
            Dialogs.warning("同步", "当前章节没有关联的故事单元", parent=self)
            return

        reply = QMessageBox.question(
            self, "确认推送",
            "将把当前章节的修改回写到关联单元。\n"
            "单元对应段落的内容会被章节内容替换。\n\n"
            "确定执行推送吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from app.services import unit_chapter_mapper
            result = unit_chapter_mapper.sync_chapter_to_unit(self.current_chapter_id)
            if result.ok:
                self._reload_books()
                self.structure_changed.emit()
                Dialogs.info("推送完成", f"已同步到单元：{result.message}", parent=self)
            else:
                Dialogs.warning("推送失败", result.message, parent=self)
        except Exception as e:
            Dialogs.warning("推送失败", str(e), parent=self)

    def _on_goto_unit(self) -> None:
        """跳转到关联的故事单元。"""
        unit_id = self._get_current_unit_id()
        if not unit_id:
            return
        # 发射信号，由主窗口处理 Tab 切换
        self.goto_unit_requested.emit(unit_id)

    def _on_export_chapters(self) -> None:
        """导出章节大纲为 .json 或 .md"""
        if not self.current_project or not self.current_project_id:
            return
        # 收集当前项目所有章节 + 大纲
        try:
            books_data = book_service.list_for_project(self.current_project_id)
        except ServiceError as e:
            Dialogs.warning("导出", f"加载卷册失败: {e}", parent=self)
            return

        chapters_out = []
        for b in books_data.get("books", []):
            vol_no = b.get("volume_no", "?")
            vol_title = b.get("title", "")
            try:
                ch_data = chapter_service.list_for_book(b["id"])
            except ServiceError:
                ch_data = {"chapters": []}
            for c in ch_data.get("chapters", []):
                ch_no = c.get("chapter_no", "?")
                # 尝试加载大纲
                outline_text = ""
                try:
                    ol = outline_service.get_outline(c["id"], SINGLE_VERSION)
                    if ol:
                        outline_text = ol.get("outline", "")
                except Exception:
                    pass
                chapters_out.append({
                    "volume_no": vol_no,
                    "volume_title": vol_title,
                    "chapter_no": ch_no,
                    "chapter_id": c["id"],
                    "title": c.get("title", ""),
                    "outline": outline_text,
                })

        if not chapters_out:
            Dialogs.info("导出", "当前项目没有章节可供导出", parent=self)
            return

        # 弹出保存文件对话框
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "导出章节大纲",
            f"{self.current_project.get('name', 'outline')}.json",
            "JSON (*.json);;Markdown (*.md)",
        )
        if not path:
            return

        try:
            if path.lower().endswith(".md"):
                self._export_as_md(path, chapters_out)
            else:
                self._export_as_json(path, chapters_out)
        except Exception as e:
            Dialogs.warning("导出失败", str(e), parent=self)
            return

        Dialogs.info("导出完成", f"已导出 {len(chapters_out)} 章大纲到:\n{path}", parent=self)

    @staticmethod
    def _export_as_json(path: str, chapters: list) -> None:
        """导出为 JSON 格式"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(chapters, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _export_as_md(path: str, chapters: list) -> None:
        """导出为 Markdown 格式"""
        lines = []
        current_vol = None
        for ch in chapters:
            vol_label = f"第{ch['volume_no']}卷 {ch['volume_title']}".strip()
            if vol_label != current_vol:
                current_vol = vol_label
                lines.append(f"\n# {vol_label}\n")
            lines.append(f"## 第{ch['chapter_no']}章 {ch['title']}")
            if ch.get("outline"):
                lines.append(f"\n{ch['outline']}\n")
            else:
                lines.append("")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _load_outline(self) -> None:
        """加载当前章节的大纲 (单版本)."""
        if not self.current_chapter_id:
            return
        try:
            data = outline_service.get_outline(self.current_chapter_id, SINGLE_VERSION)
        except Exception as e:
            log.warning(f"[OutlineTab] load outline failed: {e}")
            data = None

        if data:
            self.ed_outline.setPlainText(data.get("outline", ""))
            self.ed_core.setPlainText(data.get("core_events", ""))
            self.ed_emotion.setPlainText(data.get("emotion_arc", ""))
            wt = data.get("word_target")
            self.spn_words.setValue(int(wt) if wt else 2500)
            self.status_label.setText("大纲已加载")
        else:
            self.ed_outline.clear()
            self.ed_core.clear()
            self.ed_emotion.clear()
            self.spn_words.setValue(2500)
            self.status_label.setText("本章暂无大纲, 可直接编辑")

    def _clear_editor(self) -> None:
        self.ed_outline.clear()
        self.ed_core.clear()
        self.ed_emotion.clear()
        self.spn_words.setValue(2500)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self.btn_save.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)

    def _on_tab_changed(self, idx: int) -> None:
        """右侧 tab 切换时更新按钮启用状态与提示."""
        if not self.current_project_id:
            self.btn_save.setEnabled(False)
            self.btn_delete.setEnabled(False)
            return

        has_chapter = self.current_chapter_id is not None
        has_volume = self.current_book_id is not None
        has_tree_selection = has_chapter or has_volume

        if idx == 0:  # 大纲编辑
            self.btn_save.setEnabled(has_chapter)
            self.btn_delete.setEnabled(has_tree_selection)
            if has_chapter:
                self.btn_save.setToolTip("保存当前章节大纲")
                self.btn_delete.setToolTip("删除当前章节")
            elif has_volume:
                self.btn_save.setToolTip("请选中章节后保存大纲")
                self.btn_delete.setToolTip("删除当前卷册")
            else:
                self.btn_save.setToolTip("保存当前章节大纲")
                self.btn_delete.setToolTip("删除当前章节大纲")
        elif idx == 1:  # 伏笔管理
            self.btn_save.setEnabled(True)
            self.btn_delete.setEnabled(has_volume if not has_chapter else True)
            self.btn_save.setToolTip("保存全书伏笔")
            if has_volume and not has_chapter:
                self.btn_delete.setToolTip("删除当前卷册")
            else:
                self.btn_delete.setToolTip("清空伏笔内容")
        elif idx == 2:  # 潜文本卡
            self.btn_save.setEnabled(has_chapter)
            self.btn_delete.setEnabled(has_chapter or has_volume)
            if has_chapter:
                self.btn_save.setToolTip("保存潜文本卡")
                self.btn_delete.setToolTip("删除潜文本卡")
            elif has_volume:
                self.btn_save.setToolTip("请选中章节后保存潜文本卡")
                self.btn_delete.setToolTip("删除当前卷册")
            else:
                self.btn_save.setToolTip("保存潜文本卡")
                self.btn_delete.setToolTip("删除潜文本卡")

    # ---- 操作 ----

    def _on_save(self) -> None:
        """根据当前激活的 tab 保存对应内容."""
        tab_idx = self.right_tabs.currentIndex()
        # Tab 0: 大纲编辑
        if tab_idx == 0:
            if not self.current_chapter_id:
                return
            outline_text = self.ed_outline.toPlainText().strip()
            if not outline_text:
                Dialogs.warning("保存", "大纲内容不能为空", parent=self)
                return
            try:
                outline_service.save_outline(
                    self.current_chapter_id, SINGLE_VERSION,
                    outline=outline_text,
                    core_events=self.ed_core.toPlainText().strip() or None,
                    emotion_arc=self.ed_emotion.toPlainText().strip() or None,
                    word_target=self.spn_words.value() or None,
                )
                self.status_label.setText("✅ 大纲已保存")
            except Exception as e:
                Dialogs.warning("保存大纲", str(e), parent=self)
        # Tab 1: 伏笔管理
        elif tab_idx == 1:
            self.hooks_panel._on_save()
        # Tab 2: 潜文本卡
        elif tab_idx == 2:
            self.subtext_panel._on_save_subtext()

    def _on_delete(self) -> None:
        """全局删除按钮: 优先处理树节点删除, 否则按 tab 分发."""
        # 1) 检查树选中节点 — 卷册/章节 → 从目录删除
        items = self.outline_tree.selectedItems()
        if items:
            data = items[0].data(0, Qt.ItemDataRole.UserRole)
            if data:
                node_type = data.get("type")
                if node_type == "volume":
                    vol_no = data.get("volume_no", "?")
                    ok, _ = Dialogs.confirm(
                        "删除卷册",
                        f"确定要删除第 {vol_no} 卷「{data.get('title', '')}」及其所有章节吗？\n此操作不可恢复！",
                        danger=True,
                        confirm_text="确认删除",
                        parent=self,
                    )
                    if not ok:
                        return
                    try:
                        book_service.delete(data["id"])
                    except ServiceError as e:
                        Dialogs.warning("删除卷册", str(e), parent=self)
                        return
                    self.current_book_id = None
                    self.current_chapter_id = None
                    self.current_chapter = None
                    self._clear_editor()
                    self.status_label.setText("选中章节后编辑大纲…")
                    self.subtext_panel.set_chapter(None)
                    self._reload_books()
                    self._on_tab_changed(self.right_tabs.currentIndex())
                    self.structure_changed.emit()
                    return
                elif node_type == "chapter":
                    ch_no = data.get("chapter_no", "?")
                    ok, _ = Dialogs.confirm(
                        "删除章节",
                        f"确定要删除第 {ch_no} 章「{data.get('title', '')}」吗？",
                        danger=True,
                        confirm_text="确认删除",
                        parent=self,
                    )
                    if not ok:
                        return
                    try:
                        chapter_service.delete(data["id"])
                    except ServiceError as e:
                        Dialogs.warning("删除章节", str(e), parent=self)
                        return
                    self.current_chapter_id = None
                    self.current_chapter = None
                    self._clear_editor()
                    self.status_label.setText("选中章节后编辑大纲…")
                    self.subtext_panel.set_chapter(None)
                    self._reload_books()
                    self._on_tab_changed(self.right_tabs.currentIndex())
                    self.structure_changed.emit()
                    return

        # 2) 树没有选中节点 → 按 tab 删除内容
        tab_idx = self.right_tabs.currentIndex()
        if tab_idx == 0:  # 大纲编辑 — 删除大纲
            if not self.current_chapter_id:
                return
            ok, _ = Dialogs.confirm(
                "删除大纲",
                f"确定要删除第 {self.current_chapter.get('chapter_no', '?')} 章的大纲吗？",
                parent=self,
            )
            if not ok:
                return
            try:
                outline_service.delete_outline(self.current_chapter_id, SINGLE_VERSION)
                self._clear_editor()
                self.status_label.setText("已删除大纲")
                self._on_tab_changed(self.right_tabs.currentIndex())
            except Exception as e:
                Dialogs.warning("删除", str(e), parent=self)
        elif tab_idx == 1:  # 伏笔管理 — 清空伏笔
            ok, _ = Dialogs.confirm(
                "清空伏笔",
                "确定要清空全书伏笔吗？",
                parent=self,
            )
            if not ok:
                return
            self.hooks_panel.ed_hooks.clear()
            self.hooks_panel._on_save()
        elif tab_idx == 2:  # 潜文本卡 — 删除潜文本卡
            self.subtext_panel._on_delete_subtext()

    # ------------------------------------------------------------------
    # V4.0-P4-新: 导入大纲 (从小说设定tab移过来)
    # ------------------------------------------------------------------
    def _on_import_outline(self) -> None:
        """弹文件选择 → 写入 chapter.outline (或 setting_service.chapter_outline 兜底)."""
        if not self.current_project:
            return
        from PySide6.QtWidgets import QFileDialog
        from app.services import setting_io
        path, _ = QFileDialog.getOpenFileName(
            self, "选择大纲文件 (md / json)",
            "", "Markdown / JSON (*.md *.markdown *.json);;All files (*.*)",
        )
        if not path:
            return
        try:
            result = setting_io.import_outlines(self.current_project["id"], path)
        except Exception as e:
            Dialogs.warning("导入失败", str(e), parent=self)
            return
        Dialogs.info(
            "导入完成",
            f"已导入章节大纲: {result.get('imported', 0)} 章\n"
            f"新建分卷: {result.get('created_volumes', 0)} 卷\n"
            f"新建章节: {result.get('created_chapters', 0)} 章\n"
            f"格式: {result.get('format', '?')}",
            parent=self,
        )
        # 导入后刷新章节列表
        self._reload_books()
        self.structure_changed.emit()
