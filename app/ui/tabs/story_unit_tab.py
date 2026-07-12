# -*- coding: utf-8 -*-
"""
故事单元 Tab (Story Unit Tab)

以故事单元为单位的创作管理界面：
- 左侧：单元列表（可排序）
- 右侧：单元详情 + 草稿编辑 + 快照管理 + 拆章功能
"""
from __future__ import annotations

import json
import logging
from typing import Optional

_logger = logging.getLogger("NovelWriter.ui.story_unit_tab")

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QListWidget, QListWidgetItem,
    QLineEdit, QTextEdit, QComboBox, QMessageBox, QGroupBox,
    QFormLayout, QSpinBox, QSplitter, QInputDialog, QDialog,
    QDialogButtonBox, QPlainTextEdit, QProgressBar,
)
from app.ui.theme import text_chip

from app.services import story_unit_service_v2 as story_unit_service
from app.services.story_unit_service_v2 import VALID_TRANSITIONS
from app.services import unit_writing_service
from app.services import unit_chapter_mapper
from app.services import emotion_analyzer
from app.services import book_service
from app.services import ServiceError
from app.ui.widgets import Dialogs


SPLIT_STRATEGIES = [
    ("auto", "自动"),
    ("爽文", "爽文"),
    ("悬疑", "悬疑"),
    ("感情", "感情"),
    ("节奏", "节奏"),
    ("平稳", "平稳"),
]


UNIT_TYPE_LABELS = {
    "battle": "⚔️ 战斗",
    "romance": "💕 感情",
    "reveal": "🔮 揭秘",
    "transition": "🔄 过渡",
    "climax": "🔥 高潮",
    "setup": "🎬 铺垫",
    "payoff": "🎯 回收",
    "filler": "📖 日常",
    "other": "📦 其他",
}

STATUS_LABELS = {
    "draft": "📝 草稿",
    "outlining": "📐 大纲中",
    "writing": "✍️ 写作中",
    "completed": "✅ 已完成",
    "split": "📦 已拆章",
}

TRANSITION_LABELS = {
    "direct": "直接",
    "time_jump": "时间跳跃",
    "pov_switch": "视角切换",
    "flashback": "闪回",
    "parallel": "平行",
    "chekhov": "契诃夫之枪",
    "contrast": "对比",
    "suspense_front": "悬念前置",
}


def _parse_json_list(v) -> list:
    """把 JSON 字符串/列表安全解析为字符串列表."""
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


class DeleteUnitDialog(QDialog):
    """删除单元确认对话框 - 三选一"""

    DELETE_CHAPTERS = "delete_chapters"
    DETACH_CHAPTERS = "detach_chapters"
    CANCEL = "cancel"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("删除单元")
        self.setMinimumWidth(420)
        self._result = self.CANCEL
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        tip = QLabel(
            "删除单元会同时清理单元的快照、段落、钩子等数据。\n"
            "请选择如何处理已从该单元拆分出的章节："
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        btn_delete = QPushButton("🗑️  一并删除章节（完整清理）")
        btn_delete.clicked.connect(self._on_delete_chapters)
        layout.addWidget(btn_delete)

        btn_detach = QPushButton("🔗  保留章节，解除关联（章节转正）")
        btn_detach.clicked.connect(self._on_detach_chapters)
        layout.addWidget(btn_detach)

        btn_cancel = QPushButton("❌  取消删除")
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

        hint = QLabel(
            "💡 说明：\n"
            "• 一并删除：单元和它拆出的章节全部删除，不可恢复\n"
            "• 保留章节：章节变成独立章节，不再关联到该单元\n"
            "• 手动编辑/锁定的钩子和记忆会保留 manual_locked 标记"
        )
        hint.setStyleSheet(f"color: {text_chip()}; font-size: 12px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _on_delete_chapters(self):
        self._result = self.DELETE_CHAPTERS
        self.accept()

    def _on_detach_chapters(self):
        self._result = self.DETACH_CHAPTERS
        self.accept()

    def get_option(self) -> str:
        return self._result


class StoryUnitTab(QWidget):
    """故事单元管理 Tab"""

    unit_selected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._project_id: Optional[str] = None
        self._current_unit_id: Optional[str] = None
        self._units: list = []
        self._split_report = None
        self._split_positions: Optional[list[int]] = None
        self._build_ui()

    # ── UI 构建 ──

    def _build_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # 左侧：单元列表
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 4, 8)
        left_layout.setSpacing(6)

        # 顶部工具栏
        toolbar = QHBoxLayout()
        title = QLabel("📦 故事单元")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        toolbar.addWidget(title)

        toolbar.addWidget(QLabel("视图："))
        self.cmb_timeline = QComboBox()
        self.cmb_timeline.addItem("故事时间", "story")
        self.cmb_timeline.addItem("呈现顺序", "present")
        self.cmb_timeline.currentIndexChanged.connect(lambda: self._refresh_list())
        toolbar.addWidget(self.cmb_timeline)
        toolbar.addStretch()

        btn_add = QPushButton("+ 新增")
        btn_add.clicked.connect(self._on_add_unit)
        toolbar.addWidget(btn_add)

        btn_composite = QPushButton("📦 复合单元")
        btn_composite.setToolTip("创建复合单元，将多个子单元组织在一起")
        btn_composite.clicked.connect(self._on_create_composite)
        toolbar.addWidget(btn_composite)

        left_layout.addLayout(toolbar)

        # 单元列表 (QTreeWidget 支持复合单元折叠)
        self.unit_list = QTreeWidget()
        self.unit_list.setHeaderHidden(True)
        self.unit_list.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.unit_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.unit_list.itemClicked.connect(self._on_unit_clicked)
        left_layout.addWidget(self.unit_list, 1)

        # 底部操作
        bottom_bar = QHBoxLayout()
        btn_up = QPushButton("↑ 上移")
        btn_up.clicked.connect(self._on_move_up)
        bottom_bar.addWidget(btn_up)

        btn_down = QPushButton("↓ 下移")
        btn_down.clicked.connect(self._on_move_down)
        bottom_bar.addWidget(btn_down)

        btn_delete = QPushButton("🗑️ 删除")
        btn_delete.clicked.connect(self._on_delete_unit)
        bottom_bar.addWidget(btn_delete)

        left_layout.addLayout(bottom_bar)

        splitter.addWidget(left_panel)
        splitter.setStretchFactor(0, 1)

        # 右侧：单元详情（滚动区域）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 8, 8, 8)
        right_layout.setSpacing(8)

        # 基本信息
        info_group = QGroupBox("基本信息")
        info_form = QFormLayout(info_group)

        self.ed_title = QLineEdit()
        self.ed_title.setPlaceholderText("单元标题")
        info_form.addRow("标题：", self.ed_title)

        self.cmb_type = QComboBox()
        for key, label in UNIT_TYPE_LABELS.items():
            self.cmb_type.addItem(label, key)
        info_form.addRow("类型：", self.cmb_type)

        self.cmb_status = QComboBox()
        for key, label in STATUS_LABELS.items():
            self.cmb_status.addItem(label, key)
        info_form.addRow("状态：", self.cmb_status)

        self.cmb_transition = QComboBox()
        for key in VALID_TRANSITIONS:
            label = TRANSITION_LABELS.get(key, key)
            self.cmb_transition.addItem(label, key)
        info_form.addRow("转场：", self.cmb_transition)

        self.ed_transition_text = QLineEdit()
        self.ed_transition_text.setPlaceholderText("转场说明（如：三年后 / 同一夜）")
        info_form.addRow("转场说明：", self.ed_transition_text)

        self.sp_order = QSpinBox()
        self.sp_order.setRange(1, 9999)
        info_form.addRow("排序：", self.sp_order)

        self.sp_target_chars = QSpinBox()
        self.sp_target_chars.setRange(500, 100000)
        self.sp_target_chars.setValue(5000)
        self.sp_target_chars.setSingleStep(500)
        info_form.addRow("目标字数：", self.sp_target_chars)

        self.lbl_word_count = QLabel("0 字")
        info_form.addRow("字数：", self.lbl_word_count)

        right_layout.addWidget(info_group)

        # 写作进度
        progress_group = QGroupBox("写作进度")
        progress_layout = QVBoxLayout(progress_group)

        progress_row = QHBoxLayout()
        self.lbl_progress = QLabel("第 0 / 0 步")
        progress_row.addWidget(self.lbl_progress)
        progress_row.addStretch()
        self.lbl_progress_pct = QLabel("0%")
        progress_row.addWidget(self.lbl_progress_pct)
        progress_layout.addLayout(progress_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        progress_layout.addWidget(self.progress_bar)

        # 快照管理
        snap_row = QHBoxLayout()
        self.lbl_snapshot_count = QLabel("快照：0 个")
        snap_row.addWidget(self.lbl_snapshot_count)
        snap_row.addStretch()

        btn_rollback = QPushButton("⏪ 回滚到选中快照")
        btn_rollback.clicked.connect(self._on_rollback_snapshot)
        snap_row.addWidget(btn_rollback)
        progress_layout.addLayout(snap_row)

        self.snapshot_list = QListWidget()
        self.snapshot_list.setMaximumHeight(100)
        progress_layout.addWidget(self.snapshot_list)

        right_layout.addWidget(progress_group)

        # 简介
        synopsis_group = QGroupBox("单元简介")
        synopsis_layout = QVBoxLayout(synopsis_group)
        self.ed_synopsis = QTextEdit()
        self.ed_synopsis.setPlaceholderText("简要描述这个单元的主要剧情...")
        self.ed_synopsis.setMaximumHeight(80)
        synopsis_layout.addWidget(self.ed_synopsis)
        right_layout.addWidget(synopsis_group)

        # 因果与伏笔 (设计 §3.2 / §3.4)
        causal_group = QGroupBox("因果与伏笔")
        causal_layout = QVBoxLayout(causal_group)

        causal_layout.addWidget(QLabel("起因总结 (cause_summary)："))
        self.ed_cause = QTextEdit()
        self.ed_cause.setPlaceholderText("本单元因何而起（衔接上一单元后果）")
        self.ed_cause.setMaximumHeight(60)
        causal_layout.addWidget(self.ed_cause)

        causal_layout.addWidget(QLabel("后果总结 (effect_summary)："))
        self.ed_effect = QTextEdit()
        self.ed_effect.setPlaceholderText("本单元导致什么（供下一单元衔接）")
        self.ed_effect.setMaximumHeight(60)
        causal_layout.addWidget(self.ed_effect)

        hook_layout = QHBoxLayout()
        plant_col = QVBoxLayout()
        plant_col.addWidget(QLabel("计划埋设伏笔："))
        self.ed_hooks_plant = QPlainTextEdit()
        self.ed_hooks_plant.setPlaceholderText("每行一个伏笔")
        self.ed_hooks_plant.setMaximumHeight(70)
        plant_col.addWidget(self.ed_hooks_plant)

        pay_col = QVBoxLayout()
        pay_col.addWidget(QLabel("计划回收伏笔："))
        self.ed_hooks_pay = QPlainTextEdit()
        self.ed_hooks_pay.setPlaceholderText("每行一个伏笔")
        self.ed_hooks_pay.setMaximumHeight(70)
        pay_col.addWidget(self.ed_hooks_pay)

        hook_layout.addLayout(plant_col)
        hook_layout.addLayout(pay_col)
        causal_layout.addLayout(hook_layout)

        right_layout.addWidget(causal_group)

        # 单元简介(详) (设计 §3.2)
        brief_group = QGroupBox("单元简介（详）")
        brief_layout = QVBoxLayout(brief_group)

        brief_layout.addWidget(QLabel("核心事件 (core_events，每行一个)："))
        self.ed_core_events = QPlainTextEdit()
        self.ed_core_events.setPlaceholderText("每行一个核心事件")
        self.ed_core_events.setMaximumHeight(70)
        brief_layout.addWidget(self.ed_core_events)

        brief_layout.addWidget(QLabel("情绪弧 (emotion_arc)："))
        self.ed_emotion_arc = QTextEdit()
        self.ed_emotion_arc.setPlaceholderText("本单元情绪走向描述")
        self.ed_emotion_arc.setMaximumHeight(60)
        brief_layout.addWidget(self.ed_emotion_arc)

        right_layout.addWidget(brief_group)

        # 草稿编辑
        draft_group = QGroupBox("单元草稿")
        draft_layout = QVBoxLayout(draft_group)

        draft_toolbar = QHBoxLayout()
        draft_toolbar.addWidget(QLabel("正文草稿"))
        draft_toolbar.addStretch()

        btn_save = QPushButton("💾 保存草稿")
        btn_save.clicked.connect(self._on_save_draft)
        draft_toolbar.addWidget(btn_save)

        draft_layout.addLayout(draft_toolbar)

        self.ed_draft = QPlainTextEdit()
        self.ed_draft.setPlaceholderText("在这里写单元正文...")
        self.ed_draft.textChanged.connect(self._update_word_count)
        draft_layout.addWidget(self.ed_draft, 1)

        right_layout.addWidget(draft_group, 1)

        # 拆章功能已废弃: 多单元拼接断章移至发布模块「成稿向导」(AssemblyWizard)

        scroll.setWidget(right_panel)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(1, 3)

        # 初始状态
        self._set_details_enabled(False)

    # ── 对外接口 ──

    def set_project(self, project) -> None:
        """设置当前项目，加载单元列表。

        main_window 统一把 project dict 传给各页 set_project,
        这里兼容 str id 与 dict 两种形态。
        """
        if isinstance(project, dict):
            self._project_id = project.get("id") or ""
        else:
            self._project_id = project or ""
        self._current_unit_id = None
        self._refresh_books()
        self._refresh_list()
        self._clear_details()

    def refresh(self):
        """刷新数据。"""
        current_id = self._current_unit_id
        self._refresh_list()
        if current_id:
            self._select_unit_by_id(current_id)

    # ── 列表操作 ──

    def _refresh_list(self):
        """刷新单元列表。"""
        self.unit_list.clear()
        self._units = []

        if not self._project_id:
            return

        try:
            order_by = "story"
            if getattr(self, "cmb_timeline", None) is not None:
                order_by = self.cmb_timeline.currentData() or "story"
            self._units = story_unit_service.list_for_project(
                self._project_id, order_by=order_by
            )
        except ServiceError as e:
            Dialogs.error("加载失败", str(e))
            return

        order_label = "故事" if order_by == "story" else "呈现"

        # 分离复合单元和原子单元
        composites = {}
        top_level = []
        for unit in self._units:
            if unit.sequence_id:
                composites.setdefault(unit.sequence_id, []).append(unit)
            else:
                top_level.append(unit)

        for unit in top_level:
            type_label = UNIT_TYPE_LABELS.get(unit.unit_type, unit.unit_type)
            status_label = STATUS_LABELS.get(unit.status, unit.status)
            title = unit.title or "（无标题）"
            wc = f" ({unit.word_count}字)" if unit.word_count else ""

            children = composites.get(unit.id, [])
            child_count = len(children)

            if unit.unit_type == "sequence" and child_count > 0:
                # 复合单元: 折叠显示
                item_text = f"📦 {title} [{child_count}个子单元]{wc}"
                item = QTreeWidgetItem(self.unit_list)
                item.setText(0, item_text)
                item.setData(0, Qt.ItemDataRole.UserRole, unit.id)
                item.setExpanded(False)

                for child in children:
                    child_type = UNIT_TYPE_LABELS.get(child.unit_type, child.unit_type)
                    child_status = STATUS_LABELS.get(child.status, child.status)
                    child_title = child.title or "（无标题）"
                    child_wc = f" ({child.word_count}字)" if child.word_count else ""
                    child_text = f"  {child_type}  {child_title}{child_wc}  {child_status}"
                    child_item = QTreeWidgetItem(item)
                    child_item.setText(0, child_text)
                    child_item.setData(0, Qt.ItemDataRole.UserRole, child.id)
            else:
                # 普通单元
                item_text = f"{type_label}  {title}{wc}  {status_label}  {order_label}序:{getattr(unit, order_by + '_order', unit.story_order)}"
                item = QTreeWidgetItem(self.unit_list)
                item.setText(0, item_text)
                item.setData(0, Qt.ItemDataRole.UserRole, unit.id)

    def _on_unit_clicked(self, item: QTreeWidgetItem, col: int = 0):
        unit_id = item.data(0, Qt.ItemDataRole.UserRole)
        if unit_id:
            self._load_unit_details(unit_id)

    def _select_unit_by_id(self, unit_id: str):
        """按 ID 选中单元。"""
        for i in range(self.unit_list.topLevelItemCount()):
            item = self.unit_list.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == unit_id:
                self.unit_list.setCurrentItem(item)
                self._load_unit_details(unit_id)
                return
            # 检查子项
            for j in range(item.childCount()):
                child = item.child(j)
                if child.data(0, Qt.ItemDataRole.UserRole) == unit_id:
                    self.unit_list.setCurrentItem(child)
                    item.setExpanded(True)
                    self._load_unit_details(unit_id)
                    return

    # ── 详情操作 ──

    def _load_unit_details(self, unit_id: str):
        """加载单元详情。"""
        try:
            unit = story_unit_service.get(unit_id)
        except ServiceError as e:
            Dialogs.error("加载失败", str(e))
            return

        self._current_unit_id = unit_id
        self._set_details_enabled(True)

        self.ed_title.setText(unit.title)
        idx = self.cmb_type.findData(unit.unit_type)
        if idx >= 0:
            self.cmb_type.setCurrentIndex(idx)
        idx = self.cmb_status.findData(unit.status)
        if idx >= 0:
            self.cmb_status.setCurrentIndex(idx)

        self.sp_order.setValue(unit.story_order)
        self.sp_target_chars.setValue(unit.target_chars or 5000)
        self.lbl_word_count.setText(f"{unit.word_count} 字")
        self.ed_synopsis.setPlainText(unit.synopsis or "")
        self.ed_draft.setPlainText(unit.draft or "")
        self._original_draft = unit.draft or ""  # v4.3: 保存原始草稿用于 diff

        # 转场
        idx = self.cmb_transition.findData(getattr(unit, "transition_type", "direct") or "direct")
        if idx >= 0:
            self.cmb_transition.setCurrentIndex(idx)
        self.ed_transition_text.setText(getattr(unit, "transition_text", "") or "")

        # 因果与伏笔 (brief)
        try:
            brief = story_unit_service.get_brief(unit_id)
        except Exception:
            brief = None
        if brief is not None:
            self.ed_cause.setPlainText(getattr(brief, "cause_summary", "") or "")
            self.ed_effect.setPlainText(getattr(brief, "effect_summary", "") or "")
            self.ed_core_events.setPlainText(
                "\n".join(_parse_json_list(getattr(brief, "core_events", "[]")))
            )
            self.ed_emotion_arc.setPlainText(getattr(brief, "emotion_arc", "") or "")
            self.ed_hooks_plant.setPlainText(
                "\n".join(_parse_json_list(getattr(brief, "hooks_planned_plant", "[]")))
            )
            self.ed_hooks_pay.setPlainText(
                "\n".join(_parse_json_list(getattr(brief, "hooks_planned_pay", "[]")))
            )

        # 更新写作进度
        self._refresh_progress()

        # 更新快照列表
        self._refresh_snapshots()

        self.unit_selected.emit(unit_id)

    def _refresh_progress(self):
        """刷新写作进度显示。"""
        if not self._current_unit_id:
            self.progress_bar.setValue(0)
            self.lbl_progress.setText("第 0 / 0 步")
            self.lbl_progress_pct.setText("0%")
            return

        try:
            prog = unit_writing_service.get_progress(self._current_unit_id)
            current = prog["current_step"]
            total = prog["total_steps"]
            pct = prog["progress_percent"]

            self.progress_bar.setValue(int(pct))
            self.lbl_progress.setText(f"第 {current} / {total} 步")
            self.lbl_progress_pct.setText(f"{pct:.1f}%")
        except Exception:
            pass

    def _refresh_snapshots(self):
        """刷新快照列表。"""
        self.snapshot_list.clear()
        if not self._current_unit_id:
            self.lbl_snapshot_count.setText("快照：0 个")
            return

        try:
            snaps = unit_writing_service.list_snapshots(self._current_unit_id)
            self.lbl_snapshot_count.setText(f"快照：{len(snaps)} 个")

            for snap in reversed(snaps):
                label = (
                    f"Step {snap.step_no}  |  {snap.word_count}字  "
                    f"|  {snap.created_at}"
                )
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, snap.id)
                self.snapshot_list.addItem(item)

            if snaps:
                self.snapshot_list.setCurrentRow(0)
        except Exception as e:
            self.lbl_snapshot_count.setText(f"快照：加载失败 ({e})")

    def _refresh_books(self):
        """保留接口 (拆章目标分卷选择已移至发布模块成稿向导 AssemblyWizard)."""
        if not self._project_id:
            return
        try:
            book_service.list_for_project(self._project_id)
        except ServiceError:
            pass

    def _clear_details(self):
        """清空详情面板。"""
        self._current_unit_id = None
        self.ed_title.clear()
        self.ed_synopsis.clear()
        self.ed_draft.clear()
        self.ed_transition_text.clear()
        self.ed_cause.clear()
        self.ed_effect.clear()
        self.ed_core_events.clear()
        self.ed_emotion_arc.clear()
        self.ed_hooks_plant.clear()
        self.ed_hooks_pay.clear()
        self.lbl_word_count.setText("0 字")
        self.snapshot_list.clear()
        self.progress_bar.setValue(0)
        self.lbl_progress.setText("第 0 / 0 步")
        self.lbl_progress_pct.setText("0%")
        self.lbl_snapshot_count.setText("快照：0 个")
        self._set_details_enabled(False)

    def _set_details_enabled(self, enabled: bool):
        """启用/禁用详情面板。"""
        for w in [
            self.ed_title, self.cmb_type, self.cmb_status,
            self.cmb_transition, self.ed_transition_text,
            self.sp_order, self.sp_target_chars, self.ed_synopsis,
            self.ed_draft,
            self.ed_cause, self.ed_effect,
            self.ed_core_events, self.ed_emotion_arc,
            self.ed_hooks_plant, self.ed_hooks_pay,
        ]:
            w.setEnabled(enabled)

    def _update_word_count(self):
        """更新字数显示。"""
        text = self.ed_draft.toPlainText()
        self.lbl_word_count.setText(f"{len(text)} 字")

    # ── 按钮回调 ──

    def _on_add_unit(self):
        """新增单元。"""
        if not self._project_id:
            Dialogs.info("提示", "请先创建或打开项目")
            return

        title, ok = QInputDialog.getText(self, "新增单元", "单元标题：")
        if not ok or not title.strip():
            return

        try:
            unit = story_unit_service.create(
                self._project_id,
                title.strip(),
                unit_type="other",
            )
            self._refresh_list()
            self._select_unit_by_id(unit.id)
        except ServiceError as e:
            Dialogs.error("创建失败", str(e))

    def _on_create_composite(self):
        """创建复合单元."""
        if not self._project_id:
            Dialogs.info("提示", "请先创建或打开项目")
            return

        title, ok = QInputDialog.getText(self, "创建复合单元", "复合单元标题（如：宗门大比）：")
        if not ok or not title.strip():
            return

        try:
            unit = story_unit_service.create_composite(
                self._project_id,
                title.strip(),
            )
            self._refresh_list()
            self._select_unit_by_id(unit.id)
        except ServiceError as e:
            Dialogs.error("创建失败", str(e))

    def _on_delete_unit(self):
        """删除单元 - 三选一弹窗。"""
        if not self._current_unit_id:
            return

        dlg = DeleteUnitDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        option = dlg.get_option()
        if option == DeleteUnitDialog.CANCEL:
            return

        try:
            story_unit_service.delete(self._current_unit_id, option=option)
            self._refresh_list()
            self._clear_details()
            Dialogs.info("删除成功", "单元已删除")
        except ServiceError as e:
            Dialogs.error("删除失败", str(e))

    def _on_move_up(self):
        """上移单元。"""
        if not self._current_unit_id or not self._project_id:
            return

        units = self._units
        current_idx = None
        for i, u in enumerate(units):
            if u.id == self._current_unit_id:
                current_idx = i
                break

        if current_idx is None or current_idx == 0:
            return

        new_idx = current_idx - 1
        try:
            story_unit_service.move_unit(
                self._project_id, self._current_unit_id, new_idx,
                order_type="story"
            )
            self._refresh_list()
            self._select_unit_by_id(self._current_unit_id)
        except ServiceError as e:
            Dialogs.error("移动失败", str(e))

    def _on_move_down(self):
        """下移单元。"""
        if not self._current_unit_id or not self._project_id:
            return

        units = self._units
        current_idx = None
        for i, u in enumerate(units):
            if u.id == self._current_unit_id:
                current_idx = i
                break

        if current_idx is None or current_idx >= len(units) - 1:
            return

        new_idx = current_idx + 1
        try:
            story_unit_service.move_unit(
                self._project_id, self._current_unit_id, new_idx,
                order_type="story"
            )
            self._refresh_list()
            self._select_unit_by_id(self._current_unit_id)
        except ServiceError as e:
            Dialogs.error("移动失败", str(e))

    def _on_save_draft(self):
        """保存草稿。"""
        if not self._current_unit_id:
            return

        # v4.3: 保存前展示 diff 预览 (patch_preview 接入)
        new_draft = self.ed_draft.toPlainText()
        old_draft = getattr(self, "_original_draft", "")
        if old_draft and new_draft != old_draft:
            from PySide6.QtWidgets import QDialog
            from app.ui.widgets.patch_diff_dialog import PatchDiffDialog
            dlg = PatchDiffDialog(old_draft, new_draft, parent=self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return

        title = self.ed_title.text().strip()
        if not title:
            Dialogs.warning("提示", "请先填写单元标题")
            return

        try:
            story_unit_service.update(
                self._current_unit_id,
                title=title,
                unit_type=self.cmb_type.currentData(),
                status=self.cmb_status.currentData(),
                story_order=self.sp_order.value(),
                target_chars=self.sp_target_chars.value(),
                synopsis=self.ed_synopsis.toPlainText(),
                draft=self.ed_draft.toPlainText(),
                transition_type=self.cmb_transition.currentData(),
                transition_text=self.ed_transition_text.text().strip(),
            )

            # 保存因果与伏笔 (brief)
            plant_lines = [l.strip() for l in self.ed_hooks_plant.toPlainText().splitlines() if l.strip()]
            pay_lines = [l.strip() for l in self.ed_hooks_pay.toPlainText().splitlines() if l.strip()]
            core_lines = [l.strip() for l in self.ed_core_events.toPlainText().splitlines() if l.strip()]
            story_unit_service.update_brief(
                self._current_unit_id,
                cause_summary=self.ed_cause.toPlainText(),
                effect_summary=self.ed_effect.toPlainText(),
                core_events=json.dumps(core_lines, ensure_ascii=False),
                emotion_arc=self.ed_emotion_arc.toPlainText(),
                hooks_planned_plant=json.dumps(plant_lines, ensure_ascii=False),
                hooks_planned_pay=json.dumps(pay_lines, ensure_ascii=False),
            )

            self._refresh_list()
            self._select_unit_by_id(self._current_unit_id)
            Dialogs.info("保存成功", "单元已保存")
        except ServiceError as e:
            Dialogs.error("保存失败", str(e))

    def _on_rollback_snapshot(self):
        """回滚到选中的快照。"""
        if not self._current_unit_id:
            return

        item = self.snapshot_list.currentItem()
        if not item:
            Dialogs.warning("提示", "请先选择一个快照")
            return

        snap_id = item.data(Qt.ItemDataRole.UserRole)
        if not snap_id:
            return

        reply = QMessageBox.question(
            self, "确认回滚",
            "回滚后，该快照之后的所有写作内容、自动生成的记忆和钩子都将被删除。\n"
            "（手动锁定的记忆和钩子会保留）\n\n"
            "确定要回滚吗？此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            unit_writing_service.rollback_to_snapshot(self._current_unit_id, snap_id)
            self._load_unit_details(self._current_unit_id)
            Dialogs.info("回滚成功", "已回滚到选中的快照")
        except ServiceError as e:
            Dialogs.error("回滚失败", str(e))

    # ── 拆章 ──

    # ── 拆章功能已废弃: 多单元拼接断章移至发布模块「成稿向导」(AssemblyWizard) ──

    # (拆章逻辑结束；多单元拼接断章见 app/ui/widgets/assembly_wizard.py)
