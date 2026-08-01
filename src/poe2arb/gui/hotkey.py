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

Windows-only, via `RegisterHotKey` through ctypes on a thread that pumps its own
messages. No new dependency, and a no-op everywhere else so the rest of the app
needn't care which platform it's on.

**Two shipped attempts at this failed, both by routing WM_HOTKEY through Qt.**
0.5.0 read `ctypes.wintypes.MSG` without importing the submodule, so every press
raised inside the filter's own catch-all. 0.6.0 fixed that import and the key
still did nothing in game *or* with the app focused (reported from the field
2026-07-31), which rules out anything to do with foreground windows and points
at the delivery path itself: `GlobalHotkey` inherited from both `QObject` and
`QAbstractNativeEventFilter`, and PySide6 does not reliably construct the C++
side of a second wrapper base, so the filter Qt was handed may never have been
called at all.

So Qt is out of the path entirely now. `RegisterHotKey(NULL, ...)` posts
WM_HOTKEY to *the thread that registered it*, so the thread registers the key
and runs its own `GetMessage` loop — the message never has to reach Qt's event
dispatcher to be seen. The thread is a `QThread` purely so its `pressed` signal
crosses back to the GUI thread through Qt's own queued-connection machinery.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading

from PySide6.QtCore import QObject, QThread, Signal

log = logging.getLogger(__name__)

# `ctypes.wintypes` is a submodule, not an attribute: `import ctypes` alone
# leaves `ctypes.wintypes` undefined. Imported here, once, and guarded because
# the module only exists on Windows.
if sys.platform == "win32":  # pragma: no cover - exercised only on Windows
    import ctypes.wintypes

    MSG = ctypes.wintypes.MSG
else:
    MSG = None

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

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


HOTKEY_ID = 0xA7B1  # arbitrary, only needs to be unique within this process


class _HotkeyPump(QThread):
    """Owns the hotkey registration and the message loop that receives it.

    Both have to happen on the same thread: `RegisterHotKey(NULL, ...)` posts
    WM_HOTKEY to the registering *thread's* queue, and only `GetMessage` on that
    thread will ever see it. Stopped by posting WM_QUIT to it, which is the one
    way to break `GetMessage` from outside.
    """

    pressed = Signal()
    failed = Signal(str)

    def __init__(self, mods: int, vk: int, parent=None):
        super().__init__(parent)
        self._mods = mods
        self._vk = vk
        self._thread_id = 0
        self.ok = False
        # Registration happens on the pump thread but `register` reports success
        # synchronously, so the caller waits for this.
        self.ready = threading.Event()
        # Diagnostics for the Settings dialog. Two shipped releases claimed a
        # live hotkey that did nothing, and nothing on screen could tell the
        # difference — so the count is kept and shown.
        self.presses = 0

    def run(self) -> None:  # pragma: no cover - Windows only
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        user32.GetMessageW.restype = ctypes.c_int
        self._thread_id = kernel32.GetCurrentThreadId()
        try:
            self.ok = bool(user32.RegisterHotKey(None, HOTKEY_ID, self._mods, self._vk))
        except Exception as e:  # noqa: BLE001 — a dead hotkey must not stop the app
            log.warning("could not register hotkey", exc_info=True)
            self.failed.emit(str(e))
            self.ready.set()
            return
        self.ready.set()
        if not self.ok:
            return
        msg = MSG()
        try:
            while True:
                # 0 is WM_QUIT, -1 an error; either way the loop is over.
                got = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if got in (0, -1):
                    break
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    self.presses += 1
                    self.pressed.emit()
        except Exception:  # noqa: BLE001 — never raise out of a thread
            log.warning("hotkey message loop failed", exc_info=True)
            self.failed.emit("the hotkey stopped listening — rebind it in Settings")
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    def stop(self) -> None:  # pragma: no cover - Windows only
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(  # type: ignore[attr-defined]
                self._thread_id, WM_QUIT, 0, 0
            )
        if not self.wait(2000):
            log.warning("hotkey thread did not stop; terminating")
            self.terminate()
            self.wait(500)


class GlobalHotkey(QObject):
    """Registers one system-wide hotkey and emits `pressed` when it fires.

    Silently inert on non-Windows platforms and whenever registration fails —
    typically because another application already owns the combination. The
    caller is told through `error` so it can say so rather than leaving the user
    pressing a dead key.
    """

    pressed = Signal()
    error = Signal(str)

    HOTKEY_ID = HOTKEY_ID

    def __init__(self, parent=None):
        super().__init__(parent)
        self._binding: str | None = None
        self._pump: _HotkeyPump | None = None

    @property
    def supported(self) -> bool:
        return sys.platform == "win32"

    @property
    def active(self) -> bool:
        return self._pump is not None and self._pump.ok

    @property
    def binding(self) -> str | None:
        return self._binding if self.active else None

    @property
    def presses(self) -> int:
        """How many times the key has fired since it was bound.

        Read by Settings, so "is this thing listening?" has an answer that does
        not require going into the game to find out.
        """
        return self._pump.presses if self._pump is not None else 0

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
        pump = _HotkeyPump(mods, vk, self)
        pump.pressed.connect(self.pressed)
        pump.failed.connect(self.error)
        pump.start()
        # Bounded: a pump that never reports back is a broken one, and blocking
        # the GUI thread on it would hang the window rather than the hotkey.
        if not pump.ready.wait(5.0) or not pump.ok:
            pump.stop()
            self.error.emit(
                f"{format_hotkey(text)} is already taken by another program — pick another."
            )
            return False
        self._pump = pump
        self._binding = text
        log.info("global hotkey registered: %s", format_hotkey(text))
        return True

    def unregister(self) -> None:
        pump, self._pump = self._pump, None
        self._binding = None
        if pump is not None:
            pump.stop()
