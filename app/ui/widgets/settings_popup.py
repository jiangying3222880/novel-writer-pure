"""
设置弹窗 (v4.1)

右上角齿轮 → QDialog 弹窗, 5 个 tab: AI / 外观 / 存储 / 插件 / 高级.

v4.1: AI tab 重写, 接入完整的 27 厂商预设 + app_setting_service CRUD.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QPushButton, QGroupBox, QFormLayout, QComboBox,
    QSpinBox, QCheckBox, QLineEdit, QFileDialog, QListWidget,
    QListWidgetItem, QMessageBox, QStackedWidget, QSplitter,
)

from app.ui.theme import text_subtle, text_secondary, text_indigo
from app.ui.theme_observer import bind_theme


# --------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------- #

def _grouped_presets() -> list[tuple[str, list[tuple[str, str]]]]:
    """返回 [(分组名, [(display_name, preset_key)]), ...] 供 UI 分组下拉."""
    from app.core.llm import PROVIDER_PRESETS, PROVIDER_PRESET_DISPLAY_NAMES, PROVIDER_GROUPS

    groups: dict[str, list[tuple[str, str]]] = {}
    for key, p in PROVIDER_PRESETS.items():
        grp = p.get("group", "china")
        label = PROVIDER_GROUPS.get(grp, grp)
        groups.setdefault(label, []).append(
            (PROVIDER_PRESET_DISPLAY_NAMES.get(key, key), key)
        )

    order = ["国际", "国内", "Coding Plan", "聚合", "本地"]
    result = []
    for g in order:
        g_label = PROVIDER_GROUPS.get(
            {"国际": "overseas", "国内": "china", "Coding Plan": "coding_plan",
             "聚合": "aggregator", "本地": "local"}.get(g, g), g
        )
        if groups:
            items = groups.pop(g_label, None)
            if items:
                result.append((g, items))
    # 兜底
    for k, v in groups.items():
        result.append((k, v))
    return result


# --------------------------------------------------------------------- #
# SettingsPopup
# --------------------------------------------------------------------- #

class SettingsPopup(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._parent_main = parent  # 保存父窗口引用, 用于跳转
        self._editing_name: str | None = None
        self.setWindowTitle("设置")
        self.setMinimumSize(640, 480)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._build()
        bind_theme(self, self._apply_theme)

    def _apply_theme(self) -> None:
        """主题切换时重新应用内联样式."""
        for lbl in self.findChildren(QLabel):
            if hasattr(lbl, '_theme_style'):
                lbl.setStyleSheet(lbl._theme_style())
        for btn in self.findChildren(QPushButton):
            if hasattr(btn, '_theme_style'):
                btn.setStyleSheet(btn._theme_style())

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.addTab(self._build_ai_tab(), "AI")
        tabs.addTab(self._build_appearance_tab(), "外观")
        tabs.addTab(self._build_storage_tab(), "存储")
        tabs.addTab(self._build_plugin_tab(), "插件")
        tabs.addTab(self._build_advanced_tab(), "高级")
        layout.addWidget(tabs)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    # ================================================================== #
    # AI Tab (v4.1 重写)
    # ================================================================== #

    def _build_ai_tab(self) -> QWidget:
        from app.services import app_setting_service
        from app.core.llm import PROVIDER_PRESETS, PROVIDER_PRESET_DISPLAY_NAMES

        w = QWidget()
        root = QVBoxLayout(w)

        # ---- 已配置的 Provider 列表 ----
        g_list = QGroupBox("已配置的 LLM 提供商")
        list_layout = QVBoxLayout(g_list)

        self._provider_list = QListWidget()
        self._provider_list.setMaximumHeight(140)
        self._provider_list.itemSelectionChanged.connect(self._on_sel_provider)
        list_layout.addWidget(self._provider_list)

        btn_list_row = QHBoxLayout()
        self._btn_add_new = QPushButton("＋ 新建")
        self._btn_add_new.clicked.connect(self._on_edit_new)
        self._btn_delete = QPushButton("🗑 删除")
        self._btn_delete.clicked.connect(self._on_delete_provider)
        self._btn_set_active = QPushButton("⭐ 设为当前")
        self._btn_set_active.clicked.connect(self._on_set_active)
        btn_list_row.addWidget(self._btn_add_new)
        btn_list_row.addWidget(self._btn_delete)
        btn_list_row.addStretch(1)
        btn_list_row.addWidget(self._btn_set_active)
        list_layout.addLayout(btn_list_row)

        root.addWidget(g_list)

        # ---- 编辑表单 ----
        g_form = QGroupBox("编辑提供商")
        form = QFormLayout(g_form)

        # 预设分组下拉
        self._cmb_preset = QComboBox()
        for grp_name, items in _grouped_presets():
            self._cmb_preset.insertSeparator(self._cmb_preset.count())
            self._cmb_preset.addItem(f"── {grp_name} ──")
            self._cmb_preset.model().item(
                self._cmb_preset.count() - 1
            ).setEnabled(False)
            for display, key in items:
                self._cmb_preset.addItem(f"  {display}", userData=key)
        self._cmb_preset.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow("预设:", self._cmb_preset)

        self._ed_name = QLineEdit()
        self._ed_name.setPlaceholderText("唯一标识, e.g. deepseek-main")
        form.addRow("名称:", self._ed_name)

        self._ed_api_base = QLineEdit()
        self._ed_api_base.setPlaceholderText("https://api.deepseek.com")
        form.addRow("API Base:", self._ed_api_base)

        self._ed_api_key = QLineEdit()
        self._ed_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._ed_api_key.setPlaceholderText("sk-... 或留空")
        form.addRow("API Key:", self._ed_api_key)

        self._cmb_model = QComboBox()
        self._cmb_model.setEditable(True)
        self._cmb_model.setPlaceholderText("选择或输入模型名")
        form.addRow("模型:", self._cmb_model)

        self._ed_timeout = QSpinBox()
        self._ed_timeout.setRange(10, 600)
        self._ed_timeout.setValue(120)
        self._ed_timeout.setSuffix(" 秒")
        form.addRow("超时:", self._ed_timeout)

        # 按钮行
        btn_form_row = QHBoxLayout()
        self._btn_save = QPushButton("💾 保存")
        self._btn_save.clicked.connect(self._on_save)
        self._btn_test = QPushButton("🧪 测试连接")
        self._btn_test.clicked.connect(self._on_test)
        btn_form_row.addWidget(self._btn_save)
        btn_form_row.addWidget(self._btn_test)
        btn_form_row.addStretch(1)
        form.addRow(btn_form_row)

        root.addWidget(g_form)

        # ---- 底部提示 ----
        link_row = QHBoxLayout()
        hint = QLabel("需要更多高级设置（温度/优先级/路由策略等）？")
        hint._theme_style = lambda: f"color: {text_subtle()}; font-size: 12px;"
        hint.setStyleSheet(hint._theme_style())
        link_row.addWidget(hint)
        go_btn = QPushButton("打开完整模型配置 →")
        go_btn.setFlat(True)
        go_btn._theme_style = lambda: f"color: {text_indigo()}; font-size: 12px;"
        go_btn.setStyleSheet(go_btn._theme_style())
        go_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        go_btn.clicked.connect(self._on_open_full_config)
        link_row.addWidget(go_btn)
        link_row.addStretch(1)
        root.addLayout(link_row)

        # 初始加载
        self._reload_provider_list()
        return w

    # ---- provider 列表 ----

    def _reload_provider_list(self) -> None:
        from app.services import app_setting_service
        self._provider_list.blockSignals(True)
        self._provider_list.clear()
        providers = app_setting_service.list_providers()
        active = app_setting_service.get_active_name()
        for p in providers:
            icon = "⭐ " if p["name"] == active else "   "
            item = QListWidgetItem(f"{icon}{p['name']}  ({p.get('model', '?')})")
            item.setData(Qt.ItemDataRole.UserRole, p["name"])
            self._provider_list.addItem(item)
        self._provider_list.blockSignals(False)

    def _on_sel_provider(self) -> None:
        from app.services import app_setting_service
        from app.core.llm import get_provider_preset

        item = self._provider_list.currentItem()
        if not item:
            self._clear_form()
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        try:
            p = app_setting_service.get_provider(name)
        except Exception:
            self._clear_form()
            return
        self._editing_name = name

        # 反查 preset
        api_base = p.get("api_base", "")
        matched_key = self._match_preset_key(api_base)
        idx = self._cmb_preset.findData(matched_key)
        if idx >= 0:
            self._cmb_preset.blockSignals(True)
            self._cmb_preset.setCurrentIndex(idx)
            self._cmb_preset.blockSignals(False)

        # 重建模型下拉
        preset = get_provider_preset(matched_key)
        self._cmb_model.blockSignals(True)
        self._cmb_model.clear()
        saved_model = p.get("model", "")
        found = False
        for m in preset.get("models", []):
            if m.get("enabled", True):
                self._cmb_model.addItem(m["id"], userData=m)
        for i in range(self._cmb_model.count()):
            if self._cmb_model.itemData(i).get("id") == saved_model:
                self._cmb_model.setCurrentIndex(i)
                found = True
                break
        if not found and saved_model:
            self._cmb_model.setCurrentText(saved_model)
        self._cmb_model.blockSignals(False)

        self._ed_name.setText(p.get("name", ""))
        self._ed_api_base.setText(p.get("api_base", ""))
        self._ed_api_key.setText(p.get("api_key", ""))
        self._ed_timeout.setValue(int(p.get("timeout", 120)))

    def _on_edit_new(self) -> None:
        self._editing_name = None
        self._clear_form()
        self._provider_list.clearSelection()
        self._ed_name.setFocus()

    def _clear_form(self) -> None:
        self._editing_name = None
        self._ed_name.clear()
        self._ed_api_base.clear()
        self._ed_api_key.clear()
        self._cmb_model.blockSignals(True)
        self._cmb_model.clear()
        self._cmb_model.blockSignals(False)
        self._ed_timeout.setValue(120)

    def _on_preset_changed(self, index: int) -> None:
        from app.core.llm import get_provider_preset
        key = self._cmb_preset.itemData(index)
        if not key:
            return
        preset = get_provider_preset(key)
        self._ed_api_base.setText(preset.get("api_base", ""))
        self._cmb_model.blockSignals(True)
        self._cmb_model.clear()
        for m in preset.get("models", []):
            if m.get("enabled", True):
                self._cmb_model.addItem(m["id"], userData=m)
        if self._cmb_model.count() > 0:
            self._cmb_model.setCurrentIndex(0)
        self._cmb_model.blockSignals(False)

    @staticmethod
    def _match_preset_key(api_base: str) -> str:
        from app.core.llm import PROVIDER_PRESETS
        best = "custom"
        best_len = 0
        for key, p in PROVIDER_PRESETS.items():
            pb = p.get("api_base", "")
            if pb and api_base.startswith(pb) and len(pb) > best_len:
                best = key
                best_len = len(pb)
        return best

    # ---- 按钮 ----

    def _on_save(self) -> None:
        from app.services import app_setting_service
        from app.services.exceptions import ValidationError

        name = self._ed_name.text().strip()
        if not name:
            QMessageBox.warning(self, "保存失败", "名称不能为空")
            return

        patch = {
            "provider_type": "openai_compat",
            "api_base": self._ed_api_base.text().strip(),
            "api_key": self._ed_api_key.text(),
            "model": self._cmb_model.currentText().strip(),
            "timeout": self._ed_timeout.value(),
        }

        try:
            if self._editing_name is None:
                payload = {"name": name, **patch}
                app_setting_service.add_provider(payload)
            else:
                app_setting_service.update_provider(self._editing_name, patch)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return

        self._reload_provider_list()
        QMessageBox.information(self, "已保存", f"Provider '{name}' 已保存")

    def _on_test(self) -> None:
        from app.core.llm import LLMClient, ProviderConfig, ProviderType, ChatMessage

        name = self._ed_name.text().strip()
        api_base = self._ed_api_base.text().strip()
        api_key = self._ed_api_key.text()
        model = self._cmb_model.currentText().strip()

        if not name or not model:
            QMessageBox.warning(self, "测试", "请先填写名称和模型")
            return

        try:
            cfg = ProviderConfig(
                name=name,
                provider_type=ProviderType.OPENAI_COMPAT,
                api_base=api_base,
                api_key=api_key,
                model=model,
                max_tokens=16,
                temperature=0.0,
                timeout=float(self._ed_timeout.value()),
                priority=0,
            )
        except Exception as e:
            QMessageBox.warning(self, "配置错误", str(e))
            return

        client = LLMClient()
        client.configure([cfg])
        try:
            resp = client.chat(
                [ChatMessage(role="user", content="hi")],
                temperature=0.0,
                max_tokens=8,
                step="test",
            )
        except Exception as e:
            QMessageBox.warning(self, "测试失败", str(e))
            return
        finally:
            client.close()

        QMessageBox.information(
            self, "测试成功",
            f"provider={resp.provider}\nmodel={resp.model}\n"
            f"tokens_in={resp.tokens_in} tokens_out={resp.tokens_out}\n"
            f"reply={resp.content[:80]!r}",
        )

    def _on_delete_provider(self) -> None:
        from app.services import app_setting_service

        item = self._provider_list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        ok = QMessageBox.question(
            self, "确认删除",
            f"删除 provider '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        try:
            app_setting_service.delete_provider(name)
        except Exception as e:
            QMessageBox.warning(self, "删除失败", str(e))
            return
        self._clear_form()
        self._reload_provider_list()

    def _on_set_active(self) -> None:
        from app.services import app_setting_service

        item = self._provider_list.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择一个 provider")
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        try:
            app_setting_service.set_active(name)
        except Exception as e:
            QMessageBox.warning(self, "设置失败", str(e))
            return
        self._reload_provider_list()
        QMessageBox.information(self, "已切换", f"当前 active = {name}")

    def _on_open_full_config(self) -> None:
        """打开完整模型配置弹窗."""
        from app.ui.widgets.dialogs import SubWindowDialog
        from app.ui.tabs.settings_tab import ModelSettingsWidget
        widget = ModelSettingsWidget()
        self.accept()
        dlg = SubWindowDialog(
            "完整模型配置",
            widget,
            width=960,
            height=640,
            parent=self._parent_main,
        )
        dlg.exec()

    # ================================================================== #
    # 其他 tabs (保持不变)
    # ================================================================== #

    def _build_appearance_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        g = QGroupBox("主题")
        f = QFormLayout(g)
        theme = QComboBox()
        theme.addItems(["深色（默认）", "浅色", "高对比"])
        f.addRow("主题:", theme)
        font_size = QSpinBox()
        font_size.setRange(10, 24)
        font_size.setValue(13)
        f.addRow("字体大小:", font_size)
        layout.addWidget(g)

        layout.addStretch(1)
        return w

    def _build_storage_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        g = QGroupBox("项目存储")
        f = QFormLayout(g)
        data_dir = QLineEdit()
        browse = QPushButton("浏览...")
        row = QHBoxLayout()
        row.addWidget(data_dir)
        row.addWidget(browse)
        browse.clicked.connect(lambda: self._browse_dir(data_dir))
        f.addRow("数据目录:", row)
        layout.addWidget(g)

        g2 = QGroupBox("备份")
        f2 = QFormLayout(g2)
        auto_backup = QCheckBox("保存时自动备份")
        auto_backup.setChecked(True)
        f2.addRow(auto_backup)
        interval = QSpinBox()
        interval.setRange(1, 30)
        interval.setValue(7)
        f2.addRow("备份间隔 (天):", interval)
        layout.addWidget(g2)

        layout.addStretch(1)
        return w

    def _build_plugin_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        label = QLabel("插件管理将在 v4.1 实现。")
        label._theme_style = lambda: f"color: {text_subtle()}; font-style: italic; padding: 20px;"
        label.setStyleSheet(label._theme_style())
        layout.addWidget(label)
        layout.addStretch(1)
        return w

    def _build_advanced_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        g = QGroupBox("日志")
        f = QFormLayout(g)
        log_level = QComboBox()
        log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        log_level.setCurrentText("INFO")
        f.addRow("日志级别:", log_level)
        layout.addWidget(g)

        g2 = QGroupBox("关于")
        layout2 = QVBoxLayout(g2)
        about_text = QLabel(
            "Novel Writer Pure v4.1\n"
            "故事引擎 + 故事引导系统\n\n"
            "开源协议: MIT"
        )
        about_text._theme_style = lambda: f"color: {text_secondary()}; padding: 8px;"
        about_text.setStyleSheet(about_text._theme_style())
        layout2.addWidget(about_text)
        layout.addWidget(g2)

        layout.addStretch(1)
        return w

    @staticmethod
    def _browse_dir(line_edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(None, "选择目录")
        if path:
            line_edit.setText(path)
