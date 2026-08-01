"""Whisper outcomes: recording, folding verdicts, and refusing to over-claim."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from poe2arb.listings import Band, Listing, build_candidates
from poe2arb.outcomes import (
    MIN_SAMPLES,
    Attempt,
    Outcome,
    label_for,
    leagues,
    read_attempts,
    record_amendment,
    record_attempt,
    record_outcome,
    sessions,
    suggested_gap_band,
    summarise,
)
from poe2arb.outcomes import plan_correction, record_correction
from poe2arb.listings import replan_units, repriced

NOW = datetime.now(timezone.utc)


@pytest.fixture
def log_path(tmp_path):
    return tmp_path / "outcomes.jsonl"


def candidate(*, item="omen", pay=11.0, ce=12.0, stock=1.0, char="Seller", afk=False, age_h=3.0):
    listing = Listing(
        item_id=item,
        account=f"{char}#1",
        character=char,
        pay_amount=pay,
        get_amount=1.0,
        stock=stock,
        indexed=NOW - timedelta(hours=age_h),
        afk=afk,
        whisper="@x buy {0} for {1}",
        item_whisper="{0} Thing",
        pay_whisper="{0} Coin",
    )
    [c] = build_candidates(
        [listing], {item: ce, "divine": 1.0}, {item: "Omen of Light"},
        min_gap=1.05, max_gap=1.5, sale_unit_divines=0.0023,
    )
    return c


def attempt(**kw) -> Attempt:
    base = dict(
        id="a", ts=NOW, item_id="omen", item_name="Omen", account="s#1", character="S",
        pay_currency="divine", unit_price_divines=11.0, ce_divines=12.0, gap=1.09,
        band="plausible", lots=1, units=1.0, cost_divines=11.0,
        expected_profit_divines=0.9, listing_age_s=3600.0, afk=False,
        outcome=Outcome.FILLED,
    )
    base.update(kw)
    return Attempt(**base)


# --- recording -------------------------------------------------------------

def test_copying_a_whisper_records_a_pending_attempt(log_path):
    """Logged on copy, not on success — otherwise the file says everything fills."""
    attempt_id = record_attempt(log_path, candidate())
    [got] = read_attempts(log_path)
    assert got.id == attempt_id
    assert got.outcome is Outcome.PENDING
    assert got.item_name == "Omen of Light"
    assert got.gap == pytest.approx(1.09, abs=0.01)
    assert got.expected_profit_divines > 0


def test_a_verdict_folds_onto_its_attempt(log_path):
    attempt_id = record_attempt(log_path, candidate())
    record_outcome(log_path, attempt_id, Outcome.FILLED, actual_profit_divines=1.75)
    [got] = read_attempts(log_path)
    assert got.outcome is Outcome.FILLED
    assert got.actual_profit_divines == 1.75
    assert got.resolved_at is not None


def test_the_last_verdict_wins(log_path):
    """Mis-clicks happen; correcting one shouldn't need the file edited."""
    attempt_id = record_attempt(log_path, candidate())
    record_outcome(log_path, attempt_id, Outcome.NO_REPLY)
    record_outcome(log_path, attempt_id, Outcome.FILLED)
    [got] = read_attempts(log_path)
    assert got.outcome is Outcome.FILLED


def test_features_that_might_predict_a_fill_are_all_captured(log_path):
    record_attempt(log_path, candidate(afk=True, age_h=30.0))
    [got] = read_attempts(log_path)
    assert got.afk is True
    assert got.listing_age_s == pytest.approx(30 * 3600, rel=0.01)
    assert got.band in {b.value for b in Band}
    assert got.pay_currency == "divine"


def test_reading_survives_a_corrupt_line(log_path):
    record_attempt(log_path, candidate())
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("{not json\n\n")
    record_attempt(log_path, candidate(char="Other"))
    assert len(read_attempts(log_path)) == 2


def test_a_verdict_for_an_unknown_attempt_is_ignored(log_path):
    record_attempt(log_path, candidate())
    record_outcome(log_path, "nosuchid", Outcome.FILLED)
    [got] = read_attempts(log_path)
    assert got.outcome is Outcome.PENDING


def test_missing_file_reads_as_empty(tmp_path):
    assert read_attempts(tmp_path / "nothing.jsonl") == []


def test_a_failed_write_does_not_raise(tmp_path):
    """Losing a log line must never interrupt a trade in progress."""
    blocked = tmp_path / "file-not-dir"
    blocked.write_text("x")
    record_attempt(blocked / "outcomes.jsonl", candidate())  # no exception


# --- summarising -----------------------------------------------------------

def test_no_fill_rate_is_claimed_from_too_few_attempts():
    """The 2-of-14 mistake, encoded: direction yes, rate no."""
    s = summarise([attempt(id=str(i), outcome=Outcome.FILLED) for i in range(3)])
    assert s.fills == 3
    assert s.fill_rate is None
    assert not s.has_enough_data


def test_fill_rate_appears_once_there_is_enough_data():
    rows = [attempt(id=str(i), outcome=Outcome.FILLED) for i in range(5)]
    rows += [attempt(id=f"n{i}", outcome=Outcome.NO_REPLY) for i in range(5)]
    s = summarise(rows)
    assert s.resolved == MIN_SAMPLES
    assert s.fill_rate == pytest.approx(0.5)


def test_pending_attempts_are_excluded_from_rates():
    rows = [attempt(id=str(i), outcome=Outcome.PENDING) for i in range(20)]
    rows += [attempt(id=f"f{i}", outcome=Outcome.FILLED) for i in range(10)]
    s = summarise(rows)
    assert s.total == 30
    assert s.resolved == 10
    assert s.fill_rate == pytest.approx(1.0)


def test_buckets_split_by_gap_age_and_presence():
    rows = [attempt(id=f"a{i}", gap=1.05, listing_age_s=600.0) for i in range(3)]
    rows += [attempt(id=f"b{i}", gap=8.0, listing_age_s=200_000.0, afk=True) for i in range(3)]
    s = summarise(rows)
    assert {b.label for b in s.by_gap} == {"1.0-1.1x", "over 3x"}
    assert {b.label for b in s.by_age} == {"under 1h", "over a day"}
    assert {b.label for b in s.by_presence} == {"seller active", "seller AFK"}


def test_realised_profit_prefers_the_reported_figure():
    """Expected profit is an estimate; what the user actually got is not."""
    rows = [attempt(id="a", outcome=Outcome.FILLED, expected_profit_divines=1.79,
                    actual_profit_divines=1.0)]
    assert summarise(rows).realised_divines == 1.0


def test_realised_profit_falls_back_to_expected_when_unreported():
    rows = [attempt(id="a", outcome=Outcome.FILLED, expected_profit_divines=1.79)]
    assert summarise(rows).realised_divines == pytest.approx(1.79)


def test_sold_and_no_reply_stay_distinct():
    """A seller who says 'gone' was reachable; silence may mean anything."""
    rows = [attempt(id="a", outcome=Outcome.SOLD), attempt(id="b", outcome=Outcome.NO_REPLY)]
    s = summarise(rows)
    assert s.resolved == 2 and s.fills == 0


def test_value_per_attempt_is_what_a_ranking_should_maximise():
    """A 10% fill rate on 5-divine trades beats 50% on 0.3-divine ones."""
    big = [attempt(id=f"b{i}", gap=1.4, outcome=Outcome.NO_REPLY) for i in range(9)]
    big += [attempt(id="bf", gap=1.4, outcome=Outcome.FILLED, expected_profit_divines=5.0)]
    small = [attempt(id=f"s{i}", gap=1.05, outcome=Outcome.FILLED,
                     expected_profit_divines=0.3) for i in range(5)]
    small += [attempt(id=f"sn{i}", gap=1.05, outcome=Outcome.NO_REPLY) for i in range(5)]
    s = summarise(big + small)
    by_label = {b.label: b for b in s.by_gap}
    assert by_label["1.25-1.5x"].value_per_attempt > by_label["1.0-1.1x"].value_per_attempt
    assert by_label["1.0-1.1x"].fill_rate > by_label["1.25-1.5x"].fill_rate


def test_no_band_is_suggested_without_data():
    assert suggested_gap_band(summarise([attempt(id="a")])) is None


def test_a_band_is_suggested_once_buckets_are_populated():
    rows = [attempt(id=f"a{i}", gap=1.05, outcome=Outcome.NO_REPLY) for i in range(10)]
    rows += [attempt(id=f"b{i}", gap=1.3, outcome=Outcome.FILLED,
                     expected_profit_divines=2.0) for i in range(10)]
    band = suggested_gap_band(summarise(rows))
    assert band == (1.25, 1.5)


# --- sessions, seasons and corrections --------------------------------------

def test_an_attempt_carries_its_session_and_league(log_path):
    """Neither is recoverable afterwards: sessions are how the app was driven,
    and league names rotate, so a log without them mixes two economies."""
    record_attempt(log_path, candidate(), session_id="sess1", league="Rise of the Abyssal")
    [a] = read_attempts(log_path)
    assert a.session_id == "sess1"
    assert a.league == "Rise of the Abyssal"
    assert a.pay_units == 11.0


def test_older_records_without_a_session_still_read(log_path):
    log_path.write_text(
        '{"kind": "attempt", "id": "x", "ts": "%s", "item_id": "omen", '
        '"gap": 1.2, "band": "plausible"}\n' % NOW.isoformat(),
        encoding="utf-8",
    )
    [a] = read_attempts(log_path)
    assert a.session_id is None and a.league is None


def test_an_amendment_corrects_the_quantity_and_keeps_the_ask(log_path):
    """The field case: whispered for 18, the seller only had 3."""
    c = candidate(pay=11.0, stock=18.0)
    attempt_id = record_attempt(log_path, c, session_id="s")
    record_amendment(log_path, attempt_id, replan_units(c, 3.0))
    record_outcome(log_path, attempt_id, Outcome.FILLED)

    [a] = read_attempts(log_path)
    assert a.amended is True
    assert a.units == 3.0
    assert a.asked_units == 18.0
    assert a.cost_divines == 33.0
    assert a.outcome is Outcome.FILLED


def test_an_amendment_can_correct_the_price_alone(log_path):
    """The counteroffer case: 1 fill in 36, and it logged a profit it lost."""
    c = candidate(pay=11.0, stock=1.0)
    attempt_id = record_attempt(log_path, c)
    record_amendment(log_path, attempt_id, repriced(c, 14.0))

    [a] = read_attempts(log_path)
    assert a.amended is True
    assert a.units == 1.0            # untouched
    assert a.cost_divines == 14.0
    assert a.asked_cost_divines == 11.0
    assert a.asked_pay_units == 11.0
    assert a.expected_profit_divines == pytest.approx(
        c.plan.proceeds_divines - 14.0
    )


def test_a_second_amendment_still_reports_the_original_ask(log_path):
    """Otherwise the ask decays into whatever the last correction left."""
    c = candidate(pay=11.0, stock=18.0)
    attempt_id = record_attempt(log_path, c)
    record_amendment(log_path, attempt_id, replan_units(c, 9.0))
    record_amendment(log_path, attempt_id, replan_units(c, 3.0))
    [a] = read_attempts(log_path)
    assert a.units == 3.0
    assert a.asked_units == 18.0


def test_the_settlement_floor_is_recorded_so_a_correction_can_reapply_it(log_path):
    """Profit rounds down to a whole unit of it, and nothing else records it."""
    record_attempt(log_path, candidate())
    [a] = read_attempts(log_path)
    assert a.sale_unit_divines == pytest.approx(0.0023)
    assert a.settle_currency == "divine"


def test_records_written_before_the_floor_was_logged_still_read(log_path):
    log_path.write_text(
        '{"kind": "attempt", "id": "x", "ts": "%s", "item_id": "omen", '
        '"gap": 1.2, "band": "plausible"}\n' % NOW.isoformat(),
        encoding="utf-8",
    )
    [a] = read_attempts(log_path)
    assert a.sale_unit_divines is None
    assert a.settle_currency is None


def test_a_verdict_after_an_amendment_is_not_undone_by_it(log_path):
    """Order in the file must not decide which correction wins."""
    c = candidate(pay=11.0, stock=18.0)
    attempt_id = record_attempt(log_path, c)
    record_outcome(log_path, attempt_id, Outcome.FILLED, actual_profit_divines=2.5)
    record_amendment(log_path, attempt_id, replan_units(c, 3.0))
    [a] = read_attempts(log_path)
    assert a.units == 3.0
    assert a.outcome is Outcome.FILLED
    assert a.actual_profit_divines == 2.5


# --- correcting a row whose listing is long gone -----------------------------
#
# The route back to a trade the queue can no longer reach: an expired verdict
# the timer got wrong, a quantity nobody corrected at the time, a counteroffered
# price. There is no candidate to re-plan — all that survives is the log row.

class TestPlanCorrection:
    def test_a_smaller_quantity_keeps_the_price_per_item(self):
        """"They only had three" does not change what three cost each."""
        a = attempt(lots=6, units=18.0, pay_units=198.0, cost_divines=198.0,
                    ce_divines=12.0, expected_profit_divines=18.0)
        got = plan_correction(a, units=3.0)
        assert got.units == 3.0
        assert got.lots == 1
        assert got.cost_divines == pytest.approx(33.0)
        assert got.pay_units == pytest.approx(33.0)

    def test_the_quantity_snaps_to_a_whole_lot(self):
        """Part of a lot would cost part of an orb, which cannot be traded."""
        a = attempt(lots=6, units=18.0, cost_divines=198.0, pay_units=198.0)
        assert plan_correction(a, units=4.0).units == 3.0
        assert plan_correction(a, units=5.0).units == 6.0

    def test_a_changed_price_leaves_the_quantity_and_the_proceeds_alone(self):
        """The counteroffer case: same goods, more money."""
        a = attempt(units=1.0, pay_units=11.0, cost_divines=11.0,
                    expected_profit_divines=0.9)
        got = plan_correction(a, cost_divines=14.0)
        assert got.units == 1.0
        # Proceeds were 11.9; profit follows the cost down.
        assert got.expected_profit_divines == pytest.approx(-2.1)

    def test_a_counteroffer_scales_the_sellers_own_currency_too(self):
        a = attempt(pay_currency="exalted", units=1.0, pay_units=2412.0,
                    cost_divines=5.58, expected_profit_divines=1.0)
        got = plan_correction(a, cost_divines=11.16)
        assert got.pay_units == pytest.approx(4824.0)

    def test_proceeds_are_re_floored_when_the_quantity_changes(self):
        """Partial currency cannot be traded, so they round down to a whole unit."""
        a = attempt(lots=4, units=4.0, pay_units=4.0, cost_divines=4.0,
                    ce_divines=3.79, expected_profit_divines=11.0,
                    sale_unit_divines=1.0)
        got = plan_correction(a, units=3.0)
        # floor(3 * 3.79) = 11, less 3 divines paid.
        assert got.expected_profit_divines == pytest.approx(8.0)

    def test_a_finer_settlement_currency_floors_less(self):
        a = attempt(lots=4, units=4.0, pay_units=4.0, cost_divines=4.0,
                    ce_divines=3.79, expected_profit_divines=11.0,
                    sale_unit_divines=0.0023)
        got = plan_correction(a, units=3.0)
        # 3 x 3.79 = 11.37, floored to 11.3689 rather than to 11, less 3 paid.
        assert got.expected_profit_divines == pytest.approx(8.3689, abs=1e-3)

    def test_an_unrecorded_settlement_floor_falls_back_to_a_whole_divine(self):
        """The pessimistic reading — understating profit is the safe error."""
        a = attempt(lots=4, units=4.0, pay_units=4.0, cost_divines=4.0,
                    ce_divines=3.79, expected_profit_divines=11.0,
                    sale_unit_divines=None)
        assert plan_correction(a, units=3.0).expected_profit_divines == pytest.approx(8.0)

    def test_correcting_nothing_reproduces_the_row(self):
        a = attempt(lots=2, units=2.0, pay_units=4.8, cost_divines=4.8,
                    expected_profit_divines=1.4)
        got = plan_correction(a)
        assert got.units == 2.0
        assert got.cost_divines == pytest.approx(4.8)
        assert got.expected_profit_divines == pytest.approx(1.4)


def test_a_correction_is_appended_like_any_other_amendment(log_path):
    c = candidate(pay=11.0, stock=18.0)
    attempt_id = record_attempt(log_path, c)
    [logged] = read_attempts(log_path)
    got = plan_correction(logged, units=3.0)
    record_correction(
        log_path, attempt_id,
        lots=got.lots, units=got.units, pay_units=got.pay_units,
        cost_divines=got.cost_divines,
        expected_profit_divines=got.expected_profit_divines,
    )
    [a] = read_attempts(log_path)
    assert a.units == 3.0
    assert a.asked_units == 18.0
    assert a.amended is True


def test_a_correction_omits_the_fields_it_was_not_given(log_path):
    """A price correction must not have to invent a quantity to go with it."""
    attempt_id = record_attempt(log_path, candidate(pay=11.0, stock=18.0))
    record_correction(log_path, attempt_id, cost_divines=200.0)
    rows = [json.loads(line) for line in log_path.read_text().splitlines()]
    amend = next(r for r in rows if r["kind"] == "amend")
    assert set(amend) == {"kind", "id", "ts", "cost_divines"}
    [a] = read_attempts(log_path)
    assert a.units == 18.0
    assert a.cost_divines == 200.0


def test_a_correction_can_reverse_a_verdict_the_timer_got_wrong(log_path):
    """The Rigwald's Ferocity case — the biggest trade, logged as no_reply."""
    attempt_id = record_attempt(log_path, candidate())
    record_outcome(log_path, attempt_id, Outcome.EXPIRED)
    assert read_attempts(log_path)[0].outcome is Outcome.EXPIRED
    record_outcome(log_path, attempt_id, Outcome.FILLED)
    assert read_attempts(log_path)[0].outcome is Outcome.FILLED


def test_sessions_group_by_id_and_come_back_newest_first(log_path):
    record_attempt(log_path, candidate(char="A"), session_id="old", league="Dawn")
    record_attempt(log_path, candidate(char="B"), session_id="new", league="Abyssal")
    record_attempt(log_path, candidate(char="C"), session_id="new", league="Abyssal")
    found = sessions(read_attempts(log_path))
    assert [s.id for s in found] == ["new", "old"]
    assert found[0].attempts == 2
    assert found[0].league == "Abyssal"
    assert "0/2 traded" in found[0].label


def test_leagues_lists_what_the_log_has_seen(log_path):
    record_attempt(log_path, candidate(char="A"), league="Dawn")
    record_attempt(log_path, candidate(char="B"), league="Abyssal")
    assert set(leagues(read_attempts(log_path))) == {"Dawn", "Abyssal"}


# --- the verdict vocabulary -------------------------------------------------
# NO_REPLY was retired as a *button* in 0.8.0 and split three ways. It stays in
# the enum because `outcomes.jsonl` returns records written under it forever —
# the same constraint that keeps `bands.symbol_for_name` resolving old bands.


def test_a_no_reply_record_still_reads_back(log_path):
    attempt_id = record_attempt(log_path, candidate())
    log_path.write_text(
        log_path.read_text()
        + json.dumps({"kind": "outcome", "id": attempt_id,
                      "ts": NOW.isoformat(), "outcome": "no_reply"}) + "\n"
    )
    [got] = read_attempts(log_path)
    assert got.outcome is Outcome.NO_REPLY
    assert label_for(got.outcome) == "No Reply"


@pytest.mark.parametrize(
    "outcome", [Outcome.EXPIRED, Outcome.AFK, Outcome.OFFLINE]
)
def test_the_new_verdicts_round_trip(log_path, outcome):
    attempt_id = record_attempt(log_path, candidate())
    record_outcome(log_path, attempt_id, outcome)
    [got] = read_attempts(log_path)
    assert got.outcome is outcome
    assert got.outcome.is_resolved and not got.outcome.is_success


def test_every_verdict_has_a_word_for_it():
    """A missing label would put a raw enum value in the table."""
    assert all(label_for(o) and not label_for(o).islower() for o in Outcome)


def test_silence_covers_the_old_value_too():
    """Anything asking "did they answer" must keep matching pre-split records."""
    assert {o for o in Outcome if o.is_silence} == {
        Outcome.NO_REPLY, Outcome.EXPIRED, Outcome.AFK, Outcome.OFFLINE
    }
