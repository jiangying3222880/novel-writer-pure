"""
E3 SMOKE: 记忆总管 (Memory Manager)
- assemble_for_writing: 拼装 L1+L2+人物+压力+反 AI
- can_proceed: 压力决策
- after_writing: 写后自动更新 (反 AI 检查 + 压力 + fade)
- preview: UI 预览 dict

5 分钟自动超时 (threading.Timer, 跨平台, 防卡死)
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path

# stdout UTF-8 (Windows GBK 兼容)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 5 分钟全局超时 (smoke 卡死保护, Windows 兼容用 Timer)
_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_e3_memory_manager 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    print(f"[TIMEOUT] 请检查: 1) 终端输出最后一行  2) logs/NovelWriter_*.log  3) 是否被外部 IO 阻塞")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.constants import MemoryLevel, PressureZone
from app.db import connection, migrator
from app.services import (
    anti_ai, character_tracker, memory, memory_manager, pressure,
)


# ────────────────────── 计数器 ──────────────────────

_pass = 0
_fail = 0


def check(cond: bool, msg: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  [PASS] {msg}")
    else:
        _fail += 1
        print(f"  [FAIL] {msg}")


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


# ────────────────────── DB 初始化 ──────────────────────

def _setup_db():
    tmpdir = tempfile.mkdtemp(prefix="nw_smoke_e3_")
    db_path = Path(tmpdir) / "test.db"
    connection.init(db_path)
    conn = connection.get_conn()
    schema_sql = (ROOT / "app" / "db" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    migrator.run_migrations()
    return tmpdir


def _make_project_chapters() -> tuple[str, list[str]]:
    conn = connection.get_conn()
    pid = "p_" + uuid.uuid4().hex[:6]
    bid = "b_" + uuid.uuid4().hex[:6]
    conn.execute("INSERT INTO projects (id, name) VALUES (?, ?)", (pid, "E3 项目"))
    conn.execute("INSERT INTO books (id, project_id, volume_no) VALUES (?, ?, ?)", (bid, pid, 1))
    chapter_ids = []
    for i in range(1, 6):
        cid = f"c_{i:03d}"
        conn.execute(
            "INSERT INTO chapters (id, book_id, chapter_no) VALUES (?, ?, ?)",
            (cid, bid, i),
        )
        chapter_ids.append(cid)
    return pid, chapter_ids


# ═══════════════════════════════════════════════════════════
#                  E3 MEMORY MANAGER
# ═══════════════════════════════════════════════════════════

def test_assemble_empty(pid: str, cids: list[str]) -> None:
    section("[ASSEMBLE 1] 空项目拼装")

    asm = memory_manager.assemble_for_writing(pid, cids[0])
    check(isinstance(asm, memory_manager.AssembleResult), "返回 AssembleResult")
    check(asm.l1_arcs == [], "空 L1")
    check(asm.l2_commitments == [], "空 L2 commitments")
    check(asm.l2_world_rules == [], "空 L2 rules")
    check(asm.character_snapshots == {}, "空人物")
    check(asm.current_pressure is None, "无历史压力 → current_pressure=None")
    check(asm.pressure_zone == PressureZone.GREEN, "默认 green zone")
    check(asm.can_open_hook is True, "无压力时允许开钩子")
    check(asm.anti_ai_tips != "", "含反 AI 味提示")
    check(asm.full_text != "", "full_text 非空 (至少有 tips)")


def test_assemble_with_data(pid: str, cids: list[str]) -> None:
    section("[ASSEMBLE 2] 含数据拼装")

    # L1 故事弧
    memory.add_arc(pid, memory.CAT_ARC_MAIN, "主角觉醒血脉踏上修真路", chapter_id=cids[0])
    memory.add_arc(pid, memory.CAT_ARC_SUB, "副线: 师傅身世之谜", chapter_id=cids[1])
    memory.add_arc(pid, memory.CAT_ARC_CHAR, "主角从自卑到自信", chapter_id=cids[2])

    # L2 承诺 + 世界规则
    memory.add_commitment(pid, "答应师傅一年内突破筑基", kind="promise", chapter_id=cids[1])
    memory.add_commitment(pid, "已营救被困同门", kind="active", chapter_id=cids[2])
    memory.add_world_rule(pid, "修真分九境: 练气→筑基→金丹→元婴→化神→炼虚→合体→大乘→渡劫", kind="power")
    memory.add_world_rule(pid, "本界天道不允许跨界", kind="view")

    # 人物状态
    character_tracker.record(pid, cids[0], "林婉", location="京城·林府", power_level="凡人", equipment="玉佩")
    character_tracker.record(pid, cids[2], "林婉", location="皇宫", power_level="筑基期")
    character_tracker.record(pid, cids[0], "师傅", location="青云山", state="重伤")

    # 上一章压力 (c2 写完后压力 50 = yellow)
    pressure.record(pid, cids[1], active_hooks=2, open_promises=2, unresolved_subplots=2)

    # 拼装 c3 写前
    asm = memory_manager.assemble_for_writing(pid, cids[2])
    check(len(asm.l1_arcs) == 3, f"L1 弧 3 条 (实际 {len(asm.l1_arcs)})")
    check(len(asm.l2_commitments) == 2, f"L2 commitments 2 条 (实际 {len(asm.l2_commitments)})")
    check(len(asm.l2_world_rules) == 2, f"L2 world rules 2 条 (实际 {len(asm.l2_world_rules)})")
    check(len(asm.character_snapshots) == 2, f"人物 2 个 (实际 {len(asm.character_snapshots)})")
    check("林婉" in asm.character_snapshots, "含林婉")
    check("师傅" in asm.character_snapshots, "含师傅")

    # 林婉最新状态应该是 c2 (因为 c2 是 <= c3 的最新)
    lw = asm.character_snapshots["林婉"]
    check(lw.location == "皇宫", f"林婉位置=皇宫 (实际 {lw.location})")
    check(lw.power_level == "筑基期", f"林婉境界=筑基期")

    # 压力
    check(asm.current_pressure is not None, "current_pressure 非空")
    check(asm.pressure_zone == PressureZone.YELLOW, f"c2 50 → yellow (实际 {asm.pressure_zone})")
    check(asm.can_open_hook is True, "yellow 仍可开钩子")

    # full_text 含关键字段
    check("修真九境" in asm.full_text or "修真分九境" in asm.full_text, "full_text 含世界规则")
    check("京城" in asm.full_text or "皇宫" in asm.full_text, "full_text 含人物状态")
    check("林婉" in asm.full_text, "full_text 含人物名")
    check("6 大去 AI 味" in asm.full_text, "full_text 含反 AI 提示")
    check("yellow" in asm.full_text.lower() or "谨慎" in asm.full_text, "full_text 含 zone 提示")

    # to_dict
    d = asm.to_dict()
    check(d["l1_count"] == 3, "to_dict l1_count=3")
    check(d["l2_commit_count"] == 2, "to_dict l2_commit_count=2")
    check(d["char_count"] == 2, "to_dict char_count=2")


def test_assemble_as_of_filter(pid: str, cids: list[str]) -> None:
    section("[ASSEMBLE 3] as_of_chapter 时间过滤")

    # 加 1 个 c4 才出现的承诺
    memory.add_commitment(pid, "c4 才出现的承诺", kind="promise", chapter_id=cids[3])

    # 拼装 c2 写前, 不应见 c4
    asm = memory_manager.assemble_for_writing(pid, cids[1])
    contents = [m.content for m in asm.l2_commitments]
    check("c4 才出现的承诺" not in contents, "as_of=c2 不见 c4 承诺")

    # 拼装 c4 写前, 应见
    asm = memory_manager.assemble_for_writing(pid, cids[3])
    contents = [m.content for m in asm.l2_commitments]
    check("c4 才出现的承诺" in contents, "as_of=c4 见 c4 承诺")


def test_can_proceed(pid: str, cids: list[str]) -> None:
    section("[DECISION 1] can_proceed 决策")

    # 清空所有压力, 应放行
    conn = connection.get_conn()
    conn.execute("DELETE FROM narrative_pressures WHERE project_id=?", (pid,))
    ok, msg = memory_manager.can_proceed(pid, cids[0])
    check(ok and "无历史" in msg, f"无历史压力放行: {msg}")

    # 加 1 个 c1 压力
    pressure.record(pid, cids[0], pressure=10)  # green
    ok, msg = memory_manager.can_proceed(pid, cids[1])
    check(ok, "green 放行")
    check("放行" in msg, f"含'放行' (实际 {msg})")

    # 加 1 个 c2 压力 = 80 (orange)
    pressure.record(pid, cids[1], pressure=80)
    ok, msg = memory_manager.can_proceed(pid, cids[2])
    check(ok, "orange 警告但放行")
    check("orange" in msg.lower() or "🟠" in msg, f"含 orange 提示: {msg}")

    # 加 1 个 c3 压力 = 99 (red)
    pressure.record(pid, cids[2], pressure=99)
    ok, msg = memory_manager.can_proceed(pid, cids[3])
    check(not ok, "red 阻断")
    check("red" in msg.lower() or "🔴" in msg, f"含 red 提示: {msg}")


def test_after_writing(pid: str, cids: list[str]) -> None:
    section("[AFTER_WRITE 1] 写后自动更新")

    # 清空压力
    conn = connection.get_conn()
    conn.execute("DELETE FROM narrative_pressures WHERE project_id=?", (pid,))

    # 写后 (c1 草稿: 干净 + 适度长度)
    draft_clean = (
        "他抬起了头, 看着远方的山峦。\n\n"
        "剑光一闪, 寒芒乍现, 划破了夜的寂静。\n\n"
        "她退了一步, 没有说话, 只是静静地看着他。"
    )
    result = memory_manager.after_writing(
        pid, cids[0], draft_clean,
        active_hooks=2, open_promises=1, unresolved_subplots=0,
    )
    check(isinstance(result, memory_manager.AfterWriteResult), "返回 AfterWriteResult")
    check(isinstance(result.anti_ai_issues, list), "anti_ai_issues 是 list")
    check(result.new_pressure is not None, "new_pressure 非空")
    # 2*5 + 1*8 + 0*3 = 18 → green
    check(result.new_pressure.pressure == 18, f"压力 18 (实际 {result.new_pressure.pressure})")
    check(result.new_pressure.zone == PressureZone.GREEN, f"zone green (实际 {result.new_pressure.zone})")
    check(result.faded_count == 0, "无 RAG 时 faded=0")

    # 写后 (c2 草稿: AI 味重)
    draft_ai = (
        "他心想这个主意不错。\n"
        "他心想时间紧迫。\n"
        "他心想不能再拖了。\n"
        "他心想这局有变。\n\n"
        "在" + "字" * 100 + "里, 景色非常美, 极其壮观, 十分动人, 格外迷人, 异常秀丽, 完美无瑕, 倾国倾城。"
    )
    result = memory_manager.after_writing(
        pid, cids[1], draft_ai,
        active_hooks=5, open_promises=3, unresolved_subplots=2,
    )
    # 5*5 + 3*8 + 2*3 = 25 + 24 + 6 = 55 → yellow
    check(result.new_pressure.pressure == 55, f"c2 压力 55 (实际 {result.new_pressure.pressure})")
    check(result.new_pressure.zone == PressureZone.YELLOW, f"c2 zone yellow")
    check(len(result.anti_ai_issues) >= 2, f"AI 味文本触发多条 (实际 {len(result.anti_ai_issues)})")
    check(result.anti_ai_summary["total"] >= 2, "summary.total >= 2")
    check("info_gap" in result.anti_ai_summary["by_kind"] or "rhetoric_mod" in result.anti_ai_summary["by_kind"],
          f"触发 info_gap/rhetoric: {result.anti_ai_summary['by_kind']}")

    # to_dict
    d = result.to_dict()
    check(d["new_pressure"] == 55, "to_dict new_pressure=55")
    check(d["new_zone"] == PressureZone.YELLOW, "to_dict new_zone=yellow")


def test_after_writing_fade(pid: str, cids: list[str]) -> None:
    section("[AFTER_WRITE 2] 自动 fade 旧 RAG")

    # 加 25 个 RAG chunk
    for i in range(25):
        memory.add_rag_chunk(pid, f"rag chunk #{i:02d}", chapter_id=cids[0], ref_id=f"kb_{i}")
    # 确认 25 条
    l3 = memory.list_by_level(pid, MemoryLevel.L3_RAG)
    check(len(l3) == 25, f"25 条 RAG (实际 {len(l3)})")

    # 写一章, 触发 fade
    draft = "简单的草稿。他抬起了头。"
    result = memory_manager.after_writing(pid, cids[2], draft)
    # 应 fade 5 条 (25 - 20)
    check(result.faded_count == 5, f"fade 5 条 (实际 {result.faded_count})")

    # 查 L3 只剩 20
    l3_after = memory.list_by_level(pid, MemoryLevel.L3_RAG)
    check(len(l3_after) == 20, f"L3 剩 20 条 (实际 {len(l3_after)})")

    # fade 关闭时不动
    memory.add_rag_chunk(pid, "another rag", chapter_id=cids[0])
    result = memory_manager.after_writing(
        pid, cids[3], "test draft", auto_fade_old_rag=False,
    )
    l3_after = memory.list_by_level(pid, MemoryLevel.L3_RAG)
    check(len(l3_after) == 21, f"auto_fade=False 时不动 (实际 {len(l3_after)})")


def test_preview(pid: str, cids: list[str]) -> None:
    section("[PREVIEW] UI 预览")

    d = memory_manager.preview(pid, cids[2])
    check(isinstance(d, dict), "返回 dict")
    check(d["chapter_id"] == cids[2], "chapter_id 正确")
    check("l1_arcs" in d and isinstance(d["l1_arcs"], list), "l1_arcs 是 list")
    check("l2_commitments" in d, "l2_commitments 存在")
    check("l2_world_rules" in d, "l2_world_rules 存在")
    check("characters" in d, "characters 存在")
    check("pressure" in d, "pressure 存在")
    check("can_open_hook" in d, "can_open_hook 存在")
    check("hook_message" in d, "hook_message 存在")
    check("anti_ai_tips" in d, "anti_ai_tips 存在")
    check("full_text_chars" in d, "full_text_chars 存在")

    # c2 写完后压力 55, c3 之前
    if d["pressure"]:
        check(d["pressure"]["pressure"] == 55, f"pressure=55")
        check(d["pressure"]["zone"] == PressureZone.YELLOW, "zone=yellow")


# ═══════════════════════════════════════════════════════════
#                  MAIN
# ═══════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 60)
    print("E3 SMOKE: Memory Manager (记忆总管)")
    print("=" * 60)

    _setup_db()
    pid, cids = _make_project_chapters()
    print(f"\n[SETUP] project={pid}, chapters={len(cids)}")

    test_assemble_empty(pid, cids)
    test_assemble_with_data(pid, cids)
    test_assemble_as_of_filter(pid, cids)
    test_can_proceed(pid, cids)
    test_after_writing(pid, cids)
    test_after_writing_fade(pid, cids)
    test_preview(pid, cids)

    print(f"\n{'=' * 60}")
    print(f"结果: {_pass} passed, {_fail} failed")
    print(f"{'=' * 60}")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
