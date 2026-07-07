"""
Reusable composite widgets shared across tabs (I4-I24).

设计参考 docs/widgets-mockup.html (2026-06-10 批准).

公开 API:
- CollapsiblePanel    (I4)  - 折叠面板
- ColorPalette        (I5)  - 颜色面板
- ThemeToggle         (I5)  - 暗/亮主题切换 (对接 ThemeManager)
- Dialogs             (I6)  - 弹窗库便捷调用入口
  - ConfirmDialog / InputDialog / MultiSelectDialog / SubWindowDialog
- RichTextViewer      (I13) - Markdown/HTML 富文本
- SystemTray / TrayAction (I14) - 系统托盘
- SplitterHelper      (I16) - 分割条比例保存
- ImageLabel          (I17) - 图像 + 缩放
- MultiPageInput      (I20) - 向导式多步表单
- ProgressDialog      (I22) - 进度条弹窗
- FontSetting         (I24) - 字体设置
- Button Utils     (v4.0P) - 按钮工厂 + 布局标准化 + 事件诊断

使用:
    from app.ui.widgets import CollapsiblePanel, ColorPalette, Dialogs
"""
from app.ui.widgets.collapsible import CollapsiblePanel
from app.ui.widgets.color_palette import (
    ColorPalette,
    DEFAULT_PALETTE,
    PaletteEntry,
    ThemeToggle,
)
from app.ui.widgets.dialogs import (
    ConfirmDialog,
    Dialogs,
    InputDialog,
    MultiSelectDialog,
    SubWindowDialog,
)
from app.ui.widgets.anti_rule_editor_dialog import AntiRuleEditorDialog
from app.ui.widgets.memory_editor_dialog import MemoryEditorDialog
from app.ui.widgets.font_setting import FontSetting
from app.ui.widgets.image_label import ImageLabel
from app.ui.widgets.multi_page import MultiPageInput, PageSpec
from app.ui.widgets.new_project_dialog import NewProjectDialog
from app.ui.widgets.progress_dialog import ProgressDialog
from app.ui.widgets.rich_text import RichTextViewer
from app.ui.widgets.splitter_helper import SplitterHelper
from app.ui.widgets.tray import SystemTray, TrayAction
from app.ui.widgets.export_dialog import ExportDialog  # M10-A
from app.ui.widgets.license_widget import LicenseWidget  # M10-B
from app.ui.widgets.publish_progress import PublishProgressWidget  # M11-D
from app.ui.widgets.publish_wizard import PublishWizard  # M11-D
from app.ui.widgets.feature_gate_widgets import (  # M10-C
    FeatureGateBadge, apply_feature_gate, refresh_all_badges,
    assert_feature_or_dialog, is_feature_available, get_current_tier_label,
)
from app.ui.widgets.router_status_bar import RouterStatusBar  # M10-D
from app.ui.widgets.conversation_wizard_dialog import ConversationWizardDialog  # V4.0-P4
from app.ui.widgets.conversation_creation_dialog import ConversationCreationDialog  # V4.0-P5
from app.ui.widgets._guide_panel import GuidePanel  # v3.5.2 Story Guidance 面板
from app.ui.widgets.button_utils import (  # v4.0P 按钮规范补丁
    make_button, standardize_layout, diagnose_button_click, ensure_button_clickable,
)

__all__ = [
    # I4
    "CollapsiblePanel",
    # I5
    "ColorPalette",
    "DEFAULT_PALETTE",
    "PaletteEntry",
    "ThemeToggle",
    # I6
    "ConfirmDialog",
    "Dialogs",
    "InputDialog",
    "MultiSelectDialog",
    "SubWindowDialog",
    "AntiRuleEditorDialog",  # v3.3.0
    "MemoryEditorDialog",     # v3.3.0
    "NewProjectDialog",       # 综合新建项目弹窗 (替换两次 Dialogs.input)
    # I13
    "RichTextViewer",
    # I14
    "SystemTray",
    "TrayAction",
    # I16
    "SplitterHelper",
    # I17
    "ImageLabel",
    # I20
    "MultiPageInput",
    "PageSpec",
    # I22
    "ProgressDialog",
    # I24
    "FontSetting",
    # M10-A
    "ExportDialog",
    # M10-B
    "LicenseWidget",
    # M10-C
    "FeatureGateBadge",
    "apply_feature_gate",
    "refresh_all_badges",
    "assert_feature_or_dialog",
    "is_feature_available",
    "get_current_tier_label",
    # M10-D
    "RouterStatusBar",
    # M11-D
    "PublishWizard",
    "PublishProgressWidget",
    # V4.0-P4
    "ConversationWizardDialog",
    # V4.0-P5
    "ConversationCreationDialog",
    # v3.5.2
    "GuidePanel",
    # v4.0P 按钮规范补丁
    "make_button",
    "standardize_layout",
    "diagnose_button_click",
    "ensure_button_clickable",
]
