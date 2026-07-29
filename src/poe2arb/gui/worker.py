"""Background scan worker: runs the scan pipeline off the UI thread."""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

from ..client import ScanCancelled
from ..config import Config
from ..scan import ScanResult, run_scan

log = logging.getLogger(__name__)


def stop_thread(thread: QThread | None, timeout_ms: int = 5000) -> None:
    """Cancel and join a worker thread, so quitting never destroys a live QThread.

    Qt aborts the process if a QThread is garbage-collected while still
    running, which is how a quit during an in-flight scan turns into a hang.
    """
    if thread is None or not thread.isRunning():
        return
    if isinstance(thread, (ScanWorker, SweepWorker)):
        thread.cancel()
    thread.requestInterruption()
    if not thread.wait(timeout_ms):
        log.warning("worker did not stop in %dms; terminating", timeout_ms)
        thread.terminate()
        thread.wait(1000)


class ScanWorker(QThread):
    """One-shot scan in a background thread; re-created per scan by the window."""

    progress = Signal(int, int)          # (done, total) book requests
    finished_ok = Signal(object)         # ScanResult
    failed = Signal(str)

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._cancelled = False
        self.was_cancelled = False

    def cancel(self) -> None:
        """Ask the scan to abort at its next checkpoint (thread-safe: a bool set)."""
        self._cancelled = True

    def _is_cancelled(self) -> bool:
        return self._cancelled or self.isInterruptionRequested()

    def run(self) -> None:  # QThread entry point
        try:
            result: ScanResult = run_scan(
                self._cfg,
                progress=lambda i, n: self.progress.emit(i, n),
                should_cancel=self._is_cancelled,
            )
        except ScanCancelled:
            log.info("scan cancelled")  # normal stop path, nothing to report
            self.was_cancelled = True
            return
        except Exception as e:  # surfaced to the UI, not raised on a Qt thread
            log.exception("scan failed")
            self.failed.emit(str(e))
        else:
            self.finished_ok.emit(result)


class SweepWorker(QThread):
    """One cross-venue sweep off the UI thread.

    Separate from ScanWorker rather than a mode of it: a sweep answers a
    different question (which live listings are underpriced against the
    Currency Exchange), takes a different amount of time, and must be
    cancellable independently — the two can't usefully run at once, since both
    spend the same GGG request budget.
    """

    progress = Signal(int, int)   # (items done, total)
    finished_ok = Signal(object)  # SweepResult
    failed = Signal(str)

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._cancelled = False
        self.was_cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _is_cancelled(self) -> bool:
        return self._cancelled or self.isInterruptionRequested()

    def run(self) -> None:
        from ..sweep import run_sweep

        try:
            result = run_sweep(
                self._cfg,
                progress=lambda i, n: self.progress.emit(i, n),
                should_cancel=self._is_cancelled,
            )
        except ScanCancelled:
            log.info("sweep cancelled")
            self.was_cancelled = True
            return
        except Exception as e:  # surfaced to the UI, not raised on a Qt thread
            log.exception("sweep failed")
            self.failed.emit(str(e))
        else:
            self.finished_ok.emit(result)


class RecheckWorker(QThread):
    """One uncached request confirming a listing is still there.

    Off-thread like every other network call, but deliberately *not*
    cancellable through `stop_thread`: it is a single request that resolves in
    about a second, and the user is waiting on its answer before whispering.
    """

    done = Signal(object, object)  # (candidate, RecheckResult)

    def __init__(self, cfg: Config, candidate, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._candidate = candidate

    def run(self) -> None:
        from ..sweep import RecheckResult, RecheckStatus, recheck

        try:
            result = recheck(self._cfg, self._candidate)
        except Exception as e:  # noqa: BLE001 — never raise on a Qt thread
            log.warning("recheck failed", exc_info=True)
            result = RecheckResult(RecheckStatus.UNKNOWN, str(e), None)
        self.done.emit(self._candidate, result)


class UniverseWorker(QThread):
    """Load every priced item across poe.ninja's economy categories.

    Only touches poe.ninja, which isn't the rate-limited API — GGG's exchange
    endpoint is. One cached-or-cheap GET per category, versus the dozens of
    paced requests a scan needs.
    """

    loaded = Signal(object)  # market.Universe

    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self._cfg = cfg

    def run(self) -> None:
        from ..client import NinjaClient

        client = NinjaClient(self._cfg)
        try:
            league = self._cfg.league or client.current_league()
            self.loaded.emit(client.universe(league))
        except Exception:
            log.info("could not load economy data", exc_info=True)
        finally:
            client.close()


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
