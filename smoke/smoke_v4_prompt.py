"""
Week 3 verification: SUC Builder + Prompt Compiler
Tests: StoryState → SUC → CompiledPrompt (messages)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from story import (
    StoryState, StateBridge, StoryUnderstandingContext, SucSegment,
    build_suc, compile, compile_minimal, CompiledPrompt,
    Strategy, StrategyResult, DecisionSignal, decide,
)

print("1. IMPORTS: OK")

# ===== 2. Build a rich StoryState =====
from story.state.story_state import HookSnapshot, CommitmentSnapshot

state = (
    StoryState(
        unit_id="u_suc", title="试剑大会",
        current_step=3, total_steps=5,
        pov_character="林凡",
        unit_type="battle",
        synopsis="林凡在试剑大会上面对宿敌韩枫，发现对方使用被禁的血魔功",
    )
    .with_character("林凡", {"trust": 50, "realm": "金丹初期", "health": "轻伤"})
    .with_character("韩枫", {"trust": 10, "realm": "金丹中期", "secret": "血魔功"})
    .with_character("慕容雪", {"trust": 70, "realm": "筑基巅峰"})
    .with_world(
        time_label="宗门大比日·午时",
        location="天剑峰·试剑台",
        weather="烈日，风起",
        active_factions=["天剑宗", "血煞门(暗中)"],
    )
)

state = state.with_hook(
    HookSnapshot(hook_id="h1", hook_type="plant", description="韩枫眼中闪过血光", status="active", planted_at_step=1)
)
state = state.with_hook(
    HookSnapshot(hook_id="h2", hook_type="plant", description="试剑台地面异常龟裂", status="active", planted_at_step=2)
)
state = state.with_hook(
    HookSnapshot(hook_id="h3", hook_type="payoff", description="慕容雪认出韩枫招式", status="resolved", planted_at_step=1, paid_at_step=3)
)
state = state.with_commitment(
    CommitmentSnapshot(description="林凡承诺为师父查明当年真相", status="pending")
)

print(f"2. STATE: chars={state.character_names()}, hooks_active={state.active_hooks_count()}, pending_c={len(state.pending_commitments())}")
assert state.active_hooks_count() == 2
assert len(state.pending_commitments()) == 1

# ===== 3. Build SUC =====
signals = [
    DecisionSignal(
        guide_id="g1", source="pressure", priority=0.9, confidence=0.85,
        advice="当前节奏需加速", reason="压力区间", dimension="pacing", urgent=True,
    ),
    DecisionSignal(
        guide_id="g2", source="character_state", priority=0.6, confidence=0.75,
        advice="林凡信任度下降需铺垫", dimension="character",
    ),
]

suc = build_suc(state, signals=signals, max_tokens=2000)
print(f"3. SUC BUILT: tokens={suc.total_tokens()}")
print(f"   character: {suc.character.content[:80]}...")
print(f"   world:     {suc.world.content[:80]}...")
print(f"   hook:      {suc.hook.content[:80]}...")
print(f"   tension:   {suc.tension.content[:80]}...")
assert suc.total_tokens() > 0
assert "林凡" in suc.character.content
assert "天剑峰" in suc.world.content
assert "活跃伏笔" in suc.hook.content
print("   OK")

# ===== 4. SUC segments ranked correctly =====
ranked = suc.ranked_segments()
print(f"4. SEGMENT ORDER: {[s.label for s in ranked]}")
assert ranked[0].label == "角色状态"
assert ranked[1].label == "世界环境"
assert ranked[2].label == "伏笔管理"
assert ranked[3].label == "叙事张力"
print("   OK")

# ===== 5. Decision → compile =====
result = decide(signals, story_state=state)
compiled = compile(
    suc,
    strategy_result=result,
    unit_title=state.title,
    unit_synopsis=state.synopsis,
)
messages = compiled.to_messages()
print(f"5. COMPILED: messages={len(messages)}, tokens≈{compiled.token_estimate}")
assert len(messages) >= 2
assert messages[0]["role"] == "system"
assert messages[1]["role"] == "user"
assert "林凡" in messages[1]["content"]
assert "试剑大会" in messages[1]["content"]
print("   OK")

# ===== 6. compile_minimal convenience =====
mini = compile_minimal(state, strategy_result=result)
mini_msgs = mini.to_messages()
print(f"6. MINIMAL COMPILE: messages={len(mini_msgs)}, tokens≈{mini.token_estimate}")
assert len(mini_msgs) >= 2
print("   OK")

# ===== 7. SUC without signals =====
suc_no_signals = build_suc(state, max_tokens=1000)
print(f"7. SUC WITHOUT SIGNALS: tokens={suc_no_signals.total_tokens()}, tension still built from state")
assert suc_no_signals.total_tokens() > 0
print("   OK")

# ===== 8. Empty state → SUC =====
empty_state = StoryState(unit_id="empty", title="空单元")
empty_suc = build_suc(empty_state, max_tokens=500)
empty_compiled = compile_minimal(empty_state)
print(f"8. EMPTY STATE: suc_tokens={empty_suc.total_tokens()}, compiled_tokens≈{empty_compiled.token_estimate}")
# 空状态也应该能编译出基础 prompt
assert empty_compiled.token_estimate > 0
print("   OK")

# ===== 9. SUC to_dict =====
d = suc.to_dict()
print(f"9. SUC DICT: keys={list(d.keys())}")
assert "character" in d
assert "world" in d
assert "hook" in d
assert "tension" in d
print("   OK")

# ===== 10. CompiledPrompt to_dict =====
cd = compiled.to_dict()
print(f"10. COMPILED DICT: keys={list(cd.keys())}")
assert "messages" in cd
assert cd["token_estimate"] > 0
print("    OK")

print()
print("ALL TESTS PASSED")
