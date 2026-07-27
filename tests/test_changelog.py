"""Release notes are cut from CHANGELOG.md by the release workflow."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packaging"))

from changelog_section import CHANGELOG, extract  # noqa: E402

SAMPLE = """# Changelog

Preamble that must never end up in release notes.

## [Unreleased]

- something in flight

## [0.3.0] — 2026-08-01

### Added
- a thing

## [0.2.5] — 2026-07-27

### Fixed
- an older thing

## [0.2.4]

- the last section
"""


class TestExtract:
    def test_pulls_the_named_section(self):
        assert extract(SAMPLE, "0.3.0") == "### Added\n- a thing"

    def test_stops_at_the_next_version(self):
        assert "older thing" not in extract(SAMPLE, "0.3.0")

    def test_leading_v_is_accepted(self):
        """Tags are v0.3.0; headings are 0.3.0."""
        assert extract(SAMPLE, "v0.3.0") == extract(SAMPLE, "0.3.0")

    def test_last_section_runs_to_the_end(self):
        assert extract(SAMPLE, "0.2.4") == "- the last section"

    def test_preamble_is_never_included(self):
        assert "Preamble" not in (extract(SAMPLE, "0.3.0") or "")

    def test_unreleased_is_addressable(self):
        assert extract(SAMPLE, "Unreleased") == "- something in flight"

    def test_unknown_version_is_none(self):
        assert extract(SAMPLE, "1.0.0") is None

    def test_empty_section_is_none(self):
        """An empty entry is as bad as a missing one — the job should fail."""
        text = "## [0.1.0]\n\n## [0.0.9]\n- real\n"
        assert extract(text, "0.1.0") is None


class TestRealChangelog:
    def test_every_released_version_has_a_section(self):
        """A tag with no notes fails the release job; catch it here instead."""
        from poe2arb import __version__

        text = CHANGELOG.read_text(encoding="utf-8")
        assert extract(text, __version__) or extract(text, "Unreleased"), (
            f"CHANGELOG.md needs a section for {__version__} or an Unreleased one"
        )

    def test_headings_are_shaped_the_way_the_parser_expects(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        headings = re.findall(r"^## .*$", text, re.MULTILINE)
        assert headings, "no version headings found"
        for heading in headings:
            assert re.match(r"^##\s+\[[^\]]+\]", heading), heading
