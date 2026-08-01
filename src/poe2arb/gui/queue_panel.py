"""The Opportunities tab: trades to act on, and trades waiting on an answer.

Two lists, because they ask the user for two different things:

- **Ready to whisper** — everything takeable, oldest at the top and the newest
  arrival at the bottom, with the live offer marked. Both are takeable; the
  difference is only whether it's currently worth interrupting a map for.
- **Waiting on a reply** — everything already whispered, **newest first**, each
  self-marking as "no reply" when its timer runs out.

The two orders are deliberately opposite. Ready is read top-down and must not
reshuffle under the cursor, so new rows append at the bottom. Waiting is read
when a reply arrives, and a reply is almost always to the whisper just sent.

**Money is shown in the currency the seller asked for**, not in divines. A
listing whispered as "2412 exalted" displayed as "5.6 div" is unrecognisable as
the offer that was made — which matters most when a reply lands an hour later in
a language the user doesn't read. Profit stays in divines, because that is the
only unit the two sides of the trade can be compared in.

**Every action is one click on the row itself.** No select-then-press: the
buttons live in the row they act on, because this is used mid-map and a
two-step interaction is one step too many. That constrains the refresh — the
tables redraw once a second for the countdowns, and rebuilding a row would
destroy the button under the user's cursor mid-click. So `refresh` rebuilds
only when the *set* of trades changes and otherwise touches just the timer text.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..format import currency_label, fmt_amount, fmt_qty
from ..listings import Band
from ..outcomes import Outcome
from ..trade_queue import QueueState
from .bankroll_bar import BankrollBar
from .table_items import NumericItem, RowHoverTable, TextItem, flexible_columns
from .theme import muted_color

log = logging.getLogger(__name__)

_COST_TIP = (
    "Total you'd hand over, in the currency the seller asked for — the figure "
    "that goes into the whisper."
)
_EACH_TIP = "Price of one, in the same currency, so rows stay comparable."
_SETTLE_TIP = (
    "What you'd take when reselling on the Currency Exchange. It sets the "
    "Profit figure, because proceeds round down to a whole unit of it — a whole "
    "divine if you settle in divines, which is the expensive way round."
)

READY_COLUMNS = [
    ("", "A dot marks the live offer — the one the hotkey will copy."),
    ("Item", "What you'd be buying."),
    ("Buy", "How many to ask for."),
    ("Each", _EACH_TIP),
    ("Cost", _COST_TIP),
    ("Profit", "Divines you'd clear, after rounding."),
    ("Settle", _SETTLE_TIP),
    ("Seller", "Character to whisper."),
    ("Expires", "How long before this drops off the list."),
    ("", "Accept copies the whisper. Decline drops it for the rest of the session."),
]

AWAITING_COLUMNS = [
    ("Item", "What you asked for."),
    ("Buy", "How many you asked for."),
    ("Each", _EACH_TIP),
    ("Cost", _COST_TIP),
    ("Profit", "Divines you'd clear if they trade."),
    ("Settle", _SETTLE_TIP),
    ("Seller", "Who you whispered."),
    ("Sent", "How long ago you copied the whisper."),
    ("Auto", "Marks itself as no reply when this runs out."),
    (
        "",
        "Copy again puts the same whisper back on the clipboard. Adjust "
        "corrects the quantity to what you actually bought.",
    ),
]

READY_TIMER_COLUMN = 8
READY_ACTION_COLUMN = 9
AWAITING_ELAPSED_COLUMN = 7
AWAITING_TIMER_COLUMN = 8
AWAITING_ACTION_COLUMN = 9

TRADE_ID = Qt.ItemDataRole.UserRole


class QueuePanel(QWidget):
    """Live offers and outstanding whispers, driven by a TradeQueue."""

    take_requested = Signal(str)              # trade id
    outcome_reported = Signal(str, object)    # (trade id, Outcome)
    dismiss_requested = Signal(str)           # trade id
    recopy_requested = Signal(str)            # trade id, already whispered
    revise_requested = Signal(str, float)     # (trade id, units actually traded)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.headline = QLabel()
        font = self.headline.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        self.headline.setFont(font)
        self.headline.setWordWrap(True)
        layout.addWidget(self.headline)

        self.hint = QLabel()
        self.hint.setStyleSheet(f"color: {muted_color(self)};")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        # Bankroll belongs with the trades it constrains, not on the browsing
        # tab: it decides the Buy quantity on every row shown below it.
        self.bankroll = BankrollBar()
        layout.addWidget(self.bankroll)

        # Draggable, like Quick Lookup below it. How the two sections should be
        # divided depends entirely on which half of the loop you're in — early
        # in a session everything is Ready, late in one everything is awaiting a
        # reply — and that is not a split the app can guess.
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setChildrenCollapsible(False)
        self.ready = _make_table(READY_COLUMNS)
        self.awaiting = _make_table(AWAITING_COLUMNS)
        self.split.addWidget(_section(self, "Ready to whisper", self.ready))
        self.split.addWidget(_section(self, "Waiting on a reply", self.awaiting))
        self.split.setSizes([300, 300])
        layout.addWidget(self.split, stretch=1)

        self._icons = None
        self._hotkey_hint = ""
        # The queue as last drawn, so an in-row button can look its own trade up.
        self._queue = None
        # Row identity as last drawn, so a redraw can tell "same trades, new
        # countdown" from "the list actually changed".
        self._ready_ids: list[str] = []
        self._awaiting_ids: list[str] = []
        self.refresh(None)

    # --- wiring ------------------------------------------------------------

    def set_icons(self, provider) -> None:
        self._icons = provider

    def set_hotkey_hint(self, binding: str) -> None:
        from .hotkey import format_hotkey

        self._hotkey_hint = format_hotkey(binding) if binding else ""

    # --- rendering ---------------------------------------------------------

    def refresh(self, queue, now=None) -> None:
        self._queue = queue
        if queue is None:
            self.ready.setRowCount(0)
            self.awaiting.setRowCount(0)
            self._ready_ids = []
            self._awaiting_ids = []
            self.headline.setText("No trades yet")
            self.hint.setText(
                "Switch on Find trades in the toolbar. Anything worth acting on will "
                "appear here one at a time."
            )
            return

        now = now or datetime.now(timezone.utc)
        self._sync_ready(queue.available, now)
        self._sync_awaiting(queue.awaiting, now)
        self.ready._column_layout.size_to_contents()
        self.awaiting._column_layout.size_to_contents()
        self._update_headline(queue, now)

    def _update_headline(self, queue, now) -> None:
        offered = queue.offered
        if offered is not None:
            left = offered.seconds_left(now) or 0
            c = offered.candidate
            self.headline.setText(
                f"{fmt_qty(c.plan.units)} × {c.item_name} for "
                f"{fmt_amount(c.pay_total, c.listing.pay_currency)} "
                f"→ +{c.profit_divines:.2f} div     ({_countdown(left)})"
            )
            self.hint.setText(
                f"Press {self._hotkey_hint} to copy it, or click Accept below."
                if self._hotkey_hint
                else "Click Accept to copy the whisper."
            )
            return
        ready = len(queue.available)
        waiting = len(queue.awaiting)
        bits = []
        if ready:
            bits.append(f"{ready} trade{'s' if ready != 1 else ''} ready")
        if waiting:
            bits.append(f"{waiting} waiting on a reply")
        self.headline.setText("  ·  ".join(bits) if bits else "Nothing to do")
        self.hint.setText(
            "Anything left unanswered marks itself as no reply."
            if waiting
            else "Find trades keeps looking while it's switched on."
        )

    # --- ready section -----------------------------------------------------

    def _sync_ready(self, trades, now) -> None:
        ids = [t.id for t in trades]
        if ids != self._ready_ids:
            self._rebuild_ready(trades)
            self._ready_ids = ids
        for row, t in enumerate(trades):
            live = t.state is QueueState.OFFERED
            marker = self.ready.item(row, 0)
            if marker is not None:
                marker.setText("●" if live else "")
            left = t.seconds_left(now)
            item = self.ready.item(row, READY_TIMER_COLUMN)
            if item is not None:
                item.setText(_countdown(left))

    def _rebuild_ready(self, trades) -> None:
        _clear_widgets(self.ready, READY_ACTION_COLUMN)
        self.ready.setRowCount(len(trades))
        for row, t in enumerate(trades):
            c = t.candidate
            marker = TextItem("")
            marker.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setToolTip("Live offer — the hotkey copies this one.")
            marker.setData(TRADE_ID, t.id)
            self.ready.setItem(row, 0, marker)

            self.ready.setItem(row, 1, self._name_cell(c))
            self._set_money(self.ready, row, c, first=2)
            self.ready.setItem(row, 7, TextItem(_seller(c)))
            self.ready.setItem(row, READY_TIMER_COLUMN, TextItem(""))
            actions = _actions(
                [
                    ("Accept", "Copy the whisper and move this to 'waiting on a reply'.",
                     lambda tid=t.id: self.take_requested.emit(tid)),
                    ("Decline", "Drop this trade. It won't be offered again this session.",
                     lambda tid=t.id: self.dismiss_requested.emit(tid)),
                ]
            )
            self.ready.setCellWidget(row, READY_ACTION_COLUMN, actions)
            self.ready.watch(actions, row)

    # --- awaiting section --------------------------------------------------

    def _sync_awaiting(self, trades, now) -> None:
        ids = [t.id for t in trades]
        if ids != self._awaiting_ids:
            self._rebuild_awaiting(trades)
            self._awaiting_ids = ids
        for row, t in enumerate(trades):
            since = (now - t.taken_at).total_seconds() if t.taken_at else 0.0
            elapsed = self.awaiting.item(row, AWAITING_ELAPSED_COLUMN)
            if elapsed is not None:
                elapsed.setText(_elapsed(since))
            timer = self.awaiting.item(row, AWAITING_TIMER_COLUMN)
            if timer is not None:
                timer.setText(_countdown(t.seconds_left(now)))

    def _rebuild_awaiting(self, trades) -> None:
        _clear_widgets(self.awaiting, AWAITING_ACTION_COLUMN)
        self.awaiting.setRowCount(len(trades))
        for row, t in enumerate(trades):
            c = t.candidate
            name = self._name_cell(c)
            name.setData(TRADE_ID, t.id)
            self.awaiting.setItem(row, 0, name)
            self._set_money(self.awaiting, row, c, first=1)
            self.awaiting.setItem(row, 6, TextItem(_seller(c)))
            self.awaiting.setItem(row, AWAITING_ELAPSED_COLUMN, TextItem(""))
            self.awaiting.setItem(row, AWAITING_TIMER_COLUMN, TextItem(""))
            actions = _actions(
                [
                    # First, because it is the one with a deadline: a seller who
                    # answers wants the offer repeated, and retyping it by hand
                    # is how a trade gets lost.
                    ("Copy again", "Put this whisper back on the clipboard, unchanged.",
                     lambda tid=t.id: self.recopy_requested.emit(tid)),
                    # Before the verdict buttons, because it has to be used
                    # first: marking a trade as Traded resolves it, and the
                    # quantity has to be right before that is written down.
                    ("Adjust…",
                     "They had fewer than they listed, or you could only afford part "
                     "of it — correct the quantity before recording the trade.",
                     lambda tid=t.id: self._ask_quantity(tid)),
                    ("Traded", "The trade went through.",
                     lambda tid=t.id: self.outcome_reported.emit(tid, Outcome.FILLED)),
                    ("No reply", "They never answered.",
                     lambda tid=t.id: self.outcome_reported.emit(tid, Outcome.NO_REPLY)),
                    ("Already sold", "They replied to say it's gone.",
                     lambda tid=t.id: self.outcome_reported.emit(tid, Outcome.SOLD)),
                ]
            )
            self.awaiting.setCellWidget(row, AWAITING_ACTION_COLUMN, actions)
            self.awaiting.watch(actions, row)

    # --- corrections -------------------------------------------------------

    def _ask_quantity(self, trade_id: str) -> None:
        """Open the correction dialog for one whispered trade."""
        trade = self._queue.get(trade_id) if self._queue is not None else None
        if trade is None:
            return
        units = QuantityDialog.ask(self, trade.candidate)
        if units is not None:
            self.revise_requested.emit(trade_id, units)

    # --- shared cells ------------------------------------------------------

    def _name_cell(self, candidate) -> TextItem:
        name = TextItem(candidate.item_name)
        if self._icons is not None:
            icon = self._icons.icon(candidate.listing.item_id)
            if icon is not None:
                name.setIcon(icon)
        if candidate.band is Band.THIN:
            name.setToolTip(
                "The discount is inside the Exchange price's own margin of "
                "error, so the profit figure is uncertain."
            )
        return name

    @staticmethod
    def _set_money(table: QTableWidget, row: int, c, *, first: int) -> None:
        """Buy / Each / Cost / Profit / Settle, in that order from `first`.

        One writer for both tables. They showed the same five facts in two
        vocabularies once already; the columns only stay in step if there is a
        single place that fills them.
        """
        pay = c.listing.pay_currency
        table.setItem(row, first, NumericItem(fmt_qty(c.plan.units), c.plan.units))
        each = NumericItem(fmt_amount(c.pay_per_unit, pay), c.pay_per_unit)
        each.setToolTip(_EACH_TIP)
        table.setItem(row, first + 1, each)
        cost = NumericItem(fmt_amount(c.pay_total, pay), c.pay_total)
        cost.setToolTip(
            f"{_COST_TIP}\n\nThat's {c.plan.cost_divines:.2f} divines' worth."
        )
        table.setItem(row, first + 2, cost)
        table.setItem(
            row, first + 3, NumericItem(f"+{c.profit_divines:.2f}", c.profit_divines)
        )
        settle = TextItem(currency_label(c.settle_currency))
        settle.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        settle.setToolTip(_SETTLE_TIP)
        table.setItem(row, first + 4, settle)

    # --- helpers used by tests ---------------------------------------------

    def row_id(self, table: QTableWidget, row: int) -> str | None:
        item = table.item(row, 0)
        return item.data(TRADE_ID) if item is not None else None

    def click_action(self, table: QTableWidget, row: int, label: str) -> bool:
        """Press an in-row button by its label. Returns False if it isn't there."""
        column = (
            READY_ACTION_COLUMN if table is self.ready else AWAITING_ACTION_COLUMN
        )
        widget = table.cellWidget(row, column)
        if widget is None:
            return False
        for btn in widget.findChildren(QPushButton):
            if btn.text() == label:
                btn.click()
                return True
        return False


class QuantityDialog(QDialog):
    """Correct a whispered trade to the quantity that was actually available.

    Two things happened in the second field test that the app had no way to
    record: a whisper for 18 Faded Crisis Fragments where only 3 were
    affordable at the time, and a seller advertising 2 Omens of Whittling who
    turned out to hold 1. Both were logged at the quantity asked for, so the
    outcome log carried a cost and a profit that never happened.

    The quantity steps in whole lots rather than single items, because the price
    only divides that finely — see `listings.smallest_lot` — and it cannot go
    above the original ask, which was capped by the seller's own stock.
    """

    def __init__(self, parent, candidate):
        super().__init__(parent)
        from ..listings import replan_units

        self._candidate = candidate
        self._replan = replan_units
        self.setWindowTitle("Adjust the quantity")

        layout = QVBoxLayout(self)
        blurb = QLabel(
            f"How many {candidate.item_name} did you actually get from "
            f"{_seller(candidate)}?"
        )
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        form = QFormLayout()
        step = candidate.plan.get_per_lot or 1.0
        self.units = QDoubleSpinBox()
        self.units.setDecimals(0 if float(step).is_integer() else 2)
        self.units.setRange(step, candidate.plan.units)
        self.units.setSingleStep(step)
        self.units.setValue(candidate.plan.units)
        self.units.setToolTip(
            "Steps in whole lots, because the seller's price only divides that "
            "far — part of a lot would cost part of an orb, which cannot be "
            "traded."
        )
        self.units.valueChanged.connect(lambda _: self._preview())
        form.addRow("Quantity", self.units)
        layout.addLayout(form)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(f"color: {muted_color(self)};")
        layout.addWidget(self.summary)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._preview()

    def _preview(self) -> None:
        """Say what the correction does to the cost and the profit."""
        revised = self._replan(self._candidate, self.units.value())
        pay = revised.listing.pay_currency
        self.summary.setText(
            f"{fmt_qty(revised.plan.units)} for "
            f"{fmt_amount(revised.pay_total, pay)}  ·  "
            f"profit +{revised.profit_divines:.2f} div"
        )

    def chosen_units(self) -> float:
        return self.units.value()

    @staticmethod
    def ask(parent, candidate) -> float | None:
        """Run the dialog. Returns the new quantity, or None if cancelled."""
        dlg = QuantityDialog(parent, candidate)
        if not dlg.exec():
            return None
        return dlg.chosen_units()


def _seller(candidate) -> str:
    return candidate.listing.character or candidate.listing.account


def _clear_widgets(table: QTableWidget, column: int) -> None:
    """Drop the action widgets before a rebuild.

    `setRowCount` does not reliably reap cell widgets, and a survivor stays
    parented to the viewport at its *old* geometry — which, once the columns
    resize, paints a live pair of buttons on top of a different row. Seen
    exactly that way: an Accept/Decline landing over the Item column.

    `removeCellWidget` alone is not enough: it only schedules deletion, and the
    orphan keeps painting until the event loop gets round to it. Unparenting is
    what actually takes it off screen this frame.
    """
    # The highlighted row index describes the old row set, and the rebuild is
    # what changed it. Cleared here rather than left to drift onto whichever
    # trade inherits the index; the fresh widget under the cursor re-reports it.
    table.set_hover_row(-1)
    for row in range(table.rowCount()):
        widget = table.cellWidget(row, column)
        if widget is None:
            continue
        table.removeCellWidget(row, column)
        widget.setParent(None)
        widget.deleteLater()


def _actions(specs) -> QWidget:
    """A row of small buttons that act on their own row in one click."""
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(2, 0, 2, 0)
    layout.setSpacing(4)
    for label, tip, slot in specs:
        btn = QPushButton(label)
        btn.setToolTip(tip)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # don't steal focus mid-map
        btn.clicked.connect(lambda _=False, s=slot: s())
        layout.addWidget(btn)
    layout.addStretch(1)
    return holder


def _section(widget: QWidget, text: str, table: QTableWidget) -> QWidget:
    """A titled table, as one splitter pane so the label travels with it."""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    layout.addWidget(label)
    layout.addWidget(table, stretch=1)
    return page


def _make_table(columns) -> RowHoverTable:
    table = RowHoverTable(len(columns))
    table.setHorizontalHeaderLabels([c[0] for c in columns])
    for i, (_, tip) in enumerate(columns):
        table.horizontalHeaderItem(i).setToolTip(tip)
    # No selection at all: every action is a button in its own row, so a
    # highlighted row would only suggest a second step that doesn't exist. The
    # row still lights up on hover — see RowHoverTable — which is feedback about
    # what a click would act on rather than a state the user has to clear.
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    # Deliberately not sortable: the order is presentation order — oldest first
    # in Ready, newest first in Waiting — and a click that reordered it would
    # move rows out from under the cursor mid-click. Reordering and resizing the
    # *columns* is a different thing entirely, and is allowed — see
    # `flexible_columns`. Item no longer takes the whole slack on its own;
    # widening the window now grows every column.
    # The action column is exempt from the fit-to-window squeeze: its buttons
    # have a real width and are no use half cut off.
    flexible_columns(table, protected=(len(columns) - 1,))
    # Long item names elide rather than wrapping onto a second line, so every
    # row is one line tall and the countdown columns stay aligned.
    table.setWordWrap(False)
    return table


def _countdown(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds >= 60:
        return f"{seconds / 60:.0f}m"
    return f"{seconds:.0f}s"


def _elapsed(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.0f}h ago"
    if seconds >= 60:
        return f"{seconds / 60:.0f}m ago"
    return "just now"
