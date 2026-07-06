"""
G10 SMOKE: 世界状态观察器 (World State Observer)
- observe_chapter: 观察 + 写快照
- get_entity_history: 实体历史
- get_chapter_changes: 本章变化
- get_project_snapshot: 完整快照
- get_chronicle: 编年史
- get_state_drift: 漂移检测
- get_relations_graph: 图谱数据
- get_observer_stats: 统计

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
    print(f"\n[TIMEOUT] smoke_g10_observer 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 隔离真实数据
# ============================================================

TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_g10_"))
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
    world_observer, worldbuilding, character_tracker, world_sync,
    project_service, book_service, chapter_service,
)
from app.services.db import init_db


# ============================================================
# 工具
# ============================================================

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


# ============================================================
# 公共 fixture
# ============================================================

def _setup_project():
    """建项目 + 书 + 5 章 + 3 实体 (1 角色 + 1 物品 + 1 地点)."""
    p = project_service.create("G10 测试项目", genre="玄幻")
    pid = p["id"]
    b = book_service.create(pid, 1, title="第一卷", synopsis="")
    bid = b["id"]
    # 加 3 实体到世界观
    char = worldbuilding.create(pid, worldbuilding.KIND_CHARACTER, "林渊",
                                description="主角", role="主角")
    item = worldbuilding.create(pid, worldbuilding.KIND_ITEM, "青锋剑",
                                description="主角佩剑", owner="林渊", tier="灵器")
    loc = worldbuilding.create(pid, worldbuilding.KIND_LOCATION, "青云宗",
                               description="宗门", region="东域")
    # 建 5 章
    chapters = []
    for i in range(1, 6):
        c = chapter_service.create(bid, i, title=f"第{i}章")
        chapters.append(c)
    return pid, bid, chapters, [char, item, loc]


# ============================================================
# 测试 1: observe_chapter
# ============================================================

def test_observe_chapter() -> None:
    section("[G10 1] observe_chapter: 观察 + 写快照")
    pid, bid, chapters, _ = _setup_project()

    # 第 1 章: 写到青云宗, 林渊持青锋剑
    draft1 = "林渊在青云宗修行, 手中持着青锋剑, 一剑破空。"
    result = world_observer.observe_chapter(pid, chapters[0]["id"], 1, draft1)
    check(result["snapshot_count"] >= 3, f"第 1 章快照 ≥ 3 (实际 {result['snapshot_count']})")
    check("林渊" in result["new_entities"], f"林渊 首次出现 → new (实际 {result['new_entities']})")
    check("青锋剑" in result["new_entities"], f"青锋剑 首次出现 → new")
    check("青云宗" in result["new_entities"], f"青云宗 首次出现 → new")


# ============================================================
# 测试 2: get_entity_history
# ============================================================

def test_entity_history() -> None:
    section("[G10 2] get_entity_history: 实体历史")
    pid, bid, chapters, _ = _setup_project()

    drafts = [
        "林渊在青云宗, 持青锋剑。",                    # 1
        "林渊回到青云宗, 继续修炼剑法, 青锋剑在握。",  # 2
        "林渊在青云宗闭关, 青锋剑插在身前。",          # 3
        "林渊远行, 飘然离去。",                        # 4 - 不提任何实体
        "林渊归来, 回到青云宗。",                      # 5 - 青云宗 重新出现
    ]
    for c, d in zip(chapters, drafts):
        world_observer.observe_chapter(pid, c["id"], c["chapter_no"], d)

    # 林渊: 5 章都有
    h = world_observer.get_entity_history(pid, "林渊")
    check(h is not None, "林渊 有历史")
    check(h.first_chapter == 1, f"林渊 first=1 (实际 {h.first_chapter})")
    check(h.last_chapter == 5, f"林渊 last=5 (实际 {h.last_chapter})")
    check(h.total_chapters == 5, f"林渊 total=5 (实际 {h.total_chapters})")
    check(h.is_active, f"林渊 is_active=True (last=current=5)")

    # 青云宗: 1,2,3,5 章出现 (第 4 章消失)
    h2 = world_observer.get_entity_history(pid, "青云宗")
    check(h2 is not None, "青云宗 有历史")
    check(h2.total_chapters == 4, f"青云宗 4 章 (实际 {h2.total_chapters})")
    check(4 not in h2.chapters, "第 4 章未出现 (青云宗)")

    # 青锋剑: 1,2,3 章 (第 4-5 章消失)
    h3 = world_observer.get_entity_history(pid, "青锋剑")
    check(h3 is not None, "青锋剑 有历史")
    check(h3.total_chapters == 3, f"青锋剑 3 章 (实际 {h3.total_chapters})")
    check(4 not in h3.chapters, "第 4 章未出现 (青锋剑)")
    check(5 not in h3.chapters, "第 5 章未出现 (青锋剑)")

    # list_tracked_entities
    entities = world_observer.list_tracked_entities(pid)
    check(len(entities) == 3, f"3 个实体 (实际 {len(entities)})")
    check("林渊" in entities, "林渊 在列表")
    check("青锋剑" in entities, "青锋剑 在列表")
    check("青云宗" in entities, "青云宗 在列表")


# ============================================================
# 测试 3: get_chapter_changes
# ============================================================

def test_chapter_changes() -> None:
    section("[G10 3] get_chapter_changes: 本章变化")
    pid, bid, chapters, _ = _setup_project()

    drafts = [
        "林渊在青云宗, 持青锋剑。",       # 1 - 全部 new
        "林渊回到青云宗, 继续修炼。",     # 2 - 林渊+青云宗 returning, 青锋剑 消失
        "林渊在青云宗闭关, 青锋剑插在身前。",  # 3 - 全部 returning, 状态延续
        "林渊远行, 飘然离去。",           # 4 - 林渊 returning, 青云宗+青锋剑 消失
        "林渊归来, 回到青云宗。",         # 5 - 青云宗 returning
    ]
    for c, d in zip(chapters, drafts):
        world_observer.observe_chapter(pid, c["id"], c["chapter_no"], d)

    # 第 1 章
    ch1 = world_observer.get_chapter_changes(pid, 1)
    check(len(ch1.new_entities) == 3, f"第 1 章 new=3 (实际 {len(ch1.new_entities)})")
    check(len(ch1.returning_entities) == 0, f"第 1 章 returning=0")

    # 第 2 章: 林渊+青云宗 returning, 青锋剑 消失 (1→2)
    ch2 = world_observer.get_chapter_changes(pid, 2)
    check(len(ch2.new_entities) == 0, f"第 2 章 new=0")
    check(len(ch2.returning_entities) == 2, f"第 2 章 returning=2 (实际 {len(ch2.returning_entities)})")
    check("青锋剑" in ch2.disappeared, f"第 2 章 青锋剑 消失 (1→2 实际 {ch2.disappeared})")

    # 第 3 章: 全部 returning, 无消失
    ch3 = world_observer.get_chapter_changes(pid, 3)
    check(len(ch3.new_entities) == 0, f"第 3 章 new=0")
    check(len(ch3.returning_entities) == 3, f"第 3 章 returning=3 (实际 {len(ch3.returning_entities)})")
    check(len(ch3.disappeared) == 0, f"第 3 章 disappeared=0")

    # 第 4 章: 青云宗+青锋剑 消失 (3→4)
    ch4 = world_observer.get_chapter_changes(pid, 4)
    check("青云宗" in ch4.disappeared, f"第 4 章 青云宗 消失 (实际 {ch4.disappeared})")
    check("青锋剑" in ch4.disappeared, f"第 4 章 青锋剑 消失 (实际 {ch4.disappeared})")

    # 第 5 章: 青云宗 返回
    ch5 = world_observer.get_chapter_changes(pid, 5)
    check("青云宗" in ch5.returning_entities, f"第 5 章 青云宗 returning (实际 {ch5.returning_entities})")


# ============================================================
# 测试 4: get_project_snapshot
# ============================================================

def test_project_snapshot() -> None:
    section("[G10 4] get_project_snapshot: 完整快照")
    pid, bid, chapters, _ = _setup_project()

    drafts = [
        "林渊在青云宗, 持青锋剑。",  # 1
        "林渊回到青云宗。",          # 2
        "林渊在青云宗。",            # 3
    ]
    for c, d in zip(chapters[:3], drafts):
        world_observer.observe_chapter(pid, c["id"], c["chapter_no"], d)

    snap = world_observer.get_project_snapshot(pid, 1)
    check(snap.chapter_no == 1, f"snapshot chapter=1")
    check(snap.total_entities == 3, f"3 个实体 (实际 {snap.total_entities})")
    check(worldbuilding.KIND_CHARACTER in snap.entities, "character 类存在")
    check("林渊" in snap.entities[worldbuilding.KIND_CHARACTER], "林渊 在 character")
    check(worldbuilding.KIND_LOCATION in snap.entities, "location 类存在")
    check(worldbuilding.KIND_ITEM in snap.entities, "item 类存在")
    check(snap.by_kind.get(worldbuilding.KIND_CHARACTER) == 1, "by_kind[character]=1")


# ============================================================
# 测试 5: get_chronicle
# ============================================================

def test_chronicle() -> None:
    section("[G10 5] get_chronicle: 编年史")
    pid, bid, chapters, _ = _setup_project()

    drafts = [
        "林渊在青云宗, 持青锋剑。",       # 1
        "林渊回到青云宗。",               # 2
        "林渊在青云宗闭关。",             # 3
    ]
    for c, d in zip(chapters[:3], drafts):
        world_observer.observe_chapter(pid, c["id"], c["chapter_no"], d)

    chronicle = world_observer.get_chronicle(pid, limit=10)
    check(len(chronicle) == 3, f"编年史 3 条 (实际 {len(chronicle)})")
    # 编年史按 chapter_no 倒序
    check(chronicle[0].chapter_no == 3, f"第 1 条 = 第 3 章 (实际 {chronicle[0].chapter_no})")
    check(chronicle[-1].chapter_no == 1, f"最后 1 条 = 第 1 章")


# ============================================================
# 测试 6: get_state_drift
# ============================================================

def test_state_drift() -> None:
    section("[G10 6] get_state_drift: 漂移检测")
    pid, bid, chapters, _ = _setup_project()

    # 第 1 章: 林渊 在青云宗
    draft1 = "林渊在青云宗修行。"
    world_observer.observe_chapter(pid, chapters[0]["id"], 1, draft1)

    # 第 2-5 章: 不再提林渊 (模拟他消失)
    for c in chapters[1:]:
        draft = "其他角色登场, 江湖风云变幻。"
        world_observer.observe_chapter(pid, c["id"], c["chapter_no"], draft)

    # 林渊 消失 4 章 (第 2-5 章)
    drift = world_observer.get_state_drift(pid, "林渊", threshold_chapters=3)
    check(drift is not None, f"林渊 有漂移 (实际 {drift})")
    if drift:
        check(drift.drift_kind == "absent", f"drift_kind=absent (实际 {drift.drift_kind})")
        check(drift.chapters_since_last >= 4, f"消失 ≥ 4 章 (实际 {drift.chapters_since_last})")
        check(drift.severity in ("high", "medium"), f"severity=high/medium (实际 {drift.severity})")

    # 其他角色 (一直在) - 无漂移
    no_drift = world_observer.get_state_drift(pid, "其他角色", threshold_chapters=3)
    check(no_drift is None, f"其他角色 无漂移 (实际 {no_drift})")

    # 列表
    drifted = world_observer.list_drifted_entities(pid, threshold_chapters=3)
    drift_names = [d.entity_name for d in drifted]
    check("林渊" in drift_names, f"林渊 在漂移列表 (实际 {drift_names})")


# ============================================================
# 测试 7: get_relations_graph (B3.3 插件数据)
# ============================================================

def test_relations_graph() -> None:
    section("[G10 7] get_relations_graph: 图谱数据 (供 B3.3 插件)")
    pid, bid, chapters, _ = _setup_project()

    drafts = [
        "林渊在青云宗, 持青锋剑。",       # 1 - 3 实体共现
        "林渊回到青云宗, 青锋剑出鞘。",   # 2 - 3 实体共现
        "林渊独行, 青锋剑收在背后。",     # 3 - 青云宗 不出现
    ]
    for c, d in zip(chapters[:3], drafts):
        world_observer.observe_chapter(pid, c["id"], c["chapter_no"], d)

    # 全项目 (_setup_project 建了 5 章, 所以 current=5)
    g = world_observer.get_relations_graph(pid)
    check(g.chapter_no == 5, f"全项目 chapter_no=current=5 (实际 {g.chapter_no})")
    check(len(g.nodes) == 3, f"3 节点 (实际 {len(g.nodes)})")
    # 边: 林渊-青云宗 (2 章共现: 1+2), 林渊-青锋剑 (3 章: 1+2+3), 青云宗-青锋剑 (2 章: 1+3)
    edge_weights = {(e["source"], e["target"]): e["weight"] for e in g.edges}
    check(edge_weights.get(("林渊", "青锋剑")) == 3, f"林渊-青锋剑 weight=3 (实际 {edge_weights.get(('林渊', '青锋剑'))})")
    check(edge_weights.get(("林渊", "青云宗")) == 2, f"林渊-青云宗 weight=2")
    # 节点 size
    node_size = {n["id"]: n["size"] for n in g.nodes}
    check(node_size.get("林渊") == 3, f"林渊 出现 3 章 size=3")

    # 截至第 1 章
    g1 = world_observer.get_relations_graph(pid, chapter_no=1)
    check(g1.chapter_no == 1, f"截至第 1 章 chapter=1")
    # 1 章只有 1 边 (3 实体全共现 → 3 边)
    check(len(g1.edges) == 3, f"第 1 章 3 边 (实际 {len(g1.edges)})")


# ============================================================
# 测试 8: get_observer_stats
# ============================================================

def test_observer_stats() -> None:
    section("[G10 8] get_observer_stats: 仪表盘统计")
    pid, bid, chapters, _ = _setup_project()

    drafts = [
        "林渊在青云宗, 持青锋剑。",
        "林渊回到青云宗。",
        "林渊在青云宗闭关。",
        "林渊远行。",
        "林渊归来。",
    ]
    for c, d in zip(chapters, drafts):
        world_observer.observe_chapter(pid, c["id"], c["chapter_no"], d)

    stats = world_observer.get_observer_stats(pid)
    check(stats["total_entities"] == 3, f"3 个实体 (实际 {stats['total_entities']})")
    check(stats["active_chapters"] == 5, f"5 章 (实际 {stats['active_chapters']})")
    check(stats["total_snapshots"] >= 5, f"快照 ≥ 5 (实际 {stats['total_snapshots']})")
    check(stats["by_kind"].get(worldbuilding.KIND_CHARACTER) == 5, f"character 5 次 (实际 {stats['by_kind'].get(worldbuilding.KIND_CHARACTER)})")
    check(stats["by_kind"].get(worldbuilding.KIND_ITEM) >= 1, f"item ≥ 1")
    check(stats["by_kind"].get(worldbuilding.KIND_LOCATION) >= 3, f"location ≥ 3")


# ============================================================
# 测试 9: 端到端 (写 5 章 → 看完整时间轴)
# ============================================================

def test_e2e() -> None:
    section("[G10 9] 端到端: 5 章剧情演化")
    pid, bid, chapters, _ = _setup_project()

    # 模拟一段剧情: 林渊 入门 → 出门历练 → 归家
    plot = [
        "林渊初入青云宗, 获赠青锋剑。",       # 1 - 3 实体
        "林渊苦修剑法, 持青锋剑练剑。",       # 2 - 林渊+青锋剑
        "林渊下山历练, 离开青云宗, 青锋剑在握。",  # 3 - 林渊+青锋剑+青云宗 (告别)
        "林渊独闯江湖, 青锋剑随行。",         # 4 - 林渊+青锋剑
        "林渊凯旋而归, 重回青云宗。",         # 5 - 林渊+青云宗
    ]
    for c, d in zip(chapters, plot):
        result = world_observer.observe_chapter(pid, c["id"], c["chapter_no"], d)

    # 编年史 5 条
    chronicle = world_observer.get_chronicle(pid)
    check(len(chronicle) == 5, f"编年史 5 条")

    # 第 4 章: 青云宗 消失 (3→4)
    ch4 = world_observer.get_chapter_changes(pid, 4)
    check("青云宗" in ch4.disappeared, f"第 4 章 青云宗 消失 (3→4 实际 {ch4.disappeared})")

    # 第 5 章: 青云宗 回归
    ch5 = world_observer.get_chapter_changes(pid, 5)
    check("青云宗" in ch5.returning_entities, f"第 5 章 青云宗 回归")

    # 图谱: 林渊-青锋剑 4 章共现 (1+2+3+4)
    g = world_observer.get_relations_graph(pid)
    edge = next((e for e in g.edges
                 if {e["source"], e["target"]} == {"林渊", "青锋剑"}), None)
    check(edge is not None and edge["weight"] == 4, f"林渊-青锋剑 4 章共现 (实际 {edge['weight'] if edge else 'None'})")

    # 统计
    stats = world_observer.get_observer_stats(pid)
    check(stats["active_chapters"] == 5, f"5 章活跃")


# ============================================================
# Main
# ============================================================

def main() -> int:
    print("=" * 60)
    print("G10 SMOKE: 世界状态观察器 (World State Observer)")
    print("=" * 60)
    print(f"[setup] tmpdir = {TMPDIR}")

    init_db()
    from app.db import connection
    connection.init(DB_PATH)
    print(f"[setup] DB = {DB_PATH}")

    tests = [
        lambda: test_observe_chapter(),
        lambda: test_entity_history(),
        lambda: test_chapter_changes(),
        lambda: test_project_snapshot(),
        lambda: test_chronicle(),
        lambda: test_state_drift(),
        lambda: test_relations_graph(),
        lambda: test_observer_stats(),
        lambda: test_e2e(),
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            fails.append(f"{t.__name__} 异常")
            print(f"\n✗ {t.__name__}: EXCEPTION — {type(e).__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"通过: {passed}    失败: {len(fails)}")
    if fails:
        print("\n失败列表:")
        for f in fails:
            print(f"  - {f}")
        print("=" * 60)
        return 1
    print(f"全部 {passed} 项检查通过 ✓")
    print("=" * 60)
    return 0


def _cleanup() -> None:
    import time
    import shutil
    try:
        from app.db import connection
        connection.close()
    except Exception:
        pass
    time.sleep(0.1)
    for ext in ("", "-wal", "-shm"):
        f = DB_PATH.parent / f"{DB_PATH.name}{ext}"
        if f.exists():
            try:
                f.unlink()
            except (PermissionError, OSError):
                pass
    try:
        shutil.rmtree(STORY_DIR, ignore_errors=True)
    except Exception:
        pass
    try:
        TMPDIR.rmdir()
    except (PermissionError, OSError):
        pass


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        _cleanup()
    sys.exit(rc)
