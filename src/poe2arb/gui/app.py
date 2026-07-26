"""GUI entry point: poe2-arb-gui."""

from __future__ import annotations

import logging
import sys


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("poe2-arb")
    app.setQuitOnLastWindowClosed(False)  # tray keeps us alive while watching
    window = MainWindow()

    # Offered before the window appears; if the user installs, the freshly
    # installed copy takes over and this one exits.
    from .install_prompt import maybe_offer_install

    if maybe_offer_install(window.cfg, window):
        return 0

    # Catch-all: whatever triggers the quit (tray menu, window close, session
    # logout), worker threads get joined before the interpreter tears down.
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
