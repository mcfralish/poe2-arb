"""Main window: opportunity table, market view, watch loop, tray notifications."""

from __future__ import annotations

import logging
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QComboBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import (
    Config,
    load_config,
    migrate_legacy_cache,
    save_config,
    user_config_path,
)
from ..format import fmt_depth, fmt_pct, fmt_skew
from ..market import BASE_CURRENCY_CHOICES, Universe
from ..rate_limit import Severity, check_pacing, min_safe_interval, worst_severity
from ..trade_queue import TradeQueue
from .icon import make_app_icon
from .icon_provider import IconProvider
from .settings_dialog import SettingsDialog
from .table_items import NumericItem, TextItem
from .theme import banner_style, budget_style
from .ui_state import (
    decode_geometry,
    encode_geometry,
    load_ui_state,
    save_ui_state,
    ui_state_path,
)
from .updates import RELEASES_PAGE
from .lookup import QuickLookup
from .market_panel import MarketPanel
from .results import ResultsTab
from .hotkey import GlobalHotkey, format_hotkey
from .queue_panel import QueuePanel
from .sweep_panel import SweepPanel
from .worker import (
    RecheckWorker,
    SweepWorker,
    UniverseWorker,
    UpdateCheckWorker,
    stop_thread,
)


log = logging.getLogger(__name__)

# How far back the log and tables are repopulated on launch.
BACKLOAD_HOURS = 8.0

# How recent the last saved scan must be for its opportunities to count as
# "already announced" — see _carry_forward_alerts.
ALERT_MEMORY_HOURS = 1.0


class Column(NamedTuple):
    title: str
    tooltip: str


def _play_alert_sound() -> None:
    if sys.platform == "win32":
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_ICONASTERISK)
            return
        except Exception:
            pass
    QApplication.beep()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"poe2-arb {__version__} — PoE2 arbitrage watch (analysis only)")
        # Wide enough for the Market tab bar to show all 15 tabs without
        # scrolling, and no wider — the columns size to their content, so extra
        # width buys nothing but dead space.
        self.resize(900, 620)
        self.setMinimumSize(700, 400)
        self.setWindowIcon(make_app_icon())

        # Startup notices collected before the log widget exists.
        self._pending_log: list[str] = []
        self.cfg = self._load_cfg()
        self._sweep_worker: SweepWorker | None = None
        self._next_sweep_at: float | None = None
        # id -> display name from the last scan, so Settings can accept
        # in-game currency names and flag typos.
        self._known_currencies: dict[str, str] = {}
        self._currency_values: dict[str, float] = {}
        self._universe: Universe | None = None
        # poe.ninja's league list and what auto-detect resolved to, for the
        # Settings dropdown. Empty until the preload lands.
        self._leagues: list[str] = []
        self._detected_league: str | None = None
        # Kept so the long-shots slider can re-rank without another sweep.
        self._last_sweep = None
        self._quitting = False

        self.trade_queue = TradeQueue(
            offer_window_s=self.cfg.offer_window_s,
            available_ttl_s=self.cfg.available_ttl_s,
            awaiting_timeout_s=self.cfg.awaiting_timeout_s,
            # Any appetite above zero means the user asked to see long shots,
            # so they have to be allowed into the queue to be offered at all.
            queue_ghosts=self.cfg.risk_appetite > 0.0,
        )

        self.icons = IconProvider(self.cfg.cache_dir, self)
        # One repaint per batch of arrivals rather than per icon: a table of 600
        # rows would otherwise re-render 600 times as the fetches land.
        self._icon_refresh = QTimer(self)
        self._icon_refresh.setSingleShot(True)
        self._icon_refresh.setInterval(400)
        self._icon_refresh.timeout.connect(self._reapply_view_settings)
        self.icons.ready.connect(lambda _: self._icon_refresh.start())

        # Timers first: _build_central wires widgets that reference them.
        self._build_timers()
        self._build_toolbar()
        self._build_status_bar()
        self._build_central()
        self._restore_ui_state()
        for line in self._pending_log:
            self._log(line)
        self._pending_log.clear()
        self._build_tray()
        self._check_updates()
        self._preload_currencies()

        if not self.statusBar().currentMessage():
            self.statusBar().showMessage(
                "Ready — press Find trades to start looking"
            )

    # ------------------------------------------------------------------ setup

    def _load_cfg(self) -> Config:
        moved = migrate_legacy_cache()
        if moved is not None:
            self._pending_log.append(f"moved cached data to {moved}")
        path = user_config_path()
        try:
            if path.exists():
                cfg = load_config(path)
                self._warn_if_unsafe_pacing(cfg)
                return cfg
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Config", f"Could not read {path}:\n{e}\nUsing defaults.")
        return Config()

    def _warn_if_unsafe_pacing(self, cfg: Config) -> None:
        """A config written by an older version can hold unsafe pacing."""
        issues = check_pacing(
            cfg.request_interval_s, safety_fraction=cfg.rate_limit_safety_fraction
        )
        if worst_severity(issues) is not Severity.ERROR:
            return
        safe = min_safe_interval(safety_fraction=cfg.rate_limit_safety_fraction)
        self._pending_log.append(
            f"saved request spacing of {cfg.request_interval_s:g}s risks a rate-limit "
            f"ban; raised to {safe:g}s (change it in Settings)"
        )
        cfg.request_interval_s = safe

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        # One toggle, not a button and a checkbox. A sweep takes minutes and
        # the listings it finds go stale in minutes, so the useful mode is
        # "keep looking" — a one-shot run is just this switched off again.
        self.sweep_action = QAction("Find trades", self)
        self.sweep_action.setCheckable(True)
        self.sweep_action.setToolTip(
            "Keep checking live listings against Currency Exchange prices.\n"
            "Runs a sweep now and another every few minutes until switched off.\n"
            "Anything worth acting on appears on the Opportunities tab."
        )
        self.sweep_action.toggled.connect(self._sweep_toggled)
        tb.addAction(self.sweep_action)

        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.open_settings)
        tb.addAction(settings_action)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        tb.addWidget(QLabel("Show prices in "))
        self.base_currency_box = QComboBox()
        for cid, label in BASE_CURRENCY_CHOICES:
            self.base_currency_box.addItem(label, cid)
        index = self.base_currency_box.findData(self.cfg.base_currency)
        self.base_currency_box.setCurrentIndex(max(0, index))
        self.base_currency_box.setToolTip(
            "The currency every price in the app is shown in.\n"
            "Display only — the maths always works in Divine Orbs."
        )
        self.base_currency_box.currentIndexChanged.connect(self._base_currency_changed)
        tb.addWidget(self.base_currency_box)

    def _build_central(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)

        self.update_banner = QWidget()
        banner_layout = QHBoxLayout(self.update_banner)
        banner_layout.setContentsMargins(8, 4, 8, 4)
        self.update_label = QLabel()
        banner_layout.addWidget(self.update_label, stretch=1)
        get_btn = QPushButton("Download")
        get_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._update_url)))
        banner_layout.addWidget(get_btn)
        self.update_banner.setStyleSheet(banner_style(self))
        self.update_banner.hide()
        self._update_url = RELEASES_PAGE
        layout.addWidget(self.update_banner)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.queue_panel = QueuePanel()
        self.queue_panel.set_icons(self.icons)
        self.queue_panel.bankroll.set_values({
            "divine": self.cfg.bankroll_divines,
            "exalted": self.cfg.bankroll_exalted,
        })
        self.queue_panel.bankroll.changed.connect(self._bankroll_changed)
        self.queue_panel.bankroll.set_appetite(self.cfg.risk_appetite)
        self.queue_panel.bankroll.set_settlement(self.cfg.sale_currency)
        self.queue_panel.bankroll.settlement_changed.connect(self._settlement_changed)
        self.queue_panel.bankroll.appetite_changed.connect(self._appetite_changed)
        self.queue_panel.take_requested.connect(self._queue_take)
        self.queue_panel.outcome_reported.connect(self._queue_outcome)
        self.queue_panel.dismiss_requested.connect(self._queue_dismiss)
        self.lookup = QuickLookup()
        self.ops_split = QSplitter(Qt.Orientation.Vertical)
        self.ops_split.addWidget(self.queue_panel)
        self.ops_split.addWidget(self.lookup)
        # The queues take every spare pixel; Quick Lookup is a fixed-height
        # lookup and gains nothing from being taller.
        self.ops_split.setStretchFactor(0, 1)
        self.ops_split.setStretchFactor(1, 0)
        # Stretch factors alone don't decide the *initial* split — a QSplitter
        # starts from each child's sizeHint, and Quick Lookup's was big enough to
        # claim about half the tab. The queues are the point of this tab, so give
        # them the lion's share outright; the splitter is still draggable.
        self.ops_split.setSizes([680, 140])
        self.ops_split.setCollapsible(1, True)
        self.tabs.addTab(self.ops_split, "Opportunities")

        self.market = MarketPanel()
        self.market.set_exclusions(self.cfg.exclude_currencies)
        self.market.set_base_currency(self.cfg.base_currency)
        self.market.set_icons(self.icons)
        self.market.exclusions_changed.connect(self._exclusions_changed)
        self.tabs.addTab(self.market, "Market")

        self.sweep = SweepPanel()
        self.sweep.set_icons(self.icons)
        self.sweep.attempt_copied.connect(self._attempt_copied)
        self.sweep.recheck_requested.connect(self._recheck)
        self._setup_hotkey()
        self.sweep.outcome_reported.connect(self._outcome_reported)
        self.tabs.addTab(self.sweep, "Trades")

        # Book Edges is gone. It was a raw dump of the triangular search's
        # graph — every pay/receive edge with its depth — and that search is
        # the thing 0.3.0 established was pointed at the wrong market. Quick
        # Lookup answers "what is this pair trading at" without the dump.

        self.results = ResultsTab()
        self.tabs.addTab(self.results, "Results")

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.tabs.addTab(self._log_tab(), "Log")

        self.results.set_path(self.cfg.outcomes_path)

        self.setCentralWidget(central)

    def _log_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.addStretch(1)
        clear = QPushButton("Clear")
        clear.setToolTip("Empty the log view. Saved scan history is untouched.")
        clear.clicked.connect(self.log_view.clear)
        tools.addWidget(clear)
        export = QPushButton("Save to file…")
        export.setToolTip("Write everything shown here to a text file.")
        export.clicked.connect(self._export_log)
        tools.addWidget(export)
        layout.addLayout(tools)
        layout.addWidget(self.log_view)
        return page

    def _export_log(self) -> None:
        default = f"poe2-arb-log-{datetime.now().strftime('%Y%m%d-%H%M')}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save log", str(Path.home() / default), "Text files (*.txt)"
        )
        if not path:
            return
        try:
            Path(path).write_text(self.log_view.toPlainText(), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "Save log", f"Could not write {path}:\n{e}")
            return
        self._log(f"log saved to {path}")

    @staticmethod
    def _make_table(columns: list[Column], sort_column: int = 0,
                    sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> QTableWidget:
        """Table whose first column absorbs slack and whose numbers stay compact."""
        t = QTableWidget(0, len(columns))
        t.setHorizontalHeaderLabels([c.title for c in columns])
        header = t.horizontalHeader()
        # Stretching the *last* column made the rightmost cell absurdly wide;
        # the name/route column is the one that benefits from extra room.
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(columns)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        for i, col in enumerate(columns):
            item = t.horizontalHeaderItem(i)
            item.setToolTip(col.tooltip)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSortingEnabled(True)
        t.setAlternatingRowColors(True)
        t.verticalHeader().hide()
        # Without an explicit default Qt sorts by column 0, which buries the
        # interesting rows (biggest profit, most valuable) at the bottom.
        t.sortByColumn(sort_column, sort_order)
        return t

    def _base_currency_changed(self) -> None:
        """Switch display currency from the toolbar, everywhere at once."""
        # Some platforms (WSLg in particular) leave the popup open after a
        # click, so it needs dismissing explicitly rather than relying on the
        # combo box to close itself.
        self.base_currency_box.hidePopup()
        chosen = self.base_currency_box.currentData()
        if not chosen or chosen == self.cfg.base_currency:
            return
        self.cfg.base_currency = chosen
        self.market.set_base_currency(chosen)
        self._reapply_view_settings()
        self.lookup.set_base_currency(chosen)
        try:
            save_config(self.cfg, user_config_path())
        except OSError:
            log.warning("could not save base currency", exc_info=True)
        self._log(f"showing prices in {self._universe.name(chosen) if self._universe else chosen}")

    def _build_status_bar(self) -> None:
        """A permanent budget readout in the opposite corner from the progress.

        GGG reports the IP's usage on every reply, and the IP is shared with
        anything else the player runs against the trade API — so this is the
        only honest answer to "am I about to get locked out for 30 minutes".
        """
        self.budget_label = QLabel()
        self.budget_label.setToolTip(
            "Requests this IP has spent in the tightest rate-limit window, as "
            "reported by GGG. Counts every trade tool you're running, not just "
            "this one. Goes red once the window is nearly spent."
        )
        self.statusBar().addPermanentWidget(self.budget_label)
        self._show_budget(None)

    def _show_budget(self, budget) -> None:
        if budget is None:
            self.budget_label.clear()
            return
        self.budget_label.setText(budget.label)
        self.budget_label.setStyleSheet(budget_style(self, budget))

    def _build_tray(self) -> None:
        # No tray on some Linux desktops and under WSLg (no StatusNotifierWatcher).
        # Hiding to a tray that doesn't exist strands the window with no way to
        # restore or quit it, so every tray path is guarded by this flag.
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        if not self.tray_available:
            self.tray = None
            self._log(
                "note: no system tray on this desktop — closing the window will quit "
                "the app instead of watching in the background"
            )
            return
        self.tray = QSystemTrayIcon(make_app_icon(), self)
        menu_show = QAction("Show window", self)
        menu_show.triggered.connect(self._show_from_tray)
        menu_quit = QAction("Quit", self)
        menu_quit.triggered.connect(self._quit)
        from PySide6.QtWidgets import QMenu

        menu = QMenu()
        menu.addAction(menu_show)
        menu.addSeparator()
        menu.addAction(menu_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._show_from_tray()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        self.tray.setToolTip("poe2-arb")
        self.tray.show()

    def _build_timers(self) -> None:
        # Waits out the gap between sweeps while "Find trades" is on.
        self.sweep_timer = QTimer(self)
        self.sweep_timer.setSingleShot(True)
        self.sweep_timer.timeout.connect(self.start_sweep)

        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(1000)
        self.countdown_timer.timeout.connect(self._tick_countdown)
        self.countdown_timer.start()

        # Drives the offer countdown and promotes the next trade when one lapses.
        self.queue_timer = QTimer(self)
        self.queue_timer.setInterval(1000)
        self.queue_timer.timeout.connect(self._queue_tick)
        self.queue_timer.start()

        # Coalesces a run of spin-box steps into one config write.
        self._bankroll_save_timer = QTimer(self)
        self._bankroll_save_timer.setSingleShot(True)
        self._bankroll_save_timer.setInterval(1500)
        self._bankroll_save_timer.timeout.connect(self._persist_bankroll)

    def _preload_currencies(self) -> None:
        """Populate the currency list before any scan has run.

        Settings' exclusion list would otherwise be empty on a fresh install,
        with no way to pick anything until a multi-minute scan finished.
        """
        self._currency_worker = UniverseWorker(self.cfg, self)
        self._currency_worker.loaded.connect(self._universe_loaded)
        self._currency_worker.ce_loaded.connect(self._ce_prices_loaded)
        self._currency_worker.leagues_loaded.connect(self._leagues_loaded)
        self._currency_worker.start()

    def _leagues_loaded(self, leagues: list, detected: str) -> None:
        """Remember the league list so Settings can offer it as a dropdown."""
        self._leagues = list(leagues)
        self._detected_league = detected
        if not self.cfg.league:
            self._log(f"league auto-detected as {detected}")

    def _ce_prices_loaded(self, ce: dict) -> None:
        """Re-price the catalogue from the Currency Exchange where it can.

        Arrives after the universe, so everything is already on screen with
        poe.ninja's consensus and this only improves it. An empty dict means
        poe2scout was unreachable, which costs the better prices and nothing
        else.
        """
        if self._universe is None:
            return
        if not ce:
            self._log("Currency Exchange prices unavailable — using poe.ninja")
            return
        self._universe = self._universe.with_ce_prices(ce)
        priced = len(self._universe.ce_priced)
        self._log(
            f"{priced} of {len(self._universe)} items priced from the Currency "
            f"Exchange; the rest from poe.ninja"
        )
        self._push_universe()

    def _universe_loaded(self, universe: Universe) -> None:
        """Full economy data arrived: feed the pickers and the lookup tool."""
        self._universe = universe
        self.icons.set_images(universe.images())
        self.lookup.set_icons(self.icons)
        self._log(
            f"loaded {len(universe)} items across "
            f"{len(universe.by_category())} categories from poe.ninja"
        )
        self._push_universe()

    def _push_universe(self) -> None:
        """Hand the current catalogue to everything that displays prices."""
        universe = self._universe
        if universe is None:
            return
        self.market.set_universe(universe)
        self.lookup.set_universe(universe)
        self.lookup.set_base_currency(self.cfg.base_currency)
        self._known_currencies = universe.names()
        self._currency_values = universe.values()
        self._render_market()

    def _render_market(self) -> None:
        """Fill the Market tab from the economy snapshot.

        poe.ninja is now the only source. The scan used to overlay its own
        order-book figures for the handful of currencies it fetched; with that
        gone the universe is simply the whole picture.
        """
        if self._universe is None:
            return
        self.market.render(
            names=self._universe.names(),
            values=self._universe.values(),
            volumes={
                i.id: i.volume_divine for i in self._universe.items.values()
            },
        )

    def _check_updates(self) -> None:
        self._update_worker = UpdateCheckWorker(__version__, self)
        self._update_worker.update_available.connect(self._show_update_banner)
        self._update_worker.start()

    # ------------------------------------------------------------------ scanning

    def start_sweep(self) -> None:
        """Run one cross-venue sweep. A second request while one runs is ignored."""
        if self._sweep_worker is not None and self._sweep_worker.isRunning():
            return
        self.sweep_timer.stop()
        self.sweep.set_running(True)
        self.sweep.set_status("Checking Currency Exchange prices…")
        self._log("cross-venue sweep started")
        self._sweep_worker = SweepWorker(self.cfg, self)
        self._sweep_worker.progress.connect(self._sweep_progress)
        self._sweep_worker.budget.connect(self._show_budget)
        self._sweep_worker.finished_ok.connect(self._sweep_done)
        self._sweep_worker.failed.connect(self._sweep_failed)
        self._sweep_worker.finished.connect(self._sweep_thread_finished)
        self._sweep_worker.start()

    def stop_sweep(self) -> None:
        """Switch the toggle off, which cancels anything in flight."""
        self.sweep_action.setChecked(False)

    def _sweep_toggled(self, on: bool) -> None:
        if on:
            self._log("looking for trades")
            self.start_sweep()
            return
        self.sweep_timer.stop()
        self._next_sweep_at = None
        # Stop means stop. The backlog would otherwise keep surfacing offers for
        # minutes, since `tick` promotes one every offer window regardless of
        # whether anything is still sweeping. Already-offered and awaiting rows
        # survive — see TradeQueue.cancel_pending.
        dropped = self.trade_queue.cancel_pending()
        if dropped:
            self._log(f"dropped {dropped} queued trade(s) not yet offered")
        self.queue_panel.refresh(self.trade_queue)
        if self._sweep_worker is not None and self._sweep_worker.isRunning():
            self._sweep_worker.cancel()
            self.sweep.set_status("Stopping…")
            self._log("stopping sweep…")
        else:
            self._log("stopped looking for trades")
            self.statusBar().showMessage("Stopped")

    def _schedule_next_sweep(self) -> None:
        """Wait out the gap, then sweep again.

        The gap exists because listings churn slower than a sweep runs, and
        because back-to-back sweeps would spend the whole rate-limit budget on
        re-reading the same listings.
        """
        if not self.sweep_action.isChecked():
            return
        interval_ms = int(self.cfg.sweep_interval_minutes * 60_000)
        self.sweep_timer.start(interval_ms)
        self._next_sweep_at = time.monotonic() + interval_ms / 1000

    def _tick_countdown(self) -> None:
        """Count down to the next sweep in the status bar."""
        if self._next_sweep_at is None:
            return
        if self._sweep_worker is not None and self._sweep_worker.isRunning():
            return
        remaining = int(self._next_sweep_at - time.monotonic())
        if remaining < 0:
            return
        mins, secs = divmod(remaining, 60)
        self.statusBar().showMessage(f"Next sweep in {mins}:{secs:02d}")

    def _sweep_progress(self, done: int, total: int, item: str) -> None:
        """Name the item being fetched, on the tab and in the status bar.

        A sweep is minutes of waiting on paced requests. "item 14 of 69" says
        nothing about whether it is stuck; the item's name does.
        """
        message = f"Checking {item} — {done} of {total}"
        self.sweep.set_status(message)
        self.statusBar().showMessage(message)

    def _sweep_thread_finished(self) -> None:
        """Runs on every exit path, including cancellation, which emits no result."""
        self.sweep.set_running(False)
        if self._sweep_worker is not None and self._sweep_worker.was_cancelled:
            self.sweep.set_status("Sweep stopped.")
            self._log("sweep stopped")
            self.statusBar().showMessage("Stopped")
            return
        self._schedule_next_sweep()

    def _sweep_done(self, result) -> None:
        self._last_sweep = result
        # Set before the table is filled, and from the value this sweep actually
        # used. Updating it when the dropdown changes would label the rows with a
        # currency their Profit figures were never computed against.
        self.sweep.set_settlement_currency(self.cfg.sale_currency)
        self.sweep.set_result(result, risk_appetite=self.cfg.risk_appetite)
        # A sweep that lands in the same instant the toggle went off must not
        # refill the queue we just cancelled. The Trades tab still shows what it
        # found — stopping suppresses interruptions, not information.
        if not self.sweep_action.isChecked():
            self._log(
                f"sweep finished after stop — {len(result.candidates)} candidate(s) "
                "shown in Trades, none queued"
            )
            self._queue_tick()
            return
        added = self.trade_queue.submit(result.candidates)
        if added:
            self._log(f"{added} new trade(s) queued")
        self._queue_tick()
        plausible = sum(1 for c in result.candidates if c.band.name == "PLAUSIBLE")
        self._log(
            f"sweep complete — {result.listings_seen} listings across "
            f"{len(result.items)} items, {len(result.candidates)} candidates "
            f"({plausible} plausible)"
        )
        for item_id, why in sorted(result.errors.items()):
            self._log(f"  sweep: {item_id} failed: {why}")

    def _sweep_failed(self, message: str) -> None:
        self.sweep.set_status(f"Sweep failed: {message}")
        self._log(f"sweep failed: {message}")

    # ------------------------------------------------------------------ trade queue

    def _queue_tick(self) -> None:
        """Advance the queue's clocks, announce a new offer, redraw.

        Runs once a second: the panel shows live countdowns, and an offer that
        silently outlives its window would leave the hotkey pointing at nothing.
        """
        tick = self.trade_queue.tick()
        if tick.newly_offered is not None:
            self._announce_offer(tick.newly_offered)
        for t in tick.expired:
            log.debug("trade offer expired: %s", t.candidate.item_name)
        for t in tick.auto_resolved:
            self._record_auto_no_reply(t)
        if tick.auto_resolved:
            self.trade_queue.forget_resolved()
        self.queue_panel.refresh(self.trade_queue)

    def _record_auto_no_reply(self, trade) -> None:
        """Write a timed-out whisper to the outcome log as NO_REPLY.

        The queue has already changed the trade's state; this is only the
        persistence half, kept here because the queue has no business knowing
        where the log lives.
        """
        from ..outcomes import record_outcome

        if trade.attempt_id:
            assert self.cfg.outcomes_path is not None
            record_outcome(self.cfg.outcomes_path, trade.attempt_id, trade.outcome)
        self._log(f"{trade.candidate.item_name}: no reply (timed out)")
        self.results.reload()

    def _announce_offer(self, trade) -> None:
        """One toast per offer, and only while no other offer is live.

        The queue guarantees the second part — it never promotes a trade while
        one is already offered — so this can simply fire whenever it's called.
        """
        c = trade.candidate
        seller = c.listing.character or c.listing.account
        key_hint = (
            f"  ·  {format_hotkey(self.cfg.trade_hotkey)}"
            if self.cfg.trade_hotkey_enabled and self._hotkey.active
            else ""
        )
        self._notify(
            f"Trade: +{c.profit_divines:.2f} div{key_hint}",
            f"{c.plan.units:g} × {c.item_name} from {seller} "
            f"for {c.plan.cost_divines:.1f} div",
        )
        self._log(
            f"offered: {c.plan.units:g} × {c.item_name} from {seller} "
            f"for {c.plan.cost_divines:.1f} div (+{c.profit_divines:.2f})"
        )

    def _hotkey_pressed(self) -> None:
        """Take the live offer, if there is one. Otherwise do nothing loudly."""
        trade = self.trade_queue.offered
        if trade is None:
            self.statusBar().showMessage("No trade is being offered right now", 4000)
            return
        self._queue_take(trade.id)

    def _queue_take(self, trade_id: str) -> None:
        """Copy the whisper and move the trade to 'waiting on a reply'."""
        from PySide6.QtGui import QGuiApplication

        from ..listings import whisper_text
        from ..outcomes import record_attempt

        trade = self.trade_queue.get(trade_id)
        if trade is None:
            return
        text = whisper_text(trade.candidate)
        if not text:
            self._log("that listing has no whisper template; dropped")
            self.trade_queue.drop(trade_id)
            self.queue_panel.refresh(self.trade_queue)
            return
        taken = self.trade_queue.take(trade_id)
        if taken is None:
            return  # already gone — a lapse raced the click
        QGuiApplication.clipboard().setText(text)
        assert self.cfg.outcomes_path is not None
        taken.attempt_id = record_attempt(
            self.cfg.outcomes_path, taken.candidate,
            retention_days=self.cfg.history_retention_days,
        )
        c = taken.candidate
        self.statusBar().showMessage(
            f"Copied — paste in game with Ctrl+V, then Enter.  "
            f"{c.plan.units:g} × {c.item_name} for {c.plan.cost_divines:.1f} div",
            15000,
        )
        self._log(f"whisper copied: {c.item_name} from "
                  f"{c.listing.character or c.listing.account}")
        self.results.reload()
        self.queue_panel.refresh(self.trade_queue)

    def _queue_outcome(self, trade_id: str, outcome) -> None:
        from ..outcomes import record_outcome

        trade = self.trade_queue.get(trade_id)
        if trade is None:
            return
        resolved = self.trade_queue.resolve(trade_id, outcome)
        if resolved is None:
            return
        if resolved.attempt_id:
            assert self.cfg.outcomes_path is not None
            record_outcome(self.cfg.outcomes_path, resolved.attempt_id, outcome)
        self._log(f"{resolved.candidate.item_name}: {outcome.value}")
        self.results.reload()
        self.trade_queue.forget_resolved()
        self.queue_panel.refresh(self.trade_queue)

    def _queue_dismiss(self, trade_id: str) -> None:
        trade = self.trade_queue.get(trade_id)
        if trade is not None and self.trade_queue.drop(trade_id):
            self._log(f"dismissed: {trade.candidate.item_name}")
        self.queue_panel.refresh(self.trade_queue)

    def _setup_hotkey(self) -> None:
        """Bind the global hotkey, if the user turned it on and the OS allows it.

        Failure is reported on the Trades tab and in the log rather than raised:
        a hotkey that another program already owns is a normal thing to hit, and
        the tab works fine without it.
        """
        self._hotkey = GlobalHotkey(self)
        self._hotkey.pressed.connect(self._hotkey_pressed)
        self._hotkey.error.connect(lambda msg: self._log(f"hotkey: {msg}"))
        if not self.cfg.trade_hotkey_enabled or not self.cfg.trade_hotkey:
            return
        if not self._hotkey.supported:
            self._log("hotkey: only available on Windows")
            return
        if self._hotkey.register(self.cfg.trade_hotkey):
            self._log(
                f"hotkey {format_hotkey(self.cfg.trade_hotkey)} copies the next trade"
            )
            self.sweep.set_hotkey_hint(self.cfg.trade_hotkey)
            self.queue_panel.set_hotkey_hint(self.cfg.trade_hotkey)

    def _recheck(self, candidate) -> None:
        """Confirm a listing still exists, just before the whisper is copied."""
        self._recheck_worker = RecheckWorker(self.cfg, candidate, self)
        self._recheck_worker.done.connect(self.sweep.recheck_finished)
        self._recheck_worker.start()

    def _attempt_copied(self, candidate) -> None:
        """Log the whisper as a pending attempt the moment it hits the clipboard."""
        from ..outcomes import record_attempt

        assert self.cfg.outcomes_path is not None
        attempt_id = record_attempt(
            self.cfg.outcomes_path, candidate,
            retention_days=self.cfg.history_retention_days,
        )
        self.sweep.note_attempt(candidate, attempt_id)
        self.results.reload()
        self._log(
            f"whisper copied — {candidate.plan.units:g} × {candidate.item_name} "
            f"from {candidate.listing.character or candidate.listing.account} "
            f"for {candidate.plan.cost_divines:.2f} div"
        )

    def _outcome_reported(self, attempt_id: str, outcome) -> None:
        from ..outcomes import record_outcome

        assert self.cfg.outcomes_path is not None
        record_outcome(self.cfg.outcomes_path, attempt_id, outcome)
        self._log(f"trade outcome recorded: {outcome.value}")
        self.results.reload()

    def _bankroll_changed(self, currency: str, held: float) -> None:
        """Take the new bankroll immediately, persist it lazily.

        The spin box fires on every step, so the config write is deferred to
        when editing settles — the in-memory value is what the next sweep reads,
        and that is already correct.
        """
        field = f"bankroll_{currency}"
        if not hasattr(self.cfg, field):
            log.warning("no bankroll field for %r", currency)
            return
        setattr(self.cfg, field, held)
        self._bankroll_save_timer.start()

    def _appetite_changed(self, appetite: float) -> None:
        """Re-rank what's already on screen, then persist lazily.

        Waiting for the next sweep would be a fifteen-minute round trip to see
        the effect of moving a slider.
        """
        self.cfg.risk_appetite = appetite
        self.trade_queue.queue_ghosts = appetite > 0.0
        if self._last_sweep is not None:
            self.sweep.set_result(self._last_sweep, risk_appetite=appetite)
        self._bankroll_save_timer.start()

    def _settlement_changed(self, currency: str) -> None:
        """Takes effect on the next sweep — every Profit figure is recomputed.

        Unlike the appetite slider this cannot re-rank what is on screen: the
        settlement unit feeds `plan_trade`'s rounding, so the profits already
        shown were computed against the old one and would have to be rebuilt
        from the listings.
        """
        self.cfg.sale_currency = currency
        self._log(f"settling sales in {currency} from the next sweep")
        self._bankroll_save_timer.start()

    def _persist_bankroll(self) -> None:
        try:
            save_config(self.cfg, user_config_path())
        except OSError:
            log.warning("could not save bankroll", exc_info=True)

    def _restore_ui_state(self) -> None:
        """Put the window back where it was, if that's still a sensible place."""
        state = load_ui_state(ui_state_path(self.cfg.cache_dir))
        geometry = decode_geometry(state.get("geometry"))
        if geometry and self.restoreGeometry(geometry):
            # A saved position can point at a monitor that's since been
            # unplugged, leaving the window somewhere unreachable.
            if not any(
                s.availableGeometry().intersects(self.frameGeometry())
                for s in QApplication.screens()
            ):
                self.resize(720, 460)
                self.move(100, 100)
        sizes = state.get("ops_split")
        if isinstance(sizes, list) and len(sizes) == 2 and all(
            isinstance(n, int) and n >= 0 for n in sizes
        ):
            self.ops_split.setSizes(sizes)
        tab = state.get("tab")
        if isinstance(tab, int) and 0 <= tab < self.tabs.count():
            self.tabs.setCurrentIndex(tab)

    def _save_ui_state(self) -> None:
        save_ui_state(
            ui_state_path(self.cfg.cache_dir),
            {
                "geometry": encode_geometry(self.saveGeometry()),
                "ops_split": self.ops_split.sizes(),
                "tab": self.tabs.currentIndex(),
            },
        )

    @staticmethod
    def _set_row(table: QTableWidget, row: int, items: list[QTableWidgetItem]) -> None:
        for col, item in enumerate(items):
            table.setItem(row, col, item)

    # ------------------------------------------------------------------ watch loop

    def open_settings(self) -> None:
        dlg = SettingsDialog(
            self.cfg,
            self,
            known_currencies=self._known_currencies,
            currency_values=self._currency_values,
            universe=self._universe,
            leagues=self._leagues,
            detected_league=self._detected_league,
        )
        if dlg.exec():
            previous = self.cfg
            self.cfg = dlg.result_config()
            save_config(self.cfg, user_config_path())
            self._log(f"settings saved to {user_config_path()}")
            self.market.set_exclusions(self.cfg.exclude_currencies)
            self._apply_queue_settings(previous)
            self._reapply_view_settings()

    def _apply_queue_settings(self, previous: Config) -> None:
        """Push changed timings and hotkey onto the objects already running.

        Without this, every one of these needs a restart to take effect, which
        for a countdown the user just shortened is confusing enough to look
        broken.
        """
        self.trade_queue.offer_window_s = self.cfg.offer_window_s
        self.trade_queue.available_ttl_s = self.cfg.available_ttl_s
        self.trade_queue.awaiting_timeout_s = self.cfg.awaiting_timeout_s
        self.trade_queue.queue_ghosts = self.cfg.risk_appetite > 0.0

        rebind = (
            previous.trade_hotkey != self.cfg.trade_hotkey
            or previous.trade_hotkey_enabled != self.cfg.trade_hotkey_enabled
        )
        if not rebind:
            return
        self._hotkey.unregister()
        self.queue_panel.set_hotkey_hint("")
        self.sweep.set_hotkey_hint("")
        if self.cfg.trade_hotkey_enabled and self.cfg.trade_hotkey:
            if self._hotkey.register(self.cfg.trade_hotkey):
                self.queue_panel.set_hotkey_hint(self.cfg.trade_hotkey)
                self._log(
                    f"hotkey {format_hotkey(self.cfg.trade_hotkey)} copies the next trade"
                )
        else:
            self._log("hotkey disabled")
        self.queue_panel.refresh(self.trade_queue)

    def _exclusions_changed(self, excluded: list[str]) -> None:
        """Persist a tick from the Market tab straight away.

        No OK button stands between the click and the effect, so saving here is
        what makes the change survive a restart. The next scan picks it up;
        nothing is re-rendered, because the row the user just ticked should
        stay exactly where it is under their cursor.
        """
        self.cfg.exclude_currencies = list(excluded)
        try:
            save_config(self.cfg, user_config_path())
        except OSError:
            log.warning("could not save exclusions", exc_info=True)
        self._log(f"{len(excluded)} item(s) excluded from the search")

    def _reapply_view_settings(self) -> None:
        """Re-render the Market tab after a settings or icon change."""
        self._render_market()

    def _notify(self, title: str, message: str) -> None:
        if self.tray is not None and self.tray.isVisible():
            self.tray.showMessage(title, message, make_app_icon(), 10_000)
        if self.cfg.alert_sound:
            _play_alert_sound()

    def _show_update_banner(self, tag: str, url: str) -> None:
        self._update_url = url
        self.update_label.setText(
            f"Update available: {tag} (you have {__version__}) — download the new version from GitHub"
        )
        self.update_banner.show()

    def _log(self, line: str, ts: datetime | None = None) -> None:
        """Append a log line, timestamped. `ts` overrides for replayed history.

        Anything logged before the Log tab is built is buffered instead —
        setup logs from the middle of _build_central, and a startup crash in
        the logger would take down the whole window before it ever appeared.
        """
        if getattr(self, "log_view", None) is None:
            self._pending_log.append(line)
            return
        stamp = (ts or datetime.now()).strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{stamp}] {line}")

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._quitting = True
        self.close()

    def shutdown(self) -> None:
        """Stop timers and join worker threads before the event loop goes away."""
        self._save_ui_state()
        self.icons.shutdown()
        self.sweep_timer.stop()
        self.countdown_timer.stop()
        if getattr(self, "_hotkey", None) is not None:
            self._hotkey.unregister()
        stop_thread(self._sweep_worker)
        stop_thread(getattr(self, "_recheck_worker", None), timeout_ms=2000)
        stop_thread(getattr(self, "_update_worker", None), timeout_ms=2000)
        stop_thread(getattr(self, "_currency_worker", None), timeout_ms=2000)

    def closeEvent(self, event: QCloseEvent) -> None:
        # While watching, closing hides to tray so alerts keep coming — but only
        # where a tray actually exists, otherwise the window would be unreachable.
        if self.sweep_action.isChecked() and self.tray_available and not self._quitting:
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "poe2-arb still watching",
                "Scans continue in the background. Right-click the tray icon to quit.",
                make_app_icon(),
                5_000,
            )
            return
        self.shutdown()
        event.accept()
        QApplication.quit()  # quit-on-last-window is disabled for tray mode
