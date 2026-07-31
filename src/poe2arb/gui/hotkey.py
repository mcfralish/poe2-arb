"""A global hotkey that advances the trade queue and fills the clipboard.

The edge on a cross-venue trade is about a divine, so the tool only pays for
itself if an attempt costs almost nothing. The intended loop is: play, press
one key, `Enter` `Ctrl+V` `Enter` in chat, carry on playing. If they answer, go
trade; if not, nothing was lost but a keystroke.

**The hotkey only ever writes to the clipboard.** It sends no input to the game,
reads no game state, and watches no chat. That keeps this on the same side of
the line as the trade site's own copy-whisper button — the user still types and
still sends. Automating the send, or reacting to a reply, would be automating
play, which the app does not do.

Windows-only, via `RegisterHotKey` through ctypes plus a Qt native event filter.
No new dependency, and a no-op everywhere else so the rest of the app needn't
care which platform it's on.
"""

from __future__ import annotations

import ctypes
import logging
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

log = logging.getLogger(__name__)

# `ctypes.wintypes` is a submodule, not an attribute: `import ctypes` alone
# leaves `ctypes.wintypes` undefined. The event filter read `ctypes.wintypes.MSG`
# without it, so every keypress raised AttributeError inside the filter's own
# catch-all and was logged at debug and dropped — the hotkey registered
# successfully, said so in the log, and then did nothing at all when pressed
# (reported from the field 2026-07-31). Imported here, once, and guarded because
# the module only exists on Windows.
if sys.platform == "win32":  # pragma: no cover - exercised only on Windows
    import ctypes.wintypes

    MSG = ctypes.wintypes.MSG
else:
    MSG = None

WM_HOTKEY = 0x0312

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
# Stops the keypress being re-delivered while held down, which would otherwise
# advance the queue several times per press.
MOD_NOREPEAT = 0x4000

_MODIFIERS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "meta": MOD_WIN,
}

# Virtual-key codes for the keys worth binding. Deliberately not the full set:
# a hotkey is global, so offering the whole keyboard mostly offers new ways to
# break something else the player has bound.
_KEYS = {
    **{f"f{n}": 0x6F + n for n in range(1, 13)},          # F1-F12 -> 0x70-0x7B
    **{c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"},
    **{str(d): ord(str(d)) for d in range(10)},
    "space": 0x20,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "numpad0": 0x60,
    "numpad1": 0x61,
    "numpad2": 0x62,
    "numpad3": 0x63,
    "numpad4": 0x64,
    "numpad5": 0x65,
    "numpad6": 0x66,
    "numpad7": 0x67,
    "numpad8": 0x68,
    "numpad9": 0x69,
}

DEFAULT_HOTKEY = "ctrl+alt+d"


class HotkeyError(ValueError):
    pass


def parse_hotkey(text: str) -> tuple[int, int]:
    """"ctrl+alt+d" -> (modifiers, virtual-key). Raises HotkeyError if unusable.

    A bare key with no modifier is refused: this registers system-wide, so
    binding plain "d" would swallow the letter everywhere, including in chat.
    """
    parts = [p.strip().lower() for p in (text or "").split("+") if p.strip()]
    if not parts:
        raise HotkeyError("no hotkey given")
    *mod_names, key_name = parts
    mods = 0
    for name in mod_names:
        if name not in _MODIFIERS:
            raise HotkeyError(f"unknown modifier {name!r}")
        mods |= _MODIFIERS[name]
    if key_name in _MODIFIERS:
        raise HotkeyError("a hotkey needs a key, not just modifiers")
    if key_name not in _KEYS:
        raise HotkeyError(f"unsupported key {key_name!r}")
    if not mods:
        raise HotkeyError("add a modifier — a bare key would be captured everywhere")
    return mods | MOD_NOREPEAT, _KEYS[key_name]


def format_hotkey(text: str) -> str:
    """Tidy a binding for display: "CTRL + ALT + D"."""
    parts = [p.strip() for p in (text or "").split("+") if p.strip()]
    return " + ".join(p.upper() for p in parts)


class GlobalHotkey(QObject, QAbstractNativeEventFilter):
    """Registers one system-wide hotkey and emits `pressed` when it fires.

    Silently inert on non-Windows platforms and whenever registration fails —
    typically because another application already owns the combination. The
    caller is told through `error` so it can say so rather than leaving the user
    pressing a dead key.
    """

    pressed = Signal()
    error = Signal(str)

    HOTKEY_ID = 0xA7B1  # arbitrary, only needs to be unique within this process

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered = False
        self._binding: str | None = None
        self._filter_installed = False
        self._filter_failed = False

    @property
    def supported(self) -> bool:
        return sys.platform == "win32"

    @property
    def active(self) -> bool:
        return self._registered

    @property
    def binding(self) -> str | None:
        return self._binding if self._registered else None

    def register(self, text: str) -> bool:
        """Bind `text`. Returns True if the hotkey is now live."""
        self.unregister()
        if not self.supported:
            return False
        try:
            mods, vk = parse_hotkey(text)
        except HotkeyError as e:
            self.error.emit(str(e))
            return False
        try:
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            ok = bool(user32.RegisterHotKey(None, self.HOTKEY_ID, mods, vk))
        except Exception as e:  # noqa: BLE001 — a dead hotkey must not stop the app
            log.warning("could not register hotkey %s", text, exc_info=True)
            self.error.emit(str(e))
            return False
        if not ok:
            self.error.emit(
                f"{format_hotkey(text)} is already taken by another program — pick another."
            )
            return False
        if not self._filter_installed:
            from PySide6.QtCore import QCoreApplication

            app = QCoreApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self)
                self._filter_installed = True
        self._registered = True
        self._binding = text
        log.info("global hotkey registered: %s", format_hotkey(text))
        return True

    def unregister(self) -> None:
        if not self._registered or not self.supported:
            self._registered = False
            return
        try:
            ctypes.windll.user32.UnregisterHotKey(None, self.HOTKEY_ID)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            log.debug("could not unregister hotkey", exc_info=True)
        self._registered = False
        self._binding = None

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt naming)
        """Qt hands us every native message; we care about exactly one."""
        if not self._registered or MSG is None:
            return False, 0
        try:
            if event_type not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                return False, 0
            msg = MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                self.pressed.emit()
                # Not consumed: the message is ours by registration, and Qt has
                # no further use for it either way.
                return False, 0
        except Exception:  # noqa: BLE001 — this runs for every native message
            # Warning, not debug: this path silently disabled the hotkey for a
            # whole release. It runs per native message, so it is logged once
            # and then suppressed rather than flooding the file.
            if not self._filter_failed:
                self._filter_failed = True
                log.warning("hotkey event filter failed; hotkey is inert", exc_info=True)
                self.error.emit(
                    "the hotkey registered but its key events can't be read — "
                    "use the Accept button instead"
                )
        return False, 0
