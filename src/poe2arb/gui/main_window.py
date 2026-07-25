"""Main window: opportunity table, market view, watch loop, tray notifications."""

from __future__ import annotations

import sys
import time
import webbrowser
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QIcon
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import Config, load_config, save_config, user_config_path
from ..graph import Opportunity
from ..report import route_str
from ..scan import ScanResult
from .icon import make_app_icon
from .settings_dialog import SettingsDialog
from .updates import RELEASES_PAGE
from .worker import ScanWorker, UpdateCheckWorker


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
        self.resize(900, 560)
        self.setWindowIcon(make_app_icon())

        self.cfg = self._load_cfg()
        self._worker: ScanWorker | None = None
        self._known: dict[tuple[str, ...], float] = {}
        self._first_seen: dict[tuple[str, ...], str] = {}
        self._next_scan_at: float | None = None
        self._quitting = False

        self._build_toolbar()
        self._build_central()
        self._build_tray()
        self._build_timers()
        self._check_updates()

        self.statusBar().showMessage("Ready — press Scan now, or Watch to scan continuously")

    # ------------------------------------------------------------------ setup

    def _load_cfg(self) -> Config:
        path = user_config_path()
        try:
            if path.exists():
                return load_config(path)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Config", f"Could not read {path}:\n{e}\nUsing defaults.")
        return Config()

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

        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.open_settings)
        tb.addAction(settings_action)

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
            ["Route", "Profit/loop", "Depth (div)", "First seen"]
        )
        self.tabs.addTab(self.ops_table, "Opportunities")

        self.market_table = self._make_table(
            ["Currency", "Value (div)", "Daily volume (div)", "In graph"]
        )
        self.tabs.addTab(self.market_table, "Market")

        self.edges_table = self._make_table(
            ["Pay", "Receive", "Book rate", "After fee", "Depth (div)"]
        )
        self.tabs.addTab(self.edges_table, "Book edges")

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.tabs.addTab(self.log_view, "Log")

        self.setCentralWidget(central)

    @staticmethod
    def _make_table(headers: list[str]) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setStretchLastSection(True)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSortingEnabled(True)
        t.verticalHeader().hide()
        return t

    def _build_tray(self) -> None:
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

    def _check_updates(self) -> None:
        self._update_worker = UpdateCheckWorker(__version__, self)
        self._update_worker.update_available.connect(self._show_update_banner)
        self._update_worker.start()

    # ------------------------------------------------------------------ scanning

    def start_scan(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.scan_action.setEnabled(False)
        self.statusBar().showMessage("Scanning — fetching order books…")
        self._worker = ScanWorker(self.cfg, self)
        self._worker.progress.connect(
            lambda i, n: self.statusBar().showMessage(f"Scanning — order books {i}/{n}…")
        )
        self._worker.finished_ok.connect(self._scan_done)
        self._worker.failed.connect(self._scan_failed)
        self._worker.start()

    def _scan_done(self, result: ScanResult) -> None:
        self.scan_action.setEnabled(True)
        now = datetime.now().strftime("%H:%M:%S")
        names = result.overview.names

        current = {op.key: op for op in result.opportunities}
        new_keys = [k for k in current if k not in self._known]
        gone_keys = [k for k in self._known if k not in current]

        for k in new_keys:
            op = current[k]
            self._first_seen[k] = now
            msg = f"NEW  {route_str(op, names)}: +{op.profit_pct:.2f}% (depth {op.min_depth_divines:.1f} div)"
            self._log(f"[{now}] {msg}")
            self._notify("Arbitrage opportunity", msg)
        for k in gone_keys:
            self._log(f"[{now}] gone  {' → '.join(k)} (was +{self._known[k]:.2f}%)")
            self._first_seen.pop(k, None)
        if not new_keys and not gone_keys:
            self._log(f"[{now}] scan complete — {len(current)} above threshold, no changes")

        self._known = {k: op.profit_pct for k, op in current.items()}
        self._refresh_tables(result)

        hint = " (longer/deeper loop exists below reporting window)" if result.longer_cycle_hint else ""
        self.statusBar().showMessage(
            f"{result.league} — scanned {now} — {len(current)} opportunity(ies){hint}"
        )
        if self.watch_action.isChecked():
            self._schedule_next()

    def _scan_failed(self, message: str) -> None:
        self.scan_action.setEnabled(True)
        now = datetime.now().strftime("%H:%M:%S")
        self._log(f"[{now}] scan failed: {message}")
        self.statusBar().showMessage(f"Scan failed: {message}")
        if self.watch_action.isChecked():
            self._schedule_next()  # keep watching; next interval may succeed

    def _refresh_tables(self, result: ScanResult) -> None:
        names = result.overview.names

        ops = result.opportunities
        self.ops_table.setSortingEnabled(False)
        self.ops_table.setRowCount(len(ops))
        for r, op in enumerate(ops):
            self._set_row(
                self.ops_table,
                r,
                [
                    route_str(op, names),
                    f"+{op.profit_pct:.2f}%",
                    f"{op.min_depth_divines:.1f}",
                    self._first_seen.get(op.key, "—"),
                ],
            )
        self.ops_table.setSortingEnabled(True)

        overview = result.overview
        rows = sorted(overview.values, key=lambda c: -overview.values[c])
        self.market_table.setSortingEnabled(False)
        self.market_table.setRowCount(len(rows))
        in_graph = set(result.nodes)
        for r, cid in enumerate(rows):
            vol = overview.volumes.get(cid, 0)
            self._set_row(
                self.market_table,
                r,
                [
                    names.get(cid, cid),
                    f"{overview.values[cid]:.4f}",
                    "∞" if vol == float("inf") else f"{vol:,.0f}",
                    "✓" if cid in in_graph else "",
                ],
            )
        self.market_table.setSortingEnabled(True)

        edges = sorted(result.edges.values(), key=lambda e: (e.src, e.dst))
        self.edges_table.setSortingEnabled(False)
        self.edges_table.setRowCount(len(edges))
        for r, e in enumerate(edges):
            self._set_row(
                self.edges_table,
                r,
                [
                    names.get(e.src, e.src),
                    names.get(e.dst, e.dst),
                    f"{e.raw_rate:.6g}",
                    f"{e.rate:.6g}",
                    f"{e.depth_filled_divines:.1f}",
                ],
            )
        self.edges_table.setSortingEnabled(True)

    @staticmethod
    def _set_row(table: QTableWidget, row: int, values: list[str]) -> None:
        for col, text in enumerate(values):
            item = QTableWidgetItem(text)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, col, item)

    # ------------------------------------------------------------------ watch loop

    def _watch_toggled(self, on: bool) -> None:
        if on:
            self._log("watch started")
            self.start_scan()
        else:
            self._log("watch stopped")
            self.watch_timer.stop()
            self._next_scan_at = None

    def _schedule_next(self) -> None:
        interval_ms = self.cfg.watch_interval_minutes * 60_000
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
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            self.cfg = dlg.result_config()
            save_config(self.cfg, user_config_path())
            self._log(f"settings saved to {user_config_path()}")

    def _notify(self, title: str, message: str) -> None:
        if self.tray.isVisible():
            self.tray.showMessage(title, message, make_app_icon(), 10_000)
        if self.cfg.alert_sound:
            _play_alert_sound()

    def _show_update_banner(self, tag: str, url: str) -> None:
        self._update_url = url
        self.update_label.setText(
            f"Update available: {tag} (you have {__version__}) — download the new version from GitHub"
        )
        self.update_banner.show()

    def _log(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self._quitting = True
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        # While watching, closing hides to tray so alerts keep coming.
        if self.watch_action.isChecked() and not self._quitting:
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "poe2-arb still watching",
                "Scans continue in the background. Right-click the tray icon to quit.",
                make_app_icon(),
                5_000,
            )
        else:
            event.accept()
            QApplication.quit()  # quit-on-last-window is disabled for tray mode
