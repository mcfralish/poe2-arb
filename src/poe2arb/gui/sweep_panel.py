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
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..listings import Band, whisper_text
from ..outcomes import Outcome
from .table_items import NumericItem, TextItem
from .theme import muted_color

log = logging.getLogger(__name__)

COLUMNS = [
    ("", "Whether the discount is one that has been seen to fill."),
    ("Item", "What you'd be buying."),
    (
        "Listed",
        "Price per item in divines, whatever currency the seller wants. "
        "Converted so rows stay comparable.",
    ),
    ("Pay", "The currency the seller actually wants."),
    ("Exchange", "What one is worth on the in-game Currency Exchange."),
    ("Gap", "How far under Exchange value the listing is. 1.20x means 20% under."),
    ("Buy", "How many to ask for — the most that stock and your bankroll allow."),
    ("Cost", "Divines you'd spend."),
    (
        "Profit",
        "Divines you'd clear, after rounding. Assumes you take payment in the "
        "settlement currency from Settings — exalted by default, which is much "
        "finer than divine and loses far less to rounding.",
    ),
    ("Age", "How long ago the listing was indexed. * means the seller is AFK."),
    ("Seller", "Character to whisper."),
]

BAND_COLUMN = 0
PROFIT_COLUMN = 8

BAND_LABEL = {
    Band.PLAUSIBLE: "●",
    Band.THIN: "○",
    Band.GHOST: "×",
}
BAND_TIP = {
    Band.PLAUSIBLE: "Plausible — a real seller under market. These are the ones that fill.",
    Band.THIN: (
        "Thin — the discount is inside the Exchange price's own margin of error, "
        "so both the gap and the profit are uncertain."
    ),
    Band.GHOST: (
        "Ghost — far below market. Measured fill rate on these is zero: they're "
        "mistakes, abandoned listings, or already sold. Shown so you can judge "
        "for yourself, ranked last so they don't waste whispers."
    ),
}


class SweepPanel(QWidget):
    """Ranked cross-venue candidates, with one-click whisper copying."""

    sweep_requested = Signal()
    stop_requested = Signal()
    bankroll_changed = Signal(float)
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

        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.sweep_btn = QPushButton("Find trades")
        self.sweep_btn.setToolTip(
            "Check live listings for every tracked item against Currency Exchange "
            "prices. Takes a few minutes — requests to the trade API are paced."
        )
        self.sweep_btn.clicked.connect(self.sweep_requested)
        controls.addWidget(self.sweep_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested)
        controls.addWidget(self.stop_btn)

        controls.addSpacing(12)
        controls.addWidget(QLabel("Bankroll:"))
        self.bankroll = QDoubleSpinBox()
        self.bankroll.setRange(0.0, 1_000_000.0)
        self.bankroll.setDecimals(0)
        self.bankroll.setSingleStep(10.0)
        self.bankroll.setSuffix(" div")
        self.bankroll.setSpecialValueText("no limit")
        self.bankroll.setToolTip(
            "Divines you have to spend. Trades you can't afford are still listed, "
            "but the quantity is capped at what your bankroll reaches. "
            "0 means don't cap."
        )
        self.bankroll.valueChanged.connect(self.bankroll_changed)
        controls.addWidget(self.bankroll)

        controls.addSpacing(12)
        self.hide_ghosts = QCheckBox("Hide ghosts")
        self.hide_ghosts.setToolTip(BAND_TIP[Band.GHOST])
        self.hide_ghosts.toggled.connect(self._apply_filter)
        controls.addWidget(self.hide_ghosts)

        controls.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(200)
        self.search.textChanged.connect(self._apply_filter)
        controls.addWidget(self.search)
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
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
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
        for outcome, label, tip in (
            (Outcome.FILLED, "Traded", "The trade went through."),
            (Outcome.SOLD, "Already sold", "They replied that it's gone."),
            (Outcome.NO_REPLY, "No reply", "No response."),
            (Outcome.DECLINED, "Refused", "They replied but wouldn't honour the price."),
        ):
            btn = QPushButton(label)
            btn.setToolTip(tip + "  Recorded so the ranking can learn which listings fill.")
            btn.setEnabled(False)
            btn.clicked.connect(lambda _=False, o=outcome: self._report(o))
            bottom.addWidget(btn)
            self._outcome_btns[outcome] = btn

        self.status = QLabel()
        self.status.setStyleSheet(f"color: {muted_color(self)};")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, stretch=1)
        layout.addLayout(bottom)

        self.set_status(
            "No sweep yet. \"Find trades\" checks live listings against "
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

    def set_bankroll(self, divines: float) -> None:
        blocked = self.bankroll.blockSignals(True)
        self.bankroll.setValue(divines)
        self.bankroll.blockSignals(blocked)

    def set_running(self, running: bool) -> None:
        self.sweep_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    # --- content -----------------------------------------------------------

    def set_result(self, result) -> None:
        self._candidates = list(result.candidates)
        self._attempt_ids.clear()
        self._rechecked.clear()
        self._last_copied = None
        self._update_outcome_buttons()
        self._populate()
        plausible = sum(1 for c in self._candidates if c.band is Band.PLAUSIBLE)
        thin = sum(1 for c in self._candidates if c.band is Band.THIN)
        ghosts = sum(1 for c in self._candidates if c.band is Band.GHOST)
        best = max((c.profit_divines for c in self._candidates), default=0.0)
        parts = [
            f"{len(result.items)} items checked in {result.duration_s / 60:.0f} min",
            f"{result.listings_seen} live listings",
            f"{plausible} plausible · {thin} thin · {ghosts} ghost",
        ]
        if plausible:
            parts.append(f"best plausible trade +{self._best_plausible():.2f} div")
        elif best:
            parts.append("nothing in the plausible band this sweep")
        if result.errors:
            parts.append(f"{len(result.errors)} item(s) failed — see the Log tab")
        self.set_status("  ·  ".join(parts))

    def _best_plausible(self) -> float:
        return max(
            (c.profit_divines for c in self._candidates if c.band is Band.PLAUSIBLE),
            default=0.0,
        )

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
            age = listing.age_s()
            self.table.setItem(row, 9, NumericItem(_age(age, listing.afk), age or 0.0))
            self.table.setItem(row, 10, TextItem(listing.character or listing.account))
        self.table.setSortingEnabled(True)
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self.search.text().strip().lower()
        hide_ghosts = self.hide_ghosts.isChecked()
        for row in range(self.table.rowCount()):
            c = self._candidate_at(row)
            if c is None:
                continue
            hidden = False
            if hide_ghosts and c.band is Band.GHOST:
                hidden = True
            elif needle:
                haystack = f"{c.item_name} {c.listing.character or ''} {c.listing.account}"
                hidden = needle not in haystack.lower()
            self.table.setRowHidden(row, hidden)

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
        self.outcome_reported.emit(attempt_id, outcome)
        verdict = {
            Outcome.FILLED: "Recorded as traded",
            Outcome.SOLD: "Recorded as already sold",
            Outcome.NO_REPLY: "Recorded as no reply",
            Outcome.DECLINED: "Recorded as refused",
        }[outcome]
        self.set_status(f"{verdict} — {c.item_name} from {c.listing.character or c.listing.account}.")

    def note_attempt(self, candidate, attempt_id: str) -> None:
        """Remember which log row a copied whisper produced."""
        self._attempt_ids[candidate.key] = attempt_id
        self._update_outcome_buttons()

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
    return {"exalted": "ex", "divine": "div", "chaos": "chaos"}.get(currency, currency)


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
