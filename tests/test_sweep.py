"""Sweep orchestration: item selection gates, and resilience of the run itself."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from poe2arb.client import ScanCancelled
from poe2arb.config import Config
from poe2arb.listings import Band, Listing
from poe2arb.scout import parse_snapshot_pairs
from poe2arb.sweep import run_sweep, select_sweep_items

FIXTURE = Path(__file__).parent / "fixtures" / "scout_snapshot_pairs.json"


@pytest.fixture
def snapshot():
    return parse_snapshot_pairs(
        json.loads(FIXTURE.read_text(encoding="utf-8")),
        "Runes of Aldur",
        datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc),
    )


def cfg(**kw) -> Config:
    base = dict(
        sweep_items=50,
        sweep_min_value_divines=2.0,
        sweep_min_ce_traded=0.0,
        min_gap_ratio=1.05,
        max_gap_ratio=1.5,
        sale_currency="exalted",
        min_profit_divines=0.25,
    )
    base.update(kw)
    return Config(**base)


class FakeGgg:
    def __init__(self, per_item: dict[str, list[Listing]] | None = None, fail: set[str] = frozenset()):
        self.per_item = per_item or {}
        self.fail = fail
        self.asked: list[str] = []
        self.closed = False

    def fetch_listings(self, league: str, want: str, have: str = "divine"):
        self.asked.append(want)
        if want in self.fail:
            raise RuntimeError("boom")
        return list(self.per_item.get(want, []))

    def close(self):
        self.closed = True


def listing(item_id: str, pay: float, get: float = 1.0, stock: float = 1.0, account="s#1") -> Listing:
    return Listing(
        item_id=item_id,
        account=account,
        character="Char",
        pay_amount=pay,
        get_amount=get,
        stock=stock,
        whisper="@Char buy {0} for {1}",
        item_whisper="{0} Thing",
        pay_whisper="{0} Divine Orb",
    )


# --- item selection --------------------------------------------------------

def test_selection_drops_items_too_cheap_to_clear_the_floor(snapshot):
    """Exalted is worth 1/430 of a divine; no lot of it can profit here."""
    picked = select_sweep_items(snapshot, cfg())
    assert "exalted" not in picked
    assert "fracturing-orb" in picked


def test_selection_drops_items_the_ce_barely_trades(snapshot):
    """A discount is worthless if you cannot sell the item afterwards."""
    everything = select_sweep_items(snapshot, cfg(sweep_min_ce_traded=0.0))
    gated = select_sweep_items(snapshot, cfg(sweep_min_ce_traded=10_000_000.0))
    assert set(gated) < set(everything)


def test_selection_drops_unpriced_items(snapshot):
    """The thin-pair item has no believable price, so it cannot be compared."""
    assert "the-greatwolfs-rune-of-claws" not in select_sweep_items(snapshot, cfg())


def test_selection_is_ordered_by_exit_liquidity(snapshot):
    picked = select_sweep_items(snapshot, cfg())
    traded = [snapshot.items[i].value_traded for i in picked]
    assert traded == sorted(traded, reverse=True)


def test_selection_respects_the_item_cap(snapshot):
    assert len(select_sweep_items(snapshot, cfg(sweep_items=2))) == 2


def test_selection_honours_exclusions(snapshot):
    picked = select_sweep_items(snapshot, cfg(exclude_currencies=["fracturing-orb"]))
    assert "fracturing-orb" not in picked


def test_expensive_items_are_not_cut(snapshot):
    """Six spot-check samples suggested a ceiling; that is not enough to cut one.

    Sweeping them costs minutes and measured yield can prune them later.
    """
    picked = select_sweep_items(snapshot, cfg())
    assert any(snapshot.items[i].divines and snapshot.items[i].divines > 5 for i in picked)


# --- running the sweep -----------------------------------------------------

def test_sweep_prices_listings_against_the_ce(snapshot):
    ggg = FakeGgg({"core-destabiliser": [listing("core-destabiliser", pay=2.0)]})
    result = run_sweep(cfg(), ggg=ggg, snapshot=snapshot)
    [cand] = [c for c in result.candidates if c.listing.item_id == "core-destabiliser"]
    assert cand.ce_divines == pytest.approx(3.79, rel=0.06)
    assert cand.plan.lots == 1
    # The trade that actually filled, settled in exalted rather than divines.
    assert cand.profit_divines == pytest.approx(1.57, abs=0.01)


def test_settlement_currency_decides_whether_a_trade_exists(snapshot):
    """The same listing is worth 0.57 divines or nothing, depending on payout.

    Buying one unit at 3 against a 3.57 CE price: settle in divines and
    proceeds floor to 3, so the trade nets exactly zero and should not be
    shown. Settle in exalted — 432x finer — and it clears 0.57. This is the
    single largest correction the sweep makes to a hand-traded result.
    """
    ggg = FakeGgg({"core-destabiliser": [listing("core-destabiliser", pay=3.0)]})

    in_divines = run_sweep(cfg(sale_currency="divine"), ggg=ggg, snapshot=snapshot)
    assert [c for c in in_divines.candidates if c.listing.item_id == "core-destabiliser"] == []

    in_exalted = run_sweep(cfg(sale_currency="exalted"), ggg=ggg, snapshot=snapshot)
    [cand] = [c for c in in_exalted.candidates if c.listing.item_id == "core-destabiliser"]
    assert cand.profit_divines == pytest.approx(0.57, abs=0.01)


def test_unknown_settlement_currency_falls_back_to_divines(snapshot):
    """Pessimistic, not wrong: an unpriceable payout currency must not inflate profit."""
    ggg = FakeGgg({"core-destabiliser": [listing("core-destabiliser", pay=3.0)]})
    result = run_sweep(cfg(sale_currency="nonexistent-orb"), ggg=ggg, snapshot=snapshot)
    assert [c for c in result.candidates if c.listing.item_id == "core-destabiliser"] == []


def test_exalted_priced_listings_are_costed_correctly(snapshot):
    """Exalted is the more common denomination on this venue and must not be
    read as if the amounts were divines."""
    ex = listing("core-destabiliser", pay=1000.0, stock=1.0)
    ex = type(ex)(**{**ex.__dict__, "pay_currency": "exalted"})
    ggg = FakeGgg({"core-destabiliser": [ex]})
    result = run_sweep(cfg(), ggg=ggg, snapshot=snapshot)
    [cand] = [c for c in result.candidates if c.listing.item_id == "core-destabiliser"]
    # 1000 exalted is ~2.3 divines, not 1000.
    assert cand.unit_price_divines == pytest.approx(2.32, abs=0.05)
    assert cand.plan.cost_divines == pytest.approx(2.32, abs=0.05)


def test_sweep_ranks_plausible_ahead_of_ghosts(snapshot):
    """That the sweep applies `rank_candidates` at all, not what it decides.

    The ghost pays 8 rather than 1, because since `FILL_PRIOR[GHOST]` was fitted
    to 0.16 a ghost with enough profit *should* outrank a plausible — the
    crossover itself is pinned in tests/test_listings.py.
    """
    ggg = FakeGgg({
        "omen-of-light": [
            listing("omen-of-light", pay=8.0, stock=1.0, account="ghost#1"),
            listing("omen-of-light", pay=11.0, stock=1.0, account="real#1"),
        ]
    })
    result = run_sweep(cfg(), ggg=ggg, snapshot=snapshot)
    omens = [c for c in result.candidates if c.listing.item_id == "omen-of-light"]
    assert omens[0].listing.account == "real#1"
    assert omens[0].band is Band.PLAUSIBLE
    assert omens[-1].band is Band.GHOST


def test_one_failing_item_does_not_lose_the_rest(snapshot):
    items = select_sweep_items(snapshot, cfg())
    ggg = FakeGgg(
        {items[1]: [listing(items[1], pay=1.0)]},
        fail={items[0]},
    )
    result = run_sweep(cfg(), ggg=ggg, snapshot=snapshot)
    assert items[0] in result.errors
    assert result.listings_seen == 1
    assert len(ggg.asked) == len(items)  # kept going


def test_cancellation_aborts_the_sweep(snapshot):
    class Cancelling(FakeGgg):
        def fetch_listings(self, league, want, have="divine"):
            raise ScanCancelled()

    with pytest.raises(ScanCancelled):
        run_sweep(cfg(), ggg=Cancelling(), snapshot=snapshot)


def test_progress_is_reported_per_item(snapshot):
    seen = []
    items = select_sweep_items(snapshot, cfg())
    run_sweep(
        cfg(), ggg=FakeGgg(), snapshot=snapshot,
        progress=lambda n, t, what: seen.append((n, t, what)),
    )
    assert [(n, t) for n, t, _ in seen] == [
        (i, len(items)) for i in range(1, len(items) + 1)
    ]


def test_progress_names_the_item_being_fetched(snapshot):
    """"item 14 of 69" can't be told apart from a stall; a name can."""
    seen = []
    run_sweep(
        cfg(), ggg=FakeGgg(), snapshot=snapshot,
        progress=lambda n, t, what: seen.append(what),
    )
    names = {i.name for i in snapshot.items.values()}
    assert seen and all(what in names for what in seen)


# --- stopping and starting again -------------------------------------------
# The maintainer uses the *Find trades* toggle as a pause when replies pile up,
# and a restart used to begin at the top of the list — re-fetching items it had
# just read and re-finding listings already dealt with.


def test_the_item_reached_is_reported_so_a_restart_can_resume(snapshot):
    seen = []
    items = select_sweep_items(snapshot, cfg())
    run_sweep(cfg(), ggg=FakeGgg(), snapshot=snapshot, on_item=seen.append)
    assert seen == items


def test_resuming_rotates_the_list_rather_than_truncating_it(snapshot):
    """The rest of the pass first, then round to what it had already read.

    Truncating would leave the top of the list permanently unswept by anyone
    who pauses often, which is exactly the user this is for.
    """
    seen = []
    items = select_sweep_items(snapshot, cfg())
    assert len(items) > 1
    run_sweep(
        cfg(), ggg=FakeGgg(), snapshot=snapshot,
        on_item=seen.append, resume_from=items[1],
    )
    assert seen == items[1:] + items[:1]


def test_resuming_from_an_item_that_has_gone_starts_at_the_top(snapshot):
    """The universe shifts between sweeps; that is not a reason to fetch none."""
    seen = []
    items = select_sweep_items(snapshot, cfg())
    run_sweep(
        cfg(), ggg=FakeGgg(), snapshot=snapshot,
        on_item=seen.append, resume_from="no-such-item",
    )
    assert seen == items


def test_candidates_are_reported_as_each_item_is_priced(snapshot):
    """A sweep is fifteen minutes long; holding the results to the end meant a
    long silence and then every offer at once (reported from the field
    2026-07-31)."""
    ggg = FakeGgg({
        "core-destabiliser": [listing("core-destabiliser", pay=2.0)],
        "omen-of-light": [listing("omen-of-light", pay=3.0, stock=4.0)],
    })
    batches = []
    result = run_sweep(
        cfg(), ggg=ggg, snapshot=snapshot, on_candidates=batches.append,
    )
    # One call per item that produced anything, and never an empty one.
    assert len(batches) == 2
    assert all(batch for batch in batches)
    streamed = [c.key for batch in batches for c in batch]
    assert sorted(streamed) == sorted(c.key for c in result.candidates)


def test_a_failed_item_streams_nothing_and_does_not_end_the_sweep(snapshot):
    ggg = FakeGgg(
        {"core-destabiliser": [listing("core-destabiliser", pay=2.0)]},
        fail={"omen-of-light"},
    )
    batches = []
    result = run_sweep(cfg(), ggg=ggg, snapshot=snapshot, on_candidates=batches.append)
    assert "omen-of-light" in result.errors
    assert len(batches) == 1


def test_injected_clients_are_not_closed_by_the_sweep(snapshot):
    """The caller owns what the caller passed in."""
    ggg = FakeGgg()
    run_sweep(cfg(), ggg=ggg, snapshot=snapshot)
    assert ggg.closed is False


def test_bankroll_limits_planned_quantity(snapshot):
    ggg = FakeGgg({"omen-of-light": [listing("omen-of-light", pay=3.0, stock=10.0)]})
    rich = run_sweep(cfg(bankroll_divines=0.0), ggg=ggg, snapshot=snapshot)
    poor = run_sweep(cfg(bankroll_divines=6.0), ggg=ggg, snapshot=snapshot)
    assert rich.candidates[0].plan.lots > poor.candidates[0].plan.lots
    assert poor.candidates[0].plan.cost_divines <= 6.0


def test_result_reports_what_was_swept(snapshot):
    ggg = FakeGgg()
    result = run_sweep(cfg(sweep_items=3), ggg=ggg, snapshot=snapshot)
    assert result.items == ggg.asked
    assert result.league == "Runes of Aldur"
    assert result.duration_s >= 0


# --- pre-whisper re-check --------------------------------------------------

from poe2arb.sweep import RecheckStatus, recheck  # noqa: E402


def _candidate(snapshot, pay=11.0, stock=2.0, account="s#1", currency="divine"):
    from poe2arb.listings import build_candidates
    ls = Listing(
        item_id="omen-of-light", account=account, character="Char",
        pay_currency=currency, pay_amount=pay, get_amount=1.0, stock=stock,
        whisper="@Char buy {0} for {1}", item_whisper="{0} Thing", pay_whisper="{0} Coin",
    )
    ce = {i.item_id: i.divines for i in snapshot.priced() if i.divines}
    [c] = build_candidates([ls], ce, {}, min_gap=1.05, max_gap=1.5,
                           sale_unit_divines=ce.get("exalted", 1.0))
    return c


class RecheckGgg:
    def __init__(self, listings): self.listings = listings; self.uncached = False
    def fetch_listings(self, league, want, have=("divine", "exalted"), *, use_cache=True):
        self.uncached = not use_cache
        return list(self.listings)
    def close(self): pass


def test_recheck_confirms_a_listing_that_is_still_there(snapshot):
    c = _candidate(snapshot)
    ggg = RecheckGgg([c.listing])
    got = recheck(cfg(), c, ggg=ggg)
    assert got.status is RecheckStatus.LIVE
    assert got.worth_whispering


def test_recheck_bypasses_the_cache(snapshot):
    """A cached answer would confirm the very data the check exists to doubt."""
    c = _candidate(snapshot)
    ggg = RecheckGgg([c.listing])
    recheck(cfg(), c, ggg=ggg)
    assert ggg.uncached is True


def test_recheck_catches_a_listing_that_has_gone(snapshot):
    """Two of the first four field attempts failed exactly this way."""
    c = _candidate(snapshot)
    got = recheck(cfg(), c, ggg=RecheckGgg([]))
    assert got.status is RecheckStatus.GONE
    assert not got.worth_whispering


def test_recheck_does_not_match_a_different_seller(snapshot):
    c = _candidate(snapshot, account="s#1")
    other = _candidate(snapshot, account="someone-else#9").listing
    assert recheck(cfg(), c, ggg=RecheckGgg([other])).status is RecheckStatus.GONE


def test_recheck_does_not_match_a_reposted_price(snapshot):
    """A seller who re-listed higher is not the trade that was planned."""
    c = _candidate(snapshot, pay=11.0)
    reposted = _candidate(snapshot, pay=12.0).listing
    assert recheck(cfg(), c, ggg=RecheckGgg([reposted])).status is RecheckStatus.GONE


def test_recheck_does_not_match_across_denominations(snapshot):
    c = _candidate(snapshot, pay=11.0, currency="divine")
    same_number_different_currency = _candidate(
        snapshot, pay=11.0, currency="exalted"
    ).listing
    got = recheck(cfg(), c, ggg=RecheckGgg([same_number_different_currency]))
    assert got.status is RecheckStatus.GONE


def test_recheck_reports_reduced_stock_rather_than_failing(snapshot):
    c = _candidate(snapshot, stock=5.0)
    shrunk = Listing(**{**c.listing.__dict__, "stock": 2.0})
    got = recheck(cfg(), c, ggg=RecheckGgg([shrunk]))
    assert got.status is RecheckStatus.REDUCED
    assert got.worth_whispering            # smaller trade is still a trade
    assert "stock down" in got.detail


def test_a_failed_recheck_does_not_block_the_user(snapshot):
    """Unknown is not evidence of absence — don't talk them out of a real trade."""
    class Broken(RecheckGgg):
        def fetch_listings(self, *a, **k): raise RuntimeError("network down")

    got = recheck(cfg(), _candidate(snapshot), ggg=Broken([]))
    assert got.status is RecheckStatus.UNKNOWN
    assert got.worth_whispering


# --- league resolution -----------------------------------------------------

def test_league_is_never_silently_standard(monkeypatch):
    """A default install must sweep the league being played, not the permanent one.

    `cfg.league or "Standard"` shipped through 0.4.0. Measured 2026-07-30,
    Standard priced Omen of Whittling 5.7x above the temp league, so the mismatch
    made every listing look like a windfall against sellers who could never
    answer.
    """
    from poe2arb import sweep as sweep_mod

    calls = []

    class FakeNinja:
        def __init__(self, cfg):
            calls.append(cfg)

        def current_league(self):
            return "Runes of Aldur"

        def close(self):
            pass

    monkeypatch.setattr("poe2arb.client.NinjaClient", FakeNinja)
    assert sweep_mod.resolve_league(Config()) == "Runes of Aldur"
    assert len(calls) == 1


def test_a_configured_league_is_used_verbatim(monkeypatch):
    """An explicit league must not trigger a lookup that could disagree with it."""
    from poe2arb import sweep as sweep_mod

    def explode(cfg):  # pragma: no cover - must never run
        raise AssertionError("should not consult poe.ninja when league is set")

    monkeypatch.setattr("poe2arb.client.NinjaClient", explode)
    assert sweep_mod.resolve_league(Config(league="Hardcore")) == "Hardcore"
