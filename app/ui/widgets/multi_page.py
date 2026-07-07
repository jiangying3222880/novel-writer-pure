"""
I20 MultiPageInput - 向导式多页输入.

设计参考 docs/widgets-mockup.html I20 (2026-06-10 批准).

特性:
- 顶部步骤条 (横向), 显示当前进度
- 每步承载一个 QWidget (Step 1..N)
- 上一步/下一步/完成 按钮
- AI 状态栏 (可选, 显示正在处理中)
- 步骤切换信号 pageChanged(int)
- 完成信号 finished(dict) (key 为 step_id, value 为该步 widget 收集的数据)

使用:
    mp = MultiPageInput([
        ("step1", "基础信息", basic_widget),
        ("step2", "角色追踪", char_widget),
    ])
    mp.finished.connect(lambda results: print(results))
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from app.ui.theme import text_muted


@dataclass
class PageSpec:
    step_id: str
    title: str
    widget: QWidget
    # 收集数据的回调 (返回 dict). 若 None, 跳过收集
    collect: Optional[Callable[[QWidget], Dict[str, Any]]] = None
    # 该步是否必须通过校验才能 next. 返回 None/空字符串表示通过
    validate: Optional[Callable[[QWidget], Optional[str]]] = None


class MultiPageInput(QFrame):
    """多步表单."""

    pageChanged = Signal(int)  # 0..N-1
    finished = Signal(dict)  # 收集结果
    cancelled = Signal()

    def __init__(
        self,
        pages: List[Tuple[str, str, QWidget]],
        *,
        finish_text: str = "完成",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("multiPageInput")
        self._pages: List[PageSpec] = [
            PageSpec(step_id=sid, title=title, widget=w) for (sid, title, w) in pages
        ]
        self._current = 0
        self._ai_status_text = ""

        self._build_ui()
        self._apply_style()
        self._go_to(0)

    def set_collectors(
        self,
        index: int,
        collect: Callable[[QWidget], Dict[str, Any]],
    ) -> None:
        if 0 <= index < len(self._pages):
            self._pages[index].collect = collect

    def set_validators(
        self,
        index: int,
        validate: Callable[[QWidget], Optional[str]],
    ) -> None:
        if 0 <= index < len(self._pages):
            self._pages[index].validate = validate

    def set_ai_status(self, text: str) -> None:
        """显示 AI 处理状态 (传空字符串隐藏)."""
        self._ai_status_text = text
        if text:
            self._ai_status.setText(f"● {text}")
            self._ai_status.setVisible(True)
        else:
            self._ai_status.setVisible(False)

    # ---- 公开 API ----
    def page_count(self) -> int:
        return len(self._pages)

    def current_index(self) -> int:
        return self._current

    def set_current(self, index: int) -> None:
        self._go_to(index)

    def next(self) -> bool:
        if not self._validate_current():
            return False
        if self._current >= len(self._pages) - 1:
            self._finish()
            return True
        self._go_to(self._current + 1)
        return True

    def prev(self) -> None:
        if self._current == 0:
            return
        self._go_to(self._current - 1)

    def cancel(self) -> None:
        self.cancelled.emit()

    def collect_all(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for spec in self._pages:
            if spec.collect is not None:
                try:
                    data = spec.collect(spec.widget) or {}
                except Exception as e:
                    data = {"__error__": str(e)}
                if isinstance(data, dict):
                    out[spec.step_id] = data
                else:
                    out[spec.step_id] = {"value": data}
        return out

    # ---- 内部 ----
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 步骤条
        self._steps_bar = QFrame(self)
        self._steps_bar.setObjectName("mpStepsBar")
        self._steps_bar.setAttribute(Qt.WA_StyledBackground, True)
        steps_layout = QHBoxLayout(self._steps_bar)
        steps_layout.setContentsMargins(12, 8, 12, 8)
        steps_layout.setSpacing(6)
        self._step_chips: List[QLabel] = []
        for i, spec in enumerate(self._pages):
            chip = QLabel(f"{i + 1}. {spec.title}", self._steps_bar)
            chip.setObjectName("mpStep")
            self._step_chips.append(chip)
            steps_layout.addWidget(chip)
            if i < len(self._pages) - 1:
                arrow = QLabel("›", self._steps_bar)
                arrow.setObjectName("mpArrow")
                steps_layout.addWidget(arrow)
        steps_layout.addStretch(1)
        layout.addWidget(self._steps_bar)

        # 主体 (QStackedWidget)
        self._stack = QStackedWidget(self)
        for spec in self._pages:
            # 容器: 给 widget 留 padding
            wrap = QWidget(self._stack)
            wrap_layout = QVBoxLayout(wrap)
            wrap_layout.setContentsMargins(16, 14, 16, 14)
            wrap_layout.setSpacing(8)
            wrap_layout.addWidget(spec.widget)
            wrap_layout.addStretch(1)
            self._stack.addWidget(wrap)
        layout.addWidget(self._stack, 1)

        # 底部
        footer = QFrame(self)
        footer.setObjectName("mpFooter")
        footer.setAttribute(Qt.WA_StyledBackground, True)
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(12, 10, 12, 10)
        f_layout.setSpacing(8)
        self._ai_status = QLabel("", footer)
        self._ai_status.setObjectName("mpAiStatus")
        self._ai_status.setVisible(False)
        f_layout.addWidget(self._ai_status)
        f_layout.addStretch(1)
        self._cancel_btn = QPushButton("取消", footer)
        self._cancel_btn.clicked.connect(self.cancel)
        f_layout.addWidget(self._cancel_btn)
        self._prev_btn = QPushButton("上一步", footer)
        self._prev_btn.clicked.connect(self.prev)
        f_layout.addWidget(self._prev_btn)
        self._next_btn = QPushButton("下一步 →", footer)
        self._next_btn.setObjectName("primaryAction")
        self._next_btn.clicked.connect(self.next)
        f_layout.addWidget(self._next_btn)
        layout.addWidget(footer)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            "QFrame#multiPageInput { background: #0a0b0d; border: 1px solid #2a2b2f; border-radius: 4px; }"
            "QFrame#mpStepsBar { background: #191a1b; border-bottom: 1px solid #2a2b2f; }"
            "QFrame#mpFooter { background: #0a0b0d; border-top: 1px solid #2a2b2f; }"
            "QLabel#mpStep { color: #8a8f98; font-size: 12px; padding: 4px 10px; border-radius: 3px; }"
            "QLabel#mpStep.active { background: rgba(108,122,224,0.2); color: #6c7ae0; font-weight: 600; }"
            "QLabel#mpStep.done { color: #4ec970; }"
            "QLabel#mpArrow { color: #555a63; margin: 0 4px; }"
            "QLabel#mpAiStatus { color: #8a8f98; font-size: 11px; }"
            "QPushButton { background: #191a1b; color: #f0f1f2; border: 1px solid #2a2b2f; border-radius: 4px; padding: 6px 12px; font-size: 13px; }"
            "QPushButton:hover { background: #222326; }"
            "QPushButton:disabled { color: #555a63; }"
            "QPushButton#primaryAction { background: #6c7ae0; color: #ffffff; border: none; font-weight: 600; }"
            "QPushButton#primaryAction:hover { background: #7d8aff; }"
        )

    def _go_to(self, index: int) -> None:
        if not (0 <= index < len(self._pages)):
            return
        self._current = index
        self._stack.setCurrentIndex(index)
        # 更新步骤样式
        for i, chip in enumerate(self._step_chips):
            chip.setProperty("class", "")
            chip.setStyleSheet("")
            if i < index:
                chip.setText(f"✓ {self._pages[i].title}")
            elif i == index:
                chip.setText(f"{i + 1}. {self._pages[i].title}")
                chip.setStyleSheet(
                    "background: rgba(108,122,224,0.2); color: #6c7ae0; font-weight: 600; padding: 4px 10px; border-radius: 3px; font-size: 12px;"
                )
            else:
                chip.setText(f"{i + 1}. {self._pages[i].title}")
                chip.setStyleSheet(f"color: {text_muted()}; padding: 4px 10px; border-radius: 3px; font-size: 12px;")
        # 按钮状态
        self._prev_btn.setEnabled(index > 0)
        is_last = index == len(self._pages) - 1
        self._next_btn.setText("完成" if is_last else "下一步 →")
        self.pageChanged.emit(index)

    def _validate_current(self) -> bool:
        spec = self._pages[self._current]
        if spec.validate is None:
            return True
        try:
            err = spec.validate(spec.widget)
        except Exception as e:
            err = f"校验异常: {e}"
        if err:
            self._ai_status.setText(f"⚠ {err}")
            self._ai_status.setVisible(True)
            return False
        return True

    def _finish(self) -> None:
        data = self.collect_all()
        self.finished.emit(data)
