"""
E1 SMOKE: Character Tracker (5 维度动态追踪)
- record / record_dimension
- get_latest (含 as_of_chapter)
- get_history (按 chapter 排序, 按 dim 过滤)
- list_characters / get_all_latest
- diff (5 维度对比)
- search_dimension (关键词搜)
- delete_for_chapter / delete_for_character
- format_snapshot / format_all_latest

5 分钟自动超时 (threading.Timer, 跨平台, 防卡死)
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path

# 5 分钟全局超时 (smoke 卡死保护, Windows 兼容用 Timer)
_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_e1_character_tracker 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    print(f"[TIMEOUT] 请检查: 1) 终端输出最后一行  2) logs/NovelWriter_*.log  3) 是否被外部 IO 阻塞")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import connection, migrator
from app.services.character_tracker import (
    DIM_LOCATION, DIM_STATE, DIM_POWER, DIM_EQUIPMENT, DIM_RELATIONSHIP,
    ALL_DIMS, DIM_LABELS,
    TrackerSnapshot, DiffEntry,
    record, record_dimension,
    get_latest, get_history, list_characters, get_all_latest,
    diff, search_dimension,
    delete_for_chapter, delete_for_character,
    format_snapshot, format_all_latest,
    MAX_DIM_LEN,
)


def _setup_db():
    """每个测试跑前重置 DB。"""
    tmpdir = tempfile.mkdtemp(prefix="nw_smoke_e1_")
    db_path = Path(tmpdir) / "test.db"
    connection.init(db_path)
    conn = connection.get_conn()
    schema_sql = (ROOT / "app" / "db" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    migrator.run_migrations()
    return tmpdir


def _make_project_book_chapter() -> tuple[str, str, list[str]]:
    """创建 1 个项目 + 1 本书 + 5 章节。返回 (project_id, book_id, [chapter_ids])。"""
    conn = connection.get_conn()
    pid = "p_" + uuid.uuid4().hex[:6]
    bid = "b_" + uuid.uuid4().hex[:6]
    conn.execute("INSERT INTO projects (id, name) VALUES (?, ?)", (pid, "测试项目"))
    conn.execute("INSERT INTO books (id, project_id, volume_no) VALUES (?, ?, ?)", (bid, pid, 1))
    chapter_ids = []
    for i in range(1, 6):
        cid = f"c_{i:03d}"
        conn.execute(
            "INSERT INTO chapters (id, book_id, chapter_no) VALUES (?, ?, ?)",
            (cid, bid, i),
        )
        chapter_ids.append(cid)
    return pid, bid, chapter_ids


def main() -> int:
    fails = []
    passed = 0

    def check(cond, msg):
        nonlocal passed
        if cond:
            passed += 1
            print(f"  [PASS] {msg}")
        else:
            fails.append(msg)
            print(f"  [FAIL] {msg}")

    print("=" * 60)
    print("E1 SMOKE: Character Tracker (5 维度)")
    print("=" * 60)

    tmpdir = _setup_db()
    try:
        pid, bid, cids = _make_project_book_chapter()
        print(f"\n[setup] project={pid}, chapters={cids}")

        # 1) record 基础
        print("\n[1] record 基础")
        s = record(pid, cids[0], "林婉",
                   location="京城·林府",
                   state="清醒",
                   power_level="凡人",
                   equipment="玉佩一枚",
                   relationship="母亲(健在)/父亲(已故)")
        check(s.id and len(s.id) == 12, f"快照 id 生成 (实际 {s.id!r})")
        check(s.character_name == "林婉", "character_name 正确")
        check(s.location == "京城·林府", "location 正确")
        check(s.power_level == "凡人", "power_level 正确")
        check(len(s.dims) == 5, f"5 维度都有值 (实际 {len(s.dims)})")

        # 2) record_dimension (单维度)
        print("\n[2] record_dimension (单维度)")
        s2 = record_dimension(pid, cids[1], "林婉", DIM_LOCATION, "城外·破庙")
        check(s2.location == "城外·破庙", "单维度 location 记录")
        check(s2.state == "" and s2.power_level == "", "其他维度留空")

        # 3) get_latest 基础
        print("\n[3] get_latest")
        latest = get_latest(pid, "林婉")
        check(latest is not None, "get_latest 不为 None")
        check(latest.chapter_id == cids[1], f"最新章节 (实际 {latest.chapter_id})")
        check(latest.location == "城外·破庙", f"最新 location (实际 {latest.location})")

        # 4) get_latest + as_of_chapter
        print("\n[4] get_latest + as_of_chapter")
        snap_at_2 = get_latest(pid, "林婉", as_of_chapter=cids[1])
        check(snap_at_2.chapter_id == cids[1], f"as_of=cids[1] 命中 cids[1]")
        snap_at_0 = get_latest(pid, "林婉", as_of_chapter=cids[0])
        check(snap_at_0.chapter_id == cids[0], f"as_of=cids[0] 命中 cids[0] (实际 {snap_at_0.chapter_id})")
        # 用一个根本不该命中的角色 (从未记录过)
        snap_unknown = get_latest(pid, "从未存在", as_of_chapter="c_001")
        check(snap_unknown is None, f"不存在的角色 → None (实际 {snap_unknown})")
        # 用 'c_000' (lexically < c_001) 验证能过滤掉所有真实记录
        snap_before_all = get_latest(pid, "林婉", as_of_chapter="c_000")
        check(snap_before_all is None, f"as_of=c_000 (早于所有) → None (实际 {snap_before_all})")

        # 5) 多角色 + list_characters
        print("\n[5] 多角色 + list_characters")
        record(pid, cids[2], "苏沐", location="山巅", power_level="金丹期")
        record(pid, cids[2], "反派甲", location="暗处", state="潜伏")
        chars = list_characters(pid)
        check("林婉" in chars and "苏沐" in chars and "反派甲" in chars,
              f"list_characters 含 3 个 (实际 {chars})")
        check(chars.index("林婉") < chars.index("苏沐"),
              f"林婉 早于 苏沐 出现 (顺序: {chars})")

        # 6) get_all_latest
        print("\n[6] get_all_latest")
        all_latest = get_all_latest(pid)
        check(len(all_latest) == 3, f"3 个角色 latest (实际 {len(all_latest)})")
        check(all_latest["林婉"].location == "城外·破庙", "林婉 latest = 城外·破庙")
        check(all_latest["苏沐"].power_level == "金丹期", "苏沐 latest = 金丹期")

        # 7) get_history
        print("\n[7] get_history")
        # 给林婉多写几章
        record(pid, cids[3], "林婉", location="京城", state="轻伤")
        record(pid, cids[4], "林婉", location="皇宫", power_level="筑基期")
        hist = get_history(pid, "林婉")
        check(len(hist) == 4, f"林婉 4 条历史 (实际 {len(hist)})")
        check(hist[0].chapter_id == cids[0] and hist[-1].chapter_id == cids[4],
              f"按 chapter 升序 (第一 {hist[0].chapter_id}, 末 {hist[-1].chapter_id})")

        # 8) get_history + dim 过滤
        print("\n[8] get_history + dim 过滤")
        loc_hist = get_history(pid, "林婉", dim=DIM_LOCATION)
        check(len(loc_hist) == 4, f"location 非空 4 条 (实际 {len(loc_hist)})")
        locs = [s.location for s in loc_hist]
        check(all(l for l in locs), f"所有 location 非空 (实际 {locs})")

        # state: cids[0]=清醒, cids[3]=轻伤, 其他空 → 非空 2 条
        state_hist = get_history(pid, "林婉", dim=DIM_STATE)
        check(len(state_hist) == 2, f"state 非空 2 条 (实际 {len(state_hist)})")
        states = [s.state for s in state_hist]
        check("清醒" in states and "轻伤" in states,
              f"state 含 '清醒' 和 '轻伤' (实际 {states})")

        # 9) diff
        print("\n[9] diff")
        d = diff(pid, "林婉", from_chapter=cids[0], to_chapter=cids[4])
        check(len(d) == 5, f"5 个 DiffEntry (实际 {len(d)})")
        check(all(isinstance(e, DiffEntry) for e in d), "都是 DiffEntry")
        loc_diff = next(e for e in d if e.dim == DIM_LOCATION)
        check(loc_diff.before == "京城·林府" and loc_diff.after == "皇宫",
              f"location 变化: {loc_diff.before!r} → {loc_diff.after!r}")
        power_diff = next(e for e in d if e.dim == DIM_POWER)
        check(power_diff.before == "凡人" and power_diff.after == "筑基期",
              f"power 变化: {power_diff.before!r} → {power_diff.after!r}")
        # 装备: cids[0]=玉佩一枚, cids[4]=空 (装备丢了) → 实际是 "变了"
        equip_diff = next(e for e in d if e.dim == DIM_EQUIPMENT)
        check(equip_diff.changed, f"装备从 '玉佩一枚' 变成 '' (changed={equip_diff.changed})")
        check(equip_diff.before == "玉佩一枚" and equip_diff.after == "",
              f"装备 diff 正确: {equip_diff.before!r} → {equip_diff.after!r}")
        # 关系: cids[0] 有, cids[4] 无 → 变了
        rel_diff = next(e for e in d if e.dim == DIM_RELATIONSHIP)
        check(rel_diff.changed, f"关系也变了 (changed={rel_diff.changed})")
        # 状态: cids[0]=清醒, cids[3]=轻伤, cids[4]=空 → 实际 to_chapter=cids[4] 时为 ''
        state_diff = next(e for e in d if e.dim == DIM_STATE)
        check(state_diff.changed, f"状态从 '清醒' → '' (changed={state_diff.changed})")

        # 10) search_dimension
        print("\n[10] search_dimension")
        # 搜 '京' → 应命中 林婉 cids[0] (京城·林府) 和 cids[3] (京城)
        hits = search_dimension(pid, "京")
        check(len(hits) >= 2, f"搜 '京' 命中 ≥ 2 (实际 {len(hits)})")
        for h in hits:
            check("京" in h.location or "京" in h.state or "京" in h.power_level or
                  "京" in h.equipment or "京" in h.relationship,
                  f"{h.character_name} @ {h.chapter_id} 含 '京'")
        # dim 限定
        loc_hits = search_dimension(pid, "京", dim=DIM_LOCATION)
        check(all("京" in h.location for h in loc_hits), f"dim=location 全含 '京'")
        # 空 query
        check(search_dimension(pid, "") == [], "空 query → []")
        check(search_dimension(pid, "   ") == [], "空白 query → []")

        # 11) search_dimension 搜装备/关系
        print("\n[11] search_dimension 搜装备/关系")
        eq_hits = search_dimension(pid, "玉佩", dim=DIM_EQUIPMENT)
        check(len(eq_hits) == 1, f"搜 '玉佩' 装备命中 1 (实际 {len(eq_hits)})")
        rel_hits = search_dimension(pid, "母亲", dim=DIM_RELATIONSHIP)
        check(len(rel_hits) == 1, f"搜 '母亲' 关系命中 1 (实际 {len(rel_hits)})")

        # 12) 边界: 维度值过长
        print("\n[12] 边界: 维度值过长")
        try:
            record(pid, cids[0], "X", location="a" * (MAX_DIM_LEN + 1))
            check(False, "过长应抛 ValueError")
        except ValueError:
            check(True, "过长抛 ValueError")

        # 13) 边界: 必填字段
        print("\n[13] 边界: 必填字段")
        for kwargs in [
            {"project_id": "", "chapter_id": "c1", "character_name": "X"},
            {"project_id": "p", "chapter_id": "", "character_name": "X"},
            {"project_id": "p", "chapter_id": "c1", "character_name": ""},
        ]:
            try:
                record(**kwargs)
                check(False, f"必填缺失应抛: {kwargs}")
            except ValueError:
                check(True, f"必填缺失抛 ValueError: {kwargs}")

        # 14) 边界: 未知 dim
        print("\n[14] 边界: 未知 dim")
        try:
            record_dimension(pid, cids[0], "X", "未知维度", "v")
            check(False, "未知 dim 应抛")
        except ValueError:
            check(True, "未知 dim 抛 ValueError")
        try:
            get_history(pid, "X", dim="未知")
            check(False, "get_history 未知 dim 应抛")
        except ValueError:
            check(True, "get_history 未知 dim 抛")

        # 15) delete_for_chapter
        print("\n[15] delete_for_chapter")
        n = delete_for_chapter(pid, cids[2])
        check(n == 2, f"删 cids[2] 应删 2 条 (实际 {n})")
        # 苏沐 + 反派甲 都写在了 cids[2]
        chars_after = list_characters(pid)
        check("苏沐" not in chars_after, f"苏沐 已删 (剩余 {chars_after})")
        check("反派甲" not in chars_after, "反派甲 已删")

        # 16) delete_for_character
        print("\n[16] delete_for_character")
        n = delete_for_character(pid, "林婉")
        check(n == 4, f"删林婉全部应删 4 条 (实际 {n})")
        check(get_latest(pid, "林婉") is None, "林婉 无记录")
        check(list_characters(pid) == [], "项目无角色")

        # 17) format_snapshot
        print("\n[17] format_snapshot")
        s = record(pid, cids[0], "格式测试", location="A", state="B", power_level="C",
                   equipment="E", relationship="F")
        text = format_snapshot(s)
        check("格式测试" in text and "@" in text, f"含角色名和章节 (实际 {text[:50]!r})")
        for label in ["位置", "状态", "实力", "装备", "关系"]:
            check(label in text, f"含标签 {label}")
        # 5 维度全设, 装备标签在 text 中只出现 1 次 (非 "装备: (空)")
        check(text.count("装备") == 1, f"装备标签出现 1 次 (实际 {text.count('装备')})")

        # 空维度默认跳过: 只设 3 维, 装备/关系 不应在 text 中
        # 用"空测试"做名字, 避免"装备"/"关系"在角色名中被误计
        s_empty = record(pid, cids[1], "空测试", location="A", state="B", power_level="C")
        text_empty = format_snapshot(s_empty)
        check(text_empty.count("装备") == 0, "空装备维度默认不出现")
        check(text_empty.count("关系") == 0, "空关系维度默认不出现")
        check("位置" in text_empty and "状态" in text_empty and "实力" in text_empty,
              "3 个非空标签都在")

        # include_empty=True 时, 空维度显示 "(空)"
        text_inc = format_snapshot(s_empty, include_empty=True)
        check("(空)" in text_inc, "include_empty=True 显示 (空)")

        # 18) format_all_latest
        print("\n[18] format_all_latest")
        record(pid, cids[1], "甲", location="X")
        record(pid, cids[1], "乙", power_level="Y")
        out = format_all_latest(pid)
        check("甲" in out and "乙" in out, f"含甲乙 (实际 {out[:80]!r})")
        check("位置=X" in out, "甲含 location")

        # 19) TrackerSnapshot.dims / to_dict
        print("\n[19] TrackerSnapshot.dims / to_dict")
        # 3 维全设
        s = record(pid, cids[2], "SnapTest", location="L", state="S", power_level="P")
        d = s.dims
        check("location" in d and "state" in d and "power_level" in d,
              f"dims 含 3 个键 (实际 {list(d.keys())})")
        check(d["location"] == "L", "dims[location]=L")
        check(d["state"] == "S", "dims[state]=S")
        check(d["power_level"] == "P", "dims[power_level]=P")
        # 空 power_level 不在 dims
        s2 = record(pid, cids[2], "SnapTest2", location="L", state="S")
        d2 = s2.dims
        check("power_level" not in d2, "空 power_level 不在 dims")
        check(len(d2) == 2, f"空 power_level 过滤后剩 2 个键 (实际 {list(d2.keys())})")
        dd = s.to_dict()
        check(dd["character_name"] == "SnapTest", "to_dict 含 character_name")
        check("id" in dd and "updated_at" in dd, "to_dict 含 id/updated_at")

        # 20) TrackerSnapshot.from_row
        print("\n[20] TrackerSnapshot.from_row")
        conn = connection.get_conn()
        row = conn.execute("SELECT * FROM character_trackers LIMIT 1").fetchone()
        snap = TrackerSnapshot.from_row(row)
        check(snap.id == row["id"], "from_row 还原 id")
        check(snap.character_name == row["character_name"], "from_row 还原 character_name")

    finally:
        try:
            connection.close()
        except Exception:
            pass
        # 清临时 dir
        import time
        time.sleep(0.1)
        for ext in ["", "-wal", "-shm"]:
            f = Path(tmpdir) / f"test.db{ext}"
            if f.exists():
                try:
                    f.unlink()
                except (PermissionError, OSError):
                    pass
        try:
            Path(tmpdir).rmdir()
        except (PermissionError, OSError):
            pass

    print("\n" + "=" * 60)
    if not fails:
        print(f"E1 SMOKE PASS ({passed} assertions)")
        return 0
    else:
        print(f"E1 SMOKE FAIL ({len(fails)} failed):")
        for f in fails:
            print(f"  - {f}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
