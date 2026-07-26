"""Optional per-user install for the frozen Windows build.

Deliberately a *per-user* install into %LOCALAPPDATA%\\Programs — the same
place VS Code and Discord put themselves — rather than Program Files. That
needs no elevation, so the app never has to show a UAC prompt or elevate an
unsigned binary, and it never touches antivirus settings. Both of those
behaviours are indistinguishable from a malware dropper and would make the
false-positive problem worse, not better.

Path logic is kept pure and platform-independent so it can be tested from
anywhere; only `perform_install` actually touches the disk.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "poe2-arb"
EXE_NAME = f"{APP_NAME}.exe"
SHORTCUT_NAME = f"{APP_NAME}.lnk"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle rather than source."""
    return bool(getattr(sys, "frozen", False))


def current_exe() -> Path:
    return Path(sys.executable).resolve()


def install_dir(local_appdata: str | None = None) -> Path:
    """%LOCALAPPDATA%\\Programs\\poe2-arb — per-user, no admin rights needed."""
    base = local_appdata or os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "Programs" / APP_NAME


def installed_exe_path(local_appdata: str | None = None) -> Path:
    return install_dir(local_appdata) / EXE_NAME


def start_menu_dir(appdata: str | None = None) -> Path:
    base = appdata or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def is_installed(exe: Path | None = None, local_appdata: str | None = None) -> bool:
    """Is the running exe already the installed copy?"""
    exe = (exe or current_exe()).resolve()
    try:
        return exe == installed_exe_path(local_appdata).resolve()
    except OSError:
        return False


def should_offer_install(
    *, frozen: bool, platform: str, already_installed: bool, user_declined: bool
) -> bool:
    """Offer only for a frozen Windows build that isn't installed yet.

    Running from source, on another OS, or after the user has said no once —
    all reasons to stay quiet.
    """
    return frozen and platform == "win32" and not already_installed and not user_declined


@dataclass(frozen=True)
class InstallResult:
    exe_path: Path
    shortcut_path: Path | None
    shortcut_error: str | None = None


def _powershell_shortcut_script(target: Path, shortcut: Path, description: str) -> str:
    """WScript.Shell is the dependency-free way to write a .lnk on Windows."""
    def q(value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    return (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({q(str(shortcut))});"
        f"$s.TargetPath = {q(str(target))};"
        f"$s.WorkingDirectory = {q(str(target.parent))};"
        f"$s.IconLocation = {q(str(target) + ',0')};"
        f"$s.Description = {q(description)};"
        f"$s.Save()"
    )


def create_start_menu_shortcut(target: Path, appdata: str | None = None) -> Path:
    shortcut_dir = start_menu_dir(appdata)
    shortcut_dir.mkdir(parents=True, exist_ok=True)
    shortcut = shortcut_dir / SHORTCUT_NAME
    script = _powershell_shortcut_script(
        target, shortcut, "PoE2 currency arbitrage watch (analysis only)"
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        timeout=30,
        creationflags=creation_flags,
    )
    return shortcut


def perform_install(source: Path | None = None) -> InstallResult:
    """Copy the running exe into the per-user install dir and add a shortcut.

    Reading your own executable is fine on Windows — a running image is locked
    against writes, not reads. A shortcut failure is reported but doesn't fail
    the install; the copied exe is the part that matters.
    """
    source = (source or current_exe()).resolve()
    target_dir = install_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / EXE_NAME
    if target.resolve() != source:
        shutil.copy2(source, target)

    shortcut: Path | None = None
    error: str | None = None
    try:
        shortcut = create_start_menu_shortcut(target)
    except (subprocess.SubprocessError, OSError) as e:
        error = str(e)
        log.warning("could not create Start Menu shortcut", exc_info=True)
    return InstallResult(exe_path=target, shortcut_path=shortcut, shortcut_error=error)


def launch(exe: Path) -> None:
    """Start the installed copy detached, so this process can exit."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([str(exe)], creationflags=flags, close_fds=True)
