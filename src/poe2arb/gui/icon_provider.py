"""Hands out item icons to the tables, fetching what isn't cached yet.

Fetching is demand-driven rather than a bulk download, but be clear about what
that means in practice: the Market table has a row per priced item, so the
first render asks for essentially all of them. Measured on a real first run,
that's **570 icons / 5.9 MB pulled in about 20 seconds**, in the background,
without blocking the window. After that it's a one-time cost — item art doesn't
change between leagues, so the cache is never invalidated.

Cached icons are returned immediately, on the calling thread — they're a small
file read. Anything missing returns a blank placeholder of the right size and
is queued for a single background thread, which emits `ready` as each arrives.
Callers connect that to a refresh so the icon appears without a rescan.

The CDN is GGG's static asset host, not the rate-limited trade API, so there's
no pacing here. It is exactly what that host exists to serve.
"""

from __future__ import annotations

import logging
import queue
from pathlib import Path

import httpx
from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap

from .. import __version__
from ..icons import fetch, load, store

log = logging.getLogger(__name__)

ICON_SIZE = 22  # table row height leaves room for about this much

# Enough that a full table's worth queues without blocking, small enough that a
# runaway caller can't grow it without bound.
MAX_QUEUED = 2000


class _Fetcher(QThread):
    """Serial background downloader. One connection, one item at a time."""

    fetched = Signal(str, bytes)   # (image_path, png bytes)

    def __init__(self, cache_dir: Path, parent=None):
        super().__init__(parent)
        self._cache_dir = cache_dir
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=MAX_QUEUED)
        self._seen: set[str] = set()

    def request(self, image_path: str) -> None:
        if image_path in self._seen:
            return  # already fetched or in flight
        self._seen.add(image_path)
        try:
            self._queue.put_nowait(image_path)
        except queue.Full:
            self._seen.discard(image_path)

    def stop(self) -> None:
        self.requestInterruption()
        try:
            self._queue.put_nowait(None)  # wake the blocking get
        except queue.Full:
            pass

    def run(self) -> None:
        client = httpx.Client(
            headers={"User-Agent": f"poe2-arb/{__version__}"},
            timeout=15,
            follow_redirects=True,
        )
        try:
            while not self.isInterruptionRequested():
                try:
                    image_path = self._queue.get(timeout=0.25)
                except queue.Empty:
                    continue
                if image_path is None:
                    return
                data = load(self._cache_dir, image_path)
                if data is None:
                    data = fetch(image_path, client)
                    if data is not None:
                        store(self._cache_dir, image_path, data)
                if data is not None:
                    self.fetched.emit(image_path, data)
        finally:
            client.close()


class IconProvider(QObject):
    """QIcon for an item id, cached in memory, on disk, then fetched."""

    ready = Signal(str)  # item id whose icon just became available

    def __init__(self, cache_dir: Path, parent=None):
        super().__init__(parent)
        self._cache_dir = Path(cache_dir)
        self._images: dict[str, str] = {}     # item id -> CDN path
        self._icons: dict[str, QIcon] = {}    # image path -> icon
        self._blank: QIcon | None = None
        self._fetcher = _Fetcher(self._cache_dir, self)
        self._fetcher.fetched.connect(self._store_icon)
        self._fetcher.start()

    def set_images(self, images: dict[str, str]) -> None:
        """Supply the item id -> CDN path map, from the loaded universe."""
        self._images = dict(images)

    def blank(self) -> QIcon:
        """A transparent icon, so rows without art still align with rows that have it."""
        if self._blank is None:
            pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
            pixmap.fill(Qt.GlobalColor.transparent)
            self._blank = QIcon(pixmap)
        return self._blank

    def icon(self, item_id: str) -> QIcon:
        """The item's icon if it's to hand, otherwise a placeholder and a fetch."""
        image_path = self._images.get(item_id)
        if not image_path:
            return self.blank()
        cached = self._icons.get(image_path)
        if cached is not None:
            return cached
        data = load(self._cache_dir, image_path)
        if data is not None:
            return self._decode(image_path, data)
        self._fetcher.request(image_path)
        return self.blank()

    def _decode(self, image_path: str, data: bytes) -> QIcon:
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            # Corrupt bytes: cache a blank so we don't retry it every repaint.
            self._icons[image_path] = self.blank()
            return self.blank()
        scaled = pixmap.scaled(
            QSize(ICON_SIZE, ICON_SIZE),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        icon = QIcon(scaled)
        self._icons[image_path] = icon
        return icon

    def _store_icon(self, image_path: str, data: bytes) -> None:
        self._decode(image_path, data)
        for item_id, path in self._images.items():
            if path == image_path:
                self.ready.emit(item_id)
                break

    def shutdown(self) -> None:
        self._fetcher.stop()
        if not self._fetcher.wait(3000):
            log.warning("icon fetcher did not stop; terminating")
            self._fetcher.terminate()
            self._fetcher.wait(500)
