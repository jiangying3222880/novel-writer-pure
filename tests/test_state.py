"""
tests/test_state — StoryState + StateBridge 单元测试
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from story.state.story_state import StoryState, CharacterSnapshot, HookSnapshot, WorldSnapshot
from story.state.state_bridge import StateBridge


def test_story_state_creation():
    s = StoryState(unit_id="u1", title="测试单元", pov_character="林凡")
    assert s.unit_id == "u1"
    assert s.title == "测试单元"
    assert s.pov_character == "林凡"
    print("  StoryState creation: OK")


def test_story_state_immutability():
    s = StoryState(unit_id="u1")
    s2 = s.with_character("张三", {"hp": 100})
    assert s.get_character("张三") is None  # 原始不变
    assert s2.get_character("张三") is not None  # 新实例有
    print("  StoryState immutability: OK")


def test_story_state_with_character():
    s = StoryState(unit_id="u1")
    s = s.with_character("林凡", {"trust": 80, "realm": "筑基"})
    s = s.with_character("林凡", {"trust": 60})  # 更新
    char = s.get_character("林凡")
    assert char.traits["trust"] == 60
    assert char.traits["realm"] == "筑基"  # 保留旧字段
    print("  StoryState with_character: OK")


def test_story_state_with_hook():
    s = StoryState(unit_id="u1")
    h = HookSnapshot(hook_id="h1", description="伏笔1", status="active")
    s = s.with_hook(h)
    assert s.active_hooks_count() == 1
    h2 = HookSnapshot(hook_id="h1", description="伏笔1", status="resolved")
    s = s.with_hook(h2)
    assert s.active_hooks_count() == 0
    print("  StoryState with_hook: OK")


def test_story_state_to_dict():
    s = StoryState(unit_id="u1", title="测试")
    d = s.to_dict()
    assert d["unit_id"] == "u1"
    assert d["title"] == "测试"
    print("  StoryState to_dict: OK")


def test_state_bridge_diff():
    s1 = StoryState(unit_id="u1").with_character("张三", {"hp": 100})
    s2 = s1.with_character("张三", {"hp": 70}).with_character("李四", {"hp": 50})
    diff = StateBridge.diff(s1, s2)
    assert diff.total_changes() == 2
    print("  StateBridge.diff: OK")


def main():
    print("test_state:")
    test_story_state_creation()
    test_story_state_immutability()
    test_story_state_with_character()
    test_story_state_with_hook()
    test_story_state_to_dict()
    test_state_bridge_diff()
    print("  ALL PASSED")


if __name__ == "__main__":
    main()
