"""Category-menu pickers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2arb.client import NinjaOverview  # noqa: E402
from poe2arb.gui.item_picker import (  # noqa: E402
    ExclusionPicker,
    ItemPicker,
    rank_matches,
)
from poe2arb.market import merge_overviews  # noqa: E402

NOW = datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def universe():
    currency = NinjaOverview(
        league="T", fetched_at=NOW,
        values={"divine": 1.0, "chaos": 0.11, "mirror": 4886.0},
        volumes={"divine": 1.0, "chaos": 1.0, "mirror": 1.0},
        names={"divine": "Divine Orb", "chaos": "Chaos Orb", "mirror": "Mirror of Kalandra"},
    )
    runes = NinjaOverview(
        league="T", fetched_at=NOW,
        values={"rune-a": 0.02}, volumes={"rune-a": 5.0}, names={"rune-a": "Iron Rune"},
    )
    return merge_overviews("T", NOW, {"Currency": currency, "Runes": runes})


def submenus(picker):
    return [a for a in picker.menu().actions() if a.menu()]


def search(picker, text):
    """Type into the picker's search box and return the visible match labels."""
    picker._search.field.setText(text)
    return [a.text() for a in picker._search._results if a.isVisible()]


class TestExclusionPicker:
    def test_groups_by_category(self, app, universe):
        picker = ExclusionPicker([], universe)
        assert [a.text() for a in submenus(picker)] == ["Currency", "Runes"]

    def test_items_alphabetical_within_category(self, app, universe):
        picker = ExclusionPicker([], universe)
        currency = submenus(picker)[0].menu()
        assert [a.text() for a in currency.actions()] == [
            "Chaos Orb", "Divine Orb", "Mirror of Kalandra",
        ]

    def test_saved_selection_is_ticked(self, app, universe):
        picker = ExclusionPicker(["mirror"], universe)
        currency = submenus(picker)[0].menu()
        mirror = [a for a in currency.actions() if a.text() == "Mirror of Kalandra"][0]
        assert mirror.isChecked()

    def test_toggling_updates_selection_and_label(self, app, universe):
        picker = ExclusionPicker([], universe)
        currency = submenus(picker)[0].menu()
        chaos = [a for a in currency.actions() if a.text() == "Chaos Orb"][0]
        chaos.setChecked(True)
        assert picker.selected_ids() == ["chaos"]
        assert picker.text() == "Chaos Orb"
        chaos.setChecked(False)
        assert picker.selected_ids() == []
        assert picker.text() == "Nothing excluded"

    def test_summary_is_a_count_not_a_growing_list(self, app, universe):
        """The label must not stretch the settings form as items are ticked."""
        picker = ExclusionPicker(["divine", "chaos", "mirror"], universe)
        assert picker.text() == "3 items excluded"

    def test_single_selection_named_in_full(self, app, universe):
        assert ExclusionPicker(["mirror"], universe).text() == "Mirror of Kalandra"

    def test_branches_marked_when_they_hold_a_selection(self, app, universe):
        """Otherwise finding what you ticked means opening every category."""
        picker = ExclusionPicker(["mirror"], universe)
        titles = [a.text() for a in submenus(picker)]
        assert any("•" in t for t in titles)
        clean = ExclusionPicker([], universe)
        assert not any("•" in a.text() for a in submenus(clean))

    def test_clear_all(self, app, universe):
        picker = ExclusionPicker(["chaos", "mirror"], universe)
        picker.clear()
        assert picker.selected_ids() == []

    def test_selection_from_another_league_kept(self, app, universe):
        """Excluding something absent from this league must not silently drop it."""
        picker = ExclusionPicker(["long-gone-orb"], universe)
        assert "long-gone-orb" in picker.selected_ids()
        assert "Not in this league" in [a.text() for a in submenus(picker)]

    def test_handles_missing_universe(self, app):
        picker = ExclusionPicker(["chaos"], None)
        assert picker.selected_ids() == ["chaos"]

    def test_submenus_survive_rebuild(self, app, universe):
        """PySide will collect unreferenced submenus and blank the menu."""
        picker = ExclusionPicker([], universe)
        picker.rebuild(universe)
        picker.rebuild(universe)
        currency = submenus(picker)[0].menu()
        assert len(currency.actions()) == 3  # still alive after two rebuilds


class TestRanking:
    def test_prefix_match_beats_a_later_word(self, universe):
        """Typing "orb" should lead with Orb of…, not with Divine Orb."""
        wider = merge_overviews(
            "T", NOW,
            {"Currency": NinjaOverview(
                league="T", fetched_at=NOW,
                values={"divine": 1.0, "annul": 0.1, "chaos": 0.01},
                volumes={"divine": 1.0, "annul": 1.0, "chaos": 1.0},
                names={"divine": "Divine Orb", "annul": "Orb of Annulment",
                       "chaos": "Chaos Orb"},
            )},
        )
        assert rank_matches(wider, "orb")[0].name == "Orb of Annulment"

    def test_word_start_beats_mid_word(self, universe):
        inner = merge_overviews(
            "T", NOW,
            {"Runes": NinjaOverview(
                league="T", fetched_at=NOW,
                values={"a": 1.0, "b": 1.0},
                volumes={"a": 1.0, "b": 1.0},
                names={"a": "Glassblower Rune", "b": "Iron Ruin"},
            )},
        )
        assert [i.name for i in rank_matches(inner, "ru")] == [
            "Glassblower Rune", "Iron Ruin",
        ]

    def test_case_insensitive(self, universe):
        assert rank_matches(universe, "MIRROR")[0].id == "mirror"

    def test_blank_query_matches_nothing(self, universe):
        assert rank_matches(universe, "   ") == []

    def test_no_universe_is_safe(self):
        assert rank_matches(None, "chaos") == []

    def test_result_count_is_capped(self, universe):
        assert len(rank_matches(universe, "o", limit=2)) == 2


class TestSearch:
    def test_typing_shows_matches(self, app, universe):
        picker = ItemPicker("Pick…", universe)
        assert any("Chaos Orb" in label for label in search(picker, "chaos"))

    def test_tree_hidden_while_searching(self, app, universe):
        """A search that left the categories showing below it would be noise."""
        picker = ItemPicker("Pick…", universe)
        search(picker, "chaos")
        assert not any(a.isVisible() for a in submenus(picker))

    def test_clearing_brings_the_tree_back(self, app, universe):
        picker = ItemPicker("Pick…", universe)
        search(picker, "chaos")
        search(picker, "")
        assert all(a.isVisible() for a in submenus(picker))
        assert not any(a.isVisible() for a in picker._search._results)

    def test_no_matches_says_so(self, app, universe):
        picker = ItemPicker("Pick…", universe)
        assert search(picker, "zzzzz") == []
        assert picker._search._empty.isVisible()

    def test_choosing_a_match_selects_it(self, app, universe):
        picker = ItemPicker("Pick…", universe)
        search(picker, "mirror")
        picker._search._results[0].trigger()
        assert picker.current_id() == "mirror"

    def test_matches_are_priced_like_the_tree(self, app, universe):
        picker = ItemPicker("Pick…", universe, base_id="divine")
        assert all("div)" in label for label in search(picker, "orb"))

    def test_exclusion_search_reflects_existing_ticks(self, app, universe):
        picker = ExclusionPicker(["mirror"], universe)
        search(picker, "mirror")
        assert picker._search._results[0].isChecked()

    def test_ticking_from_search_updates_the_selection(self, app, universe):
        picker = ExclusionPicker([], universe)
        search(picker, "chaos")
        picker._search._results[0].trigger()  # a checkable action toggles itself
        assert picker.selected_ids() == ["chaos"]

    def test_ticking_from_search_ticks_the_tree_too(self, app, universe):
        """Otherwise reopening the menu shows the item as unticked."""
        picker = ExclusionPicker([], universe)
        search(picker, "chaos")
        picker._search._results[0].trigger()
        currency = submenus(picker)[0].menu()
        chaos = [a for a in currency.actions() if a.text() == "Chaos Orb"][0]
        assert chaos.isChecked()

    def test_relabelling_slots_does_not_count_as_clicking(self, app, universe):
        """Result actions are reused, so their checked state gets rewritten."""
        picker = ExclusionPicker(["mirror"], universe)
        search(picker, "mirror")
        search(picker, "chaos")
        search(picker, "orb")
        assert picker.selected_ids() == ["mirror"]

    def test_search_survives_a_rebuild(self, app, universe):
        picker = ItemPicker("Pick…", universe)
        picker.rebuild(universe)
        assert any("Chaos Orb" in label for label in search(picker, "chaos"))

    def test_reopening_starts_fresh(self, app, universe):
        picker = ItemPicker("Pick…", universe)
        search(picker, "chaos")
        picker.menu().aboutToShow.emit()
        assert picker._search.field.text() == ""
        assert all(a.isVisible() for a in submenus(picker))


class TestItemPicker:
    def test_placeholder_until_chosen(self, app, universe):
        picker = ItemPicker("Pick one…", universe)
        assert picker.current_id() is None
        assert picker.text() == "Pick one…"

    def test_selecting_sets_name(self, app, universe):
        picker = ItemPicker("Pick…", universe)
        picker.set_current("chaos")
        assert picker.current_id() == "chaos"
        assert picker.text() == "Chaos Orb"

    def test_labels_include_value_in_base(self, app, universe):
        picker = ItemPicker("Pick…", universe, base_id="divine")
        currency = submenus(picker)[0].menu()
        mirror = [a for a in currency.actions() if a.text().startswith("Mirror")][0]
        assert "div)" in mirror.text()

    def test_base_change_relabels(self, app, universe):
        picker = ItemPicker("Pick…", universe, base_id="divine")
        picker.rebuild(universe, base_id="chaos")
        currency = submenus(picker)[0].menu()
        assert any("chaos)" in a.text() for a in currency.actions())

    def test_adaptive_prices_each_item_in_a_readable_unit(self, app, universe):
        picker = ItemPicker("Pick…", universe, base_id="adaptive")
        currency = submenus(picker)[0].menu()
        labels = {a.text().split("   (")[0]: a.text() for a in currency.actions()}
        assert "div)" in labels["Mirror of Kalandra"]
        assert "chaos)" in labels["Chaos Orb"]

    def test_selection_cleared_if_absent_after_rebuild(self, app, universe):
        picker = ItemPicker("Pick…", universe)
        picker.set_current("chaos")
        smaller = merge_overviews(
            "T", NOW,
            {"Runes": NinjaOverview(
                league="T", fetched_at=NOW, values={"rune-a": 0.02},
                volumes={"rune-a": 1.0}, names={"rune-a": "Iron Rune"},
            )},
        )
        picker.rebuild(smaller)
        assert picker.current_id() is None
