"""Category-menu pickers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2arb.client import NinjaOverview  # noqa: E402
from poe2arb.gui.item_picker import ExclusionPicker, ItemPicker  # noqa: E402
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
