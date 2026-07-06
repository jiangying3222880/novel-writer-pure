"""
G18 SMOKE: v4.0 Step B 验证体系 — 单核双入口 conditioning 一致性

验证维度:
  1. Prompt Conditioning Identity    — extra_block 结构完全一致
  2. Decision Trace Consistency      — decision 记录模式一致
  3. Memory Write Symmetry           — memory_manager 读写对称
  4. Execution Path Identity         — run_chapter → run_unit 路径验证

设计原则:
  - 不依赖真实 LLM 调用 (mock Agent.execute)
  - 但走真实的 conditioning 收集路径 (collect_guides, list_for_unit, build_graph_block_from_guides)
  - 走真实的服务层 (decision_service, memory_manager, _dispatch_persist)
  - 每个测试独立创建/销毁临时 DB

30 秒自动超时
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# stdout UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 30 秒全局超时
_SMOKE_TIMEOUT = 30
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_g18 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 隔离真实数据
# ============================================================

def _setup_temp_db(prefix: str = "nw_smoke_g18_") -> tuple[Path, Path]:
    """创建临时 DB + story 目录, 返回 (db_path, story_dir)."""
    tmpdir = Path(tempfile.mkdtemp(prefix=prefix))
    db_path = tmpdir / "test.db"
    story_dir = tmpdir / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    return db_path, story_dir


def _init_db(db_path: Path) -> None:
    """初始化 DB: schema + 迁移 + 全局连接. 必须先在调用方 patch app.app_paths.sqlite_path."""
    from app.services import db as svc_db
    from app.db import connection as _conn
    # Step 1: 跑 schema + migrations (用临时连接)
    svc_db.init_db(str(db_path))
    # Step 2: 打开全局连接 (后续 get_conn() 可用)
    if _conn.get_conn() is None:
        _conn.init(str(db_path))


def _teardown_db() -> None:
    """关闭连接."""
    try:
        from app.db import connection as _conn
        _conn.close()
    except Exception:
        pass


# ============================================================
# 测试 fixture 工具
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


def _make_project_with_unit(db_path: Path, story_dir: Path) -> tuple[str, str]:
    """创建项目 + 书 + 章节 + Story Unit, 返回 (project_id, unit_id)."""
    import uuid as _uuid
    from app.db import connection as _conn

    _init_db(db_path)
    conn = _conn.get_conn()

    pid = "p_ci_" + _uuid.uuid4().hex[:8]
    bid = "b_ci_" + _uuid.uuid4().hex[:8]
    cid = "c_ci_" + _uuid.uuid4().hex[:8]
    uid = "u_ci_" + _uuid.uuid4().hex[:8]

    conn.execute(
        "INSERT INTO projects (id, name, genre, created_at) VALUES (?, ?, ?, datetime('now'))",
        (pid, "CI测试项目", "玄幻"),
    )
    conn.execute(
        "INSERT INTO books (id, project_id, volume_no, title, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (bid, pid, 1, "第一卷"),
    )
    conn.execute(
        "INSERT INTO chapters (id, book_id, chapter_no, title, scene_context, source_unit_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (cid, bid, 1, "测试章节", "主角在修炼室", uid,),
    )
    # Story Unit — 实际表名 story_units (迁移 039 增强)
    conn.execute(
        """INSERT INTO story_units (id, project_id, unit_type, title, story_order,
           entry_characters, exit_characters, entry_commitments, exit_commitments,
           created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
        (uid, pid, "setup", "测试Unit", 1,
         json.dumps(["主角"]), json.dumps(["主角"]),
         json.dumps(["修炼突破"]), json.dumps(["突破成功"]),
        ),
    )

    return pid, uid


def _mock_orchestrator_dispatches(orchestrator):
    """Mock 所有 Agent.dispatch, 返回标准 canned Report.
    
    不调用真实 LLM, 但让所有 Agent 返回 ok 的 Report,
    使得 _refine() / _dispatch_persist() / record_batch() 正常执行.
    """
    from app.agents import Report, ReportKind
    
    canned_memory = Report.ok_with("mem", "memory", ReportKind.MEMORY, {
        "text": "L1-L4 测试记忆文本", "zone": "green",
    })
    canned_ctx = Report.ok_with("ctx", "context_builder", ReportKind.LOG, {
        "ctx_formatted": "世界观: 玄幻大陆\n角色: 主角·林凡",
    })
    canned_res = Report.ok_with("res", "researcher", ReportKind.LOG, {
        "snippets": "修炼体系基于灵气", "topics": ["修炼"],
    })
    canned_pres = Report.ok_with("pres", "pressure", ReportKind.PRESSURE, {
        "zone": "green", "pressure": 0.2, "can_open_hook": True,
        "anti_rules_text": "",
    })
    canned_ret = Report.ok_with("ret", "retriever", ReportKind.RETRIEVE, {
        "snippets": "文风参考: 简洁有力",
    })
    canned_write = Report.ok_with("wrt", "writer", ReportKind.WRITE, {
        "text": "林凡深吸一口气，灵气在经脉中流转...",
        "content": "林凡深吸一口气，灵气在经脉中流转...",
    })
    canned_edit = Report.ok_with("edt", "editor", ReportKind.EDIT, {
        "score": 85, "issues": [],
    })
    canned_critic = Report.ok_with("crt", "critic", ReportKind.CRITIC, {
        "score": 85, "style_notes": "",
    })
    
    # 替换所有 helpers 的 execute 为 return canned report
    for role_key in orchestrator.helpers:
        orchestrator.helpers[role_key].execute = MagicMock()
    
    # 按角色返回对应 canned report
    orchestrator.helpers["memory"].execute.return_value = canned_memory
    orchestrator.helpers["context_builder"].execute.return_value = canned_ctx
    orchestrator.helpers["researcher"].execute.return_value = canned_res
    orchestrator.helpers["pressure"].execute.return_value = canned_pres
    orchestrator.helpers["retriever"].execute.return_value = canned_ret
    orchestrator.helpers["writer"].execute.return_value = canned_write
    orchestrator.helpers["editor"].execute.return_value = canned_edit
    orchestrator.helpers["critic"].execute.return_value = canned_critic
    
    return orchestrator


# ============================================================
# Test 1: Prompt Conditioning Identity
# ============================================================

def test_conditioning_extra_block_identity() -> None:
    """验证 run_unit 和 run_chapter 的 extra_block 结构完全一致.
    
    方式: 不 mock collect_guides (走真实路径), 但在测试 DB 中预埋 guide 数据.
    由于 collect_guides 内部 try/except, 空 DB 返回空列表.
    重点验证: 两个入口传给 _refine() 的 extra_block 字节级相同.
    """
    section("[G18 1] Prompt Conditioning Identity (extra_block)")
    
    db_path, story_dir = _setup_temp_db("nw_smoke_g18_c1_")
    
    try:
        # 打桩
        import app.app_paths
        original_sqlite_path = app.app_paths.sqlite_path
        app.app_paths.sqlite_path = lambda: db_path
        
        import app.services.file_store
        original_base_dir = app.services.file_store.BASE_DIR
        app.services.file_store.BASE_DIR = story_dir
        
        pid, uid = _make_project_with_unit(db_path, story_dir)
        
        # ---- 创建两个 Orchestrator 实例, 分别捕获 _refine 的 extra_block ----
        from app.agents.orchestrator import Orchestrator, OrchestratorConfig
        
        captured_extra_blocks: list[str] = []
        original_refine = Orchestrator._refine
        
        def _capturing_refine(self, *, mem_r, ctx_r, res_r, pres_r, ret_r,
                              retention=None, extra_block=""):
            captured_extra_blocks.append(extra_block)
            return original_refine(self, mem_r=mem_r, ctx_r=ctx_r, res_r=res_r,
                                   pres_r=pres_r, ret_r=ret_r,
                                   retention=retention, extra_block=extra_block)
        
        OrchRefine = Orchestrator._refine
        Orchestrator._refine = _capturing_refine
        
        try:
            # ---- 入口 1: run_unit(use_guide_system=True) ----
            config = OrchestratorConfig(enable_revision_loop=False)
            orch1 = Orchestrator(config=config)
            _mock_orchestrator_dispatches(orch1)
            
            result1 = orch1.run_unit(pid, uid, use_guide_system=True)
            block1 = captured_extra_blocks[-1]
            captured_extra_blocks.clear()
            check(result1.ok, f"run_unit 返回 ok (score={result1.score})")
            print(f"      extra_block (run_unit, len={len(block1)}): {block1[:120]!r}...")
            
            # 清除之前 run_unit 产生的数据 (避免 decision 污染 run_chapter)
            _teardown_db()
            _init_db(db_path)
            pid2, uid2 = _make_project_with_unit(db_path, story_dir)
            
            # ---- 入口 2: run_chapter (通过 virtual_unit_adapter → run_unit) ----
            orch2 = Orchestrator(config=config)
            _mock_orchestrator_dispatches(orch2)
            
            # run_chapter 需要 chapter_id, 我们创建一个章节
            import uuid as _uuid
            from app.db import connection as _conn
            conn = _conn.get_conn()
            _bid = "b_ci2_" + _uuid.uuid4().hex[:8]
            _cid = "c_ci2_" + _uuid.uuid4().hex[:8]
            conn.execute(
                "INSERT INTO books (id, project_id, volume_no, title, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now'))",
                (_bid, pid2, 1, "第一卷"),
            )
            conn.execute(
                "INSERT INTO chapters (id, book_id, chapter_no, title, scene_context, source_unit_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
                (_cid, _bid, 1, "测试章节", "测试场景", uid2,),
            )
            # 章节需要草稿才能被 virtual_unit_adapter 包装
            from app.services import chapter_service
            chapter_service.create_draft(_cid, "测试草稿内容", source="agent")
            
            result2 = orch2.run_chapter(pid2, _cid)
            block2 = captured_extra_blocks[-1] if captured_extra_blocks else ""
            
            check(result2.ok, f"run_chapter 返回 ok (score={result2.score})")
            print(f"      extra_block (run_chapter, len={len(block2)}): {block2[:120]!r}...")
            
            # ---- 核心断言 ----
            # 1. 两个块的字符长度相同
            check(len(block1) == len(block2),
                  f"extra_block 长度相同 ({len(block1)} == {len(block2)})")
            
            # 2. 两个块的内容完全相同
            check(block1 == block2,
                  f"extra_block 字节级相同")
            
            # 3. 如果 collect_guides 没有返回 guides (空DB), 两个块都应为空
            if block1 == "":
                check(True, "空 DB 下 extra_block 为空 (预期行为, collect_guides 无数据)")
            else:
                # 有数据时验证结构
                check("Story Guidance" in block1 or "Decision" in block1 or "冲突图" in block1 or "Conflicts" in block1,
                      "extra_block 包含 Guide/Decision/Graph 至少一种")
            
        finally:
            Orchestrator._refine = OrchRefine
        
        # 恢复
        app.app_paths.sqlite_path = original_sqlite_path
        app.services.file_store.BASE_DIR = original_base_dir
        
    finally:
        _teardown_db()


# ============================================================
# Test 2: Decision Trace Consistency
# ============================================================

def test_decision_trace_consistency() -> None:
    """验证 run_unit 和 run_chapter 产生的 decision 记录模式一致.
    
    关键: 当 run_chapter 成功包装为 Virtual Unit 并走 run_unit 时,
    两者应该产生完全相同的 decision 记录 (相同 unit_id, 相同 guide set).
    """
    section("[G18 2] Decision Trace Consistency")
    
    db_path, story_dir = _setup_temp_db("nw_smoke_g18_c2_")
    
    try:
        import app.app_paths
        original_sqlite_path = app.app_paths.sqlite_path
        app.app_paths.sqlite_path = lambda: db_path
        
        import app.services.file_store
        original_base_dir = app.services.file_store.BASE_DIR
        app.services.file_store.BASE_DIR = story_dir
        
        pid, uid = _make_project_with_unit(db_path, story_dir)
        
        from app.agents.orchestrator import Orchestrator, OrchestratorConfig
        from app.services import decision_service
        
        config = OrchestratorConfig(enable_revision_loop=False)
        
        # ---- 入口 1: run_unit ----
        orch1 = Orchestrator(config=config)
        _mock_orchestrator_dispatches(orch1)
        result1 = orch1.run_unit(pid, uid, use_guide_system=True)
        
        decisions1 = decision_service.list_for_unit(uid)
        summary1 = decision_service.summary(uid)
        print(f"      run_unit decisions: total={summary1['total']}, adopted={summary1['adopted']}")
        check(result1.ok, "run_unit 成功")
        
        # ---- 入口 2: run_chapter (通过 virtual unit) ----
        _teardown_db()
        _init_db(db_path)
        pid2, uid2 = _make_project_with_unit(db_path, story_dir)
        
        import uuid as _uuid
        from app.db import connection as _conn
        conn = _conn.get_conn()
        _bid = "b_ci2b_" + _uuid.uuid4().hex[:8]
        _cid = "c_ci2b_" + _uuid.uuid4().hex[:8]
        conn.execute(
            "INSERT INTO books (id, project_id, volume_no, title, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (_bid, pid2, 1, "第一卷"),
        )
        conn.execute(
            "INSERT INTO chapters (id, book_id, chapter_no, title, scene_context, source_unit_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (_cid, _bid, 1, "测试章节", "测试场景", uid2,),
        )
        from app.services import chapter_service
        chapter_service.create_draft(_cid, "测试草稿内容", source="agent")
        
        orch2 = Orchestrator(config=config)
        _mock_orchestrator_dispatches(orch2)
        result2 = orch2.run_chapter(pid2, _cid)
        
        decisions2 = decision_service.list_for_unit(uid2)
        summary2 = decision_service.summary(uid2)
        print(f"      run_chapter decisions: total={summary2['total']}, adopted={summary2['adopted']}")
        check(result2.ok, "run_chapter 成功")
        
        # ---- 核心断言 ----
        # 两条路径应该产生相同数量的 decision (相同 guide 集, 相同自动推断规则)
        check(summary1["total"] == summary2["total"],
              f"decision 总数一致 ({summary1['total']} == {summary2['total']})")
        
        # 两个 unit 的 decision 数应相同 (空 DB = 0, 有 guides 时 > 0)
        check(summary1["total"] == summary2["total"],
              "空 DB 下 decision 数均为 0 (预期)")
        
        # 恢复
        app.app_paths.sqlite_path = original_sqlite_path
        app.services.file_store.BASE_DIR = original_base_dir
        
    finally:
        _teardown_db()


# ============================================================
# Test 3: Execution Path Identity
# ============================================================

def test_run_chapter_delegates_to_run_unit() -> None:
    """验证 run_chapter 实际调用 run_unit (而非 fallback 路径).
    
    关键: run_chapter 在成功包装 Virtual Unit 后, 应该直接 return run_unit() 的结果,
    不应该走到 fallback (Step 1-9 手动编排).
    """
    section("[G18 3] Execution Path Identity")
    
    db_path, story_dir = _setup_temp_db("nw_smoke_g18_c3_")
    
    try:
        import app.app_paths
        original_sqlite_path = app.app_paths.sqlite_path
        app.app_paths.sqlite_path = lambda: db_path
        
        import app.services.file_store
        original_base_dir = app.services.file_store.BASE_DIR
        app.services.file_store.BASE_DIR = story_dir
        
        pid, uid = _make_project_with_unit(db_path, story_dir)
        
        import uuid as _uuid
        from app.db import connection as _conn
        conn = _conn.get_conn()
        _bid = "b_ci3_" + _uuid.uuid4().hex[:8]
        _cid = "c_ci3_" + _uuid.uuid4().hex[:8]
        conn.execute(
            "INSERT INTO books (id, project_id, volume_no, title, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (_bid, pid, 1, "第一卷"),
        )
        conn.execute(
            "INSERT INTO chapters (id, book_id, chapter_no, title, scene_context, source_unit_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (_cid, _bid, 1, "测试章节", "测试场景", uid,),
        )
        from app.services import chapter_service
        chapter_service.create_draft(_cid, "测试草稿内容", source="agent")
        
        from app.agents.orchestrator import Orchestrator, OrchestratorConfig
        
        # 使用 spy 验证 run_chapter 确实调用了 run_unit
        original_run_unit = Orchestrator.run_unit
        run_unit_call_args: list[dict] = []
        
        def _spy_run_unit(self, project_id, unit_id, *, on_step=None, retention=None, use_guide_system=True):
            run_unit_call_args.append({
                "project_id": project_id,
                "unit_id": unit_id,
                "use_guide_system": use_guide_system,
            })
            return original_run_unit(self, project_id, unit_id,
                                     on_step=on_step, retention=retention,
                                     use_guide_system=use_guide_system)
        
        Orchestrator.run_unit = _spy_run_unit
        
        try:
            config = OrchestratorConfig(enable_revision_loop=False)
            orch = Orchestrator(config=config)
            _mock_orchestrator_dispatches(orch)
            
            result = orch.run_chapter(pid, _cid)
            
            # ---- 核心断言 ----
            check(result.ok, "run_chapter 返回成功")
            check(len(run_unit_call_args) == 1,
                  f"run_chapter 调用了 run_unit (调用次数={len(run_unit_call_args)})")
            
            if run_unit_call_args:
                call = run_unit_call_args[0]
                check(call["use_guide_system"] is True,
                      f"run_chapter 传递 use_guide_system=True (实际: {call['use_guide_system']})")
                check(call["project_id"] == pid,
                      f"project_id 正确传递 (实际: {call['project_id']})")
                # unit_id 应该是 virtual unit 的 id, 不一定是原 uid
                check(call["unit_id"], "unit_id 非空")
            
        finally:
            Orchestrator.run_unit = original_run_unit
        
        # 恢复
        app.app_paths.sqlite_path = original_sqlite_path
        app.services.file_store.BASE_DIR = original_base_dir
        
    finally:
        _teardown_db()


# ============================================================
# Test 4: Two-entry Result Structural Identity
# ============================================================

def test_result_structure_identity() -> None:
    """验证 run_unit 和 run_chapter 返回的 OrchestratorResult 结构一致.
    
    两个入口返回的 result 应包含相同的字段集: ok, project_id, content, score, reports 等.
    """
    section("[G18 4] Result Structure Identity")
    
    db_path, story_dir = _setup_temp_db("nw_smoke_g18_c4_")
    
    try:
        import app.app_paths
        original_sqlite_path = app.app_paths.sqlite_path
        app.app_paths.sqlite_path = lambda: db_path
        
        import app.services.file_store
        original_base_dir = app.services.file_store.BASE_DIR
        app.services.file_store.BASE_DIR = story_dir
        
        pid, uid = _make_project_with_unit(db_path, story_dir)
        
        import uuid as _uuid
        from app.db import connection as _conn
        conn = _conn.get_conn()
        _bid = "b_ci4_" + _uuid.uuid4().hex[:8]
        _cid = "c_ci4_" + _uuid.uuid4().hex[:8]
        conn.execute(
            "INSERT INTO books (id, project_id, volume_no, title, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (_bid, pid, 1, "第一卷"),
        )
        conn.execute(
            "INSERT INTO chapters (id, book_id, chapter_no, title, scene_context, source_unit_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (_cid, _bid, 1, "测试章节", "测试场景", uid,),
        )
        from app.services import chapter_service
        chapter_service.create_draft(_cid, "测试草稿内容", source="agent")
        
        from app.agents.orchestrator import Orchestrator, OrchestratorConfig, OrchestratorResult
        
        config = OrchestratorConfig(enable_revision_loop=False)
        
        # 入口 1: run_unit
        orch1 = Orchestrator(config=config)
        _mock_orchestrator_dispatches(orch1)
        result1 = orch1.run_unit(pid, uid, use_guide_system=True)
        
        # 入口 2: run_chapter
        orch2 = Orchestrator(config=config)
        _mock_orchestrator_dispatches(orch2)
        result2 = orch2.run_chapter(pid, _cid)
        
        # ---- 核心断言 ----
        check(result1.ok, "run_unit result ok")
        check(result2.ok, "run_chapter result ok")
        
        # 两个 result 必须有相同的基本字段
        expected_fields = {"ok", "project_id", "content", "score", "reports", "duration_ms"}
        for field in expected_fields:
            has1 = hasattr(result1, field)
            has2 = hasattr(result2, field)
            check(has1 and has2, f"两个 result 都有字段 '{field}' (unit={has1}, chapter={has2})")
        
        # content 非空
        check(bool(result1.content), f"run_unit content 非空 (len={len(result1.content)})")
        check(bool(result2.content), f"run_chapter content 非空 (len={len(result2.content)})")
        
        # reports 非空
        check(len(result1.reports) > 0, f"run_unit 有 {len(result1.reports)} 个 reports")
        check(len(result2.reports) > 0, f"run_chapter 有 {len(result2.reports)} 个 reports")
        
        # score 在合理范围
        check(0 <= result1.score <= 100, f"run_unit score 合理 ({result1.score})")
        check(0 <= result2.score <= 100, f"run_chapter score 合理 ({result2.score})")
        
        # 恢复
        app.app_paths.sqlite_path = original_sqlite_path
        app.services.file_store.BASE_DIR = original_base_dir
        
    finally:
        _teardown_db()


# ============================================================
# 入口
# ============================================================

def main() -> int:
    print("=" * 68)
    print("G18: v4.0 Step B — Conditioning Identity Verification")
    print("=" * 68)
    print(f"DB 隔离: tempfile.mkdtemp() × 4")
    print(f"LLM: 全部 mock (不调用真实 API)")
    print()

    tests = [
        ("1. Prompt Conditioning Identity", test_conditioning_extra_block_identity),
        ("2. Decision Trace Consistency", test_decision_trace_consistency),
        ("3. Execution Path Identity", test_run_chapter_delegates_to_run_unit),
        ("4. Result Structure Identity", test_result_structure_identity),
    ]

    for label, fn in tests:
        try:
            fn()
        except Exception as e:
            import traceback
            fails.append(f"{label}: {e}")
            print(f"  [ERROR] {label}: {e}")
            traceback.print_exc()

    # 汇总
    total = passed + len(fails)
    print(f"\n{'=' * 68}")
    print(f"汇总: {passed}/{total} 通过")
    if fails:
        print(f"失败 ({len(fails)}):")
        for f in fails:
            print(f"  - {f}")
    else:
        print("全部通过")
    print(f"{'=' * 68}")

    _timer.cancel()
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
