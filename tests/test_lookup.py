"""Quick Lookup: one item, one denomination, and which price source answered."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2arb.client import NinjaOverview  # noqa: E402
from poe2arb.gui.lookup import DENOMINATIONS, QuickLookup  # noqa: E402
from poe2arb.market import merge_overviews  # noqa: E402

NOW = datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def universe():
    overview = NinjaOverview(
        league="T", fetched_at=NOW,
        values={"divine": 1.0, "chaos": 0.1, "exalted": 0.0025, "mirror": 4886.0},
        volumes={"divine": 1.0, "chaos": 1.0, "exalted": 1.0, "mirror": 1.0},
        names={"divine": "Divine Orb", "chaos": "Chaos Orb",
               "exalted": "Exalted Orb", "mirror": "Mirror of Kalandra"},
    )
    return merge_overviews("T", NOW, {"Currency": overview})


@pytest.fixture
def lookup(app, universe):
    widget = QuickLookup()
    widget.set_universe(universe)
    return widget


def ask(lookup, item, denomination):
    lookup.item_picker.set_current(item)
    index = lookup.denomination.findData(denomination)
    assert index >= 0, f"{denomination} is not an offered denomination"
    lookup.denomination.setCurrentIndex(index)
    return lookup


class TestDenominations:
    """Only currencies the Exchange has real depth in are offered."""

    def test_the_four_tradeable_denominations_are_offered(self, lookup):
        assert [c for c, _ in DENOMINATIONS] == [
            "exalted", "divine", "chaos", "annul"
        ]
        offered = {
            lookup.denomination.itemData(i)
            for i in range(lookup.denomination.count())
        }
        assert offered == {"exalted", "divine", "chaos", "annul"}

    def test_there_is_no_arbitrary_pair_conversion(self, lookup):
        """Most items don't trade against each other, so we don't imply they do."""
        assert not hasattr(lookup, "want_picker")
        assert not hasattr(lookup, "have_picker")


class TestPriceSource:
    """Currency Exchange where it prices both sides, poe.ninja consensus otherwise."""

    def test_it_falls_back_to_consensus_and_says_so(self, lookup):
        ask(lookup, "chaos", "divine")
        assert "poe.ninja" in lookup.note.text()

    def test_a_ce_priced_pair_is_named_as_such(self, lookup, universe):
        lookup.set_universe(universe.with_ce_prices({"divine": 1.0, "chaos": 0.2}))
        ask(lookup, "chaos", "divine")
        assert "Currency Exchange" in lookup.note.text()
        assert "poe.ninja" not in lookup.note.text()

    def test_the_ce_price_is_the_one_used(self, lookup, universe):
        lookup.set_universe(universe.with_ce_prices({"divine": 1.0, "chaos": 0.2}))
        ask(lookup, "chaos", "divine")
        assert "0.20 div" == lookup.value.text()

    def test_half_a_ce_pair_is_not_a_ce_price(self, lookup, universe):
        """Mixing the two markets gives a number belonging to neither."""
        lookup.set_universe(universe.with_ce_prices({"chaos": 0.2}))
        ask(lookup, "chaos", "divine")
        assert "poe.ninja" in lookup.note.text()

    def test_a_thin_price_is_flagged_as_a_ceiling(self, lookup, universe):
        """Measured 2026-07-30: thin items ran ~26% above what a sale realised."""
        lookup.set_universe(universe.with_ce_prices({"divine": 1.0, "chaos": 0.2}))
        ask(lookup, "chaos", "divine")
        assert "ceiling" in lookup.note.text()


class TestDisplay:
    def test_the_value_carries_the_denomination(self, lookup):
        ask(lookup, "mirror", "divine")
        assert lookup.value.text().endswith(" div")
        assert "4,886" in lookup.value.text()

    def test_the_denomination_changes_the_number(self, lookup):
        ask(lookup, "mirror", "divine")
        in_divine = lookup.value.text()
        ask(lookup, "mirror", "chaos")
        assert lookup.value.text() != in_divine
        assert lookup.value.text().endswith(" chaos")

    def test_no_prose_restating_the_number(self, lookup):
        """"1 of these gets you N of those" was noise; it's gone."""
        assert not hasattr(lookup, "detail")

    def test_prompts_until_an_item_is_chosen(self, lookup):
        assert lookup.value.text() == "—"
        assert "Pick an item" in lookup.note.text()

    def test_an_item_priced_in_itself_is_one(self, lookup):
        ask(lookup, "divine", "divine")
        assert lookup.value.text() == "1 div"

    def test_an_unpriceable_pair_says_so(self, lookup):
        ask(lookup, "mirror", "annul")   # no annul price in this universe
        assert lookup.value.text() == "—"
        assert "No price" in lookup.note.text()

    def test_exclusions_are_irrelevant_here(self, lookup):
        """Excluding something from the sweep must not stop you pricing it."""
        ask(lookup, "mirror", "divine")
        assert "4,886" in lookup.value.text()
