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
from enum import Enum
from pathlib import Path

from .version import is_newer

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


VERSION_MARKER = "version.txt"


def version_marker_path(local_appdata: str | None = None) -> Path:
    """Records which version sits in the install directory.

    Reading the version out of the exe itself would mean parsing a PE resource
    or taking a pywin32 dependency; a one-line text file next to it answers the
    same question and costs nothing.
    """
    return install_dir(local_appdata) / VERSION_MARKER


def installed_version(local_appdata: str | None = None) -> str | None:
    """The version currently installed, or None if nothing is (or it's unmarked)."""
    if not installed_exe_path(local_appdata).exists():
        return None
    try:
        text = version_marker_path(local_appdata).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def write_version_marker(version: str, local_appdata: str | None = None) -> None:
    try:
        path = version_marker_path(local_appdata)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(version, encoding="utf-8")
    except OSError:
        # Losing the marker costs an unnecessary re-copy next launch, nothing more.
        log.warning("could not write version marker", exc_info=True)


class InstallAction(str, Enum):
    """What launching this exe should do about the per-user install."""

    NONE = "none"      # nothing to do — stay quiet
    OFFER = "offer"    # nothing installed: ask whether to install
    UPDATE = "update"  # an older version is installed: replace it silently


def decide_install_action(
    *,
    frozen: bool,
    platform: str,
    already_installed: bool,
    user_declined: bool,
    running_version: str,
    installed_exists: bool,
    installed: str | None,
) -> InstallAction:
    """Decide between staying quiet, offering an install, and updating in place.

    Updating is deliberately silent: the user already chose to install this app
    once, so re-asking every release is a nag, not a question.

    Two separate facts, because conflating them was a real bug: `installed_exists`
    says whether an exe is sitting in the install directory at all, and
    `installed` says which version it claims to be. An exe with no version marker
    is an install written by 0.2.6 or earlier — markers only started in 0.2.7 —
    so it is by definition older than anything running this code, and it gets
    updated rather than treated as "nothing installed". Reading a missing marker
    as an empty install directory is what made the first-run prompt reappear on
    every single launch for anyone who already had the app.

    A *newer* installed version means this exe is an old copy someone launched
    out of Downloads; replacing it would be a silent downgrade, so that does
    nothing at all.
    """
    if not frozen or platform != "win32" or already_installed:
        return InstallAction.NONE
    if not installed_exists:
        # `user_declined` only silences the question, never an update: someone
        # who said no has nothing installed to update.
        return InstallAction.NONE if user_declined else InstallAction.OFFER
    if installed is None:
        return InstallAction.UPDATE  # pre-marker install, i.e. <= 0.2.6
    if is_newer(running_version, installed):
        return InstallAction.UPDATE
    return InstallAction.NONE


def should_offer_install(
    *, frozen: bool, platform: str, already_installed: bool, user_declined: bool
) -> bool:
    """Kept for callers that only care about the first-run offer."""
    return decide_install_action(
        frozen=frozen,
        platform=platform,
        already_installed=already_installed,
        user_declined=user_declined,
        running_version="0",
        installed_exists=False,
        installed=None,
    ) is InstallAction.OFFER


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
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=creation_flags,
    )
    if result.returncode != 0:
        # CalledProcessError's message is just the exit code, which says nothing
        # about why PowerShell refused. Carry its stderr instead.
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise OSError(
            f"powershell exited {result.returncode}"
            + (f": {detail[0]}" if detail else "")
        )
    if not shortcut.exists():
        raise OSError("powershell reported success but wrote no shortcut")
    return shortcut


def perform_install(
    source: Path | None = None, version: str | None = None
) -> InstallResult:
    """Copy the running exe into the per-user install dir and add a shortcut.

    Reading your own executable is fine on Windows — a running image is locked
    against writes, not reads. A shortcut failure is reported but doesn't fail
    the install; the copied exe is the part that matters.

    Doubles as the updater: copying over an existing exe is the whole update.
    Only the exe is touched, so cache, config and scan history — which live in
    LOCALAPPDATA and APPDATA, not here — survive untouched.
    """
    source = (source or current_exe()).resolve()
    target_dir = install_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / EXE_NAME
    if target.resolve() != source:
        shutil.copy2(source, target)
    if version is not None:
        write_version_marker(version)

    shortcut: Path | None = None
    error: str | None = None
    try:
        shortcut = create_start_menu_shortcut(target)
    except (subprocess.SubprocessError, OSError) as e:
        error = str(e) or e.__class__.__name__
        log.warning("could not create Start Menu shortcut: %s", error, exc_info=True)
    return InstallResult(exe_path=target, shortcut_path=shortcut, shortcut_error=error)


def launch(exe: Path) -> None:
    """Start the installed copy detached, so this process can exit."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([str(exe)], creationflags=flags, close_fds=True)
