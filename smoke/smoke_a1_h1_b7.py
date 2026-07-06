"""
A1 + H1 + B7 增量 smoke 测试 (3.3.0 新增).

覆盖:
  - A1 genre_presets 解析/序列化/关键词反查
  - A1 BasicInfoWidget UI 集成 (1-5 多选 + 校验)
  - A1 prompt_assembler 注入题材
  - H1 OutlineService CRUD + 选版本
  - H1 AIOutlineGenPlugin 批量生成 + fallback
  - H1 PluginManager 集成
  - B7 version 模块
  - 集成: outline_service -> chapter_brief 选定写入

60+ 项检查
"""
from __future__ import annotations
import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path

# 5 分钟超时 (与项目一致)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_SMOKE_TIMEOUT = 300
_timer = None


def _timeout_kill() -> None:
    print(f"\n[smoke_a1_h1_b7] {_SMOKE_TIMEOUT}s 超时, 强制退出")
    os._exit(2)


def _arm_timeout() -> None:
    global _timer
    _timer = threading.Timer(_SMOKE_TIMEOUT, _timeout_kill)
    _timer.daemon = True
    _timer.start()


def _disarm_timeout() -> None:
    global _timer
    if _timer:
        _timer.cancel()
        _timer = None


_pass = 0
_fail = 0


def check(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  [OK] {label}")
    else:
        _fail += 1
        print(f"  [FAIL] {label}")


def section(name: str) -> None:
    print(f"\n--- {name} ---")


# ============================================================== #
# 测试体
# ============================================================== #

def setup_env() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="a1h1b7_"))
    db_path = tmp / "test.db"
    import app.app_paths
    app.app_paths.sqlite_path = lambda: db_path
    from app.services.db import init_db
    init_db()
    from app.db import connection
    connection.init(db_path)
    # M11-A: 让 data_access 拿到真 ProjectReader / SettingReader 实现
    from app.core.wiring import wire_default_services
    wire_default_services()
    return tmp


def test_a1_presets() -> None:
    section("[A1 1] genre_presets 模块")
    from app.services import genre_presets
    check(len(genre_presets.GENRE_PRESETS) >= 12, f"题材 >= 12 ({len(genre_presets.GENRE_PRESETS)})")
    check(len(genre_presets.PLATFORM_PRESETS) >= 5, f"平台 >= 5 ({len(genre_presets.PLATFORM_PRESETS)})")
    g_list = genre_presets.list_genres()
    check(len(g_list) == len(genre_presets.GENRE_PRESETS), "list_genres 长度一致")
    for g in g_list:
        check("id" in g and "name" in g and "desc" in g and "keywords" in g,
              f"  {g['id']} 字段齐全")
        break  # 抽检一个

    check(genre_presets.parse_genre_string(None) == [], "None -> []")
    check(genre_presets.parse_genre_string("") == [], "'' -> []")
    check(genre_presets.parse_genre_string("玄幻") == ["玄幻"], "单值解析")
    check(genre_presets.parse_genre_string("玄幻,都市") == ["玄幻", "都市"], "逗号")
    check(genre_presets.parse_genre_string("玄幻、修真") == ["玄幻", "修真"], "顿号")
    check(genre_presets.parse_genre_string("  玄幻  ,  都市  ") == ["玄幻", "都市"], "去空格")
    check(genre_presets.parse_genre_string("玄幻,玄幻,都市") == ["玄幻", "都市"], "去重")

    check(genre_presets.serialize_genres([]) == "", "空列表")
    check(genre_presets.serialize_genres(["玄幻"]) == "玄幻", "单值")
    check(genre_presets.serialize_genres(["玄幻", "都市"]) == "玄幻、都市", "顿号分隔")
    check(genre_presets.serialize_genres(["  玄幻  ", "", " 修真"]) == "玄幻、修真", "trim 空值")

    kws = genre_presets.genre_to_keywords("玄幻、修真")
    check("修炼等级" in kws and "筑基" in kws, f"关键词含 玄幻+修真 ({kws})")
    check(genre_presets.genre_to_keywords(None) == [], "None 无关键词")
    check(genre_presets.genre_to_keywords("不存在的题材") == [], "未知题材无关键词")


def test_a1_project_integration() -> None:
    section("[A1 2] project + genre 字段集成")
    from app.services import project_service, genre_presets
    p = project_service.create(name="A1测试", book_title="测试书", genre="玄幻、都市",
                               platform="起点中文网", word_target=300_000)
    check(p.get("genre") == "玄幻、都市", f"创建后 genre={p.get('genre')}")
    check(p.get("word_target") == 300_000, "word_target=300k")
    check(p.get("platform") == "起点中文网", "platform")

    # 更新
    p2 = project_service.update(p["id"], genre=genre_presets.serialize_genres(["修真"]))
    check(p2.get("genre") == "修真", "更新 genre")

    # 解析回
    parsed = genre_presets.parse_genre_string(p2.get("genre"))
    check(parsed == ["修真"], f"回解析 {parsed}")


def test_a1_prompt_injection() -> None:
    section("[A1 3] prompt_assembler 注入题材")
    from app.services import project_service, book_service, chapter_service
    from app.core.prompt_assembler import assemble_writer_prompt
    p = project_service.create(name="A1 prompt测试", genre="修真、仙侠")
    b = book_service.create(p["id"], volume_no=1, title="卷一")
    ch = chapter_service.create(b["id"], chapter_no=1, title="测试章")

    prompt = assemble_writer_prompt(p["id"], ch["id"])
    check("题材设定" in prompt["system"], "system 含 '题材设定' 节")
    check("修真" in prompt["system"], "system 含 '修真'")
    check("筑基" in prompt["system"], "system 含关键词 '筑基'")
    check("长生" in prompt["system"], "system 含关键词 '长生'")

    # 无 genre 时不注入
    p2 = project_service.create(name="无 genre")
    b2 = book_service.create(p2["id"], volume_no=1)
    ch2 = chapter_service.create(b2["id"], chapter_no=1)
    prompt2 = assemble_writer_prompt(p2["id"], ch2["id"])
    check("题材设定" not in prompt2["system"], "无 genre 时不注入 题材节")


def test_a1_basic_info_widget() -> None:
    section("[A1 4] BasicInfoWidget UI (offscreen)")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from app.ui.tabs.settings_tab import BasicInfoWidget
    from app.services import project_service

    p = project_service.create(name="A1 UI 测试", genre="玄幻")
    widget = BasicInfoWidget()
    widget.set_project(p)
    check(widget.current_project is not None, "set_project 后 current 非空")
    check(widget.btn_save.isEnabled(), "btn_save 启用")
    check(widget.lst_genres.count() >= 12, f"listwidget 项数 ({widget.lst_genres.count()})")
    # 检查默认勾选了 玄幻
    checked = widget._selected_genres()
    check("玄幻" in checked, f"已勾选 玄幻 (实际 {checked})")
    check(len(checked) == 1, f"只勾 1 个 (实际 {len(checked)})")
    # 测试校验: 0 个 -> 不应能保存 (但 save 校验会弹窗, 这里只测 widget 自身)
    # 改项目名
    widget.ed_name.setText("改名后")
    # 保存会弹 Dialogs.info, patch
    from app.ui.widgets import Dialogs
    orig = Dialogs.info
    Dialogs.info = lambda *a, **kw: (True, None)
    try:
        widget._on_save()
        p_re = project_service.get(p["id"])
        check(p_re.get("name") == "改名后", f"改名成功 ({p_re.get('name')})")
    finally:
        Dialogs.info = orig


def test_h1_outline_service() -> None:
    section("[H1 1] OutlineService CRUD")
    from app.services import project_service, book_service, chapter_service
    from app.services import outline_service

    p = project_service.create(name="H1 outline 测试")
    b = book_service.create(p["id"], volume_no=1)
    ch = chapter_service.create(b["id"], chapter_no=1, title="第1章")
    cid = ch["id"]

    check(outline_service.count_versions(cid) == 0, "初始 0 个")

    outline_service.save_outline(cid, "A", "A 版", core_events="事件A", emotion_arc="起")
    outline_service.save_outline(cid, "B", "B 版")
    outline_service.save_outline(cid, "C", "C 版")
    check(outline_service.count_versions(cid) == 3, "3 个版本")

    all_o = outline_service.list_outlines(cid)
    check([o["version"] for o in all_o] == ["A", "B", "C"], "按 A/B/C 排序")

    # upsert
    outline_service.save_outline(cid, "A", "A 版 v2")
    a = outline_service.get_outline(cid, "A")
    check(a["outline"] == "A 版 v2", "A 已被覆盖")
    check(outline_service.count_versions(cid) == 3, "仍 3 个")

    # select
    sel = outline_service.select_version(cid, "B")
    check(sel["selected"] == 1, "B 标记 selected")
    for o in outline_service.list_outlines(cid):
        if o["version"] == "B":
            check(o["selected"] == 1, "B 仍是 selected")
        else:
            check(o["selected"] == 0, f"{o['version']} 已清 selected")

    # get_selected
    selected = outline_service.get_selected(cid)
    check(selected is not None and selected["version"] == "B", "get_selected 返 B")

    # diff
    d = outline_service.diff_versions(cid)
    check("A" in d and "B" in d and "C" in d, "diff_keys")
    check(d["A"]["outline"] == "A 版 v2", "diff[A] outline")
    check(d["B"]["selected"] == 1, "diff[B] selected")

    # 错误处理
    try:
        outline_service.save_outline(cid, "D", "X")
        check(False, "D 应抛异常")
    except outline_service.OutlineServiceError as e:
        check("version 必须是 A/B/C" in str(e), f"错误捕获: {e}")
    try:
        outline_service.save_outline(cid, "A", "   ")
        check(False, "空 outline 应抛异常")
    except outline_service.OutlineServiceError as e:
        check("不能为空" in str(e), "空 outline 校验")

    # delete
    check(outline_service.delete_outline(cid, "A") is True, "删 A 成功")
    check(outline_service.count_versions(cid) == 2, "剩 2 个")
    check(outline_service.delete_outline(cid, "A") is False, "再删 A 返 False")
    check(outline_service.delete_all_for_chapter(cid) == 2, "清空返 2")
    check(outline_service.count_versions(cid) == 0, "清空后 0 个")


def test_h1_plugin_generation() -> None:
    section("[H1 2] AIOutlineGenPlugin 批量生成")
    from app.services import project_service, outline_service
    from app.plugins.builtin import AIOutlineGenPlugin

    p = project_service.create(name="H1 plugin 测试", genre="玄幻")
    plugin = AIOutlineGenPlugin()
    plugin.setup({})
    results = plugin.generate_outlines(p["id"], num_chapters=5, use_llm=False)
    check(len(results) == 5, f"5 章结果 (实际 {len(results)})")
    for r in results:
        check("A" in r.drafts and "B" in r.drafts and "C" in r.drafts,
              f"第 {r.chapter_no} 章 3 版本齐全")
        check(r.drafts["A"].fallback is True, f"第 {r.chapter_no} 章 A 走 fallback")
        check(len(r.drafts["A"].outline) > 0, f"第 {r.chapter_no} 章 A 内容非空")
        # 已保存到 DB
        outlines_db = outline_service.list_outlines(r.chapter_id)
        check(len(outlines_db) == 3, f"第 {r.chapter_no} 章 DB 3 行")

    # 错误: num_chapters 越界
    try:
        plugin.generate_outlines(p["id"], num_chapters=0)
        check(False, "0 应抛异常")
    except ValueError as e:
        check("1-10" in str(e), f"num_chapters 校验: {e}")
    try:
        plugin.generate_outlines(p["id"], num_chapters=11)
        check(False, "11 应抛异常")
    except ValueError as e:
        check("1-10" in str(e), f"num_chapters 校验: {e}")


def test_h1_plugin_manager() -> None:
    section("[H1 3] PluginManager 集成")
    from app.plugins.builtin import AIOutlineGenPlugin
    from app.plugins.manager import PluginManager
    tmp = Path(tempfile.mkdtemp())
    mgr = PluginManager(plugins_dir=tmp / "plugins")
    p = AIOutlineGenPlugin()
    mgr.register_builtin(p)
    info = mgr.get("ai_outline_gen")
    check(info is not None, "plugin 在 manager")
    check(info.builtin is True, "builtin=True")
    check(info.enabled is True, "enabled=True (内置默认开)")
    check(info.version == "1.0.0", f"version={info.version}")
    inst = mgr.get_instance("ai_outline_gen")
    check(inst is p, "instance 是同一个对象")


def test_b7_version() -> None:
    section("[B7] version 模块")
    from app.core import version
    check(version.VERSION == "3.4.0", f"VERSION=3.4.0 (实际 {version.VERSION})")
    info = version.get_full_info()
    check(info["version"] == "3.4.0", "get_full_info version")
    check("3.4.0" in info["changelog"], "changelog 含 3.4.0")
    check("M11-C" in info["changelog"], "changelog 含 M11-C")
    check("M11-B" in info["changelog"], "changelog 含 M11-B")
    check("M11-D" in info["changelog"], "changelog 含 M11-D")
    text = version.format_about_text()
    check("3.4.0" in text, "about text 含版本")
    check("AI 辅助" in text, "about text 含 APP_DESCRIPTION")
    tup = version.get_version_tuple()
    check(tup == (3, 4, 0), f"version_tuple={tup}")


def test_integration_end_to_end() -> None:
    section("[E2E] A1 + H1 + B7 端到端")
    from app.services import project_service, book_service, chapter_service
    from app.services import outline_service, setting_service, genre_presets
    from app.core.prompt_assembler import assemble_writer_prompt
    from app.plugins.builtin import AIOutlineGenPlugin

    # 1. 创项目 + 题材 + 设定
    p = project_service.create(name="E2E", genre="玄幻、修真", platform="起点中文网")
    setting_service.set_setting(p["id"], "worldbuilding", {"修炼": "筑基→金丹→元婴"})
    setting_service.set_setting(p["id"], "characters", [{"name": "主角", "traits": "坚韧"}])

    # 2. 生成 3 章大纲
    plugin = AIOutlineGenPlugin()
    plugin.setup({})
    plugin.generate_outlines(p["id"], num_chapters=3, use_llm=False)

    # 3. 验证 prompt 注入
    books = book_service.list_for_project(p["id"])["books"]
    b = books[0]
    chapters = sorted(
        chapter_service.list_for_book(b["id"])["chapters"],
        key=lambda c: c["chapter_no"]
    )[:3]
    for ch in chapters:
        prompt = assemble_writer_prompt(p["id"], ch["id"])
        assert "题材设定" in prompt["system"]
        assert "玄幻" in prompt["system"] or "修真" in prompt["system"]

    # 4. 选第一版 (A) 为 selected
    sel = outline_service.select_version(chapters[0]["id"], "A")
    assert sel["selected"] == 1

    # 5. 验证 version 字段
    from app.core import version
    assert version.VERSION == "3.4.0"

    print("  [OK] 端到端 OK")


# ============================================================== #
# main
# ============================================================== #

def main() -> int:
    _arm_timeout()
    print("=" * 60)
    print("smoke_a1_h1_b7: A1 题材 + H1 大纲 + B7 版本 (3.3.0 增量)")
    print("=" * 60)
    try:
        setup_env()
        test_a1_presets()
        test_a1_project_integration()
        test_a1_prompt_injection()
        test_a1_basic_info_widget()
        test_h1_outline_service()
        test_h1_plugin_generation()
        test_h1_plugin_manager()
        test_b7_version()
        test_integration_end_to_end()
    except Exception as e:
        import traceback
        print(f"\n[EXC] {type(e).__name__}: {e}")
        traceback.print_exc()
        _disarm_timeout()
        return 1
    finally:
        _disarm_timeout()
    print(f"\n{'=' * 60}")
    print(f"结果: {_pass} passed, {_fail} failed")
    print(f"{'=' * 60}")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
