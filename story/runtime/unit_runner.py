"""
unit_runner — v4 Runtime 闭环入口.

串联: DB → StateBridge → StoryState → collect_signals → decide → build_suc → compile
输出: 编译好的 prompt (可直接喂 LLM) + 全链路中间产物

设计原则:
  - 不持有状态, 每次 run() 是无副作用的纯函数
  - DB 读取通过 service 层, 不直接操作 SQL
  - UI 事件通过 UIStateBridge 发布, 不直接耦合 Qt
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from story.state.story_state import StoryState
from story.state.state_bridge import StateBridge
from story.state.apply_event import apply_event, apply_events
from story.guide.collector import collect_signals, DecisionSignal
from story.decision.engine import decide
from story.decision.strategy import StrategyResult
from story.prompt.suc_builder import build_suc, StoryUnderstandingContext
from story.prompt.compiler import compile as compile_prompt, CompiledPrompt

_logger = logging.getLogger("NovelWriter.story.unit_runner")


@dataclass
class RunResult:
    """run_unit() 的完整输出."""
    ok: bool
    project_id: str
    unit_id: str
    state: StoryState | None = None
    signals: list[DecisionSignal] = field(default_factory=list)
    decision: StrategyResult | None = None
    suc: StoryUnderstandingContext | None = None
    prompt: CompiledPrompt | None = None
    error: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "project_id": self.project_id,
            "unit_id": self.unit_id,
            "signal_count": len(self.signals),
            "strategy": self.decision.label if self.decision else None,
            "decision_confidence": round(self.decision.confidence, 2) if self.decision else None,
            "suc_tokens": self.suc.total_tokens if self.suc else 0,
            "prompt_tokens": self.prompt.token_estimate if self.prompt else 0,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


class UnitRunner:
    """v4 Runtime 闭环.

    用法:
        runner = UnitRunner()
        result = runner.run("proj_001", "unit_001")
        if result.ok:
            # result.prompt.messages 可直接喂 LLM
            pass
    """

    def run(
        self,
        project_id: str,
        unit_id: str,
        *,
        signals: Optional[list[DecisionSignal]] = None,
        on_step: Optional[Any] = None,
        **prompt_kwargs: Any,
    ) -> RunResult:
        """运行一个 Unit 的完整 v4 链路.

        Args:
            project_id: 项目 ID
            unit_id: 单元 ID
            signals: 可选, 外部注入的 Guide signals; 不传则自动 collect
            on_step: 可选, 进度回调 (step_no, label)
            **prompt_kwargs: 透传给 compile_prompt() 的参数

        Returns:
            RunResult 包含全链路中间产物
        """
        t0 = time.time()

        def _emit(step: int, label: str) -> None:
            if on_step:
                try:
                    on_step(step, label)
                except Exception:
                    pass

        try:
            # Step 1: 从 DB 加载 Unit
            _emit(1, "加载单元")
            unit = self._load_unit(unit_id)

            # Step 2: 转换为 StoryState
            _emit(2, "构建状态")
            state = StateBridge.from_unit_v2(unit)

            # Step 3: 收集 Guide signals (如果未注入)
            _emit(3, "收集信号")
            if signals is None:
                signals = collect_signals(unit_id, project_id=project_id)

            # Step 4: Decision 决策
            _emit(4, "决策")
            decision = decide(signals, story_state=state)

            # Step 5: 构建 SUC
            _emit(5, "构建上下文")
            suc = build_suc(state, signals=signals)

            # Step 6: 编译 Prompt
            _emit(6, "编译提示")
            compiled = compile_prompt(suc, decision, **prompt_kwargs)

            duration = int((time.time() - t0) * 1000)
            _logger.info(
                "[runner] run_unit ok: unit=%s strategy=%s tokens=%d %dms",
                unit_id, decision.label, compiled.token_estimate, duration,
            )

            return RunResult(
                ok=True,
                project_id=project_id,
                unit_id=unit_id,
                state=state,
                signals=signals,
                decision=decision,
                suc=suc,
                prompt=compiled,
                duration_ms=duration,
            )

        except Exception as e:
            duration = int((time.time() - t0) * 1000)
            _logger.exception("[runner] run_unit failed: unit=%s", unit_id)
            return RunResult(
                ok=False,
                project_id=project_id,
                unit_id=unit_id,
                error=f"{type(e).__name__}: {e}",
                duration_ms=duration,
            )

    def apply_and_diff(
        self,
        state: StoryState,
        events: list[dict[str, Any]],
    ) -> tuple[StoryState, Any]:
        """应用事件列表并返回 (new_state, diff).

        用于 LLM 生成后将结果事件写回状态.
        """
        new_state = apply_events(state, events)
        d = StateBridge.diff(state, new_state)
        return new_state, d

    @staticmethod
    def _load_unit(unit_id: str):
        """从 DB 加载 StoryUnitV2."""
        from app.services import story_unit_service_v2 as svc
        return svc.get(unit_id)
