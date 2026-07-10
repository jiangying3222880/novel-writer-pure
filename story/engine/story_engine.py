"""
StoryEngine — Story OS 执行引擎

串联完整管线: State → Guide → Decision → Prompt → Agents → Write → Evaluate → Persist.

v4.3: 从 Orchestrator 迁入完整执行管线，成为唯一执行引擎。
Orchestrator 缩减为薄调用层。
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from story.state.story_state import StoryState
from story.state.state_bridge import StateBridge
from story.state.apply_event import apply_event, apply_events, rebuild_state
from story.guide.collector import collect_signals, signals_summary
from story.decision.engine import decide
from story.decision.strategy import StrategyResult
from story.prompt.suc_builder import build_suc, StoryUnderstandingContext
from story.prompt.compiler import compile, CompiledPrompt

_logger = logging.getLogger("NovelWriter.story.engine")


# ============================================================
# 结果数据结构
# ============================================================

@dataclass
class EngineResult:
    """StoryEngine 执行结果."""
    ok: bool = True
    project_id: str = ""
    unit_id: str = ""
    content: str = ""
    score: int = 0
    revisions: int = 0
    refined_prompt: str = ""
    signals: list = field(default_factory=list)
    decision: Optional[StrategyResult] = None
    suc: Optional[StoryUnderstandingContext] = None
    prompt: Optional[CompiledPrompt] = None
    duration_ms: int = 0
    error: str = ""


# ============================================================
# StoryEngine
# ============================================================

class StoryEngine:
    """Story OS 执行引擎 — 串联完整管线.

    管线步骤:
      A. 准备: 加载 State
      B. Guide 收集: collect_signals → decide → build_suc → compile
      C. Agent 研究: Memory/Context/Researcher/Pressure/Retriever
      D. Prompt 精炼: 合并 Agent 输出 + Guide + KB
      E. 因果审查: 检查 cause/effect 衔接
      F. 写作: Writer Agent
      G. 评估循环: Editor + Critic → 改稿
      H. 持久化: 段落 + 一致性扫描
      I. 后处理: Decision 记录 + 影响分析 + 因果图更新
      J. UI 通知: UIStateBridge
    """

    def __init__(self) -> None:
        self._event_log: list[dict[str, Any]] = []

    # ================================================================
    # 主入口
    # ================================================================

    def run_unit(
        self,
        project_id: str,
        unit_id: str,
        *,
        on_step: Optional[Any] = None,
        use_guide_system: bool = True,
        max_revisions: int = 2,
        pass_score: int = 70,
        enable_revision_loop: bool = True,
    ) -> EngineResult:
        """完整执行管线.

        Args:
            project_id: 项目 ID
            unit_id: 单元 ID
            on_step: 步骤回调 (step_no, label)
            use_guide_system: 是否启用 Guide 系统
            max_revisions: 最大改稿轮数
            pass_score: 及格分
            enable_revision_loop: 是否启用改稿循环

        Returns:
            EngineResult
        """
        t0 = time.time()
        old_state = None

        def _emit(step: int, label: str) -> None:
            if on_step:
                try:
                    on_step(step, label)
                except Exception:
                    pass

        try:
            # ---- Phase A: 准备 ----
            _emit(0, "加载状态")
            old_state = self._load_state(project_id, unit_id)

            # ---- Phase B: Guide 收集 (4 步管线) ----
            _emit(1, "Guide 收集")
            signals = collect_signals(unit_id, project_id=project_id)
            decision = decide(signals, story_state=old_state)
            suc = build_suc(old_state, signals=signals)
            prompt = compile(suc, decision)

            # ---- Phase C: 5-Agent 研究管线 ----
            _emit(2, "Agent 研究")
            agent_results = self._run_agents(project_id, unit_id)

            # ---- Phase D: Prompt 精炼 ----
            _emit(3, "精炼提示")
            guide_block = ""
            if use_guide_system:
                guide_block = self._build_guide_block(unit_id, project_id)
            refined = self._refine(
                agent_results=agent_results,
                extra_block=guide_block,
            )

            # ---- Phase E: 因果审查 ----
            _emit(4, "因果审查")
            causal_review = self._review_causality(project_id, unit_id)

            # ---- Phase F: 写作 ----
            _emit(5, "写作")
            write_result = self._write(project_id, unit_id, refined)
            if not write_result.get("ok"):
                return self._fail(project_id, unit_id, f"写作失败: {write_result.get('error')}", t0)

            # ---- Phase G: 评估循环 ----
            _emit(6, "评估")
            score, revisions, final_content = self._evaluate_and_revise(
                project_id, unit_id, write_result, refined,
                max_revisions=max_revisions,
                pass_score=pass_score,
                enable_revision_loop=enable_revision_loop,
            )

            # ---- Phase H: 持久化 ----
            _emit(7, "落库")
            self._persist(project_id, unit_id, final_content, score)

            # ---- Phase I: 后处理 ----
            _emit(8, "后处理")
            self._post_process(project_id, unit_id, signals, final_content)

            # ---- Phase J: UI 通知 ----
            _emit(9, "通知 UI")
            self._notify_ui(project_id, unit_id, old_state)

            duration_ms = int((time.time() - t0) * 1000)
            _logger.info(
                "[engine] run_unit 完成: project=%s unit=%s score=%d revisions=%d %dms",
                project_id, unit_id[:8], score, revisions, duration_ms,
            )

            return EngineResult(
                ok=True,
                project_id=project_id,
                unit_id=unit_id,
                content=final_content,
                score=score,
                revisions=revisions,
                refined_prompt=refined,
                signals=signals,
                decision=decision,
                suc=suc,
                prompt=prompt,
                duration_ms=duration_ms,
            )

        except Exception as e:
            _logger.exception("[engine] run_unit 异常")
            return self._fail(project_id, unit_id, f"{type(e).__name__}: {e}", t0)

    # ================================================================
    # Phase A: 加载状态
    # ================================================================

    def _load_state(self, project_id: str, unit_id: str) -> StoryState:
        """从 DB 加载 StoryState."""
        from app.services import story_unit_service_v2 as unit_svc
        unit = unit_svc.get(unit_id)
        return StateBridge.from_unit_v2(unit)

    # ================================================================
    # Phase C: 5-Agent 研究管线
    # ================================================================

    def _run_agents(self, project_id: str, unit_id: str) -> dict[str, Any]:
        """运行 5 个研究 Agent，返回各自的结果.

        通过 Orchestrator 的 dispatch 机制执行，但由 StoryEngine 编排流程.
        """
        from app.agents.orchestrator import Orchestrator, OrchestratorConfig, AgentRole

        orch = Orchestrator(config=OrchestratorConfig(enable_revision_loop=False))
        results = {}

        agent_steps = [
            (AgentRole.MEMORY, 1, "拼装记忆"),
            (AgentRole.CONTEXT_BUILDER, 2, "上下文构建"),
            (AgentRole.RESEARCHER, 3, "资料研究"),
            (AgentRole.PRESSURE, 4, "压力观察"),
            (AgentRole.RETRIEVER, 5, "知识检索"),
        ]

        for role, step, label in agent_steps:
            try:
                report = orch._dispatch(role, project_id, unit_id, step=step)
                results[role.value] = report
            except Exception as e:
                _logger.warning("[engine] Agent %s 失败: %s", role.value, e)
                # 创建空 report 兼容
                from app.agents.report import Report, ReportKind
                results[role.value] = Report(
                    agent_id="", agent_role=role.value, kind=ReportKind.RESULT,
                    ok=False, error=str(e),
                )

        return results

    # ================================================================
    # Phase D: Prompt 精炼
    # ================================================================

    def _build_guide_block(self, unit_id: str, project_id: str) -> str:
        """构建 Guide + Decision + 冲突图 prompt 块."""
        parts = []

        # Guide
        try:
            from app.core.types import collect_guides
            guides = collect_guides(unit_id, project_id=project_id)
            if guides:
                block = "\n\n## Story Guidance (建议, 非强制)\n" + \
                    "\n".join(g.to_prompt_block() for g in guides[:10])
                parts.append(block)
        except Exception as e:
            _logger.warning("[engine] collect_guides 失败: %s", e)

        # Decision
        try:
            from app.services.decision_service import list_for_unit, build_decisions_block
            prev_decisions = list_for_unit(unit_id)
            if prev_decisions:
                parts.append("\n\n" + build_decisions_block(prev_decisions))
        except Exception as e:
            _logger.warning("[engine] Decision 收集失败: %s", e)

        # 冲突图
        try:
            from app.services.guide_graph import build_graph_block_from_guides
            from app.core.types import collect_guides
            guides = collect_guides(unit_id, project_id=project_id)
            graph = build_graph_block_from_guides(guides).strip()
            if graph:
                parts.append("\n\n" + graph)
        except Exception as e:
            _logger.warning("[engine] 冲突图失败: %s", e)

        return "".join(parts)

    def _refine(
        self,
        agent_results: dict[str, Any],
        extra_block: str = "",
    ) -> str:
        """合并 Agent 输出 + Guide + KB 为精炼提示.

        复用 Orchestrator 的 _refine 方法，传入 Agent 报告.
        """
        from app.agents.orchestrator import Orchestrator, OrchestratorConfig
        from app.agents.report import Report, ReportKind

        orch = Orchestrator(config=OrchestratorConfig(enable_revision_loop=False))

        # 构造 Report 对象: 如果 agent_results 中没有对应 key，用空 Report
        def _get_report(key: str) -> Report:
            r = agent_results.get(key)
            if r is not None:
                return r
            return Report(
                agent_id="", agent_role=key, kind=ReportKind.RESULT,
                ok=False, error="agent not run",
            )

        mem_r = _get_report("memory")
        ctx_r = _get_report("context_builder")
        res_r = _get_report("researcher")
        pw_r = _get_report("pressure")
        ret_r = _get_report("retriever")

        refined, _ = orch._refine(
            mem_r=mem_r, ctx_r=ctx_r, res_r=res_r,
            pres_r=pw_r, ret_r=ret_r,
            extra_block=extra_block,
        )
        return refined

    # ================================================================
    # Phase E: 因果审查
    # ================================================================

    def _review_causality(self, project_id: str, unit_id: str) -> dict:
        """因果审查: 检查 cause/effect 衔接."""
        from app.agents.orchestrator import Orchestrator, OrchestratorConfig

        orch = Orchestrator(config=OrchestratorConfig(enable_revision_loop=False))
        try:
            return orch.review_causality(project_id, unit_id)
        except Exception as e:
            _logger.warning("[engine] 因果审查失败: %s", e)
            return {"ok": False, "error": str(e), "issues": []}

    # ================================================================
    # Phase F: 写作
    # ================================================================

    def _write(self, project_id: str, unit_id: str, refined_prompt: str) -> dict:
        """调用 Writer Agent 写作."""
        from app.agents.orchestrator import Orchestrator, OrchestratorConfig, AgentRole

        orch = Orchestrator(config=OrchestratorConfig(enable_revision_loop=False))
        try:
            report = orch._dispatch(
                AgentRole.WRITER, project_id, unit_id,
                step=7, extra={"refined_prompt": refined_prompt},
            )
            return {"ok": report.ok, "data": report.data, "error": report.error}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ================================================================
    # Phase G: 评估循环
    # ================================================================

    def _evaluate_and_revise(
        self,
        project_id: str,
        unit_id: str,
        write_result: dict,
        refined_prompt: str,
        *,
        max_revisions: int = 2,
        pass_score: int = 70,
        enable_revision_loop: bool = True,
    ) -> tuple[int, int, str]:
        """评估 + 改稿循环. 返回 (score, revisions, final_content)."""
        from app.agents.orchestrator import Orchestrator, OrchestratorConfig, AgentRole

        orch = Orchestrator(config=OrchestratorConfig(enable_revision_loop=False))
        content = write_result.get("data", {}).get("text", "") if isinstance(write_result.get("data"), dict) else ""
        score = 0
        revisions = 0

        # 首次评估
        ed_r = orch._dispatch(AgentRole.EDITOR, project_id, unit_id, step=8,
                              extra={"content": content})
        crit_r = orch._dispatch(AgentRole.CRITIC, project_id, unit_id, step=8,
                                extra={"content": content})
        score = orch._aggregate_score(ed_r, crit_r)

        # 改稿循环
        while (score < pass_score
               and revisions < max_revisions
               and enable_revision_loop):
            revisions += 1
            _logger.info("[engine] 改稿第%d轮 (score=%d)", revisions, score)
            refine_feedback = orch._build_refine_from_feedback(ed_r, crit_r)
            write_result = self._write(project_id, unit_id, refine_feedback)
            if not write_result.get("ok"):
                break
            content = write_result.get("data", {}).get("text", "") if isinstance(write_result.get("data"), dict) else ""
            ed_r = orch._dispatch(AgentRole.EDITOR, project_id, unit_id, step=8,
                                  extra={"content": content})
            crit_r = orch._dispatch(AgentRole.CRITIC, project_id, unit_id, step=8,
                                    extra={"content": content})
            score = orch._aggregate_score(ed_r, crit_r)

        return score, revisions, content

    # ================================================================
    # Phase H: 持久化
    # ================================================================

    def _persist(self, project_id: str, unit_id: str, content: str, score: int) -> None:
        """持久化: 写入段落."""
        try:
            from app.services import unit_paragraph_service as para_svc
            para_svc.replace_full_text(unit_id, project_id, content)
            _logger.info("[engine] 段落已持久化: unit=%s", unit_id[:8])
        except Exception as e:
            _logger.warning("[engine] 段落持久化失败: %s", e)

    # ================================================================
    # Phase I: 后处理
    # ================================================================

    def _post_process(
        self,
        project_id: str,
        unit_id: str,
        signals: list,
        content: str,
    ) -> None:
        """后处理: Decision 记录 + 影响分析 + 因果图更新."""
        # Decision 记录
        try:
            from app.core.types import collect_guides
            guides = collect_guides(unit_id, project_id=project_id)
            if guides:
                from app.services.decision_service import record_batch
                record_batch(unit_id, guides, project_id=project_id, step_no=0)
        except Exception as e:
            _logger.warning("[engine] Decision 记录失败: %s", e)

        # 影响分析
        try:
            from app.services.story_compiler import analyze_impact
            impact = analyze_impact(unit_id)
            if impact.has_impact:
                _logger.info("[engine] Impact: %d affected units", len(impact.impacted_units))
        except Exception as e:
            _logger.warning("[engine] 影响分析失败: %s", e)

        # 因果图更新
        try:
            from app.agents.orchestrator import Orchestrator, OrchestratorConfig
            orch = Orchestrator(config=OrchestratorConfig(enable_revision_loop=False))
            orch.update_causal_graph(project_id, unit_id, content)
        except Exception as e:
            _logger.warning("[engine] 因果图更新失败: %s", e)

    # ================================================================
    # Phase J: UI 通知
    # ================================================================

    def _notify_ui(self, project_id: str, unit_id: str, old_state: Optional[StoryState]) -> None:
        """通过 UIStateBridge 通知 UI 状态变更."""
        try:
            from story.ui.bridge.state_bridge import get_bridge
            new_state = self._load_state(project_id, unit_id)
            diff = StateBridge.diff(old_state, new_state) if old_state else None
            bridge = get_bridge()
            bridge.on_state_change(old_state, new_state, diff)
            bridge.on_unit_completed(project_id, unit_id, {
                "strategy": "v4_pipeline",
                "signal_count": 0,
                "prompt_tokens": 0,
            })
        except Exception as e:
            _logger.warning("[engine] UI 通知失败: %s", e)

    # ================================================================
    # 辅助
    # ================================================================

    def _fail(self, project_id: str, unit_id: str, error: str, t0: float) -> EngineResult:
        """构造失败结果."""
        return EngineResult(
            ok=False,
            project_id=project_id,
            unit_id=unit_id,
            error=error,
            duration_ms=int((time.time() - t0) * 1000),
        )

    # ---- 兼容旧接口 ----

    def apply_event(self, state: StoryState, event: dict[str, Any]) -> StoryState:
        new_state = apply_event(state, event)
        self._event_log.append(event)
        return new_state

    def rebuild_state(self, initial: StoryState, events: list[dict[str, Any]]) -> StoryState:
        result = rebuild_state(initial, events)
        self._event_log.extend(events)
        return result

    @property
    def event_count(self) -> int:
        return len(self._event_log)

    def reset_log(self) -> None:
        self._event_log.clear()
