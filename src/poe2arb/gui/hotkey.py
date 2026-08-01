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

**And the delivery path was never the bug.** Diagnosed 2026-08-01: none of the
three fixes above mattered, because `RegisterHotKey` was *returning 0* the whole
time, and Windows hands a hotkey to whoever asks first. **Why it was refused is
still unknown** — the first answer, "Sidekick owns the combination", came from a
test that quit Sidekick *and* rebound the key, and was withdrawn the same day
when the app registered fine with Sidekick running throughout. The live
candidates are the specific combination being taken by something, or a stale
poe2-arb process still holding it; see FINDINGS. Three releases could not see any
of this because the false return was swallowed silently, so this module now:

- calls `GetLastError` on a refusal and reports it, giving Settings a third
  state — *refused* — that the old "listening / not listening" line could not
  express;
- offers `probe()`, a trial register-then-unregister so a binding can be tested
  **before** it is saved. It runs on the pump thread, because `RegisterHotKey`
  is thread-affine and a key registered from the GUI thread posts WM_HOTKEY
  where nothing is listening — which is one line away from the original bug;
- retries on a timer, because ownership is first-come-first-served and whoever
  asks first keeps it until it exits. That makes a refusal a *transient* state
  as often as a permanent one, so a pre-check is necessary and *not* sufficient.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading

from PySide6.QtCore import QObject, QThread, QTimer, Signal

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


def describe_error(code: int) -> str:
    """A Windows error from `RegisterHotKey`, in words a player can act on.

    **Deliberately does not name a program.** An earlier draft blamed Sidekick,
    on a one-shot test that changed two variables at once and was withdrawn the
    same day — see FINDINGS, 2026-08-01. Naming a specific culprit on that
    evidence sends people to close something innocent, and the honest advice
    ("try a different combination") is the one that works whoever is holding it.
    """
    if code == ERROR_HOTKEY_ALREADY_REGISTERED:
        return (
            "another program already owns this combination, so Windows refused "
            "it. Overlays and trade tools claim hotkeys without always showing "
            "them in their own settings, so the quickest fix is a different "
            "combination — a rarely-used one with two modifiers."
        )
    return f"Windows refused to register it (error {code})."


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
# A separate id for the pre-check, so a trial can never collide with the live
# registration by identity — the collision that matters is over the *key*, and
# that one is handled by unregistering ourselves first. See `GlobalHotkey.probe`.
PROBE_ID = 0xA7B2

# `RegisterHotKey` sets this when another process already owns the combination.
# The one refusal worth naming: "already taken" is a fixable problem where a bare
# error number is not. Which program holds it is not knowable from here — Win32
# offers no "who owns this key?" query — so the message must not guess.
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# How often to try again for a key that was refused. Ownership is
# first-come-first-served, so the common way to lose the hotkey is a startup
# order that put someone else ahead of us — and the common way to get it back is
# for that program to close. Neither generates an event we can wait on, so this
# polls. A minute is far below the cost of noticing by hand and far above the
# cost of one syscall.
RETRY_INTERVAL_MS = 60_000


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
        # What Windows said when it refused. 0 means "not refused"; 1409 means
        # another program owns the combination, which is the case that has a
        # remedy. Kept so Settings can say which of those happened.
        self.last_error = 0
        # A binding to trial-register on this thread, set by `probe` before the
        # loop starts. `RegisterHotKey` is thread-affine, so the test has to
        # happen here or it tests the wrong thread's key table.
        self._probe: tuple[int, int] | None = None
        self.probe_error: int | None = None
        self.probed = threading.Event()
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
            if not self.ok:
                # The line whose absence cost three releases. A bare `return`
                # here is why "not listening" was the only thing the app could
                # ever say about a key another program had taken.
                self.last_error = kernel32.GetLastError()
        except Exception as e:  # noqa: BLE001 — a dead hotkey must not stop the app
            log.warning("could not register hotkey", exc_info=True)
            self.failed.emit(str(e))
            self.ready.set()
            return
        self.ready.set()
        if not self.ok:
            log.warning(
                "RegisterHotKey refused (GetLastError=%d: %s)",
                self.last_error, describe_error(self.last_error),
            )
            self.failed.emit(describe_error(self.last_error))
            return
        msg = MSG()
        try:
            while True:
                if self._probe is not None:
                    self._run_probe(user32, kernel32)
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

    def _run_probe(self, user32, kernel32) -> None:  # pragma: no cover - Windows only
        """Trial-register the pending binding, then give it straight back."""
        mods, vk = self._probe
        self._probe = None
        try:
            if user32.RegisterHotKey(None, PROBE_ID, mods, vk):
                user32.UnregisterHotKey(None, PROBE_ID)
                self.probe_error = 0
            else:
                self.probe_error = kernel32.GetLastError()
        except Exception:  # noqa: BLE001 — a failed test must not kill the pump
            log.warning("hotkey probe failed", exc_info=True)
            self.probe_error = None
        finally:
            self.probed.set()

    def probe(self, mods: int, vk: int, timeout: float = 2.0) -> int | None:
        """Ask the pump thread whether `mods`+`vk` can be registered.

        Returns 0 if it can, a Windows error code if it cannot, and None if the
        pump never answered. Queued rather than called directly: the answer is
        only meaningful on the thread that would own the key.
        """
        self.probe_error = None
        self.probed.clear()
        self._probe = (mods, vk)
        # Wake `GetMessage`, which is otherwise blocked until the key is pressed.
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(  # type: ignore[attr-defined]
                self._thread_id, 0x0000, 0, 0        # WM_NULL
            )
        if not self.probed.wait(timeout):
            return None
        return self.probe_error

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
    # The binding came back. Emitted by the retry, so the UI can stop saying
    # the key is dead without the user having to open Settings to find out.
    recovered = Signal(str)

    HOTKEY_ID = HOTKEY_ID

    def __init__(self, parent=None):
        super().__init__(parent)
        self._binding: str | None = None
        self._pump: _HotkeyPump | None = None
        # What was asked for but refused, and why. Distinct from "nothing is
        # bound": a refused key is a live problem with a remedy, and the app
        # used to render both as "Not listening…".
        self._refused: str | None = None
        self._refused_error = 0
        self._retry: QTimer | None = None

    @property
    def supported(self) -> bool:
        return sys.platform == "win32"

    @property
    def active(self) -> bool:
        return self._pump is not None and self._pump.ok

    @property
    def refused(self) -> str | None:
        """The binding Windows would not give us, or None."""
        return self._refused

    @property
    def refusal_reason(self) -> str:
        return describe_error(self._refused_error) if self._refused else ""

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

    def register(self, text: str, *, retry: bool = True) -> bool:
        """Bind `text`. Returns True if the hotkey is now live.

        A refusal is remembered rather than forgotten: `refused` holds the
        binding, `refusal_reason` says why, and unless `retry` is off the
        registration is attempted again on a timer. Ownership is
        first-come-first-served, so a key lost to startup order comes back on
        its own when the other program closes — the user should not have to
        know that reopening Settings is what fixes it.
        """
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
        answered = pump.ready.wait(5.0)
        if not answered or not pump.ok:
            self._refused = text
            self._refused_error = pump.last_error if answered else 0
            pump.stop()
            # `failed` has already carried the detail out of the pump; this says
            # which binding it was about.
            self.error.emit(
                f"{format_hotkey(text)} is not listening — {self.refusal_reason}"
            )
            if retry:
                self._schedule_retry()
            return False
        self._pump = pump
        self._binding = text
        self._refused = None
        self._refused_error = 0
        self._stop_retry()
        log.info("global hotkey registered: %s", format_hotkey(text))
        return True

    def probe(self, text: str) -> str:
        """Test `text` without keeping it. "" if it is free, else why not.

        Three traps, all of them load-bearing:

        (a) **A key we already hold must not be reported as taken** — it is
            taken, by us. Testing the live binding would fail every hotkey that
            is currently working, so that case answers "free" up front.
        (b) It is a **race** — another program can claim the key between this
            answer and the save — so `register` still has to report failure.
            This buys a better message, not a guarantee.
        (c) The trial runs **on the pump thread**, because `RegisterHotKey` is
            thread-affine. Testing it from the GUI thread would answer a
            different question from the one that matters, which is one line
            away from the bug this whole thing is about.
        """
        if not self.supported:
            return ""
        try:
            mods, vk = parse_hotkey(text)
        except HotkeyError as e:
            return str(e)
        if self._binding == text:
            return ""     # already ours and working; nothing to find out
        pump = self._pump
        if pump is None or not pump.ok:
            # Nothing of ours is holding a key, so a throwaway pump can answer.
            # Registered and released on its own thread, exactly like the real
            # one — see (c).
            trial = _HotkeyPump(mods, vk, self)
            trial.start()
            answered = trial.ready.wait(5.0)
            code = 0 if (answered and trial.ok) else (trial.last_error if answered else 0)
            trial.stop()
            return "" if code == 0 else describe_error(code)
        code = pump.probe(mods, vk)
        if code is None:
            return ""     # the pump never answered; don't block a save on that
        return "" if code == 0 else describe_error(code)

    def unregister(self) -> None:
        pump, self._pump = self._pump, None
        self._binding = None
        self._stop_retry()
        if pump is not None:
            pump.stop()

    # --- getting a refused key back ----------------------------------------

    def _schedule_retry(self) -> None:
        if self._retry is None:
            self._retry = QTimer(self)
            self._retry.setInterval(RETRY_INTERVAL_MS)
            self._retry.timeout.connect(self._try_again)
        self._retry.start()

    def _stop_retry(self) -> None:
        if self._retry is not None:
            self._retry.stop()

    def _try_again(self) -> None:
        """Have another go at a refused binding, quietly."""
        text = self._refused
        if text is None or self.active:
            self._stop_retry()
            return
        # `retry=False` so a failure re-arms nothing: the timer is already
        # running and re-entering `register` would restart it each tick.
        if self.register(text, retry=False):
            log.info("global hotkey recovered: %s", format_hotkey(text))
            self.recovered.emit(text)
        else:
            self._schedule_retry()
