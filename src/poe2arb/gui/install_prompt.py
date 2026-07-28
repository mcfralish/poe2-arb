"""First-run offer to install into the per-user Programs folder."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox

from .. import __version__
from ..config import Config, save_config, user_config_path
from ..install import (
    InstallAction,
    decide_install_action,
    install_dir,
    installed_version,
    is_frozen,
    is_installed,
    launch,
    perform_install,
)
from .icon import make_app_icon

log = logging.getLogger(__name__)


def maybe_offer_install(cfg: Config, parent=None) -> bool:
    """Install, update or do nothing. Returns True if the app should now exit.

    Exiting matters: after installing we hand over to the copy in the install
    directory, so the user ends up running the one their shortcut points at
    rather than whatever is still sitting in Downloads.
    """
    action = decide_install_action(
        frozen=is_frozen(),
        platform=sys.platform,
        already_installed=is_installed(),
        user_declined=cfg.skip_install_prompt,
        running_version=__version__,
        installed=installed_version(),
    )
    if action is InstallAction.NONE:
        return False
    if action is InstallAction.UPDATE:
        return _update_in_place(parent)

    box = QMessageBox(parent)
    box.setWindowIcon(make_app_icon())
    box.setIconPixmap(make_app_icon().pixmap(64, 64))
    box.setWindowTitle("Install poe2-arb?")
    box.setText("<b>Install poe2-arb for quick access?</b>")
    box.setInformativeText(
        f"This copies the app to your personal programs folder and adds a Start "
        f"Menu shortcut, so you don't have to keep it in Downloads.<br><br>"
        f"<b>Installs to:</b><br><code>{install_dir()}</code><br><br>"
        f"No administrator rights are needed and nothing else on your system is "
        f"changed. You can remove it later by deleting that folder."
    )
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.Yes)
    box.button(QMessageBox.StandardButton.Yes).setText("Install")
    box.button(QMessageBox.StandardButton.No).setText("Not now")
    dont_ask = QCheckBox("Don't ask again")
    box.setCheckBox(dont_ask)

    choice = box.exec()

    if choice != QMessageBox.StandardButton.Yes:
        if dont_ask.isChecked():
            cfg.skip_install_prompt = True
            _persist(cfg)
        return False

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        result = perform_install(version=__version__)
    except OSError as e:
        QMessageBox.warning(
            parent,
            "Install failed",
            f"Could not install to {install_dir()}:\n{e}\n\n"
            f"You can keep running the app from its current location.",
        )
        return False
    finally:
        QApplication.restoreOverrideCursor()

    detail = f"Installed to:\n{result.exe_path}"
    if result.shortcut_path is not None:
        detail += "\n\nA Start Menu shortcut has been created."
    elif result.shortcut_error:
        detail += (
            "\n\nThe app was copied, but the Start Menu shortcut could not be "
            "created. You can pin the installed copy manually."
        )
    detail += "\n\nThe installed copy will start now."

    QMessageBox.information(parent, "Installed", detail)
    try:
        launch(result.exe_path)
    except OSError:
        log.warning("could not launch installed copy", exc_info=True)
        return False
    return True


def _update_in_place(parent=None) -> bool:
    """Replace an older installed copy without asking. Returns True to exit.

    No dialog on the way in: the user already chose to install this app, so
    asking again every release is a nag rather than a question. Only the exe is
    replaced — cache, config and scan history live in separate directories and
    are untouched by an update.

    A failure here is non-fatal by design. The copy in the install directory
    may be running, or locked by antivirus mid-scan, and neither is a reason to
    stop the app the user just launched: it carries on from where it is.
    """
    previous = installed_version()
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        result = perform_install(version=__version__)
    except OSError:
        log.warning("could not update the installed copy", exc_info=True)
        return False
    finally:
        QApplication.restoreOverrideCursor()

    log.info("updated installed copy from %s to %s", previous, __version__)
    try:
        launch(result.exe_path)
    except OSError:
        log.warning("could not launch the updated copy", exc_info=True)
        return False
    return True


def _persist(cfg: Config) -> None:
    try:
        save_config(cfg, user_config_path())
    except OSError:
        log.warning("could not save config", exc_info=True)
