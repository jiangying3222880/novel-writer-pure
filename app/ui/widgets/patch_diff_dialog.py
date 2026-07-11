"""
PatchDiffDialog — 保存前的 diff 预览对话框

展示新旧内容的差异，用户确认后才保存。
"""
from __future__ import annotations

import difflib
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QPushButton, QSplitter, QFrame,
)


class PatchDiffDialog(QDialog):
    """Diff 预览对话框."""

    def __init__(self, old_text: str, new_text: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("变更预览")
        self.setMinimumSize(800, 500)
        self._build(old_text, new_text)

    def _build(self, old_text: str, new_text: str) -> None:
        layout = QVBoxLayout(self)

        # 统计
        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()
        added = max(0, len(new_lines) - len(old_lines))
        removed = max(0, len(old_lines) - len(new_lines))
        stats = QLabel(f"变更统计: +{added} 行 / -{removed} 行 / 共 {len(new_lines)} 行")
        stats.setStyleSheet("font-weight: bold; padding: 8px;")
        layout.addWidget(stats)

        # Diff 视图
        diff_text = "\n".join(difflib.unified_diff(
            old_lines, new_lines,
            fromfile="原内容", tofile="新内容",
            lineterm="",
        ))

        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(diff_text)
        # 简单着色: + 绿, - 红
        editor.setStyleSheet("""
            QTextEdit {
                font-family: Consolas, monospace;
                font-size: 12px;
                background: #1e1e2e;
                color: #cdd6f4;
            }
        """)
        layout.addWidget(editor, 1)

        # 按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = QPushButton("取消保存")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        confirm_btn = QPushButton("确认保存")
        confirm_btn.setObjectName("primaryButton")
        confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(confirm_btn)
        layout.addLayout(btn_row)
