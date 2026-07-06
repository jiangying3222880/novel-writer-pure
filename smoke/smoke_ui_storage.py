"""
P0-新: 自定义项目/数据目录功能 smoke test.

覆盖:
  A. app_paths 基础 API (override / getter / 默认回退)
  B. apply_storage_overrides_from_settings (从 kv 读)
  C. migrate_story_dir 实际复制文件
  D. file_store._base_dir() 跟随 override
  E. SettingsTab(scope="app") 8 个 tab + 存储 tab 控件存在
  F. _apply_story_dir mock: 校验写入 (mock Dialogs)

退出码: 0 全过, 1 有失败
"""
from __future__ import annotations
import os
import sys
import tempfile
import shutil
from pathlib import Path

# GBK 编码 fix (Windows + emoji)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 路径 + UTF-8
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_pass = 0
_fail = 0


def check(cond: bool, msg: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  [PASS] {msg}")
    else:
        _fail += 1
        print(f"  [FAIL] {msg}")


def section(name: str) -> None:
    print()
    print("=" * 60)
    print(name)
    print("=" * 60)


# ============================================================
# A. app_paths 基础 API
# ============================================================
def test_a_app_paths_basics() -> None:
    section("[A] app_paths 基础 API")
    from app.app_paths import (
        STORY_DIR_DEFAULT, DATA_DIR_DEFAULT,
        get_story_dir, get_data_dir,
        set_story_dir_override, set_data_dir_override,
        sqlite_path, get_signals_dir, get_signals_projects_dir,
    )

    check(STORY_DIR_DEFAULT.exists(), f"STORY_DIR_DEFAULT 存在 ({STORY_DIR_DEFAULT})")
    check(DATA_DIR_DEFAULT.exists(), f"DATA_DIR_DEFAULT 存在 ({DATA_DIR_DEFAULT})")
    check(get_story_dir() == STORY_DIR_DEFAULT, "默认 get_story_dir = STORY_DIR_DEFAULT")
    check(get_data_dir() == DATA_DIR_DEFAULT, "默认 get_data_dir = DATA_DIR_DEFAULT")

    with tempfile.TemporaryDirectory() as td:
        new_story = Path(td) / "novels"
        new_data = Path(td) / "data"
        # override
        set_story_dir_override(new_story)
        set_data_dir_override(new_data)
        check(get_story_dir() == new_story.resolve(), f"override 后 get_story_dir = {new_story}")
        check(get_data_dir() == new_data.resolve(), f"override 后 get_data_dir = {new_data}")
        # 新 getter 跟随 override
        check(sqlite_path().parent == (new_data / "data").resolve(),
              f"sqlite_path() 跟 override ({sqlite_path()})")
        check(get_signals_dir() == new_data.parent.resolve() / "signals" or
              get_signals_dir() == (new_data.parent / "signals"),
              f"signals_dir 跟 override ({get_signals_dir()})")
        # reset
        set_story_dir_override(None)
        set_data_dir_override(None)
        check(get_story_dir() == STORY_DIR_DEFAULT, "reset 后回默认")
        check(get_data_dir() == DATA_DIR_DEFAULT, "reset 后回默认")


# ============================================================
# B. apply_storage_overrides_from_settings
# ============================================================
def test_b_apply_overrides_from_settings() -> None:
    section("[B] apply_storage_overrides_from_settings")
    from app.app_paths import (
        set_story_dir_override, set_data_dir_override,
        get_story_dir, get_data_dir,
    )
    # reset 状态
    set_story_dir_override(None)
    set_data_dir_override(None)

    # 临时设置 app_settings.json
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "fake_data"
        fake.mkdir()
        target = Path(td) / "my_novels"
        target.mkdir()
        cfg = fake / "app_settings.json"
        cfg.write_text(
            '{"providers": [], "active_provider": null, "kv": '
            f'{{"storage.story_dir": "{str(target).replace(chr(92), chr(92)*2)}", '
            f'"storage.data_dir": "{str(fake).replace(chr(92), chr(92)*2)}"}}}}',
            encoding="utf-8",
        )
        # monkey-patch SETTINGS_FILE
        from app.services import app_setting_service
        orig_path = app_setting_service.SETTINGS_FILE
        app_setting_service.SETTINGS_FILE = cfg
        try:
            from app.app_paths import apply_storage_overrides_from_settings
            apply_storage_overrides_from_settings()
            check(get_story_dir() == target.resolve(), f"从 settings 读出 story_dir ({get_story_dir()})")
            check(get_data_dir() == fake.resolve(), f"从 settings 读出 data_dir ({get_data_dir()})")
        finally:
            app_setting_service.SETTINGS_FILE = orig_path
            set_story_dir_override(None)
            set_data_dir_override(None)


# ============================================================
# C. migrate_story_dir
# ============================================================
def test_c_migrate_story_dir() -> None:
    section("[C] migrate_story_dir 实际复制文件")
    from app.app_paths import migrate_story_dir, STORY_DIR_DEFAULT

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "old"
        src.mkdir()
        # 准备一些假项目文件
        for name in ("project_001.json", "project_002.json", "README.txt"):
            (src / name).write_text(f"data of {name}", encoding="utf-8")
        # 准备一个子目录
        (src / "project_003").mkdir()
        (src / "project_003" / "chapters.json").write_text("ch", encoding="utf-8")

        # monkey-patch STORY_DIR_DEFAULT 来指向我们的临时 src
        import app.app_paths as ap
        orig = ap.STORY_DIR_DEFAULT
        ap.STORY_DIR_DEFAULT = src
        try:
            dst = Path(td) / "new"
            r = migrate_story_dir(dst)
            check(r["copied"] == 4, f"复制 4 项 (实际 {r['copied']})")
            check(r["skipped"] == 0, f"跳过 0 项 (实际 {r['skipped']})")
            check(r["errors"] == [], f"无错误 (实际 {r['errors']})")
            check((dst / "project_001.json").exists(), "project_001.json 复制成功")
            check((dst / "project_003" / "chapters.json").exists(), "子目录复制成功")

            # 再迁移一次应该全部 skipped
            r2 = migrate_story_dir(dst)
            check(r2["copied"] == 0, f"重复迁移 copied=0 (实际 {r2['copied']})")
            check(r2["skipped"] == 4, f"重复迁移 skipped=4 (实际 {r2['skipped']})")
        finally:
            ap.STORY_DIR_DEFAULT = orig


# ============================================================
# D. file_store._base_dir() 跟随 override
# ============================================================
def test_d_file_store_follows_override() -> None:
    section("[D] file_store 跟随 override")
    from app.app_paths import set_story_dir_override
    with tempfile.TemporaryDirectory() as td:
        new = Path(td) / "my"
        set_story_dir_override(new)
        try:
            # 重新 import (因为 _base_dir() 用了 lazy import 不会冻结)
            from app.services import file_store
            d = file_store._get_project_dir("test_id")
            check(str(d).startswith(str(new.resolve())),
                  f"file_store 项目目录 = {d} (override {new})")
        finally:
            set_story_dir_override(None)


# ============================================================
# E. SettingsTab (scope="app") UI  (左导航 + 右内容)
# ============================================================
def test_e_settings_page_ui() -> None:
    section("[E] SettingsTab(scope=app) 8 左导航项 + 存储 tab 控件")
    from PySide6.QtWidgets import QApplication, QListWidget, QStackedWidget
    from app.ui.tabs.settings_tab import SettingsTab
    app = QApplication.instance() or QApplication(sys.argv)
    p = SettingsTab(scope=SettingsTab.SCOPE_APP)
    # 4.0 重构: QTabWidget → QListWidget(左) + QStackedWidget(右)
    check(isinstance(p.nav_list, QListWidget), "nav_list 是 QListWidget (左导航)")
    check(isinstance(p.stack, QStackedWidget), "stack 是 QStackedWidget (右内容)")
    check(p.nav_list.count() == 8, f"8 个导航项 (实际 {p.nav_list.count()})")
    check(p.stack.count() == 8, f"stack 也 8 项 (实际 {p.stack.count()})")
    nav_titles = [p.nav_list.item(i).text() for i in range(p.nav_list.count())]
    check("📁 存储" in nav_titles, "存储 导航项存在")
    check(any("AI 路由" in t for t in nav_titles), "AI 路由 导航项存在")
    check("🤖 模型" in nav_titles, "模型 导航项存在")
    check("💾 备份" in nav_titles, "备份 导航项存在")
    check("🎨 外观" in nav_titles, "外观 导航项存在")

    # 点 "存储" 导航项, 切到对应右内容
    storage_idx = None
    for i in range(p.nav_list.count()):
        if "存储" in p.nav_list.item(i).text():
            p.nav_list.setCurrentRow(i)
            storage_idx = i
            break
    check(storage_idx is not None, "找到 存储 导航项 index")
    check(p.stack.currentIndex() == storage_idx, f"切到 stack[{storage_idx}]")

    storage = p.storage_widget
    check(hasattr(storage, "lbl_cur_story"), "storage.lbl_cur_story 存在")
    check(hasattr(storage, "lbl_cur_data"), "storage.lbl_cur_data 存在")
    check(hasattr(storage, "ed_story"), "storage.ed_story 存在")
    check(hasattr(storage, "ed_data"), "storage.ed_data 存在")
    check(storage.lbl_cur_story.text() != "", f"lbl_cur_story 有内容 ({storage.lbl_cur_story.text()[:50]})")
    check(storage.lbl_cur_data.text() != "", f"lbl_cur_data 有内容 ({storage.lbl_cur_data.text()[:50]})")
    check(callable(getattr(storage, "_apply_story_dir", None)), "_apply_story_dir 方法存在")
    check(callable(getattr(storage, "_apply_data_dir", None)), "_apply_data_dir 方法存在")
    check(callable(getattr(storage, "_browse_story_dir", None)), "_browse_story_dir 方法存在")
    check(callable(getattr(storage, "_browse_data_dir", None)), "_browse_data_dir 方法存在")
    check(callable(getattr(storage, "_open_in_explorer", None)), "_open_in_explorer 方法存在")


# ============================================================
# F. _apply_story_dir 端到端 (mock Dialogs + QFileDialog)
# ============================================================
def test_f_apply_story_dir_endtoend() -> None:
    section("[F] _apply_story_dir 端到端 (mock 弹窗)")
    from PySide6.QtWidgets import QApplication
    from app.services import app_setting_service
    from app.app_paths import set_story_dir_override, get_story_dir, STORY_DIR_DEFAULT
    from app.ui.widgets import Dialogs
    from app.ui.tabs.settings_tab import SettingsTab

    app = QApplication.instance() or QApplication(sys.argv)
    p = SettingsTab(scope=SettingsTab.SCOPE_APP)
    storage = p.storage_widget

    # mock Dialogs 三件套
    confirm_response = [True]   # 同意迁移
    info_calls: list[tuple] = []
    error_calls: list[tuple] = []

    def fake_confirm(*a, **k):
        return (confirm_response[0], None)
    def fake_info(title, msg, **k):
        info_calls.append((title, msg))
        return (True, None)
    def fake_error(title, msg, **k):
        error_calls.append((title, msg))
        return (False, None)

    orig_confirm = Dialogs.confirm
    orig_info = Dialogs.info
    orig_error = Dialogs.error
    Dialogs.confirm = staticmethod(fake_confirm)
    Dialogs.info = staticmethod(fake_info)
    Dialogs.error = staticmethod(fake_error)

    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "my_novels"
        target.mkdir()
        try:
            storage.ed_story.setText(str(target))
            storage._apply_story_dir()
            # kv 写入
            check(app_setting_service.get("storage.story_dir") == str(target),
                  f"app_settings kv 写入 ({app_setting_service.get('storage.story_dir')})")
            # 当前 label 更新
            check(storage.lbl_cur_story.text() != str(STORY_DIR_DEFAULT),
                  "lbl_cur_story 更新到新目录")
            # info 弹过
            check(len(info_calls) >= 1, f"info 弹窗 (实际 {len(info_calls)})")
        finally:
            Dialogs.confirm = orig_confirm
            Dialogs.info = orig_info
            Dialogs.error = orig_error
            # 清理 kv
            app_setting_service.delete("storage.story_dir")
            set_story_dir_override(None)


def main() -> int:
    test_a_app_paths_basics()
    test_b_apply_overrides_from_settings()
    test_c_migrate_story_dir()
    test_d_file_store_follows_override()
    test_e_settings_page_ui()
    test_f_apply_story_dir_endtoend()
    print()
    print("=" * 60)
    print(f"通过: {_pass}    失败: {_fail}")
    if _fail == 0:
        print(f"全部 {_pass} 项检查通过 ✓")
    else:
        print(f"!! {_fail} 项失败 !!")
    print("=" * 60)
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
