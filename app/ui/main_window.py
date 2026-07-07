"""
Main window (v4.0) - Module Navigation

布局结构:
  ┌──────────────────────────────────────────────┐
  │  Title Bar (logo + theme toggle + progress)  │  height: 36
  ├──────────┬───────────────────────────────────┤
  │  Module  │  Content Topbar (page title)      │  height: 44
  │  Nav     ├───────────────────────────────────┤
  │  (4 btn) │  Content Body (QStackedWidget)    │
  │          │                                   │
  ├──────────┴───────────────────────────────────┤
  │  Status Bar (project · model · version)      │  height: 28
  └──────────────────────────────────────────────┘

4 个一级模块:
  📖 Story   → Book / Outline / Characters / World
  ✍ Create  → Current Unit / Unit Library / Auto-Edit  (默认首页)
  👁 Observe → Story Health / World Graph / Analytics / Knowledge Base
  🚀 Publish → Chapter Preview / Export / Platform

Settings: 右上角齿轮弹窗 (Ctrl+,)

v4.0 废弃: 旧的 QTreeWidget 侧边栏 (NAV_GROUPS / _populate_nav / _on_nav_clicked)
"""
from __future__ import annotations
import logging
import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow,
    QStatusBar,
    QWidget,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QStackedWidget,
    QFrame,
    QSizePolicy,
    QProgressBar,
)

from app.services import project_service, app_setting_service, ServiceError
from app.ui.theme import get_theme, text_indigo, text_warn, text_warn_ok, text_danger, text_primary, text_secondary, text_muted, surface_bg, mock_mode_bg, mock_mode_fg
from app.ui.screen_adapter import ScreenAdapter
from app.ui.pages import (
    PAGE_REGISTRY,
    get_all_page_classes,
    get_page_title,
)
from app.ui.welcome import show_welcome_if_first_time
from app.ui.widgets import Dialogs, NewProjectDialog, ThemeToggle

log = logging.getLogger(__name__)


# v4.0: 模块→页面映射 (替代旧 NAV_GROUPS)
MODULE_PAGE_MAP = {
    "story": {
        "book": ("novel-settings", "\u5c0f\u8bf4\u8bbe\u5b9a"),
        "outline": ("outline-mgmt", "\u5927\u7eb2\u7ba1\u7406"),
        "characters": ("character-mgmt", "\u89d2\u8272\u7ba1\u7406"),
        "world": ("worldview", "\u4e16\u754c\u89c2"),
    },
    "create": {
        "current": ("generate", "\u5f53\u524d\u521b\u4f5c"),
        "unit": ("story-unit", "\u6545\u4e8b\u5355\u5143"),
        "editor": ("projects", "\u5355\u5143\u5e93"),
        "signals": ("edit-signals", "\u81ea\u52a8\u8fdb\u5316"),
    },
    "observe": {
        "health": ("story-health", "\u6545\u4e8b\u5065\u5eb7"),
        "graph": ("guide-graph", "\u5f15\u5bfc\u56fe\u8c31"),
        "analytics": ("usage-analytics", "\u7528\u91cf\u5206\u6790"),
        "knowledge": ("knowledge", "\u77e5\u8bc6\u5e93"),
    },
    "publish": {
        "overview": ("publish", "\u53d1\u5e03\u603b\u89c8"),
        "export": ("generate", "\u5bfc\u51fa"),
        "model": ("model", "AI \u6a21\u578b"),
        "appearance": ("appearance", "\u5916\u89c2"),
        "logs": ("logs", "\u65e5\u5fd7"),
    },
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        from app.core.version import VERSION
        self.setWindowTitle(f"小说写作助手 v{VERSION}")
        self.resize(1440, 900)

        self.current_project: Optional[dict] = None
        self.projects: list[dict] = []
        self._pages: dict[str, QWidget] = {}  # page_id -> widget

        # 10 page 实例化
        for page_id, cls in PAGE_REGISTRY.items():
            self._pages[page_id] = cls()

        self._build_ui()
        self._build_shortcuts()
        self._build_statusbar()
        self._wire_signals()

        # 应用暗色主题 (默认)
        theme = get_theme()
        theme.changed.connect(self._on_theme_changed)
        if not self._app_has_stylesheet():
            theme.apply(self._qapp(), "dark")

        # 默认显示 Create 模块的 Current Unit
        self._select_page("generate")

        self._update_action_states()
        log.info("MainWindow initialised (v4.0, 10-page mockup-aligned)")

        # 屏幕适配
        self.screen_adapter = ScreenAdapter.instance()
        self.screen_adapter.attach(self)
        try:
            qapp = self._qapp()
            qapp.screenAdded.connect(lambda _s: self.screen_adapter.compute_and_apply())
            qapp.screenRemoved.connect(lambda _s: self.screen_adapter.compute_and_apply())
        except Exception:
            pass

        # 欢迎页
        QTimer.singleShot(50, self._show_welcome_once)
        # 延迟加载项目
        QTimer.singleShot(0, self._reload_projects)

    # ------------------------------------------------------------------
    # Welcome
    # ------------------------------------------------------------------
    def _show_welcome_once(self) -> None:
        try:
            dlg = show_welcome_if_first_time(self)
            if dlg is not None and getattr(dlg, "accept_create", False):
                self._on_new_project()
        except Exception as e:
            log.warning("欢迎页弹出失败: %s", e)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1. Title Bar
        root.addWidget(self._build_titlebar())

        # 2. Body (sidebar + content)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_content())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 1200])
        root.addWidget(splitter, 1)

    def _build_titlebar(self) -> QWidget:
        """Title Bar: logo + theme toggle + 项目进度 (完成章节/总章节).

        height: 36px (与 mockup .titlebar 高度一致).
        旧的 3 dots 装饰已移除: 实际是 mockup 风格的"窗口控制"装饰, 无功能.
        改为有意义的"项目进度指示器", 显示当前项目的写作进度.
        """
        tb = QWidget()
        tb.setObjectName("titleBar")
        tb.setFixedHeight(36)
        lay = QHBoxLayout(tb)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        # Logo: "Novel Writer" + 蓝色 "Pure v{VERSION}"
        logo_main = QLabel("Novel Writer")
        logo_main.setObjectName("titleBarLogo")
        lay.addWidget(logo_main)
        from app.core.version import VERSION as _LOGO_VER
        logo_acc = QLabel(f"Pure v{_LOGO_VER}")
        logo_acc.setObjectName("titleBarLogoAccent")
        lay.addWidget(logo_acc)

        lay.addStretch(1)

        # Theme toggle (复用现有 widget)
        self.theme_toggle = ThemeToggle()
        self.theme_toggle.setObjectName("themeToggle")
        self.theme_toggle.setToolTip("切换暗/亮主题  (Ctrl+T)")
        lay.addWidget(self.theme_toggle)

        # 项目进度 (完成章节/总章节) - 替代旧 3 dots 装饰
        self.progress_widget = self._build_project_progress()
        lay.addWidget(self.progress_widget)
        return tb

    def _build_project_progress(self) -> QWidget:
        """项目进度 widget: 📊 12/30 章 + 进度条.

        进度条:
        - 范围 0 ~ total_chapters
        - total = word_target / 2500 (网文平均 2500 字/章) - 仅参考, 实际目标用户可在小说设定调整
        - done = 累加 book→chapter 中 word_count>=500 的章节数
        - 无项目时显示 —/—
        """
        w = QWidget()
        w.setObjectName("titleBarProgress")
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        icon = QLabel("📊")
        icon.setObjectName("titleBarProgressIcon")
        h.addWidget(icon)
        self.lbl_progress_text = QLabel("—/—")
        self.lbl_progress_text.setObjectName("titleBarProgressText")
        self.lbl_progress_text.setToolTip("完成章节 / 估算总章节\n(总章节 = 目标字数 ÷ 2500)")
        h.addWidget(self.lbl_progress_text)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("titleBarProgressBar")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedWidth(80)
        self.progress_bar.setFixedHeight(8)
        h.addWidget(self.progress_bar)
        return w

    def _build_sidebar(self) -> QWidget:
        """v4.0: ModuleNav + 齿轮按钮."""
        wrap = QWidget()
        wrap.setObjectName("sidebar")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        from app.ui.widgets.module_nav import ModuleNav
        self.module_nav = ModuleNav()
        self.module_nav.module_selected.connect(self._on_module_selected)
        self.module_nav.sub_page_selected.connect(self._on_sub_page_selected)
        lay.addWidget(self.module_nav, 1)

        from app.core.version import VERSION
        footer = QWidget()
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(12, 6, 12, 8)
        fl.setSpacing(6)
        gear_btn = QPushButton("⚙")
        gear_btn.setObjectName("gearBtn")
        gear_btn.setFixedSize(28, 28)
        gear_btn.setToolTip("Settings (Ctrl+,)")
        gear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # v4.0 patch: 移除硬编码暗色 QSS, 走全局主题 QSS (#gearBtn).
        # 确保事件不被吞.
        gear_btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        gear_btn.clicked.connect(self._on_open_settings)
        fl.addWidget(gear_btn)
        flbl = QLabel(f"v{VERSION}")
        flbl.setObjectName("sidebarFooter")
        fl.addWidget(flbl)
        fl.addStretch(1)
        lay.addWidget(footer)

        return wrap

    def _on_module_selected(self, module_id: str) -> None:
        pass

    def _on_sub_page_selected(self, module_id: str, sub_id: str) -> None:
        pages = MODULE_PAGE_MAP.get(module_id, {})
        entry = pages.get(sub_id)
        if entry:
            page_id, _title = entry
            if page_id in self._pages:
                self._select_page(page_id)

    def _on_open_settings(self) -> None:
        from app.ui.widgets.settings_popup import SettingsPopup
        dlg = SettingsPopup(self)
        dlg.exec()

    def _build_content(self) -> QWidget:
        """Content area: topbar (44) + body (10 page Stacked)."""
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Topbar
        topbar = QFrame()
        topbar.setObjectName("contentTopbar")
        topbar.setFixedHeight(44)
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(20, 0, 20, 0)
        tb.setSpacing(8)
        self.lbl_page_title = QLabel("仪表盘")
        self.lbl_page_title.setObjectName("contentTopbarTitle")
        tb.addWidget(self.lbl_page_title)
        # 当前项目 badge
        self.lbl_page_badge = QLabel("")
        self.lbl_page_badge.setObjectName("contentTopbarBadge")
        self.lbl_page_badge.setVisible(False)
        tb.addWidget(self.lbl_page_badge)
        tb.addStretch(1)
        lay.addWidget(topbar)

        # 10 page StackedWidget
        self.tabs = QStackedWidget()
        self.tabs.setObjectName("contentStack")
        for cls in get_all_page_classes():
            self.tabs.addWidget(self._pages[getattr(cls, "PAGE_ID")])
        lay.addWidget(self.tabs, 1)

        # 兼容占位 (旧 API 仍可用, 不显示)
        self.project_list = QListWidget()
        self.project_list.hide()
        return wrap

    def _build_shortcuts(self) -> None:
        """全局快捷键.

        - Ctrl+1/2/3/4  切换模块 (Story/Create/Observe/Publish)
        - Ctrl+,        打开设置
        - Ctrl+T        切换暗/亮主题
        - Ctrl+N        新建项目
        - Ctrl+Q        退出
        - F1            关于
        """
        sc_1 = QShortcut(QKeySequence("Ctrl+1"), self)
        sc_1.activated.connect(lambda: self.module_nav.select_module("story"))
        sc_2 = QShortcut(QKeySequence("Ctrl+2"), self)
        sc_2.activated.connect(lambda: self.module_nav.select_module("create"))
        sc_3 = QShortcut(QKeySequence("Ctrl+3"), self)
        sc_3.activated.connect(lambda: self.module_nav.select_module("observe"))
        sc_4 = QShortcut(QKeySequence("Ctrl+4"), self)
        sc_4.activated.connect(lambda: self.module_nav.select_module("publish"))
        sc_comma = QShortcut(QKeySequence("Ctrl+,"), self)
        sc_comma.activated.connect(self._on_open_settings)
        sc_theme = QShortcut(QKeySequence("Ctrl+T"), self)
        sc_theme.activated.connect(self._on_toggle_theme)
        sc_new = QShortcut(QKeySequence("Ctrl+N"), self)
        sc_new.activated.connect(self._on_new_project)
        sc_about = QShortcut(QKeySequence("F1"), self)
        sc_about.activated.connect(self._on_about)
        sc_quit = QShortcut(QKeySequence("Ctrl+Q"), self)
        sc_quit.activated.connect(self.close)

    def _build_statusbar(self) -> None:
        """Status Bar: 项目 · 字数 · 章节 · 模型指示 · spacer · 版本号."""
        sb = QStatusBar()
        self.setStatusBar(sb)
        # 左: 状态文本 (default)
        sb.showMessage("就绪")
        # 中间: 项目信息 chips
        self._ver_label = QLabel("")
        self._ver_label.setObjectName("versionLabel")
        self._ver_label.setToolTip("点击查看更新日志")
        self._ver_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ver_label.mousePressEvent = lambda _e: self._on_about()
        sb.addPermanentWidget(self._ver_label)
        # 状态指示 (项目 + 模型)
        self._status_proj = QLabel("未打开项目")
        self._status_proj.setObjectName("statusBarIndicator")
        sb.addPermanentWidget(self._status_proj)
        sep1 = QLabel("|")
        sep1.setObjectName("statusBarSep")
        sb.addPermanentWidget(sep1)
        self._status_model = QLabel("")  # 初始为空, _refresh_model_status 填充
        self._status_model.setObjectName("statusBarIndicator")
        sb.addPermanentWidget(self._status_model)
        # 启动时检测一次模型状态
        self._refresh_model_status()

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _wire_signals(self) -> None:
        theme = get_theme()
        theme.changed.connect(self._on_theme_changed)
        # 大纲管理结构变更 → 刷新生成页章节结构
        outline_page = self._pages.get("outline-mgmt")
        if outline_page and hasattr(outline_page, "_inner"):
            inner = outline_page._inner
            if hasattr(inner, "structure_changed"):
                inner.structure_changed.connect(self._on_outline_structure_changed)

    def _refresh_model_status(self) -> None:
        """刷新状态栏模型指示: Mock 模式 / 真实模型 / 未配置."""
        # 1) 检测 Mock 模式
        mock_env = os.environ.get("NW_AI_MOCK", "0") == "1"
        mock_installed = False
        try:
            from app.ai import mock as _mock_mod
            mock_installed = _mock_mod.is_installed()
        except Exception:
            pass
        is_mock = mock_env or mock_installed

        if is_mock:
            self._status_model.setText(" 🧪 Mock 模式 ")
            # 橙色背景 + 高对比白色, 明暗主题都醒目 (统一警示色)
            self._status_model.setStyleSheet(
                f"background:{mock_mode_bg()}; color:{mock_mode_fg()}; border-radius:4px;"
                "padding:1px 6px 1px 6px; font-weight:600;"
            )
            self._status_model.setToolTip(
                "当前为 Mock 模式, AI 响应为模板占位内容\n"
                "如需真实 AI, 请: 设置 → 模型 → 配置 API Key\n"
                "或取消环境变量 NW_AI_MOCK=1"
            )
            return

        # 2) 非 Mock: 尝试读取已配置的活跃模型
        model_label = "未配置模型"
        try:
            p = app_setting_service.get_active()
            if p:
                model_label = f"{p.get('name', '')} · {p.get('model', '')}"
        except Exception:
            pass

        self._status_model.setText(f" 🤖 {model_label} ")
        # 正常模式: 清除特殊样式, 恢复 statusBarIndicator 默认外观
        self._status_model.setStyleSheet("")
        self._status_model.setToolTip("当前使用的 AI 模型 (primary)")

    def _app_has_stylesheet(self) -> bool:
        try:
            return bool(self._qapp().styleSheet())
        except Exception:
            return False

    def _qapp(self):
        from PySide6.QtWidgets import QApplication
        return QApplication.instance()

    def navigate_to(self, page_id: str) -> None:
        """Public API: 外部组件跳转到指定页面."""
        self._select_page(page_id)

    def _select_page(self, page_id: str) -> None:
        """根据 page_id 切换 StackedWidget + 顶栏 title."""
        if page_id not in self._pages:
            return
        # 找到 index
        for idx in range(self.tabs.count()):
            w = self.tabs.widget(idx)
            if w is self._pages[page_id]:
                self.tabs.setCurrentIndex(idx)
                break
        title = get_page_title(page_id)
        self.lbl_page_title.setText(title)
        # 顶栏 badge: 当前项目 (仅 novel-settings / chapter-mgmt / dashboard 等数据相关页显示)
        if self.current_project and page_id in {"novel-settings", "character-mgmt", "dashboard", "world-graph", "usage-analytics"}:
            name = self.current_project.get("name", "(unnamed)")
            self.lbl_page_badge.setText(f"📚 {name}")
            self.lbl_page_badge.setVisible(True)
        else:
            self.lbl_page_badge.setVisible(False)

    def _on_outline_structure_changed(self) -> None:
        """大纲管理结构变更(重命名/新增/删除) → 刷新生成页."""
        gen_page = self._pages.get("generate")
        if gen_page and hasattr(gen_page, "set_project") and self.current_project:
            gen_page.set_project(self.current_project)

    # ------------------------------------------------------------------
    # Slots - 主题
    # ------------------------------------------------------------------
    def _on_toggle_theme(self) -> None:
        get_theme().toggle(self._qapp())

    def _on_theme_changed(self, name: str) -> None:
        log.debug(f"[MainWindow] theme changed to {name}")

    # ------------------------------------------------------------------
    # Slots - 项目
    # ------------------------------------------------------------------
    def _on_new_project(self) -> None:
        """新建项目综合弹窗 (NewProjectDialog).

        一次弹窗收集 name / book_title / genre / platform / word_target
        (替代旧的两个 Dialogs.input).
        """
        from PySide6.QtWidgets import QDialog
        dlg = NewProjectDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.result()
        if not data:
            return
        try:
            project_service.create(**data)
        except ServiceError as e:
            Dialogs.warning("新建项目失败", f"创建失败: {e}", parent=self)
            return
        self._reload_projects()

    def _on_backup(self) -> None:
        if not self.current_project:
            return
        Dialogs.info(
            "备份",
            f"Phase 6: 备份功能实装。\n当前项目: {self.current_project.get('name')}",
            parent=self,
        )

    def _on_about(self) -> None:
        from app.ui.widgets import SubWindowDialog
        from PySide6.QtWidgets import QTextBrowser
        from app.core.version import format_about_text
        browser = QTextBrowser()
        browser.setHtml(f"<pre style='color:#c8cdd4; font-size:13px'>{format_about_text()}</pre>")
        SubWindowDialog(
            "About",
            browser,
            width=480, height=380,
            confirm_text="关闭",
            parent=self,
        ).exec()

    def _on_project_selected(self) -> None:
        """旧 API 兼容."""
        item = self.project_list.currentItem()
        if item is None:
            self.current_project = None
        else:
            self.current_project = item.data(Qt.ItemDataRole.UserRole)
        self._update_action_states()
        self._notify_project_changed()

    def _notify_project_changed(self) -> None:
        # 通知所有 page
        for page in self._pages.values():
            if hasattr(page, "set_project"):
                try:
                    page.set_project(self.current_project)
                except Exception as e:
                    log.warning("[MainWindow] page.set_project 失败: %s", e)
        # worker
        self._refresh_signal_worker()
        # topbar badge + status bar
        if self.current_project:
            name = self.current_project.get("name", "(unnamed)")
            self._status_proj.setText(f"📚 {name}")
        else:
            self._status_proj.setText("(无项目)")
        self._refresh_model_status()
        # 触发当前 page badge 更新
        cur_widget = self.tabs.currentWidget()
        for pid, w in self._pages.items():
            if w is cur_widget:
                self._select_page(pid)
                break

    def _update_action_states(self) -> None:
        # 留作扩展
        pass

    # ------------------------------------------------------------------
    # v3.0 Edit Signals: worker 生命周期
    # ------------------------------------------------------------------
    def _refresh_signal_worker(self) -> None:
        try:
            from app.workflow import edit_signals as _es
            if not _es.is_signal_enabled():
                return
            _es.stop_all_workers()
            if self.current_project:
                _es.start_worker(self.current_project["id"])
                log.info("[edit_signals] worker 启动: project=%s",
                         self.current_project.get("id"))
        except Exception as e:
            log.warning("[edit_signals] worker 启动失败: %s", e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_projects(self, projects: list[dict]) -> None:
        """把项目列表存到 self.projects. 项目选择走 sidebar chip 路径 (Phase 2.2 完善)."""
        self.projects = list(projects)
        # project_list 兼容
        self.project_list.clear()
        for p in self.projects:
            label = p.get("name", "(unnamed)")
            if p.get("book_title"):
                label += f"  ·  {p['book_title']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.project_list.addItem(item)
        # 项目组: 当前项目取第一个 (mockup 默认行为)
        if self.projects:
            self._set_current_project(self.projects[0])

    def _set_current_project(self, project: dict) -> None:
        # V4.0-P4-新: 重新从 service 拿完整数据 (合并 structure.json 的 sub_genres /
        # volumes / chapters_per_volume / words_per_chaper). list_all() 返回的只是
        # SQLite 原始行, 没有 structure.json 里的字段, 那些是 NovelSettingsPage
        # 项目基础信息卡要显示的 (主题材/副题材/分卷结构).
        try:
            full = project_service.get(project.get("id")) if project else None
        except Exception:
            full = project
        self.current_project = full or project
        self._update_action_states()
        self._refresh_project_progress()
        self._notify_project_changed()

        # §9 双模式: 检测项目类型并设置默认视图
        if self.current_project:
            project_id = self.current_project.get("id")
            if project_id:
                self._detect_and_set_project_mode(project_id)

    def _refresh_project_progress(self) -> None:
        """刷新 titlebar 的项目进度: 完成章节/估算总章节.

        总章节 = word_target / 2500 (网文平均 2500 字/章, 参考用).
        完成章节 = 累加所有 book 下 word_count>=500 的章节数.
        无项目时显示 —/—.
        """
        if not self.current_project:
            self.lbl_progress_text.setText("—/—")
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
            return
        try:
            from app.services import book_service, chapter_service
            project_id = self.current_project.get("id")
            word_target = int(self.current_project.get("word_target") or 200_000)
            total = max(1, word_target // 2500)
            done = 0
            for bk in book_service.list_for_project(project_id).get("books", []):
                for ch in chapter_service.list_for_book(bk["id"]).get("chapters", []):
                    if (ch.get("word_count") or 0) >= 500:
                        done += 1
            self.lbl_progress_text.setText(f"{done}/{total} 章")
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(done, total))
        except Exception as e:
            log.warning("[progress] 刷新失败: %s", e)
            self.lbl_progress_text.setText("—/—")
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)

    def _detect_and_set_project_mode(self, project_id: str) -> None:
        """§9 双模式: 检测项目类型并设置默认视图; 老项目提示升级为单元模式."""
        try:
            from app.services.project_type import (
                detect_project_type, get_default_view, should_prompt_upgrade,
            )
            project_type = detect_project_type(project_id)
            default_view = get_default_view(project_id)

            log.info("[mode] 项目 %s 类型: %s, 默认视图: %s", project_id[:8], project_type, default_view)

            # §9(c): 老项目 -> 提示升级为单元模式 (包装所有章节为虚拟单元)
            if should_prompt_upgrade(project_id):
                self._maybe_prompt_upgrade(project_id)
                # 升级后重新判定 (升级使项目变 mixed -> unit 视图)
                project_type = detect_project_type(project_id)
                default_view = get_default_view(project_id)

            # 根据项目类型切换到对应视图
            if default_view == "unit":
                # 新项目 / 已升级: 切换到单元视图
                self.module_nav.select_module("create")
                try:
                    self._on_sub_page_selected("create", "unit")
                except Exception:
                    pass
            # 老项目且未升级: 保持章节视图 (默认), 不切换

            # 存储项目模式信息供其他组件使用
            if self.current_project:
                self.current_project["_project_type"] = project_type
                self.current_project["_default_view"] = default_view

        except Exception as e:
            log.warning("[mode] 项目类型检测失败: %s", e)

    def _maybe_prompt_upgrade(self, project_id: str) -> None:
        """§9(c): 会话内仅提示一次, 用户确认后升级老项目为虚拟单元."""
        if not hasattr(self, "_upgrade_prompted"):
            self._upgrade_prompted = set()
        if project_id in self._upgrade_prompted:
            return
        self._upgrade_prompted.add(project_id)

        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "升级为单元模式",
            "检测到这是一个「章节模式」老项目。\n\n"
            "是否升级为「单元模式」？\n"
            "系统会将现有章节自动包装为虚拟单元，之后即可使用故事单元的全部功能。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            from app.services.project_type import upgrade_old_project
            result = upgrade_old_project(project_id)
            if result.get("ok"):
                log.info(
                    "[mode] 项目 %s 升级完成, 包装 %d 个虚拟单元",
                    project_id[:8], result.get("wrapped_count", 0),
                )
                self._refresh_project_progress()
            else:
                log.warning("[mode] 项目 %s 升级未成功: %s", project_id[:8], result)
        except Exception as e:
            log.warning("[mode] 升级失败: %s", e)

    def _reload_projects(self) -> None:
        try:
            data = project_service.list_all()
        except ServiceError as e:
            log.error("Failed to load projects: %s", e)
            self.set_status(f"加载项目失败: {e}")
            return
        self.set_projects(data.get("projects", []))
        self.set_status(f"已加载 {data.get('total', 0)} 个项目")

    def set_status(self, msg: str) -> None:
        self.statusBar().showMessage(msg)
