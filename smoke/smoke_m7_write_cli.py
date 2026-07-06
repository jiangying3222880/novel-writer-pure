"""
smoke_m7_write_cli.py - M7-A 写入类 CLI smoke.

验证:
- project create: --name 必填, --dry-run 不写, --json 返回新行
- book create: --project + --volume-no 必填, --dry-run, --json
- chapter create: --book + --chapter-no 必填, --status 校验, --dry-run, --json
- 错误路径: 缺必填参数 → 非 0, --status 非法 → 非 0
- 数据回流: 写入后能立刻 list/show 看到
- DB 清理: 测试结束把临时 project 删了
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("NOVEL_WRITER_TESTING", "1")

CHECKS: list = []
FAILURES: list = []
_CREATED_PROJECTS: list[str] = []  # 测试结束清


def check(cond: bool, name: str, detail: str = "") -> None:
    CHECKS.append((cond, name))
    if not cond:
        FAILURES.append(f"{name} - {detail}")
        print(f"  ❌ {name} - {detail}")
    else:
        print(f"  ✅ {name}")


def run_cli(*args: str, timeout: int = 60) -> tuple[int, str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        [sys.executable, "-m", "app.cli", *args],
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=timeout,
    )
    return r.returncode, r.stdout, r.stderr


def cleanup() -> None:
    """测试结束清临时 project, 不污染主 DB."""
    if not _CREATED_PROJECTS:
        return
    from app.services import project_service
    for pid in _CREATED_PROJECTS:
        try:
            project_service.delete(pid)
        except Exception:
            pass


def main() -> int:
    print("[smoke_m7_write_cli] M7-A 写入类 CLI smoke\n")

    # 注入 headless 弹窗
    from app.adapters.headless.dialogs_impl import install as _install_dialogs
    _install_dialogs()

    marker = "M7-Smoke-Marker-20260613"

    # ── Part 1: project create ──
    print("── Part 1: project create ──")

    # --dry-run (不写)
    code, out, err = run_cli("project", "create", "--name", f"{marker}-dry", "--dry-run")
    check(code == 0, f"project create --dry-run 退出码 0 (got {code}, err={err[:200]})")
    check("[DRY-RUN]" in out and "project create" in out, "project --dry-run 打印横幅 + 参数")
    check(f"{marker}-dry" in out, "project --dry-run 包含 --name")

    # dry-run 之后, list 应当找不到 (没真写)
    code, out, _ = run_cli("project", "list", "--json")
    try:
        data = json.loads(out)
        ids = [p["id"] for p in data.get("projects", [])]
        check(not any(f"{marker}-dry" in (p.get("name") or "") for p in data.get("projects", [])),
              "project --dry-run 没真写, list 找不到")
    except Exception as e:
        check(False, f"project list 解析失败: {e}")

    # 真正创建
    code, out, err = run_cli("project", "create",
                             "--name", f"{marker}-1",
                             "--book-title", "测试书",
                             "--genre", "奇幻",
                             "--word-target", "50000",
                             "--json")
    check(code == 0, f"project create 退出码 0 (got {code}, err={err[:200]})")
    proj = None
    try:
        proj = json.loads(out)
        check(proj.get("name") == f"{marker}-1", f"project create name == '{marker}-1' (got {proj.get('name')})")
        check(proj.get("book_title") == "测试书", f"book_title == '测试书' (got {proj.get('book_title')})")
        check(proj.get("word_target") == 50000, f"word_target == 50000 (got {proj.get('word_target')})")
        check(bool(proj.get("id")), "project create 返回 id")
    except Exception as e:
        check(False, f"project create --json 解析失败: {e}")
    if proj and proj.get("id"):
        _CREATED_PROJECTS.append(proj["id"])

    # text 模式
    code, out, err = run_cli("project", "create",
                             "--name", f"{marker}-2",
                             "--json")
    check(code == 0, f"project create 简化参数退出码 0 (got {code}, err={err[:200]})")
    try:
        p2 = json.loads(out)
        check(p2.get("name") == f"{marker}-2", "text 模式 name 正确")
        check(p2.get("word_target") == 200000, f"word_target 默认 200000 (got {p2.get('word_target')})")
        if p2.get("id"):
            _CREATED_PROJECTS.append(p2["id"])
    except Exception as e:
        check(False, f"project create 简化 --json 解析失败: {e}")

    # 错误路径: 缺 --name
    code, out, err = run_cli("project", "create")
    check(code != 0, f"project create 缺 --name 退出非 0 (got {code})")

    # 错误路径: --name 空字符串
    code, out, err = run_cli("project", "create", "--name", "   ")
    check(code != 0, f"project create --name 空字符串退出非 0 (got {code})")

    # 错误路径: name 太长 (SQLite 默认不限, services 不强制, 这里只保证不崩)
    code, out, err = run_cli("project", "create", "--name", "x" * 5000, "--json")
    check(code == 0, f"project create 5000 字 name 不崩 (got {code})")

    # ── Part 2: book create ──
    print("\n── Part 2: book create ──")

    if not proj:
        check(False, "Part 2 跳过: 没有可用的 project id")
    else:
        pid = proj["id"]

        # dry-run
        code, out, _ = run_cli("book", "create", "--project", pid,
                               "--volume-no", "1", "--title", "DRY 卷", "--dry-run")
        check(code == 0, f"book create --dry-run 退出码 0 (got {code})")
        check("[DRY-RUN]" in out and "book create" in out, "book --dry-run 横幅正确")

        # 真创建
        code, out, err = run_cli("book", "create", "--project", pid,
                                 "--volume-no", "1", "--title", "第一卷", "--json")
        check(code == 0, f"book create 退出码 0 (got {code}, err={err[:200]})")
        bk = None
        try:
            bk = json.loads(out)
            check(bk.get("title") == "第一卷", f"book title == '第一卷' (got {bk.get('title')})")
            check(bk.get("volume_no") == 1, f"volume_no == 1 (got {bk.get('volume_no')})")
            check(bk.get("project_id") == pid, f"project_id 匹配 (got {bk.get('project_id')})")
        except Exception as e:
            check(False, f"book create --json 解析失败: {e}")

        # 错误路径: project 不存在
        code, out, err = run_cli("book", "create",
                                 "--project", "00000000-0000-0000-0000-000000000000",
                                 "--volume-no", "1")
        check(code != 0, f"book create project 不存在退出非 0 (got {code})")

        # 错误路径: 缺 --volume-no
        code, out, err = run_cli("book", "create", "--project", pid)
        check(code != 0, f"book create 缺 --volume-no 退出非 0 (got {code})")

        # ── Part 3: chapter create ──
        print("\n── Part 3: chapter create ──")

        if not bk:
            check(False, "Part 3 跳过: 没有可用的 book id")
        else:
            bid = bk["id"]

            # dry-run
            code, out, _ = run_cli("chapter", "create", "--book", bid,
                                   "--chapter-no", "1", "--title", "DRY 章节", "--dry-run")
            check(code == 0, f"chapter create --dry-run 退出码 0 (got {code})")
            check("[DRY-RUN]" in out, "chapter --dry-run 横幅正确")

            # 真创建
            code, out, err = run_cli("chapter", "create", "--book", bid,
                                     "--chapter-no", "1", "--title", "开篇", "--json")
            check(code == 0, f"chapter create 退出码 0 (got {code}, err={err[:200]})")
            ch = None
            try:
                ch = json.loads(out)
                check(ch.get("title") == "开篇", f"chapter title == '开篇' (got {ch.get('title')})")
                check(ch.get("chapter_no") == 1, f"chapter_no == 1 (got {ch.get('chapter_no')})")
                check(ch.get("status") == "draft", f"status 默认 draft (got {ch.get('status')})")
                check(ch.get("book_id") == bid, "book_id 匹配")
            except Exception as e:
                check(False, f"chapter create --json 解析失败: {e}")

            # 自定义 status
            code, out, err = run_cli("chapter", "create", "--book", bid,
                                     "--chapter-no", "2", "--title", "中段", "--status", "generated", "--json")
            check(code == 0, f"chapter create --status=generated 退出码 0 (got {code})")
            try:
                ch2 = json.loads(out)
                check(ch2.get("status") == "generated", f"status == 'generated' (got {ch2.get('status')})")
            except Exception as e:
                check(False, f"chapter create --status=generated --json 解析失败: {e}")

            # 错误路径: --status 非法
            code, out, err = run_cli("chapter", "create", "--book", bid,
                                     "--chapter-no", "3", "--status", "bogus")
            check(code != 0, f"chapter create --status=bogus 退出非 0 (got {code}, err={err[:200]})")

            # 错误路径: book 不存在
            code, out, err = run_cli("chapter", "create",
                                     "--book", "00000000-0000-0000-0000-000000000000",
                                     "--chapter-no", "1")
            check(code != 0, f"chapter create book 不存在退出非 0 (got {code})")

            # 错误路径: 缺 --chapter-no
            code, out, err = run_cli("chapter", "create", "--book", bid)
            check(code != 0, f"chapter create 缺 --chapter-no 退出非 0 (got {code})")

    # ── Part 4: 端到端回环 (create → list → show) ──
    print("\n── Part 4: 端到端回环 ──")
    code, out, _ = run_cli("project", "list", "--json")
    try:
        data = json.loads(out)
        names = [p.get("name") for p in data.get("projects", [])]
        check(f"{marker}-1" in names, f"project list 能找到刚建的 '{marker}-1'")
    except Exception as e:
        check(False, f"project list 解析失败: {e}")

    if proj:
        code, out, _ = run_cli("project", "show", proj["id"])
        check(code == 0 and f"{marker}-1" in out, "project show 能找到刚建的")

    # 清理
    cleanup()

    # ── 收尾 ──
    print(f"\n── 总结 ──")
    print(f"  通过: {len(CHECKS) - len(FAILURES)}/{len(CHECKS)}")
    if FAILURES:
        print("  ❌ 失败:")
        for f in FAILURES:
            print(f"     - {f}")
        return 1
    print("  ✅ 全部通过")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        # 兜底清理 (异常时也清)
        try:
            cleanup()
        except Exception:
            pass
