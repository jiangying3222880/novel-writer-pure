"""
smoke_quick.py — 快速 smoke 工具 (按改动自动选相关测试, 不跑全部)

解决的问题:
  - 跑全量 38 个 smoke 太慢 (5-15 分钟)
  - 修改一行代码不需要重跑所有测试
  - "我改了 main_window.py, 我只想跑 UI 相关 smoke"

用法:
  python smoke/smoke_quick.py                          # 默认 --fast (10-15 秒)
  python smoke/smoke_quick.py --full                   # 跑全量
  python smoke/smoke_quick.py app/ui/main_window.py    # 改动某个文件, 自动选相关 smoke
  python smoke/smoke_quick.py app/services/            # 改动整个目录
  python smoke/smoke_quick.py --list                   # 列出所有分类映射
  python smoke/smoke_quick.py --tag ui                 # 按 tag 选
  python smoke/smoke_quick.py --tag core,services      # 多 tag
  python smoke/smoke_quick.py --timeout 15             # 单个 smoke 15 秒超时 (默认 30)

设计原则:
  1. fast 模式永远 10-15 秒 (5 个核心 smoke)
  2. 按文件路径前缀 → 分类 → smoke 列表
  3. 单个 smoke 超时强制跳过 (UI 弹窗阻塞兜底)
  4. 失败时给"改了什么 / 建议看哪里" 的提示
"""
from __future__ import annotations

import argparse
import importlib
import io
import multiprocessing
import os
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # UI 测试不弹窗
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ────────────────────── smoke 分类映射 ──────────────────────

# 按"被测代码"路径前缀 → 关联 smoke 列表
FILE_TO_SMOKES: list[tuple[str, list[str]]] = [
    # L0 基础设施
    ("app/core/", [
        "smoke.smoke_m1_core",
        "smoke.smoke_m0_db",
    ]),
    ("app/db/", [
        "smoke.smoke_m0_db",
    ]),
    ("app/ai/", [
        "smoke.smoke_g1_engine",
        "smoke.smoke_a4_pricing",
    ]),
    ("app/knowledge/", [
        "smoke.smoke_d1_knowledge",
        "smoke.smoke_d2_finder",
        "smoke.smoke_f1_bm25",
        "smoke.smoke_f2_vector",
    ]),

    # L2 业务
    ("app/services/", [
        "smoke.smoke_m2_services",
        "smoke.smoke_g3_subtext",
        "smoke.smoke_g5_g9",
        "smoke.smoke_g10_observer",
        "smoke.smoke_c1_importer",
    ]),
    ("app/agents/", [
        "smoke.smoke_g17_agents",
        "smoke.smoke_g18_conditioning_identity",
        "smoke.smoke_g19_stability_harness",
        "smoke.smoke_g19_5_enhanced_divergence",
        "smoke.smoke_g19_6_stress_manifold",
        "smoke.smoke_g20_causal_attribution",
        "smoke.smoke_g21_closed_loop",
    ]),
    ("app/validators/", [
        "smoke.smoke_g11_g16",
    ]),
    ("app/workflow/", [
        "smoke.smoke_v3_signals",
    ]),
    ("app/plugins/", [
        "smoke.smoke_h2_knowledge_plugin",
        "smoke.smoke_h3_plot_deduction",
        "smoke.smoke_h7_h8",
    ]),

    # L3 扩展点 (无独立 smoke, 走 services)

    # L4 UI
    ("app/ui/", [
        "smoke.smoke_ui_nav_theme",
        "smoke.smoke_ui_welcome",
        "smoke.smoke_ui_tokens_hint",
        "smoke.smoke_ui_subtext",
        "smoke.smoke_ui_screen_adapter",
        "smoke.smoke_ui_editor_subtext_mark",
        "smoke.smoke_ui_widgets",
        "smoke.smoke_ui_storage",
        "smoke.smoke_new_project_progress",
    ]),

    # smoke 自身
    ("smoke/", [
        # 改 smoke 自身 → 跑全量
    ]),

    # 资源
    ("app/resources/", [
        "smoke.smoke_h4_config",
    ]),

    # 顶层
    ("app/main.py", [
        "smoke.smoke_ui_nav_theme",
    ]),
    ("app/app_paths.py", [
        "smoke.smoke_ui_storage",
    ]),
]

# 特殊 (跨多个分类)
CROSS_CUTTING = {
    "character": ["smoke.smoke_e1_character_tracker", "smoke.smoke_d3_d4_worldbuilding"],
    "world": ["smoke.smoke_d3_d4_worldbuilding", "smoke.smoke_g10_observer"],
    "memory": ["smoke.smoke_e2_memory_pressure_anti_ai", "smoke.smoke_e3_memory_manager"],
    "outline": ["smoke.smoke_g5_g9", "smoke.smoke_h3_plot_deduction"],
    "ai": ["smoke.smoke_g1_engine", "smoke.smoke_a4_pricing", "smoke.smoke_a1_h1_b7"],
    "license": ["smoke.smoke_b5_license"],
    "signals": ["smoke.smoke_v3_signals"],
    "build": ["smoke.smoke_j2_pyinstaller"],
    "i18n": ["smoke.smoke_i6_i8_dialogs"],
}

# fast 模式 (10-15 秒, 5 个核心 smoke)
FAST_SMOKES = [
    "smoke.smoke_m0_db",              # DB 基础
    "smoke.smoke_m1_core",            # core 基础
    "smoke.smoke_m2_services",        # services 基础
    "smoke.smoke_ui_nav_theme",       # UI 导航 + 主题
    "smoke.smoke_new_project_progress",  # 新建项目 (用户最常用)
]

# 全量 (按 run_all.py 顺序)
FULL_SMOKES = [
    "smoke.smoke_m0_db",
    "smoke.smoke_m1_core",
    "smoke.smoke_m2_services",
    "smoke.smoke_d1_knowledge",
    "smoke.smoke_d2_finder",
    "smoke.smoke_d3_d4_worldbuilding",
    "smoke.smoke_e1_character_tracker",
    "smoke.smoke_e2_memory_pressure_anti_ai",
    "smoke.smoke_e3_memory_manager",
    "smoke.smoke_f1_bm25",
    "smoke.smoke_f2_vector",
    "smoke.smoke_c1_importer",
    "smoke.smoke_h2_knowledge_plugin",
    "smoke.smoke_h3_plot_deduction",
    "smoke.smoke_h4_config",
    "smoke.smoke_h7_h8",
    "smoke.smoke_g3_subtext",
    "smoke.smoke_g5_g9",
    "smoke.smoke_g17_agents",
    "smoke.smoke_g18_conditioning_identity",
    "smoke.smoke_g19_stability_harness",
    "smoke.smoke_g19_5_enhanced_divergence",
    "smoke.smoke_g19_6_stress_manifold",
    "smoke.smoke_g20_causal_attribution",
    "smoke.smoke_g21_closed_loop",
    "smoke.smoke_b5_license",
    "smoke.smoke_g1_engine",
    "smoke.smoke_g10_observer",
    "smoke.smoke_a4_pricing",
    "smoke.smoke_ui_nav_theme",
    "smoke.smoke_ui_welcome",
    "smoke.smoke_ui_tokens_hint",
    "smoke.smoke_ui_subtext",
    "smoke.smoke_ui_screen_adapter",
    "smoke.smoke_ui_editor_subtext_mark",
    "smoke.smoke_ui_widgets",
    "smoke.smoke_g11_g16",
    "smoke.smoke_j2_pyinstaller",
    "smoke.smoke_a1_h1_b7",
    "smoke.smoke_m7_write_cli",
    "smoke.smoke_m9_exporter",
    "smoke.smoke_m9_license",
    "smoke.smoke_m9_router",
    "smoke.smoke_m10_a_export_ui",
    "smoke.smoke_m10_b_license_ui",
    "smoke.smoke_m10_c_feature_gate",
    "smoke.smoke_m10_d_router_status",
    "smoke.smoke_i6_i8_dialogs",
    "smoke.smoke_v3_signals",
    "smoke.smoke_ui_storage",
    "smoke.smoke_new_project_progress",
]


# ────────────────────── 选择逻辑 ──────────────────────

def select_by_files(paths: list[str]) -> list[str]:
    """根据文件路径选 smoke 列表 (去重, 保序)."""
    seen: set[str] = set()
    result: list[str] = []
    for p in paths:
        # 转相对路径
        try:
            rel = str(Path(p).resolve().relative_to(ROOT))
        except ValueError:
            rel = p
        # 走分类映射
        matched = False
        for prefix, smokes in FILE_TO_SMOKES:
            if rel.startswith(prefix) or rel == prefix.rstrip("/"):
                for s in smokes:
                    if s not in seen:
                        seen.add(s)
                        result.append(s)
                matched = True
        # 走 cross_cutting
        rel_lower = rel.lower()
        for tag, smokes in CROSS_CUTTING.items():
            if tag in rel_lower:
                for s in smokes:
                    if s not in seen:
                        seen.add(s)
                        result.append(s)
                matched = True
        if not matched:
            # 默认跑 fast
            for s in FAST_SMOKES:
                if s not in seen:
                    seen.add(s)
                    result.append(s)
    return result


def select_by_tags(tags: list[str]) -> list[str]:
    """按 tag 选 smoke. tag ∈ FILE_TO_SMOKES 的前缀最后一段 + cross_cutting 键."""
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        tag = tag.strip()
        # 找匹配的前缀
        for prefix, smokes in FILE_TO_SMOKES:
            tag_name = prefix.rstrip("/").split("/")[-1]
            if tag_name == tag:
                for s in smokes:
                    if s not in seen:
                        seen.add(s)
                        result.append(s)
        # cross_cutting
        if tag in CROSS_CUTTING:
            for s in CROSS_CUTTING[tag]:
                if s not in seen:
                    seen.add(s)
                    result.append(s)
    return result


# ────────────────────── 跑 smoke ──────────────────────

class _Utf8Buffer(io.StringIO):
    encoding = "utf-8"


def _reset_state() -> None:
    """跨 smoke 重置全局状态 (DB conn + 缓存)."""
    try:
        from app.db import _impl as _c
        _c.close()
    except Exception:
        pass
    try:
        from app.services import db as _svc_db
        local = getattr(_svc_db, "_local", None)
        if local is not None:
            conn = getattr(local, "conn", None)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            local.conn = None
    except Exception:
        pass
    time.sleep(0.05)


def _smoke_worker(name: str, conn) -> None:  # type: ignore[no-untyped-def]
    """子进程 worker: 跑 smoke, 把结果通过 Pipe 传回."""
    try:
        mod = importlib.import_module(name)
        buf = _Utf8Buffer()
        try:
            with redirect_stdout(buf):
                rc = mod.main()
        finally:
            _reset_state()
            for fn_name in ("_cleanup", "cleanup", "teardown"):
                fn = getattr(mod, fn_name, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:
                        pass
        out = buf.getvalue()
        ok = (rc == 0) or (rc is None and ("全部" in out and "通过" in out))
        tail = "\n".join(out.splitlines()[-15:]) if not ok else ""
        conn.send({"ok": ok, "out": tail, "err": ""})
    except Exception as e:
        import traceback
        conn.send({"ok": False, "out": "", "err": f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}"})


def run_smoke(name: str, timeout: float = 30.0) -> tuple[bool, float, str]:
    """跑一个 smoke (子进程 + 强制超时). 返回 (ok, 耗时秒, 输出尾部)."""
    parent_conn, child_conn = multiprocessing.Pipe()
    proc = multiprocessing.Process(target=_smoke_worker, args=(name, child_conn), daemon=True)
    t0 = time.time()
    proc.start()
    proc.join(timeout=timeout)
    dt = time.time() - t0

    if proc.is_alive():
        proc.terminate()
        proc.join(1)
        if proc.is_alive():
            proc.kill()
        return False, dt, f"⏱️ TIMEOUT (>{timeout}s) — 弹窗阻塞, 强制结束"

    if not parent_conn.poll(0):
        return False, dt, "❌ 子进程无响应"
    result = parent_conn.recv()
    if result.get("err"):
        return False, dt, result["err"]
    return result["ok"], dt, result["out"]


def run_batch(smokes: list[str], label: str = "", timeout: float = 30.0) -> int:
    """跑一批 smoke. 返回 exit code."""
    if not smokes:
        print("[!] 没选中任何 smoke")
        return 1
    print("=" * 60)
    print(f"  Quick smoke  ({label})  {len(smokes)} 个")
    print("=" * 60)
    passed: list[tuple[str, float]] = []
    failed: list[tuple[str, str, str]] = []  # (name, dt, tail)
    t_start = time.time()
    for name in smokes:
        print(f"\n[run] {name}")
        ok, dt, tail = run_smoke(name)
        if ok:
            passed.append((name, dt))
            print(f"  [OK]   {name}  ({dt:.1f}s)")
        else:
            failed.append((name, f"{dt:.1f}s", tail))
            print(f"  [FAIL] {name}  ({dt:.1f}s)")
            if tail:
                print(tail)
    dt_total = time.time() - t_start
    print()
    print("=" * 60)
    print(f"  {len(passed)}/{len(smokes)} 通过  (总耗时 {dt_total:.1f}s)")
    if failed:
        print(f"\n  失败 {len(failed)} 个:")
        for n, d, _ in failed:
            print(f"    - {n}  ({d})")
    print("=" * 60)
    return 0 if not failed else 1


# ────────────────────── list ──────────────────────

def cmd_list() -> None:
    print()
    print("可用分类 (--tag 或文件前缀):")
    print()
    print("  按文件路径前缀:")
    for prefix, smokes in FILE_TO_SMOKES:
        if smokes:
            tag = prefix.rstrip("/").split("/")[-1]
            print(f"    {tag:20s}  ({prefix})  → {len(smokes)} smoke")
    print()
    print("  按 tag (--tag):")
    for tag, smokes in CROSS_CUTTING.items():
        print(f"    {tag:20s}  → {len(smokes)} smoke")
    print()
    print("用法:")
    print("  python smoke/smoke_quick.py                          # fast 模式 5 个")
    print("  python smoke/smoke_quick.py --full                   # 全量 38 个")
    print("  python smoke/smoke_quick.py app/ui/main_window.py    # 改这个文件")
    print("  python smoke/smoke_quick.py --tag ui                 # UI 全部")
    print("  python smoke/smoke_quick.py --tag core,services      # 多个 tag")
    print()


# ────────────────────── main ──────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="快速 smoke 工具 (按改动选相关测试, 不跑全量)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("paths", nargs="*", help="改动文件路径 (可多个)")
    ap.add_argument("--full", action="store_true", help="跑全量 38 个 smoke")
    ap.add_argument("--fast", action="store_true", help="跑 5 个核心 smoke (默认)")
    ap.add_argument("--tag", help="按 tag 选 (逗号分隔)")
    ap.add_argument("--list", action="store_true", help="列出所有分类")
    ap.add_argument("--timeout", type=float, default=30.0, help="单个 smoke 超时秒数 (默认 30)")
    args = ap.parse_args()

    if args.list:
        cmd_list()
        return 0

    if args.full:
        return run_batch(FULL_SMOKES, "--full", timeout=args.timeout)

    if args.tag:
        smokes = select_by_tags(args.tag.split(","))
        return run_batch(smokes, f"--tag {args.tag}", timeout=args.timeout)

    if args.paths:
        smokes = select_by_files(args.paths)
        rel_paths = ", ".join(Path(p).name for p in args.paths[:3])
        return run_batch(smokes, f"files: {rel_paths}", timeout=args.timeout)

    # 默认 fast
    return run_batch(FAST_SMOKES, "--fast (默认)", timeout=args.timeout)


if __name__ == "__main__":
    # Windows multiprocessing 必需
    multiprocessing.freeze_support()
    sys.exit(main())
