"""
M5 SMOKE: 单元池 UI + 成稿向导集成 (QTest, offscreen)

测点:
- UnitPoolWidget 实例化 + 检索列出池单元
- 「发送到项目」clone_to_project → 项目 story_units 新增行
- 成稿向导 _UnitPoolPickerDialog 列出并可勾选
- AssemblyWizard.set_project 显示已克隆的单元

5 分钟超时 (threading.Timer)
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] M5 smoke 超时, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.db import connection, migrator
from app.services import unit_pool_service as ups
from app.services import project_service
from app.services import story_unit_service_v2 as usvc
from app.ui.widgets.unit_pool_widget import UnitPoolWidget
from app.ui.widgets.assembly_wizard import AssemblyWizard, _UnitPoolPickerDialog


def _setup_db():
    tmpdir = tempfile.mkdtemp(prefix="nw_smoke_m5_")
    db_path = Path(tmpdir) / "test.db"
    import app.app_paths as _ap
    _ap.sqlite_path = lambda: str(db_path)
    connection.init(db_path)
    conn = connection.get_conn()
    schema_sql = (ROOT / "app" / "db" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    migrator.run_migrations()
    return tmpdir


def main() -> int:
    fails = []
    passed = 0
    def check(cond, msg):
        nonlocal passed
        if cond:
            passed += 1
            print(f"  [PASS] {msg}")
        else:
            fails.append(msg)
            print(f"  [FAIL] {msg}")

    app = QApplication.instance() or QApplication([])

    print("=" * 60)
    print("M5 SMOKE: 单元池 UI + 向导集成")
    print("=" * 60)

    tmpdir = _setup_db()

    # 种子池单元
    u1 = ups.create("林间初遇", "暮色里少年与少女在林间初次相遇。", genre="仙侠", emotion="悸动")
    u2 = ups.create("山门比试", "擂台之上剑光交错，少年以巧破力。", genre="仙侠", scene_type="战斗")
    check(ups.count() == 2, f"种子池 2 条 (实际 {ups.count()})")

    # 项目
    proj = project_service.create("M5测试项目", book_title="M5书", create_books=True)
    pid = proj["id"]

    # 1) Widget 列出
    print("\n[1] UnitPoolWidget 检索")
    w = UnitPoolWidget()
    w.set_project(pid)
    w.refresh()
    check(w._list.count() == 2, f"列表显示 2 条 (实际 {w._list.count()})")

    # 2) 发送到项目 (克隆) — 选中 u1 对应的列表项 (列表按 created_at 倒序)
    print("\n[2] 发送到项目 (clone_to_project)")
    target_row = -1
    for i in range(w._list.count()):
        if w._list.item(i).data(Qt.UserRole) == u1["id"]:
            target_row = i
            break
    check(target_row >= 0, "在列表中找到 u1 项")
    w._list.item(target_row).setSelected(True)   # 选中 (clone 依赖 isSelected)
    w._on_send()
    units = usvc.list_for_project(pid)
    check(len(units) == 1, f"项目 story_units 新增 1 行 (实际 {len(units)})")
    print(f"  [INFO] draft={units[0].draft!r}  pool_content={u1['content']!r}")
    check(units[0].draft == u1["content"], "克隆单元 draft 与池内容一致")

    # 3) 向导池选择器
    print("\n[3] 成稿向导 单元池选择器")
    dlg = _UnitPoolPickerDialog()
    dlg._do_search()
    check(dlg._list.count() == 2, f"选择器列出 2 条 (实际 {dlg._list.count()})")
    u2_row = -1
    for i in range(dlg._list.count()):
        if dlg._list.item(i).data(Qt.UserRole) == u2["id"]:
            u2_row = i
            break
    check(u2_row >= 0, "在选择器中找到 u2 项")
    dlg._list.item(u2_row).setSelected(True)
    sel = dlg.selected_ids()
    check(len(sel) == 1 and sel[0] == u2["id"], "勾选返回正确 pool_id")

    # 4) 向导 set_project 显示已克隆单元
    print("\n[4] AssemblyWizard.set_project")
    aw = AssemblyWizard()
    aw.set_project(pid)
    check(aw._unit_list.count() == 1, f"向导单元列表 1 条 (实际 {aw._unit_list.count()})")

    # 清理
    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass

    print("\n" + "=" * 60)
    if not fails:
        print(f"M5 SMOKE PASS ({passed} assertions)")
        return 0
    else:
        print(f"M5 SMOKE FAIL ({len(fails)} failed):")
        for f in fails:
            print(f"  - {f}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
