"""A hotkey field you set by pressing the keys, not by typing their names.

Typing "ctrl+shift+f9" into a text box asks the user to know this app's spelling
of every key — whether it wants "ctrl" or "control", "pageup" or "page_up" — and
gives no feedback until the dialog is saved. Recording the real keystroke removes
the vocabulary problem entirely: the widget writes the canonical string itself.

The canonical strings this produces are exactly the ones `hotkey.parse_hotkey`
accepts, and `_QT_KEYS` below is derived from `hotkey._KEYS` at import so the two
cannot drift. A key Windows will not let us bind is refused *while recording*,
which is the only moment the user is thinking about it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from .hotkey import _KEYS, DEFAULT_HOTKEY, HotkeyError, format_hotkey, parse_hotkey

# Qt keycode -> the name hotkey._KEYS uses. Built from that table rather than
# restated, so adding a bindable key there makes it recordable here for free.
_QT_KEYS: dict[int, str] = {}
for _n in range(1, 13):
    _QT_KEYS[getattr(Qt.Key, f"Key_F{_n}")] = f"f{_n}"
for _c in "abcdefghijklmnopqrstuvwxyz":
    _QT_KEYS[getattr(Qt.Key, f"Key_{_c.upper()}")] = _c
for _d in range(10):
    _QT_KEYS[getattr(Qt.Key, f"Key_{_d}")] = str(_d)
_QT_KEYS.update({
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup",
    Qt.Key.Key_PageDown: "pagedown",
})
# Anything mapped must actually be bindable, or recording would offer a key that
# fails on save.
_QT_KEYS = {k: v for k, v in _QT_KEYS.items() if v in _KEYS}

# Modifier order is fixed so the same combination always produces the same
# string — a binding that round-trips differently than it was recorded would
# look like the app forgot it.
_MOD_ORDER = (
    (Qt.KeyboardModifier.ControlModifier, "ctrl"),
    (Qt.KeyboardModifier.AltModifier, "alt"),
    (Qt.KeyboardModifier.ShiftModifier, "shift"),
    (Qt.KeyboardModifier.MetaModifier, "win"),
)

_BARE_MODIFIERS = {
    Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift,
    Qt.Key.Key_Meta, Qt.Key.Key_AltGr,
}


def binding_from_event(event: QKeyEvent) -> str | None:
    """The canonical binding string for a keypress, or None if it isn't one yet.

    None covers the normal case of a modifier being held before its key arrives:
    the user pressing Ctrl is mid-gesture, not making a mistake, so the widget
    keeps listening rather than complaining.
    """
    key = Qt.Key(event.key())
    if key in _BARE_MODIFIERS:
        return None
    name = _QT_KEYS.get(key)
    if name is None:
        return None
    mods = event.modifiers()
    parts = [label for flag, label in _MOD_ORDER if mods & flag]
    if not parts:
        return None  # bare key: refused, and parse_hotkey says why
    return "+".join([*parts, name])


class HotkeyEdit(QWidget):
    """Shows the current binding; click to record a new one.

    Grabs the keyboard while recording so Tab, Space and the arrow keys reach
    `keyPressEvent` instead of being eaten by Qt's focus handling — those are
    keys people genuinely bind, and a field that silently ignores them looks
    broken.
    """

    changed = Signal(str)

    def __init__(self, binding: str = DEFAULT_HOTKEY, parent=None):
        super().__init__(parent)
        self._binding = binding or DEFAULT_HOTKEY
        self._recording = False
        self._problem = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton()
        self.button.setCheckable(True)
        self.button.setToolTip(
            "Click, then press the key combination you want.\n"
            "Needs at least one of Ctrl, Alt, Shift or Win — a bare key would be\n"
            "captured everywhere, including in chat."
        )
        self.button.clicked.connect(self._toggle_recording)
        layout.addWidget(self.button, stretch=1)

        self.clear_button = QPushButton("Reset")
        self.clear_button.setToolTip(f"Put this back to {format_hotkey(DEFAULT_HOTKEY)}.")
        self.clear_button.clicked.connect(lambda: self.set_binding(DEFAULT_HOTKEY))
        layout.addWidget(self.clear_button)

        self._refresh()

    # --- state ------------------------------------------------------------

    def binding(self) -> str:
        return self._binding

    def set_binding(self, binding: str) -> None:
        if not binding:
            return
        self._binding = binding
        self._problem = ""
        self._stop_recording()
        self._refresh()
        self.changed.emit(binding)

    def problem(self) -> str:
        """Why the shown binding is unusable, or "" if it's fine."""
        if self._problem:
            return self._problem
        try:
            parse_hotkey(self._binding)
        except HotkeyError as e:
            return str(e)
        return ""

    # --- recording --------------------------------------------------------

    def _toggle_recording(self, on: bool) -> None:
        if on:
            self._recording = True
            self._problem = ""
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            self.grabKeyboard()
        else:
            self._stop_recording()
        self._refresh()

    def _stop_recording(self) -> None:
        if self._recording:
            self.releaseKeyboard()
        self._recording = False
        blocked = self.button.blockSignals(True)
        self.button.setChecked(False)
        self.button.blockSignals(blocked)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt naming)
        if not self._recording:
            super().keyPressEvent(event)
            return
        if Qt.Key(event.key()) == Qt.Key.Key_Escape:
            self._stop_recording()   # cancel, keeping whatever was already set
            self._refresh()
            event.accept()
            return
        binding = binding_from_event(event)
        if binding is None:
            # Still mid-gesture, or a key we can't bind. Only say so once the
            # user has actually pressed something that isn't a modifier.
            if Qt.Key(event.key()) not in _BARE_MODIFIERS:
                self._problem = (
                    "add a modifier — a bare key would be captured everywhere"
                    if not event.modifiers()
                    else "that key can't be bound as a global hotkey"
                )
                self._refresh()
            event.accept()
            return
        self.set_binding(binding)
        event.accept()

    def _refresh(self) -> None:
        if self._recording:
            self.button.setText("Press a key combination…  (Esc to cancel)")
        else:
            self.button.setText(format_hotkey(self._binding) or "Click to set")
        self.button.setChecked(self._recording)
