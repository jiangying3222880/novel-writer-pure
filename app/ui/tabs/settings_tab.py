"""
Settings tab (小说设定 + 模型配置 + 改稿信号).

三个 sub-tab:
  - 📚 小说设定: 项目级 JSON 设定 (worldbuilding / characters / anti_rules 等)
  - 🤖 模型: 全局 LLM provider 配置 (app_setting_service)
  - 📚 改稿信号: v3.0 Edit Signals 4 档开关 + 试运行/立即聚类/立即进化/一键清空
"""
from __future__ import annotations
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QObject, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QComboBox,
    QLineEdit,
    QFormLayout,
    QGroupBox,
    QCheckBox,
    QAbstractItemView,
    QFileDialog,
    QMessageBox,
    QFrame,
    QStackedWidget,
    QSlider,
)

# ---- 共用小工具 (从 pages.py 抽过来) ----

def _section_header(title: str, parent: QWidget | None = None) -> QLabel:
    h = QLabel(title, parent)
    h.setStyleSheet("font-size: 14px; font-weight: 600; padding: 4px 0;")
    return h


def _sub_header(title: str, parent: QWidget | None = None) -> QLabel:
    from app.ui.theme import text_muted
    h = QLabel(title, parent)
    h.setStyleSheet(f"font-size: 12px; font-weight: 600; padding: 2px 0; color: {text_muted()};")
    return h


def _spin(lo: int, hi: int, init: int):
    from app.ui.widgets._number_input import NumberInput
    return NumberInput(lo=lo, hi=hi, default=init)

from app.services import setting_service, app_setting_service, project_service, ServiceError
from app.services import genre_presets
from app.ui.widgets import Dialogs, LicenseWidget  # M10-B
from app.ui.widgets._number_input import NumberInput, DoubleInput
from app.ui.theme import (
    text_muted, text_subtle, text_warn, text_warn_ok, text_danger,
    text_indigo, text_secondary, text_primary, surface_bg, deep_bg,
    border_color, hover_bg, accent_tint_bg, accent_tint_border,
)

# 反规则在 PROJECT_SETTING_LABELS 里的 key
_ANTI_RULES_KEY = "anti_rules"

# v3.0 Edit Signals (静默导入, 关了也不报错)
try:
    from app.core import config as _app_config
    from app.workflow import edit_signals as _es
    _HAS_ES = True
except Exception:
    _app_config = None
    _es = None
    _HAS_ES = False

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# preset ↔ provider_type 转换辅助
# --------------------------------------------------------------------- #

def _resolve_provider_type(preset_name: str, api_base_fallback: str) -> str:
    """由 api_base 启发式决定 provider_type. preset 只用于填默认 base/model, 不影响 type."""
    if "anthropic" in (api_base_fallback or "").lower():
        return "anthropic"
    return "openai_compat"


def _match_preset(provider: dict) -> str:
    """由已存 provider 反查最匹配的 preset 名 (按 api_base 精确匹配, 找不到返回 'custom')."""
    from app.core.llm import PROVIDER_PRESETS
    base = (provider.get("api_base") or "").rstrip("/")
    for name, preset in PROVIDER_PRESETS.items():
        if preset.get("api_base", "").rstrip("/") == base:
            return name
    return "custom"


PROJECT_SETTING_LABELS = {
    "anti_rules": "🚫 全文反规则",
}


# --------------------------------------------------------------------- #
# A1 题材 + 基础信息编辑卡
# --------------------------------------------------------------------- #

class BasicInfoWidget(QGroupBox):
    """项目基础信息 (项目名 / 书名 / 作者 / 主题材 / 副题材 / 平台 / 字数目标 / 分卷结构).

    V4.0-P4-新: 同步项目管理弹窗 (NewProjectDialog) 的所有字段.
      - 主题材 (单选, QComboBox, 16 类大分类)
      - 副题材 (多选, chip + MultiSelectDialog, 元素标签)
      - 作者 (V4.0-P3 引入)
      - 分卷数 / 章节数 / 章节字数 (V4.0-P2 引入, 只读, 因为改它们会破坏已建 books)
      - 字数目标 (可改)

    主题材 ↔ project.genre (单值). 副题材 ↔ structure.json 的 sub_genres (list).
    旧版是多选 (1-5 个), 现在主+副双轨, 数据兼容: 旧数据有逗号分隔的 genre 字符串,
    set_project 时把第一个解析成主题材, 后续 parse 进 sub_genres.
    """

    def __init__(self, on_changed=None) -> None:
        super().__init__(" 项目基础信息")
        self.current_project: Optional[dict] = None
        self._on_changed = on_changed
        # 副题材 / 平台 内部状态 (驱动 chip label)
        self._sub_genres: List[str] = []
        self._platform_list: List[str] = []
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        form = QFormLayout()
        outer.addLayout(form)

        # 1) 项目名
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("项目名 (e.g. 我的第一本书)")
        self.ed_name.setMaxLength(64)
        form.addRow("项目名 *:", self.ed_name)

        # 2) 书名
        self.ed_book_title = QLineEdit()
        self.ed_book_title.setPlaceholderText("书名 (显示给读者看的)")
        self.ed_book_title.setMaxLength(64)
        form.addRow("书名:", self.ed_book_title)

        # 3) 作者 (V4.0-P4-新)
        self.ed_author = QLineEdit()
        self.ed_author.setPlaceholderText("作者笔名 (可空)")
        self.ed_author.setMaxLength(64)
        form.addRow("作者:", self.ed_author)

        # 4) 主题材 (单选, QComboBox)
        self.cmb_main_genre = QComboBox()
        self.cmb_main_genre.setObjectName("cmbMainGenre")
        self.cmb_main_genre.addItem("（请选择）", userData=None)
        for _gid, name, _desc, _kw in genre_presets.GENRE_PRESETS:
            self.cmb_main_genre.addItem(name, userData=name)
        self.cmb_main_genre.currentIndexChanged.connect(self._on_main_genre_changed)
        form.addRow("主题材 *:", self.cmb_main_genre)

        # 5) 副题材 (多选, chip + 弹窗)
        sub_row = QHBoxLayout()
        sub_row.setSpacing(6)
        self.lbl_sub = QLabel("（未选）")
        self.lbl_sub.setObjectName("valueLabel")
        self.lbl_sub.setWordWrap(True)
        sub_row.addWidget(self.lbl_sub, 1)
        btn_sub = QPushButton("🏷️ 选择…")
        btn_sub.setObjectName("btnPickSubGenre")
        btn_sub.setToolTip("选 0~N 个元素标签: 脑洞/爽文/穿越/重生/系统/无限流/...")
        btn_sub.clicked.connect(self._pick_subgenre)
        sub_row.addWidget(btn_sub)
        form.addRow("副题材 (可多选):", sub_row)

        # 6) 平台 (多选 chip)
        plat_row = QHBoxLayout()
        plat_row.setSpacing(6)
        self.lbl_plat = QLabel("（未选）")
        self.lbl_plat.setObjectName("valueLabel")
        self.lbl_plat.setWordWrap(True)
        plat_row.addWidget(self.lbl_plat, 1)
        btn_plat = QPushButton("🏷️ 选择…")
        btn_plat.setObjectName("btnPickPlatform")
        btn_plat.clicked.connect(self._pick_platform)
        plat_row.addWidget(btn_plat)
        form.addRow("发布平台:", plat_row)

        # 7) 字数目标
        self.spn_word_target = NumberInput(lo=10_000, hi=10_000_000, default=200_000, suffix=" 字")
        form.addRow("字数目标:", self.spn_word_target)

        # 8) 分卷结构 (V4.0-P4-新: 只读, 由项目管理弹窗的 NewProjectDialog 锁定)
        struct_frame = QFrame()
        struct_frame.setObjectName("structFrame")
        struct_frame.setStyleSheet(
            "QFrame#structFrame {"
            "  background: rgba(99, 102, 241, 0.06);"
            "  border: 1px solid rgba(99, 102, 241, 0.20);"
            "  border-radius: 6px;"
            "  padding: 8px 10px;"
            "}"
        )
        struct_grid = QGridLayout(struct_frame)
        struct_grid.setContentsMargins(0, 0, 0, 0)
        struct_grid.setHorizontalSpacing(12)
        struct_grid.setVerticalSpacing(2)

        # 标题 (灰底)
        lbl_struct_title = QLabel("📐 分卷结构 (建项目时锁定, 不可改)")
        lbl_struct_title.setObjectName("structTitle")
        lbl_struct_title.setStyleSheet(f"color: {text_muted()}; font-size: 11px; font-weight: 600;")
        struct_grid.addWidget(lbl_struct_title, 0, 0, 1, 4)

        # 4 个只读字段
        self.lbl_struct_volumes = QLabel("—")
        self.lbl_struct_volumes.setObjectName("structValue")
        self.lbl_struct_cpv = QLabel("—")
        self.lbl_struct_cpv.setObjectName("structValue")
        self.lbl_struct_wpc = QLabel("—")
        self.lbl_struct_wpc.setObjectName("structValue")
        self.lbl_struct_total = QLabel("—")
        self.lbl_struct_total.setObjectName("structValue")
        for w in (self.lbl_struct_volumes, self.lbl_struct_cpv,
                  self.lbl_struct_wpc, self.lbl_struct_total):
            w.setStyleSheet(f"color: {text_indigo()}; font-size: 13px; font-weight: 700;")

        lbl_v = QLabel("分卷数")
        lbl_v.setObjectName("structLabel")
        lbl_c = QLabel("单元数/卷")
        lbl_c.setObjectName("structLabel")
        lbl_w = QLabel("单元字数")
        lbl_w.setObjectName("structLabel")
        lbl_t = QLabel("总单元数")
        lbl_t.setObjectName("structLabel")
        for w in (lbl_v, lbl_c, lbl_w, lbl_t):
            w.setStyleSheet(f"color: {text_muted()}; font-size: 10px;")

        struct_grid.addWidget(lbl_v, 1, 0)
        struct_grid.addWidget(self.lbl_struct_volumes, 2, 0)
        struct_grid.addWidget(QLabel("×"), 2, 1, Qt.AlignmentFlag.AlignCenter)
        struct_grid.addWidget(lbl_c, 1, 2)
        struct_grid.addWidget(self.lbl_struct_cpv, 2, 2)
        struct_grid.addWidget(QLabel("×"), 2, 3, Qt.AlignmentFlag.AlignCenter)
        struct_grid.addWidget(lbl_w, 1, 4)
        struct_grid.addWidget(self.lbl_struct_wpc, 2, 4)
        struct_grid.addWidget(QLabel("= "), 2, 5, Qt.AlignmentFlag.AlignCenter)
        struct_grid.addWidget(lbl_t, 1, 6)
        struct_grid.addWidget(self.lbl_struct_total, 2, 6)
        struct_grid.setColumnStretch(7, 1)

        form.addRow("", struct_frame)

        # 全文反规则 — 纯文本编辑
        outer.addWidget(_sub_header("🚫 全文反规则"))
        self.ed_anti_rules = QPlainTextEdit()
        self.ed_anti_rules.setPlaceholderText(
            "全文反规则示例：\n\n"
            "禁止使用以下表达：\n"
            "- \"仿佛\" \"好像\" \"似乎\" (过度使用比喻)\n"
            "- \"不禁\" \"忍不住\" (滥用情绪反应)\n"
            "- \"竟然\" \"居然\" (过度惊讶)\n\n"
            "格式要求：\n"
            "- 每行一条规则\n"
            "- 支持正则表达式匹配"
        )
        outer.addWidget(self.ed_anti_rules, 1)

        # 统一保存
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setEnabled(False)
        btn_row.addWidget(self.btn_save)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

    def set_project(self, project: Optional[dict]) -> None:
        """V4.0-P4-新: 同步所有字段, 包括 author / main_genre / sub_genres / volumes 等.

        project dict 由 project_service.get() 返回, 已合并 structure.json 的字段
        (volumes / chapters_per_volume / words_per_chapter / sub_genres / author).
        """
        self.current_project = project
        self.btn_save.setEnabled(project is not None)
        if project is None:
            self.ed_name.clear()
            self.ed_book_title.clear()
            self.ed_author.clear()
            self.cmb_main_genre.setCurrentIndex(0)
            self._sub_genres = []
            self._update_sub_label()
            self._platform_list = []
            self._update_platform_label()
            self.spn_word_target.setValue(200_000)
            self.lbl_struct_volumes.setText("—")
            self.lbl_struct_cpv.setText("—")
            self.lbl_struct_wpc.setText("—")
            self.lbl_struct_total.setText("—")
            self.ed_anti_rules.clear()
            return

        # 1) 项目名 / 书名
        self.ed_name.setText(project.get("name", "") or "")
        self.ed_book_title.setText(project.get("book_title", "") or "")

        # 2) 作者 (V4.0-P4-新: 从 project dict 读, get() 已合并 structure.json)
        self.ed_author.setText(project.get("author", "") or "")

        # 3) 主题材: project.genre (单值) → 找对应 index
        # 兼容旧数据: 旧 genre 是逗号分隔的字符串, 取第一个当主题材
        raw_genre = (project.get("genre") or "").strip()
        main_genre = ""
        if raw_genre:
            first = raw_genre.split("、")[0].split(",")[0].strip()
            main_genre = first
        idx = 0  # 默认「请选择」
        if main_genre:
            for i in range(self.cmb_main_genre.count()):
                if self.cmb_main_genre.itemData(i) == main_genre:
                    idx = i
                    break
        self.cmb_main_genre.blockSignals(True)
        self.cmb_main_genre.setCurrentIndex(idx)
        self.cmb_main_genre.blockSignals(False)

        # 4) 副题材: 优先读 sub_genres (list); 兼容旧数据 (逗号分隔在 genre 里)
        subs = project.get("sub_genres") or []
        if isinstance(subs, str):
            subs = genre_presets.parse_subgenre_string(subs)
        elif not isinstance(subs, list):
            subs = []
        # 旧数据兼容: 旧 genre 字符串里「除主题材外的其它项」也加进来当 sub
        if not subs and raw_genre:
            all_names = [s.strip() for s in raw_genre.replace("、", ",").split(",") if s.strip()]
            for n in all_names:
                if n and n != main_genre and n in set(genre_presets.list_subgenre_names()):
                    subs.append(n)
        # 过滤: 只保留在 SUBGENRE_PRESETS 里的 (兼容/容错)
        valid = set(genre_presets.list_subgenre_names())
        self._sub_genres = [s for s in subs if s in valid]
        self._update_sub_label()

        # 5) 平台: project.platform (逗号分隔字符串 → list)
        plat = project.get("platform") or ""
        if isinstance(plat, str) and plat:
            self._platform_list = [
                p for p in plat.replace("、", ",").split(",")
                if p.strip() and p in set(genre_presets.PLATFORM_PRESETS)
            ]
        else:
            self._platform_list = []
        self._update_platform_label()

        # 6) 字数目标
        try:
            self.spn_word_target.setValue(int(project.get("word_target") or 200_000))
        except (TypeError, ValueError):
            self.spn_word_target.setValue(200_000)

        # 7) 分卷结构 (只读)
        try:
            v = int(project.get("volumes") or 1)
        except (TypeError, ValueError):
            v = 1
        try:
            cpv = int(project.get("chapters_per_volume") or 100)
        except (TypeError, ValueError):
            cpv = 100
        try:
            wpc = int(project.get("words_per_chapter") or 2000)
        except (TypeError, ValueError):
            wpc = 2000
        self.lbl_struct_volumes.setText(f"{v} 卷")
        self.lbl_struct_cpv.setText(f"{cpv} 单元")
        self.lbl_struct_wpc.setText(f"{wpc:,} 字")
        total_chap = v * cpv
        self.lbl_struct_total.setText(f"{total_chap:,} 单元")

        # 加载全文反规则
        self.ed_anti_rules.clear()
        try:
            data = setting_service.get_setting(project["id"], _ANTI_RULES_KEY)
        except ServiceError as e:
            Dialogs.warning("加载设定", str(e), parent=self)
            return
        if data.get("data") is not None:
            if isinstance(data["data"], str):
                self.ed_anti_rules.setPlainText(data["data"])
            else:
                self.ed_anti_rules.setPlainText(
                    json.dumps(data["data"], ensure_ascii=False, indent=2)
                )

    # ------------------------------------------------------------------
    # Picker handlers
    # ------------------------------------------------------------------
    def _on_main_genre_changed(self, idx: int) -> None:
        # userData 存的是显示名; idx=0 是 None
        pass  # 当前不依赖实时通知, 保存时读 self.cmb_main_genre 即可

    def _pick_subgenre(self) -> None:
        from app.ui.widgets import MultiSelectDialog
        options: List[tuple] = [
            (name, name in self._sub_genres, "") for name in genre_presets.list_subgenre_names()
        ]
        dlg = MultiSelectDialog(
            "选择副题材（可多选, 0~N 个元素标签）",
            options,
            parent=self,
        )
        if dlg.exec():
            self._sub_genres = dlg.selected_labels()
            self._update_sub_label()

    def _pick_platform(self) -> None:
        from app.ui.widgets import MultiSelectDialog
        options: List[tuple] = [
            (p, p in self._platform_list, "") for p in genre_presets.PLATFORM_PRESETS
        ]
        dlg = MultiSelectDialog(
            "选择平台（可多选）",
            options,
            parent=self,
        )
        if dlg.exec():
            self._platform_list = dlg.selected_labels()
            self._update_platform_label()

    def _update_sub_label(self) -> None:
        if not self._sub_genres:
            self.lbl_sub.setText("（未选）")
            self.lbl_sub.setToolTip("")
            return
        if len(self._sub_genres) > 3:
            shown = "、".join(self._sub_genres[:3]) + f"… 等 {len(self._sub_genres)} 个"
        else:
            shown = "、".join(self._sub_genres)
        self.lbl_sub.setText(shown)
        self.lbl_sub.setToolTip("、".join(self._sub_genres))

    def _update_platform_label(self) -> None:
        if not self._platform_list:
            self.lbl_plat.setText("（未选）")
            self.lbl_plat.setToolTip("")
            return
        self.lbl_plat.setText("、".join(self._platform_list))
        self.lbl_plat.setToolTip("、".join(self._platform_list))

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def _on_save(self) -> None:
        if not self.current_project:
            return
        name = self.ed_name.text().strip()
        if not name:
            Dialogs.warning("保存失败", "项目名不能为空", parent=self)
            return
        # 主题材: 从 combo 取 userData (idx=0 是 None)
        main_genre = self.cmb_main_genre.currentData()
        if not main_genre:
            Dialogs.warning("保存失败", "请选择 1 个主题材（如: 玄幻/都市/仙侠…）", parent=self)
            return
        try:
            updated = project_service.update(
                self.current_project["id"],
                name=name,
                book_title=self.ed_book_title.text().strip() or None,
                author=self.ed_author.text().strip() or None,
                # 4.0 双轨: 主题材写 genre (单), 副题材写 sub_genres (多)
                genre=main_genre,
                sub_genres=list(self._sub_genres),
                platform="、".join(self._platform_list) if self._platform_list else None,
                word_target=int(self.spn_word_target.value()),
            )
        except ServiceError as e:
            Dialogs.warning("保存失败", str(e), parent=self)
            return
        self.current_project = updated
        # V4.0-P4: project_service.update 内部已经 publish event, ProjectsPage / NovelSettingsPage 自动同步.
        # 详情面板的题材显示是「主题材 (副题材1/副题材2/...)」格式, 由 ProjectsPage 自己在 reload 时组装.

        # 同时保存全文反规则
        anti_raw = self.ed_anti_rules.toPlainText().strip()
        try:
            setting_service.set_setting(updated["id"], _ANTI_RULES_KEY, anti_raw)
        except ServiceError as e:
            Dialogs.warning("反规则保存失败", str(e), parent=self)

        Dialogs.info(
            "保存",
            f"基础信息已保存\n项目: {updated.get('name')}\n"
            f"作者: {updated.get('author') or '(未填)'}\n"
            f"题材: {updated.get('genre') or '(空)'}"
            + (f" + ({' / '.join(updated.get('sub_genres') or [])})"
               if (updated.get('sub_genres') or []) else ""),
            parent=self,
        )
        if self._on_changed:
            self._on_changed(updated)


# --------------------------------------------------------------------- #
# Sub-tab 1: 小说设定 (项目级)
# --------------------------------------------------------------------- #

class ProjectSettingsWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.current_project: Optional[dict] = None
        # V4.0-P4-新: 订阅 project_event_bus, 当外部 (项目管理弹窗 / 三步对话)
        # update 了当前项目, 这里自动 reload 基础信息 (作者/主题材/副题材/...).
        from app.services import project_event_bus
        self._event_handler = project_event_bus.subscribe(self._on_project_event)
        self.destroyed.connect(lambda *_: project_event_bus.unsubscribe(self._event_handler))
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        self.title = QLabel("小说设定（未选择项目）")
        self.title.setObjectName("projectTitle")
        outer.addWidget(self.title)

        # A1 题材 + 基础信息卡 + 全文反规则 (全部合并在 BasicInfoWidget 内)
        self.basic_info = BasicInfoWidget(on_changed=self._on_basic_info_saved)
        outer.addWidget(self.basic_info, 1)

    def set_project(self, project: Optional[dict]) -> None:
        self.current_project = project
        if project is None:
            self.title.setText("小说设定（未选择项目）")
            self.basic_info.set_project(None)
            return
        self.title.setText(f"小说设定 — {project.get('name', '')}")
        # BasicInfoWidget 内部负责加载基础信息 + 全文反规则
        self.basic_info.set_project(project)

    def _on_basic_info_saved(self, updated_project: dict) -> None:
        """基础信息保存后回调. 刷新 title, 当前 project 引用, 以及上层 (e.g. main_window)."""
        self.current_project = updated_project
        self.title.setText(f"小说设定 — {updated_project.get('name', '')}")

    def _on_project_event(self, event: str, pid: str, project: Optional[dict]) -> None:
        """V4.0-P4-新: project.updated → 如果是当前打开的项目, 重 load basic_info.

        这样不论是项目管理页编辑、还是三步对话创建、还是别处更新, 当前打开
        的小说设定页都会自动反映最新数据.
        """
        try:
            if not self.current_project or not project:
                return
            if self.current_project.get("id") != pid:
                return
            if event in ("project.updated", "project.created"):
                self.set_project(project)
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(
                "ProjectSettingsWidget._on_project_event failed: %s", e
            )



    def _on_import_outline(self) -> None:
        """弹文件选择 → 写入 chapter.outline (或 setting_service.chapter_outline 兜底)."""
        if not self.current_project:
            return
        from PySide6.QtWidgets import QFileDialog
        from app.services import setting_io
        path, _ = QFileDialog.getOpenFileName(
            self, "选择大纲文件 (md / json)",
            "", "Markdown / JSON (*.md *.markdown *.json);;All files (*.*)",
        )
        if not path:
            return
        try:
            result = setting_io.import_outlines(self.current_project["id"], path)
        except Exception as e:
            Dialogs.warning("导入失败", str(e), parent=self)
            return
        Dialogs.info(
            "导入完成",
            f"已导入章节大纲: {result.get('imported', 0)} 章\n"
            f"新建分卷: {result.get('created_volumes', 0)} 卷\n"
            f"新建章节: {result.get('created_chapters', 0)} 章\n"
            f"格式: {result.get('format', '?')}",
            parent=self,
        )



# --------------------------------------------------------------------- #
# Sub-tab 4: 风格指纹 (L1 作者笔法 6维 + L2 作品调性 4维)
# --------------------------------------------------------------------- #

class LearnStyleWorker(QObject):
    """后台线程: 调用 style_learner.learn_and_apply(), 避免阻塞 UI."""

    finished = Signal(object, object)  # (LearnedStyle, AuthorFingerprint)
    error_signal = Signal(str)

    def __init__(self, project_id: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.project_id = project_id

    def run(self) -> None:
        try:
            from app.services.style_learner import learn_and_apply
            learned, fp = learn_and_apply(self.project_id)
            self.finished.emit(learned, fp)
        except Exception as e:
            self.error_signal.emit(str(e))


class StyleFingerprintWidget(QWidget):
    """双层风格指纹编辑器.

    L1 作者指纹 (6 维滑杆, 1-10): 跨书迁移, 描述笔法.
    L2 作品指纹 (4 维滑杆, 1-10): 随书而定, 描述调性.
    """

    def __init__(self) -> None:
        super().__init__()
        self.current_project: Optional[dict] = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        # 标题
        title = QLabel("🎨 风格指纹 (双层)")
        title.setObjectName("fingerprintTitle")
        outer.addWidget(title)

        desc = QLabel(
            "L1 作者笔法: 描述「你这个人怎么写」— 跨书迁移, 换题材不变.\n"
            "L2 作品调性: 描述「这本小说的气质」— 随书而定, 新书重新初始化."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {text_subtle()}; font-size: 11px;")
        outer.addWidget(desc)

        # ---- L1 作者指纹 ----
        l1_box = QGroupBox("✍️ L1 作者笔法 (6 维, 跨书迁移)")
        l1_layout = QVBoxLayout(l1_box)
        l1_layout.setContentsMargins(8, 8, 8, 8)
        l1_layout.setSpacing(4)

        self._l1_sliders: dict[str, QSlider] = {}
        self._l1_labels: dict[str, QLabel] = {}

        from app.services.style_fingerprint import AUTHOR_DIMS, AUTHOR_DIM_LABELS, AUTHOR_DIM_HINTS
        for dim in AUTHOR_DIMS:
            label = AUTHOR_DIM_LABELS.get(dim, dim)
            lo_hint, hi_hint = AUTHOR_DIM_HINTS.get(dim, ("", ""))
            row = QHBoxLayout()
            lbl_dim = QLabel(f"{label}")
            lbl_dim.setMinimumWidth(80)
            lbl_dim.setStyleSheet("font-weight: 600; font-size: 11px;")
            row.addWidget(lbl_dim)

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(1, 10)
            slider.setValue(5)
            slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            slider.setTickInterval(1)
            slider.setObjectName(f"fpSlider_{dim}")
            slider.valueChanged.connect(lambda v, d=dim: self._on_l1_changed(d, v))
            row.addWidget(slider, 1)
            self._l1_sliders[dim] = slider

            val_lbl = QLabel("5")
            val_lbl.setMinimumWidth(24)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val_lbl.setStyleSheet(f"font-weight: 700; font-size: 12px; color: {text_indigo()};")
            row.addWidget(val_lbl)
            self._l1_labels[dim] = val_lbl

            hint_lbl = QLabel(f"{lo_hint}  ←  →  {hi_hint}")
            hint_lbl.setStyleSheet(f"color: {text_subtle()}; font-size: 10px;")
            l1_layout.addLayout(row)
            hint_row = QHBoxLayout()
            hint_row.addSpacing(80)
            hint_row.addWidget(hint_lbl)
            hint_row.addSpacing(24)
            l1_layout.addLayout(hint_row)

        outer.addWidget(l1_box)

        # ---- L2 作品指纹 ----
        l2_box = QGroupBox("📖 L2 作品调性 (4 维, 随书而定)")
        l2_layout = QVBoxLayout(l2_box)
        l2_layout.setContentsMargins(8, 8, 8, 8)
        l2_layout.setSpacing(4)

        self._l2_sliders: dict[str, QSlider] = {}
        self._l2_labels: dict[str, QLabel] = {}

        from app.services.style_fingerprint import BOOK_DIMS, BOOK_DIM_LABELS, BOOK_DIM_HINTS
        for dim in BOOK_DIMS:
            label = BOOK_DIM_LABELS.get(dim, dim)
            lo_hint, hi_hint = BOOK_DIM_HINTS.get(dim, ("", ""))
            row = QHBoxLayout()
            lbl_dim = QLabel(f"{label}")
            lbl_dim.setMinimumWidth(80)
            lbl_dim.setStyleSheet("font-weight: 600; font-size: 11px;")
            row.addWidget(lbl_dim)

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(1, 10)
            slider.setValue(5)
            slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            slider.setTickInterval(1)
            slider.setObjectName(f"fpBookSlider_{dim}")
            slider.valueChanged.connect(lambda v, d=dim: self._on_l2_changed(d, v))
            row.addWidget(slider, 1)
            self._l2_sliders[dim] = slider

            val_lbl = QLabel("5")
            val_lbl.setMinimumWidth(24)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val_lbl.setStyleSheet(f"font-weight: 700; font-size: 12px; color: {text_danger()};")
            row.addWidget(val_lbl)
            self._l2_labels[dim] = val_lbl

            hint_lbl = QLabel(f"{lo_hint}  ←  →  {hi_hint}")
            hint_lbl.setStyleSheet(f"color: {text_subtle()}; font-size: 10px;")
            l2_layout.addLayout(row)
            hint_row = QHBoxLayout()
            hint_row.addSpacing(80)
            hint_row.addWidget(hint_lbl)
            hint_row.addSpacing(24)
            l2_layout.addLayout(hint_row)

        outer.addWidget(l2_box)

        # ---- 按钮 ----
        btn_row = QHBoxLayout()
        self.btn_learn = QPushButton("🧠 AI 学习")
        self.btn_learn.setToolTip("从当前项目前10章自动学习作者风格指纹并应用到 L1")
        self.btn_learn.clicked.connect(self._on_learn)
        self.btn_learn.setEnabled(False)
        btn_row.addWidget(self.btn_learn)

        self.btn_save = QPushButton("💾 保存风格指纹")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setEnabled(False)
        btn_row.addWidget(self.btn_save)

        self.btn_reset = QPushButton("↩️ 重置为默认 (全部 5)")
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_reset.setEnabled(False)
        btn_row.addWidget(self.btn_reset)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        # 状态
        self.lbl_status = QLabel("未选择项目")
        self.lbl_status.setStyleSheet(f"color: {text_subtle()}; font-size: 11px;")
        outer.addWidget(self.lbl_status)

        # 指纹预览
        self.preview_box = QGroupBox("📋 Prompt 注入预览")
        self.preview_layout = QVBoxLayout(self.preview_box)
        self.preview_layout.setContentsMargins(8, 8, 8, 8)
        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(220)
        self.preview_text.setStyleSheet("font-family: Consolas, monospace; font-size: 10px;")
        self.preview_layout.addWidget(self.preview_text)
        outer.addWidget(self.preview_box)

        outer.addStretch(1)

    def _on_l1_changed(self, dim: str, val: int) -> None:
        self._l1_labels[dim].setText(str(val))
        self._refresh_preview()

    def _on_l2_changed(self, dim: str, val: int) -> None:
        self._l2_labels[dim].setText(str(val))
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        """实时刷新 prompt 注入预览."""
        from app.services.style_fingerprint import (
            AuthorFingerprint, BookFingerprint,
            to_author_prompt_block, to_book_prompt_block,
            AUTHOR_DIMS, BOOK_DIMS,
        )
        af = AuthorFingerprint()
        for d in AUTHOR_DIMS:
            setattr(af, d, self._l1_sliders[d].value())
        bf = BookFingerprint(project_id=self.current_project.get("id", "") if self.current_project else "")
        for d in BOOK_DIMS:
            setattr(bf, d, self._l2_sliders[d].value())

        preview = to_author_prompt_block(af) + "\n\n" + to_book_prompt_block(bf)
        self.preview_text.setPlainText(preview)

    # ---- 项目切换 ----

    def set_project(self, project: Optional[dict]) -> None:
        self.current_project = project
        has_p = project is not None
        self.btn_save.setEnabled(has_p)
        self.btn_reset.setEnabled(has_p)
        self.btn_learn.setEnabled(has_p)
        if not project:
            self.lbl_status.setText("未选择项目")
            self._set_all_sliders(5)
            return
        pid = project.get("id", "")
        self.lbl_status.setText(f"项目: {project.get('name', '?')}  ({pid})")
        self._load_from_db(pid)

    def _set_all_sliders(self, val: int = 5) -> None:
        """所有滑杆设同一个值."""
        for s in self._l1_sliders.values():
            s.blockSignals(True)
            s.setValue(val)
            s.blockSignals(False)
        for s in self._l2_sliders.values():
            s.blockSignals(True)
            s.setValue(val)
            s.blockSignals(False)
        for lbl in self._l1_labels.values():
            lbl.setText(str(val))
        for lbl in self._l2_labels.values():
            lbl.setText(str(val))
        self._refresh_preview()

    def _load_from_db(self, project_id: str) -> None:
        """从 DB 加载 L1 作者指纹 + L2 作品指纹并设到滑杆."""
        from app.services.style_fingerprint import (
            get_author_fp, get_book_fp,
            AUTHOR_DIMS, BOOK_DIMS,
        )
        try:
            af = get_author_fp()
            for d in AUTHOR_DIMS:
                v = getattr(af, d, 5)
                s = self._l1_sliders[d]
                s.blockSignals(True)
                s.setValue(v)
                s.blockSignals(False)
                self._l1_labels[d].setText(str(v))
        except Exception as e:
            log.warning("[fingerprint] 加载 L1 失败: %s", e)

        try:
            bf = get_book_fp(project_id)
            for d in BOOK_DIMS:
                v = getattr(bf, d, 5)
                s = self._l2_sliders[d]
                s.blockSignals(True)
                s.setValue(v)
                s.blockSignals(False)
                self._l2_labels[d].setText(str(v))
        except Exception as e:
            log.warning("[fingerprint] 加载 L2 失败: %s", e)

        self.lbl_status.setText(
            f"已加载 — 项目: {self.current_project.get('name', '?') if self.current_project else '?'}"
        )
        self._refresh_preview()

    def _on_save(self) -> None:
        if not self.current_project:
            return
        pid = self.current_project["id"]
        from app.services.style_fingerprint import (
            upsert_author_fp, upsert_book_fp,
            AUTHOR_DIMS, BOOK_DIMS,
        )
        try:
            l1_dims = {d: self._l1_sliders[d].value() for d in AUTHOR_DIMS}
            upsert_author_fp(source="manual", **l1_dims)
            l2_dims = {d: self._l2_sliders[d].value() for d in BOOK_DIMS}
            upsert_book_fp(pid, source="manual", **l2_dims)
        except Exception as e:
            Dialogs.warning("保存失败", str(e), parent=self)
            return
        self.lbl_status.setText(
            f"✓ 已保存 — {self.current_project.get('name', '?')}"
        )
        Dialogs.info("保存", "L1 作者笔法 + L2 作品调性已保存。", parent=self)

    def _on_reset(self) -> None:
        ok, _ = Dialogs.confirm(
            "重置风格指纹",
            "将 L1 和 L2 所有维度重置为默认值 5，是否继续？",
            danger=True,
            confirm_text="重置",
            parent=self,
        )
        if not ok:
            return
        self._set_all_sliders(5)

    # ---- AI 学习 ----

    def _on_learn(self) -> None:
        """在后台线程调用 style_learner.learn_and_apply(), 避免阻塞 UI."""
        if not self.current_project:
            return
        pid = self.current_project["id"]
        self.btn_learn.setEnabled(False)
        self.btn_learn.setText("⏳ AI 学习中…")
        self.lbl_status.setText("🧠 AI 正在学习当前作品的风格指纹…")

        self._learn_thread = QThread()
        self._learn_worker = LearnStyleWorker(pid)
        self._learn_worker.moveToThread(self._learn_thread)

        self._learn_thread.started.connect(self._learn_worker.run)
        self._learn_worker.finished.connect(self._on_learn_finished)
        self._learn_worker.error_signal.connect(self._on_learn_error)

        # 清理
        self._learn_worker.finished.connect(self._learn_thread.quit)
        self._learn_worker.error_signal.connect(self._learn_thread.quit)
        self._learn_worker.finished.connect(self._learn_worker.deleteLater)
        self._learn_worker.error_signal.connect(self._learn_worker.deleteLater)
        self._learn_thread.finished.connect(self._learn_thread.deleteLater)

        self._learn_thread.start()

    def _on_learn_finished(self, learned, fp) -> None:
        """学习完成: 将结果写入滑杆并显示统计."""
        from app.services.style_fingerprint import AUTHOR_DIMS
        self._learn_thread = None
        self._learn_worker = None

        # 更新 L1 滑杆 6 维
        for d in AUTHOR_DIMS:
            v = getattr(learned, d, 5)
            s = self._l1_sliders[d]
            s.blockSignals(True)
            s.setValue(v)
            s.blockSignals(False)
            self._l1_labels[d].setText(str(v))

        self._refresh_preview()
        self.btn_learn.setEnabled(True)
        self.btn_learn.setText("🧠 AI 学习")

        pname = self.current_project.get("name", "?") if self.current_project else "?"
        self.lbl_status.setText(
            f"✓ AI 学习完成 — {pname}  "
            f"({learned.sample_chapters} 章 / {learned.sample_chars:,} 字)"
        )

        # 弹窗展示学习结果
        dim_names = {
            "sentence_rhythm": "句子节奏", "dialogue_density": "对话密度",
            "description_style": "描写风格", "emotion_expression": "情绪表达",
            "paragraph_density": "段落密度", "language_level": "语言层级",
        }
        lines = [f"📊 从 {learned.sample_chapters} 章 ({learned.sample_chars:,} 字) 中学到:"]
        for d in AUTHOR_DIMS:
            v = getattr(learned, d, 5)
            bar = "█" * v + "░" * (10 - v)
            lines.append(f"  {dim_names.get(d, d):　<6} [{bar}] {v}/10")
        lines.append("\n💡 L1 作者指纹已自动更新到滑杆，请确认后保存。")

        Dialogs.info("AI 学习完成", "\n".join(lines), parent=self)

    def _on_learn_error(self, err: str) -> None:
        self._learn_thread = None
        self._learn_worker = None
        self.btn_learn.setEnabled(True)
        self.btn_learn.setText("🧠 AI 学习")
        self.lbl_status.setText("❌ AI 学习失败，请检查日志")
        Dialogs.warning("AI 学习失败", err, parent=self)


# --------------------------------------------------------------------- #
# Sub-tab 5: 改稿信号 (v3.0 Edit Signals 4 档开关 + 试运行/立即聚类/立即进化/一键清空)
# --------------------------------------------------------------------- #

class EditSignalsWidget(QWidget):
    """v3.0 改稿信号控制台.

    4 档开关 (L1-L4):
      ☑ L1 启用改稿信号学习 (signal_enabled)            默认开
      ☑ L2 完成后右下角通知我 (signal_popup_muted)        默认开 → 取消勾选即静默
      ☐ LLM 异步泛化 (signal_llm_generalize_enabled)    opt-in, 默认关
      ☐ 注入到 writer prompt (signal_inject_to_prompt)   opt-in, 默认关
      ☑ 反例聚合 (signal_anti_aggregate_enabled)          默认开

    操作按钮 (4 个):
      [试运行聚类 (dry-run)]   [立即聚类]
      [试运行进化 (dry-run)]   [立即进化]
      [打开候选目录]
      [导出项目信号包]
      [一键清空所有改稿数据] (二次确认)

    状态显示:
      - 当前项目信号统计 (active buffer / 封存 / 候选 / 备份)
      - 上次聚类 / 进化时间
    """

    def __init__(self) -> None:
        super().__init__()
        self.current_project: Optional[dict] = None
        self._build_ui()
        self._load_settings()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        # 标题
        title = QLabel("📚 自动进化控制台 (v3.0)")
        title.setObjectName("signalsTitle")
        outer.addWidget(title)

        desc = QLabel(
            "从您的改稿动作中静默学习, 沉淀项目专属 Skill.\n"
            "4 档开关, 默认开 L1+L2, 可选 LLM 泛化和 prompt 注入."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {text_subtle()}; font-size: 11px;")
        outer.addWidget(desc)

        # ---- 4 档开关 ----
        switch_box = QGroupBox("⚙️ 4 档开关")
        switch_layout = QVBoxLayout(switch_box)
        switch_layout.setContentsMargins(8, 8, 8, 8)

        self.chk_enabled = QCheckBox("L1  启用改稿信号学习 (信号落盘 + 聚类 + 进化)")
        self.chk_enabled.setChecked(True)
        self.chk_enabled.toggled.connect(self._on_setting_toggled)
        switch_layout.addWidget(self.chk_enabled)

        self.chk_popup = QCheckBox("L2  完成后右下角通知我 (取消勾选 = 静默不弹窗)")
        self.chk_popup.setChecked(True)
        self.chk_popup.toggled.connect(self._on_setting_toggled)
        switch_layout.addWidget(self.chk_popup)

        self.chk_llm = QCheckBox("LLM 异步泛化 (1 周 1 次, 后台 thread, opt-in)")
        self.chk_llm.setChecked(False)
        self.chk_llm.toggled.connect(self._on_setting_toggled)
        switch_layout.addWidget(self.chk_llm)

        self.chk_inject = QCheckBox("注入到 writer prompt (候选 Skill → [📚 项目内参考] 段, 默认开)")
        self.chk_inject.setChecked(True)
        self.chk_inject.toggled.connect(self._on_setting_toggled)
        switch_layout.addWidget(self.chk_inject)

        self.chk_anti = QCheckBox("反例聚合 (discard 信号 → 反向候选, 默认开)")
        self.chk_anti.setChecked(True)
        self.chk_anti.toggled.connect(self._on_setting_toggled)
        switch_layout.addWidget(self.chk_anti)

        outer.addWidget(switch_box)

        # ---- 操作按钮 ----
        action_box = QGroupBox("🛠️ 操作")
        action_layout = QVBoxLayout(action_box)
        action_layout.setContentsMargins(8, 8, 8, 8)

        # 第 1 行: 聚类
        row1 = QHBoxLayout()
        self.btn_dry_curate = QPushButton("🧪 试运行聚类 (dry-run)")
        self.btn_dry_curate.clicked.connect(lambda: self._on_force_curate(dry_run=True))
        row1.addWidget(self.btn_dry_curate)
        self.btn_curate = QPushButton("⚡ 立即聚类")
        self.btn_curate.clicked.connect(lambda: self._on_force_curate(dry_run=False))
        row1.addWidget(self.btn_curate)
        row1.addStretch(1)
        action_layout.addLayout(row1)

        # 第 2 行: 进化
        row2 = QHBoxLayout()
        self.btn_dry_evolve = QPushButton("🧪 试运行进化 (dry-run)")
        self.btn_dry_evolve.clicked.connect(lambda: self._on_force_evolve(dry_run=True))
        row2.addWidget(self.btn_dry_evolve)
        self.btn_evolve = QPushButton("🧬 立即进化")
        self.btn_evolve.clicked.connect(lambda: self._on_force_evolve(dry_run=False))
        row2.addWidget(self.btn_evolve)
        row2.addStretch(1)
        action_layout.addLayout(row2)

        # 第 3 行: 文件 / 导出
        row3 = QHBoxLayout()
        self.btn_open_dir = QPushButton("📂 打开候选目录")
        self.btn_open_dir.clicked.connect(self._on_open_dir)
        row3.addWidget(self.btn_open_dir)
        self.btn_export = QPushButton("📦 导出项目信号包")
        self.btn_export.clicked.connect(self._on_export)
        row3.addWidget(self.btn_export)
        row3.addStretch(1)
        action_layout.addLayout(row3)

        # 第 4 行: 清空 (危险)
        self.btn_clear = QPushButton("🗑️ 一键清空所有改稿数据 (二次确认)")
        self.btn_clear.setStyleSheet(f"color: {text_danger()};")
        self.btn_clear.clicked.connect(self._on_clear)
        action_layout.addWidget(self.btn_clear)

        outer.addWidget(action_box)

        # ---- 状态显示 ----
        status_box = QGroupBox("📊 当前项目状态")
        status_layout = QVBoxLayout(status_box)
        status_layout.setContentsMargins(8, 8, 8, 8)

        self.lbl_status = QLabel("未选择项目")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        status_layout.addWidget(self.lbl_status)

        self.btn_refresh_status = QPushButton("🔄 刷新状态")
        self.btn_refresh_status.clicked.connect(self._refresh_status)
        status_layout.addWidget(self.btn_refresh_status)

        outer.addWidget(status_box)
        outer.addStretch(1)

    # ---- 加载 / 持久化 ----

    def _load_settings(self) -> None:
        """从 config 读 4 档开关 + 3 个子开关."""
        if not (_HAS_ES and _app_config):
            return
        try:
            self.chk_enabled.setChecked(bool(_app_config.get("signal_enabled", True)))
            self.chk_popup.setChecked(not bool(_app_config.get("signal_popup_muted", False)))
            self.chk_llm.setChecked(bool(_app_config.get("signal_llm_generalize_enabled", False)))
            self.chk_inject.setChecked(bool(_app_config.get("signal_inject_to_prompt", False)))
            self.chk_anti.setChecked(bool(_app_config.get("signal_anti_aggregate_enabled", True)))
        except Exception as e:
            log.warning("[signals] load settings 失败: %s", e)

    def _on_setting_toggled(self) -> None:
        """开关变化: 立即写 config."""
        if not (_HAS_ES and _app_config):
            return
        try:
            _app_config.set("signal_enabled", self.chk_enabled.isChecked())
            _app_config.set("signal_popup_muted", not self.chk_popup.isChecked())
            _app_config.set("signal_llm_generalize_enabled", self.chk_llm.isChecked())
            _app_config.set("signal_inject_to_prompt", self.chk_inject.isChecked())
            _app_config.set("signal_anti_aggregate_enabled", self.chk_anti.isChecked())
        except Exception as e:
            log.warning("[signals] save setting 失败: %s", e)

    # ---- 项目切换 ----

    def set_project(self, project: Optional[dict]) -> None:
        self.current_project = project
        self._refresh_status()

    # ---- 状态显示 ----

    def _refresh_status(self) -> None:
        if not _HAS_ES:
            self.lbl_status.setText("⚠️ edit_signals 模块未加载")
            return
        if not self.current_project:
            self.lbl_status.setText("未选择项目")
            return
        try:
            pid = self.current_project["id"]
            pdir = _es.get_project_dir(pid)
            from app.workflow.edit_signals.jsonl_store import SIGNALS_DIR
            base = SIGNALS_DIR / f"projects/{pid}"
            active_buf = base / "active_buffer.jsonl"
            chapters_dir = base / "chapters"
            cand_dir = base / "candidates"
            sidecar = base / "sidecar" / "candidate_usage.json"
            backup_dir = base / "backups"
            # 计数
            n_active = 0
            if active_buf.exists():
                n_active = sum(1 for _ in active_buf.read_text(encoding="utf-8", errors="ignore").splitlines() if _.strip())
            n_chapters = 0
            n_chapter_signals = 0
            if chapters_dir.exists():
                for f in chapters_dir.glob("*.jsonl"):
                    n_chapters += 1
                    n_chapter_signals += sum(1 for _ in f.read_text(encoding="utf-8", errors="ignore").splitlines() if _.strip())
            n_candidates = 0
            if cand_dir.exists():
                n_candidates = sum(1 for _ in cand_dir.glob("*.json"))
            # sidecar 状态
            n_proven = n_builtin = n_uncertain = 0
            if sidecar.exists():
                try:
                    sd = json.loads(sidecar.read_text(encoding="utf-8"))
                    for v in sd.values():
                        st = v.get("status", "active")
                        if st == "proven":
                            n_proven += 1
                        elif st == "builtin":
                            n_builtin += 1
                        elif st == "uncertain":
                            n_uncertain += 1
                except Exception:
                    pass
            n_backup = 0
            if backup_dir.exists():
                n_backup = sum(1 for _ in backup_dir.glob("*.tar.gz"))
            txt = (
                f"项目: {self.current_project.get('name', '?')} (id={pid})\n"
                f"信号目录: {base}\n"
                f"  • active buffer:  {n_active} 条\n"
                f"  • 封存章节:       {n_chapters} 个, 共 {n_chapter_signals} 条\n"
                f"  • 候选 Skill:     {n_candidates} 个 "
                f"(proven={n_proven}, builtin={n_builtin}, uncertain={n_uncertain})\n"
                f"  • 备份:           {n_backup} 个"
            )
            self.lbl_status.setText(txt)
        except Exception as e:
            self.lbl_status.setText(f"刷新失败: {e}")
            log.warning("[signals] refresh status 失败: %s", e)

    # ---- 按钮回调 ----

    def _on_force_curate(self, *, dry_run: bool) -> None:
        if not self.current_project:
            Dialogs.warning("提示", "请先选择项目", parent=self)
            return
        if not _HAS_ES:
            Dialogs.warning("提示", "edit_signals 模块未加载", parent=self)
            return
        try:
            worker = _es.get_worker(self.current_project["id"])
            stats = worker.force_curate(dry_run=dry_run)
            msg = "【试运行】" if dry_run else "【已执行】"
            msg += f"curate 完成\n"
            msg += f"  • 新增 candidate: {len(stats.get('new_candidates', []))}\n"
            msg += f"  • 扫描 signals:   {stats.get('signals_scanned', 0)}\n"
            msg += f"  • 触发章节数:     {stats.get('chapters_scanned', 0)}"
            Dialogs.info("聚类", msg, parent=self)
            self._refresh_status()
        except Exception as e:
            Dialogs.warning("聚类失败", str(e), parent=self)
            log.exception("[signals] force_curate 失败")

    def _on_force_evolve(self, *, dry_run: bool) -> None:
        if not self.current_project:
            Dialogs.warning("提示", "请先选择项目", parent=self)
            return
        if not _HAS_ES:
            Dialogs.warning("提示", "edit_signals 模块未加载", parent=self)
            return
        try:
            worker = _es.get_worker(self.current_project["id"])
            stats = worker.force_evolve(dry_run=dry_run)
            msg = "【试运行】" if dry_run else "【已执行】"
            msg += "evolve 完成\n"
            msg += f"  • merged:    {len(stats.get('merged', []))}\n"
            msg += f"  • promoted:  {len(stats.get('promoted', []))}\n"
            msg += f"  • anti:      {len(stats.get('anti_patterns', []))}\n"
            if stats.get("llm_generalize"):
                msg += f"  • LLM 泛化:  {stats['llm_generalize']}\n"
            Dialogs.info("进化", msg, parent=self)
            self._refresh_status()
        except Exception as e:
            Dialogs.warning("进化失败", str(e), parent=self)
            log.exception("[signals] force_evolve 失败")

    def _on_open_dir(self) -> None:
        """打开候选目录."""
        if not self.current_project:
            Dialogs.warning("提示", "请先选择项目", parent=self)
            return
        if not _HAS_ES:
            return
        try:
            pid = self.current_project["id"]
            pdir = _es.get_project_dir(pid) / "candidates"
            pdir.mkdir(parents=True, exist_ok=True)
            self._open_in_explorer(pdir)
        except Exception as e:
            Dialogs.warning("打开失败", str(e), parent=self)

    def _on_export(self) -> None:
        """导出项目信号包 (.tar.gz)."""
        if not self.current_project:
            Dialogs.warning("提示", "请先选择项目", parent=self)
            return
        if not _HAS_ES:
            return
        try:
            pid = self.current_project["id"]
            ts = time.strftime("%Y%m%d_%H%M%S")
            default_name = f"signals_proj{pid}_{ts}.tar.gz"
            path, _ = QFileDialog.getSaveFileName(
                self, "导出项目信号包", default_name, "Tar Gzip (*.tar.gz)"
            )
            if not path:
                return
            pdir = _es.get_project_dir(pid)
            # tar 全项目目录
            import tarfile
            with tarfile.open(path, "w:gz") as tar:
                for sub in ("active_buffer.jsonl", "chapters", "candidates", "sidecar", "backups"):
                    p = pdir / sub
                    if p.exists():
                        tar.add(p, arcname=sub)
            Dialogs.info("导出", f"已导出到:\n{path}", parent=self)
        except Exception as e:
            Dialogs.warning("导出失败", str(e), parent=self)

    def _on_clear(self) -> None:
        """L4: 一键清空 (二次确认)."""
        if not self.current_project:
            Dialogs.warning("提示", "请先选择项目", parent=self)
            return
        if not _HAS_ES:
            return
        ok, _ = Dialogs.confirm(
            "⚠️ 一键清空",
            f"将删除项目 {self.current_project.get('name', '?')} 的所有改稿数据:\n"
            f"  • active buffer\n  • 封存章节\n  • 候选 Skill\n  • sidecar\n  • 备份\n\n"
            f"此操作不可逆!",
            danger=True, confirm_text="确认清空", parent=self,
        )
        if not ok:
            return
        try:
            pid = self.current_project["id"]
            # 先停 worker
            _es.stop_worker(pid)
            # 删目录
            import shutil
            pdir = _es.get_project_dir(pid)
            if pdir.exists():
                shutil.rmtree(pdir)
            Dialogs.info("清空", f"项目 {pid} 的所有改稿数据已清空", parent=self)
            self._refresh_status()
        except Exception as e:
            Dialogs.warning("清空失败", str(e), parent=self)

    @staticmethod
    def _open_in_explorer(path: Path) -> None:
        """跨平台打开文件管理器."""
        try:
            p = str(path)
            if sys.platform.startswith("win"):
                os.startfile(p)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
        except Exception as e:
            log.warning("open explorer 失败: %s", e)


# --------------------------------------------------------------------- #
# Sub-tab 3: 模型 (全局 LLM)
# --------------------------------------------------------------------- #

class ModelSettingsWidget(QWidget):
    """全局 LLM provider 配置. 不依赖 project."""

    def __init__(self) -> None:
        super().__init__()
        self._current_name: Optional[str] = None  # 当前编辑中的 provider name
        self._dirty: bool = False
        self._build_ui()
        self._reload_list()

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        # ---- 左: provider 列表 ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Provider 列表:"))

        self.provider_list = QListWidget()
        self.provider_list.itemSelectionChanged.connect(self._on_provider_selected)
        left_layout.addWidget(self.provider_list, 1)

        self.btn_add = QPushButton("➕ 新建")
        self.btn_add.clicked.connect(self._on_add)
        self.btn_del = QPushButton("🗑️ 删除")
        self.btn_del.clicked.connect(self._on_delete)
        left_layout.addWidget(self.btn_add)
        left_layout.addWidget(self.btn_del)
        splitter.addWidget(left)

        # ---- 右: 表单 ----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.active_label = QLabel("当前 active: (未设置)")
        self.active_label.setObjectName("activeLabel")
        right_layout.addWidget(self.active_label)

        form_box = QGroupBox("Provider 配置")
        form = QFormLayout(form_box)

        self.cmb_preset = QComboBox()
        from app.core.llm import PROVIDER_PRESET_DISPLAY_NAMES
        for key in app_setting_service.list_presets():
            display = PROVIDER_PRESET_DISPLAY_NAMES.get(key, key)
            self.cmb_preset.addItem(display, userData=key)
        self.cmb_preset.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow("预设:", self.cmb_preset)

        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("唯一标识, e.g. deepseek-main")
        form.addRow("名称:", self.ed_name)

        self.ed_api_base = QLineEdit()
        self.ed_api_base.setPlaceholderText("https://api.deepseek.com/v1")
        form.addRow("API Base:", self.ed_api_base)

        self.ed_api_key = QLineEdit()
        self.ed_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_api_key.setPlaceholderText("sk-...")
        form.addRow("API Key:", self.ed_api_key)

        self.cmb_model = QComboBox()
        self.cmb_model.setEditable(True)   # 允许手动输入自定义模型
        self.cmb_model.setPlaceholderText("选择或输入模型")
        form.addRow("模型:", self.cmb_model)

        self.spn_max_tokens = NumberInput(lo=1, hi=1_000_000, default=4096)
        form.addRow("max_tokens:", self.spn_max_tokens)

        self.dspn_temperature = DoubleInput(lo=0.0, hi=2.0, default=0.7, decimals=1)
        form.addRow("temperature:", self.dspn_temperature)

        self.dspn_timeout = DoubleInput(lo=1.0, hi=600.0, default=120.0, decimals=1)
        form.addRow("timeout (s):", self.dspn_timeout)

        self.spn_priority = NumberInput(lo=0, hi=100, default=0)
        form.addRow("priority:", self.spn_priority)

        right_layout.addWidget(form_box, 1)

        # ---- AI 路由配置 (合并) ----
        router_box = QGroupBox("🤖 AI 路由配置")
        router_form = QFormLayout(router_box)
        router_form.setContentsMargins(8, 8, 8, 8)

        self.cmb_strategy = QComboBox()
        for k, label in RouterSettingsWidget.STRATEGY_LABELS.items():
            self.cmb_strategy.addItem(f"{label} ({k})", k)
        router_form.addRow("路由策略:", self.cmb_strategy)

        self.spn_l1 = NumberInput(lo=16, hi=4096, default=256, suffix=" 条")
        router_form.addRow("L1 缓存大小:", self.spn_l1)

        self.spn_parallel = NumberInput(lo=1, hi=5, default=3)
        router_form.addRow("并行 N (parallel 策略):", self.spn_parallel)

        self.chk_fallback = QCheckBox("启用 fallback 链 (单模型失败时自动降级到备)")
        self.chk_fallback.setChecked(True)
        router_form.addRow("", self.chk_fallback)

        right_layout.addWidget(router_box)

        # ---- 底部按钮 ----
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_test = QPushButton("🧪 测试连接")
        self.btn_test.clicked.connect(self._on_test)
        self.btn_active = QPushButton("⭐ 设为 active")
        self.btn_active.clicked.connect(self._on_set_active)
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_test)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_active)
        right_layout.addLayout(btn_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([260, 700])

    # ---- 加载 / 切换 ----

    def _reload_list(self) -> None:
        self.provider_list.blockSignals(True)
        self.provider_list.clear()
        providers = app_setting_service.list_providers()
        active = app_setting_service.get_active_name()
        for p in providers:
            label = f"⭐ {p['name']}" if p["name"] == active else f"   {p['name']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, p["name"])
            self.provider_list.addItem(item)
        self.provider_list.blockSignals(False)
        if active:
            self.active_label.setText(f"当前 active: {active}")
        else:
            self.active_label.setText("当前 active: (未设置)")

    def _on_provider_selected(self) -> None:
        from app.core.llm import get_provider_preset
        item = self.provider_list.currentItem()
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        try:
            p = app_setting_service.get_provider(name)
        except ServiceError as e:
            Dialogs.warning("加载", str(e), parent=self)
            return
        self._current_name = name
        self._dirty = False
        # 反查 preset: 按 api_base 匹配最接近的预设
        matched_key = _match_preset(p)
        idx = self.cmb_preset.findData(matched_key)
        if idx >= 0:
            self.cmb_preset.setCurrentIndex(idx)

        # 先阻断 model combo 信号，重建后再设值
        self.cmb_model.blockSignals(True)
        saved_model = p.get("model", "")
        # 按 preset 重建 model 下拉
        preset = get_provider_preset(matched_key)
        self.cmb_model.clear()
        found = False
        for m in preset.get("models", []):
            if m.get("enabled", True):
                self.cmb_model.addItem(m["id"], userData=m)
        # 尝试选中保存的模型
        for i in range(self.cmb_model.count()):
            if self.cmb_model.itemData(i).get("id") == saved_model:
                self.cmb_model.setCurrentIndex(i)
                found = True
                break
        if not found and saved_model:
            # 未找到则直接设文本（用户自定义模型）
            self.cmb_model.setCurrentText(saved_model)
        self.cmb_model.blockSignals(False)

        self.ed_name.setText(p.get("name", ""))
        self.ed_api_base.setText(p.get("api_base", ""))
        self.ed_api_key.setText(p.get("api_key", ""))
        self.spn_max_tokens.setValue(int(p.get("max_tokens", 4096)))
        self.dspn_temperature.setValue(float(p.get("temperature", 0.7)))
        self.dspn_timeout.setValue(float(p.get("timeout", 120.0)))
        self.spn_priority.setValue(int(p.get("priority", 0)))

    def _on_preset_changed(self, index: int) -> None:
        """选预设时，自动填 api_base + 重建模型下拉 + 填默认温度。"""
        from app.core.llm import get_provider_preset
        key = self.cmb_preset.itemData(index) or "custom"
        preset = get_provider_preset(key)
        # 填 api_base
        self.ed_api_base.setText(preset.get("api_base", ""))
        # 重建模型下拉
        self.cmb_model.blockSignals(True)
        self.cmb_model.clear()
        for m in preset.get("models", []):
            # 只显示 enabled 的，userData 存完整 dict
            if m.get("enabled", True):
                self.cmb_model.addItem(m["id"], userData=m)
        # 选第一个可用模型
        if self.cmb_model.count() > 0:
            self.cmb_model.setCurrentIndex(0)
        self.cmb_model.blockSignals(False)
        # 填默认温度
        self.dspn_temperature.setValue(preset.get("default_temperature", 0.7))

    # ---- 按钮 ----

    def _on_add(self) -> None:
        # 清空表单, 准备新建
        self._current_name = None
        idx = self.cmb_preset.findData("custom")
        if idx >= 0:
            self.cmb_preset.setCurrentIndex(idx)
        self.ed_name.clear()
        self.ed_api_base.clear()
        self.ed_api_key.clear()
        self.cmb_model.clear()
        self.spn_max_tokens.setValue(4096)
        self.dspn_temperature.setValue(0.7)
        self.dspn_timeout.setValue(120.0)
        self.spn_priority.setValue(0)
        self.ed_name.setFocus()
        self.provider_list.clearSelection()

    def _load_router_settings(self) -> None:
        """加载 AI 路由配置到合并的表单."""
        try:
            from app.services import app_setting_service
            strategy = app_setting_service.get("ai.strategy", "single")
            cache_l1 = int(app_setting_service.get("ai.cache_l1_size", 256))
            parallel_n = int(app_setting_service.get("ai.parallel_n", 3))
            use_fallback = bool(app_setting_service.get("engine.use_fallback", True))

            idx = self.cmb_strategy.findData(strategy)
            if idx >= 0:
                self.cmb_strategy.setCurrentIndex(idx)
            self.spn_l1.setValue(cache_l1)
            self.spn_parallel.setValue(parallel_n)
            self.chk_fallback.setChecked(use_fallback)
        except Exception:
            pass

    def _save_router_settings(self) -> None:
        """保存 AI 路由配置."""
        try:
            from app.services import app_setting_service
            strategy = self.cmb_strategy.currentData() or "single"
            app_setting_service.set("ai.strategy", strategy)
            app_setting_service.set("ai.cache_l1_size", self.spn_l1.value())
            app_setting_service.set("ai.parallel_n", self.spn_parallel.value())
            app_setting_service.set("engine.use_fallback", self.chk_fallback.isChecked())
        except Exception as e:
            log.warning(f"保存路由配置失败: {e}")

    def _on_save(self) -> None:
        # 收集表单
        preset_key = self.cmb_preset.currentData() or "custom"
        from app.core.llm import get_provider_preset
        preset = get_provider_preset(preset_key)
        patch = {
            "provider_type": _resolve_provider_type(
                preset.get("api_base", ""),
                self.ed_api_base.text().strip(),
            ),
            "api_base": self.ed_api_base.text().strip(),
            "api_key": self.ed_api_key.text(),
            "model": self.cmb_model.currentText().strip(),
            "max_tokens": self.spn_max_tokens.value(),
            "temperature": self.dspn_temperature.value(),
            "timeout": self.dspn_timeout.value(),
            "priority": self.spn_priority.value(),
        }
        name_in_form = self.ed_name.text().strip()
        if not name_in_form:
            Dialogs.warning("保存失败", "名称不能为空", parent=self)
            return
        try:
            if self._current_name is None:
                # 新建
                payload = {"name": name_in_form, **patch}
                created = app_setting_service.add_provider(payload)
                self._current_name = created["name"]
            else:
                app_setting_service.update_provider(self._current_name, patch)
        except ServiceError as e:
            Dialogs.warning("保存失败", str(e), parent=self)
            return
        # 自动激活：如果保存后只有 1 个 provider 且当前没有 active，自动设为 active
        try:
            providers = app_setting_service.list_providers()
            active = app_setting_service.get_active_name()
            if len(providers) == 1 and not active:
                app_setting_service.set_active(providers[0]["name"])
                self._reload_list()
                Dialogs.info("保存", f"已保存，并自动设为 active（唯一配置）", parent=self)
            else:
                self._reload_list()
                Dialogs.info("保存", "已保存", parent=self)
        except Exception:
            self._reload_list()
            Dialogs.info("保存", "已保存", parent=self)
        # 保存路由配置
        self._save_router_settings()

    def _on_delete(self) -> None:
        if self._current_name is None:
            return
        ok, _ = Dialogs.confirm(
            "确认删除",
            f"删除 provider '{self._current_name}'?",
            danger=True,
            confirm_text="删除",
            parent=self,
        )
        if not ok:
            return
        try:
            app_setting_service.delete_provider(self._current_name)
        except ServiceError as e:
            Dialogs.warning("删除失败", str(e), parent=self)
            return
        self._current_name = None
        self._reload_list()
        self._on_add()  # 清空表单

    def _on_set_active(self) -> None:
        if self._current_name is None:
            Dialogs.info("提示", "请先选择一个 provider 或保存当前表单", parent=self)
            return
        try:
            app_setting_service.set_active(self._current_name)
        except ServiceError as e:
            Dialogs.warning("设置失败", str(e), parent=self)
            return
        self._reload_list()
        Dialogs.info("已切换", f"active = {self._current_name}", parent=self)

    def _on_test(self) -> None:
        """用 LLMClient 发 'hi', 验证连通性."""
        # 先保存当前表单内容 (避免拿老数据测试)
        from app.core.llm import LLMClient, ProviderConfig, ProviderType, ChatMessage, get_provider_preset

        preset_key = self.cmb_preset.currentData() or "custom"
        preset = get_provider_preset(preset_key)
        name_in_form = self.ed_name.text().strip()
        if not name_in_form:
            Dialogs.warning("测试", "请先填名称再测试", parent=self)
            return
        try:
            cfg = ProviderConfig(
                name=name_in_form,
                provider_type=ProviderType(preset.get("provider_type", "openai_compat")),
                api_base=self.ed_api_base.text().strip(),
                api_key=self.ed_api_key.text(),
                model=self.cmb_model.currentText().strip(),
                max_tokens=16,
                temperature=0.0,
                timeout=float(self.dspn_timeout.value()),
                priority=0,
            )
        except ValueError as e:
            Dialogs.warning("配置错误", str(e), parent=self)
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
            Dialogs.warning("测试失败", str(e), parent=self)
            return
        finally:
            client.close()
        Dialogs.info(
            "测试成功",
            f"provider={resp.provider}\nmodel={resp.model}\n"
            f"tokens_in={resp.tokens_in} tokens_out={resp.tokens_out}\n"
            f"reply={resp.content[:80]!r}",
            parent=self,
        )


# --------------------------------------------------------------------- #
# Sub-tab 6: AI 路由 (M11-C: 策略 + 缓存阈值 + 并行数)
# --------------------------------------------------------------------- #

class RouterSettingsWidget(QWidget):
    """M11-C: AI 路由阈值面板.

    配置:
      - 路由策略 (ai.strategy): single / parallel / cache_first
      - 缓存 L1 大小 (ai.cache_l1_size): 16 - 4096
      - 缓存目录 (ai.cache_dir): 文件系统路径
      - 并行数 (ai.parallel_n): 1 - 5
      - 启用 fallback (engine.use_fallback): 单选框

    变更后写 config (立即生效, 重启持久化).
    """

    DEFAULTS = {
        "ai.strategy": "single",
        "ai.cache_l1_size": 256,
        "ai.cache_dir": "",
        "ai.parallel_n": 3,
        "engine.use_fallback": True,
    }
    STRATEGY_LABELS = {
        "single": "单模型 (含降级)",
        "parallel": "并行 N 模型",
        "cache_first": "缓存优先",
    }

    def __init__(self) -> None:
        super().__init__()
        self._dirty: bool = False
        self._build_ui()
        self._load_settings()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        # 标题
        title = QLabel(" AI 路由配置")
        title.setObjectName("routerSettingsTitle")
        outer.addWidget(title)

        desc = QLabel(
            "调整 LLM 路由策略和缓存阈值。变更立即生效, 重启持久化。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {text_subtle()}; font-size: 11px;")
        outer.addWidget(desc)

        # ---- 表单 ----
        form_box = QGroupBox("⚙️ 路由参数")
        form = QFormLayout(form_box)
        form.setContentsMargins(8, 8, 8, 8)

        # 策略
        self.cmb_strategy = QComboBox()
        for k, label in self.STRATEGY_LABELS.items():
            self.cmb_strategy.addItem(f"{label} ({k})", k)
        self.cmb_strategy.currentIndexChanged.connect(self._on_changed)
        form.addRow("路由策略:", self.cmb_strategy)

        # 缓存 L1
        self.spn_l1 = NumberInput(lo=16, hi=4096, default=256, suffix=" 条")
        self.spn_l1.valueChanged.connect(self._on_changed)
        form.addRow("L1 缓存大小:", self.spn_l1)

        # 缓存目录
        cache_dir_row = QHBoxLayout()
        self.ed_cache_dir = QLineEdit()
        self.ed_cache_dir.setPlaceholderText("默认 %APPDATA%/NovelWriterPure/data/cache/llm")
        self.ed_cache_dir.textChanged.connect(self._on_changed)
        cache_dir_row.addWidget(self.ed_cache_dir, 1)
        self.btn_browse = QPushButton("📂 浏览…")
        self.btn_browse.clicked.connect(self._on_browse_cache_dir)
        cache_dir_row.addWidget(self.btn_browse)
        form.addRow("缓存目录:", cache_dir_row)

        # 并行 N
        self.spn_parallel_n = NumberInput(lo=1, hi=5, default=3)
        self.spn_parallel_n.valueChanged.connect(self._on_changed)
        form.addRow("并行 N (parallel 策略):", self.spn_parallel_n)

        # fallback 开关
        self.chk_fallback = QCheckBox("启用 fallback 链 (单模型失败时自动降级到备)")
        self.chk_fallback.setChecked(True)
        self.chk_fallback.toggled.connect(self._on_changed)
        form.addRow("", self.chk_fallback)

        outer.addWidget(form_box)

        # ---- 状态 + 按钮 ----
        status_box = QGroupBox("📊 状态")
        status_layout = QVBoxLayout(status_box)
        status_layout.setContentsMargins(8, 8, 8, 8)
        self.lbl_status = QLabel("(未应用)")
        self.lbl_status.setObjectName("routerSettingsStatus")
        self.lbl_status.setStyleSheet(f"font-size: 11px; color: {text_subtle()};")
        status_layout.addWidget(self.lbl_status)
        outer.addWidget(status_box)

        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_save.setEnabled(False)
        self.btn_save.setDefault(True)
        btn_row.addWidget(self.btn_save)
        self.btn_reset = QPushButton("↩️ 恢复默认")
        self.btn_reset.clicked.connect(self._on_reset)
        btn_row.addWidget(self.btn_reset)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        outer.addStretch(1)

    # ---- 加载 / 保存 ----

    def _load_settings(self) -> None:
        from app.core import config as _cfg
        try:
            self.cmb_strategy.blockSignals(True)
            self.spn_l1.blockSignals(True)
            self.ed_cache_dir.blockSignals(True)
            self.spn_parallel_n.blockSignals(True)
            self.chk_fallback.blockSignals(True)

            strategy = str(_cfg.get("ai.strategy", self.DEFAULTS["ai.strategy"]))
            idx = self.cmb_strategy.findData(strategy)
            if idx >= 0:
                self.cmb_strategy.setCurrentIndex(idx)
            self.spn_l1.setValue(int(_cfg.get("ai.cache_l1_size", self.DEFAULTS["ai.cache_l1_size"])))
            self.ed_cache_dir.setText(str(_cfg.get("ai.cache_dir", self.DEFAULTS["ai.cache_dir"])))
            self.spn_parallel_n.setValue(int(_cfg.get("ai.parallel_n", self.DEFAULTS["ai.parallel_n"])))
            self.chk_fallback.setChecked(bool(_cfg.get("engine.use_fallback", self.DEFAULTS["engine.use_fallback"])))

            self.cmb_strategy.blockSignals(False)
            self.spn_l1.blockSignals(False)
            self.ed_cache_dir.blockSignals(False)
            self.spn_parallel_n.blockSignals(False)
            self.chk_fallback.blockSignals(False)
            self._dirty = False
            self._update_status("已加载")
        except Exception as e:
            log.warning("[router settings] load failed: %s", e)
            self._update_status(f"加载失败: {e}", error=True)

    def _on_changed(self, *_args) -> None:
        if not self._dirty:
            self._dirty = True
            self.btn_save.setEnabled(True)
            self._update_status("● 未保存的修改", dirty=True)

    def _update_status(self, text: str, *, dirty: bool = False, error: bool = False) -> None:
        if error:
            self.lbl_status.setStyleSheet(f"color: {text_danger()}; font-size: 11px;")
        elif dirty:
            self.lbl_status.setStyleSheet(f"color: {text_warn()}; font-size: 11px;")
        else:
            self.lbl_status.setStyleSheet(f"color: {text_warn_ok()}; font-size: 11px;")
        self.lbl_status.setText(text)

    def _on_browse_cache_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择 LLM 缓存目录")
        if path:
            self.ed_cache_dir.setText(path)

    def _on_save(self) -> None:
        from app.core import config as _cfg
        try:
            _cfg.set("ai.strategy", self.cmb_strategy.currentData(), persist=True)
            _cfg.set("ai.cache_l1_size", int(self.spn_l1.value()), persist=True)
            _cfg.set("ai.cache_dir", self.ed_cache_dir.text().strip(), persist=True)
            _cfg.set("ai.parallel_n", int(self.spn_parallel_n.value()), persist=True)
            _cfg.set("engine.use_fallback", bool(self.chk_fallback.isChecked()), persist=True)
            self._dirty = False
            self.btn_save.setEnabled(False)
            self._update_status("✓ 已保存 (重启后 cache 目录生效)")
            Dialogs.info("保存", "AI 路由配置已保存", parent=self)
        except Exception as e:
            self._update_status(f"保存失败: {e}", error=True)
            Dialogs.warning("保存失败", str(e), parent=self)

    def _on_reset(self) -> None:
        ok, _ = Dialogs.confirm(
            "恢复默认",
            "将 AI 路由配置重置为默认值, 是否继续?",
            danger=True, confirm_text="恢复默认", parent=self,
        )
        if not ok:
            return
        self.cmb_strategy.blockSignals(True)
        self.spn_l1.blockSignals(True)
        self.ed_cache_dir.blockSignals(True)
        self.spn_parallel_n.blockSignals(True)
        self.chk_fallback.blockSignals(True)
        idx = self.cmb_strategy.findData(self.DEFAULTS["ai.strategy"])
        if idx >= 0:
            self.cmb_strategy.setCurrentIndex(idx)
        self.spn_l1.setValue(int(self.DEFAULTS["ai.cache_l1_size"]))
        self.ed_cache_dir.setText(str(self.DEFAULTS["ai.cache_dir"]))
        self.spn_parallel_n.setValue(int(self.DEFAULTS["ai.parallel_n"]))
        self.chk_fallback.setChecked(bool(self.DEFAULTS["engine.use_fallback"]))
        self.cmb_strategy.blockSignals(False)
        self.spn_l1.blockSignals(False)
        self.ed_cache_dir.blockSignals(False)
        self.spn_parallel_n.blockSignals(False)
        self.chk_fallback.blockSignals(False)
        self._dirty = True
        self.btn_save.setEnabled(True)
        self._update_status("● 已恢复默认, 点击保存生效", dirty=True)


# --------------------------------------------------------------------- #
# Sub-tab 7: 关于 (M11-C: 版本 + 更新日志 + 链接)
# --------------------------------------------------------------------- #

class AboutWidget(QWidget):
    """M11-C: 关于面板.

    显示:
      - 应用名 + 版本号 + 构建日期 + Git commit
      - 应用描述
      - 更新日志 (CHANGELOG, 可滚动)
      - 链接 (项目主页 / 检查更新 / License)
    """

    def __init__(self) -> None:
        super().__init__()
        self._build_ui()

    def _build_ui(self) -> None:
        from app.core.version import get_full_info

        info = get_full_info()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        # 应用名 + 版本
        self.lbl_title = QLabel(f"{info['display_name']} v{info['version']}")
        self.lbl_title.setObjectName("aboutTitle")
        self.lbl_title.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {text_primary()};")
        outer.addWidget(self.lbl_title)

        desc = QLabel(info["description"])
        desc.setStyleSheet(f"color: {text_subtle()}; font-size: 12px;")
        outer.addWidget(desc)

        # 构建信息
        info_box = QGroupBox("📦 构建信息")
        info_layout = QFormLayout(info_box)
        info_layout.setContentsMargins(8, 8, 8, 8)
        info_layout.addRow("版本:", QLabel(info["version"]))
        info_layout.addRow("构建日期:", QLabel(info["build_date"]))
        info_layout.addRow("Git:", QLabel(info["git_commit"]))
        info_layout.addRow("应用名:", QLabel(info["name"]))
        outer.addWidget(info_box)

        # 更新日志
        changelog_box = QGroupBox("📜 更新日志")
        changelog_layout = QVBoxLayout(changelog_box)
        changelog_layout.setContentsMargins(8, 8, 8, 8)
        self.changelog_view = QPlainTextEdit()
        self.changelog_view.setReadOnly(True)
        self.changelog_view.setPlainText(info["changelog"])
        self.changelog_view.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        changelog_layout.addWidget(self.changelog_view, 1)
        outer.addWidget(changelog_box, 1)

        # 链接
        link_row = QHBoxLayout()
        self.btn_homepage = QPushButton("🌐 项目主页")
        self.btn_homepage.clicked.connect(self._on_homepage)
        link_row.addWidget(self.btn_homepage)
        self.btn_check_update = QPushButton("🔄 检查更新")
        self.btn_check_update.clicked.connect(self._on_check_update)
        link_row.addWidget(self.btn_check_update)
        self.btn_license = QPushButton("📜 许可证")
        self.btn_license.clicked.connect(self._on_license)
        link_row.addWidget(self.btn_license)
        link_row.addStretch(1)
        outer.addLayout(link_row)

    def _on_homepage(self) -> None:
        Dialogs.info(
            "项目主页",
            "https://github.com/novel-writer-pure\n(M11-C 占位, 实际链接待部署)",
            parent=self,
        )

    def _on_check_update(self) -> None:
        """M11-C 占位: 实际检查更新走 HTTP (M12 范围)."""
        from app.core.version import VERSION
        Dialogs.info(
            "检查更新",
            f"当前版本: v{VERSION}\n最新版本检查功能将在 M12 实现。",
            parent=self,
        )

    def _on_license(self) -> None:
        """显示软件许可信息."""
        from app.services.license import get_current_tier, reset_cache as _lic_reset
        try:
            _lic_reset()
            tier = get_current_tier()
        except Exception:
            tier = "STANDARD"
        tier_text = {
            "FREE": "🆓 Free (免费版)",
            "STANDARD": "⭐ Standard (标准版)",
            "PRO": "💎 PRO (专业版)",
        }.get(str(tier), str(tier))
        Dialogs.info(
            "许可证",
            f"当前等级: {tier_text}\n\n"
            f"PRO 专属功能 (M10 起):\n"
            f"  • AI Cache (跨章节缓存)\n"
            f"  • AI Router.parallel (N 模型并行)\n"
            f"  • AI Router.fallback (降级链)\n"
            f"  • 一键出版 (M11-D)\n\n"
            f"升级 PRO: 设置 → 🔐 License → 输入激活码",
            parent=self,
        )


# --------------------------------------------------------------------- #
# 顶层 SettingsTab (左导航 + 右内容 容器)
# --------------------------------------------------------------------- #

# 4.0 修复: _NAV_QSS 之前硬编码 #cbd5e1/#ffffff 等暗色字, 切到亮色下左导航文字看不清.
# 现在 nav_list 走 objectName="settingsNav", 颜色全部由 theme.py 的
# QListWidget#settingsNav (暗/亮双套) 管, 这里只 setStyleSheet("") 清掉旧硬编码,
# 留 setStyleSheet 调用是 Qt 推荐的"显式清空"模式, 确保无残留 inline 样式.


class SettingsTab(QWidget):
    """统一 settings 容器 — 左侧导航 + 右侧内容.

    scope:
      - "novel" (默认, 给 小说管理 > 小说设定 用):  3 项 = 📚 小说设定 / 🎭 潜文本卡 / 📚 改稿信号
      - "app"   (给 左栏 > 设置 用):                  8 项 = 🎨 外观 / 🤖 模型 / 📁 存储
                                                       / 💾 备份 / 📋 日志 / 🔑 授权
                                                       / 🤖 AI 路由 / ℹ️ 关于

    4.0 修复 (UI 二次调整): 原 QTabWidget 把 8 个 sub-tab 平铺在顶部, 像浏览器多 tab 一样挤成一排.
    改成左侧 QListWidget 垂直列表 + 右侧 QStackedWidget, 标准"左导航 + 右内容"布局,
    与本软件主页 (📚 小说管理 / ⚙️ 设置 / …) 的导航风格一致.
    """

    SCOPE_NOVEL = "novel"  # 小说管理 > 小说设定
    SCOPE_APP = "app"      # 左栏 > 设置

    def __init__(self, scope: str = SCOPE_NOVEL) -> None:
        super().__init__()
        self.scope = scope
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- 左侧: 导航列表 ----
        self.nav_list = QListWidget()
        self.nav_list.setObjectName("settingsNav")
        # 4.0 修复: 清空 inline 样式, 让 QListWidget#settingsNav 走 theme.py 的暗/亮双套 QSS
        self.nav_list.setStyleSheet("")
        self.nav_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.nav_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_list.setMinimumWidth(168)
        self.nav_list.setMaximumWidth(220)
        # 左边一条竖线作为视觉分隔
        self.nav_list.setFrameShape(QFrame.Shape.NoFrame)

        # ---- 右侧: 页面栈 ----
        self.stack = QStackedWidget()
        self.stack.setObjectName("settingsStack")
        # 内容区在视觉上跟 nav 拉开距离
        stack_wrap = QWidget()
        stack_wrap.setObjectName("settingsStackWrap")
        stack_layout = QVBoxLayout(stack_wrap)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        stack_layout.addWidget(self.stack)

        # 填内容
        if self.scope == self.SCOPE_APP:
            entries: list[tuple[str, str, QWidget]] = [
                ("🎨 外观",   "appearance_widget", AppearanceTab()),
                ("🤖 模型配置",   "model_widget",      ModelSettingsWidget()),
                ("📁 存储备份",   "storage_backup_widget",    StorageBackupTab()),
                ("📋 日志",   "log_widget",        LogTab()),
                ("🔑 授权",   "license_widget",    LicenseWidget()),
                ("ℹ️ 关于",   "about_widget",      AboutWidget()),
            ]
        else:
            entries = [
                ("📚 小说设定", "project_widget", ProjectSettingsWidget()),
                ("🎨 风格指纹", "fingerprint_widget", StyleFingerprintWidget()),
                ("📚 自动进化", "signals_widget", EditSignalsWidget()),
            ]

        for title, attr, widget in entries:
            # 保留旧属性名 (project_widget / subtext_widget / signals_widget / model_widget
            #               / storage_widget / backup_widget / license_widget / router_widget
            #               / about_widget / appearance_widget / log_widget) — 避免破坏外部引用
            setattr(self, attr, widget)
            item = QListWidgetItem(title)
            item.setToolTip(title)
            self.nav_list.addItem(item)
            self.stack.addWidget(widget)

        # 默认选中第一项
        self.nav_list.setCurrentRow(0)

        # 同步: 列表选 → 栈切
        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)

        # 布局
        outer.addWidget(self.nav_list)
        outer.addWidget(stack_wrap, 1)

        # 左侧 nav 视觉分隔线 (用 QFrame 当分割条)
        sep = QFrame()
        sep.setObjectName("settingsNavSeparator")
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setStyleSheet("color: rgba(127,127,127,0.25);")
        sep.setFixedWidth(1)
        outer.insertWidget(1, sep)

    # ---- 项目切换 (只 novel scope 关心) ----

    def set_project(self, project: Optional[dict]) -> None:
        if self.scope == self.SCOPE_NOVEL:
            self.project_widget.set_project(project)
            self.fingerprint_widget.set_project(project)
            self.signals_widget.set_project(project)


# ===================================================================== #
# 系统级 SettingsTab 子页 (设置 左栏的 4 个 tab)
#   - AppearanceTab  (外观: 主题 / 字号 / 窗口最小宽度)
#   - StorageTab     (存储: 项目/数据目录 + 迁移)
#   - BackupTab      (备份: 自动备份开关 + 间隔 + 保留份数)
#   - LogTab         (日志: 级别 + 单文件最大 MB)
#   以上 4 个是 v3.4 从 pages.py 抽出来的, 跟 小说设定 的 4 个 sub-tab 解耦.
# ===================================================================== #

class AppearanceTab(QWidget):
    """🎨 外观: 主题 / 正文字体大小 / 窗口最小宽度."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)
        v.addWidget(_section_header("🎨 外观设置"))
        # 主题
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("主题:"))
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(["暗色 (默认)", "亮色"])
        try:
            from app.ui.theme import get_theme
            if get_theme().current() == "light":
                self.cmb_theme.setCurrentIndex(1)
        except Exception:
            pass
        self.cmb_theme.currentIndexChanged.connect(self._on_theme_change)
        h1.addWidget(self.cmb_theme)
        h1.addStretch(1)
        v.addLayout(h1)
        # 字体
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("正文字体大小:"))
        self.spn_size = _spin(11, 20, 13)
        h2.addWidget(self.spn_size)
        h2.addStretch(1)
        v.addLayout(h2)
        # 屏宽
        h3 = QHBoxLayout()
        h3.addWidget(QLabel("窗口最小宽度:"))
        self.spn_w = _spin(960, 2400, 1440)
        h3.addWidget(self.spn_w)
        h3.addStretch(1)
        v.addLayout(h3)
        v.addStretch(1)

    def _on_theme_change(self, idx: int) -> None:
        try:
            from app.ui.theme import get_theme
            name = "light" if idx == 1 else "dark"
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            get_theme().apply(app, name)
            # 持久化到 app_settings, 下次启动恢复用户偏好
            try:
                from app.services import app_setting_service
                app_setting_service.set("ui.theme", name)
            except Exception:
                pass
        except Exception as e:
            log.warning(f"[AppearanceTab] theme switch failed: {e}")


class StorageTab(QWidget):
    """📁 存储: 项目目录 / 数据目录 (含迁移工具)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        from app.app_paths import (
            STORY_DIR_DEFAULT, DATA_DIR_DEFAULT,
            get_story_dir, get_data_dir,
        )
        from app.services.app_setting_service import get as kv_get

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(12)
        v.addWidget(_section_header("📁 存储位置"))

        # 当前生效路径
        cur_story = str(get_story_dir())
        cur_data = str(get_data_dir())
        saved_story = kv_get("storage.story_dir") or ""
        saved_data = kv_get("storage.data_dir") or ""

        info = QLabel(
            f"💡 默认项目目录: <code>{STORY_DIR_DEFAULT}</code><br>"
            f"💡 默认数据目录: <code>{DATA_DIR_DEFAULT}</code><br>"
            f"<span style='color:#888'>设置保存在 <code>app_settings.json</code> 的 <code>kv</code> 字段,"
            f"重启后生效。</span>"
        )
        info.setWordWrap(True)
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(info)

        # ----- 项目目录 -----
        v.addWidget(_sub_header("📚 项目目录 (存放各小说的 JSON 文件)"))
        row1 = QHBoxLayout()
        self.lbl_cur_story = QLabel(cur_story)
        self.lbl_cur_story.setObjectName("storageCurPath")
        self.lbl_cur_story.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row1.addWidget(QLabel("当前:"))
        row1.addWidget(self.lbl_cur_story, 1)
        btn_open_story = QPushButton("📂 打开")
        btn_open_story.setObjectName("btnSecondary")
        btn_open_story.clicked.connect(lambda: self._open_in_explorer(cur_story))
        row1.addWidget(btn_open_story)
        v.addLayout(row1)
        row1b = QHBoxLayout()
        self.ed_story = QLineEdit(saved_story)
        self.ed_story.setPlaceholderText(f"留空 = 默认 ({STORY_DIR_DEFAULT})")
        row1b.addWidget(QLabel("自定义:"))
        row1b.addWidget(self.ed_story, 1)
        btn_browse_story = QPushButton("浏览…")
        btn_browse_story.clicked.connect(self._browse_story_dir)
        row1b.addWidget(btn_browse_story)
        btn_apply_story = QPushButton("✅ 应用 + 迁移")
        btn_apply_story.setObjectName("btnPrimary")
        btn_apply_story.clicked.connect(self._apply_story_dir)
        row1b.addWidget(btn_apply_story)
        btn_reset_story = QPushButton("重置")
        btn_reset_story.clicked.connect(lambda: self.ed_story.setText(""))
        row1b.addWidget(btn_reset_story)
        v.addLayout(row1b)

        v.addSpacing(8)

        # ----- 数据目录 -----
        v.addWidget(_sub_header("💾 数据目录 (sqlite / 日志 / 备份 / 改稿信号)"))
        row2 = QHBoxLayout()
        self.lbl_cur_data = QLabel(cur_data)
        self.lbl_cur_data.setObjectName("storageCurPath")
        self.lbl_cur_data.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row2.addWidget(QLabel("当前:"))
        row2.addWidget(self.lbl_cur_data, 1)
        btn_open_data = QPushButton("📂 打开")
        btn_open_data.setObjectName("btnSecondary")
        btn_open_data.clicked.connect(lambda: self._open_in_explorer(cur_data))
        row2.addWidget(btn_open_data)
        v.addLayout(row2)
        row2b = QHBoxLayout()
        self.ed_data = QLineEdit(saved_data)
        self.ed_data.setPlaceholderText(f"留空 = 默认 ({DATA_DIR_DEFAULT})")
        row2b.addWidget(QLabel("自定义:"))
        row2b.addWidget(self.ed_data, 1)
        btn_browse_data = QPushButton("浏览…")
        btn_browse_data.clicked.connect(self._browse_data_dir)
        row2b.addWidget(btn_browse_data)
        btn_apply_data = QPushButton("✅ 应用 (需重启)")
        btn_apply_data.setObjectName("btnPrimary")
        btn_apply_data.clicked.connect(self._apply_data_dir)
        row2b.addWidget(btn_apply_data)
        btn_reset_data = QPushButton("重置")
        btn_reset_data.clicked.connect(lambda: self.ed_data.setText(""))
        row2b.addWidget(btn_reset_data)
        v.addLayout(row2b)

        warn = QLabel(
            "⚠️ 改数据目录后, 必须<strong>重启软件</strong>才能生效。"
            "sqlite 会在新目录重建, 旧目录数据会保留 (不会自动清理)。"
        )
        warn.setObjectName("storageWarn")
        warn.setWordWrap(True)
        v.addWidget(warn)

        v.addStretch(1)

    def _open_in_explorer(self, path: str) -> None:
        try:
            p = Path(path)
            p.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        except Exception as e:
            from app.ui.widgets import Dialogs
            Dialogs.warning("打开失败", str(e), parent=self)

    def _browse_story_dir(self) -> None:
        from app.app_paths import get_story_dir
        d = QFileDialog.getExistingDirectory(self, "选择项目目录", str(get_story_dir()))
        if d:
            self.ed_story.setText(d)

    def _browse_data_dir(self) -> None:
        from app.app_paths import get_data_dir
        d = QFileDialog.getExistingDirectory(self, "选择数据目录", str(get_data_dir()))
        if d:
            self.ed_data.setText(d)

    def _apply_story_dir(self) -> None:
        from app.services import app_setting_service
        from app.app_paths import (
            set_story_dir_override, get_story_dir,
            migrate_story_dir, STORY_DIR_DEFAULT,
        )
        from app.ui.widgets import Dialogs

        new_path = self.ed_story.text().strip()
        try:
            if new_path:
                p = Path(new_path).expanduser()
                p.mkdir(parents=True, exist_ok=True)
                test = p / ".nw_write_test"
                test.write_text("ok", encoding="utf-8")
                test.unlink()
            set_story_dir_override(new_path or None)
            app_setting_service.set("storage.story_dir", new_path)
        except Exception as e:
            Dialogs.error("保存失败", f"无法写入该目录: {e}", parent=self)
            return

        if new_path and str(STORY_DIR_DEFAULT) != str(get_story_dir()):
            ok, _ = Dialogs.confirm(
                "迁移数据",
                f"是否把旧项目目录里的数据迁移到新位置?\n\n"
                f"源: {STORY_DIR_DEFAULT}\n"
                f"目标: {new_path}\n\n"
                f"(跳过则只改设置, 旧项目文件保留在原位, 新项目写入新位置)",
                confirm_text="迁移",
                parent=self,
            )
            if ok:
                try:
                    r = migrate_story_dir(new_path)
                    msg = f"复制 {r['copied']} 项, 跳过 {r['skipped']} 项"
                    if r["errors"]:
                        msg += f"\n\n错误:\n" + "\n".join(r["errors"][:5])
                    Dialogs.info("迁移完成", msg, parent=self)
                except Exception as e:
                    Dialogs.error("迁移失败", str(e), parent=self)
                    return

        Dialogs.info("已保存", f"项目目录已设为:\n{get_story_dir()}\n\n重启后生效。", parent=self)
        self.lbl_cur_story.setText(str(get_story_dir()))

    def _apply_data_dir(self) -> None:
        from app.services import app_setting_service
        from app.app_paths import set_data_dir_override, get_data_dir
        from app.ui.widgets import Dialogs

        new_path = self.ed_data.text().strip()
        try:
            if new_path:
                p = Path(new_path).expanduser()
                p.mkdir(parents=True, exist_ok=True)
                test = p / ".nw_write_test"
                test.write_text("ok", encoding="utf-8")
                test.unlink()
            set_data_dir_override(new_path or None)
            app_setting_service.set("storage.data_dir", new_path)
        except Exception as e:
            Dialogs.error("保存失败", f"无法写入该目录: {e}", parent=self)
            return

        Dialogs.info(
            "已保存",
            f"数据目录已设为:\n{get_data_dir()}\n\n"
            f"⚠️ 必须<strong>重启软件</strong>才能生效。",
            parent=self,
        )
        self.lbl_cur_data.setText(str(get_data_dir()))


class BackupTab(QWidget):
    """💾 备份: 自动备份开关 + 间隔 (小时) + 保留份数.

    改完点 💾 保存 才会存到 app_settings (backup.auto / interval_hours / keep_count).
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)
        v.addWidget(_section_header("💾 备份设置"))
        form = QFormLayout()
        form.setContentsMargins(0, 8, 0, 8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        h1 = QHBoxLayout()
        self.cb_auto = QCheckBox("启用")
        h1.addWidget(self.cb_auto)
        h1.addStretch(1)
        wrap1 = QWidget()
        wrap1.setLayout(h1)
        form.addRow("自动备份:", wrap1)
        self.spn_intv = _spin(1, 168, 24)
        form.addRow("备份间隔 (小时):", self.spn_intv)
        self.spn_keep = _spin(1, 100, 7)
        form.addRow("保留份数:", self.spn_keep)
        v.addLayout(form)
        self.lbl_status = QLabel("")
        self.lbl_status.setObjectName("backupStatus")
        self.lbl_status.setStyleSheet(f"color: {text_subtle()}; font-size: 11px;")
        v.addWidget(self.lbl_status)
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存")
        self.btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self.btn_save)
        btn_row.addStretch(1)
        v.addLayout(btn_row)
        v.addStretch(1)
        self._load()

    def _load(self) -> None:
        from app.services import app_setting_service
        try:
            self.cb_auto.setChecked(bool(app_setting_service.get("backup.auto", True)))
            self.spn_intv.setValue(int(app_setting_service.get("backup.interval_hours", 24)))
            self.spn_keep.setValue(int(app_setting_service.get("backup.keep_count", 7)))
            self.lbl_status.setText("✓ 已加载当前设置")
            self.lbl_status.setStyleSheet(f"color: {text_warn_ok()}; font-size: 11px;")
        except Exception as e:
            self.lbl_status.setText(f"(加载失败, 显示默认: {e})")
            self.lbl_status.setStyleSheet(f"color: {text_subtle()}; font-size: 11px;")

    def _on_save(self) -> None:
        from app.services import app_setting_service
        from app.ui.widgets import Dialogs
        try:
            app_setting_service.set("backup.auto", bool(self.cb_auto.isChecked()))
            app_setting_service.set("backup.interval_hours", int(self.spn_intv.value()))
            app_setting_service.set("backup.keep_count", int(self.spn_keep.value()))
        except Exception as e:
            self.lbl_status.setText(f"❌ 保存失败: {e}")
            self.lbl_status.setStyleSheet(f"color: {text_danger()}; font-size: 11px;")
            Dialogs.error("保存失败", str(e), parent=self)
            return
        self.lbl_status.setText(
            f"✓ 已保存: auto={self.cb_auto.isChecked()}, "
            f"interval={self.spn_intv.value()}h, keep={self.spn_keep.value()}"
        )
        self.lbl_status.setStyleSheet(f"color: {text_warn_ok()}; font-size: 11px;")
        Dialogs.info(
            "保存",
            f"备份设置已保存:\n"
            f"  自动备份: {'启用' if self.cb_auto.isChecked() else '禁用'}\n"
            f"  间隔: {self.spn_intv.value()} 小时\n"
            f"  保留: {self.spn_keep.value()} 份",
            parent=self,
        )


class StorageBackupTab(QWidget):
    """📁 存储备份: 合并存储位置 + 备份设置."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # 上半: 存储位置
        self._storage = StorageTab()
        v.addWidget(self._storage, 1)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: rgba(127,127,127,0.2);")
        sep.setFixedHeight(1)
        v.addWidget(sep)

        # 下半: 备份设置
        self._backup = BackupTab()
        v.addWidget(self._backup, 1)


class LogTab(QWidget):
    """📋 日志: 级别 + 单文件最大 MB.

    (纯展示, 不持久化 — 日志系统运行期由 main.py 决定, 不允许运行时改)
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)
        v.addWidget(_section_header("📋 日志设置"))
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("日志级别:"))
        self.cmb_lvl = QComboBox()
        self.cmb_lvl.addItems(["DEBUG", "INFO", "WARN", "ERROR"])
        self.cmb_lvl.setCurrentIndex(1)
        self.cmb_lvl.setEnabled(False)  # 启动期固定, 不允许运行时改
        h1.addWidget(self.cmb_lvl)
        h1.addStretch(1)
        v.addLayout(h1)
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("单文件最大 MB:"))
        self.spn_logmb = _spin(1, 100, 10)
        self.spn_logmb.setEnabled(False)  # 同上
        h2.addWidget(self.spn_logmb)
        h2.addStretch(1)
        v.addLayout(h2)
        v.addWidget(QLabel(
            "<i>日志相关参数在 <code>app/main.py</code> 启动时确定, 运行时不可改。"
            "如需调整请改 <code>DEFAULT_SETTINGS</code> 里的 <code>log.*</code> key。</i>"
        ))
        v.addStretch(1)
