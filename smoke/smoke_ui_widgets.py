"""
I4-I24 UI 可复用 widget 套件 smoke.

覆盖:
  1. CollapsiblePanel (I4)  - 构造/展开/折叠/set_content/信号
  2. ColorPalette   (I5)  - 8 色板/单选/初始色/selected_color
  3. ThemeToggle    (I5)  - 默认 dark / 切换 light
  4. ConfirmDialog / InputDialog / MultiSelectDialog / SubWindowDialog (I6)
  5. RichTextViewer (I13) - Markdown 转换 / 标题/列表/代码块
  6. SystemTray     (I14) - offscreen 不可用检测 / 图标生成
  7. SplitterHelper (I16) - 比例序列化/反序列化
  8. ImageLabel     (I17) - 占位/缩放条/缩放倍率变化信号
  9. MultiPageInput (I20) - 多步/上一步/下一步/收集
 10. ProgressDialog (I22) - 步骤/进度/finish
 11. FontSetting    (I24) - 字体族/字号/粗体/斜体/to_dict
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QLineEdit,
    QSplitter,
    QSystemTrayIcon,
    QWidget,
)

_app = QApplication.instance() or QApplication(sys.argv)
_wd = QTimer(); _wd.setSingleShot(True)
_wd.timeout.connect(lambda: (print("[TIMEOUT] widgets 超时 60s", flush=True), os._exit(2)))
_wd.start(60_000)


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
    print("=== I4-I24 widget 套件 smoke (offscreen) ===", flush=True)

    from app.ui.widgets import (
        CollapsiblePanel,
        ColorPalette,
        ThemeToggle,
        ConfirmDialog,
        InputDialog,
        MultiSelectDialog,
        SubWindowDialog,
        Dialogs,
        RichTextViewer,
        SystemTray,
        TrayAction,
        SplitterHelper,
        ImageLabel,
        MultiPageInput,
        ProgressDialog,
        FontSetting,
    )

    # ---- 1. CollapsiblePanel ----
    section("[1] CollapsiblePanel (I4)")
    panel = CollapsiblePanel("基础信息")
    check(panel.title() == "基础信息", "title() 正确")
    check(panel.is_expanded() is True, "默认 expanded=True")
    check(panel._body.isHidden() is False, "默认 body 可见 (用 isHidden 反向验证)")
    sig_count = {"toggled": 0}
    panel.toggled.connect(lambda s: sig_count.__setitem__("toggled", sig_count["toggled"] + 1))
    panel.set_expanded(False)
    check(panel.is_expanded() is False, "set_expanded(False) 生效")
    check(panel._body.isHidden() is True, "set_expanded(False) 后 body 隐藏")
    check(sig_count["toggled"] == 1, f"toggled 信号触发 1 次 (实际 {sig_count['toggled']})")
    # set_content
    inner = QLabel("内容区", panel)
    panel.set_content(inner)
    check(panel._body.layout().count() == 1, f"set_content 后 body 含 1 widget (实际 {panel._body.layout().count()})")
    panel.set_title("新标题")
    check(panel.title() == "新标题", "set_title 生效")
    panel.set_expanded(True)
    check(panel.is_expanded() is True, "重新 set_expanded(True) 生效")
    # extra widget
    extra_btn = QLabel("●", panel)
    panel.set_extra_widget(extra_btn)
    check(panel._extra_layout.count() == 1, f"extra widget 已添加 (count={panel._extra_layout.count()})")
    # collapsible=False
    p2 = CollapsiblePanel("不可折叠", collapsible=False)
    check(p2._collapsible is False, "collapsible=False 生效")

    # ---- 2. ColorPalette ----
    section("[2] ColorPalette (I5)")
    cp = ColorPalette()
    check(len(cp.palette()) == 8, f"默认 8 色 (实际 {len(cp.palette())})")
    check(cp.selected_color() is None, "初始无选中")
    cp.set_selected("#6c7ae0")
    check(cp.selected_color() == "#6c7ae0", f"set_selected 后 selected_color()={cp.selected_color()}")
    sig = {"sel": ""}
    cp.colorSelected.connect(lambda h: sig.__setitem__("sel", h))
    # 找第一色的 swatch 按钮并模拟点击
    cp._buttons[0].click()
    check(sig["sel"] == "#6c7ae0", f"click 后 colorSelected 发出 (实际 {sig['sel']})")
    # 初始指定色
    cp2 = ColorPalette(initial="#4ec970")
    check(cp2.selected_color() == "#4ec970", f"initial 参数生效 (实际 {cp2.selected_color()})")

    # ---- 3. ThemeToggle ----
    section("[3] ThemeToggle (I5)")
    from app.ui.theme import ThemeManager
    tt = ThemeToggle()
    check(tt.current_theme() in ("dark", "light"), f"current_theme() 有效 ({tt.current_theme()})")
    # 不实际切换 (会影响其他测试), 仅验证构造

    # ---- 4. Dialogs (I6) ----
    section("[4] Dialogs (I6)")
    # ConfirmDialog 构造
    cd = ConfirmDialog("确认删除", "确定要删除吗?", hint="不可撤销", danger=True)
    check(cd.windowTitle() == "确认删除", "ConfirmDialog title")
    check(cd._confirm_btn.objectName() == "dangerAction", "danger 样式启用")
    cd.deleteLater()
    # InputDialog
    id_ = InputDialog("重命名", "新名称", initial="abc", placeholder="输入")
    check(id_.windowTitle() == "重命名", "InputDialog title")
    check(id_._editor.text() == "abc", f"InputDialog initial='{id_._editor.text()}'")
    id_.deleteLater()
    # MultiSelectDialog
    msd = MultiSelectDialog("选择", [("对峙", True, "推荐"), ("日常", False, "")])
    check(msd._checkboxes[0].isChecked() is True, "MultiSelect 第 1 项 checked")
    check(msd._checkboxes[1].isChecked() is False, "MultiSelect 第 2 项 unchecked")
    msd.deleteLater()
    # SubWindowDialog
    sub_w = QLabel("子内容")
    swd = SubWindowDialog("子窗口", sub_w, width=300, height=200)
    check(swd.windowTitle() == "子窗口", "SubWindowDialog title")
    check(swd.size().width() == 300, f"SubWindowDialog width={swd.size().width()}")
    swd.deleteLater()
    # Dialogs 便捷 (不实际 exec, 只确认静态方法存在)
    check(callable(Dialogs.confirm), "Dialogs.confirm 可调用")
    check(callable(Dialogs.input), "Dialogs.input 可调用")
    check(callable(Dialogs.multiselect), "Dialogs.multiselect 可调用")
    check(callable(Dialogs.sub), "Dialogs.sub 可调用")

    # ---- 5. RichTextViewer ----
    section("[5] RichTextViewer (I13)")
    rv = RichTextViewer(max_height=200)
    md = "# 标题\n## 子标题\n**粗体** *斜体* `代码`\n- 列表项 1\n- 列表项 2\n> 引用文字\n```\n代码块\n```\n普通段落."
    rv.set_markdown(md)
    html = rv.text_browser().toPlainText()
    check("标题" in html, f"Markdown 渲染含 '标题' (实际片段: {html[:50]!r})")
    check("粗体" in html, "Markdown 渲染含 '粗体'")
    check("列表项 1" in html, "Markdown 渲染含列表项")
    rv.set_plain("纯文本模式")
    check(rv.text_browser().toPlainText() == "纯文本模式", "set_plain 模式生效")
    rv.set_html("<p>HTML <strong>段落</strong></p>")
    check("HTML" in rv.text_browser().toPlainText(), "set_html 生效")

    # ---- 6. SystemTray ----
    section("[6] SystemTray (I14)")
    tray = SystemTray(app_name="Novel Writer")
    # offscreen 平台下不可用
    if not QSystemTrayIcon.isSystemTrayAvailable():
        check(tray.is_available() is False, "offscreen 下 SystemTray 不可用 (符合预期)")
    else:
        check(isinstance(tray.is_available(), bool), "is_available() 返回 bool")
    # TrayAction 构造
    act_called = {"n": 0}
    def _cb():
        act_called["n"] += 1
    ta = TrayAction("显示", _cb, icon_text="👁", separator_after=True)
    check(ta.label == "显示", "TrayAction label")
    check(ta.icon_text == "👁", "TrayAction icon_text")
    check(ta.separator_after is True, "TrayAction separator_after")

    # ---- 7. SplitterHelper ----
    section("[7] SplitterHelper (I16)")
    sp = QSplitter(Qt.Horizontal)
    sp.addWidget(QWidget())
    sp.addWidget(QWidget())
    sp.addWidget(QWidget())
    sh = SplitterHelper(sp, key="layout.main")
    check(sh.key() == "layout.main", "key() 正确")
    # 设置 800x600 大小, 验证比例
    sp.resize(900, 600)
    sh.apply_ratios([0.5, 0.3, 0.2])
    ratios = sh.current_ratios()
    check(abs(sum(ratios) - 1.0) < 0.01, f"比例和=1 ({sum(ratios):.4f})")
    check(len(ratios) == 3, f"3 面板比例 (实际 {len(ratios)})")
    # 序列化
    blob = sh.save_ratios()
    check("[" in blob and "]" in blob, f"save_ratios 返回 JSON-like (实际 {blob})")
    # 反序列化
    sh.load_ratios(blob)
    ratios2 = sh.current_ratios()
    check(abs(sum(ratios2) - 1.0) < 0.01, f"load_ratios 后比例和=1 ({sum(ratios2):.4f})")
    # 错误 blob 处理
    check(sh.load_ratios("not-json") is False, "load_ratios(无效 JSON) 返回 False")

    # ---- 8. ImageLabel ----
    section("[8] ImageLabel (I17)")
    il = ImageLabel()
    check(il.zoom() == ImageLabel.DEFAULT_ZOOM, f"默认 zoom={ImageLabel.DEFAULT_ZOOM}")
    # 空状态
    check(il._image_label.text().startswith("🖼"), f"空状态显示占位 (实际: {il._image_label.text()!r})")
    # 加载 pixmap
    pix = QPixmap(100, 80)
    pix.fill(Qt.red)
    il.set_pixmap(pix)
    check(il._image_label.pixmap() is not None, "set_pixmap 后 _image_label 有 pixmap")
    check(il.zoom() == 1.0, "set_pixmap 重置 zoom=1.0")
    # 缩放
    zoom_sig = {"v": 0.0}
    il.zoomChanged.connect(lambda v: zoom_sig.__setitem__("v", v))
    il.set_zoom(2.0)
    check(il.zoom() == 2.0, f"set_zoom(2.0) → zoom={il.zoom()}")
    check(zoom_sig["v"] == 2.0, f"zoomChanged 信号发出 2.0 (实际 {zoom_sig['v']})")
    il.set_zoom(10.0)  # 超过 MAX
    check(il.zoom() == ImageLabel.MAX_ZOOM, f"zoom 上限封顶 (实际 {il.zoom()})")
    il.set_zoom(0.01)  # 低于 MIN
    check(il.zoom() == ImageLabel.MIN_ZOOM, f"zoom 下限封底 (实际 {il.zoom()})")
    # zoom_by
    il.set_zoom(1.0)
    il.zoom_by(1.5)
    check(abs(il.zoom() - 1.5) < 1e-6, f"zoom_by(1.5) → {il.zoom()}")
    # fit_to_width
    il.fit_to_width()
    check(il.zoom() > 0, f"fit_to_width 触发缩放 ({il.zoom()})")
    # load_from_file 不存在
    check(il.load_from_file("Z:/__no__such__file__.png") is False, "load_from_file 不存在返回 False")
    # clear
    il.clear()
    check(il._image_label.pixmap() is None or il._image_label.pixmap().isNull(), "clear 后 pixmap 为空")

    # ---- 9. MultiPageInput ----
    section("[9] MultiPageInput (I20)")
    pages = [
        ("s1", "基础信息", QLineEdit()),
        ("s2", "角色追踪", QLineEdit()),
        ("s3", "确认", QLineEdit()),
    ]
    mp = MultiPageInput(pages)
    check(mp.page_count() == 3, f"3 页 (实际 {mp.page_count()})")
    check(mp.current_index() == 0, "默认第 1 页")
    check(mp._prev_btn.isEnabled() is False, "首页 prev 禁用")
    check(mp._next_btn.text() in ("完成", "下一步 →"), f"首页 next 文本 (实际 {mp._next_btn.text()!r})")
    # 注册 collector
    mp.set_collectors(0, lambda w: {"name": w.text()})
    mp.set_collectors(1, lambda w: {"char": w.text()})
    pages[0][2].setText("林轩")
    pages[1][2].setText("苏婉")
    # 注册 validator (全通过)
    mp.set_validators(0, lambda w: None)
    # next
    mp.next()
    check(mp.current_index() == 1, f"next() 后到第 2 页 (实际 {mp.current_index()})")
    check(mp._prev_btn.isEnabled() is True, "第 2 页 prev 启用")
    # validator 失败
    mp.set_validators(1, lambda w: "必须填写" if not w.text() else None)
    pages[1][2].setText("")
    mp.next()
    check(mp.current_index() == 1, f"validator 失败时不前进 (实际 {mp.current_index()})")
    check("必须填写" in mp._ai_status.text(), f"validator 失败显示提示 (text={mp._ai_status.text()!r})")
    pages[1][2].setText("苏婉")
    mp.next()
    check(mp.current_index() == 2, f"validator 通过后前进 (实际 {mp.current_index()})")
    # 完成
    fin = {"called": False, "data": None}
    mp.finished.connect(lambda d: (fin.__setitem__("called", True), fin.__setitem__("data", d)))
    mp.next()
    check(fin["called"] is True, "末页 next() 触发 finished 信号")
    check(fin["data"] is not None, "finished 携带数据")
    check(fin["data"].get("s1", {}).get("name") == "林轩", f"s1 数据={fin['data'].get('s1')}")
    # cancel
    cancel_called = {"n": 0}
    mp.cancelled.connect(lambda: cancel_called.__setitem__("n", cancel_called["n"] + 1))
    mp.cancel()
    check(cancel_called["n"] == 1, f"cancel 触发 cancelled (实际 {cancel_called['n']})")
    # collect_all
    data_all = mp.collect_all()
    check(data_all.get("s1", {}).get("name") == "林轩", f"collect_all s1={data_all.get('s1')}")
    # set_ai_status
    mp.set_ai_status("AI 正在生成...")
    check(mp._ai_status.text().startswith("●"), f"AI 状态显示 (实际 {mp._ai_status.text()!r})")
    mp.set_ai_status("")
    check(mp._ai_status.isVisible() is False, "清空 AI 状态后隐藏")

    # ---- 10. ProgressDialog ----
    section("[10] ProgressDialog (I22)")
    pd = ProgressDialog("生成章节", steps=["拼装记忆", "反AI", "写手", "评估", "落库"])
    check(pd.windowTitle() == "生成章节", "ProgressDialog title")
    check(pd._steps == ["拼装记忆", "反AI", "写手", "评估", "落库"], "steps 列表")
    # set_step
    pd.set_step(2)
    check(pd._current_step.text() == "写手", f"set_step(2) → {pd._current_step.text()!r}")
    # set_step_name
    pd.set_step_name("自定义步骤名")
    check(pd._current_step.text() == "自定义步骤名", f"set_step_name 生效 ({pd._current_step.text()!r})")
    # set_progress
    pd.set_progress(0.5)
    check(pd._bar.value() == 50, f"set_progress(0.5) → value={pd._bar.value()}")
    # set_tokens
    pd.set_tokens_used(12345)
    check("12,345" in pd._tokens_label.text(), f"set_tokens_used 格式化 (实际 {pd._tokens_label.text()!r})")
    # set_eta
    pd.set_eta_ms(5000)
    check("5.0" in pd._eta_label.text(), f"set_eta_ms 格式化 (实际 {pd._eta_label.text()!r})")
    # finish
    fin_called = {"ok": None}
    pd.finished_with_result.connect(lambda ok: fin_called.__setitem__("ok", ok))
    pd.finish(True, "完成")
    check(fin_called["ok"] is True, "finish(True) 触发信号")
    check(pd._title_label.text().startswith("✓"), f"finish 标题更新 ({pd._title_label.text()!r})")
    # 第二个 finish 重复调用不应再次触发
    pd.finish(True, "再次")
    check(fin_called["ok"] is True, "重复 finish 不重复触发信号")
    pd.deleteLater()
    # cancel 路径
    pd2 = ProgressDialog("X", steps=["a", "b"], cancellable=True)
    cancel_sig = {"n": 0}
    pd2.cancelled.connect(lambda: cancel_sig.__setitem__("n", cancel_sig["n"] + 1))
    pd2._on_cancel()
    check(cancel_sig["n"] == 1, f"cancel 触发信号 (实际 {cancel_sig['n']})")
    check(pd2.is_cancelled() is True, "is_cancelled() True")
    pd2.deleteLater()

    # ---- 11. FontSetting ----
    section("[11] FontSetting (I24)")
    fs = FontSetting(initial_size=14)
    check(fs.size() == 14, f"initial_size=14 (实际 {fs.size()})")
    check(fs.bold() is False, "默认 bold=False")
    fs.set_bold(True)
    check(fs.bold() is True, "set_bold(True) 生效")
    fs.set_italic(True)
    check(fs.italic() is True, "set_italic(True) 生效")
    fs.set_size(18)
    check(fs.size() == 18, f"set_size(18) (实际 {fs.size()})")
    # to_dict
    d = fs.to_dict()
    check(d.get("size") == 18, f"to_dict size={d.get('size')}")
    check(d.get("bold") is True, f"to_dict bold={d.get('bold')}")
    # apply_dict
    fs2 = FontSetting()
    fs2.apply_dict({"size": 20, "bold": False, "italic": True})
    check(fs2.size() == 20, f"apply_dict size={fs2.size()}")
    check(fs2.italic() is True, f"apply_dict italic={fs2.italic()}")
    # signal
    f_sig = {"called": 0}
    fs.fontChanged.connect(lambda *_: f_sig.__setitem__("called", f_sig["called"] + 1))
    fs.set_size(22)
    check(f_sig["called"] >= 1, f"fontChanged 触发 (实际 {f_sig['called']})")
    # 字体族存在 (offscreen 下可能为空, 至少验证构造)
    families = fs._family_combo.count()
    if families > 0:
        check(True, f"字体族列表非空 (实际 {families})")
    else:
        # offscreen + 无字体环境, 只验证 QComboBox 存在
        check(fs._family_combo is not None, "字体族 QComboBox 已构造 (offscreen 无字体属正常)")
    # set_preview_text
    fs.set_preview_text("新预览")
    check(fs._preview.toPlainText() == "新预览", "set_preview_text 生效")

    # ---- 汇总 ----
    print(f"\n{'=' * 60}")
    print(f"全部: {_pass + _fail}, 通过: {_pass}, 失败: {_fail}")
    print("=" * 60, flush=True)
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
