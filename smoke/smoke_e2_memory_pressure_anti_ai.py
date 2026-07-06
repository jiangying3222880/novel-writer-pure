"""
E2 SMOKE: 记忆 L1-L4 + 压力计 + 6 大去 AI 味
- memory.add / add_arc / add_commitment / add_world_rule / add_rag_chunk
- memory.fade / fulfill_promise / get_l1_l2 / list_by_level
- pressure.compute_zone / compute_pressure / record / get_for_chapter
- pressure.can_open_new_hook / zone_summary / get_trend
- anti_ai.run_all / 6 项 check 函数

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
    print(f"\n[TIMEOUT] smoke_e2_memory_pressure_anti_ai 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    print(f"[TIMEOUT] 请检查: 1) 终端输出最后一行  2) logs/NovelWriter_*.log  3) 是否被外部 IO 阻塞")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.constants import MemoryLevel, PressureZone, PRESSURE_THRESHOLDS
from app.db import connection, migrator
from app.services import memory, pressure
from app.services.anti_ai import (
    Severity, CheckKind, CHECK_LABELS, SEVERITY_ORDER,
    Issue,
    check_sentence_pattern, check_dialogue_voice, check_pacing_breath,
    check_rhetoric_mod, check_pov_consist, check_info_gap,
    run_all, summary, format_report,
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
    tmpdir = tempfile.mkdtemp(prefix="nw_smoke_e2_")
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
    conn.execute("INSERT INTO projects (id, name) VALUES (?, ?)", (pid, "E2 项目"))
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
#                  MEMORY 模块
# ═══════════════════════════════════════════════════════════

def test_memory_basic(pid: str, cids: list[str]) -> None:
    section("[MEMORY 1] add / list_by_category")

    # L1 故事弧
    m1 = memory.add_arc(pid, memory.CAT_ARC_MAIN, "主角觉醒血脉, 踏上修真路", chapter_id=cids[0])
    check(m1.level == MemoryLevel.L1_ARC, f"主线弧 level=L1 (实际 {m1.level})")
    check(m1.token_count > 0, f"自动估算 token: {m1.token_count}")

    m2 = memory.add_arc(pid, memory.CAT_ARC_SUB, "副线: 师傅身世之谜", chapter_id=cids[1])
    check(m2.category == memory.CAT_ARC_SUB, "副线弧 category=arc_sub")

    m3 = memory.add_arc(pid, memory.CAT_ARC_CHAR, "主角从自卑到自信", chapter_id=cids[2])
    check(m3.category == memory.CAT_ARC_CHAR, "人物弧 category=arc_char")

    # L2 承诺
    m4 = memory.add_commitment(pid, "答应师傅: 一年内突破筑基", kind="promise", chapter_id=cids[1])
    check(m4.category == memory.CAT_COMMIT_PROMISE, "承诺 promise")

    m5 = memory.add_commitment(pid, "主角已被迫卷入江湖纷争", kind="active", chapter_id=cids[2])
    check(m5.category == memory.CAT_COMMIT_ACTIVE, "承诺 active")

    # L2 世界规则
    m6 = memory.add_world_rule(pid, "修真分九境: 练气→筑基→金丹→元婴→化神→炼虚→合体→大乘→渡劫", kind="power")
    check(m6.category == memory.CAT_WORLD_POWER, "力量规则")
    check(m6.chapter_id is None, "世界规则 chapter_id=NULL")

    m7 = memory.add_world_rule(pid, "本界天道只允许渡劫飞升, 不允许跨界", kind="view")
    check(m7.category == memory.CAT_WORLD_VIEW, "世界规则 view")

    # L3 RAG
    m8 = memory.add_rag_chunk(pid, "[知识库] 仙侠常见桥段: 跌落悬崖获奇遇", chapter_id=cids[0], ref_id="kb_001")
    check(m8.level == MemoryLevel.L3_RAG, "RAG chunk level=L3")
    check(m8.ref_id == "kb_001", f"ref_id={m8.ref_id}")

    # list_by_category
    mains = memory.list_by_category(pid, memory.CAT_ARC_MAIN)
    check(len(mains) == 1 and mains[0].id == m1.id, f"主线弧列表 1 条 (实际 {len(mains)})")

    rules = memory.list_by_category(pid, memory.CAT_WORLD_POWER)
    check(len(rules) == 1, f"力量规则 1 条 (实际 {len(rules)})")

    # count_by_level
    counts = memory.count_by_level(pid)
    check(counts.get(MemoryLevel.L1_ARC, 0) == 3, f"L1 数量 3 (实际 {counts.get(MemoryLevel.L1_ARC, 0)})")
    # L2 含 commitment + world_rule, 共 4 条
    check(counts.get("L2", 0) == 4, f"L2 数量 4 (实际 {counts.get('L2', 0)})")
    check(counts.get(MemoryLevel.L3_RAG, 0) == 1, f"L3 RAG 数量 1")


def test_memory_l1l2_and_promises(pid: str, cids: list[str]) -> None:
    section("[MEMORY 2] get_l1_l2 / promise 状态机")

    # 先在第 1 章加 1 个 promise
    p1 = memory.add_commitment(pid, "答应母亲: 三年内回家", kind="promise", chapter_id=cids[0])
    p2 = memory.add_commitment(pid, "已经营救被困同门", kind="active", chapter_id=cids[1])

    # get_l1_l2: 应返回 L1+L2, 不含 L3/L4
    l1l2 = memory.get_l1_l2(pid)
    levels = {m.level for m in l1l2}
    check(MemoryLevel.L3_RAG not in levels, "get_l1_l2 不含 L3")
    check(MemoryLevel.L4_FADE not in levels, "get_l1_l2 不含 L4")

    # get_active_commitments
    active = memory.get_active_commitments(pid)
    check(len(active) >= 1, f"active commitments >= 1 (实际 {len(active)})")
    check(any(p.id == p2.id for p in active), f"p2 在 active 列表中")

    # get_open_promises
    open_p = memory.get_open_promises(pid)
    check(any(p.id == p1.id for p in open_p), f"p1 在 open_promises 列表中")

    # fulfill_promise: p1 promise → active
    ok = memory.fulfill_promise(pid, p1.id)
    check(ok, "fulfill_promise 成功")
    new_active = memory.get_active_commitments(pid)
    check(any(p.id == p1.id for p in new_active), "p1 转 active 成功")

    # 二次 fulfill 应抛错
    try:
        memory.fulfill_promise(pid, p1.id)
        check(False, "二次 fulfill 应抛错")
    except ValueError:
        check(True, "二次 fulfill 抛 ValueError")


def test_memory_fade(pid: str, cids: list[str]) -> None:
    section("[MEMORY 3] fade (L3 → L4 优雅遗忘)")

    rag = memory.add_rag_chunk(pid, "短期素材: 茶楼场景描写", chapter_id=cids[0], ref_id="kb_fade_test")
    check(rag.level == MemoryLevel.L3_RAG, "创建时 L3")

    ok = memory.fade(pid, rag.id)
    check(ok, "fade 返回 True")
    # 查回
    faded = memory.get_by_id(pid, rag.id)
    check(faded is not None, "fade 后仍可查得 (历史保留)")
    check(faded.level == MemoryLevel.L4_FADE, f"fade 后 level=L4 (实际 {faded.level})")
    check(faded.category == memory.CAT_FADED, "fade 后 category=faded_detail")
    check(faded.ref_id == rag.id, f"ref_id 指向自身 (实际 {faded.ref_id})")

    # L3 不应再含此条
    l3 = memory.list_by_level(pid, MemoryLevel.L3_RAG)
    check(all(m.id != rag.id for m in l3), "fade 后不在 L3 列表")

    # 非 L3 不能 fade
    arc = memory.add_arc(pid, memory.CAT_ARC_SUB, "测试不能遗忘 L1")
    try:
        memory.fade(pid, arc.id)
        check(False, "fade L1 应抛错")
    except ValueError:
        check(True, "fade L1 抛 ValueError")


def test_memory_as_of(pid: str, cids: list[str]) -> None:
    section("[MEMORY 4] as_of_chapter 时间过滤")

    # 在不同章节加承诺
    memory.add_commitment(pid, "c1 的承诺", kind="promise", chapter_id=cids[0])
    memory.add_commitment(pid, "c3 的承诺", kind="promise", chapter_id=cids[2])
    memory.add_commitment(pid, "c5 的承诺", kind="promise", chapter_id=cids[4])

    # as_of=cids[2]: 应只见 c1 + c3
    promises = memory.get_open_promises(pid, as_of_chapter=cids[2])
    contents = [m.content for m in promises]
    check("c1 的承诺" in contents, "as_of=c2 含 c1")
    check("c3 的承诺" in contents, "as_of=c2 含 c3")
    check("c5 的承诺" not in contents, "as_of=c2 不含 c5")


# ═══════════════════════════════════════════════════════════
#                  PRESSURE 模块
# ═══════════════════════════════════════════════════════════

def test_pressure_compute() -> None:
    section("[PRESSURE 1] compute_zone / compute_pressure")

    # 边界
    check(pressure.compute_zone(0) == PressureZone.GREEN, "0 → green")
    check(pressure.compute_zone(29) == PressureZone.GREEN, "29 → green")
    check(pressure.compute_zone(30) == PressureZone.YELLOW, "30 → yellow")
    check(pressure.compute_zone(69) == PressureZone.YELLOW, "69 → yellow")
    check(pressure.compute_zone(70) == PressureZone.ORANGE, "70 → orange")
    check(pressure.compute_zone(94) == PressureZone.ORANGE, "94 → orange")
    check(pressure.compute_zone(95) == PressureZone.RED, "95 → red")
    check(pressure.compute_zone(999) == PressureZone.RED, "999 → red")
    check(pressure.compute_zone(-10) == PressureZone.GREEN, "负数 → green (容错)")

    # compute_pressure
    check(pressure.compute_pressure(active_hooks=2, open_promises=1, unresolved_subplots=3) == 2*5 + 1*8 + 3*3,
          f"默认权重计算: {pressure.compute_pressure(2, 1, 3)}")
    check(pressure.compute_pressure(active_hooks=0, open_promises=0, unresolved_subplots=0) == 0, "全 0 → 0")
    # 自定义权重
    custom = pressure.compute_pressure(1, 1, 1, weights={"hook": 10, "promise": 1, "subplot": 1})
    check(custom == 12, f"自定义权重: {custom}")

    # can_open_new_hook
    ok, msg = pressure.can_open_new_hook(10)
    check(ok and "green" in msg.lower() or "🟢" in msg, f"green 允许开: {msg}")
    ok, msg = pressure.can_open_new_hook(50)
    check(ok and "yellow" in msg.lower() or "🟡" in msg, f"yellow 谨慎: {msg}")
    ok, msg = pressure.can_open_new_hook(80)
    check(not ok and "orange" in msg.lower() or "🟠" in msg, f"orange 必关: {msg}")
    ok, msg = pressure.can_open_new_hook(99)
    check(not ok and "red" in msg.lower() or "🔴" in msg, f"red 阻止: {msg}")


def test_pressure_record_and_query(pid: str, cids: list[str]) -> None:
    section("[PRESSURE 2] record / get / list / trend")

    # 在不同章节记录不同压力
    p1 = pressure.record(pid, cids[0], active_hooks=2, open_promises=1, unresolved_subplots=0)
    check(p1.zone == PressureZone.GREEN, f"c1 2+1+0=18 → green (实际 {p1.zone})")

    p3 = pressure.record(pid, cids[2], active_hooks=4, open_promises=3, unresolved_subplots=2)
    # 4*5 + 3*8 + 2*3 = 20 + 24 + 6 = 50 → yellow
    check(p3.pressure == 50, f"c3 50 (实际 {p3.pressure})")
    check(p3.zone == PressureZone.YELLOW, f"c3 → yellow (实际 {p3.zone})")

    p5 = pressure.record(pid, cids[4], active_hooks=10, open_promises=5, unresolved_subplots=5,
                        deadline_chapter=10)
    # 10*5 + 5*8 + 5*3 = 50 + 40 + 15 = 105 → red
    check(p5.pressure == 105, f"c5 105 (实际 {p5.pressure})")
    check(p5.zone == PressureZone.RED, f"c5 → red (实际 {p5.zone})")
    check(p5.deadline_chapter == 10, f"deadline=10")

    # 手动指定压力
    p2 = pressure.record(pid, cids[1], pressure=80)
    check(p2.pressure == 80, f"手动指定 pressure=80")
    check(p2.zone == PressureZone.ORANGE, f"手动 → orange")

    # get_for_chapter
    got = pressure.get_for_chapter(pid, cids[2])
    check(got is not None and got.pressure == 50, "get_for_chapter c3")

    # list_for_project
    all_p = pressure.list_for_project(pid)
    check(len(all_p) == 4, f"全部 4 章压力 (实际 {len(all_p)})")

    # get_latest
    latest = pressure.get_latest(pid)
    check(latest.chapter_id == cids[4], f"latest = c5 (实际 {latest.chapter_id})")

    # get_trend
    trend = pressure.get_trend(pid, last_n=3)
    check(len(trend) == 3, f"trend 3 条 (实际 {len(trend)})")
    # 顺序: DESC 取 [c5, c3, c2] → reversed 后 [c2, c3, c5]
    check(trend[0].chapter_id == cids[1], f"trend 最早 = c2 (实际 {trend[0].chapter_id})")
    check(trend[-1].chapter_id == cids[4], f"trend 最晚 = c5")

    # zone_summary
    summary_map = pressure.zone_summary(pid)
    check(summary_map.get(PressureZone.GREEN, 0) == 1, f"green 1 章")
    check(summary_map.get(PressureZone.YELLOW, 0) == 1, f"yellow 1 章")
    check(summary_map.get(PressureZone.ORANGE, 0) == 1, f"orange 1 章")
    check(summary_map.get(PressureZone.RED, 0) == 1, f"red 1 章")

    # upsert: 再次 record 同 chapter 应覆盖
    pressure.record(pid, cids[0], pressure=0)
    after = pressure.list_for_project(pid)
    check(len(after) == 4, f"upsert 后仍 4 章 (实际 {len(after)})")
    c0_new = pressure.get_for_chapter(pid, cids[0])
    check(c0_new.pressure == 0, f"c1 已覆盖为 0 (实际 {c0_new.pressure})")


def test_pressure_format() -> None:
    section("[PRESSURE 3] format / decision 辅助")

    p = pressure.Pressure(
        id="x", project_id="p", chapter_id="c007",
        pressure=75, active_hooks=5, open_promises=3, unresolved_subplots=2,
        zone=PressureZone.ORANGE, deadline_chapter=12, created_at="2026-01-01",
    )
    text = pressure.format_for_prompt(p)
    check("c007" in text and "75" in text and "ORANGE" in text.upper() or "必关" in text, "format 含关键字段")
    check("12" in text, "format 含 deadline")

    # trend
    pressures = [p, p]
    trend_text = pressure.format_trend(pressures)
    check("叙事压力趋势" in trend_text, "format_trend 含标题")


# ═══════════════════════════════════════════════════════════
#                  ANTI_AI 模块
# ═══════════════════════════════════════════════════════════

def test_anti_ai_basic() -> None:
    section("[ANTI_AI 1] 基础 6 项检查注册表")

    # 全部 check 函数应可独立调用
    sample = "他说: 「好。」她说: 「行。」他说: 「走。」她说: 「嗯。」"
    issues_dialog = check_dialogue_voice(sample)
    check(isinstance(issues_dialog, list), "check_dialogue_voice 返回 list")
    check(all(isinstance(i, Issue) for i in issues_dialog), "Issue 类型正确")

    # 全部跑
    all_issues = run_all(sample)
    check(isinstance(all_issues, list), "run_all 返回 list")

    # summary
    s = summary(all_issues)
    check("total" in s and "by_kind" in s and "by_severity" in s, "summary 字段完整")
    check("has_block" in s, "summary 含 has_block")

    # format_report
    rep = format_report(all_issues)
    check("6 大去 AI 味" in rep, "format_report 含标题")


def test_anti_ai_sentence_pattern() -> None:
    section("[ANTI_AI 2] sentence_pattern 句式去重")

    # 连续 4 句同模板 (前 4 字相同) → 应触发
    bad = "他走进了门。他走进了山。他走进了城。他走进了林。"
    issues = check_sentence_pattern(bad)
    check(len(issues) >= 1, f"连续 '他走进...' 句式应触发 (实际 {len(issues)} 条)")
    if issues:
        check(issues[0].kind == CheckKind.SENTENCE_PATTERN, "kind 正确")
        check(issues[0].severity in (Severity.WARN, Severity.BLOCK), "severity 正确")

    # 句式丰富 → 不应触发
    good = "他走向前去。剑光一闪, 寒芒乍现。\n脚步未停。"
    issues = check_sentence_pattern(good)
    check(len(issues) == 0, f"句式丰富应无问题 (实际 {len(issues)} 条)")


def test_anti_ai_dialogue_voice() -> None:
    section("[ANTI_AI 3] dialogue_voice 对话个性化")

    # 同一角色 3 段以上同长度 → 触发 (用 "说" 后无标点包裹, 适配现有 regex)
    bad = "林凡说这样吧。林凡说不是吧。林凡说也许吧。"
    issues = check_dialogue_voice(bad)
    # 长度差 < 2, 至少 1 条问题
    check(len(issues) >= 1, f"同长度对话应触发 (实际 {len(issues)} 条)")

    # 长度差异大 → 不触发
    good = "林凡说这件事, 我们需要从长计议, 不可操之过急。林凡说好。"
    issues = check_dialogue_voice(good)
    # 3 段以下不告警
    check(len(issues) == 0, f"长度差异大 / 段数少应无问题 (实际 {len(issues)} 条)")


def test_anti_ai_pacing() -> None:
    section("[ANTI_AI 4] pacing_breath 节奏呼吸")

    # 全长句 (4 句, 每句 >= 30 字)
    para = (
        "他抬起了头, 看着远方的山峦, 心中涌起无限感慨, 三十年如白驹过隙。"
        "这三十年的风霜仿佛在眼前一一闪过, 让他一时间无法言语, 不知所措。"
        "他只是静静地站着, 任凭风吹过他的衣袂, 不发一语, 眼角似乎有什么在闪动。"
        "远处的云在山巅翻涌, 像是他心中那无法言说的思绪, 翻腾不息, 缠绕不去。"
    )
    issues = check_pacing_breath(para)
    check(len(issues) >= 1, f"全中长句段落应触发 (实际 {len(issues)} 条)")

    # 短句交替
    good = "他动了。剑光一闪。她退了一步。风起。"
    issues = check_pacing_breath(good)
    check(len(issues) == 0, f"短句混合不强制告警 (实际 {len(issues)} 条)")


def test_anti_ai_rhetoric() -> None:
    section("[ANTI_AI 5] rhetoric_mod 修辞适度")

    # 长段落 + 多个修辞词
    bad = "在" + "字" * 100 + "里, 景色非常美, 极其壮观, 十分动人, 格外迷人, 异常秀丽, 完美无瑕, 惊为天人, 倾国倾城, 让人无法忘怀。"
    issues = check_rhetoric_mod(bad)
    check(len(issues) >= 1, f"修辞堆叠应触发 (实际 {len(issues)} 条)")
    if issues:
        check(issues[0].kind == CheckKind.RHETORIC_MOD, "kind 正确")

    # 短段落
    good = "他走了。"
    issues = check_rhetoric_mod(good)
    check(len(issues) == 0, f"短段落应无问题 (实际 {len(issues)} 条)")


def test_anti_ai_pov() -> None:
    section("[ANTI_AI 6] pov_consist 视角一致")

    # 主 POV = first, 中间混入 third
    mixed = (
        "我走在山间小路上, 看着远方的云。\n\n"
        "他回头看了她一眼, 心里想着这女子究竟是谁, 她的眼神里藏着什么秘密, "
        "她为何独自一人出现在这荒山野岭, 是否与师门失踪一事有关联。\n\n"
        "我继续前行, 心里想着师傅的嘱托。"
    )
    issues = check_pov_consist(mixed)
    # 应触发 (第 2 段以 third 为主)
    check(len(issues) >= 1, f"POV 漂移应触发 (实际 {len(issues)} 条)")

    # 全程 first
    good = (
        "我走在山间小路上, 看着远方的云。\n\n"
        "我继续前行, 心里想着师傅的嘱托, 想着母亲在家中等待。"
    )
    issues = check_pov_consist(good)
    check(len(issues) == 0, f"全程 first 应无问题 (实际 {len(issues)} 条)")

    # 显式指定 expected_pov
    issues = check_pov_consist(mixed, expected_pov="first")
    check(len(issues) >= 1, "显式 expected_pov=first 仍应检测漂移")


def test_anti_ai_info_gap() -> None:
    section("[ANTI_AI 7] info_gap 信息差")

    # 多个"心想"
    bad = "他心想这件事不简单。她心想他应该回来了。心中暗道这事有蹊跷。心里想这局该如何破。"
    issues = check_info_gap(bad)
    check(len(issues) >= 1, f"多个'心想'应触发 (实际 {len(issues)} 条)")
    if issues:
        check(issues[0].kind == CheckKind.INFO_GAP, "kind 正确")

    # 0 处心想
    good = "他看着远方的天际, 没有说话。"
    issues = check_info_gap(good)
    check(len(issues) == 0, f"无'心想'应无问题 (实际 {len(issues)} 条)")


def test_anti_ai_run_all() -> None:
    section("[ANTI_AI 8] run_all 综合")

    # 极 AI 味文本: 触发多种 (info_gap + rhetoric)
    # 1) 多处"心想"  2) 长段落 + 多个修辞词
    ai_text = (
        "他心想这个主意不错。\n"
        "他心想时间紧迫。\n"
        "他心想不能再拖了。\n"
        "他心想这局有变。\n\n"
        "在" + "字" * 100 + "里, 景色非常美, 极其壮观, 十分动人, 格外迷人, "
        "异常秀丽, 完美无瑕, 倾国倾城, 风华绝代。"
    )
    issues = run_all(ai_text)
    check(len(issues) >= 2, f"run_all 应至少 2 条 (实际 {len(issues)})")

    # 干净文本
    clean = "他抬眼。\n剑光一闪, 寒芒乍现, 划破了夜的寂静。她退了一步, 没有说话。"
    issues = run_all(clean)
    # 干净文本应 <= 1 条
    check(len(issues) <= 1, f"干净文本应 <= 1 条问题 (实际 {len(issues)})")


# ═══════════════════════════════════════════════════════════
#                  MAIN
# ═══════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 60)
    print("E2 SMOKE: 记忆 L1-L4 + 压力计 + 6 大去 AI 味")
    print("=" * 60)

    _setup_db()
    pid, cids = _make_project_chapters()
    print(f"\n[SETUP] project={pid}, chapters={len(cids)}")

    # memory
    test_memory_basic(pid, cids)
    test_memory_l1l2_and_promises(pid, cids)
    test_memory_fade(pid, cids)
    test_memory_as_of(pid, cids)

    # pressure
    test_pressure_compute()
    test_pressure_record_and_query(pid, cids)
    test_pressure_format()

    # anti_ai
    test_anti_ai_basic()
    test_anti_ai_sentence_pattern()
    test_anti_ai_dialogue_voice()
    test_anti_ai_pacing()
    test_anti_ai_rhetoric()
    test_anti_ai_pov()
    test_anti_ai_info_gap()
    test_anti_ai_run_all()

    print(f"\n{'=' * 60}")
    print(f"结果: {_pass} passed, {_fail} failed")
    print(f"{'=' * 60}")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
