"""The Trades tab: ranking on screen, filtering, and clipboard behaviour."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2arb.gui.sweep_panel import (  # noqa: E402
    AGE_COLUMN,
    BAND_COLUMN,
    PROFIT_COLUMN,
    SELLER_COLUMN,
    SweepPanel,
)
from poe2arb.listings import (  # noqa: E402
    Band,
    Listing,
    build_candidates,
    rank_candidates,
)
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
    from PySide6.QtCore import Qt

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
