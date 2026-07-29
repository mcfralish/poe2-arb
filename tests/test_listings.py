"""Cross-venue candidate maths: lot sizing, the integer floor, ranking, whispers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poe2arb.client import parse_listings
from poe2arb.listings import (
    Band,
    Listing,
    build_candidates,
    classify,
    plan_trade,
    rank_candidates,
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
        pay_amount=3.0, get_amount=1.0, stock=10.0, ce_divines=5.0, bankroll_divines=9.0
    )
    assert plan is not None
    assert plan.lots == 3
    assert plan.cost_divines == 9.0


def test_bankroll_below_one_lot_yields_nothing():
    assert plan_trade(
        pay_amount=30.0, get_amount=10.0, stock=10.0, ce_divines=5.0, bankroll_divines=9.0
    ) is None


def test_zero_bankroll_means_unbounded():
    plan = plan_trade(
        pay_amount=1.0, get_amount=1.0, stock=50.0, ce_divines=3.0, bankroll_divines=0.0
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
    assert c.plan.lots == 2
    text = whisper_text(c)
    assert "8 Divine Orb" in text
    assert "2412 Exalted Orb" in text     # 2 lots x 1206 exalted
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
