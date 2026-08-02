"""Settings: every sweep knob is reachable, and round-trips."""

from __future__ import annotations

import dataclasses

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from poe2arb.config import Config  # noqa: E402
from poe2arb.gui.settings_dialog import SettingsDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(qapp):
    return SettingsDialog(Config())


def section_titles(dialog):
    return [
        label.text()
        for label in dialog.findChildren(QLabel)
        if label.font().bold() and label.text()
    ]


class TestSections:
    def test_the_form_is_grouped(self, dialog):
        assert section_titles(dialog) == [
            "General", "Finding trades", "The trade queue",
        ]

    def test_nothing_from_the_triangular_search_is_left(self, dialog):
        """It was deleted outright — no loop length, no graph size, no margin."""
        for gone in ("threshold", "margin", "max_currencies", "max_cycle_len",
                     "liquidity", "max_value", "interval",
                     "sale_currency"):
            assert not hasattr(dialog, gone), gone


class TestSweepSettings:
    """These existed in the config file and had no UI at all before."""

    def test_defaults_are_shown(self, dialog):
        d = Config()
        assert dialog.sweep_items.value() == d.sweep_items
        assert dialog.sweep_interval.value() == pytest.approx(d.sweep_interval_minutes)
        assert dialog.min_gap.value() == pytest.approx(d.min_gap_ratio)
        assert dialog.max_gap.value() == pytest.approx(d.max_gap_ratio)

    def test_edits_survive_into_the_saved_config(self, dialog):
        dialog.sweep_items.setValue(40)
        dialog.sweep_min_value.setValue(3.5)
        dialog.min_profit.setValue(1.0)
        dialog.sweep_interval.setValue(25.0)
        dialog.min_gap.setValue(1.1)
        dialog.max_gap.setValue(2.0)

        cfg = dialog.result_config()
        assert cfg.sweep_items == 40
        assert cfg.sweep_min_value_divines == pytest.approx(3.5)
        assert cfg.min_profit_divines == pytest.approx(1.0)
        assert cfg.sweep_interval_minutes == pytest.approx(25.0)
        assert cfg.min_gap_ratio == pytest.approx(1.1)
        assert cfg.max_gap_ratio == pytest.approx(2.0)

    def test_the_sweep_cadence_is_editable(self, dialog):
        """Find trades runs on a loop; the gap between runs has to be settable."""
        assert dialog.sweep_interval.isEnabled()


class TestRoundTrip:
    def test_untouched_settings_come_back_unchanged(self, qapp):
        """Opening Settings and pressing OK must be a no-op."""
        cfg = Config(
            league="Runes of Aldur", sweep_items=42, sale_currency="divine",
            min_gap_ratio=1.08, max_gap_ratio=1.9, bankroll_exalted=9000.0,
            risk_appetite=0.3, sweep_interval_minutes=25.0,
        )
        assert SettingsDialog(cfg).result_config() == cfg

    def test_fields_with_no_widget_are_carried_through(self, qapp):
        """The dialog edits a subset; the rest must not be reset to defaults."""
        cfg = Config(bankroll_divines=120.0, risk_appetite=0.75,
                     sale_currency="divine")
        result = SettingsDialog(cfg).result_config()
        assert result.bankroll_divines == 120.0
        assert result.risk_appetite == 0.75
        # Settlement moved to the Opportunities tab; Settings must not reset it.
        assert result.sale_currency == "divine"

    def test_restore_defaults_covers_the_sweep_settings_too(self, qapp):
        cfg = Config(sweep_items=11, max_gap_ratio=8.0, sweep_interval_minutes=99.0)
        dialog = SettingsDialog(cfg)
        dialog.restore_defaults()
        result = dialog.result_config()
        default = Config()
        for name in ("sweep_items", "max_gap_ratio", "sweep_interval_minutes",
                     "min_gap_ratio", "min_profit_divines",
                     "sweep_min_value_divines"):
            assert getattr(result, name) == getattr(default, name), name

    def test_restore_defaults_leaves_untouched_fields_alone(self, qapp):
        """It restores the page, not the whole config — bankroll isn't here."""
        dialog = SettingsDialog(Config(bankroll_exalted=9000.0))
        dialog.restore_defaults()
        assert dialog.result_config().bankroll_exalted == 9000.0

    def test_every_edited_field_is_a_real_config_field(self, dialog):
        names = {f.name for f in dataclasses.fields(Config)}
        changed = {
            f.name for f in dataclasses.fields(Config)
            if getattr(dialog.result_config(), f.name) != getattr(Config(), f.name)
        }
        assert changed <= names


class TestLeague:
    """A dropdown, because a typo prices trades against the wrong economy."""

    def test_automatic_is_the_default_and_saves_as_none(self, qapp):
        d = SettingsDialog(Config(), leagues=["Runes of Aldur", "Standard"])
        assert d.league.currentIndex() == 0
        assert d.result_config().league is None

    def test_the_detected_league_is_named_in_the_automatic_entry(self, qapp):
        d = SettingsDialog(
            Config(), leagues=["Runes of Aldur", "Standard"],
            detected_league="Runes of Aldur",
        )
        assert "Runes of Aldur" in d.league.itemText(0)

    def test_a_configured_league_is_preselected(self, qapp):
        d = SettingsDialog(
            Config(league="Standard"), leagues=["Runes of Aldur", "Standard"]
        )
        assert d.league.currentData() == "Standard"
        assert d.result_config().league == "Standard"

    def test_an_unconfirmed_league_is_kept_not_dropped(self, qapp):
        """poe.ninja being unreachable must not silently move the user's league."""
        d = SettingsDialog(Config(league="Some Old League"), leagues=[])
        assert d.league.currentData() == "Some Old League"
        assert d.result_config().league == "Some Old League"

    def test_restore_defaults_returns_to_automatic(self, qapp):
        d = SettingsDialog(
            Config(league="Standard"), leagues=["Runes of Aldur", "Standard"]
        )
        d.restore_defaults()
        assert d.result_config().league is None


class TestTheQueueTimersAreInMinutes:
    """Reading "600 s" off a spin box to work out whether it's long enough is
    arithmetic the dialog should be doing. The config stays in seconds."""

    def test_the_widgets_show_minutes(self, dialog):
        assert dialog.available_ttl.suffix().strip() == "min"
        assert dialog.awaiting_timeout.suffix().strip() == "min"
        assert dialog.available_ttl.value() == 5.0     # 300 s
        assert dialog.awaiting_timeout.value() == 10.0  # 600 s

    def test_saving_converts_back_to_seconds(self, dialog):
        dialog.available_ttl.setValue(2.5)
        dialog.awaiting_timeout.setValue(15)
        cfg = dialog.result_config()
        assert cfg.available_ttl_s == 150.0
        assert cfg.awaiting_timeout_s == 900.0

    def test_an_untouched_dialog_round_trips_exactly(self, dialog):
        """A dialog opened and OK'd must not quietly change the saved values."""
        cfg = dialog.result_config()
        assert cfg.available_ttl_s == Config().available_ttl_s
        assert cfg.awaiting_timeout_s == Config().awaiting_timeout_s

    def test_zero_still_means_never(self, dialog):
        dialog.awaiting_timeout.setValue(0)
        assert dialog.awaiting_timeout.specialValueText() == "never"
        assert dialog.result_config().awaiting_timeout_s == 0.0

    def test_the_alert_window_is_gone(self, dialog):
        """0.9.0 removed the toast, so there is no window to set."""
        assert not hasattr(dialog, "offer_window")


class TestAlwaysOnTop:
    def test_it_is_offered_and_defaults_off(self, dialog):
        assert dialog.always_on_top.isChecked() is False

    def test_it_round_trips(self, dialog):
        dialog.always_on_top.setChecked(True)
        assert dialog.result_config().always_on_top is True

    def test_restore_defaults_clears_it(self, dialog):
        dialog.always_on_top.setChecked(True)
        dialog.restore_defaults()
        assert dialog.always_on_top.isChecked() is False


# --- the hotkey has three states, not two ------------------------------------
# Diagnosed 2026-08-01: a key Windows had *refused* rendered as "Not listening",
# which is identical to what an unbound key says. That ambiguity is why the real
# cause survived three releases, and a wrong answer to it survived half a day.


class _FakeHotkey:
    """Enough of `GlobalHotkey` for the state line and the OK gate."""

    supported = True

    def __init__(self, *, active=False, refused=None, reason="", probe=""):
        self.active = active
        self.refused = refused
        self.refusal_reason = reason
        self.presses = 0
        self._probe = probe
        self.probed: list[str] = []

    def probe(self, binding):
        self.probed.append(binding)
        return self._probe

    class _Sig:
        @staticmethod
        def connect(_):
            pass

    pressed = _Sig()


def test_a_refused_binding_says_so_and_not_just_not_listening(qapp):
    hk = _FakeHotkey(refused="ctrl+shift+c", reason="another program already owns it.")
    d = SettingsDialog(Config(), hotkey=hk)
    text = d.hotkey_state.text()
    assert "Refused" in text
    assert "CTRL + SHIFT + C" in text
    assert "another program already owns it." in text
    assert "Not listening" not in text


def test_an_unbound_key_still_reads_as_not_listening(qapp):
    d = SettingsDialog(Config(), hotkey=_FakeHotkey())
    assert "Not listening" in d.hotkey_state.text()


def test_a_live_key_reads_as_listening(qapp):
    d = SettingsDialog(Config(), hotkey=_FakeHotkey(active=True))
    assert "Listening" in d.hotkey_state.text()


def test_a_binding_windows_would_refuse_blocks_the_save(qapp):
    """The maintainer's call: find out before the setting saves clean."""
    from PySide6.QtWidgets import QDialogButtonBox

    hk = _FakeHotkey(probe="another program already owns this combination")
    d = SettingsDialog(Config(), hotkey=hk)
    d.hotkey_enabled.setChecked(True)
    d._revalidate()
    ok = d.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    assert hk.probed


def test_a_free_binding_is_saveable(qapp):
    from PySide6.QtWidgets import QDialogButtonBox

    d = SettingsDialog(Config(), hotkey=_FakeHotkey())
    d.hotkey_enabled.setChecked(True)
    d._revalidate()
    assert d.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_the_pre_check_is_skipped_when_the_hotkey_is_off(qapp):
    """No point testing a key that is not going to be bound."""
    hk = _FakeHotkey(probe="taken")
    d = SettingsDialog(Config(), hotkey=hk)
    d.hotkey_enabled.setChecked(False)
    d._revalidate()
    assert hk.probed == []
