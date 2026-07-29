"""The Trades tab: ranking on screen, filtering, and clipboard behaviour."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2arb.gui.sweep_panel import BAND_COLUMN, PROFIT_COLUMN, SweepPanel  # noqa: E402
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
    assert p.table.item(0, 10).text() == "Real"
    assert p.table.item(1, 10).text() == "Ghost"
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
    seller = p.table.item(0, 10).text()
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
    assert "ghost" in text


def test_status_says_so_when_nothing_plausible_turned_up(qapp):
    """Two live sweeps in a row found only ghosts — the user should be told."""
    p = panel(qapp, result_from([listing("omen", 1.0, char="Ghost", stock=2.0)]))
    assert "nothing in the plausible band" in p.status.text()


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
    assert p.table.item(0, 9).text().endswith("*")


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


def test_a_new_sweep_clears_stale_attempt_state(qapp):
    """Buttons must not stay live against candidates from the previous sweep."""
    from poe2arb.outcomes import Outcome

    p = panel(qapp, result_from([listing("omen", 11.0, char="Real")]))
    p.table.selectRow(0)
    qapp.processEvents()
    p.copy_selected()
    p.note_attempt(p.selected_candidate(), "abc123")
    qapp.processEvents()
    assert p._outcome_btns[Outcome.FILLED].isEnabled()

    p.set_result(result_from([listing("omen", 11.5, char="Fresh")]))
    p.table.selectRow(0)
    qapp.processEvents()
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
