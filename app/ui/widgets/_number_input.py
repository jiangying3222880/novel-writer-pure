"""带验证器的数字输入框，替代 QSpinBox/QDoubleSpinBox（Qt6 下 SpinBox + padding QSS 会导致按钮卡死）。"""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit
from PySide6.QtGui import QIntValidator, QDoubleValidator
from PySide6.QtCore import Signal


class NumberInput(QLineEdit):
    """纯文本整数输入框，内置 QIntValidator，兼容 QSpinBox 常用 API。

    属性/方法:
        .value()  → int
        .setValue(v: int)
        .setRange(lo, hi)
        .valueChanged 信号 (int) — 当文本改变时发出
    """

    valueChanged = Signal(int)

    def __init__(
        self, lo: int = 0, hi: int = 999999, default: int = 0, parent=None,
        *, suffix: str = "",
    ) -> None:
        super().__init__(parent)
        self._lo = lo
        self._hi = hi
        self._suffix = suffix
        self._validator = QIntValidator(lo, hi, self)
        self.setValidator(self._validator)
        self.setText(str(default))
        self.textChanged.connect(self._emit_if_valid)

    def _emit_if_valid(self, _text: str = "") -> None:
        try:
            int(self.text())
            self.valueChanged.emit(self.value())
        except ValueError:
            pass

    def value(self) -> int:
        try:
            return int(self.text())
        except ValueError:
            return self._lo

    def setValue(self, v: int) -> None:
        old = self.blockSignals(True)
        self.setText(str(v))
        self.blockSignals(old)

    def setRange(self, lo: int, hi: int) -> None:
        self._lo = lo
        self._hi = hi
        self.setValidator(QIntValidator(lo, hi, self))

    def minimum(self) -> int: return self._lo
    def maximum(self) -> int: return self._hi
    def setSingleStep(self, step: int) -> None: pass
    def setSuffix(self, s: str) -> None: self._suffix = s


class DoubleInput(QLineEdit):
    """纯文本浮点数输入框，内置 QDoubleValidator，兼容 QDoubleSpinBox 常用 API。

    属性/方法:
        .value()  → float
        .setValue(v: float)
        .setRange(lo, hi)
        .setDecimals(n)
        .setSingleStep(s)
    """

    valueChanged = Signal(float)

    def __init__(
        self, lo: float = 0.0, hi: float = 100.0, default: float = 0.0,
        decimals: int = 1, parent=None,
    ) -> None:
        super().__init__(parent)
        self._lo = lo
        self._hi = hi
        self._decimals = decimals
        self._validator = QDoubleValidator(lo, hi, decimals, self)
        self.setValidator(self._validator)
        self._set_text(default)
        self.textChanged.connect(self._emit_if_valid)

    def _set_text(self, v: float) -> None:
        self.setText(f"{v:.{self._decimals}f}".rstrip("0").rstrip("."))

    def _emit_if_valid(self, _text: str = "") -> None:
        try:
            float(self.text())
            self.valueChanged.emit(self.value())
        except ValueError:
            pass

    def value(self) -> float:
        try:
            return float(self.text())
        except ValueError:
            return self._lo

    def setValue(self, v: float) -> None:
        old = self.blockSignals(True)
        self._set_text(v)
        self.blockSignals(old)

    def setRange(self, lo: float, hi: float) -> None:
        self._lo = lo
        self._hi = hi
        self.setValidator(QDoubleValidator(lo, hi, self._decimals, self))

    def setDecimals(self, n: int) -> None:
        self._decimals = n
        self._validator.setDecimals(n)

    def setSingleStep(self, step: float) -> None: pass
