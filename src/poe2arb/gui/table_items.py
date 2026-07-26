"""Table cell types.

QTableWidgetItem sorts by comparing display *text*, so "8.7700" sorts above
"4,886.0000" — string order, not numeric. Every numeric column needs an item
that carries the underlying number and compares on that instead.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem


class NumericItem(QTableWidgetItem):
    """Displays formatted text, sorts by the real number behind it."""

    def __init__(self, text: str, value: float):
        super().__init__(text)
        self._value = value if value is not None and not math.isnan(value) else -math.inf
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    @property
    def value(self) -> float:
        return self._value

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, NumericItem):
            return self._value < other._value
        return super().__lt__(other)


class TextItem(QTableWidgetItem):
    """Plain read-only text cell."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)
