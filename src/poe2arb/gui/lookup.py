"""What one item is worth, in a currency you choose.

Deliberately **not** an any-pair converter. It used to ask "how many X for one
Y?" for any two items in the economy, which quietly implied those two things
trade against each other. Almost none of them do: the Currency Exchange is
organised as items against a handful of currencies, so a Rune-for-Omen ratio is
arithmetic we performed, not a market anyone is making. Offering it invited
exactly the trade that cannot be executed.

So there is one item on one side, and on the other a denomination the Exchange
really quotes in. The four offered are the ones with enough depth for the answer
to mean anything.

Unaffected by the exclusion list on purpose: leaving something out of the sweep
shouldn't stop you looking its price up. Which source the number came from is
always stated, because a Currency Exchange price and a poe.ninja consensus price
are different claims and the gap between them is what this app trades on.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
)

from ..format import fmt_num
from ..market import Universe
from .item_picker import ItemPicker
from .theme import muted_color

# The denominations the Exchange actually quotes against, with the short suffix
# used everywhere else in the app. Ordered finest-value-first so the default
# lands on the one most prices are quoted in.
DENOMINATIONS = (
    ("exalted", "ex"),
    ("divine", "div"),
    ("chaos", "chaos"),
    ("annul", "annul"),
)


class QuickLookup(QGroupBox):
    """One item, one denomination, one number."""

    def __init__(self, parent=None):
        super().__init__("Quick Lookup", parent)
        self._universe: Universe | None = None
        self._base_id = "adaptive"

        outer = QVBoxLayout(self)

        row = QHBoxLayout()
        outer.addLayout(row)

        self.item_picker = ItemPicker("Choose an item…")
        self.item_picker.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.item_picker.selected.connect(lambda _: self._recalculate())
        row.addWidget(self.item_picker, stretch=3)

        worth = QLabel("is worth")
        worth.setStyleSheet(f"color: {muted_color(self)};")
        row.addWidget(worth)

        self.value = QLabel()
        self.value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        font = self.value.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self.value.setFont(font)
        row.addWidget(self.value, stretch=2)

        self.denomination = QComboBox()
        for currency, suffix in DENOMINATIONS:
            self.denomination.addItem(suffix, currency)
        self.denomination.setToolTip(
            "Which currency to price the item in.\n\n"
            "These four are the ones the Exchange has real depth in. Pick whichever\n"
            "makes the number easy to read — a cheap item in divine is all decimal\n"
            "places."
        )
        self.denomination.currentIndexChanged.connect(lambda _: self._recalculate())
        row.addWidget(self.denomination)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {muted_color(self)};")
        outer.addWidget(self.note)

        self._recalculate()

    # ------------------------------------------------------------------ inputs

    def set_icons(self, provider) -> None:
        self.item_picker.set_icons(provider)

    def set_universe(self, universe: Universe) -> None:
        self._universe = universe
        self.item_picker.rebuild(universe, self._base_id)
        self._recalculate()

    def set_base_currency(self, base_id: str) -> None:
        """Re-price the menu labels in the chosen unit."""
        self._base_id = base_id
        if self._universe is not None:
            self.item_picker.rebuild(self._universe, base_id)

    def denomination_id(self) -> str:
        return self.denomination.currentData()

    # ------------------------------------------------------------------ pricing

    def _recalculate(self) -> None:
        item_id = self.item_picker.current_id()
        denom_id = self.denomination_id()
        if self._universe is None:
            self._show_message("Loading economy data…")
            return
        if item_id is None:
            self._show_message("Pick an item.")
            return
        if item_id == denom_id:
            suffix = dict(DENOMINATIONS)[denom_id]
            self.value.setText(f"1 {suffix}")
            self.note.setText("That's the currency it's being priced in.")
            return

        rate = self._universe.convert(item_id, denom_id)
        if rate is None or rate <= 0:
            suffix = dict(DENOMINATIONS)[denom_id]
            self._show_message(f"No price for this item in {suffix}.")
            return

        suffix = dict(DENOMINATIONS)[denom_id]
        self.value.setText(f"{fmt_num(rate, 2)} {suffix}")
        self.note.setText(self._source_note(item_id, denom_id))

    def _source_note(self, item_id: str, denom_id: str) -> str:
        """Which price source this came from, and what it's worth.

        Both sides have to be Currency Exchange priced for the answer to be a
        Currency Exchange price — one CE price over one consensus price is
        neither.
        """
        priced = self._universe.ce_priced if self._universe is not None else frozenset()
        if item_id in priced and denom_id in priced:
            return (
                "In-game Currency Exchange price. Rarely-traded items have run "
                "well above what a sale actually fetches, so treat a thin item's "
                "figure as a ceiling. Fees and gold aren't included."
            )
        return (
            "poe.ninja consensus — a guide, not a live price. The Currency "
            "Exchange doesn't quote both sides of this, which usually means the "
            "item barely trades."
        )

    def _show_message(self, text: str) -> None:
        self.value.setText("—")
        self.note.setText(text)
