"""Per-user install: path logic, when to offer, shortcut script construction.

The disk-touching parts are exercised via a fake source exe; the Windows
shortcut call is only checked for correct script construction, since
WScript.Shell doesn't exist off Windows.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from poe2arb.install import (
    EXE_NAME,
    InstallAction,
    _powershell_shortcut_script,
    decide_install_action,
    install_dir,
    installed_exe_path,
    installed_version,
    is_installed,
    perform_install,
    should_offer_install,
    start_menu_dir,
    write_version_marker,
)


class TestPaths:
    def test_install_dir_is_per_user_programs(self):
        d = install_dir(local_appdata=r"C:\Users\someone\AppData\Local")
        assert d == Path(r"C:\Users\someone\AppData\Local") / "Programs" / "poe2-arb"

    def test_not_program_files(self):
        """Program Files would need elevation — deliberately avoided."""
        assert "Program Files" not in str(install_dir(local_appdata=r"C:\x\Local"))

    def test_installed_exe_path(self):
        assert installed_exe_path(local_appdata=r"C:\x").name == EXE_NAME

    def test_start_menu_dir(self):
        d = start_menu_dir(appdata=r"C:\Users\someone\AppData\Roaming")
        assert d.as_posix().endswith("Microsoft/Windows/Start Menu/Programs")

    def test_is_installed_detects_match(self, tmp_path, monkeypatch):
        local = tmp_path / "Local"
        target = local / "Programs" / "poe2-arb"
        target.mkdir(parents=True)
        exe = target / EXE_NAME
        exe.write_text("x")
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        assert is_installed(exe)

    def test_is_installed_false_elsewhere(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
        other = tmp_path / "Downloads" / EXE_NAME
        other.parent.mkdir(parents=True)
        other.write_text("x")
        assert not is_installed(other)


class TestShouldOffer:
    BASE = dict(frozen=True, platform="win32", already_installed=False, user_declined=False)

    def test_offers_for_fresh_frozen_windows(self):
        assert should_offer_install(**self.BASE)

    def test_silent_when_running_from_source(self):
        assert not should_offer_install(**{**self.BASE, "frozen": False})

    def test_silent_on_other_platforms(self):
        assert not should_offer_install(**{**self.BASE, "platform": "linux"})

    def test_silent_once_installed(self):
        assert not should_offer_install(**{**self.BASE, "already_installed": True})

    def test_silent_after_user_declines(self):
        assert not should_offer_install(**{**self.BASE, "user_declined": True})


class TestShortcutScript:
    def test_script_sets_target_and_icon(self):
        script = _powershell_shortcut_script(
            Path(r"C:\apps\poe2-arb.exe"), Path(r"C:\menu\poe2-arb.lnk"), "desc"
        )
        assert "CreateShortcut" in script
        assert r"C:\apps\poe2-arb.exe" in script
        assert ",0'" in script  # icon index
        assert "$s.Save()" in script

    def test_quotes_are_escaped(self):
        """A path with an apostrophe must not break out of the PowerShell string."""
        script = _powershell_shortcut_script(
            Path(r"C:\Hinekora's\poe2-arb.exe"), Path(r"C:\m\s.lnk"), "d"
        )
        assert "Hinekora''s" in script


class TestPerformInstall:
    def test_copies_exe_to_install_dir(self, tmp_path, monkeypatch):
        local = tmp_path / "Local"
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        source = tmp_path / "Downloads" / EXE_NAME
        source.parent.mkdir(parents=True)
        source.write_bytes(b"fake exe")

        result = perform_install(source)

        assert result.exe_path == local / "Programs" / "poe2-arb" / EXE_NAME
        assert result.exe_path.read_bytes() == b"fake exe"
        # No Windows shell here, so the shortcut fails — install still succeeds.
        assert result.shortcut_path is None or result.shortcut_path.exists()

    def test_reinstall_over_itself_is_safe(self, tmp_path, monkeypatch):
        local = tmp_path / "Local"
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        target = local / "Programs" / "poe2-arb" / EXE_NAME
        target.parent.mkdir(parents=True)
        target.write_bytes(b"already here")

        result = perform_install(target)
        assert result.exe_path.read_bytes() == b"already here"


class TestInstallAction:
    """Three-way: stay quiet, offer a first install, or update in place."""

    def decide(self, **over):
        base = dict(
            frozen=True, platform="win32", already_installed=False,
            user_declined=False, running_version="0.2.7", installed=None,
        )
        base.update(over)
        return decide_install_action(**base)

    def test_first_run_offers(self):
        assert self.decide() is InstallAction.OFFER

    def test_older_installed_updates_without_asking(self):
        assert self.decide(installed="0.2.5") is InstallAction.UPDATE

    def test_same_version_does_nothing(self):
        assert self.decide(installed="0.2.7") is InstallAction.NONE

    def test_newer_installed_is_never_downgraded(self):
        """An old exe launched from Downloads must not overwrite a newer install."""
        assert self.decide(installed="0.3.0") is InstallAction.NONE

    def test_running_the_installed_copy_does_nothing(self):
        assert self.decide(already_installed=True, installed="0.2.5") is InstallAction.NONE

    def test_declining_silences_the_offer(self):
        assert self.decide(user_declined=True) is InstallAction.NONE

    def test_declining_does_not_silence_updates(self):
        """Different question: they have it installed, this just refreshes it."""
        assert self.decide(user_declined=True, installed="0.2.5") is InstallAction.UPDATE

    def test_unmarked_install_is_left_alone(self):
        """No marker means an unknown version; overwriting on a guess is worse."""
        assert self.decide(installed=None, user_declined=True) is InstallAction.NONE

    def test_unparseable_installed_version_does_nothing(self):
        assert self.decide(installed="garbage") is InstallAction.NONE

    def test_source_checkout_never_acts(self):
        assert self.decide(frozen=False, installed="0.2.5") is InstallAction.NONE

    def test_other_platforms_never_act(self):
        assert self.decide(platform="linux", installed="0.2.5") is InstallAction.NONE

    def test_minor_versions_compare_numerically(self):
        assert self.decide(running_version="0.10.0", installed="0.9.0") is (
            InstallAction.UPDATE
        )


class TestVersionMarker:
    def test_round_trips(self, tmp_path):
        (install_dir(str(tmp_path)) ).mkdir(parents=True, exist_ok=True)
        installed_exe_path(str(tmp_path)).write_text("exe", encoding="utf-8")
        write_version_marker("0.2.7", str(tmp_path))
        assert installed_version(str(tmp_path)) == "0.2.7"

    def test_no_install_means_no_version(self, tmp_path):
        assert installed_version(str(tmp_path)) is None

    def test_exe_without_a_marker_reads_as_unknown(self, tmp_path):
        install_dir(str(tmp_path)).mkdir(parents=True, exist_ok=True)
        installed_exe_path(str(tmp_path)).write_text("exe", encoding="utf-8")
        assert installed_version(str(tmp_path)) is None

    def test_marker_without_an_exe_is_ignored(self, tmp_path):
        """A leftover marker must not make a missing install look present."""
        write_version_marker("0.2.7", str(tmp_path))
        assert installed_version(str(tmp_path)) is None

    def test_blank_marker_reads_as_unknown(self, tmp_path):
        install_dir(str(tmp_path)).mkdir(parents=True, exist_ok=True)
        installed_exe_path(str(tmp_path)).write_text("exe", encoding="utf-8")
        write_version_marker("   ", str(tmp_path))
        assert installed_version(str(tmp_path)) is None
