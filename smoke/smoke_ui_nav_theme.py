"""
UI 折叠树 + 主题 + 10-page smoke 测试 (v4.0 mockup-aligned).

覆盖:
  1. 主题管理器: dark ↔ light 切换 + QApplication stylesheet 应用
  2. MainWindow: 3 个折叠树分组 (📖 小说管理 / 📊 信息总览 / 🔧 其他功能) + 10 个 page
  3. 10 page 顺序: dashboard / projects / novel-settings / chapter-mgmt /
     world-graph / usage-analytics / knowledge / plugins / logs / settings
  4. 折叠树点击 → 切 page → 顶栏 title 跟随
  5. 主题按钮 (ThemeToggle widget) 同步
  6. 默认显示 dashboard (page 0)
  7. sidebar header "工作台" 存在
  8. footer "v3.x.x · PySide6" 存在
  9. 5 page placeholder 含特定标题
"""
from __future__ import annotations
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Force UTF-8
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 强制 stdout UTF-8,避免 GBK 编码 emoji 报错
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 必须在 import app.* 之前打补丁: UI 测试用临时 DB, 避免污染真实数据
import tempfile
_TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_ui_"))
_TEST_DB = _TMPDIR / "test.db"
_TEST_STORY = _TMPDIR / "story"
_TEST_STORY.mkdir(parents=True, exist_ok=True)

import app.app_paths
app.app_paths.sqlite_path = lambda: _TEST_DB

import app.services.file_store
app.services.file_store.BASE_DIR = _TEST_STORY
app.services.file_store._base_dir = lambda: _TEST_STORY

# 也 patch app_setting_service.SETTINGS_FILE 防止污染 %APPDATA%
import app.services.app_setting_service
app.services.app_setting_service.SETTINGS_FILE = _TMPDIR / "app_settings.json"

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget


# Watchdog
_done = threading.Event()
def _watchdog() -> None:
    if not _done.wait(timeout=180):
        print("[TIMEOUT] ui_nav_theme 超时 180s, 强制退出", flush=True)
        os._exit(2)
_thread = threading.Thread(target=_watchdog, daemon=True)
_thread.start()


# Counters
_pass = 0
_fail = 0
def check(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  [PASS] {label}", flush=True)
    else:
        _fail += 1
        print(f"  [FAIL] {label}", flush=True)


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}", flush=True)


# 期望的 3 折叠分组 + 17 子项 (V4.0-P4-新: 二级 tab 展平)
# 注: 插件系统已废弃, 从 "🔧 其他功能" 移除"插件管理"
EXPECTED_GROUPS = [
    ("📖 小说管理", ["项目管理", "小说设定", "世界观", "角色管理", "大纲管理", "章节生成", "自动进化"]),
    ("📊 信息总览", ["仪表盘", "世界图谱", "用量分析"]),
    ("🔧 其他功能", ["知识库", "外观", "模型配置", "存储备份", "日志", "授权", "关于"]),
]


def main() -> int:
    print("=== UI 折叠树 + 主题 + 10-page smoke (offscreen, v4.0) ===", flush=True)

    # ---- 启动 DB ----
    try:
        from app.services import db as svc_db
        svc_db.init_db()
    except Exception as e:
        print(f"[warn] init_db failed: {e}")

    # ---- ThemeManager 单测 ----
    section("[Theme 1] 主题管理器")
    from app.ui.theme import get_theme, DARK_QSS, LIGHT_QSS
    tm = get_theme()
    check(tm is get_theme(), "单例")
    check(tm.current() == "dark", f"默认 dark (实际 {tm.current()})")
    check("QMainWindow" in DARK_QSS and "QPushButton" in DARK_QSS, "DARK_QSS 包含基础规则")
    check("QMainWindow" in LIGHT_QSS and "QPushButton" in LIGHT_QSS, "LIGHT_QSS 包含基础规则")
    check("0a0b0d" in DARK_QSS and "f0f1f2" in DARK_QSS, "DARK 含暗色调色板")
    check("ffffff" in LIGHT_QSS and "1a1c1e" in LIGHT_QSS, "LIGHT 含亮色调色板")

    # ---- QApplication ----
    app = QApplication.instance() or QApplication(sys.argv)
    tm.apply(app, "dark")
    check("background: #0f1011" in app.styleSheet() or "QMainWindow" in app.styleSheet(),
          f"暗色 stylesheet 已应用 ({len(app.styleSheet())} 字符)")

    tm.apply(app, "light")
    check("background: #f5f6f7" in app.styleSheet() or "QMainWindow" in app.styleSheet(),
          "亮色 stylesheet 已应用")

    after = tm.toggle(app)
    check(after == "dark", f"toggle 回到 dark (实际 {after})")

    # ---- MainWindow 启动 ----
    section("[UI 1] MainWindow 启动")
    from app.ui.main_window import MainWindow
    tm.apply(app, "dark")
    w = MainWindow()
    check(w.windowTitle() == "小说写作助手 v3.4.0", f"windowTitle={w.windowTitle()}")
    check(w.nav_tree is not None, "nav_tree 存在")
    check(w.tabs is not None and w.tabs.count() == 17, f"StackedWidget 17 page (实际 {w.tabs.count()})")
    # 默认是 dashboard (idx 0)
    check(w.tabs.currentIndex() == 0, f"默认 index=0 dashboard (实际 {w.tabs.currentIndex()})")
    check(w.lbl_page_title.text() == "仪表盘", f"page_title 仪表盘 (实际 {w.lbl_page_title.text()})")

    # ---- 折叠树结构: 3 折叠组 + 10 子项 ----
    section("[UI 2] 折叠树结构 (3 组 + 10 子项)")
    check(w.nav_tree.topLevelItemCount() == 3,
          f"3 个折叠组 (实际 {w.nav_tree.topLevelItemCount()})")

    for i, (grp_label, children_expected) in enumerate(EXPECTED_GROUPS):
        gi = w.nav_tree.topLevelItem(i)
        check(gi is not None, f"  第 {i+1} 组存在")
        check(gi.text(0) == grp_label, f"  第 {i+1} 组 label='{grp_label}' (实际 '{gi.text(0)}')")
        check(gi.childCount() == len(children_expected),
              f"  '{grp_label}' 子项数 {len(children_expected)} (实际 {gi.childCount()})")
        actual_children = [gi.child(j).text(0) for j in range(gi.childCount())]
        check(actual_children == children_expected,
              f"  '{grp_label}' 子项顺序: {actual_children}")
        # 分组不可选
        flags = gi.flags()
        check(not (flags & Qt.ItemFlag.ItemIsSelectable), f"  '{grp_label}' 节点不可选")

    # 总子项数 = 18
    total_children = sum(w.nav_tree.topLevelItem(i).childCount()
                         for i in range(w.nav_tree.topLevelItemCount()))
    check(total_children == 17, f"总子项数 17 (实际 {total_children})")

    # ---- 17 page 顺序 (V4.0-P4-新: 二级 tab 展平, 插件页已废弃) ----
    section("[UI 3] 17 page 顺序 (与 mockup 1:1)")
    expected_order = [
        ("dashboard",         "仪表盘"),
        ("projects",          "项目管理"),
        ("novel-settings",    "小说设定"),
        ("worldview",         "世界观"),
        ("character-mgmt",    "角色管理"),
        ("outline-mgmt",      "大纲管理"),
        ("edit-signals",      "自动进化"),
        ("generate",          "章节生成"),
        ("world-graph",       "世界图谱"),
        ("usage-analytics",   "用量分析"),
        ("knowledge",         "知识库"),
        ("appearance",        "外观"),
        ("model",             "模型配置"),
        ("storage-backup",    "存储备份"),
        ("logs",              "日志"),
        ("license",           "授权"),
        ("about",             "关于"),
    ]
    from app.ui.pages import PAGE_REGISTRY
    for idx, (page_id, page_title) in enumerate(expected_order):
        check(page_id in PAGE_REGISTRY, f"  PAGE_REGISTRY 含 '{page_id}'")
        cls = PAGE_REGISTRY[page_id]
        check(getattr(cls, "PAGE_ID", None) == page_id, f"  {page_id}.PAGE_ID")
        check(getattr(cls, "PAGE_TITLE", None) == page_title, f"  {page_id}.PAGE_TITLE='{page_title}'")

    # ---- 折叠树点击 → 切 page ----
    section("[UI 4] 点击导航 → 切 page + 顶栏 title 跟随")
    # 用 title -> page_id 反查 (group 内子项顺序与 PAGE_REGISTRY 不一致)
    title_to_pageid = {title: pid for pid, title in expected_order}
    for grp_idx, (grp_label, children) in enumerate(EXPECTED_GROUPS):
        gi = w.nav_tree.topLevelItem(grp_idx)
        for child_idx, child_label in enumerate(children):
            ci = gi.child(child_idx)
            w.nav_tree.itemClicked.emit(ci, 0)
            page_id = title_to_pageid[child_label]
            actual_widget = w.tabs.currentWidget()
            check(actual_widget is w._pages[page_id],
                  f"  '{child_label}' → page '{page_id}' (实际 {type(actual_widget).__name__})")
            check(w.lbl_page_title.text() == child_label,
                  f"  '{child_label}' → topbar title (实际 '{w.lbl_page_title.text()}')")

    # 回到 dashboard
    dash_node = w.nav_tree.topLevelItem(1).child(0)  # 📊 信息总览 > 仪表盘
    w.nav_tree.itemClicked.emit(dash_node, 0)
    check(w.tabs.currentIndex() == 0, "回到 dashboard (idx 0)")

    # ---- 主题按钮 (ThemeToggle widget) ----
    section("[UI 5] ThemeToggle 主题切换")
    check(hasattr(w, "theme_toggle"), "MainWindow 有 theme_toggle")
    check(w.theme_toggle is not None, "theme_toggle 实例化")
    check(tm.current() == "dark", f"初始 dark (实际 {tm.current()})")
    w._on_toggle_theme()
    check(tm.current() == "light", f"切到 light (实际 {tm.current()})")
    check(w.theme_toggle._light_btn.isChecked(), "light 按钮被选中")
    check(not w.theme_toggle._dark_btn.isChecked(), "dark 按钮未选中")
    w._on_toggle_theme()
    check(tm.current() == "dark", f"切回 dark (实际 {tm.current()})")
    check(w.theme_toggle._dark_btn.isChecked(), "dark 按钮被选中")
    check(not w.theme_toggle._light_btn.isChecked(), "light 按钮未选中")
    w.theme_toggle._light_btn.click()
    check(tm.current() == "light", f"ThemeToggle 内部触发切到 light (实际 {tm.current()})")
    w.theme_toggle._dark_btn.click()
    check(tm.current() == "dark", f"ThemeToggle 内部触发切回 dark (实际 {tm.current()})")

    # ---- Title Bar 元素 ----
    section("[UI 6] Title Bar (logo + 项目进度)")
    # M11-A: 旧 3 个圆点已移除, 改为有意义的"项目进度指示器"
    found_progress = sum(1 for c in w.findChildren(QWidget)
                        if c.objectName() in ("titleBarProgress", "titleBarProgressBar"))
    check(found_progress >= 1, f"项目进度 widget 存在 (实际 {found_progress})")
    # logo
    found_logo = sum(1 for c in w.findChildren(QLabel)
                     if c.objectName() in ("titleBarLogo", "titleBarLogoAccent"))
    check(found_logo == 2, f"2 个 logo label (实际 {found_logo})")

    # ---- Sidebar header + footer ----
    section("[UI 7] Sidebar header + footer")
    found_header = sum(1 for c in w.findChildren(QWidget)
                       if c.objectName() == "sidebarHeader")
    check(found_header >= 1, f"sidebarHeader 存在 ({found_header})")
    found_footer = sum(1 for c in w.findChildren(QLabel)
                       if c.objectName() == "sidebarFooter")
    check(found_footer >= 1, f"sidebarFooter 存在 ({found_footer})")

    # ---- 4 page placeholder 内容 (插件页已移除) ----
    section("[UI 8] 4 个占位 page 文字提示存在")
    placeholder_titles = {
        "projects":        "项目管理",
        "world-graph":     "世界图谱",
        "usage-analytics": "用量分析",
        "knowledge":       "知识库",
    }
    for pid, expected_title in placeholder_titles.items():
        widget = w._pages[pid]
        labels = widget.findChildren(QLabel)
        title_found = any(expected_title in (lbl.text() or "") for lbl in labels)
        check(title_found, f"  '{pid}' 占位含 '{expected_title}' 文字")

    # ---- _on_new_project 兼容 (mock 弹窗) ----
    section("[UI 9] _on_new_project 兼容 (mock 弹窗)")
    from app.ui.widgets import Dialogs
    _orig_input = Dialogs.input
    responses = [(True, "test_proj"), (True, "测试书")]
    ridx = [0]
    def fake_input(*a, **k):
        r = responses[ridx[0]] if ridx[0] < len(responses) else (False, "")
        ridx[0] += 1
        return r
    Dialogs.input = staticmethod(fake_input)
    # M11-A: _on_new_project 用的是 NewProjectDialog (一弹窗收 5 字段), 不是 Dialogs.input
    # patch 掉 NewProjectDialog.exec 让它不阻塞
    from app.ui.widgets import new_project_dialog as _npd
    _orig_npd_exec = _npd.NewProjectDialog.exec
    def fake_npd_exec(self):
        self._result = {"name": "test_proj", "book_title": "测试书", "genre": "玄幻",
                        "platform": "起点中文网", "word_target": 100_000}
        from PySide6.QtWidgets import QDialog
        return QDialog.DialogCode.Accepted
    _npd.NewProjectDialog.exec = fake_npd_exec
    from app.services import project_service
    _create_orig = project_service.create
    created: list[dict] = []
    def fake_create(*args, **kwargs) -> dict:
        d = {"id": f"x{len(created)}", "name": kwargs.get("name", args[0] if args else "?"),
             "book_title": kwargs.get("book_title")}
        created.append(d)
        return d
    project_service.create = fake_create
    _orig_reload = w._reload_projects
    w._reload_projects = lambda: None
    try:
        w._on_new_project()
    except Exception as e:
        print(f"  [warn] _on_new_project raised: {e}", flush=True)
    check(len(created) == 1, f"创建 1 次 (实际 {len(created)})")
    if created:
        check(created[0]["name"] == "test_proj", f"项目1={created[0]}")
        check(created[0]["book_title"] == "测试书", f"书名1={created[0]['book_title']!r}")
    project_service.create = _create_orig
    w._reload_projects = _orig_reload
    Dialogs.input = _orig_input
    _npd.NewProjectDialog.exec = _orig_npd_exec

    print(f"\n{'=' * 60}")
    print(f"通过: {_pass}    失败: {_fail}")
    if _fail == 0:
        print(f"全部 {_pass} 项检查通过 ✓")
    else:
        print(f"!! {_fail} 项失败 !!")
    print(f"{'=' * 60}")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
