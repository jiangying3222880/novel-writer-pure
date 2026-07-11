"""
tests/test_services — 核心服务单元测试
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_pressure_constants():
    from app.services.pressure import (
        PressureZone, ZONE_LABELS, ZONE_ORDER,
        compute_zone, compute_pressure,
    )
    assert compute_zone(0) == PressureZone.GREEN
    assert compute_zone(50) == PressureZone.YELLOW
    assert compute_zone(80) == PressureZone.ORANGE
    assert compute_zone(95) == PressureZone.RED
    p = compute_pressure(active_hooks=5, open_promises=3, unresolved_subplots=2)
    assert p > 0
    print("  pressure constants: OK")


def test_guide_graph():
    from app.services.guide_graph import detect_conflict, detect_support
    from app.core.types import Guide
    g1 = Guide(source="pressure", advice="加速节奏")
    g2 = Guide(source="pressure", advice="减速节奏")
    # detect_conflict 和 detect_support 应该能处理
    result = detect_conflict(g1, g2)
    print(f"  guide_graph detect_conflict: OK (result={result})")


def test_character_arc_service():
    from app.services.character_arc_service import get_arc_expectation, _STAGE_KEYWORDS
    assert "犹豫" in _STAGE_KEYWORDS
    assert "成长" in _STAGE_KEYWORDS
    # get_arc_expectation 需要 DB, 只测导入
    print("  character_arc_service: OK")


def test_volume_transition_service():
    from app.services.volume_transition_service import create, get, list_for_project
    # 需要 DB, 只测导入
    print("  volume_transition_service: OK")


def test_reverse_compile():
    from app.services.reverse_compile import _extract_patterns
    patterns = _extract_patterns("AI生成的内容", "作者修改后的内容")
    assert isinstance(patterns, list)
    print("  reverse_compile: OK")


def test_patch_preview():
    from app.services.patch_preview import _diff_contents
    changes = _diff_contents("test", "u1", "旧内容\n第二行", "新内容\n第二行\n第三行")
    assert len(changes) > 0
    print("  patch_preview: OK")


def main():
    print("test_services:")
    test_pressure_constants()
    test_guide_graph()
    test_character_arc_service()
    test_volume_transition_service()
    test_reverse_compile()
    test_patch_preview()
    print("  ALL PASSED")


if __name__ == "__main__":
    main()
