"""Quick Lookup: which price source wins, and how the ratio reads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2arb.client import NinjaOverview  # noqa: E402
from poe2arb.gui.lookup import QuickLookup, ratio_parts  # noqa: E402
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


class TestPriceSource:
    """Currency Exchange where it prices the pair, poe.ninja consensus otherwise.

    Both sides have to be CE-priced: one CE price against one consensus price
    is a ratio between two different markets, which is not a rate at all.
    """

    def test_it_falls_back_to_consensus_and_says_so(self, lookup):
        ask(lookup, "divine", "chaos")
        assert "poe.ninja" in lookup.note.text()
        assert lookup.ratio.text() == "10.00 : 1.00"

    def test_a_ce_priced_pair_is_named_as_such(self, lookup, universe):
        lookup.set_universe(universe.with_ce_prices({"divine": 1.0, "chaos": 0.2}))
        ask(lookup, "divine", "chaos")
        assert "Currency Exchange" in lookup.note.text()
        assert "poe.ninja" not in lookup.note.text()

    def test_the_ce_price_is_the_one_used(self, lookup, universe):
        lookup.set_universe(universe.with_ce_prices({"divine": 1.0, "chaos": 0.2}))
        ask(lookup, "divine", "chaos")
        assert lookup.ratio.text() == "5.00 : 1.00"

    def test_half_a_ce_pair_is_not_a_ce_rate(self, lookup, universe):
        """Mixing the two markets gives a number belonging to neither."""
        lookup.set_universe(universe.with_ce_prices({"chaos": 0.2}))
        ask(lookup, "divine", "chaos")
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
        """Excluding something from the sweep must not stop you pricing it."""
        ask(lookup, "divine", "mirror")
        assert "4,886" in lookup.ratio.text() or "4886" in lookup.ratio.text()
