"""
Story OS — Event-driven Narrative Operating System

  Event → State → Signal → Decision → Language → UI

v4 runtime layer: state + guidance + decision + prompt compilation.
Persistence and UI eventing continue through existing app/core/ and app/services/.
"""
from story.state.story_state import StoryState, CharacterSnapshot, HookSnapshot, WorldSnapshot, CommitmentSnapshot, StateDiff
from story.state.state_bridge import StateBridge
from story.state.apply_event import apply_event, apply_events, rebuild_state
from story.guide.collector import collect_signals, DecisionSignal, signals_summary
from story.decision.strategy import Strategy, StrategyResult, STRATEGY_LABELS
from story.decision.dimension_matrix import compute_dimension_vector, DimensionVector, DimensionScore
from story.decision.engine import decide
from story.prompt.suc_builder import build_suc, StoryUnderstandingContext, SucSegment
from story.prompt.compiler import compile, compile_minimal, CompiledPrompt
from story.engine.story_engine import StoryEngine

__all__ = [
    "StoryState",
    "CharacterSnapshot",
    "HookSnapshot",
    "WorldSnapshot",
    "CommitmentSnapshot",
    "StateDiff",
    "StateBridge",
    "apply_event",
    "apply_events",
    "rebuild_state",
    "collect_signals",
    "DecisionSignal",
    "signals_summary",
    "Strategy",
    "StrategyResult",
    "STRATEGY_LABELS",
    "compute_dimension_vector",
    "DimensionVector",
    "DimensionScore",
    "decide",
    "build_suc",
    "StoryUnderstandingContext",
    "SucSegment",
    "compile",
    "compile_minimal",
    "CompiledPrompt",
    "StoryEngine",
]
