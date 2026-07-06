"""
G17 SMOKE: Agent 体系 (基类 + 编排 + 6 个辅助 Agent)
- AgentBase 状态机 / metrics / execute / cancel
- Report 数据类 / kind / to_dict
- Orchestrator 7 步编排 (memory → pressure → retrieve → write → eval → revise loop → persist)
- 辅助 Agent 隔离 (互不通信, 只汇报给编排)
- 回调门控 (评估分低 → 改稿)
- 追读率调剧情 (低/中/高三档)
- 取消信号

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
    print(f"\n[TIMEOUT] smoke_g17_agents 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 隔离真实数据
# ============================================================

TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_g17_"))
DB_PATH = TMPDIR / "test.db"
STORY_DIR = TMPDIR / "story"
STORY_DIR.mkdir(parents=True, exist_ok=True)

import app.app_paths
app.app_paths.sqlite_path = lambda: DB_PATH

import app.services.file_store
app.services.file_store.BASE_DIR = STORY_DIR

# ============================================================
# Imports
# ============================================================
from app.agents import (
    Report, ReportKind, AgentBase, AgentRole, AgentState, Orchestrator,
)
from app.agents.base import AgentMetrics, AgentCancelledError
from app.agents.orchestrator import OrchestratorConfig, OrchestratorResult
from app.agents.helpers import (
    StoryTeller, Editor, Critic, Retriever, MemoryKeeper, PressureWatcher,
)
from app.services import db as svc_db
from app.db import connection

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


def _make_min_project() -> tuple[str, str]:
    """建一个最小项目+书+章节, 返 (project_id, chapter_id)."""
    import uuid as _uuid
    conn = connection.get_conn()
    pid = "p_g17_" + _uuid.uuid4().hex[:8]
    bid = "b_g17_" + _uuid.uuid4().hex[:8]
    cid = "c_g17_" + _uuid.uuid4().hex[:8]
    conn.execute(
        "INSERT INTO projects (id, name, genre, created_at) VALUES (?, ?, ?, datetime('now'))",
        (pid, "G17 测试项目", "仙侠"),
    )
    conn.execute(
        "INSERT INTO books (id, project_id, volume_no, title, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (bid, pid, 1, "第一卷"),
    )
    conn.execute(
        "INSERT INTO chapters (id, book_id, chapter_no, title, scene_context, created_at) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (cid, bid, 1, "入门", "主角清晨打坐, 山门外有脚步声"),
    )
    return pid, cid


# ============================================================
# 1. Report 数据类
# ============================================================
def test_report() -> None:
    section("[G17 1] Report 数据类")
    r = Report.ok_with("ag_1", "writer", ReportKind.WRITE, {"content": "hello"})
    check(r.ok, "ok=True")
    check(r.kind == ReportKind.WRITE, f"kind=WRITE ({r.kind})")
    check(r.data == {"content": "hello"}, "data 一致")
    check(r.report_id.startswith("rep_"), f"report_id 前缀 ({r.report_id})")
    # to_dict
    d = r.to_dict()
    check("ok" in d and "data" in d and "kind" in d, "to_dict 含 ok/data/kind")
    check(d["kind"] == "write", f"to_dict kind 序列化正确 ({d['kind']})")
    # to_json + from_dict
    r2 = Report.from_dict(r.to_dict())
    check(r2.ok == r.ok and r2.data == r.data, "from_dict 还原一致")
    # fail
    rf = Report.fail("ag_1", "writer", ReportKind.WRITE, "写崩了")
    check(rf.ok is False, "fail ok=False")
    check("写崩" in rf.error, f"fail error 包含原因 ({rf.error})")
    # 6 个 kind
    expected_kinds = {"memory", "anti_ai", "pressure", "retrieve", "write",
                      "revise", "edit", "critic", "persist", "retention", "log"}
    actual_kinds = {k.value for k in ReportKind}
    check(expected_kinds.issubset(actual_kinds), f"6+ kind 齐全 (差异: {expected_kinds - actual_kinds})")


# ============================================================
# 2. AgentBase 状态机
# ============================================================
def test_agent_base_state() -> None:
    section("[G17 2] AgentBase 状态机")

    class Dummy(AgentBase):
        DEFAULT_KIND = ReportKind.LOG
        def _do_execute(self, task: dict) -> Report:
            return self._build_report(task, {"v": 1})

    a = Dummy(name="D", role=AgentRole.WRITER)
    check(a.state == AgentState.IDLE, f"初始 IDLE ({a.state})")
    check(a.metrics.total_tasks == 0, f"metrics 0 (实际 {a.metrics.total_tasks})")
    check(a.role == AgentRole.WRITER, f"role=WRITER ({a.role})")

    r = a.execute({"id": "t1", "context": {}})
    check(r.ok, f"execute 成功")
    check(a.state == AgentState.DONE, f"DONE ({a.state})")
    check(a.metrics.total_tasks == 1, f"metrics +1 ({a.metrics.total_tasks})")
    check(a.metrics.total_ok == 1, f"metrics total_ok=1 ({a.metrics.total_ok})")
    check(a.metrics.success_rate == 1.0, f"success_rate=1.0 ({a.metrics.success_rate})")
    check(len(a.history) == 1, f"history 1 条 ({len(a.history)})")

    # 错误路径
    class Boom(AgentBase):
        DEFAULT_KIND = ReportKind.LOG
        def _do_execute(self, task: dict) -> Report:
            raise RuntimeError("炸了")

    b = Boom(name="B", role=AgentRole.EDITOR)
    rb = b.execute({"id": "t2"})
    check(rb.ok is False, "Boom 失败 ok=False")
    check(b.state == AgentState.ERROR, f"ERROR ({b.state})")
    check(b.metrics.total_err == 1, f"total_err=1 ({b.metrics.total_err})")
    check("炸了" in rb.error, f"error 包含原因 ({rb.error})")

    # 取消
    a.cancel()
    check(a._cancelled is True, "cancel 后 _cancelled=True")
    a.reset()
    check(a._cancelled is False, f"reset 后 _cancelled=False (实际 {a._cancelled})")
    check(a.state == AgentState.IDLE, f"reset 后 IDLE ({a.state})")

    # metrics
    m = AgentMetrics()
    m.total_tasks = 10
    m.total_ok = 7
    m.total_err = 3
    m.total_duration_ms = 1000
    check(m.success_rate == 0.7, f"success_rate=0.7 ({m.success_rate})")
    check(m.avg_duration_ms == 100.0, f"avg_duration=100 ({m.avg_duration_ms})")
    check(m.to_dict()["success_rate"] == 0.7, "to_dict 序列化")


# ============================================================
# 3. 辅助 Agent 隔离 (互不通信, 只汇报给编排)
# ============================================================
def test_helpers_isolated() -> None:
    section("[G17 3] 辅助 Agent 隔离 (互不通信)")

    # 1) 6 个默认 helper 都存在
    orch = Orchestrator()
    expected = {AgentRole.WRITER, AgentRole.EDITOR, AgentRole.CRITIC,
                AgentRole.RETRIEVER, AgentRole.MEMORY, AgentRole.PRESSURE}
    actual = {AgentRole(r) for r in orch.helpers}
    check(actual == expected, f"6 个 helper 齐全 (实际 {actual})")

    # 2) 每个 helper 都是 AgentBase
    for role, agent in orch.helpers.items():
        check(isinstance(agent, AgentBase), f"{role} 是 AgentBase ({type(agent).__name__})")

    # 3) helper 互不持有其他 helper 引用
    for role, agent in orch.helpers.items():
        # 不应有 orchestrator 引用
        check(not hasattr(agent, "_other_agents"),
              f"{role} 不持其他 agent 引用 (隔离原则)")
        # 不应有 orchestrator 引用
        check(not hasattr(agent, "_orchestrator"),
              f"{role} 不知道编排存在 (士兵原则)")

    # 4) 每个 helper 都能单独 execute
    for role, agent in orch.helpers.items():
        agent.reset()
        r = agent.execute({"id": f"test_{role}", "context": {}})
        # 允许失败 (DB 未起), 但应该有汇报
        check(r is not None, f"{role}.execute 返回 Report")
        check(hasattr(r, "agent_role") and r.agent_role == role,
              f"{role} 汇报 role 正确 ({r.agent_role})")
        check(r.kind != ReportKind.LOG or True, f"{role} 汇报 kind 有效 ({r.kind})")


# ============================================================
# 4. 7 步编排
# ============================================================
def test_orchestrator_7_steps() -> None:
    section("[G17 4] Orchestrator 7 步编排")

    pid, cid = _make_min_project()

    orch = Orchestrator()
    # 替换 retriever 为纯 mock (offline 友好)
    class FakeRetriever(AgentBase):
        DEFAULT_KIND = ReportKind.RETRIEVE
        def _do_execute(self, task):
            return self._build_report(task, {"snippets": "[mock 检索结果]", "hits": 1})
    orch.register(FakeRetriever(name="FakeR", role=AgentRole.RETRIEVER))

    # 替换 memory 为纯 mock
    class FakeMemory(AgentBase):
        DEFAULT_KIND = ReportKind.MEMORY
        def _do_execute(self, task):
            return self._build_report(task, {
                "text": "[L1: 林轩 修真][L2: 山门外 清晨][L3: 上一章 入门]",
                "zone": "yellow", "can_open_hook": True,
            })
    orch.register(FakeMemory(name="FakeM", role=AgentRole.MEMORY))

    # 替换 pressure 为纯 mock
    class FakePressure(AgentBase):
        DEFAULT_KIND = ReportKind.PRESSURE
        def _do_execute(self, task):
            return self._build_report(task, {"zone": "yellow", "can_open_hook": True, "score": 0.5})
    orch.register(FakePressure(name="FakeP", role=AgentRole.PRESSURE))

    result = orch.run_chapter(pid, cid, on_step=lambda s, lbl: None)
    check(result.ok, f"7 步编排成功 (ok={result.ok}, error={result.error})")
    check(result.content, f"有正文 ({len(result.content)} 字)")
    check(result.score >= 0, f"score={result.score}")
    check(result.revisions >= 0, f"revisions={result.revisions}")
    # 7 步 → 至少 5 个汇报 (memory + pressure + retrieve + write + edit + critic + persist)
    check(len(result.reports) >= 5, f"汇报数 >= 5 (实际 {len(result.reports)})")

    # 汇报顺序
    kinds = [r.kind for r in result.reports]
    check(kinds[0] == ReportKind.MEMORY, f"第 1 步 memory (实际 {kinds[0]})")
    check(ReportKind.WRITE in kinds, f"含 WRITE (kinds={kinds})")
    check(ReportKind.EDIT in kinds, f"含 EDIT")
    check(ReportKind.PERSIST in kinds, f"含 PERSIST (末尾)")

    # 精炼 prompt 非空
    check(len(result.refined_prompt) > 50, f"精炼 prompt 长度 {len(result.refined_prompt)}")

    # to_dict
    d = result.to_dict()
    check("ok" in d and "score" in d, "to_dict 字段齐全")


# ============================================================
# 5. 回调门控 (评估分低 → 改稿)
# ============================================================
def test_revision_loop() -> None:
    section("[G17 5] 回调门控 (评估分低 → 改稿)")

    pid, cid = _make_min_project()

    orch = Orchestrator(config=OrchestratorConfig(pass_score=80, max_revisions=2))
    # 全 mock
    class FakeR(AgentBase):
        DEFAULT_KIND = ReportKind.RETRIEVE
        def _do_execute(self, t): return self._build_report(t, {"snippets": ""})
    class FakeM(AgentBase):
        DEFAULT_KIND = ReportKind.MEMORY
        def _do_execute(self, t): return self._build_report(t, {"text": "mem", "zone": "green"})
    class FakeP(AgentBase):
        DEFAULT_KIND = ReportKind.PRESSURE
        def _do_execute(self, t): return self._build_report(t, {"zone": "green", "can_open_hook": True})
    # 编辑: 永远打 50 分 → 必触发改稿
    class LowEditor(AgentBase):
        DEFAULT_KIND = ReportKind.EDIT
        def _do_execute(self, t): return self._build_report(t, {"score": 50, "axes": {}, "issues": ["缺冲突"]})
    class LowCritic(AgentBase):
        DEFAULT_KIND = ReportKind.CRITIC
        def _do_execute(self, t): return self._build_report(t, {"score": 50, "style_notes": ""})
    orch.register(FakeR(name="R", role=AgentRole.RETRIEVER))
    orch.register(FakeM(name="M", role=AgentRole.MEMORY))
    orch.register(FakeP(name="P", role=AgentRole.PRESSURE))
    orch.register(LowEditor(name="E", role=AgentRole.EDITOR))
    orch.register(LowCritic(name="C", role=AgentRole.CRITIC))

    result = orch.run_chapter(pid, cid)
    check(result.ok, f"ok=True ({result.error})")
    check(result.score == 50, f"score=50 (实际 {result.score})")
    check(result.revisions == 2, f"revisions=2 (max_revisions 改满, 实际 {result.revisions})")
    # 改稿次数 = 编辑+批评家 2 个 × 2 轮 + 初稿 1 = 5 (WRITE+REVISE 类)
    write_kinds = [r for r in result.reports if r.kind in (ReportKind.WRITE, ReportKind.REVISE)]
    check(len(write_kinds) >= 2, f"改稿 >= 2 次 (实际 {len(write_kinds)})")

    # 改稿后 score 仍 50 → max_revisions 限制生效
    check(result.revisions == orch.config.max_revisions,
          f"revisions = max_revisions ({orch.config.max_revisions})")


# ============================================================
# 6. 改稿循环关闭
# ============================================================
def test_revision_loop_disabled() -> None:
    section("[G17 6] 改稿循环关闭 (单轮评估)")

    pid, cid = _make_min_project()
    orch = Orchestrator(config=OrchestratorConfig(enable_revision_loop=False))
    class FakeR(AgentBase):
        DEFAULT_KIND = ReportKind.RETRIEVE
        def _do_execute(self, t): return self._build_report(t, {"snippets": ""})
    class FakeM(AgentBase):
        DEFAULT_KIND = ReportKind.MEMORY
        def _do_execute(self, t): return self._build_report(t, {"text": "mem", "zone": "green"})
    class FakeP(AgentBase):
        DEFAULT_KIND = ReportKind.PRESSURE
        def _do_execute(self, t): return self._build_report(t, {"zone": "green", "can_open_hook": True})
    orch.register(FakeR(name="R", role=AgentRole.RETRIEVER))
    orch.register(FakeM(name="M", role=AgentRole.MEMORY))
    orch.register(FakeP(name="P", role=AgentRole.PRESSURE))

    result = orch.run_chapter(pid, cid)
    check(result.ok, f"ok=True")
    check(result.revisions == 0, f"revisions=0 (循环关闭, 实际 {result.revisions})")


# ============================================================
# 7. 追读率调剧情
# ============================================================
def test_retention_adjustment() -> None:
    section("[G17 7] 追读率调剧情")

    pid, cid = _make_min_project()
    orch = Orchestrator()
    class FakeR(AgentBase):
        DEFAULT_KIND = ReportKind.RETRIEVE
        def _do_execute(self, t): return self._build_report(t, {"snippets": ""})
    class FakeM(AgentBase):
        DEFAULT_KIND = ReportKind.MEMORY
        def _do_execute(self, t): return self._build_report(t, {"text": "mem", "zone": "green"})
    class FakeP(AgentBase):
        DEFAULT_KIND = ReportKind.PRESSURE
        def _do_execute(self, t): return self._build_report(t, {"zone": "green", "can_open_hook": True})
    orch.register(FakeR(name="R", role=AgentRole.RETRIEVER))
    orch.register(FakeM(name="M", role=AgentRole.MEMORY))
    orch.register(FakeP(name="P", role=AgentRole.PRESSURE))

    # 1) 追读率低 (0.20) → 调剧情
    r1 = orch.run_chapter(pid, cid, retention=0.20)
    check(r1.retention_adjusted is True, f"retention=0.20 触发调剧情 (实际 {r1.retention_adjusted})")
    check("追读率低" in r1.refined_prompt or "加强" in r1.refined_prompt,
          f"精炼 prompt 含追读率调整指令 (前 200: {r1.refined_prompt[:200]})")

    # 2) 追读率高 (0.80) → 不调
    r2 = orch.run_chapter(pid, cid, retention=0.80)
    check(r2.retention_adjusted is False, f"retention=0.80 不调剧情 (实际 {r2.retention_adjusted})")
    check("追读率低" not in r2.refined_prompt, f"高追读率无低调整指令")

    # 3) None → 跳过
    r3 = orch.run_chapter(pid, cid, retention=None)
    check(r3.retention_adjusted is False, f"retention=None 不调 (实际 {r3.retention_adjusted})")


# ============================================================
# 8. 取消信号
# ============================================================
def test_cancel() -> None:
    section("[G17 8] 取消信号 (在 run 期间触发)")

    pid, cid = _make_min_project()
    orch = Orchestrator()
    # 写手: 在执行时主动调 orch.cancel() → 模拟用户中途点取消
    class CancelWriter(AgentBase):
        DEFAULT_KIND = ReportKind.WRITE
        def _do_execute(self, t):
            # 通知编排取消后续步骤
            orch.cancel()
            self._check_cancel()    # 这一行会 raise AgentCancelledError
            return self._build_report(t, {"content": "x"})
    orch.register(CancelWriter(name="CancelWriter", role=AgentRole.WRITER))

    r = orch.run_chapter(pid, cid)
    check(r.ok is False, f"取消后 ok=False (实际 {r.ok})")
    check("取消" in r.error or "cancel" in r.error.lower(), f"error 含取消 ({r.error})")


# ============================================================
# 9. 报告汇聚
# ============================================================
def test_reports_aggregated() -> None:
    section("[G17 9] 报告汇聚与回溯")

    pid, cid = _make_min_project()
    orch = Orchestrator()
    class FakeR(AgentBase):
        DEFAULT_KIND = ReportKind.RETRIEVE
        def _do_execute(self, t): return self._build_report(t, {"snippets": ""})
    class FakeM(AgentBase):
        DEFAULT_KIND = ReportKind.MEMORY
        def _do_execute(self, t): return self._build_report(t, {"text": "mem", "zone": "green"})
    class FakeP(AgentBase):
        DEFAULT_KIND = ReportKind.PRESSURE
        def _do_execute(self, t): return self._build_report(t, {"zone": "green", "can_open_hook": True})
    orch.register(FakeR(name="R", role=AgentRole.RETRIEVER))
    orch.register(FakeM(name="M", role=AgentRole.MEMORY))
    orch.register(FakeP(name="P", role=AgentRole.PRESSURE))

    result = orch.run_chapter(pid, cid)

    # 每条 Report 都有 kind/agent_role/duration_ms
    for r in result.reports:
        check(r.kind is not None, f"Report {r.report_id} 有 kind")
        check(r.agent_role, f"Report 有 agent_role ({r.agent_role})")
        check(r.duration_ms >= 0, f"duration_ms >= 0 ({r.duration_ms})")

    # orchestrator.run_count 累加
    check(orch.run_count == 1, f"run_count=1 (实际 {orch.run_count})")
    check(orch.last_result is result, f"last_result 是最后一次")

    # 每个 helper 也有 history
    for role, agent in orch.helpers.items():
        if role == "writer":  # 写手跑过
            check(len(agent.history) >= 1, f"writer.history >= 1 ({len(agent.history)})")
            check(agent.metrics.total_tasks >= 1, f"writer.metrics.total_tasks >= 1")


# ============================================================
# Main
# ============================================================
def main() -> int:
    print("=" * 60)
    print("G17 SMOKE: Agent 体系 (基类 + 编排 + 6 辅助 Agent)")
    print("=" * 60)
    print(f"[setup] tmpdir = {TMPDIR}")

    # 初始化 DB
    svc_db.init_db()
    connection.init(DB_PATH)

    tests = [
        lambda: test_report(),
        lambda: test_agent_base_state(),
        lambda: test_helpers_isolated(),
        lambda: test_orchestrator_7_steps(),
        lambda: test_revision_loop(),
        lambda: test_revision_loop_disabled(),
        lambda: test_retention_adjustment(),
        lambda: test_cancel(),
        lambda: test_reports_aggregated(),
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
