"""The offer queue: one at a time, with clocks that can be driven from a test."""

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
    return TradeQueue(offer_window_s=60.0, available_ttl_s=600.0, **kw)


# --- offering one at a time ------------------------------------------------

def test_one_trade_is_offered_at_a_time():
    """A second toast while the first is unread makes both of them noise."""
    q = queue()
    q.submit([cand(char="A"), cand(char="B"), cand(char="C")], T0)
    tick = q.tick(T0)
    assert tick.newly_offered is not None
    assert len(q.available) == 1
    assert len(q.pending) == 2

    # Ticking again changes nothing while the offer stands.
    assert q.tick(T0 + timedelta(seconds=5)).newly_offered is None
    assert len(q.available) == 1


def test_the_best_trade_is_offered_first():
    q = queue()
    q.submit([cand(char="Small", pay=11.5), cand(char="Big", pay=8.5)], T0)
    offered = q.tick(T0).newly_offered
    assert offered.candidate.listing.character == "Big"


def test_taking_the_offer_frees_the_slot_for_the_next():
    q = queue()
    q.submit([cand(char="A"), cand(char="B")], T0)
    first = q.tick(T0).newly_offered
    q.take_offered(T0 + timedelta(seconds=5))
    second = q.tick(T0 + timedelta(seconds=6)).newly_offered
    assert second is not None
    assert second.id != first.id


def test_ghosts_are_not_queued_by_default():
    """Interrupting a map for something measured never to fill is pure cost."""
    q = queue()
    assert q.submit([cand(pay=1.0)], T0) == 0  # 12x gap -> GHOST
    assert q.tick(T0).newly_offered is None


def test_ghosts_can_be_queued_if_asked_for():
    q = queue(queue_ghosts=True)
    assert q.submit([cand(pay=1.0)], T0) == 1


def test_a_candidate_with_no_whisper_template_is_never_queued():
    q = queue()
    assert q.submit([cand(whisper=False)], T0) == 0


# --- the offer window ------------------------------------------------------

def test_an_unclaimed_offer_lapses_into_available():
    q = queue()
    q.submit([cand()], T0)
    q.tick(T0)
    tick = q.tick(T0 + timedelta(seconds=61))
    assert len(tick.lapsed_to_available) == 1
    assert tick.lapsed_to_available[0].state is QueueState.AVAILABLE
    # Still takeable, just no longer interrupting.
    assert len(q.available) == 1


def test_lapsing_lets_the_next_trade_be_offered():
    q = queue()
    q.submit([cand(char="A"), cand(char="B")], T0)
    first = q.tick(T0).newly_offered
    tick = q.tick(T0 + timedelta(seconds=61))
    assert tick.newly_offered is not None
    assert tick.newly_offered.id != first.id
    assert len(q.available) == 2  # the lapsed one plus the new offer


def test_available_trades_expire_eventually():
    """Listings churn in tens of minutes; holding one longer wastes a whisper."""
    q = queue()
    q.submit([cand()], T0)
    q.tick(T0)
    q.tick(T0 + timedelta(seconds=61))
    tick = q.tick(T0 + timedelta(seconds=61 + 601))
    assert len(tick.expired) == 1
    assert q.available == []


def test_seconds_left_counts_down():
    q = queue()
    q.submit([cand()], T0)
    t = q.tick(T0).newly_offered
    assert t.seconds_left(T0) == pytest.approx(60.0)
    assert t.seconds_left(T0 + timedelta(seconds=45)) == pytest.approx(15.0)
    assert t.seconds_left(T0 + timedelta(seconds=90)) == 0.0


# --- taking and resolving --------------------------------------------------

def test_taking_moves_a_trade_to_awaiting():
    q = queue()
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_offered(T0 + timedelta(seconds=10))
    assert taken.state is QueueState.AWAITING
    assert taken.taken_at is not None
    assert q.awaiting == [taken]
    assert q.available == []


def test_a_lapsed_trade_can_still_be_taken_from_the_panel():
    q = queue()
    q.submit([cand()], T0)
    q.tick(T0)
    q.tick(T0 + timedelta(seconds=61))
    [available] = q.available
    assert q.take(available.id, T0 + timedelta(seconds=70)) is not None
    assert q.awaiting[0].id == available.id


def test_taking_when_nothing_is_armed_does_nothing():
    """The hotkey outside an offer window must be a no-op, not a crash."""
    q = queue()
    assert q.take_offered(T0) is None


def test_an_expired_trade_cannot_be_taken():
    q = queue()
    q.submit([cand()], T0)
    q.tick(T0)
    q.tick(T0 + timedelta(seconds=61))
    [t] = [x for x in q._trades]
    q.tick(T0 + timedelta(seconds=700))
    assert q.take(t.id, T0 + timedelta(seconds=701)) is None


def test_resolving_records_the_verdict():
    q = queue()
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_offered(T0)
    resolved = q.resolve(taken.id, Outcome.FILLED)
    assert resolved.state is QueueState.RESOLVED
    assert resolved.outcome is Outcome.FILLED
    assert q.awaiting == []


def test_only_awaiting_trades_can_be_resolved():
    q = queue()
    q.submit([cand()], T0)
    offered = q.tick(T0).newly_offered
    assert q.resolve(offered.id, Outcome.FILLED) is None


def test_awaiting_is_oldest_first():
    """Whatever went cold longest ago is the thing most in need of an answer."""
    q = queue()
    q.submit([cand(char="A"), cand(char="B")], T0)
    q.tick(T0)
    first = q.take_offered(T0 + timedelta(seconds=1))
    q.tick(T0 + timedelta(seconds=2))
    second = q.take_offered(T0 + timedelta(seconds=30))
    assert [t.id for t in q.awaiting] == [first.id, second.id]


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
    q.take_offered(T0)
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
    offered = q.tick(T0).newly_offered
    assert q.drop(offered.id) is True
    assert q.available == [] and q.awaiting == []


def test_a_whispered_trade_cannot_be_dropped():
    """It's already logged as an attempt; it needs a verdict, not a delete."""
    q = queue()
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_offered(T0)
    assert q.drop(taken.id) is False


def test_cancel_pending_stops_new_offers_but_keeps_live_work():
    """Stopping the sweep must stop the backlog, not retract work in progress.

    Reported from the field 2026-07-30: offers kept arriving for minutes after
    *Find trades* was switched off, because `tick` promotes the backlog whether
    or not anything is still sweeping.
    """
    q = queue()
    q.submit([cand(char=c) for c in ("A", "B", "C", "D")], T0)
    q.tick(T0)                      # A is offered
    taken = q.take_offered(T0)      # ...and whispered
    q.tick(T0 + timedelta(seconds=1))   # B takes the free slot
    assert len(q.pending) == 2      # C and D still waiting

    assert q.cancel_pending() == 2
    assert q.pending == []
    # The whispered one still needs its verdict; the offered one is still takeable.
    assert [t.id for t in q.awaiting] == [taken.id]
    assert len(q.available) == 1

    # And no amount of ticking conjures another offer.
    for i in range(2, 12):
        assert q.tick(T0 + timedelta(minutes=i)).newly_offered is None


def test_cancel_pending_lets_a_later_sweep_refind_the_listing():
    """Cancelled-but-never-offered isn't a verdict, so it must not blacklist."""
    q = queue()
    q.submit([cand(char="A")], T0)
    assert q.cancel_pending() == 1
    assert q.submit([cand(char="A")], T0 + timedelta(minutes=10)) == 1


def test_forget_resolved_keeps_live_work():
    q = queue()
    q.submit([cand(char="A"), cand(char="B")], T0)
    q.tick(T0)
    taken = q.take_offered(T0)
    q.resolve(taken.id, Outcome.NO_REPLY)
    q.tick(T0 + timedelta(seconds=1))
    assert q.forget_resolved() == 1
    assert len(q.available) == 1


def test_the_live_offer_is_listed_first_even_when_worth_less():
    """It's what the hotkey acts on; burying it would misrepresent the key."""
    q = queue()
    q.submit([cand(char="Rich", pay=8.0)], T0)
    q.tick(T0)
    q.tick(T0 + timedelta(seconds=61))        # Rich lapses to available
    q.submit([cand(char="Poor", pay=11.5)], T0 + timedelta(seconds=62))
    q.tick(T0 + timedelta(seconds=62))        # Poor becomes the live offer
    rows = q.available
    assert rows[0].state is QueueState.OFFERED
    assert rows[0].candidate.listing.character == "Poor"
    assert rows[1].candidate.profit_divines > rows[0].candidate.profit_divines


# --- the three windows are independent -------------------------------------

def test_the_hotkey_window_is_shorter_than_the_available_window():
    """It gates queue throughput, not how long the user has to decide."""
    q = TradeQueue(offer_window_s=15.0, available_ttl_s=60.0)
    q.submit([cand(char="A"), cand(char="B")], T0)
    q.tick(T0)

    # 15s: the offer lapses and the next one is presented immediately.
    tick = q.tick(T0 + timedelta(seconds=16))
    assert len(tick.lapsed_to_available) == 1
    assert tick.newly_offered is not None

    # The lapsed one is still takeable well past the hotkey window.
    lapsed = tick.lapsed_to_available[0]
    assert q.take(lapsed.id, T0 + timedelta(seconds=50)) is not None


def test_a_lapsed_offer_expires_after_the_available_window():
    q = TradeQueue(offer_window_s=15.0, available_ttl_s=60.0)
    q.submit([cand()], T0)
    q.tick(T0)
    q.tick(T0 + timedelta(seconds=16))          # -> AVAILABLE
    assert q.available
    tick = q.tick(T0 + timedelta(seconds=16 + 61))
    assert len(tick.expired) == 1
    assert q.available == []


# --- auto no-reply ---------------------------------------------------------

def test_an_unanswered_whisper_becomes_no_reply():
    """Silence is the common case; leaving it pending forever biases the log."""
    q = TradeQueue(offer_window_s=15.0, available_ttl_s=60.0, awaiting_timeout_s=300.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_offered(T0 + timedelta(seconds=5))
    assert q.awaiting == [taken]

    tick = q.tick(T0 + timedelta(seconds=5 + 301))
    assert tick.auto_resolved == [taken]
    assert taken.outcome is Outcome.NO_REPLY
    assert taken.state is QueueState.RESOLVED
    assert q.awaiting == []


def test_answering_before_the_timeout_wins():
    q = TradeQueue(offer_window_s=15.0, available_ttl_s=60.0, awaiting_timeout_s=300.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_offered(T0)
    q.resolve(taken.id, Outcome.FILLED, T0 + timedelta(seconds=30))
    tick = q.tick(T0 + timedelta(seconds=400))
    assert tick.auto_resolved == []
    assert taken.outcome is Outcome.FILLED


def test_awaiting_shows_how_long_is_left_before_it_self_marks():
    q = TradeQueue(offer_window_s=15.0, available_ttl_s=60.0, awaiting_timeout_s=300.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_offered(T0)
    assert taken.seconds_left(T0 + timedelta(seconds=60)) == pytest.approx(240.0)


def test_a_zero_timeout_means_never_auto_resolve():
    """An escape hatch for anyone who would rather answer every one by hand."""
    q = TradeQueue(offer_window_s=15.0, available_ttl_s=60.0, awaiting_timeout_s=0.0)
    q.submit([cand()], T0)
    q.tick(T0)
    taken = q.take_offered(T0)
    assert taken.expires_at is None
    assert q.tick(T0 + timedelta(days=1)).auto_resolved == []
    assert q.awaiting == [taken]


def test_the_shipped_windows_are_ordered_sensibly():
    """alert < listed < auto-resolve, or the states step on each other.

    If the alert outlived the listed window an offer would expire before it
    ever lapsed; if auto-resolve fired sooner than the listed window, whispers
    would self-mark faster than trades could be taken.
    """
    from poe2arb.config import Config

    cfg = Config()
    assert cfg.offer_window_s < cfg.available_ttl_s < cfg.awaiting_timeout_s
