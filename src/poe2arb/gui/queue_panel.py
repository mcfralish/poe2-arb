"""The Opportunities tab: trades to act on, and trades waiting on an answer.

Two lists, because they ask the user for two different things:

- **Ready to whisper** — everything found and not yet dealt with, **best
  first**, so row 1 is the trade the hotkey will take and row 2 is the one
  after it. ● marks it.
- **Waiting on a reply** — everything already whispered, **newest first**, each
  self-marking as Expired when its timer runs out, unless it has been pinned.

Ready was drawn oldest-first until 0.9.0, so that nothing already on screen
moved. That rule assumed a user glancing at the table mid-map; the first real
play session on 0.8.0 measured otherwise, and the maintainer shrinks this pane
to a handful of rows to give the room to *Waiting on a reply* — at which point
an order that is not the hotkey's order means the visible rows are not the ones
the key acts on. The old rule's cost is now this one's: a better candidate
arriving moves the rows below it. Two mitigations, both here rather than in the
queue: **the order is held while the pointer is over the table**, and ● marks
the trade the hotkey will take rather than the top row, so it stays truthful
while the order is held.

Waiting is read when a reply arrives, and a reply is almost always to the
whisper just sent. Pinned rows are the exception and sort above everything: a
row is pinned *because* a seller answered, so it is the trade in progress
rather than one of a dozen outstanding messages.

**Money is shown in the currency the seller asked for**, not in divines. A
listing whispered as "2412 exalted" displayed as "5.6 div" is unrecognisable as
the offer that was made — which matters most when a reply lands an hour later in
a language the user doesn't read. Profit stays in divines, because that is the
only unit the two sides of the trade can be compared in.

**Every action is one click on the row itself.** No select-then-press: the
buttons live in the row they act on, and a two-step interaction is one step too
many at the rate this queue fills. That constrains the refresh — the tables
redraw once a second for the countdowns, and rebuilding a row would destroy the
button under the user's cursor mid-click. So `refresh` rebuilds only when the
*set* of trades changes and otherwise writes into the cells already there.

**Amount, Price per and Total are edited in the row** on *Waiting on a reply*,
which is the same constraint one notch tighter: a rebuild would destroy an open
editor, so one is held off while a spin box has focus. See `_MoneyEditors`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..format import currency_label, fmt_amount, fmt_profit, fmt_qty
from ..listings import Band, replan_units
from ..outcomes import TIPS, Outcome, label_for
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
_AUTO_TIP = (
    "Marks itself Expired when this runs out — which only means nobody said "
    "what happened, not that the seller stayed silent. Pin the row if they've "
    "answered and it will stop counting down."
)
# A pinned row is state, not risk, so it must not borrow the band colours.
_PIN_COLOUR = "#f0b429"

# Amount / Price per / Total, not Buy / Each / Cost. Renamed 2026-08-01 after
# the old headers were misread by their own author: "Buy 5 · Each 1 div · Cost
# 5 div" read back as "I bought 1 for 5 div", and a losing trade got explained
# as a bug in the profit column. Both tables here and the Results tab use the
# same three words.
_EDIT_TIP = (
    "\n\nType or use the arrows to correct it to what actually happened. The "
    "three move together: one of them changing re-derives the others, and the "
    "original ask is kept in the log either way."
)

READY_COLUMNS = [
    ("", "A dot marks the trade the hotkey will copy — normally the top row."),
    ("Item", "What you'd be buying."),
    ("Amount", "How many to ask for."),
    ("Price per", _EACH_TIP),
    ("Total", _COST_TIP),
    ("Profit", "Divines you'd clear, after rounding."),
    ("Settle", _SETTLE_TIP),
    ("Seller", "Character to whisper."),
    ("Expires", "How long before this drops off the list."),
    ("", "Accept copies the whisper. Decline drops it for the rest of the session."),
]

AWAITING_COLUMNS = [
    ("Item", "What you asked for."),
    ("Amount", "How many you asked for." + _EDIT_TIP),
    ("Price per", _EACH_TIP + _EDIT_TIP),
    ("Total", _COST_TIP + _EDIT_TIP),
    ("Profit", "Divines you'd clear if they trade."),
    ("Settle", _SETTLE_TIP),
    ("Seller", "Who you whispered."),
    ("Sent", "How long ago you copied the whisper."),
    ("Auto", _AUTO_TIP),
    (
        "",
        "Pin holds a row that's been answered off the clock, and Copy Again "
        "puts the same whisper back on the clipboard. The rest record what "
        "came of it.",
    ),
]

READY_TIMER_COLUMN = 8
READY_ACTION_COLUMN = 9
# The three cells that are editable in place, in the order they are drawn.
AWAITING_UNITS_COLUMN = 1
AWAITING_PER_COLUMN = 2
AWAITING_TOTAL_COLUMN = 3
AWAITING_ELAPSED_COLUMN = 7
AWAITING_TIMER_COLUMN = 8
AWAITING_ACTION_COLUMN = 9

TRADE_ID = Qt.ItemDataRole.UserRole


class QueuePanel(QWidget):
    """Takeable trades and outstanding whispers, driven by a TradeQueue."""

    take_requested = Signal(str)              # trade id
    outcome_reported = Signal(str, object)    # (trade id, Outcome)
    dismiss_requested = Signal(str)           # trade id
    recopy_requested = Signal(str)            # trade id, already whispered
    # (trade id, units actually traded, total actually paid in the seller's
    # currency). Both travel together because `TradeQueue.revise` re-applies
    # them to the original ask, so sending only the one that moved would let
    # the other snap back to what was whispered — the same lie in the log that
    # this exists to stop.
    revise_requested = Signal(str, float, float)
    pin_requested = Signal(str, bool)         # (trade id, hold it off the clock)

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
        # countdown" from "the list actually changed". For Ready it is also the
        # order actually on screen, which is what a held reshuffle restores.
        self._ready_ids: list[str] = []
        # The money each Ready row was last drawn with. A bankroll change
        # re-sizes rows in place, which moves four cells without changing a
        # single id — so identity alone would leave the old quantity on screen.
        self._ready_money: list[tuple] = []
        # Identity *and* pin state: pinning changes the row's highlight, its
        # button and its countdown cell, so it has to force a rebuild the same
        # way an arriving trade does.
        self._awaiting_ids: list[tuple[str, bool]] = []
        # One set of spin boxes per whispered row, by trade id.
        self._editors: dict[str, _MoneyEditors] = {}
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
            self._ready_money = []
            self._awaiting_ids = []
            self._editors.clear()
            self.headline.setText("No trades yet")
            self.hint.setText(
                "Switch on Find trades in the toolbar. Anything worth acting on "
                "lands here as it's found, best first."
            )
            return

        now = now or datetime.now(timezone.utc)
        self._sync_ready(self._ready_order(queue.available), queue.next_up, now)
        self._sync_awaiting(queue.awaiting, now)
        self.ready._column_layout.size_to_contents()
        self.awaiting._column_layout.size_to_contents()
        self._update_headline(queue, now)

    def _ready_order(self, trades: list) -> list:
        """Rank order — held still while the pointer is over the table.

        The reshuffle is the price of ranking this list, and it is only ever a
        problem under the cursor: a row that moves between the glance and the
        click is a row clicked by mistake. So while the pointer is in the
        table, rows already on screen keep their positions and anything new
        goes to the bottom; the real order snaps back within a second of the
        pointer leaving. ● keeps marking the hotkey's trade throughout, so the
        held order never lies about what the key will do.
        """
        # `hover_row` is the row under the pointer and is deliberately cleared
        # by a rebuild, which would otherwise leave the highlight on whichever
        # trade inherited the index — so the pointer's own position is asked
        # for as well, or one held rebuild would release every later one.
        if not (self.ready.hover_row >= 0 or self.ready.underMouse()):
            return trades
        if not self._ready_ids:
            return trades
        by_id = {t.id: t for t in trades}
        held = [by_id.pop(i) for i in self._ready_ids if i in by_id]
        return held + [t for t in trades if t.id in by_id]

    def _update_headline(self, queue, now) -> None:
        ready = len(queue.available)
        waiting = len(queue.awaiting)
        bits = []
        if ready:
            bits.append(f"{ready} trade{'s' if ready != 1 else ''} ready")
        if waiting:
            bits.append(f"{waiting} waiting on a reply")
        self.headline.setText("  ·  ".join(bits) if bits else "Nothing to do")
        if ready:
            self.hint.setText(
                f"Press {self._hotkey_hint} to copy the one marked ●, or click "
                "Accept on any row."
                if self._hotkey_hint
                else "Click Accept on any row to copy its whisper."
            )
        elif waiting:
            self.hint.setText(
                "Anything left unanswered marks itself as Expired. Pin a row "
                "once the seller replies and it stops counting down."
            )
        else:
            self.hint.setText("Find trades keeps looking while it's switched on.")

    # --- ready section -----------------------------------------------------

    def _sync_ready(self, trades, next_up, now) -> None:
        ids = [t.id for t in trades]
        money = [_money_shape(t) for t in trades]
        if ids != self._ready_ids or money != self._ready_money:
            self._rebuild_ready(trades)
            self._ready_ids = ids
            self._ready_money = money
        for row, t in enumerate(trades):
            # A position rather than a state, since 0.9.0: it marks whichever
            # row the hotkey would take, which is row 1 except while a
            # reshuffle is being held for the cursor.
            marker = self.ready.item(row, 0)
            if marker is not None:
                marker.setText("●" if next_up is not None and t.id == next_up.id else "")
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
            marker.setToolTip("The hotkey copies this one.")
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
        ids = [(t.id, t.pinned) for t in trades]
        if ids != self._awaiting_ids:
            # A rebuild destroys the spin box being typed into, so a row
            # arriving or expiring waits until the edit is finished. Held, not
            # dropped: the next tick is a second away and the countdown cells
            # below still describe the rows actually on screen.
            if self._editing():
                return
            self._rebuild_awaiting(trades)
            self._awaiting_ids = ids
        for row, t in enumerate(trades):
            # `show` reports whether the trade's numbers moved, so a correction
            # redraws Profit and the cells under the editors while an untouched
            # row costs nothing on a once-a-second redraw.
            editors = self._editors.get(t.id)
            if editors is not None and editors.show(t.candidate):
                self._set_money(self.awaiting, row, t.candidate, first=1)
                if t.pinned:
                    self._mark_pinned(row)
            since = (now - t.taken_at).total_seconds() if t.taken_at else 0.0
            elapsed = self.awaiting.item(row, AWAITING_ELAPSED_COLUMN)
            if elapsed is not None:
                elapsed.setText(_elapsed(since))
            timer = self.awaiting.item(row, AWAITING_TIMER_COLUMN)
            if timer is not None:
                # `seconds_left` already returns None for a pinned row, so this
                # shows the em-dash without a second test for it here.
                timer.setText("held" if t.pinned else _countdown(t.seconds_left(now)))

    def _editing(self) -> bool:
        """Is one of the in-row spin boxes mid-edit right now?"""
        return any(e.busy for e in self._editors.values())

    def _rebuild_awaiting(self, trades) -> None:
        _clear_widgets(self.awaiting, AWAITING_ACTION_COLUMN)
        for column in (
            AWAITING_UNITS_COLUMN, AWAITING_PER_COLUMN, AWAITING_TOTAL_COLUMN
        ):
            _clear_widgets(self.awaiting, column)
        self._editors.clear()
        self.awaiting.setRowCount(len(trades))
        for row, t in enumerate(trades):
            c = t.candidate
            name = self._name_cell(c)
            name.setData(TRADE_ID, t.id)
            self.awaiting.setItem(row, 0, name)
            self._set_money(self.awaiting, row, c, first=1)
            editors = _MoneyEditors(t, self._revise_from_row)
            editors.attach(self.awaiting, row)
            self._editors[t.id] = editors
            self.awaiting.setItem(row, 6, TextItem(_seller(c)))
            self.awaiting.setItem(row, AWAITING_ELAPSED_COLUMN, TextItem(""))
            self.awaiting.setItem(row, AWAITING_TIMER_COLUMN, TextItem(""))
            if t.pinned:
                self._mark_pinned(row)
            actions = _actions(
                [
                    # First, because it is what a reply calls for and it is the
                    # one action that has to happen *before* the timer would
                    # otherwise fire.
                    ("Unpin" if t.pinned else "Pin",
                     "Let this row start counting down again."
                     if t.pinned
                     else "They've answered — hold this row off the clock so the "
                          "timer can't write it down as unanswered mid-trade.",
                     lambda tid=t.id, on=not t.pinned: self.pin_requested.emit(tid, on)),
                    # A seller who answers wants the offer repeated, and
                    # retyping it by hand is how a trade gets lost.
                    ("Copy Again", "Put this whisper back on the clipboard, unchanged.",
                     lambda tid=t.id: self.recopy_requested.emit(tid)),
                    # Three verdicts, not five. AFK and Offline were separate
                    # buttons in 0.8.0 and were used properly for one session
                    # and then rejected: at this queue's rate, a three-way
                    # judgement costs more than the answer is worth, and the
                    # game's own log can tell the three apart afterwards. What
                    # is left is what the *user* knows — it traded, it was
                    # already gone, or nobody was there.
                    *(
                        (label_for(o), TIPS[o],
                         lambda tid=t.id, o=o: self.outcome_reported.emit(tid, o))
                        for o in (Outcome.FILLED, Outcome.UNAVAILABLE, Outcome.SOLD)
                    ),
                ]
            )
            self.awaiting.setCellWidget(row, AWAITING_ACTION_COLUMN, actions)
            self.awaiting.watch(actions, row)

    def _mark_pinned(self, row: int) -> None:
        """Tint a held row. Its own colour — this is state, not risk."""
        colour = QColor(_PIN_COLOUR)
        for column in range(self.awaiting.columnCount()):
            item = self.awaiting.item(row, column)
            if item is not None:
                item.setForeground(colour)

    # --- corrections -------------------------------------------------------

    def _revise_from_row(self, trade_id: str, units: float, pay_units: float) -> None:
        """One in-row edit, on its way to the outcome log as an amendment.

        Both numbers always travel, because `TradeQueue.revise` re-applies them
        to the original ask — sending only the one that moved would let the
        other quietly snap back to what was whispered.
        """
        self.revise_requested.emit(trade_id, units, pay_units)

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
        # Signed, because an amended trade is allowed to have lost money.
        table.setItem(
            row, first + 3,
            NumericItem(fmt_profit(c.profit_divines), c.profit_divines),
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
        """Press an in-row button by name. Returns False if it isn't there.

        Matches the `action` property rather than the button text, because the
        text is a glyph — see `GLYPHS`.
        """
        column = (
            READY_ACTION_COLUMN if table is self.ready else AWAITING_ACTION_COLUMN
        )
        widget = table.cellWidget(row, column)
        if widget is None:
            return False
        for btn in widget.findChildren(QPushButton):
            if btn.property("action") == label:
                btn.click()
                return True
        return False


class _MoneyEditors:
    """The three numbers on a whispered row, editable where they are shown.

    Three things happened in the field that the app had no way to record. Two
    are quantities: a whisper for 18 Faded Crisis Fragments where only 3 were
    affordable at the time, and a seller advertising 2 Omens of Whittling who
    turned out to hold 1. The third is a price — **1 fill in 36 was
    counteroffered** (2026-08-01, joined to `Client.txt`), and that one logged
    +38.00 divines on a trade that lost money, because a changed price had
    nowhere to go.

    0.8.0 answered all three with an *Adjust…* dialog. **Replaced 2026-08-02
    on maintainer feedback after using it**: at this queue's rate a dialog is
    two clicks and a context switch to change one number. The obstacle the
    dialog existed to dodge is real and is solved rather than avoided — the
    table rebuilds once a second for the countdowns, so `QueuePanel` holds a
    rebuild while one of these has focus, and a row's numbers are written into
    the boxes instead.

    The three stay consistent: **units × price per = total**, and moving any
    one of them re-derives the others.

    - *Amount* re-prices at the listing's own rate, which is what "they only
      had three" means and is nearly always the whole correction. It steps in
      whole lots, because the price only divides that finely (see
      `listings.smallest_lot`), and it cannot exceed the original ask, which
      was capped by the seller's own stock.
    - *Total* and *Price per* are the counteroffer, and have no such ceiling —
      a seller who counteroffers is usually asking for more. `Total` steps in
      whole units of the seller's currency, because partial currency cannot be
      traded, and `Price per` therefore steps by exactly one of those divided
      by the quantity.

    Every commit sends both numbers (see `TradeQueue.revise`) and is debounced,
    so holding an arrow down writes one amendment rather than one per click.
    """

    # Long enough that a run of arrow clicks is one correction, short enough
    # that letting go feels like it took effect.
    COMMIT_DELAY_MS = 500

    def __init__(self, trade, commit):
        self._trade_id = trade.id
        self._commit = commit
        asked = trade.asked or trade.candidate
        c = trade.candidate
        pay = c.listing.pay_currency
        self._syncing = False

        step = c.plan.get_per_lot or 1.0
        self.units = _spin(
            value=c.plan.units,
            low=step,
            high=max(asked.plan.units, c.plan.units),
            step=step,
            decimals=0 if float(step).is_integer() else 2,
            tip="How many you actually got. Steps in whole lots, because the "
                "seller's price only divides that far, and can't go above what "
                "you asked for.",
        )
        # The currency travels with the number, as it does everywhere else a
        # price is shown: two rows here can be priced in two currencies, and a
        # bare 36900 beside a bare 12.6 is unreadable. Money is never shown in
        # divines on this tab — see the module docstring.
        suffix = f" {currency_label(pay)}"
        # Whole units unless the listing was somehow priced in fractions:
        # partial currency cannot be traded, so a decimal place here would be
        # offering something that does not exist.
        self._whole = float(c.pay_total).is_integer()
        self.total = _spin(
            value=c.pay_total,
            low=1.0 if self._whole else 0.01,
            high=1e9,
            step=1.0,
            decimals=0 if self._whole else 2,
            suffix=suffix,
            tip=f"What you handed over, in {currency_label(pay)}. A seller who "
                "counteroffers changes this rather than the quantity.",
        )
        self.per = _spin(
            value=c.pay_per_unit,
            low=0.01,
            high=1e9,
            step=self._per_step(c.plan.units),
            decimals=2,
            suffix=suffix,
            tip=f"Price of one, in {currency_label(pay)}. Moves the total with "
                "it, and the other way round.",
        )
        self._timer = QTimer(self.units)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.COMMIT_DELAY_MS)
        self._timer.timeout.connect(self._send)

        self.units.valueChanged.connect(lambda _: self._changed("units"))
        self.per.valueChanged.connect(lambda _: self._changed("per"))
        self.total.valueChanged.connect(lambda _: self._changed("total"))
        for box in self._boxes:
            box.editingFinished.connect(self._send_now)
        # The ask, kept so a quantity change re-prices at the listing's rate
        # rather than at whatever the last correction happened to leave.
        self._asked = asked

    @property
    def _boxes(self) -> tuple[QDoubleSpinBox, ...]:
        return (self.units, self.per, self.total)

    @property
    def busy(self) -> bool:
        """Mid-edit: focused, or holding a change that hasn't been sent yet.

        Both halves are needed. Focus alone misses the pause between an arrow
        click and its debounced commit; a pending change alone misses someone
        who has clicked into the field and not typed yet.
        """
        return self._timer.isActive() or any(b.hasFocus() for b in self._boxes)

    def attach(self, table: QTableWidget, row: int) -> None:
        table.setCellWidget(row, AWAITING_UNITS_COLUMN, self.units)
        table.setCellWidget(row, AWAITING_PER_COLUMN, self.per)
        table.setCellWidget(row, AWAITING_TOTAL_COLUMN, self.total)
        for box in self._boxes:
            table.watch(box, row)

    def show(self, candidate) -> bool:
        """Write the trade's current numbers in. True if any of them moved.

        The row is redrawn once a second, so this is the common path and has
        to be cheap and silent — writing a value back fires `valueChanged`,
        which would otherwise commit the value it just displayed.
        """
        wanted = (candidate.plan.units, candidate.pay_per_unit, candidate.pay_total)
        if all(
            abs(box.value() - value) < 1e-9
            for box, value in zip(self._boxes, wanted)
        ):
            return False
        if self.busy:
            return False  # the user is mid-edit; theirs wins until they stop
        self._syncing = True
        try:
            self.units.setValue(wanted[0])
            self.per.setValue(wanted[1])
            self.total.setValue(wanted[2])
        finally:
            self._syncing = False
        return True

    # --- keeping the three honest about each other -------------------------

    def _per_step(self, units: float) -> float:
        """One whole unit of the seller's currency, spread over the quantity."""
        return 1.0 / units if units else 1.0

    def _changed(self, which: str) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            units = self.units.value()
            if which == "units":
                # At the listed rate: a smaller quantity costs what the seller
                # advertised for it, unless the user then says otherwise.
                self.total.setValue(replan_units(self._asked, units).pay_total)
                self.per.setSingleStep(self._per_step(units))
                self.per.setValue(self.total.value() / units if units else 0.0)
            elif which == "per":
                self.total.setValue(self._rounded(self.per.value() * units))
            else:
                self.per.setValue(self.total.value() / units if units else 0.0)
        finally:
            self._syncing = False
        self._timer.start()

    def _rounded(self, total: float) -> float:
        return round(total) if self._whole else total

    def _send_now(self) -> None:
        self._timer.stop()
        self._send()

    def _send(self) -> None:
        self._commit(self._trade_id, self.units.value(), self.total.value())


class _CellSpin(QDoubleSpinBox):
    """A spin box sized to the number in it, not to the widest one allowed.

    Qt sizes a spin box from its *range*, which is right for a form and wrong
    for a table cell: the ceiling on a counteroffer is nine figures, so every
    Total column came back 150px wide to hold a number that will never be
    typed — and the width had to come out of Seller and Sent, which then
    truncated. The floor `ColumnLayout` reads is this hint, so this is where
    the column width is really decided.
    """

    # Room for the arrows, the frame and a digit of growth.
    PADDING = 34

    def sizeHint(self):  # noqa: N802 (Qt naming)
        hint = super().sizeHint()
        hint.setWidth(
            self.fontMetrics().horizontalAdvance(self.text()) + self.PADDING
        )
        return hint

    def minimumSizeHint(self):  # noqa: N802 (Qt naming)
        return self.sizeHint()


def _spin(
    *,
    value: float,
    low: float,
    high: float,
    step: float,
    decimals: int,
    tip: str,
    suffix: str = "",
) -> QDoubleSpinBox:
    """One in-row number field. Its arrows are the whole point of it."""
    box = _CellSpin()
    box.setDecimals(decimals)
    box.setRange(low, high)
    box.setSingleStep(step)
    box.setSuffix(suffix)
    # Totals here run to five figures — 21,708 exalted is an ordinary listing.
    box.setGroupSeparatorShown(True)
    box.setValue(value)
    box.setToolTip(tip)
    box.setKeyboardTracking(False)  # commit on Enter or focus-out, not per digit
    box.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    box.setFrame(False)  # it is a table cell first and a control second
    return box


def _seller(candidate) -> str:
    return candidate.listing.character or candidate.listing.account


def _money_shape(trade) -> tuple:
    """Everything `_set_money` draws, so a redraw can tell whether it moved.

    A re-size from a bankroll change rewrites a row's quantity and price without
    touching its id, and `_sync_ready` only rebuilds when the row list changes —
    so this is what makes the corrected number reach the screen.
    """
    plan = trade.candidate.plan
    return (plan.units, plan.pay_units, plan.cost_divines, plan.profit_divines)


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


# One glyph per action, with the wording kept as the tooltip. Words were what
# shipped, and the row of them is why the action column could not shrink and why
# *Already sold* was clipped at narrow widths in the fourth field test — the
# awaiting row now carries seven actions, which as words is wider than the rest
# of the table put together. `click_action` still finds a button by its full
# name, so tests and screenshots read in words rather than in glyphs.
#
# **Dingbats, not emoji.** 👍 / 👎 / 📌 were what was asked for and they are the
# wrong bet for a shipped exe: they need a colour emoji font, and where one is
# missing every button reads as an identical empty box — verified by screenshot,
# which is also how the set below was checked to draw in a plain text font.
# Proper PoE2-styled icon assets are still the right answer and are still open.
GLYPHS = {
    "Accept": "✔",
    "Decline": "✖",
    # A raised flag for held, a lowered one for released.
    "Pin": "⚑",
    "Unpin": "⚐",
    "Copy Again": "❐",
    "Traded": "✔",
    # One button where 0.8.0 had AFK and Offline — see the awaiting row.
    "Not Available": "⊘",
    "Already Sold": "✕",
}

# Square enough for a glyph and no bigger.
_GLYPH_SIZE = 30


def _actions(specs) -> QWidget:
    """A row of small buttons that act on their own row in one click."""
    holder = QWidget()
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(2, 0, 2, 0)
    layout.setSpacing(2)
    for label, tip, slot in specs:
        glyph = GLYPHS.get(label)
        btn = QPushButton(glyph or label)
        # The name goes first in the tooltip: with no visible label it is the
        # only thing that says which action this is.
        btn.setToolTip(f"{label} — {tip}" if glyph else tip)
        # Read back by `click_action`, and by anything else that wants to find
        # an action by name now that the text on it is a picture.
        btn.setProperty("action", label)
        if glyph:
            btn.setFixedSize(_GLYPH_SIZE, _GLYPH_SIZE)
        # Never take focus: the row's spin boxes are the only thing here that
        # wants it, and a button stealing it mid-edit would commit the edit.
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
    # Deliberately not sortable: the order carries meaning the user cannot get
    # back by re-sorting — best first in Ready, so row 1 is the hotkey's row,
    # and newest first in Waiting — and a click that reordered it would move
    # rows out from under the cursor mid-click. Reordering and resizing the
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
