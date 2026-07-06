"""
smoke_v4_runtime — Week 4 全链路 MVP 验收.

验证:
1. UnitRunner 可实例化
2. RunResult 数据结构正确
3. UIStateBridge 可发布事件
4. apply_and_diff 链路正确
5. 端到端: State → Signals → Decision → SUC → Prompt 完整跑通
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from story.runtime.unit_runner import UnitRunner, RunResult
from story.state.story_state import StoryState, CharacterSnapshot, HookSnapshot, WorldSnapshot
from story.state.state_bridge import StateBridge
from story.state.apply_event import apply_event, apply_events
from story.guide.collector import DecisionSignal
from story.decision.engine import decide
from story.prompt.suc_builder import build_suc
from story.prompt.compiler import compile as compile_prompt
from story.ui.bridge.state_bridge import UIStateBridge, get_bridge


def _make_state() -> StoryState:
    return StoryState(
        unit_id="test_unit_001",
        title="试剑大会",
        unit_type="battle",
        current_step=3,
        total_steps=5,
        pov_character="林凡",
        transition_type="escalation",
        synopsis="林凡在试剑大会上面对宿敌韩枫",
        characters={
            "林凡": CharacterSnapshot(
                name="林凡",
                traits={"trust": 50, "realm": "金丹初期", "health": "轻伤"},
                location="天剑峰·试剑台",
            ),
            "韩枫": CharacterSnapshot(
                name="韩枫",
                traits={"trust": 10, "realm": "金丹后期"},
                location="天剑峰·试剑台",
            ),
        },
        hooks=[
            HookSnapshot(hook_id="h1", hook_type="plant", description="韩枫眼中闪过血光", status="active", planted_at_step=1),
            HookSnapshot(hook_id="h2", hook_type="plant", description="试剑台地面异常龟裂", status="active", planted_at_step=2),
        ],
        world=WorldSnapshot(time_label="宗门大比日·午时", location="天剑峰", weather="烈日"),
    )


def _make_signals() -> list[DecisionSignal]:
    return [
        DecisionSignal(guide_id="g1", source="pressure", priority=0.85, confidence=0.9,
                       advice="节奏过慢，需加速推进", dimension="pacing", urgent=True),
        DecisionSignal(guide_id="g2", source="hook", priority=0.7, confidence=0.8,
                       advice="韩枫血光伏笔应在此单元回收", dimension="hook",
                       conflicts_with=["g3"]),
        DecisionSignal(guide_id="g3", source="consistency", priority=0.65, confidence=0.75,
                       advice="血魔功揭露需铺垫，不宜过早", dimension="hook"),
    ]


def main():
    print("=" * 60)
    print("smoke_v4_runtime — Week 4 全链路 MVP")
    print("=" * 60)

    # 1. UnitRunner 实例化
    runner = UnitRunner()
    print("1. UnitRunner 实例化: OK")

    # 2. RunResult 结构
    r = RunResult(ok=True, project_id="p1", unit_id="u1")
    d = r.to_dict()
    assert "ok" in d and "strategy" in d and "duration_ms" in d
    print(f"2. RunResult.to_dict(): keys={sorted(d.keys())} OK")

    # 3. 端到端 pipeline (不走 DB, 直接注入 state + signals)
    state = _make_state()
    signals = _make_signals()

    decision = decide(signals, story_state=state)
    assert decision is not None
    print(f"3. decide(): strategy={decision.label}, confidence={decision.confidence:.2f} OK")

    suc = build_suc(state, signals=signals)
    assert suc.total_tokens() > 0
    print(f"4. build_suc(): tokens={suc.total_tokens()}, segments={len(suc.ranked_segments())} OK")

    compiled = compile_prompt(suc, decision)
    assert len(compiled.messages) == 2
    assert compiled.token_estimate > 0
    print(f"5. compile_prompt(): messages={len(compiled.messages)}, tokens≈{compiled.token_estimate} OK")

    # 6. apply_and_diff
    event = {
        "event_type": "character_state",
        "entity_name": "林凡",
        "field_name": "health",
        "old_value": "轻伤",
        "new_value": "中伤",
    }
    new_state, d = runner.apply_and_diff(state, [event])
    assert new_state != state
    assert d.has_changes
    assert new_state.get_character("林凡").traits.get("health") == "中伤"
    print(f"6. apply_and_diff: changes={d.total_changes()}, health=中伤 OK")

    # 7. UIStateBridge
    bridge = UIStateBridge()
    received = []
    bridge.subscribe("state_updated", lambda p: received.append(p))
    bridge.on_state_change(state, new_state, d)
    assert len(received) == 1
    assert received[0]["unit_id"] == "test_unit_001"
    assert received[0]["snapshot"]["pov"] == "林凡"
    print(f"7. UIStateBridge: event received, snapshot.pov={received[0]['snapshot']['pov']} OK")

    # 8. get_bridge() 单例
    b1 = get_bridge()
    b2 = get_bridge()
    assert b1 is b2
    print("8. get_bridge() 单例: OK")

    # 9. 完整链路汇总
    print(f"\n{'=' * 60}")
    print(f"FULL CHAIN: State → Signals({len(signals)}) → "
          f"Decision({decision.label}) → SUC({suc.total_tokens()}tok) → "
          f"Prompt({compiled.token_estimate}tok)")
    print(f"{'=' * 60}")

    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
