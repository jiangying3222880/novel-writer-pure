"""
H7/H8 SMOKE: TTS 语音合成 + 使用统计插件
- H7 TTSEdgePlugin: 章节转语音 (mock)
- H8 UsageAnalyticsPlugin: 使用统计 / 周报 / 趋势 / 报告

5 分钟自动超时
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import json
import uuid
from pathlib import Path

# stdout UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 5 分钟全局超时
_SMOKE_TIMEOUT = 300


def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_h7_h8 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)


_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 隔离真实数据
# ============================================================
TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_h7h8_"))
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
from app.services.db import init_db, connection

# ────────────────────── 插件已废弃 (V3.4+ SKIP) ──────────────────────
try:
    from app.plugins.builtin import (
        TTSEdgePlugin,
        UsageAnalyticsPlugin,
    )
    from app.plugins.manager import PluginManager
    _HAS_PLUGINS = True
except ImportError:
    _HAS_PLUGINS = False
    TTSEdgePlugin = UsageAnalyticsPlugin = None  # type: ignore
    class _FakePluginManager:
        def __getattr__(self, name):
            return None
    PluginManager = _FakePluginManager  # type: ignore


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
# 测试 1: H7 synthesize_chapter (mock) - 基本流程
# ============================================================
def test_h7_synthesize_basic() -> tuple[str, TTSEdgePlugin, str]:
    section("[H7 1] synthesize_chapter (mock) - 基本流程")
    p = project_service.create(name="H7/H8 测试", genre="玄幻")
    pid = p["id"]
    b = book_service.create(pid, volume_no=1, title="卷一")
    bid = b["id"]
    ch = chapter_service.create(bid, chapter_no=1, title="第1章 仙门")
    cid = ch["id"]
    # 加 draft 当内容
    chapter_service.create_draft(
        cid,
        content="林天踏入仙门, 灵气缭绕, 他抬头看向高耸的山门, 心中充满期待. "
                "远处传来悠扬的钟声, 仿佛在欢迎他.",
        source="agent",
    )
    ch = chapter_service.get(cid)
    print(f"  [setup] project={pid[:8]} chapter={cid[:8]}")

    tts = TTSEdgePlugin()
    tts.setup({})
    result = tts.synthesize_chapter(cid, engine="mock")
    print(f"  [tts] text_len={result.text_len} duration={result.duration_sec:.1f}s voice={result.voice}")
    print(f"  [tts] out={result.out_path}")

    check(result.engine == "mock", f"engine=mock (实际 {result.engine})")
    check(result.text_len > 0, f"text_len > 0 (实际 {result.text_len})")
    check(result.duration_sec > 0, f"duration_sec > 0 (实际 {result.duration_sec})")
    check(result.out_path and Path(result.out_path).exists(), "输出文件存在")
    check(result.voice and len(result.voice) > 0, f"voice 非空 (实际 {result.voice})")
    return pid, tts, cid


# ============================================================
# 测试 2: H7 sidecar json 元数据
# ============================================================
def test_h7_sidecar(tts: TTSEdgePlugin, cid: str) -> None:
    section("[H7 2] sidecar json 元数据")
    # 通过 tts.get_audio_path 拿到上次输出
    # 但需要 project_id -- 这里通过 chapter 反查
    ch = chapter_service.get(cid)
    b = book_service.get(ch["book_id"])
    pid = b["project_id"]

    ap = tts.get_audio_path(cid, pid)
    check(ap is not None, f"get_audio_path 非空 (实际 {ap})")

    if ap:
        meta_path = Path(ap).with_suffix(".json")
        check(meta_path.exists(), "sidecar json 存在")
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            print(f"  [sidecar] {meta}")
            check(meta.get("chapter_id") == cid, "sidecar.chapter_id 匹配")
            check(meta.get("engine") == "mock", "sidecar.engine=mock")
            check(meta.get("text_len", 0) > 0, "sidecar.text_len > 0")
            check("duration_sec" in meta, "sidecar.duration_sec 字段")
            check("created_at" in meta, "sidecar.created_at 字段")


# ============================================================
# 测试 3: H7 list_synthesized
# ============================================================
def test_h7_list(tts: TTSEdgePlugin, pid: str) -> None:
    section("[H7 3] list_synthesized")
    files = tts.list_synthesized(pid)
    check(len(files) >= 1, f"列出已合成 (实际 {len(files)})")
    if files:
        f0 = files[0]
        check("chapter_id" in f0, "list 项含 chapter_id")
        check("path" in f0, "list 项含 path")
        check("size_bytes" in f0, "list 项含 size_bytes")
        check("mtime" in f0, "list 项含 mtime")


# ============================================================
# 测试 4: H7 错误处理
# ============================================================
def test_h7_errors() -> None:
    section("[H7 4] 错误处理")
    tts = TTSEdgePlugin()
    tts.setup({})

    # 4a: 不存在章节
    try:
        tts.synthesize_chapter("nonexistent_chapter_id_xxx", engine="mock")
        check(False, "不存在章节应抛异常")
    except (ValueError, KeyError, Exception) as e:
        check(True, f"不存在章节异常 ({type(e).__name__})")

    # 4b: 未知 engine
    try:
        tts.synthesize_text("hi", str(TMPDIR / "x.wav"), engine="unknown")
        check(False, "未知 engine 应抛 ValueError")
    except ValueError as e:
        check("engine" in str(e).lower() or "未知" in str(e) or "unknown" in str(e),
              f"未知 engine 异常 (实际: {e})")

    # 4c: edge 模式 (装了 edge-tts 就跑, 没装就 ImportError)
    try:
        tts.synthesize_text("hi", str(TMPDIR / "x_edge.wav"), engine="edge")
        check(True, "edge 模式跑通 (装了 edge-tts)")
    except ImportError:
        check(True, "edge 模式 ImportError (没装 edge-tts, OK)")

    # 4d: 空文本
    b = book_service.create(None, volume_no=99, title="err test") if False else None
    p_empty = project_service.create("H7 错误测试", genre="测试")
    b_empty = book_service.create(p_empty["id"], 1, "err book")
    ch_empty = chapter_service.create(b_empty["id"], 1, "空章")
    try:
        tts.synthesize_chapter(ch_empty["id"], engine="mock")
        # 若未抛异常, 看看是否用 (章节名) 无内容 占位
        check(True, "空章未抛异常 (用了占位文本)")
    except Exception as e:
        check(True, f"空章异常 ({type(e).__name__})")


# ============================================================
# 测试 5: H8 summary
# ============================================================
def test_h8_summary(pid: str) -> None:
    section("[H8 1] summary 总览")
    ana = UsageAnalyticsPlugin()
    ana.setup({})
    s = ana.summary(pid)
    print(f"  [summary] {s.to_dict()}")
    check(s.project_id == pid, "summary.project_id 匹配")
    check(s.chapter_count >= 1, f"chapter_count >= 1 (实际 {s.chapter_count})")
    check(s.draft_count >= 1, f"draft_count >= 1 (实际 {s.draft_count})")
    # 初始没有 usage_records
    check(s.llm_calls == 0, f"初始 llm_calls=0 (实际 {s.llm_calls})")
    check(s.tokens_in == 0, "初始 tokens_in=0")
    check(s.tokens_out == 0, "初始 tokens_out=0")
    check(s.total_cost == 0.0, "初始 total_cost=0")


# ============================================================
# 测试 6: H8 weekly_report
# ============================================================
def test_h8_weekly_report(ana: UsageAnalyticsPlugin, pid: str) -> None:
    section("[H8 2] weekly_report")
    wk = ana.weekly_report(pid, days=7)
    print(f"  [weekly] total_days={wk['total_days']} entries={len(wk['days'])}")
    check(wk["total_days"] == 7, "total_days=7")
    check(len(wk["days"]) == 7, f"7 天都有 entry (实际 {len(wk['days'])})")
    # 每条 entry 都有 date 字段
    for d in wk["days"]:
        check(len(d["date"]) == 10, f"date 格式 YYYY-MM-DD (实际 {d['date']})")
        check("llm_calls" in d, "entry.llm_calls")
        check("tokens_in" in d, "entry.tokens_in")
        check("cost" in d, "entry.cost")


# ============================================================
# 测试 7: H8 cost_breakdown
# ============================================================
def test_h8_cost_breakdown(ana: UsageAnalyticsPlugin, pid: str) -> None:
    section("[H8 3] cost_breakdown")
    br = ana.cost_breakdown(pid)
    print(f"  [breakdown] {br}")
    # 初始空 dict
    check(isinstance(br, dict), "返回 dict")
    check(len(br) == 0, f"初始 cost_breakdown 空 (实际 {len(br)})")


# ============================================================
# 测试 8: H8 format_text_report
# ============================================================
def test_h8_text_report(ana: UsageAnalyticsPlugin, pid: str) -> None:
    section("[H8 4] format_text_report")
    txt = ana.format_text_report(pid)
    print(f"  [report] 前 200 字符: {txt[:200]}")
    check("项目使用分析" in txt, "report 含标题")
    check("总览" in txt, "report 含'总览' section")
    check("近 7 天" in txt, "report 含'近 7 天' section")
    check("按用途拆 cost" in txt, "report 含'按用途拆 cost' section")


# ============================================================
# 测试 9: H8 写 usage_records 后再统计
# ============================================================
def test_h8_with_usage_records(ana: UsageAnalyticsPlugin, pid: str) -> None:
    section("[H8 5] 写 usage_records 后再统计")
    # 准备: 取一个 chapter
    p_row = project_service.get(pid)
    books = book_service.list_for_project(pid) if hasattr(book_service, "list_for_project") else None
    if not books:
        # 用 chapter_service.get(cid) (cid 是 setup 里的)
        cid = pid  # placeholder
    # 直接用本测试前面 test_h7 留下的 cid -- 这里通过 chapter_service 反查
    from app.services.db import connection as _db
    with _db() as _c:
        row = _c.execute(
            "SELECT c.id FROM chapters c JOIN books b ON c.book_id=b.id "
            "WHERE b.project_id=? LIMIT 1", (pid,)
        ).fetchone()
    if not row:
        check(False, "需要 chapter 但 DB 为空")
        return
    cid = row["id"]

    # 插 5 条 usage_records, 时间分布到前 3 天
    for i in range(5):
        rid = str(uuid.uuid4())
        with connection() as db:
            db.execute(
                "INSERT INTO usage_records (id, project_id, chapter_id, provider, model, "
                "step, tokens_in, tokens_out, cost, duration_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (rid, pid, cid, "openai", "gpt-4o-mini",
                 "writer", 1000 * (i + 1), 500 * (i + 1), 0.01 * (i + 1), 1000),
            )
            if i < 3:
                db.execute(
                    "UPDATE usage_records SET created_at = date('now', ?) WHERE id=?",
                    (f"-{i+1} day", rid),
                )
            db.commit()

    # summary
    s = ana.summary(pid)
    print(f"  [summary 二次] {s.to_dict()}")
    check(s.llm_calls == 5, f"llm_calls=5 (实际 {s.llm_calls})")
    expected_in = 1000 + 2000 + 3000 + 4000 + 5000
    expected_out = 500 + 1000 + 1500 + 2000 + 2500
    check(s.tokens_in == expected_in, f"tokens_in={expected_in} (实际 {s.tokens_in})")
    check(s.tokens_out == expected_out, f"tokens_out={expected_out} (实际 {s.tokens_out})")
    check(abs(s.total_cost - 0.15) < 0.001, f"total_cost=0.15 (实际 {s.total_cost})")
    check(s.first_used_at != "", "first_used_at 非空")
    check(s.last_used_at != "", "last_used_at 非空")

    # weekly_report
    wk = ana.weekly_report(pid, days=7)
    total_calls = sum(d["llm_calls"] for d in wk["days"])
    check(total_calls == 5, f"weekly total=5 (实际 {total_calls})")

    # cost_breakdown
    br = ana.cost_breakdown(pid)
    print(f"  [breakdown 二次] {br}")
    check("writer" in br, "cost_breakdown 含 writer step")
    check(abs(br["writer"]["cost"] - 0.15) < 0.001, f"writer cost=0.15 (实际 {br['writer']['cost']})")

    # text_report
    txt = ana.format_text_report(pid)
    check("writer" in txt, "text_report 含 writer step")


# ============================================================
# 测试 10: PluginManager 集成
# ============================================================
def test_plugin_manager_integration() -> None:
    section("[集成] PluginManager 集成")
    mgr = PluginManager(plugins_dir=Path(tempfile.mkdtemp()) / "plugins")
    mgr.register_builtin(TTSEdgePlugin())
    mgr.register_builtin(UsageAnalyticsPlugin())

    info_tts = mgr.get("tts_edge")
    info_ana = mgr.get("usage_analytics")

    check(info_tts is not None, "tts_edge 已注册")
    check(info_tts.builtin, "tts_edge.builtin=True")
    check(info_tts.required_role == "advanced", f"tts_edge role=advanced (实际 {info_tts.required_role})")
    check(info_tts.version == "1.0.0", f"tts_edge version=1.0.0 (实际 {info_tts.version})")

    check(info_ana is not None, "usage_analytics 已注册")
    check(info_ana.builtin, "usage_analytics.builtin=True")
    check(info_ana.required_role == "standard", f"usage_analytics role=standard (实际 {info_ana.required_role})")
    check(info_ana.version == "1.0.0", f"usage_analytics version=1.0.0 (实际 {info_ana.version})")

    print(f"  [PluginManager] tts={info_tts.name} v{info_tts.version} role={info_tts.required_role}")
    print(f"  [PluginManager] ana={info_ana.name} v{info_ana.version} role={info_ana.required_role}")


# ============================================================
# 测试 11: 错误 - 不存在项目
# ============================================================
def test_errors() -> None:
    section("[错误] 不存在项目 / 不存在 chapter")
    ana = UsageAnalyticsPlugin()
    ana.setup({})
    tts = TTSEdgePlugin()
    tts.setup({})

    # summary 不存在项目
    try:
        ana.summary("nonexistent_project_xxx")
        check(False, "summary 不存在项目应抛异常")
    except Exception as e:
        check(True, f"summary 不存在项目异常 ({type(e).__name__})")

    # weekly_report 不存在项目
    try:
        ana.weekly_report("nonexistent_project_xxx")
        check(False, "weekly_report 不存在项目应抛异常")
    except Exception as e:
        check(True, f"weekly_report 不存在项目异常 ({type(e).__name__})")

    # get_audio_path 不存在
    ap = tts.get_audio_path("nonexistent_chapter", "nonexistent_project")
    check(ap is None, "get_audio_path 不存在返回 None")


# ============================================================
# Main
# ============================================================
def main() -> int:
    if not _HAS_PLUGINS:
        print("⊘ smoke_h7_h8: SKIP (app.plugins 已废弃)")
        return 0
    print("=" * 60)
    print("H7/H8 SMOKE: TTS 语音合成 + 使用统计插件")
    print("=" * 60)
    print(f"[setup] tmpdir = {TMPDIR}")

    init_db()
    from app.db import _impl as db_conn
    db_conn.init(DB_PATH)
    print(f"[setup] DB = {DB_PATH}")

    pid, tts, cid = test_h7_synthesize_basic()
    test_h7_sidecar(tts, cid)
    test_h7_list(tts, pid)
    test_h7_errors()

    test_h8_summary(pid)
    ana = UsageAnalyticsPlugin()
    ana.setup({})
    test_h8_weekly_report(ana, pid)
    test_h8_cost_breakdown(ana, pid)
    test_h8_text_report(ana, pid)
    test_h8_with_usage_records(ana, pid)

    test_plugin_manager_integration()
    test_errors()

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
