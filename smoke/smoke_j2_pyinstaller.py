"""
J2 PyInstaller 打包 SMOKE 测试

覆盖:
  1. spec 文件存在 + 语法 OK
  2. spec 中所有 datas 源路径存在
  3. spec 中所有 hiddenimports 模块可 import
  4. spec 中 excludes 不含误排除
  5. build_pyinstaller.py 语法 + 关键函数
  6. 入口 app/__main__.py 存在
  7. 入口 app/main.py main() 可导入
  8. PyInstaller 已安装
  9. spec 含 COLLECT (one-folder 模式)

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

# 5 分钟超时
_SMOKE_TIMEOUT = 300


def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_j2_pyinstaller 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)


_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 测试统计
# ============================================================
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


# ============================================================
# 测试 1: spec 文件存在 + 语法
# ============================================================
def test_spec_exists() -> None:
    section("[1] spec 文件存在 + 语法")
    spec = ROOT / "novel_writer.spec"
    check(spec.exists(), f"spec 存在: {spec}")

    # 编译语法
    try:
        compile(spec.read_text(encoding="utf-8"), str(spec), "exec")
        check(True, "spec 语法 OK")
    except SyntaxError as e:
        check(False, f"spec 语法错: {e}")


# ============================================================
# 测试 2: spec 中 datas 源路径全部存在
# ============================================================
def test_spec_datas_paths() -> None:
    section("[2] spec datas 源路径")
    spec = ROOT / "novel_writer.spec"
    import re
    # 匹配 (str(...) / "..." ...) , "dest") 模式
    # 也匹配 ("src", "dest") 简单模式
    src_pat = re.compile(r'\(\s*str\(APP_DIR\s*/\s*["\']([^"\']+)["\']\s*/\s*["\']?([^"\']*)["\']?')
    text = spec.read_text(encoding="utf-8")
    found: list = []
    for m in src_pat.finditer(text):
        # 拼接路径
        parts = [g for g in m.groups() if g]
        if parts:
            found.append("/".join(parts))
    # 也支持简单 ("path",) 模式
    simple_pat = re.compile(r'\(\s*r?["\']([^"\']+\.[a-z]+)["\']\s*,')
    for m in simple_pat.finditer(text):
        found.append(m.group(1))

    # 去重
    found = list(set(found))
    print(f"  [info] 找到 {len(found)} 个 datas 源路径")
    missing = []
    for p in found:
        pp = ROOT / "app" / p
        if not pp.exists():
            missing.append(p)
            print(f"  [MISS] {p}")
            continue
        check(True, f"源路径存在: {p}")
    for m in missing:
        check(False, f"源路径缺失: {m}")


# ============================================================
# 测试 3: spec 中关键 hiddenimports 可 import
# ============================================================
def test_spec_hiddenimports() -> None:
    section("[3] spec hiddenimports (关键项抽样)")
    spec = ROOT / "novel_writer.spec"
    import re
    text = spec.read_text(encoding="utf-8")
    # 抽所有 "app.xxx" / "PySide6.X" 字符串
    mods_pat = re.compile(r'^\s*"([\w.]+)"\s*,?\s*$', re.M)
    mods = [m.group(1) for m in mods_pat.finditer(text) if "." in m.group(1)]
    print(f"  [info] 找到 {len(mods)} 个 hiddenimport 项")

    # 抽 8 个关键模块验证可 import (PyInstaller 静默漏模块很常见)
    key_samples = [
        "app.agents.orchestrator",
        "app.agents.helpers.storyteller",
        "app.ui.main_window",
        "app.ui.tabs.editor_tab",
        "app.validators.repetition",
        "app.plugins.loader",
        "app.services.subtext",
        "app.knowledge.bm25",
    ]
    for mod in key_samples:
        check(mod in mods, f"hiddenimports 含 {mod}")
        try:
            __import__(mod)
            check(True, f"实际可 import: {mod}")
        except Exception as e:
            check(False, f"import 失败 {mod}: {type(e).__name__}: {e}")


# ============================================================
# 测试 4: spec 不误排除关键模块
# ============================================================
def test_spec_excludes() -> None:
    section("[4] spec excludes 不误伤")
    spec = ROOT / "novel_writer.spec"
    text = spec.read_text(encoding="utf-8")
    must_not_exclude = ["PySide6", "app", "app.ui", "app.services", "jieba", "numpy", "sklearn"]
    for m in must_not_exclude:
        # 简单 grep: 排除列表不应含 (允许在 hiddenimports 出现)
        if m in text:
            # 找 "excludes = [" 段
            import re
            m_excl = re.search(r"excludes\s*=\s*\[(.*?)\]", text, re.S)
            if m_excl:
                block = m_excl.group(1)
                is_in_excl = re.search(rf'["\']{re.escape(m)}["\']', block)
                check(not is_in_excl, f"{m} 不在 excludes")
            else:
                check(True, f"{m} 不在 excludes (excludes 段未找到)")
        else:
            check(True, f"{m} 不在 spec (可能为可选)")


# ============================================================
# 测试 5: 入口 + main()
# ============================================================
def test_entry_point() -> None:
    section("[5] 入口 + main()")
    main_py = ROOT / "app" / "main.py"
    main2 = ROOT / "app" / "__main__.py"
    check(main_py.exists(), f"app/main.py 存在")
    check(main2.exists(), f"app/__main__.py 存在")
    # 抽 spec 入口: 应该是 app/__main__.py
    spec = ROOT / "novel_writer.spec"
    text = spec.read_text(encoding="utf-8")
    check("__main__.py" in text, "spec 入口含 __main__.py")
    # main() 可 import
    from app.main import main as app_main
    check(callable(app_main), "app.main.main 可调用")


# ============================================================
# 测试 6: PyInstaller 已安装
# ============================================================
def test_pyinstaller_installed() -> None:
    section("[6] PyInstaller 已安装")
    try:
        import PyInstaller
        ver = getattr(PyInstaller, "__version__", "?")
        check(True, f"PyInstaller v{ver} 已安装")
    except ImportError:
        check(False, "PyInstaller 未安装 (pip install pyinstaller)")


# ============================================================
# 测试 7: spec 含 COLLECT (one-folder 模式)
# ============================================================
def test_spec_onefolder() -> None:
    section("[7] spec 模式 (one-folder vs onefile)")
    spec = ROOT / "novel_writer.spec"
    text = spec.read_text(encoding="utf-8")
    has_collect = "COLLECT(" in text
    has_exe = "EXE(" in text
    check(has_collect, "spec 含 COLLECT (one-folder)")
    check(has_exe, "spec 含 EXE")
    # one-folder 关键: exclude_binaries=True + COLLECT 存在
    check("exclude_binaries=True" in text, "EXE 用 exclude_binaries=True (one-folder)")


# ============================================================
# 测试 8: build_pyinstaller.py 脚本
# ============================================================
def test_build_script() -> None:
    section("[8] build_pyinstaller.py 脚本")
    script = ROOT / "scripts" / "build_pyinstaller.py"
    check(script.exists(), f"脚本存在: {script}")
    # 编译语法
    try:
        compile(script.read_text(encoding="utf-8"), str(script), "exec")
        check(True, "脚本语法 OK")
    except SyntaxError as e:
        check(False, f"脚本语法错: {e}")
        return

    # import + 检查关键函数
    sys.path.insert(0, str(script.parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_pyinstaller", str(script))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        check(False, f"脚本 exec 失败: {e}")
        return
    for fn in ("check_pyinstaller", "check_spec_syntax", "clean_outputs", "build", "main"):
        check(hasattr(mod, fn), f"脚本含函数 {fn}")


# ============================================================
# 测试 8.5: spec 关键变量 + 数据可被 PyInstaller 工具读
# ============================================================
def test_spec_exec() -> None:
    section("[8.5] spec 关键变量 + PyInstaller 工具读")
    spec = ROOT / "novel_writer.spec"
    # 1) 准备 namespace
    import os
    ns = {
        "SPECPATH": str(ROOT),
        "__file__": str(spec),
        "os": os,
        "sys": sys,
    }
    # 2) 用 stub 代替 PyInstaller classes (避免 Analysis 跑全项目)
    class _Stub:
        def __init__(self, *a, **kw): pass
        def __getattr__(self, k): return self
        def __call__(self, *a, **kw): return self
    for cls in ("Analysis", "PYZ", "EXE", "COLLECT"):
        ns[cls] = _Stub
    try:
        code = spec.read_text(encoding="utf-8")
        compile(code, str(spec), "exec")
        exec(code, ns)
        check(True, "spec exec OK (PyInstaller classes stubbed)")
    except Exception as e:
        import traceback
        traceback.print_exc()
        check(False, f"spec exec 失败: {type(e).__name__}: {e}")
        return

    # 3) 验证关键变量
    for var in ("datas", "hiddenimports", "excludes"):
        if var in ns:
            check(True, f"spec 产出 {var} 存在")
        else:
            check(False, f"spec 产出 {var} 缺失")

    # 4) 验证 datas 是 list[tuple]
    if "datas" in ns:
        datas = ns["datas"]
        check(isinstance(datas, list), f"datas 是 list (n={len(datas)})")
        check(all(isinstance(d, tuple) and len(d) == 2 for d in datas),
              f"datas 全部 (src, dest) tuple")
        # 抽 src 路径
        for src, dest in datas:
            if not Path(src).exists():
                check(False, f"datas 源路径缺失: {src} (dest={dest})")
        # 至少 5 个
        check(len(datas) >= 5, f"datas 数量 ≥ 5 (实际 {len(datas)})")

    # 5) hiddenimports 数量
    if "hiddenimports" in ns:
        hi = ns["hiddenimports"]
        check(isinstance(hi, list), f"hiddenimports 是 list")
        check(len(hi) >= 50, f"hiddenimports ≥ 50 (实际 {len(hi)})")
        # 关键项
        must = ["PySide6.QtCore", "app", "app.ui.main_window", "app.agents.orchestrator",
                "app.validators.repetition", "jieba", "numpy"]
        for m in must:
            check(m in hi, f"hiddenimports 含 {m}")

    # 6) excludes 数量
    if "excludes" in ns:
        ex = ns["excludes"]
        check(isinstance(ex, list), "excludes 是 list")
        check("PySide6" not in ex, "excludes 不含 PySide6")
        check("PyQt5" in ex, "excludes 含 PyQt5 (避免冲突)")


# ============================================================
# 测试 9: 关键资源数据存在
# ============================================================
def test_resource_files() -> None:
    section("[9] 关键资源文件存在")
    must_exist = [
        "app/resources/seed_models.json",
        "app/resources/style.qss",
        "app/db/schema.sql",
        "app/db/migrations/028_app_settings.sql",
    ]
    for rel in must_exist:
        p = ROOT / rel
        check(p.exists(), f"{rel} 存在")


# ============================================================
# Main
# ============================================================
def main() -> int:
    print("=" * 60)
    print("J2 PyInstaller 打包 SMOKE: spec + 脚本 + 路径")
    print("=" * 60)

    test_spec_exists()
    test_spec_datas_paths()
    test_spec_hiddenimports()
    test_spec_excludes()
    test_entry_point()
    test_pyinstaller_installed()
    test_spec_onefolder()
    test_build_script()
    test_spec_exec()
    test_resource_files()

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
