"""The Opportunities tab: trades to act on, and trades waiting on an answer.

Two lists, because they ask the user for two different things:

- **Ready to whisper** — the live offer sits at the top with a countdown and the
  hotkey armed. Anything that lapsed stays below it until it expires. Both are
  takeable; the difference is only whether it's currently worth interrupting a
  map for.
- **Waiting on a reply** — everything already whispered, each self-marking as
  "no reply" when its timer runs out.

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
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..listings import Band
from ..outcomes import Outcome
from ..trade_queue import QueueState
from .bankroll_bar import BankrollBar
from .table_items import NumericItem, TextItem
from .theme import muted_color

log = logging.getLogger(__name__)

READY_COLUMNS = [
    ("", "A dot marks the live offer — the one the hotkey will copy."),
    ("Item", "What you'd be buying."),
    ("Buy", "How many to ask for."),
    ("Cost", "Divines you'd spend."),
    ("Profit", "Divines you'd clear, after rounding."),
    ("Seller", "Character to whisper."),
    ("Expires", "How long before this drops off the list."),
    ("", "Accept copies the whisper. Decline drops it."),
]

AWAITING_COLUMNS = [
    ("Item", "What you asked for."),
    ("Buy", "How many you asked for."),
    ("Cost", "Divines offered."),
    ("Profit", "Divines you'd clear if they trade."),
    ("Seller", "Who you whispered."),
    ("Sent", "How long ago you copied the whisper."),
    ("Auto", "Marks itself as no reply when this runs out."),
    ("", "One click records what happened."),
]

READY_TIMER_COLUMN = 6
READY_ACTION_COLUMN = 7
AWAITING_ELAPSED_COLUMN = 5
AWAITING_TIMER_COLUMN = 6
AWAITING_ACTION_COLUMN = 7

TRADE_ID = Qt.ItemDataRole.UserRole


class QueuePanel(QWidget):
    """Live offers and outstanding whispers, driven by a TradeQueue."""

    take_requested = Signal(str)              # trade id
    outcome_reported = Signal(str, object)    # (trade id, Outcome)
    dismiss_requested = Signal(str)           # trade id

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

        layout.addWidget(_section_label(self, "Ready to whisper"))
        self.ready = _make_table(READY_COLUMNS)
        layout.addWidget(self.ready, stretch=1)

        layout.addWidget(_section_label(self, "Waiting on a reply"))
        self.awaiting = _make_table(AWAITING_COLUMNS)
        layout.addWidget(self.awaiting, stretch=1)

        self._icons = None
        self._hotkey_hint = ""
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
        self._update_headline(queue, now)

    def _update_headline(self, queue, now) -> None:
        offered = queue.offered
        if offered is not None:
            left = offered.seconds_left(now) or 0
            c = offered.candidate
            self.headline.setText(
                f"{c.plan.units:g} × {c.item_name} for {c.plan.cost_divines:.1f} div "
                f"→ +{c.profit_divines:.2f} div     ({left:.0f}s)"
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

            name = TextItem(c.item_name)
            if self._icons is not None:
                icon = self._icons.icon(c.listing.item_id)
                if icon is not None:
                    name.setIcon(icon)
            if c.band is Band.THIN:
                name.setToolTip(
                    "The discount is inside the Exchange price's own margin of "
                    "error, so the profit figure is uncertain."
                )
            self.ready.setItem(row, 1, name)
            self.ready.setItem(row, 2, NumericItem(f"{c.plan.units:g}", c.plan.units))
            self.ready.setItem(
                row, 3, NumericItem(f"{c.plan.cost_divines:.1f}", c.plan.cost_divines)
            )
            self.ready.setItem(
                row, 4, NumericItem(f"+{c.profit_divines:.2f}", c.profit_divines)
            )
            self.ready.setItem(
                row, 5, TextItem(c.listing.character or c.listing.account)
            )
            self.ready.setItem(row, READY_TIMER_COLUMN, TextItem(""))
            self.ready.setCellWidget(
                row,
                READY_ACTION_COLUMN,
                _actions(
                    [
                        ("Accept", "Copy the whisper and move this to 'waiting on a reply'.",
                         lambda tid=t.id: self.take_requested.emit(tid)),
                        ("Decline", "Drop this trade without whispering anyone.",
                         lambda tid=t.id: self.dismiss_requested.emit(tid)),
                    ]
                ),
            )

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
            name = TextItem(c.item_name)
            name.setData(TRADE_ID, t.id)
            if self._icons is not None:
                icon = self._icons.icon(c.listing.item_id)
                if icon is not None:
                    name.setIcon(icon)
            self.awaiting.setItem(row, 0, name)
            self.awaiting.setItem(row, 1, NumericItem(f"{c.plan.units:g}", c.plan.units))
            self.awaiting.setItem(
                row, 2, NumericItem(f"{c.plan.cost_divines:.1f}", c.plan.cost_divines)
            )
            self.awaiting.setItem(
                row, 3, NumericItem(f"+{c.profit_divines:.2f}", c.profit_divines)
            )
            self.awaiting.setItem(
                row, 4, TextItem(c.listing.character or c.listing.account)
            )
            self.awaiting.setItem(row, AWAITING_ELAPSED_COLUMN, TextItem(""))
            self.awaiting.setItem(row, AWAITING_TIMER_COLUMN, TextItem(""))
            self.awaiting.setCellWidget(
                row,
                AWAITING_ACTION_COLUMN,
                _actions(
                    [
                        ("Traded", "The trade went through.",
                         lambda tid=t.id: self.outcome_reported.emit(tid, Outcome.FILLED)),
                        ("No reply", "They never answered.",
                         lambda tid=t.id: self.outcome_reported.emit(tid, Outcome.NO_REPLY)),
                        ("Already sold", "They replied to say it's gone.",
                         lambda tid=t.id: self.outcome_reported.emit(tid, Outcome.SOLD)),
                    ]
                ),
            )

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


def _section_label(widget: QWidget, text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


def _make_table(columns) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels([c[0] for c in columns])
    for i, (_, tip) in enumerate(columns):
        table.horizontalHeaderItem(i).setToolTip(tip)
    # No selection at all: every action is a button in its own row, so a
    # highlighted row would only suggest a second step that doesn't exist.
    table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    # Deliberately not sortable: the order is the queue's ranking, and a click
    # that reordered it would move the live offer away from the top.
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    seller = next(i for i, (title, _) in enumerate(columns) if title == "Seller")
    header.setSectionResizeMode(seller, QHeaderView.ResizeMode.Stretch)
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
