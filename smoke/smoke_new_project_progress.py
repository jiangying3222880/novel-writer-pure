"""
P0-新: 综合新建项目弹窗 + titlebar 项目进度 widget smoke test.

覆盖:
  A. NewProjectDialog UI 控件存在 (5 字段: name/book/genre/平台/字数)
  B. NewProjectDialog 必填校验 (空 name 弹 warning, 焦点回到 name)
  C. NewProjectDialog.result() 返回结构化 dict (name/book_title/genre/platform/word_target)
  D. NewProjectDialog genre/platform 选择流 (label 反查 id)
  E. MainWindow 旧 3 dots 已删除, 改为 titleBarProgress
  F. _refresh_project_progress 无项目时显示 —/—
  G. _refresh_project_progress 算 done/total: total=word_target//2500, done=word_count>=500 的 chapter
  H. _set_current_project 触发 _refresh_project_progress

退出码: 0 全过, 1 有失败
"""
from __future__ import annotations
import os
import sys
import tempfile
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
# A. NewProjectDialog UI 控件存在
# ============================================================
def test_a_dialog_widgets() -> None:
    section("[A] NewProjectDialog 控件存在")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from app.ui.widgets.new_project_dialog import NewProjectDialog
    dlg = NewProjectDialog()
    check(dlg.windowTitle() == "新建项目", f"windowTitle == 新建项目 (实际 {dlg.windowTitle()!r})")
    check(hasattr(dlg, "ed_name"), "有 ed_name (项目名输入框)")
    check(hasattr(dlg, "ed_book"), "有 ed_book (书名输入框)")
    check(hasattr(dlg, "lbl_genre"), "有 lbl_genre (题材显示)")
    check(hasattr(dlg, "lbl_plat"), "有 lbl_plat (平台显示)")
    check(hasattr(dlg, "spin_words"), "有 spin_words (目标字数)")
    check(dlg.spin_words.value() == 200_000, f"默认 word_target = 200000 (实际 {dlg.spin_words.value()})")
    check(dlg.lbl_genre.text() == "（未选）", f"genre 默认未选 (实际 {dlg.lbl_genre.text()!r})")
    check(dlg.lbl_plat.text() == "（未选）", f"platform 默认未选 (实际 {dlg.lbl_plat.text()!r})")
    # 找创建按钮 (通过 text)
    from PySide6.QtWidgets import QPushButton
    create_btn = None
    for c in dlg.findChildren(QPushButton):
        if "创建" in c.text():
            create_btn = c
            break
    check(create_btn is not None, "找到「创建」按钮")
    check(create_btn.isDefault(), "创建按钮是 default")
    dlg.deleteLater()


# ============================================================
# B. 必填校验
# ============================================================
def test_b_required_validation() -> None:
    section("[B] NewProjectDialog 必填校验")
    from PySide6.QtWidgets import QApplication, QDialog
    app = QApplication.instance() or QApplication(sys.argv)

    from app.ui.widgets.new_project_dialog import NewProjectDialog
    from app.ui.widgets import Dialogs

    captured = {"warned": False, "title": None, "msg": None}
    real_warn = Dialogs.warning

    def fake_warn(title, msg, parent=None):
        captured["warned"] = True
        captured["title"] = title
        captured["msg"] = msg

    Dialogs.warning = fake_warn
    try:
        dlg = NewProjectDialog()
        dlg.ed_name.setText("")  # 空名
        dlg._on_ok()
        check(captured["warned"], "空 name 触发 warning")
        check(captured["msg"] and "项目名" in captured["msg"],
              f"warning msg 含 '项目名' (实际 {captured['msg']!r})")
        check(dlg.result() is None, "result() 仍为 None (未 accept)")
        dlg.deleteLater()
    finally:
        Dialogs.warning = real_warn


# ============================================================
# C. result() 结构
# ============================================================
def test_c_result_structure() -> None:
    section("[C] result() 返回结构化 dict")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from app.ui.widgets.new_project_dialog import NewProjectDialog
    dlg = NewProjectDialog()
    dlg.ed_name.setText("  Test项目  ")
    dlg.ed_book.setText("")  # 空书名 → 默认用项目名
    dlg._genre_list = ["xuanhuan", "dushi"]
    dlg._platform_list = ["起点中文网"]
    dlg.spin_words.setValue(150_000)
    dlg._on_ok()
    res = dlg.result()
    check(res is not None, "result() 不为 None")
    check(res["name"] == "Test项目", f"name = 'Test项目' (实际 {res['name']!r})")
    check(res["book_title"] == "Test项目", f"空书名 → 用项目名 (实际 {res['book_title']!r})")
    check(res["genre"] == "xuanhuan,dushi", f"genre = 'xuanhuan,dushi' (实际 {res['genre']!r})")
    check(res["platform"] == "起点中文网", f"platform = '起点中文网' (实际 {res['platform']!r})")
    check(res["word_target"] == 150_000, f"word_target = 150000 (实际 {res['word_target']})")
    # 空 genre / platform 应是 None 而不是 ""
    dlg2 = NewProjectDialog()
    dlg2.ed_name.setText("X")
    dlg2._on_ok()
    res2 = dlg2.result()
    check(res2["genre"] is None, f"空 genre → None (实际 {res2['genre']!r})")
    check(res2["platform"] is None, f"空 platform → None (实际 {res2['platform']!r})")
    dlg.deleteLater()
    dlg2.deleteLater()


# ============================================================
# D. label <-> id 转换
# ============================================================
def test_d_label_id_conversion() -> None:
    section("[D] genre/platform label ↔ id 转换")
    from app.ui.widgets.new_project_dialog import NewProjectDialog
    from app.services.genre_presets import GENRE_PRESETS, PLATFORM_PRESETS

    dlg = NewProjectDialog()
    # _pick_genre 不弹窗, 直接测 label→id 反查逻辑
    id_to_name = {gid: name for gid, name, _, _ in GENRE_PRESETS}
    label_to_id = {name: gid for gid, name, _, _ in GENRE_PRESETS}
    # 假设用户选了 "玄幻" / "仙侠"
    dlg._genre_list = [label_to_id["玄幻"], label_to_id["仙侠"]]
    dlg._update_genre_label()
    text = dlg.lbl_genre.text()
    check("玄幻" in text and "仙侠" in text,
          f"label 正确显示中文 (实际 {text!r})")

    dlg._platform_list = ["起点中文网", "番茄小说"]
    dlg._update_platform_label()
    text2 = dlg.lbl_plat.text()
    check("起点中文网" in text2 and "番茄小说" in text2,
          f"platform label 正确 (实际 {text2!r})")

    # 空 list → 未选
    dlg._genre_list = []
    dlg._update_genre_label()
    check(dlg.lbl_genre.text() == "（未选）", "空 genre_list → '（未选）'")
    dlg.deleteLater()


# ============================================================
# E. MainWindow 旧 3 dots 已删除, 新 progress widget 存在
# ============================================================
def test_e_titlebar_widgets() -> None:
    section("[E] MainWindow titlebar 旧 3 dots 已删除, 新 progress widget 存在")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    # Patch screen_adapter 避免多屏幕初始化
    from app.ui import screen_adapter as _sa
    _orig = _sa.ScreenAdapter.attach
    _sa.ScreenAdapter.attach = lambda self, w: None
    try:
        from app.ui.main_window import MainWindow
        mw = MainWindow()
        # 找 titleBarProgress (QWidget)
        from PySide6.QtWidgets import QWidget
        prog = None
        for c in mw.findChildren(QWidget):
            if c.objectName() == "titleBarProgress":
                prog = c
                break
        check(prog is not None, "找到 titleBarProgress widget")
        # 旧 3 dots objectName 不应存在
        old_dots = [c for c in mw.findChildren(QWidget)
                    if c.objectName() in ("titleBarDotR", "titleBarDotY", "titleBarDotG")]
        check(len(old_dots) == 0, f"旧 3 dots 已删除 (实际还有 {len(old_dots)} 个)")
        check(hasattr(mw, "lbl_progress_text"), "mw.lbl_progress_text 存在")
        check(hasattr(mw, "progress_bar"), "mw.progress_bar 存在")
        check(mw.lbl_progress_text.text() == "—/—",
              f"初始进度 = '—/—' (实际 {mw.lbl_progress_text.text()!r})")
        check(mw.progress_bar.maximum() == 1, "进度条 max 初始 = 1")
        mw.close()
    finally:
        _sa.ScreenAdapter.attach = _orig


# ============================================================
# F. _refresh_project_progress 无项目 → —/—
# ============================================================
def test_f_refresh_no_project() -> None:
    section("[F] _refresh_project_progress 无项目时")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from app.ui import screen_adapter as _sa
    _sa.ScreenAdapter.attach = lambda self, w: None
    from app.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        mw.current_project = None
        mw._refresh_project_progress()
        check(mw.lbl_progress_text.text() == "—/—", "无项目 → '—/—'")
        check(mw.progress_bar.maximum() == 1, "无项目 → max=1")
        check(mw.progress_bar.value() == 0, "无项目 → value=0")
    finally:
        mw.close()


# ============================================================
# G. _refresh_project_progress 算 done/total
# ============================================================
def test_g_refresh_with_data() -> None:
    section("[G] _refresh_project_progress 算 done/total")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from app.services import db as _svc_db
    from app.services import project_service, book_service, chapter_service
    from app import app_paths

    with tempfile.TemporaryDirectory(prefix="nw_smoke_prog_") as td:
        # 把 sqlite 重定向到临时目录, 这样不污染现有 DB
        app_paths.set_data_dir_override(td)
        try:
            # 跑迁移
            _svc_db.init_db()
            # 创建 project (word_target=75000 → total=30)
            proj = project_service.create(
                name="Smoke进度测试",
                book_title="测试书",
                word_target=75_000,
            )
            bk = book_service.create(proj["id"], 1, title="第一卷")
            # 创建 3 章: 2 章 word_count>=500 (完成), 1 章 <500 (草稿)
            ch1 = chapter_service.create(bk["id"], 1, title="第1章")
            chapter_service.update(ch1["id"], word_count=2000, status="generated")
            ch2 = chapter_service.create(bk["id"], 2, title="第2章")
            chapter_service.update(ch2["id"], word_count=1800, status="generated")
            ch3 = chapter_service.create(bk["id"], 3, title="第3章")
            chapter_service.update(ch3["id"], word_count=100, status="draft")  # 草稿不计数

            # 调刷新
            from app.ui import screen_adapter as _sa
            _sa.ScreenAdapter.attach = lambda self, w: None
            from app.ui.main_window import MainWindow
            mw = MainWindow()
            try:
                mw._set_current_project({
                    "id": proj["id"],
                    "name": proj["name"],
                    "book_title": proj["book_title"],
                    "word_target": 75_000,
                })
                check(mw.lbl_progress_text.text() == "2/30 章",
                      f"完成 2/30 章 (实际 {mw.lbl_progress_text.text()!r})")
                check(mw.progress_bar.maximum() == 30, f"max = 30 (实际 {mw.progress_bar.maximum()})")
                check(mw.progress_bar.value() == 2, f"value = 2 (实际 {mw.progress_bar.value()})")
            finally:
                mw.close()
        finally:
            app_paths.set_data_dir_override(None)


# ============================================================
# H. _set_current_project 触发刷新
# ============================================================
def test_h_set_current_triggers_refresh() -> None:
    section("[H] _set_current_project 触发 _refresh_project_progress")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    from app.ui import screen_adapter as _sa
    _sa.ScreenAdapter.attach = lambda self, w: None
    from app.ui.main_window import MainWindow
    mw = MainWindow()
    try:
        called = {"n": 0}
        real_refresh = mw._refresh_project_progress
        def spy():
            called["n"] += 1
            return real_refresh()
        mw._refresh_project_progress = spy

        # None
        mw._set_current_project(None)
        check(called["n"] == 1, "set_current_project(None) 触发 refresh")

        # dict
        mw._set_current_project({"id": "x", "name": "X", "word_target": 100000})
        check(called["n"] == 2, "set_current_project(dict) 触发 refresh")
    finally:
        mw.close()


def main() -> int:
    # 顶部 init DB (后续 MainWindow 创建需要)
    from PySide6.QtWidgets import QApplication
    qa = QApplication.instance() or QApplication(sys.argv)
    from app.services import db as _svc_db
    try:
        _svc_db.init_db()
    except Exception as e:
        print(f"[WARN] init_db 失败: {e}")

    test_a_dialog_widgets()
    test_b_required_validation()
    test_c_result_structure()
    test_d_label_id_conversion()
    test_e_titlebar_widgets()
    test_f_refresh_no_project()
    test_g_refresh_with_data()
    test_h_set_current_triggers_refresh()

    print()
    print("=" * 60)
    print(f"PASS: {_pass}    FAIL: {_fail}")
    print("=" * 60)
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
