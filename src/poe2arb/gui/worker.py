"""Background scan worker: runs the scan pipeline off the UI thread."""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal

from ..client import ScanCancelled
from ..config import Config

log = logging.getLogger(__name__)


def stop_thread(thread: QThread | None, timeout_ms: int = 5000) -> None:
    """Cancel and join a worker thread, so quitting never destroys a live QThread.

    Qt aborts the process if a QThread is garbage-collected while still
    running, which is how a quit during an in-flight scan turns into a hang.
    """
    if thread is None or not thread.isRunning():
        return
    if isinstance(thread, SweepWorker):
        thread.cancel()
    thread.requestInterruption()
    if not thread.wait(timeout_ms):
        log.warning("worker did not stop in %dms; terminating", timeout_ms)
        thread.terminate()
        thread.wait(1000)


class SweepWorker(QThread):
    """One cross-venue sweep off the UI thread.

    Cancellable mid-flight: a sweep is minutes of paced requests, and quitting
    the app must not wait one out.
    """

    progress = Signal(int, int, str)  # (item number, total, item name)
    budget = Signal(object)           # BudgetState, straight off the headers
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
                progress=lambda i, n, what: self.progress.emit(i, n, what),
                on_budget=self.budget.emit,
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
    """Load the item catalogue, then the Currency Exchange prices over the top.

    Two sources, in that order, because they cover different things:

    - **poe.ninja** has every item — 637 of them, names, categories, images,
      volume — and a consensus price for all of them.
    - **poe2scout** has the real Currency Exchange price, which is what an item
      is worth on the venue you would actually sell into, but only for the
      subset with genuine traded volume (226 of the 637, measured 2026-07-29).

    Where both have a price they agree closely — median 3.3% across the overlap,
    0.8% on the most-traded items — so this is not a correction so much as a
    preference for the number measured on the venue that matters. Only poe2scout
    was ever checked against the game itself (0.4-4.7%, five items).

    Neither is the rate-limited API; GGG's exchange endpoint is.
    """

    loaded = Signal(object)          # market.Universe
    ce_loaded = Signal(object)       # {item_id: divines} from the CE, may be {}

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
            return
        finally:
            client.close()
        # After the universe, never instead of it: a poe2scout outage must cost
        # the better prices, not the whole Market tab.
        self.ce_loaded.emit(self._ce_prices(league))

    def _ce_prices(self, league: str) -> dict[str, float]:
        from ..scout import ScoutClient

        scout = ScoutClient(self._cfg)
        try:
            snapshot = scout.snapshot(league)
        except Exception:
            log.info("could not load Currency Exchange prices", exc_info=True)
            return {}
        finally:
            scout.close()
        return {i.item_id: i.divines for i in snapshot.priced() if i.divines}


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
