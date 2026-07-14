"""
Page widget 集合 (v4.0 全面对齐 mockup).

设计参考 docs/novel-writer-ui-mockup.html (2026-06-10 批准).

V4.0-P4-新: 二级 tab 全部展平到一级.
  旧版: 小说设定 页面里 3 个 sub-tab (小说设定/潜文本卡/改稿信号) +
         设置 页面里 8 个 sub-tab (外观/模型/存储/备份/日志/授权/AI 路由/关于)
  新版: 子 tab 提升为 sidebar 一级菜单, 各自独立 page.

页面顺序 (当前):
  0. dashboard         仪表盘
  1. projects          项目管理
  2. novel-settings    小说设定 (项目基础信息)
  3. edit-signals      自动进化
  4. outline-mgmt      大纲管理
  5. generate          章节生成
  6. world-graph       世界图谱
  7. usage-analytics   用量分析
  8. knowledge         知识库
  9. plugins           插件管理
 10. logs              日志查看
 11. appearance        外观
 12. model             模型配置
 13. storage-backup    存储备份
 14. license           授权
 15. about             关于

公共 API:
  - _PAGE_TUPLES    list[tuple]: 唯一事实源 (page_id, title, class, module, nav_group, nav_order)
  - PAGE_BY_ID      dict: page_id -> class (供实例化)
  - NAV_GROUPS      dict: nav_group -> [(page_id, title)] (供 tree_nav)
  - MODULE_PAGES    dict: module -> [page_id] (替代旧 MODULE_PAGE_MAP)
  - get_page_title(page_id) -> str (供 topbar 显示)
"""
from __future__ import annotations
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Type, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGridLayout, QScrollArea, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QSplitter,
    QPlainTextEdit, QTextBrowser, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QComboBox, QLineEdit, QFileDialog,
    QSizePolicy, QCheckBox, QDialog, QAbstractItemView,
    QFormLayout,  # KnowledgePage 编辑器 (字段撑满)
)

from app.ui.tabs.dashboard_tab import DashboardTab
from app.ui.tabs.settings_tab import (
    SettingsTab,
    ProjectSettingsWidget,  # 小说设定 (项目基础信息)
    EditSignalsWidget,      # 自动进化
    AppearanceTab,          # 外观
    ModelSettingsWidget,    # 模型配置
    StorageBackupTab,       # 存储备份
)
from app.ui.tabs.editor_tab import EditorTab  # 保留导入 (GenerateTab 已合并其功能)
from app.ui.tabs.generate_tab import GenerateTab  # 章节生成
from app.ui.tabs.story_unit_tab import StoryUnitTab  # 故事单元
from app.ui.tabs.unit_pool_tab import UnitPoolTab  # 单元池 (M5)
from app.ui.tabs.volume_tab import VolumeTab  # 卷管理
from app.ui.tabs.writing_wizard_tab import WritingWizard  # 写作流程向导
from app.ui.tabs.outline_tab import OutlineTab  # 大纲管理
from app.ui.tabs.worldview_tab import WorldviewTab  # 世界观
from app.ui.tabs.character_mgmt_tab import CharacterMgmtTab  # 角色管理
from app.ui.tabs.subtext_tab import SubtextTab  # 潜文本卡
from app.ui.tabs.publish_tab import PublishTab  # 发布总览（章节树+编辑+情绪曲线+断章）
from app.ui.widgets import Dialogs, LicenseWidget  # 授权
from app.ui.widgets._number_input import NumberInput  # 替代 QSpinBox
from app.ui.tabs.settings_tab import AboutWidget  # 关于
from app.ui.theme import (
    text_muted, text_subtle, text_warn, text_secondary, text_primary,
    text_indigo, text_indigo_strong, surface_bg, deep_bg, border_color,
    border_strong, hover_bg, pressed_bg, list_header_bg, accent_tint_bg,
    accent_tint_border,
)  # 主题颜色

log = logging.getLogger(__name__)


# ===================================================================== #
# 通用样式辅助
# ===================================================================== #

def _stat_card(parent: QWidget, label: str, value: str,
               accent: str = "#6c7ae0") -> QFrame:
    """3 stat 数字卡 (与 mockup 一致)."""
    card = QFrame(parent)
    card.setObjectName("card")
    v = QVBoxLayout(card)
    v.setContentsMargins(14, 12, 14, 12)
    v.setSpacing(4)
    lbl = QLabel(label)
    lbl.setObjectName("statLabel")
    val = QLabel(value)
    val.setObjectName("statValue")
    val.setStyleSheet(f"color: {accent};")
    v.addWidget(lbl)
    v.addWidget(val)
    return card


def _section_header(title: str, parent: QWidget | None = None) -> QLabel:
    h = QLabel(title, parent)
    h.setStyleSheet("font-size: 14px; font-weight: 600; padding: 4px 0;")
    return h


def _sub_header(title: str, parent: QWidget | None = None) -> QLabel:
    h = QLabel(title, parent)
    h.setStyleSheet(f"font-size: 12px; font-weight: 600; padding: 2px 0; color: {text_muted()};")
    return h


# ===================================================================== #
# 通用列表工具
# ===================================================================== #

def _select_list_item_by_role(
    list_widget: QListWidget,
    role: Qt.ItemDataRole,
    value: str,
    *,
    block_signals: bool = False,
) -> bool:
    """在 list_widget 中找到 role=value 的项并选中。

    返回 True if found, False otherwise.
    """
    for i in range(list_widget.count()):
        if list_widget.item(i).data(role) == value:
            if block_signals:
                list_widget.blockSignals(True)
            list_widget.setCurrentRow(i)
            if block_signals:
                list_widget.blockSignals(False)
            return True
    return False


# ===================================================================== #
# 0. DashboardPage  (复用 DashboardTab)
# ===================================================================== #

class DashboardPage(QWidget):
    PAGE_ID = "dashboard"
    PAGE_TITLE = "仪表盘"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = DashboardTab()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


# ===================================================================== #
# 1. ProjectsPage  (Phase 2.2: 项目卡片网格)
# ===================================================================== #

class ProjectsPage(QWidget):
    """项目管理: 主从视图 — 左侧项目列表 + 右侧详情面板.

    V4.0-P3-重做:
      - 之前 3 列卡片网格, 删除/导出按钮藏在卡片角落, 用户找不到.
      - 现在 经典主从布局: 左边 QListWidget (项目列表), 右边详情面板
        (项目元信息 + 分卷/章节/字数 统计 + 切换/导出/删除 3 个动作按钮).
      - 点了左列表项 → 右侧详情立刻更新, 「切换/导出/删除」3 个按钮
        自动根据是否已选为当前项目 启用/禁用.
    """
    PAGE_ID = "projects"
    PAGE_TITLE = "项目管理"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_project: Optional[dict] = None
        self._projects: list[dict] = []  # 全量列表 (供左边 list widget 用)
        self._build_ui()
        self.reload()
        # V4.0-P4-新: 订阅 project_event_bus, 任何地方改了 project 都能同步刷新
        # 这里 subscribe / unsubscribe 在 widget 生命周期内一一对应; __init__ 里
        # subscribe 一次, 当 widget 被销毁时 (QObject.destroyed 信号) 取消订阅.
        from app.services import project_event_bus
        self._event_handler = project_event_bus.subscribe(self._on_project_event)
        # destroyed 信号 → 取消订阅, 防止野指针
        self.destroyed.connect(lambda *_: project_event_bus.unsubscribe(self._event_handler))

    def _on_project_event(self, event: str, pid: str, project: Optional[dict]) -> None:
        """V4.0-P4-新: 任何项目变更后被调用 → 刷新左 list + 右详情.

        事件:
          - project.created  → 重新加载全量列表, 自动选中新项目
          - project.updated  → 重新加载全量列表, 如果是当前项目/详情选中项目, 重新渲染
          - project.deleted  → 重新加载, 如果删的是当前项目, 清空 current_project
        """
        try:
            self.reload()
            # 选中新/被改的项目, 保持详情面板聚焦
            _select_list_item_by_role(self.list_widget, Qt.ItemDataRole.UserRole, pid)
            if event == "project.deleted" and self.current_project and \
                    self.current_project.get("id") == pid:
                self.current_project = None
        except Exception as e:
            log.debug("ProjectsPage._on_project_event failed: %s", e)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 12)
        outer.setSpacing(12)

        # ===== 顶部 header: 标题 =====
        header = QHBoxLayout()
        title = QLabel("📚 项目管理  ·  我的项目")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        outer.addLayout(header)

        # ===== 中部主从视图: 左边列表 + 右边详情 =====
        body = QHBoxLayout()
        body.setSpacing(12)

        # ---- 左侧: 项目列表 ----
        left = QFrame()
        left.setObjectName("projListFrame")
        left.setMinimumWidth(200)
        left.setMaximumWidth(280)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # 列表头 (N 个项目)
        self.lbl_list_header = QLabel("项目列表 (0)")
        self.lbl_list_header.setObjectName("projListHeader")
        self.lbl_list_header.setStyleSheet(
            f"color: {text_secondary()}; font-size: 11px; font-weight: 600; "
            f"padding: 8px 12px; background: {list_header_bg()}; "
            f"border-bottom: 1px solid {border_color()};"
        )
        left_layout.addWidget(self.lbl_list_header)

        # 列表本体
        self.list_widget = QListWidget()
        self.list_widget.setObjectName("projList")
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.currentRowChanged.connect(self._on_list_selection_changed)
        left_layout.addWidget(self.list_widget, 1)

        body.addWidget(left, 1)

        # ---- 右侧: 详情面板 (可直接编辑) ----
        self.detail_panel = QFrame()
        self.detail_panel.setObjectName("detailPanel")
        self.detail_panel.setMinimumWidth(420)
        detail_layout = QVBoxLayout(self.detail_panel)
        detail_layout.setContentsMargins(20, 16, 20, 16)
        detail_layout.setSpacing(10)

        # 详情头 (项目名)
        self.lbl_detail_name = QLabel("📖  请在左侧选择项目")
        self.lbl_detail_name.setObjectName("detailName")
        self.lbl_detail_name.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.lbl_detail_name.setWordWrap(True)
        detail_layout.addWidget(self.lbl_detail_name)

        # 当前项目状态条
        self.lbl_current_state = QLabel("当前: — (未选择)")
        self.lbl_current_state.setObjectName("currentStateLabel")
        self.lbl_current_state.setStyleSheet(
            f"color: {text_muted()}; font-size: 12px; padding: 4px 10px; "
            f"background: {accent_tint_bg(0.04)}; border-radius: 4px;"
        )
        detail_layout.addWidget(self.lbl_current_state)

        # 分隔
        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setObjectName("detailDivider")
        detail_layout.addWidget(line1)

        # ---- 可编辑表单 ----
        form = QFormLayout()
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        def _mk_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(f"color: {text_muted()}; font-size: 12px;")
            return lbl

        from app.core.genre_presets import list_genre_names, list_platforms, list_subgenre_names

        def _mk_line(placeholder: str = "") -> QLineEdit:
            ed = QLineEdit()
            ed.setPlaceholderText(placeholder)
            return ed

        self.ed_name      = _mk_line("项目名称")
        self.ed_book      = _mk_line("书名（可与项目名不同）")
        self.ed_author    = _mk_line("作者笔名")

        self.cmb_genre = QComboBox()
        self.cmb_genre.setEditable(True)
        self.cmb_genre.addItem("")
        for g in list_genre_names():
            self.cmb_genre.addItem(g)

        self.cmb_platform = QComboBox()
        self.cmb_platform.setEditable(True)
        self.cmb_platform.addItem("")
        for p in list_platforms():
            self.cmb_platform.addItem(p)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(6)
        self.lbl_sub_genres = QLabel("（未选）")
        self.lbl_sub_genres.setStyleSheet(f"color: {text_subtle()}; font-size: 12px;")
        self.lbl_sub_genres.setWordWrap(True)
        sub_row.addWidget(self.lbl_sub_genres, 1)
        self.btn_pick_sub = QPushButton("🏷️ 选择…")
        self.btn_pick_sub.setObjectName("btnSm")
        self.btn_pick_sub.clicked.connect(self._on_pick_sub_genres)
        sub_row.addWidget(self.btn_pick_sub)
        self._sub_genres: list[str] = []

        self.spn_volumes  = NumberInput(lo=1, hi=999, default=1)
        self.spn_chap_per_vol = NumberInput(lo=1, hi=9999, default=20)
        self.spn_wpc = NumberInput(lo=100, hi=100000, default=2500, suffix=" 字/章")

        form.addRow(_mk_label("📖 项目名"), self.ed_name)
        form.addRow(_mk_label("📚 书名"),   self.ed_book)
        form.addRow(_mk_label("✍️ 作者"),   self.ed_author)
        form.addRow(_mk_label("🎭 主题材"), self.cmb_genre)
        form.addRow(_mk_label("✨ 副题材"), sub_row)
        form.addRow(_mk_label("📡 平台"),   self.cmb_platform)
        form.addRow(_mk_label("📚 分卷数"), self.spn_volumes)
        form.addRow(_mk_label("📃 章节数/卷"), self.spn_chap_per_vol)
        form.addRow(_mk_label("✍️ 章节字数"), self.spn_wpc)
        detail_layout.addLayout(form)

        # 统计条 (只读)
        self.stats_frame = QFrame()
        self.stats_frame.setObjectName("detailStatsFrame")
        self.stats_frame.setStyleSheet(
            "QFrame#detailStatsFrame {"
            f"  background: {accent_tint_bg(0.08)};"
            f"  border: 1px solid {accent_tint_border(0.25)};"
            "  border-radius: 6px;"
            "  padding: 10px;"
            "}"
            f"QLabel#detailStatsLabel {{ color: {text_muted()}; font-size: 11px; }}"
            f"QLabel#detailStatsValue {{ color: {text_indigo()}; font-size: 15px; font-weight: 700; }}"
        )
        stats_grid = QGridLayout(self.stats_frame)
        stats_grid.setContentsMargins(0, 0, 0, 0)
        stats_grid.setHorizontalSpacing(20)
        lbl_tc = QLabel("📖 总章节数")
        lbl_tc.setObjectName("detailStatsLabel")
        self.lbl_detail_total_chap = QLabel("—")
        self.lbl_detail_total_chap.setObjectName("detailStatsValue")
        lbl_tw = QLabel("📊 总字数")
        lbl_tw.setObjectName("detailStatsLabel")
        self.lbl_detail_total_words = QLabel("—")
        self.lbl_detail_total_words.setObjectName("detailStatsValue")
        stats_grid.addWidget(lbl_tc, 0, 0)
        stats_grid.addWidget(self.lbl_detail_total_chap, 1, 0)
        stats_grid.addWidget(lbl_tw, 0, 1)
        stats_grid.addWidget(self.lbl_detail_total_words, 1, 1)
        detail_layout.addWidget(self.stats_frame)

        detail_layout.addStretch(1)

        body.addWidget(self.detail_panel, 2)
        outer.addLayout(body, 1)

        # ===== 底部全局操作按钮行 =====
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_chat = QPushButton("💬 对话创建")
        self.btn_chat.setObjectName("btnPrimary")
        self.btn_chat.setToolTip("通过 AI 对话从灵感梳理出完整设定并创建项目")
        self.btn_chat.clicked.connect(self._on_chat_create)
        btn_row.addWidget(self.btn_chat)

        self.btn_new = QPushButton("➕ 新建项目")
        self.btn_new.setObjectName("btnPrimary")
        self.btn_new.setToolTip("新建一个小说项目")
        self.btn_new.clicked.connect(self._on_new)
        btn_row.addWidget(self.btn_new)

        self.btn_import = QPushButton("📥 导入")
        self.btn_import.setToolTip("从 *.novel.zip / *.nwp.json 文件恢复项目")
        self.btn_import.clicked.connect(self._on_import)
        btn_row.addWidget(self.btn_import)

        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_refresh.setToolTip("重新从数据库加载项目列表")
        self.btn_refresh.clicked.connect(self.reload)
        btn_row.addWidget(self.btn_refresh)

        btn_row.addStretch(1)

        self.btn_switch = QPushButton("⭐ 激活")
        self.btn_switch.setObjectName("btnPrimary")
        self.btn_switch.setToolTip("把选中项目设为当前项目（进入写作/设定/章节等页面都用它的数据）")
        self.btn_switch.clicked.connect(self._on_switch_btn_clicked)
        self.btn_switch.setEnabled(False)
        btn_row.addWidget(self.btn_switch)

        self.btn_save = QPushButton("💾 保存")
        self.btn_save.setObjectName("btnPrimary")
        self.btn_save.setToolTip("保存右侧面板中对项目信息的修改")
        self.btn_save.clicked.connect(self._on_save_inline)
        self.btn_save.setEnabled(False)
        btn_row.addWidget(self.btn_save)

        self.btn_export = QPushButton("📤 导出")
        self.btn_export.setToolTip("把项目数据打包为 *.novel.zip 压缩包")
        self.btn_export.clicked.connect(self._on_export)
        self.btn_export.setEnabled(False)
        btn_row.addWidget(self.btn_export)

        self.btn_delete = QPushButton("🗑 删除")
        self.btn_delete.setObjectName("btnDanger")
        self.btn_delete.setToolTip("删除项目及全部数据（不可恢复）")
        self.btn_delete.clicked.connect(self._on_delete_current)
        self.btn_delete.setEnabled(False)
        btn_row.addWidget(self.btn_delete)

        outer.addLayout(btn_row)

        # 初始详情: 无选中
        self._render_detail_empty()

    def _kv(self, key_text: str, default_value: str) -> tuple[QLabel, QLabel]:
        """构造一对 (label, value) QLabel, 给 QFormLayout 用."""
        k = QLabel(key_text)
        k.setObjectName("detailKey")
        k.setStyleSheet(f"color: {text_muted()}; font-size: 12px;")
        v = QLabel(default_value)
        v.setObjectName("detailValue")
        v.setStyleSheet(f"color: {text_secondary()}; font-size: 12px; font-weight: 500;")
        v.setWordWrap(True)
        return (k, v)

    # ------------------------------------------------------------------
    # Data load
    # ------------------------------------------------------------------
    def reload(self) -> None:
        from app.services import project_service, ServiceError
        try:
            data = project_service.list_all()
            self._projects = data.get("projects", [])
        except ServiceError as e:
            log.error(f"[ProjectsPage] list_all failed: {e}")
            self._projects = []

        # 重填左 list
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        if not self._projects:
            placeholder = QListWidgetItem("📭 暂无项目")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(placeholder)
        else:
            for p in self._projects:
                name = p.get("name") or "(未命名)"
                item = QListWidgetItem(f"📖  {name}")
                item.setData(Qt.ItemDataRole.UserRole, p.get("id"))
                self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)

        # 列表头
        self.lbl_list_header.setText(f"项目列表 ({len(self._projects)})")

        # 保留旧选中 (按 id 同步)
        prev_id = (
            self.current_project.get("id") if self.current_project else None
        )
        if prev_id:
            _select_list_item_by_role(self.list_widget, Qt.ItemDataRole.UserRole, prev_id)
        else:
            # 默认选中第 1 个 (如果有)
            if self._projects:
                self.list_widget.setCurrentRow(0)

        self._render_current_state_label()

    def _on_list_selection_changed(self, row: int) -> None:
        if row < 0 or row >= len(self._projects):
            self._render_detail_empty()
            return
        p = self._projects[row]
        self._render_detail(p)
        self._render_current_state_label()

    # ------------------------------------------------------------------
    # Render helpers
    # ------------------------------------------------------------------
    def _render_detail_empty(self) -> None:
        self.lbl_detail_name.setText("📖  请在左侧选择项目")
        self.ed_name.clear()
        self.ed_book.clear()
        self.ed_author.clear()
        self.cmb_genre.setCurrentText("")
        self.cmb_platform.setCurrentText("")
        self._sub_genres = []
        self._update_sub_genres_label()
        self.spn_volumes.setValue(1)
        self.spn_chap_per_vol.setValue(20)
        self.spn_wpc.setValue(2500)
        self.lbl_detail_total_chap.setText("—")
        self.lbl_detail_total_words.setText("—")
        self.btn_switch.setEnabled(False)
        self.btn_save.setEnabled(False)
        self.btn_export.setEnabled(False)
        self.btn_delete.setEnabled(False)
        self.btn_pick_sub.setEnabled(False)
        # 输入框只读
        for w in (self.ed_name, self.ed_book, self.ed_author):
            w.setReadOnly(True)
        self.cmb_genre.setEnabled(False)
        self.cmb_platform.setEnabled(False)
        self.spn_volumes.setEnabled(False)
        self.spn_chap_per_vol.setEnabled(False)
        self.spn_wpc.setEnabled(False)

    def _render_detail(self, project: dict) -> None:
        name = project.get("name") or "(未命名)"
        book = project.get("book_title") or ""
        self.lbl_detail_name.setText(f"📖  {name}")

        # 填充可编辑字段
        self.ed_name.setText(project.get("name") or "")
        self.ed_book.setText(project.get("book_title") or "")
        self.ed_author.setText(project.get("author") or "")
        self.cmb_genre.setCurrentText(project.get("genre") or "")
        self.cmb_platform.setCurrentText(project.get("platform") or "")

        subs = project.get("sub_genres") or []
        if isinstance(subs, str):
            from app.core.genre_presets import parse_subgenre_string
            subs = parse_subgenre_string(subs)
        self._sub_genres = list(subs) if subs else []
        self._update_sub_genres_label()

        self.spn_volumes.setValue(int(project.get("volumes") or 1))
        self.spn_chap_per_vol.setValue(int(project.get("chapters_per_volume") or 20))
        self.spn_wpc.setValue(int(project.get("words_per_chapter") or 2500))

        # 统计（只读）
        self.lbl_detail_total_chap.setText(
            f"{int(project.get('total_chapters') or 0):,}"
        )
        self.lbl_detail_total_words.setText(
            f"{int(project.get('word_target') or 0):,}"
        )

        # 启用输入框和按钮
        for w in (self.ed_name, self.ed_book, self.ed_author):
            w.setReadOnly(False)
        self.cmb_genre.setEnabled(True)
        self.cmb_platform.setEnabled(True)
        self.btn_pick_sub.setEnabled(True)
        self.spn_volumes.setEnabled(True)
        self.spn_chap_per_vol.setEnabled(True)
        self.spn_wpc.setEnabled(True)
        self.btn_switch.setEnabled(True)
        self.btn_save.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.btn_delete.setEnabled(True)

    def _render_current_state_label(self) -> None:
        if self.current_project:
            name = self.current_project.get("name") or "(未命名)"
            self.lbl_current_state.setText(f"当前: {name}")
            self.lbl_current_state.setStyleSheet(
                f"color: {text_indigo()}; font-size: 12px; font-weight: 600; "
                f"padding: 4px 10px; background: {accent_tint_bg(0.12)}; "
                f"border: 1px solid {accent_tint_border(0.35)}; border-radius: 4px;"
            )
        else:
            self.lbl_current_state.setText("当前: — (未选择)")
            self.lbl_current_state.setStyleSheet(
                f"color: {text_muted()}; font-size: 12px; padding: 4px 10px; "
                f"background: {accent_tint_bg(0.04)}; border-radius: 4px;"
            )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _on_switch_btn_clicked(self) -> None:
        # 4.0 修复: 详情面板的「🔄 切换为当前项目」按钮 — 显式设置 current_project
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self._projects):
            return
        self._on_switch(self._projects[row])

    def _get_target_project(self) -> Optional[dict]:
        """决定当前操作针对哪个项目.

        优先级:
          1) 左侧 QListWidget 选中项 (用户最后在列表里点的)
          2) self.current_project (从主窗口 / 详情面板「切换」过的)
          3) 全量列表里唯一 1 个 → 自动选
          4) 都没有 → 返回 None
        """
        # 1) 左侧 list 选中
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._projects):
            return self._projects[row]
        # 2) current_project
        if self.current_project:
            return self.current_project
        # 3) 唯一 1 个
        if len(self._projects) == 1:
            return self._projects[0]
        return None

    def _on_switch(self, project: dict) -> None:
        # 4.0 修复: 切换时同步左 list 选中 + 右侧详情 + 主窗口 current_project
        self.current_project = project
        # 同步左 list
        pid = project.get("id")
        _select_list_item_by_role(self.list_widget, Qt.ItemDataRole.UserRole, pid, block_signals=True)
        # 同步右侧详情
        self._render_detail(project)
        self._render_current_state_label()
        # 通知主窗口
        win = self.window()
        if hasattr(win, "_set_current_project"):
            win._set_current_project(project)
        Dialogs.info("已激活", f"当前项目: {project.get('name')}", parent=self)

    def _on_save_inline(self) -> None:
        """内联编辑保存: 直接从面板读取字段, 调 project_service.update."""
        from app.services import project_service, ServiceError
        project = self._get_target_project()
        if not project:
            Dialogs.info("请先选择项目", "请在左侧列表中选中要保存的项目。", parent=self)
            return
        pid = project.get("id")
        if not pid:
            Dialogs.warning("保存失败", "当前项目缺少 id", parent=self)
            return
        name = self.ed_name.text().strip()
        if not name:
            Dialogs.warning("保存失败", "项目名称不能为空", parent=self)
            return
        data = {
            "name":               name,
            "book_title":         self.ed_book.text().strip() or None,
            "author":             self.ed_author.text().strip() or None,
            "genre":              self.cmb_genre.currentText().strip() or None,
            "platform":           self.cmb_platform.currentText().strip() or None,
            "sub_genres":         list(self._sub_genres),
            "volumes":            self.spn_volumes.value(),
            "chapters_per_volume": self.spn_chap_per_vol.value(),
            "words_per_chapter":  self.spn_wpc.value(),
        }
        try:
            updated = project_service.update(pid, **data)
        except ServiceError as e:
            Dialogs.warning("保存失败", str(e), parent=self)
            return
        self.reload()
        _select_list_item_by_role(self.list_widget, Qt.ItemDataRole.UserRole, pid)
        # 如果保存的是当前激活项目, 同步主窗口
        win = self.window()
        if hasattr(win, "_set_current_project") and self.current_project and \
                self.current_project.get("id") == pid:
            win._set_current_project(updated)
        Dialogs.info("已保存", f"项目「{updated.get('name')}」信息已更新", parent=self)

    def _on_pick_sub_genres(self) -> None:
        """副题材多选弹窗."""
        from app.core.genre_presets import list_subgenre_names
        from app.ui.widgets import MultiSelectDialog
        options = [(name, name in self._sub_genres, "") for name in list_subgenre_names()]
        dlg = MultiSelectDialog("选择副题材（可多选, 0~N 个元素标签）", options, parent=self)
        if dlg.exec():
            self._sub_genres = dlg.selected_labels()
            self._update_sub_genres_label()

    def _update_sub_genres_label(self) -> None:
        """更新副题材显示标签."""
        if not self._sub_genres:
            self.lbl_sub_genres.setText("（未选）")
            self.lbl_sub_genres.setToolTip("")
            return
        if len(self._sub_genres) > 3:
            shown = "、".join(self._sub_genres[:3]) + f"… 等 {len(self._sub_genres)} 个"
        else:
            shown = "、".join(self._sub_genres)
        self.lbl_sub_genres.setText(shown)
        self.lbl_sub_genres.setToolTip("、".join(self._sub_genres))

    def _on_delete_current(self) -> None:
        # 4.0 修复: 详情面板的「🗑 删除该项目」按钮 — 优先用左 list 选中项
        project = self._get_target_project()
        if not project:
            Dialogs.info("未选择项目", "请先在左侧选择要删除的项目。", parent=self)
            return
        self._on_delete(project)

    def _on_delete(self, project: dict) -> None:
        if not Dialogs.confirm(
            "删除项目",
            f"确认删除「{project.get('name')}」?\n"
            f"该项目下的所有书、章节、世界书、记忆等数据将无法恢复。",
            parent=self,
        ):
            return
        from app.services import project_service, ServiceError
        try:
            project_service.delete(project["id"])
        except ServiceError as e:
            Dialogs.warning("删除失败", str(e), parent=self)
            return
        Dialogs.info("已删除", f"项目「{project.get('name')}」已删除", parent=self)
        # 4.0 修复: 如果删的是当前项目, 清掉 self.current_project
        if self.current_project and self.current_project.get("id") == project["id"]:
            self.current_project = None
        self.reload()
        self._render_current_state_label()
        # 4.0 修复: 通知主窗口 (老 API 兼容)
        win = self.window()
        if getattr(win, "current_project", None) and win.current_project.get("id") == project["id"]:
            win.current_project = None
            if hasattr(win, "_notify_project_changed"):
                win._notify_project_changed()

    def _on_new(self) -> None:
        # 4.0 修复: 之前调 self.parent()._on_new_project() —— 但 ProjectsPage 父是
        # QStackedWidget, 没有 _on_new_project 方法, 导致点击"新建"没反应.
        # 现在 ProjectsPage 自己直接弹 NewProjectDialog, 不依赖 parent 链.
        from PySide6.QtWidgets import QDialog
        from app.ui.widgets import NewProjectDialog
        from app.services import project_service, ServiceError

        dlg = NewProjectDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result()
        if not data:
            return
        try:
            new_proj = project_service.create(**data)
        except ServiceError as e:
            Dialogs.warning("新建项目失败", f"创建失败: {e}", parent=self)
            return
        self.reload()
        Dialogs.info("已新建", f"项目「{new_proj.get('name')}」创建成功", parent=self)
        # 切到新项目
        win = self.window()
        if hasattr(win, "_set_current_project"):
            win._set_current_project(new_proj)
        # 如果是当前项目, 同步刷新主窗口
        win = self.window()
        if hasattr(win, "_set_current_project") and self.current_project and \
                self.current_project.get("id") == pid:
            win._set_current_project(updated)

    def _on_chat_create(self) -> None:
        """V4.0-P4-新: 弹 3 步对话创建项目.

        行为:
          - 弹 ConversationWizardDialog
          - 用户走完 3 步 → dialog 自动 create project → 触发 project_event_bus
            → 我们这边 subscribe 会自动 reload + 选中新项目 + 切到详情
          - dialog 接受后, 切到新项目为 current_project
        """
        from PySide6.QtWidgets import QDialog
        from app.ui.widgets import ConversationCreationDialog
        dlg = ConversationCreationDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_pid = dlg.created_project_id
        if not new_pid:
            return
        # 切到新项目为 current
        from app.services import project_service
        try:
            new_proj = project_service.get(new_pid)
        except Exception:
            return
        win = self.window()
        if hasattr(win, "_set_current_project"):
            win._set_current_project(new_proj)
        Dialogs.info(
            "已创建",
            f"项目「{new_proj.get('name')}」已创建并设为当前项目\n"
            f"世界观、角色、大纲等设定已自动同步，可在小说设定页查看调整。",
            parent=self,
        )

    def _on_export(self) -> None:
        # 4.0 修复: 「详情面板的导出」直接用左 list 选中项, 不依赖 current_project.
        from PySide6.QtWidgets import QFileDialog
        from pathlib import Path
        from app.services import project_io, ServiceError
        from PySide6.QtCore import QThread, Signal as QSignal

        # 优先级: 1) 左 list 选中项; 2) current_project; 3) 唯一 1 个项目 → 自动选.
        project = self._get_target_project()
        if not project:
            Dialogs.info(
                "请先选择项目",
                "请在左侧项目列表中先选中要导出的项目。",
                parent=self,
            )
            return

        pid = project.get("id")
        if not pid:
            Dialogs.warning("导出失败", "当前项目缺少 id, 无法导出", parent=self)
            return

        # 默认文件名: <name>_<date>.nwp.json
        try:
            from app.app_paths import get_story_dir
            default_dir = str(get_story_dir())
        except Exception:
            default_dir = ""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出项目",
            default_dir,
            "Novel Writer Project (*.novel.zip);;Zip Files (*.zip);;All Files (*)",
        )
        if not path:
            return
        # 强制 .novel.zip 后缀
        lower = path.lower()
        if not (lower.endswith(".novel.zip") or lower.endswith(".zip")):
            path = path + ".novel.zip"
        elif lower.endswith(".zip") and not lower.endswith(".novel.zip"):
            # 用户选了 .zip 但没 .novel → 改成 .novel.zip
            path = path[:-4] + ".novel.zip"

        # 异步导出: 不阻塞 UI
        class _ExportWorker(QThread):
            done = QSignal(object)
            error = QSignal(str)

            def __init__(self, pid, path):
                super().__init__()
                self.pid = pid
                self.path = path

            def run(self):
                try:
                    result = project_io.export_project(self.pid, Path(self.path))
                    self.done.emit(result)
                except Exception as e:
                    self.error.emit(str(e))

        self._export_worker = _ExportWorker(pid, path)
        self._export_worker.done.connect(
            lambda written: Dialogs.info(
                "已导出",
                f"项目「{project.get('name')}」已导出到:\n{written}\n\n大小: {max(1, written.stat().st_size // 1024)} KB",
                parent=self,
            )
        )
        self._export_worker.error.connect(
            lambda msg: Dialogs.warning("导出失败", msg, parent=self)
        )
        self._export_worker.start()

    def _on_import(self) -> None:
        # 4.0 修复: 之前 _on_import 只是个占位提示, 现在接 project_io.import_project.
        from PySide6.QtWidgets import QFileDialog
        from pathlib import Path
        from app.services import project_io

        path, _ = QFileDialog.getOpenFileName(
            self, "导入项目", "",
            "Novel Writer Project (*.novel.zip *.zip *.nwp.json *.json);;All Files (*)",
        )
        if not path:
            return
        try:
            new_pid = project_io.import_project(Path(path))
        except FileNotFoundError:
            Dialogs.warning("导入失败", "文件不存在", parent=self)
            return
        except ValueError as e:
            Dialogs.warning("导入失败", str(e), parent=self)
            return
        except Exception as e:
            log.error(f"[ProjectsPage] import failed: {e}")
            Dialogs.warning("导入失败", f"解析文件失败: {e}", parent=self)
            return
        self.reload()
        Dialogs.info(
            "已导入",
            f"项目导入成功, 新项目 id = {new_pid[:8]}…\n（数据已重建为新项目）",
            parent=self,
        )

    def set_project(self, project) -> None:
        # 4.0 修复: MainWindow 切项目时走这里, 同步 current_project + 刷新视图
        self.current_project = project
        # 同步左 list 选中
        if project and project.get("id"):
            _select_list_item_by_role(self.list_widget, Qt.ItemDataRole.UserRole, project.get("id"), block_signals=True)
        self._render_detail(project) if project else self._render_detail_empty()
        self._render_current_state_label()

    def _update_header_state(self) -> None:
        # 4.0 修复: 根据 current_project 启用/禁用 导出/删除按钮 + 更新「当前」标签
        # (V4.0-P3 兼容保留: 主窗口切项目时仍会调这个方法)
        if not hasattr(self, "btn_export") or not hasattr(self, "btn_delete"):
            return
        if self.current_project:
            self.btn_export.setEnabled(True)
            self.btn_delete.setEnabled(True)
        else:
            self.btn_export.setEnabled(False)
            self.btn_delete.setEnabled(False)
        self._render_current_state_label()


# ===================================================================== #
# 2. NovelSettingsPage  (复用 SettingsTab)
# ===================================================================== #

class NovelSettingsPage(QWidget):
    """V4.0-P4-新: 小说设定 (项目基础信息) — 已展平为一级菜单, 直接展示 ProjectSettingsWidget."""
    PAGE_ID = "novel-settings"
    PAGE_TITLE = "小说设定"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = ProjectSettingsWidget()
        outer.addWidget(self._inner)
        # V4.0-P4-新: 订阅 project_event_bus, 当项目基础信息被其他页面改了,
        # 这里自动重 load 表单.
        from app.services import project_event_bus
        self._event_handler = project_event_bus.subscribe(self._on_project_event)
        self.destroyed.connect(lambda *_: project_event_bus.unsubscribe(self._event_handler))

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)

    def _on_project_event(self, event: str, pid: str, project: Optional[dict]) -> None:
        try:
            if not self._inner.current_project or not project:
                return
            if self._inner.current_project.get("id") != pid:
                return
            if event in ("project.updated", "project.created"):
                self._inner.set_project(project)
        except Exception as e:
            log.debug("NovelSettingsPage._on_project_event failed: %s", e)


# --------------------------------------------------------------------- #
# V4.0-P4-新: 展平后的 3 个项目级一级菜单 (替代旧 SettingsTab.SCOPE_NOVEL 的 3 sub-tab)
# --------------------------------------------------------------------- #

class SubtextPage(QWidget):
    """潜文本卡 (一级菜单). 旧版是 NovelSettings 的 sub-tab, 现在是独立 page."""
    PAGE_ID = "subtext"
    PAGE_TITLE = "潜文本卡"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = SubtextTab()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


class EditSignalsPage(QWidget):
    """自动进化 (一级菜单). 旧版是 NovelSettings 的 sub-tab, 现在是独立 page."""
    PAGE_ID = "edit-signals"
    PAGE_TITLE = "自动进化"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = EditSignalsWidget()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


# ===================================================================== #
# V4.0-P4-新: 世界观管理 (独立 tab)
# ===================================================================== #

class WorldviewPage(QWidget):
    """世界观管理 (一级菜单). 从小说设定中独立出来."""
    PAGE_ID = "worldview"
    PAGE_TITLE = "世界观"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = WorldviewTab()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


# ===================================================================== #
# V4.0-P4-新: 角色管理 (独立 tab, 卡片展示)
# ===================================================================== #

class CharacterMgmtPage(QWidget):
    """角色管理 (一级菜单). 从小说设定中独立出来, 卡片式展示."""
    PAGE_ID = "character-mgmt"
    PAGE_TITLE = "角色管理"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = CharacterMgmtTab()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)

    # ── 生命周期钩子 ──────────────────────────────────────────────
    def activate_and_refresh(self) -> None:
        if not hasattr(self, "context"):
            return
        proj = self.context.get_current_project()
        if proj and hasattr(self._inner, "set_project"):
            self._inner.set_project(proj)

    def deactivate_and_save(self) -> None:
        pass  # CharacterMgmtTab 有独立持久层


# ===================================================================== #
# 3. OutlineMgmtPage  (大纲管理 — 复用 OutlineTab)
# ===================================================================== #

class OutlineMgmtPage(QWidget):
    """大纲管理: 卷册 → 章节树状结构 + 单版本大纲编辑 + 潜文本卡 + 伏笔管理."""
    PAGE_ID = "outline-mgmt"
    PAGE_TITLE = "大纲管理"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = OutlineTab()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


# ===================================================================== #
# 卷管理 Page
# ===================================================================== #

class VolumeMgmtPage(QWidget):
    """卷管理: 分卷列表 + 卷纲编辑."""
    PAGE_ID = "volume-mgmt"
    PAGE_TITLE = "卷管理"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = VolumeTab()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


# ===================================================================== #
# 写作流程向导 Page
# ===================================================================== #

class WritingWizardPage(QWidget):
    """写作流程向导: 项目创建→大纲→第一单元."""
    PAGE_ID = "writing-wizard"
    PAGE_TITLE = "写作向导"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = WritingWizard()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        pass  # 向导不需要 set_project


# ===================================================================== #
# 4. WorldGraphPage  (Phase 2.5: SVG 关系图 + 4 stat)
# ===================================================================== #

class _WorldGraphView(QWidget):
    """增强关系图: 圆形节点 + 按类型着色/按强度变宽的边."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nodes: list[dict] = []
        self._edges: list[dict] = []  # 每项: {src_id, dst_id, relation_type, intensity, relation}
        self.setMinimumHeight(380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # kind -> 节点颜色
        self._node_colors = {
            "character": "#6c7ae0",
            "location":  "#4ec970",
            "item":      "#e8a23a",
            "faction":   "#a855f7",
            "power":     "#06b6d4",
        }
        # relation_type -> 边颜色 (与 worldbuilding.RELATION_COLORS 同步)
        self._edge_colors = {
            "emotional": "#ff6b9d",
            "benefit":   "#ffd93d",
            "hostile":   "#ff4757",
            "mentor":    "#5f7cff",
            "blood":     "#a855f7",
            "location":  "#4ec970",
            "ownership": "#e8a23a",
            "alliance":  "#00d2ff",
            "neutral":   "#9ca3af",
            "general":   "#6c7ae0",
        }

    def set_data(self, nodes: list[dict], edges: list[dict]) -> None:
        self._nodes = nodes
        self._edges = edges
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        from app.ui.theme import graph_palette
        bg_hex, edge_hex, stroke_hex, label_hex = graph_palette()
        p.fillRect(0, 0, w, h, QColor(bg_hex))
        if not self._nodes:
            p.setPen(QColor(label_hex))
            p.setFont(QFont("", 11))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无实体关系")
            return
        # 圆形布局
        n = len(self._nodes)
        cx, cy = w // 2, h // 2
        radius = min(w, h) * 0.38
        pos: dict[str, tuple[int, int]] = {}
        import math
        for i, node in enumerate(self._nodes):
            angle = 2 * math.pi * i / max(1, n)
            x = int(cx + radius * math.cos(angle))
            y = int(cy + radius * math.sin(angle))
            pos[node["id"]] = (x, y)
        # 画边 (按类型着色, 按强度变宽)
        for edge in self._edges:
            a, b = edge.get("src_id"), edge.get("dst_id")
            if a not in pos or b not in pos:
                continue
            rel_type = edge.get("relation_type", "general")
            intensity = edge.get("intensity", 5)
            color_hex = self._edge_colors.get(rel_type, edge_hex)
            # 强度 1-10 → 线宽 1-4
            line_width = max(1, min(4, int(intensity * 0.4)))
            pen = QPen(QColor(color_hex), line_width)
            # 敌对关系用虚线
            if rel_type == "hostile":
                pen.setStyle(Qt.PenStyle.DashLine)
            # 中立关系用细虚线
            elif rel_type == "neutral":
                pen.setStyle(Qt.PenStyle.DotLine)
            p.setPen(pen)
            p.drawLine(pos[a][0], pos[a][1], pos[b][0], pos[b][1])
            # 边中点标注关系描述 (仅当强度 >= 6 时显示)
            if intensity >= 6 and edge.get("relation"):
                mx = (pos[a][0] + pos[b][0]) // 2
                my = (pos[a][1] + pos[b][1]) // 2
                p.setPen(QColor(label_hex))
                p.setFont(QFont("", 7))
                rel_text = edge["relation"][:4]
                p.drawText(mx - 15, my - 4, 30, 12, Qt.AlignmentFlag.AlignCenter, rel_text)
        # 画节点
        for node in self._nodes:
            x, y = pos[node["id"]]
            color = QColor(self._node_colors.get(node.get("kind", "character"), "#6c7ae0"))
            p.setBrush(color)
            p.setPen(QPen(QColor(stroke_hex), 1))
            p.drawEllipse(x - 14, y - 14, 28, 28)
            # 名称
            p.setPen(QColor(label_hex))
            p.setFont(QFont("", 9))
            label = node.get("name", "?")[:8]
            p.drawText(x - 40, y + 22, 80, 16,
                       Qt.AlignmentFlag.AlignCenter, label)
        p.end()


class _GraphLegend(QWidget):
    """关系类型图例: 显示颜色 + 类型名."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMaximumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _e) -> None:
        from app.services.worldbuilding import RELATION_TYPES, RELATION_COLORS
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        from app.ui.theme import graph_palette
        bg_hex, _, _, label_hex = graph_palette()
        p.fillRect(0, 0, w, h, QColor(bg_hex))

        items = list(RELATION_TYPES.items())
        item_w = 70
        total_w = len(items) * item_w
        x_start = max(4, (w - total_w) // 2)
        y = h // 2

        p.setFont(QFont("", 8))
        for i, (key, label) in enumerate(items):
            x = x_start + i * item_w
            color_hex = RELATION_COLORS.get(key, "#6c7ae0")
            # 颜色方块
            p.setBrush(QColor(color_hex))
            p.setPen(QPen(QColor(color_hex), 1))
            p.drawRect(x, y - 5, 10, 10)
            # 标签
            p.setPen(QColor(label_hex))
            p.drawText(x + 14, y + 4, label)
        p.end()


class WorldGraphPage(QWidget):
    """世界图谱: 5 维统计 + 增强关系图 (按类型着色/按强度变宽)."""
    PAGE_ID = "world-graph"
    PAGE_TITLE = "世界图谱"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_project: Optional[dict] = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        # header
        header = QHBoxLayout()
        title = QLabel("🌍 世界图谱")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_refresh.clicked.connect(self.reload)
        header.addWidget(self.btn_refresh)
        outer.addLayout(header)

        # 5 stat cards (含关系数)
        stat_row = QHBoxLayout()
        stat_row.setSpacing(10)
        self.card_char = _stat_card(self, "👥 角色", "—", "#6c7ae0")
        self.card_loc = _stat_card(self, "📍 地点", "—", "#4ec970")
        self.card_item = _stat_card(self, "💎 物品", "—", "#e8a23a")
        self.card_fac = _stat_card(self, "🏛️ 势力", "—", "#a855f7")
        self.card_rel = _stat_card(self, "🔗 关系", "—", "#00d2ff")
        for c in (self.card_char, self.card_loc, self.card_item, self.card_fac, self.card_rel):
            stat_row.addWidget(c)
        outer.addLayout(stat_row)

        # 关系图
        outer.addWidget(_section_header("🕸️ 实体关系图 (按类型着色, 按强度变宽)"))
        self.graph = _WorldGraphView()
        outer.addWidget(self.graph, 1)
        # 图例
        self.legend = _GraphLegend()
        outer.addWidget(self.legend)

    def reload(self) -> None:
        if not self.current_project:
            for c in (self.card_char, self.card_loc, self.card_item, self.card_fac, self.card_rel):
                c.findChild(QLabel, "statValue").setText("—")
            self.graph.set_data([], [])
            return
        from app.services import worldbuilding
        try:
            entities = []
            for kind in ("character", "location", "item", "faction", "power"):
                entities.extend(worldbuilding.list_all(self.current_project["id"], kind))
            relations = worldbuilding.list_relations(self.current_project["id"])
        except Exception as e:
            log.warning(f"[WorldGraphPage] load failed: {e}")
            entities = []
            relations = []
        # 统计
        counts = {"character": 0, "location": 0, "item": 0, "faction": 0, "power": 0}
        for e in entities:
            k = e.get("kind", "character")
            counts[k] = counts.get(k, 0) + 1
        self.card_char.findChild(QLabel, "statValue").setText(str(counts["character"]))
        self.card_loc.findChild(QLabel, "statValue").setText(str(counts["location"]))
        self.card_item.findChild(QLabel, "statValue").setText(str(counts["item"]))
        self.card_fac.findChild(QLabel, "statValue").setText(str(counts["faction"]))
        self.card_rel.findChild(QLabel, "statValue").setText(str(len(relations)))
        # 节点 + 边 (带类型和强度)
        nodes = [{"id": e["id"], "name": e.get("name", "?"), "kind": e.get("kind", "character")}
                 for e in entities]
        edges = [
            {
                "src_id": r.get("src_id"),
                "dst_id": r.get("dst_id"),
                "relation_type": r.get("relation_type", "general"),
                "intensity": r.get("intensity", 5),
                "relation": r.get("relation", ""),
            }
            for r in relations
        ]
        self.graph.set_data(nodes[:30], edges)

    def set_project(self, project) -> None:
        self.current_project = project
        self.reload()


# ===================================================================== #
# 5. UsageAnalyticsPage  (Phase 2.6: 4 stat + 2 chart + table)
# ===================================================================== #

class UsageAnalyticsPage(QWidget):
    """用量分析: 4 stat + 2 折线图 + 记录表."""
    PAGE_ID = "usage-analytics"
    PAGE_TITLE = "用量分析"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_project: Optional[dict] = None
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("📊 用量分析")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_refresh.clicked.connect(self.reload)
        header.addWidget(self.btn_refresh)
        outer.addLayout(header)

        # 4 stat cards
        stat_row = QHBoxLayout()
        stat_row.setSpacing(10)
        self.card_cost = _stat_card(self, "💰 本月费用 (¥)", "0.00", "#e8a23a")
        self.card_tokens = _stat_card(self, "🔤 Tokens", "0", "#6c7ae0")
        self.card_chapters = _stat_card(self, "📚 生成章节", "0", "#4ec970")
        self.card_quality = _stat_card(self, "⭐ 平均质量", "—", "#a855f7")
        for c in (self.card_cost, self.card_tokens, self.card_chapters, self.card_quality):
            stat_row.addWidget(c)
        outer.addLayout(stat_row)

        # 2 chart 区域 (复用 dashboard 风格)
        chart_row = QHBoxLayout()
        chart_row.setSpacing(10)
        self.chart_cost = _SimpleLineChart("💰 每日费用趋势 (¥)", "#e8a23a")
        self.chart_tokens = _SimpleLineChart("🔤 每日 Tokens 趋势", "#6c7ae0")
        chart_row.addWidget(self.chart_cost)
        chart_row.addWidget(self.chart_tokens)
        outer.addLayout(chart_row)

        # table
        outer.addWidget(_section_header("📋 近期记录"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["时间", "类型", "Tokens", "费用(¥)", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        outer.addWidget(self.table, 1)

    def reload(self) -> None:
        # 尝试从 usage_analytics 读取,失败回退到本地占位
        records: list[dict] = []
        try:
            from app.services.usage_analytics import UsageAnalyticsPlugin
            plugin = UsageAnalyticsPlugin()
            if self.current_project:
                data = plugin.cost_breakdown(self.current_project["id"])
                records = [
                    {"ts": "", "type": step, "tokens": info["total_tokens"], "cost": info["cost"], "status": "✓"}
                    for step, info in data.items()
                ]
        except Exception:
            pass
        # 回退数据 (无项目或插件失败时)
        if not records and self.current_project:
            try:
                from app.services import chapter_service
                chs = chapter_service.list_chapters(self.current_project["id"])
                records = [
                    {
                        "ts": ch.get("updated_at") or ch.get("created_at", ""),
                        "type": "生成",
                        "tokens": ch.get("tokens", 0) or 0,
                        "cost": ch.get("cost", 0) or 0,
                        "status": "✓",
                    }
                    for ch in (chs or [])[:20]
                ]
            except Exception:
                pass
        # 统计
        total_cost = sum(r.get("cost", 0) for r in records)
        total_tokens = sum(r.get("tokens", 0) for r in records)
        self.card_cost.findChild(QLabel, "statValue").setText(f"{total_cost:.2f}")
        self.card_tokens.findChild(QLabel, "statValue").setText(f"{total_tokens:,}")
        self.card_chapters.findChild(QLabel, "statValue").setText(str(len(records)))
        self.card_quality.findChild(QLabel, "statValue").setText("—")
        # chart (从 records 抽取)
        cost_pts = [(i, int(r.get("cost", 0) * 100)) for i, r in enumerate(records[:30])]
        tok_pts = [(i, r.get("tokens", 0)) for i, r in enumerate(records[:30])]
        self.chart_cost.set_data(cost_pts)
        self.chart_tokens.set_data(tok_pts)
        # table
        self.table.setRowCount(len(records))
        for i, r in enumerate(records[:50]):
            self.table.setItem(i, 0, QTableWidgetItem(str(r.get("ts", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(str(r.get("type", ""))))
            self.table.setItem(i, 2, QTableWidgetItem(f"{r.get('tokens', 0):,}"))
            self.table.setItem(i, 3, QTableWidgetItem(f"{r.get('cost', 0):.4f}"))
            self.table.setItem(i, 4, QTableWidgetItem(str(r.get("status", ""))))

    def set_project(self, project) -> None:
        self.current_project = project
        self.reload()


class _SimpleLineChart(QWidget):
    """通用折线小图 (与 dashboard 一致)."""

    def __init__(self, title: str, color: str = "#6c7ae0",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.color = QColor(color)
        self.points: list[tuple[int, float]] = []
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_data(self, points: list[tuple[int, float]]) -> None:
        self.points = points
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        # 4.0 修复: 之前硬编码 #191a1b 暗色, 切到亮色主题还是黑底. 改用 chart_palette().
        from app.ui.theme import chart_palette
        bg_hex, title_hex, label_hex, grid_hex = chart_palette()
        p.fillRect(0, 0, w, h, QColor(bg_hex))
        p.setPen(QColor(title_hex))
        p.setFont(QFont("", 10, QFont.Weight.Bold))
        from PySide6.QtCore import QRect
        p.drawText(QRect(10, 6, w - 20, 18), Qt.AlignmentFlag.AlignLeft, self.title)
        if not self.points:
            p.setPen(QColor(label_hex))
            p.setFont(QFont("", 10))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无数据")
            return
        ml, mr, mt, mb = 40, 16, 32, 26
        cw, ch = w - ml - mr, h - mt - mb
        vals = [v for _, v in self.points]
        vmax = max(vals) or 1
        # y 轴
        p.setPen(QPen(QColor(grid_hex), 1))
        for f in (0, 0.5, 1):
            y = mt + int(ch * (1 - f))
            p.drawLine(ml, y, w - mr, y)
            p.setPen(QColor(label_hex))
            p.setFont(QFont("", 8))
            p.drawText(QRect(2, y - 6, ml - 4, 12),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{vmax * f:.0f}")
            p.setPen(QPen(QColor(grid_hex), 1))
        # 折线
        p.setPen(QPen(self.color, 2))
        path = []
        for i, (_, v) in enumerate(self.points):
            x = ml + int(cw * i / max(1, len(self.points) - 1))
            y = mt + ch - int(ch * v / vmax)
            path.append((x, y))
        for i in range(len(path) - 1):
            p.drawLine(path[i][0], path[i][1], path[i + 1][0], path[i + 1][1])
        p.setBrush(self.color)
        for x, y in path:
            p.drawEllipse(x - 3, y - 3, 6, 6)
        p.end()


# ===================================================================== #
# 6. KnowledgePage  (Phase 2.7: 左列表 + 右内容)
# ===================================================================== #


def _inline_html(text: str) -> str:
    """处理行内 Markdown 格式（加粗/斜体/行内代码/链接）。
    注意：不在此处做全文档 html.escape()，由调用方控制。
    """
    import html
    t = html.escape(text, quote=False)
    # 行内代码 `code`（在转义后处理）
    t = re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    # 加粗 **bold**（先于单 * 斜体处理，避免冲突）
    t = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', t)
    # 斜体 *italic*（排除已是 bold 的）
    t = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', t)
    # 链接 [text](url)
    t = re.sub(r'\[([^]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', t)
    return t


def _md_to_html(text: str, *, is_dark: bool = True) -> str:
    """Markdown → HTML（逐行解析，兼容非标准格式）。

    实际文档特点：
    - 开头有 ---tags:[...]source:[...]--- 元数据行（非标准 YAML）
    - ### 标题可能和正文连在同一行
    - 大段内容没有 \\n\\n 分隔
    - **加粗** 散布在段落中间
    """
    muted = "#888888" if is_dark else "#777777"
    border = "#444444" if is_dark else "#cccccc"
    link = "#6c7ae0"
    block_bg = "#1e1e2e" if is_dark else "#f0f4ff"

    lines = text.splitlines()
    # 预处理：把行内 ##/### 标题拆成独立行
    # 如 "绝世师尊...（批次39）## 文风分析" → ["绝世师尊...（批次39）", "## 文风分析"]
    expanded: list[str] = []
    for line in lines:
        # 找到所有 ## 或 ### 后面跟中文/字母的位置
        # 排除行首的 #（即 m.start() == 0 的）
        matches = [m for m in re.finditer(r'(#{2,6})\s+([\u4e00-\u9fffA-Za-z])', line) if m.start() > 0]
        if not matches:
            expanded.append(line)
            continue
        # 从后往前拆，避免索引偏移
        last_end = len(line)
        suffixes: list[str] = []
        for m in reversed(matches):
            hash_part = m.group(1)
            after_hash_start = m.end()  # 跳过了 # 后面的空格和第一个字符
            # 把第一个字符加回来
            suffix_text = line[m.start() + len(hash_part):last_end].strip()
            if suffix_text:
                suffixes.insert(0, f'{hash_part} {suffix_text}')
            last_end = m.start()
        prefix = line[:last_end].rstrip()
        if prefix:
            expanded.append(prefix)
        expanded.extend(suffixes)
    lines = expanded

    out: list[str] = []
    in_list = False

    def _flush_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 空行
        if not stripped:
            _flush_list()
            out.append("<br>")
            i += 1
            continue

        # 元数据行: ---tags:[...]source:[...]---
        if stripped.startswith("---") and ("tags" in stripped or "source" in stripped):
            _flush_list()
            tags_m = re.search(r'tags\s*:\s*\[([^\]]*)\]', stripped)
            src_m = re.search(r'source\s*:\s*\[([^\]]*)\]', stripped)
            parts = []
            if tags_m:
                parts.append(f"tags: {tags_m.group(1)}")
            if src_m:
                parts.append(f"source: {src_m.group(1)}")
            if not parts:
                clean = stripped.strip("-").strip()
                if clean:
                    parts.append(clean)
            meta_text = "  |  ".join(parts)
            out.append(
                f'<div style="color:{muted};font-size:11px;margin:4px 0">'
                f'{_inline_html(meta_text)}</div>'
            )
            i += 1
            continue

        # 标准 YAML frontmatter 分隔符
        if re.match(r'^---\s*$', stripped):
            _flush_list()
            i += 1
            while i < len(lines) and not re.match(r'^---\s*$', lines[i].strip()):
                i += 1
            if i < len(lines):
                i += 1
            continue

        # 分隔线: --- 或 ***
        if re.match(r'^[-]{3,}\s*$', stripped) or re.match(r'^[*]{3,}\s*$', stripped):
            _flush_list()
            out.append(f'<hr style="border:none;border-top:1px solid {border};margin:10px 0">')
            i += 1
            continue

        # 引用块: > 开头
        if stripped.startswith(">"):
            _flush_list()
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                q = lines[i].strip().lstrip(">").strip()
                quote_lines.append(q)
                i += 1
            out.append(
                f'<blockquote style="border-left:3px solid {link};'
                f'margin:6px 0;padding:6px 10px;color:{muted};'
                f'background:{block_bg}">{_inline_html(" ".join(quote_lines))}</blockquote>'
            )
            continue

        # 标题: ### xxx（可能和正文连在一起，甚至嵌在行中间）
        hm = re.match(r'^(#{1,6})\s+(.*)', stripped)
        if hm:
            _flush_list()
            lvl = min(len(hm.group(1)), 6)
            rest = hm.group(2)
            h_size = [22, 19, 16, 14, 13, 12][lvl - 1]
            out.append(
                f'<h{lvl} style="font-size:{h_size}px;font-weight:700;'
                f'margin:12px 0 6px 0">{_inline_html(rest)}</h{lvl}>'
            )
            i += 1
            continue
        # 行内 ### 标题（如 "同人 文风语料### 火影：..."，### 前后无空格但后面跟中文/字母）
        hm_inline = re.search(r'#{1,6}\s+[\u4e00-\u9fffA-Za-z]', stripped)
        if hm_inline:
            _flush_list()
            m2 = re.match(r'.*?(#{1,6})\s+(.*)', stripped)
            if m2:
                lvl = min(len(m2.group(1)), 6)
                rest = m2.group(2)
                h_size = [22, 19, 16, 14, 13, 12][lvl - 1]
                out.append(
                    f'<h{lvl} style="font-size:{h_size}px;font-weight:700;'
                    f'margin:12px 0 6px 0">{_inline_html(rest)}</h{lvl}>'
                )
                i += 1
                continue

        # 无序列表: - xxx 或 * xxx
        lm = re.match(r'^[-*]\s+(.*)', stripped)
        if lm:
            if not in_list:
                out.append('<ul style="margin:4px 0;padding-left:20px">')
                in_list = True
            out.append(f'<li style="margin:2px 0">{_inline_html(lm.group(1))}</li>')
            i += 1
            continue

        # 有序列表: 1. xxx
        om = re.match(r'^\d+[.)]\s+(.*)', stripped)
        if om:
            if not in_list:
                out.append('<ul style="margin:4px 0;padding-left:20px">')
                in_list = True
            out.append(f'<li style="margin:2px 0">{_inline_html(om.group(1))}</li>')
            i += 1
            continue

        # 普通段落
        _flush_list()
        para_lines = [stripped]
        i += 1
        while i < len(lines):
            nl = lines[i].strip()
            if not nl:
                break
            if re.match(r'^#{1,6}\s+', nl):
                break
            if re.match(r'^[-*]\s+', nl) or re.match(r'^\d+[.)]\s+', nl):
                break
            if nl.startswith(">"):
                break
            if re.match(r'^---+\s*$', nl) or re.match(r'^\*\*\*+\s*$', nl):
                break
            if nl.startswith("---") and ("tags" in nl or "source" in nl):
                break
            para_lines.append(nl)
            i += 1
        out.append(f'<p style="margin:4px 0">{_inline_html(" ".join(para_lines))}</p>')

    _flush_list()
    return "\n".join(out)


class KnowledgePage(QWidget):
    """知识库: 左侧条目 + 右侧内容.

    4.0 修复: 原 UI 用的是写死的假数据 (Phase 2.7 占位, Phase 3 该接 knowledge_plugin 但没接).
    现在调 KnowledgePlugin.list_by_dimension() 读真数据, 文风/桥段/人设/场景 4 维度都接了.
    """
    PAGE_ID = "knowledge"
    PAGE_TITLE = "知识库"

    # UI 分类 → plugin 维度 (知识库 plugin 不收录 "框架模板", 这个走 scan_category 走 builtin)
    UI_CATEGORIES = (
        ("文风语料", "style",     "文风语料 (4 维之一)"),
        ("桥段",     "plot",      "桥段 (4 维之一)"),
        ("人物人设", "character", "人物人设 (4 维之一)"),
        ("场景描写", "scene",     "场景描写 (4 维之一)"),
        ("框架模板", None,        "框架模板 (结构/英雄之旅 等)"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        # 订阅主题切换，刷新 viewer 的 DefaultStyleSheet
        try:
            from app.ui.theme import get_theme_signals
            get_theme_signals().theme_changed.connect(self._on_theme_changed)
        except Exception:
            pass

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        # 左: 类别 + 条目
        left = QFrame()
        left.setObjectName("card")
        left.setMinimumWidth(220)
        left.setMaximumWidth(280)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(10, 10, 10, 10)
        lv.setSpacing(6)
        lv.addWidget(_section_header("📚 知识库"))
        # 类别
        cat_row = QHBoxLayout()
        self.cmb_cat = QComboBox()
        for cat, _dim, _desc in self.UI_CATEGORIES:
            self.cmb_cat.addItem(cat)
        self.cmb_cat.currentIndexChanged.connect(self._reload)
        cat_row.addWidget(self.cmb_cat)
        lv.addLayout(cat_row)
        # 顶部按钮行: 新建 + 刷新 (常驻)
        top_btn_row = QHBoxLayout()
        self.btn_kb_new = QPushButton("➕ 新建")
        self.btn_kb_new.clicked.connect(self._on_new)
        self.btn_kb_refresh = QPushButton("🔄 刷新")
        self.btn_kb_refresh.clicked.connect(self._reload)
        top_btn_row.addWidget(self.btn_kb_new)
        top_btn_row.addWidget(self.btn_kb_refresh)
        lv.addLayout(top_btn_row)
        # 目录树 (3层: 来源 > 子目录 > 文档)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.itemClicked.connect(self._on_tree_select)
        lv.addWidget(self.tree, 1)

        # 右: 内容
        right = QFrame()
        right.setObjectName("card")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(14, 12, 14, 12)
        rv.setSpacing(8)
        self.lbl_title = QLabel("(未选择)")
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        rv.addWidget(self.lbl_title)
        self.lbl_meta = QLabel("")
        self.lbl_meta.setStyleSheet(f"color: {text_muted()}; font-size: 11px;")
        rv.addWidget(self.lbl_meta)
        self.viewer = QTextBrowser()
        self.viewer.setReadOnly(True)
        self.viewer.setOpenExternalLinks(False)
        self.viewer.setStyleSheet("font-size: 13px;")
        rv.addWidget(self.viewer, 1)

        # 底部按钮行: 编辑 / 删除 (仅 local 文档可见) + 保存 / 取消 (编辑模式)
        self.bottom_btn_row = QHBoxLayout()
        self.btn_kb_edit = QPushButton("✏️ 编辑")
        self.btn_kb_edit.setEnabled(False)  # 默认禁用, 选中 local 文档时启用
        self.btn_kb_edit.clicked.connect(self._on_edit)
        self.btn_kb_delete = QPushButton("🗑️ 删除")
        self.btn_kb_delete.setObjectName("btnDanger")
        self.btn_kb_delete.setEnabled(False)
        self.btn_kb_delete.clicked.connect(self._on_delete)
        self.btn_kb_save = QPushButton("💾 保存")
        self.btn_kb_save.setVisible(False)
        self.btn_kb_save.clicked.connect(self._on_save_edit)
        self.btn_kb_cancel = QPushButton("❌ 取消")
        self.btn_kb_cancel.setVisible(False)
        self.btn_kb_cancel.clicked.connect(self._on_cancel_edit)
        self.bottom_btn_row.addWidget(self.btn_kb_edit)
        self.bottom_btn_row.addWidget(self.btn_kb_delete)
        self.bottom_btn_row.addWidget(self.btn_kb_save)
        self.bottom_btn_row.addWidget(self.btn_kb_cancel)
        self.bottom_btn_row.addStretch(1)
        rv.addLayout(self.bottom_btn_row)

        # 编辑模式状态 (用 _editing 标志位 + _editing_backup 存原内容)
        self._editing = False
        self._editing_backup: str = ""
        self._editing_path: str = ""
        self._editing_name: str = ""

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter)
        self._reload()

    def _get_plugin(self):
        """拿 knowledge 服务实例. 取不到返回 None."""
        try:
            from app.services.knowledge_service import KnowledgePlugin
            return KnowledgePlugin()
        except Exception:
            return None

    def _is_dark_theme(self) -> bool:
        """判断当前是否为深色主题。"""
        try:
            from app.ui.theme import get_theme
            return get_theme().current() == "dark"
        except Exception:
            return True

    def _on_theme_changed(self, theme_name: str) -> None:
        """主题切换时刷新 viewer 样式表。"""
        self.viewer.document().setDefaultStyleSheet(self._viewer_stylesheet())

    def _rebuild_zvec_if_available(self) -> None:
        """知识文档变更后触发 zvec 索引重建 (best-effort)."""
        try:
            from app.knowledge._zvec_index import ZvecIndex
            idx = ZvecIndex()
            idx._populate_from_knowledge()
        except Exception:
            pass

    def _viewer_stylesheet(self) -> str:
        """返回 QTextBrowser 的 DefaultStyleSheet（body/h1-h6/code 等颜色由 CSS 变量驱动）。"""
        if self._is_dark_theme():
            return (
                "body { color:#e0e0e0; background-color:#0f1011; font-size:13px; }\n"
                "h1,h2,h3,h4,h5,h6 { color:#e8e8f0; font-weight:700; margin:8px 0 4px 0; }\n"
                "p { color:#d8d8e0; }\n"
                "a { color:#6c7ae0; }\n"
                "code { background:#2d2d2d; padding:1px 4px; border-radius:3px; font-size:12px; }\n"
                "pre { background:#2d2d2d; padding:8px; border-radius:4px; overflow-x:auto; }\n"
                "pre code { background:transparent; padding:0; }\n"
                "ul { color:#d0d0e0; }\n"
                "li { margin:2px 0; }\n"
                "table { color:#d0d0e0; }\n"
                "th { color:#e0e0f0; background:#1e1e2e; }\n"
                "td { color:#d0d0e0; }\n"
                "blockquote { color:#9898b8; }"
            )
        else:
            return (
                "body { color:#222222; background-color:#ffffff; font-size:13px; }\n"
                "h1,h2,h3,h4,h5,h6 { color:#1a1a2e; font-weight:700; margin:8px 0 4px 0; }\n"
                "p { color:#333333; }\n"
                "a { color:#4a5ad0; }\n"
                "code { background:#f0f0f5; padding:1px 4px; border-radius:3px; font-size:12px; }\n"
                "pre { background:#f5f5f5; padding:8px; border-radius:4px; overflow-x:auto; }\n"
                "pre code { background:transparent; padding:0; }\n"
                "ul { color:#333333; }\n"
                "li { margin:2px 0; }\n"
                "table { color:#333333; }\n"
                "th { color:#1a1a2e; background:#f0f4ff; }\n"
                "td { color:#333333; }\n"
                "blockquote { color:#666666; }"
            )

    def _reload(self) -> None:
        """按 3层目录树构建: 来源(内置/本地) > 分类 > 文档."""
        self.tree.clear()
        self.lbl_title.setText("(未选择)")
        self.lbl_meta.setText("")
        self.viewer.clear()

        cat_idx = self.cmb_cat.currentIndex() if hasattr(self, "cmb_cat") else -1
        if cat_idx < 0:
            return

        cat_label, dim, _desc = self.UI_CATEGORIES[cat_idx]

        # 快速失败: knowledge 插件未注册
        plugin = self._get_plugin()
        if plugin is None:
            root = QTreeWidgetItem(self.tree, ["(knowledge 插件未注册)"])
            root.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tree.addTopLevelItem(root)
            return

        # 收集文档: builtin + local, 按分类
        from app.knowledge import (
            KnowledgeDoc, SOURCE_BUILTIN, SOURCE_LOCAL,
            get_category_dir, get_source_dir,
        )

        def _collect_docs() -> dict[str, dict[str, list[KnowledgeDoc]]]:
            """返回 {source: {category: [docs]}}。"""
            out: dict[str, dict[str, list[KnowledgeDoc]]] = {
                SOURCE_BUILTIN: {},
                SOURCE_LOCAL: {},
            }
            for source in (SOURCE_BUILTIN, SOURCE_LOCAL):
                if dim is not None:
                    # 4 维之一: 按 dimension 查
                    try:
                        out[source] = {cat_label: list(plugin.list_by_dimension(dim, source=source))}
                    except Exception:
                        out[source] = {}
                else:
                    # 框架模板: 直接扫该分类目录
                    try:
                        docs_list = list(plugin.list_by_dimension(cat_label, source=source))
                        out[source] = {cat_label: docs_list}
                    except Exception:
                        out[source] = {}
            return out

        docs_by_src = _collect_docs()

        # 树节点: 内置文档 / 本地文档
        src_labels = {
            SOURCE_BUILTIN: "📁 内置文档",
            SOURCE_LOCAL: "📁 本地文档",
        }

        for source in (SOURCE_LOCAL, SOURCE_BUILTIN):
            src_node = QTreeWidgetItem(self.tree, [src_labels[source]])
            src_node.setFlags(Qt.ItemFlag.NoItemFlags)  # 不可选，只作分组标题
            src_node.setExpanded(True)

            categories = docs_by_src.get(source, {})
            for cat, doc_list in categories.items():
                if not doc_list:
                    continue
                cat_node = QTreeWidgetItem(src_node, [cat])
                cat_node.setFlags(Qt.ItemFlag.NoItemFlags)
                cat_node.setExpanded(True)

                for d in doc_list:
                    doc_item = QTreeWidgetItem(cat_node, [d.name])
                    doc_item.setFlags(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled)
                    doc_item.setData(0, Qt.ItemDataRole.UserRole, {
                        "path": str(d.path),
                        "source": d.source,
                        "name": d.name,
                        "category": d.category,
                        "genre": d.genre,
                    })
                    # 深色主题: local=白色, builtin=灰色
                    txt_color = "#e0e0e0" if self._is_dark_theme() else "#222222"
                    doc_item.setForeground(0, QColor(txt_color))

        # 空状态提示
        total_docs = sum(
            len(cat_docs)
            for cats in docs_by_src.values()
            for cat_docs in cats.values()
        )
        if total_docs == 0:
            root = QTreeWidgetItem(self.tree, [f"(暂无 {cat_label} 类别的文档)"])
            root.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tree.addTopLevelItem(root)

        # 自动选中第一个文档
        if self.tree.topLevelItemCount() > 0:
            first_src = self.tree.topLevelItem(0)
            if first_src and first_src.childCount() > 0:
                first_cat = first_src.child(0)
                if first_cat and first_cat.childCount() > 0:
                    self.tree.setCurrentItem(first_cat.child(0))
                    self._on_tree_select(first_cat.child(0), 0)

    def _on_tree_select(self, item: QTreeWidgetItem | None, column: int) -> None:
        """选中文档节点 → 读 .md 内容 + 启停编辑/删除按钮 (按 source)."""
        # 编辑模式下切换文档: 取消编辑先
        if self._editing:
            self._on_cancel_edit()
        if item is None:
            self.lbl_title.setText("(未选择)")
            self.lbl_meta.setText("")
            self.viewer.clear()
            self.btn_kb_edit.setEnabled(False)
            self.btn_kb_delete.setEnabled(False)
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict) or not data.get("path"):
            return
        path = data["path"]
        try:
            from app.knowledge import read_doc
            doc = read_doc(path)
            self.lbl_title.setText(doc.name)
            self.lbl_meta.setText(
                f"类别: {doc.category}  ·  类型: {doc.genre}  ·  来源: {doc.source}"
            )
            self.viewer.setHtml(_md_to_html(doc.content, is_dark=self._is_dark_theme()))
            self.viewer.document().setDefaultStyleSheet(self._viewer_stylesheet())
            # 记录当前文档路径 (编辑/删除用)
            self._editing_path = str(path)
            self._editing_name = doc.name
            # local 才能编辑/删除; builtin 禁用
            is_local = (doc.source == "local")
            self.btn_kb_edit.setEnabled(is_local)
            self.btn_kb_delete.setEnabled(is_local)
        except Exception as e:
            self.lbl_title.setText("(读取失败)")
            self.lbl_meta.setText(str(e))
            self.viewer.clear()
            self.btn_kb_edit.setEnabled(False)
            self.btn_kb_delete.setEnabled(False)

    def set_project(self, project) -> None:
        pass

    # ────────────────── CRUD: 新建 / 编辑 / 保存 / 取消 / 删除 ──────────────────

    def _on_new(self) -> None:
        """弹出新建对话框, 让用户填名字 + 内容, 导入到当前类别."""
        from app.ui.widgets import Dialogs
        cat_idx = self.cmb_cat.currentIndex()
        cat_label, dim, _desc = self.UI_CATEGORIES[cat_idx]
        dlg = _KnowledgeEditDialog(
            parent=self,
            title=f"新建: {cat_label}",
            initial_name="",
            initial_content="",
            initial_genre="通用",
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        name, genre, content = dlg.get_values()
        if not name.strip() or not content.strip():
            Dialogs.warning("新建", "名字和内容不能为空", parent=self)
            return
        # 导入到 local (用 import_text)
        try:
            from app.knowledge.importer import import_text
            result = import_text(
                content=content,
                name=name.strip(),
                category=cat_label,
                genre=genre.strip() or "通用",
                use_ai=False,           # 用户已手填 genre, 不再走 AI 推断
                overwrite=False,
            )
        except Exception as e:
            Dialogs.error("新建失败", str(e), parent=self)
            return
        if not result.success:
            Dialogs.error("新建失败", getattr(result, "error", "未知错误"), parent=self)
            return
        Dialogs.info(
            "新建成功",
            f"已保存: {result.path.name}\n"
            f"  类别: {result.suggestion.category}\n"
            f"  类型: {result.suggestion.genre}\n"
            f"  字数: {result.content_chars}",
            parent=self,
        )
        self._reload()

    def _on_edit(self) -> None:
        """进入编辑模式: viewer 解锁只读, 切换按钮."""
        if not self._editing_path or self._editing:
            return
        from app.knowledge import read_doc
        try:
            doc = read_doc(self._editing_path)
        except Exception as e:
            from app.ui.widgets import Dialogs
            Dialogs.error("读取失败", str(e), parent=self)
            return
        self._editing_backup = doc.content
        self.viewer.setReadOnly(False)
        self.viewer.setStyleSheet(
            f"font-size: 13px; line-height: 1.6; border: 2px solid {text_indigo()};"
        )
        # 切换按钮可见性
        self.btn_kb_edit.setVisible(False)
        self.btn_kb_delete.setVisible(False)
        self.btn_kb_save.setVisible(True)
        self.btn_kb_cancel.setVisible(True)
        self._editing = True
        # 禁用左侧目录树 (避免切换)
        self.tree.setEnabled(False)
        # 顶部按钮也禁用 (避免新建/刷新打断编辑)
        self.btn_kb_new.setEnabled(False)
        self.btn_kb_refresh.setEnabled(False)
        self.cmb_cat.setEnabled(False)

    def _on_save_edit(self) -> None:
        """把编辑后的内容写回 (用 import_text overwrite=True)."""
        from app.ui.widgets import Dialogs
        from app.knowledge.importer import import_text
        from pathlib import Path
        # 解析 frontmatter 拿回 genre/category
        try:
            from app.knowledge import read_doc
            orig = read_doc(self._editing_path)
            category = orig.category
            genre = orig.genre
        except Exception:
            category, genre = None, "通用"
        # 写回同名 (overwrite)
        try:
            result = import_text(
                content=self.viewer.toPlainText(),
                name=self._editing_name,
                category=category,
                genre=genre,
                use_ai=False,
                overwrite=True,
            )
        except Exception as e:
            Dialogs.error("保存失败", str(e), parent=self)
            return
        if not result.success:
            Dialogs.error("保存失败", getattr(result, "error", "未知错误"), parent=self)
            return
        # 退出编辑模式
        self._exit_edit_mode()
        # 提示并刷新
        Dialogs.info("保存成功", f"已写回: {result.path.name}\n  {result.content_chars} 字", parent=self)
        # 重新加载当前类别
        cur_idx = self.cmb_cat.currentIndex()
        self.cmb_cat.setCurrentIndex(-1)
        self.cmb_cat.setCurrentIndex(cur_idx)
        # 触发 zvec 索引重建
        self._rebuild_zvec_if_available()

    def _on_cancel_edit(self) -> None:
        """放弃编辑, 恢复原内容."""
        from app.ui.widgets import Dialogs
        if self._editing and self.viewer.toPlainText() != self._editing_backup:
            from app.ui.widgets import Dialogs
            if not Dialogs.confirm("放弃编辑", "当前修改未保存, 确定放弃吗?", parent=self):
                return
        self._exit_edit_mode()

    def _exit_edit_mode(self) -> None:
        """共用退出逻辑: 还原 viewer + 按钮 + 备份."""
        self.viewer.setReadOnly(True)
        self.viewer.setStyleSheet("font-size: 13px;")
        self.viewer.document().setDefaultStyleSheet(self._viewer_stylesheet())
        self.btn_kb_edit.setVisible(True)
        self.btn_kb_delete.setVisible(True)
        self.btn_kb_save.setVisible(False)
        self.btn_kb_cancel.setVisible(False)
        self._editing = False
        self.tree.setEnabled(True)
        self.btn_kb_new.setEnabled(True)
        self.btn_kb_refresh.setEnabled(True)
        self.cmb_cat.setEnabled(True)
        # 恢复原内容
        if self._editing_path:
            try:
                from app.knowledge import read_doc
                doc = read_doc(self._editing_path)
                self.viewer.setHtml(_md_to_html(doc.content, is_dark=self._is_dark_theme()))
                self.viewer.document().setDefaultStyleSheet(self._viewer_stylesheet())
            except Exception:
                self.viewer.setHtml(_md_to_html(self._editing_backup, is_dark=self._is_dark_theme()))
                self.viewer.document().setDefaultStyleSheet(self._viewer_stylesheet())

    def _on_delete(self) -> None:
        """删除 local 文档 (builtin 禁用此路径)."""
        from app.ui.widgets import Dialogs
        from app.knowledge.importer import delete_local_doc
        if not self._editing_path:
            return
        if not Dialogs.confirm(
            "删除",
            f"确定要删除『{self._editing_name}』吗?\n文件: {self._editing_path}\n此操作不可恢复。",
            parent=self,
        ):
            return
        try:
            ok = delete_local_doc(self._editing_path)
        except Exception as e:
            Dialogs.error("删除失败", str(e), parent=self)
            return
        if not ok:
            Dialogs.error("删除失败", "文件不存在或已被删除", parent=self)
            return
        Dialogs.info("已删除", f"已删除: {self._editing_name}", parent=self)
        # 清理状态 + 重新加载
        self._editing_path = ""
        self._editing_name = ""
        cur_idx = self.cmb_cat.currentIndex()
        self.cmb_cat.setCurrentIndex(-1)
        self.cmb_cat.setCurrentIndex(cur_idx)
        self._rebuild_zvec_if_available()


# ────────────────── 知识库编辑对话框 ──────────────────

class _KnowledgeEditDialog(QDialog):
    """新建/编辑 知识库文档的对话框.

    字段: 名字 / 类型 (genre) / 内容 (multi-line).
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "新建知识库文档",
        initial_name: str = "",
        initial_content: str = "",
        initial_genre: str = "通用",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 520)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)
        v.addWidget(_section_header("✏️ " + title))
        # 名字
        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        self.ed_name = QLineEdit(initial_name)
        self.ed_name.setPlaceholderText("例如: 仙侠·爽文节奏")
        form.addRow("名字:", self.ed_name)
        self.ed_genre = QLineEdit(initial_genre)
        self.ed_genre.setPlaceholderText("仙侠 / 都市 / 悬疑 / 通用 …")
        form.addRow("类型 (genre):", self.ed_genre)
        v.addLayout(form)
        # 内容
        v.addWidget(QLabel("内容:"))
        self.ed_content = QPlainTextEdit()
        self.ed_content.setPlainText(initial_content)
        self.ed_content.setStyleSheet("font-size: 13px; line-height: 1.6;")
        v.addWidget(self.ed_content, 1)
        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("确定")
        self.btn_ok.setDefault(True)
        self.btn_ok.clicked.connect(self._on_ok)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addWidget(self.btn_ok)
        v.addLayout(btn_row)

    def _on_ok(self) -> None:
        if not self.ed_name.text().strip() or not self.ed_content.toPlainText().strip():
            from app.ui.widgets import Dialogs
            Dialogs.warning("提示", "名字和内容不能为空", parent=self)
            return
        self.accept()

    def get_values(self) -> tuple[str, str, str]:
        return (
            self.ed_name.text().strip(),
            self.ed_genre.text().strip(),
            self.ed_content.toPlainText(),
        )


# ===================================================================== #
# 8. LogsPage  (Phase 2.9: 单色 + 4 级别过滤)
# ===================================================================== #

class LogsPage(QWidget):
    """日志查看 + 日志设置（合并）。"""
    PAGE_ID = "logs"
    PAGE_TITLE = "日志"

    _LEVELS = ["ALL", "INFO", "WARN", "ERROR"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._all_lines: list[str] = []
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)

        # ── 头部工具栏 ──
        header = QHBoxLayout()
        title = QLabel("📋 日志查看")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        # 级别过滤
        header.addWidget(QLabel("级别:"))
        self.cmb_level = QComboBox()
        self.cmb_level.addItems(self._LEVELS)
        self.cmb_level.currentIndexChanged.connect(self._apply_filter)
        header.addWidget(self.cmb_level)
        # 关键字过滤
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText("🔍 关键字过滤…")
        self.ed_filter.setMaximumWidth(240)
        self.ed_filter.textChanged.connect(self._apply_filter)
        header.addWidget(self.ed_filter)
        self.btn_refresh = QPushButton("🔄 刷新")
        self.btn_refresh.clicked.connect(self.reload)
        header.addWidget(self.btn_refresh)
        outer.addLayout(header)

        # ── 日志查看区 ──
        self.viewer = QPlainTextEdit()
        self.viewer.setReadOnly(True)
        self.viewer.setObjectName("logViewer")
        outer.addWidget(self.viewer, 1)

        # ── 日志设置区 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        outer.addWidget(sep)

        cfg_header = QHBoxLayout()
        cfg_title = QLabel("⚙️ 日志设置")
        cfg_title.setStyleSheet("font-size: 15px; font-weight: 600;")
        cfg_header.addWidget(cfg_title)
        cfg_header.addStretch(1)
        outer.addLayout(cfg_header)

        cfg_row = QHBoxLayout()
        cfg_row.addWidget(QLabel("日志级别:"))
        self.cmb_lvl = QComboBox()
        self.cmb_lvl.addItems(["DEBUG", "INFO", "WARN", "ERROR"])
        self.cmb_lvl.setCurrentIndex(1)
        self.cmb_lvl.setEnabled(False)   # 启动期固定，运行时不可改
        cfg_row.addWidget(self.cmb_lvl)
        cfg_row.addSpacing(24)
        cfg_row.addWidget(QLabel("单文件最大 MB:"))
        self.spn_logmb = NumberInput(lo=1, hi=100, default=10)
        self.spn_logmb.setEnabled(False)
        cfg_row.addWidget(self.spn_logmb)
        cfg_row.addSpacing(12)
        cfg_row.addWidget(QLabel(
            "<i>日志参数在 <code>app/main.py</code> 启动时确定，运行时不可改。"
            "如需调整请修改 <code>DEFAULT_SETTINGS</code> 里的 <code>log.*</code> key。</i>"))
        cfg_row.addStretch(1)
        outer.addLayout(cfg_row)

    def reload(self) -> None:
        self._all_lines = []
        log_dir = self._find_log_dir()
        if not log_dir or not log_dir.exists():
            self._all_lines = ["(no log directory found)"]
        else:
            files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            for f in files[:3]:
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                    self._all_lines.append(f"===== {f.name} =====")
                    self._all_lines.extend(content.splitlines()[-200:])
                except Exception as e:
                    self._all_lines.append(f"(read {f.name} failed: {e})")
        self._apply_filter()

    def _find_log_dir(self) -> Optional[Path]:
        candidates = []
        try:
            from app.app_paths import DATA_DIR
            candidates.append(Path(DATA_DIR) / "logs")
        except Exception:
            pass
        # fallback: %APPDATA%/NovelWriterPure/logs
        appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if appdata:
            candidates.append(Path(appdata) / "NovelWriterPure" / "logs")
        for c in candidates:
            if c.exists():
                return c
        return candidates[0] if candidates else None

    def _apply_filter(self) -> None:
        level = self.cmb_level.currentText() if hasattr(self, "cmb_level") else "ALL"
        kw = self.ed_filter.text().strip() if hasattr(self, "ed_filter") else ""
        out: list[str] = []
        for line in self._all_lines:
            if level != "ALL" and f"| {level}" not in line and not line.startswith("====="):
                continue
            if kw and kw.lower() not in line.lower():
                continue
            out.append(line)
        if not out:
            out = ["(无匹配日志)"]
        self.viewer.setPlainText("\n".join(out[-2000:]))

    def set_project(self, project) -> None:
        pass


# ===================================================================== #
# 9. SettingsPage  (Phase 4.0: 委托给 SettingsTab(scope="app"))
# ===================================================================== #

# --------------------------------------------------------------------- #
# V4.0-P4-新: 8 个系统级一级菜单 (替代旧 SettingsPage 内的 8 sub-tab)
# --------------------------------------------------------------------- #

def _wrap_widget_page(cls):
    """工厂: 给一个 widget 类生成一个 page 包装类, 走 set_project 转发."""
    class _Page(QWidget):
        PAGE_ID = getattr(cls, "PAGE_ID", None) or cls.__name__.lower()
        PAGE_TITLE = getattr(cls, "PAGE_TITLE", None) or cls.__name__

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            outer = QVBoxLayout(self)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)
            self._inner = cls()
            outer.addWidget(self._inner)

        def set_project(self, project) -> None:
            if hasattr(self._inner, "set_project"):
                self._inner.set_project(project)

    _Page.__name__ = cls.__name__ + "Page"
    _Page.PAGE_ID = cls.__name__.lower().replace("page", "").replace("tab", "").replace("widget", "")
    _Page.PAGE_TITLE = _Page.PAGE_ID
    return _Page


# 外观
class AppearancePage(QWidget):
    PAGE_ID = "appearance"
    PAGE_TITLE = "外观"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = AppearanceTab()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


# 模型配置
class ModelPage(QWidget):
    PAGE_ID = "model"
    PAGE_TITLE = "模型配置"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = ModelSettingsWidget()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


# 存储备份 (合并存储 + 备份)
class StorageBackupPage(QWidget):
    PAGE_ID = "storage-backup"
    PAGE_TITLE = "存储备份"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = StorageBackupTab()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


# 日志设置 (区别于「日志查看」)
# 授权
class LicensePage(QWidget):
    PAGE_ID = "license"
    PAGE_TITLE = "授权"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = LicenseWidget()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


# 关于
class AboutPage(QWidget):
    PAGE_ID = "about"
    PAGE_TITLE = "关于"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = AboutWidget()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


# ===================================================================== #
# 生成页 (V4.0-P4: 从编辑器深处提到侧边栏一级入口)
# ===================================================================== #

class GeneratePage(QWidget):
    """章节生成 — 侧边栏一级入口.

    P0 修复: GenerateTab 原本藏在「章节管理 → 编辑器 → ✨ 生成」按钮背后,
    普通用户找不到入口. 现在直接放到侧边栏, 一键进入 7 步写作流程.
    """
    PAGE_ID = "generate"
    PAGE_TITLE = "章节生成"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = GenerateTab()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)

    # ── 生命周期钩子（ProjectContext 集成）──────────────────────────
    def deactivate_and_save(self) -> None:
        """离开写作页：编辑器文本回写 Context + 落盘"""
        if not hasattr(self, "context"):
            return
        editor = getattr(self._inner, "editor", None)
        if editor is not None:
            self.context.update_field("current_content", editor.toPlainText())
            self.context.save_to_disk()

    def activate_and_refresh(self) -> None:
        """进入写作页：从 Context 恢复正文 + 刷新关联数据"""
        if not hasattr(self, "context"):
            return
        saved = self.context.data.get("current_content", "")
        editor = getattr(self._inner, "editor", None)
        if editor is not None and editor.toPlainText() != saved:
            editor.setPlainText(saved)
        # 刷新内页项目数据
        if hasattr(self._inner, "set_project"):
            proj = self.context.get_current_project()
            if proj:
                self._inner.set_project(proj)


class StoryUnitPage(QWidget):
    """故事单元 — 单元创作管理."""
    PAGE_ID = "story-unit"
    PAGE_TITLE = "故事单元"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = StoryUnitTab()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


class PublishPage(QWidget):
    """发布模块聚合页: 章节树 + 章节编辑/同步 + 情绪曲线 + 断章."""
    PAGE_ID = "publish"
    PAGE_TITLE = "发布"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = PublishTab()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)

    # ── 生命周期钩子 ──────────────────────────────────────────────
    def activate_and_refresh(self) -> None:
        if not hasattr(self, "context"):
            return
        proj = self.context.get_current_project()
        if proj and hasattr(self._inner, "set_project"):
            self._inner.set_project(proj)

    def deactivate_and_save(self) -> None:
        if not hasattr(self, "context"):
            return
        self.context.save_to_disk()


class UnitPoolPage(QWidget):
    """单元池 — 故事单元素材库 (M5)."""
    PAGE_ID = "unit-pool"
    PAGE_TITLE = "单元池"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = UnitPoolTab()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


# ===================================================================== #
# v4.0 Observe 模块页面
# ===================================================================== #

class StoryHealthPage(QWidget):
    PAGE_ID = "story-health"
    PAGE_TITLE = "故事健康"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from app.ui.observe.story_health_page import StoryHealthPage as Inner
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = Inner()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)

    # ── 生命周期钩子 ──────────────────────────────────────────────
    def activate_and_refresh(self) -> None:
        if not hasattr(self, "context"):
            return
        proj = self.context.get_current_project()
        if proj and hasattr(self._inner, "set_project"):
            self._inner.set_project(proj)

    def deactivate_and_save(self) -> None:
        pass  # 观测页只读


class DecisionHistoryPage(QWidget):
    PAGE_ID = "decision-history"
    PAGE_TITLE = "\u51b3\u7b56\u5386\u53f2"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from app.ui.observe.decision_history_page import DecisionHistoryPage as Inner
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = Inner()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


class GuideGraphPage(QWidget):
    PAGE_ID = "guide-graph"
    PAGE_TITLE = "\u5f15\u5bfc\u56fe\u8c31"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from app.ui.observe.guide_graph_page import GuideGraphPage as Inner
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = Inner()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


class ImpactReportPage(QWidget):
    PAGE_ID = "impact-report"
    PAGE_TITLE = "\u5f71\u54cd\u5206\u6790"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from app.ui.observe.impact_report_page import ImpactReportPage as Inner
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._inner = Inner()
        outer.addWidget(self._inner)

    def set_project(self, project) -> None:
        if hasattr(self._inner, "set_project"):
            self._inner.set_project(project)


# ===================================================================== #
# 注册表 — 唯一事实源 (SSOT)
# ===================================================================== #
# 每个条目: (page_id, title, class, module, nav_group, nav_order)
#   page_id    页面唯一ID
#   title      页面标题 (topbar显示)
#   class      QWidget子类
#   module     所属模块 (story/create/observe/publish)
#   nav_group  导航分组 (project/story/write/dashboard/settings/observe)
#   nav_order  在导航组内的排序

_PAGE_TUPLES: list[tuple[str, str, type, str, str, int]] = [
    # -- 📁 项目管理 --
    ("dashboard",         "综合仪表盘",   DashboardPage,         "publish", "dashboard", 0),
    ("projects",          "项目列表",     ProjectsPage,          "publish", "project",   0),
    # -- 📖 故事设定 --
    ("novel-settings",    "小说设定",     NovelSettingsPage,     "story",   "story",     0),
    ("subtext",           "潜文本卡",     SubtextPage,           "story",   "story",     1),
    ("outline-mgmt",      "大纲管理",     OutlineMgmtPage,       "story",   "story",     2),
    ("volume-mgmt",       "卷管理",       VolumeMgmtPage,        "story",   "story",     2),
    ("character-mgmt",    "角色管理",     CharacterMgmtPage,     "story",   "story",     3),
    ("worldview",         "世界观",       WorldviewPage,         "story",   "story",     4),
    # -- ✍ 开始写作 --
    ("writing-wizard",    "写作向导",     WritingWizardPage,     "create",  "write",     0),
    ("generate",          "当前创作",     GeneratePage,          "create",  "write",     1),
    ("story-unit",        "故事单元",     StoryUnitPage,         "create",  "write",     2),
    ("edit-signals",      "自动进化",     EditSignalsPage,       "create",  "write",     3),
    ("unit-pool",         "单元池",       UnitPoolPage,          "create",  "write",     4),
    ("publish",           "章节管理",     PublishPage,           "publish", "write",     5),
    # -- 🔍 观察 --
    ("story-health",      "故事健康",     StoryHealthPage,       "observe", "observe",   0),
    ("guide-graph",       "引导图谱",     GuideGraphPage,        "observe", "observe",   1),
    ("decision-history",  "决策历史",     DecisionHistoryPage,   "observe", "observe",   2),
    ("impact-report",     "影响分析",     ImpactReportPage,      "observe", "observe",   3),
    ("world-graph",       "世界图谱",     WorldGraphPage,        "observe", "observe",   4),
    ("usage-analytics",   "用量分析",     UsageAnalyticsPage,    "observe", "observe",   5),
    # -- ⚙ 设置 --
    ("knowledge",         "知识库",       KnowledgePage,         "observe", "settings",  0),
    ("model",             "AI 模型",      ModelPage,             "publish", "settings",  1),
    ("appearance",        "外观",         AppearancePage,        "publish", "settings",  2),
    ("storage-backup",    "存储备份",     StorageBackupPage,     "publish", "settings",  3),
    ("logs",              "日志",         LogsPage,              "publish", "settings",  4),
    ("license",           "授权",         LicensePage,           "publish", "settings",  5),
    ("about",             "关于",         AboutPage,             "publish", "settings",  6),
]

# --- 派生数据 (从 _PAGE_TUPLES 自动生成, 禁止手动维护) --- #

PAGE_BY_ID: dict[str, type] = {pid: cls for pid, _t, cls, *_ in _PAGE_TUPLES}

# 导航分组 (tree_nav 读取): nav_group → [(page_id, title), ...]
NAV_GROUPS: dict[str, list[tuple[str, str]]] = {}
for pid, title, _cls, _mod, group, order in _PAGE_TUPLES:
    NAV_GROUPS.setdefault(group, []).append((pid, title))

# 模块分组 (替代旧 MODULE_PAGE_MAP): module → [page_id, ...]
MODULE_PAGES: dict[str, list[str]] = {}
for pid, _t, _cls, mod, _g, _o in _PAGE_TUPLES:
    MODULE_PAGES.setdefault(mod, []).append(pid)

# 旧接口兼容
PAGE_REGISTRY = PAGE_BY_ID


def get_page_title(page_id: str) -> str:
    """根据 page_id 取标题 (供 topbar 显示)."""
    for pid, title, _cls, *_ in _PAGE_TUPLES:
        if pid == page_id:
            return title
    return page_id
