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
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .theme import muted_color

# The two currencies sellers actually quote in. Anything else is unconstrained.
POTS = (
    ("divine", "div", 10.0),
    ("exalted", "ex", 500.0),
)

# Every string the appetite readout can show. Its width is sized to the longest
# of these rather than to a guessed pixel count, so the label cannot be clipped
# by a wider font or a higher DPI.
_APPETITE_LABELS = ("proven only", "profit only", "100%")


def _fits(widget, *texts: str, padding: int = 0) -> int:
    """Width in pixels that holds the longest of `texts` in `widget`'s font."""
    metrics = QFontMetrics(widget.font())
    return max(metrics.horizontalAdvance(t) for t in texts) + padding


class BankrollBar(QWidget):
    """A spin box per currency. 0 means "don't cap this one"."""

    changed = Signal(str, float)          # (currency id, units held)
    appetite_changed = Signal(float)      # 0.0 (proven only) .. 1.0 (profit only)
    settlement_changed = Signal(str)      # currency id sales are priced in

    def __init__(self, parent=None):
        super().__init__(parent)
        # Two rows, and normally only the first has anything in it. The money
        # controls and the long-shots slider do not both fit at the window's
        # minimum width, and something has to give: overflowing clipped the
        # right-hand end of the row, and letting the spin boxes shrink truncated
        # "no limit (div)" to "no limit (di…" — which is exactly the state the
        # denomination in that string exists to disambiguate (reported from the
        # field 2026-07-31). So the slider drops to its own line instead. See
        # `_reflow`.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)
        self._top = QHBoxLayout()
        self._top.setContentsMargins(0, 0, 0, 0)
        self._bottom = QHBoxLayout()
        self._bottom.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self._top)
        outer.addLayout(self._bottom)

        self.money = QWidget()
        layout = QHBoxLayout(self.money)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Bankroll:"))

        self.spins: dict[str, QDoubleSpinBox] = {}
        for currency, suffix, step in POTS:
            spin = QDoubleSpinBox()
            spin.setRange(0.0, 100_000_000.0)
            spin.setDecimals(0)
            spin.setSingleStep(step)
            spin.setSuffix(f" {suffix}")
            # The special text replaces the *whole* display, suffix included, so
            # a plain "no limit" left the two boxes identical and there was no
            # way to tell which one was divine (reported from the field
            # 2026-07-30). Naming the denomination keeps them distinguishable in
            # exactly the state where the number can't do it.
            spin.setSpecialValueText(f"no limit ({suffix})")
            spin.setToolTip(
                f"How many {currency} orbs you have to spend.\n\n"
                f"This only limits listings that ask to be paid in {currency} — "
                f"sellers wanting something else\nare unaffected, because you "
                f"can't pay them out of this pot. Set it to 0 for no limit."
            )
            spin.valueChanged.connect(
                lambda held, c=currency: self.changed.emit(c, held)
            )
            self.spins[currency] = spin
            layout.addWidget(spin)

        # No "committed" readout. v0.6.0 held outstanding whispers back from the
        # bankroll and showed what they had claimed; reverted 2026-07-31 because
        # at a ~2-21% fill rate the money is almost never actually spent, so the
        # holdback suppressed more real trades than it prevented double-spends.

        layout.addSpacing(10)
        layout.addWidget(QLabel("Settle in:"))
        # Here rather than in Settings because it changes every Profit figure
        # in the table below by a large factor — exalted is ~432x finer than
        # divine, so far less is lost rounding down to a whole unit.
        self.settlement = QComboBox()
        for currency, suffix, _ in POTS:
            self.settlement.addItem(currency, currency)
        self.settlement.setToolTip(
            "What you ask to be paid in when you resell on the Currency Exchange.\n"
            "This changes every Profit figure below.\n\n"
            "Exalted: you keep more, because payment can be split into much\n"
            "smaller amounts and less is lost rounding down.\n\n"
            "Divine: the cautious figure — and far cheaper in gold. The Exchange\n"
            "charges gold per orb traded, so taking thousands of exalted instead\n"
            "of a few divine can cost tens of times more gold and leave you unable\n"
            "to trade at all."
        )
        self.settlement.currentIndexChanged.connect(
            lambda _: self.settlement_changed.emit(self.settlement.currentData())
        )
        layout.addWidget(self.settlement)

        self.long_shots = QWidget()
        shots = QHBoxLayout(self.long_shots)
        shots.setContentsMargins(0, 0, 0, 0)
        shots.addWidget(QLabel("Long shots:"))
        # A slider, not a number: this is a taste, and no one has a considered
        # opinion about whether their appetite is 0.35 or 0.4.
        self.appetite = QSlider(Qt.Orientation.Horizontal)
        self.appetite.setRange(0, 100)
        self.appetite.setFixedWidth(90)
        self.appetite.setToolTip(
            "How far to chase big discounts that rarely fill.\n"
            "Left: rank by what actually fills — long shots sink to the bottom "
            "and are kept out of the queue.\n"
            "Right: rank on profit alone — the 12x listings come first.\n"
            "Nothing is ever hidden either way; only the order changes."
        )
        self.appetite.valueChanged.connect(self._appetite_moved)
        shots.addWidget(self.appetite)

        self.appetite_label = QLabel()
        self.appetite_label.setStyleSheet(f"color: {muted_color(self)};")
        # Sized to its own longest string and pinned there. A minimum width alone
        # let the layout hand the slider the slack and clip the readout instead,
        # which is what put "45%" half under the slider on a narrow window.
        # Left-aligned within that width: right-aligned, a short reading like
        # "45%" sat at the far end of the box with a finger's width of nothing
        # between it and the slider it belongs to.
        self.appetite_label.setFixedWidth(_fits(self.appetite_label, *_APPETITE_LABELS, padding=6))
        self.appetite_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        shots.addWidget(self.appetite_label)
        self._refresh_appetite_label()

        self._top.addWidget(self.money)
        self._top.addStretch(1)
        self._bottom.addStretch(1)
        self._wrapped = False
        self._top.addWidget(self.long_shots)
        self._size_spins()

    # -- layout

    def _size_spins(self) -> None:
        """Pin each spin box wide enough for its own longest text.

        Measured after the widget is polished, and taken as the larger of what
        the text needs and what the style asks for: computing it at construction
        from the default font under-measured on Windows, where the box inherits
        a wider font from the window and the frame plus the up/down buttons cost
        more than the padding guessed here.
        """
        for currency, suffix, _step in POTS:
            spin = self.spins[currency]
            spin.ensurePolished()
            spin.setMinimumWidth(
                max(
                    _fits(spin, f"no limit ({suffix})", f"100000000 {suffix}", padding=44),
                    spin.sizeHint().width(),
                )
            )

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        from PySide6.QtCore import QEvent

        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._size_spins()
            self._reflow()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        """Drop the long-shots slider onto its own row when the row won't hold it.

        Decided from the two groups' size hints rather than from their current
        geometry, so the answer doesn't depend on which row they are in and the
        two states can't oscillate.
        """
        needed = (
            self.money.sizeHint().width() + self.long_shots.sizeHint().width() + 24
        )
        wrapped = self.width() < needed
        if wrapped == self._wrapped:
            return
        self._wrapped = wrapped
        (self._top if wrapped else self._bottom).removeWidget(self.long_shots)
        (self._bottom if wrapped else self._top).addWidget(self.long_shots)
        self.long_shots.setVisible(True)

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
