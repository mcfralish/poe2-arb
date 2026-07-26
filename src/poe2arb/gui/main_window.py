"""Main window: opportunity table, market view, watch loop, tray notifications."""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from typing import NamedTuple

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
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
from ..client import NinjaOverview
from ..config import (
    Config,
    load_config,
    migrate_legacy_cache,
    save_config,
    user_config_path,
)
from ..format import fmt_depth, fmt_pct, fmt_rate, fmt_value, fmt_volume
from ..history import read_recent
from ..market import BASE_CURRENCY_CHOICES, Universe
from ..rate_limit import Severity, check_pacing, min_safe_interval, worst_severity
from ..report import route_str
from ..scan import ScanResult, result_from_history_record
from .icon import make_app_icon
from .settings_dialog import SettingsDialog
from .table_items import NumericItem, TextItem
from .updates import RELEASES_PAGE
from .lookup import QuickLookup
from .worker import ScanWorker, UniverseWorker, UpdateCheckWorker, stop_thread


log = logging.getLogger(__name__)

# How far back the log and tables are repopulated on launch.
BACKLOAD_HOURS = 8.0


class Column(NamedTuple):
    title: str
    tooltip: str


# Tooltips are written for someone who plays the game but doesn't trade
# professionally — no jargon, no maths, just what the number means for them.
OPS_COLUMNS = [
    Column(
        "Route",
        "The chain of trades to make, in order. You end up back in the currency "
        "you started with — hopefully holding more of it than when you began.",
    ),
    Column(
        "Profit/loop",
        "How much more you'd finish with after going all the way around once, "
        "if every trade fills at the price currently listed. Fees and a bit of "
        "slippage are already subtracted.",
    ),
    Column(
        "Depth (div)",
        "Roughly how much this trade can absorb, in Divine Orbs, before you run "
        "out of people offering these prices. The tightest step in the chain "
        "sets the limit. Trade bigger than this and the profit shrinks.",
    ),
    Column(
        "First seen",
        "When this opportunity first showed up in a scan. Ones that have "
        "survived several scans tend to be more real than ones that just blinked "
        "into existence.",
    ),
]

MARKET_COLUMNS = [
    Column("Currency", "The currency item, as poe.ninja names it."),
    Column(
        "Value (div)",
        "What one of these is worth in Divine Orbs, according to poe.ninja's "
        "market data. A Divine Orb itself is 1.0000.",
    ),
    Column(
        "Daily volume (div)",
        "How much of this currency changes hands in a day, measured in Divine "
        "Orbs of value. Higher means a busier market, which means your trades "
        "are more likely to actually fill.",
    ),
    Column(
        "In graph",
        "A tick means this currency was included in the arbitrage search. "
        "Quiet or excluded currencies are left out — they produce tempting "
        "numbers that never actually trade.",
    ),
]

EDGE_COLUMNS = [
    Column("Pay", "The currency you hand over."),
    Column("Receive", "The currency you get back."),
    Column(
        "Book rate",
        "How many you'd receive for paying 1, based on real offers currently "
        "listed on the official trade site — not a theoretical price.",
    ),
    Column(
        "After fee",
        "The same rate once the exchange fee and expected slippage are taken "
        "off. This is the number the profit calculation actually uses.",
    ),
    Column(
        "Depth (div)",
        "How much value, in Divine Orbs, is available at this rate before you'd "
        "have to accept worse prices.",
    ),
]


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
        self.resize(720, 460)
        self.setMinimumSize(560, 360)
        self.setWindowIcon(make_app_icon())

        # Startup notices collected before the log widget exists.
        self._pending_log: list[str] = []
        self.cfg = self._load_cfg()
        self._worker: ScanWorker | None = None
        self._known: dict[tuple[str, ...], float] = {}
        self._first_seen: dict[tuple[str, ...], str] = {}
        # id -> display name from the last scan, so Settings can accept
        # in-game currency names and flag typos.
        self._known_currencies: dict[str, str] = {}
        self._currency_values: dict[str, float] = {}
        self._universe: Universe | None = None
        self._last_result: ScanResult | None = None
        self._backload_record: dict | None = None
        self._next_scan_at: float | None = None
        self._quitting = False

        self._build_toolbar()
        self._build_central()
        for line in self._pending_log:
            self._log(line)
        self._pending_log.clear()
        self._build_tray()
        self._build_timers()
        self._backload_from_history()
        self._check_updates()
        self._preload_currencies()

        if not self.statusBar().currentMessage():
            self.statusBar().showMessage(
                "Ready — press Scan now, or Watch to scan continuously"
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

        self.scan_action = QAction("Scan now", self)
        self.scan_action.triggered.connect(self.start_scan)
        tb.addAction(self.scan_action)

        self.watch_action = QAction("Watch", self)
        self.watch_action.setCheckable(True)
        self.watch_action.toggled.connect(self._watch_toggled)
        tb.addAction(self.watch_action)

        self.stop_action = QAction("Stop", self)
        self.stop_action.setToolTip(
            "Cancel the scan in progress and stop watching. A scan can take "
            "several minutes, so this is how you get out of one early."
        )
        self.stop_action.setEnabled(False)
        self.stop_action.triggered.connect(self.stop_scan)
        tb.addAction(self.stop_action)

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
        self.update_banner.setStyleSheet(
            "background: #8a6d1a; border-radius: 4px; color: white;"
        )
        self.update_banner.hide()
        self._update_url = RELEASES_PAGE
        layout.addWidget(self.update_banner)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.ops_table = self._make_table(
            OPS_COLUMNS, 1, Qt.SortOrder.DescendingOrder  # biggest profit first
        )
        self.lookup = QuickLookup()
        ops_split = QSplitter(Qt.Orientation.Vertical)
        ops_split.addWidget(self.ops_table)
        ops_split.addWidget(self.lookup)
        ops_split.setStretchFactor(0, 3)
        ops_split.setStretchFactor(1, 2)
        self.tabs.addTab(ops_split, "Opportunities")

        self.market_table = self._make_table(
            MARKET_COLUMNS, 1, Qt.SortOrder.DescendingOrder  # most valuable first
        )
        self._update_market_header()
        self.tabs.addTab(self.market_table, "Market")

        self.edges_table = self._make_table(
            EDGE_COLUMNS, 4, Qt.SortOrder.DescendingOrder  # deepest books first
        )
        self.tabs.addTab(self.edges_table, "Book edges")

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.tabs.addTab(self.log_view, "Log")

        self.setCentralWidget(central)

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
        self._update_market_header()
        self._reapply_view_settings()
        self.lookup.set_base_currency(chosen)
        try:
            save_config(self.cfg, user_config_path())
        except OSError:
            log.warning("could not save base currency", exc_info=True)
        self._log(f"showing prices in {self._universe.name(chosen) if self._universe else chosen}")

    def _update_market_header(self) -> None:
        """Market value column names whichever currency the user picked."""
        label = dict(BASE_CURRENCY_CHOICES).get(self.cfg.base_currency, "Divine Orb")
        short = label.split()[0].lower()
        item = self.market_table.horizontalHeaderItem(1)
        item.setText(f"Value ({short})")
        item.setToolTip(
            f"What one of these is worth in {label}s, according to poe.ninja's "
            f"market data. Change the unit in Settings."
        )

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
        self.watch_timer = QTimer(self)
        self.watch_timer.setSingleShot(True)
        self.watch_timer.timeout.connect(self.start_scan)

        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(1000)
        self.countdown_timer.timeout.connect(self._tick_countdown)
        self.countdown_timer.start()

    def _backload_from_history(self) -> None:
        """Repopulate the log and tables from recent scans on disk.

        A restart otherwise looks like a blank slate even though the app has
        hours of results banked. Only the last BACKLOAD_HOURS are replayed —
        older readings describe a market that has since moved on.
        """
        records = read_recent(self.cfg.history_path, BACKLOAD_HOURS)
        if not records:
            return

        seen: dict[tuple[str, ...], float] = {}
        for record in records:
            ts = datetime.fromisoformat(record["ts"]).astimezone()
            current = {
                tuple(o["cycle"]): float(o["profit_pct"])
                for o in record.get("opportunities", [])
            }
            for key, profit in current.items():
                if key not in seen:
                    route = " → ".join(key) + f" → {key[0]}"
                    self._log(f"NEW  {route}: +{profit:.2f}%", ts=ts)
                    self._first_seen.setdefault(key, ts.strftime("%H:%M:%S"))
            for key in set(seen) - set(current):
                route = " → ".join(key) + f" → {key[0]}"
                self._log(f"gone  {route} (was +{seen[key]:.2f}%)", ts=ts)
                self._first_seen.pop(key, None)
            seen = current

        latest = records[-1]
        latest_ts = datetime.fromisoformat(latest["ts"]).astimezone()
        self._backload_record = latest
        self._refresh_tables(result_from_history_record(latest, self._known_currencies))
        self._log(
            f"restored {len(records)} scan(s) from the last "
            f"{BACKLOAD_HOURS:g}h — newest {latest_ts.strftime('%H:%M:%S')}"
        )
        self.statusBar().showMessage(
            f"Showing saved results from {latest_ts.strftime('%H:%M:%S')} — "
            f"press Scan now to refresh"
        )

    def _preload_currencies(self) -> None:
        """Populate the currency list before any scan has run.

        Settings' exclusion list would otherwise be empty on a fresh install,
        with no way to pick anything until a multi-minute scan finished.
        """
        self._currency_worker = UniverseWorker(self.cfg, self)
        self._currency_worker.loaded.connect(self._universe_loaded)
        self._currency_worker.start()

    def _universe_loaded(self, universe: Universe) -> None:
        """Full economy data arrived: feed the pickers and the lookup tool."""
        self._universe = universe
        self.lookup.set_universe(universe)
        self.lookup.set_base_currency(self.cfg.base_currency)
        self._log(
            f"loaded {len(universe)} items across "
            f"{len(universe.by_category())} categories from poe.ninja"
        )
        names = universe.names()
        values = universe.values()
        volumes = {i.id: i.volume_divine for i in universe.items.values()}
        self._currencies_loaded(names, values, volumes)

    def _currencies_loaded(self, names: dict, values: dict, volumes: dict) -> None:
        # A completed scan is a better source; don't overwrite it.
        if self._known_currencies:
            return
        self._known_currencies = names
        self._currency_values = values
        if self._worker is not None and self._worker.isRunning():
            return  # a live scan is about to replace these tables anyway
        self._render_market_only(names, values, volumes)

    def _render_market_only(self, names: dict, values: dict, volumes: dict) -> None:
        """Show fresh poe.ninja prices without disturbing restored scan data.

        Rebuilds the Market tab from the newer figures while keeping whatever
        Opportunities and Book edges were restored from history — those need a
        real scan (order books) and can't come from poe.ninja alone.
        """
        base = self._backload_record
        if base is not None:
            record = dict(base)
            ninja_ts = datetime.now(timezone.utc).isoformat()
            # Use whichever price snapshot is newer for the Market tab.
            if record["ts"] < ninja_ts:
                record["ninja_values_divine"] = values
                record["ninja_volumes_divine"] = volumes
            self._refresh_tables(result_from_history_record(record, names))
            return
        overview = NinjaOverview(
            league=self.cfg.league or "?",
            fetched_at=datetime.now(timezone.utc),
            values=values,
            volumes=volumes,
            names=names,
        )
        self._refresh_tables(
            ScanResult(
                league=overview.league,
                overview=overview,
                nodes=[],
                edges={},
                opportunities=[],
                longer_cycle_hint=False,
            )
        )

    def _check_updates(self) -> None:
        self._update_worker = UpdateCheckWorker(__version__, self)
        self._update_worker.update_available.connect(self._show_update_banner)
        self._update_worker.start()

    # ------------------------------------------------------------------ scanning

    def start_scan(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.scan_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.statusBar().showMessage("Scanning — fetching order books…")
        self._worker = ScanWorker(self.cfg, self)
        self._worker.progress.connect(
            lambda i, n: self.statusBar().showMessage(f"Scanning — order books {i}/{n}…")
        )
        self._worker.finished_ok.connect(self._scan_done)
        self._worker.failed.connect(self._scan_failed)
        # Runs on every exit path, including cancellation — which emits no
        # result signal at all, so the buttons would otherwise stay disabled.
        self._worker.finished.connect(self._scan_thread_finished)
        self._worker.start()

    def stop_scan(self) -> None:
        """Cancel the running scan and stop watching."""
        now = datetime.now().strftime("%H:%M:%S")
        was_watching = self.watch_action.isChecked()
        if was_watching:
            self.watch_action.setChecked(False)  # also stops the timer
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._log("stopping scan…")
            self.statusBar().showMessage("Stopping…")
        elif was_watching:
            self._log("watch stopped")
        self.watch_timer.stop()
        self._next_scan_at = None

    def _scan_thread_finished(self) -> None:
        self.scan_action.setEnabled(True)
        self.stop_action.setEnabled(self.watch_action.isChecked())
        if self._worker is not None and self._worker.was_cancelled:
            now = datetime.now().strftime("%H:%M:%S")
            self._log("scan stopped")
            self.statusBar().showMessage("Scan stopped")

    def _scan_done(self, result: ScanResult) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        names = result.overview.names

        current = {op.key: op for op in result.opportunities}
        new_keys = [k for k in current if k not in self._known]
        gone_keys = [k for k in self._known if k not in current]

        for k in new_keys:
            op = current[k]
            self._first_seen.setdefault(k, now)
            msg = f"NEW  {route_str(op, names)}: +{op.profit_pct:.2f}% (depth {op.min_depth_divines:.1f} div)"
            self._log(msg)
            self._notify("Arbitrage opportunity", msg)
        for k in gone_keys:
            self._log(f"gone  {' → '.join(k)} (was +{self._known[k]:.2f}%)")
            self._first_seen.pop(k, None)
        if not new_keys and not gone_keys:
            self._log(f"scan complete — {len(current)} above threshold, no changes")

        self._known = {k: op.profit_pct for k, op in current.items()}
        self._backload_record = None
        self._known_currencies = dict(names)
        self._currency_values = dict(result.overview.values)
        self._refresh_tables(result)

        hint = " (longer/deeper loop exists below reporting window)" if result.longer_cycle_hint else ""
        self.statusBar().showMessage(
            f"{result.league} — scanned {now} — {len(current)} opportunity(ies){hint}"
        )
        if self.watch_action.isChecked():
            self._schedule_next()

    def _scan_failed(self, message: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._log(f"scan failed: {message}")
        self.statusBar().showMessage(f"Scan failed: {message}")
        if self.watch_action.isChecked():
            self._schedule_next()  # keep watching; next interval may succeed

    def _refresh_tables(self, result: ScanResult) -> None:
        self._last_result = result
        names = result.overview.names

        ops = result.opportunities
        self.ops_table.setSortingEnabled(False)
        self.ops_table.setRowCount(len(ops))
        for r, op in enumerate(ops):
            self._set_row(
                self.ops_table,
                r,
                [
                    TextItem(route_str(op, names)),
                    NumericItem(fmt_pct(op.profit_pct), op.profit_pct),
                    NumericItem(fmt_depth(op.min_depth_divines), op.min_depth_divines),
                    TextItem(self._first_seen.get(op.key, "—")),
                ],
            )
        self.ops_table.setSortingEnabled(True)

        overview = result.overview
        # Excluded items stay cached and logged, they're just not shown — the
        # point of excluding something is to stop having to look at it.
        excluded = {c.strip().lower() for c in self.cfg.exclude_currencies}
        rows = sorted(
            (c for c in overview.values if c not in excluded),
            key=lambda c: -overview.values[c],
        )
        self.market_table.setSortingEnabled(False)
        self.market_table.setRowCount(len(rows))
        in_graph = set(result.nodes)
        base_rate = overview.values.get(self.cfg.base_currency) or 1.0
        for r, cid in enumerate(rows):
            vol = overview.volumes.get(cid, 0.0)
            # Stored in divines; shown in whatever unit the user picked.
            value = overview.values[cid] / base_rate
            self._set_row(
                self.market_table,
                r,
                [
                    TextItem(names.get(cid, cid)),
                    NumericItem(fmt_value(value), value),
                    NumericItem(fmt_volume(vol), vol),
                    TextItem("✓" if cid in in_graph else ""),
                ],
            )
        self.market_table.setSortingEnabled(True)

        edges = sorted(
            (
                e for e in result.edges.values()
                if e.src not in excluded and e.dst not in excluded
            ),
            key=lambda e: (e.src, e.dst),
        )
        self.edges_table.setSortingEnabled(False)
        self.edges_table.setRowCount(len(edges))
        for r, e in enumerate(edges):
            self._set_row(
                self.edges_table,
                r,
                [
                    TextItem(names.get(e.src, e.src)),
                    TextItem(names.get(e.dst, e.dst)),
                    NumericItem(fmt_rate(e.raw_rate), e.raw_rate),
                    NumericItem(fmt_rate(e.rate), e.rate),
                    NumericItem(fmt_depth(e.depth_filled_divines), e.depth_filled_divines),
                ],
            )
        self.edges_table.setSortingEnabled(True)

    @staticmethod
    def _set_row(table: QTableWidget, row: int, items: list[QTableWidgetItem]) -> None:
        for col, item in enumerate(items):
            table.setItem(row, col, item)

    # ------------------------------------------------------------------ watch loop

    def _watch_toggled(self, on: bool) -> None:
        if on:
            self._log("watch started")
            self.stop_action.setEnabled(True)
            self.start_scan()
        else:
            self._log("watch stopped")
            self.watch_timer.stop()
            self._next_scan_at = None

    def _schedule_next(self) -> None:
        interval_ms = int(self.cfg.watch_interval_minutes * 60_000)
        self.watch_timer.start(interval_ms)
        self._next_scan_at = time.monotonic() + interval_ms / 1000

    def _tick_countdown(self) -> None:
        if self._next_scan_at is None or (self._worker and self._worker.isRunning()):
            return
        remaining = int(self._next_scan_at - time.monotonic())
        if remaining > 0:
            mins, secs = divmod(remaining, 60)
            self.statusBar().showMessage(
                self.statusBar().currentMessage().split(" | next scan")[0]
                + f" | next scan in {mins}:{secs:02d}"
            )

    # ------------------------------------------------------------------ misc

    def open_settings(self) -> None:
        dlg = SettingsDialog(
            self.cfg,
            self,
            known_currencies=self._known_currencies,
            currency_values=self._currency_values,
            universe=self._universe,
        )
        if dlg.exec():
            self.cfg = dlg.result_config()
            save_config(self.cfg, user_config_path())
            self._log(f"settings saved to {user_config_path()}")
            self._update_market_header()
            self._reapply_view_settings()

    def _reapply_view_settings(self) -> None:
        """Re-render tables after a settings change, without a fresh scan."""
        if self._last_result is not None:
            self._refresh_tables(self._last_result)

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
        """Append a log line, timestamped. `ts` overrides for replayed history."""
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
        self.watch_timer.stop()
        self.countdown_timer.stop()
        stop_thread(self._worker)
        stop_thread(getattr(self, "_update_worker", None), timeout_ms=2000)
        stop_thread(getattr(self, "_currency_worker", None), timeout_ms=2000)

    def closeEvent(self, event: QCloseEvent) -> None:
        # While watching, closing hides to tray so alerts keep coming — but only
        # where a tray actually exists, otherwise the window would be unreachable.
        if self.watch_action.isChecked() and self.tray_available and not self._quitting:
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
