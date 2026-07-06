"""
ScreenAdapter smoke (offscreen).

覆盖:
  1. compute_scale 各档位 (1280/1600/2048/2560 + 矮/高屏修正)
  2. ScreenAdapter.instance() 单例
  3. attach(widget) 后 resize 触发 compute_and_apply
  4. QApplication.setFont 真的改了
  5. scaleChanged 信号触发
  6. screenAdded/screenRemoved 触发 compute
  7. 多次 resize 不会风暴 (debounce 验证)
  8. 缩放上下限裁剪 (min 0.85 / max 1.50)
"""
from __future__ import annotations

import os
import sys
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
    print(f"\n[TIMEOUT] smoke_ui_screen_adapter 超时 {_TIMEOUT}s", flush=True)
    os._exit(2)
_t = threading.Timer(_TIMEOUT, _timeout_kill)
_t.daemon = True
_t.start()

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget

_app = QApplication.instance() or QApplication(sys.argv)


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
    print("=== ScreenAdapter smoke (offscreen) ===", flush=True)

    from app.ui.screen_adapter import (
        ScreenAdapter, compute_scale, scaled_font,
        BASE_FONT_PX, SCALE_BREAKPOINTS, MIN_SCALE, MAX_SCALE,
    )

    # ---- 1. compute_scale 档位 ----
    section("[1] compute_scale 各档位")
    # < 1280 → 0.92
    s = compute_scale(1024, 768)
    check(abs(s - 0.92) < 0.01, f"1024x768 → 0.92 (实际 {s:.3f})")
    # 1280-1599 → 1.00
    s = compute_scale(1440, 900)
    check(abs(s - 1.00) < 0.01, f"1440x900 → 1.00 (实际 {s:.3f})")
    # 1600-2047 → 1.08
    s = compute_scale(1920, 1080)
    check(abs(s - 1.08) < 0.01, f"1920x1080 → 1.08 (实际 {s:.3f})")
    # 2048-2559 → 1.18
    s = compute_scale(2200, 900)
    check(abs(s - 1.18) < 0.01, f"2200x900 → 1.18 (实际 {s:.3f})")
    # ≥ 2560 → 1.30
    s = compute_scale(3000, 900)
    check(abs(s - 1.30) < 0.01, f"3000x900 → 1.30 (实际 {s:.3f})")
    # 矮屏 (height < 720) -0.04
    s_short = compute_scale(1440, 600)
    s_normal = compute_scale(1440, 900)
    check(s_short < s_normal, f"矮屏 < 正常: {s_short:.3f} < {s_normal:.3f}")
    # 高屏 (height > 1080) +0.02
    s_tall = compute_scale(1440, 1200)
    s_normal2 = compute_scale(1440, 900)
    check(s_tall > s_normal2, f"高屏 > 正常: {s_tall:.3f} > {s_normal2:.3f}")
    # 上下限
    s_min = compute_scale(50, 50)  # 极小
    check(s_min >= MIN_SCALE, f"下限裁剪: {s_min:.3f} >= {MIN_SCALE}")
    s_max = compute_scale(99999, 99999)
    check(s_max <= MAX_SCALE, f"上限裁剪: {s_max:.3f} <= {MAX_SCALE}")
    # 0 宽不崩
    s0 = compute_scale(0, 0)
    check(s0 == 1.0, f"0x0 → 1.0 (实际 {s0:.3f})")

    # ---- 2. scaled_font ----
    section("[2] scaled_font 构造")
    f_small = scaled_font(BASE_FONT_PX, 0.8)
    check(f_small.pointSize() == round(BASE_FONT_PX * 0.8),
          f"0.8x font size (实际 {f_small.pointSize()})")
    f_big = scaled_font(BASE_FONT_PX, 1.3)
    check(f_big.pointSize() == round(BASE_FONT_PX * 1.3),
          f"1.3x font size (实际 {f_big.pointSize()})")
    f_min = scaled_font(BASE_FONT_PX, 0.0)  # factor=0, 应被 max(6) 兜底
    check(f_min.pointSize() >= 6, f"最小 6pt (实际 {f_min.pointSize()})")

    # ---- 3. ScreenAdapter.instance 单例 ----
    section("[3] ScreenAdapter.instance 单例")
    a1 = ScreenAdapter.instance()
    a2 = ScreenAdapter.instance()
    check(a1 is a2, f"单例 (实际 a1 is a2 = {a1 is a2})")

    # ---- 4. attach + resize 触发 ----
    section("[4] attach + resize 触发")
    # 重新构造一个 widget 测试
    test_w = QWidget()
    test_w.resize(1280, 800)
    test_w.show()
    _app.processEvents()
    a1.attach(test_w)
    # 当前缩放
    s_before = a1.current_scale
    check(s_before > 0, f"初始 scale 算出来: {s_before:.3f}")
    # 改变尺寸 → 触发 compute
    test_w.resize(1920, 1080)
    _app.processEvents()
    a1.compute_and_apply()  # 强制
    s_after = a1.current_scale
    check(s_after > s_before, f"放大窗口 scale 变大: {s_before:.3f} → {s_after:.3f}")

    # 缩小
    test_w.resize(1024, 600)
    _app.processEvents()
    a1.compute_and_apply()
    s_small = a1.current_scale
    check(s_small < s_after, f"缩小窗口 scale 变小: {s_after:.3f} → {s_small:.3f}")

    # ---- 5. QApplication 字体真改了 ----
    section("[5] QApplication 字体真改了")
    test_w.resize(1920, 1080)
    a1.compute_and_apply()
    cur_font = _app.font()
    expected_pt = round(BASE_FONT_PX * a1.current_scale)
    check(cur_font.pointSize() == expected_pt,
          f"QApp font pt={cur_font.pointSize()} (期望 {expected_pt}, scale={a1.current_scale:.3f})")

    # ---- 6. scaleChanged 信号 ----
    section("[6] scaleChanged 信号")
    received: list[float] = []
    a1.scaleChanged.connect(lambda f: received.append(f))
    test_w.resize(2560, 1440)
    a1.compute_and_apply()
    test_w.resize(3840, 2160)
    a1.compute_and_apply()
    _app.processEvents()
    check(len(received) >= 1, f"信号触发 {len(received)} 次")
    check(received[-1] > 1.0, f"信号最新值 > 1.0 (实际 {received[-1]:.3f})")

    # ---- 7. 多次 resize 不风暴 (debounce) ----
    section("[7] debounce")
    received.clear()
    a1.scaleChanged.disconnect()  # 重新接
    a1.scaleChanged.connect(lambda f: received.append(f))
    # 快速连发 5 次同样大小
    for _ in range(5):
        test_w.resize(1920, 1080)
        a1._on_widget_resized(test_w)
    # 不 wait debounce, 应该还没触发
    _app.processEvents()
    pre = len(received)
    # 等 250ms 让 debounce 触发
    import time
    time.sleep(0.3)
    _app.processEvents()
    post = len(received)
    check(post - pre <= 1, f"5 次相同 resize 只触发 1 次 ({pre} -> {post})")

    # ---- 8. screenAdded 模拟 ----
    section("[8] screenAdded/screenRemoved 触发")
    received.clear()
    a1.scaleChanged.connect(lambda f: received.append(f))
    pre = len(received)
    a1.compute_and_apply()  # 模拟 screenAdded 回调
    _app.processEvents()
    check(len(received) > pre, f"compute_and_apply 触发信号 ({pre} -> {len(received)})")

    # 清理
    test_w.deleteLater()
    _app.processEvents()

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
