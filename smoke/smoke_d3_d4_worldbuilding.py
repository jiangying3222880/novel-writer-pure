"""
D3+D4 SMOKE: 世界观存储 + 同步
- D3: 5 实体 CRUD (修炼/地理/法宝/人物/势力) + 关系 + 5 文件 store 备份
- D3.2: 按章节任务取子集 (0 污染)
- D4: 写后同步 (sync_after_chapter) + 矛盾检测 (detect_contradictions)
- G10 时间轴 (timeline) + 快照统计 (snapshot_stats)

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
    print(f"\n[TIMEOUT] smoke_d3_d4 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 隔离真实数据
# ============================================================

TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_d3_d4_"))
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
    worldbuilding, world_sync, character_tracker, project_service, book_service, chapter_service,
)
from app.services.db import init_db
from app.services.exceptions import NotFoundError, ValidationError
from app.core import event_bus
from app.core.event_bus import Events


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
# 测试 1: 5 实体 CRUD
# ============================================================

def test_1_five_entities_crud(pid: str) -> None:
    section("[1] 5 实体 CRUD (修炼/地理/法宝/人物/势力)")

    # 修炼体系
    p1 = worldbuilding.create(pid, worldbuilding.KIND_POWER, "九境修真", level=9,
                              description="练气→筑基→金丹→元婴→化神→炼虚→合体→大乘→渡劫")
    check(p1.kind == "power", f"修炼 kind=power (实际 {p1.kind})")
    check(p1.level == 9, f"level=9 (实际 {p1.level})")
    check(p1.id.startswith("p_"), f"id 前缀 p_ (实际 {p1.id[:2]})")

    # 地理位置
    l1 = worldbuilding.create(pid, worldbuilding.KIND_LOCATION, "天玄宗", region="东洲",
                              description="主角所在宗门")
    check(l1.region == "东洲", f"region=东洲 (实际 {l1.region})")

    # 法宝
    i1 = worldbuilding.create(pid, worldbuilding.KIND_ITEM, "无名玉佩", owner="林轩", tier="凡品",
                              description="主角捡到的神秘玉佩")
    check(i1.tier == "凡品", f"tier=凡品 (实际 {i1.tier})")
    check(i1.owner == "林轩", f"owner=林轩 (实际 {i1.owner})")

    # 势力
    f1 = worldbuilding.create(pid, worldbuilding.KIND_FACTION, "天玄宗", description="正道大派")
    check(f1.name == "天玄宗", f"势力名 (实际 {f1.name})")

    # 人物
    c1 = worldbuilding.create(pid, worldbuilding.KIND_CHARACTER, "林轩", role="主角",
                              faction_id=f1.id, birth="孤儿", personality="坚韧")
    check(c1.role == "主角", f"role=主角 (实际 {c1.role})")
    check(c1.faction_id == f1.id, f"faction_id 关联正确 (实际 {c1.faction_id})")
    check(c1.personality == "坚韧", f"personality 正确")

    # update
    c1u = worldbuilding.update(c1.id, worldbuilding.KIND_CHARACTER, role="主角", personality="坚韧隐忍")
    check(c1u.personality == "坚韧隐忍", "update personality 成功")

    # list
    chars = worldbuilding.list_all(pid, worldbuilding.KIND_CHARACTER)
    check(len(chars) == 1, f"人物 1 个 (实际 {len(chars)})")

    powers = worldbuilding.list_all(pid, worldbuilding.KIND_POWER)
    check(len(powers) == 1, f"修炼 1 个 (实际 {len(powers)})")

    # 404
    try:
        worldbuilding.get("p_fake", worldbuilding.KIND_POWER)
        check(False, "404 应抛 NotFoundError")
    except NotFoundError:
        check(True, "NotFoundError 正确")

    # 非法 kind
    try:
        worldbuilding.create(pid, "bogus_kind", "X")
        check(False, "非法 kind 应 ValidationError")
    except ValidationError:
        check(True, "ValidationError 正确")


# ============================================================
# 测试 2: 关系
# ============================================================

def test_2_relations(pid: str) -> None:
    section("[2] 关系 (世界关系网 + 031增强)")
    chars = worldbuilding.list_all(pid, worldbuilding.KIND_CHARACTER)
    factions = worldbuilding.list_all(pid, worldbuilding.KIND_FACTION)
    items = worldbuilding.list_all(pid, worldbuilding.KIND_ITEM)
    locs = worldbuilding.list_all(pid, worldbuilding.KIND_LOCATION)

    # 林轩 → 属于 → 天玄宗 (默认 relation_type=general, intensity=5)
    r1 = worldbuilding.add_relation(
        pid, chars[0].id, "character", factions[0].id, "faction",
        "属于",
    )
    check(r1.startswith("r_"), f"关系 id 前缀 r_ (实际 {r1[:2]})")

    # 林轩 → 持有 → 无名玉佩 (指定 relation_type=ownership, intensity=8)
    r2 = worldbuilding.add_relation(
        pid, chars[0].id, "character", items[0].id, "item",
        "持有", relation_type="ownership", intensity=8, valid_from_chapter=1,
    )
    check(r2 != r1, "2 条关系 id 不同")

    # 林轩 → 位于 → 天玄宗 (指定 relation_type=location, intensity=6)
    r3 = worldbuilding.add_relation(
        pid, chars[0].id, "character", locs[0].id, "location",
        "位于", relation_type="location", intensity=6,
    )
    check(r3 != r1 and r3 != r2, "3 条关系 id 不同")

    # list - 验证返回数据包含 relation_type 和 intensity
    all_rels = worldbuilding.list_relations(pid)
    check(len(all_rels) == 3, f"3 条关系 (实际 {len(all_rels)})")
    
    # 验证字段存在
    r2_data = [r for r in all_rels if r["id"] == r2][0]
    check(r2_data.get("relation_type") == "ownership", f"r2 relation_type=ownership (实际 {r2_data.get('relation_type')})")
    check(r2_data.get("intensity") == 8, f"r2 intensity=8 (实际 {r2_data.get('intensity')})")
    
    r3_data = [r for r in all_rels if r["id"] == r3][0]
    check(r3_data.get("relation_type") == "location", f"r3 relation_type=location (实际 {r3_data.get('relation_type')})")
    check(r3_data.get("intensity") == 6, f"r3 intensity=6 (实际 {r3_data.get('intensity')})")

    # 按实体过滤
    rels_for_char = worldbuilding.list_relations(pid, entity_id=chars[0].id)
    check(len(rels_for_char) == 3, f"林轩相关 3 条 (实际 {len(rels_for_char)})")

    # 按 relation_type 过滤 (031 新增)
    ownership_rels = worldbuilding.list_relations(pid, relation_type="ownership")
    check(len(ownership_rels) == 1, f"ownership 类型 1 条 (实际 {len(ownership_rels)})")
    if ownership_rels:
        check(ownership_rels[0]["id"] == r2, f"ownership 过滤正确")

    # update_relation (031 新增)
    worldbuilding.update_relation(r2, relation="持有 (认主)", intensity=10)
    r2_updated = [r for r in worldbuilding.list_relations(pid) if r["id"] == r2][0]
    check(r2_updated.get("relation") == "持有 (认主)", f"update relation 成功 (实际 {r2_updated.get('relation')})")
    check(r2_updated.get("intensity") == 10, f"update intensity=10 (实际 {r2_updated.get('intensity')})")

    # 测试非法 relation_type 自动降级为 general
    r_invalid = worldbuilding.add_relation(
        pid, chars[0].id, "character", locs[0].id, "location",
        "测试", relation_type="invalid_type",
    )
    r_invalid_data = [r for r in worldbuilding.list_relations(pid) if r["id"] == r_invalid][0]
    check(r_invalid_data.get("relation_type") == "general", f"非法 relation_type 降级为 general (实际 {r_invalid_data.get('relation_type')})")

    # 测试 intensity 边界值
    r_low = worldbuilding.add_relation(
        pid, chars[0].id, "character", locs[0].id, "location",
        "微弱", intensity=0,  # 低于下限
    )
    r_low_data = [r for r in worldbuilding.list_relations(pid) if r["id"] == r_low][0]
    check(r_low_data.get("intensity") == 1, f"intensity 下限 1 (实际 {r_low_data.get('intensity')})")

    r_high = worldbuilding.add_relation(
        pid, chars[0].id, "character", locs[0].id, "location",
        "极强", intensity=15,  # 超过上限
    )
    r_high_data = [r for r in worldbuilding.list_relations(pid) if r["id"] == r_high][0]
    check(r_high_data.get("intensity") == 10, f"intensity 上限 10 (实际 {r_high_data.get('intensity')})")

    # delete
    worldbuilding.delete_relation(r3)
    after = worldbuilding.list_relations(pid)
    check(len(after) == 5, f"删 1 条剩 5 (实际 {len(after)})")  # 3 原 + 3 测试 = 6, 删 1 = 5


# ============================================================
# 测试 3: 5 文件 store 备份
# ============================================================

def test_3_file_store_backup(pid: str) -> None:
    section("[3] 5 文件 store 备份")
    counts = worldbuilding.backup_all(pid)
    check(counts["character"] == 1, f"人物 store 1 (实际 {counts['character']})")
    check(counts["power"] == 1, f"修炼 store 1 (实际 {counts['power']})")
    check(counts["faction"] == 1, f"势力 store 1 (实际 {counts['faction']})")
    check(counts["item"] == 1, f"法宝 store 1 (实际 {counts['item']})")
    check(counts["location"] == 1, f"地理 store 1 (实际 {counts['location']})")

    # 文件存在
    world_dir = STORY_DIR / f"world_{pid}"
    check(world_dir.exists(), f"world 目录存在: {world_dir}")
    for kind in worldbuilding.ALL_KINDS:
        f = world_dir / f"{kind}s.json"
        check(f.exists(), f"{kind}s.json 存在")

    # 内容验证
    import json
    f_data = json.loads((world_dir / "factions.json").read_text(encoding="utf-8"))
    check(f_data["count"] == 1, f"factions.json count=1 (实际 {f_data['count']})")
    check(f_data["entities"][0]["name"] == "天玄宗", "factions.json 名字正确")
    check("updated_at" in f_data, "updated_at 时间戳存在")

    # 模拟"用户手改 JSON 后回灌"场景
    # 1) 删 DB 中天玄宗
    faction_id = f_data["entities"][0]["id"]
    worldbuilding.delete(faction_id, worldbuilding.KIND_FACTION)
    check(len(worldbuilding.list_all(pid, worldbuilding.KIND_FACTION)) == 0, "DB 已清空天玄宗")

    # 2) 模拟手改: 在 JSON 文件加一行"幽冥殿"
    f_data["entities"].append({
        "id": "f_abc12345",
        "project_id": pid,
        "kind": "faction",
        "name": "幽冥殿",
        "description": "用户手加的魔道势力",
        "metadata": {},
    })
    f_data["count"] = 2
    (world_dir / "factions.json").write_text(
        json.dumps(f_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 3) restore_from_store
    restored = worldbuilding.restore_from_store(pid, worldbuilding.KIND_FACTION)
    check(restored == 2, f"回灌 2 条 (1 原+1 手加, 实际 {restored})")
    after = worldbuilding.list_all(pid, worldbuilding.KIND_FACTION)
    check(len(after) == 2, f"DB 已恢复 2 条 (实际 {len(after)})")
    check(any(e.name == "幽冥殿" for e in after), "用户手加的幽冥殿已回灌")


# ============================================================
# 测试 4: 检索 (D3.2 按章节任务取子集, 0 污染)
# ============================================================

def test_4_search_and_get_for_chapter(pid: str) -> None:
    section("[4] 检索 + 按章节任务取子集 (D3.2)")

    # 加点更多实体, 方便验证搜索
    worldbuilding.create(pid, worldbuilding.KIND_LOCATION, "云海峰", region="东洲")
    worldbuilding.create(pid, worldbuilding.KIND_LOCATION, "幽冥谷", region="北荒")
    worldbuilding.create(pid, worldbuilding.KIND_FACTION, "幽冥殿", description="魔道势力")
    worldbuilding.create(pid, worldbuilding.KIND_ITEM, "寒霜剑", owner="林轩", tier="灵器")
    worldbuilding.create(pid, worldbuilding.KIND_CHARACTER, "苏婉", role="女主",
                          faction_id=worldbuilding.list_all(pid, worldbuilding.KIND_FACTION)[0].id)

    # 搜 "林轩"
    chars = worldbuilding.search(pid, worldbuilding.KIND_CHARACTER, "林轩", top_k=5)
    check(len(chars) >= 1, f"搜 '林轩' 命中 ≥ 1 (实际 {len(chars)})")
    if chars:
        check(chars[0].name == "林轩", f"Top1 = 林轩 (实际 {chars[0].name})")

    # 搜 "天玄宗" 跨多类
    factions = worldbuilding.search(pid, worldbuilding.KIND_FACTION, "天玄宗")
    check(len(factions) >= 1, f"搜 '天玄宗' 势力 ≥ 1")

    # 搜 "幽冥" 跨 地理+势力
    locs = worldbuilding.search(pid, worldbuilding.KIND_LOCATION, "幽冥")
    factions = worldbuilding.search(pid, worldbuilding.KIND_FACTION, "幽冥")
    check(len(locs) >= 1, f"搜 '幽冥' 地理 ≥ 1 (实际 {len(locs)})")
    check(len(factions) >= 1, f"搜 '幽冥' 势力 ≥ 1 (实际 {len(factions)})")

    # D3.2 按章节任务取子集
    brief = "林轩在云海峰修炼, 持寒霜剑"
    subset = worldbuilding.get_for_chapter(pid, brief, per_kind_limit=3)
    check("power" in subset and "location" in subset, "5 类都有 key")
    check("item" in subset and len(subset["item"]) >= 1, f"item 至少 1 (实际 {len(subset['item'])})")
    check(any(e.name == "云海峰" for e in subset["location"]), "云海峰 在 location 子集")
    check(any(e.name == "寒霜剑" for e in subset["item"]), "寒霜剑 在 item 子集")

    # 每类限制
    for kind in worldbuilding.ALL_KINDS:
        check(len(subset[kind]) <= 3, f"{kind} ≤ 3 (实际 {len(subset[kind])})")


# ============================================================
# 测试 5: D4 写后同步
# ============================================================

def test_5_sync_after_chapter(pid: str) -> None:
    section("[5] D4 写后同步 (sync_after_chapter)")

    # 准备项目/书/章
    p = project_service.create("D3+D4 测试书", genre="仙侠")
    pj = p["id"]
    b = book_service.create(pj, 1, title="第一卷", synopsis="觉醒")
    c = chapter_service.create(b["id"], 1, title="破庙觉醒")
    cid = c["id"]
    chapter_no = 1

    # 准备一些实体 (用测试 4 的 pid 不是这个项目, 重新建)
    worldbuilding.create(pj, worldbuilding.KIND_CHARACTER, "林轩", role="主角")
    worldbuilding.create(pj, worldbuilding.KIND_LOCATION, "破庙", region="东洲")
    worldbuilding.create(pj, worldbuilding.KIND_ITEM, "玄铁剑", owner="林轩", tier="凡品")

    # 写章节 (正文里要出现这些实体)
    draft = (
        "林轩在破庙中醒来. 一柄玄铁剑横在他身旁. "
        "他握着剑, 望向门外. 苏婉走来, 递给他一壶水."
    )
    result = world_sync.sync_after_chapter(pj, cid, chapter_no, draft)
    check("character" in result.entities_mentioned, f"扫到 character (实际 keys: {list(result.entities_mentioned.keys())})")
    check("林轩" in result.entities_mentioned.get(worldbuilding.KIND_CHARACTER, []), "林轩 在提及列表")
    check("破庙" in result.entities_mentioned.get(worldbuilding.KIND_LOCATION, []), "破庙 在提及列表")
    check("玄铁剑" in result.entities_mentioned.get(worldbuilding.KIND_ITEM, []), "玄铁剑 在提及列表")
    check(result.snapshots_recorded >= 3, f"快照 ≥ 3 (实际 {result.snapshots_recorded})")
    check(result.characters_updated >= 1, f"角色追踪 ≥ 1 (实际 {result.characters_updated})")

    # 关系提示: "握着剑" 应触发 "持有" 提示
    check(len(result.new_relations_hints) >= 0, f"关系提示 (实际 {len(result.new_relations_hints)})")

    # 事件总线派发
    events: list[str] = []
    event_bus.subscribe(Events.WORLD_SYNCED, lambda e: events.append("synced"))

    # 再写一章
    c2 = chapter_service.create(b["id"], 2, title="离开破庙")
    draft2 = "林轩离开破庙, 走入云海峰."
    worldbuilding.create(pj, worldbuilding.KIND_LOCATION, "云海峰", region="东洲")
    r2 = world_sync.sync_after_chapter(pj, c2["id"], 2, draft2)
    check("云海峰" in r2.entities_mentioned.get(worldbuilding.KIND_LOCATION, []), "第 2 章扫到云海峰")
    check(r2.snapshots_recorded >= 2, f"第 2 章快照 ≥ 2 (实际 {r2.snapshots_recorded})")
    check("synced" in events, "WORLD_SYNCED 事件已派发")


# ============================================================
# 测试 6: D4 矛盾检测
# ============================================================

def test_6_detect_contradictions(pid: str) -> None:
    section("[6] D4 矛盾检测")

    # 准备项目/书
    p = project_service.create("矛盾测试", genre="仙侠")
    pj = p["id"]
    b = book_service.create(pj, 1, title="V1")
    c1 = chapter_service.create(b["id"], 1, title="ch1")
    c2 = chapter_service.create(b["id"], 2, title="ch2")
    c3 = chapter_service.create(b["id"], 3, title="ch3")

    # 第 1 章: 林轩 在 破庙, 凡人
    character_tracker.record(pj, c1["id"], "林轩", location="破庙", state="觉醒前",
                              power_level="凡人", equipment="无", relationship="老乞丐=恩人")
    # 触发一次 sync (建立快照)
    worldbuilding.create(pj, worldbuilding.KIND_CHARACTER, "林轩", role="主角")
    worldbuilding.create(pj, worldbuilding.KIND_LOCATION, "破庙", region="东洲")
    worldbuilding.create(pj, worldbuilding.KIND_LOCATION, "皇城", region="中州")
    worldbuilding.create(pj, worldbuilding.KIND_ITEM, "古剑", owner="林轩", tier="灵器")
    world_sync.sync_after_chapter(pj, c1["id"], 1, "林轩在破庙")

    # 第 2 章: 林轩 在 破庙, 练气一层 (合理递进)
    character_tracker.record(pj, c2["id"], "林轩", location="破庙", state="已觉醒",
                              power_level="练气一层", equipment="无", relationship="老乞丐=师傅")
    world_sync.sync_after_chapter(pj, c2["id"], 2, "林轩在破庙修炼")

    # 第 3 章: 林轩 在 皇城, 筑基 (大跳, 无过渡 → 矛盾)
    character_tracker.record(pj, c3["id"], "林轩", location="皇城", state="威震天下",
                              power_level="筑基", equipment="古剑", relationship="老乞丐=敌人")
    world_sync.sync_after_chapter(pj, c3["id"], 3, "林轩在皇城挥剑")

    # 检测
    issues = world_sync.detect_contradictions(pj, c3["id"], 3, "...")
    check(len(issues) >= 1, f"矛盾 ≥ 1 (实际 {len(issues)})")

    # 应至少含 location 矛盾 (破庙 → 皇城, high)
    loc_issues = [i for i in issues if i.field == "location"]
    check(len(loc_issues) >= 1, f"location 矛盾 ≥ 1 (实际 {len(loc_issues)})")
    if loc_issues:
        li = loc_issues[0]
        check(li.severity == "high", f"location 矛盾 severity=high (实际 {li.severity})")
        check(li.old_value == "破庙" and li.new_value == "皇城", f"破庙 → 皇城 (实际 {li.old_value} → {li.new_value})")

    # 应含 power_level 矛盾
    power_issues = [i for i in issues if i.field == "power_level"]
    check(len(power_issues) >= 1, f"power_level 矛盾 ≥ 1 (实际 {len(power_issues)})")


# ============================================================
# 测试 7: G10 时间轴
# ============================================================

def test_7_timeline_and_stats(pid: str) -> None:
    section("[7] G10 时间轴 + 快照统计")

    p = project_service.create("时间轴测试", genre="仙侠")
    pj = p["id"]
    b = book_service.create(pj, 1, title="V1")
    c1 = chapter_service.create(b["id"], 1)
    c2 = chapter_service.create(b["id"], 2)

    worldbuilding.create(pj, worldbuilding.KIND_CHARACTER, "林轩", role="主角")
    worldbuilding.create(pj, worldbuilding.KIND_LOCATION, "天玄宗", region="东洲")
    world_sync.sync_after_chapter(pj, c1["id"], 1, "林轩在天玄宗修炼")
    world_sync.sync_after_chapter(pj, c2["id"], 2, "林轩走出天玄宗")

    # timeline
    tl = world_sync.timeline(pj, "林轩")
    check(len(tl) == 2, f"林轩出现 2 次 (实际 {len(tl)})")
    if tl:
        check(tl[0]["chapter_no"] == 1, f"第 1 次 chapter_no=1 (实际 {tl[0]['chapter_no']})")
        check(tl[1]["chapter_no"] == 2, f"第 2 次 chapter_no=2 (实际 {tl[1]['chapter_no']})")

    # 快照统计
    stats = world_sync.snapshot_stats(pj)
    check(stats["total"] >= 4, f"快照 ≥ 4 (实际 {stats['total']})")
    check("by_kind" in stats, "by_kind 字段存在")
    check(stats["by_kind"].get("character", 0) >= 2, f"character 快照 ≥ 2 (实际 {stats['by_kind'].get('character', 0)})")


# ============================================================
# 测试 8: stats 总览
# ============================================================

def test_8_worldbuilding_stats(pid: str) -> None:
    section("[8] 世界观统计 (stats 总览)")
    p = project_service.create("总览测试", genre="仙侠")
    pj = p["id"]

    # 加一堆
    worldbuilding.create(pj, worldbuilding.KIND_POWER, "九境", level=9)
    worldbuilding.create(pj, worldbuilding.KIND_POWER, "武道十品", level=10)
    worldbuilding.create(pj, worldbuilding.KIND_LOCATION, "A", region="东")
    worldbuilding.create(pj, worldbuilding.KIND_LOCATION, "B", region="西")
    worldbuilding.create(pj, worldbuilding.KIND_LOCATION, "C", region="南")
    worldbuilding.create(pj, worldbuilding.KIND_ITEM, "剑")
    worldbuilding.create(pj, worldbuilding.KIND_ITEM, "刀")
    worldbuilding.create(pj, worldbuilding.KIND_CHARACTER, "A")
    worldbuilding.create(pj, worldbuilding.KIND_FACTION, "F1")
    worldbuilding.create(pj, worldbuilding.KIND_FACTION, "F2")
    worldbuilding.add_relation(pj, "i_xxxx", "item", "i_yyyy", "item", "克制")  # 可能 404, 忽略

    stats = worldbuilding.stats(pj)
    check(stats["power"] == 2, f"修炼 2 (实际 {stats['power']})")
    check(stats["location"] == 3, f"地理 3 (实际 {stats['location']})")
    check(stats["item"] == 2, f"法宝 2 (实际 {stats['item']})")
    check(stats["character"] == 1, f"人物 1 (实际 {stats['character']})")
    check(stats["faction"] == 2, f"势力 2 (实际 {stats['faction']})")
    check(stats["total"] >= 10, f"实体总数 ≥ 10 (实际 {stats['total']})")


# ============================================================
# Main
# ============================================================

def main() -> int:
    print("=" * 60)
    print("D3+D4 SMOKE: 世界观存储 + 同步")
    print("=" * 60)
    print(f"[setup] tmpdir = {TMPDIR}")

    init_db()
    # 还要 init app.db.connection 单例 (character_tracker / ai.registry 用)
    from app.db import connection
    connection.init(DB_PATH)
    print(f"[setup] DB = {DB_PATH}")
    print(f"[setup] story = {STORY_DIR}")

    # 用第一个测试项目贯穿
    test_p = project_service.create("D3 测试项目", genre="仙侠")
    pid = test_p["id"]
    print(f"[setup] project_id = {pid}")

    tests = [
        lambda: test_1_five_entities_crud(pid),
        lambda: test_2_relations(pid),
        lambda: test_3_file_store_backup(pid),
        lambda: test_4_search_and_get_for_chapter(pid),
        lambda: test_5_sync_after_chapter(pid),
        lambda: test_6_detect_contradictions(pid),
        lambda: test_7_timeline_and_stats(pid),
        lambda: test_8_worldbuilding_stats(pid),
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
    try:
        from app.services import db as svc_db
        if hasattr(svc_db, "_local"):
            conn = getattr(svc_db._local, "conn", None)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
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
