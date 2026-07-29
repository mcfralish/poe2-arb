"""Settings dialog: edits the Config fields that matter day-to-day.

Grouped by which of the app's two jobs a setting belongs to. That grouping is
the point, not decoration: 0.3.0 established that the triangular cycle search
was reading the wrong market, so its knobs — loop length, graph size, per-hop
margin — no longer describe anything the app finds trades with. They still work,
and they are still here, but sitting unlabelled beside the live settings they
read as advice about how to find trades, which they are not.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from .theme import error_color, muted_color, warning_color
from ..rate_limit import Severity, check_pacing, min_safe_interval, worst_severity


class SettingsDialog(QDialog):
    def __init__(
        self,
        cfg: Config,
        parent=None,
        known_currencies: dict[str, str] | None = None,
        currency_values: dict[str, float] | None = None,
        universe=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._cfg = cfg
        # id -> display name and id -> divine value, both from the last scan,
        # so the exclusion dropdown can list real currencies with their prices.
        self._known = known_currencies or {}
        self._values = currency_values or {}
        self._universe = universe

        layout = QVBoxLayout(self)
        # The form is taller than a 1080p screen once every section is open,
        # and a dialog that runs off the bottom hides its own OK button.
        page = QWidget()
        form = QFormLayout(page)
        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        layout.addWidget(scroll, stretch=1)

        self._section(form, "General")

        self.league = QLineEdit(cfg.league or "")
        self.league.setPlaceholderText("blank = auto-detect current league")
        form.addRow("League", self.league)

        self.request_interval = self._dspin(
            cfg.request_interval_s, 1.0, 120.0, 0.1, " s", decimals=1
        )
        self.request_interval.setToolTip(
            "How long to wait between requests to the official trade API.\n"
            "Lower is faster but risks a rate-limit ban on your whole IP."
        )
        form.addRow("Seconds between requests", self.request_interval)

        self.safety = QSpinBox()
        self.safety.setRange(20, 100)
        self.safety.setSingleStep(10)
        self.safety.setSuffix(" %")
        self.safety.setValue(round(cfg.rate_limit_safety_fraction * 100))
        self.safety.setToolTip(
            "How much of GGG's rate limit this app is allowed to use.\n"
            "Lower it if you run other trade tools on the same connection —\n"
            "the limit is per IP address, so everything shares one budget."
        )
        form.addRow("Share of rate limit to use", self.safety)

        self.retention = self._dspin(
            cfg.history_retention_days, 0.0, 365.0, 1.0, " days", decimals=0
        )
        self.retention.setSpecialValueText("keep everything")
        self.retention.setToolTip(
            "How long saved scans are kept on disk. Watching writes a record\n"
            "every scan, so without a limit the history file grows forever.\n"
            "Set to 0 to keep everything."
        )
        form.addRow("Keep scan history for", self.retention)

        self.sound = QCheckBox("Play sound with notifications")
        self.sound.setChecked(cfg.alert_sound)
        form.addRow("", self.sound)

        self._section(form, "Finding trades")

        self.sweep_items = QSpinBox()
        self.sweep_items.setRange(5, 300)
        self.sweep_items.setValue(cfg.sweep_items)
        self.sweep_items.setToolTip(
            "How many items each sweep checks, busiest on the Currency Exchange\n"
            "first. More is more thorough and takes proportionally longer — the\n"
            "requests are paced, so this is the main thing that sets sweep length."
        )
        form.addRow("Items per sweep", self.sweep_items)

        self.sweep_interval = self._dspin(
            cfg.sweep_interval_minutes, 1.0, 240.0, 1.0, " min", decimals=0
        )
        self.sweep_interval.setToolTip(
            "How long to wait after one sweep before starting the next, while\n"
            "Find trades is on. Listings churn slower than a sweep runs, so\n"
            "back-to-back sweeps mostly re-read the same listings."
        )
        form.addRow("Wait between sweeps", self.sweep_interval)

        self.sweep_min_value = self._dspin(
            cfg.sweep_min_value_divines, 0.0, 1000.0, 0.5, " div", decimals=1
        )
        self.sweep_min_value.setToolTip(
            "Skip items worth less than this each. Stock on this venue is in\n"
            "single digits, so a cheap item cannot clear enough profit in one\n"
            "trade to be worth the message."
        )
        form.addRow("Skip items worth under", self.sweep_min_value)

        self.min_profit = self._dspin(
            cfg.min_profit_divines, 0.0, 100.0, 0.25, " div", decimals=2
        )
        self.min_profit.setToolTip(
            "Drop trades that clear less than this. Settling in exalted makes\n"
            "tiny trades arithmetically profitable; +0.02 divines is real and\n"
            "still not worth whispering a stranger about."
        )
        form.addRow("Minimum profit per trade", self.min_profit)

        self.min_gap = self._dspin(cfg.min_gap_ratio, 1.0, 3.0, 0.01, "x", decimals=2)
        self.min_gap.setToolTip(
            "Below this, a discount is inside the Exchange price's own margin\n"
            "of error — the reference ran 0.4%-4.7% under the live game — so\n"
            "neither the gap nor the profit means much. Marked thin, not hidden."
        )
        form.addRow("Discount is credible from", self.min_gap)

        self.max_gap = self._dspin(cfg.max_gap_ratio, 1.0, 20.0, 0.05, "x", decimals=2)
        self.max_gap.setToolTip(
            "Above this, a listing is treated as a ghost. Across ~10 whispers at\n"
            "3.8x-12.5x, none filled: they are mistakes, stale listings, or\n"
            "already sold. Use the Long shots slider to decide how far to chase\n"
            "them anyway."
        )
        form.addRow("Ghost above", self.max_gap)

        self._section(form, "The trade queue")

        self.offer_window = self._dspin(
            cfg.offer_window_s, 5.0, 300.0, 5.0, " s", decimals=0
        )
        self.offer_window.setToolTip(
            "How long a new trade stays live: a notification appears and the\n"
            "hotkey is armed. Short is fine — ignoring it costs nothing, it\n"
            "just moves down to the list below."
        )
        form.addRow("Trade alert lasts", self.offer_window)

        self.available_ttl = self._dspin(
            cfg.available_ttl_s, 15.0, 3600.0, 15.0, " s", decimals=0
        )
        self.available_ttl.setToolTip(
            "How long a trade stays in 'Ready to whisper' after its alert\n"
            "lapses. Listings do get taken by other people, so holding one\n"
            "much longer mostly wastes a whisper."
        )
        form.addRow("Trade stays listed for", self.available_ttl)

        self.awaiting_timeout = self._dspin(
            cfg.awaiting_timeout_s, 0.0, 3600.0, 30.0, " s", decimals=0
        )
        self.awaiting_timeout.setSpecialValueText("never")
        self.awaiting_timeout.setToolTip(
            "How long a whisper waits for you to say what happened before it\n"
            "records itself as 'no reply'. Set to 0 to answer every one by hand."
        )
        form.addRow("Mark as no reply after", self.awaiting_timeout)

        self.hotkey_enabled = QCheckBox("Global hotkey copies the next trade")
        self.hotkey_enabled.setChecked(cfg.trade_hotkey_enabled)
        self.hotkey_enabled.setToolTip(
            "Press one key anywhere — including in game — to put the next trade's\n"
            "whisper on your clipboard. Paste it with Ctrl+V and press Enter to\n"
            "send. The app never types into the game or sends anything for you.\n"
            "Windows only."
        )
        form.addRow("", self.hotkey_enabled)

        self.hotkey = QLineEdit(cfg.trade_hotkey)
        self.hotkey.setPlaceholderText("ctrl+alt+d")
        self.hotkey.setToolTip(
            "Modifiers plus one key, e.g. ctrl+alt+d or ctrl+shift+f9.\n"
            "A modifier is required: a bare key would be swallowed everywhere,\n"
            "including in chat."
        )
        self.hotkey.setEnabled(cfg.trade_hotkey_enabled)
        self.hotkey_enabled.toggled.connect(self.hotkey.setEnabled)
        self.hotkey.textChanged.connect(self._revalidate)
        form.addRow("Hotkey", self.hotkey)

        self.budget_label = QLabel()
        self.budget_label.setWordWrap(True)
        layout.addWidget(self.budget_label)
        self.setMinimumWidth(560)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        restore = self.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        restore.setToolTip(
            "Put every setting on this page back to its shipped value.\n"
            "Nothing is saved until you press OK, so this is undoable\n"
            "with Cancel."
        )
        restore.clicked.connect(self.restore_defaults)
        layout.addWidget(self.buttons)

        for widget in (
            self.request_interval, self.sweep_items, self.sweep_interval, self.safety
        ):
            widget.valueChanged.connect(self._revalidate)
        self._revalidate()

    def restore_defaults(self) -> None:
        """Reset every widget to the shipped default.

        Deliberately only touches the widgets, not the saved file: pressing
        Cancel afterwards must leave the existing config exactly as it was.
        The league is included — blank means auto-detect, which is the default
        and the right answer for almost everyone.
        """
        d = Config()
        self.league.setText("")
        self.sweep_interval.setValue(d.sweep_interval_minutes)
        self.request_interval.setValue(d.request_interval_s)
        self.safety.setValue(round(d.rate_limit_safety_fraction * 100))
        self.retention.setValue(d.history_retention_days)
        self.sound.setChecked(d.alert_sound)
        self.offer_window.setValue(d.offer_window_s)
        self.available_ttl.setValue(d.available_ttl_s)
        self.awaiting_timeout.setValue(d.awaiting_timeout_s)
        self.hotkey_enabled.setChecked(d.trade_hotkey_enabled)
        self.hotkey.setText(d.trade_hotkey)
        self.sweep_items.setValue(d.sweep_items)
        self.sweep_min_value.setValue(d.sweep_min_value_divines)
        self.min_profit.setValue(d.min_profit_divines)
        self.min_gap.setValue(d.min_gap_ratio)
        self.max_gap.setValue(d.max_gap_ratio)
        # Exclusions are the user's own curation, not a setting with a sensible
        # default — wiping a long list on a button labelled "restore defaults"
        # would be a nasty surprise. Clear All inside the picker still exists.
        self._revalidate()

    # ---------------------------------------------------------------- validation

    def _revalidate(self) -> None:
        """Re-check the request budget and gate the OK button on it.

        Exceeding a window doesn't just throttle you, it bans the IP for up to
        30 minutes — so an over-limit setting is refused outright rather than
        merely warned about.
        """
        interval = self.request_interval.value()
        fraction = self.safety.value() / 100.0
        issues = check_pacing(interval, safety_fraction=fraction)
        severity = worst_severity(issues)

        # A sweep is one request per item, paced by the interval.
        n = self.sweep_items.value()
        duration = max(0, n - 1) * interval
        summary = (
            f"One sweep: {n} requests, about {duration / 60:.1f} minutes "
            f"(cached data is reused, so most sweeps are shorter)."
        )
        gap = self.sweep_interval.value() * 60
        if duration > gap:
            summary += (
                f"<br>That's longer than the {self.sweep_interval.value():g}-minute "
                f"gap between sweeps, so it would run almost continuously. "
                f"Consider fewer items or a longer gap."
            )

        if severity is Severity.ERROR:
            safe = min_safe_interval(safety_fraction=fraction)
            detail = " ".join(i.message for i in issues if i.severity is Severity.ERROR)
            self.budget_label.setText(
                f"<b>Too fast — this would get your IP banned.</b><br>{detail}<br>"
                f"Use at least <b>{safe:g} s</b> between requests.<br><br>{summary}"
            )
            self.budget_label.setStyleSheet(f"color: {error_color(self)};")
        elif severity is Severity.WARNING:
            detail = " ".join(i.message for i in issues if i.severity is Severity.WARNING)
            self.budget_label.setText(
                f"<b>Close to the limit.</b><br>{detail}<br><br>{summary}"
            )
            self.budget_label.setStyleSheet(f"color: {warning_color(self)};")
        else:
            self.budget_label.setText(
                f"Comfortably inside GGG's rate limits, with room for other "
                f"trade tools on the same connection.<br><br>{summary}"
            )
            self.budget_label.setStyleSheet(f"color: {muted_color(self)};")

        hotkey_problem = self._hotkey_problem()
        if hotkey_problem:
            self.budget_label.setText(
                f"<b>Hotkey:</b> {hotkey_problem}<br><br>{self.budget_label.text()}"
            )
            self.budget_label.setStyleSheet(f"color: {warning_color(self)};")

        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        blocked = severity is Severity.ERROR or bool(hotkey_problem)
        ok.setEnabled(not blocked)
        if severity is Severity.ERROR:
            ok.setToolTip(
                "Fix the request spacing first — these settings would get your IP "
                "temporarily banned from the trade API."
            )
        elif hotkey_problem:
            ok.setToolTip(f"Fix the hotkey first: {hotkey_problem}")
        else:
            ok.setToolTip("")

    def _hotkey_problem(self) -> str:
        """Why the typed hotkey can't be used, or "" if it's fine.

        Checked here rather than on save because a rejected binding leaves the
        user with a key that silently does nothing — the failure would otherwise
        only show up in the log.
        """
        if not self.hotkey_enabled.isChecked():
            return ""
        from .hotkey import HotkeyError, parse_hotkey

        try:
            parse_hotkey(self.hotkey.text().strip())
        except HotkeyError as e:
            return str(e)
        return ""

    def _section(self, form, title: str, note: str = "") -> None:
        """A bold heading spanning the form, optionally with an explanation."""
        label = QLabel(title)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        if form.rowCount():
            label.setContentsMargins(0, 12, 0, 0)
        form.addRow(label)
        if note:
            explain = QLabel(note)
            explain.setWordWrap(True)
            explain.setStyleSheet(f"color: {muted_color(self)};")
            form.addRow(explain)

    @staticmethod
    def _dspin(
        value: float, lo: float, hi: float, step: float, suffix: str,
        decimals: int = 2,
    ) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setDecimals(decimals)
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setSuffix(suffix)
        s.setValue(value)
        return s

    def result_config(self) -> Config:
        return replace(
            self._cfg,
            rate_limit_safety_fraction=self.safety.value() / 100.0,
            league=self.league.text().strip() or None,
            sweep_interval_minutes=self.sweep_interval.value(),
            request_interval_s=self.request_interval.value(),
            history_retention_days=self.retention.value(),
            alert_sound=self.sound.isChecked(),
            offer_window_s=self.offer_window.value(),
            available_ttl_s=self.available_ttl.value(),
            awaiting_timeout_s=self.awaiting_timeout.value(),
            trade_hotkey=self.hotkey.text().strip(),
            trade_hotkey_enabled=self.hotkey_enabled.isChecked(),
            sweep_items=self.sweep_items.value(),
            sweep_min_value_divines=self.sweep_min_value.value(),
            min_profit_divines=self.min_profit.value(),
            min_gap_ratio=self.min_gap.value(),
            max_gap_ratio=self.max_gap.value(),
        )
