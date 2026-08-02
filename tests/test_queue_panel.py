"""The Opportunities tab: two sections, in-row edits, verdicts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QPushButton,
    QWidget,
)

from poe2arb.gui.queue_panel import (  # noqa: E402
    AWAITING_ACTION_COLUMN,
    AWAITING_TIMER_COLUMN,
    READY_ACTION_COLUMN,
    READY_TIMER_COLUMN,
    TRADE_ID,
    QueuePanel,
)
from poe2arb.listings import Listing, build_candidates  # noqa: E402
from poe2arb.outcomes import Outcome  # noqa: E402
from poe2arb.trade_queue import QueueState, TradeQueue  # noqa: E402

T0 = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def cand(*, char="Seller", pay=11.0, item="omen", stock=1.0, get=1.0):
    listing = Listing(
        item_id=item, account=f"{char}#1", character=char,
        pay_amount=pay, get_amount=get, stock=stock, indexed=T0,
        whisper=f"@{char} buy {{0}} for {{1}}",
        item_whisper="{0} Thing", pay_whisper="{0} Coin",
    )
    [c] = build_candidates(
        [listing], {item: 12.0, "divine": 1.0}, {item: "Omen of Light"},
        min_gap=1.05, max_gap=1.5, sale_unit_divines=0.0023,
    )
    return c


def loaded(qapp, *candidates, tick_at=T0):
    # The shipped windows: 60s listed, 5min before a whisper self-marks.
    q = TradeQueue(available_ttl_s=60.0, awaiting_timeout_s=300.0)
    q.submit(list(candidates), T0)
    q.tick(tick_at)
    p = QueuePanel()
    p.refresh(q, tick_at)
    qapp.processEvents()
    return p, q


# --- the two sections ------------------------------------------------------

def test_a_found_trade_appears_in_ready_with_a_marker(qapp):
    p, q = loaded(qapp, cand())
    assert p.ready.rowCount() == 1
    assert p.awaiting.rowCount() == 0
    assert p.ready.item(0, 0).text() == "●"


def test_the_headline_counts_both_sections(qapp):
    """It named the live offer until 0.9.0. There is no live offer any more —
    the table itself says which trade is next, in the row order the hotkey
    uses — so the headline went back to being a count.
    """
    p, q = loaded(qapp, cand())
    assert p.headline.text() == "1 trade ready"
    q.take_next(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    assert p.headline.text() == "1 waiting on a reply"


def test_taking_moves_a_trade_between_the_sections(qapp):
    p, q = loaded(qapp, cand())
    q.take_next(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    assert p.ready.rowCount() == 0
    assert p.awaiting.rowCount() == 1


def test_the_marker_follows_the_hotkey_not_the_top_row(qapp):
    """● is a position, not a state, since 0.9.0 — and the position it marks
    is whichever row `take_next` would take. Normally that is row 1; while the
    panel is holding a reshuffle under the cursor it need not be, and the
    marker has to stay truthful.
    """
    p, q = loaded(qapp, cand(char="Fair", pay=9.0))
    p.ready.set_hover_row(0)                       # pointer parked on the table
    q.submit([cand(char="Better", pay=8.0)], T0)
    p.refresh(q, T0)
    qapp.processEvents()
    assert [p.ready.item(r, 7).text() for r in range(2)] == ["Fair", "Better"]
    assert [p.ready.item(r, 0).text() for r in range(2)] == ["", "●"]

    p.ready.set_hover_row(-1)                      # pointer leaves; order snaps
    p.refresh(q, T0)
    qapp.processEvents()
    assert [p.ready.item(r, 7).text() for r in range(2)] == ["Better", "Fair"]
    assert [p.ready.item(r, 0).text() for r in range(2)] == ["●", ""]


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
    assert seen == [q.next_up.id]


def test_decline_drops_the_trade_in_a_single_click(qapp):
    seen = []
    p, q = loaded(qapp, cand())
    p.dismiss_requested.connect(seen.append)
    assert p.click_action(p.ready, 0, "Decline")
    assert seen == [q.next_up.id]


@pytest.mark.parametrize(
    "label,outcome",
    [("Traded", Outcome.FILLED), ("Not Available", Outcome.UNAVAILABLE),
     ("Already Sold", Outcome.SOLD)],
)
def test_each_verdict_is_a_single_click(qapp, label, outcome):
    seen = []
    p, q = loaded(qapp, cand())
    p.outcome_reported.connect(lambda i, o: seen.append((i, o)))
    taken = q.take_next(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    assert p.click_action(p.awaiting, 0, label)
    assert seen == [(taken.id, outcome)]


def test_only_the_verdicts_asked_for_are_offered(qapp):
    """Three, not five. AFK and Offline were used properly for one session and
    then rejected — at this queue's rate a three-way judgement costs more than
    the answer is worth, and `Client.txt` can tell them apart afterwards.
    """
    p, q = loaded(qapp, cand())
    q.take_next(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    for gone in ("Refused", "No Reply", "AFK", "Offline", "Adjust…"):
        assert not p.click_action(p.awaiting, 0, gone), gone
    for label in ("Traded", "Not Available", "Already Sold"):
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
    widget = p.ready.cellWidget(0, READY_ACTION_COLUMN)
    p.refresh(q, T0 + timedelta(seconds=5))
    qapp.processEvents()
    assert p.ready.cellWidget(0, READY_ACTION_COLUMN) is widget          # same widget object
    assert p.ready.item(0, READY_TIMER_COLUMN).text() != "1m"           # but the timer moved


def test_a_changed_row_set_does_rebuild(qapp):
    p, q = loaded(qapp, cand(char="A"))
    first = p.ready.cellWidget(0, READY_ACTION_COLUMN)
    q.submit([cand(char="B")], T0)
    q.tick(T0 + timedelta(seconds=16))
    p.refresh(q, T0 + timedelta(seconds=16))
    qapp.processEvents()
    assert p.ready.rowCount() == 2
    assert p.ready.cellWidget(0, READY_ACTION_COLUMN) is not first


def test_a_re_sized_row_redraws_even_though_its_id_did_not_change(qapp):
    """A bankroll change rewrites the money on a row without touching the row
    list, so identity alone would leave the old quantity on screen — and the
    stale quantity is exactly what the whisper would then ask for."""
    p, q = loaded(qapp, cand(stock=10.0))
    assert p.ready.item(0, 2).text() == "10"

    q.resize({"divine": 55.0})
    p.refresh(q, T0)
    qapp.processEvents()

    assert p.ready.rowCount() == 1
    assert p.ready.item(0, 2).text() == "5"
    assert p.ready.item(0, 4).text() == "55 div"


def test_awaiting_shows_its_auto_no_reply_countdown(qapp):
    p, q = loaded(qapp, cand())
    q.take_next(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    assert p.awaiting.item(0, AWAITING_TIMER_COLUMN).text() == "5m"
    p.refresh(q, T0 + timedelta(seconds=270))
    qapp.processEvents()
    assert p.awaiting.item(0, AWAITING_TIMER_COLUMN).text() == "30s"


def test_an_auto_resolved_trade_leaves_the_lower_section(qapp):
    p, q = loaded(qapp, cand())
    q.take_next(T0)
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
    q.take_next(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    holders = [w for w in p.ready.findChildren(QWidget)
               if w.findChildren(QPushButton) and w.parent() is p.ready.viewport()]
    assert holders == []


# --- money is shown in the currency the seller asked for --------------------

def ex_cand(*, char="Xiaolong", pay=2412.0, get=1.0, item="omen"):
    """An exalted-priced listing, which is the more common kind on this venue."""
    listing = Listing(
        item_id=item, account=f"{char}#1", character=char,
        pay_currency="exalted", pay_amount=pay, get_amount=get, stock=9.0,
        indexed=T0, whisper=f"@{char} buy {{0}} for {{1}}",
        item_whisper="{0} Thing", pay_whisper="{0} Coin",
    )
    [c] = build_candidates(
        [listing], {item: 6.9, "divine": 1.0, "exalted": 0.00231},
        {item: "Omen of Whittling"},
        min_gap=1.05, max_gap=1.5, sale_unit_divines=0.00231,
        settle_currency="exalted",
    )
    return c


class TestCostColumns:
    """A listing whispered as "2412 exalted" showed on screen as "5.6 div".

    Unrecognisable as the offer that was made — which is exactly the problem
    when a reply lands an hour later in a language you don't read.
    """

    def test_ready_shows_the_total_in_the_sellers_currency(self, qapp):
        p, q = loaded(qapp, ex_cand())
        assert p.ready.item(0, 4).text() == "21,708 ex"

    def test_ready_shows_the_per_unit_price_alongside_it(self, qapp):
        p, q = loaded(qapp, ex_cand())
        assert p.ready.item(0, 3).text() == "2,412 ex"

    def test_ready_names_the_settlement_currency(self, qapp):
        """It sets the Profit figure, so a row has to say which one it used."""
        p, q = loaded(qapp, ex_cand())
        assert p.ready.item(0, 6).text() == "ex"

    def test_the_same_five_columns_appear_in_waiting(self, qapp):
        p, q = loaded(qapp, ex_cand())
        q.take_next(T0)
        p.refresh(q, T0)
        qapp.processEvents()
        assert p.awaiting.item(0, 2).text() == "2,412 ex"   # each
        assert p.awaiting.item(0, 3).text() == "21,708 ex"  # cost
        assert p.awaiting.item(0, 5).text() == "ex"         # settle

    def test_the_row_is_the_only_place_the_price_appears(self, qapp):
        """The headline quoted it while it named a live offer. It counts rows
        now, so the seller's currency has to be right in the table."""
        p, q = loaded(qapp, ex_cand())
        assert "21,708 ex" == p.ready.item(0, 4).text()


# --- the row lights up, but not under a button -----------------------------

def _enter(widget):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QEnterEvent

    pos = QPoint(2, 2)
    QApplication.sendEvent(
        widget, QEnterEvent(pos, pos, widget.mapToGlobal(pos))
    )


class TestRowHover:
    """Pointing at a button highlights the button; pointing at the row lights it.

    Reported from the field 2026-07-31: reaching for Accept lit the whole row,
    which is noise around the control you are already aiming at. The row tint
    exists to say *which trade* a click acts on, and the cursor sitting on the
    button has answered that already.
    """

    def _button(self, panel, table, row, label):
        column = (
            READY_ACTION_COLUMN if table is panel.ready else AWAITING_ACTION_COLUMN
        )
        widget = table.cellWidget(row, column)
        return next(
            b for b in widget.findChildren(QPushButton)
            if b.property("action") == label
        )

    def test_hovering_accept_leaves_the_row_alone(self, qapp):
        p, q = loaded(qapp, cand(char="A"), cand(char="B"))
        q.tick(T0 + timedelta(seconds=16))
        p.refresh(q, T0 + timedelta(seconds=16))
        qapp.processEvents()
        assert p.ready.rowCount() == 2
        p.ready.set_hover_row(1)
        _enter(self._button(p, p.ready, 1, "Accept"))
        assert p.ready.hover_row == -1

    def test_the_waiting_verdict_buttons_do_the_same(self, qapp):
        p, q = loaded(qapp, cand())
        q.take_next(T0)
        p.refresh(q, T0)
        qapp.processEvents()
        for label in ("Traded", "Not Available", "Already Sold"):
            p.awaiting.set_hover_row(0)
            _enter(self._button(p, p.awaiting, 0, label))
            assert p.awaiting.hover_row == -1, label

    def test_the_rest_of_the_row_still_lights_up(self, qapp):
        """Including the gaps between the buttons, which are row, not control."""
        p, q = loaded(qapp, cand())
        holder = p.ready.cellWidget(0, READY_ACTION_COLUMN)
        p.ready.set_hover_row(-1)
        _enter(holder)
        assert p.ready.hover_row == 0


# --- repeating a whisper ----------------------------------------------------

def test_copy_again_asks_for_the_same_trade(qapp):
    """A seller who answers wants the offer repeated; retyping it loses trades."""
    p, q = loaded(qapp, cand())
    taken = q.take_next(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    seen = []
    p.recopy_requested.connect(seen.append)
    assert p.click_action(p.awaiting, 0, "Copy Again")
    assert seen == [taken.id]


# --- the two sections can be resized against each other ---------------------

def test_the_two_sections_share_a_draggable_splitter(qapp):
    """How to divide them depends on which half of the loop you're in."""
    p, _ = loaded(qapp, cand())
    assert p.split.count() == 2
    assert not p.split.childrenCollapsible()


# --- pinning a row off the clock --------------------------------------------

def test_pin_is_one_click_on_the_row(qapp):
    seen = []
    p, q = loaded(qapp, cand())
    taken = q.take_next(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    p.pin_requested.connect(lambda i, on: seen.append((i, on)))
    assert p.click_action(p.awaiting, 0, "Pin")
    assert seen == [(taken.id, True)]


def test_a_pinned_row_offers_unpin_and_stops_counting_down(qapp):
    p, q = loaded(qapp, cand())
    taken = q.take_next(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    assert p.awaiting.item(0, AWAITING_TIMER_COLUMN).text() == "5m"

    q.pin(taken.id)
    p.refresh(q, T0 + timedelta(seconds=290))
    qapp.processEvents()
    assert p.awaiting.item(0, AWAITING_TIMER_COLUMN).text() == "held"
    assert not p.click_action(p.awaiting, 0, "Pin")

    seen = []
    p.pin_requested.connect(lambda i, on: seen.append((i, on)))
    assert p.click_action(p.awaiting, 0, "Unpin")
    assert seen == [(taken.id, False)]


def test_pinning_redraws_the_row(qapp):
    """Pin state changes the button and the cell, so identity alone is not enough."""
    p, q = loaded(qapp, cand())
    taken = q.take_next(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    before = p.awaiting.cellWidget(0, AWAITING_ACTION_COLUMN)
    q.pin(taken.id)
    p.refresh(q, T0)
    qapp.processEvents()
    assert p.awaiting.cellWidget(0, AWAITING_ACTION_COLUMN) is not before


# --- correcting a trade in the row it is shown in ---------------------------
# 0.8.0 did this in an *Adjust…* dialog. Replaced 2026-08-02 after the
# maintainer used it: at this queue's rate, two clicks and a context switch to
# change one number is too much. The obstacle the dialog dodged — a table that
# rebuilds every second for the countdowns — is solved here instead.


def edited(qapp, **kw):
    """A whispered row with its three editors on screen."""
    p, q = loaded(qapp, cand(**kw))
    taken = q.take_next(T0)
    p.refresh(q, T0)
    qapp.processEvents()
    return p, q, taken, p._editors[taken.id]


def test_the_three_money_cells_are_editable_in_place(qapp):
    from PySide6.QtWidgets import QDoubleSpinBox

    from poe2arb.gui.queue_panel import (
        AWAITING_PER_COLUMN, AWAITING_TOTAL_COLUMN, AWAITING_UNITS_COLUMN,
    )

    p, q, taken, _ = edited(qapp, pay=11.0, stock=18.0)
    for column in (AWAITING_UNITS_COLUMN, AWAITING_PER_COLUMN, AWAITING_TOTAL_COLUMN):
        assert isinstance(p.awaiting.cellWidget(0, column), QDoubleSpinBox)
    # And only there: a Ready row is an ask, not a record of what happened.
    assert p.ready.cellWidget(0, AWAITING_UNITS_COLUMN) is None


def test_a_quantity_correction_re_prices_at_the_listed_rate(qapp):
    """"They only had three" does not change what three cost each."""
    p, q, taken, e = edited(qapp, pay=11.0, stock=18.0)
    seen = []
    p.revise_requested.connect(lambda *a: seen.append(a))
    e.units.setValue(3.0)
    e._send_now()
    assert e.total.value() == 33.0
    assert e.per.value() == 11.0
    assert seen[-1] == (taken.id, 3.0, 33.0)


def test_a_counteroffered_total_moves_the_price_per(qapp):
    """1 fill in 36 was negotiated, and it logged +38.00 on a losing trade."""
    p, q, taken, e = edited(qapp, pay=11.0, stock=18.0)
    seen = []
    p.revise_requested.connect(lambda *a: seen.append(a))
    e.total.setValue(216.0)
    e._send_now()
    assert e.per.value() == 12.0
    assert e.units.value() == 18.0
    assert seen[-1] == (taken.id, 18.0, 216.0)


def test_a_price_per_correction_moves_the_total(qapp):
    p, q, taken, e = edited(qapp, pay=11.0, stock=18.0)
    seen = []
    p.revise_requested.connect(lambda *a: seen.append(a))
    e.per.setValue(12.0)
    e._send_now()
    assert e.total.value() == 216.0
    assert seen[-1] == (taken.id, 18.0, 216.0)


def test_the_quantity_cannot_exceed_what_was_asked_for(qapp):
    """The extra was never on offer — the ask was capped by the seller's stock."""
    p, q, taken, e = edited(qapp, pay=11.0, stock=18.0)
    assert e.units.maximum() == 18.0
    assert e.units.value() == 18.0


def test_the_quantity_steps_in_whole_lots(qapp):
    """Part of a lot would cost part of an orb, which cannot be traded."""
    p, q, taken, e = edited(qapp, pay=32.0, stock=18.0, get=3.0)
    assert e.units.singleStep() == 3.0
    assert e.units.minimum() == 3.0


def test_the_price_per_steps_by_one_whole_unit_of_the_total(qapp):
    """Partial currency cannot be traded, so that is the finest real change."""
    p, q, taken, e = edited(qapp, pay=11.0, stock=18.0)
    assert e.per.singleStep() == pytest.approx(1 / 18)
    assert e.total.singleStep() == 1.0


def test_an_open_editor_survives_the_once_a_second_redraw(qapp):
    """The rebuild that would destroy it is held until the edit is finished."""
    p, q, taken, e = edited(qapp, pay=11.0, stock=18.0)
    e.units.setValue(15.0)          # arrows clicked; the commit is pending
    assert p._editing()
    q.submit([cand(char="Other", pay=9.0)], T0)
    q.take(q.next_up.id, T0)
    p.refresh(q, T0 + timedelta(seconds=1))
    qapp.processEvents()
    assert p.awaiting.rowCount() == 1               # the arrival waited
    assert p._editors[taken.id] is e                # and the editor is untouched

    e._send_now()                   # the edit lands, and the queue catches up
    p.refresh(q, T0 + timedelta(seconds=2))
    qapp.processEvents()
    assert p.awaiting.rowCount() == 2


def test_a_correction_made_elsewhere_is_written_into_the_row(qapp):
    """The Trades tab and the timer both change rows this panel is showing."""
    p, q, taken, e = edited(qapp, pay=11.0, stock=18.0)
    q.revise(taken.id, 3.0)
    p.refresh(q, T0 + timedelta(seconds=1))
    qapp.processEvents()
    assert e.units.value() == 3.0
    assert p.awaiting.item(0, 1).text() == "3"
    assert p.awaiting.item(0, 3).text() == "33 div"


def test_writing_a_row_back_does_not_re_commit_it(qapp):
    """A redraw that fired `valueChanged` would log an amendment a second."""
    p, q, taken, e = edited(qapp, pay=11.0, stock=18.0)
    q.revise(taken.id, 3.0)
    seen = []
    p.revise_requested.connect(lambda *a: seen.append(a))
    for i in range(3):
        p.refresh(q, T0 + timedelta(seconds=i))
        qapp.processEvents()
    assert seen == []
