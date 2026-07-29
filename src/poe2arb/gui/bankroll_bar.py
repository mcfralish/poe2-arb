"""What you have to spend, what you settle in, and how far to chase long shots.

The three controls that decide which trades you are shown, sitting above the
trades themselves rather than behind a Settings dialog — each one changes the
list underneath it, and that connection is invisible from a modal.

The bankroll is per currency because one pooled divine figure was wrong.
Sellers ask for divines or for exalted, and you can only pay in what you hold —
converting between them on the Currency Exchange costs the spread, so "500
divines" does not mean "216,000 exalted available". Each pot caps only the
listings priced in that currency.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QWidget,
)

from .theme import muted_color

# The two currencies sellers actually quote in. Anything else is unconstrained.
POTS = (
    ("divine", "div", 10.0),
    ("exalted", "ex", 500.0),
)


class BankrollBar(QWidget):
    """A spin box per currency. 0 means "don't cap this one"."""

    changed = Signal(str, float)          # (currency id, units held)
    appetite_changed = Signal(float)      # 0.0 (proven only) .. 1.0 (profit only)
    settlement_changed = Signal(str)      # currency id sales are priced in

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Bankroll:"))

        self.spins: dict[str, QDoubleSpinBox] = {}
        for currency, suffix, step in POTS:
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 100_000_000.0)
            spin.setDecimals(0)
            spin.setSingleStep(step)
            spin.setSuffix(f" {suffix}")
            spin.setSpecialValueText("no limit")
            spin.setToolTip(
                f"How many {currency} orbs you have to spend. Caps the quantity "
                f"on listings priced in {currency} only — sellers wanting a "
                f"different currency are unaffected. 0 means don't cap."
            )
            spin.valueChanged.connect(
                lambda held, c=currency: self.changed.emit(c, held)
            )
            self.spins[currency] = spin
            layout.addWidget(spin)

        layout.addSpacing(12)
        layout.addWidget(QLabel("Settle in:"))
        # Here rather than in Settings because it changes every Profit figure
        # in the table below by a large factor — exalted is ~432x finer than
        # divine, so far less is lost rounding down to a whole unit.
        self.settlement = QComboBox()
        for currency, suffix, _ in POTS:
            self.settlement.addItem(currency, currency)
        self.settlement.setToolTip(
            "What you take payment in when you resell on the Currency Exchange.\n"
            "Exalted is about 432x finer than divine, so much less profit is\n"
            "lost rounding down to a whole unit. Divine prices the pessimistic\n"
            "case. Changes every Profit figure below."
        )
        self.settlement.currentIndexChanged.connect(
            lambda _: self.settlement_changed.emit(self.settlement.currentData())
        )
        layout.addWidget(self.settlement)

        layout.addStretch(1)

        layout.addWidget(QLabel("Long shots:"))
        # A slider, not a number: this is a taste, and no one has a considered
        # opinion about whether their appetite is 0.35 or 0.4.
        self.appetite = QSlider(Qt.Orientation.Horizontal)
        self.appetite.setRange(0, 100)
        self.appetite.setFixedWidth(110)
        self.appetite.setToolTip(
            "How far to chase big discounts that rarely fill.\n"
            "Left: rank by what actually fills — long shots sink to the bottom "
            "and are kept out of the queue.\n"
            "Right: rank on profit alone — the 12x listings come first.\n"
            "Nothing is ever hidden either way; only the order changes."
        )
        self.appetite.valueChanged.connect(self._appetite_moved)
        layout.addWidget(self.appetite)

        self.appetite_label = QLabel()
        self.appetite_label.setStyleSheet(f"color: {muted_color(self)};")
        self.appetite_label.setMinimumWidth(70)
        layout.addWidget(self.appetite_label)
        self._refresh_appetite_label()

    def set_values(self, held: dict[str, float]) -> None:
        """Load saved amounts without reporting them back as user edits."""
        for currency, spin in self.spins.items():
            blocked = spin.blockSignals(True)
            spin.setValue(held.get(currency, 0.0))
            spin.blockSignals(blocked)

    def values(self) -> dict[str, float]:
        return {c: spin.value() for c, spin in self.spins.items()}

    # -- settlement currency

    def set_settlement(self, currency: str) -> None:
        index = self.settlement.findData(currency)
        if index < 0:
            return
        blocked = self.settlement.blockSignals(True)
        self.settlement.setCurrentIndex(index)
        self.settlement.blockSignals(blocked)

    def settlement_currency(self) -> str:
        return self.settlement.currentData()

    # -- risk appetite

    def set_appetite(self, appetite: float) -> None:
        blocked = self.appetite.blockSignals(True)
        self.appetite.setValue(int(round(min(1.0, max(0.0, appetite)) * 100)))
        self.appetite.blockSignals(blocked)
        self._refresh_appetite_label()

    def appetite_value(self) -> float:
        return self.appetite.value() / 100.0

    def _appetite_moved(self, _value: int) -> None:
        self._refresh_appetite_label()
        self.appetite_changed.emit(self.appetite_value())

    def _refresh_appetite_label(self) -> None:
        appetite = self.appetite_value()
        if appetite == 0.0:
            self.appetite_label.setText("proven only")
        elif appetite >= 1.0:
            self.appetite_label.setText("profit only")
        else:
            self.appetite_label.setText(f"{appetite:.0%}")
