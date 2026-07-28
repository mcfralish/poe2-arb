"""Trends tab: what the banked scan history says over time.

Two questions, two tables. *Which loops keep coming back* — a loop seen once is
an anecdote, one seen twenty times is a pattern worth trading. And *which
currencies are earning their slot* — the graph can only hold a handful, so a
currency tracked for a week that never appeared in a single loop is a slot the
node-selection work should be reclaiming.

Everything here reads from disk. No network, no scan required.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..format import fmt_depth, fmt_pct, fmt_skew
from ..history_stats import (
    DEAD_WEIGHT_MIN_SCANS,
    HistorySummary,
    dead_weight,
    judgeable,
    summarise_file,
    window_choices,
)
from .table_items import NumericItem, TextItem
from .theme import muted_color

LOOP_COLUMNS = [
    ("Route", "The chain of trades, as it was recorded."),
    ("Times seen", "How many scans found this loop above your threshold."),
    ("Of scans", "That count as a share of every scan in the window. High means "
                 "a standing feature of the market rather than a blip."),
    ("Best", "The largest profit this loop ever showed."),
    ("Typical", "The middle value across every sighting — what to actually expect."),
    ("Depth", "Median bottleneck depth in Divine Orbs."),
    ("Spread", "Median time between the oldest and newest price in the loop."),
    ("Last seen", "When it was most recently found."),
]

CURRENCY_COLUMNS = [
    ("Currency", "A currency that has been part of the arbitrage graph."),
    ("Scans tracked", "How many scans included it. Compared against, not added "
                      "to, the next column — a currency added yesterday isn't "
                      "judged against one tracked for a month."),
    ("In a loop", "How many of those scans found it inside a profitable loop."),
    ("Hit rate", "The second as a share of the first. Zero over many scans means "
                 "it is occupying a slot without ever paying for it."),
    ("Best", "The largest profit of any loop it took part in."),
]


class TrendsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._history_path = None
        self._summary: HistorySummary | None = None

        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Show "))
        self.window_box = QComboBox()
        for label, days in window_choices():
            self.window_box.addItem(label, days)
        self.window_box.setCurrentIndex(1)  # last 7 days
        self.window_box.currentIndexChanged.connect(self.reload)
        controls.addWidget(self.window_box)
        refresh = QPushButton("Refresh")
        refresh.setToolTip("Re-read the saved scan history from disk.")
        refresh.clicked.connect(self.reload)
        controls.addWidget(refresh)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.tabs = QTabWidget()
        self.loops_table = _make_table(LOOP_COLUMNS, 1)
        self.tabs.addTab(self.loops_table, "Recurring loops")
        self.currencies_table = _make_table(CURRENCY_COLUMNS, 3)
        self.tabs.addTab(self.currencies_table, "Currency performance")
        layout.addWidget(self.tabs)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {muted_color(self)};")
        layout.addWidget(self.note)

    def set_history_path(self, path) -> None:
        self._history_path = path
        self.reload()

    def reload(self) -> None:
        if self._history_path is None:
            return
        days = self.window_box.currentData()
        self._summary = summarise_file(self._history_path, float(days or 0.0))
        self._render(self._summary)

    # ------------------------------------------------------------------ render

    def _render(self, summary: HistorySummary) -> None:
        self._render_headline(summary)
        self._render_loops(summary)
        self._render_currencies(summary)
        self._render_note(summary)

    def _render_headline(self, summary: HistorySummary) -> None:
        if summary.is_empty:
            self.summary_label.setText(
                "<b>No saved scans in this window.</b> History builds up as you "
                "scan — leave Watch running and come back."
            )
            return
        span = ""
        if summary.first_scan and summary.last_scan:
            span = (
                f" between {_short(summary.first_scan)} and "
                f"{_short(summary.last_scan)}"
            )
        self.summary_label.setText(
            f"<b>{summary.scans} scan(s)</b>{span}. "
            f"{summary.scans_with_opportunity} found something "
            f"({summary.hit_rate_pct:.0f}% of scans), across "
            f"<b>{len(summary.loops)} distinct loop(s)</b>."
        )

    def _render_loops(self, summary: HistorySummary) -> None:
        table = self.loops_table
        table.setSortingEnabled(False)
        table.setRowCount(len(summary.loops))
        for r, loop in enumerate(summary.loops):
            route = " → ".join(loop.cycle) + f" → {loop.cycle[0]}"
            cells = [
                TextItem(route),
                NumericItem(str(loop.times_seen), loop.times_seen),
                NumericItem(f"{loop.frequency_pct:.0f}%", loop.frequency_pct),
                NumericItem(fmt_pct(loop.best_profit_pct), loop.best_profit_pct),
                NumericItem(fmt_pct(loop.median_profit_pct), loop.median_profit_pct),
                NumericItem(
                    fmt_depth(loop.median_depth_divines), loop.median_depth_divines
                ),
                NumericItem(
                    fmt_skew(loop.median_skew_s),
                    loop.median_skew_s if loop.median_skew_s is not None else float("inf"),
                ),
                TextItem(_short(loop.last_seen)),
            ]
            for c, cell in enumerate(cells):
                table.setItem(r, c, cell)
        table.setSortingEnabled(True)

    def _render_currencies(self, summary: HistorySummary) -> None:
        table = self.currencies_table
        table.setSortingEnabled(False)
        table.setRowCount(len(summary.currencies))
        for r, stat in enumerate(summary.currencies):
            cells = [
                TextItem(stat.item_id),
                NumericItem(str(stat.scans_tracked), stat.scans_tracked),
                NumericItem(str(stat.loops_seen), stat.loops_seen),
                NumericItem(f"{stat.hit_rate_pct:.0f}%", stat.hit_rate_pct),
                NumericItem(fmt_pct(stat.best_profit_pct), stat.best_profit_pct),
            ]
            for c, cell in enumerate(cells):
                table.setItem(r, c, cell)
        table.setSortingEnabled(True)

    def _render_note(self, summary: HistorySummary) -> None:
        """Say what the data supports — and nothing more.

        The dangerous case is a nearly-empty history: with two scans and no
        loops, "every currency has appeared in a loop" is both reassuring and
        false. So the sample size is checked before any verdict is offered.
        """
        if summary.is_empty:
            self.note.setText("")
            return
        if not judgeable(summary):
            self.note.setText(
                f"Not enough history yet to say which currencies are earning "
                f"their place — that takes at least {DEAD_WEIGHT_MIN_SCANS} "
                f"scans of each. Keep Watch running."
            )
            return
        idle = dead_weight(summary)
        if idle:
            names = ", ".join(c.item_id for c in idle[:6])
            more = f" and {len(idle) - 6} more" if len(idle) > 6 else ""
            self.note.setText(
                f"Tracked all this time without ever appearing in a loop: "
                f"{names}{more}. Those are graph slots that could go to "
                f"something else."
            )
            return
        self.note.setText(
            "Every currency tracked long enough to judge has appeared in at "
            "least one loop over this window."
        )

    def rename(self, names: dict[str, str]) -> None:
        """Swap currency ids for display names once they're known."""
        for r in range(self.currencies_table.rowCount()):
            item = self.currencies_table.item(r, 0)
            if item is not None:
                item.setText(names.get(item.text(), item.text()))


def _short(when: datetime) -> str:
    return when.astimezone().strftime("%d %b %H:%M")


def _make_table(columns: list[tuple[str, str]], sort_column: int) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels([c[0] for c in columns])
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for i in range(1, len(columns)):
        header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
    for i, (_, tip) in enumerate(columns):
        table.horizontalHeaderItem(i).setToolTip(tip)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSortingEnabled(True)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    table.sortByColumn(sort_column, Qt.SortOrder.DescendingOrder)
    return table
