"""
M10-B: License 设置面板 smoke (offscreen).

覆盖:
  1. LicenseWidget 构造 + 4 按钮存在
  2. 默认无 license → tier=STANDARD, status=STANDARD
  3. LicenseWidget.refresh 调 get_license / get_tier / get_machine_code
  4. tokens_hint FEATURE_REGISTRY 含 settings_license (M10-B 新加)
  5. 激活合法万能 key → tier=PRO, status=PREMIUM
  6. 激活非法 key → 弹 Dialogs.error, status=INVALID
  7. 降级 → tier=STANDARD, status=STANDARD
  8. 复制机器码 → 剪贴板含 8 位哈希
  9. SettingsTab 集成: 5 个 tab 含 🔐 License
  10. LicenseWidget 软依赖: 模拟 license 不可用
  11. 4 个按钮启用状态 (PREMIUM 时 deactivate 启用 / 其它时 activate 启用)
  12. 端到端: 激活 PRO → 检查 PRO 功能解锁 → 降级 → 检查锁回
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
from PySide6.QtWidgets import QApplication, QPushButton, QGroupBox

# watchdog: 60s 强退
_app = QApplication.instance() or QApplication(sys.argv)
_wd = QTimer(); _wd.setSingleShot(True)
_wd.timeout.connect(lambda: (print("[TIMEOUT] m10_b 超时 60s", flush=True), os._exit(2)))
_wd.start(60_000)

# 顶层 stdout reconfigure
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
    print("=== M10-B: License 设置面板 smoke (offscreen) ===", flush=True)

    # 启动 DB
    try:
        from app.services import db as svc_db
        svc_db.init_db()
    except Exception as e:
        print(f"[warn] init_db: {e}")

    # ---- 1. LicenseWidget 构造 ----
    section("[1] LicenseWidget 构造 + 4 按钮")
    from app.ui.widgets.license_widget import LicenseWidget, _HAS_LICENSE
    check(_HAS_LICENSE, f"license / feature_gate 服务已加载 (实际 {_HAS_LICENSE})")
    w = LicenseWidget()
    check(isinstance(w, QGroupBox), f"LicenseWidget 是 QGroupBox")
    check("License" in w.title(), f"title 含 License: {w.title()}")
    check(w.lbl_tier is not None, "lbl_tier 存在")
    check(w.lbl_status is not None, "lbl_status 存在")
    check(w.lbl_machine is not None, "lbl_machine 存在")
    check(w.lbl_expire is not None, "lbl_expire 存在")
    check(w.lbl_unlocked is not None, "lbl_unlocked 存在")
    check(w.btn_activate.text() and "激活" in w.btn_activate.text(), f"激活按钮: {w.btn_activate.text()}")
    check(w.btn_deactivate.text() and "降级" in w.btn_deactivate.text(), f"降级按钮: {w.btn_deactivate.text()}")
    check(w.btn_copy_machine.text() and "机器码" in w.btn_copy_machine.text(), f"复制按钮: {w.btn_copy_machine.text()}")
    check(w.btn_refresh.text() and "刷新" in w.btn_refresh.text(), f"刷新按钮: {w.btn_refresh.text()}")

    # ---- 2. 默认无 license → STANDARD ----
    section("[2] 默认无 license → tier=STANDARD")
    from app.services.license import deactivate as _deact, reset_cache as _lic_reset
    from app.services.feature_gate import get_tier, Tier
    _lic_reset()
    # 确保无 license
    try:
        _deact()
    except Exception:
        pass
    _lic_reset()
    w.refresh()
    check("STANDARD" in w.lbl_tier.text(), f"tier 含 STANDARD: {w.lbl_tier.text()}")
    check("标准版" in w.lbl_status.text() or "STANDARD" in w.lbl_status.text(),
          f"status 含 标准版/STANDARD: {w.lbl_status.text()}")

    # 按钮启用状态: 无 license → activate 启用, deactivate 禁用
    check(w.btn_activate.isEnabled(), "无 license 时 btn_activate enabled")
    check(not w.btn_deactivate.isEnabled(), "无 license 时 btn_deactivate disabled")

    # ---- 3. refresh 读 get_license / get_tier / get_machine_code ----
    section("[3] refresh 读 license / tier / machine_code")
    check(w.lbl_machine.text() and w.lbl_machine.text() != "—",
          f"机器码非空: {w.lbl_machine.text()}")
    check(len(w.lbl_machine.text()) >= 8, f"机器码长度 ≥ 8: {len(w.lbl_machine.text())}")
    # 已解锁 N / 总 M
    check("/" in w.lbl_unlocked.text(), f"已解锁 N/M: {w.lbl_unlocked.text()}")
    check("功能" in w.lbl_unlocked.text(), "已解锁含 '功能'")

    # ---- 4. tokens_hint FEATURE_REGISTRY 含 settings_license ----
    section("[4] tokens_hint FEATURE_REGISTRY 含 settings_license")
    from app.ui.tokens_hint import FEATURE_REGISTRY
    # settings_license 是 M10-B 新加
    check("settings_license" in FEATURE_REGISTRY, f"settings_license 已注册 (keys={[k for k in FEATURE_REGISTRY if 'license' in k]})")
    info = FEATURE_REGISTRY.get("settings_license")
    if info:
        check(info.icon == "🔐", f"settings_license icon=🔐 (实际 {info.icon})")
        check("License" in info.name or "授权" in info.name, f"name 含 License/授权: {info.name}")
        check("0 元" in info.per_use_cny or "0元" in info.per_use_cny, f"per_use_cny 标 0 元: {info.per_use_cny}")
    # 兼容旧
    check("editor_export" in FEATURE_REGISTRY, "editor_export 仍在 (M10-A 兼容)")
    check("editor_tts" in FEATURE_REGISTRY, "editor_tts 仍在 (M8 兼容)")

    # ---- 5. 激活万能 key → PRO ----
    section("[5] 激活万能 key → tier=PRO")
    from app.services.license import activate as _act, LicenseStatus
    import re
    # 万能 key 格式 NV-UNIV-XXXX-XXXX-XXXX (但 generate_key 生成的也以 NV- 开头, machine=None)
    # 用 _run_cli 不能, 直接调 generate + activate
    from app.services.license import generate_key
    key = generate_key(machine_code=None, days=30)  # 任何机器可用
    check(key.startswith("NV-"), f"key 格式: {key}")
    info = _act(key)
    check(info.status == LicenseStatus.PREMIUM, f"激活后 status=PREMIUM (实际 {info.status})")
    check(not info.error_msg, f"无 error: {info.error_msg}")
    _lic_reset()
    check(get_tier() == Tier.PRO, f"激活后 tier=PRO (实际 {get_tier()})")
    w.refresh()
    check("PRO" in w.lbl_tier.text(), f"UI 显示 PRO: {w.lbl_tier.text()}")
    check("已激活" in w.lbl_status.text() or "PREMIUM" in w.lbl_status.text(),
          f"status 含 已激活/PREMIUM: {w.lbl_status.text()}")
    # 按钮状态翻转
    check(not w.btn_activate.isEnabled(), "PREMIUM 时 btn_activate disabled")
    check(w.btn_deactivate.isEnabled(), "PREMIUM 时 btn_deactivate enabled")
    # 解锁数变多 (PRO 解锁全部 23 个, STANDARD 只能 17 左右)
    # 文本是富文本格式, 提取数字检查
    import re as _re
    nums = _re.findall(r">(\d+)<.*?>\s*/\s*(\d+)", w.lbl_unlocked.text())
    if not nums:
        # fallback: 简单文本匹配
        nums = _re.findall(r"(\d+)\s*/\s*(\d+)", w.lbl_unlocked.text())
    check(nums and int(nums[0][0]) == 23 and int(nums[0][1]) == 23,
          f"PRO 解锁全部 23: {w.lbl_unlocked.text()}")

    # ---- 6. 激活非法 key ----
    section("[6] 激活非法 key → 弹错")
    # monkey-patch Dialogs.error 拦截
    from app.ui.widgets import dialogs as dlg_mod
    error_called = []
    orig_error = dlg_mod.Dialogs.error
    def fake_error(title, message, **kw):
        error_called.append((title, message))
        return (False, None)
    dlg_mod.Dialogs.error = staticmethod(fake_error)
    try:
        # _on_activate 弹 InputDialog, 拦截
        from app.ui.widgets import license_widget as lw_mod
        orig_input = dlg_mod.Dialogs.input
        dlg_mod.Dialogs.input = staticmethod(
            lambda *a, **kw: (True, "NV-INVA-LID0-XXXX-0000")
        )
        try:
            w._on_activate()
            check(any("激活" in t for t, _ in error_called),
                  f"非法 key → 弹 error (error_called={error_called[:1]})")
        finally:
            dlg_mod.Dialogs.input = orig_input
    finally:
        dlg_mod.Dialogs.error = orig_error
    # 状态仍 PREMIUM (没改)
    _lic_reset()
    check(get_tier() == Tier.PRO, f"非法激活后 tier 仍 PRO: {get_tier()}")

    # ---- 7. 降级 ----
    section("[7] 降级 → tier=STANDARD")
    # monkey-patch confirm
    orig_confirm = dlg_mod.Dialogs.confirm
    dlg_mod.Dialogs.confirm = staticmethod(lambda *a, **kw: True)
    try:
        orig_info = dlg_mod.Dialogs.info
        info_called = []
        dlg_mod.Dialogs.info = staticmethod(
            lambda title, message, **kw: info_called.append((title, message))
        )
        try:
            w._on_deactivate()
            check(any("降级" in t or "STANDARD" in m for t, m in info_called),
                  f"降级成功弹 info (info_called={info_called})")
        finally:
            dlg_mod.Dialogs.info = orig_info
    finally:
        dlg_mod.Dialogs.confirm = orig_confirm
    _lic_reset()
    check(get_tier() == Tier.STANDARD, f"降级后 tier=STANDARD (实际 {get_tier()})")
    w.refresh()
    check("STANDARD" in w.lbl_tier.text(), f"UI 显示回 STANDARD: {w.lbl_tier.text()}")

    # ---- 8. 复制机器码 ----
    section("[8] 复制机器码 → 剪贴板")
    from app.services.license import get_machine_code
    expected = get_machine_code()
    # monkey-patch info
    orig_info2 = dlg_mod.Dialogs.info
    info_called2 = []
    dlg_mod.Dialogs.info = staticmethod(
        lambda title, message, **kw: info_called2.append((title, message))
    )
    try:
        w._on_copy_machine()
        from PySide6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        actual = cb.text() if cb else ""
        check(actual == expected, f"剪贴板 = 机器码 (actual={actual!r}, expected={expected!r})")
        check(any("复制" in t or "已复制" in t for t, _ in info_called2),
              f"复制后弹 info (info_called2={info_called2})")
    finally:
        dlg_mod.Dialogs.info = orig_info2

    # ---- 9. SettingsTab 集成 (4.0 重构: scope=app, 8 左导航项) ----
    section("[9] SettingsTab(scope=app) 8 左导航项含 🔑 授权 (M11-C 增 2 项)")
    from app.ui.tabs.settings_tab import SettingsTab
    st = SettingsTab(scope=SettingsTab.SCOPE_APP)
    check(hasattr(st, "license_widget"), "SettingsTab.license_widget 存在")
    check(isinstance(st.license_widget, LicenseWidget), "是 LicenseWidget 实例")
    # 4.0 重构: QTabWidget → QListWidget(左) + QStackedWidget(右)
    from PySide6.QtWidgets import QListWidget, QStackedWidget
    check(isinstance(st.nav_list, QListWidget), "nav_list 是 QListWidget (左导航)")
    check(isinstance(st.stack, QStackedWidget), "stack 是 QStackedWidget (右内容)")
    check(st.nav_list.count() == 8, f"8 个左导航项 (实际 {st.nav_list.count()})")
    nav_titles = [st.nav_list.item(i).text() for i in range(st.nav_list.count())]
    check("🔑 授权" in nav_titles, f"含 🔑 授权 导航项 (实际: {nav_titles})")
    # M11-C 增 2 项
    check(any("AI 路由" in t for t in nav_titles), f"含 🤖 AI 路由 导航项 (实际: {nav_titles})")
    check(any("关于" in t and "ℹ️" in t for t in nav_titles), f"含 ℹ️ 关于 导航项 (实际: {nav_titles})")

    # ---- 10. 软依赖: license 不可用 ----
    section("[10] LicenseWidget 软依赖 (license 不可用时不崩)")
    import app.ui.widgets.license_widget as lw_module
    orig_has = lw_module._HAS_LICENSE
    lw_module._HAS_LICENSE = False
    try:
        w2 = LicenseWidget()
        w2.refresh()
        check("未加载" in w2.lbl_tier.text() or "❌" in w2.lbl_tier.text(),
              f"不可用时显示兜底: {w2.lbl_tier.text()}")
        # 4 按钮全禁用
        check(not w2.btn_activate.isEnabled(), "activate disabled")
        check(not w2.btn_deactivate.isEnabled(), "deactivate disabled")
    finally:
        lw_module._HAS_LICENSE = orig_has

    # ---- 11. 按钮启用状态 (切来切去) ----
    section("[11] 按钮启用状态切来切去")
    # 1) 无 license: activate=en, deactivate=dis
    _lic_reset()
    _deact()
    _lic_reset()
    w.refresh()
    check(w.btn_activate.isEnabled(), "无 license → activate enabled")
    check(not w.btn_deactivate.isEnabled(), "无 license → deactivate disabled")
    # 2) PREMIUM: activate=dis, deactivate=en
    _act(generate_key(machine_code=None, days=30))
    _lic_reset()
    w.refresh()
    check(not w.btn_activate.isEnabled(), "PREMIUM → activate disabled")
    check(w.btn_deactivate.isEnabled(), "PREMIUM → deactivate enabled")
    # 3) 降级回 STANDARD
    _deact()
    _lic_reset()
    w.refresh()
    check(w.btn_activate.isEnabled(), "降级后 → activate enabled")
    check(not w.btn_deactivate.isEnabled(), "降级后 → deactivate disabled")

    # ---- 12. 端到端: 激活 PRO → 验证 PRO 功能解锁 → 降级 → 锁回 ----
    section("[12] 端到端: 激活 → PRO 解锁 → 降级 → 锁回")
    from app.services.feature_gate import check_feature
    # PRO 专属: ai.critic, export.epub, export.docx
    _deact()
    _lic_reset()
    check(not check_feature("ai.critic"), "STANDARD 时 ai.critic 锁")
    check(not check_feature("export.epub"), "STANDARD 时 export.epub 锁")
    check(check_feature("core.editor"), "STANDARD 时 core.editor 仍可用 (FREE)")

    # 激活 PRO
    _act(generate_key(machine_code=None, days=30))
    _lic_reset()
    check(check_feature("ai.critic"), "PRO 时 ai.critic 解锁")
    check(check_feature("export.epub"), "PRO 时 export.epub 解锁")
    check(check_feature("export.docx"), "PRO 时 export.docx 解锁")
    check(check_feature("core.editor"), "PRO 时 core.editor 仍可用")

    # 降级
    _deact()
    _lic_reset()
    check(not check_feature("ai.critic"), "降级后 ai.critic 锁回")
    check(not check_feature("export.epub"), "降级后 export.epub 锁回")
    check(check_feature("core.editor"), "降级后 core.editor 仍可用")

    # 清理
    _deact()

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
