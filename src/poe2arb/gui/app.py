"""GUI entry point: poe2-arb-gui."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

LOG_NAME = "poe2-arb.log"
LOG_MAX_BYTES = 1 * 1024 * 1024
LOG_BACKUPS = 2


def setup_logging() -> Path | None:
    """Log to a file as well as stderr, and return where.

    The exe is built --windowed, which on Windows means there is no console at
    all: anything written to stderr is discarded. That made every log call in
    the frozen app worthless, and it mattered most exactly where it hurt — an
    install failure shows a dialog, and if the user clicks past it the only
    record is gone. A rotating file in the cache directory survives that.
    """
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)

    try:
        from ..config import user_cache_path

        path = user_cache_path() / LOG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
        )
        handler.setFormatter(fmt)
        root.addHandler(handler)
        return path
    except (OSError, ImportError):
        # No log file is a nuisance, never a reason to fail to start.
        return None


def main() -> int:
    log_path = setup_logging()
    logging.getLogger(__name__).info("poe2-arb starting")
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("poe2-arb")
    app.setQuitOnLastWindowClosed(False)  # tray keeps us alive while watching
    window = MainWindow()
    if log_path is not None:
        window.log_path = log_path
        window._log(f"logging to {log_path}")

    # Offered before the window appears; if the user installs, the freshly
    # installed copy takes over and this one exits.
    from .install_prompt import maybe_offer_install

    if maybe_offer_install(window.cfg, window):
        return 0

    # Only now, because a global hotkey belongs to a process and the line above
    # can start a second one. On the handover path the installed copy launches
    # while this one is still exiting, and whichever registered first keeps the
    # key — so an update used to leave the surviving process refused with 1409
    # and the hotkey dead until it was rebound by hand. Registering after the
    # handover means the process that is leaving never claims it.
    window.start_hotkey()

    # Catch-all: whatever triggers the quit (tray menu, window close, session
    # logout), worker threads get joined before the interpreter tears down.
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
