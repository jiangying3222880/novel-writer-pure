"""
M10-D: AI Router 状态条 (DashboardTab 顶部) smoke (offscreen).

覆盖:
  1. RouterStatusBar 构造 + 4 个 QLabel
  2. 软依赖: router 不可用时不崩, 显示兜底
  3. lbl_model 含模型名 (or 未配置)
  4. lbl_strategy 含策略名 (single/parallel/cache_first)
  5. lbl_cache 含 'hit='/'miss='/'rate='
  6. lbl_calls 含 '调用'/'次' 或 '—'
  7. lbl_tier 紫色样式 + 当前 tier 标签
  8. badge (PRO 角标) STANDARD 下显示, PRO 下隐藏
  9. refresh() 二次调不崩 + 字段更新
  10. _parse_cache_stats 静态方法: TieredCache 嵌套 / 扁平 / 空 三种格式
  11. DashboardTab 集成: router_bar 是 RouterStatusBar 实例
  12. DashboardTab 顶部 layout 顺序: header > router_bar > stat_row
  13. DashboardTab.set_project(project) 调 router_bar.refresh() 不崩
  14. DashboardTab.set_project(None) 调 router_bar.refresh() 不崩
  15. tokens_hint FEATURE_REGISTRY 仍含 settings_license / editor_export (M10 兼容)
"""
from __future__ import annotations

import os
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QHBoxLayout, QVBoxLayout

# watchdog: 60s 强退
_app = QApplication.instance() or QApplication(sys.argv)
_wd = QTimer(); _wd.setSingleShot(True)
_wd.timeout.connect(lambda: (print("[TIMEOUT] m10_d 超时 60s", flush=True), os._exit(2)))
_wd.start(60_000)

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


def _ensure_standard() -> None:
    from app.services.license import deactivate as _deact, reset_cache as _lic_reset
    _lic_reset()
    try:
        _deact()
    except Exception:
        pass
    _lic_reset()


def _activate_pro(days: int = 30) -> str:
    from app.services.license import activate as _act, generate_key, reset_cache as _lic_reset
    key = generate_key(machine_code=None, days=days)
    info = _act(key)
    _lic_reset()
    return key


def main() -> int:
    print("=== M10-D: AI Router 状态条 smoke (offscreen) ===", flush=True)

    try:
        from app.services import db as svc_db
        svc_db.init_db()
    except Exception as e:
        print(f"[warn] init_db: {e}")

    from app.services.license import reset_cache as _lic_reset
    _ensure_standard()
    _lic_reset()

    # ---- 1. RouterStatusBar 构造 ----
    section("[1] RouterStatusBar 构造 + 4 个 QLabel + tier + badge")
    from app.ui.widgets.router_status_bar import RouterStatusBar
    from app.ui.widgets.feature_gate_widgets import FeatureGateBadge
    bar = RouterStatusBar()
    check(isinstance(bar, QFrame), "RouterStatusBar 继承 QFrame")
    check(bar.objectName() == "router_status_bar", f"objectName: {bar.objectName()}")
    check(isinstance(bar.lbl_model, QLabel), "lbl_model 是 QLabel")
    check(isinstance(bar.lbl_strategy, QLabel), "lbl_strategy 是 QLabel")
    check(isinstance(bar.lbl_cache, QLabel), "lbl_cache 是 QLabel")
    check(isinstance(bar.lbl_calls, QLabel), "lbl_calls 是 QLabel")
    check(isinstance(bar.lbl_tier, QLabel), "lbl_tier 是 QLabel")
    check(isinstance(bar.badge, FeatureGateBadge), "badge 是 FeatureGateBadge")
    check(bar.badge.feature_id == "ai.cache", f"badge.feature_id: {bar.badge.feature_id}")

    # ---- 2. 软依赖: router 不可用时不崩 ----
    section("[2] 软依赖降级 (router 不可用时显示兜底)")
    # 构造一个新 bar, 然后在 _refresh_inner 抛异常时 (模拟) 应不崩
    # 直接调 refresh() 测硬异常 (例如删 cache 引用)
    bar2 = RouterStatusBar()
    # 模拟 router 不可用: 把 cache 属性设成不存在的对象
    try:
        from app.ai import router as _router_mod
        orig = _router_mod._router_singleton
        _router_mod._router_singleton = None
        # 让 get_router 失败: 直接 monkey-patch get_router
        from app.ai import router as _r
        orig_get = _r.get_router
        def bad_get():
            raise RuntimeError("router 不可用 (simulated)")
        _r.get_router = bad_get
        try:
            bar2.refresh()  # 应不崩
            # _refresh_inner: 先 get_registry() (成功) → model='🤖 未配置'
            #                 然后 get_router() 抛 RuntimeError → 整段 _refresh_inner 抛
            #                 refresh 顶层 catch → model='🤖 router 不可用'
            check(bar2.lbl_model.text() in ("🤖 router 不可用", "🤖 未配置"),
                  f"model 显示兜底: {bar2.lbl_model.text()!r}")
            check("err" in bar2.lbl_cache.text() or "—" in bar2.lbl_cache.text(),
                  f"cache 显示兜底: {bar2.lbl_cache.text()}")
        finally:
            _r.get_router = orig_get
            _router_mod._router_singleton = orig
    except Exception as e:
        check(False, f"软依赖降级测崩: {e}")

    # ---- 3. lbl_model 含模型名 ----
    section("[3] lbl_model 含 '🤖' + 模型名 or 未配置")
    _ensure_standard()
    bar3 = RouterStatusBar()
    check(bar3.lbl_model.text().startswith("🤖"),
          f"model 文本以 🤖 开头: {bar3.lbl_model.text()}")
    check("未配置" in bar3.lbl_model.text() or
          any(name in bar3.lbl_model.text() for name in ("gpt", "claude", "deepseek", "kimi", "doubao", "ollama", "mock")),
          f"model 文本含具体模型: {bar3.lbl_model.text()}")

    # ---- 4. lbl_strategy 含策略名 ----
    section("[4] lbl_strategy 含 '📡' + 策略 (单模型/并行/缓存优先)")
    check(bar3.lbl_strategy.text().startswith("📡"),
          f"strategy 文本以 📡 开头: {bar3.lbl_strategy.text()}")
    check(any(kw in bar3.lbl_strategy.text() for kw in ("单模型", "并行", "缓存优先")),
          f"strategy 文本含策略关键词: {bar3.lbl_strategy.text()}")

    # ---- 5. lbl_cache 含 hit/miss/rate ----
    section("[5] lbl_cache 含 '💾' + hit/miss/rate")
    check(bar3.lbl_cache.text().startswith("💾"),
          f"cache 文本以 💾 开头: {bar3.lbl_cache.text()}")
    txt = bar3.lbl_cache.text()
    if "rate" in txt or "%" in txt:
        check(True, f"cache 含命中率信息: {txt}")
    else:
        check("hit" in txt or "—" in txt or "err" in txt, f"cache 文本: {txt}")

    # ---- 6. lbl_calls 含 '调用'/'次' 或 '—' ----
    section("[6] lbl_calls 含 '📊' + 调用信息 or '—'")
    check(bar3.lbl_calls.text().startswith("📊"),
          f"calls 文本以 📊 开头: {bar3.lbl_calls.text()}")
    txt = bar3.lbl_calls.text()
    check("调用" in txt or "—" in txt or "err" in txt,
          f"calls 含调用信息: {txt}")

    # ---- 7. lbl_tier 紫色样式 ----
    section("[7] lbl_tier 紫色样式 + 当前 tier 标签")
    check("STANDARD" in bar3.lbl_tier.text() or "PRO" in bar3.lbl_tier.text() or "FREE" in bar3.lbl_tier.text(),
          f"lbl_tier 含 tier 标签: {bar3.lbl_tier.text()}")
    ss = bar3.lbl_tier.styleSheet()
    check("#7b1fa2" in ss, f"lbl_tier 紫色样式: {ss[:60]}")
    check("border-radius" in ss, "lbl_tier 圆角")

    # ---- 8. badge STANDARD 下显示, PRO 下隐藏 ----
    section("[8] badge STANDARD 下显示, PRO 下隐藏")
    _ensure_standard()
    _lic_reset()
    bar4 = RouterStatusBar()
    check(not bar4.badge.isHidden(),
          f"STANDARD 下 badge 显示 (hidden={bar4.badge.isHidden()})")
    _activate_pro()
    bar4.refresh()
    check(bar4.badge.isHidden(),
          f"PRO 下 badge hidden (hidden={bar4.badge.isHidden()})")
    check("PRO" in bar4.lbl_tier.text() and "💎" in bar4.lbl_tier.text(),
          f"lbl_tier 变 PRO: {bar4.lbl_tier.text()}")
    _ensure_standard()
    _lic_reset()
    bar4.refresh()
    check(not bar4.badge.isHidden(),
          f"降 STANDARD 后 badge 重显示: hidden={bar4.badge.isHidden()}")

    # ---- 9. refresh() 二次调不崩 + 字段更新 ----
    section("[9] refresh() 多次调用稳定")
    try:
        for _ in range(3):
            bar.refresh()
        check(True, "refresh() 调 3 次不崩")
    except Exception as e:
        check(False, f"refresh() 崩: {e}")

    # ---- 10. _parse_cache_stats 静态方法: 嵌套/扁平/空 ----
    section("[10] _parse_cache_stats 三种格式")
    # 嵌套 TieredCache
    h, m, s = RouterStatusBar._parse_cache_stats({
        "l1": {"hit": 5, "miss": 3, "size": 8},
        "l2": {"hit": 2, "miss": 1, "size": 3},
    })
    check(h == 7 and m == 4 and s == 11, f"嵌套 (5+2=7 hit, 3+1=4 miss, 8+3=11 size): got {h}/{m}/{s}")
    # 扁平
    h, m, s = RouterStatusBar._parse_cache_stats({"hit": 10, "miss": 2, "size": 12})
    check(h == 10 and m == 2 and s == 12, f"扁平: {h}/{m}/{s}")
    # 空
    h, m, s = RouterStatusBar._parse_cache_stats({})
    check(h == 0 and m == 0 and s == 0, f"空: {h}/{m}/{s}")
    # None
    h, m, s = RouterStatusBar._parse_cache_stats(None)  # type: ignore[arg-type]
    check(h == 0 and m == 0 and s == 0, f"None: {h}/{m}/{s}")
    # 异常类型
    h, m, s = RouterStatusBar._parse_cache_stats("not a dict")  # type: ignore[arg-type]
    check(h == 0 and m == 0 and s == 0, f"非 dict: {h}/{m}/{s}")

    # ---- 11. DashboardTab 集成 ----
    section("[11] DashboardTab 集成 RouterStatusBar")
    from app.ui.tabs.dashboard_tab import DashboardTab
    dt = DashboardTab()
    check(hasattr(dt, "router_bar"), "DashboardTab.router_bar 存在")
    check(isinstance(dt.router_bar, RouterStatusBar), "router_bar 是 RouterStatusBar 实例")

    # ---- 12. DashboardTab 顶部 layout 顺序 ----
    section("[12] DashboardTab 顶部 layout 顺序: header > router_bar > stat_row")
    # 找 outer layout 的 children
    outer = dt.layout()
    if outer is not None:
        widgets_in_order = []
        for i in range(outer.count()):
            item = outer.itemAt(i)
            w = item.widget() if item is not None else None
            layout = item.layout() if item is not None else None
            if w is not None:
                widgets_in_order.append(type(w).__name__)
            elif layout is not None:
                # 嵌套 layout (header / stat_row / trend_row 都是 QHBoxLayout)
                widgets_in_order.append(f"LAYOUT[{type(layout).__name__}]")
        check(any("router_status_bar" == (getattr(dt.router_bar.objectName(), '', '')) for _ in [0])
              or any("RouterStatusBar" in s or s == "RouterStatusBar" for s in widgets_in_order),
              f"router_bar 在 outer layout 里: {widgets_in_order}")
        # 检查 router_bar 索引 = 1 (header 在 0)
        rb_idx = -1
        for i in range(outer.count()):
            item = outer.itemAt(i)
            if item is not None and item.widget() is dt.router_bar:
                rb_idx = i
                break
        check(rb_idx == 1, f"router_bar 索引 = 1 (期望 header 在 0): 实际 {rb_idx}")
    else:
        check(False, "DashboardTab 没 layout")

    # ---- 13. set_project(project) 不崩 ----
    section("[13] DashboardTab.set_project 调 router_bar.refresh 不崩")
    fake_project = {"id": "test_proj_id", "name": "测试项目"}
    try:
        dt.set_project(fake_project)
        check(True, "set_project(fake_project) 不崩")
        check(dt.router_bar.lbl_model.text().startswith("🤖"),
              f"router_bar 仍显示 model: {dt.router_bar.lbl_model.text()}")
    except Exception as e:
        check(False, f"set_project 崩: {e}")

    # ---- 14. set_project(None) 不崩 ----
    section("[14] DashboardTab.set_project(None) 不崩")
    try:
        dt.set_project(None)
        check(True, "set_project(None) 不崩")
        check("未选择" in dt.title.text(), f"title 含 '未选择': {dt.title.text()}")
    except Exception as e:
        check(False, f"set_project(None) 崩: {e}")

    # ---- 15. tokens_hint FEATURE_REGISTRY 兼容 ----
    section("[15] tokens_hint FEATURE_REGISTRY 兼容 M10-A/B/C/D")
    from app.ui.tokens_hint import FEATURE_REGISTRY
    check("settings_license" in FEATURE_REGISTRY, "settings_license 仍在 (M10-B)")
    check("editor_export" in FEATURE_REGISTRY, "editor_export 仍在 (M10-A)")
    check("editor_tts" in FEATURE_REGISTRY, "editor_tts 仍在 (M8 兼容)")

    # ---- 最终 ----
    section(f"[最终] smoke_m10_d_router_status: {_pass} PASS / {_fail} FAIL")
    _ensure_standard()
    _lic_reset()
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
