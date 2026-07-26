"""PyInstaller entry point for the windowed exe.

--smoke-test exits immediately after imports succeed; used by CI to verify the
frozen bundle without a display.
"""

import sys

if "--smoke-test" in sys.argv:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    import poe2arb.gui.main_window  # noqa: F401  (pulls in the whole app)
    from poe2arb.gui.icon import icon_path, make_app_icon

    # Data files are easy to leave out of a bundle; fail the build if the icon
    # didn't make it in, rather than shipping the fallback icon unnoticed.
    app = QApplication([])
    if not icon_path().exists():
        sys.exit(f"icon missing from bundle: {icon_path()}")
    if make_app_icon().isNull():
        sys.exit("icon failed to load from bundle")

    print("smoke test OK (icon bundled)")
    sys.exit(0)

from poe2arb.gui.app import main

sys.exit(main())
