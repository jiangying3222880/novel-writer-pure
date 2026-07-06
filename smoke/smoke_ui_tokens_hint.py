"""
Tokens 提示系统 smoke (offscreen).

覆盖:
  1. FEATURE_REGISTRY 4 项, 字段齐全
  2. PriceBar 构造 + 字段填充正确
  3. GenerateTab / EditorTab 顶部都有 PriceBar (集成验证)
  4. FirstUsePopup 构造 + 部件齐
  5. 首次弹 → is_shown 变 True, 二次不弹
  6. 不勾选 "不再提示" → 不写标志
  7. reset_shown() 重置成功
  8. unknown feature_id 不抛异常
  9. 与 tab 集成: _start_generate / _start_rewrite 会调 show_first_use_if_needed
 10. PriceBar objectName 匹配 theme.py 的 #priceBar 样式
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

# watchdog: 60s 强退
_app = QApplication.instance() or QApplication(sys.argv)
_wd = QTimer(); _wd.setSingleShot(True)
_wd.timeout.connect(lambda: (print("[TIMEOUT] tokens_hint 超时 60s", flush=True), os._exit(2)))
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
    print("=== Tokens 提示系统 smoke (offscreen) ===", flush=True)

    # 启动 DB
    try:
        from app.services import db as svc_db
        svc_db.init_db()
    except Exception as e:
        print(f"[warn] init_db: {e}")

    from app.services import app_setting_service

    # ---- 1. FEATURE_REGISTRY 字段检查 ----
    section("[1] FEATURE_REGISTRY 字段")
    from app.ui.tokens_hint import (
        FEATURE_REGISTRY, is_shown, mark_shown, reset_shown,
        PriceBar, FirstUsePopup, show_first_use_if_needed,
    )
    # M11-A: 现在有 7 个功能 (4 核心 + editor_tts/editor_export/settings_license)
    check(len(FEATURE_REGISTRY) >= 4, f">=4 个功能 (实际 {len(FEATURE_REGISTRY)})")
    expected_keys = ["generate", "editor_rewrite", "consistency", "voice_inference"]
    for k in expected_keys:
        check(k in FEATURE_REGISTRY, f"key={k} 存在")
    for fid, info in FEATURE_REGISTRY.items():
        check(info.icon and len(info.icon) >= 1, f"{fid}.icon 非空: {info.icon}")
        check(info.name and len(info.name) >= 2, f"{fid}.name 非空: {info.name}")
        # 花钱功能含 "约" / 免费功能含 "0 元" 或 "免费" — 至少要可读
        check(
            ("约" in info.per_use_cny) or ("元" in info.per_use_cny) or ("免费" in info.per_use_cny),
            f"{fid}.per_use_cny 含 '约' 或 '元' 或 '免费'",
        )
        check("不用" in info.compare_with, f"{fid}.compare_with 含 '不用'")
        check(len(info.detail_note) > 0, f"{fid}.detail_note 非空")
        check(info.shown_key.startswith("ui.tokens_hint.shown."),
              f"{fid}.shown_key 前缀正确: {info.shown_key}")

    # ---- 2. PriceBar 构造 + 字段 ----
    section("[2] PriceBar 构造")
    reset_shown()
    bar = PriceBar("generate")
    check(bar.objectName() == "priceBar", f"objectName=priceBar (实际 {bar.objectName()})")
    check("章节生成" in bar._name.text(), f"name={bar._name.text()}")
    check("约" in bar._price.text() and "¥" in bar._price.text(),
          f"price 含 '约' 和 '¥' (实际 {bar._price.text()})")
    check(bar._updated.text() != "", f"updated 标签非空: {bar._updated.text()}")
    check(bar._sub.text() != "", f"sub 标签非空")

    # unknown feature
    bar_bad = PriceBar("nonexistent_xyz")
    check("(未知功能)" in bar_bad._name.text() or bar_bad._name.text() != "",
          f"unknown feature 不抛: {bar_bad._name.text()}")

    # refresh() 不抛
    try:
        bar.refresh()
        passed = True
    except Exception as e:
        passed = False
        print(f"  [ERROR] refresh failed: {e}", flush=True)
    check(passed, "PriceBar.refresh() 不抛异常")

    # ---- 3. FirstUsePopup 构造 + 部件 ----
    section("[3] FirstUsePopup 构造")
    reset_shown()
    dlg = FirstUsePopup("generate")
    check(dlg.isModal(), "modal dialog")
    check("章节生成" in dlg.windowTitle(), f"title 含功能名: {dlg.windowTitle()}")
    check(dlg.chk_dont_show.isChecked(), "默认勾选'不再提示'")
    check(hasattr(dlg, "btn_ok"), "btn_ok 存在")
    check("继续" in dlg.btn_ok.text(), f"btn_ok: {dlg.btn_ok.text()}")

    # ---- 4. 首次弹 → 写标志 ----
    section("[4] 首次弹 → 写 shown_key")
    reset_shown()
    check(is_shown("generate") is False, "重置后 is_shown(generate) False")
    dlg = FirstUsePopup("generate")
    dlg.accept()
    check(is_shown("generate") is True, "关闭后 is_shown(generate) True")
    check(app_setting_service.get("ui.tokens_hint.shown.generate") is True,
          "app_setting_service 已写 shown_key=True")

    # ---- 5. 二次不再弹 ----
    section("[5] 二次不再弹")
    result = show_first_use_if_needed("generate")
    check(result is None, f"show_first_use_if_needed 已弹过 → None (实际 {result})")

    # ---- 6. 不勾选 → 不写标志 ----
    section("[6] 不勾选 → 不写标志")
    reset_shown()
    dlg2 = FirstUsePopup("editor_rewrite")
    dlg2.chk_dont_show.setChecked(False)
    dlg2.accept()
    check(is_shown("editor_rewrite") is False,
          "不勾选时不写标志 (实际 is_shown False)")
    check(app_setting_service.get("ui.tokens_hint.shown.editor_rewrite") is not True,
          "app_setting_service 未写 shown_key=True")

    # ---- 7. reset_shown 全量 / 单个 ----
    section("[7] reset_shown")
    mark_shown("generate")
    mark_shown("editor_rewrite")
    check(is_shown("generate") is True, "mark 后 is_shown True")
    reset_shown("generate")
    check(is_shown("generate") is False, "reset 单个 → False")
    check(is_shown("editor_rewrite") is True, "不影响其他")

    reset_shown()
    check(is_shown("editor_rewrite") is False, "reset 全部 → False")
    check(is_shown("consistency") is False, "consistency 也被 reset")
    check(is_shown("voice_inference") is False, "voice_inference 也被 reset")

    # ---- 8. unknown feature_id 静默 ----
    section("[8] unknown feature_id 静默")
    try:
        result = show_first_use_if_needed("totally_made_up_xxx")
        passed = (result is None)
    except Exception as e:
        passed = False
        print(f"  [ERROR] {e}", flush=True)
    check(passed, "unknown feature_id → 静默返 None")

    # mark_shown unknown 也静默
    try:
        mark_shown("totally_made_up_xxx")
        passed = True
    except Exception:
        passed = False
    check(passed, "mark_shown unknown → 静默不抛")

    # is_shown unknown 返 False
    check(is_shown("totally_made_up_xxx") is False, "is_shown unknown → False")

    # ---- 9. tab 集成: PriceBar 已挂载 ----
    section("[9] GenerateTab + EditorTab 集成 PriceBar")
    from app.ui.tabs.generate_tab import GenerateTab
    from app.ui.tabs.editor_tab import EditorTab
    gt = GenerateTab()
    et = EditorTab()
    check(hasattr(gt, "price_bar") and isinstance(gt.price_bar, PriceBar),
          f"GenerateTab.price_bar 存在且是 PriceBar")
    check(hasattr(et, "price_bar") and isinstance(et.price_bar, PriceBar),
          f"EditorTab.price_bar 存在且是 PriceBar")
    check(gt.price_bar.feature_id == "generate", f"GenerateTab bar feature_id=generate")
    check(et.price_bar.feature_id == "editor_rewrite", f"EditorTab bar feature_id=editor_rewrite")

    # ---- 10. tab 集成: 触发函数会调 show_first_use_if_needed ----
    section("[10] tab 触发函数含 show_first_use_if_needed 调用")
    import inspect
    from app.ui.tabs import generate_tab as gt_mod
    from app.ui.tabs import editor_tab as et_mod
    src_gt = inspect.getsource(gt_mod.GenerateTab._start_generate)
    src_et = inspect.getsource(et_mod.EvaluationPanel._start_rewrite)
    check("show_first_use_if_needed" in src_gt, "GenerateTab._start_generate 含调用")
    check("show_first_use_if_needed" in src_et, "EditorTab EvalPanel._start_rewrite 含调用")
    check('"generate"' in src_gt, "调用传 feature_id=generate")
    check('"editor_rewrite"' in src_et, "调用传 feature_id=editor_rewrite")

    # ---- 11. theme.py 包含 PriceBar 样式 ----
    section("[11] theme.py 含 PriceBar 样式")
    from app.ui import theme as theme_mod
    dark_qss = theme_mod.DARK_QSS
    light_qss = theme_mod.LIGHT_QSS
    check("priceBar" in dark_qss, "DARK_QSS 含 #priceBar 样式")
    check("priceBar" in light_qss, "LIGHT_QSS 含 #priceBar 样式")
    check("priceBarPrice" in dark_qss, "DARK_QSS 含 #priceBarPrice 样式")
    check("popupFeeBox" in dark_qss, "DARK_QSS 含 #popupFeeBox 样式")

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
