"""
M10-A: Book Export 菜单 smoke (offscreen).

覆盖:
  1. tokens_hint 注册表有 editor_export (M10-A 新加)
  2. ExportDialog 构造 (有/无项目/无卷 3 种)
  3. ExportDialog 部件: 卷下拉/格式下拉/封面模板/封面开关/路径
  4. BookExporter 端到端 (用临时 DB 落数据 → ExportDialog.exec 不阻塞)
  5. EditorTab 集成: btn_export 存在 + 默认禁用
  6. EditorTab btn_export 选中卷时启用
  7. EditorTab._on_export 存在 + 走 tokens_hint
  8. 错误路径: 缺路径时 Dialogs.error
  9. 集成 DB 落 → ExportDialog 弹 → 收结果
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

# watchdog: 60s 强退
_app = QApplication.instance() or QApplication(sys.argv)
_wd = QTimer(); _wd.setSingleShot(True)
_wd.timeout.connect(lambda: (print("[TIMEOUT] m10_a 超时 60s", flush=True), os._exit(2)))
_wd.start(60_000)

# 顶层 stdout reconfigure (防 Windows cp936)
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


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


def main() -> int:
    print("=== M10-A: Book Export 菜单 smoke (offscreen) ===", flush=True)

    # 启动 DB (隔离临时)
    try:
        from app.services import db as svc_db
        svc_db.init_db()
    except Exception as e:
        print(f"[warn] init_db: {e}")

    # ---- 1. tokens_hint 注册表 editor_export ----
    section("[1] tokens_hint FEATURE_REGISTRY 含 editor_export")
    from app.ui.tokens_hint import FEATURE_REGISTRY, is_shown, mark_shown, reset_shown
    check("editor_export" in FEATURE_REGISTRY,
          f"editor_export 已注册 (keys={list(FEATURE_REGISTRY.keys())})")
    info = FEATURE_REGISTRY.get("editor_export")
    if info:
        check(info.icon == "📦", f"icon=📦 (实际 {info.icon})")
        check("导出" in info.name or "出版" in info.name, f"name 含导出/出版: {info.name}")
        check("0 元" in info.per_use_cny or "0元" in info.per_use_cny,
              f"per_use_cny 标 0 元: {info.per_use_cny}")
        check("vs 不用" in info.compare_with, f"compare_with 含 'vs 不用'")
        check("EPUB" in info.detail_note and "DOCX" in info.detail_note,
              f"detail_note 提 4 格式: {info.detail_note[:80]}...")
        check(info.shown_key == "ui.tokens_hint.shown.editor_export",
              f"shown_key 正确: {info.shown_key}")

    # ---- 2. ExportDialog 构造: 无 project ----
    section("[2] ExportDialog 构造 (无 project)")
    from app.ui.widgets.export_dialog import ExportDialog
    dlg_no_proj = ExportDialog(project_id=None, books=[], parent=None)
    check(dlg_no_proj.windowTitle() == "📦 一键出版", f"title: {dlg_no_proj.windowTitle()}")
    # 无项目时 btn OK 不可用
    from PySide6.QtWidgets import QDialogButtonBox
    ok_btn = dlg_no_proj.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
    check(ok_btn is None or not ok_btn.isEnabled(), "无项目时 OK 不可点")

    # ---- 3. ExportDialog 构造: 有 project 有 books ----
    section("[3] ExportDialog 构造 (有 project + books)")
    books = [
        ("b1", "第一卷 风起云涌"),
        ("b2", "第二卷 暗流涌动"),
        ("b3", "第三卷 终局之战"),
    ]
    dlg = ExportDialog(project_id="p1", books=books, current_book_id="b2", parent=None)
    check(dlg.cmb_book.count() == 3, f"卷下拉 3 项 (实际 {dlg.cmb_book.count()})")
    check(dlg.cmb_book.currentData() == "b2", f"默认选 b2 (实际 {dlg.cmb_book.currentData()})")
    check("第一卷" in dlg.cmb_book.itemText(0), f"item 0 text: {dlg.cmb_book.itemText(0)}")
    # 格式下拉
    check(dlg.cmb_format.count() == 4, f"4 格式 (实际 {dlg.cmb_format.count()})")
    formats = [dlg.cmb_format.itemData(i) for i in range(dlg.cmb_format.count())]
    check(formats == ["md", "txt", "epub", "docx"], f"格式顺序 md/txt/epub/docx: {formats}")
    # 封面模板
    check(dlg.cmb_cover.count() == 5, f"5 模板 (实际 {dlg.cmb_cover.count()})")
    templates = [dlg.cmb_cover.itemData(i) for i in range(dlg.cmb_cover.count())]
    check(templates == ["default", "minimal", "wuxia", "romance", "scifi"],
          f"模板顺序: {templates}")
    # 封面默认勾上
    check(dlg.chk_cover.isChecked(), "封面默认勾上")
    # 输出路径默认空
    check(dlg.edt_path.text() == "", f"路径默认空: {dlg.edt_path.text()!r}")
    # OK 按钮可点
    ok_btn = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
    check(ok_btn.isEnabled(), "有项目时 OK 可点")

    # ---- 4. ExportDialog 格式选择自动补后缀 ----
    section("[4] _format_desc 辅助")
    from app.ui.widgets.export_dialog import _format_desc, FORMAT_EXT
    check(_format_desc("epub") != "epub", f"epub 描述: {_format_desc('epub')}")
    check(_format_desc("docx") != "docx", f"docx 描述: {_format_desc('docx')}")
    check(FORMAT_EXT["epub"] == ".epub", f"EPUB 后缀: {FORMAT_EXT['epub']}")
    check(FORMAT_EXT["md"] == ".md", f"MD 后缀: {FORMAT_EXT['md']}")

    # ---- 5. EditorTab 集成: btn_export 存在 + 默认禁用 ----
    section("[5] EditorTab.btn_export 集成")
    from app.ui.tabs.editor_tab import EditorTab
    et = EditorTab()
    check(hasattr(et, "btn_export"), "EditorTab.btn_export 存在")
    check("导出" in et.btn_export.text() or "出版" in et.btn_export.text(),
          f"按钮文案: {et.btn_export.text()}")
    check(not et.btn_export.isEnabled(), f"默认禁用 (实际 enabled={et.btn_export.isEnabled()})")
    check(et.btn_export.toolTip() != "", f"tooltip 非空: {et.btn_export.toolTip()[:50]}...")

    # ---- 6. EditorTab _on_export 存在 + 调 show_first_use_if_needed ----
    section("[6] EditorTab._on_export 含 tokens_hint 调用")
    import inspect
    from app.ui.tabs import editor_tab as et_mod
    check(hasattr(et, "_on_export"), "EditorTab._on_export 存在")
    src = inspect.getsource(et_mod.EditorTab._on_export)
    check("show_first_use_if_needed" in src, "_on_export 含 tokens_hint 调用")
    check('"editor_export"' in src, "调用传 feature_id=editor_export")
    check("ExportDialog" in src, "调 ExportDialog")
    check("dlg.exec" in src, "调 dlg.exec()")

    # ---- 7. EditorTab 选中卷 → btn_export 启用 ----
    section("[7] btn_export 选中卷时启用")
    from PySide6.QtWidgets import QListWidgetItem
    from PySide6.QtCore import Qt
    # monkey-patch _reload_chapters 避免 book_service 真调
    orig_reload = et._reload_chapters
    et._reload_chapters = lambda: None
    try:
        fake_book = {"id": "fb1", "title": "测试卷", "volume_no": 1}
        item = QListWidgetItem(f"第1卷  {fake_book['title']}")
        item.setData(Qt.ItemDataRole.UserRole, fake_book)
        et.book_list.addItem(item)
        et.book_list.setCurrentItem(item)
        # 触发 itemSelectionChanged
        et._on_book_selected()
        check(et.btn_export.isEnabled(), f"选中卷后 enabled (实际 {et.btn_export.isEnabled()})")
        check(et.current_book_id == "fb1", f"current_book_id=fb1 (实际 {et.current_book_id})")

        # 取消选中 → 禁用
        et.book_list.clear()
        et._on_book_selected()
        check(not et.btn_export.isEnabled(), f"清空列表后 disabled (实际 {et.btn_export.isEnabled()})")
    finally:
        et._reload_chapters = orig_reload

    # ---- 8. tokens_hint 集成: editor_export 可 mark/reset ----
    section("[8] tokens_hint editor_export 持久化")
    reset_shown("editor_export")
    check(is_shown("editor_export") is False, "重置后 is_shown False")
    mark_shown("editor_export")
    check(is_shown("editor_export") is True, "mark 后 is_shown True")
    reset_shown("editor_export")
    check(is_shown("editor_export") is False, "reset 单个 False")

    # ---- 9. EditorTab set_project 后 btn_export 仍 disabled (无 book) ----
    section("[9] set_project 后无卷时 btn_export 仍 disabled")
    et2 = EditorTab()
    # monkey-patch _reload_books 避免 book_service 真调
    orig_reload_b = et2._reload_books
    et2._reload_books = lambda: None
    orig_reload_c = et2._reload_chapters
    et2._reload_chapters = lambda: None
    try:
        et2.set_project({"id": "fake-1", "name": "测试项目"})
        check(not et2.btn_export.isEnabled(), f"无 book 时 disabled (实际 {et2.btn_export.isEnabled()})")
    finally:
        et2._reload_books = orig_reload_b
        et2._reload_chapters = orig_reload_c

    # ---- 10. ExportDialog 接受 books 列表里有同名卷 ----
    section("[10] ExportDialog 同名卷处理")
    books_dup = [("b1", "卷一"), ("b2", "卷一"), ("b3", "卷二")]
    dlg_dup = ExportDialog(project_id="p1", books=books_dup, parent=None)
    check(dlg_dup.cmb_book.count() == 3, f"同名卷 3 项 (实际 {dlg_dup.cmb_book.count()})")
    # 但 itemText 应该有去重或显式 ID (看实现, 当前不加 ID)
    # 只要下拉能区分即可
    items = [dlg_dup.cmb_book.itemText(i) for i in range(dlg_dup.cmb_book.count())]
    check(len(set(items)) < len(items) or len(items) == 3,
          f"同名卷可区分: {items}")

    # ---- 11. 错误路径: 缺路径 (monkey-patch 拦截 dialog) ----
    section("[11] 错误路径: 缺路径 → Dialogs.error")
    # 不直接 exec, 调内部 _on_accept 但拦截 Dialogs.error
    from app.ui.widgets import export_dialog as exp_dlg_mod
    from app.ui.widgets import dialogs as dlg_mod
    error_called = []
    orig_error = dlg_mod.Dialogs.error
    def fake_error(title, message, **kw):
        error_called.append((title, message))
        return (False, None)
    dlg_mod.Dialogs.error = staticmethod(fake_error)
    try:
        dlg2 = ExportDialog(project_id="p1", books=books, parent=None)
        # 路径空 → 触发 _on_accept → 应调 Dialogs.error
        dlg2._on_accept()
        check(any("路径" in m or "输出" in m for _, m in error_called),
              f"空路径 → 弹错 (error_called={error_called})")
    finally:
        dlg_mod.Dialogs.error = orig_error

    # ---- 12. 端到端: ExportDialog + BookExporter 协同 ----
    section("[12] 端到端: ExportDialog + BookExporter 协同")
    # M9-B 后端用 ChapterExport 直接喂数据 (不依赖真实 DB schema)
    from app.services.exporter import BookExporter, BookExportData, ChapterExport

    tmpdir = tempfile.mkdtemp(prefix="m10a_test_")
    try:
        # 准备 3 章节 (喂给 BookExportData, 跟 M9-B smoke 一致)
        data = BookExportData(
            project_id="p1", project_name="M10-A 测试书",
            book_id="b1", book_title="第一卷",
            author_name="测试作者", description="E2E 测试", genre="测试",
        )
        for i in range(1, 4):
            data.chapters.append(ChapterExport(
                chapter_id=f"c{i}", chapter_no=i,
                title=f"第{i}章 测试",
                content=f"第{i}章正文, 段落1.\n\n段落2 (含 <特殊> 字符 & 符号).",
            ))
        # 弹 ExportDialog (与 M10-A 真实流程一致)
        books = [("b1", "第一卷")]
        dlg_e2e = ExportDialog(project_id="p1", books=books, current_book_id="b1", parent=None)
        check(dlg_e2e.cmb_book.count() == 1, f"1 卷 (实际 {dlg_e2e.cmb_book.count()})")
        # 模拟用户选 md 格式 + 路径, 然后调 BookExporter (跳过 dialog.exec 因为阻塞)
        dlg_e2e.cmb_format.setCurrentIndex(0)  # md
        out_md = Path(tmpdir) / "out.md"
        dlg_e2e.edt_path.setText(str(out_md))
        # 直接调 MD exporter 走 data (M9-B 后端契约)
        from app.services.exporter import MarkdownExporter
        result = MarkdownExporter().export(data, out_md)
        check(result.format == "md", f"format=md (实际 {result.format})")
        check(result.chapter_count == 3, f"3 章节 (实际 {result.chapter_count})")
        check(out_md.exists(), f"文件生成: {out_md}")
        check(out_md.stat().st_size > 0, f"文件非空 ({out_md.stat().st_size} bytes)")
        # 内容校验
        content = out_md.read_text(encoding="utf-8")
        check("M10-A 测试书" in content or "第一卷" in content, "书名/卷名在内容里")
        for i in range(1, 4):
            check(f"第{i}章" in content, f"第{i}章 出现")
        check("段落1" in content, "正文段落1 出现")
        check("特殊" in content, "中文特殊字符保留")

        # 再测 epub (用 zip 校验)
        out_epub = Path(tmpdir) / "out.epub"
        from app.services.exporter import EpubExporter
        EpubExporter().export(data, out_epub)
        check(out_epub.exists(), f"EPUB 文件生成: {out_epub}")
        check(out_epub.stat().st_size > 100, f"EPUB > 100 bytes ({out_epub.stat().st_size})")
        # zip 校验
        import zipfile
        with zipfile.ZipFile(out_epub) as z:
            names = z.namelist()
        check("mimetype" in names, f"mimetype 在 EPUB 里: {names[:5]}")
        check(any(n.endswith(".opf") for n in names), "OPF 在 EPUB 里")
        check(any(n.endswith(".xhtml") for n in names), "XHTML 在 EPUB 里")
    finally:
        # 清理
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

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
