"""Log file setup.

The exe is built --windowed, so on Windows there is no console and anything
written to stderr is discarded. Without a file handler every log call in the
frozen app is worthless — which bites hardest on install failures, where the
dialog is easy to click past and then nothing is left to diagnose from.
"""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("PySide6")

from poe2arb.gui.app import LOG_NAME, setup_logging  # noqa: E402


@pytest.fixture
def clean_root():
    root = logging.getLogger()
    saved = list(root.handlers)
    root.handlers.clear()
    yield root
    for h in root.handlers:
        h.close()
    root.handlers.clear()
    root.handlers.extend(saved)


class TestSetupLogging:
    def test_writes_to_a_file_in_the_cache_dir(self, clean_root, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        path = setup_logging()
        assert path is not None and path.name == LOG_NAME
        logging.getLogger("poe2arb.x").error("boom")
        assert "boom" in path.read_text(encoding="utf-8")

    def test_stderr_still_gets_records(self, clean_root, tmp_path, monkeypatch):
        """Running from source, the console is where you actually look."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        setup_logging()
        assert any(
            isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.RotatingFileHandler)
            for h in clean_root.handlers
        )

    def test_records_carry_a_timestamp(self, clean_root, tmp_path, monkeypatch):
        """A log line with no time in it is nearly useless for a bug report."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        path = setup_logging()
        logging.getLogger("poe2arb.x").error("boom")
        first = path.read_text(encoding="utf-8").splitlines()[0]
        assert first[:4].isdigit() and "ERROR" in first

    def test_rotation_is_bounded(self, clean_root, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        setup_logging()
        handlers = [
            h for h in clean_root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert handlers and handlers[0].maxBytes > 0 and handlers[0].backupCount > 0

    def test_an_unwritable_location_does_not_stop_startup(
        self, clean_root, tmp_path, monkeypatch
    ):
        blocker = tmp_path / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setenv("XDG_CACHE_HOME", str(blocker))
        assert setup_logging() is None  # no file, but no exception either
