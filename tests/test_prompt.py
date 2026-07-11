"""
tests/test_prompt — SUC Builder + Prompt Compiler 单元测试
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from story.state.story_state import StoryState, HookSnapshot, CommitmentSnapshot
from story.guide.collector import DecisionSignal
from story.prompt.suc_builder import build_suc
from story.prompt.compiler import compile, compile_minimal


def _make_state() -> StoryState:
    s = StoryState(
        unit_id="u_test", title="试剑大会",
        current_step=3, total_steps=5,
        pov_character="林凡", unit_type="battle",
        synopsis="林凡在试剑大会上面对宿敌",
    )
    s = s.with_character("林凡", {"trust": 50, "realm": "金丹初期"})
    s = s.with_character("韩枫", {"trust": 10, "realm": "金丹中期"})
    s = s.with_world(time_label="宗门大比日", location="天剑峰")
    s = s.with_hook(HookSnapshot(hook_id="h1", description="血光", status="active"))
    s = s.with_commitment(CommitmentSnapshot(description="查明真相", status="pending"))
    return s


def test_build_suc():
    state = _make_state()
    signals = [
        DecisionSignal(
            guide_id="g1", source="pressure", priority=0.9, confidence=0.85,
            advice="节奏需加速", reason="压力", dimension="pacing", urgent=True,
        ),
    ]
    suc = build_suc(state, signals=signals, max_tokens=2000)
    assert suc.total_tokens() > 0
    assert "林凡" in suc.character.content
    print("  build_suc: OK")


def test_compile():
    state = _make_state()
    signals = [
        DecisionSignal(
            guide_id="g1", source="pressure", priority=0.9, confidence=0.85,
            advice="节奏需加速", dimension="pacing", urgent=True,
        ),
    ]
    suc = build_suc(state, signals=signals, max_tokens=2000)
    from story.decision.engine import decide
    from story.decision.strategy import StrategyResult
    result = decide(signals, story_state=state)
    compiled = compile(suc, result)
    messages = compiled.to_messages()
    assert len(messages) >= 2
    assert messages[0]["role"] == "system"
    print("  compile: OK")


def test_compile_minimal():
    state = _make_state()
    mini = compile_minimal(state)
    messages = mini.to_messages()
    assert len(messages) >= 2
    print("  compile_minimal: OK")


def test_empty_state():
    empty = StoryState(unit_id="empty", title="空")
    suc = build_suc(empty, max_tokens=500)
    mini = compile_minimal(empty)
    assert suc.total_tokens() > 0
    assert mini.token_estimate > 0
    print("  empty state: OK")


def main():
    print("test_prompt:")
    test_build_suc()
    test_compile()
    test_compile_minimal()
    test_empty_state()
    print("  ALL PASSED")


if __name__ == "__main__":
    main()
