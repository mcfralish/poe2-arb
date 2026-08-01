"""Results tab: what your whispers actually earned.

This replaces the Trends tab, which charted the triangular scan history — a
search that was reading the wrong market and never produced a trade, so its
charts plotted a flat nothing.

The outcome log is the only record the app keeps that is worth accumulating.
Every whisper copied is written down with the gap it was taken at, the seller's
state, the listing's age and the profit expected; every verdict the user gives
resolves one. That is exactly the data needed to answer the question the
ranking is currently guessing at: **which discounts are worth the message?**

Nothing here claims a rate below `outcomes.MIN_SAMPLES` attempts. A fill rate
computed from three whispers is noise with a percent sign on it, and the whole
point of this tab is to replace guesses with measurements — so it says "not
enough data yet" until there genuinely is.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..outcomes import (
    MIN_SAMPLES,
    label_for,
    read_attempts,
    suggested_gap_band,
    summarise,
)
from .bands import legend_text, legend_tooltip, symbol_for_name, tip_for_name
from .table_items import NumericItem, TextItem
from .theme import muted_color

log = logging.getLogger(__name__)

# The first column is named per table — the same shape describes discounts,
# listing ages and seller states, and "" tells the reader none of that.
BUCKET_COLUMNS = [
    ("", "The group of attempts this row describes."),
    ("Whispers", "How many resolved attempts fell in this group."),
    ("Filled", "How many of them actually traded."),
    (
        "Fill rate",
        f"Filled as a share of whispers sent. Blank until there are "
        f"{MIN_SAMPLES} attempts — a rate from fewer is noise.",
    ),
    ("Earned", "Divines actually cleared by this group, in total."),
    (
        "Per whisper",
        "Divines earned divided by whispers sent. This is the number a ranking "
        "should maximise: a high fill rate on 0.3-divine trades is worth less "
        "than a low one on 5-divine trades.",
    ),
]

ATTEMPT_COLUMNS = [
    ("When", "When the whisper was copied."),
    ("Item", "What you asked for."),
    ("Buy", "How many."),
    ("Gap", "How far under Exchange value the listing was."),
    (
        "Odds",
        "How it was rated at the time — the same symbols as the Trades tab.\n"
        "●  worth trying      ○  uncertain      ×  too good to be true",
    ),
    ("Seller", "Who you whispered."),
    ("Result", "What you reported back."),
    ("Profit", "Expected, or actual once you reported a figure."),
]

# Verdict wording comes from `outcomes.label_for`, not from a copy here: this
# tab and the Trades tab had the same dict twice and it is exactly the drift
# CLAUDE.md warns about. It also has to keep naming `no_reply`, which the log
# still returns from before the verdict was split three ways.


class ResultsTab(QWidget):
    """Fill rates and takings, read straight off the outcome log."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = None
        self._attempts: list = []

        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Re-read the trade log from disk.")
        refresh.clicked.connect(self.reload)
        controls.addWidget(refresh)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.headline = QLabel()
        font = self.headline.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        self.headline.setFont(font)
        self.headline.setWordWrap(True)
        layout.addWidget(self.headline)

        self.tabs = QTabWidget()
        self.by_gap = _make_table(_buckets_named("Discount"))
        self.tabs.addTab(self.by_gap, "By discount")
        self.by_age = _make_table(_buckets_named("Listing age"))
        self.tabs.addTab(self.by_age, "By listing age")
        self.by_presence = _make_table(_buckets_named("Seller"))
        self.tabs.addTab(self.by_presence, "By seller state")
        # Trades before whispers: "what did I actually buy" is the question
        # asked most often, and answering it by opening Every whisper and
        # sorting on Result was two steps too many (asked for from the field
        # 2026-07-31). Same columns, same rows — just the ones that filled.
        self.trades = _make_table(ATTEMPT_COLUMNS, sort_column=0)
        self.tabs.addTab(self.trades, "Every trade")
        self.attempts = _make_table(ATTEMPT_COLUMNS, sort_column=0)
        self.tabs.addTab(self.attempts, "Every whisper")
        layout.addWidget(self.tabs)

        # The same key as the Trades tab, from the same source, so the glyphs
        # cannot drift apart again.
        self.legend = QLabel(legend_text())
        self.legend.setStyleSheet(f"color: {muted_color(self)};")
        self.legend.setWordWrap(True)
        self.legend.setToolTip(legend_tooltip())
        layout.addWidget(self.legend)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {muted_color(self)};")
        layout.addWidget(self.note)

        self._render()

    # --- input --------------------------------------------------------------

    def set_path(self, path) -> None:
        self._path = path
        self.reload()

    def reload(self) -> None:
        """Re-read the log. A missing or unreadable file is simply no data."""
        if self._path is None:
            return
        try:
            self._attempts = read_attempts(self._path)
        except OSError:
            log.warning("could not read the trade log at %s", self._path, exc_info=True)
            self._attempts = []
        self._render()

    # --- rendering ----------------------------------------------------------

    def _render(self) -> None:
        if not self._attempts:
            self.headline.setText("No trades logged yet")
            self.note.setText(
                "Every whisper you copy is recorded here, along with whatever you "
                "report back about it. Once there are enough, this tab can tell "
                "you which discounts are worth messaging about — which is "
                "currently an estimate from a handful of trades."
            )
            for table in (
                self.by_gap, self.by_age, self.by_presence, self.trades, self.attempts
            ):
                table.setRowCount(0)
            return

        summary = summarise(self._attempts)
        self._fill_buckets(self.by_gap, summary.by_gap)
        self._fill_buckets(self.by_age, summary.by_age)
        self._fill_buckets(self.by_presence, summary.by_presence)
        self._fill_attempts(self.attempts, self._attempts)
        self._fill_attempts(
            self.trades, [a for a in self._attempts if a.outcome.is_success]
        )

        pending = sum(1 for a in self._attempts if not a.outcome.is_resolved)
        bits = [f"{summary.fills} of {summary.resolved} whispers traded"]
        if summary.realised_divines:
            bits.append(f"+{summary.realised_divines:.1f} div earned")
        if pending:
            bits.append(f"{pending} still unanswered")
        self.headline.setText("  ·  ".join(bits))
        self.note.setText(self._advice(summary))

    def _advice(self, summary) -> str:
        """What the log is and isn't yet entitled to say."""
        if not summary.has_enough_data:
            short = MIN_SAMPLES - summary.resolved
            return (
                f"{short} more answered whisper{'s' if short != 1 else ''} before "
                f"fill rates mean anything. Rates are left blank until then "
                f"rather than shown as a number nobody should trust."
            )
        band = suggested_gap_band(summary)
        if band is None:
            return (
                "Not enough spread across discount ranges yet to say which one "
                "pays best. Keep whispering across the bands."
            )
        low, high = band
        return (
            f"Your best-earning discount range so far is <b>{low:g}x-{high:g}x</b> "
            f"per whisper sent. This is what your own trades say, not a rule — "
            f"the gap band in Settings is still whatever you set it to."
        )

    def _fill_buckets(self, table: QTableWidget, buckets: list) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(len(buckets))
        for row, bucket in enumerate(buckets):
            rate = bucket.fill_rate
            per = bucket.value_per_attempt
            cells = [
                # Sorted on position, not text: "over 3x" must not sort next to
                # "1.0-1.1x" alphabetically. The ranges read as a progression.
                NumericItem(bucket.label, row),
                NumericItem(str(bucket.attempts), bucket.attempts),
                NumericItem(str(bucket.fills), bucket.fills),
                # Sorted below zero when unknown: "no data" is not a good score.
                NumericItem(
                    f"{rate:.0%}" if rate is not None else "—",
                    rate if rate is not None else -1.0,
                ),
                NumericItem(f"{bucket.realised_divines:.2f}", bucket.realised_divines),
                NumericItem(
                    f"{per:.2f}" if per is not None else "—",
                    per if per is not None else -1.0,
                ),
            ]
            for col, cell in enumerate(cells):
                if col:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, col, cell)
        table.setSortingEnabled(True)
        table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def _fill_attempts(self, table: QTableWidget, attempts: list) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(len(attempts))
        for row, a in enumerate(attempts):
            profit = (
                a.actual_profit_divines
                if a.actual_profit_divines is not None
                else a.expected_profit_divines
            )
            stamp = a.ts.astimezone()
            bought = NumericItem(f"{a.units:g}", a.units)
            if a.amended and a.asked_units:
                # The ask is kept as well as the correction: the difference is
                # itself a measurement of how much listed stock isn't there.
                bought.setToolTip(
                    f"Asked for {a.asked_units:g}, traded {a.units:g} — corrected "
                    f"after the fact."
                )
            cells = [
                NumericItem(stamp.strftime("%d %b %H:%M"), stamp.timestamp()),
                TextItem(a.item_name),
                bought,
                NumericItem(f"{a.gap:.2f}x", a.gap),
                _band_cell(a.band),
                TextItem(a.character or a.account),
                TextItem(label_for(a.outcome)),
                NumericItem(f"{profit:+.2f}", profit),
            ]
            for col, cell in enumerate(cells):
                if col:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row, col, cell)
        table.setSortingEnabled(True)
        # Newest first: the last thing you did is the thing you're looking for.
        table.sortByColumn(0, Qt.SortOrder.DescendingOrder)


def _band_cell(name: str) -> TextItem:
    """The band as the glyph the Trades tab uses, with its explanation attached.

    This column used to print the raw stored word ("plausible"), so the same fact
    looked like two unrelated columns across the two tabs.
    """
    cell = TextItem(symbol_for_name(name))
    cell.setToolTip(tip_for_name(name))
    return cell


def _buckets_named(first: str) -> list[tuple[str, str]]:
    return [(first, BUCKET_COLUMNS[0][1])] + BUCKET_COLUMNS[1:]


def _make_table(columns, sort_column: int | None = None) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels([c[0] for c in columns])
    for i, (_, tip) in enumerate(columns):
        table.horizontalHeaderItem(i).setToolTip(tip)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    table.setSortingEnabled(True)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    # Nothing stretches: with five narrow number columns, stretching the last
    # one gave "Per whisper" half the window and a single digit in the middle.
    header.setStretchLastSection(False)
    if sort_column is not None:
        table.sortByColumn(sort_column, Qt.SortOrder.DescendingOrder)
    return table
