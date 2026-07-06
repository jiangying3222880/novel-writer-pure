"""
H3 SMOKE: 剧情推演 (Plot Deduction) 插件
- 剧情线 CRUD (主线/支线/旁支, 活跃/休眠/已结)
- 伏笔 CRUD (已埋/已回收/已放弃)
- find_holes: 长未回收伏笔 / 长休眠主线
- suggest_next: 推演下一章走向 (含压力计)
- stats 统计

5 分钟自动超时
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

# stdout UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 5 分钟全局超时
_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_h3_plot_deduction 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 隔离真实数据
# ============================================================
TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_h3_"))
DB_PATH = TMPDIR / "test.db"
STORY_DIR = TMPDIR / "story"
STORY_DIR.mkdir(parents=True, exist_ok=True)

import app.app_paths
app.app_paths.sqlite_path = lambda: DB_PATH

import app.services.file_store
app.services.file_store.BASE_DIR = STORY_DIR

# ============================================================
# 真正的 import
# ============================================================
from app.services import (
    project_service, book_service, chapter_service,
)
from app.services.db import init_db

# ────────────────────── 插件已废弃 (V3.4+ SKIP) ──────────────────────
try:
    from app.plugins.builtin.plot_deduction_plugin import (
        PlotDeductionPlugin,
        THREAD_MAIN, THREAD_SUBPLOT, THREAD_SIDE,
        STATUS_ACTIVE, STATUS_DORMANT, STATUS_RESOLVED,
        FORESHADOW_PLANTED, FORESHADOW_PAIDOFF, FORESHADOW_ABANDONED,
        PlotThread, Foreshadow, PlotHole,
    )
    _HAS_PLUGINS = True
except ImportError:
    _HAS_PLUGINS = False
    PlotDeductionPlugin = None  # type: ignore
    THREAD_MAIN = THREAD_SUBPLOT = THREAD_SIDE = ""
    STATUS_ACTIVE = STATUS_DORMANT = STATUS_RESOLVED = ""
    FORESHADOW_PLANTED = FORESHADOW_PAIDOFF = FORESHADOW_ABANDONED = ""

    class _StubClass:
        def __getattr__(self, n): return None

    PlotThread = Foreshadow = PlotHole = _StubClass  # type: ignore


fails: list[str] = []
passed: int = 0


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


def _setup() -> tuple[PlotDeductionPlugin, str, str]:
    """建项目 + 插件 setup."""
    p = project_service.create("H3 测试", genre="仙侠")
    pj = p["id"]
    b = book_service.create(pj, 1, title="第一卷")
    plugin = PlotDeductionPlugin()
    plugin.setup({})
    return plugin, pj, b["id"]


# ============================================================
# 测试 1: 剧情线 CRUD
# ============================================================
def test_thread_crud(plugin: PlotDeductionPlugin, pid: str) -> None:
    section("[H3 1] 剧情线 CRUD")

    # add
    t1 = plugin.add_thread(pid, "林轩复仇", kind=THREAD_MAIN, importance=9, started_chapter=1,
                            description="主角复仇主线")
    check(t1.id.startswith("pt_"), f"thread id 格式 (实际 {t1.id})")
    check(t1.status == STATUS_ACTIVE, "默认 status=active")
    check(t1.kind == THREAD_MAIN, "kind=main")
    check(t1.importance == 9, f"importance=9 (实际 {t1.importance})")

    # add 支线
    t2 = plugin.add_thread(pid, "师妹感情线", kind=THREAD_SUBPLOT, started_chapter=3)
    check(t2.kind == THREAD_SUBPLOT, "支线 kind=subplot")

    # add 旁支
    t3 = plugin.add_thread(pid, "路人甲出场", kind=THREAD_SIDE)
    check(t3.kind == THREAD_SIDE, "旁支 kind=side")

    # list
    threads = plugin.list_threads(pid)
    check(len(threads) == 3, f"列出 3 条 (实际 {len(threads)})")
    # 按 importance DESC 排序
    check(threads[0].importance == 9, f"按 importance 排 (实际 {threads[0].importance})")

    # list with filter
    main_only = plugin.list_threads(pid, kind=THREAD_MAIN)
    check(len(main_only) == 1, f"主线过滤 (实际 {len(main_only)})")

    # update
    plugin.update_thread(t1.id, name="林轩复仇 (更新)", description="含家仇 + 师仇")
    t1_upd = plugin.get_thread(t1.id)
    check("更新" in t1_upd.name, "update 生效")

    # resolve
    plugin.resolve_thread(t1.id, resolved_chapter=50)
    t1_resolved = plugin.get_thread(t1.id)
    check(t1_resolved.status == STATUS_RESOLVED, "resolve 后 status=resolved")
    check(t1_resolved.resolved_chapter == 50, f"resolved_chapter=50 (实际 {t1_resolved.resolved_chapter})")

    # delete
    plugin.delete_thread(t3.id)
    threads_after_del = plugin.list_threads(pid)
    check(len(threads_after_del) == 2, f"删除后剩 2 条 (实际 {len(threads_after_del)})")

    # 非法 kind
    try:
        plugin.add_thread(pid, "bad", kind="xxx")
        check(False, "非法 kind 应抛 ValueError")
    except ValueError:
        check(True, "非法 kind 抛 ValueError")

    # 非法 importance
    try:
        plugin.add_thread(pid, "bad", importance=20)
        check(False, "非法 importance 应抛 ValueError")
    except ValueError:
        check(True, "非法 importance 抛 ValueError")


# ============================================================
# 测试 2: 伏笔 CRUD
# ============================================================
def test_foreshadow_crud(plugin: PlotDeductionPlugin, pid: str) -> None:
    section("[H3 2] 伏笔 CRUD")

    # plant
    f1 = plugin.plant_foreshadow(pid, "山洞里那把锈剑", planted_chapter=2,
                                  planted_in_text="石缝间, 一把锈迹斑斑的长剑斜插其中.",
                                  note="可能是上古神兵")
    check(f1.id.startswith("fs_"), f"foreshadow id 格式 (实际 {f1.id})")
    check(f1.status == FORESHADOW_PLANTED, "默认 status=planted")

    # plant 多个
    f2 = plugin.plant_foreshadow(pid, "神秘女修身份", planted_chapter=5)
    f3 = plugin.plant_foreshadow(pid, "师门血案真相", planted_chapter=1)

    # list
    all_fs = plugin.list_foreshadows(pid)
    check(len(all_fs) == 3, f"列出 3 条 (实际 {len(all_fs)})")

    # list by status
    planted = plugin.list_foreshadows(pid, status=FORESHADOW_PLANTED)
    check(len(planted) == 3, f"已埋 3 条 (实际 {len(planted)})")

    # payoff
    f1_paid = plugin.payoff_foreshadow(f1.id, paidoff_chapter=20, paidoff_in_text="他拔剑而起, 一道寒光划破夜空.")
    check(f1_paid.status == FORESHADOW_PAIDOFF, "payoff 后 status=paidoff")
    check(f1_paid.paidoff_chapter == 20, f"paidoff_chapter=20 (实际 {f1_paid.paidoff_chapter})")

    # abandon
    f3_aban = plugin.abandon_foreshadow(f3.id, note="后期放弃了这条线")
    check(f3_aban.status == FORESHADOW_ABANDONED, "abandon 后 status=abandoned")

    # list by status
    paid = plugin.list_foreshadows(pid, status=FORESHADOW_PAIDOFF)
    check(len(paid) == 1, f"已回收 1 条 (实际 {len(paid)})")

    # delete
    plugin.delete_foreshadow(f2.id)
    remaining = plugin.list_foreshadows(pid)
    check(len(remaining) == 2, f"删除后剩 2 条 (实际 {len(remaining)})")


# ============================================================
# 测试 3: 找漏洞 (find_holes)
# ============================================================
def test_find_holes(plugin: PlotDeductionPlugin, pid: str, bid: str) -> None:
    section("[H3 3] 找漏洞 (find_holes)")

    # 准备: 建 50 章, 让漏洞能触发
    for i in range(1, 51):
        chapter_service.create(bid, i, title=f"第{i}章")

    # 埋一个 5 章前的伏笔, 没回收
    old_fs = plugin.plant_foreshadow(pid, "远古封印钥匙", planted_chapter=5)
    # 埋一个 5 章前的休眠主线
    dormant_thread = plugin.add_thread(pid, "支线 B", kind=THREAD_MAIN, started_chapter=5)
    # 立即休眠
    plugin.update_thread(dormant_thread.id, status=STATUS_DORMANT)

    # 找漏洞 (默认 30 章阈值)
    holes = plugin.find_holes(pid, max_unpaid_chapters=20)
    check(len(holes) >= 2, f"至少 2 个漏洞 (实际 {len(holes)})")
    # 验证 kind
    kinds = {h.kind for h in holes}
    check("foreshadow_unpaid" in kinds, f"含 foreshadow_unpaid (实际 {kinds})")
    check("thread_dormant_too_long" in kinds, f"含 thread_dormant_too_long (实际 {kinds})")
    # 验证 severity
    sevs = {h.severity for h in holes}
    check("high" in sevs or "medium" in sevs, f"有 severity (实际 {sevs})")
    # message 非空
    for h in holes:
        check(len(h.message) > 0, f"hole.message 非空 ({h.kind})")
    # to_dict 字段
    d = holes[0].to_dict()
    check("kind" in d and "severity" in d and "message" in d, "hole.to_dict 字段完整")


# ============================================================
# 测试 4: 推演下一章 (suggest_next)
# ============================================================
def test_suggest_next(plugin: PlotDeductionPlugin, pid: str, bid: str) -> None:
    section("[H3 4] 推演下一章 (suggest_next)")

    # 准备: 1 章, 当前压力未变 (无 prompt_assembler)
    c1 = chapter_service.create(bid, 100, title="推演测试章")
    # 加活跃主线
    plugin.add_thread(pid, "推演主线 A", kind=THREAD_MAIN, started_chapter=100, importance=8)
    # 加未回收伏笔
    plugin.plant_foreshadow(pid, "推演伏笔 1", planted_chapter=99)

    # 推演
    result = plugin.suggest_next(pid)
    check("active_threads" in result, "active_threads 字段")
    check("unpaid_foreshadows" in result, "unpaid_foreshadows 字段")
    check("pressure_zone" in result, "pressure_zone 字段")
    check("recommendations" in result, "recommendations 字段")
    check("hint" in result, "hint 字段")
    check(isinstance(result["active_threads"], list), "active_threads 是 list")
    check(isinstance(result["recommendations"], list), "recommendations 是 list")
    check(len(result["active_threads"]) >= 1, f"至少 1 条活跃线程 (实际 {len(result['active_threads'])})")
    check(len(result["unpaid_foreshadows"]) >= 1, f"至少 1 条未回收伏笔 (实际 {len(result['unpaid_foreshadows'])})")
    check(len(result["hint"]) > 0, f"hint 非空 (实际 '{result['hint'][:50]}')")
    # 验证 hint 含建议
    check("建议" in result["hint"], f"hint 含'建议' (实际 '{result['hint'][:80]}')")
    # 压力区是合法值
    check(result["pressure_zone"] in ("green", "yellow", "red"), f"压力区合法 (实际 {result['pressure_zone']})")


# ============================================================
# 测试 5: 统计 (stats)
# ============================================================
def test_stats(plugin: PlotDeductionPlugin, pid: str) -> None:
    section("[H3 5] 统计 (stats)")

    stats = plugin.stats(pid)
    check("total_threads" in stats, "total_threads 字段")
    check("by_thread_status" in stats, "by_thread_status 字段")
    check("by_thread_kind" in stats, "by_thread_kind 字段")
    check("total_foreshadows" in stats, "total_foreshadows 字段")
    check("by_foreshadow_status" in stats, "by_foreshadow_status 字段")
    # by_thread_status 3 项
    check(set(stats["by_thread_status"].keys()) == {STATUS_ACTIVE, STATUS_DORMANT, STATUS_RESOLVED},
          f"by_thread_status 3 项 (实际 {set(stats['by_thread_status'].keys())})")
    # by_thread_kind 3 项
    check(set(stats["by_thread_kind"].keys()) == {THREAD_MAIN, THREAD_SUBPLOT, THREAD_SIDE},
          f"by_thread_kind 3 项 (实际 {set(stats['by_thread_kind'].keys())})")
    # 数字都是 int >= 0
    for k, v in stats["by_thread_status"].items():
        check(isinstance(v, int) and v >= 0, f"by_thread_status[{k}] = {v}")
    for k, v in stats["by_thread_kind"].items():
        check(isinstance(v, int) and v >= 0, f"by_thread_kind[{k}] = {v}")


# ============================================================
# 测试 6: 元信息 (get_meta)
# ============================================================
def test_meta(plugin: PlotDeductionPlugin) -> None:
    section("[H3 6] 元信息 (get_meta)")

    meta = plugin.get_meta()
    check(meta["name"] == "plot_deduction", f"name=plot_deduction (实际 {meta['name']})")
    check(meta["version"] == "1.0.0", f"version=1.0.0 (实际 {meta['version']})")
    check("剧情" in meta["description"] or "推演" in meta["description"], f"description 含'推演'")
    check("enabled" in meta and meta["enabled"], "enabled=True")
    check("required_role" in meta, "required_role 字段")
    check("features" in meta, "features 字段")
    check(isinstance(meta["features"], list) and len(meta["features"]) >= 3, f"features 列表 (实际 {len(meta['features'])} 条)")


# ============================================================
# 测试 7: 序列化 (to_dict 字段)
# ============================================================
def test_serialization(plugin: PlotDeductionPlugin, pid: str) -> None:
    section("[H3 7] 序列化 (to_dict 字段)")

    t = plugin.add_thread(pid, "序列化测试", kind=THREAD_SUBPLOT)
    d = t.to_dict()
    expected_keys = {"id", "project_id", "name", "kind", "kind_label",
                     "status", "status_label", "description",
                     "started_chapter", "resolved_chapter", "importance"}
    check(set(d.keys()) >= expected_keys, f"thread.to_dict 含预期字段 (实际 {set(d.keys())})")
    check(d["kind_label"] == "支线", f"kind_label 翻译 (实际 {d['kind_label']})")
    check(d["status_label"] == "活跃", f"status_label 翻译 (实际 {d['status_label']})")

    f = plugin.plant_foreshadow(pid, "序列化测试伏笔")
    d = f.to_dict()
    check("content" in d and d["content"] == "序列化测试伏笔", "foreshadow.to_dict content")
    check(d["status_label"] == "已埋", f"foreshadow status_label 翻译 (实际 {d['status_label']})")


# ============================================================
# Main
# ============================================================
def main() -> int:
    if not _HAS_PLUGINS:
        print("⊘ smoke_h3_plot_deduction: SKIP (app.plugins 已废弃)")
        return 0
    print("=" * 60)
    print("H3 SMOKE: 剧情推演插件 (plot_deduction)")
    print("=" * 60)
    print(f"[setup] tmpdir = {TMPDIR}")

    init_db()
    from app.db import connection
    connection.init(DB_PATH)
    print(f"[setup] DB = {DB_PATH}")

    plugin, pid, bid = _setup()
    print(f"[setup] project_id = {pid}, book_id = {bid}")

    tests = [
        lambda: test_thread_crud(plugin, pid),
        lambda: test_foreshadow_crud(plugin, pid),
        lambda: test_find_holes(plugin, pid, bid),
        lambda: test_suggest_next(plugin, pid, bid),
        lambda: test_stats(plugin, pid),
        lambda: test_meta(plugin),
        lambda: test_serialization(plugin, pid),
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            fails.append(f"测试抛异常: {type(e).__name__}: {e}")
            print(f"  [EXC] {type(e).__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"汇总: {passed} 通过, {len(fails)} 失败")
    if fails:
        print("\n失败列表:")
        for f in fails[:20]:
            print(f"  - {f}")
    print("=" * 60)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
