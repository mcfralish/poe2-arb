"""What one item is worth, in a currency you choose — either way round.

Deliberately **not** an any-pair converter. It used to ask "how many X for one
Y?" for any two items in the economy, which quietly implied those two things
trade against each other. Almost none of them do: the Currency Exchange is
organised as items against a handful of currencies, so a Rune-for-Omen ratio is
arithmetic we performed, not a market anyone is making. Offering it invited
exactly the trade that cannot be executed.

So there is one item on one side, and on the other a denomination the Exchange
really quotes in. The four offered are the ones with enough depth for the answer
to mean anything.

What **is** swappable is which side is the unit, because both questions are real
and only one of them was answerable:

    1 Omen of Whittling  is worth  0.42 div      (how much do I get for it?)
    1 div                is worth  2.4 omens     (how many can I buy?)

Both are the same ratio, and both are the same trade — the denomination stays a
denomination whichever end it is on, so this does not reopen the any-pair
converter. Restored 2026-07-31 after the field test: sizing a purchase means
asking how many of something a divine buys, and inverting a small decimal in
your head mid-map is exactly the sort of arithmetic this panel exists to avoid.

Unaffected by the exclusion list on purpose: leaving something out of the sweep
shouldn't stop you looking its price up. Which source the number came from is
always stated, because a Currency Exchange price and a poe.ninja consensus price
are different claims and the gap between them is what this app trades on.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from ..format import currency_label, fmt_num
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
    """One item, one denomination, one number — in either direction."""

    def __init__(self, parent=None):
        super().__init__("Quick Lookup", parent)
        self._universe: Universe | None = None
        self._base_id = "adaptive"
        # False: "<item> is worth N <denom>".  True: "1 <denom> is worth N <item>".
        self._inverted = False

        outer = QVBoxLayout(self)

        row = QHBoxLayout()
        outer.addLayout(row)

        self.item_picker = ItemPicker("Choose an item…")
        self.item_picker.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.item_picker.selected.connect(lambda _: self._recalculate())

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

        # The row reads as a sentence: "1 <thing> is worth <number> <other>".
        # The leading 1 never moves — whichever side is currently the unit sits
        # directly after it — and without it the inverted form read as "ex is
        # worth 0.00033 Omen of Whittling", which names no quantity at all.
        self.one = QLabel("1")
        self.one.setStyleSheet(f"color: {muted_color(self)};")

        # "is worth" sits between the two sides and stays there when they swap,
        # so the sentence reads left to right whichever way round it is. Given
        # slack of its own and centred in it, rather than butting up against
        # whichever widget happens to be to its left.
        self.worth = QLabel("is worth")
        self.worth.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.worth.setStyleSheet(f"color: {muted_color(self)};")

        self.swap = QPushButton("⇄")
        self.swap.setFixedWidth(32)
        self.swap.setToolTip(
            "Swap the two sides.\n\n"
            "One way answers 'what will this fetch me?'; the other answers 'how\n"
            "many of these does one buy?'. Same ratio, and the currency stays the\n"
            "currency either way — this is not a general any-pair converter,\n"
            "because most pairs don't trade against each other."
        )
        self.swap.clicked.connect(self._toggle_direction)

        # Built once, re-ordered on swap: rebuilding the row would destroy the
        # picker's current selection, which is the one thing that must survive.
        self._row = row
        row.addWidget(self.swap)
        row.addWidget(self.one)
        self._lay_out_row()

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {muted_color(self)};")
        # A wrapped label reports one line as its minimum, so dragging the
        # splitter down clipped the source note to a sliver — and that note is
        # the part saying whether the number is a live Exchange price or a
        # consensus guess, which is the whole difference between a figure you
        # can trade on and one you can't. Three lines is what the longer of the
        # two notes wraps to at this panel's usual width.
        self.note.setMinimumHeight(QFontMetrics(self.note.font()).lineSpacing() * 3)
        outer.addWidget(self.note)
        # Keeps the row and note at the top when the pane is dragged taller,
        # rather than floating them apart.
        outer.addStretch(1)
        # Grow freely, shrink no further than the two rows above need. Paired
        # with the splitter refusing to collapse this pane, it is what pins the
        # panel to a readable minimum at the bottom of the tab.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        self._recalculate()

    # ------------------------------------------------------------------ layout

    def _lay_out_row(self) -> None:
        """Put the two sides either side of "is worth", current direction first.

        Slots 2..5 of the row, after the swap button and the leading "1":
        unit, "is worth", the number, then the thing the number counts. Only
        which of the picker and the denomination lands in slot 2 changes.
        """
        moving = (self.item_picker, self.worth, self.value, self.denomination)
        for widget in moving:
            self._row.removeWidget(widget)
        # "1 <denom> is worth N <item>" when inverted; "1 <item> is worth N
        # <denom>" otherwise. Stretch follows the widget, not the slot: the
        # picker needs the room wherever it sits, the combo never does.
        unit, counted = (
            (self.denomination, self.item_picker)
            if self._inverted
            else (self.item_picker, self.denomination)
        )
        self._row.insertWidget(2, unit, 3 if unit is self.item_picker else 0)
        self._row.insertWidget(3, self.worth, 1)
        self._row.insertWidget(4, self.value, 2)
        self._row.insertWidget(5, counted, 3 if counted is self.item_picker else 0)
        for widget in moving:
            widget.show()

    def _toggle_direction(self) -> None:
        self._inverted = not self._inverted
        self._lay_out_row()
        self._recalculate()

    @property
    def inverted(self) -> bool:
        return self._inverted

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
        suffix = currency_label(denom_id)
        if item_id == denom_id:
            self.value.setText("1" if self._inverted else f"1 {suffix}")
            self.note.setText("That's the currency it's being priced in.")
            return

        # Always priced item-in-denomination; inverting is one reciprocal rather
        # than a second conversion, so the two directions cannot disagree.
        rate = self._universe.convert(item_id, denom_id)
        if rate is None or rate <= 0:
            self._show_message(f"No price for this item in {suffix}.")
            return

        if self._inverted:
            self.value.setText(fmt_num(1.0 / rate, 2))
        else:
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
