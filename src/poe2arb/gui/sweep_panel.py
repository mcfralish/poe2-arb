"""The Trades tab: live listings priced against the Currency Exchange.

Buy underpriced listings by whisper on the Bulk Item Exchange, sell into the
Currency Exchange. The tab's whole job is to get you from "a sweep finished" to
"a whisper is on my clipboard" in one click, because the edge per trade is about
a divine and only survives if the effort per attempt is near zero.

Two things here look like bugs and are not:

- **Ghosts are shown, and sort last.** A listing far below market reads as the
  best row in the table and is the one measured never to fill (see TODO.md,
  "Negative results"). Hiding them would make the ranking unfalsifiable; ranking
  by profit would walk the user straight into them.
- **Nothing is ever typed into the game.** The button fills the clipboard. You
  paste. That line is the difference between a trade helper and an automation
  tool, and the app stays firmly on this side of it.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..format import currency_label
from ..listings import Band, rank_candidates, whisper_text
from ..outcomes import TIPS, Outcome, label_for, leagues, read_attempts, sessions
from .bands import (
    BAND_LABEL,
    BAND_TIP,
    legend_text,
    legend_tooltip,
    symbol_for_name,
    tip_for_name,
)
from .table_items import NumericItem, TextItem, flexible_columns
from .theme import muted_color

log = logging.getLogger(__name__)

COLUMNS = [
    (
        "Odds",
        "Whether this is the kind of discount that has been seen to work out.\n"
        "●  worth trying — a real seller pricing under market.\n"
        "○  uncertain — the discount is no bigger than our price estimate's error.\n"
        "×  too good to be true — never once worked.",
    ),
    ("Item", "What you'd be buying."),
    (
        "Price per",
        "Price of one item in divines, whatever currency the seller wants. "
        "Converted so rows stay comparable.",
    ),
    ("Pay with", "The currency the seller wants — you can only pay in this."),
    ("Exchange", "What one is worth on the in-game Currency Exchange."),
    ("Gap", "How far under Exchange value the listing is. 1.20x means 20% under."),
    ("Amount", "How many to ask for — the most that stock and your bankroll allow."),
    ("Total", "Divines you'd spend."),
    (
        "Profit",
        "Divines you'd clear, after rounding down to a whole unit of whatever "
        "you take payment in.",
    ),
    (
        "Settle in",
        "The currency you'd take when reselling on the Currency Exchange, set "
        "above the trade queue. It changes the Profit figure, because proceeds "
        "round down to a whole unit of it.",
    ),
    ("Age", "How long ago the listing was indexed. * means the seller is AFK."),
    ("Seller", "Character to whisper."),
]

BAND_COLUMN = 0
PROFIT_COLUMN = 8
SETTLE_COLUMN = 9
AGE_COLUMN = 10
SELLER_COLUMN = 11

# What the Trades table is showing. "Whispered" and "Bought" are the two the
# field test asked for: after a session it was hard to find what the items you
# actually bought had been valued at, because the table listed everything the
# sweep saw with no record of what you did about it.
SHOW_ALL = "all"
SHOW_WHISPERED = "whispered"
SHOW_BOUGHT = "bought"

SHOW_MODES = (
    (SHOW_ALL, "All Results", "Every listing the last pass turned up."),
    (SHOW_WHISPERED, "Attempts", "Listings whose whisper you copied."),
    (SHOW_BOUGHT, "Trades", "Listings you recorded as an actual trade."),
)

# What the session picker is pointed at. LIVE is the sweep in front of you;
# anything else is read back out of the outcome log, where a row is a whisper
# that was actually sent rather than a listing that was merely found.
SESSION_LIVE = "live"
SESSION_ALL = "all"

# Every league, rather than the one being played. Kept separate from the session
# picker because a season is a different question — "how did I do in Rise of the
# Abyssal" — and league names rotate, so a log spanning two of them is two
# economies in one table.
SEASON_ALL = "all"

# A history row carries its logged attempt where a live row carries a candidate.
# Both live on the band cell, because sorting reorders the view and the row
# index stops being an index into anything.
_ATTEMPT_ROLE = Qt.ItemDataRole.UserRole + 1

# What the Settle in column says on a history row: the verdict, since the
# settlement currency was never recorded per attempt and what happened is the
# more useful thing to have there. The wording comes from `outcomes.label_for`,
# which the Results tab reads too — this module and that one carried the same
# dict twice until 0.8.0.



class SweepPanel(QWidget):
    """Ranked cross-venue candidates, with one-click whisper copying."""

    attempt_copied = Signal(object)          # Candidate
    recheck_requested = Signal(object)       # Candidate
    outcome_reported = Signal(str, object)   # (attempt id, Outcome)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._candidates: list = []
        self._icons = None
        # Candidate key -> the attempt id logged when its whisper was copied,
        # so a verdict attaches to the right row afterwards. Keyed on content,
        # not object identity: a candidate read back out of a Qt item is not
        # guaranteed to be the same Python object.
        self._attempt_ids: dict[tuple, str] = {}
        self._rechecked: set[tuple] = set()
        self._last_copied = None
        # Candidate key -> the verdict the user reported, so the table can filter
        # down to what actually happened rather than only what was on offer.
        self._outcomes: dict[tuple, Outcome] = {}
        # Candidates kept alive past the sweep that found them, because they
        # were whispered. A listing you *bought* is by definition absent from
        # the next sweep, so without this "Trades" empties itself the
        # moment the purchase succeeds — the exact case it exists to answer.
        # Held out of "All Results", which means what it says.
        self._carried: dict[tuple, object] = {}
        # What sales are priced in. Shown per row because it decides the Profit
        # figure, and because after a session you need to know which currency a
        # given trade was costed against.
        self._settlement = "divine"
        # The outcome log, for reviewing sessions other than the live one.
        self._history_path = None
        self._history: list = []
        self._live_session: str | None = None

        layout = QVBoxLayout(self)

        # Starting and stopping lives on the toolbar toggle: two ways to run
        # the same thing, one of them a one-shot and one a loop, is a way to
        # end up with two sweeps arguing over the request budget.
        controls = QHBoxLayout()

        # Which session, and which league. Both come from the outcome log, so
        # they can only offer what has actually been traded; the live sweep is
        # always the first entry and the default.
        self.season = QComboBox()
        self.season.addItem("All seasons", SEASON_ALL)
        self.season.setToolTip(
            "Which league's trades to list. Prices are only comparable within "
            "one — a league rollover moves everything."
        )
        # Hidden until the log holds more than one league: until then it is a
        # dropdown with a single choice.
        self.season.setVisible(False)
        self.season.currentIndexChanged.connect(lambda _: self._season_changed())
        controls.addWidget(self.season)

        self.session = QComboBox()
        # Seeded here rather than left to the first log read, so the tab has a
        # live selection — and therefore draws sweeps — before any whisper has
        # ever been recorded.
        self.session.addItem("This session", SESSION_LIVE)
        self.session.addItem("All time", SESSION_ALL)
        self.session.setToolTip(
            "Which sitting to show.\n\n"
            "A session starts when you press Find trades and ends when the last "
            "opportunity has left the queue with nothing still running — so "
            "pressing Find trades again mid-session continues it rather than "
            "starting another.\n\n"
            "This session lists what the last sweep found. The rest are read "
            "back from the trade log, so they list whispers you sent."
        )
        self.session.currentIndexChanged.connect(lambda _: self._source_changed())
        controls.addWidget(self.session)

        self.show_mode = QComboBox()
        for mode, label, tip in SHOW_MODES:
            self.show_mode.addItem(label, mode)
            self.show_mode.setItemData(
                self.show_mode.count() - 1, tip, Qt.ItemDataRole.ToolTipRole
            )
        self.show_mode.setToolTip(
            "Which of these to list.\n\n"
            "All Results is what the last pass saw. The other two narrow it "
            "to what you did about it, which is how you check afterwards what a "
            "trade you actually made was valued at."
        )
        self.show_mode.currentIndexChanged.connect(lambda _: self._apply_filter())
        controls.addWidget(self.show_mode)

        self.hide_ghosts = QCheckBox("Hide the too-good-to-be-true ones")
        self.hide_ghosts.setToolTip(BAND_TIP[Band.GHOST])
        self.hide_ghosts.toggled.connect(self._apply_filter)
        controls.addWidget(self.hide_ghosts)

        controls.addSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search item or seller")
        self.search.setClearButtonEnabled(True)
        # Given the rest of the row's slack rather than capped at 200px: item
        # names here run to "Zarokh's Reliquary Key: Against the Darkness" and a
        # search box you can't read your own query in is worse than no box.
        self.search.setMinimumWidth(240)
        self.search.textChanged.connect(self._apply_filter)
        controls.addWidget(self.search, stretch=1)
        layout.addLayout(controls)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        for i, (_, tip) in enumerate(COLUMNS):
            self.table.horizontalHeaderItem(i).setToolTip(tip)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        # Reorderable and resizable, and every column grows when the window does
        # — not just the one that used to be stretched.
        self.columns = flexible_columns(self.table)
        self.table.setWordWrap(False)
        # Double-click is the fast path; the button is for discoverability.
        self.table.itemDoubleClicked.connect(lambda _: self.copy_selected())
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table)

        bottom = QHBoxLayout()
        self.copy_btn = QPushButton("Copy whisper")
        self.copy_btn.setEnabled(False)
        self.copy_btn.setToolTip(
            "Copy the trade message for the selected row. Paste it into the game's "
            "chat with Ctrl+V and press Enter to send — the app never types for you."
        )
        self.copy_btn.clicked.connect(self.copy_selected)
        bottom.addWidget(self.copy_btn)

        self.recheck_box = QCheckBox("Check first")
        self.recheck_box.setChecked(True)
        self.recheck_box.setToolTip(
            "Before copying, spend one request confirming the listing is still "
            "there. Listings disappear within minutes, and this catches the most "
            "common wasted whisper."
        )
        bottom.addWidget(self.recheck_box)

        # Reporting what happened is the only way the ranking ever improves, so
        # the buttons sit next to Copy rather than behind a menu. They stay
        # disabled until a whisper has actually been copied — there is nothing
        # to report a verdict on before that.
        self._outcome_btns: dict[Outcome, QPushButton] = {}
        # The same four verdicts the Opportunities queue offers, from the same
        # source. No Reply is gone from both: the timer writes Expired on its
        # own, and by hand the two things ever actually meant were AFK and
        # Offline.
        for outcome in (
            Outcome.FILLED, Outcome.SOLD, Outcome.AFK, Outcome.OFFLINE,
            Outcome.DECLINED,
        ):
            btn = QPushButton(label_for(outcome))
            btn.setToolTip(
                TIPS[outcome]
                + "  Recorded so the ranking can learn which listings fill."
            )
            btn.setEnabled(False)
            btn.clicked.connect(lambda _=False, o=outcome: self._report(o))
            bottom.addWidget(btn)
            self._outcome_btns[outcome] = btn

        self.status = QLabel()
        self.status.setStyleSheet(f"color: {muted_color(self)};")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, stretch=1)
        layout.addLayout(bottom)

        # A visible key for the Odds glyphs. They were explained only in the
        # column header's tooltip, which nobody found — the symbols read as
        # decoration until you happen to hover the right pixel.
        self.legend = QLabel(legend_text())
        self.legend.setStyleSheet(f"color: {muted_color(self)};")
        self.legend.setWordWrap(True)
        self.legend.setToolTip(legend_tooltip())
        layout.addWidget(self.legend)

        self.set_status(
            "No sweep yet. Switch on Find trades to check live listings against "
            "Currency Exchange prices."
        )

    # --- wiring ------------------------------------------------------------

    def set_icons(self, provider) -> None:
        self._icons = provider

    def set_hotkey_hint(self, binding: str) -> None:
        """The hotkey serves the Opportunities queue, not this table.

        Kept as a no-op hook so the window can tell both panels about the
        binding without caring which of them uses it.
        """

    def set_running(self, running: bool) -> None:
        """No-op hook: the toolbar toggle owns the run/stop state now.

        Kept so the window drives both panels through the same calls.
        """

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    # --- sessions and seasons ----------------------------------------------

    def set_history_path(self, path) -> None:
        self._history_path = path
        self.reload_history()

    def set_live_session(self, session_id: str | None) -> None:
        """Tell the tab which session is currently running, if any."""
        self._live_session = session_id
        self.reload_history()

    def reload_history(self) -> None:
        """Re-read the trade log and rebuild the two pickers.

        Called whenever a whisper or a verdict is recorded, so a session that
        has only just started appears in the list without a restart.
        """
        if self._history_path is None:
            return
        try:
            self._history = read_attempts(self._history_path)
        except OSError:
            log.warning("could not read the trade log", exc_info=True)
            self._history = []
        self._rebuild_pickers()

    def _rebuild_pickers(self) -> None:
        """Refill the season and session combos, keeping the current choice.

        Both are rebuilt wholesale rather than patched: a whisper can create a
        season, a session, or neither, and working out which is more code than
        rebuilding two short lists.
        """
        wanted_season = self.season.currentData() or SEASON_ALL
        wanted_session = self.session.currentData() or SESSION_LIVE

        blocked = self.season.blockSignals(True)
        self.season.clear()
        self.season.addItem("All seasons", SEASON_ALL)
        for name in leagues(self._history):
            self.season.addItem(name, name)
        index = self.season.findData(wanted_season)
        self.season.setCurrentIndex(max(0, index))
        self.season.blockSignals(blocked)
        self.season.setVisible(self.season.count() > 2)

        season = self.season.currentData()
        blocked = self.session.blockSignals(True)
        self.session.clear()
        self.session.addItem("This session", SESSION_LIVE)
        self.session.addItem("All time", SESSION_ALL)
        for s in sessions(self._history):
            if season != SEASON_ALL and s.league != season:
                continue
            # The running session is already the first entry; listing it twice
            # would offer the same rows under two names.
            if s.id is not None and s.id == self._live_session:
                continue
            self.session.addItem(s.label, s.id or "")
        index = self.session.findData(wanted_session)
        self.session.setCurrentIndex(max(0, index))
        self.session.blockSignals(blocked)
        self._source_changed()

    def _season_changed(self) -> None:
        self._rebuild_pickers()

    def _source_changed(self) -> None:
        """Point the table at the live sweep or at the log, and redraw."""
        live = self.session.currentData() == SESSION_LIVE
        # Two columns carry a different fact in each mode, so they are renamed
        # rather than left saying "Settle in" over a verdict. The columns
        # themselves are shared because the other ten mean the same thing in
        # both, and a second table would have to be kept in step with this one.
        for column, title in (
            (SETTLE_COLUMN, "Settle in" if live else "Result"),
            (AGE_COLUMN, "Age" if live else "When"),
        ):
            self.table.horizontalHeaderItem(column).setText(title)
        self.table.horizontalHeaderItem(SETTLE_COLUMN).setToolTip(
            COLUMNS[SETTLE_COLUMN][1] if live else "What you reported back."
        )
        self.table.horizontalHeaderItem(AGE_COLUMN).setToolTip(
            COLUMNS[AGE_COLUMN][1] if live else "When you copied the whisper."
        )
        if live:
            self._populate()
        else:
            self._populate_history()

    def _selected_attempts(self) -> list:
        chosen = self.session.currentData()
        season = self.season.currentData()
        rows = [
            a for a in self._history
            if season == SEASON_ALL or a.league == season
        ]
        if chosen == SESSION_ALL:
            return rows
        return [a for a in rows if (a.session_id or "") == chosen]

    def _populate_history(self) -> None:
        """Fill the table from the outcome log rather than from a sweep.

        A logged attempt is not a candidate — the listing it came from is long
        gone, and there is nothing left to whisper — so the rows carry no
        candidate and Copy stays disabled against them. What they do carry is
        the whole point: what a trade you actually made was valued at.
        """
        attempts = self._selected_attempts()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(attempts))
        for row, a in enumerate(attempts):
            band = NumericItem(symbol_for_name(a.band), 0)
            band.setToolTip(tip_for_name(a.band))
            band.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            band.setData(Qt.ItemDataRole.UserRole, None)
            band.setData(_ATTEMPT_ROLE, a)
            self.table.setItem(row, BAND_COLUMN, band)

            name = TextItem(a.item_name)
            if self._icons is not None:
                icon = self._icons.icon(a.item_id)
                if icon is not None:
                    name.setIcon(icon)
            if a.amended and a.asked_units:
                name.setToolTip(
                    f"Corrected after the fact: asked for {a.asked_units:g}, "
                    f"traded {a.units:g}."
                )
            self.table.setItem(row, 1, name)
            self.table.setItem(
                row, 2,
                NumericItem(_div(a.unit_price_divines), a.unit_price_divines),
            )
            self.table.setItem(row, 3, TextItem(_pay_label(a.pay_currency)))
            self.table.setItem(row, 4, NumericItem(_div(a.ce_divines), a.ce_divines))
            self.table.setItem(row, 5, NumericItem(f"{a.gap:.2f}x", a.gap))
            self.table.setItem(row, 6, NumericItem(f"{a.units:g}", a.units))
            self.table.setItem(
                row, 7, NumericItem(_div(a.cost_divines), a.cost_divines)
            )
            profit = (
                a.actual_profit_divines
                if a.actual_profit_divines is not None
                else a.expected_profit_divines
            )
            self.table.setItem(
                row, PROFIT_COLUMN, NumericItem(f"+{_div(profit)}", profit)
            )
            # The verdict, where the live table shows the settlement currency.
            # On a past session what happened is the column worth having, and
            # the settlement currency is not recorded per attempt.
            verdict = TextItem(label_for(a.outcome))
            verdict.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, SETTLE_COLUMN, verdict)
            stamp = a.ts.astimezone()
            when = NumericItem(stamp.strftime("%d %b %H:%M"), stamp.timestamp())
            self.table.setItem(row, AGE_COLUMN, when)
            self.table.setItem(
                row, SELLER_COLUMN, TextItem(a.character or a.account)
            )
        self.table.setSortingEnabled(True)
        self.columns.size_to_contents()
        self._apply_filter()
        self._describe_history(attempts)

    def _describe_history(self, attempts: list) -> None:
        fills = [a for a in attempts if a.outcome is Outcome.FILLED]
        earned = sum(
            a.actual_profit_divines
            if a.actual_profit_divines is not None
            else a.expected_profit_divines
            for a in fills
        )
        if not attempts:
            self.set_status(
                "No whispers recorded for this selection. Sessions appear here "
                "once you've messaged someone in them."
            )
            return
        self.set_status(
            f"{len(attempts)} whisper(s) sent  ·  {len(fills)} traded  ·  "
            f"+{earned:.2f} div earned  ·  from the trade log, so Copy is off "
            f"— these listings are gone"
        )

    # --- content -----------------------------------------------------------

    def set_result(self, result, *, risk_appetite: float = 0.0) -> None:
        """Show a sweep. Re-callable with the same result to re-rank in place.

        Moving the long-shots slider has to reorder what is already on screen —
        waiting for the next sweep is a fifteen-minute round trip to see the
        effect of dragging a slider.
        """
        fresh = rank_candidates(list(result.candidates), risk_appetite=risk_appetite)
        seen = {c.key for c in fresh}
        # Anything whispered stays on the table even once the sweep stops
        # finding it — which is what happens the moment a purchase succeeds.
        self._carried = {
            c.key: c
            for c in list(self._candidates) + list(self._carried.values())
            if c.key in self._attempt_ids and c.key not in seen
        }
        self._candidates = fresh + list(self._carried.values())
        # `_attempt_ids` and `_outcomes` deliberately survive a sweep. They used
        # to be cleared here, which emptied "Attempts" and "Trades"
        # every ten minutes — so by the time a session was worth
        # reviewing, both filters were blank (reported from the field
        # 2026-07-31). They are keyed on candidate identity, not on row, so a
        # re-found listing carries its own history back onto the new table; keys
        # for listings this sweep didn't see simply match nothing.
        self._rechecked.clear()
        self._last_copied = None
        # Only redraws if the table is pointed at the live sweep; a user
        # reviewing an old session should not have it yanked out from under them
        # every ten minutes.
        live = self.session.currentData() == SESSION_LIVE
        if live:
            self._populate()
        # After the rebuild, not before. Repopulating leaves the selection on
        # whatever row index survives, without necessarily emitting a selection
        # change — so a check run beforehand describes the previous table and
        # can leave the verdict buttons live against a listing never whispered.
        self._update_outcome_buttons()
        # Counted over this sweep's own candidates, never the carried ones —
        # the line describes what the pass found.
        plausible = sum(1 for c in fresh if c.band is Band.PLAUSIBLE)
        thin = sum(1 for c in fresh if c.band is Band.THIN)
        ghosts = sum(1 for c in fresh if c.band is Band.GHOST)
        best = max((c.profit_divines for c in fresh), default=0.0)
        # Same words as the legend below the table. These read as three unrelated
        # jargon terms otherwise, with nothing on screen tying them to the glyphs.
        parts = [
            f"{len(result.items)} items checked in {result.duration_s / 60:.0f} min",
            f"{result.listings_seen} live listings",
            f"{plausible} worth trying · {thin} uncertain · "
            f"{ghosts} too good to be true",
        ]
        if plausible:
            best_plausible = max(
                c.profit_divines for c in fresh if c.band is Band.PLAUSIBLE
            )
            parts.append(f"best is +{best_plausible:.2f} div")
        elif best:
            parts.append("nothing worth trying this time")
        if result.errors:
            parts.append(f"{len(result.errors)} item(s) failed — see the Log tab")
        if live:
            self.set_status("  ·  ".join(parts))

    def _populate(self) -> None:
        # Sorting off while filling: Qt re-sorts on every insert otherwise, which
        # both scrambles row indices mid-loop and is quadratic.
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._candidates))
        for row, c in enumerate(self._candidates):
            listing = c.listing
            # Sorts on -rank so the column groups plausible first rather than
            # ordering the glyphs alphabetically. Carries the candidate itself,
            # because sorting reorders the view and the row index stops being an
            # index into `_candidates`.
            band_cell = NumericItem(BAND_LABEL[c.band], -c.band.rank)
            band_cell.setToolTip(BAND_TIP[c.band])
            band_cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            band_cell.setData(Qt.ItemDataRole.UserRole, c)
            self.table.setItem(row, BAND_COLUMN, band_cell)

            name_cell = TextItem(c.item_name)
            if self._icons is not None:
                icon = self._icons.icon(listing.item_id)
                if icon is not None:
                    name_cell.setIcon(icon)
            self.table.setItem(row, 1, name_cell)
            self.table.setItem(row, 2, NumericItem(_div(c.unit_price_divines), c.unit_price_divines))
            self.table.setItem(row, 3, TextItem(_pay_label(listing.pay_currency)))
            self.table.setItem(row, 4, NumericItem(_div(c.ce_divines), c.ce_divines))
            self.table.setItem(
                row, 5, NumericItem(">99x" if c.gap > 99 else f"{c.gap:.2f}x", c.gap)
            )
            self.table.setItem(row, 6, NumericItem(f"{c.plan.units:g}", c.plan.units))
            self.table.setItem(
                row, 7, NumericItem(_div(c.plan.cost_divines), c.plan.cost_divines)
            )
            self.table.setItem(
                row, PROFIT_COLUMN,
                NumericItem(f"+{_div(c.profit_divines)}", c.profit_divines),
            )
            settle = TextItem(_pay_label(self._settlement))
            settle.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, SETTLE_COLUMN, settle)
            age = listing.age_s()
            self.table.setItem(
                row, AGE_COLUMN, NumericItem(_age(age, listing.afk), age or 0.0)
            )
            self.table.setItem(
                row, SELLER_COLUMN, TextItem(listing.character or listing.account)
            )
        self.table.setSortingEnabled(True)
        self.columns.size_to_contents()
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Hide rows the current filters exclude, and say so if that's everything."""
        needle = self.search.text().strip().lower()
        hide_ghosts = self.hide_ghosts.isChecked()
        mode = self.show_mode.currentData()
        shown = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, BAND_COLUMN)
            if item is None:
                continue
            c = item.data(Qt.ItemDataRole.UserRole)
            if c is not None:
                hidden = self._hide_candidate(c, mode, hide_ghosts, needle)
            else:
                a = item.data(_ATTEMPT_ROLE)
                if a is None:
                    continue
                hidden = self._hide_attempt(a, mode, hide_ghosts, needle)
            self.table.setRowHidden(row, hidden)
            shown += not hidden
        self._note_empty_filter(mode, shown)

    def _hide_candidate(self, c, mode, hide_ghosts, needle) -> bool:
        if hide_ghosts and c.band is Band.GHOST:
            return True
        if not self._matches_mode(c, mode):
            return True
        if needle:
            haystack = f"{c.item_name} {c.listing.character or ''} {c.listing.account}"
            return needle not in haystack.lower()
        return False

    def _hide_attempt(self, a, mode, hide_ghosts, needle) -> bool:
        """The same filters against a logged whisper.

        "Attempts" matches everything here — the log only holds whispers
        that were sent — so the mode that does any work is "Trades".
        """
        if hide_ghosts and a.band == Band.GHOST.value:
            return True
        if mode == SHOW_BOUGHT and a.outcome is not Outcome.FILLED:
            return True
        if needle:
            haystack = f"{a.item_name} {a.character or ''} {a.account}"
            return needle not in haystack.lower()
        return False

    def _matches_mode(self, candidate, mode: str) -> bool:
        if mode == SHOW_WHISPERED:
            return candidate.key in self._attempt_ids
        if mode == SHOW_BOUGHT:
            return self._outcomes.get(candidate.key) is Outcome.FILLED
        # "All Results" is the last pass, not the last pass plus history.
        return candidate.key not in self._carried

    def _note_empty_filter(self, mode: str, shown: int) -> None:
        """Explain an empty table rather than leaving it looking broken.

        Only when a filter is what emptied it — an empty sweep has its own
        message from `set_result`, and overwriting that would lose the counts.
        """
        if shown or not self.table.rowCount():
            return
        if mode == SHOW_BOUGHT:
            self.set_status(
                "Nothing here yet — this lists trades you marked as Traded. "
                "Report a verdict after a whisper and it'll show up."
            )
        elif mode == SHOW_WHISPERED:
            self.set_status(
                "Nothing here yet — this lists listings whose whisper you copied."
            )

    def _candidate_at(self, row: int):
        """Map a view row back to its candidate.

        Sorting reorders the view, so the row index is not an index into
        `_candidates`. The item text identifies it well enough for a lookup, but
        storing the object on the cell is exact and survives re-sorts.
        """
        item = self.table.item(row, BAND_COLUMN)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    # --- clipboard ---------------------------------------------------------

    def _selection_changed(self) -> None:
        c = self.selected_candidate()
        self.copy_btn.setEnabled(c is not None and whisper_text(c) is not None)
        self._update_outcome_buttons()

    def _update_outcome_buttons(self) -> None:
        """Enabled only for a row whose whisper has actually been copied.

        Reporting an outcome for a listing you never messaged would poison the
        very data the ranking is meant to learn from, so the buttons follow the
        attempt rather than the selection.
        """
        c = self.selected_candidate()
        has_attempt = c is not None and c.key in self._attempt_ids
        for btn in self._outcome_btns.values():
            btn.setEnabled(has_attempt)

    def _report(self, outcome: Outcome) -> None:
        c = self.selected_candidate()
        if c is None:
            return
        attempt_id = self._attempt_ids.get(c.key)
        if attempt_id is None:
            return
        # Kept here as well as in the outcome log, so the "Trades" filter
        # can work without re-reading the file.
        self._outcomes[c.key] = outcome
        self._apply_filter()
        self.outcome_reported.emit(attempt_id, outcome)
        self.set_status(
            f"Recorded as {label_for(outcome)} — {c.item_name} from "
            f"{c.listing.character or c.listing.account}."
        )

    def note_attempt(self, candidate, attempt_id: str) -> None:
        """Remember which log row a copied whisper produced.

        Called for whispers copied here *and* for ones taken from the
        Opportunities queue, which is where almost all of them come from. Left
        unwired, the two filters below only ever knew about the handful copied
        from this table and read as permanently empty.
        """
        self._attempt_ids[candidate.key] = attempt_id
        self.reload_history()
        if not any(c.key == candidate.key for c in self._candidates):
            # Whispered from the queue, and this sweep never surfaced it here —
            # add it so there is a row for the verdict to land on.
            self._carried[candidate.key] = candidate
            self._candidates = list(self._candidates) + [candidate]
            self._populate()
            return
        self._update_outcome_buttons()
        self._apply_filter()

    def note_outcome(self, candidate, outcome: Outcome) -> None:
        """Record a verdict reached elsewhere, so the filters agree with it."""
        self._outcomes[candidate.key] = outcome
        self._apply_filter()
        self.reload_history()

    def note_revision(self, candidate) -> None:
        """Swap in a candidate whose quantity was corrected after the whisper.

        Matched on `key`, which is the listing rather than the quantity, so the
        corrected trade lands on the row the original one is already on instead
        of appearing beside it as a second listing that never existed.
        """
        replaced = False
        for i, existing in enumerate(self._candidates):
            if existing.key == candidate.key:
                self._candidates[i] = candidate
                replaced = True
        if candidate.key in self._carried:
            self._carried[candidate.key] = candidate
        if replaced and self.session.currentData() == SESSION_LIVE:
            self._populate()
        self.reload_history()

    def set_settlement_currency(self, currency: str) -> None:
        """What sales are priced in, for the Settle in column.

        Only redraws the column, not the table: the profit figures come from the
        sweep and are recomputed there, so re-populating here would be both
        wasteful and a chance for the two to disagree.
        """
        if currency == self._settlement:
            return
        self._settlement = currency
        label = _pay_label(currency)
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, SETTLE_COLUMN)
            if cell is not None:
                cell.setText(label)

    def selected_candidate(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        return self._candidate_at(rows[0].row())

    def copy_selected(self) -> None:
        c = self.selected_candidate()
        if c is None:
            return
        text = whisper_text(c)
        if not text:
            self.set_status("That listing has no whisper template, so it can't be messaged.")
            return
        if self.recheck_box.isChecked() and c.key not in self._rechecked:
            self.set_status(f"Checking {c.item_name} is still listed…")
            self.recheck_requested.emit(c)
            return
        self._copy_now(c)

    def recheck_finished(self, candidate, result) -> None:
        """Copy, or explain why not, once the confirmation request lands."""
        from ..sweep import RecheckStatus

        # Only checked once per candidate: a second click after a warning is the
        # user overriding it, and re-checking would loop them back into the same
        # message forever.
        self._rechecked.add(candidate.key)
        if result.status is RecheckStatus.GONE:
            self.set_status(
                f"{candidate.item_name} from "
                f"{candidate.listing.character or candidate.listing.account} is "
                f"{result.detail} — nothing copied. Click again to copy anyway."
            )
            return
        self._copy_now(candidate)
        if result.status is RecheckStatus.REDUCED:
            self.set_status(self.status.text() + f"   ·  warning: {result.detail}")
        elif result.status is RecheckStatus.UNKNOWN:
            self.set_status(self.status.text() + "   ·  (couldn't verify it's still listed)")

    def _copy_now(self, c) -> None:
        text = whisper_text(c)
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        self._last_copied = c
        self.attempt_copied.emit(c)
        seller = c.listing.character or c.listing.account
        self.set_status(
            f"Copied — paste in game with Ctrl+V, then Enter to send.   "
            f"{c.plan.units:g} × {c.item_name} from {seller} "
            f"for {_div(c.plan.cost_divines)} div  (+{_div(c.profit_divines)} div)"
            f"   ·  then tell me how it went"
        )


def _div(value: float) -> str:
    if value >= 1000:
        return f"{value:,.0f}"
    if value >= 10:
        return f"{value:.1f}"
    return f"{value:.3g}"


def _pay_label(currency: str) -> str:
    return currency_label(currency)


def _age(seconds: float | None, afk: bool) -> str:
    if seconds is None:
        return "?"
    if seconds >= 86400:
        text = f"{seconds / 86400:.0f}d"
    elif seconds >= 3600:
        text = f"{seconds / 3600:.0f}h"
    else:
        text = f"{seconds / 60:.0f}m"
    return f"{text}*" if afk else text
