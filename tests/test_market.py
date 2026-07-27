"""The multi-category item universe."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from poe2arb.client import NinjaOverview
from poe2arb.market import (
    BASE_CURRENCY_CHOICES,
    CATEGORIES,
    GRAPH_CATEGORY,
    Item,
    Universe,
    category_label,
    merge_overviews,
)

NOW = datetime.now(timezone.utc)


def overview(values, names, volumes=None):
    return NinjaOverview(
        league="Test",
        fetched_at=NOW,
        values=values,
        volumes=volumes or {k: 100.0 for k in values},
        names=names,
    )


CURRENCY = overview(
    {"divine": 1.0, "chaos": 0.11, "exalted": 0.00225},
    {"divine": "Divine Orb", "chaos": "Chaos Orb", "exalted": "Exalted Orb"},
)
FRAGMENTS = overview({"frag-a": 0.5}, {"frag-a": "Ancient Crisis Fragment"})
RUNES = overview({"rune-b": 0.02}, {"rune-b": "Iron Rune"})


@pytest.fixture
def universe() -> Universe:
    return merge_overviews(
        "Test", NOW,
        {"Currency": CURRENCY, "Fragments": FRAGMENTS, "Runes": RUNES},
    )


class TestCategories:
    def test_all_live_categories_listed(self):
        """Verified live 2026-07-26; all 14 returned data."""
        assert len(CATEGORIES) == 14
        assert "Currency" in CATEGORIES and "Fragments" in CATEGORIES

    def test_graph_stays_narrow(self):
        """Widening this multiplies paced GGG requests per scan."""
        assert GRAPH_CATEGORY == "Currency"

    def test_display_labels_are_readable(self):
        assert category_label("UncutGems") == "Uncut Gems"
        assert category_label("LineageSupportGems") == "Lineage Support Gems"
        assert category_label("Currency") == "Currency"

    def test_base_choices_lead_with_adaptive_then_ascend_in_value(self):
        ids = [cid for cid, _ in BASE_CURRENCY_CHOICES]
        assert ids == ["adaptive", "exalted", "chaos", "annul", "divine"]

    def test_abbreviations(self):
        from poe2arb.market import base_abbreviation

        assert base_abbreviation("exalted") == "ex"
        assert base_abbreviation("divine") == "div"
        assert base_abbreviation("chaos") == "chaos"
        assert base_abbreviation("annul") == "annul"


class TestAdaptiveUnit:
    def test_expensive_items_priced_in_divines(self, universe):
        rich = merge_overviews("T", NOW, {"Currency": overview(
            {"divine": 1.0, "chaos": 0.11, "exalted": 0.00225, "mirror": 4886.0},
            {"divine": "Divine Orb", "chaos": "Chaos Orb",
             "exalted": "Exalted Orb", "mirror": "Mirror"},
        )})
        assert rich.adaptive_unit("mirror") == "divine"

    def test_cheap_items_priced_in_exalts(self, universe):
        cheap = merge_overviews("T", NOW, {"Currency": overview(
            {"divine": 1.0, "exalted": 0.00225, "scrap": 0.000001},
            {"divine": "Divine Orb", "exalted": "Exalted Orb", "scrap": "Scrap"},
        )})
        assert cheap.adaptive_unit("scrap") == "exalted"

    def test_each_currency_reads_as_one_of_itself(self, universe):
        for cid in ("divine", "chaos", "exalted"):
            assert universe.adaptive_unit(cid) == cid


class TestMerge:
    def test_items_from_every_category(self, universe):
        assert len(universe) == 5
        assert universe.get("frag-a").category == "Fragments"
        assert universe.get("rune-b").category == "Runes"

    def test_names_and_values_preserved(self, universe):
        item = universe.get("chaos")
        assert item.name == "Chaos Orb"
        assert item.value_divine == 0.11

    def test_unknown_id_is_none_not_an_error(self, universe):
        assert universe.get("nope") is None
        assert universe.name("nope") == "nope"

    def test_first_category_wins_on_collision(self):
        """No collisions exist live, but a future one must not corrupt the map."""
        a = overview({"dupe": 1.0}, {"dupe": "From A"})
        b = overview({"dupe": 2.0}, {"dupe": "From B"})
        merged = merge_overviews("T", NOW, {"Currency": a, "Runes": b})
        assert merged.get("dupe").name == "From A"
        assert merged.get("dupe").category == "Currency"


class TestGrouping:
    def test_categories_sorted_alphabetically(self, universe):
        assert list(universe.by_category()) == ["Currency", "Fragments", "Runes"]

    def test_items_sorted_alphabetically_within_category(self, universe):
        names = [i.name for i in universe.by_category()["Currency"]]
        assert names == ["Chaos Orb", "Divine Orb", "Exalted Orb"]

    def test_grouping_covers_every_item(self, universe):
        grouped = sum(len(v) for v in universe.by_category().values())
        assert grouped == len(universe)


class TestConversion:
    def test_converts_between_any_two_items(self, universe):
        # 1 divine = 1/0.11 chaos
        assert universe.convert("divine", "chaos") == pytest.approx(9.0909, rel=1e-3)

    def test_identity_is_one(self, universe):
        assert universe.convert("chaos", "chaos") == 1.0

    def test_inverse_round_trip(self, universe):
        there = universe.convert("chaos", "exalted")
        back = universe.convert("exalted", "chaos")
        assert there * back == pytest.approx(1.0)

    def test_cross_category_conversion(self, universe):
        """A fragment priced in runes — only possible because all use divines."""
        assert universe.convert("frag-a", "rune-b") == pytest.approx(25.0)

    def test_unknown_side_returns_none(self, universe):
        assert universe.convert("divine", "nope") is None
        assert universe.convert("nope", "divine") is None

    def test_zero_valued_base_returns_none(self):
        u = merge_overviews(
            "T", NOW, {"Currency": overview({"a": 1.0, "z": 0.0}, {"a": "A", "z": "Z"})}
        )
        assert u.convert("a", "z") is None


class TestTiers:
    def test_tier_extracted_from_name(self):
        from poe2arb.market import tier_for

        assert tier_for("Greater Essence of Ice") == "Greater"
        assert tier_for("Perfect Essence of Battle") == "Perfect"
        assert tier_for("Lesser Essence of Ice") == "Lesser"
        assert tier_for("Essence of Enhancement") == "Standard"

    def test_earliest_tier_word_wins(self):
        """'Ancient Concentrated Liquid Fear' clusters with the Ancients."""
        from poe2arb.market import tier_for

        assert tier_for("Ancient Concentrated Liquid Isolation") == "Ancient"

    def test_ranks_follow_measured_prices_not_the_alphabet(self):
        """The whole point: alphabetically Greater precedes Lesser."""
        from poe2arb.market import tier_rank

        assert tier_rank("Lesser") < tier_rank("Greater") < tier_rank("Perfect")
        assert tier_rank("Diluted") < tier_rank("Standard") < tier_rank("Concentrated")
        assert tier_rank("Concentrated") < tier_rank("Potent")
        assert tier_rank("Standard") < tier_rank("Refined")
        # Measured below its plain counterpart, so it must not read as prestige.
        assert tier_rank("Ancient") < tier_rank("Standard")

    def test_natural_sort_orders_levels_numerically(self):
        from poe2arb.market import natural_key

        names = ["Uncut Skill Gem (Level 11)", "Uncut Skill Gem (Level 6)"]
        assert sorted(names, key=natural_key) == [
            "Uncut Skill Gem (Level 6)", "Uncut Skill Gem (Level 11)",
        ]

    def test_uncut_gems_group_by_type(self):
        from poe2arb.market import _uncut_gem_group

        assert _uncut_gem_group("Uncut Skill Gem (Level 13)") == "Skill Gems"
        assert _uncut_gem_group("Uncut Spirit Gem (Level 4)") == "Spirit Gems"
        assert _uncut_gem_group("Divine Orb") == "Other"

    def test_verisium_groups_by_kind(self):
        from poe2arb.market import _verisium_group

        assert _verisium_group("Prismatic Alloy") == "Alloys"
        assert _verisium_group("Warding Starlit Ore") == "Ores"
        assert _verisium_group("Verisium") == "Other"


class TestTierGrouping:
    def _universe_with(self, names_values, category="Essences"):
        ov = NinjaOverview(
            league="T", fetched_at=NOW,
            values={n.lower().replace(" ", "-"): v for n, v in names_values.items()},
            volumes={n.lower().replace(" ", "-"): 1.0 for n in names_values},
            names={n.lower().replace(" ", "-"): n for n in names_values},
        )
        return merge_overviews("T", NOW, {category: ov})

    def test_tiers_ordered_by_strength(self):
        items = {f"{tier} Essence of Ice {i}": 1.0
                 for tier in ("Perfect", "Lesser", "Greater")
                 for i in range(4)}
        u = self._universe_with(items)
        assert list(u.by_category_and_tier()["Essences"]) == [
            "Lesser", "Greater", "Perfect",
        ]

    def test_small_categories_stay_flat(self):
        u = self._universe_with({"Greater Essence of Ice": 1.0, "Lesser Essence of Ice": 2.0})
        groups = u.by_category_and_tier()["Essences"]
        assert list(groups) == ["Standard"]

    def test_single_item_tiers_folded_into_standard(self):
        items = {f"Essence of Thing {i}": 1.0 for i in range(14)}
        items["Perfect Essence of Rare"] = 5.0  # lone Perfect
        u = self._universe_with(items)
        groups = u.by_category_and_tier()["Essences"]
        assert "Perfect" not in groups
        assert len(groups["Standard"]) == 15

    def test_every_item_appears_exactly_once(self):
        items = {f"{tier} Essence {i}": 1.0
                 for tier in ("Perfect", "Lesser", "Greater", "")
                 for i in range(4)}
        u = self._universe_with(items)
        grouped = u.by_category_and_tier()["Essences"]
        total = sum(len(v) for v in grouped.values())
        assert total == len(u)


class TestMenuSizeCap:
    def _items(self, n, prefix="Thing"):
        from poe2arb.market import Item
        return [Item(f"id{i}", f"{prefix} {chr(65 + i % 26)}{i}", "Runes", 1.0, 1.0)
                for i in range(n)]

    def test_small_groups_left_alone(self):
        from poe2arb.market import MAX_ITEMS_PER_MENU, chunk_group
        items = self._items(MAX_ITEMS_PER_MENU)
        assert chunk_group("Standard", items, True) == [("Standard", items)]

    def test_oversized_groups_are_split(self):
        from poe2arb.market import MAX_ITEMS_PER_MENU, chunk_group
        chunks = chunk_group("Standard", self._items(90), True)
        assert len(chunks) >= 3
        assert all(len(v) <= MAX_ITEMS_PER_MENU for _, v in chunks)

    def test_no_item_lost_or_duplicated(self):
        from poe2arb.market import chunk_group
        items = self._items(85)
        rebuilt = [i for _, chunk in chunk_group("S", items, True) for i in chunk]
        assert rebuilt == items

    def test_chunks_named_after_their_first_entry(self):
        from poe2arb.market import chunk_group
        chunks = chunk_group("Standard", self._items(70), True)
        for label, items in chunks:
            assert label.rstrip("…") in items[0].name

    def test_group_name_kept_when_not_the_only_group(self):
        from poe2arb.market import chunk_group
        chunks = chunk_group("Standard", self._items(70), False)
        assert all(label.startswith("Standard: ") for label, _ in chunks)

    def test_shared_prefix_names_stay_distinct(self):
        """Every Ritual item is an 'Omen of …'; labels must still differ."""
        from poe2arb.market import chunk_group
        items = self._items(70, prefix="Omen of the")
        labels = [label for label, _ in chunk_group("Standard", items, True)]
        assert len(set(labels)) == len(labels)

    def test_live_data_never_exceeds_the_cap(self):
        """The real economy is what this exists for."""
        import glob, json
        from datetime import datetime, timezone
        from poe2arb.client import parse_overview
        from poe2arb.market import MAX_ITEMS_PER_MENU

        files = glob.glob("/tmp/ninjacat/*.json")
        if not files:
            pytest.skip("no captured category data available")
        per = {f.split("/")[-1].replace(".json", ""):
               parse_overview(json.load(open(f)), "T", datetime.now(timezone.utc))
               for f in files}
        u = merge_overviews("T", datetime.now(timezone.utc), per)
        for groups in u.by_category_and_tier().values():
            for items in groups.values():
                assert len(items) <= MAX_ITEMS_PER_MENU
