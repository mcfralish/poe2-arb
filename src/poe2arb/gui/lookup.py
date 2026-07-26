"""Quick pay/receive lookup, driven by poe.ninja values.

Answers "how many of X for one Y" from the consensus price data, which covers
every item in the economy — not just the handful the arbitrage scan trades.
Deliberately unaffected by the exclusion list: excluding something from the
scan shouldn't stop you looking up its price.

These are poe.ninja's consensus values, not live order-book quotes, so the
answer is a fair-value estimate rather than a fillable price.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..format import fmt_num
from ..market import Universe
from .item_picker import ItemPicker


class QuickLookup(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Quick lookup", parent)
        self._universe: Universe | None = None
        self._base_id = "divine"

        outer = QVBoxLayout(self)
        grid = QGridLayout()
        outer.addLayout(grid)

        self.pay_picker = ItemPicker("Choose what you pay…")
        self.receive_picker = ItemPicker("Choose what you want…")
        for picker in (self.pay_picker, self.receive_picker):
            picker.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            picker.selected.connect(lambda _: self._recalculate())

        grid.addWidget(QLabel("I pay"), 0, 0)
        grid.addWidget(self.pay_picker, 0, 1)
        swap = QPushButton("⇅")
        swap.setToolTip("Swap the two sides")
        swap.setFixedWidth(32)
        swap.clicked.connect(self._swap)
        grid.addWidget(swap, 0, 2, 2, 1)
        grid.addWidget(QLabel("I receive"), 1, 0)
        grid.addWidget(self.receive_picker, 1, 1)
        grid.setColumnStretch(1, 1)

        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.result)

        self.note = QLabel(
            "Fair value from poe.ninja — a guide, not a live offer. Real trades "
            "fill at whatever people are actually listing."
        )
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray;")
        outer.addWidget(self.note)

        self._recalculate()

    def set_universe(self, universe: Universe) -> None:
        self._universe = universe
        self.pay_picker.rebuild(universe, self._base_id)
        self.receive_picker.rebuild(universe, self._base_id)
        self._recalculate()

    def set_base_currency(self, base_id: str) -> None:
        """Re-price the menu labels in the chosen unit."""
        self._base_id = base_id
        if self._universe is not None:
            self.pay_picker.rebuild(self._universe, base_id)
            self.receive_picker.rebuild(self._universe, base_id)

    def _swap(self) -> None:
        pay, receive = self.pay_picker.current_id(), self.receive_picker.current_id()
        self.pay_picker.set_current(receive)
        self.receive_picker.set_current(pay)
        self._recalculate()

    def _recalculate(self) -> None:
        pay_id = self.pay_picker.current_id()
        receive_id = self.receive_picker.current_id()
        if self._universe is None:
            self.result.setText("Loading economy data…")
            return
        if pay_id is None or receive_id is None:
            self.result.setText("Pick something on both sides.")
            return
        if pay_id == receive_id:
            self.result.setText("Those are the same item.")
            return

        rate = self._universe.convert(pay_id, receive_id)
        if rate is None or rate <= 0:
            self.result.setText("No price available for that pair.")
            return

        pay = self._universe.get(pay_id)
        receive = self._universe.get(receive_id)
        inverse = 1.0 / rate
        self.result.setText(
            f"<b>1 {pay.name}</b> is worth <b>{fmt_num(rate, 2)} {receive.name}</b>"
            f"<br><b>1 {receive.name}</b> is worth <b>{fmt_num(inverse, 2)} {pay.name}</b>"
        )
