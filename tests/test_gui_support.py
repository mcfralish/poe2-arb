"""Qt-free tests for GUI support code: update check versioning, config save/load."""

from __future__ import annotations

from pathlib import Path

from poe2arb.config import Config, load_config, save_config
from poe2arb.gui.updates import is_newer, parse_version


class TestVersions:
    def test_parse(self):
        assert parse_version("v0.2.0") == (0, 2, 0)
        assert parse_version("1.10.3") == (1, 10, 3)
        assert parse_version("not-a-version") is None

    def test_is_newer(self):
        assert is_newer("v0.3.0", "0.2.0")
        assert is_newer("v0.2.1", "0.2.0")
        assert not is_newer("v0.2.0", "0.2.0")
        assert not is_newer("v0.1.9", "0.2.0")
        assert is_newer("v0.10.0", "0.9.0")  # numeric, not lexicographic
        assert not is_newer("garbage", "0.2.0")  # malformed never triggers a banner

    def test_no_qt_import(self):
        # updates.py must stay importable without PySide6 (CLI installs, tests).
        import sys

        import poe2arb.gui.updates  # noqa: F401

        assert not any(m.startswith("PySide6") for m in sys.modules)


class TestConfigRoundTrip:
    def test_save_then_load_preserves_values(self, tmp_path: Path):
        cfg = Config(
            league="Test League",
            profit_threshold_pct=4.5,
            fee_pct=2.0,
            watch_interval_minutes=15,
            alert_sound=False,
            max_currencies=8,
            cache_dir=tmp_path / "cache",
        )
        path = tmp_path / "cfg" / "poe2arb.toml"
        save_config(cfg, path)
        loaded = load_config(path)
        assert loaded.league == "Test League"
        assert loaded.profit_threshold_pct == 4.5
        assert loaded.fee_pct == 2.0
        assert loaded.watch_interval_minutes == 15
        assert loaded.alert_sound is False
        assert loaded.max_currencies == 8
        assert loaded.cache_dir == tmp_path / "cache"

    def test_none_league_omitted_and_defaults(self, tmp_path: Path):
        path = tmp_path / "poe2arb.toml"
        save_config(Config(), path)
        # An all-defaults config writes an empty file: nothing to pin, so every
        # value follows whatever the current version's defaults are.
        assert path.read_text() == ""
        loaded = load_config(path)
        assert loaded.league is None
        assert loaded.watch_interval_minutes == 10

    def test_quotes_and_backslashes_escaped(self, tmp_path: Path):
        cfg = Config(user_agent='agent "quoted" C:\\path')
        path = tmp_path / "poe2arb.toml"
        save_config(cfg, path)
        assert load_config(path).user_agent == 'agent "quoted" C:\\path'
