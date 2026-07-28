"""Quick pay/receive lookup, laid out like the in-game Currency Exchange.

Answers "how many of X for one Y" for every item in the economy — not just the
handful the arbitrage scan trades. Deliberately unaffected by the exclusion
list: excluding something from the scan shouldn't stop you looking up its price.

Two sources, in order of preference:
  1. the live order book, where the last scan happened to cover the pair — a
     rate someone is actually offering right now;
  2. poe.ninja's consensus values, which cover everything but describe what a
     pair is *worth*, not what it will fill at.
Which one produced the number is always stated, because the difference between
them is the whole point of this app.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from ..format import fmt_num
from ..graph import Edge
from ..market import Universe
from .item_picker import ItemPicker
from .theme import muted_color

# Past this, "from the last scan" is overstating it — the book has moved.
LIVE_RATE_MAX_AGE_MINUTES = 45.0


def ratio_parts(want_per_have: float) -> tuple[float, float]:
    """Normalise a rate to an `x : y` pair with the smaller side at exactly 1.

    The in-game exchange states ratios this way, and it reads far better than
    two decimals of a fraction: "94 : 1" rather than "1 : 0.0106".
    """
    if want_per_have >= 1.0:
        return want_per_have, 1.0
    return 1.0, 1.0 / want_per_have


def fmt_age(fetched_at: datetime | None) -> str:
    """'4 minutes ago' — or empty when there's no timestamp to report."""
    if fetched_at is None:
        return ""
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    minutes = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 60.0
    if minutes < 1.5:
        return "just now"
    if minutes < 90:
        return f"{round(minutes)} minutes ago"
    return f"{round(minutes / 60)} hours ago"


class QuickLookup(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Quick Lookup", parent)
        self._universe: Universe | None = None
        self._base_id = "adaptive"
        self._edges: dict[tuple[str, str], Edge] = {}
        self._edges_at: datetime | None = None

        outer = QVBoxLayout(self)
        grid = QGridLayout()
        outer.addLayout(grid)

        # Want on the left, have on the right, ratio between them — the same
        # arrangement as the game's Currency Exchange, so the muscle memory
        # carries over.
        self.want_picker = ItemPicker("Choose what you want…")
        self.have_picker = ItemPicker("Choose what you have…")
        for picker in (self.want_picker, self.have_picker):
            picker.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            picker.selected.connect(lambda _: self._recalculate())

        grid.addWidget(self._heading("I Want"), 0, 0)
        grid.addWidget(self._heading("Market Ratio"), 0, 1)
        grid.addWidget(self._heading("I Have"), 0, 2)

        grid.addWidget(self.want_picker, 1, 0)
        self.ratio = QLabel()
        self.ratio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ratio.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = self.ratio.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        self.ratio.setFont(font)
        grid.addWidget(self.ratio, 1, 1)
        grid.addWidget(self.have_picker, 1, 2)

        self.swap = QPushButton("⇅  Swap")
        self.swap.setToolTip("Swap the two sides")
        self.swap.clicked.connect(self._swap)
        grid.addWidget(self.swap, 2, 1, alignment=Qt.AlignmentFlag.AlignCenter)

        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 3)

        self.detail = QLabel()
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.detail)

        self.note = QLabel()
        self.note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.note.setWordWrap(True)
        self.note.setStyleSheet(f"color: {muted_color(self)};")
        outer.addWidget(self.note)

        self._recalculate()

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    # ------------------------------------------------------------------ inputs

    def set_universe(self, universe: Universe) -> None:
        self._universe = universe
        self.want_picker.rebuild(universe, self._base_id)
        self.have_picker.rebuild(universe, self._base_id)
        self._recalculate()

    def set_base_currency(self, base_id: str) -> None:
        """Re-price the menu labels in the chosen unit."""
        self._base_id = base_id
        if self._universe is not None:
            self.want_picker.rebuild(self._universe, base_id)
            self.have_picker.rebuild(self._universe, base_id)

    def set_edges(
        self, edges: dict[tuple[str, str], Edge], fetched_at: datetime | None = None
    ) -> None:
        """Supply the last scan's order book, so lookups can prefer live rates."""
        self._edges = edges or {}
        self._edges_at = fetched_at
        self._recalculate()

    def _swap(self) -> None:
        want, have = self.want_picker.current_id(), self.have_picker.current_id()
        self.want_picker.set_current(have)
        self.have_picker.set_current(want)
        self._recalculate()

    # ------------------------------------------------------------------ pricing

    def _stale(self) -> bool:
        """True once the stored book is too old to call a live rate."""
        if self._edges_at is None:
            return False  # no timestamp offered; trust the caller
        at = self._edges_at
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        minutes = (datetime.now(timezone.utc) - at).total_seconds() / 60.0
        return minutes > LIVE_RATE_MAX_AGE_MINUTES

    def live_rate(self, have_id: str, want_id: str) -> float | None:
        """Book rate for this direction, if a recent scan priced it.

        The book rate before fees, which is what the pair is being offered at —
        the margin-adjusted number belongs to the profit calculation, not to a "what
        is this worth" lookup.
        """
        if not self._edges or self._stale():
            return None
        edge = self._edges.get((have_id, want_id))
        return edge.raw_rate if edge is not None and edge.raw_rate > 0 else None

    def _recalculate(self) -> None:
        want_id = self.want_picker.current_id()
        have_id = self.have_picker.current_id()
        if self._universe is None:
            self._show_message("Loading economy data…")
            return
        if want_id is None or have_id is None:
            self._show_message("Pick something on both sides.")
            return
        if want_id == have_id:
            self._show_message("Those are the same item.")
            return

        live = self.live_rate(have_id, want_id)
        rate = live if live is not None else self._universe.convert(have_id, want_id)
        if rate is None or rate <= 0:
            self._show_message("No price available for that pair.")
            return

        want = self._universe.get(want_id)
        have = self._universe.get(have_id)
        left, right = ratio_parts(rate)
        self.ratio.setText(f"{fmt_num(left, 2)} : {fmt_num(right, 2)}")
        self.detail.setText(
            f"<b>1 {have.name}</b> gets you <b>{fmt_num(rate, 2)} {want.name}</b>"
            f" &nbsp;·&nbsp; "
            f"<b>1 {want.name}</b> costs <b>{fmt_num(1.0 / rate, 2)} {have.name}</b>"
        )
        self.note.setText(self._source_note(live is not None))

    def _source_note(self, is_live: bool) -> str:
        if is_live:
            age = fmt_age(self._edges_at)
            when = f" from the scan {age}" if age else " from the last scan"
            return (
                f"Live order-book rate{when} — what people are actually offering, "
                f"at the fill depth you configured. Exchange fees aren't included."
            )
        return (
            "poe.ninja fair value — a guide, not a live offer. Real trades fill "
            "at whatever people are listing. Scan the pair for a live rate."
        )

    def _show_message(self, text: str) -> None:
        self.ratio.setText("—")
        self.detail.setText(text)
        self.note.setText("")
