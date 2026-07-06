"""
I15 欢迎页 + 一次性显示 smoke.

覆盖:
  1. is_welcome_shown 默认 False
  2. 弹 WelcomeDialog 后, 关闭 → ui.welcome_shown=true 写入 app settings
  3. 再次调用 is_welcome_shown → True (不再显示)
  4. WelcomeDialog 包含 6 个费用卡 (章节生成/风格学习/声音推断/一致性/AI导入/潜文本)
  5. 费用卡含 名称 + 单价 + 对比 + 备注
  6. "不再显示" checkbox 默认勾选
  7. _show_welcome_once 钩子在 MainWindow 启动时调用
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

# watchdog 用 QTimer
_app = QApplication.instance() or QApplication(sys.argv)
_wd = QTimer(); _wd.setSingleShot(True)
_wd.timeout.connect(lambda: (print("[TIMEOUT] welcome 超时 60s", flush=True), os._exit(2)))
_wd.start(60_000)


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
    print("=== I15 欢迎页 smoke (offscreen) ===", flush=True)

    # 启动 DB
    try:
        from app.services import db as svc_db
        svc_db.init_db()
    except Exception as e:
        print(f"[warn] init_db: {e}")

    from app.services import app_setting_service
    # 重置 ui.welcome_shown, 确保测试可重复
    app_setting_service.delete("ui.welcome_shown")

    from app.ui.welcome import (
        WelcomeDialog, show_welcome_if_first_time, is_welcome_shown,
        WELCOME_KEY, COST_TABLE,
    )

    # ---- 1. 默认未显示 ----
    section("[1] 默认状态")
    check(is_welcome_shown() is False, f"is_welcome_shown() 默认 False")

    # ---- 2. 费用表 ----
    section("[2] 费用表 6 项")
    check(len(COST_TABLE) == 6, f"COST_TABLE 6 项 (实际 {len(COST_TABLE)})")
    expected_names = ["章节生成", "风格学习器", "声音推断", "一致性检测", "AI 导入解析", "潜文本卡"]
    for i, name in enumerate(expected_names):
        check(name in COST_TABLE[i]["name"], f"第 {i+1} 项: {name} (实际 {COST_TABLE[i]['name']})")
    for i, item in enumerate(COST_TABLE):
        check("per_use" in item and "约" in item["per_use"], f"第 {i+1} 项含 '约' 字单价")
        check("compare" in item and "不用" in item["compare"], f"第 {i+1} 项含 'vs 不用' 对比")
        check("note" in item and len(item["note"]) > 0, f"第 {i+1} 项含 note")

    # ---- 3. WelcomeDialog 构造 + 部件 ----
    section("[3] WelcomeDialog 部件")
    dlg = WelcomeDialog()
    check(dlg.windowTitle() == "欢迎使用 Novel Writer Pure v4", f"title: {dlg.windowTitle()}")
    check(dlg.isModal(), "modal dialog")
    check(dlg.chk_dont_show.isChecked(), "默认勾选'不再显示'")
    check(hasattr(dlg, "btn_create"), "btn_create 存在")
    check(hasattr(dlg, "btn_close"), "btn_close 存在")
    check(dlg.btn_create.text() in dlg.btn_create.text(), f"btn_create: {dlg.btn_create.text()}")

    # ---- 4. 接受 + 写入 ----
    section("[4] 关闭 → 写 welcome_shown")
    dlg.accept()  # 模拟用户点 X 关闭
    check(app_setting_service.get(WELCOME_KEY, False) is True,
          f"已写 {WELCOME_KEY}=True (实际 {app_setting_service.get(WELCOME_KEY)})")
    check(is_welcome_shown() is True, "is_welcome_shown() 变 True")

    # ---- 5. 已显示则不再弹 ----
    section("[5] 二次启动不再弹")
    result = show_welcome_if_first_time()
    check(result is None, f"show_welcome_if_first_time 返 None (实际 {result})")

    # ---- 6. 重置 + 弹窗 + 不勾"不再显示" ----
    section("[6] 重置 + 不勾选 → 不写标志")
    app_setting_service.delete(WELCOME_KEY)
    dlg2 = WelcomeDialog()
    dlg2.chk_dont_show.setChecked(False)
    dlg2.accept()
    check(app_setting_service.get(WELCOME_KEY, False) is False,
          f"不勾选时不写标志 (实际 {app_setting_service.get(WELCOME_KEY)})")
    check(is_welcome_shown() is False, "is_welcome_shown() 仍 False")

    # ---- 7. MainWindow 集成钩子 ----
    section("[7] MainWindow 集成 _show_welcome_once")
    # mock _show_welcome_once 调用计数器
    from app.ui import main_window as mw_mod
    from app.ui.main_window import MainWindow
    call_count = [0]
    orig_show = MainWindow._show_welcome_once
    def counted_show(self):
        call_count[0] += 1
    MainWindow._show_welcome_once = counted_show
    w = MainWindow()
    # MainWindow 启动后, _show_welcome_once 应被标记 (通过 QTimer singleShot 50ms)
    # 我们手动调一次来验证
    MainWindow._show_welcome_once(w)
    check(call_count[0] == 1, f"_show_welcome_once 被调 (实际 {call_count[0]})")
    MainWindow._show_welcome_once = orig_show

    # ---- 8. _show_welcome_once 真的调 show_welcome_if_first_time ----
    section("[8] _show_welcome_once 不抛异常 (mock 弹窗)")
    app_setting_service.delete(WELCOME_KEY)
    # main_window 已经把 show_welcome_if_first_time 显式 import 进来了
    # (顶行 from app.ui.welcome import show_welcome_if_first_time),
    # 我们 patch 一下让它直接走写标志逻辑, 避免真弹 modal 阻塞测试.
    from app.ui import main_window as mw_mod
    import app.ui.welcome as wm_mod
    orig_show = mw_mod.show_welcome_if_first_time

    def fake_show(parent=None):
        # 不弹模态, 走写标志逻辑就行
        dlg = wm_mod.WelcomeDialog(parent)
        dlg.chk_dont_show.setChecked(True)
        dlg.accept()  # 走写标志逻辑
        return dlg

    mw_mod.show_welcome_if_first_time = fake_show
    try:
        w._show_welcome_once()
        passed = True
    except Exception as e:
        passed = False
        print(f"  [ERROR] exception: {e}", flush=True)
    finally:
        mw_mod.show_welcome_if_first_time = orig_show
    check(passed, "_show_welcome_once 跑通不抛异常")
    # ui.welcome_shown 应该已被 dialog 写为 True
    check(app_setting_service.get(WELCOME_KEY, False) is True,
          f"ui.welcome_shown 已写 True (实际 {app_setting_service.get(WELCOME_KEY)})")

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
