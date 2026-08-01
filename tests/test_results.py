"""The Results tab: what the whisper log is, and isn't, entitled to say."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2arb.gui.results import ResultsTab  # noqa: E402
from poe2arb.outcomes import MIN_SAMPLES, Outcome  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def write_log(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def attempt(i, *, gap=1.2, band="plausible", profit=2.0, afk=False, age=1800.0):
    return {
        "kind": "attempt", "id": f"a{i}",
        "ts": f"2026-07-{10 + i % 20:02d}T12:00:00+00:00",
        "item_id": "omen", "item_name": "Omen of Light",
        "account": f"seller{i}#1", "character": f"seller{i}",
        "pay_currency": "divine", "unit_price_divines": 10.0,
        "ce_divines": 12.0, "gap": gap, "band": band, "lots": 1, "units": 1.0,
        "cost_divines": 10.0, "expected_profit_divines": profit,
        "listing_age_s": age, "afk": afk,
    }


def verdict(i, outcome, profit=None):
    row = {"kind": "outcome", "id": f"a{i}",
           "ts": "2026-07-20T12:05:00+00:00", "outcome": outcome.value}
    if profit is not None:
        row["actual_profit_divines"] = profit
    return row


@pytest.fixture
def tab(qapp, tmp_path):
    def build(rows=()):
        path = tmp_path / "outcomes.jsonl"
        if rows:
            write_log(path, list(rows))
        t = ResultsTab()
        t.set_path(path)
        return t
    return build


class TestEmpty:
    def test_it_says_there_is_nothing_yet(self, tab):
        t = tab()
        assert "No trades logged yet" in t.headline.text()
        assert t.by_gap.rowCount() == 0

    def test_a_missing_file_is_not_an_error(self, tab, tmp_path):
        t = ResultsTab()
        t.set_path(tmp_path / "nothing-here.jsonl")
        assert t.attempts.rowCount() == 0

    def test_a_truncated_line_does_not_stop_the_tab(self, tab, tmp_path):
        path = tmp_path / "outcomes.jsonl"
        path.write_text(json.dumps(attempt(1)) + "\n{ half a li", encoding="utf-8")
        t = ResultsTab()
        t.set_path(path)
        assert t.attempts.rowCount() == 1


class TestHonestyAboutSampleSize:
    """The tab exists to replace guesses with measurements. It must not guess."""

    def test_no_fill_rate_is_claimed_from_a_handful(self, tab):
        rows = [attempt(i) for i in range(3)]
        rows += [verdict(i, Outcome.FILLED) for i in range(3)]
        t = tab(rows)
        rates = {
            t.by_gap.item(r, 3).text() for r in range(t.by_gap.rowCount())
        }
        assert rates == {"—"}

    def test_it_says_how_many_more_are_needed(self, tab):
        rows = [attempt(i) for i in range(3)]
        rows += [verdict(i, Outcome.FILLED) for i in range(3)]
        t = tab(rows)
        assert f"{MIN_SAMPLES - 3} more" in t.note.text()

    def test_a_rate_appears_once_there_is_enough(self, tab):
        n = MIN_SAMPLES + 2
        rows = [attempt(i) for i in range(n)]
        rows += [verdict(i, Outcome.FILLED if i % 2 else Outcome.NO_REPLY)
                 for i in range(n)]
        t = tab(rows)
        rates = [t.by_gap.item(r, 3).text() for r in range(t.by_gap.rowCount())]
        assert any(text.endswith("%") for text in rates)

    def test_unknown_rates_sort_below_real_ones(self, tab):
        """"no data" is not a good score; sorting on the column must not rank
        an unmeasured bucket above a measured one."""
        from PySide6.QtCore import Qt

        rows = [attempt(i, gap=1.15) for i in range(MIN_SAMPLES)]
        rows += [verdict(i, Outcome.FILLED) for i in range(MIN_SAMPLES)]
        rows += [attempt(99, gap=4.0), verdict(99, Outcome.NO_REPLY)]
        t = tab(rows)
        t.by_gap.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        assert t.by_gap.item(0, 3).text() != "—"
        assert t.by_gap.item(t.by_gap.rowCount() - 1, 3).text() == "—"

    def test_buckets_stay_in_their_natural_order(self, tab):
        """Discount ranges read as a progression; sorting them by rate hides that."""
        rows = [attempt(1, gap=1.05), attempt(2, gap=4.0)]
        rows += [verdict(1, Outcome.FILLED), verdict(2, Outcome.NO_REPLY)]
        t = tab(rows)
        assert t.by_gap.item(0, 0).text() == "1.0-1.1x"
        assert t.by_gap.item(1, 0).text() == "over 3x"


class TestTakings:
    def test_the_headline_counts_fills_and_divines(self, tab):
        rows = [attempt(1), attempt(2), verdict(1, Outcome.FILLED, 3.5),
                verdict(2, Outcome.NO_REPLY)]
        t = tab(rows)
        assert "1 of 2 whispers traded" in t.headline.text()
        assert "3.5 div" in t.headline.text()

    def test_unanswered_whispers_are_called_out(self, tab):
        rows = [attempt(1), attempt(2), verdict(1, Outcome.FILLED, 1.0)]
        t = tab(rows)
        assert "1 still unanswered" in t.headline.text()

    def test_reported_profit_beats_the_estimate(self, tab):
        """What you actually cleared is the number that counts."""
        rows = [attempt(1, profit=9.0), verdict(1, Outcome.FILLED, 2.0)]
        t = tab(rows)
        assert "2.0 div" in t.headline.text()

    def test_the_estimate_is_used_when_no_figure_was_given(self, tab):
        rows = [attempt(1, profit=9.0), verdict(1, Outcome.FILLED)]
        t = tab(rows)
        assert "9.0 div" in t.headline.text()


class TestEveryWhisper:
    def test_each_attempt_gets_a_row(self, tab):
        t = tab([attempt(i) for i in range(4)])
        assert t.attempts.rowCount() == 4

    def test_a_pending_attempt_reads_as_waiting(self, tab):
        t = tab([attempt(1)])
        assert t.attempts.item(0, 6).text() == "Waiting"

    def test_verdicts_are_shown_in_plain_words(self, tab):
        rows = [attempt(1), verdict(1, Outcome.EXPIRED)]
        t = tab(rows)
        assert t.attempts.item(0, 6).text() == "Expired"

    def test_records_written_before_the_verdict_was_split_still_read(self, tab):
        """`no_reply` is never written now and is returned by the log forever."""
        t = tab([attempt(1), verdict(1, Outcome.NO_REPLY)])
        assert t.attempts.item(0, 6).text() == "No Reply"

    def test_newest_first(self, tab):
        """The thing you just did is the thing you're looking for."""
        rows = [attempt(1), attempt(5)]
        t = tab(rows)
        stamps = [t.attempts.item(r, 0).text() for r in range(2)]
        assert stamps == sorted(stamps, reverse=True)


class TestBreakdowns:
    def test_seller_state_is_split(self, tab):
        rows = [attempt(1, afk=True), attempt(2, afk=False)]
        rows += [verdict(1, Outcome.NO_REPLY), verdict(2, Outcome.FILLED)]
        t = tab(rows)
        labels = {t.by_presence.item(r, 0).text()
                  for r in range(t.by_presence.rowCount())}
        assert labels == {"seller active", "seller AFK"}

    def test_empty_buckets_are_not_shown(self, tab):
        """A row of zeroes for a range you never whispered is just noise."""
        rows = [attempt(1, gap=1.15), verdict(1, Outcome.FILLED)]
        t = tab(rows)
        assert t.by_gap.rowCount() == 1

    def test_reloading_picks_up_new_trades(self, tab, tmp_path):
        t = tab([attempt(1)])
        write_log(tmp_path / "outcomes.jsonl", [attempt(1), attempt(2)])
        t.reload()
        assert t.attempts.rowCount() == 2


# --- Every trade ------------------------------------------------------------

def test_every_trade_lists_only_the_ones_that_filled(tab):
    """Asked for from the field: finding what you bought meant opening Every
    whisper and sorting on Result."""
    t = tab([
        attempt(0), verdict(0, Outcome.FILLED, profit=3.0),
        attempt(1), verdict(1, Outcome.NO_REPLY),
        attempt(2), verdict(2, Outcome.SOLD),
        attempt(3), verdict(3, Outcome.FILLED),
    ])
    assert t.attempts.rowCount() == 4
    assert t.trades.rowCount() == 2
    results = {t.trades.item(r, 6).text() for r in range(t.trades.rowCount())}
    assert results == {"Traded"}


def test_every_trade_is_empty_without_a_fill(tab):
    t = tab([attempt(0), verdict(0, Outcome.NO_REPLY)])
    assert t.attempts.rowCount() == 1
    assert t.trades.rowCount() == 0


def test_a_corrected_quantity_shows_what_was_asked_for(tab):
    """The difference between the ask and the trade measures missing stock."""
    t = tab([
        attempt(0),
        {"kind": "amend", "id": "a0", "ts": "2026-07-20T12:04:00+00:00",
         "lots": 1, "units": 3.0, "cost_divines": 3.0,
         "expected_profit_divines": 0.9},
        verdict(0, Outcome.FILLED),
    ])
    cell = t.trades.item(0, 2)
    assert cell.text() == "3"
    assert "Asked for 1" in cell.toolTip()
