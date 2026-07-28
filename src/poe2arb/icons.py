"""Disk cache for item icons.

poe.ninja hands out CDN paths; the images themselves live on GGG's static host.
They're 64x64 PNGs averaging ~10 KB. Measured on a real first run: **570 icons,
5.9 MB**, because the Market table lists every priced item and so asks for
nearly all of them. Nothing is fetched twice, and item art doesn't change
between leagues, so this is paid once and never again.

The cache is deliberately *outside* the install directory, in the same
regenerable-data folder as everything else, so updating the app never discards
it. Item art doesn't change between leagues either, which is why there's no
league in the key and no expiry: a cached icon stays valid indefinitely.

Qt-free on purpose — the GUI wraps this, but the fetching and storing are
plain bytes and can be tested without a display.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# The images are served by GGG's static CDN, not by poe.ninja, and not by the
# rate-limited trade API. No pacing needed.
IMAGE_HOST = "https://web.poecdn.com"

ICON_DIR_NAME = "icons"

# A 64px PNG that grew past this is not an item icon; refuse to store it rather
# than let a redirect page or an error body fill the cache.
MAX_ICON_BYTES = 512 * 1024


def icon_dir(cache_dir: Path) -> Path:
    return Path(cache_dir) / ICON_DIR_NAME


def cache_name(image_path: str) -> str:
    """A filename for a CDN path.

    The paths carry base64 segments and arbitrary punctuation, so they're
    hashed rather than sanitised — sanitising risks two different paths
    colliding on one filename, which would show the wrong art for an item.
    """
    digest = hashlib.sha256(image_path.encode("utf-8")).hexdigest()[:32]
    return f"{digest}.png"


def cached_path(cache_dir: Path, image_path: str) -> Path:
    return icon_dir(cache_dir) / cache_name(image_path)


def load(cache_dir: Path, image_path: str) -> bytes | None:
    """Icon bytes from disk, or None if not cached yet."""
    try:
        return cached_path(cache_dir, image_path).read_bytes()
    except OSError:
        return None


def store(cache_dir: Path, image_path: str, data: bytes) -> bool:
    """Write icon bytes to the cache. Returns whether it stuck."""
    if not data or len(data) > MAX_ICON_BYTES:
        return False
    target = cached_path(cache_dir, image_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Via a temp file so a half-written icon is never read back as valid.
        tmp = target.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(target)
        return True
    except OSError:
        log.debug("could not cache icon %s", image_path, exc_info=True)
        return False


def image_url(image_path: str) -> str:
    if image_path.startswith(("http://", "https://")):
        return image_path
    return IMAGE_HOST + image_path


def fetch(image_path: str, client: httpx.Client, user_agent: str = "") -> bytes | None:
    """Download one icon. None on any failure — art is never worth an exception."""
    try:
        resp = client.get(image_url(image_path))
    except httpx.HTTPError:
        log.debug("icon fetch failed for %s", image_path, exc_info=True)
        return None
    if resp.status_code != 200:
        return None
    content_type = resp.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        # A 200 that isn't an image means the CDN served an error page.
        return None
    return resp.content


def fetch_and_store(
    cache_dir: Path, image_path: str, client: httpx.Client
) -> bytes | None:
    """Cache-first read: disk, then network, storing what comes back."""
    existing = load(cache_dir, image_path)
    if existing is not None:
        return existing
    data = fetch(image_path, client)
    if data is None:
        return None
    store(cache_dir, image_path, data)
    return data


def cache_size_bytes(cache_dir: Path) -> int:
    """Total bytes on disk, for reporting to the user."""
    directory = icon_dir(cache_dir)
    if not directory.is_dir():
        return 0
    total = 0
    for entry in directory.iterdir():
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def clear(cache_dir: Path) -> int:
    """Delete every cached icon. Returns how many went."""
    directory = icon_dir(cache_dir)
    if not directory.is_dir():
        return 0
    removed = 0
    for entry in directory.iterdir():
        try:
            if entry.is_file():
                entry.unlink()
                removed += 1
        except OSError:
            continue
    return removed
