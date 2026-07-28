"""Settings dialog: edits the Config fields that matter day-to-day."""

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
    QSpinBox,
    QVBoxLayout,
)

from ..config import Config
from .theme import error_color, muted_color, warning_color
from ..rate_limit import (
    Severity,
    check_pacing,
    min_safe_interval,
    requests_per_scan,
    scan_duration_estimate_s,
    worst_severity,
)


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
        form = QFormLayout()
        layout.addLayout(form)

        self.league = QLineEdit(cfg.league or "")
        self.league.setPlaceholderText("blank = auto-detect current league")
        form.addRow("League", self.league)

        self.threshold = self._dspin(cfg.profit_threshold_pct, 0.0, 100.0, 0.1, "%")
        form.addRow("Profit threshold", self.threshold)

        self.margin = self._dspin(cfg.safety_margin_pct, 0.0, 20.0, 0.1, "%")
        self.margin.setToolTip(
            "Extra caution subtracted from every step of a loop.\n"
            "Not a fee: the exchange charges gold, which isn't priced in\n"
            "divines, and slippage is already handled by pricing each edge\n"
            "at the depth you set. This covers the offer being gone when\n"
            "you get there. 0 reports what the books actually say."
        )
        form.addRow("Safety margin per hop", self.margin)

        self.interval = self._dspin(
            cfg.watch_interval_minutes, 0.5, 240.0, 0.5, " min", decimals=1
        )
        form.addRow("Watch interval", self.interval)

        self.max_currencies = QSpinBox()
        self.max_currencies.setRange(3, 20)
        self.max_currencies.setValue(cfg.max_currencies)
        form.addRow("Currencies in graph (top-N by volume)", self.max_currencies)

        self.max_cycle_len = QComboBox()
        self.max_cycle_len.addItems(["3", "4"])
        self.max_cycle_len.setCurrentText(str(cfg.max_cycle_len))
        form.addRow("Max loop length", self.max_cycle_len)

        self.liquidity = self._dspin(
            cfg.liquidity_floor_divines, 0.0, 100000.0, 1.0, " div", decimals=0
        )
        self.liquidity.setToolTip(
            "Ignore currencies that trade less than this much per day. Quiet "
            "markets show tempting prices that never actually fill."
        )
        form.addRow("Liquidity floor (daily volume)", self.liquidity)

        self.max_value = self._dspin(
            cfg.max_currency_value_divines, 0.0, 1_000_000.0, 5.0, " div", decimals=0
        )
        self.max_value.setSpecialValueText("no limit")
        self.max_value.setToolTip(
            "Also skip any currency worth more than this per unit.\n"
            "Set to 0 for no limit."
        )
        form.addRow("Skip currencies worth over", self.max_value)

        self.depth = self._dspin(cfg.depth_divines, 0.5, 1000.0, 0.5, " div", decimals=1)
        form.addRow("Fill depth per edge", self.depth)

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

        self.budget_label = QLabel()
        self.budget_label.setWordWrap(True)
        layout.addWidget(self.budget_label)

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
            self.request_interval, self.max_currencies, self.interval, self.safety
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
        self.threshold.setValue(d.profit_threshold_pct)
        self.margin.setValue(d.safety_margin_pct)
        self.interval.setValue(d.watch_interval_minutes)
        self.max_currencies.setValue(d.max_currencies)
        self.max_cycle_len.setCurrentText(str(d.max_cycle_len))
        self.liquidity.setValue(d.liquidity_floor_divines)
        self.max_value.setValue(d.max_currency_value_divines)
        self.depth.setValue(d.depth_divines)
        self.request_interval.setValue(d.request_interval_s)
        self.safety.setValue(round(d.rate_limit_safety_fraction * 100))
        self.retention.setValue(d.history_retention_days)
        self.sound.setChecked(d.alert_sound)
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

        n = requests_per_scan(self.max_currencies.value(), self._cfg.have_chunk)
        duration = scan_duration_estimate_s(
            self.max_currencies.value(), self._cfg.have_chunk, interval
        )
        summary = (
            f"One full scan: {n} requests, about {duration / 60:.1f} minutes "
            f"(cached data is reused, so most scans are shorter)."
        )
        if duration > self.interval.value() * 60:
            summary += (
                f"<br>That's longer than your {self.interval.value()}-minute watch "
                f"interval, so scanning would run almost continuously. Consider "
                f"fewer currencies or a longer interval."
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

        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(severity is not Severity.ERROR)
        ok.setToolTip(
            "Fix the request spacing first — these settings would get your IP "
            "temporarily banned from the trade API."
            if severity is Severity.ERROR
            else ""
        )

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
            max_currency_value_divines=self.max_value.value(),
            rate_limit_safety_fraction=self.safety.value() / 100.0,
            league=self.league.text().strip() or None,
            profit_threshold_pct=self.threshold.value(),
            safety_margin_pct=self.margin.value(),
            watch_interval_minutes=self.interval.value(),
            max_currencies=self.max_currencies.value(),
            max_cycle_len=int(self.max_cycle_len.currentText()),
            liquidity_floor_divines=self.liquidity.value(),
            depth_divines=self.depth.value(),
            request_interval_s=self.request_interval.value(),
            history_retention_days=self.retention.value(),
            alert_sound=self.sound.isChecked(),
        )
