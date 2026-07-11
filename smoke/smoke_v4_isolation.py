"""
smoke_v4_isolation — Agent 基础测试

验证 Agent 基类、Report、Orchestrator 基础功能。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.base import AgentBase, AgentRole, AgentState, AgentMetrics
from app.agents.report import Report, ReportKind
from app.agents.orchestrator import Orchestrator, OrchestratorConfig


def main():
    print("=" * 60)
    print("smoke_v4_isolation — Agent 基础测试")
    print("=" * 60)

    # 1. AgentRole 枚举
    assert AgentRole.WRITER.value == "writer"
    assert AgentRole.CRITIC.value == "critic"
    print("1. AgentRole enum: OK")

    # 2. AgentState 枚举
    assert AgentState.IDLE.value == "idle"
    assert AgentState.WORKING.value == "working"
    print("2. AgentState enum: OK")

    # 3. AgentMetrics
    m = AgentMetrics()
    m.total_tasks = 5
    m.total_ok = 4
    m.total_err = 1
    assert m.success_rate == 0.8
    print("3. AgentMetrics: OK")

    # 4. Report 创建
    r = Report(
        agent_id="test_agent",
        agent_role="writer",
        kind=ReportKind.WRITE,
        ok=True,
        data={"content": "test"},
    )
    assert r.ok
    assert r.to_dict()["ok"] is True
    print("4. Report: OK")

    # 5. Report 失败
    r_fail = Report.fail("test", "writer", ReportKind.LOG, "test error")
    assert not r_fail.ok
    assert r_fail.error == "test error"
    print("5. Report.fail: OK")

    # 6. Orchestrator 实例化
    orch = Orchestrator()
    assert hasattr(orch, "run_unit"), "Orchestrator 缺少 run_unit"
    assert hasattr(orch, "review_causality"), "Orchestrator 缺少 review_causality"
    assert hasattr(orch, "update_causal_graph"), "Orchestrator 缺少 update_causal_graph"
    print("6. Orchestrator: OK")

    # 7. OrchestratorConfig
    cfg = OrchestratorConfig(enable_revision_loop=False)
    assert cfg.enable_revision_loop is False
    print("7. OrchestratorConfig: OK")

    # 8. AgentBase 子类检查
    assert AgentRole.WRITER in AgentRole
    assert len(AgentRole) >= 8
    print(f"8. AgentBase roles: {len(AgentRole)} roles defined")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
