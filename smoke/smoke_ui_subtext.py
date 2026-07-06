"""
Subtext UI smoke (offscreen).

覆盖:
  1. SubtextTab 构造 (13 字段 + 章节列表 + 模板下拉)
  2. SettingsTab 集成 SubtextTab 为第 3 个子 tab
  3. FieldHelpButton 13 字段全覆盖 + tooltip 含 label/hint/example
  4. ProjectModeHeader 模式切换下拉 (3 模式) + 模板下拉 (manual 才显示)
  5. set_project(None) 不抛
  6. set_project 加载章节列表 (mock book + chapter)
  7. _on_chapter_selected 加载卡 / 提示无卡
  8. _on_save 写卡 + 状态更新
  9. _on_delete 删卡
 10. _on_ai_generate (跳过过渡章)
 11. _on_apply_chapter_template 套模板填字段
 12. theme.py 包含 Subtext UI 样式
 13. 关闭模式: 表单只读
"""
from __future__ import annotations
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# stdout UTF-8 (Windows GBK 兼容, 含 🎭 字符)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# 5 分钟 watchdog
_TIMEOUT = 300
def _timeout_kill():
    print(f"\n[TIMEOUT] smoke_ui_subtext 超时 {_TIMEOUT}s", flush=True)
    os._exit(2)
_t = threading.Timer(_TIMEOUT, _timeout_kill)
_t.daemon = True
_t.start()

# 隔离 DB
TMPDIR = Path(tempfile.mkdtemp(prefix="nw_smoke_subtext_ui_"))
DB_PATH = TMPDIR / "test.db"
STORY_DIR = TMPDIR / "story"
STORY_DIR.mkdir(parents=True, exist_ok=True)

import app.app_paths
app.app_paths.sqlite_path = lambda: DB_PATH
import app.services.file_store
app.services.file_store.BASE_DIR = STORY_DIR

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)

# 启动 DB (2 套连接都初始化, 兼容 services 子模块 + memory/character_tracker/ai.registry)
from app.db import _impl as _db_conn
from app.services.db import init_db as _svc_init_db
_svc_init_db()
_db_conn.init(DB_PATH)
from app.services import subtext as subtext_svc
subtext_svc.seed_presets()  # 确保 6 模板已 seed


_pass = 0
_fail = 0
def check(cond: bool, label: str) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  [PASS] {label}", flush=True)
    else:
        _fail += 1
        print(f"  [FAIL] {label}", flush=True)

def section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}", flush=True)


def main() -> int:
    print("=== Subtext UI smoke (offscreen) ===", flush=True)

    from app.ui.tabs.subtext_tab import SubtextTab, FieldHelpButton, ProjectModeHeader
    from app.ui.tabs.settings_tab import SettingsTab
    from app.ui.tabs import subtext_tab as st_mod
    from app.ui.widgets import Dialogs as _Dialogs
    from app.services.subtext import (
        SUBTEXT_FIELDS, FIELD_HELP, MODE_AI_AUTO, MODE_MANUAL, MODE_CLOSED, ALL_MODES,
    )
    from app.services import project_service, book_service, chapter_service, subtext

    # ---- 共用 mock helpers (4.0: tabs 用 Dialogs, 不再 patch QMessageBox) ----
    called = {"info": 0, "warn": 0, "confirm": 0, "sub": 0, "input": 0, "multiselect": 0, "error": 0}
    def fake_info(*a, **kw):
        called["info"] += 1
        return (True, None)
    def fake_warn(*a, **kw):
        called["warn"] += 1
        return (True, None)
    def fake_error(*a, **kw):
        called["error"] += 1
        return (True, None)
    def fake_confirm_yes(*a, **kw):
        called["confirm"] += 1
        return (True, None)
    orig_info = _Dialogs.info
    orig_warn = _Dialogs.warning
    orig_confirm = _Dialogs.confirm
    orig_error = _Dialogs.error

    # ---- 1. SettingsTab 集成 (4.0: scope=novel 默认, 3 左导航项) ----
    section("[1] SettingsTab(scope=novel) 集成 SubtextTab")
    st2 = SettingsTab()  # 默认 scope=novel
    # 4.0 重构: QTabWidget → QListWidget(左) + QStackedWidget(右)
    from PySide6.QtWidgets import QListWidget, QStackedWidget
    check(isinstance(st2.nav_list, QListWidget), "nav_list 是 QListWidget (左导航)")
    check(isinstance(st2.stack, QStackedWidget), "stack 是 QStackedWidget (右内容)")
    labels = [st2.nav_list.item(i).text() for i in range(st2.nav_list.count())]
    check("🎭 潜文本卡" in labels, f"子 tab 含'🎭 潜文本卡' (实际 {labels})")
    check(st2.nav_list.count() == 3, f"3 个左导航项 (实际 {st2.nav_list.count()})")
    check(isinstance(st2.subtext_widget, SubtextTab), "subtext_widget 是 SubtextTab 实例")

    # ---- 2. SubtextTab 字段 ----
    section("[2] SubtextTab 13 字段")
    st = SubtextTab()
    check(len(st.form.rows) == 13, f"13 个字段行 (实际 {len(st.form.rows)})")
    for fld in SUBTEXT_FIELDS:
        check(fld in st.form.rows, f"字段行 {fld} 存在")
    check(set(st.form.rows.keys()) == set(SUBTEXT_FIELDS), "字段行 = SUBTEXT_FIELDS")

    # ---- 3. FieldHelpButton tooltip ----
    section("[3] FieldHelpButton 13 字段全覆盖")
    for fld in SUBTEXT_FIELDS:
        btn = FieldHelpButton(fld)
        tip = btn.toolTip()
        info = FIELD_HELP[fld]
        check(info["label"] in tip, f"{fld} tooltip 含 label: {info['label']}")
        check(info["hint"] in tip, f"{fld} tooltip 含 hint")
        check(info["example"] in tip, f"{fld} tooltip 含 example")
    # 未知字段不抛
    btn_bad = FieldHelpButton("totally_unknown_field")
    check("未知" in btn_bad.toolTip() or "totally_unknown" in btn_bad.toolTip(),
          f"未知字段不抛: {btn_bad.toolTip()[:40]}")

    # ---- 4. ProjectModeHeader 模式 ----
    section("[4] ProjectModeHeader 模式切换")
    header = ProjectModeHeader()
    check(header.cmb_mode.count() == 3, f"3 模式 (实际 {header.cmb_mode.count()})")
    modes_in_combo = [header.cmb_mode.itemData(i) for i in range(header.cmb_mode.count())]
    check(modes_in_combo == ALL_MODES, f"模式数据 = ALL_MODES (实际 {modes_in_combo})")

    # set_project(None) 不抛
    try:
        header.set_project(None)
        passed = True
    except Exception as e:
        passed = False
        print(f"  [ERROR] {e}", flush=True)
    check(passed, "set_project(None) 不抛")
    check("(无项目)" in header.lbl_mode.text(), f"label 变 '(无项目)': {header.lbl_mode.text()}")
    check(header.cmb_mode.isEnabled() is False, "无项目时 cmb_mode 禁用")

    # set_project(real project) 加载模式 + 模板
    proj = project_service.create(name="ui_subtext_test")
    project_id = proj["id"]
    header.set_project(proj)
    check("🧠 AI 自动" in header.lbl_mode.text() or "AI 自动" in header.lbl_mode.text(),
          f"默认 AI 自动: {header.lbl_mode.text()}")
    check(header.cmb_template.count() >= 7,  # — + 6 模板
          f"模板下拉 ≥ 7 项 (实际 {header.cmb_template.count()})")
    check(header.cmb_template.isVisible() is False, "AI 自动模式时模板下拉隐藏")

    # 切到手动
    header.cmb_mode.setCurrentIndex(ALL_MODES.index(MODE_MANUAL))
    check("✏️ 手动" in header.lbl_mode.text(), f"切到手动: {header.lbl_mode.text()}")
    # header 是 standalone, isVisible() 依赖父链可见, 用 isVisibleTo 父
    check(header.cmb_template.isVisibleTo(header) is True,
          f"手动模式时模板下拉 visible (实际 isVisibleTo={header.cmb_template.isVisibleTo(header)})")

    # 切到关闭
    header.cmb_mode.setCurrentIndex(ALL_MODES.index(MODE_CLOSED))
    check("🚫 关闭" in header.lbl_mode.text() or "关闭" in header.lbl_mode.text(),
          f"切到关闭: {header.lbl_mode.text()}")
    check(header.cmb_template.isVisible() is False, "关闭模式时模板下拉隐藏")

    # 验证 DB 真的写了
    saved = subtext.get_project_mode(project_id)
    check(saved["mode"] == MODE_CLOSED, f"DB 写入关闭模式: {saved['mode']}")

    # 重置回 AI 自动
    header.cmb_mode.setCurrentIndex(ALL_MODES.index(MODE_AI_AUTO))

    # ---- 5. set_project 加载章节列表 ----
    section("[5] set_project 加载章节")
    st.set_project(proj)
    # 创建一本书 + 3 章
    book = book_service.create(project_id=project_id, volume_no=1, title="第 1 卷")
    ch1 = chapter_service.create(book_id=book["id"], chapter_no=1, title="开篇")
    ch2 = chapter_service.create(book_id=book["id"], chapter_no=2, title="中段")
    ch3 = chapter_service.create(book_id=book["id"], chapter_no=3, title="结尾")
    st.set_project(proj)  # 触发 reload
    check(st.chapter_list.count() == 3, f"3 章节 (实际 {st.chapter_list.count()})")
    # 全部无卡: ❌
    for i in range(st.chapter_list.count()):
        it = st.chapter_list.item(i)
        check("❌" in it.text(), f"第 {i+1} 章初始无卡: {it.text()}")

    # ---- 6. 选章节 → 提示无卡 ----
    section("[6] 选章节 → 加载卡")
    st.chapter_list.setCurrentRow(0)
    check(st.current_chapter_id == ch1["id"], f"current_chapter_id = ch1")
    check("无潜文本卡" in st.lbl_chapter_status.text() or "❌" in st.lbl_chapter_status.text(),
          f"提示无卡: {st.lbl_chapter_status.text()}")
    check(st.btn_ai_gen.isEnabled() and st.btn_delete.isEnabled() and st.btn_save.isEnabled(),
          "3 个按钮都启用")

    # 填几个字段后保存
    st.form.rows["surface_event"].setText("主角在山门登场")
    st.form.rows["emotional"].setText("好奇 + 紧张")
    st.form.rows["pacing"].setText("缓起")
    # patch Dialogs 避免弹窗阻塞
    _Dialogs.info = fake_info
    _Dialogs.warning = fake_warn
    try:
        st.btn_save.click()
    finally:
        _Dialogs.info = orig_info
        _Dialogs.warning = orig_warn
    # 检查 DB
    card = subtext.get_card_for_chapter(ch1["id"])
    check(card is not None, f"卡已保存 (实际 {card})")
    if card:
        check(card.surface_event == "主角在山门登场", f"surface_event 正确: {card.surface_event}")
        check(card.emotional == "好奇 + 紧张", f"emotional 正确: {card.emotional}")
        check(card.source == "manual", f"source = manual (实际 {card.source})")

    # 重新选回第 1 章
    st.set_project(proj)
    for i in range(st.chapter_list.count()):
        it = st.chapter_list.item(i)
        if it.data(Qt.ItemDataRole.UserRole)["id"] == ch1["id"]:
            st.chapter_list.setCurrentItem(it)
            break
    # 列表项状态: ✏️ 手动
    it_ch1 = None
    for i in range(st.chapter_list.count()):
        it = st.chapter_list.item(i)
        if it.data(Qt.ItemDataRole.UserRole)["id"] == ch1["id"]:
            it_ch1 = it
            break
    check("✏️" in it_ch1.text(), f"ch1 状态标 ✏️: {it_ch1.text()}")
    check("已有卡" in st.lbl_chapter_status.text(), f"状态提示: {st.lbl_chapter_status.text()}")

    # ---- 7. AI 自动生成 (过渡章 < 1000 字会被拒) ----
    section("[7] AI 自动生成")
    st.chapter_list.setCurrentRow(1)  # ch2 无卡
    # patch Dialogs 后再 click, 避免阻塞
    _Dialogs.info = fake_info
    _Dialogs.warning = fake_warn
    try:
        st.btn_ai_gen.click()
    finally:
        _Dialogs.info = orig_info
        _Dialogs.warning = orig_warn
    check(called["info"] >= 1, f"过渡章弹了信息提示 (count={called['info']})")
    # ch2 仍应无卡
    card_ch2 = subtext.get_card_for_chapter(ch2["id"])
    check(card_ch2 is None, f"ch2 仍无卡 (实际 {card_ch2})")

    # ---- 8. 套模板 ----
    section("[8] 章节级套模板")
    # 把 ch3 套 tpl_confrontation
    st.chapter_list.setCurrentRow(2)  # ch3
    # 找 cmb_chapter_tpl 中 tpl_confrontation 的 index
    tpl_idx = -1
    for i in range(st.cmb_chapter_tpl.count()):
        if st.cmb_chapter_tpl.itemData(i) == "tpl_confrontation":
            tpl_idx = i
            break
    check(tpl_idx > 0, f"找到 tpl_confrontation index={tpl_idx}")
    # patch Dialogs
    _Dialogs.info = fake_info
    _Dialogs.warning = fake_warn
    try:
        st.cmb_chapter_tpl.setCurrentIndex(tpl_idx)
    finally:
        _Dialogs.info = orig_info
        _Dialogs.warning = orig_warn
    # 字段已被填充
    check("压抑" in st.form.rows["emotional"].text() or
          "紧张" in st.form.rows["emotional"].text(),
          f"emotional 已套模板: {st.form.rows['emotional'].text()}")
    # 状态提示
    check("已套模板" in st.lbl_chapter_status.text() or "tpl_confrontation" in st.lbl_chapter_status.text(),
          f"状态: {st.lbl_chapter_status.text()}")
    # 保存
    _Dialogs.info = fake_info
    _Dialogs.warning = fake_warn
    try:
        st.btn_save.click()
    finally:
        _Dialogs.info = orig_info
        _Dialogs.warning = orig_warn
    card_ch3 = subtext.get_card_for_chapter(ch3["id"])
    check(card_ch3 is not None, "ch3 模板卡已保存")
    if card_ch3:
        check(card_ch3.template_id == "tpl_confrontation",
              f"template_id 正确 (实际 {card_ch3.template_id})")
        check(card_ch3.source == "manual", f"source = manual")

    # ---- 9. 删除卡 ----
    section("[9] 删除卡")
    _Dialogs.confirm = fake_confirm_yes
    _Dialogs.warning = fake_warn
    _Dialogs.info = fake_info
    try:
        # 选回 ch3
        for i in range(st.chapter_list.count()):
            it = st.chapter_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole)["id"] == ch3["id"]:
                st.chapter_list.setCurrentItem(it)
                break
        st.btn_delete.click()
    finally:
        _Dialogs.confirm = orig_confirm
        _Dialogs.warning = orig_warn
        _Dialogs.info = orig_info
    card_ch3_after = subtext.get_card_for_chapter(ch3["id"])
    check(card_ch3_after is None, f"ch3 卡片已删 (实际 {card_ch3_after})")

    # ---- 10. 关闭模式: 表单只读 ----
    section("[10] 关闭模式: 表单只读")
    subtext.set_project_mode(project_id, MODE_CLOSED)
    st.set_project(proj)  # 重新加载模式
    st.chapter_list.setCurrentRow(0)  # ch1 有卡
    for fld, row in st.form.rows.items():
        check(row.editor.isReadOnly() is True, f"关闭模式 {fld} 只读")

    # ---- 11. theme.py 含 Subtext 样式 ----
    section("[11] theme.py 含 Subtext UI 样式")
    from app.ui import theme as theme_mod
    dark_qss = theme_mod.DARK_QSS
    light_qss = theme_mod.LIGHT_QSS
    for selector in ["subtextModeHeader", "subtextHeaderTitle", "subtextModeLabel",
                     "subtextChapterStatus", "fieldLabel", "fieldEditor", "fieldHelpBtn"]:
        check(selector in dark_qss, f"DARK_QSS 含 #{selector}")
        check(selector in light_qss, f"LIGHT_QSS 含 #{selector}")

    # 清理
    try:
        project_service.delete(project_id)
    except Exception:
        pass

    print(f"\n{'=' * 60}")
    print(f"通过: {_pass}    失败: {_fail}")
    if _fail == 0:
        print(f"全部 {_pass} 项检查通过 ✓")
    else:
        print(f"!! {_fail} 项失败 !!")
    print(f"{'=' * 60}")
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
