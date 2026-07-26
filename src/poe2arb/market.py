"""The full poe.ninja item universe, across every economy category.

The arbitrage scan only trades currencies, but the app is more useful when it
knows about everything poe.ninja prices — fragments, essences, runes and the
rest — for lookups and for choosing what to exclude.

Verified live (2026-07-26, Runes of Aldur): 14 categories, 636 items, **no id
collisions between categories**, and every category quotes prices in divines.
So a single flat id -> Item map is safe and values are directly comparable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

# Exchange-overview categories, as poe.ninja's `type` parameter spells them.
CATEGORIES: tuple[str, ...] = (
    "Currency",
    "Fragments",
    "Abyss",
    "UncutGems",
    "LineageSupportGems",
    "Essences",
    "SoulCores",
    "Idols",
    "Runes",
    "Ritual",
    "Expedition",
    "Delirium",
    "Breach",
    "Verisium",
)

# The category the arbitrage graph draws from. Widening this multiplies the
# number of paced GGG order-book requests a scan needs, so it stays narrow.
GRAPH_CATEGORY = "Currency"

_DISPLAY_NAMES = {
    "UncutGems": "Uncut Gems",
    "LineageSupportGems": "Lineage Support Gems",
    "SoulCores": "Soul Cores",
}

# Currencies offered as the unit to price everything else in.
BASE_CURRENCY_CHOICES: tuple[tuple[str, str], ...] = (
    ("divine", "Divine Orb"),
    ("exalted", "Exalted Orb"),
    ("chaos", "Chaos Orb"),
    ("annul", "Orb of Annulment"),
)


def category_label(category: str) -> str:
    """'UncutGems' -> 'Uncut Gems' for display."""
    return _DISPLAY_NAMES.get(category, category)


# Tier words that appear in item names, ranked weakest to strongest.
#
# Ranks were checked against live median values rather than guessed, because
# alphabetical order is actively wrong here — "Greater" sorts before "Lesser"
# but outranks it. Measured on 2026-07-26 (Runes of Aldur), medians in divines:
#   Essences  Lesser 0.0030 < Greater 0.0034 < Perfect 0.0122
#   Delirium  Diluted 0.00011 < base 0.0020 < Concentrated 0.143 < Potent 0.726
#   Breach    base 0.0133 < Refined 0.229
# "Ancient" consistently prices *below* its plain counterpart in Delirium and
# Runes, so it sits low rather than reading as a prestige word.
STANDARD_TIER = "Standard"
STANDARD_TIER_RANK = 30

TIER_RANKS: dict[str, int] = {
    "Diluted": 10,
    "Ancient": 15,
    "Lesser": 20,
    STANDARD_TIER: STANDARD_TIER_RANK,
    "Greater": 40,
    "Refined": 40,
    "Concentrated": 45,
    "Potent": 50,
    "Vaal": 55,
    "Perfect": 60,
}

# Below this many items a category reads better as one flat list.
MIN_ITEMS_TO_SPLIT_BY_TIER = 12


def tier_for(name: str) -> str:
    """The tier word in an item's name, or 'Standard' if it has none.

    Names carry at most one meaningful tier for grouping purposes; where two
    appear ("Ancient Concentrated Liquid Fear") the earliest word wins, which
    matches how the prices actually cluster.
    """
    words = name.replace("'s", "").split()
    for word in words:
        cleaned = word.strip(",.").capitalize()
        if cleaned in TIER_RANKS and cleaned != STANDARD_TIER:
            return cleaned
    return STANDARD_TIER


def tier_rank(tier: str) -> int:
    return TIER_RANKS.get(tier, STANDARD_TIER_RANK)


def natural_key(name: str) -> tuple:
    """Sort key that reads embedded numbers as numbers.

    Plain alphabetical puts "Uncut Skill Gem (Level 11)" before "(Level 6)",
    which is nonsense for anything level-graded.
    """
    return tuple(
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", name)
    )


def _uncut_gem_group(name: str) -> str:
    """'Uncut Skill Gem (Level 13)' -> 'Skill Gems'."""
    match = re.search(r"Uncut\s+(\w+)\s+Gem", name)
    return f"{match.group(1)} Gems" if match else "Other"


def _verisium_group(name: str) -> str:
    """Group by the kind of thing it is: Alloys, Ores, everything else."""
    last = name.split()[-1].strip("()")
    if last in {"Alloy", "Ore"}:
        return f"{last}s"
    return "Other"


# Categories whose names carry a more useful structure than tier words.
CATEGORY_GROUPERS = {
    "UncutGems": _uncut_gem_group,
    "Verisium": _verisium_group,
}

# A tier holding fewer than this folds back into Standard: a submenu for a
# single item is a level of nesting that earns nothing.
MIN_TIER_SIZE = 2

# Longest a single menu is allowed to get. Qt will either scroll a taller menu
# behind small arrows or run it off the bottom of the screen depending on
# platform and style, and neither is usable — so oversized groups are split
# here rather than left for the toolkit to cope with.
MAX_ITEMS_PER_MENU = 30


def _truncate(name: str, limit: int = 18) -> str:
    """Shorten a name for use as a menu label, breaking on a word if possible."""
    if len(name) <= limit:
        return name
    cut = name.rfind(" ", 0, limit)
    return (name[:cut] if cut > limit // 2 else name[:limit]).rstrip() + "…"


def chunk_group(label: str, items: list[Item], only_group: bool) -> list[tuple[str, list[Item]]]:
    """Split an over-long group into chunks labelled by where each one starts.

    Alphabet-range labels ("A–O") read badly when a group shares a prefix —
    every Ritual item is an "Omen of …", so the ranges collapse to a single
    letter and say nothing. Naming each chunk after its first entry is always
    unambiguous, and the list is sorted, so it tells you exactly where to look.
    """
    if len(items) <= MAX_ITEMS_PER_MENU:
        return [(label, items)]
    chunks = -(-len(items) // MAX_ITEMS_PER_MENU)  # ceil
    size = -(-len(items) // chunks)                # balance them evenly
    out = []
    for start in range(0, len(items), size):
        piece = items[start : start + size]
        span = _truncate(piece[0].name)
        out.append((span if only_group else f"{label}: {span}", piece))
    return out


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    category: str
    value_divine: float
    volume_divine: float

    @property
    def tier(self) -> str:
        return tier_for(self.name)


@dataclass(frozen=True)
class Universe:
    """Every priced item in the league, keyed by id."""

    league: str
    fetched_at: datetime
    items: dict[str, Item] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.items)

    def get(self, item_id: str) -> Item | None:
        return self.items.get(item_id)

    def name(self, item_id: str) -> str:
        item = self.items.get(item_id)
        return item.name if item else item_id

    def names(self) -> dict[str, str]:
        return {i.id: i.name for i in self.items.values()}

    def values(self) -> dict[str, float]:
        return {i.id: i.value_divine for i in self.items.values()}

    def by_category(self) -> dict[str, list[Item]]:
        """Items grouped by category, each list sorted alphabetically by name."""
        grouped: dict[str, list[Item]] = {}
        for item in self.items.values():
            grouped.setdefault(item.category, []).append(item)
        for items in grouped.values():
            items.sort(key=lambda i: i.name.lower())
        return dict(
            sorted(grouped.items(), key=lambda kv: category_label(kv[0]).lower())
        )

    def by_category_and_tier(self) -> dict[str, dict[str, list[Item]]]:
        """Items grouped category -> tier -> items.

        Categories are alphabetical and items within a tier are alphabetical,
        but **tiers are ordered by strength**, not by name. A category with
        only one tier, or too few items to be worth splitting, comes back as a
        single Standard group so the menu doesn't gain a pointless level.
        """
        grouped: dict[str, dict[str, list[Item]]] = {}
        for category, items in self.by_category().items():
            custom = CATEGORY_GROUPERS.get(category)
            buckets: dict[str, list[Item]] = {}
            for item in items:
                key = custom(item.name) if custom else item.tier
                buckets.setdefault(key, []).append(item)

            if custom is None:
                # Fold thin tiers back into Standard before deciding to split.
                for tier in [t for t in buckets if t != STANDARD_TIER]:
                    if len(buckets[tier]) < MIN_TIER_SIZE:
                        buckets.setdefault(STANDARD_TIER, []).extend(buckets.pop(tier))

            too_small = len(items) < MIN_ITEMS_TO_SPLIT_BY_TIER
            if len(buckets) < 2 or (custom is None and too_small):
                flat = sorted(items, key=lambda i: natural_key(i.name))
                grouped[category] = dict(chunk_group(STANDARD_TIER, flat, True))
                continue

            for bucket in buckets.values():
                bucket.sort(key=lambda i: natural_key(i.name))
            if custom is None:
                order = sorted(buckets.items(), key=lambda kv: (tier_rank(kv[0]), kv[0]))
            else:
                order = sorted(buckets.items(), key=lambda kv: kv[0].lower())
            final: dict[str, list[Item]] = {}
            for label, bucket in order:
                for sub_label, piece in chunk_group(label, bucket, len(order) == 1):
                    final[sub_label] = piece
            grouped[category] = final
        return grouped

    def convert(self, item_id: str, base_id: str) -> float | None:
        """Price of `item_id` expressed in units of `base_id`.

        Everything is quoted in divines, so this is one division — but it
        returns None rather than guessing when either side is unpriced.
        """
        item = self.items.get(item_id)
        base = self.items.get(base_id)
        if item is None or base is None or base.value_divine <= 0:
            return None
        return item.value_divine / base.value_divine


def merge_overviews(league: str, fetched_at: datetime, per_category: dict) -> Universe:
    """Build a Universe from {category: NinjaOverview}."""
    items: dict[str, Item] = {}
    # Fixed order, not whatever order the caller happened to build the dict in:
    # poe.ninja reports the primary unit (Divine Orb) inside *every* category,
    # so without this it lands in an arbitrary one. Currency leads CATEGORIES,
    # which is where it belongs.
    ordered = sorted(
        per_category.items(),
        key=lambda kv: CATEGORIES.index(kv[0]) if kv[0] in CATEGORIES else len(CATEGORIES),
    )
    for category, overview in ordered:
        for item_id, value in overview.values.items():
            # An id already claimed by an earlier category wins; verified not
            # to happen live, but a future poe.ninja change shouldn't corrupt
            # the map silently.
            if item_id in items:
                continue
            items[item_id] = Item(
                id=item_id,
                name=overview.names.get(item_id, item_id),
                category=category,
                value_divine=value,
                volume_divine=overview.volumes.get(item_id, 0.0),
            )
    return Universe(league=league, fetched_at=fetched_at, items=items)
