"""Background scan worker: runs the scan pipeline off the UI thread."""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

from ..config import Config
from ..scan import ScanResult, run_scan

log = logging.getLogger(__name__)


class ScanWorker(QThread):
    """One-shot scan in a background thread; re-created per scan by the window."""

    progress = Signal(int, int)          # (done, total) book requests
    finished_ok = Signal(object)         # ScanResult
    failed = Signal(str)

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self._cfg = cfg

    def run(self) -> None:  # QThread entry point
        try:
            result: ScanResult = run_scan(
                self._cfg, progress=lambda i, n: self.progress.emit(i, n)
            )
        except Exception as e:  # surfaced to the UI, not raised on a Qt thread
            log.exception("scan failed")
            self.failed.emit(str(e))
        else:
            self.finished_ok.emit(result)


class UpdateCheckWorker(QThread):
    """Checks GitHub Releases for a newer version (network, so off-thread)."""

    update_available = Signal(str, str)  # (version tag, release url)

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self._current = current_version

    def run(self) -> None:
        from .updates import check_for_update

        found = check_for_update(self._current)
        if found is not None:
            tag, url = found
            self.update_available.emit(tag, url)
