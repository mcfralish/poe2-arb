"""The trade queue: everything takeable at once, with drivable clocks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from poe2arb.listings import Band, Listing, build_candidates
from poe2arb.outcomes import Outcome
from poe2arb.trade_queue import QueueState, TradeQueue

T0 = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def cand(*, item="omen", pay=11.0, ce=12.0, char="Seller", stock=1.0, whisper=True):
    listing = Listing(
        item_id=item,
        account=f"{char}#1",
        character=char,
        pay_amount=pay,
        get_amount=1.0,
        stock=stock,
        indexed=T0 - timedelta(hours=1),
        whisper=f"@{char} buy {{0}} for {{1}}" if whisper else None,
        item_whisper="{0} Thing" if whisper else None,
        pay_whisper="{0} Coin" if whisper else None,
    )
    out = build_candidates(
        [listing], {item: ce, "divine": 1.0}, {item: "Omen of Light"},
        min_gap=1.05, max_gap=1.5, sale_unit_divines=0.0023,
    )
    return out[0] if out else None


def queue(**kw) -> TradeQueue:
    return TradeQueue(available_ttl_s=600.0, **kw)


# --- everything found is takeable at once ----------------------------------
# The drip — one trade promoted per `offer_window_s` — went in 0.9.0 with the
# rest of the interruption model. A sweep's candidates used to trickle in over
# minutes and sit invisible meanwhile.

def test_every_candidate_is_takeable_the_moment_it_is_found():
    q = queue()
    q.submit([cand(char="A"), cand(char="B"), cand(char="C")], T0)
    assert len(q.available) == 3
    # And no clock has to run for that to be true.
    assert q.tick(T0).changed is False
    assert len(q.available) == 3


def test_ready_is_sorted_best_first():
    """Row 1 is what the hotkey takes — the whole point of the 0.9.0 rework."""
    q = queue()
    q.submit([cand(char="Small", pay=11.5), cand(char="Big", pay=8.5)], T0)
    assert [t.candidate.listing.character for t in q.available] == ["Big", "Small"]
    assert q.next_up.candidate.listing.character == "Big"


def test_a_better_candidate_arriving_takes_the_top_spot():
    """The cost of ranking the list, recorded rather than avoided.

    Presentation order used to be arrival order so that nothing already on
    screen moved. The panel holds the reshuffle while the pointer is over the
    table; the queue itself always reports the true order.
    """
    q = queue()
    q.submit([cand(char="Fair", pay=11.0)], T0)
    q.submit([cand(char="Better", pay=8.5)], T0 + timedelta(seconds=30))
    assert [t.candidate.listing.character for t in q.available] == ["Better", "Fair"]


def test_taking_the_top_trade_promotes_the_next_one():
    q = queue()
    q.submit([cand(char="A", pay=8.5), cand(char="B", pay=11.0)], T0)
    first = q.take_next(T0 + timedelta(seconds=5))
    assert first.candidate.listing.character == "A"
    assert q.next_up.candidate.listing.character == "B"


def test_ghosts_are_not_queued_by_default():
    """At *Long shots* 0 the user has said not to chase them at all."""
    q = queue()
    assert q.submit([cand(pay=1.0)], T0) == 0  # 12x gap -> GHOST
    assert q.next_up is None


def test_ghosts_can_be_queued_if_asked_for():
    q = queue(queue_ghosts=True)
    assert q.submit([cand(pay=1.0)], T0) == 1


def test_a_candidate_with_no_whisper_template_is_never_queued():
    q = queue()
    assert q.submit([cand(whisper=False)], T0) == 0


# --- the listing window ----------------------------------------------------

def test_a_ready_trade_expires_eventually():
    """Listings churn in tens of minutes; holding one longer wastes a whisper."""
    q = queue()
    q.submit([cand()], T0)
    tick = q.tick(T0 + timedelta(seconds=601))
    assert len(tick.expired) == 1
    assert q.available == []


def test_the_clock_starts_when_the_trade_is_found():
    """One deadline, set at `submit` and never restarted.

    Up to 0.8.0 it was set at promotion, which meant a trade's five listed
    minutes began whenever the drip got round to it — and was floored at the
    alert window so a short TTL could not retire a live toast. Both went with
    the promotion step: the countdown now measures the age of the listing,
    which is the thing it was always meant to describe.
    """
    q = queue()   # 600s listed
    q.submit([cand()], T0)
    t = q.next_up
    assert t.seconds_left(T0) == pytest.approx(600.0)
    assert t.seconds_left(T0 + timedelta(seconds=45)) == pytest.approx(555.0)
    assert t.seconds_left(T0 + timedelta(seconds=900)) == 0.0
    q.tick(T0 + timedelta(seconds=900))
    assert t.state is QueueState.EXPIRED


# --- taking and resolving --------------------------------------------------

def test_taking_moves_a_trade_to_awaiting():
    q = queue()
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_next(T0 + timedelta(seconds=10))
    assert taken.state is QueueState.AWAITING
    assert taken.taken_at is not None
    assert q.awaiting == [taken]
    assert q.available == []


def test_any_ready_row_can_be_taken_not_only_the_top_one():
    """Every row carries its own Accept; the hotkey is a shortcut, not the way."""
    q = queue()
    q.submit([cand(char="Best", pay=8.5), cand(char="Rest", pay=11.0)], T0)
    second = q.available[1]
    assert q.take(second.id, T0 + timedelta(seconds=70)) is not None
    assert q.awaiting[0].id == second.id


def test_taking_when_nothing_is_ready_does_nothing():
    """The hotkey on an empty queue must be a no-op, not a crash."""
    q = queue()
    assert q.take_next(T0) is None


def test_an_expired_trade_cannot_be_taken():
    q = queue()
    q.submit([cand()], T0)
    [t] = [x for x in q._trades]
    q.tick(T0 + timedelta(seconds=700))
    assert q.take(t.id, T0 + timedelta(seconds=701)) is None


def test_resolving_records_the_verdict():
    q = queue()
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_next(T0)
    resolved = q.resolve(taken.id, Outcome.FILLED)
    assert resolved.state is QueueState.RESOLVED
    assert resolved.outcome is Outcome.FILLED
    assert q.awaiting == []


def test_only_awaiting_trades_can_be_resolved():
    q = queue()
    q.submit([cand()], T0)
    offered = q.next_up
    assert q.resolve(offered.id, Outcome.FILLED) is None


def test_awaiting_is_newest_first():
    """A reply is almost always to the whisper just sent, so put that on top.

    The opposite order to `available`, deliberately: the rows going cold at the
    bottom resolve themselves without being touched.
    """
    q = queue()
    q.submit([cand(char="A"), cand(char="B")], T0)
    q.tick(T0)
    first = q.take_next(T0 + timedelta(seconds=1))
    q.tick(T0 + timedelta(seconds=2))
    second = q.take_next(T0 + timedelta(seconds=30))
    assert [t.id for t in q.awaiting] == [second.id, first.id]


# --- deduplication ---------------------------------------------------------

def test_a_repeated_sweep_does_not_re_offer_the_same_listing():
    """Sweeps overlap; re-offering would have the user whisper twice."""
    q = queue()
    c = cand()
    assert q.submit([c], T0) == 1
    assert q.submit([cand()], T0 + timedelta(minutes=10)) == 0


def test_an_already_whispered_listing_is_not_re_offered():
    q = queue()
    q.submit([cand()], T0)
    q.tick(T0)
    q.take_next(T0)
    assert q.submit([cand()], T0 + timedelta(minutes=5)) == 0


def test_an_expired_listing_can_come_back():
    """If it's still on the exchange an hour later, it is genuinely on offer again."""
    q = queue()
    q.submit([cand()], T0)
    q.tick(T0)
    q.tick(T0 + timedelta(seconds=61))
    q.tick(T0 + timedelta(seconds=700))
    assert q.submit([cand()], T0 + timedelta(seconds=800)) == 1


# --- housekeeping ----------------------------------------------------------

def test_dropping_dismisses_without_recording_an_attempt():
    q = queue()
    q.submit([cand()], T0)
    offered = q.next_up
    assert q.drop(offered.id) is True
    assert q.available == [] and q.awaiting == []


def test_a_whispered_trade_cannot_be_dropped():
    """It's already logged as an attempt; it needs a verdict, not a delete."""
    q = queue()
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_next(T0)
    assert q.drop(taken.id) is False


def test_stopping_the_sweep_leaves_the_visible_queue_alone():
    """There is no backlog to cancel any more, so stopping stops adding.

    `cancel_pending` existed to drop the QUEUED trades that `tick` would
    otherwise keep promoting for minutes after *Find trades* was switched off
    (reported from the field 2026-07-30). With everything takeable on arrival
    the backlog is gone, and the rows on screen are the user's to finish — the
    toggle is used as a pause when replies pile up.
    """
    q = queue()
    q.submit([cand(char=c) for c in ("A", "B", "C", "D")], T0)
    taken = q.take_next(T0)
    assert len(q.available) == 3
    for i in range(1, 9):   # right up to their own 10-minute deadline
        assert q.tick(T0 + timedelta(minutes=i)).changed is False
    assert [t.id for t in q.awaiting] == [taken.id]
    assert len(q.available) == 3


def test_forget_resolved_keeps_live_work():
    q = queue()
    q.submit([cand(char="A"), cand(char="B")], T0)
    q.tick(T0)
    taken = q.take_next(T0)
    q.resolve(taken.id, Outcome.NO_REPLY)
    q.tick(T0 + timedelta(seconds=1))
    assert q.forget_resolved() == 1
    assert len(q.available) == 1


def test_ready_reports_rank_order_even_as_rows_arrive():
    """The queue never holds a reshuffle back — the panel does that, and only
    while the pointer is over the table. Here the truth is always rank order.
    """
    q = queue()
    q.submit([cand(char="Poor", pay=11.5)], T0)
    q.submit([cand(char="Rich", pay=8.0)], T0 + timedelta(seconds=62))
    rows = q.available
    assert [t.candidate.listing.character for t in rows] == ["Rich", "Poor"]
    assert q.next_up is rows[0]


# --- the two windows are independent ---------------------------------------

def test_a_ready_row_outlives_nothing_but_its_own_ttl():
    q = TradeQueue(available_ttl_s=60.0)
    q.submit([cand()], T0)
    assert q.available
    assert q.tick(T0 + timedelta(seconds=30)).expired == []
    tick = q.tick(T0 + timedelta(seconds=61))
    assert len(tick.expired) == 1
    assert q.available == []


# --- auto expiry -----------------------------------------------------------

def test_an_unanswered_whisper_expires():
    """Leaving it pending forever biases the log toward whatever got clicked.

    The verdict is EXPIRED, not NO_REPLY: all the timer knows is that its
    deadline passed. Measured 2026-08-01, it wrote `no_reply` three and a half
    minutes *after* a trade completed.
    """
    q = TradeQueue(available_ttl_s=60.0, awaiting_timeout_s=300.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_next(T0 + timedelta(seconds=5))
    assert q.awaiting == [taken]

    tick = q.tick(T0 + timedelta(seconds=5 + 301))
    assert tick.auto_resolved == [taken]
    assert taken.outcome is Outcome.EXPIRED
    assert taken.state is QueueState.RESOLVED
    assert q.awaiting == []


def test_answering_before_the_timeout_wins():
    q = TradeQueue(available_ttl_s=60.0, awaiting_timeout_s=300.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_next(T0)
    q.resolve(taken.id, Outcome.FILLED, T0 + timedelta(seconds=30))
    tick = q.tick(T0 + timedelta(seconds=400))
    assert tick.auto_resolved == []
    assert taken.outcome is Outcome.FILLED


def test_awaiting_shows_how_long_is_left_before_it_self_marks():
    q = TradeQueue(available_ttl_s=60.0, awaiting_timeout_s=300.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_next(T0)
    assert taken.seconds_left(T0 + timedelta(seconds=60)) == pytest.approx(240.0)


def test_a_zero_timeout_means_never_auto_resolve():
    """An escape hatch for anyone who would rather answer every one by hand."""
    q = TradeQueue(available_ttl_s=60.0, awaiting_timeout_s=0.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_next(T0)
    assert taken.expires_at is None
    assert q.tick(T0 + timedelta(days=1)).auto_resolved == []
    assert q.awaiting == [taken]


def test_the_shipped_windows_are_ordered_sensibly():
    """listed < auto-resolve, or the two clocks step on each other.

    If a whisper self-marked sooner than a row stayed listed, trades would be
    written off faster than they could be taken.
    """
    from poe2arb.config import Config

    cfg = Config()
    assert cfg.available_ttl_s < cfg.awaiting_timeout_s


# --- declining is remembered for the session -------------------------------

def test_a_declined_trade_is_not_re_offered_by_a_later_sweep():
    """A sweep every ten minutes re-finds the same listing.

    Being shown a trade you already said no to costs the same attention as a
    new one and carries none of the information.
    """
    q = queue()
    c = cand(char="Nope")
    q.submit([c], T0)
    assert q.decline(q.next_up.id) is True

    assert q.submit([c], T0 + timedelta(minutes=10)) == 0
    assert q.available == []


def test_a_drop_the_app_made_itself_is_not_a_decline():
    """Dropping a listing with no whisper template is a fact about the fetch.

    It is not a judgement the user made, so it must not suppress the listing
    if a later sweep returns it complete.
    """
    q = queue()
    c = cand(char="Silent")
    q.submit([c], T0)
    offered = q.next_up
    assert q.drop(offered.id) is True
    assert q.declined == frozenset()
    assert q.submit([c], T0 + timedelta(minutes=10)) == 1


# --- outstanding whispers do not hold the bankroll ------------------------

def test_an_outstanding_whisper_does_not_hold_back_the_next_trade():
    """The 0.6.0 holdback, reverted 2026-07-31 on the maintainer's call.

    Treating a copied whisper as money spent until the user said otherwise was
    accurate only if whispers usually fill. They do not: 79% go unanswered, so
    the guard mostly withheld trades from a bankroll that was never touched.
    """
    q = queue()
    q.submit([cand(char="A", pay=11.0), cand(char="B", pay=11.5)], T0)
    first = q.next_up
    q.take(first.id, T0)
    second = q.next_up
    assert second is not None
    assert second.candidate.listing.character == "B"


def test_outstanding_counts_everything_still_in_flight():
    """What decides whether a session is over — see session.py."""
    q = queue()
    assert q.outstanding == 0
    q.submit([cand(char="A", pay=11.0)], T0)
    ready = q.next_up
    assert q.outstanding == 1              # ready to whisper
    q.take(ready.id, T0)
    assert q.outstanding == 1              # awaiting a reply
    q.resolve(ready.id, Outcome.NO_REPLY)
    assert q.outstanding == 0


def test_revise_corrects_the_quantity_without_losing_the_trades_identity():
    """Whispered for 18, the seller had 3 — see listings.replan_units."""
    q = queue()
    q.submit([cand(char="A", pay=11.0, stock=18.0)], T0)
    trade = q.next_up
    q.take(trade.id, T0)
    before = trade.key
    revised = q.revise(trade.id, 3.0)
    assert revised is not None
    assert revised.candidate.plan.units == 3.0
    assert revised.key == before
    # Nothing to change is reported as nothing changed.
    assert q.revise(trade.id, 3.0) is None


def test_revise_records_a_counteroffered_price():
    """1 fill in 36 was negotiated, and it logged a profit it did not earn."""
    q = queue()
    q.submit([cand(char="A", pay=11.0, stock=18.0)], T0)
    trade = q.next_up
    q.take(trade.id, T0)
    before = trade.key

    revised = q.revise(trade.id, 18.0, 250.0)
    assert revised is not None
    assert revised.candidate.plan.units == 18.0        # quantity untouched
    assert revised.candidate.pay_total == 250.0
    assert revised.key == before
    assert q.revise(trade.id, 18.0, 250.0) is None


def test_revise_applies_the_quantity_before_the_price():
    """Shrinking re-prices at the listed rate; a price given overrides that."""
    q = queue()
    q.submit([cand(char="A", pay=11.0, stock=18.0)], T0)
    trade = q.next_up
    q.take(trade.id, T0)
    revised = q.revise(trade.id, 3.0, 40.0)
    assert revised.candidate.plan.units == 3.0
    assert revised.candidate.pay_total == 40.0         # not the listed 33


# --- pinning ---------------------------------------------------------------
# Requested 2026-08-01. The log had already produced the case twice that
# evening: both false expiries were sellers who had *answered*, one of them
# mid-trade when the timer fired. A seller who has spoken is not on a clock.


def test_a_pinned_row_does_not_expire():
    q = TradeQueue(available_ttl_s=60.0, awaiting_timeout_s=300.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_next(T0)
    assert q.pin(taken.id) is taken

    tick = q.tick(T0 + timedelta(hours=2))
    assert tick.auto_resolved == []
    assert taken.state is QueueState.AWAITING
    assert q.awaiting == [taken]


def test_a_pinned_row_shows_no_countdown():
    """The Expires cell has to say "held", not a number that never moves."""
    q = TradeQueue(available_ttl_s=60.0, awaiting_timeout_s=300.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_next(T0)
    assert taken.seconds_left(T0 + timedelta(seconds=60)) == pytest.approx(240.0)
    q.pin(taken.id)
    assert taken.seconds_left(T0 + timedelta(seconds=60)) is None


def test_unpinning_restarts_nothing():
    """A row released past its deadline resolves on the next tick.

    Deliberate: the deadline was real, the pin only held it. Restarting the
    clock would let a row be kept alive indefinitely by pinning and unpinning.
    """
    q = TradeQueue(available_ttl_s=60.0, awaiting_timeout_s=300.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_next(T0)
    q.pin(taken.id)
    q.tick(T0 + timedelta(hours=1))
    q.pin(taken.id, False)
    assert q.tick(T0 + timedelta(hours=1, seconds=1)).auto_resolved == [taken]


def test_pinned_rows_sort_above_the_rest():
    q = TradeQueue(available_ttl_s=60.0, awaiting_timeout_s=300.0)
    q.submit([cand(char="A"), cand(char="B")], T0)
    q.tick(T0)
    first = q.take_next(T0)
    q.tick(T0 + timedelta(seconds=16))
    second = q.take_next(T0 + timedelta(seconds=16))
    assert [t.id for t in q.awaiting] == [second.id, first.id]  # newest first
    q.pin(first.id)
    assert [t.id for t in q.awaiting] == [first.id, second.id]


def test_only_a_whispered_row_can_be_pinned():
    q = queue()
    q.submit([cand()], T0)
    assert q.pin(q.next_up.id) is None


def test_resolving_releases_the_pin():
    q = queue(awaiting_timeout_s=300.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_next(T0)
    q.pin(taken.id)
    q.resolve(taken.id, Outcome.FILLED)
    assert not taken.pinned


# --- a settled listing is not offered again --------------------------------
# Measured 2026-08-01: the same stale listing went out five times across four
# sessions in 3½ hours, because a Bulk listing does not delist when the stock
# is gone. `forget_resolved` drops the row that would have deduplicated it, so
# the key has to be remembered separately.


@pytest.mark.parametrize(
    "outcome", [Outcome.FILLED, Outcome.SOLD, Outcome.OFFLINE, Outcome.DECLINED]
)
def test_a_settled_listing_is_never_re_offered(outcome):
    q = queue(awaiting_timeout_s=300.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_next(T0)
    q.resolve(taken.id, outcome)
    q.forget_resolved()
    assert q.submit([cand()], T0 + timedelta(minutes=20)) == 0


@pytest.mark.parametrize(
    "outcome", [Outcome.EXPIRED, Outcome.AFK, Outcome.UNAVAILABLE]
)
def test_a_silent_listing_can_be_tried_again(outcome):
    """An away seller comes back, and a deadline says nothing about the stock.

    `UNAVAILABLE` is here rather than in the set above, and it was a decision:
    the one button that writes it replaced AFK *and* Offline, which sat on
    opposite sides of `SETTLED_OUTCOMES`, so the merged verdict takes the
    weaker claim — which is the only honest reading of a press that says
    nothing about why.
    """
    q = queue(awaiting_timeout_s=300.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_next(T0)
    q.resolve(taken.id, outcome)
    q.forget_resolved()
    assert q.submit([cand()], T0 + timedelta(minutes=20)) == 1


def test_the_timer_settles_nothing_by_itself():
    """Auto-expiry must not suppress the listing — it is not a verdict on it."""
    q = TradeQueue(available_ttl_s=60.0, awaiting_timeout_s=300.0)
    q.submit([cand()], T0)
    q.tick(T0)
    q.take_next(T0)
    q.tick(T0 + timedelta(seconds=400))
    q.forget_resolved()
    assert q.settled == frozenset()
    assert q.submit([cand()], T0 + timedelta(minutes=20)) == 1


# --- corrections are measured from the ask ---------------------------------


def test_a_correction_can_be_walked_back_up_again():
    """Inline arrows have to work in both directions.

    `replan_units` only ever shrinks what it is given, so applying each
    correction to the last one would ratchet: one nudge too far down and the
    row could never be brought back. 0.8.0's dialog dodged this by being opened
    fresh each time; the editors in the row cannot.
    """
    q = queue()
    q.submit([cand(char="A", pay=11.0, stock=18.0)], T0)
    trade = q.take_next(T0)
    assert trade.asked.plan.units == 18.0

    assert q.revise(trade.id, 3.0).candidate.plan.units == 3.0
    assert q.revise(trade.id, 12.0).candidate.plan.units == 12.0
    assert q.revise(trade.id, 18.0).candidate.plan.units == 18.0
    # And never above what was actually asked for — the extra was never on offer.
    assert q.revise(trade.id, 40.0) is None


def test_the_ask_survives_a_correction_for_the_next_one():
    q = queue()
    q.submit([cand(char="A", pay=11.0, stock=18.0)], T0)
    trade = q.take_next(T0)
    q.revise(trade.id, 3.0, 40.0)
    # Re-priced against the ask, not against the 40 just recorded.
    assert q.revise(trade.id, 6.0).candidate.pay_total == pytest.approx(66.0)
