"""Global hotkey parsing and registration behaviour.

Registration itself is Windows-only and untestable here, so these cover the
parsing rules and the guarantee that everything degrades quietly elsewhere.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from poe2arb.gui.hotkey import (  # noqa: E402
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    GlobalHotkey,
    HotkeyError,
    format_hotkey,
    parse_hotkey,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_parses_modifiers_and_key():
    mods, vk = parse_hotkey("ctrl+alt+d")
    assert mods & MOD_CONTROL and mods & MOD_ALT
    assert vk == ord("D")


def test_norepeat_is_always_set():
    """Held keys would otherwise advance the queue dozens of times per press."""
    mods, _ = parse_hotkey("ctrl+shift+f9")
    assert mods & MOD_NOREPEAT


def test_function_keys_map_correctly():
    assert parse_hotkey("ctrl+f1")[1] == 0x70
    assert parse_hotkey("ctrl+f12")[1] == 0x7B


def test_case_and_spacing_are_forgiven():
    assert parse_hotkey("  CTRL + Shift + D ") == parse_hotkey("ctrl+shift+d")


def test_aliases_for_the_same_modifier():
    assert parse_hotkey("control+d") == parse_hotkey("ctrl+d")
    assert parse_hotkey("win+d") == parse_hotkey("super+d")


def test_a_bare_key_is_refused():
    """It registers system-wide — plain 'd' would be swallowed everywhere, chat included."""
    with pytest.raises(HotkeyError, match="modifier"):
        parse_hotkey("d")


def test_modifiers_alone_are_refused():
    with pytest.raises(HotkeyError, match="needs a key"):
        parse_hotkey("ctrl+alt")


@pytest.mark.parametrize("text", ["", "   ", "ctrl+nope", "wat+d", "+"])
def test_unusable_bindings_raise(text):
    with pytest.raises(HotkeyError):
        parse_hotkey(text)


def test_format_is_readable():
    assert format_hotkey("ctrl+alt+d") == "CTRL + ALT + D"
    assert format_hotkey("") == ""


def test_shift_is_supported_as_a_modifier():
    mods, _ = parse_hotkey("ctrl+shift+1")
    assert mods & MOD_SHIFT and mods & MOD_CONTROL


# --- degradation -----------------------------------------------------------

def test_registration_is_a_no_op_off_windows(qapp, monkeypatch):
    monkeypatch.setattr("poe2arb.gui.hotkey.sys.platform", "linux")
    hk = GlobalHotkey()
    assert hk.supported is False
    assert hk.register("ctrl+alt+d") is False
    assert hk.active is False
    assert hk.binding is None
    hk.unregister()  # must not raise


def test_a_bad_binding_reports_rather_than_raises(qapp, monkeypatch):
    monkeypatch.setattr("poe2arb.gui.hotkey.sys.platform", "win32")
    seen = []
    hk = GlobalHotkey()
    hk.error.connect(seen.append)
    assert hk.register("nonsense") is False
    assert seen and "unsupported key" in seen[0]


def test_a_taken_combination_reports_which_one(qapp, monkeypatch):
    """The usual failure: another program already owns the keys."""
    import ctypes

    monkeypatch.setattr("poe2arb.gui.hotkey.sys.platform", "win32")

    class FakeUser32:
        def RegisterHotKey(self, *a):  # noqa: N802
            return 0

        def UnregisterHotKey(self, *a):  # noqa: N802
            return 1

    class FakeWindll:
        user32 = FakeUser32()

    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)
    seen = []
    hk = GlobalHotkey()
    hk.error.connect(seen.append)
    assert hk.register("ctrl+alt+d") is False
    assert seen and "already taken" in seen[0]
    assert "CTRL + ALT + D" in seen[0]


def test_a_successful_registration_reports_its_binding(qapp, monkeypatch):
    import ctypes

    monkeypatch.setattr("poe2arb.gui.hotkey.sys.platform", "win32")

    class FakeUser32:
        def RegisterHotKey(self, *a):  # noqa: N802
            return 1

        def UnregisterHotKey(self, *a):  # noqa: N802
            return 1

    class FakeWindll:
        user32 = FakeUser32()

    monkeypatch.setattr(ctypes, "windll", FakeWindll(), raising=False)
    hk = GlobalHotkey()
    assert hk.register("ctrl+alt+d") is True
    assert hk.active and hk.binding == "ctrl+alt+d"
    hk.unregister()
    assert not hk.active and hk.binding is None


# --- the Settings dialog ---------------------------------------------------

def test_settings_rejects_an_unusable_hotkey(qapp):
    """A bad binding would otherwise leave the user pressing a dead key."""
    from PySide6.QtWidgets import QDialogButtonBox

    from poe2arb.config import Config
    from poe2arb.gui.settings_dialog import SettingsDialog

    d = SettingsDialog(Config(trade_hotkey_enabled=True, trade_hotkey="ctrl+alt+d"))
    ok = d.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok.isEnabled()

    # A config carrying a bare key can't be recorded any more, but it can still
    # be loaded from a hand-edited file, so it must still be refused.
    d.hotkey.set_binding("d")
    qapp.processEvents()
    assert not ok.isEnabled()

    d.hotkey.set_binding("ctrl+shift+f9")
    qapp.processEvents()
    assert ok.isEnabled()


def test_a_disabled_hotkey_is_not_validated(qapp):
    from PySide6.QtWidgets import QDialogButtonBox

    from poe2arb.config import Config
    from poe2arb.gui.settings_dialog import SettingsDialog

    d = SettingsDialog(Config(trade_hotkey_enabled=False, trade_hotkey="nonsense"))
    qapp.processEvents()
    assert d.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_the_hotkey_can_be_set_before_it_is_enabled(qapp):
    """It shipped greyed out until the checkbox was ticked, so it read as broken.

    The checkbox defaults to off, so on a fresh install the field was disabled
    and the hotkey looked unassignable (reported from the field 2026-07-30).
    """
    from poe2arb.config import Config
    from poe2arb.gui.settings_dialog import SettingsDialog

    d = SettingsDialog(Config(trade_hotkey_enabled=False))
    assert d.hotkey.isEnabled()


def test_hotkey_round_trips_through_the_dialog(qapp):
    from poe2arb.config import Config
    from poe2arb.gui.settings_dialog import SettingsDialog

    d = SettingsDialog(Config())
    d.hotkey_enabled.setChecked(True)
    d.hotkey.set_binding("ctrl+shift+t")
    cfg = d.result_config()
    assert cfg.trade_hotkey == "ctrl+shift+t"
    assert cfg.trade_hotkey_enabled is True


def test_settings_changes_reach_the_running_queue(qapp, monkeypatch):
    """A rebind or a shortened countdown that needed a restart would look broken.

    Called unbound against a stand-in: MainWindow is a QWidget and cannot be
    instantiated without building the whole window, but the method under test
    only touches attributes.
    """
    from types import SimpleNamespace

    import poe2arb.gui.main_window as mw
    from poe2arb.config import Config

    monkeypatch.setattr("poe2arb.gui.hotkey.sys.platform", "linux")

    panel = SimpleNamespace(
        set_hotkey_hint=lambda *_a: None, refresh=lambda *_a, **_k: None
    )
    window = SimpleNamespace(
        cfg=Config(
            trade_hotkey="ctrl+shift+f9", trade_hotkey_enabled=True,
            offer_window_s=30.0, available_ttl_s=120.0, awaiting_timeout_s=600.0,
        ),
        trade_queue=SimpleNamespace(
            offer_window_s=15.0, available_ttl_s=60.0, awaiting_timeout_s=300.0,
            set_bankroll=lambda *_a: None,
        ),
        _hotkey=GlobalHotkey(),
        queue_panel=panel,
        sweep=panel,
        _log=lambda *_a: None,
        _apply_always_on_top=lambda: None,
    )
    before = Config(trade_hotkey="ctrl+alt+d", trade_hotkey_enabled=True)

    mw.MainWindow._apply_queue_settings(window, before)

    assert window.trade_queue.offer_window_s == 30.0
    assert window.trade_queue.available_ttl_s == 120.0
    assert window.trade_queue.awaiting_timeout_s == 600.0


# --- recording a binding by pressing it ------------------------------------

def _press(key, mods=None):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    return QKeyEvent(
        QEvent.Type.KeyPress, key,
        mods if mods is not None else Qt.KeyboardModifier.NoModifier,
    )


def test_a_keypress_becomes_a_canonical_binding():
    """What the widget records must be what parse_hotkey accepts."""
    from PySide6.QtCore import Qt

    from poe2arb.gui.hotkey_edit import binding_from_event
    from poe2arb.gui.hotkey import parse_hotkey

    mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
    binding = binding_from_event(_press(Qt.Key.Key_D, mods))
    assert binding == "ctrl+alt+d"
    parse_hotkey(binding)  # must not raise


def test_modifier_order_is_fixed_regardless_of_press_order():
    """A binding that round-trips differently looks like the app forgot it."""
    from PySide6.QtCore import Qt

    from poe2arb.gui.hotkey_edit import binding_from_event

    mods = (
        Qt.KeyboardModifier.ShiftModifier
        | Qt.KeyboardModifier.ControlModifier
        | Qt.KeyboardModifier.AltModifier
    )
    assert binding_from_event(_press(Qt.Key.Key_F9, mods)) == "ctrl+alt+shift+f9"


def test_holding_a_modifier_alone_is_not_yet_a_binding():
    """Pressing Ctrl first is the normal gesture, not an error."""
    from PySide6.QtCore import Qt

    from poe2arb.gui.hotkey_edit import binding_from_event

    for key in (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta):
        assert binding_from_event(_press(key)) is None


def test_recording_a_bare_key_is_refused():
    """It registers system-wide, so plain 'd' would be swallowed in chat."""
    from PySide6.QtCore import Qt

    from poe2arb.gui.hotkey_edit import binding_from_event

    assert binding_from_event(_press(Qt.Key.Key_D)) is None


def test_recording_updates_the_widget_and_reports_no_problem(qapp):
    from PySide6.QtCore import Qt

    from poe2arb.gui.hotkey_edit import HotkeyEdit

    w = HotkeyEdit("ctrl+alt+d")
    w._toggle_recording(True)
    w.keyPressEvent(_press(Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier
                           | Qt.KeyboardModifier.ShiftModifier))
    qapp.processEvents()
    assert w.binding() == "ctrl+shift+k"
    assert w.problem() == ""
    assert not w._recording      # a successful capture stops listening


def test_escape_cancels_recording_and_keeps_the_old_binding(qapp):
    from PySide6.QtCore import Qt

    from poe2arb.gui.hotkey_edit import HotkeyEdit

    w = HotkeyEdit("ctrl+alt+d")
    w._toggle_recording(True)
    w.keyPressEvent(_press(Qt.Key.Key_Escape))
    qapp.processEvents()
    assert w.binding() == "ctrl+alt+d"
    assert not w._recording
