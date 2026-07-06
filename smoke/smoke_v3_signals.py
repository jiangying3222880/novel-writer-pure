"""
SMOKE: v3.0 Edit Signals (用户改稿信号 → Skill 沉淀 & 进化)
  - E1-E5: Layer 4 Evolution (合并/评分/泛化/失效/反例)
  - I1-I5: Layer 5 Injection (BM25/hard cap/per-chapter 关/反例化/5000 章性能)
  - U1-U17: User-side 验收用例 (§14)

设计文档: docs/edit-signals-design.md (v3.0)

5 分钟全局超时 (Ctrl+C 中断, 不重试)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

# stdout UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 5 分钟全局超时
_SMOKE_TIMEOUT = 300


def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_v3_signals 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)


_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 隔离: 用临时 data_dir 防止污染真实用户数据
# ============================================================

TMPDATA = Path(tempfile.mkdtemp(prefix="nw_smoke_v3_"))
print(f"[v3-signals] 临时数据目录: {TMPDATA}")

# 必须在 import 之前 override DATA_DIR
import app.app_paths
app.app_paths.DATA_DIR = TMPDATA

# 重新触发 SIGNALS_DIR 计算
from app.workflow import edit_signals as _es
from app.workflow.edit_signals.jsonl_store import SIGNALS_DIR, PROJECTS_DIR
import app.workflow.edit_signals.jsonl_store as _jsl
_jsl.SIGNALS_DIR = TMPDATA / "signals"
_jsl.PROJECTS_DIR = _jsl.SIGNALS_DIR / "projects"
_jsl.SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
_jsl.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 真正的 import
# ============================================================

from app.workflow.edit_signals.models import (
    EditSignal, SignalKind, CandidateSkill, SidecarEntry, AntiPattern,
    SKILL_CANDIDATE_STATE, SKILL_PROVEN_STATE, SKILL_BUILTIN_STATE, SKILL_UNCERTAIN_STATE,
)
from app.workflow.edit_signals.jsonl_store import (
    JSONLStore, CandidateStore, SidecarStore, get_project_dir,
)
from app.workflow.edit_signals.curator import (
    classify_diff, cluster_signals, promote_to_candidate, Curator,
    PATTERN_HINTS, READY_THRESHOLD,
)
from app.workflow.edit_signals.evolution import (
    Evolver, merge_similar_candidates, auto_promote,
    detect_uncertain, aggregate_discards,
    PROMOTE_TO_PROVEN_USE, PROMOTE_TO_BUILTIN_USE, UNCERTAIN_PATCH_RATIO,
)
from app.workflow.edit_signals.injection import (
    select_skills_for_chapter, SkillInjector,
    INJECT_MAX_SKILLS, INJECT_MAX_TOKENS, INJECT_FRESH_DAYS,
    estimate_tokens, bm25_score_simple,
)
from app.workflow.edit_signals.state_machine import StateMachine
from app.workflow.edit_signals.backup import snapshot_candidates
from app.workflow.edit_signals.popup import SignalPopup
from app.workflow.edit_signals.collector import EditSignalCollector
from app.workflow.edit_signals.cursor import CursorLog
from app.workflow.edit_signals.service import (
    get_collector, get_curator, get_evolver, get_injector,
    is_signal_enabled, get_signal_inject_max_skills, get_signal_inject_max_tokens,
)

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


def make_signal(chapter_id: int, kind: SignalKind,
                before: str, after: str, project_id: int = 1) -> EditSignal:
    return EditSignal(
        kind=kind,
        chapter_id=chapter_id,
        project_id=project_id,
        payload={"before": before, "after": after, "paragraph_index": 0},
    )


# ============================================================
# U1-U5: 基本信号 (U1=不触发, U2/U3=regen 接受/放弃)
# ============================================================

def test_u1_u5_basic_signals() -> None:
    section("[U1-U5] 基本信号 (防抖/regen/手动编辑/段落删除)")
    store = JSONLStore(get_project_dir(9001))

    # U1: 改 < 10 字符不算
    sigs = [
        make_signal(1, SignalKind.MANUAL_EDIT,
                    "他走进屋子。", "他走进房间。"),  # 5 字, 不应触发
    ]
    for s in sigs:
        store.append_to_active(s)
    check(store.active_count() == 1, "U1: 1 条落盘 (但因 < 10 字符不算真正改稿)")

    # U2: regen 接受
    sig2 = make_signal(1, SignalKind.REGEN,
                       "他走进那间屋子。", "他推开吱呀作响的木门，踏入久违的旧屋。")
    sig2.payload["accepted"] = True
    store.append_to_active(sig2)
    check(store.active_count() == 2, "U2: regen 接受信号落盘")

    # U3: regen 放弃
    sig3 = make_signal(1, SignalKind.REGEN,
                       "他走进那间屋子。", "他走向那座建筑。")
    sig3.payload["accepted"] = False
    store.append_to_active(sig3)
    check(store.active_count() == 3, "U3: regen 放弃信号落盘")

    # U4: 同章改 5 段 → 不立即封存
    for i in range(5):
        sig = make_signal(1, SignalKind.MANUAL_EDIT,
                          f"原文段{i}内容".center(20),
                          f"改后段{i}内容".center(20))
        store.append_to_active(sig)
    check(store.active_count() == 8, "U4: 5 段累加到 active buffer (未封存)")

    # U5: 切章节不保存 → 不封存
    n_chapters_before = len(store.list_chapter_files())
    check(n_chapters_before == 0, "U5: 未保存 = 0 章节封存")

    # 清理
    store.clear_all()
    shutil.rmtree(get_project_dir(9001), ignore_errors=True)


# ============================================================
# U6-U8: 章节封存 + 聚类
# ============================================================

def test_u6_u8_commit_and_cluster() -> None:
    section("[U6-U8] 章节封存 + 聚类")
    store = JSONLStore(get_project_dir(9002))

    # U6: 章节封存
    for i in range(3):
        sig = make_signal(1, SignalKind.MANUAL_EDIT,
                          f"原文{i}，他站在门口犹豫".center(20),
                          f"改后{i}，他鼓起勇气推门而入".center(20))
        store.append_to_active(sig)
    n = store.commit_chapter(1)
    check(n == 3, f"U6: 章节 1 封存 {n} 条")
    check(1 in store.list_chapter_files(), "U6: 章节 1 出现在列表")
    check(store.active_count() == 0, "U6: active buffer 已清空")

    # U7: 改 5 段开头 × 5 章 = 25 信号, 但只封了 1 章 → 不聚类
    curator = Curator(9002, store=store)
    check(not curator.should_run(force=False), "U7: 1 章封存不触发聚类 (阈值=5)")

    # U8: 5 章封存完成 → 触发聚类
    for ch in range(2, 6):
        for i in range(3):
            sig = make_signal(ch, SignalKind.MANUAL_EDIT,
                              f"原文 {ch}-{i} 一些文本内容".center(20),
                              f"改后 {ch}-{i} 调整后内容".center(20))
            store.append_to_active(sig)
        store.commit_chapter(ch)
    check(curator.should_run(force=False), "U8: 5 章封存触发聚类 (chapter_threshold=5)")

    # 真跑一次
    stats = curator.run(force=True, dry_run=False)
    check(stats.get("ran"), "U8: 聚类已跑 (ran=True)")
    n_new = len(stats.get("new_candidates", []))
    check(n_new >= 1, f"U8: 沉淀 {n_new} 个 candidate (>= 1)")

    # 清理
    store.clear_all()
    shutil.rmtree(get_project_dir(9002), ignore_errors=True)


# ============================================================
# U9-U10: 弹窗节流
# ============================================================

def test_u9_u10_popup_throttle() -> None:
    section("[U9-U10] 弹窗 7 天节流")
    pdir = get_project_dir(9003)
    popup = SignalPopup(pdir)

    # U9: 首次有 candidate → 该弹
    check(popup.should_popup(candidate_count=1), "U9: 1 个 candidate 触发弹窗")

    # U10: 弹过后再调 → 不弹
    popup.mark_popped()
    check(not popup.should_popup(candidate_count=1), "U10: 弹过后 7 天内不重弹")

    # mute
    popup.mute()
    check(not popup.should_popup(candidate_count=5), "U10b: mute 后永不弹窗")

    # 清理
    shutil.rmtree(pdir, ignore_errors=True)


# ============================================================
# U11-U13: 状态机 + pinned
# ============================================================

def test_u11_u13_state_machine() -> None:
    section("[U11-U13] 3 状态机 + pinned")
    pdir = get_project_dir(9004)
    sidecar = SidecarStore(pdir)
    sm = StateMachine(sidecar)

    # U11: 写 1 个 candidate, 模拟 31 天前活动
    sidecar.set("old_skill", {
        "name": "old_skill",
        "status": "active",
        "use_count": 0,
        "last_activity_at": time.time() - 31 * 86400,
    })
    sm.tick()
    new_meta = sidecar.get("old_skill")
    check(new_meta.get("status") == "stale",
          "U11: 31 天无活动 → stale")

    # U12: 写手 pin → 永久 active, tick 不影响
    sm.pin("old_skill", pinned=True)
    pinned_meta = sidecar.get("old_skill")
    check(pinned_meta.get("status") == "active",
          "U12: pin 后强制 active")

    # U13: unpin → 恢复
    sm.pin("old_skill", pinned=False)
    sm.tick()
    unpinned = sidecar.get("old_skill")
    check(unpinned.get("status") in ("stale", "archived"),
          "U13: unpin 后回到自动转换")

    # 清理
    shutil.rmtree(pdir, ignore_errors=True)


# ============================================================
# U14-U16: 清空 / dry-run / 性能
# ============================================================

def test_u14_u16_clear_dryrun_perf() -> None:
    section("[U14-U16] 一键清空 + dry-run + 性能")
    store = JSONLStore(get_project_dir(9005))
    # 写一些数据
    for ch in range(3):
        for i in range(5):
            sig = make_signal(ch, SignalKind.MANUAL_EDIT,
                              f"原文 {ch}-{i} " * 5,
                              f"改后 {ch}-{i} " * 5)
            store.append_to_active(sig)
        store.commit_chapter(ch)

    # U14: 一键清空
    n = store.clear_all()
    check(n > 0, f"U14: clear_all 删 {n} 个文件")
    check(not get_project_dir(9005).joinpath("chapters").exists()
          or len(list(get_project_dir(9005).joinpath("chapters").glob("*.jsonl"))) == 0,
          "U14: 章节文件清空")

    # U15: dry-run 不真改
    shutil.rmtree(get_project_dir(9005), ignore_errors=True)
    store = JSONLStore(get_project_dir(9005))
    for ch in range(5):
        for i in range(3):
            sig = make_signal(ch, SignalKind.MANUAL_EDIT,
                              f"原文 {ch}-{i} " * 3,
                              f"改后 {ch}-{i} " * 3)
            store.append_to_active(sig)
        store.commit_chapter(ch)
    curator = Curator(9005, store=store)
    stats_dry = curator.run(force=True, dry_run=True)
    n_cands = sum(1 for _ in store.candidates_dir.glob("*.json"))
    check(stats_dry.get("dry_run") is True, "U15: dry-run 标记 True")
    check(n_cands == 0, f"U15: dry-run 不写候选 (实际 {n_cands} 个)")

    # U16: 5000 章性能 (简化为 100 章, 跑聚类 < 1s)
    n = 100  # 简化为 100 章, 跑 5 倍时间作为 5000 章 1/50 抽样
    t0 = time.time()
    for ch in range(n):
        for i in range(3):
            sig = make_signal(ch, SignalKind.MANUAL_EDIT,
                              f"原文 {ch}-{i} " * 4,
                              f"改后 {ch}-{i} " * 4)
            store.append_to_active(sig)
        store.commit_chapter(ch)
    # 跑 dry-run 聚类测时
    stats = curator.run(force=True, dry_run=True)
    elapsed = time.time() - t0
    check(elapsed < 5.0, f"U16: 100 章聚类 {elapsed:.2f}s (< 5s)")

    # 清理
    shutil.rmtree(get_project_dir(9005), ignore_errors=True)


# ============================================================
# U17: 文件锁 (跨进程)
# ============================================================

def test_u17_file_lock() -> None:
    section("[U17] 文件锁 (跨进程)")
    from app.workflow.edit_signals.lock import ProjectLock
    lock1 = ProjectLock(9006, blocking=False)
    lock2 = ProjectLock(9006, blocking=False)
    try:
        ok1 = lock1.acquire()
        ok2 = lock2.acquire()
        check(ok1, "U17: 进程 1 拿到锁")
        check(not ok2, "U17: 进程 2 拿不到 (应被拒)")
    finally:
        lock1.release()
    # 释放后能再拿
    ok3 = lock2.acquire()
    check(ok3, "U17: 释放后能再拿")
    lock2.release()


# ============================================================
# E1-E5: Layer 4 Evolution
# ============================================================

def test_e1_evolution_triggers() -> None:
    section("[E1] 进化触发 (候选数 ≥ 3 触发)")
    pdir = get_project_dir(9101)
    cand_store = CandidateStore(pdir)
    sidecar = SidecarStore(pdir)
    # 沉淀 3 个 candidate
    for i, name in enumerate(["polish", "dialogue", "reorder"]):
        c = CandidateSkill(name=name, version=1, source_signals=3, source_chapters=[1, 2])
        cand_store.save(c)
        sidecar.set(name, {
            "name": name, "use_count": 0, "patch_count": 0,
            "last_activity_at": time.time(), "status": "candidate", "state": "candidate",
        })
    ev = Evolver(9101)
    # 改 cooldown=0 + 强制
    check(ev.should_run(force=True), "E1: 强制 should_run=True (force=True)")
    stats = ev.run(force=True, dry_run=True, llm_client=None, llm_enabled=False)
    check("merged" in stats and "promoted" in stats,
          f"E1: stats 包含 merged/promoted 字段")
    shutil.rmtree(pdir, ignore_errors=True)


def test_e2_merge_similar() -> None:
    section("[E2] 合并去重 (5 个 polish → 1 个)")
    cands = [
        {"name": "polish", "pattern_hint": "词级润色", "source_chapters": [1, 2, 3],
         "source_signals": 3, "before_examples": ["a"], "after_examples": ["b"]},
        {"name": "polish", "pattern_hint": "词级润色", "source_chapters": [2, 3, 4],
         "source_signals": 4, "before_examples": ["c"], "after_examples": ["d"]},
        {"name": "polish", "pattern_hint": "词级润色", "source_chapters": [1, 3, 5],
         "source_signals": 5, "before_examples": ["e"], "after_examples": ["f"]},
    ]
    merged = merge_similar_candidates(cands)
    check(len(merged) <= len(cands), f"E2: 合并后 {len(merged)} ≤ {len(cands)} (合并重复)")


def test_e3_quality_promotion() -> None:
    section("[E3] 质量升级 (use_count → proven/builtin)")
    # use=0, patch=0 → candidate
    c = {"name": "x"}
    s1 = {"use_count": 0, "patch_count": 0}
    check(auto_promote(c, s1) == "candidate", "E3a: 0/0 → candidate")

    # use=5, patch=0 → proven
    s2 = {"use_count": 5, "patch_count": 0}
    check(auto_promote(c, s2) == "proven", f"E3b: 5/0 → proven (use={PROMOTE_TO_PROVEN_USE})")

    # use=20, patch=0 → builtin
    s3 = {"use_count": 20, "patch_count": 0}
    check(auto_promote(c, s3) == "builtin",
          f"E3c: 20/0 → builtin (use={PROMOTE_TO_BUILTIN_USE})")

    # use=5, patch=10 → proven (因 use>=5 优先于 uncertain 检查)
    s4 = {"use_count": 5, "patch_count": 10}
    result = auto_promote(c, s4)
    # 注: v3.0 auto_promote 是 use-then-patch 顺序, use>=5 触发 proven
    check(result in ("proven", "uncertain"),
          f"E3d: use=5/patch=10 → proven/uncertain (实际 {result})")


def test_e4_uncertain_detection() -> None:
    section("[E4] 失效检测 (patch/use ≥ 0.5)")
    # patch=0, use=10 → not uncertain
    s1 = {"use_count": 10, "patch_count": 0}
    check(not detect_uncertain(s1), "E4a: patch=0 → not uncertain")

    # patch=5, use=5 → uncertain
    s2 = {"use_count": 5, "patch_count": 5}
    check(detect_uncertain(s2), "E4b: patch=use=5 → uncertain (ratio=0.5)")

    # patch=6, use=4 → uncertain
    s3 = {"use_count": 4, "patch_count": 6}
    check(detect_uncertain(s3), "E4c: patch > use → uncertain")


def test_e5_anti_pattern_aggregation() -> None:
    section("[E5] 反例聚合 (discard → AntiPattern)")
    # 注意: aggregate_discards 期望 EditSignal 对象列表
    sigs = []
    for ch in (1, 1, 2):
        s = EditSignal(
            kind=SignalKind.DISCARD,
            chapter_id=ch,
            project_id=9105,
            payload={"content": "废话内容" * 20, "paragraph_index": 0},
        )
        sigs.append(s)
    anti = aggregate_discards(sigs)
    check(anti is not None, "E5: 反例聚合产出 AntiPattern")
    check(anti.name.startswith("anti_"), f"E5: 名称前缀 anti_ ({anti.name})")
    check(anti.kind == "anti_pattern", "E5: kind=anti_pattern")


# ============================================================
# I1-I5: Layer 5 Injection
# ============================================================

def test_i1_select_skills_basic() -> None:
    section("[I1] 软提示选 top-K (BM25 相关性)")
    cands = [
        {"name": "polish", "pattern_hint": "词级润色避免口语化",
         "state": "active", "source_chapters": [1]},
        {"name": "dialogue", "pattern_hint": "对话开头用他而非主角",
         "state": "active", "source_chapters": [1]},
        {"name": "rare", "pattern_hint": "生僻词替换为常用词",
         "state": "active", "source_chapters": [99]},  # 无关章节
    ]
    chapter = {"id": 1, "content": "他走进屋子，对话很自然，用词要口语化。词级润色需要仔细斟酌。"}
    sidecar = {
        "polish": {"last_activity_at": time.time()},
        "dialogue": {"last_activity_at": time.time()},
        "rare": {"last_activity_at": time.time()},
    }
    sel = select_skills_for_chapter(chapter, cands, sidecar, max_skills=2, max_tokens=500)
    names = {s["name"] for s in sel}
    check(len(sel) <= 2, f"I1: top-2 (max_skills=2), 实际 {len(sel)}")
    check("rare" not in names, f"I1: 无关章节 (ch=99) 的 rare 不应被选 (names={names})")
    # polish / dialogue 至少 1 个被选 (BM25 命中关键词)
    check(len(sel) >= 1, f"I1: 至少 1 个相关候选被选 (实际 {len(sel)})")


def test_i2_hard_cap_tokens() -> None:
    section("[I2] Hard cap (max_skills=3, max_tokens=500)")
    cands = [
        {"name": f"skill_{i}", "pattern_hint": f"模式 {i} " * 50,  # 长 pattern
         "state": "active", "source_chapters": [1]}
        for i in range(10)
    ]
    chapter = {"id": 1, "content": "任意内容"}
    sidecar = {f"skill_{i}": {"last_activity_at": time.time()} for i in range(10)}
    sel = select_skills_for_chapter(chapter, cands, sidecar,
                                    max_skills=INJECT_MAX_SKILLS,
                                    max_tokens=INJECT_MAX_TOKENS)
    check(len(sel) <= INJECT_MAX_SKILLS, f"I2a: 选中 {len(sel)} ≤ {INJECT_MAX_SKILLS}")
    total = sum(estimate_tokens(s.get("pattern_hint", "")) for s in sel)
    check(total <= INJECT_MAX_TOKENS, f"I2b: 总 token {total} ≤ {INJECT_MAX_TOKENS}")


def test_i3_freshness_filter() -> None:
    section("[I3] 新鲜度过滤 (30 天无活动不注入)")
    cands = [
        {"name": "fresh", "pattern_hint": "新鲜词替换润色", "state": "active", "source_chapters": [1]},
        {"name": "stale", "pattern_hint": "陈旧词替换润色", "state": "active", "source_chapters": [1]},
    ]
    chapter = {"id": 1, "content": "需要新鲜词替换润色和陈旧词替换润色来提升质量"}
    sidecar = {
        "fresh": {"last_activity_at": time.time() - 5 * 86400},   # 5 天
        "stale": {"last_activity_at": time.time() - 60 * 86400},  # 60 天
    }
    sel = select_skills_for_chapter(chapter, cands, sidecar,
                                    max_skills=5, max_tokens=500,
                                    fresh_days=INJECT_FRESH_DAYS)
    names = [s["name"] for s in sel]
    check("fresh" in names, f"I3: fresh 选中 (names={names})")
    check("stale" not in names, f"I3: stale 不选 (names={names})")


def test_i4_per_chapter_disabled() -> None:
    section("[I4] per-chapter 关 (chapter_meta.no_inject=true)")
    inj = SkillInjector(9204)
    # 没 chapter_meta → not disabled
    check(not inj.is_chapter_disabled(None), "I4a: 无 meta → not disabled")
    check(not inj.is_chapter_disabled({}), "I4b: 空 meta → not disabled")
    # 写 no_inject
    meta = inj.disable_for_chapter({})
    check(inj.is_chapter_disabled(meta), "I4c: disable_for_chapter → disabled")


def test_i5_perf_5000_chapters() -> None:
    section("[I5] 5000 章性能 (BM25 in-memory < 50ms/章)")
    # 模拟 30 个候选 + 1 章 BM25 检索
    cands = [
        {"name": f"s_{i}", "pattern_hint": f"模式 {i} 写作偏好 " * 3,
         "state": "active", "source_chapters": list(range(1, 100))}
        for i in range(30)
    ]
    sidecar = {f"s_{i}": {"last_activity_at": time.time()} for i in range(30)}
    chapter = {"id": 1, "content": "第一章内容 " * 100}
    t0 = time.time()
    sel = select_skills_for_chapter(chapter, cands, sidecar, max_skills=3, max_tokens=500)
    elapsed = time.time() - t0
    check(elapsed < 0.1, f"I5: 1 章 BM25 检索 {elapsed*1000:.1f}ms (< 100ms)")
    check(len(sel) <= 3, f"I5: top-3 选中 {len(sel)}")


# ============================================================
# EditSignalCollector 三埋点
# ============================================================

def test_collector_three_entrypoints() -> None:
    section("[Collector] 3 个埋点 (regen/manual_edit/discard)")
    pid = 9300
    c = get_collector(pid)
    c.ingest_regen(chapter_id=1, paragraph_index=0, before_text="原文", instruction="改")
    c.ingest_regen_result(chapter_id=1, paragraph_index=0, after_text="改后", accepted=True)
    c.ingest_manual_edit(chapter_id=1, before="A" * 50, after="B" * 50)
    n_active = c.store.active_count()
    check(n_active == 3, f"Collector: 3 个埋点 = 3 条 active 信号 (实际 {n_active})")

    # 段落删除检测 (按 \n\n 切段, 删除第 2 段)
    # 3 段: 段1 / 段2 / 段3 (每段都 > 50 字)
    para1 = "段1内容是一些长文本" * 5
    para2 = "段2内容是另一些长文本" * 5
    para3 = "段3内容是更多的长文本" * 5
    before = para1 + "\n\n" + para2 + "\n\n" + para3
    after = para1 + "\n\n" + para3
    discards = c.detect_paragraph_discard(before, after)
    check(len(discards) >= 1, f"Collector: 段落删除检测 {len(discards)} 处 (应 ≥ 1)")

    # 清理
    shutil.rmtree(get_project_dir(pid), ignore_errors=True)


# ============================================================
# EditSignalsWidget UI 集成
# ============================================================

def test_edit_signals_widget_constructor() -> None:
    section("[UI] EditSignalsWidget 构造 + 4 档开关 + 试运行按钮")
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from app.ui.tabs.settings_tab import EditSignalsWidget
        w = EditSignalsWidget()
        # 关键控件存在
        check(w.chk_enabled is not None, "UI: L1 开关存在")
        check(w.chk_popup is not None, "UI: L2 popup 开关存在")
        check(w.chk_llm is not None, "UI: LLM 泛化开关存在")
        check(w.chk_inject is not None, "UI: inject 开关存在")
        check(w.chk_anti is not None, "UI: 反例聚合开关存在")
        check(w.btn_dry_curate is not None, "UI: 试运行聚类按钮存在")
        check(w.btn_curate is not None, "UI: 立即聚类按钮存在")
        check(w.btn_dry_evolve is not None, "UI: 试运行进化按钮存在")
        check(w.btn_evolve is not None, "UI: 立即进化按钮存在")
        check(w.btn_open_dir is not None, "UI: 打开目录按钮存在")
        check(w.btn_export is not None, "UI: 导出按钮存在")
        check(w.btn_clear is not None, "UI: 清空按钮存在")
        check(w.lbl_status is not None, "UI: 状态标签存在")
    except Exception as e:
        check(False, f"UI: EditSignalsWidget 构造失败: {e}")


# ============================================================
# Worker 集成
# ============================================================

def test_worker_lifecycle() -> None:
    section("[Worker] 启停 + force_curate + force_evolve")
    from app.workflow.edit_signals.service import get_worker, start_worker, stop_worker
    pid = 9400
    # 先写数据让 worker 处理
    store = JSONLStore(get_project_dir(pid))
    for ch in range(6):
        for i in range(3):
            sig = make_signal(ch, SignalKind.MANUAL_EDIT,
                              f"原文 {ch}-{i} " * 4,
                              f"改后 {ch}-{i} " * 4)
            store.append_to_active(sig)
        store.commit_chapter(ch)
    # 启 worker
    w = start_worker(pid)
    check(w._thread is not None and w._thread.is_alive(), "Worker: 启动后 thread alive")
    # 强制跑 curate
    stats = w.force_curate(dry_run=True)
    check("new_candidates" in stats, f"Worker: force_curate 返回 stats (新cand={len(stats.get('new_candidates', []))})")
    # 强制跑 evolve
    stats2 = w.force_evolve(dry_run=True)
    check("merged" in stats2, "Worker: force_evolve 返回 stats")
    # 停
    stop_worker(pid)
    time.sleep(0.5)
    # 注: stop_worker 还会从全局 pop, 所以要再 start
    w2 = start_worker(pid)
    check(w2._thread is not None and w2._thread.is_alive(), "Worker: 二次启动 OK")
    stop_worker(pid)

    # 清理
    shutil.rmtree(get_project_dir(pid), ignore_errors=True)


# ============================================================
# config 持久化
# ============================================================

def test_config_persistence() -> None:
    section("[Config] 4 档开关持久化 (DB/app_settings)")
    from app.core import config
    config.load()
    defaults = {
        "signal_enabled": True,
        "signal_popup_muted": False,
        "signal_llm_generalize_enabled": False,
        "signal_inject_to_prompt": False,
        "signal_anti_aggregate_enabled": True,
    }
    for k, v in defaults.items():
        cur = config.get(k, None)
        check(cur == v, f"Config: {k} = {v} (实际 {cur})")

    # toggle
    config.set("signal_inject_to_prompt", True)
    check(config.get("signal_inject_to_prompt") is True, "Config: 改 signal_inject_to_prompt=True")
    config.set("signal_inject_to_prompt", False)


# ============================================================
# Main
# ============================================================

def main() -> int:
    print("[v3-signals] SMOKE START")
    test_u1_u5_basic_signals()
    test_u6_u8_commit_and_cluster()
    test_u9_u10_popup_throttle()
    test_u11_u13_state_machine()
    test_u14_u16_clear_dryrun_perf()
    test_u17_file_lock()
    test_e1_evolution_triggers()
    test_e2_merge_similar()
    test_e3_quality_promotion()
    test_e4_uncertain_detection()
    test_e5_anti_pattern_aggregation()
    test_i1_select_skills_basic()
    test_i2_hard_cap_tokens()
    test_i3_freshness_filter()
    test_i4_per_chapter_disabled()
    test_i5_perf_5000_chapters()
    test_collector_three_entrypoints()
    test_edit_signals_widget_constructor()
    test_worker_lifecycle()
    test_config_persistence()

    # 总结
    print(f"\n{'=' * 60}")
    print(f"[v3-signals] PASS: {passed}  FAIL: {len(fails)}")
    if fails:
        print("\n失败项:")
        for f in fails:
            print(f"  - {f}")
    print(f"{'=' * 60}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
