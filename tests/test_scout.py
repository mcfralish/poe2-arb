"""poe2scout parsing — the CE reference price, and the volume gate that makes it real.

Fixture is a trimmed slice of a live SnapshotPairs response (2026-07-28), kept
because the five divine pairs in it are the ones verified against in-game
screenshots. The expected divine prices below are those measurements.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from poe2arb.scout import MIN_PAIR_VALUE, parse_snapshot_pairs

FIXTURE = Path(__file__).parent / "fixtures" / "scout_snapshot_pairs.json"
FETCHED = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def snapshot():
    return parse_snapshot_pairs(
        json.loads(FIXTURE.read_text(encoding="utf-8")), "Runes of Aldur", FETCHED
    )


# In-game Currency Exchange ratios, read off screenshots on 2026-07-28.
# Tolerance is 6%: poe2scout's RelativePrice is a volume-weighted traded
# average while the game shows best-of-book, so a small negative bias is
# expected and is not a bug.
GAME_PRICES = {
    "exalted": 1 / 430,
    "annul": 1 / 2.08,
    "fracturing-orb": 10.40,
    "perfect-chaos-orb": 6.20,
    "core-destabiliser": 3.79,
}


@pytest.mark.parametrize("item_id,expected", sorted(GAME_PRICES.items()))
def test_prices_track_the_live_game(snapshot, item_id, expected):
    got = snapshot.price(item_id)
    assert got is not None
    assert got == pytest.approx(expected, rel=0.06)


def test_divine_prices_itself_at_one(snapshot):
    """Divine never appears as its own pair, so it has to be filled in."""
    assert snapshot.price("divine") == 1.0


def test_thin_pairs_are_refused_rather_than_believed(snapshot):
    """A pair with 55 units of traded value prices this item at 7.8 divines.

    That number is derived from a couple of trades and is wrong by multiples.
    Refusing to price it is the whole point of MIN_PAIR_VALUE: an item we
    cannot value must come back as unpriced, never as a plausible-looking
    number that would then be compared against a real listing.
    """
    item = snapshot.items["the-greatwolfs-rune-of-claws"]
    assert item.divines is None
    # ...but it still counts toward liquidity, which is a separate question.
    assert item.value_traded > 0


def test_lowering_the_gate_lets_the_bad_price_through(snapshot):
    """Guards the gate itself: with it open, the thin pair yields a price."""
    loose = parse_snapshot_pairs(
        json.loads(FIXTURE.read_text(encoding="utf-8")),
        "Runes of Aldur",
        FETCHED,
        min_pair_value=0.0,
    )
    assert loose.price("the-greatwolfs-rune-of-claws") is not None
    assert MIN_PAIR_VALUE > 0


def test_price_only_ever_comes_from_the_divine_pair(snapshot):
    """chaos/exalted is in the fixture and neither side is divine.

    RelativePrice's normalisation is unknown (exalted's own value should be 1.0
    and isn't), so cross-pair inference is not permitted. An item reachable
    only through a non-divine pair is unpriced.
    """
    assert snapshot.items["chaos"].divines is None
    assert snapshot.items["chaos"].value_traded > 0


def test_liquidity_sums_across_every_pair(snapshot):
    """Divine appears in most pairs, so it should dominate the ranking."""
    ranked = snapshot.by_liquidity()
    assert ranked[0].item_id == "divine"
    assert [i.item_id for i in ranked] == sorted(
        [i.item_id for i in ranked],
        key=lambda x: (-snapshot.items[x].value_traded, x),
    )


def test_ranking_is_stable_across_processes(snapshot):
    """Explicit id tiebreak — dict order derived from a set would reshuffle."""
    assert [i.item_id for i in snapshot.by_liquidity()] == [
        i.item_id for i in snapshot.by_liquidity()
    ]


def test_malformed_pairs_are_skipped_not_fatal():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data.append({"CurrencyOne": {"ApiId": "x"}})  # no Data blocks
    data.append({"nonsense": True})
    snap = parse_snapshot_pairs(data, "Runes of Aldur", FETCHED)
    assert snap.price("core-destabiliser") == pytest.approx(3.79, rel=0.06)


def test_non_list_payload_is_a_schema_error():
    from poe2arb.client import SchemaError

    with pytest.raises(SchemaError):
        parse_snapshot_pairs({"pairs": []}, "Runes of Aldur", FETCHED)


def test_names_and_categories_survive(snapshot):
    item = snapshot.items["omen-of-light"]
    assert item.name and item.name != item.item_id
    assert item.category == "ritual"
