"""
M3 SMOKE: 单元池 (unit_pool) + clone_to_project 成稿连通性

测点:
- 迁移 044 已建表 (count/list 可用)
- create 超 1000 字截断 + 告警
- search_by_tags 多维度过滤 (genre/scene_type/emotion/query/tags)
- bulk_import 批量入池
- clone_to_project → story_units 有行 + draft 非空
- 克隆后 assemble_units 可成稿 (merged_text 非空 + 段落级 unit_no 标签)

5 分钟自动超时 (threading.Timer, 跨平台, 防卡死)
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] M3 smoke 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import connection, migrator
from app.services import unit_pool_service as ups
from app.services import project_service
from app.services import story_unit_service_v2 as usvc
from app.services import manuscript_assembly as ma


def _setup_db():
    tmpdir = tempfile.mkdtemp(prefix="nw_smoke_m3_")
    db_path = Path(tmpdir) / "test.db"
    # 关键: project_service 等内部用 connection() 辅助函数, 会重新打开
    # app_paths.sqlite_path() 默认路径的连接。测试必须把该路径也指向临时库,
    # 否则 project_service.create 内部 get() 会去读真实 app DB 而找不到刚插入的项目。
    import app.app_paths as _ap
    _ap.sqlite_path = lambda: str(db_path)
    connection.init(db_path)
    conn = connection.get_conn()
    schema_sql = (ROOT / "app" / "db" / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    migrator.run_migrations()
    return tmpdir


def main() -> int:
    fails = []
    passed = 0

    def check(cond, msg):
        nonlocal passed
        if cond:
            passed += 1
            print(f"  [PASS] {msg}")
        else:
            fails.append(msg)
            print(f"  [FAIL] {msg}")

    print("=" * 60)
    print("M3 SMOKE: 单元池 + clone_to_project 连通性")
    print("=" * 60)

    tmpdir = _setup_db()

    # 0) 迁移 044 表已存在
    print("\n[0] 迁移 044 建表")
    conn = connection.get_conn()
    tbl = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='unit_pool'"
    ).fetchone()
    check(tbl is not None, "unit_pool 表已创建 (迁移 044 已应用)")

    # 1) create + count
    print("\n[1] 新建池单元")
    u1 = ups.create(
        "林间初遇", "暮色里少年与少女在林间初次相遇，彼此戒备又好奇。",
        genre="仙侠", scene_type="感情", emotion="悸动", tags=["相遇", "暧昧"],
    )
    check(u1["id"], f"create 返回 id (实际 {u1['id']})")
    check(ups.count() == 1, f"count == 1 (实际 {ups.count()})")
    check(u1["word_count"] > 0, f"word_count > 0 (实际 {u1['word_count']})")

    # 2) 超长截断
    print("\n[2] 超 1000 字截断")
    long_text = "场景描写" * 600  # 1800+ 字
    u2 = ups.create("超长单元", long_text, genre="通用", scene_type="过渡")
    check(len(u2["content"]) <= ups.UNIT_POOL_MAX_CHARS,
          f"内容 ≤ {ups.UNIT_POOL_MAX_CHARS} (实际 {len(u2['content'])})")

    # 3) search_by_tags
    print("\n[3] 检索过滤")
    ups.create("山门比试", "擂台之上剑光交错，少年以巧破力。",
               genre="仙侠", scene_type="战斗", emotion="激昂", tags=["比试"])
    ups.create("旧友重逢", "十年未见，二人相对无言却已热泪盈眶。",
               genre="都市", scene_type="感情", emotion="感伤", tags=["重逢"])
    hits = ups.search_by_tags(genre="仙侠")
    check(len(hits) >= 2, f"genre=仙侠 命中 ≥2 (实际 {len(hits)})")
    hits_battle = ups.search_by_tags(genre="仙侠", scene_type="战斗")
    check(all(h["scene_type"] == "战斗" for h in hits_battle), "战斗过滤生效")
    hits_q = ups.search_by_tags(query="少年")
    check(len(hits_q) >= 1, f"query=少年 命中 (实际 {len(hits_q)})")
    hits_tag = ups.search_by_tags(tags=["重逢"])
    check(any(h["title"] == "旧友重逢" for h in hits_tag), "tags=重逢 命中")
    hits_none = ups.search_by_tags(genre="不存在")
    check(hits_none == [], "不存在 genre → 0 命中")

    # 4) bulk_import
    print("\n[4] 批量导入")
    batch = [
        "开篇：世界崩塌之日，幸存者在废墟中苏醒。",
        "转场：三年后，他在边境小镇开了一家茶馆。",
        "高潮：黑衣人推门而入，腰间令牌折射寒光。",
    ]
    imported = ups.bulk_import(batch, genre="末世", source="wiki")
    check(len(imported) == 3, f"批量导入 3 条 (实际 {len(imported)})")
    check(ups.count(genre="末世") == 3, f"末世分类 3 条 (实际 {ups.count(genre='末世')})")

    # 5) clone_to_project
    print("\n[5] 克隆进项目")
    proj = project_service.create("M3测试项目", book_title="M3书", create_books=True)
    pid = proj["id"]
    check(pid, f"项目创建成功 (id={pid})")

    unit_id = ups.clone_to_project(u1["id"], pid)
    check(unit_id, f"clone 返回 unit_id (实际 {unit_id})")
    cloned = usvc.get(unit_id)
    check(cloned.draft and cloned.draft.strip(), "克隆单元 draft 非空 (成稿可用)")
    check(cloned.draft == u1["content"], "draft 与池内容一致")
    # 段落已重建
    paras = usvc.get_paragraphs(unit_id)
    check(len(paras) >= 1, f"克隆单元段落已建 (实际 {len(paras)})")

    # 再克隆一个组成多单元
    u2_id = ups.clone_to_project(
        ups.search_by_tags(genre="仙侠", scene_type="战斗")[0]["id"], pid
    )

    # 6) assemble_units 成稿
    print("\n[6] assemble_units 连通性")
    ms = ma.assemble_units(pid, [unit_id, u2_id], timeline_mode="story")
    check(ms.merged_text.strip(), f"merged_text 非空 (实际 {len(ms.merged_text)} 字)")
    check(len(ms.segments) >= 1, f"段落级 segments ≥1 (实际 {len(ms.segments)})")
    check(all(s.unit_no for s in ms.segments), "segments 带 unit_no 标签")
    check(ms.units and len(ms.units) == 2, f"units 含 2 个克隆单元 (实际 {len(ms.units)})")

    # 7) update / delete 基本
    print("\n[7] update / delete")
    ups.update(u2["id"], title="截断后单元", emotion="平静")
    check(ups.get(u2["id"])["title"] == "截断后单元", "update 生效")
    before = ups.count()
    ups.delete(u2["id"])
    check(ups.count() == before - 1, "delete 生效")

    # 清理临时库
    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass

    print("\n" + "=" * 60)
    if not fails:
        print(f"M3 SMOKE PASS ({passed} assertions)")
        return 0
    else:
        print(f"M3 SMOKE FAIL ({len(fails)} failed):")
        for f in fails:
            print(f"  - {f}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
