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
from poe2arb.install import InstallAction, InstallResult  # noqa: E402


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
    monkeypatch.setattr(
        install_prompt, "decide_install_action", lambda **kw: InstallAction.OFFER
    )


def test_accepting_the_offer_installs_and_exits(app, accepting, monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(
        install_prompt, "perform_install",
        lambda **kw: InstallResult(tmp_path / "poe2-arb.exe", tmp_path / "s.lnk"),
    )
    monkeypatch.setattr(install_prompt, "launch", lambda exe: launched.append(exe))

    should_exit = install_prompt.maybe_offer_install(Config())

    assert should_exit is True
    assert launched == [tmp_path / "poe2-arb.exe"]
    assert QApplication.overrideCursor() is None  # cursor restored


def test_install_failure_is_reported_not_raised(app, accepting, monkeypatch):
    def boom(**kw):
        raise OSError("disk full")

    monkeypatch.setattr(install_prompt, "perform_install", boom)

    assert install_prompt.maybe_offer_install(Config()) is False
    assert QApplication.overrideCursor() is None  # restored on the failure path too


def test_shortcut_failure_still_counts_as_installed(app, accepting, monkeypatch, tmp_path):
    monkeypatch.setattr(
        install_prompt, "perform_install",
        lambda **kw: InstallResult(tmp_path / "e.exe", None, "no shell"),
    )
    monkeypatch.setattr(install_prompt, "launch", lambda exe: None)
    assert install_prompt.maybe_offer_install(Config()) is True


def test_declining_records_the_choice(app, monkeypatch, tmp_path):
    monkeypatch.setattr(
        install_prompt, "decide_install_action", lambda **kw: InstallAction.OFFER
    )
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
    monkeypatch.setattr(
        install_prompt, "decide_install_action", lambda **kw: InstallAction.NONE
    )
    called = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: called.append(1))
    assert install_prompt.maybe_offer_install(Config()) is False
    assert called == []


class TestUpdateInPlace:
    """An older installed copy is replaced silently — no dialog, no question.

    The user already chose to install this app once; asking again on every
    release is a nag, not a question.
    """

    @pytest.fixture
    def updating(self, monkeypatch):
        monkeypatch.setattr(
            install_prompt, "decide_install_action", lambda **kw: InstallAction.UPDATE
        )
        monkeypatch.setattr(install_prompt, "installed_version", lambda: "0.2.5")

    def test_no_dialog_is_shown(self, app, updating, monkeypatch, tmp_path):
        shown = []
        monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(1))
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(1))
        monkeypatch.setattr(
            install_prompt, "perform_install",
            lambda **kw: InstallResult(tmp_path / "e.exe", None),
        )
        monkeypatch.setattr(install_prompt, "launch", lambda exe: None)

        assert install_prompt.maybe_offer_install(Config()) is True
        assert shown == []

    def test_hands_over_to_the_updated_copy(self, app, updating, monkeypatch, tmp_path):
        launched = []
        monkeypatch.setattr(
            install_prompt, "perform_install",
            lambda **kw: InstallResult(tmp_path / "new.exe", None),
        )
        monkeypatch.setattr(install_prompt, "launch", lambda exe: launched.append(exe))
        install_prompt.maybe_offer_install(Config())
        assert launched == [tmp_path / "new.exe"]

    def test_stamps_the_new_version(self, app, updating, monkeypatch, tmp_path):
        seen = {}
        monkeypatch.setattr(
            install_prompt, "perform_install",
            lambda **kw: seen.update(kw) or InstallResult(tmp_path / "e.exe", None),
        )
        monkeypatch.setattr(install_prompt, "launch", lambda exe: None)
        install_prompt.maybe_offer_install(Config())
        from poe2arb import __version__

        assert seen["version"] == __version__

    def test_a_locked_exe_does_not_stop_the_app(self, app, updating, monkeypatch):
        """The installed copy may be running, or held by antivirus mid-scan."""
        def boom(**kw):
            raise OSError("in use by another process")

        monkeypatch.setattr(install_prompt, "perform_install", boom)
        assert install_prompt.maybe_offer_install(Config()) is False
        assert QApplication.overrideCursor() is None

    def test_declining_the_first_offer_does_not_block_later_updates(self, app, updating,
                                                                    monkeypatch, tmp_path):
        monkeypatch.setattr(
            install_prompt, "perform_install",
            lambda **kw: InstallResult(tmp_path / "e.exe", None),
        )
        monkeypatch.setattr(install_prompt, "launch", lambda exe: None)
        cfg = Config(skip_install_prompt=True)
        assert install_prompt.maybe_offer_install(cfg) is True
