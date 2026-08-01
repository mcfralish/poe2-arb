"""Cross-venue candidate maths: lot sizing, the integer floor, ranking, whispers."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from poe2arb.client import parse_listings
from poe2arb.listings import (
    Band,
    Listing,
    build_candidates,
    classify,
    fill_weight,
    plan_trade,
    rank_candidates,
    replan_units,
    smallest_lot,
    whisper_text,
)


def listing(**kw) -> Listing:
    base = dict(
        item_id="core-destabiliser",
        account="seller#1234",
        character="Sellerman",
        pay_amount=2.0,
        get_amount=1.0,
        stock=1.0,
        whisper="@{} Hi, I'd like to buy your {{0}} for my {{1}} in Runes of Aldur".format("Sellerman"),
        item_whisper="{0} Core Destabiliser",
        pay_whisper="{0} Divine Orb",
    )
    base.update(kw)
    return Listing(**base)


# --- the profit model ------------------------------------------------------

def test_matches_the_one_real_completed_trade():
    """1 Core Destabiliser bought for 2 div, CE quoted 3.79, realised 3.

    This is the only trade we have ground truth for, and it is the whole reason
    proceeds are floored rather than multiplied out.
    """
    plan = plan_trade(pay_amount=2.0, get_amount=1.0, stock=1.0, ce_divines=3.79)
    assert plan is not None
    assert plan.lots == 1
    assert plan.proceeds_divines == 3.0
    assert plan.profit_divines == 1.0
    # The naive gap x quantity figure would have promised 1.79.
    assert plan.rounding_loss == pytest.approx(0.79)


def test_floor_can_erase_the_entire_margin():
    """A gap that looks real vanishes once proceeds are floored."""
    # 1 unit worth 1.8 div bought for 1 div looks like +0.8. It is not: you
    # receive 1 divine, so you break even.
    plan = plan_trade(pay_amount=1.0, get_amount=1.0, stock=1.0, ce_divines=1.8)
    assert plan is None


def test_bulk_amortises_the_rounding_loss():
    """Same listing, more lots: the absolute haircut stays under a divine."""
    one = plan_trade(pay_amount=2.0, get_amount=1.0, stock=1.0, ce_divines=3.79)
    ten = plan_trade(pay_amount=2.0, get_amount=1.0, stock=10.0, ce_divines=3.79)
    assert one is not None and ten is not None
    assert one.rounding_loss == pytest.approx(0.79)
    assert ten.rounding_loss < 1.0
    # Profit per divine spent improves with size.
    assert ten.profit_divines / ten.cost_divines > one.profit_divines / one.cost_divines


def test_profit_is_not_monotonic_in_lots_so_we_search():
    """The floor makes the largest affordable trade not always the best one."""
    # 1 lot: floor(2.5) - 2 = 0. 2 lots: floor(5.0) - 4 = 1. Increments alternate.
    plan = plan_trade(pay_amount=2.0, get_amount=1.0, stock=2.0, ce_divines=2.5)
    assert plan is not None
    assert plan.lots == 2
    assert plan.profit_divines == 1.0


def test_bankroll_caps_the_trade():
    """The field test hit this: a 10-for-30 listing is unreachable with 9 divines."""
    plan = plan_trade(
        pay_amount=3.0, get_amount=1.0, stock=10.0, ce_divines=5.0, bankroll_units=9.0
    )
    assert plan is not None
    assert plan.lots == 3
    assert plan.cost_divines == 9.0


def test_bankroll_buys_part_of_an_advertised_lot():
    """A 10-for-30 listing on a 9-divine bankroll is 3 items for 9, not nothing.

    The ratio divides: 30:10 is 3:1 in lowest terms, and the trade site lets you
    ask along it. Asked for from the field 2026-07-31 — the old behaviour hid
    every listing bigger than the bankroll rather than asking for less of it.
    """
    plan = plan_trade(
        pay_amount=30.0, get_amount=10.0, stock=10.0, ce_divines=5.0, bankroll_units=9.0
    )
    assert plan is not None
    assert plan.units == 3.0
    assert plan.pay_units == 9.0
    assert plan.cost_divines == 9.0


def test_indivisible_ratios_still_trade_whole():
    """3-for-7 divides at nothing smaller: partial currency cannot be traded."""
    assert plan_trade(
        pay_amount=7.0, get_amount=3.0, stock=9.0, ce_divines=5.0, bankroll_units=6.0
    ) is None


def test_zero_bankroll_means_unbounded():
    plan = plan_trade(
        pay_amount=1.0, get_amount=1.0, stock=50.0, ce_divines=3.0, bankroll_units=0.0
    )
    assert plan is not None
    assert plan.lots == 50


def test_lots_respect_multi_unit_listings():
    """A '1 divine : 3 items' listing trades in threes, not ones."""
    plan = plan_trade(pay_amount=1.0, get_amount=3.0, stock=7.0, ce_divines=1.0)
    assert plan is not None
    assert plan.lots == 2          # 7 // 3
    assert plan.units == 6.0
    assert plan.cost_divines == 2.0


def test_no_trade_when_the_listing_is_at_or_above_market():
    assert plan_trade(pay_amount=4.0, get_amount=1.0, stock=5.0, ce_divines=3.79) is None
    assert plan_trade(pay_amount=3.79, get_amount=1.0, stock=5.0, ce_divines=3.79) is None


@pytest.mark.parametrize(
    "kw",
    [
        dict(pay_amount=0, get_amount=1, stock=1, ce_divines=5),
        dict(pay_amount=1, get_amount=0, stock=1, ce_divines=5),
        dict(pay_amount=1, get_amount=1, stock=0, ce_divines=5),
        dict(pay_amount=1, get_amount=1, stock=1, ce_divines=0),
    ],
)
def test_degenerate_inputs_yield_no_plan(kw):
    assert plan_trade(**kw) is None


# --- banding and ranking ---------------------------------------------------

def test_bands_follow_the_measured_fill_pattern():
    assert classify(1.2, min_gap=1.05, max_gap=1.5) is Band.PLAUSIBLE
    assert classify(1.01, min_gap=1.05, max_gap=1.5) is Band.THIN
    assert classify(8.9, min_gap=1.05, max_gap=1.5) is Band.GHOST


def test_thin_still_ranks_above_ghost():
    """A gap inside our error bars beats one the evidence says never fills.

    Seen live: an Omen of Light at 1.04x (profitable, but within the reference
    price's own 0.4-4.7% error) alongside one at 12.47x. The uncertain trade is
    still the better use of a whisper.
    """
    assert Band.THIN.rank < Band.GHOST.rank
    assert Band.PLAUSIBLE.rank < Band.THIN.rank


def test_ghosts_rank_below_plausible_however_profitable():
    """The 12x listing is worth more on paper and fills less often.

    Zero of roughly ten whispers at 3.8x-12.5x got a response; both fills came
    from the smallest gaps sampled. Sorting by profit alone would put the user
    straight back onto the listings that never answer.
    """
    ghost = listing(item_id="omen-of-light", pay_amount=1.0, get_amount=1.0, stock=2.0)
    plausible = listing(item_id="core-destabiliser", pay_amount=11.0, get_amount=1.0, stock=1.0)
    cands = build_candidates(
        [ghost, plausible],
        {"omen-of-light": 12.48, "core-destabiliser": 12.48},
        {},
        min_gap=1.05,
        max_gap=1.5,
    )
    ranked = rank_candidates(cands)
    assert ranked[0].band is Band.PLAUSIBLE
    assert ranked[-1].band is Band.GHOST
    # ...and the ghost really was the more profitable one on paper.
    assert ranked[-1].profit_divines > ranked[0].profit_divines


def test_ghosts_are_demoted_not_dropped():
    ghost = listing(pay_amount=1.0, get_amount=1.0, stock=2.0)
    cands = build_candidates([ghost], {"core-destabiliser": 12.0}, {}, min_gap=1.05, max_gap=1.5)
    assert len(cands) == 1
    assert cands[0].band is Band.GHOST


def test_ranking_is_stable_across_processes():
    """Explicit tiebreaks all the way down — no set or dict iteration order."""
    ls = [listing(account=f"acct{i}#1", pay_amount=2.0, stock=1.0) for i in range(6)]
    cands = build_candidates(ls, {"core-destabiliser": 3.79}, {}, min_gap=1.05, max_gap=1.5)
    first = [c.listing.account for c in rank_candidates(cands)]
    second = [c.listing.account for c in rank_candidates(list(reversed(cands)))]
    assert first == second


def test_items_without_a_ce_price_are_skipped_not_valued_at_zero():
    cands = build_candidates([listing()], {}, {}, min_gap=1.05, max_gap=1.5)
    assert cands == []


def test_gap_reports_against_unit_price_not_lot_price():
    c = build_candidates(
        [listing(pay_amount=2.0, get_amount=2.0, stock=4.0)],
        {"core-destabiliser": 2.0},
        {},
        min_gap=1.05,
        max_gap=1.5,
    )
    assert c[0].gap == pytest.approx(2.0)  # 2 div for 2 units = 1 div each vs CE 2


# --- whisper composition ---------------------------------------------------

def test_whisper_uses_gggs_template_and_planned_quantity():
    c = build_candidates(
        [listing(pay_amount=3.0, get_amount=1.0, stock=6.0)],
        {"core-destabiliser": 5.0},
        {},
        min_gap=1.05,
        max_gap=1.5,
    )[0]
    text = whisper_text(c)
    assert text is not None
    assert "6 Core Destabiliser" in text
    assert "18 Divine Orb" in text
    assert text.startswith("@Sellerman")


def test_whisper_preserves_the_sellers_language():
    """GGG localises the template; we substitute, never rewrite."""
    zh = listing(
        whisper="@米朵麦朵 嗨，我想在Runes of Aldur用{1}購買你的{0}",
        item_whisper="{0} 無效石",
        pay_whisper="{0} 崇高石",
        pay_amount=1.0,
        get_amount=1.0,
        stock=1.0,
    )
    c = build_candidates([zh], {"core-destabiliser": 3.0}, {}, min_gap=1.05, max_gap=1.5)[0]
    text = whisper_text(c)
    assert text == "@米朵麦朵 嗨，我想在Runes of Aldur用1 崇高石購買你的1 無效石"


def test_whole_quantities_have_no_trailing_decimal():
    c = build_candidates(
        [listing(pay_amount=2.0, get_amount=1.0, stock=1.0)],
        {"core-destabiliser": 3.79},
        {},
        min_gap=1.05,
        max_gap=1.5,
    )[0]
    text = whisper_text(c)
    assert "1 Core Destabiliser" in text and "1.0" not in text


def test_missing_template_disables_the_whisper_rather_than_faking_one():
    c = build_candidates(
        [listing(whisper=None, item_whisper=None, pay_whisper=None)],
        {"core-destabiliser": 3.79},
        {},
        min_gap=1.05,
        max_gap=1.5,
    )[0]
    assert whisper_text(c) is None


# --- parsing ---------------------------------------------------------------

def _response(**over) -> dict:
    entry = {
        "listing": {
            "indexed": "2026-07-28T09:00:00+00:00",
            "account": {
                "name": "seller#1234",
                "online": {"league": "Runes of Aldur"},
                "lastCharacterName": "Sellerman",
            },
            "whisper": "@Sellerman buy {0} for {1}",
            "offers": [
                {
                    "exchange": {"currency": "divine", "amount": 3, "whisper": "{0} Divine Orb"},
                    "item": {
                        "currency": "core-destabiliser",
                        "amount": 1,
                        "stock": 10,
                        "whisper": "{0} Core Destabiliser",
                    },
                }
            ],
        }
    }
    entry["listing"].update(over)
    return {"result": {"abc": entry}}


def test_parse_listings_keeps_what_the_book_parser_throws_away():
    [got] = parse_listings(_response(), "core-destabiliser")
    assert got.account == "seller#1234"
    assert got.character == "Sellerman"
    assert got.pay_amount == 3.0 and got.get_amount == 1.0 and got.stock == 10.0
    assert got.indexed == datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)
    assert got.afk is False
    assert got.whisper and got.item_whisper and got.pay_whisper


def test_parse_listings_detects_afk():
    data = _response(account={
        "name": "seller#1234",
        "online": {"league": "Runes of Aldur", "status": "afk"},
        "lastCharacterName": "Sellerman",
    })
    [got] = parse_listings(data, "core-destabiliser")
    assert got.afk is True


def test_parse_listings_ignores_offers_in_the_wrong_direction():
    """A response can carry both directions; paying in the item isn't the trade."""
    assert parse_listings(_response(), "divine") == []


def test_parse_listings_survives_a_malformed_entry():
    data = _response()
    data["result"]["broken"] = {"listing": {"account": {"name": "x#1"}, "offers": [{"item": {}}]}}
    assert len(parse_listings(data, "core-destabiliser")) == 1


def test_parse_listings_handles_the_empty_list_shape():
    """No matches arrive as an empty list, not an empty object. Seen live."""
    assert parse_listings({"result": []}, "core-destabiliser") == []


def test_listing_age():
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    assert listing(indexed=now - timedelta(hours=3)).age_s(now) == pytest.approx(10800)
    assert listing(indexed=None).age_s(now) is None


def test_whisper_quotes_the_price_in_the_sellers_currency():
    """Regression: an exalted-priced listing was offered `cost_divines` exalted.

    Seen live — a Divine Orb listing at 2412 exalted produced a message
    offering "5.58151 Сфера возвышения". The two figures coincide only when the
    listing is priced in divines, which is why divine-only sweeps never caught it.
    """
    ex = Listing(
        item_id="divine",
        account="Kkokos#1",
        character="Kkokos",
        pay_currency="exalted",
        pay_amount=1206.0,   # exalted per lot
        get_amount=4.0,      # divines per lot
        stock=8.0,
        whisper="@Kkokos buy {0} for {1}",
        item_whisper="{0} Divine Orb",
        pay_whisper="{0} Exalted Orb",
    )
    [c] = build_candidates(
        [ex],
        {"divine": 1.0, "exalted": 0.00231634},
        {},
        min_gap=1.05,
        max_gap=1.5,
        sale_unit_divines=0.00231634,
    )
    assert c.plan.units == 8.0
    assert c.plan.pay_units == 2412.0
    text = whisper_text(c)
    assert "8 Divine Orb" in text
    assert "2412 Exalted Orb" in text     # 1206:4 reduces to 603:2, so four lots
    assert "5.58" not in text             # the divine-denominated cost


def test_exalted_listing_is_priced_in_divines_for_comparison():
    ex = Listing(
        item_id="core-destabiliser", account="s#1", character="S",
        pay_currency="exalted", pay_amount=1000.0, get_amount=1.0, stock=2.0,
    )
    [c] = build_candidates(
        [ex], {"core-destabiliser": 3.79, "exalted": 0.00231634}, {},
        min_gap=1.05, max_gap=1.5, sale_unit_divines=0.00231634,
    )
    assert c.unit_price_divines == pytest.approx(2.316, abs=0.01)
    assert c.gap == pytest.approx(1.636, abs=0.01)


# --- the bankroll is per-currency, not a pooled divine total ----------------

def exalted_listing(pay_amount):
    """A seller who wants exalted, not divines."""
    return Listing(
        item_id="omen", account="s#1", character="s",
        pay_amount=pay_amount, get_amount=1.0, stock=10.0, indexed=None,
        pay_currency="exalted",
    )


PRICES = {"omen": 12.0, "divine": 1.0, "exalted": 1 / 432}


def test_a_divine_bankroll_does_not_fund_an_exalted_seller():
    """The whole reason the pots are separate: you cannot pay in what you
    don't hold, and converting costs the Currency Exchange spread."""
    [candidate] = build_candidates(
        [exalted_listing(1000.0)], PRICES, {}, min_gap=1.05, max_gap=1.5,
        bankroll={"divine": 500.0},
    )
    # 500 divines is ~216,000 exalted, so a pooled figure would allow many
    # lots. Holding no exalted, the cap is the seller's currency: unconstrained
    # here, because "exalted" is absent from the bankroll entirely.
    assert candidate.plan.lots == 10          # limited by stock, not by divines


def test_an_exalted_bankroll_caps_an_exalted_seller():
    [candidate] = build_candidates(
        [exalted_listing(1000.0)], PRICES, {}, min_gap=1.05, max_gap=1.5,
        bankroll={"exalted": 2500.0},
    )
    assert candidate.plan.lots == 2           # 2500 // 1000


def test_each_currency_is_capped_by_its_own_pot():
    divine_seller = Listing(
        item_id="omen", account="d#1", character="d",
        pay_amount=3.0, get_amount=1.0, stock=10.0, indexed=None,
        pay_currency="divine",
    )
    candidates = build_candidates(
        [divine_seller, exalted_listing(1000.0)], PRICES, {},
        min_gap=1.05, max_gap=1.5,
        bankroll={"divine": 9.0, "exalted": 2500.0},
    )
    by_account = {c.listing.account: c.plan.lots for c in candidates}
    assert by_account == {"d#1": 3, "s#1": 2}


def test_an_absent_currency_is_unconstrained():
    """Capping a currency the user never entered would hide trades silently."""
    [candidate] = build_candidates(
        [exalted_listing(1.0)], PRICES, {}, min_gap=1.05, max_gap=1.5,
        bankroll={},
    )
    assert candidate.plan.lots == 10


# --- risk appetite: how far to chase long shots ----------------------------

def graded_listing(account, pay_amount):
    return Listing(
        item_id="omen", account=account, character=account,
        pay_amount=pay_amount, get_amount=1.0, stock=1.0, indexed=None,
        pay_currency="divine",
    )


def graded_candidates():
    """Three listings, one per band, the ghost by far the most profitable."""
    listings = [
        graded_listing("plausible", 10.0),   # 1.2x gap  -> +2 div
        graded_listing("thin", 11.8),        # 1.017x    -> +0.2 div
        graded_listing("ghost", 1.0),        # 12x       -> +11 div
    ]
    return build_candidates(
        listings, {"omen": 12.0, "divine": 1.0}, {},
        min_gap=1.05, max_gap=1.5,
    )


def order(candidates):
    return [c.listing.account for c in candidates]


def test_bands_are_labelled_as_expected():
    """Guards the fixture: the rest of these tests mean nothing otherwise."""
    by_account = {c.listing.account: c.band for c in graded_candidates()}
    assert by_account == {
        "plausible": Band.PLAUSIBLE, "thin": Band.THIN, "ghost": Band.GHOST,
    }


def test_zero_appetite_buries_the_long_shot():
    """The default. The 12x listing is the most profitable and never fills."""
    assert order(rank_candidates(graded_candidates(), risk_appetite=0.0)) == [
        "plausible", "thin", "ghost",
    ]


def test_full_appetite_ranks_on_profit_alone():
    assert order(rank_candidates(graded_candidates(), risk_appetite=1.0)) == [
        "ghost", "plausible", "thin",
    ]


def test_the_default_matches_zero_appetite():
    assert order(rank_candidates(graded_candidates())) == order(
        rank_candidates(graded_candidates(), risk_appetite=0.0)
    )


def test_long_shots_climb_gradually_rather_than_all_at_once():
    """A slider people can tune, not a switch with two positions."""
    positions = [
        order(rank_candidates(graded_candidates(), risk_appetite=a)).index("ghost")
        for a in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]
    assert positions == sorted(positions, reverse=True)
    assert positions[0] == 2 and positions[-1] == 0


def test_nothing_is_ever_dropped_at_any_appetite():
    for appetite in (0.0, 0.5, 1.0):
        assert len(rank_candidates(graded_candidates(), risk_appetite=appetite)) == 3


def test_appetite_outside_the_range_is_clamped():
    assert fill_weight(Band.GHOST, -5.0) == 0.0
    assert fill_weight(Band.GHOST, 99.0) == 1.0


def test_a_proven_band_is_believed_at_any_appetite():
    assert fill_weight(Band.PLAUSIBLE, 0.0) == 1.0
    assert fill_weight(Band.PLAUSIBLE, 1.0) == 1.0


def test_ranking_is_stable_across_runs():
    """Set and dict iteration reshuffle per process; the sort must not."""
    once = order(rank_candidates(graded_candidates(), risk_appetite=0.5))
    assert all(
        order(rank_candidates(graded_candidates(), risk_appetite=0.5)) == once
        for _ in range(5)
    )


class TestWhatTheWhisperOffered:
    """`plan.cost_divines` is the same money in a unit that appears nowhere in
    the trade. A listing whispered as "2412 exalted" showed as "5.6 div"."""

    def _exalted_candidate(self, *, pay=2412.0, get=1.0, stock=9.0):
        listing = Listing(
            item_id="omen", account="Xiaolong#1", character="Xiaolong",
            pay_currency="exalted", pay_amount=pay, get_amount=get, stock=stock,
        )
        [c] = build_candidates(
            [listing], {"omen": 6.9, "divine": 1.0, "exalted": 0.00231},
            {"omen": "Omen of Whittling"},
            min_gap=1.05, max_gap=1.5, sale_unit_divines=0.00231,
            settle_currency="exalted",
        )
        return c

    def test_pay_total_is_the_sellers_currency_not_divines(self):
        c = self._exalted_candidate()
        assert c.pay_total == c.plan.lots * 2412.0
        assert c.listing.pay_currency == "exalted"
        # The same money, in the unit the maths is done in.
        assert c.plan.cost_divines == pytest.approx(c.pay_total * 0.00231)

    def test_pay_total_matches_the_amount_in_the_whisper(self):
        """The one number the user has to recognise when a reply arrives."""
        listing = Listing(
            item_id="omen", account="X#1", character="X",
            pay_currency="exalted", pay_amount=2412.0, get_amount=1.0, stock=9.0,
            whisper="@X buy {0} for {1}",
            item_whisper="{0} Omen", pay_whisper="{0} Exalted",
        )
        [c] = build_candidates(
            [listing], {"omen": 6.9, "divine": 1.0, "exalted": 0.00231},
            {"omen": "Omen of Whittling"},
            min_gap=1.05, max_gap=1.5, sale_unit_divines=0.00231,
        )
        assert f"{c.pay_total:.0f} Exalted" in whisper_text(c)

    def test_pay_per_unit_is_in_the_same_currency(self):
        c = self._exalted_candidate(pay=4824.0, get=2.0)
        assert c.pay_per_unit == 2412.0

    def test_a_candidate_records_what_its_profit_was_floored_to(self):
        """The setting can change afterwards; the row's own figure cannot."""
        assert self._exalted_candidate().settle_currency == "exalted"

    def test_it_defaults_to_the_pessimistic_reading(self):
        listing = Listing(
            item_id="omen", account="X#1", character="X",
            pay_amount=5.0, get_amount=1.0, stock=2.0,
        )
        [c] = build_candidates(
            [listing], {"omen": 6.9, "divine": 1.0}, {"omen": "Omen"},
            min_gap=1.05, max_gap=1.5,
        )
        assert c.settle_currency == "divine"


# --- sub-lot quantities and after-the-fact corrections ----------------------


def test_smallest_lot_reduces_to_lowest_terms():
    assert smallest_lot(100.0, 10.0) == (10.0, 1.0)
    assert smallest_lot(7.0, 3.0) == (7.0, 3.0)
    # Non-integer amounts are left exactly as they came.
    assert smallest_lot(2.5, 1.0) == (2.5, 1.0)


def test_the_search_window_still_finds_the_best_quantity():
    """The tail-only search must agree with checking every k."""
    for stock in (5.0, 40.0, 137.0):
        for ce in (2.5, 3.79, 11.0):
            plan = plan_trade(
                pay_amount=2.0, get_amount=1.0, stock=stock, ce_divines=ce
            )
            brute = max(
                (
                    __import__("math").floor(k * ce) - k * 2.0
                    for k in range(1, int(stock) + 1)
                ),
                default=0.0,
            )
            assert plan is not None
            assert plan.profit_divines == pytest.approx(brute)


def test_replan_units_shrinks_a_trade_to_what_was_actually_bought():
    """The field case: whispered for 18, the seller only had 3."""
    [c] = build_candidates(
        [listing(pay_amount=1.0, get_amount=1.0, stock=18.0)],
        {"core-destabiliser": 3.79},
        {},
        min_gap=1.05,
        max_gap=1.5,
    )
    assert c.plan.units == 18.0
    fewer = replan_units(c, 3.0)
    assert fewer.plan.units == 3.0
    assert fewer.plan.pay_units == 3.0
    assert fewer.plan.cost_divines == 3.0
    assert fewer.profit_divines == pytest.approx(math.floor(3 * 3.79) - 3.0)
    # The listing itself is untouched — only the quantity asked for changed.
    assert fewer.listing is c.listing
    assert "3 Core Destabiliser" in whisper_text(fewer)


def test_replan_units_clamps_to_the_original_ask():
    [c] = build_candidates(
        [listing(pay_amount=1.0, get_amount=1.0, stock=4.0)],
        {"core-destabiliser": 3.79},
        {},
        min_gap=1.05,
        max_gap=1.5,
    )
    assert replan_units(c, 99.0).plan.units == c.plan.units
    assert replan_units(c, 0.0).plan.units == 1.0
