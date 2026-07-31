"""Table cell types.

QTableWidgetItem sorts by comparing display *text*, so "8.7700" sorts above
"4,886.0000" — string order, not numeric. Every numeric column needs an item
that carries the underlying number and compares on that instead.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionViewItem,
    QTableWidget,
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


class RowHoverDelegate(QStyledItemDelegate):
    """Paints every cell of the table's hovered row as hovered.

    Qt hovers one *cell*, which on a table whose actions live in the row itself
    reads as nothing at all — you are pointing at a button and the row it acts
    on gives no sign. This widens the hover to the row and takes the row number
    from the view rather than from the mouse, so a cell widget can report a
    hover the view never saw.

    The tint is painted here rather than left to `State_MouseOver`. Verified by
    screenshot: setting the flag alone changed nothing visible under the styles
    this ships with, so the row lit up in the widget tree and not on screen.
    Translucent, and derived from the palette's highlight, so it reads the same
    over alternating rows and in either theme.
    """

    HOVER_ALPHA = 52

    def _is_hovered(self, index) -> bool:
        table = self.parent()
        return table is not None and index.row() == getattr(table, "hover_row", -1)

    def initStyleOption(self, option, index) -> None:  # noqa: N802 (Qt naming)
        super().initStyleOption(option, index)
        if self._is_hovered(index):
            option.state |= QStyle.StateFlag.State_MouseOver

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)
        if not self._is_hovered(index):
            return
        tint = QColor(option.palette.highlight().color())
        tint.setAlpha(self.HOVER_ALPHA)
        painter.fillRect(option.rect, tint)


class RowHoverTable(QTableWidget):
    """A table whose whole row lights up under the cursor, buttons included.

    Cell widgets are separate widgets parented to the viewport, so the view gets
    no mouse events at all while the pointer is over one — which is why hovering
    Accept used to highlight nothing (reported from the field 2026-07-31). Rows
    here are reported from three places: the viewport's own mouse tracking, and
    `watch` on any in-row widget and its buttons.

    Clearing is deferred by one event-loop pass and re-checked against the real
    cursor position, because Qt sends the viewport a Leave the moment the mouse
    crosses onto a child button — taking the leave at face value would make the
    highlight flicker off exactly when the user reaches for the thing it marks.
    """

    def __init__(self, columns: int, parent=None):
        super().__init__(0, columns, parent)
        self.hover_row = -1
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setItemDelegate(RowHoverDelegate(self))

    def set_hover_row(self, row: int) -> None:
        if row == self.hover_row:
            return
        self.hover_row = row
        self.viewport().update()

    def watch(self, widget, row: int) -> None:
        """Have `widget` and its children report hovers as belonging to `row`."""
        from PySide6.QtWidgets import QAbstractButton

        widget._hover_row = row  # read back by eventFilter, which sees children
        widget.installEventFilter(self)
        for child in widget.findChildren(QAbstractButton):
            child._hover_row = row
            child.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt naming)
        if event.type() == QEvent.Type.Enter:
            self.set_hover_row(getattr(watched, "_hover_row", -1))
        elif event.type() == QEvent.Type.Leave:
            self._clear_soon()
        return super().eventFilter(watched, event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.set_hover_row(self.rowAt(int(event.position().y())))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self._clear_soon()
        super().leaveEvent(event)

    def _clear_soon(self) -> None:
        QTimer.singleShot(0, self._clear_if_outside)

    def _clear_if_outside(self) -> None:
        try:
            inside = self.viewport().rect().contains(
                self.viewport().mapFromGlobal(QCursor.pos())
            )
        except RuntimeError:  # the table went away while the timer was pending
            return
        if not inside:
            self.set_hover_row(-1)


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
