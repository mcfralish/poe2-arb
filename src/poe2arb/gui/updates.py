"""Update check against GitHub Releases. Qt-free so it's unit-testable.

Notify-only: shows a banner linking to the release page. No self-modification,
no auto-download — friends click and grab the new exe themselves.
"""

from __future__ import annotations

import logging

import httpx

# Re-exported: these moved to the package root so the installer can use them
# without depending on the GUI layer. Imported here so existing callers (and
# the Qt-free import test) keep working unchanged.
from ..version import is_newer, parse_version  # noqa: F401

log = logging.getLogger(__name__)

# Set to the public repo that hosts releases.
REPO = "mcfralish/poe2-arb"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"


def check_for_update(current_version: str) -> tuple[str, str] | None:
    """Returns (tag, html_url) if a newer release exists, else None.

    Any failure (offline, rate limit, no releases yet) is silently ignored —
    an update check must never break the app.
    """
    try:
        resp = httpx.get(
            LATEST_RELEASE_API,
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": f"poe2-arb/{current_version}"},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        tag = data.get("tag_name", "")
        url = data.get("html_url") or RELEASES_PAGE
        if is_newer(tag, current_version):
            return tag, url
    except Exception:
        log.debug("update check failed", exc_info=True)
    return None
