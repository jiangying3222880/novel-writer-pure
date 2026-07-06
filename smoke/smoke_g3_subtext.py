"""
G3 SUBTEXT SMOKE: 潜文本卡
- 6 预置模板 seed + 列表
- 项目级模式 3 种 (ai_auto / manual / closed)
- 章节级卡 CRUD (13 字段)
- AI 自动模式 (含智能跳过过渡章)
- 手动模式 (模板填充)
- 关闭模式 (清后续章节的卡)
- prompt 拼装 (供 G1 引擎)
- 统计 + 状态符号

5 分钟自动超时
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

# stdout UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 5 分钟全局超时
_SMOKE_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_g3_subtext 超时 {_SMOKE_TIMEOUT}s, 强制退出")
    os._exit(2)
_timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
_timer.daemon = True
_timer.start()

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ============================================================
# 隔离真实数据
# ============================================================

TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_g3_"))
DB_PATH = TMPDIR / "test.db"
STORY_DIR = TMPDIR / "story"
STORY_DIR.mkdir(parents=True, exist_ok=True)

import app.app_paths
app.app_paths.sqlite_path = lambda: DB_PATH

import app.services.file_store
app.services.file_store.BASE_DIR = STORY_DIR

# ============================================================
# 真正的 import
# ============================================================

from app.services import (
    subtext, project_service, book_service, chapter_service,
)
from app.services.db import init_db
from app.services.exceptions import NotFoundError, ValidationError


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


# ============================================================
# 测试 1: 6 预置模板 seed + 列表
# ============================================================

def test_1_seed_presets() -> None:
    section("[1] 6 预置模板 seed + 列表")
    inserted = subtext.seed_presets()
    check(inserted == 6, f"seed 6 个模板 (实际 {inserted})")
    inserted2 = subtext.seed_presets()  # 二次 seed 应幂等
    check(inserted2 == 0, f"二次 seed 幂等 (实际 {inserted2})")

    presets = subtext.list_presets()
    check(len(presets) == 6, f"列 6 个 (实际 {len(presets)})")

    names = [p["name"] for p in presets]
    expected = ["对峙", "离别", "暧昧", "反转", "重逢", "隐瞒"]
    for exp in expected:
        check(exp in names, f"模板 '{exp}' 存在")

    # 单个模板
    t = subtext.get_preset("tpl_confrontation")
    check(t.get("name") == "对峙", f"对峙模板 name (实际 {t.get('name')})")
    check("emotional" in t, f"对峙有 emotional 字段 (实际 keys: {list(t.keys())})")

    # 404
    try:
        subtext.get_preset("tpl_bogus")
        check(False, "404 应 NotFoundError")
    except NotFoundError:
        check(True, "NotFoundError 正确")


# ============================================================
# 测试 2: 13 字段定义完整
# ============================================================

def test_2_field_definitions() -> None:
    section("[2] 13 字段定义 + 帮助 (手动模式 hover)")
    check(len(subtext.SUBTEXT_FIELDS) == 13, f"13 字段 (实际 {len(subtext.SUBTEXT_FIELDS)})")

    expected_fields = [
        "surface_event", "true_intent", "real_intent_others", "lie", "truth",
        "emotional", "pacing", "viewpoint", "anti_rules", "callback_to",
        "scene_map", "physical_anchor", "ending_scene_state",
    ]
    for f in expected_fields:
        check(f in subtext.SUBTEXT_FIELDS, f"字段 {f} 在列表中")

    # FIELD_HELP 覆盖 13 字段
    for f in expected_fields:
        check(f in subtext.FIELD_HELP, f"FIELD_HELP[{f}] 存在")
        help_info = subtext.FIELD_HELP[f]
        check("label" in help_info and "hint" in help_info and "example" in help_info,
              f"FIELD_HELP[{f}] 3 项齐全")


# ============================================================
# 测试 3: 项目级模式 3 种
# ============================================================

def test_3_project_modes(pid: str) -> None:
    section("[3] 项目级模式 (3 种)")

    # 默认 ai_auto
    mode = subtext.get_project_mode(pid)
    check(mode["mode"] == subtext.MODE_AI_AUTO, f"默认 ai_auto (实际 {mode['mode']})")

    # 切到 manual
    subtext.set_project_mode(pid, subtext.MODE_MANUAL, template_id="tpl_confrontation")
    mode = subtext.get_project_mode(pid)
    check(mode["mode"] == subtext.MODE_MANUAL, f"切到 manual (实际 {mode['mode']})")
    check(mode["template_id"] == "tpl_confrontation", f"默认模板 (实际 {mode['template_id']})")

    # 非法模式
    try:
        subtext.set_project_mode(pid, "bogus")
        check(False, "非法模式应 ValidationError")
    except ValidationError:
        check(True, "ValidationError 正确")

    # manual + 非法模板
    try:
        subtext.set_project_mode(pid, subtext.MODE_MANUAL, template_id="tpl_bogus")
        check(False, "非法模板应 NotFoundError")
    except NotFoundError:
        check(True, "NotFoundError 正确")

    # 切到 closed
    subtext.set_project_mode(pid, subtext.MODE_CLOSED)
    check(subtext.get_project_mode(pid)["mode"] == subtext.MODE_CLOSED, "切到 closed")

    # 切回 ai_auto (给后续测试用)
    subtext.set_project_mode(pid, subtext.MODE_AI_AUTO)


# ============================================================
# 测试 4: 章节级卡 CRUD (13 字段)
# ============================================================

def test_4_chapter_card_crud(pid: str) -> None:
    section("[4] 章节级卡 CRUD (13 字段)")

    p = project_service.create("Subtext测试", genre="仙侠")
    pj = p["id"]
    b = book_service.create(pj, 1, title="V1")
    c = chapter_service.create(b["id"], 1, title="第1章 破庙")
    cid = c["id"]

    # 取无卡
    none_card = subtext.get_card_for_chapter(cid)
    check(none_card is None, "新章节无卡")

    # upsert 全字段
    card = subtext.upsert_card(
        cid,
        surface_event="林轩在破庙中醒来",
        true_intent="想弄清楚自己为何穿越",
        real_intent_others="老乞丐想收他为徒",
        lie="对师傅说'晚辈只想安稳修炼'",
        truth="林轩是转世重修者",
        emotional="迷茫 + 警觉",
        pacing="缓起 → 试探 → 急转",
        viewpoint="第三人称限知·林轩",
        anti_rules="",
        callback_to="呼应第 0 章预言",
        scene_map="破庙 · 雨夜",
        physical_anchor="玄铁剑",
        ending_scene_state="林轩身世初露",
        source="manual",
    )
    check(card.id.startswith("st_"), f"卡 id 前缀 st_ (实际 {card.id[:3]})")
    check(card.surface_event == "林轩在破庙中醒来", "surface_event 正确")
    check(card.true_intent == "想弄清楚自己为何穿越", "true_intent 正确")
    check(card.source == "manual", f"source=manual (实际 {card.source})")
    check(card.updated_at != "", "updated_at 已自动设置")

    # chapters.has_subtext 标记
    ch_row = chapter_service.get(cid)
    check(ch_row is not None, "chapters 行存在")
    if ch_row is not None:
        check(ch_row.get("has_subtext") == 1, f"chapters.has_subtext=1 (实际 {ch_row.get('has_subtext')})")
        check(ch_row.get("subtext_mode") == "manual", f"chapters.subtext_mode=manual")

    # update 部分字段
    card2 = subtext.upsert_card(cid, emotional="困惑 + 隐忍", pacing="极缓 → 急停")
    check(card2.id == card.id, "upsert 应保留原 id")
    check(card2.emotional == "困惑 + 隐忍", f"update emotional (实际 {card2.emotional})")
    check(card2.surface_event == "林轩在破庙中醒来", "surface_event 保留")

    # 非法字段
    try:
        subtext.upsert_card(cid, bogus_field="x")
        check(False, "非法字段应 ValidationError")
    except ValidationError:
        check(True, "ValidationError 正确")

    # 校验字段总数 (留 anti_rules="" 空, 13 字段应 ≥ 12 非空)
    all_fields_set = sum(1 for f in subtext.SUBTEXT_FIELDS if getattr(card2, f))
    check(all_fields_set == 12, f"12 字段非空 (anti_rules 故意空, 实际 {all_fields_set})")

    # delete
    deleted = subtext.delete_card(cid)
    check(deleted, "delete 返回 True")
    check(subtext.get_card_for_chapter(cid) is None, "删除后无卡")
    ch_row2 = chapter_service.get(cid)
    if ch_row2 is not None:
        check(ch_row2.get("has_subtext") == 0, "chapters.has_subtext 清 0")


# ============================================================
# 测试 5: AI 自动模式 (含跳过过渡章)
# ============================================================

def test_5_ai_auto_mode(pid: str) -> None:
    section("[5] AI 自动模式 (含跳过过渡章)")

    p = project_service.create("AI自动测试", genre="仙侠")
    pj = p["id"]
    b = book_service.create(pj, 1, title="V1")

    # 短章 (过渡) → 跳过
    c1 = chapter_service.create(b["id"], 1, title="短章")
    try:
        subtext.auto_generate(pj, c1["id"], "简短过渡", word_count=500)
        check(False, "短章应跳过")
    except ValidationError as e:
        check("过渡" in str(e), f"过渡章跳过提示: {e}")

    # 正常章
    c2 = chapter_service.create(b["id"], 2, title="正章")
    card = subtext.auto_generate(pj, c2["id"], "林轩在破庙中觉醒, 持玄铁剑, 师傅给筑基丹",
                                  word_count=3000)
    check(card.source == "ai_auto", f"source=ai_auto (实际 {card.source})")
    check(card.surface_event != "", "surface_event 已填")
    check("林轩" in card.surface_event, f"surface_event 含 brief 内容 (实际 {card.surface_event})")
    check(card.viewpoint != "", "viewpoint 已填")
    check(card.pacing != "", "pacing 已填")

    # 二次 auto_generate 应保留 id (upsert)
    card2 = subtext.auto_generate(pj, c2["id"], "新 brief", word_count=3000)
    check(card2.id == card.id, "二次调用应保留 id")

    # chapters 标记
    ch_row = chapter_service.get(c2["id"])
    if ch_row is not None:
        check(ch_row.get("subtext_mode") == "ai_auto", f"subtext_mode=ai_auto")


# ============================================================
# 测试 6: 手动模式 (模板填充)
# ============================================================

def test_6_manual_mode(pid: str) -> None:
    section("[6] 手动模式 (模板填充)")

    p = project_service.create("手动模式测试", genre="仙侠")
    pj = p["id"]
    b = book_service.create(pj, 1, title="V1")
    c = chapter_service.create(b["id"], 1, title="第1章 对峙")
    cid = c["id"]

    # 切到 manual
    subtext.set_project_mode(pj, subtext.MODE_MANUAL, template_id="tpl_confrontation")

    # 模板填充
    card = subtext.apply_template(cid, "tpl_confrontation", brief="林轩与王师兄演武场对峙")
    check(card.source == "template", f"source=template (实际 {card.source})")
    check(card.template_id == "tpl_confrontation", f"template_id 正确")
    check("{地点}" in card.scene_map or "地点" in card.scene_map, f"scene_map 有占位/字段")
    check("{物件}" in card.physical_anchor or "物件" in card.physical_anchor, "physical_anchor 有占位/字段")
    check("压抑" in card.emotional, "emotional 来自模板")
    check("试探" in card.pacing, "pacing 来自模板")
    check("林轩" in card.surface_event, f"brief 已塞进 surface_event (实际 {card.surface_event})")

    # 用户再改
    card2 = subtext.upsert_card(cid, surface_event="林轩与王师兄雨中对峙",
                                 emotional="压抑 + 紧张 + 表面平静")
    check(card2.surface_event == "林轩与王师兄雨中对峙", "用户改 surface_event")
    check(card2.emotional == "压抑 + 紧张 + 表面平静", "用户改 emotional")
    check(card2.scene_map != "", "scene_map 仍保留模板内容")


# ============================================================
# 测试 7: 关闭模式 (清后续章节的卡, 旧章节的卡保留)
# ============================================================

def test_7_closed_mode(pid: str) -> None:
    section("[7] 关闭模式 (清后续章节的卡)")

    p = project_service.create("关闭测试", genre="仙侠")
    pj = p["id"]
    b = book_service.create(pj, 1, title="V1")

    # 旧章节: 写过了
    c_old = chapter_service.create(b["id"], 1, title="已写章节")
    cid_old = c_old["id"]
    draft_old = chapter_service.create_draft(cid_old, "这是已写章节, 长度超过 500 字, 有内容. " * 30, source="user")
    chapter_service.set_current_draft(cid_old, draft_old["id"])

    # 新章节: 没写
    c_new = chapter_service.create(b["id"], 2, title="未写章节")
    cid_new = c_new["id"]

    # 都生成卡
    subtext.auto_generate(pj, cid_old, "旧章节", word_count=2000)
    subtext.auto_generate(pj, cid_new, "新章节", word_count=2000)

    # 切到 closed
    subtext.set_project_mode(pj, subtext.MODE_CLOSED)
    cleared = subtext.close_after(pj)
    check(cleared >= 1, f"清后续章 ≥ 1 (实际 {cleared})")

    # 旧章节的卡应保留
    card_old = subtext.get_card_for_chapter(cid_old)
    check(card_old is not None, "旧章节的卡保留 (按决策)")
    # 新章节的卡应清
    card_new = subtext.get_card_for_chapter(cid_new)
    check(card_new is None, "新章节的卡已清")


# ============================================================
# 测试 8: prompt 拼装 (给 G1 引擎 / 段落重写用)
# ============================================================

def test_8_prompt_assembly(pid: str) -> None:
    section("[8] prompt 拼装 (给 G1 引擎 / 段落重写)")

    p = project_service.create("Prompt测试", genre="仙侠")
    pj = p["id"]
    b = book_service.create(pj, 1, title="V1")
    c = chapter_service.create(b["id"], 1, title="第1章")
    cid = c["id"]

    # 无卡
    result = subtext.assemble_for_prompt(cid)
    check(result["has_card"] is False, "无卡 has_card=False")

    # 有卡
    subtext.upsert_card(
        cid,
        surface_event="林轩觉醒",
        true_intent="查身世",
        emotional="警觉",
        source="manual",
    )
    result = subtext.assemble_for_prompt(cid)
    check(result["has_card"] is True, "有卡 has_card=True")
    check(result["source"] == "manual", f"source=manual (实际 {result['source']})")
    check("surface_event" in result["fields"], "fields 含 surface_event")
    check("林轩觉醒" in result["non_empty_fields"] or
          result["fields"]["surface_event"] == "林轩觉醒", "非空字段已识别")
    check(len(result["non_empty_fields"]) >= 3, f"非空字段 ≥ 3 (实际 {len(result['non_empty_fields'])})")


# ============================================================
# 测试 9: 状态符号 + 列表
# ============================================================

def test_9_status_mark(pid: str) -> None:
    section("[9] 章节状态符号 (章节管理 tab 用)")

    p = project_service.create("标记测试", genre="仙侠")
    pj = p["id"]
    b = book_service.create(pj, 1, title="V1")
    c1 = chapter_service.create(b["id"], 1, title="第1章")
    c2 = chapter_service.create(b["id"], 2, title="第2章")
    c3 = chapter_service.create(b["id"], 3, title="第3章")

    # c1 有卡
    subtext.upsert_card(c1["id"], surface_event="x", source="ai_auto")
    # c3 有卡
    subtext.upsert_card(c3["id"], surface_event="z", source="manual")

    chapters = subtext.list_chapters_with_subtext_mark(b["id"])
    check(len(chapters) == 3, f"3 章节 (实际 {len(chapters)})")

    c1m = next((c for c in chapters if c["id"] == c1["id"]), None)
    c2m = next((c for c in chapters if c["id"] == c2["id"]), None)
    c3m = next((c for c in chapters if c["id"] == c3["id"]), None)
    check(c1m is not None and c1m["has_subtext"] is True, "c1 has_subtext=True")
    check(c2m is not None and c2m["has_subtext"] is False, "c2 has_subtext=False")
    check(c3m is not None and c3m["has_subtext"] is True, "c3 has_subtext=True")
    check(subtext.SUBTEXT_MARK in c1m["title"], f"c1 title 含 🎭 (实际 {c1m['title']})")
    check(subtext.SUBTEXT_MARK not in c2m["title"], "c2 title 不含 🎭")
    check(subtext.SUBTEXT_MARK in c3m["title"], f"c3 title 含 🎭 (实际 {c3m['title']})")


# ============================================================
# 测试 10: 统计 + 整合
# ============================================================

def test_10_stats_and_integration(pid: str) -> None:
    section("[10] 统计 + 整合")

    p = project_service.create("统计测试", genre="仙侠")
    pj = p["id"]
    b = book_service.create(pj, 1, title="V1")

    subtext.set_project_mode(pj, subtext.MODE_AI_AUTO)
    stats0 = subtext.stats(pj)
    check(stats0["total_cards"] == 0, f"0 卡 (实际 {stats0['total_cards']})")
    check(stats0["mode_label"] == "AI 自动", f"mode_label=AI 自动 (实际 {stats0['mode_label']})")

    # 加卡
    c1 = chapter_service.create(b["id"], 1, title="c1")
    c2 = chapter_service.create(b["id"], 2, title="c2")
    subtext.auto_generate(pj, c1["id"], "a", word_count=2000)
    subtext.apply_template(c2["id"], "tpl_farewell", brief="b")

    stats1 = subtext.stats(pj)
    check(stats1["total_cards"] == 2, f"2 卡 (实际 {stats1['total_cards']})")
    check(stats1["chapters_with_subtext"] == 2, f"2 章节用 subtext (实际 {stats1['chapters_with_subtext']})")


# ============================================================
# Main
# ============================================================

def main() -> int:
    print("=" * 60)
    print("G3 SUBTEXT SMOKE: 潜文本卡 (3 模式 + 13 字段 + 6 模板)")
    print("=" * 60)
    print(f"[setup] tmpdir = {TMPDIR}")

    init_db()
    from app.db import connection
    connection.init(DB_PATH)
    print(f"[setup] DB = {DB_PATH}")

    p0 = project_service.create("G3 init project", genre="仙侠")
    pid = p0["id"]
    print(f"[setup] project_id = {pid}")

    tests = [
        lambda: test_1_seed_presets(),
        lambda: test_2_field_definitions(),
        lambda: test_3_project_modes(pid),
        lambda: test_4_chapter_card_crud(pid),
        lambda: test_5_ai_auto_mode(pid),
        lambda: test_6_manual_mode(pid),
        lambda: test_7_closed_mode(pid),
        lambda: test_8_prompt_assembly(pid),
        lambda: test_9_status_mark(pid),
        lambda: test_10_stats_and_integration(pid),
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
    import time
    import shutil
    try:
        from app.db import connection
        connection.close()
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
