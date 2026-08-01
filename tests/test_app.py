"""Startup ordering in `app.main`.

One thing here is worth a test file of its own: **the hotkey must be claimed
after the install handover, not before.** `maybe_offer_install` can launch the
installed copy and tell this process to exit, so an upgrade runs two poe2-arb
processes a second apart. A global hotkey belongs to a process and Windows
hands it to whoever asks first, so the copy that was leaving used to take the
key and the copy that was staying got `ERROR_HOTKEY_ALREADY_REGISTERED` —
the app locking itself out of its own hotkey on every update. Caught in the
0.8.0 log on 2026-08-01; see FINDINGS.

`main()` is driven with fakes rather than a real QApplication: the point of
these is the order of four calls, and building a second QApplication in a suite
that already has one is its own problem.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

import PySide6.QtWidgets  # noqa: E402

from poe2arb.config import Config  # noqa: E402
from poe2arb.gui import app as gui_app  # noqa: E402
from poe2arb.gui import install_prompt, main_window  # noqa: E402


class _FakeSignal:
    def __init__(self):
        self.connected = []

    def connect(self, slot):
        self.connected.append(slot)


class _FakeQApplication:
    def __init__(self, argv):
        self.argv = argv
        self.aboutToQuit = _FakeSignal()

    def setApplicationName(self, name):  # noqa: N802 - Qt's spelling
        pass

    def setQuitOnLastWindowClosed(self, value):  # noqa: N802 - Qt's spelling
        pass

    def exec(self):
        return 0


@pytest.fixture
def calls(monkeypatch):
    """Run `main()` against fakes, recording what it did and in what order."""
    order: list[str] = []

    class _FakeWindow:
        def __init__(self):
            self.cfg = Config()
            order.append("build")

        def _log(self, msg):
            pass

        def start_hotkey(self):
            order.append("start_hotkey")

        def show(self):
            order.append("show")

        def shutdown(self):
            pass

    monkeypatch.setattr(gui_app, "setup_logging", lambda: None)
    monkeypatch.setattr(PySide6.QtWidgets, "QApplication", _FakeQApplication)
    monkeypatch.setattr(main_window, "MainWindow", _FakeWindow)

    def run(*, hands_over: bool) -> list[str]:
        def offer(cfg, parent=None):
            order.append("install")
            return hands_over

        monkeypatch.setattr(install_prompt, "maybe_offer_install", offer)
        order.clear()
        gui_app.main()
        return order

    return run


def test_the_hotkey_is_claimed_after_the_install_decision(calls):
    """Not before it — a process that may be about to exit must not take the key."""
    assert calls(hands_over=False) == ["build", "install", "start_hotkey", "show"]


def test_a_process_handing_over_never_claims_the_hotkey(calls):
    """The bug itself: the leaving copy took the key and the arriving copy got 1409."""
    assert calls(hands_over=True) == ["build", "install"]
