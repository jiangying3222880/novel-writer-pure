"""
I6 AntiRuleEditorDialog - 反规则编辑器 (v3.3.0 新增).

设计参考 docs/widgets-mockup.html I6 (2026-06-10 批准).

数据结构 (存储在 setting_service.ANTI_RULES):
[
  {
    "id": str (uuid12),
    "pattern": str,           # 禁止的词/短语/句式
    "severity": "error" | "warning",  # 触达时严重度
    "description": str,        # 该规则说明 (为什么禁)
    "examples": str,           # 命中示例 (换行分隔)
  },
  ...
]

UI 结构:
  +--------------------------------------------+
  |  列表 (左)              |  详情编辑 (右)    |
  |  + 规则A                |  模式: [____]      |
  |  规则B (选中)           |  严重度: [error v]  |
  |  规则C                  |  描述: [____]      |
  |                         |  示例: [____]      |
  |  [新] [删]              |                   |
  |                         |  [保存] [取消]     |
  +--------------------------------------------+
"""
from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets import Dialogs

log = logging.getLogger(__name__)

SEV_OPTIONS = [
    ("error", "Error (硬性禁止)"),
    ("warning", "Warning (建议避免)"),
]

_EMPTY_RULE = {
    "id": "",
    "pattern": "",
    "severity": "error",
    "description": "",
    "examples": "",
}


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _normalize(rule: dict) -> dict:
    """统一字典形态 (缺字段给空)."""
    return {
        "id": str(rule.get("id") or _new_id()),
        "pattern": str(rule.get("pattern") or "").strip(),
        "severity": str(rule.get("severity") or "error"),
        "description": str(rule.get("description") or "").strip(),
        "examples": str(rule.get("examples") or "").strip(),
    }


class _RuleEditWidget(QWidget):
    """右侧详情编辑卡."""

    def __init__(self, on_change: callable = None) -> None:
        super().__init__()
        self._on_change = on_change
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.ed_pattern = QLineEdit()
        self.ed_pattern.setPlaceholderText("例如: '她咬了咬嘴唇' / '他愣了一下'")
        self.ed_pattern.textChanged.connect(self._emit_change)
        form.addRow("禁用模式:", self.ed_pattern)

        self.cb_severity = QComboBox()
        for val, label in SEV_OPTIONS:
            self.cb_severity.addItem(label, val)
        self.cb_severity.currentIndexChanged.connect(self._emit_change)
        form.addRow("严重度:", self.cb_severity)

        self.ed_description = QLineEdit()
        self.ed_description.setPlaceholderText("为什么禁? 例: 这是 AI 味的标志动作")
        self.ed_description.textChanged.connect(self._emit_change)
        form.addRow("规则描述:", self.ed_description)

        self.ed_examples = QPlainTextEdit()
        self.ed_examples.setPlaceholderText(
            "命中示例 (每行一条):\n她咬了咬嘴唇, 心里有些不安。"
            "\n他愣了一下, 似乎没料到。"
        )
        self.ed_examples.setMaximumHeight(120)
        self.ed_examples.textChanged.connect(self._emit_change)
        form.addRow("示例:", self.ed_examples)
        outer.addLayout(form)
        outer.addStretch(1)

    def _emit_change(self, *_args) -> None:
        if callable(self._on_change):
            try:
                self._on_change()
            except Exception:
                log.exception("on_change failed")

    def set_rule(self, rule: dict) -> None:
        # block signals
        for w in (self.ed_pattern, self.ed_description, self.ed_examples, self.cb_severity):
            w.blockSignals(True)
        try:
            self.ed_pattern.setText(rule.get("pattern", ""))
            self.ed_description.setText(rule.get("description", ""))
            self.ed_examples.setPlainText(rule.get("examples", ""))
            sev = rule.get("severity", "error")
            for i in range(self.cb_severity.count()):
                if self.cb_severity.itemData(i) == sev:
                    self.cb_severity.setCurrentIndex(i)
                    break
        finally:
            for w in (self.ed_pattern, self.ed_description, self.ed_examples, self.cb_severity):
                w.blockSignals(False)

    def collect(self) -> dict:
        return {
            "id": "",  # 由 list 维护
            "pattern": self.ed_pattern.text().strip(),
            "severity": self.cb_severity.currentData() or "error",
            "description": self.ed_description.text().strip(),
            "examples": self.ed_examples.toPlainText().strip(),
        }


class AntiRuleEditorDialog(QDialog):
    """反规则结构化编辑器.

    Public API:
        dlg = AntiRuleEditorDialog(parent)
        dlg.set_rules(rules: list[dict])
        rules = dlg.get_rules() -> list[dict]
        if dlg.exec() == QDialog.Accepted:  # 用户点了保存
            rules = dlg.get_rules()
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("🚫 反规则编辑")
        self.resize(900, 520)
        self._rules: List[dict] = []
        self._dirty: bool = False
        self._current_id: Optional[str] = None
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)

        header = QLabel("反规则 = 写作时禁止出现的模式 (句式/短语/动作). 在 prompt_assembler 注入到 writer.")
        header.setObjectName("dlgHint")
        header.setWordWrap(True)
        outer.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, 1)

        # ---- 左: 规则列表 ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("规则列表:"))

        self.list_rules = QListWidget()
        self.list_rules.currentItemChanged.connect(self._on_select)
        left_layout.addWidget(self.list_rules, 1)

        btn_row = QHBoxLayout()
        self.btn_new = QPushButton("新规则")
        self.btn_new.clicked.connect(self._on_new)
        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._on_delete)
        btn_row.addWidget(self.btn_new)
        btn_row.addWidget(self.btn_delete)
        btn_row.addStretch(1)
        left_layout.addLayout(btn_row)
        splitter.addWidget(left)

        # ---- 右: 详情编辑 ----
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("规则详情:"))
        self._edit = _RuleEditWidget(on_change=self._on_edit_changed)
        right_layout.addWidget(self._edit, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([280, 620])

        # ---- 底部: 保存/取消 ----
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_save = QPushButton("保存")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self._on_save)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self.btn_save)
        bottom.addWidget(self.btn_cancel)
        outer.addLayout(bottom)

    # ===========================================================
    # Public API
    # ===========================================================
    def set_rules(self, rules: list) -> None:
        """载入规则列表."""
        self._rules = [_normalize(r) for r in (rules or [])]
        self._reload_list()
        if self._rules:
            self.list_rules.setCurrentRow(0)
        else:
            self._clear_edit()

    def get_rules(self) -> list:
        """返回当前规则列表 (已 _normalize)."""
        return [dict(r) for r in self._rules]

    # ===========================================================
    # Internal
    # ===========================================================
    def _reload_list(self) -> None:
        self.list_rules.blockSignals(True)
        try:
            self.list_rules.clear()
            for r in self._rules:
                pattern = r.get("pattern", "") or "(空)"
                sev = r.get("severity", "error")
                sev_mark = "❌" if sev == "error" else "⚠️"
                item = QListWidgetItem(f"{sev_mark} {pattern}")
                item.setData(Qt.ItemDataRole.UserRole, r["id"])
                tooltip = f"id: {r['id']}\n描述: {r.get('description', '')}\n示例: {r.get('examples', '')}"
                item.setToolTip(tooltip)
                self.list_rules.addItem(item)
        finally:
            self.list_rules.blockSignals(False)
        if self.list_rules.count() > 0 and self.list_rules.currentRow() < 0:
            self.list_rules.setCurrentRow(0)

    def _on_select(self, current: Optional[QListWidgetItem], _prev) -> None:
        if current is None:
            self._current_id = None
            self._clear_edit()
            return
        rid = current.data(Qt.ItemDataRole.UserRole)
        self._current_id = rid
        rule = self._find_by_id(rid)
        if rule is not None:
            self._edit.set_rule(rule)

    def _on_new(self) -> None:
        new_rule = _normalize({})
        self._rules.append(new_rule)
        self._reload_list()
        # 选中新加项
        for i in range(self.list_rules.count()):
            it = self.list_rules.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == new_rule["id"]:
                self.list_rules.setCurrentRow(i)
                break
        self._dirty = True
        self.ed_pattern.setFocus() if hasattr(self, "ed_pattern") else None

    def _on_delete(self) -> None:
        if not self._current_id:
            return
        rule = self._find_by_id(self._current_id)
        pattern = rule.get("pattern", "") if rule else "?"
        if not Dialogs.confirm(
            "删除规则",
            f"确认删除规则 '{pattern}'?",
            parent=self,
        ):
            return
        self._rules = [r for r in self._rules if r["id"] != self._current_id]
        self._dirty = True
        self._reload_list()
        if self._rules:
            self.list_rules.setCurrentRow(0)
        else:
            self._clear_edit()

    def _on_edit_changed(self) -> None:
        if not self._current_id:
            return
        rule = self._find_by_id(self._current_id)
        if rule is None:
            return
        new = self._edit.collect()
        # 保留 id
        new["id"] = rule["id"]
        # 就地更新
        for k, v in new.items():
            rule[k] = v
        self._dirty = True
        # 同步 list 显示
        item = self.list_rules.currentItem()
        if item is not None:
            pattern = rule.get("pattern", "") or "(空)"
            sev = rule.get("severity", "error")
            sev_mark = "❌" if sev == "error" else "⚠️"
            item.setText(f"{sev_mark} {pattern}")

    def _on_save(self) -> None:
        # 校验: 至少 1 条规则必须有 pattern
        valid_rules = []
        for r in self._rules:
            r2 = _normalize(r)
            if not r2["pattern"]:
                continue  # 跳过空 pattern
            valid_rules.append(r2)
        if not valid_rules and self._rules:
            # 用户加了空规则, 但实际写过 pattern 的为 0
            Dialogs.warning(
                "保存",
                "所有规则均为空 pattern, 请至少填写一条规则。",
                parent=self,
            )
            return
        self._rules = valid_rules
        self._dirty = False
        self.accept()

    def _clear_edit(self) -> None:
        self._edit.set_rule(_EMPTY_RULE)
        self.ed_pattern = self._edit.ed_pattern  # 暴露给 _on_new
        self._current_id = None

    def _find_by_id(self, rid: str) -> Optional[dict]:
        for r in self._rules:
            if r["id"] == rid:
                return r
        return None
