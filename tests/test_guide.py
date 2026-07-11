"""
tests/test_guide — Guide 收集 + 冲突图 单元测试
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.types import Guide, collect_guides


def test_guide_creation():
    g = Guide(
        source="test",
        priority=0.8,
        confidence=0.9,
        scope="Unit",
        advice="测试建议",
    )
    assert g.priority == 0.8
    assert g.confidence == 0.9
    assert g.guide_id  # 自动生成
    print("  Guide creation: OK")


def test_guide_to_prompt_block():
    g = Guide(
        source="pressure",
        priority=0.7,
        confidence=0.8,
        scope="Unit",
        advice="压力偏高",
        reason="zone=red",
    )
    block = g.to_prompt_block()
    assert "pressure" in block
    assert "压力偏高" in block
    print("  Guide to_prompt_block: OK")


def test_guide_conflicts():
    g1 = Guide(source="a", advice="加速")
    g2 = Guide(source="b", advice="减速")
    g1.conflicts_with.append(g2.guide_id)
    assert g2.guide_id in g1.conflicts_with
    print("  Guide conflicts: OK")


def test_collect_guides():
    # collect_guides 需要 DB, 这里只测导入和函数签名
    import inspect
    sig = inspect.signature(collect_guides)
    assert "unit_id" in sig.parameters
    assert "project_id" in sig.parameters
    print("  collect_guides signature: OK")


def main():
    print("test_guide:")
    test_guide_creation()
    test_guide_to_prompt_block()
    test_guide_conflicts()
    test_collect_guides()
    print("  ALL PASSED")


if __name__ == "__main__":
    main()
