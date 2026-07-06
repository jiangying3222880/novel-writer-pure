"""
story_engine — Facade 入口: run_unit() 串联 State → Guide → Decision → Prompt.

v4 顶层入口,提供给 app/agents/orchestrator.py 在 Week 4 集成时调用.
单测可在 StoryState + mock signals 下不依赖 LLM 直接跑通.
"""
from __future__ import annotations
import logging
from typing import Any, Optional

from story.state.story_state import StoryState
from story.state.apply_event import apply_event, apply_events, rebuild_state
from story.guide.collector import collect_signals, signals_summary
from story.decision.engine import decide
from story.decision.strategy import StrategyResult
from story.prompt.suc_builder import build_suc, StoryUnderstandingContext
from story.prompt.compiler import compile, CompiledPrompt

_logger = logging.getLogger("NovelWriter.story.engine")


class StoryEngine:
    """Story OS Facade — 串联 v4 全链路, 不持有状态.

    状态通过参数显式传入,符合 SSOT 原则.
    """

    def __init__(self) -> None:
        self._event_log: list[dict[str, Any]] = []

    # ---- Event 应用 ----

    def apply_event(self, state: StoryState, event: dict[str, Any]) -> StoryState:
        new_state = apply_event(state, event)
        self._event_log.append(event)
        return new_state

    def rebuild_state(self, initial: StoryState, events: list[dict[str, Any]]) -> StoryState:
        """从初始 state + 事件列表完全重建."""
        result = rebuild_state(initial, events)
        self._event_log.extend(events)
        return result

    # ---- 全链路 facade ----

    def run_unit(
        self,
        state: StoryState,
        *,
        signals: Optional[list] = None,
        **prompt_kwargs: Any,
    ) -> dict[str, Any]:
        """运行一个 StoryUnit 的全链路: State → Signals → Decision → SUC → Prompt.

        Args:
            state: 当前 StoryState (不可变)
            signals: 可选, 外部注入的 Guide signals; 不传则用 collect_signals()
            **prompt_kwargs: 透传给 compile() 的额外参数 (温度/约束/优先级等)

        Returns:
            dict 包含:
              - state: 输入的 state (未修改, SSOT)
              - signals: 实际使用的 signals
              - decision: StrategyResult
              - suc: StoryUnderstandingContext
              - prompt: CompiledPrompt
        """
        if signals is None:
            signals = collect_signals(state.unit_id)

        decision_result: StrategyResult = decide(signals, story_state=state)

        suc: StoryUnderstandingContext = build_suc(state, signals=signals)

        compiled: CompiledPrompt = compile(suc, decision_result, **prompt_kwargs)

        return {
            "state": state,
            "signals": signals,
            "decision": decision_result,
            "suc": suc,
            "prompt": compiled,
        }

    # ---- Agent 集成 ----

    def run_with_agents(
        self,
        state: StoryState,
        *,
        project_id: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """运行完整链路 + Agent 协作."""
        try:
            from app.agents.orchestrator import OrchestratorV4
            from story.guide.collector import collect_signals

            # 收集 signals
            signals = collect_signals(state.unit_id, project_id=project_id)

            # Agent 协作
            orch = OrchestratorV4()
            agent_result = orch.run(
                state.unit_id,
                project_id=project_id,
                state=state,
                guides=signals,
            )

            # 合并结果
            base_result = self.run_unit(state, signals=signals, **kwargs)
            base_result["agent_result"] = agent_result

            return base_result

        except Exception as e:
            _logger.warning("Agent integration failed, falling back: %s", e)
            return self.run_unit(state, **kwargs)

    # ---- 状态查看 ----

    @property
    def event_count(self) -> int:
        return len(self._event_log)

    def reset_log(self) -> None:
        self._event_log.clear()
