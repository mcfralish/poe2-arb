"""Table cell types.

QTableWidgetItem sorts by comparing display *text*, so "8.7700" sorts above
"4,886.0000" — string order, not numeric. Every numeric column needs an item
that carries the underlying number and compares on that instead.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QObject, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
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
        """Have `widget` report hovers as belonging to `row` — but not its buttons.

        The buttons deliberately report **no** row. Pointing at Accept should
        light up Accept and nothing else: the row tint is there to say which
        trade a click would act on, and once the cursor is on the button itself
        that question is already answered, so a whole highlighted row is just
        noise around the thing you are aiming at (reported from the field
        2026-07-31). Hovering the gaps between the buttons still lights the row,
        because there the pointer really is on the row rather than a control.
        """
        from PySide6.QtWidgets import QAbstractButton

        widget._hover_row = row  # read back by eventFilter, which sees children
        widget.installEventFilter(self)
        for child in widget.findChildren(QAbstractButton):
            child._hover_row = -1
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


class ColumnLayout(QObject):
    """Columns the user can reorder and resize, that still grow with the window.

    Qt's header offers those three properties two at a time and never all three.
    `ResizeToContents` sizes a column well and refuses to be dragged;
    `Stretch` shares the width out and also refuses; `Interactive` is the only
    draggable mode, and it pins every column at a fixed pixel width so widening
    the window puts all the new space into one stretched column and leaves the
    rest exactly as they were.

    So growth is done here. Every widening hands each column a share of the new
    space proportional to what it already has, which is what `Stretch` does,
    while the sections stay `Interactive` and therefore draggable. Order and
    widths both persist through `state()` / `restore()`.

    Attached with `flexible_columns(table)` rather than constructed directly;
    the table keeps a reference so the filter outlives the call.
    """

    # The floor for a column with no heading — a marker or an action column.
    MIN_WIDTH = 28
    # Space around a heading: the cell's own margins, plus room for the sort
    # indicator on a sortable table, which Qt draws inside the section.
    HEADER_PADDING = 26
    # Columns holding a name someone has to read rather than a number. A header
    # width is the wrong floor for these — "Item" is four characters and its
    # contents run to "Zarokh's Reliquary Key: Against the Darkness".
    ROOMY_HEADERS = ("Item", "Seller")
    ROOMY_MIN = 120

    def __init__(
        self,
        table: QTableWidget,
        protected: tuple[int, ...] = (),
        roomy: tuple[str, ...] = ROOMY_HEADERS,
    ):
        super().__init__(table)
        self.table = table
        # Columns exempt from the initial squeeze — in practice the one holding
        # a row's action buttons, which have a real width and are useless
        # clipped. Everything else gives way to fit the window instead.
        self._protected = set(protected)
        self._roomy = set(roomy)
        self._last_width = 0
        self._sized = False
        header = table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setToolTip(
            "Drag a heading to reorder the columns, or a divider to resize one."
        )
        # The viewport, not the table, and its event's own size rather than a
        # width read back afterwards: a filter runs *before* the widget handles
        # the event, so at that point the table is wider and the viewport inside
        # it has not caught up yet.
        table.viewport().installEventFilter(self)

    # -- sizing

    def min_width(self, column: int) -> int:
        """How narrow this column may get: its own heading, plus padding.

        One floor for every column was measured too low in the fourth field
        test — at the narrow end of the window `Profit` read as "rofit" and
        `Expires` as "xpire", which is a header lying about which column you
        are looking at. A column that cannot show its own name is not a column,
        so the floor is per-column and comes from the text in the header.

        This is the same rule the action column already had for a different
        reason: a control that has been squeezed is not smaller, it is clipped.
        """
        item = self.table.horizontalHeaderItem(column)
        text = item.text() if item is not None else ""
        if not text:
            return max(self.MIN_WIDTH, self._widget_floor(column))
        metrics = self.table.horizontalHeader().fontMetrics()
        floor = metrics.horizontalAdvance(text) + self.HEADER_PADDING
        if text in self._roomy:
            floor = max(floor, self.ROOMY_MIN)
        return max(floor, self._widget_floor(column))

    def _widget_floor(self, column: int) -> int:
        """What a control in this column needs, or 0 if there isn't one.

        `resizeColumnsToContents` measures items and ignores cell widgets, so
        a column holding a spin box was sized to the number and not to the
        arrows beside it — which is the same failure as an action column sized
        to a guess, one control smaller. Row 0 is enough: every row in a column
        is built the same way, and asking each of fifty would put a loop inside
        a resize event.
        """
        if not self.table.rowCount():
            return 0
        widget = self.table.cellWidget(0, column)
        return widget.sizeHint().width() if widget is not None else 0

    def minimum_row_width(self) -> int:
        """The narrowest the whole row can be drawn without lying.

        What the window's own minimum width has to clear, plus whatever the
        chrome around the table costs.
        """
        header = self.table.horizontalHeader()
        return sum(
            max(self.min_width(i), header.sectionSize(i) if i in self._protected else 0)
            for i in range(header.count())
            if not header.isSectionHidden(i)
        )

    def size_to_contents(self) -> None:
        """Fit every column to what is in it, then to the window. Once.

        Called after the first rows arrive rather than at construction: an empty
        table sizes every column to its heading, which is where "Item" ended up
        narrower than "Seller".

        The squeeze afterwards is what `Stretch` used to do for free. Sizing to
        contents alone overflows — an item name runs to "Zarokh's Reliquary Key:
        Against the Darkness" — and the columns that fell off the right-hand
        edge were the actions, which is the half of the row you click.
        """
        if self._sized or not self.table.rowCount():
            return
        self._sized = True
        self.table.resizeColumnsToContents()
        # `resizeColumnsToContents` sizes to the *cells* and will happily leave
        # a column narrower than its own heading — "Buy" came back at 30px
        # against a 49px title. Raising each to its floor here keeps the
        # invariant the squeeze and the growth both assume: a section is never
        # below `min_width`.
        header = self.table.horizontalHeader()
        for i in range(header.count()):
            floor = self.min_width(i)
            if header.sectionSize(i) < floor:
                header.resizeSection(i, floor)
        self._fit_protected()
        width = self.table.viewport().width()
        self._last_width = width
        self._squeeze(width)

    def _fit_protected(self) -> None:
        """Size an action column to the buttons actually in it.

        `resizeColumnsToContents` measures *items*, and an action column holds a
        cell widget and no item, so the width it comes back with is a guess —
        measured 314px for a row of buttons that asks for 226. The column is
        exempt from the squeeze, so that 88px of nothing came straight off the
        columns that do hold something, and the row overflowed the window
        anyway. Asking the widget how wide it is costs one call and is the
        number the exemption was always meant to protect.
        """
        header = self.table.horizontalHeader()
        for i in self._protected:
            widths = [
                w.sizeHint().width()
                for row in range(self.table.rowCount())
                if (w := self.table.cellWidget(row, i)) is not None
            ]
            if widths:
                header.resizeSection(i, max(max(widths), self.min_width(i)))

    def _squeeze(self, width: int) -> None:
        """Shrink the unprotected columns proportionally until the row fits."""
        header = self.table.horizontalHeader()
        visible = [i for i in range(header.count()) if not header.isSectionHidden(i)]
        total = sum(header.sectionSize(i) for i in visible)
        excess = total - width
        if excess <= 0 or width <= 0:
            return
        givers = [i for i in visible if i not in self._protected]
        available = sum(
            max(0, header.sectionSize(i) - self.min_width(i)) for i in givers
        )
        if available <= 0:
            return
        take = min(excess, available)
        for i in givers:
            floor = self.min_width(i)
            slack = max(0, header.sectionSize(i) - floor)
            header.resizeSection(
                i,
                max(floor, header.sectionSize(i) - round(take * slack / available)),
            )

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 (Qt naming)
        try:
            if watched is self.table.viewport() and event.type() == QEvent.Type.Resize:
                self._grow(event.size().width())
        except (RuntimeError, AttributeError):
            # The table, or this object's C++ half, went away underneath us
            # while the event was in flight. Only happens during teardown, and
            # only Qt is left to care about the answer.
            return False
        return super().eventFilter(watched, event)

    def _grow(self, width: int) -> None:
        if not self._sized or width <= 0:
            self._last_width = max(self._last_width, width)
            return
        was, self._last_width = self._last_width, width
        header = self.table.horizontalHeader()
        visible = [
            i for i in range(header.count()) if not header.isSectionHidden(i)
        ]
        occupied = sum(header.sectionSize(i) for i in visible)
        # Hand out the space the row does not already fill, not the space the
        # *window* gained. A row can be wider than the window — the squeeze
        # stops at the per-column floors, and the first sizing runs against a
        # pre-show viewport that is narrower than the real one. Adding the
        # window's delta on top of that overflow compounds it: measured on the
        # Waiting table, a 638px sizing that had settled at 897 grew to 1235 in
        # a 976px window, and what fell off the end was the action buttons.
        delta = width - max(was, occupied)
        if delta < 0 and width >= was:
            delta = 0     # still too wide for the window, but no worse than before
        if delta == 0:
            return
        # A protected column shares in the growth but never in the shrinking.
        # Its content is a row of buttons at a fixed size, so taking width off
        # it does not make it smaller — it clips the last button off the end,
        # and an action you cannot reach is worse than one you have to scroll to.
        if delta < 0:
            visible = [i for i in visible if i not in self._protected] or visible
        total = sum(header.sectionSize(i) for i in visible)
        if total <= 0:
            return
        # Shrinking is allowed to run each column down to its own heading width
        # and no further; past that the table scrolls horizontally, which is
        # better than a header that has been truncated into a different word.
        spent = 0
        for i in visible[:-1]:
            share = round(delta * header.sectionSize(i) / total)
            header.resizeSection(
                i, max(self.min_width(i), header.sectionSize(i) + share)
            )
            spent += share
        last = visible[-1]
        header.resizeSection(
            last, max(self.min_width(last), header.sectionSize(last) + delta - spent)
        )

    # -- persistence

    def state(self) -> str:
        """Order and widths as text, for ui-state.json."""
        import base64

        return base64.b64encode(bytes(self.table.horizontalHeader().saveState())).decode("ascii")

    def restore(self, blob: object) -> bool:
        """Put back a saved arrangement. Anything unreadable is ignored."""
        import base64

        if not isinstance(blob, str) or not blob:
            return False
        try:
            data = base64.b64decode(blob.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError):
            return False
        if not self.table.horizontalHeader().restoreState(data):
            return False
        # A restored arrangement is already sized, so the first populate must
        # not overwrite it with resizeColumnsToContents.
        self._sized = True
        self._last_width = self.table.viewport().width()
        return True


def flexible_columns(
    table: QTableWidget,
    protected: tuple[int, ...] = (),
    roomy: tuple[str, ...] = ColumnLayout.ROOMY_HEADERS,
) -> ColumnLayout:
    """Give `table` reorderable, resizable, proportionally growing columns.

    Call this **after** `setHorizontalHeaderLabels`: the per-column minimum is
    read off the heading text, and a table with no headings yet would floor
    every column at `MIN_WIDTH`.
    """
    layout = ColumnLayout(table, protected, roomy)
    table._column_layout = layout  # keeps the filter alive with the table
    return layout


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
