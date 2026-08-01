"""Does the window actually open?

Every panel had tests; the window that assembles them had none, so a startup
crash could ship green. These build the real MainWindow against a throwaway
config directory, with only the two network workers stubbed out.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2arb.config import Config, save_config  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402

from poe2arb.gui import main_window as mw  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    """Build MainWindow in an empty home, without touching the network."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "config"))
    monkeypatch.setattr(mw.MainWindow, "_check_updates", lambda self: None)
    monkeypatch.setattr(mw.MainWindow, "_preload_currencies", lambda self: None)

    built: list[mw.MainWindow] = []

    def build(**overrides):
        cfg = Config(cache_dir=tmp_path / "cache", **overrides)
        path = mw.user_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        save_config(cfg, path)
        w = mw.MainWindow()
        built.append(w)
        return w

    yield build
    for w in built:
        w._quitting = True
        w.close()
        w.deleteLater()
    qapp.processEvents()


def test_a_fresh_install_opens(window):
    w = window()
    assert w.tabs.count() > 0


def test_it_opens_again_with_the_hotkey_enabled(window):
    """The 0.3.0 crash: enabling the hotkey made every later launch fail.

    _setup_hotkey logs from inside _build_central, which runs before the Log
    tab exists. First launch was fine because the hotkey defaults to off, so
    the logging path was never reached until the user turned it on — and then
    the app would not start at all.

    `start_hotkey` is called explicitly because registration no longer happens
    during construction; without it this exercises neither logging path.
    """
    w = window(trade_hotkey_enabled=True, trade_hotkey="ctrl+alt+d")
    w.start_hotkey()
    assert w.tabs.count() > 0


def test_startup_notices_survive_into_the_log(window):
    """Buffered lines must be flushed, not dropped on the floor."""
    w = window(trade_hotkey_enabled=True, trade_hotkey="ctrl+alt+d")
    w.start_hotkey()
    assert w._pending_log == []


def test_building_the_window_does_not_claim_the_hotkey(window, monkeypatch):
    """Constructing is not the same event as deciding to keep this process.

    The updater launches the installed copy and lets this one exit, so an
    upgrade briefly runs two poe2-arb processes. A global hotkey is owned per
    process and Windows gives it to whoever asks first, so registering during
    construction meant the surviving copy was refused with 1409 — the app
    locking itself out of its own hotkey on every update (observed 2026-08-01).
    Registration belongs to `start_hotkey`, which the handover path never runs.
    """
    tried: list[str] = []
    monkeypatch.setattr(
        mw.GlobalHotkey, "register", lambda self, text, **kw: tried.append(text) or True
    )
    # Otherwise `start_hotkey` returns at the platform check and proves nothing.
    monkeypatch.setattr(mw.GlobalHotkey, "supported", property(lambda self: True))
    w = window(trade_hotkey_enabled=True, trade_hotkey="ctrl+alt+d")
    assert tried == []
    w.start_hotkey()
    assert tried == ["ctrl+alt+d"]


def test_logging_before_the_widget_exists_does_not_raise(qapp):
    """_log is called from setup code; it must never be the thing that fails."""
    w = mw.MainWindow.__new__(mw.MainWindow)
    w._pending_log = []
    mw.MainWindow._log(w, "early notice")
    assert w._pending_log == ["early notice"]


# --- the status bar ---------------------------------------------------------

def test_the_budget_readout_starts_blank(window):
    """Nothing is known until a request comes back with the headers."""
    w = window()
    assert w.budget_label.text() == ""


def test_the_budget_readout_shows_what_the_headers_said(window):
    from poe2arb.rate_limit import BudgetState

    w = window()
    w._show_budget(BudgetState(4, 5, 15))
    assert w.budget_label.text() == "4/5 requests per 15s"


def test_a_lockout_is_coloured_differently_from_a_quiet_window(window):
    from poe2arb.rate_limit import BudgetState

    w = window()
    w._show_budget(BudgetState(1, 5, 15))
    quiet = w.budget_label.styleSheet()
    w._show_budget(BudgetState(5, 5, 15, restricted_for_s=1800))
    assert w.budget_label.styleSheet() != quiet


def test_sweep_progress_names_the_item_in_both_places(window):
    w = window()
    w._sweep_progress(14, 69, "Omen of Whittling")
    assert "Omen of Whittling" in w.statusBar().currentMessage()
    assert "Omen of Whittling" in w.sweep.status.text()


def test_book_edges_is_gone(window):
    """Its graph was the disproved triangular search; Quick Lookup replaced it."""
    w = window()
    titles = [w.tabs.tabText(i) for i in range(w.tabs.count())]
    assert "Book Edges" not in titles


# --- bankroll ---------------------------------------------------------------

def test_bankroll_lives_on_the_opportunities_tab(window):
    """It decides the Buy quantity on the rows shown right below it."""
    w = window()
    assert set(w.queue_panel.bankroll.spins) == {"divine", "exalted"}
    assert not hasattr(w.sweep, "bankroll")


def test_saved_bankrolls_are_loaded_per_currency(window):
    w = window(bankroll_divines=40.0, bankroll_exalted=9000.0)
    assert w.queue_panel.bankroll.values() == {"divine": 40.0, "exalted": 9000.0}


def test_editing_one_pot_leaves_the_other_alone(window):
    w = window(bankroll_divines=40.0, bankroll_exalted=9000.0)
    w.queue_panel.bankroll.spins["exalted"].setValue(1234.0)
    assert w.cfg.bankroll_exalted == 1234.0
    assert w.cfg.bankroll_divines == 40.0


def test_loading_values_is_not_mistaken_for_an_edit(window):
    """setValue fires valueChanged; startup must not look like a user edit."""
    w = window()
    seen = []
    w.queue_panel.bankroll.changed.connect(lambda c, v: seen.append(c))
    w.queue_panel.bankroll.set_values({"divine": 10.0, "exalted": 20.0})
    assert seen == []


def test_an_unknown_currency_is_ignored_rather_than_crashing(window):
    w = window()
    w._bankroll_changed("chaos", 5.0)      # no bankroll_chaos field exists


# --- long-shot appetite -----------------------------------------------------

def test_appetite_loads_from_config(window):
    w = window(risk_appetite=0.4)
    assert w.queue_panel.bankroll.appetite_value() == pytest.approx(0.4)


def test_zero_appetite_keeps_ghosts_out_of_the_queue(window):
    w = window(risk_appetite=0.0)
    assert w.trade_queue.queue_ghosts is False


def test_any_appetite_lets_ghosts_into_the_queue(window):
    """Asking to see long shots and then never being offered one is a bug."""
    w = window(risk_appetite=0.2)
    assert w.trade_queue.queue_ghosts is True


def test_moving_the_slider_retakes_effect_immediately(window):
    w = window(risk_appetite=0.0)
    w.queue_panel.bankroll.appetite.setValue(80)
    assert w.cfg.risk_appetite == pytest.approx(0.8)
    assert w.trade_queue.queue_ghosts is True


def test_the_slider_reads_out_in_words_at_the_ends(window):
    w = window()
    bar = w.queue_panel.bankroll
    bar.set_appetite(0.0)
    assert bar.appetite_label.text() == "proven only"
    bar.set_appetite(1.0)
    assert bar.appetite_label.text() == "profit only"


def test_loading_the_appetite_is_not_an_edit(window):
    w = window()
    seen = []
    w.queue_panel.bankroll.appetite_changed.connect(seen.append)
    w.queue_panel.bankroll.set_appetite(0.5)
    assert seen == []


# --- the sweep loop ---------------------------------------------------------

def test_the_triangular_scan_is_gone(window):
    """Scan now / Watch / Stop, the ops table and the Trends tab all went."""
    w = window()
    labels = {a.text() for a in w.findChildren(QAction)}
    assert "Scan now" not in labels
    assert "Watch" not in labels
    for gone in ("ops_table", "trends", "start_scan", "_watch_toggled"):
        assert not hasattr(w, gone), gone


def test_find_trades_is_a_toggle(window):
    w = window()
    assert w.sweep_action.isCheckable()
    assert w.sweep_action.text() == "Find trades"


def test_switching_it_off_stops_the_timer(window, monkeypatch):
    w = window()
    monkeypatch.setattr(w, "start_sweep", lambda: None)   # no network in tests
    w.sweep_action.setChecked(True)
    w.sweep_action.setChecked(False)
    assert not w.sweep_timer.isActive()
    assert w._next_sweep_at is None


def test_a_finished_sweep_schedules_the_next_one(window):
    """That's what makes it continuous rather than a one-shot button."""
    w = window(sweep_interval_minutes=5.0)
    w.sweep_action.blockSignals(True)
    w.sweep_action.setChecked(True)
    w.sweep_action.blockSignals(False)
    w._schedule_next_sweep()
    assert w.sweep_timer.isActive()
    assert w._next_sweep_at is not None


def test_nothing_is_scheduled_while_the_toggle_is_off(window):
    w = window()
    w._schedule_next_sweep()
    assert not w.sweep_timer.isActive()


def test_the_countdown_reports_the_wait(window):
    import time

    w = window()
    w._next_sweep_at = time.monotonic() + 125
    w._tick_countdown()
    assert "2:0" in w.statusBar().currentMessage()


# --- settlement currency ----------------------------------------------------

def test_settlement_lives_on_the_opportunities_tab(window):
    w = window(sale_currency="divine")
    assert w.queue_panel.bankroll.settlement_currency() == "divine"


def test_changing_settlement_updates_the_config(window):
    w = window(sale_currency="exalted")
    w.queue_panel.bankroll.settlement.setCurrentText("divine")
    assert w.cfg.sale_currency == "divine"


def test_loading_settlement_is_not_an_edit(window):
    w = window()
    seen = []
    w.queue_panel.bankroll.settlement_changed.connect(seen.append)
    w.queue_panel.bankroll.set_settlement("divine")
    assert seen == []


# --- the Results tab --------------------------------------------------------

def test_results_reads_the_outcome_log(window, tmp_path):
    w = window()
    assert w.results._path == w.cfg.outcomes_path


# --- Currency Exchange pricing ---------------------------------------------

def universe_with(items):
    from datetime import datetime, timezone

    from poe2arb.market import Item, Universe

    return Universe(
        league="T", fetched_at=datetime.now(timezone.utc),
        items={i: Item(i, name, "Currency", value, 10.0)
               for i, (name, value) in items.items()},
    )


UNI = {"divine": ("Divine Orb", 1.0), "chaos": ("Chaos Orb", 0.114)}


def test_ce_prices_are_applied_over_the_catalogue(window):
    w = window()
    w._universe_loaded(universe_with(UNI))
    w._ce_prices_loaded({"chaos": 0.2})
    assert w._universe.get("chaos").value_divine == 0.2
    assert w._universe.ce_priced == frozenset({"chaos"})


def test_the_market_tab_is_repriced_too(window):
    # Divine, not adaptive: adaptive shows chaos in chaos, i.e. always "1.00".
    w = window(base_currency="divine")
    w._universe_loaded(universe_with(UNI))
    w._ce_prices_loaded({"chaos": 0.2})
    values = {
        w.market.table.item(r, 0).text(): w.market.table.item(r, 1).text()
        for r in range(w.market.table.rowCount())
    }
    assert "0.20" in values["Chaos Orb"]


def test_a_poe2scout_outage_leaves_the_app_working(window):
    """The catalogue is already on screen by then; this only improves it."""
    w = window()
    w._universe_loaded(universe_with(UNI))
    w._ce_prices_loaded({})
    assert w._universe.get("chaos").value_divine == 0.114
    assert w.market.table.rowCount() == 2


def test_ce_prices_arriving_before_the_catalogue_are_ignored(window):
    w = window()
    w._ce_prices_loaded({"chaos": 0.2})       # must not raise
    assert w._universe is None


def test_the_status_line_reports_both_sources(window):
    w = window()
    w._universe_loaded(universe_with(UNI))
    w._ce_prices_loaded({"chaos": 0.2})
    assert "Currency Exchange" in w.market.status.text()
    assert "poe.ninja" in w.market.status.text()


# --- the hotkey acts on something whenever something is takeable ------------

def _queued(window, *, chars=("A",), stock=1.0):
    """A window with real candidates in its queue, offered and listed."""
    from datetime import datetime, timedelta, timezone

    from poe2arb.listings import Listing, build_candidates

    t0 = datetime.now(timezone.utc)
    cands = []
    for n, char in enumerate(chars):
        listing = Listing(
            item_id="omen", account=f"{char}#1", character=char,
            pay_amount=11.0 - n * 0.5, get_amount=1.0, stock=stock, indexed=t0,
            whisper=f"@{char} buy {{0}} for {{1}}",
            item_whisper="{0} Thing", pay_whisper="{0} Coin",
        )
        cands += build_candidates(
            [listing], {"omen": 12.0, "divine": 1.0}, {"omen": "Omen of Light"},
            min_gap=1.05, max_gap=1.5, sale_unit_divines=0.0023,
        )
    window.trade_queue.submit(cands, t0)
    window.trade_queue.tick(t0)
    return t0


def test_the_hotkey_takes_the_live_offer(window):
    w = window()
    _queued(w)
    live = w.trade_queue.offered
    w._hotkey_pressed()
    assert live.attempt_id is not None
    assert w.trade_queue.awaiting == [live]


def test_the_hotkey_falls_back_to_the_oldest_ready_trade(window):
    """The alert window is seconds and the listed window is minutes.

    Most of the time nothing is live, and the key used to do nothing at all
    while the panel was full of perfectly takeable rows.
    """
    from datetime import timedelta

    w = window()
    t0 = _queued(w, chars=("A",))
    w.trade_queue.tick(t0 + timedelta(seconds=w.cfg.offer_window_s + 1))
    assert w.trade_queue.offered is None
    [ready] = w.trade_queue.available

    w._hotkey_pressed()
    assert w.trade_queue.awaiting == [ready]


def test_the_hotkey_says_so_when_there_is_nothing_to_take(window):
    w = window()
    w._hotkey_pressed()
    assert "nothing" in w.statusBar().currentMessage().lower() or \
        "no trade" in w.statusBar().currentMessage().lower()


# --- what the queue does reaches the Trades tab -----------------------------

def test_a_whisper_taken_from_the_queue_shows_under_ones_i_messaged(window):
    """Almost every whisper comes from the queue, not from the Trades table.

    Unwired, both history filters read as permanently empty.
    """
    from poe2arb.gui.sweep_panel import SHOW_WHISPERED

    w = window()
    _queued(w)
    live = w.trade_queue.offered
    w._queue_take(live.id)
    assert live.candidate.key in w.sweep._attempt_ids
    assert w.sweep._matches_mode(live.candidate, SHOW_WHISPERED)


def test_a_trade_marked_as_bought_shows_under_ones_i_bought(window):
    from poe2arb.gui.sweep_panel import SHOW_BOUGHT
    from poe2arb.outcomes import Outcome

    w = window()
    _queued(w)
    live = w.trade_queue.offered
    candidate = live.candidate
    w._queue_take(live.id)
    w._queue_outcome(live.id, Outcome.FILLED)
    assert w.sweep._outcomes[candidate.key] is Outcome.FILLED
    assert w.sweep._matches_mode(candidate, SHOW_BOUGHT)


def test_declining_stops_a_later_sweep_re_offering_it(window):
    w = window()
    t0 = _queued(w)
    live = w.trade_queue.offered
    candidate = live.candidate
    w._queue_dismiss(live.id)
    assert w.trade_queue.submit([candidate], t0) == 0


# --- neither pane of the Opportunities tab can be lost ----------------------

def test_the_opportunities_panes_cannot_be_collapsed(window):
    """A collapsed pane is saved, so a stray drag survived restarts with
    nothing on screen to explain it but a handle jammed against the edge."""
    w = window()
    assert not w.ops_split.childrenCollapsible()
    assert not w.queue_panel.split.childrenCollapsible()


def test_a_saved_collapsed_split_is_not_restored(window, tmp_path):
    from poe2arb.gui.ui_state import save_ui_state, ui_state_path

    cache = tmp_path / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    save_ui_state(ui_state_path(cache), {"ops_split": [0, 476]})
    w = window()
    assert min(w.ops_split.sizes()) > 0


# --- sessions ---------------------------------------------------------------

def test_a_session_starts_with_find_trades_and_stamps_every_whisper(window, monkeypatch):
    from poe2arb.outcomes import read_attempts

    w = window()
    monkeypatch.setattr(w, "start_sweep", lambda: None)
    w.sweep_action.setChecked(True)
    assert w.session.active
    session_id = w.session.id

    _queued(w, chars=("A",))
    w._queue_take(w.trade_queue.offered.id)
    [logged] = read_attempts(w.cfg.outcomes_path)
    assert logged.session_id == session_id


def test_the_session_outlives_the_queue_while_still_looking(window, monkeypatch):
    """Between sweeps the queue is routinely empty; that is not the end."""
    w = window()
    monkeypatch.setattr(w, "start_sweep", lambda: None)
    w.sweep_action.setChecked(True)
    started = w.session.id
    w._queue_tick()
    assert w.session.id == started


def test_it_ends_once_nothing_is_running_and_nothing_is_left(window, monkeypatch):
    w = window()
    monkeypatch.setattr(w, "start_sweep", lambda: None)
    w.sweep_action.setChecked(True)
    started = w.session.id
    _queued(w, chars=("A",))

    w.sweep_action.setChecked(False)
    w._queue_tick()
    assert w.session.id == started        # a trade is still on offer

    w._queue_dismiss(w.trade_queue.offered.id)
    w._queue_tick()
    assert not w.session.active

    monkeypatch.setattr(w, "start_sweep", lambda: None)
    w.sweep_action.setChecked(True)
    assert w.session.id != started


# --- opportunities arrive as they are found ---------------------------------

def test_candidates_are_queued_before_the_sweep_finishes(window, monkeypatch):
    """It used to be silent for fifteen minutes and then flood the queue."""
    w = window()
    monkeypatch.setattr(w, "start_sweep", lambda: None)
    w.sweep_action.setChecked(True)
    t0 = _queued(w, chars=())          # nothing queued, just a timestamp
    from poe2arb.listings import Listing, build_candidates

    listing = Listing(
        item_id="omen", account="Streamer#1", character="Streamer",
        pay_amount=11.0, get_amount=1.0, stock=1.0, indexed=t0,
        whisper="@Streamer buy {0} for {1}",
        item_whisper="{0} Thing", pay_whisper="{0} Coin",
    )
    cands = build_candidates(
        [listing], {"omen": 12.0, "divine": 1.0}, {"omen": "Omen of Light"},
        min_gap=1.05, max_gap=1.5, sale_unit_divines=0.0023,
    )
    w._candidates_found(cands)
    assert w.trade_queue.outstanding == 1


def test_nothing_is_queued_while_the_toggle_is_off(window):
    from poe2arb.listings import Listing, build_candidates

    w = window()
    listing = Listing(
        item_id="omen", account="Streamer#1", character="Streamer",
        pay_amount=11.0, get_amount=1.0, stock=1.0,
        whisper="@Streamer buy {0} for {1}",
        item_whisper="{0} Thing", pay_whisper="{0} Coin",
    )
    w._candidates_found(build_candidates(
        [listing], {"omen": 12.0, "divine": 1.0}, {"omen": "Omen of Light"},
        min_gap=1.05, max_gap=1.5, sale_unit_divines=0.0023,
    ))
    assert w.trade_queue.outstanding == 0


# --- correcting a trade after the fact --------------------------------------

def test_revising_a_trade_rewrites_the_logged_quantity(window):
    """Whispered for 18, the seller had 3 (reported from the field 2026-07-31)."""
    from poe2arb.outcomes import read_attempts

    w = window()
    _queued(w, chars=("A",), stock=18.0)
    live = w.trade_queue.offered
    w._queue_take(live.id)
    assert live.candidate.plan.units == 18.0

    w._queue_revise(live.id, 3.0)
    [logged] = read_attempts(w.cfg.outcomes_path)
    assert logged.units == 3.0
    assert logged.asked_units == 18.0
    assert logged.amended is True
    assert w.trade_queue.get(live.id).candidate.plan.units == 3.0


def test_a_counteroffered_price_reaches_the_log(window):
    """Measured 1 fill in 36 (2026-08-01); the one that happened logged +38.00
    divines on a trade that lost money, because price had nowhere to go."""
    from poe2arb.outcomes import read_attempts

    w = window()
    _queued(w, chars=("A",), stock=18.0)
    live = w.trade_queue.offered
    w._queue_take(live.id)

    w._queue_revise(live.id, 18.0, 260.0)
    [logged] = read_attempts(w.cfg.outcomes_path)
    assert logged.units == 18.0                  # quantity untouched
    assert logged.cost_divines == 260.0
    assert logged.asked_cost_divines == 198.0    # the original ask survives
    assert logged.expected_profit_divines < 0    # the log can now say it lost


def test_the_trades_tab_corrects_a_verdict_the_timer_got_wrong(window):
    """The route back to a row the queue can no longer reach."""
    from poe2arb.outcomes import Outcome, read_attempts
    from poe2arb.gui.sweep_panel import SETTLE_COLUMN

    w = window()
    _queued(w, chars=("A",), stock=1.0)
    live = w.trade_queue.offered
    w._queue_take(live.id)
    w._queue_outcome(live.id, Outcome.EXPIRED)

    w.sweep.confirm_amendment = lambda _a: True
    w.sweep.session.setCurrentIndex(w.sweep.session.findData("all"))
    w.sweep.reload_history()
    QApplication.processEvents()
    assert w.sweep.table.rowCount() == 1
    w.sweep.table.item(0, SETTLE_COLUMN).setText("Traded")
    QApplication.processEvents()

    [logged] = read_attempts(w.cfg.outcomes_path)
    assert logged.outcome is Outcome.FILLED


def test_the_trades_tab_amends_a_quantity_in_the_log(window):
    from poe2arb.outcomes import Outcome, read_attempts
    from poe2arb.gui.sweep_panel import AMOUNT_COLUMN

    w = window()
    _queued(w, chars=("A",), stock=18.0)
    live = w.trade_queue.offered
    w._queue_take(live.id)
    w._queue_outcome(live.id, Outcome.FILLED)

    w.sweep.confirm_amendment = lambda _a: True
    w.sweep.session.setCurrentIndex(w.sweep.session.findData("all"))
    w.sweep.reload_history()
    QApplication.processEvents()
    w.sweep.table.item(0, AMOUNT_COLUMN).setText("3")
    QApplication.processEvents()

    [logged] = read_attempts(w.cfg.outcomes_path)
    assert logged.units == 3.0
    assert logged.asked_units == 18.0
    assert logged.cost_divines == pytest.approx(33.0)
    assert logged.outcome is Outcome.FILLED      # the verdict is not disturbed
