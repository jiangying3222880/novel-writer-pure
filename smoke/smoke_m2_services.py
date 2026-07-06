"""
M2 SMOKE: 服务层集成测试 (Phase 2/3)
- 底层打补丁: app_paths.sqlite_path + file_store.BASE_DIR → tmpdir
- 验证服务层 CRUD: project / book / chapter / setting
- 验证 setting_service 读写 (明文 JSON)
- 验证 memory + pressure + anti_ai 在 service-managed 项目上跑通
- 验证 prompt_assembler 用真实 services 拼装 prompt
- 验证 AI engine 用 mock LLM 跑完整 chat
- 端到端: 创建项目 → 写设定 → 加记忆 → 拼 prompt → 调 mock LLM → 写后更新记忆

5 分钟自动超时 (threading.Timer, 跨平台, 防卡死)
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path

# stdout UTF-8 (Windows GBK 兼容)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 5 分钟全局超时 (smoke 卡死保护, Windows 兼容用 Timer)
_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_m2_services 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    print(f"[TIMEOUT] 请检查: 1) 终端输出最后一行  2) logs/NovelWriter_*.log  3) 是否被外部 IO 阻塞")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 测试前: 打补丁隔离真实数据
# ============================================================

TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_m2_"))
DB_PATH = TMPDIR / "test.db"
STORY_DIR = TMPDIR / "story"
STORY_DIR.mkdir(parents=True, exist_ok=True)

# 必须在 import app.* 之前打补丁
import app.app_paths
app.app_paths.sqlite_path = lambda: DB_PATH

# 还要 patch file_store.BASE_DIR (setting_service 通过它写明文 JSON)
# v4.0-P0-新: 同时 patch _base_dir (走 app_paths.get_story_dir 动态拿)
import app.services.file_store
app.services.file_store.BASE_DIR = STORY_DIR
app.services.file_store._base_dir = lambda: STORY_DIR  # 保持测试隔离

# 强制重建 services.db 内部连接 (它缓存了 sqlite_path() 调用结果)
# 第一次 _connect() 会在 service 第一次调用时触发, 此时 lambda 已被替换

# ============================================================
# 真正的 import (在补丁之后)
# ============================================================

from app.services import (
    project_service, book_service, chapter_service, setting_service,
    character_tracker, memory, pressure, anti_ai, memory_manager,
)
from app.services.exceptions import NotFoundError, ValidationError
from app.core import prompt_assembler
from app.ai import registry as ai_registry, engine as ai_engine
from app.core import event_bus
from app.core.event_bus import Events
from app.core.interfaces import LLMResult


# ============================================================
# 工具
# ============================================================

fails: list[str] = []
passed: int = 0


def check(cond, msg: str) -> None:
    global passed
    if cond:
        passed += 1
        print(f"  [PASS] {msg}")
    else:
        fails.append(msg)
        print(f"  [FAIL] {msg}")


def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def init_db() -> None:
    """初始化 DB (兼容 2 套 db 模块).

    1. app.services.db.init_db() — 跑 schema.sql + 全部迁移 + 跟踪 schema_migrations
       (用整数版本号, services.db 模块专属)
    2. app.db.connection.init() — memory / character_tracker / ai.registry 用的
       连接单例, 只需要 init 拿到 conn, schema/迁移由 services.db 搞定
    """
    from app.db import connection
    from app.services import db as svc_db

    # 先用 services.db 跑 schema + 迁移 (统一跟踪)
    svc_db.init_db()

    # 再开 app.db.connection 单例 (memory / tracker / registry 用)
    connection.init(DB_PATH)


# ============================================================
# 测试 1: project_service CRUD
# ============================================================

def test_1_project_service() -> None:
    section("[1] project_service CRUD")
    p = project_service.create("测试小说-修真纪元", book_title="第一卷: 觉醒", genre="仙侠", word_target=200000)
    check("id" in p and len(p["id"]) == 36, f"返回 uuid id (实际 {p.get('id', '')[:8]}...)")
    check(p["name"] == "测试小说-修真纪元", "name 保存成功")
    check(p["genre"] == "仙侠", "genre 保存成功")
    check(p["word_target"] == 200000, "word_target 保存成功")

    # get
    p2 = project_service.get(p["id"])
    check(p2["name"] == p["name"], "get 返回正确")

    # 404
    try:
        project_service.get("not_exists_id")
        check(False, "404 应抛 NotFoundError")
    except NotFoundError:
        check(True, "NotFoundError 正确抛出")

    # list
    project_service.create("项目2", genre="都市")
    project_service.create("项目3", genre="悬疑")
    all_p = project_service.list_all()
    check(all_p["total"] >= 3, f"list_all 至少 3 个 (实际 {all_p['total']})")


# ============================================================
# 测试 2: book_service + chapter_service
# ============================================================

def test_2_book_chapter_service() -> None:
    section("[2] book_service + chapter_service")
    # 取刚才的项目
    all_p = project_service.list_all()
    pid = all_p["projects"][0]["id"]

    # project_service.create() 默认会自动创建一个 book (V4.0-P2 新行为),
    # 所以这里直接用 list_for_project 拿自动创建的那个 book
    books = book_service.list_for_project(pid)["books"]
    check(len(books) == 1, f"自动创建 1 个 book (实际 {len(books)})")
    b_id = books[0]["id"]
    b = book_service.get(b_id)
    check(b["title"].startswith("第一卷"), f"book title='{b['title']}'")

    # chapter
    c1 = chapter_service.create(b["id"], 1, title="破庙孤儿", scene_context="夜雨破庙")
    check("id" in c1, "chapter 创建成功")
    check(c1["status"] == "draft", f"status = draft (实际 {c1['status']})")
    check(c1["title"] == "破庙孤儿", "chapter title 正确")

    # 批量建章节
    for i in range(2, 6):
        chapter_service.create(b["id"], i, title=f"第{i}章")
    chapters = chapter_service.list_for_book(b["id"])
    check(chapters["total"] == 5, f"5 个章节 (实际 {chapters['total']})")

    # chapter brief
    chapter_service.upsert_brief(
        c1["id"],
        brief="主角在破庙中觉醒血脉",
        core_events="觉醒",
        emotion_arc="迷茫→震惊",
    )
    brief = chapter_service.get_brief(c1["id"])
    check("破庙" in brief["brief"], "brief 已写入")

    # 404 链: 删项目后 book 应 404
    fake_pid = "p_" + uuid.uuid4().hex[:6]
    fake_bid = "b_" + uuid.uuid4().hex[:6]
    from app.db import connection
    conn = connection.get_conn()
    conn.execute("INSERT INTO projects (id, name) VALUES (?, ?)", (fake_pid, "幻影项目"))
    conn.execute("INSERT INTO books (id, project_id, volume_no) VALUES (?, ?, ?)", (fake_bid, fake_pid, 1))
    try:
        book_service.get(fake_bid)  # OK
        # 直接删 project
        conn.execute("DELETE FROM projects WHERE id = ?", (fake_pid,))
        book_service.get(fake_bid)  # 应 404 (FK cascade)
        check(False, "FK cascade 后 book 应 404")
    except NotFoundError:
        check(True, "book 404 链正确")


# ============================================================
# 测试 3: setting_service (JSON 文件存储)
# ============================================================

def test_3_setting_service() -> None:
    section("[3] setting_service (明文 JSON)")
    pid = project_service.list_all()["projects"][0]["id"]

    # 写
    setting_service.set_setting(pid, "worldbuilding", {
        "items": [
            {"name": "修真界", "desc": "九境修炼体系"},
            {"name": "天道", "desc": "本界不允许跨界"},
        ]
    })
    check((STORY_DIR / f"project_{pid}" / "worldbuilding.json").exists(), "worldbuilding.json 已创建")

    # 读
    s = setting_service.get_setting(pid, "worldbuilding")
    check(len(s["data"]["items"]) == 2, f"worldbuilding 含 2 项 (实际 {len(s['data']['items'])})")

    # 改 style_fingerprint
    setting_service.set_setting(pid, "style_fingerprint", {
        "sentence_rhythm": "长短句交替",
        "vocabulary": "古风雅致",
        "view_point": "第三人称",
        "tone": "沉稳",
        "pacing": "舒缓",
    })
    s2 = setting_service.get_setting(pid, "style_fingerprint")
    check(s2["data"]["sentence_rhythm"] == "长短句交替", "style_fingerprint 读写一致")

    # 改 anti_rules
    setting_service.set_setting(pid, "anti_rules", [
        "不写网文套话",
        "不强行制造冲突",
    ])
    s3 = setting_service.get_setting(pid, "anti_rules")
    check(len(s3["data"]) == 2, f"anti_rules 2 条 (实际 {len(s3['data'])})")

    # 非法 key
    try:
        setting_service.set_setting(pid, "bogus_key", "x")
        check(False, "非法 key 应 ValidationError")
    except ValidationError:
        check(True, "非法 key ValidationError 正确")

    # 404 项目
    try:
        setting_service.set_setting("p_fake_xxx", "worldbuilding", {})
        check(False, "404 项目应 NotFoundError")
    except NotFoundError:
        check(True, "404 项目 NotFoundError 正确")


# ============================================================
# 测试 4: memory + pressure + anti_ai with real project
# ============================================================

def test_4_memory_pressure_anti_ai() -> None:
    section("[4] memory + pressure + anti_ai (真实项目)")
    pid = project_service.list_all()["projects"][0]["id"]
    chapters = chapter_service.list_for_book(book_service.list_for_project(pid)["books"][0]["id"])["chapters"]
    cids = [c["id"] for c in chapters]

    # L1 故事弧
    memory.add_arc(pid, memory.CAT_ARC_MAIN, "主角觉醒血脉踏上修真路", chapter_id=cids[0])
    memory.add_arc(pid, memory.CAT_ARC_SUB, "副线: 师傅身世之谜", chapter_id=cids[1])
    # L2 承诺 + 世界规则
    memory.add_commitment(pid, "答应师傅一年内突破筑基", kind="promise", chapter_id=cids[1])
    memory.add_commitment(pid, "营救被困同门(已触发)", kind="active", chapter_id=cids[2])
    memory.add_world_rule(pid, "修真分九境: 练气→筑基→金丹→元婴→化神→炼虚→合体→大乘→渡劫", kind="power")
    # L3 RAG chunk
    memory.add_rag_chunk(pid, "破庙中的老者传授心法", chapter_id=cids[0], ref_id="kb_001")
    # L4 遗忘 (测试添加 + 读取)
    memory.add(pid, memory.CAT_FADED, "已淡化的旧设定", chapter_id=cids[2])

    # 验证都能读到
    arcs = memory.list_by_category(pid, memory.CAT_ARC_MAIN) + memory.list_by_category(pid, memory.CAT_ARC_SUB)
    check(len(arcs) >= 2, f"故事弧 ≥ 2 (实际 {len(arcs)})")
    active = memory.get_active_commitments(pid)
    open_promises = memory.get_open_promises(pid)
    check(len(active) == 1, f"active 承诺 1 (实际 {len(active)})")
    check(len(open_promises) == 1, f"promise 承诺 1 (实际 {len(open_promises)})")
    rules = memory.list_by_category(pid, memory.CAT_WORLD_POWER)
    check(len(rules) == 1, f"世界规则 1 (实际 {len(rules)})")
    rag = memory.list_by_level(pid, memory.MemoryLevel.L3_RAG)
    check(len(rag) == 1, f"RAG 1 (实际 {len(rag)})")
    faded = memory.list_by_level(pid, memory.MemoryLevel.L4_FADE)
    check(len(faded) == 1, f"L4 遗忘 1 (实际 {len(faded)})")

    # pressure (compute_pressure 接纯数字分量, 不接 project_id)
    from app.services.pressure import compute_zone, PressureZone, compute_pressure
    p_val = compute_pressure(active_hooks=1, open_promises=1, unresolved_subplots=0)
    zone = compute_zone(p_val)
    check(zone in {"green", "yellow", "orange", "red"}, f"zone 合法 (实际 {zone})")
    check(p_val > 0, f"pressure > 0 (实际 {p_val})")

    # anti_ai
    text = "她笑了一下, 说: '我懂了'. 然后转身离开. " * 5
    issues = anti_ai.run_all(text, expected_pov="third")
    check(isinstance(issues, list), f"anti_ai 返回 list (实际 {type(issues).__name__})")


# ============================================================
# 测试 5: memory_manager 完整周期
# ============================================================

def test_5_memory_manager() -> None:
    section("[5] memory_manager 完整周期")
    pid = project_service.list_all()["projects"][0]["id"]
    chapters = chapter_service.list_for_book(book_service.list_for_project(pid)["books"][0]["id"])["chapters"]
    cids = [c["id"] for c in chapters]

    # 1) 写前拼装
    bundle = memory_manager.assemble_for_writing(pid, cids[3])
    check(hasattr(bundle, "full_text"), "assemble 返回 AssembleResult 对象")
    check(len(bundle.full_text) > 0, f"拼装文本非空 (实际 {len(bundle.full_text)} 字)")

    # 2) 决策
    can_proceed, msg = memory_manager.can_proceed(pid, cids[3])
    check(isinstance(can_proceed, bool), f"can_proceed 返回 bool (实际 {can_proceed})")

    # 3) 模拟写作后
    draft = (
        "雨声潇潇. 少年跪在破庙前, 双手合十, 眼眶通红. "
        "老者将一卷泛黄的竹简递到他面前, 沉声道: '此乃本门心法, "
        "你若能在一年内筑基, 我便带你离开.' "
    ) * 2
    result = memory_manager.after_writing(pid, cids[3], draft)
    check(hasattr(result, "faded_count"), "after_writing 返回 result")
    check(result.faded_count >= 0, f"faded_count ≥ 0 (实际 {result.faded_count})")

    # 4) 预览 (用于 dashboard)
    preview = memory_manager.preview(pid, cids[3])
    check(isinstance(preview, dict), "preview 返回 dict")
    check("pressure" in preview, "preview 含 pressure 字段")
    check("characters" in preview, "preview 含 characters 字段")
    check("full_text_chars" in preview, "preview 含 full_text_chars 字段")


# ============================================================
# 测试 6: prompt_assembler (用真实 services)
# ============================================================

def test_6_prompt_assembler() -> None:
    section("[6] prompt_assembler (真实 services)")
    pid = project_service.list_all()["projects"][0]["id"]
    chapters = chapter_service.list_for_book(book_service.list_for_project(pid)["books"][0]["id"])["chapters"]
    cids = [c["id"] for c in chapters]

    # 写 brief
    chapter_service.upsert_brief(
        cids[2],
        brief="主角在山巅接受传承, 体内真气暴涨",
        core_events="觉醒血脉 | 接受传承",
        emotion_arc="震惊→坚定",
    )

    # 拼装
    prompt = prompt_assembler.assemble_writer_prompt(pid, cids[2])
    check("system" in prompt, "返回 system 字段")
    check("user" in prompt, "返回 user 字段")
    check(len(prompt["system"]) > 0, f"system 非空 (实际 {len(prompt['system'])} 字)")
    check("第" in prompt["user"] and "章" in prompt["user"], "user 含章节号")
    check("风格指纹" in prompt["system"] or "反规则" in prompt["system"], "system 含 style/anti")
    check("世界观" in prompt["user"] or "大纲" in prompt["user"], "user 含 world/brief")

    # 携带 mindset_dict
    prompt2 = prompt_assembler.assemble_writer_prompt(
        pid, cids[2],
        mindset_dict={"conflict": "内外冲突", "hook": "山巅传承"},
    )
    check("冲突" in prompt2["user"] or "conflict" in prompt2["user"], "user 含 mindset_dict")


# ============================================================
# 测试 7: AI engine (mock LLM) 集成
# ============================================================

def test_7_ai_engine_mock() -> None:
    section("[7] AI engine (mock LLM)")
    # 注册 2 个模型 (primary + fallback)
    reg = ai_registry.get_registry()
    reg.init_defaults()
    reg.reload()
    primary = reg.get_primary()
    primary.api_key = "sk-primary"
    primary.input_price = 1.0
    primary.output_price = 2.0
    reg.save(primary)
    fallback = reg.get_fallback()
    fallback.api_key = "sk-fallback"
    reg.save(fallback)
    reg.reload()
    check(len(reg.list_enabled()) >= 2, f"启用模型 ≥ 2 (实际 {len(reg.list_enabled())})")

    # mock create_client
    from app.ai import providers
    original_factory = providers.create_client
    def mock_factory(config):
        class MockClient:
            def __init__(self, cfg):
                self.cfg = cfg
                self.provider = cfg.provider
                self.model_name = cfg.model_name
            def chat(self, messages, **kwargs):
                if getattr(self.cfg, "_fail", False):
                    raise RuntimeError(f"mock fail: {self.cfg.id}")
                return LLMResult(
                    content=f"mock reply from {self.cfg.model_name}",
                    model=self.cfg.model_name,
                    provider=self.cfg.provider,
                    input_tokens=10, output_tokens=20,
                )
        return MockClient(config)
    providers.create_client = mock_factory
    try:
        engine = ai_engine.get_engine()
        events: list[str] = []
        event_bus.subscribe(Events.MODEL_USED, lambda e: events.append("used"))

        result = engine.chat(
            [{"role": "user", "content": "hi"}],
            task="m2_test",
        )
        check("mock reply" in result.content, f"primary 成功 (实际 {result.content[:30]})")
        check(result.cost > 0, f"cost > 0 (实际 {result.cost})")
        check("used" in events, "MODEL_USED 事件已派发")
    finally:
        providers.create_client = original_factory


# ============================================================
# 测试 8: 端到端 pipeline
# ============================================================

def test_8_e2e_pipeline() -> None:
    section("[8] 端到端 pipeline (项目→书→章→记忆→拼 prompt→mock LLM)")
    pid = project_service.list_all()["projects"][0]["id"]
    bid = book_service.list_for_project(pid)["books"][0]["id"]
    chapters = chapter_service.list_for_book(bid)["chapters"]
    target_cid = chapters[2]["id"]  # 第 3 章

    # 1) 已有 worldbuilding / style_fingerprint / anti_rules (test_3 写入)

    # 2) 记录主角状态 (character_tracker)
    #    注意: record 签名 = (project_id, chapter_id, character_name, **kwargs)
    character_tracker.record(
        pid, target_cid, "林轩",
        location="破庙",
        state="觉醒前",
        power_level="凡人",
        equipment="无",
        relationship="老乞丐=恩人",
    )

    # 3) 添加本章关键记忆
    memory.add_arc(pid, memory.CAT_ARC_CHAR, "主角从自卑到自信", chapter_id=target_cid)

    # 4) 拼装 prompt
    prompt = prompt_assembler.assemble_writer_prompt(pid, target_cid)
    check(len(prompt["system"]) + len(prompt["user"]) > 100, "拼装 prompt 长度合理")

    # 5) mock LLM "生成"
    from app.ai import providers
    original_factory = providers.create_client
    def mock_factory(config):
        class MockClient:
            def __init__(self, cfg):
                self.cfg = cfg
                self.provider = cfg.provider
                self.model_name = cfg.model_name
            def chat(self, messages, **kwargs):
                return LLMResult(
                    content="林轩睁开眼, 体内真气翻涌, 老者点头微笑.",
                    model=self.cfg.model_name,
                    provider=self.cfg.provider,
                    input_tokens=len(messages[0]["content"]),
                    output_tokens=50,
                )
        return MockClient(config)
    providers.create_client = mock_factory
    try:
        engine = ai_engine.get_engine()
        result = engine.chat(
            [{"role": "system", "content": prompt["system"]},
             {"role": "user", "content": prompt["user"]}],
            task="chapter_write",
        )
        check("林轩" in result.content, "mock 生成含主角名")
        check(result.input_tokens > 0, f"input_tokens > 0 (实际 {result.input_tokens})")
    finally:
        providers.create_client = original_factory

    # 6) 写后更新角色状态
    character_tracker.record(
        pid, chapters[3]["id"], "林轩",
        location="破庙",
        state="已觉醒",
        power_level="练气一层",
        equipment="无名心法",
        relationship="老乞丐=师傅",
    )

    # 7) diff (对比第 3 章 vs 第 4 章) — 注意: diff 需要 project_id 作为第一参数
    diffs = character_tracker.diff(pid, "林轩", target_cid, chapters[3]["id"])
    changed_dims = {d.dim for d in diffs if d.changed}
    check("state" in changed_dims, "state 维度已变")
    check("power_level" in changed_dims, "power_level 维度已变")
    check("relationship" in changed_dims, "relationship 维度已变")

    # 8) 写后用 memory_manager 走一轮 (fade 旧 RAG 等)
    bundle = memory_manager.assemble_for_writing(pid, chapters[4]["id"])
    check(len(bundle.full_text) > 0, "下一章仍能拼装")


# ============================================================
# Main
# ============================================================

def main() -> int:
    print("=" * 60)
    print("M2 SMOKE: 服务层集成测试 (Phase 2/3)")
    print("=" * 60)
    print(f"[setup] tmpdir = {TMPDIR}")

    init_db()
    print(f"[setup] DB = {DB_PATH}")
    print(f"[setup] story = {STORY_DIR}")

    # M3-A: 把真实 services 注册到 container, 这样 L0 core 能通过 Protocol 拿到
    from app.core.wiring import wire_default_services
    wire_default_services()

    tests = [
        test_1_project_service,
        test_2_book_chapter_service,
        test_3_setting_service,
        test_4_memory_pressure_anti_ai,
        test_5_memory_manager,
        test_6_prompt_assembler,
        test_7_ai_engine_mock,
        test_8_e2e_pipeline,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            fails.append(f"{t.__name__} 异常")
            print(f"\n✗ {t.__name__}: EXCEPTION — {type(e).__name__}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"通过: {passed}    失败: {len(fails)}")
    if fails:
        print("\n失败列表:")
        for f in fails:
            print(f"  - {f}")
        print("=" * 60)
        return 1
    print(f"全部 {passed} 项检查通过 ✓")
    print("=" * 60)
    return 0


def _cleanup() -> None:
    """测试结束后清理 (Windows 锁容错)."""
    import time
    try:
        from app.db import connection
        connection.close()
    except Exception:
        pass
    try:
        from app.services import db as svc_db
        # 关掉 services.db 的连接
        if hasattr(svc_db, "_local"):
            conn = getattr(svc_db._local, "conn", None)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    except Exception:
        pass
    time.sleep(0.1)
    for ext in ("", "-wal", "-shm"):
        f = DB_PATH.parent / f"{DB_PATH.name}{ext}"
        if f.exists():
            try:
                f.unlink()
            except (PermissionError, OSError):
                pass
    # 删 story
    import shutil
    try:
        shutil.rmtree(STORY_DIR, ignore_errors=True)
    except Exception:
        pass
    try:
        TMPDIR.rmdir()
    except (PermissionError, OSError):
        pass


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        _cleanup()
    sys.exit(rc)
