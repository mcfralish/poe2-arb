"""Table cell types.

QTableWidgetItem sorts by comparing display *text*, so "8.7700" sorts above
"4,886.0000" — string order, not numeric. Every numeric column needs an item
that carries the underlying number and compares on that instead.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QTableWidgetItem,
)


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


class CentredCheckDelegate(QStyledItemDelegate):
    """Draws a cell's check indicator in the middle of the column.

    `setTextAlignment(AlignCenter)` does not do this. Qt lays the indicator out
    on the leading edge of the cell and centres only the *text* beside it, so a
    checkbox-only column reads as left-aligned under a centred header however the
    item is aligned. Centring it needs the indicator drawn by hand.

    Hit-testing is narrowed to the indicator to match: clicks elsewhere in the
    cell are swallowed rather than toggling, because a wide invisible hit area on
    a column that changes what gets swept is a good way to exclude something by
    accident.
    """

    def _indicator_rect(self, option: QStyleOptionViewItem) -> QRect:
        style = option.widget.style() if option.widget else QApplication.style()
        rect = QRect(0, 0,
                     style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, option, option.widget),
                     style.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight, option, option.widget))
        rect.moveCenter(option.rect.center())
        return rect

    @staticmethod
    def _check_state(index) -> Qt.CheckState:
        """The cell's check state. Qt hands this back as a bare int on some builds."""
        raw = index.data(Qt.ItemDataRole.CheckStateRole)
        if raw is None:
            return Qt.CheckState.Unchecked
        return Qt.CheckState(raw)

    def paint(self, painter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # Let the base style paint the row background and selection, but not its
        # own indicator — ours replaces it.
        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        opt.checkState = Qt.CheckState.Unchecked
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        indicator = QStyleOptionButton()
        indicator.rect = self._indicator_rect(option)
        indicator.state = QStyle.StateFlag.State_Enabled
        if self._check_state(index) == Qt.CheckState.Checked:
            indicator.state |= QStyle.StateFlag.State_On
        else:
            indicator.state |= QStyle.StateFlag.State_Off
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck,
            indicator, painter, opt.widget,
        )

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802 (Qt naming)
        if not (index.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            return False
        if event.type() == QEvent.Type.MouseButtonRelease:
            if self._indicator_rect(option).contains(event.position().toPoint()):
                now = self._check_state(index)
                flipped = (
                    Qt.CheckState.Unchecked
                    if now == Qt.CheckState.Checked
                    else Qt.CheckState.Checked
                )
                return model.setData(index, flipped, Qt.ItemDataRole.CheckStateRole)
            return True
        # A double-click on a checkbox column means the same as a click, and
        # would otherwise start an edit.
        if event.type() == QEvent.Type.MouseButtonDblClick:
            return True
        return False
