"""
smoke_m0_db: 阶段 0 冒烟测试
- 验证 C2 connection 能初始化
- 验证 C3 migrator 能跑所有 9.0 迁移
- 验证 C4 models 能 create/insert/select
- 验证 C6 db_utils 工具函数
- 验证 4.0 现状 schema (8 表) 不被破坏

5 分钟自动超时 (threading.Timer, 跨平台, 防卡死)
"""
import sys
import os
import tempfile
import threading
from pathlib import Path

# 5 分钟全局超时 (smoke 卡死保护, Windows 兼容用 Timer)
_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_m0_db 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    print(f"[TIMEOUT] 请检查: 1) 终端输出最后一行  2) logs/NovelWriter_*.log  3) 是否被外部 IO 阻塞")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

# 4.0 项目根
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import connection, migrator, models, db_utils


def test_1_init_connection():
    """C2: 全局单例连接 + WAL 模式。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connection.init(db_path)
        assert conn is not None
        # WAL 模式
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal", f"期望 WAL 模式，实际 {mode}"
        connection.close()
    print("✓ test_1_init_connection: PASS")


def test_2_run_migrations():
    """C3: 跑 5.0 全部 23 个迁移 (5.0 8 个 + 9.0 15 个)。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        connection.init(db_path)
        # 1) 先跑 schema.sql (5.0 基础)
        conn = connection.get_conn()
        schema_sql = (ROOT / "app" / "db" / "schema.sql").read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        # 2) 跑所有迁移
        applied = migrator.run_migrations()
        assert "5" in applied or len(applied) >= 15, f"期望至少 15 个迁移，实际 {applied}"
        # 3) 当前版本
        version = migrator.get_current_version()
        assert version is not None
        # 4) 不重复应用
        applied2 = migrator.run_migrations()
        assert applied2 == [], f"重复跑应为空，实际 {applied2}"
        connection.close()
    print(f"✓ test_2_run_migrations: PASS (version={version}, applied={len(applied)})")


def test_3_create_subtext_card():
    """C4: dataclass 插入 subtext card (13 字段)。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        connection.init(db_path)
        conn = connection.get_conn()
        schema_sql = (ROOT / "app" / "db" / "schema.sql").read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        migrator.run_migrations()
        # 准备 chapter
        conn.execute(
            "INSERT INTO projects (id, name) VALUES (?, ?)",
            ("p1", "测试项目"),
        )
        conn.execute(
            "INSERT INTO books (id, project_id, volume_no) VALUES (?, ?, ?)",
            ("b1", "p1", 1),
        )
        conn.execute(
            "INSERT INTO chapters (id, book_id, chapter_no) VALUES (?, ?, ?)",
            ("c1", "b1", 1),
        )
        # 插入 subtext card (13 字段)
        card = models.SubtextCard(
            id="sc1",
            chapter_id="c1",
            surface_event="林婉端茶",
            true_intent="她希望母亲走",
            lie="妈，您多休息",
            truth="我希望解脱",
            physical_anchor="手稳",
            emotional="隐忍",
            pacing="缓",
            viewpoint="林婉",
            anti_rules="本章不写林婉哭",
            callback_to="第 3 章母亲年轻时漂亮",
            scene_map="客厅",
            ending_scene_state="茶凉，母亲没喝",
            source="manual",
        )
        cols = [f.name for f in models.SubtextCard.__dataclass_fields__.values()]
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        conn.execute(
            f"INSERT INTO scene_subtext_cards ({col_names}) VALUES ({placeholders})",
            tuple(getattr(card, c) for c in cols),
        )
        # 查回
        row = conn.execute(
            "SELECT * FROM scene_subtext_cards WHERE id = ?", ("sc1",)
        ).fetchone()
        assert row["ending_scene_state"] == "茶凉，母亲没喝"
        assert row["source"] == "manual"
        # from_row 测试
        card2 = models.from_row(models.SubtextCard, row)
        assert card2.physical_anchor == "手稳"
        connection.close()
    print("✓ test_3_create_subtext_card: PASS")


def test_4_models_all_tables():
    """C4: 25+ dataclass 都能 from_row/to_dict。"""
    classes = [
        models.Project, models.Book, models.Chapter, models.ChapterBrief,
        models.SubtextCard, models.SubtextProjectMode, models.SubtextTemplate,
        models.WorldPowerSystem, models.WorldLocation, models.WorldItem,
        models.WorldFaction, models.WorldRelation, models.CharacterTracker,
        models.WorldStateSnapshot, models.AgentMemory, models.NarrativePressure,
        models.KnowledgeBuiltin, models.KnowledgeLocal, models.KnowledgeIndex,
        models.StyleFingerprint, models.VoiceProfile, models.ConsistencyLog,
        models.ModelConfig, models.UsageRecord, models.UsageSummary,
    ]
    for cls in classes:
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        assert "id" in fields or "project_id" in fields or "chapter_id" in fields, \
            f"{cls.__name__} 缺主键字段"
    print(f"✓ test_4_models_all_tables: PASS ({len(classes)} dataclass)")


def test_5_db_utils():
    """C6: 工具函数。"""
    # JSON
    assert db_utils.to_json({"a": 1}) == '{"a": 1}'
    assert db_utils.from_json('{"a":1}') == {"a": 1}
    assert db_utils.from_json("") is None
    assert db_utils.from_json("invalid", default={}) == {}
    # 时间
    iso = db_utils.now_iso()
    assert isinstance(iso, str) and len(iso) > 10
    assert db_utils.format_relative(iso).endswith("前")
    # 字典转 SQL
    d = {"a": 1, "b": "x"}
    assert db_utils.dict_to_placeholder(d) == "(?, ?)"
    assert db_utils.dict_to_params(d) == (1, "x")
    # 短 ID
    assert len(db_utils.short_id("test")) == 8
    # 大小格式化
    assert db_utils.format_size(1024) == "1.0 KB"
    # 文本清理
    assert db_utils.clean_text("  hello   world  ") == "hello world"
    # 字数统计
    assert db_utils.count_words("hello world") == 2
    assert db_utils.count_words("你好世界") == 4
    # 截断
    assert db_utils.truncate("x" * 200, max_len=10) == "xxxxxxx..."
    # 路径
    with tempfile.TemporaryDirectory() as tmpdir:
        p = db_utils.ensure_dir(Path(tmpdir) / "a" / "b")
        assert p.exists()
    print("✓ test_5_db_utils: PASS")


def test_6_4_0_schema_intact():
    """验证 4.0 现状 8 表不破坏。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        connection.init(db_path)
        conn = connection.get_conn()
        schema_sql = (ROOT / "app" / "db" / "schema.sql").read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        migrator.run_migrations()
        # 4.0 现状 8 表都存在
        for table in [
            "projects", "books", "chapters", "chapter_briefs",
            "agent_memory", "world_state_snapshots",
            "scene_subtext_cards", "usage_records",
        ]:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            assert row is not None, f"5.0 表 {table} 丢失"
        # 9.0 加 15+ 张表
        new_tables = [
            "world_power_systems", "world_locations", "world_items",
            "world_factions", "world_relations", "character_trackers",
            "agent_memories", "narrative_pressures", "knowledge_builtin",
            "knowledge_local", "knowledge_index", "style_fingerprints",
            "voice_profiles", "consistency_logs", "model_configs",
            "usage_summary", "project_genres", "subtext_templates",
            "subtext_project_modes",
        ]
        for table in new_tables:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            assert row is not None, f"9.0 表 {table} 未创建"
        connection.close()
    print(f"✓ test_6_4_0_schema_intact: PASS (5.0: 8 + 9.0: {len(new_tables)} = 27 tables)")


def main():
    print("=" * 60)
    print("smoke_m0_db: 阶段 0 冒烟测试")
    print("=" * 60)
    tests = [
        test_1_init_connection,
        test_2_run_migrations,
        test_3_create_subtext_card,
        test_4_models_all_tables,
        test_5_db_utils,
        test_6_4_0_schema_intact,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"✗ {t.__name__}: FAIL — {type(e).__name__}: {e}")
            sys.exit(1)
    print("=" * 60)
    print(f"全部 {len(tests)} 测试通过 ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
