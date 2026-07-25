"""PyInstaller entry point for the windowed exe.

--smoke-test exits immediately after imports succeed; used by CI to verify the
frozen bundle without a display.
"""

import sys

if "--smoke-test" in sys.argv:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication  # noqa: F401

    import poe2arb.gui.main_window  # noqa: F401  (pulls in the whole app)

    print("smoke test OK")
    sys.exit(0)

from poe2arb.gui.app import main

sys.exit(main())
