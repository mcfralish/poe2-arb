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
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import Config
from .hotkey_edit import HotkeyEdit
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
        leagues: list[str] | None = None,
        detected_league: str | None = None,
        hotkey=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._cfg = cfg
        # id -> display name and id -> divine value, both from the last scan,
        # so the exclusion dropdown can list real currencies with their prices.
        self._known = known_currencies or {}
        self._values = currency_values or {}
        self._universe = universe
        # poe.ninja's league list, current first. Empty when the Market tab
        # hasn't loaded yet, which the dropdown handles by falling back to a
        # free-text entry rather than offering nothing.
        self._leagues = list(leagues or [])
        self._detected_league = detected_league

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

        # A dropdown, not free text: a typo here silently prices your trades
        # against the wrong economy, and Standard runs several times higher than
        # a temp league. The list comes from poe.ninja, current league first.
        self.league = QComboBox()
        self.league.setEditable(False)
        self._fill_leagues()
        self.league.setToolTip(
            "Which league to look for trades in. Leave on automatic and the app\n"
            "follows whichever league is current.\n\n"
            "Getting this wrong is expensive: Standard has years of accumulated\n"
            "currency, so its prices run several times higher than a fresh\n"
            "league's, and sellers in another league can't trade with you at all."
        )
        form.addRow("League", self.league)

        self.request_interval = self._dspin(
            cfg.request_interval_s, 1.0, 120.0, 0.1, " s", decimals=1
        )
        self.request_interval.setToolTip(
            "How long to wait between checks against the official trade site.\n\n"
            "Lower is faster, but going too fast gets your connection blocked for\n"
            "half an hour — and that blocks the trade website and any other trade\n"
            "tool you're running, not just this app."
        )
        form.addRow("Seconds between requests", self.request_interval)

        self.safety = QSpinBox()
        self.safety.setRange(20, 100)
        self.safety.setSingleStep(10)
        self.safety.setSuffix(" %")
        self.safety.setValue(round(cfg.rate_limit_safety_fraction * 100))
        self.safety.setToolTip(
            "How much of the trade site's allowance this app may use.\n\n"
            "The allowance is per connection, so the trade website and every other\n"
            "trade tool you run share it. Turn this down if you use them alongside\n"
            "this app."
        )
        form.addRow("Share of rate limit to use", self.safety)

        self.retention = self._dspin(
            cfg.history_retention_days, 0.0, 365.0, 1.0, " days", decimals=0
        )
        self.retention.setSpecialValueText("keep everything")
        self.retention.setToolTip(
            "How long to keep the record of past passes on disk.\n\n"
            "Leaving Find trades running writes an entry every pass, so without a\n"
            "limit the file grows indefinitely."
        )
        form.addRow("Keep scan history for", self.retention)

        self.sound = QCheckBox("Play sound with notifications")
        self.sound.setChecked(cfg.alert_sound)
        form.addRow("", self.sound)

        self.always_on_top = QCheckBox("Keep this window above other windows")
        self.always_on_top.setChecked(cfg.always_on_top)
        self.always_on_top.setToolTip(
            "Float the window over everything else, including the game.\n\n"
            "Worth turning on while you're trading heavily and want the queue\n"
            "visible without alt-tabbing. Leave it off otherwise — a window that\n"
            "won't go behind anything is in the way the rest of the time.\n\n"
            "Full-screen games ignore this; use borderless windowed."
        )
        form.addRow("", self.always_on_top)

        self._section(form, "Finding trades")

        self.sweep_items = QSpinBox()
        self.sweep_items.setRange(5, 300)
        self.sweep_items.setValue(cfg.sweep_items)
        self.sweep_items.setToolTip(
            "How many different items to check each time round, most heavily\n"
            "traded first.\n\n"
            "This is the main thing that decides how long a pass takes: checks\n"
            "have to be spaced out to stay inside the trade site's limits, so\n"
            "doubling the items roughly doubles the time."
        )
        form.addRow("Items per sweep", self.sweep_items)

        self.sweep_interval = self._dspin(
            cfg.sweep_interval_minutes, 1.0, 240.0, 1.0, " min", decimals=0
        )
        self.sweep_interval.setToolTip(
            "How long to pause before starting the next pass, while Find trades\n"
            "is switched on.\n\n"
            "Listings don't change much faster than a pass takes to run, so going\n"
            "straight into another one mostly re-reads the same offers and spends\n"
            "the request budget for nothing."
        )
        form.addRow("Wait between sweeps", self.sweep_interval)

        self.sweep_min_value = self._dspin(
            cfg.sweep_min_value_divines, 0.0, 1000.0, 0.5, " div", decimals=1
        )
        self.sweep_min_value.setToolTip(
            "Ignore items cheaper than this.\n\n"
            "Sellers here list a handful of anything at a time, so however good\n"
            "the discount on a cheap item, the profit stays too small to be worth\n"
            "the message."
        )
        form.addRow("Skip items worth under", self.sweep_min_value)

        self.min_profit = self._dspin(
            cfg.min_profit_divines, 0.0, 100.0, 0.25, " div", decimals=2
        )
        self.min_profit.setToolTip(
            "Hide trades that make less than this.\n\n"
            "Taking payment in exalted means even trivial trades come out very\n"
            "slightly ahead. Two hundredths of a divine is still a profit, and\n"
            "still not worth messaging a stranger over."
        )
        form.addRow("Minimum profit per trade", self.min_profit)

        self.min_gap = self._dspin(cfg.min_gap_ratio, 1.0, 3.0, 0.01, "x", decimals=2)
        self.min_gap.setToolTip(
            "How far under market a price has to be before it counts as a real\n"
            "discount. 1.20x means the item sells for 20% more than it's listed at.\n\n"
            "Anything smaller is guesswork: our price estimate is itself only good\n"
            "to a few percent, and on rarely-traded items it has been measured\n"
            "more than 25% too high. Those trades still show up, labelled thin."
        )
        form.addRow("Count as a discount from", self.min_gap)

        self.max_gap = self._dspin(cfg.max_gap_ratio, 1.0, 20.0, 0.05, "x", decimals=2)
        self.max_gap.setToolTip(
            "Above this, a bargain is too good to be true and gets labelled a\n"
            "ghost — almost always already sold, abandoned, or a typo.\n\n"
            "Every deep discount we've tried to buy was ignored; the only two\n"
            "that ever worked were the two smallest. Ghosts stay visible and sort\n"
            "last, and the Long shots slider decides how hard to chase them."
        )
        form.addRow("Too good to be true above", self.max_gap)

        self._section(form, "The trade queue")

        self.offer_window = self._dspin(
            cfg.offer_window_s, 5.0, 300.0, 5.0, " s", decimals=0
        )
        self.offer_window.setToolTip(
            "How long a new trade stays the active one — a notification shows and\n"
            "the hotkey will copy it.\n\n"
            "Short is fine. Ignoring it costs you nothing; it just drops into\n"
            "Ready to whisper and waits there."
        )
        form.addRow("Trade alert lasts", self.offer_window)

        # Minutes, not seconds. Both of these are set in multiples of a minute
        # in practice, and reading "600 s" off a spin box to work out whether it
        # is long enough is arithmetic the dialog should be doing (reported from
        # the field 2026-07-31). The config stays in seconds — every consumer is
        # a timer — so the conversion lives here and nowhere else.
        self.available_ttl = self._dspin(
            cfg.available_ttl_s / 60.0, 0.5, 60.0, 0.5, " min", decimals=1
        )
        self.available_ttl.setToolTip(
            "How long a trade stays in Ready to whisper before it's dropped.\n\n"
            "Counted from when it first appears, so it gets the whole of this\n"
            "however long its alert was up for.\n\n"
            "Other people are buying these too, so an old offer has usually gone\n"
            "already and messaging about it just wastes the whisper."
        )
        form.addRow("Trade stays listed for", self.available_ttl)

        self.awaiting_timeout = self._dspin(
            cfg.awaiting_timeout_s / 60.0, 0.0, 60.0, 1.0, " min", decimals=0
        )
        self.awaiting_timeout.setSpecialValueText("never")
        self.awaiting_timeout.setToolTip(
            "After you send a whisper, how long the app waits for you to say what\n"
            "happened before writing it down as no reply.\n\n"
            "Silence is the usual answer, so this saves you clicking. Set it to\n"
            "never if you'd rather record every one yourself.\n\n"
            "It also frees the money up: currency promised to a whisper is held\n"
            "against your bankroll until the trade is answered for."
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

        # Always editable, deliberately. This used to be disabled until the
        # checkbox above was ticked, and since the checkbox ships off, the field
        # was greyed out on a fresh install and the hotkey looked unassignable
        # (reported from the field 2026-07-30). Setting a key before enabling it
        # is a perfectly reasonable order to work in.
        self.hotkey = HotkeyEdit(cfg.trade_hotkey)
        self.hotkey.changed.connect(lambda _: self._revalidate())
        form.addRow("Hotkey", self.hotkey)

        # Whether the key is actually listening, and whether it has ever fired.
        # Two releases shipped a hotkey that registered, said so in the log and
        # then dropped every press, with nothing on screen able to tell that
        # from a user who hadn't pressed it. This dialog stays open while the
        # key is live, so pressing it here answers the question on the spot.
        self._hotkey_obj = hotkey
        self.hotkey_state = QLabel()
        self.hotkey_state.setWordWrap(True)
        self.hotkey_state.setStyleSheet(f"color: {muted_color(self)};")
        form.addRow("", self.hotkey_state)
        if hotkey is not None:
            hotkey.pressed.connect(self._hotkey_fired)
        self._refresh_hotkey_state()

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
        self.league.setCurrentIndex(0)   # automatic — the shipped default
        self.sweep_interval.setValue(d.sweep_interval_minutes)
        self.request_interval.setValue(d.request_interval_s)
        self.safety.setValue(round(d.rate_limit_safety_fraction * 100))
        self.retention.setValue(d.history_retention_days)
        self.sound.setChecked(d.alert_sound)
        self.always_on_top.setChecked(d.always_on_top)
        self.offer_window.setValue(d.offer_window_s)
        self.available_ttl.setValue(d.available_ttl_s / 60.0)
        self.awaiting_timeout.setValue(d.awaiting_timeout_s / 60.0)
        self.hotkey_enabled.setChecked(d.trade_hotkey_enabled)
        self.hotkey.set_binding(d.trade_hotkey)
        self.sweep_items.setValue(d.sweep_items)
        self.sweep_min_value.setValue(d.sweep_min_value_divines)
        self.min_profit.setValue(d.min_profit_divines)
        self.min_gap.setValue(d.min_gap_ratio)
        self.max_gap.setValue(d.max_gap_ratio)
        # Exclusions are the user's own curation, not a setting with a sensible
        # default — wiping a long list on a button labelled "restore defaults"
        # would be a nasty surprise. Clear All inside the picker still exists.
        self._revalidate()

    # ---------------------------------------------------------------- the hotkey

    def _refresh_hotkey_state(self) -> None:
        """Say whether the binding is live right now, in plain words."""
        hk = self._hotkey_obj
        if hk is None:
            self.hotkey_state.setText("")
            return
        if not hk.supported:
            self.hotkey_state.setText("Windows only — the hotkey does nothing here.")
        elif not hk.active:
            self.hotkey_state.setText(
                "Not listening. Tick the box above and press OK to bind it."
            )
        elif hk.presses:
            self.hotkey_state.setText(
                f"Listening — fired {hk.presses} time"
                f"{'s' if hk.presses != 1 else ''} since it was bound."
            )
        else:
            self.hotkey_state.setText(
                "Listening. Press it now to check — this line will say so."
            )

    def _hotkey_fired(self) -> None:
        presses = self._hotkey_obj.presses if self._hotkey_obj is not None else 1
        self.hotkey_state.setText(
            f"Just fired — the hotkey is working ({presses} so far)."
        )

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
        return self.hotkey.problem()

    def _fill_leagues(self) -> None:
        """Automatic first, then every league poe.ninja knows.

        A league saved in the config but missing from the list is kept as its own
        entry. That happens whenever poe.ninja is unreachable, and dropping the
        user's setting because we couldn't confirm it would silently move them
        to a different economy.
        """
        auto_label = "Automatic — follow the current league"
        if self._detected_league:
            auto_label = f"Automatic — currently {self._detected_league}"
        self.league.addItem(auto_label, None)
        for name in self._leagues:
            self.league.addItem(name, name)
        current = self._cfg.league
        if current and current not in self._leagues:
            self.league.addItem(f"{current} (not confirmed)", current)
        index = self.league.findData(current)
        self.league.setCurrentIndex(index if index >= 0 else 0)

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
            league=self.league.currentData(),
            sweep_interval_minutes=self.sweep_interval.value(),
            request_interval_s=self.request_interval.value(),
            history_retention_days=self.retention.value(),
            alert_sound=self.sound.isChecked(),
            always_on_top=self.always_on_top.isChecked(),
            offer_window_s=self.offer_window.value(),
            available_ttl_s=self.available_ttl.value() * 60.0,
            awaiting_timeout_s=self.awaiting_timeout.value() * 60.0,
            trade_hotkey=self.hotkey.binding(),
            trade_hotkey_enabled=self.hotkey_enabled.isChecked(),
            sweep_items=self.sweep_items.value(),
            sweep_min_value_divines=self.sweep_min_value.value(),
            min_profit_divines=self.min_profit.value(),
            min_gap_ratio=self.min_gap.value(),
            max_gap_ratio=self.max_gap.value(),
        )
