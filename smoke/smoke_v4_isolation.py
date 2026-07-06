"""
smoke_v4_isolation — Agent 隔离测试

验证 Agent 在隔离上下文中执行，不互相干扰。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.base import AgentBase, AgentTask, AgentReport
from app.agents.isolation import IsolationKernel
from app.agents.writer import WriterAgent
from app.agents.reader import ReaderAgent
from app.agents.critic import CriticAgent
from app.agents.orchestrator import OrchestratorV4


def main():
    print("=" * 60)
    print("smoke_v4_isolation — Agent 隔离测试")
    print("=" * 60)

    # 1. AgentBase 基础测试
    writer = WriterAgent()
    task = AgentTask(unit_id="test", context={"refined_prompt": "Write a scene"})
    report = writer.execute(task)
    assert report.ok, f"Writer failed: {report.error}"
    print(f"1. WriterAgent: OK (role={report.agent_role})")

    # 2. IsolationKernel 测试
    kernel = IsolationKernel(WriterAgent())
    report2 = kernel.run(task)
    assert report2.ok, f"Kernel failed: {report2.error}"
    print(f"2. IsolationKernel: OK (agent_id={report2.agent_id})")

    # 3. 多 Agent 隔离测试
    agents = [WriterAgent(), ReaderAgent(), CriticAgent()]
    kernels = [IsolationKernel(a) for a in agents]

    reports = []
    for k in kernels:
        r = k.run(task)
        reports.append(r)

    assert all(r.ok for r in reports), "Some agents failed"
    print(f"3. Multi-agent isolation: OK ({len(reports)} agents)")

    # 4. OrchestratorV4 测试
    orch = OrchestratorV4()
    result = orch.run("test", state=None)
    assert result.get("ok"), "Orchestrator failed"
    print(f"4. OrchestratorV4: OK (score={result.get('score')})")

    # 5. 指标追踪测试
    metrics = orch.get_metrics()
    assert "writer" in metrics
    assert metrics["writer"]["total_runs"] > 0
    print(f"5. Metrics tracking: OK (writer runs={metrics['writer']['total_runs']})")

    # 6. 历史记录测试
    history = kernel.get_history()
    assert len(history) > 0
    print(f"6. History tracking: OK ({len(history)} reports)")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
