"""The first-run install dialog.

Regression cover for v0.2.3, where this path crashed on the very first click:
setOverrideCursor was called with None, which PySide rejects outright. The
dialog is only reachable from a frozen Windows build, so nothing in the test
suite exercised it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from poe2arb.config import Config  # noqa: E402
from poe2arb.gui import install_prompt  # noqa: E402
from poe2arb.install import InstallResult  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def accepting(monkeypatch):
    """Pretend the user clicked Install."""
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(install_prompt, "should_offer_install", lambda **kw: True)


def test_accepting_the_offer_installs_and_exits(app, accepting, monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(
        install_prompt, "perform_install",
        lambda: InstallResult(tmp_path / "poe2-arb.exe", tmp_path / "s.lnk"),
    )
    monkeypatch.setattr(install_prompt, "launch", lambda exe: launched.append(exe))

    should_exit = install_prompt.maybe_offer_install(Config())

    assert should_exit is True
    assert launched == [tmp_path / "poe2-arb.exe"]
    assert QApplication.overrideCursor() is None  # cursor restored


def test_install_failure_is_reported_not_raised(app, accepting, monkeypatch):
    def boom():
        raise OSError("disk full")

    monkeypatch.setattr(install_prompt, "perform_install", boom)

    assert install_prompt.maybe_offer_install(Config()) is False
    assert QApplication.overrideCursor() is None  # restored on the failure path too


def test_shortcut_failure_still_counts_as_installed(app, accepting, monkeypatch, tmp_path):
    monkeypatch.setattr(
        install_prompt, "perform_install",
        lambda: InstallResult(tmp_path / "e.exe", None, "no shell"),
    )
    monkeypatch.setattr(install_prompt, "launch", lambda exe: None)
    assert install_prompt.maybe_offer_install(Config()) is True


def test_declining_records_the_choice(app, monkeypatch, tmp_path):
    monkeypatch.setattr(install_prompt, "should_offer_install", lambda **kw: True)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.No)
    monkeypatch.setattr(
        install_prompt, "_persist", lambda cfg: None
    )
    # The "don't ask again" box defaults to unchecked, so declining once is not
    # recorded — the offer should come back next launch.
    cfg = Config()
    assert install_prompt.maybe_offer_install(cfg) is False
    assert cfg.skip_install_prompt is False


def test_silent_when_not_applicable(app, monkeypatch):
    """Running from source must never show the dialog."""
    monkeypatch.setattr(install_prompt, "should_offer_install", lambda **kw: False)
    called = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: called.append(1))
    assert install_prompt.maybe_offer_install(Config()) is False
    assert called == []
