# UI 安全重构 Checklist

**目的**：在按 Solarized 原型重写 ui/ 时，**保证不破坏 app/ 数据层和 plugins/ 的调用**。

---

## 1. 必须保留的接口契约

### 1.1 main_window.py / main_window_ui.py
- 入口：`MainWindow` 类（main.py 第 30 行调用 `MainWindow()`）
- 公开方法：被 main.py 和 tab 调用的所有方法
  - `set_project_id(project_id)` — 项目切换
  - `show_message(title, text, type)` — 弹窗（用 QMessageBox）
  - `container` 属性 — DI 容器（被 plugins/ 用）
  - 信号：theme_changed、project_changed、chapter_changed
  - 槽：`on_project_loaded`、`on_theme_changed`、`on_chapter_generated`
- **不能改**：类名、构造签名、所有公开方法签名

### 1.2 每个 Tab/Dialog 公开 API
| 文件 | 公开方法（被 app/ 或外部调） |
|------|----------------------------|
| `tabs/outline/outline_tab.py::OutlineTab` | `set_project_id(pid)`、`save_data()` |
| `tabs/generator/generator_tab.py::GeneratorTab` | `set_project_id(pid)`、`start_generation()`、`stop()` |
| `tabs/editor_tab.py::EditorTab` | `set_project_id(pid)`、`load_chapter(ch_no)` |
| `tabs/dashboard_tab.py::DashboardTab` | `set_project_id(pid)`、`refresh()` |
| `dialogs/welcome_dialog.py::WelcomeDialog` | `exec()`, `get_selected_project_id()` |
| `dialogs/model_config.py::ModelConfigDialog` | `exec()`, `get_config()` |
| `dialogs/license_dialog.py::LicenseDialog` | `exec()`, `get_license_key()` |
| `dialogs/memory_viewer.py::MemoryViewerDialog` | `__init__(parent, project_id, mm)` |
| `dialogs/user_confirm_dialog.py::UserConfirmDialog` | `__init__(parent, chapter_no)` |
| `dialogs/version_select_dialog.py::VersionSelectDialog` | `__init__(parent, chapter_no)` |
| `dialogs/self_critique_report_dialog.py::SelfCritiqueReportDialog` | `__init__(parent, chapter_no)` |
| `dialogs/subtext_card_dialog.py::SubtextCardDialog` | `__init__(parent, chapter_no)` |
| `dialogs/knowledge_base_dialog.py::KnowledgeBaseDialog` | `exec()` |
| `dialogs/style_fingerprint_dialog.py::StyleFingerprintDialog` | `__init__(parent, project_id)` |
| `dialogs/plugin_config_dialog.py::PluginConfigDialog` | `__init__(parent, container)` |
| `dialogs/voice_profile_dialog.py::VoiceProfileDialog` | `__init__(parent)` |
| `dialogs/anti_rule_editor_dialog.py::AntiRuleEditorDialog` | `__init__(parent)` |
| `dialogs/memory_editor_dialog.py::MemoryEditorDialog` | `__init__(parent, mm, project_id)` |
| `dialogs/import_dialog.py::ImportDialog` | `exec()`, `get_data()` |

### 1.3 主题系统（ui/utils/theme.py）
**必须保留**：
- `Theme.is_dark()` / `Theme.current()` / `Theme.set_theme(name)` / `Theme.apply(app)`
- `Theme.color(token_name)` — 返回色值字符串
- `Theme.color('accent_primary')` / `bg_elevated` / `text_primary` 等所有 token 名
- `DARK_COLORS` / `LIGHT_COLORS` 全局 dict（被外部直接 import）
- `get_theme_signals()` — 返回 ThemeSignals
- `ThemeSignals.theme_changed` 信号

**可以改**：
- `_QSS_TEMPLATE` 内容（重写）
- `_apply_qss()` / `_repolish_all()` 内部细节
- `SIZE_RADIUS` / `FONTS` 数值（如果需要）

**不能改**：
- 任何被外部 `from ui.utils.theme import XXX` 引用的符号

### 1.4 按钮样式（ui/utils/button_styles.py）
**必须保留**：
- `make_btn_style(semantic)` 函数签名
- 5 个语义角色：`primary` / `important` / `warning` / `auxiliary` / `default`
- 返回 str 形式的 QSS

---

## 2. 重构时序（防破坏）

### 2.1 顺序
1. **第 1 步**：重写 `theme.py` + `button_styles.py`（**不动其他文件**）
2. 跑 47 个 UI 一致性测试 → 必须全过
3. **第 2 步**：重写 `main_window.py`（壳子）
4. 启动 app，截图验证主窗口能开
5. **第 3 步**：重写侧栏 + 顶栏 + 底栏
6. **第 4 步**：逐个 Tab 重写（**每写一个跑测试**）
7. **第 5 步**：逐个 Dialog 重写
8. **第 6 步**：写视觉回归测试

### 2.2 风险控制
- **每 Phase 结束**跑 `python d:/novel-writer-pure/tests/run_ui_consistency.py`
- **每 Phase 结束**跑后端 `python -m pytest d:/novel-writer-pure/tests/backend/`
- **失败**立即回滚 git，定位问题

### 2.3 Git 策略
- 每个 Phase 独立 commit（feat(theme): / refactor(main_window): / refactor(sidebar): ...）
- 失败可 `git reset --hard HEAD~1`

---

## 3. 不改的"业务真相"清单

以下数据是**业务规则**，重写 UI 时**不能改**：

| 数据 | 位置 | 不能改的理由 |
|------|------|------------|
| `V3_DEFAULT_STEPS` = WRITE/SELF_CRITIQUE/PERSIST | generator_tab.py | 3.0 范式 |
| `V3_USER_CONFIRM_STEPS` = +USER_CONFIRM | generator_tab.py | 3.1 增强（10 章内） |
| `V3_MULTI_VERSION_STEPS` = +SELECT_VERSION | generator_tab.py | 3.1 增强 |
| `WORKFLOW_STATES` = IDLE/WRITE/SELF_CRITIQUE/PERSIST/DONE | project_db.py | 3.0 状态机 |
| `OUTLINE_TYPES` 列表 | outline_tab.py | 业务类型 |
| 角色/章节/物品/伏笔/地点 字段名 | db models | 数据模型 |

---

## 4. 与 main.py 的对接

`main.py` 第 30 行附近会 `from ui.main_window import MainWindow`，然后 `MainWindow().show()`。

**重构后**：`ui/main_window.py` 重新导出 `MainWindow` 类即可（保留类名）。

---

## 5. 视觉回归测试模板

`tests/visual_regression/test_solarized_themes.py`：

```python
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
sys.path.insert(0, r"d:\novel-writer-pure")

from PyQt6.QtWidgets import QApplication
from ui.utils.theme import Theme
from ui.main_window import MainWindow
import pytest


def capture_screenshot(theme: str) -> str:
    app = QApplication.instance() or QApplication(sys.argv)
    Theme.set_theme(theme)
    win = MainWindow()
    win.show()
    app.processEvents()
    out = f"tests/visual_regression/_baseline/{theme}_main.png"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    win.grab().save(out)
    return out


def test_dark_theme_matches_baseline():
    # 第一次跑会创建基线
    # 后续跑用 image diff 库（pixelmatch）对比
    ...
```

---

## 6. 立即可做（不依赖原型）

- [ ] 用 Pylint / ruff 跑一遍 `app/` 找 dead code（不依赖 ui）
- [ ] 写一个 `app/services/ui_bridge.py` 把 ui 依赖的 app 方法集中（重构时接口更稳定）
- [ ] 写视觉回归测试的骨架（先跑基线生成）

---

**版本**：v0.1（与 PRD 配套）
