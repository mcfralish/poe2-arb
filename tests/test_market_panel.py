"""The Market tab: in-game grouping, composed filters, and inline exclusions."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2arb.client import NinjaOverview  # noqa: E402
from poe2arb.gui.market_panel import (  # noqa: E402
    EXCLUDED_COLUMN,
    ExclusionListDialog,
    MarketPanel,
)
from poe2arb.market import (  # noqa: E402
    ALL_TAB,
    ATZIRIS_TEMPLE,
    INGAME_TABS,
    Item,
    ingame_tab,
    merge_overviews,
)

NOW = datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def universe():
    def overview(**items):
        return NinjaOverview(
            league="T", fetched_at=NOW,
            values={k: v[0] for k, v in items.items()},
            volumes={k: 10.0 for k in items},
            names={k: v[1] for k, v in items.items()},
        )

    return merge_overviews("T", NOW, {
        "Currency": overview(
            divine=(1.0, "Divine Orb"),
            chaos=(0.1, "Chaos Orb"),
            **{"architects-orb": (5.0, "Architect's Orb")},
        ),
        "Verisium": overview(**{"liquid-verisium": (0.5, "Liquid Verisium")}),
        "Expedition": overview(**{"blazing-flux": (0.2, "Blazing Flux")}),
        "LineageSupportGems": overview(**{"tacatis-ire": (3.0, "Tacati's Ire")}),
    })


@pytest.fixture
def panel(app, universe):
    p = MarketPanel()
    p.set_universe(universe)
    p.render(
        names=universe.names(),
        values=universe.values(),
        volumes={i.id: i.volume_divine for i in universe.items.values()},
        in_graph={"divine", "chaos"},
    )
    return p


def tab_names(panel):
    return [panel.tabs.tabText(i) for i in range(panel.tabs.count())]


def visible_names(panel):
    return [
        panel.table.item(r, 0).text()
        for r in range(panel.table.rowCount())
        if not panel.table.isRowHidden(r)
    ]


def select_tab(panel, name):
    for i in range(panel.tabs.count()):
        if panel.tabs.tabText(i) == name:
            panel.tabs.setCurrentIndex(i)
            return
    raise AssertionError(f"no tab {name!r} in {tab_names(panel)}")


class TestIngameTabs:
    def test_vaal_items_leave_currency(self):
        """The one split poe.ninja doesn't express."""
        item = Item("architects-orb", "Architect's Orb", "Currency", 5.0, 1.0)
        assert ingame_tab(item) == ATZIRIS_TEMPLE

    def test_vaal_orb_itself_stays_in_currency(self):
        """Named for Vaal but the game keeps it on the Currency tab."""
        assert ingame_tab(Item("vaal-orb", "Vaal Orb", "Currency", 1.0, 1.0)) == "Currency"

    def test_verisium_folds_into_expedition(self):
        assert ingame_tab(Item("x", "X", "Verisium", 1.0, 1.0)) == "Expedition"

    def test_lineage_gems_are_called_gems(self):
        assert ingame_tab(Item("x", "X", "LineageSupportGems", 1.0, 1.0)) == "Gems"

    def test_soul_cores_keep_their_own_tab(self):
        """GGG's API merges these into Vaal; the game doesn't."""
        assert ingame_tab(Item("x", "X", "SoulCores", 1.0, 1.0)) == "Soul Cores"

    def test_tab_order_follows_the_game(self, universe):
        present = list(universe.by_tab())
        assert present == [t for t in INGAME_TABS if t in present]

    def test_empty_tabs_are_omitted(self, universe):
        assert "Runes" not in universe.by_tab()


class TestGrouping:
    def test_a_shared_tab_keeps_both_categories_distinct(self, universe):
        """Expedition holds Expedition and Verisium; neither should vanish."""
        groups = universe.groups_in_tab("Expedition")
        assert any(g.startswith("Expedition:") for g in groups)
        assert any(g.startswith("Verisium:") for g in groups)

    def test_single_category_tabs_get_no_prefix(self, universe):
        assert all(":" not in g for g in universe.groups_in_tab("Currency"))


class TestFilters:
    def test_all_tab_shows_everything(self, panel):
        assert len(visible_names(panel)) == panel.table.rowCount()

    def test_tab_narrows_to_its_items(self, panel):
        select_tab(panel, ATZIRIS_TEMPLE)
        assert visible_names(panel) == ["Architect's Orb"]

    def test_search_narrows_further(self, panel):
        select_tab(panel, "Currency")
        panel.search.setText("chaos")
        assert visible_names(panel) == ["Chaos Orb"]

    def test_search_alone_works_on_the_all_tab(self, panel):
        panel.search.setText("verisium")
        assert visible_names(panel) == ["Liquid Verisium"]

    def test_group_filter_composes_with_the_tab(self, panel, universe):
        select_tab(panel, "Expedition")
        groups = list(universe.groups_in_tab("Expedition"))
        target = [g for g in groups if g.startswith("Verisium")][0]
        panel.group_box.setCurrentText(target)
        assert visible_names(panel) == ["Liquid Verisium"]

    def test_group_box_resets_when_the_tab_changes(self, panel):
        select_tab(panel, "Expedition")
        select_tab(panel, "Currency")
        assert panel.group_box.currentText() == "All groups"

    def test_status_reports_the_narrowing(self, panel):
        select_tab(panel, "Currency")
        assert "of" in panel.status.text()

    def test_no_matches_is_survivable(self, panel):
        panel.search.setText("zzzzz")
        assert visible_names(panel) == []


class TestExclusions:
    def test_excluded_items_stay_visible(self, panel):
        """The whole point of the change: you judge an item while seeing it."""
        panel.set_exclusions(["chaos"])
        panel._sync_checkboxes()
        assert "Chaos Orb" in visible_names(panel)

    def test_ticking_the_box_excludes(self, panel):
        seen = []
        panel.exclusions_changed.connect(seen.append)
        row = next(
            r for r in range(panel.table.rowCount())
            if panel.table.item(r, 0).text() == "Chaos Orb"
        )
        panel.table.item(row, EXCLUDED_COLUMN).setCheckState(Qt.CheckState.Checked)
        assert seen == [["chaos"]]

    def test_unticking_removes(self, panel):
        panel.set_exclusions(["chaos"])
        panel._sync_checkboxes()
        seen = []
        panel.exclusions_changed.connect(seen.append)
        row = next(
            r for r in range(panel.table.rowCount())
            if panel.table.item(r, 0).text() == "Chaos Orb"
        )
        panel.table.item(row, EXCLUDED_COLUMN).setCheckState(Qt.CheckState.Unchecked)
        assert seen == [[]]

    def test_filling_the_table_is_not_a_user_click(self, panel, universe):
        """Populating sets check states; none of that may look like a tick."""
        panel.set_exclusions(["chaos", "divine"])
        seen = []
        panel.exclusions_changed.connect(seen.append)
        panel.render(
            names=universe.names(),
            values=universe.values(),
            volumes={i.id: i.volume_divine for i in universe.items.values()},
            in_graph=set(),
        )
        assert seen == []

    def test_button_shows_the_count(self, panel):
        panel.set_exclusions(["chaos", "divine"])
        assert "2" in panel.exclusions_button.text()

    def test_button_is_bare_when_nothing_is_excluded(self, panel):
        panel.set_exclusions([])
        assert panel.exclusions_button.text() == "Excluded"


class TestExclusionListDialog:
    def test_lists_what_is_excluded(self, app):
        dialog = ExclusionListDialog(["chaos"], {"chaos": "Chaos Orb"})
        assert dialog.list.item(0).text() == "Chaos Orb"
        assert dialog.selected_ids() == ["chaos"]

    def test_unticking_drops_it(self, app):
        dialog = ExclusionListDialog(["chaos", "divine"], {})
        dialog.list.item(0).setCheckState(Qt.CheckState.Unchecked)
        assert len(dialog.selected_ids()) == 1

    def test_clear_all_empties_it(self, app):
        dialog = ExclusionListDialog(["chaos", "divine"], {})
        dialog._clear_all()
        assert dialog.selected_ids() == []

    def test_empty_list_is_not_an_error(self, app):
        assert ExclusionListDialog([], {}).selected_ids() == []
