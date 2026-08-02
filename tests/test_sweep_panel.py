"""The Trades tab: ranking on screen, filtering, and clipboard behaviour."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2arb.gui.sweep_panel import (  # noqa: E402
    AGE_COLUMN,
    AMOUNT_COLUMN,
    BAND_COLUMN,
    PROFIT_COLUMN,
    SELLER_COLUMN,
    SETTLE_COLUMN,
    TOTAL_COLUMN,
    SweepPanel,
)
from poe2arb.listings import (  # noqa: E402
    Band,
    Listing,
    build_candidates,
    rank_candidates,
)
from poe2arb.outcomes import Outcome  # noqa: E402
from poe2arb.sweep import SweepResult  # noqa: E402

NOW = datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def listing(item, pay, *, currency="divine", stock=1.0, char="Char", age_h=3.0, afk=False):
    return Listing(
        item_id=item,
        account=f"{char}#1",
        character=char,
        pay_currency=currency,
        pay_amount=pay,
        get_amount=1.0,
        stock=stock,
        indexed=NOW - timedelta(hours=age_h),
        afk=afk,
        whisper=f"@{char} buy {{0}} for {{1}}",
        item_whisper="{0} Thing",
        pay_whisper="{0} Coin",
    )


def result_from(listings, prices=None, **kw):
    prices = prices or {"omen": 12.0, "orb": 4.0, "divine": 1.0, "exalted": 0.0023}
    cands = rank_candidates(
        build_candidates(
            listings, prices, {"omen": "Omen of Light", "orb": "Some Orb"},
            min_gap=kw.get("min_gap", 1.05),
            max_gap=kw.get("max_gap", 1.5),
            sale_unit_divines=0.0023,
        )
    )
    return SweepResult(
        league="Runes of Aldur",
        started_at=NOW - timedelta(minutes=14),
        finished_at=NOW,
        items=["omen", "orb"],
        candidates=cands,
        listings_seen=len(listings),
        errors=kw.get("errors", {}),
    )


def panel(qapp, result, *, recheck=False) -> SweepPanel:
    p = SweepPanel()
    # Most tests exercise copying directly; the pre-whisper check is a network
    # round trip and has its own tests below.
    p.recheck_box.setChecked(recheck)
    p.set_result(result)
    qapp.processEvents()
    return p


def visible_rows(p) -> int:
    return sum(1 for r in range(p.table.rowCount()) if not p.table.isRowHidden(r))


def band_at(p, row) -> Band:
    """Band of the candidate on a *view* row, which sorting reorders."""
    return p.table.item(row, BAND_COLUMN).data(Qt.ItemDataRole.UserRole).band


# --- ranking on screen -----------------------------------------------------

def test_ghosts_render_last_despite_being_the_most_profitable(qapp):
    """The whole point of the tab: don't lead the user to the listing that never fills."""
    p = panel(qapp, result_from([
        listing("omen", 1.0, char="Ghost", stock=2.0),   # 12x gap, biggest profit
        listing("omen", 11.0, char="Real"),              # 1.09x gap, small profit
    ]))
    assert p.table.item(0, SELLER_COLUMN).text() == "Real"
    assert p.table.item(1, SELLER_COLUMN).text() == "Ghost"
    # ...and the ghost really is worth more on paper.
    top = p.table.item(0, PROFIT_COLUMN)
    bottom = p.table.item(1, PROFIT_COLUMN)
    assert bottom.value > top.value


def test_band_column_sorts_by_band_not_by_glyph(qapp):
    """Sorting the band column must group by meaning, not by character code.

    The glyphs are ● ○ ×; alphabetical order on those is arbitrary, so the cell
    carries -rank and sorts on that instead.
    """
    from PySide6.QtCore import Qt

    p = panel(qapp, result_from([
        listing("omen", 1.0, char="Ghost", stock=2.0),
        listing("omen", 11.0, char="Real"),
    ]))
    p.table.sortItems(BAND_COLUMN, Qt.SortOrder.DescendingOrder)
    qapp.processEvents()
    assert band_at(p, 0) is Band.PLAUSIBLE
    assert band_at(p, p.table.rowCount() - 1) is Band.GHOST

    p.table.sortItems(BAND_COLUMN, Qt.SortOrder.AscendingOrder)
    qapp.processEvents()
    assert band_at(p, 0) is Band.GHOST


def test_hiding_ghosts_leaves_the_real_rows(qapp):
    p = panel(qapp, result_from([
        listing("omen", 1.0, char="Ghost", stock=2.0),
        listing("omen", 11.0, char="Real"),
    ]))
    assert visible_rows(p) == 2
    p.hide_ghosts.setChecked(True)
    qapp.processEvents()
    assert visible_rows(p) == 1


def test_search_matches_item_and_seller(qapp):
    p = panel(qapp, result_from([
        listing("omen", 11.0, char="Alice"),
        listing("orb", 3.0, char="Bob"),
    ]))
    p.search.setText("bob")
    qapp.processEvents()
    assert visible_rows(p) == 1
    p.search.setText("Omen")
    qapp.processEvents()
    assert visible_rows(p) == 1
    p.search.setText("")
    qapp.processEvents()
    assert visible_rows(p) == 2


def test_search_does_not_match_the_numeric_columns(qapp):
    """A price of 11.0 shouldn't be found by typing a quantity."""
    p = panel(qapp, result_from([listing("omen", 11.0, char="Alice")]))
    p.search.setText("11")
    qapp.processEvents()
    assert visible_rows(p) == 0


# --- the clipboard ---------------------------------------------------------

def test_copy_puts_the_whisper_on_the_clipboard(qapp):
    p = panel(qapp, result_from([listing("omen", 11.0, char="Real")]))
    p.table.selectRow(0)
    qapp.processEvents()
    assert p.copy_btn.isEnabled()
    p.copy_selected()
    assert QGuiApplication.clipboard().text() == "@Real buy 1 Thing for 11 Coin"


def test_copy_survives_re_sorting(qapp):
    """Row index stops being a candidate index once the user sorts a column."""
    p = panel(qapp, result_from([
        listing("omen", 11.0, char="Real"),
        listing("orb", 3.0, char="Other"),
    ]))
    p.table.sortItems(PROFIT_COLUMN)
    qapp.processEvents()
    p.table.selectRow(0)
    qapp.processEvents()
    seller = p.table.item(0, SELLER_COLUMN).text()
    p.copy_selected()
    assert seller in QGuiApplication.clipboard().text()


def test_copy_is_disabled_without_a_whisper_template(qapp):
    bare = listing("omen", 11.0, char="Real")
    bare = Listing(**{**bare.__dict__, "whisper": None, "item_whisper": None, "pay_whisper": None})
    p = panel(qapp, result_from([bare]))
    p.table.selectRow(0)
    qapp.processEvents()
    assert not p.copy_btn.isEnabled()


def test_nothing_selected_means_nothing_copied(qapp):
    p = panel(qapp, result_from([listing("omen", 11.0)]))
    QGuiApplication.clipboard().setText("untouched")
    p.copy_selected()
    assert QGuiApplication.clipboard().text() == "untouched"


# --- status ----------------------------------------------------------------

def test_status_summarises_the_sweep(qapp):
    p = panel(qapp, result_from([
        listing("omen", 11.0, char="Real"),
        listing("omen", 1.0, char="Ghost", stock=2.0),
    ]))
    text = p.status.text()
    assert "2 items checked" in text
    assert "2 live listings" in text
    # Same words as the legend under the table, not the internal band names.
    assert "too good to be true" in text
    assert "worth trying" in text


def test_status_says_so_when_nothing_plausible_turned_up(qapp):
    """Two live sweeps in a row found only ghosts — the user should be told."""
    p = panel(qapp, result_from([listing("omen", 1.0, char="Ghost", stock=2.0)]))
    assert "nothing worth trying" in p.status.text()


def test_failed_items_are_surfaced(qapp):
    p = panel(qapp, result_from([listing("omen", 11.0)], errors={"orb": "HTTP 503"}))
    assert "1 item(s) failed" in p.status.text()


def test_empty_sweep_does_not_claim_a_best_trade(qapp):
    p = panel(qapp, result_from([]))
    assert p.table.rowCount() == 0
    assert "best plausible" not in p.status.text()


# --- mixed denominations ---------------------------------------------------

def test_exalted_rows_show_a_divine_price_and_their_own_currency(qapp):
    """A sweep mixes denominations; the price column has to stay comparable."""
    p = panel(qapp, result_from([listing("omen", 4000.0, currency="exalted", stock=1.0)]))
    assert p.table.item(0, 3).text() == "ex"
    assert p.table.item(0, 2).value == pytest.approx(9.2, abs=0.2)  # 4000 ex in divines


def test_afk_is_marked_on_the_age(qapp):
    p = panel(qapp, result_from([listing("omen", 11.0, age_h=30.0, afk=True)]))
    assert p.table.item(0, AGE_COLUMN).text().endswith("*")


# --- outcome reporting -----------------------------------------------------

def test_outcome_buttons_stay_disabled_until_a_whisper_is_copied(qapp):
    """Reporting on a listing you never messaged would poison the training data."""
    from poe2arb.outcomes import Outcome

    p = panel(qapp, result_from([listing("omen", 11.0, char="Real")]))
    p.table.selectRow(0)
    qapp.processEvents()
    assert not p._outcome_btns[Outcome.FILLED].isEnabled()

    p.copy_selected()
    p.note_attempt(p.selected_candidate(), "abc123")
    qapp.processEvents()
    assert p._outcome_btns[Outcome.FILLED].isEnabled()


def test_copying_emits_the_candidate_for_logging(qapp):
    seen = []
    p = panel(qapp, result_from([listing("omen", 11.0, char="Real")]))
    p.attempt_copied.connect(seen.append)
    p.table.selectRow(0)
    qapp.processEvents()
    p.copy_selected()
    assert len(seen) == 1
    assert seen[0].listing.character == "Real"


def test_reporting_emits_the_attempt_id_and_verdict(qapp):
    from poe2arb.outcomes import Outcome

    seen = []
    p = panel(qapp, result_from([listing("omen", 11.0, char="Real")]))
    p.outcome_reported.connect(lambda i, o: seen.append((i, o)))
    p.table.selectRow(0)
    qapp.processEvents()
    p.copy_selected()
    p.note_attempt(p.selected_candidate(), "abc123")
    p._report(Outcome.FILLED)
    assert seen == [("abc123", Outcome.FILLED)]
    assert "traded" in p.status.text().lower()


def _select_seller(p, qapp, name: str):
    """Select the row for a seller, whatever the current sort put it at."""
    for row in range(p.table.rowCount()):
        c = p._candidate_at(row)
        if c is not None and c.listing.character == name:
            p.table.selectRow(row)
            qapp.processEvents()
            return c
    raise AssertionError(f"no row for {name!r}")


def test_a_new_sweep_leaves_an_unwhispered_candidate_without_a_verdict(qapp):
    """Buttons follow the attempt, not the selection.

    Reporting an outcome against a listing you never messaged would poison the
    data the ranking is meant to learn from.
    """
    from poe2arb.outcomes import Outcome

    p = panel(qapp, result_from([listing("omen", 11.0, char="Real")]))
    p.table.selectRow(0)
    qapp.processEvents()
    p.copy_selected()
    p.note_attempt(p.selected_candidate(), "abc123")
    qapp.processEvents()
    assert p._outcome_btns[Outcome.FILLED].isEnabled()

    p.set_result(result_from([listing("omen", 11.5, char="Fresh")]))
    _select_seller(p, qapp, "Fresh")
    assert not p._outcome_btns[Outcome.FILLED].isEnabled()


# --- pre-whisper re-check --------------------------------------------------

def test_copy_asks_for_a_recheck_before_copying(qapp):
    """The listing may already be gone; find out before spending the whisper."""
    from PySide6.QtGui import QGuiApplication

    asked = []
    p = panel(qapp, result_from([listing("omen", 11.0, char="Real")]), recheck=True)
    p.recheck_requested.connect(asked.append)
    p.table.selectRow(0)
    qapp.processEvents()
    QGuiApplication.clipboard().setText("untouched")
    p.copy_selected()
    assert len(asked) == 1
    assert QGuiApplication.clipboard().text() == "untouched"  # nothing copied yet
    assert "Checking" in p.status.text()


def test_a_live_recheck_copies_the_whisper(qapp):
    from poe2arb.sweep import RecheckResult, RecheckStatus

    p = panel(qapp, result_from([listing("omen", 11.0, char="Real")]), recheck=True)
    p.table.selectRow(0)
    qapp.processEvents()
    c = p.selected_candidate()
    p.recheck_finished(c, RecheckResult(RecheckStatus.LIVE, "still listed", c.listing))
    assert QGuiApplication.clipboard().text() == "@Real buy 1 Thing for 11 Coin"


def test_a_gone_listing_is_not_copied(qapp):
    """Two of the first four field attempts died exactly this way."""
    from poe2arb.sweep import RecheckResult, RecheckStatus

    p = panel(qapp, result_from([listing("omen", 11.0, char="Real")]), recheck=True)
    p.table.selectRow(0)
    qapp.processEvents()
    QGuiApplication.clipboard().setText("untouched")
    c = p.selected_candidate()
    p.recheck_finished(c, RecheckResult(RecheckStatus.GONE, "no longer listed", None))
    assert QGuiApplication.clipboard().text() == "untouched"
    assert "no longer listed" in p.status.text()


def test_clicking_again_after_a_warning_copies_anyway(qapp):
    """The user overrules us; don't trap them in the same warning forever."""
    from poe2arb.sweep import RecheckResult, RecheckStatus

    p = panel(qapp, result_from([listing("omen", 11.0, char="Real")]), recheck=True)
    p.table.selectRow(0)
    qapp.processEvents()
    c = p.selected_candidate()
    p.recheck_finished(c, RecheckResult(RecheckStatus.GONE, "no longer listed", None))
    QGuiApplication.clipboard().setText("untouched")
    p.copy_selected()
    assert QGuiApplication.clipboard().text() == "@Real buy 1 Thing for 11 Coin"


def test_a_failed_recheck_still_copies_with_a_caveat(qapp):
    """Unknown is not evidence of absence."""
    from poe2arb.sweep import RecheckResult, RecheckStatus

    p = panel(qapp, result_from([listing("omen", 11.0, char="Real")]), recheck=True)
    p.table.selectRow(0)
    qapp.processEvents()
    c = p.selected_candidate()
    p.recheck_finished(c, RecheckResult(RecheckStatus.UNKNOWN, "network down", None))
    assert QGuiApplication.clipboard().text() == "@Real buy 1 Thing for 11 Coin"
    assert "couldn't verify" in p.status.text()


def test_reduced_stock_copies_but_warns(qapp):
    from poe2arb.sweep import RecheckResult, RecheckStatus

    p = panel(qapp, result_from([listing("omen", 11.0, char="Real", stock=4.0)]), recheck=True)
    p.table.selectRow(0)
    qapp.processEvents()
    c = p.selected_candidate()
    p.recheck_finished(c, RecheckResult(RecheckStatus.REDUCED, "stock down from 4 to 1", None))
    assert QGuiApplication.clipboard().text().startswith("@Real")
    assert "stock down" in p.status.text()


# --- what happened, not just what was on offer ------------------------------

def _select_mode(p, mode):
    index = p.show_mode.findData(mode)
    assert index >= 0
    p.show_mode.setCurrentIndex(index)


def test_the_table_can_be_narrowed_to_what_was_messaged(qapp):
    """After a session it was hard to find what you'd actually acted on."""
    from poe2arb.gui.sweep_panel import SHOW_ALL, SHOW_WHISPERED

    p = panel(qapp, result_from([
        listing("omen", 11.0, char="Messaged"),
        listing("omen", 11.2, char="Ignored"),
    ]))
    assert visible_rows(p) == 2

    target = next(
        c for c in p._candidates if c.listing.character == "Messaged"
    )
    p.note_attempt(target, "attempt-1")
    _select_mode(p, SHOW_WHISPERED)
    qapp.processEvents()
    assert visible_rows(p) == 1
    shown = [
        p.table.item(r, SELLER_COLUMN).text()
        for r in range(p.table.rowCount())
        if not p.table.isRowHidden(r)
    ]
    assert shown == ["Messaged"]

    _select_mode(p, SHOW_ALL)
    assert visible_rows(p) == 2


def test_bought_lists_only_trades_reported_as_filled(qapp):
    from poe2arb.outcomes import Outcome
    from poe2arb.gui.sweep_panel import SHOW_BOUGHT

    p = panel(qapp, result_from([
        listing("omen", 11.0, char="Bought"),
        listing("omen", 11.2, char="Silent"),
    ]))
    bought = next(c for c in p._candidates if c.listing.character == "Bought")
    silent = next(c for c in p._candidates if c.listing.character == "Silent")
    p.note_attempt(bought, "a1")
    p.note_attempt(silent, "a2")
    p._outcomes[bought.key] = Outcome.FILLED
    p._outcomes[silent.key] = Outcome.NO_REPLY

    _select_mode(p, SHOW_BOUGHT)
    qapp.processEvents()
    shown = [
        p.table.item(r, SELLER_COLUMN).text()
        for r in range(p.table.rowCount())
        if not p.table.isRowHidden(r)
    ]
    assert shown == ["Bought"]


def test_an_empty_filter_explains_itself(qapp):
    """An empty table with no explanation reads as a broken tab."""
    from poe2arb.gui.sweep_panel import SHOW_BOUGHT

    p = panel(qapp, result_from([listing("omen", 11.0)]))
    _select_mode(p, SHOW_BOUGHT)
    qapp.processEvents()
    assert visible_rows(p) == 0
    assert "marked as Traded" in p.status.text()


def test_a_whispered_listing_survives_the_next_sweep(qapp):
    """Otherwise "Trades" empties itself the moment a purchase succeeds.

    A listing you bought is by definition gone from the next sweep, and the
    verdicts were being cleared alongside it — so both history filters were
    blank by the time a session was worth reviewing.
    """
    from poe2arb.gui.sweep_panel import SHOW_ALL, SHOW_BOUGHT
    from poe2arb.outcomes import Outcome

    p = panel(qapp, result_from([listing("omen", 11.0, char="A")]))
    c = p._candidates[0]
    p.note_attempt(c, "a1")
    p.note_outcome(c, Outcome.FILLED)

    p.set_result(result_from([listing("omen", 11.0, char="B")]))
    assert p._outcomes[c.key] is Outcome.FILLED
    assert p._attempt_ids[c.key] == "a1"

    _select_mode(p, SHOW_BOUGHT)
    qapp.processEvents()
    assert visible_rows(p) == 1
    # ...but "All Results" still means what it says.
    _select_mode(p, SHOW_ALL)
    qapp.processEvents()
    assert visible_rows(p) == 1
    assert _select_seller(p, qapp, "B") is not None


# --- settlement currency ----------------------------------------------------

def test_the_settlement_currency_is_shown_per_row(qapp):
    """You need to know which currency a trade's profit was costed against."""
    from poe2arb.gui.sweep_panel import SETTLE_COLUMN

    p = SweepPanel()
    p.set_settlement_currency("exalted")
    p.set_result(result_from([listing("omen", 11.0)]))
    qapp.processEvents()
    assert p.table.item(0, SETTLE_COLUMN).text() == "ex"


def test_changing_settlement_relabels_existing_rows(qapp):
    from poe2arb.gui.sweep_panel import SETTLE_COLUMN

    p = panel(qapp, result_from([listing("omen", 11.0)]))
    p.set_settlement_currency("exalted")
    assert p.table.item(0, SETTLE_COLUMN).text() == "ex"
    p.set_settlement_currency("divine")
    assert p.table.item(0, SETTLE_COLUMN).text() == "div"


# --- a bankroll changed after the sweep --------------------------------------
#
# The sweep sizes each item as it reaches it, so a bankroll changed mid-pass or
# after it reaches nothing already on the table. Measured 2026-08-02 on the
# other surface: a 599 divine row against a 260 divine bankroll, whispered.

def test_lowering_the_bankroll_re_sizes_the_rows_on_the_table(qapp):
    p = panel(qapp, result_from([listing("omen", 11.0, stock=10.0)]))
    assert p.table.item(0, AMOUNT_COLUMN).text() == "10"

    p.set_bankroll({"divine": 55.0})
    qapp.processEvents()

    assert p.table.item(0, AMOUNT_COLUMN).text() == "5"
    assert p.table.item(0, TOTAL_COLUMN).value == 55.0


def test_a_bankroll_set_before_a_sweep_sizes_what_it_finds(qapp):
    """The sweep reads it per item; re-applying it here normalises a pass that
    straddled a change."""
    p = SweepPanel()
    p.set_bankroll({"divine": 33.0})
    p.set_result(result_from([listing("omen", 11.0, stock=10.0)]))
    qapp.processEvents()
    assert p.table.item(0, AMOUNT_COLUMN).text() == "3"


def test_a_whispered_row_keeps_the_quantity_it_was_whispered_at(qapp):
    """It is the record of a message already sent, on this surface too."""
    p = panel(qapp, result_from([listing("omen", 11.0, stock=10.0)]))
    p.note_attempt(p._candidates[0], "a1")

    p.set_bankroll({"divine": 22.0})
    qapp.processEvents()

    assert p.table.item(0, AMOUNT_COLUMN).text() == "10"


def test_the_status_line_follows_the_re_sized_profits(qapp):
    """It quotes the best profit on the table, so it cannot go on quoting one
    from a bankroll the user has just changed."""
    p = panel(qapp, result_from([listing("omen", 11.0, stock=10.0)]))
    assert "best is +10.00 div" in p.status.text()

    p.set_bankroll({"divine": 33.0})
    qapp.processEvents()

    assert "best is +3.00 div" in p.status.text()


def test_a_row_that_no_longer_profits_at_any_size_leaves_the_table(qapp):
    p = panel(qapp, result_from([listing("omen", 11.0, stock=10.0)]))
    p.set_bankroll({"divine": 5.0})
    qapp.processEvents()
    assert p.table.rowCount() == 0


# --- the odds legend --------------------------------------------------------

def test_the_odds_symbols_are_explained_on_screen(qapp):
    """They were only in a header tooltip, which reads as decoration."""
    p = panel(qapp, result_from([listing("omen", 11.0)]))
    text = p.legend.text()
    for glyph in ("●", "○", "×"):
        assert glyph in text
    assert "worth trying" in text


def test_trades_and_results_use_one_set_of_symbols(qapp):
    """The two tabs showed the same fact in two vocabularies."""
    from poe2arb.gui import bands
    from poe2arb.gui.sweep_panel import BAND_LABEL

    assert BAND_LABEL is bands.BAND_LABEL
    assert bands.symbol_for_name("plausible") == bands.BAND_LABEL[Band.PLAUSIBLE]
    assert bands.symbol_for_name("ghost") == bands.BAND_LABEL[Band.GHOST]


def test_an_unknown_band_still_prints_something(qapp):
    """Old log records must not blank the column or raise mid-redraw."""
    from poe2arb.gui import bands

    assert bands.symbol_for_name("something-retired") == "something-retired"
    assert bands.tip_for_name("something-retired") == ""


# --- reviewing a past session ----------------------------------------------

def _log(path, rows):
    import json

    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


def _attempt(n, session, league, outcome, ts=None):
    return [
        {
            "kind": "attempt", "id": f"id{n}", "ts": (ts or NOW).isoformat(),
            "session_id": session, "league": league, "item_id": "omen",
            "item_name": "Omen of Light", "account": f"seller{n}#1",
            "character": f"Seller{n}", "pay_currency": "exalted",
            "unit_price_divines": 2.4, "ce_divines": 3.1, "gap": 1.29,
            "band": "plausible", "lots": 2, "units": 2.0, "cost_divines": 4.8,
            "expected_profit_divines": 1.4, "listing_age_s": 3600.0,
            "afk": False, "outcome": "pending",
        },
        {"kind": "outcome", "id": f"id{n}", "ts": (ts or NOW).isoformat(),
         "outcome": outcome},
    ]


def test_the_session_picker_offers_what_the_log_holds(qapp, tmp_path):
    path = tmp_path / "outcomes.jsonl"
    _log(path, _attempt(0, "s1", "Abyssal", "filled") + _attempt(1, "s2", "Dawn", "no_reply"))
    p = SweepPanel()
    p.set_history_path(path)
    qapp.processEvents()
    assert [p.session.itemData(i) for i in range(2)] == ["live", "all"]
    assert p.session.count() == 4          # live, all time, and the two sessions
    # Two leagues, so the season picker is worth showing.
    assert p.season.isVisibleTo(p) or p.season.count() == 3


def test_a_past_session_lists_its_whispers_from_the_log(qapp, tmp_path):
    path = tmp_path / "outcomes.jsonl"
    _log(path, _attempt(0, "s1", "Abyssal", "filled") + _attempt(1, "s2", "Dawn", "no_reply"))
    p = SweepPanel()
    p.set_history_path(path)
    p.session.setCurrentIndex(p.session.findData("s1"))
    qapp.processEvents()
    assert p.table.rowCount() == 1
    assert p.table.item(0, SELLER_COLUMN).text() == "Seller0"
    # The Settle in column carries the verdict on a past session.
    assert p.table.item(0, 9).text() == "Traded"
    # Nothing to copy: the listing is long gone.
    assert p.selected_candidate() is None


def test_the_season_narrows_the_sessions_on_offer(qapp, tmp_path):
    path = tmp_path / "outcomes.jsonl"
    _log(path, _attempt(0, "s1", "Abyssal", "filled") + _attempt(1, "s2", "Dawn", "no_reply"))
    p = SweepPanel()
    p.set_history_path(path)
    p.season.setCurrentIndex(p.season.findData("Dawn"))
    qapp.processEvents()
    ids = [p.session.itemData(i) for i in range(p.session.count())]
    assert "s2" in ids and "s1" not in ids


def test_all_time_spans_every_session(qapp, tmp_path):
    path = tmp_path / "outcomes.jsonl"
    _log(path, _attempt(0, "s1", "Abyssal", "filled") + _attempt(1, "s2", "Dawn", "no_reply"))
    p = SweepPanel()
    p.set_history_path(path)
    p.session.setCurrentIndex(p.session.findData("all"))
    qapp.processEvents()
    assert p.table.rowCount() == 2


def test_the_running_session_is_not_listed_twice(qapp, tmp_path):
    """It is already the first entry, under the name "This session"."""
    path = tmp_path / "outcomes.jsonl"
    _log(path, _attempt(0, "live1", "Abyssal", "filled"))
    p = SweepPanel()
    p.set_live_session("live1")
    p.set_history_path(path)
    qapp.processEvents()
    assert [p.session.itemData(i) for i in range(p.session.count())] == ["live", "all"]


def test_a_sweep_does_not_yank_a_history_view_away(qapp, tmp_path):
    """The table refreshes every ten minutes; a session being reviewed must not."""
    path = tmp_path / "outcomes.jsonl"
    _log(path, _attempt(0, "s1", "Abyssal", "filled"))
    p = SweepPanel()
    p.set_history_path(path)
    p.session.setCurrentIndex(p.session.findData("s1"))
    qapp.processEvents()
    p.set_result(result_from([listing("omen", 11.0, char="Fresh")]))
    qapp.processEvents()
    assert p.table.rowCount() == 1
    assert p.table.item(0, SELLER_COLUMN).text() == "Seller0"


# --- correcting a logged trade in place --------------------------------------
#
# Item 1 of TODO's "Start here": every non-derived value on a row editable,
# price included. This is the only route back to a row the timer wrote down
# wrong, and the only way a counteroffered trade stops logging a profit it lost.

def _history_panel(qapp, tmp_path, rows=None, *, session="s1"):
    path = tmp_path / "outcomes.jsonl"
    _log(path, rows or _attempt(0, session, "Abyssal", "expired"))
    p = SweepPanel()
    # Answered without a dialog by default; the prompt has its own test.
    p.confirm_amendment = lambda _a: True
    p.set_history_path(path)
    p.session.setCurrentIndex(p.session.findData(session))
    qapp.processEvents()
    return p, path


def test_a_live_row_is_not_editable(qapp):
    """There is nothing to correct about a listing nobody has acted on."""
    from PySide6.QtWidgets import QAbstractItemView

    p = panel(qapp, result_from([listing("omen", 11.0)]))
    assert p.table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    for column in (AMOUNT_COLUMN, TOTAL_COLUMN, SETTLE_COLUMN):
        assert not p.table.item(0, column).flags() & Qt.ItemFlag.ItemIsEditable


def test_a_history_row_edits_the_three_non_derived_cells(qapp, tmp_path):
    from PySide6.QtWidgets import QAbstractItemView

    p, _ = _history_panel(qapp, tmp_path)
    assert p.table.editTriggers() & QAbstractItemView.EditTrigger.DoubleClicked
    for column in (AMOUNT_COLUMN, TOTAL_COLUMN, SETTLE_COLUMN):
        assert p.table.item(0, column).flags() & Qt.ItemFlag.ItemIsEditable
    # Derived, and therefore read-only: profit, gap, the Exchange reference.
    for column in (PROFIT_COLUMN, 4, 5):
        assert not p.table.item(0, column).flags() & Qt.ItemFlag.ItemIsEditable


def test_editing_the_result_reports_the_verdict(qapp, tmp_path):
    """The Rigwald's Ferocity case: the biggest trade, logged as expired."""
    p, _ = _history_panel(qapp, tmp_path)
    seen = []
    p.outcome_reported.connect(lambda i, o: seen.append((i, o)))
    p.table.item(0, SETTLE_COLUMN).setText("Traded")
    qapp.processEvents()
    assert seen == [("id0", Outcome.FILLED)]


def test_a_result_set_to_what_it_already_says_writes_nothing(qapp, tmp_path):
    p, _ = _history_panel(qapp, tmp_path)
    seen = []
    p.outcome_reported.connect(lambda *a: seen.append(a))
    p.table.item(0, SETTLE_COLUMN).setText("Expired")
    qapp.processEvents()
    assert seen == []


def test_an_unrecognised_verdict_is_ignored(qapp, tmp_path):
    """The drop-down cannot produce one, but a stray setText must not log it."""
    p, _ = _history_panel(qapp, tmp_path)
    seen = []
    p.outcome_reported.connect(lambda *a: seen.append(a))
    p.table.item(0, SETTLE_COLUMN).setText("Sort of")
    qapp.processEvents()
    assert seen == []


def test_editing_the_amount_re_costs_the_trade(qapp, tmp_path):
    """Whispered for 2 at 2.4 div each; only 1 was there."""
    p, _ = _history_panel(qapp, tmp_path)
    seen = []
    p.correction_requested.connect(lambda i, c: seen.append((i, c)))
    p.table.item(0, AMOUNT_COLUMN).setText("1")
    qapp.processEvents()
    [(attempt_id, correction)] = seen
    assert attempt_id == "id0"
    assert correction.units == 1.0
    assert correction.cost_divines == pytest.approx(2.4)


def test_editing_the_total_is_the_counteroffer_case(qapp, tmp_path):
    p, _ = _history_panel(qapp, tmp_path)
    seen = []
    p.correction_requested.connect(lambda i, c: seen.append((i, c)))
    p.table.item(0, TOTAL_COLUMN).setText("9.0")
    qapp.processEvents()
    [(_, correction)] = seen
    assert correction.units == 2.0                       # quantity untouched
    assert correction.cost_divines == pytest.approx(9.0)
    # Proceeds were 6.2; paying 9 for them is a loss, and the log must say so.
    assert correction.expected_profit_divines < 0


def test_a_total_typed_as_nonsense_changes_nothing_and_says_so(qapp, tmp_path):
    p, _ = _history_panel(qapp, tmp_path)
    seen = []
    p.correction_requested.connect(lambda *a: seen.append(a))
    p.table.item(0, TOTAL_COLUMN).setText("about nine")
    qapp.processEvents()
    assert seen == []
    assert "isn't a number" in p.status.text()


def test_retyping_the_same_figure_writes_nothing(qapp, tmp_path):
    p, _ = _history_panel(qapp, tmp_path)
    seen = []
    p.correction_requested.connect(lambda *a: seen.append(a))
    p.table.item(0, AMOUNT_COLUMN).setText("2")
    qapp.processEvents()
    assert seen == []


def test_declining_the_confirmation_leaves_the_record_alone(qapp, tmp_path):
    p, _ = _history_panel(qapp, tmp_path)
    p.confirm_amendment = lambda _a: False
    seen = []
    p.correction_requested.connect(lambda *a: seen.append(a))
    p.outcome_reported.connect(lambda *a: seen.append(a))
    p.table.item(0, AMOUNT_COLUMN).setText("1")
    p.table.item(0, SETTLE_COLUMN).setText("Traded")
    qapp.processEvents()
    assert seen == []


def test_a_fresh_record_is_amended_without_a_prompt(qapp, tmp_path):
    """Inside an hour the correction is part of the trade you are still doing."""
    path = tmp_path / "outcomes.jsonl"
    _log(path, _attempt(0, "s1", "Abyssal", "expired", ts=NOW))
    p = SweepPanel()
    p.set_history_path(path)
    p.session.setCurrentIndex(p.session.findData("s1"))
    qapp.processEvents()
    # No monkeypatching: a QMessageBox here would hang the test.
    assert p.confirm_amendment(p._attempt_at(0)) is True


def test_an_old_record_asks_first(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    old = NOW - timedelta(days=3)
    p, _ = _history_panel(
        qapp, tmp_path, rows=_attempt(0, "s1", "Abyssal", "no_reply", ts=old)
    )
    del p.confirm_amendment                      # back to the real one
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: asked.append(a) or QMessageBox.StandardButton.No,
    )
    assert p.confirm_amendment(p._attempt_at(0)) is False
    assert asked and "3 days ago" in asked[0][2]


def test_an_amended_row_says_what_changed(qapp, tmp_path):
    rows = _attempt(0, "s1", "Abyssal", "filled") + [
        {"kind": "amend", "id": "id0", "ts": NOW.isoformat(),
         "units": 1.0, "cost_divines": 9.0, "pay_units": 9.0,
         "expected_profit_divines": -2.8, "lots": 1},
    ]
    p, _ = _history_panel(qapp, tmp_path, rows=rows)
    tip = p.table.item(0, 1).toolTip()
    assert "asked for 2, traded 1" in tip
    assert "listed at 4.8 div, paid 9 div" in tip


def test_a_losing_trade_is_shown_as_a_loss(qapp, tmp_path):
    """It used to read "+-2.80" — or, before the amendment, "+38.00"."""
    rows = _attempt(0, "s1", "Abyssal", "filled") + [
        {"kind": "amend", "id": "id0", "ts": NOW.isoformat(),
         "cost_divines": 9.0, "expected_profit_divines": -2.8},
    ]
    p, _ = _history_panel(qapp, tmp_path, rows=rows)
    assert p.table.item(0, PROFIT_COLUMN).text() == "-2.80"


def test_the_result_editor_offers_the_verdicts_that_are_still_written(qapp, tmp_path):
    from poe2arb.gui.sweep_panel import VerdictDelegate

    p, _ = _history_panel(qapp, tmp_path)
    delegate = p.table.itemDelegateForColumn(SETTLE_COLUMN)
    assert isinstance(delegate, VerdictDelegate)
    index = p.table.model().index(0, SETTLE_COLUMN)
    editor = delegate.createEditor(p.table, None, index)
    offered = [editor.itemText(i) for i in range(editor.count())]
    assert "Traded" in offered and "AFK" in offered
    assert "No Reply" not in offered          # never written any more
    assert "Waiting" not in offered


def test_the_editor_keeps_a_legacy_verdict_it_cannot_offer(qapp, tmp_path):
    """A No Reply row is exactly the row being corrected."""
    from poe2arb.gui.sweep_panel import VerdictDelegate

    p, _ = _history_panel(
        qapp, tmp_path, rows=_attempt(0, "s1", "Abyssal", "no_reply")
    )
    delegate = p.table.itemDelegateForColumn(SETTLE_COLUMN)
    index = p.table.model().index(0, SETTLE_COLUMN)
    editor = delegate.createEditor(p.table, None, index)
    assert editor.itemText(0) == "No Reply"
    delegate.setEditorData(editor, index)
    assert editor.currentText() == "No Reply"


def test_the_verdict_editor_is_not_clipped_by_a_narrow_column(qapp, tmp_path):
    """Caught by screenshot: it opened reading "No Repl" with the arrow on the y."""
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QStyleOptionViewItem

    p, _ = _history_panel(qapp, tmp_path)
    delegate = p.table.itemDelegateForColumn(SETTLE_COLUMN)
    index = p.table.model().index(0, SETTLE_COLUMN)
    editor = delegate.createEditor(p.table, None, index)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 20, 24)          # far narrower than the drop-down
    delegate.updateEditorGeometry(editor, option, index)
    assert editor.width() >= editor.sizeHint().width()


def test_changing_the_settlement_currency_does_not_paint_over_a_verdict(qapp, tmp_path):
    """That column is Settle in on a live row and Result on a history one."""
    p, _ = _history_panel(qapp, tmp_path)
    assert p.table.item(0, SETTLE_COLUMN).text() == "Expired"
    p.set_settlement_currency("exalted")
    qapp.processEvents()
    assert p.table.item(0, SETTLE_COLUMN).text() == "Expired"
    # Still remembered, and applied the moment the live sweep is shown again.
    p.set_result(result_from([listing("omen", 11.0)]))
    p.session.setCurrentIndex(p.session.findData("live"))
    qapp.processEvents()
    assert p.table.item(0, SETTLE_COLUMN).text() == "ex"
