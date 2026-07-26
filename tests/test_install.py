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
    _powershell_shortcut_script,
    install_dir,
    installed_exe_path,
    is_installed,
    perform_install,
    should_offer_install,
    start_menu_dir,
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
