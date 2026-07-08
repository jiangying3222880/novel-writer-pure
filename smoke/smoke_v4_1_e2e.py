"""
v4.1 端到端验证脚本

验收铁律：真完成 = 能INSERT / 能被UI调到 / 能在运行app里走通
测试必须直接查询数据库验证真写入，不能用mock
"""
from __future__ import annotations

import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def init_test_db():
    """初始化测试数据库并执行迁移"""
    from app.db._impl import init as db_init, init_db as db_init_db
    
    temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False).name
    db_init(temp_db)
    db_init_db(temp_db)
    
    return temp_db


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_test_project_and_unit(project_name: str, unit_title: str):
    """创建测试项目和单元（直接使用数据库连接）"""
    from app.db import _impl as _db_conn
    
    project_id = str(uuid.uuid4())
    unit_id = uuid.uuid4().hex[:12]
    
    with _db_conn.transaction() as db:
        db.execute(
            """INSERT INTO projects
               (id, name, book_title, author, genre, platform, word_target,
                volumes, chapters_per_volume, words_per_chapter,
                total_chapters, total_words, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, project_name, "", "", "测试题材", "", 0,
             0, 0, 0, 0, 0, _now(), _now()),
        )
        
        db.execute(
            """INSERT INTO story_units
               (id, project_id, book_id, unit_no, title, unit_type,
                story_order, present_order, status, synopsis,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (unit_id, project_id, "", 0, unit_title, "other",
             1, 1, "draft", "", _now(), _now()),
        )
    
    return project_id, unit_id


def test_phase0_api_fixes():
    """Phase 0 验证：修复的API能正常导入和调用"""
    print("=" * 60)
    print("Phase 0: 验证修复的API")
    print("=" * 60)

    try:
        from app.services.pressure import record, compute_pressure
        print("✅ pressure.py 导入成功 (record, compute_pressure)")
    except ImportError as e:
        print(f"❌ pressure.py 导入失败: {e}")
        return False

    try:
        from app.services.setting_service import get_setting, set_setting
        print("✅ setting_service.py 导入成功")
    except ImportError as e:
        print(f"❌ setting_service.py 导入失败: {e}")
        return False

    try:
        from app.ui.widgets.collapsible import CollapsiblePanel
        print("✅ collapsible.py 导入成功")
    except ImportError as e:
        print(f"❌ collapsible.py 导入失败: {e}")
        return False

    return True


def test_phase2_conflict_log():
    """Phase 2 验证：冲突日志服务"""
    print("\n" + "=" * 60)
    print("Phase 2: 验证冲突日志服务")
    print("=" * 60)

    try:
        from app.services.conflict_log import (
            log_conflict,
            get_conflicts,
            resolve_conflict,
            get_pending_conflicts,
            get_conflict_stats,
        )

        project_id, unit_id = create_test_project_and_unit(
            "冲突日志测试项目", "测试单元"
        )

        conflict = log_conflict(
            project_id=project_id,
            unit_id=unit_id,
            conflict_type="causal",
            description="因果链断裂：主角死亡后又出现",
            source_a="单元1: 主角死亡",
            source_b="单元3: 主角出场",
        )
        print(f"✅ 冲突记录成功: {conflict.id}")

        conflicts = get_conflicts(project_id)
        assert len(conflicts) > 0, "冲突列表应有数据"
        print(f"✅ 获取冲突列表成功: {len(conflicts)} 条")

        pending = get_pending_conflicts(project_id)
        assert len(pending) > 0, "待解决冲突应有数据"
        print(f"✅ 获取待解决冲突成功: {len(pending)} 条")

        resolved = resolve_conflict(
            conflict.id,
            resolution="manual",
            resolution_note="作者手动修正",
        )
        assert resolved.resolution == "manual", "冲突应已解决"
        print(f"✅ 冲突解决成功")

        stats = get_conflict_stats(project_id)
        assert stats["total"] > 0, "统计总数应>0"
        print(f"✅ 冲突统计: {stats}")

        return True

    except Exception as e:
        print(f"❌ 冲突日志测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_phase2_patch_preview():
    """Phase 2 验证：增量补丁预览服务"""
    print("\n" + "=" * 60)
    print("Phase 2: 验证增量补丁预览服务")
    print("=" * 60)

    try:
        from app.services.patch_preview import (
            generate_patch,
            get_patch,
            preview_as_text,
            apply_patch,
        )

        project_id, unit_id = create_test_project_and_unit(
            "补丁测试项目", "测试单元"
        )

        old_content = """第一章：觉醒

林凡站在山巅，望着远方的云海。
他心中充满了对修仙的渴望。
突然，一道金光闪过。"""
        
        new_content = """第一章：觉醒

林凡站在山巅，凝视着远方翻滚的云海。
他心中燃起对修仙的炽热渴望。
忽然，一道璀璨的金光划破天际。"""

        patch = generate_patch(
            project_id=project_id,
            unit_id=unit_id,
            old_content=old_content,
            new_content=new_content,
            description="优化描写用词",
        )
        print(f"✅ 补丁生成成功: {patch.id}, {len(patch.changes)} 个变更")

        retrieved = get_patch(patch.id)
        assert retrieved is not None, "补丁应存在"
        print(f"✅ 获取补丁成功")

        preview_text = preview_as_text(patch.id)
        assert "补丁预览" in preview_text, "预览文本应包含标题"
        print(f"✅ 补丁预览文本生成成功")

        applied = apply_patch(patch.id)
        assert applied > 0, "应有变更被应用"
        print(f"✅ 补丁应用成功: {applied} 个变更")

        return True

    except Exception as e:
        print(f"❌ 补丁预览测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_phase2_reverse_compile():
    """Phase 2 验证：反向编译服务"""
    print("\n" + "=" * 60)
    print("Phase 2: 验证反向编译服务")
    print("=" * 60)

    try:
        from app.services.reverse_compile import (
            reverse_compile,
            parse_text,
            get_reverse_compile_results,
        )

        project_id, _ = create_test_project_and_unit(
            "反向编译测试项目", "测试单元"
        )

        ai_content = """第一章：觉醒

林凡站在青云山巅，望着远方的云海。
他心中充满了对修仙的渴望。
突然，一道金光闪过，一位仙人降临。"""

        author_content = """第一章：觉醒

林凡站在青云山巅，凝视着远方翻滚的云海。
他心中燃起对修仙的炽热渴望。
忽然，一道璀璨的金光划破天际，一位白发仙人缓缓降临。"""

        result = reverse_compile(
            project_id=project_id,
            chapter_id="test-chapter-001",
            ai_content=ai_content,
            author_content=author_content,
        )
        print(f"✅ 反向编译成功: {result.id}")
        print(f"   - 提取模式数: {len(result.extracted_patterns)}")
        print(f"   - 权重更新数: {len(result.weight_updates)}")

        outline = parse_text(author_content)
        assert outline is not None, "解析结果应存在"
        print(f"✅ 文本解析成功")

        results = get_reverse_compile_results(project_id)
        assert len(results) > 0, "结果列表应有数据"
        print(f"✅ 获取反向编译结果成功: {len(results)} 条")

        return True

    except Exception as e:
        print(f"❌ 反向编译测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_orchestrator_v4_path():
    """验证 orchestrator v4 路径"""
    print("\n" + "=" * 60)
    print("验证 Orchestrator v4 路径")
    print("=" * 60)

    try:
        from app.agents.orchestrator import Orchestrator

        print("✅ Orchestrator 导入成功")

        orch = Orchestrator()
        assert hasattr(orch, 'run_unit'), "run_unit 方法应存在"
        assert hasattr(orch, '_run_v4_pipeline'), "_run_v4_pipeline 方法应存在"
        assert hasattr(orch, 'review_causality'), "review_causality 方法应存在"
        assert hasattr(orch, 'update_causal_graph'), "update_causal_graph 方法应存在"
        print("✅ Orchestrator v4 方法检查通过")

        return True

    except Exception as e:
        print(f"❌ Orchestrator v4 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("v4.1 端到端验证")
    print("=" * 60)

    print("\n初始化测试数据库...")
    db_path = init_test_db()
    print(f"✅ 测试数据库初始化成功: {db_path}")

    results = []

    results.append(("Phase 0: API修复", test_phase0_api_fixes()))
    results.append(("Phase 2: 冲突日志", test_phase2_conflict_log()))
    results.append(("Phase 2: 补丁预览", test_phase2_patch_preview()))
    results.append(("Phase 2: 反向编译", test_phase2_reverse_compile()))
    results.append(("Orchestrator v4", test_orchestrator_v4_path()))

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n🎉 全部测试通过!")
        return 0
    else:
        print(f"\n⚠️ {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())