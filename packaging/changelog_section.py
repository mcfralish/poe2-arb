"""Pull one version's section out of CHANGELOG.md, for use as release notes.

The release workflow runs this on the tag it's building so the GitHub release
body is the hand-written changelog entry rather than a list of commit subjects.
GitHub's auto-generated notes are still appended underneath, so the commit list
isn't lost — it just stops being the headline.

    python packaging/changelog_section.py v0.2.6 RELEASE_NOTES.md

Exits non-zero if the version has no section, which fails the release job on
purpose: shipping a build whose notes nobody wrote is the thing this prevents.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

# "## [0.2.5] — 2026-07-27" and friends. The date is optional and the brackets
# aren't required, so a hand-edited heading still matches.
HEADING = re.compile(r"^##\s+\[?(?P<version>[^\]\s]+)\]?")


def extract(text: str, version: str) -> str | None:
    """The body of the section for `version`, without its heading."""
    wanted = version.lstrip("vV")
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        match = HEADING.match(line)
        if match is None:
            continue
        if start is not None:
            return "\n".join(lines[start:i]).strip() or None
        if match.group("version").lstrip("vV") == wanted:
            start = i + 1
    if start is None:
        return None
    return "\n".join(lines[start:]).strip() or None


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    version, out_path = argv[1], argv[2]
    body = extract(CHANGELOG.read_text(encoding="utf-8"), version)
    if body is None:
        print(
            f"error: CHANGELOG.md has no section for {version}. "
            f"Add one before tagging.",
            file=sys.stderr,
        )
        return 1
    Path(out_path).write_text(body + "\n", encoding="utf-8")
    print(f"release notes for {version} -> {out_path} ({len(body)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
