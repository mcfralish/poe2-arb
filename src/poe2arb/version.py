"""Version parsing and comparison, shared by the update check and the installer.

Lives at package root rather than under `gui` because the installer needs it
too, and the installer must not depend on the GUI layer.
"""

from __future__ import annotations


def parse_version(tag: str) -> tuple[int, ...] | None:
    """'v0.2.1' / '0.2.1' -> (0, 2, 1); None if malformed."""
    tag = tag.strip().lstrip("vV")
    parts = tag.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def is_newer(candidate_tag: str, current_version: str) -> bool:
    """True when `candidate_tag` is a strictly later version than `current_version`.

    A version that can't be parsed compares as "not newer" — the caller is
    always deciding whether to *act*, and acting on garbage is worse than
    doing nothing.
    """
    cand = parse_version(candidate_tag)
    cur = parse_version(current_version)
    if cand is None or cur is None:
        return False
    return cand > cur
