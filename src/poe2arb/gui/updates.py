"""Update check against GitHub Releases. Qt-free so it's unit-testable.

Notify-only: shows a banner linking to the release page. No self-modification,
no auto-download — friends click and grab the new exe themselves.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

# Set to the public repo that hosts releases.
REPO = "mcfralish/poe2-arb"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"


def parse_version(tag: str) -> tuple[int, ...] | None:
    """'v0.2.1' / '0.2.1' -> (0, 2, 1); None if malformed."""
    tag = tag.strip().lstrip("vV")
    parts = tag.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def is_newer(candidate_tag: str, current_version: str) -> bool:
    cand = parse_version(candidate_tag)
    cur = parse_version(current_version)
    if cand is None or cur is None:
        return False
    return cand > cur


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
