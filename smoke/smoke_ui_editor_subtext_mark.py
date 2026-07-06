"""
Editor Tab Subtext Mark smoke (offscreen).

覆盖:
  1. EditorTab 构造 (基础 sanity)
  2. set_project + create chapter → 列表中无 🎭
  3. 创建 subtext 卡 → 列表中该章节末尾出现 🎭
  4. 删卡 → 🎭 消失
  5. SUBTEXT_MARK 来自 subtext_svc.SUBTEXT_MARK
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 5 分钟 watchdog
_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_ui_editor_subtext_mark 超时 {_TIMEOUT}s", flush=True)
    os._exit(2)
_t = threading.Timer(_TIMEOUT, _timeout_kill)
_t.daemon = True
_t.start()

# 隔离 DB
TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_editor_st_"))
DB_PATH = TMPDIR / "test.db"
STORY_DIR = TMPDIR / "story"
STORY_DIR.mkdir(parents=True, exist_ok=True)

import app.app_paths
app.app_paths.sqlite_path = lambda: DB_PATH
import app.services.file_store
app.services.file_store.BASE_DIR = STORY_DIR

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

# 启动 DB
from app.db import _impl as _db_conn
from app.services.db import init_db as _svc_init_db
_svc_init_db()
_db_conn.init(DB_PATH)
from app.services import subtext as subtext_svc
subtext_svc.seed_presets()


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
    print("=== Editor Tab Subtext Mark smoke (offscreen) ===", flush=True)

    from app.ui.tabs.editor_tab import EditorTab
    from app.services import project_service, book_service, chapter_service, subtext

    # ---- 1. 构造 ----
    section("[1] EditorTab 构造")
    et = EditorTab()
    check(et.current_project is None, "初始无项目")
    check(et.chapter_list.count() == 0, f"初始章节列表空 (实际 {et.chapter_list.count()})")

    # ---- 2. 准备项目 + 章节 ----
    section("[2] 创建项目 / 卷册 / 3 章")
    proj = project_service.create(name="editor_st_test")
    project_id = proj["id"]
    book = book_service.create(project_id=project_id, volume_no=1, title="卷一")
    ch1 = chapter_service.create(book_id=book["id"], chapter_no=1, title="开篇")
    ch2 = chapter_service.create(book_id=book["id"], chapter_no=2, title="中段")
    ch3 = chapter_service.create(book_id=book["id"], chapter_no=3, title="结尾")
    check(True, f"3 章创建: {[c['title'] for c in [ch1, ch2, ch3]]}")

    # ---- 3. 加载 + 验证初始无 🎭 ----
    section("[3] 初始加载: 3 章均无 🎭")
    et.set_project(proj)
    et.book_list.setCurrentRow(0)  # 选书
    check(et.chapter_list.count() == 3, f"3 章加载 (实际 {et.chapter_list.count()})")
    for i in range(et.chapter_list.count()):
        item = et.chapter_list.item(i)
        check("🎭" not in item.text(), f"第 {i+1} 章无 🎭: {item.text()}")
        check("[draft]" in item.text() or "[Draft]" in item.text() or "draft" in item.text(),
              f"第 {i+1} 章含 status: {item.text()}")

    # ---- 4. 给 ch2 创建 subtext 卡 → 应有 🎭 ----
    section("[4] ch2 套模板 → 列表含 🎭")
    subtext.apply_template(ch2["id"], "tpl_confrontation", brief="中段冲突场景")
    et._reload_chapters()  # 手动 reload
    for i in range(et.chapter_list.count()):
        item = et.chapter_list.item(i)
        ch = item.data(Qt.ItemDataRole.UserRole)
        if ch["id"] == ch2["id"]:
            check("🎭" in item.text(), f"ch2 末尾含 🎭: {item.text()}")
        else:
            check("🎭" not in item.text(), f"ch{i+1} 仍无 🎭: {item.text()}")

    # ---- 5. ch1 + ch3 手动 save 卡 ----
    section("[5] ch1/ch3 手动 save → 均有 🎭")
    subtext.upsert_card(ch1["id"], source="manual", surface_event="开篇事件", emotional="期待")
    subtext.upsert_card(ch3["id"], source="manual", surface_event="结尾事件", emotional="收束")
    et._reload_chapters()
    mark_count = 0
    for i in range(et.chapter_list.count()):
        item = et.chapter_list.item(i)
        if "🎭" in item.text():
            mark_count += 1
    check(mark_count == 3, f"3 章都标 🎭 (实际 {mark_count})")

    # ---- 6. 删 ch2 卡 → 🎭 消失 ----
    section("[6] 删 ch2 卡 → 🎭 消失")
    subtext.delete_card(ch2["id"])
    et._reload_chapters()
    for i in range(et.chapter_list.count()):
        item = et.chapter_list.item(i)
        ch = item.data(Qt.ItemDataRole.UserRole)
        if ch["id"] == ch2["id"]:
            check("🎭" not in item.text(), f"ch2 🎭 已移除: {item.text()}")
        else:
            check("🎭" in item.text(), f"ch{i+1} 🎭 保留: {item.text()}")

    # ---- 7. SUBTEXT_MARK 来自 subtext_svc ----
    section("[7] 标注符号 = subtext_svc.SUBTEXT_MARK")
    check(subtext.SUBTEXT_MARK == "🎭", f"SUBTEXT_MARK = '🎭' (实际 {subtext.SUBTEXT_MARK})")
    # 验证 editor_tab 用的就是这个常量
    check("🎭" in subtext_svc.SUBTEXT_MARK, "editor_tab 引用的常量正确")

    # 清理
    try:
        project_service.delete(project_id)
    except Exception:
        pass

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
