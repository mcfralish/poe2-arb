"""Quick Lookup: which price source wins, and how the ratio reads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2arb.client import NinjaOverview  # noqa: E402
from poe2arb.graph import Edge  # noqa: E402
from poe2arb.gui.lookup import (  # noqa: E402
    LIVE_RATE_MAX_AGE_MINUTES,
    QuickLookup,
    fmt_age,
    ratio_parts,
)
from poe2arb.market import merge_overviews  # noqa: E402

NOW = datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def universe():
    overview = NinjaOverview(
        league="T", fetched_at=NOW,
        values={"divine": 1.0, "chaos": 0.1, "mirror": 4886.0},
        volumes={"divine": 1.0, "chaos": 1.0, "mirror": 1.0},
        names={"divine": "Divine Orb", "chaos": "Chaos Orb",
               "mirror": "Mirror of Kalandra"},
    )
    return merge_overviews("T", NOW, {"Currency": overview})


@pytest.fixture
def lookup(app, universe):
    widget = QuickLookup()
    widget.set_universe(universe)
    return widget


def ask(lookup, have, want):
    lookup.have_picker.set_current(have)
    lookup.want_picker.set_current(want)
    return lookup


class TestRatioParts:
    def test_larger_side_carries_the_number(self):
        assert ratio_parts(10.0) == (10.0, 1.0)

    def test_fractions_are_inverted_rather_than_shown_as_decimals(self):
        """"1 : 0.0106" is unreadable; "94.3 : 1" is the same fact."""
        left, right = ratio_parts(1 / 94.3)
        assert right == pytest.approx(94.3)
        assert left == 1.0

    def test_parity(self):
        assert ratio_parts(1.0) == (1.0, 1.0)


class TestAge:
    def test_no_timestamp(self):
        assert fmt_age(None) == ""

    def test_just_now(self):
        assert fmt_age(datetime.now(timezone.utc)) == "just now"

    def test_minutes(self):
        assert fmt_age(datetime.now(timezone.utc) - timedelta(minutes=12)) == (
            "12 minutes ago"
        )

    def test_hours(self):
        assert fmt_age(datetime.now(timezone.utc) - timedelta(hours=3)) == "3 hours ago"

    def test_naive_timestamp_treated_as_utc(self):
        """History timestamps round-trip through isoformat; don't crash on one."""
        naive = datetime.now(timezone.utc).replace(tzinfo=None)
        assert fmt_age(naive) == "just now"


class TestSourcePreference:
    def test_falls_back_to_ninja_without_a_book(self, lookup):
        ask(lookup, "divine", "chaos")
        assert lookup.live_rate("divine", "chaos") is None
        assert "poe.ninja" in lookup.note.text()
        assert lookup.ratio.text() == "10.00 : 1.00"

    def test_live_book_rate_wins(self, lookup):
        """The whole point of the app is that the book differs from consensus."""
        lookup.set_edges(
            {("divine", "chaos"): Edge("divine", "chaos", 8.7, 8.8, 40.0)}, NOW
        )
        ask(lookup, "divine", "chaos")
        assert lookup.live_rate("divine", "chaos") == 8.8
        assert lookup.ratio.text() == "8.80 : 1.00"

    def test_live_source_is_named(self, lookup):
        lookup.set_edges(
            {("divine", "chaos"): Edge("divine", "chaos", 8.7, 8.8, 40.0)}, NOW
        )
        ask(lookup, "divine", "chaos")
        assert "order-book" in lookup.note.text()
        assert "poe.ninja" not in lookup.note.text()

    def test_book_rate_used_not_the_after_fee_rate(self, lookup):
        """A lookup asks what a pair is offered at, not what a loop nets."""
        lookup.set_edges(
            {("divine", "chaos"): Edge("divine", "chaos", 8.7, 8.8, 40.0)}, NOW
        )
        assert lookup.live_rate("divine", "chaos") == 8.8

    def test_stale_book_is_not_called_live(self, lookup):
        old = NOW - timedelta(minutes=LIVE_RATE_MAX_AGE_MINUTES + 10)
        lookup.set_edges(
            {("divine", "chaos"): Edge("divine", "chaos", 8.7, 8.8, 40.0)}, old
        )
        ask(lookup, "divine", "chaos")
        assert lookup.live_rate("divine", "chaos") is None
        assert "poe.ninja" in lookup.note.text()

    def test_direction_matters(self, lookup):
        """An edge is directed: a book for div->chaos says nothing about chaos->div."""
        lookup.set_edges(
            {("divine", "chaos"): Edge("divine", "chaos", 8.7, 8.8, 40.0)}, NOW
        )
        assert lookup.live_rate("chaos", "divine") is None

    def test_uncovered_pair_falls_back(self, lookup):
        lookup.set_edges(
            {("divine", "chaos"): Edge("divine", "chaos", 8.7, 8.8, 40.0)}, NOW
        )
        ask(lookup, "divine", "mirror")
        assert "poe.ninja" in lookup.note.text()


class TestDisplay:
    def test_both_directions_are_spelled_out(self, lookup):
        ask(lookup, "divine", "chaos")
        assert "1 Divine Orb" in lookup.detail.text()
        assert "1 Chaos Orb" in lookup.detail.text()

    def test_prompts_until_both_sides_chosen(self, lookup):
        lookup.have_picker.set_current("divine")
        assert "both sides" in lookup.detail.text()

    def test_same_item_is_rejected(self, lookup):
        ask(lookup, "chaos", "chaos")
        assert "same item" in lookup.detail.text()

    def test_swap_exchanges_the_sides(self, lookup):
        ask(lookup, "divine", "chaos")
        lookup._swap()
        assert lookup.have_picker.current_id() == "chaos"
        assert lookup.want_picker.current_id() == "divine"
        # The ratio reads left-to-right in the same order as the columns:
        # want (divine) on the left, have (chaos) on the right.
        assert lookup.ratio.text() == "1.00 : 10.00"

    def test_exclusions_are_irrelevant_here(self, lookup, universe):
        """Excluding something from the scan must not stop you pricing it."""
        lookup.set_edges({}, NOW)
        ask(lookup, "divine", "mirror")
        assert "4,886" in lookup.ratio.text() or "4886" in lookup.ratio.text()
