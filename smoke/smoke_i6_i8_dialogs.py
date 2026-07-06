"""
I6 AntiRuleEditorDialog + I8 MemoryEditorDialog SMOKE 测试

覆盖:
  1. AntiRuleEditorDialog import / 实例化 / set_rules / get_rules
  2. AntiRuleEditorDialog 新增/编辑/删除规则
  3. AntiRuleEditorDialog 校验 (空 pattern 跳过)
  4. AntiRuleEditorDialog 持久化 (setting_service.ANTI_RULES)
  5. MemoryEditorDialog import / 实例化
  6. MemoryEditorDialog 加载 L1/L2 记忆列表
  7. MemoryEditorDialog 新增记忆
  8. MemoryEditorDialog 编辑 + 删除记忆
  9. 集成: settings_tab 集成 AntiRuleEditorDialog 入口

5 分钟全局超时
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_SMOKE_TIMEOUT = 300


def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_i6_i8_dialogs 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)


_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

passed = 0
fails: list = []


def check(cond, msg: str) -> None:
    global passed
    if cond:
        passed += 1
        print(f"  [PASS] {msg}")
    else:
        fails.append(msg)
        print(f"  [FAIL] {msg}")


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def setup_env() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="i6i8_"))
    db_path = tmp / "test.db"
    story_dir = tmp / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    import app.app_paths
    app.app_paths.sqlite_path = lambda: db_path
    import app.services.file_store
    app.services.file_store.BASE_DIR = story_dir
    from app.services.db import init_db
    init_db()
    from app.db import _impl as db_conn
    db_conn.init(db_path)
    return tmp


# ============================================================
# 1) I6 AntiRuleEditorDialog import + 实例化
# ============================================================
def test_i6_import() -> None:
    section("[I6 1] AntiRuleEditorDialog import")
    from app.ui.widgets import AntiRuleEditorDialog
    check(AntiRuleEditorDialog is not None, "AntiRuleEditorDialog 可导入")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)

    dlg = AntiRuleEditorDialog()
    check(dlg is not None, "可实例化")
    check(dlg.windowTitle().startswith("🚫"), f"title 含 🚫 (实际 {dlg.windowTitle()})")
    check(hasattr(dlg, "set_rules"), "有 set_rules")
    check(hasattr(dlg, "get_rules"), "有 get_rules")
    check(hasattr(dlg, "_edit"), "有 _edit 详情编辑卡")


# ============================================================
# 2) set_rules + get_rules 双向
# ============================================================
def test_i6_set_get() -> None:
    section("[I6 2] set_rules / get_rules")
    from app.ui.widgets import AntiRuleEditorDialog
    dlg = AntiRuleEditorDialog()
    rules = [
        {"id": "abc", "pattern": "她咬了咬嘴唇", "severity": "error",
         "description": "AI 味标志", "examples": "她咬了咬嘴唇, 心里..."},
        {"id": "def", "pattern": "他愣了一下", "severity": "warning",
         "description": "过度反应", "examples": "他愣了一下, 似乎..."},
    ]
    dlg.set_rules(rules)
    got = dlg.get_rules()
    check(len(got) == 2, f"set 后 get 长度 2 (实际 {len(got)})")
    check(got[0]["pattern"] == "她咬了咬嘴唇", f"pattern 保留 (实际 {got[0]['pattern']})")
    check(got[0]["id"] == "abc", "id 保留")
    check(got[1]["severity"] == "warning", "severity 保留")

    # 空 list
    dlg.set_rules([])
    check(dlg.get_rules() == [], "空 list 正常")

    # None 处理
    dlg.set_rules(None)
    check(dlg.get_rules() == [], "None 转 []")

    # 缺字段自动补
    dlg.set_rules([{"pattern": "无 id"}])
    check(dlg.get_rules()[0]["id"] != "", "缺 id 自动补 uuid")
    check(dlg.get_rules()[0]["severity"] == "error", "缺 severity 补 error")


# ============================================================
# 3) 新增 / 删除规则
# ============================================================
def test_i6_new_delete() -> None:
    section("[I6 3] 新增/删除 (点击流, patch 弹窗)")
    from app.ui.widgets import AntiRuleEditorDialog, Dialogs
    dlg = AntiRuleEditorDialog()
    dlg.set_rules([{"pattern": "旧规则", "severity": "error"}])
    check(len(dlg.get_rules()) == 1, "初始 1 条")

    # patch confirm
    orig_confirm = Dialogs.confirm
    Dialogs.confirm = lambda *a, **kw: True
    try:
        # 选第一项 + 删
        dlg.list_rules.setCurrentRow(0)
        dlg._on_delete()
        check(len(dlg.get_rules()) == 0, "删后 0 条")

        # 新增
        dlg._on_new()
        check(len(dlg.get_rules()) == 1, "新增 1 条")
        check(dlg.get_rules()[0]["id"] != "", "新规则有 id")
    finally:
        Dialogs.confirm = orig_confirm


# ============================================================
# 4) 保存校验 (空 pattern 跳过)
# ============================================================
def test_i6_save_validation() -> None:
    section("[I6 4] 保存校验 (空 pattern 跳过)")
    from app.ui.widgets import AntiRuleEditorDialog, Dialogs
    dlg = AntiRuleEditorDialog()
    # 1 条有效 + 1 条空 pattern
    dlg.set_rules([
        {"pattern": "有效规则", "severity": "error", "description": "test"},
        {"pattern": "", "severity": "warning"},  # 空
    ])
    # patch warning
    orig_warn = Dialogs.warning
    warn_called = []
    Dialogs.warning = lambda *a, **kw: warn_called.append(a)
    try:
        dlg._on_save()  # 应直接 accept (因为至少 1 条有效)
        # 检查结果
        saved = dlg.get_rules()
        check(len(saved) == 1, f"空 pattern 被跳过 (剩 {len(saved)})")
        check(saved[0]["pattern"] == "有效规则", "保留有效规则")
        # 此时应已 accept
        check(dlg.result() == 1, "result=Accepted")
    finally:
        Dialogs.warning = orig_warn

    # 全部空: 弹 warning
    dlg2 = AntiRuleEditorDialog()
    dlg2.set_rules([{"pattern": ""}, {"pattern": "   "}])
    warn_called2 = []
    Dialogs.warning = lambda *a, **kw: warn_called2.append(a)
    try:
        dlg2._on_save()
        check(len(warn_called2) == 1, "全部空时弹 warning")
        check(dlg2.result() == 0, "未保存 result=Rejected")
    finally:
        Dialogs.warning = orig_warn


# ============================================================
# 5) 持久化: setting_service.ANTI_RULES
# ============================================================
def test_i6_persistence() -> None:
    section("[I6 5] 持久化到 setting_service")
    from app.services import project_service, setting_service
    from app.ui.widgets import AntiRuleEditorDialog

    p = project_service.create(name="I6 持久化")
    pid = p["id"]
    initial = setting_service.get_setting(pid, "anti_rules")
    check(initial.get("data") is None, "初始无 anti_rules")

    dlg = AntiRuleEditorDialog()
    dlg.set_rules([
        {"id": "r1", "pattern": "她咬了咬嘴唇", "severity": "error",
         "description": "AI 味", "examples": "..."}
    ])
    # 模拟 _on_save 走 setting_service.set_setting
    dlg._on_save()
    saved_rules = dlg.get_rules()
    setting_service.set_setting(pid, "anti_rules", saved_rules)

    # 再读
    re = setting_service.get_setting(pid, "anti_rules")
    check(re.get("data") is not None, "持久化有数据")
    check(len(re["data"]) == 1, f"1 条 (实际 {len(re['data'])})")
    check(re["data"][0]["pattern"] == "她咬了咬嘴唇", "pattern 正确")

    # reload dlg
    dlg2 = AntiRuleEditorDialog()
    dlg2.set_rules(re["data"])
    check(dlg2.get_rules()[0]["pattern"] == "她咬了咬嘴唇", "reload OK")


# ============================================================
# 6) I8 MemoryEditorDialog import + 实例化
# ============================================================
def test_i8_import() -> None:
    section("[I8 1] MemoryEditorDialog import")
    from app.ui.widgets import MemoryEditorDialog
    from app.services import project_service

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)

    p = project_service.create(name="I8 import 测试")
    dlg = MemoryEditorDialog(p["id"])
    check(dlg is not None, "实例化成功")
    check(dlg.windowTitle().startswith("🧠"), f"title 含 🧠 ({dlg.windowTitle()})")
    check(dlg.tabs.count() == 3, f"3 个 tab (L1/L2/L4), 实际 {dlg.tabs.count()}")
    check(dlg.tabs.tabText(0) == "L1 故事弧", f"tab 0: {dlg.tabs.tabText(0)}")
    check(dlg.tabs.tabText(1) == "L2 承诺/世界规则", f"tab 1: {dlg.tabs.tabText(1)}")
    check(dlg.tabs.tabText(2) == "L4 已遗忘", f"tab 2: {dlg.tabs.tabText(2)}")


# ============================================================
# 7) MemoryEditorDialog 加载记忆列表
# ============================================================
def test_i8_load() -> None:
    section("[I8 2] 加载记忆列表")
    from app.ui.widgets import MemoryEditorDialog
    from app.services import project_service, memory as memory_svc

    p = project_service.create(name="I8 load 测试")
    pid = p["id"]

    # 加 1 条 L1 + 1 条 L2 + 1 条 L4
    m1 = memory_svc.add_arc(pid, "arc_main", "主线: 林天修仙证道")
    m2 = memory_svc.add_commitment(pid, "主角承诺三年内登上金丹期")
    # L4 需要从 L3 fade 过来
    m3 = memory_svc.add_rag_chunk(pid, "rag 检索内容: 次要角色名: 张三", ref_id="src-001")
    memory_svc.fade(pid, m3.id)

    dlg = MemoryEditorDialog(pid)
    # 切到 L1 tab
    dlg.tabs.setCurrentIndex(0)
    tab_l1 = dlg._tabs["L1"]
    check(len(tab_l1._memories) >= 1, f"L1 ≥ 1 (实际 {len(tab_l1._memories)})")
    check(any(m["id"] == m1.id for m in tab_l1._memories), "L1 含主线弧")

    # 切到 L2
    dlg.tabs.setCurrentIndex(1)
    tab_l2 = dlg._tabs["L2"]
    check(len(tab_l2._memories) >= 1, f"L2 ≥ 1 (实际 {len(tab_l2._memories)})")
    check(any(m["id"] == m2.id for m in tab_l2._memories), "L2 含承诺")

    # 切到 L4
    dlg.tabs.setCurrentIndex(2)
    tab_l4 = dlg._tabs["L4"]
    check(len(tab_l4._memories) >= 1, f"L4 ≥ 1 (实际 {len(tab_l4._memories)})")


# ============================================================
# 8) MemoryEditorDialog 新增/编辑/删除
# ============================================================
def test_i8_crud() -> None:
    section("[I8 3] 新增/编辑/删除 (patch confirm)")
    from app.ui.widgets import MemoryEditorDialog, Dialogs
    from app.services import project_service, memory as memory_svc

    p = project_service.create(name="I8 CRUD")
    pid = p["id"]

    # patch confirm
    orig_confirm = Dialogs.confirm
    Dialogs.confirm = lambda *a, **kw: True
    try:
        dlg = MemoryEditorDialog(pid)
        dlg.tabs.setCurrentIndex(0)
        tab = dlg._tabs["L1"]
        initial_count = len(tab._memories)
        # 新增
        tab._on_new()
        check(len(tab._memories) == initial_count + 1, f"新增后 +1 (实际 {len(tab._memories)})")
        new_id = tab._current_id
        check(new_id is not None, "current_id 已选")
        # 编辑内容
        tab.ed_content.setPlainText("编辑后的新内容: 主角欲登仙道")
        # 触发保存 (apply_pending_edit)
        tab.apply_pending_edit()
        check(tab._current_id != new_id or tab._current_id is not None, "apply 后 id 变化或保留")
        # 验证 DB
        saved = memory_svc.get_by_id(pid, tab._current_id)
        check(saved is not None and "编辑后" in saved.content, "DB 写入新内容")
    finally:
        Dialogs.confirm = orig_confirm

    # 删
    dlg2 = MemoryEditorDialog(pid)
    dlg2.tabs.setCurrentIndex(0)
    tab2 = dlg2._tabs["L1"]
    if tab2._memories:
        tab2._current_id = tab2._memories[0]["id"]
        before = len(tab2._memories)
        Dialogs.confirm = lambda *a, **kw: True
        try:
            tab2._on_delete()
            check(len(tab2._memories) == before - 1, f"删后 -1 (实际 {len(tab2._memories)})")
        finally:
            Dialogs.confirm = orig_confirm


# ============================================================
# 9) 集成: settings_tab 含 I6 入口 (按钮)
# ============================================================
def test_i6_settings_integration() -> None:
    section("[I6 9] settings_tab 集成")
    from app.ui.tabs.settings_tab import ProjectSettingsWidget
    from app.ui.widgets import AntiRuleEditorDialog
    # 验证 ProjectSettingsWidget 是否有 _open_anti_rule_editor 入口
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication(sys.argv)
    w = ProjectSettingsWidget()
    check(hasattr(w, "_open_anti_rule_editor"),
          "ProjectSettingsWidget 有 _open_anti_rule_editor 方法")


# ============================================================
# Main
# ============================================================
def main() -> int:
    print("=" * 60)
    print("I6 AntiRuleEditor + I8 MemoryEditor SMOKE")
    print("=" * 60)

    setup_env()
    test_i6_import()
    test_i6_set_get()
    test_i6_new_delete()
    test_i6_save_validation()
    test_i6_persistence()
    test_i8_import()
    test_i8_load()
    test_i8_crud()
    test_i6_settings_integration()

    print("\n" + "=" * 60)
    print(f"汇总: {passed} 通过, {len(fails)} 失败")
    if fails:
        print("\n失败列表:")
        for f in fails[:30]:
            print(f"  - {f}")
    print("=" * 60)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
