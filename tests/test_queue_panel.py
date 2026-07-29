"""The Opportunities tab: two sections, live offer, verdicts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QPushButton,
    QWidget,
)

from poe2arb.gui.queue_panel import TRADE_ID, QueuePanel  # noqa: E402
from poe2arb.listings import Listing, build_candidates  # noqa: E402
from poe2arb.outcomes import Outcome  # noqa: E402
from poe2arb.trade_queue import QueueState, TradeQueue  # noqa: E402

T0 = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def cand(*, char="Seller", pay=11.0, item="omen"):
    listing = Listing(
        item_id=item, account=f"{char}#1", character=char,
        pay_amount=pay, get_amount=1.0, stock=1.0, indexed=T0,
        whisper=f"@{char} buy {{0}} for {{1}}",
        item_whisper="{0} Thing", pay_whisper="{0} Coin",
    )
    [c] = build_candidates(
        [listing], {item: 12.0, "divine": 1.0}, {item: "Omen of Light"},
        min_gap=1.05, max_gap=1.5, sale_unit_divines=0.0023,
    )
    return c


def loaded(qapp, *candidates, tick_at=T0):
    # The shipped windows: 15s live, 60s listed, 5min before self-marking.
    q = TradeQueue(offer_window_s=15.0, available_ttl_s=60.0, awaiting_timeout_s=300.0)
    q.submit(list(candidates), T0)
    q.tick(tick_at)
    p = QueuePanel()
    p.refresh(q, tick_at)
    qapp.processEvents()
    return p, q


# --- the two sections ------------------------------------------------------

def test_a_live_offer_appears_in_ready_with_a_marker(qapp):
    p, q = loaded(qapp, cand())
    assert p.ready.rowCount() == 1
    assert p.awaiting.rowCount() == 0
    assert p.ready.item(0, 0).text() == "●"


def test_the_headline_names_the_live_offer_and_its_countdown(qapp):
    p, q = loaded(qapp, cand())
    text = p.headline.text()
    assert "Omen of Light" in text
    assert "+" in text and "div" in text
    assert "15s" in text


def test_taking_moves_a_trade_between_the_sections(qapp):
    p, q = loaded(qapp, cand())
    q.take_offered(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    assert p.ready.rowCount() == 0
    assert p.awaiting.rowCount() == 1


def test_a_lapsed_offer_stays_ready_without_the_marker(qapp):
    """Still takeable — it just isn't worth interrupting a map for any more."""
    p, q = loaded(qapp, cand())
    later = T0 + timedelta(seconds=16)
    q.tick(later)
    p.refresh(q, later)
    qapp.processEvents()
    assert p.ready.rowCount() == 1
    assert p.ready.item(0, 0).text() == ""


def test_an_expired_trade_leaves_the_panel(qapp):
    p, q = loaded(qapp, cand())
    q.tick(T0 + timedelta(seconds=16))
    late = T0 + timedelta(seconds=90)
    q.tick(late)
    p.refresh(q, late)
    qapp.processEvents()
    assert p.ready.rowCount() == 0


def test_an_empty_queue_says_what_to_do(qapp):
    p = QueuePanel()
    p.refresh(None)
    qapp.processEvents()
    assert "find trades" in p.hint.text().lower()


# --- one-click actions -----------------------------------------------------

def test_accept_takes_the_trade_in_a_single_click(qapp):
    """No select-then-press: this is used mid-map."""
    seen = []
    p, q = loaded(qapp, cand())
    p.take_requested.connect(seen.append)
    assert p.click_action(p.ready, 0, "Accept")
    assert seen == [q.offered.id]


def test_decline_drops_the_trade_in_a_single_click(qapp):
    seen = []
    p, q = loaded(qapp, cand())
    p.dismiss_requested.connect(seen.append)
    assert p.click_action(p.ready, 0, "Decline")
    assert seen == [q.offered.id]


@pytest.mark.parametrize(
    "label,outcome",
    [("Traded", Outcome.FILLED), ("No reply", Outcome.NO_REPLY),
     ("Already sold", Outcome.SOLD)],
)
def test_each_verdict_is_a_single_click(qapp, label, outcome):
    seen = []
    p, q = loaded(qapp, cand())
    p.outcome_reported.connect(lambda i, o: seen.append((i, o)))
    taken = q.take_offered(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    assert p.click_action(p.awaiting, 0, label)
    assert seen == [(taken.id, outcome)]


def test_only_the_three_verdicts_asked_for_are_offered(qapp):
    p, q = loaded(qapp, cand())
    q.take_offered(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    assert not p.click_action(p.awaiting, 0, "Refused")
    for label in ("Traded", "No reply", "Already sold"):
        assert p.click_action(p.awaiting, 0, label)


def test_buttons_act_on_their_own_row(qapp):
    """With no selection, the row must be identified by the button itself."""
    seen = []
    p, q = loaded(qapp, cand(char="A", pay=8.0), cand(char="B", pay=11.5))
    q.tick(T0 + timedelta(seconds=16))     # both listed
    p.refresh(q, T0 + timedelta(seconds=16))
    qapp.processEvents()
    p.take_requested.connect(seen.append)
    second_id = p.row_id(p.ready, 1)
    p.click_action(p.ready, 1, "Accept")
    assert seen == [second_id]


def test_the_tables_have_no_selection_to_get_lost(qapp):
    from PySide6.QtWidgets import QAbstractItemView

    p, q = loaded(qapp, cand())
    assert p.ready.selectionMode() is QAbstractItemView.SelectionMode.NoSelection
    assert p.awaiting.selectionMode() is QAbstractItemView.SelectionMode.NoSelection


# --- refresh must not destroy a button mid-click ---------------------------

def test_a_countdown_tick_does_not_rebuild_the_row(qapp):
    """The tables redraw every second; rebuilding would kill the button under
    the cursor between press and release."""
    p, q = loaded(qapp, cand())
    widget = p.ready.cellWidget(0, 7)
    p.refresh(q, T0 + timedelta(seconds=5))
    qapp.processEvents()
    assert p.ready.cellWidget(0, 7) is widget          # same widget object
    assert p.ready.item(0, 6).text() != "15s"          # but the timer moved


def test_a_changed_row_set_does_rebuild(qapp):
    p, q = loaded(qapp, cand(char="A"))
    first = p.ready.cellWidget(0, 7)
    q.submit([cand(char="B")], T0)
    q.tick(T0 + timedelta(seconds=16))
    p.refresh(q, T0 + timedelta(seconds=16))
    qapp.processEvents()
    assert p.ready.rowCount() == 2
    assert p.ready.cellWidget(0, 7) is not first


def test_awaiting_shows_its_auto_no_reply_countdown(qapp):
    p, q = loaded(qapp, cand())
    q.take_offered(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    assert p.awaiting.item(0, 6).text() == "5m"
    p.refresh(q, T0 + timedelta(seconds=270))
    qapp.processEvents()
    assert p.awaiting.item(0, 6).text() == "30s"


def test_an_auto_resolved_trade_leaves_the_lower_section(qapp):
    p, q = loaded(qapp, cand())
    q.take_offered(T0)
    late = T0 + timedelta(seconds=301)
    tick = q.tick(late)
    assert len(tick.auto_resolved) == 1
    p.refresh(q, late)
    qapp.processEvents()
    assert p.awaiting.rowCount() == 0


def test_a_rebuild_leaves_no_stray_action_widgets(qapp):
    """A survivor stays at its old geometry and paints over another row."""
    p, q = loaded(qapp, cand(char="A", pay=9.0))
    q.submit([cand(char="B", pay=8.3)], T0)
    later = T0 + timedelta(seconds=16)
    q.tick(later)
    p.refresh(q, later)
    qapp.processEvents()

    holders = [w for w in p.ready.findChildren(QWidget)
               if w.findChildren(QPushButton) and w.parent() is p.ready.viewport()]
    assert len(holders) == p.ready.rowCount()


def test_shrinking_the_list_removes_its_widgets(qapp):
    p, q = loaded(qapp, cand(char="A"))
    q.take_offered(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    holders = [w for w in p.ready.findChildren(QWidget)
               if w.findChildren(QPushButton) and w.parent() is p.ready.viewport()]
    assert holders == []
