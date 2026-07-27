"""Remembered window state, and theme-aware colours."""

from __future__ import annotations

import json

import pytest

from poe2arb.gui.ui_state import (
    decode_geometry,
    encode_geometry,
    load_ui_state,
    save_ui_state,
    ui_state_path,
)


class TestUiState:
    def test_round_trip(self, tmp_path):
        path = ui_state_path(tmp_path)
        save_ui_state(path, {"tab": 2, "ops_split": [300, 200]})
        assert load_ui_state(path) == {"tab": 2, "ops_split": [300, 200]}

    def test_missing_file_is_empty(self, tmp_path):
        assert load_ui_state(tmp_path / "nothing.json") == {}

    def test_corrupt_file_is_empty(self, tmp_path):
        path = tmp_path / "ui-state.json"
        path.write_text("{ not json", encoding="utf-8")
        assert load_ui_state(path) == {}

    def test_non_object_is_empty(self, tmp_path):
        """A JSON list would sail past json.loads and break every .get() call."""
        path = tmp_path / "ui-state.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        assert load_ui_state(path) == {}

    def test_saving_creates_the_directory(self, tmp_path):
        path = ui_state_path(tmp_path / "deep" / "cache")
        save_ui_state(path, {"tab": 0})
        assert path.exists()

    def test_unwritable_location_is_not_fatal(self, tmp_path):
        """Losing window position is never worth failing a shutdown over."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        save_ui_state(blocker / "ui-state.json", {"tab": 0})  # must not raise

    def test_geometry_survives_json(self):
        blob = bytes(range(256))
        assert decode_geometry(encode_geometry(blob)) == blob

    def test_garbage_geometry_rejected(self):
        assert decode_geometry("not base64!!") is None
        assert decode_geometry(None) is None
        assert decode_geometry(42) is None


class TestTheme:
    def test_colours_differ_between_themes(self):
        """The point of the module: one palette's colours aren't the other's."""
        pytest.importorskip("PySide6")
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QApplication, QWidget

        from poe2arb.gui.theme import error_color, is_dark, muted_color

        QApplication.instance() or QApplication([])
        light, dark = QWidget(), QWidget()
        for widget, colour in ((light, QColor("#f0f0f0")), (dark, QColor("#202020"))):
            palette = widget.palette()
            palette.setColor(QPalette.ColorRole.Window, colour)
            widget.setPalette(palette)

        assert not is_dark(light)
        assert is_dark(dark)
        assert error_color(light) != error_color(dark)
        assert muted_color(light) != muted_color(dark)
