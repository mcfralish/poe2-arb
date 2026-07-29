"""Qt-free tests for GUI support code: update check versioning, config save/load."""

from __future__ import annotations

from pathlib import Path

import pytest

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
        """updates.py must stay importable without PySide6 (CLI-only installs).

        Runs in a subprocess: once any other test module imports Qt, PySide6 is
        in this process's sys.modules regardless of what this module needs.
        """
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import poe2arb.gui.updates, sys;"
                "qt = [m for m in sys.modules if m.startswith('PySide6')];"
                "print('QT' if qt else 'CLEAN')",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "CLEAN"


class TestRetiredKeys:
    """A config written by an older version must still open the app.

    Removing a setting is our decision, not the user's mistake, so a leftover
    key is dropped rather than treated like a typo. Everyone upgrading from
    0.3.x has a file full of triangular-scan knobs.
    """

    def test_a_retired_key_does_not_stop_the_app_loading(self, tmp_path: Path):
        path = tmp_path / "poe2arb.toml"
        path.write_text("profit_threshold_pct = 4.5\nleague = \"Aldur\"\n",
                        encoding="utf-8")
        assert load_config(path).league == "Aldur"

    def test_every_removed_key_is_covered(self, tmp_path: Path):
        """A whole 0.3.x config, verbatim."""
        path = tmp_path / "poe2arb.toml"
        path.write_text(
            "\n".join([
                "profit_threshold_pct = 3.0", "safety_margin_pct = 0.0",
                "liquidity_floor_divines = 20.0", "max_currencies = 10",
                "max_cycle_len = 4", "max_currency_value_divines = 0.0",
                "depth_divines = 5.0", "bait_filter_ratio = 1.1",
                "min_accounts = 2", "have_chunk = 6",
                "watch_interval_minutes = 10.0", "fee_pct = 1.5",
                "sweep_items = 42",
            ]) + "\n",
            encoding="utf-8",
        )
        assert load_config(path).sweep_items == 42

    def test_a_retired_key_does_not_come_back_on_resave(self, tmp_path: Path):
        path = tmp_path / "poe2arb.toml"
        path.write_text("max_cycle_len = 3\n", encoding="utf-8")
        save_config(load_config(path), path)
        assert "max_cycle_len" not in path.read_text(encoding="utf-8")

    def test_a_genuine_typo_is_still_an_error(self, tmp_path: Path):
        """The whole reason unknown keys are rejected."""
        path = tmp_path / "poe2arb.toml"
        path.write_text("sweep_itmes = 42\n", encoding="utf-8")
        with pytest.raises(ValueError, match="sweep_itmes"):
            load_config(path)


class TestConfigRoundTrip:
    def test_save_then_load_preserves_values(self, tmp_path: Path):
        cfg = Config(
            league="Test League",
            sweep_items=45,
            min_gap_ratio=1.08,
            sweep_interval_minutes=15,
            alert_sound=False,
            max_gap_ratio=2.5,
            cache_dir=tmp_path / "cache",
        )
        path = tmp_path / "cfg" / "poe2arb.toml"
        save_config(cfg, path)
        loaded = load_config(path)
        assert loaded.league == "Test League"
        assert loaded.sweep_items == 45
        assert loaded.min_gap_ratio == 1.08
        assert loaded.sweep_interval_minutes == 15
        assert loaded.alert_sound is False
        assert loaded.max_gap_ratio == 2.5
        assert loaded.cache_dir == tmp_path / "cache"

    def test_none_league_omitted_and_defaults(self, tmp_path: Path):
        path = tmp_path / "poe2arb.toml"
        save_config(Config(), path)
        # An all-defaults config writes an empty file: nothing to pin, so every
        # value follows whatever the current version's defaults are.
        assert path.read_text() == ""
        loaded = load_config(path)
        assert loaded.league is None
        assert loaded.sweep_interval_minutes == 10

    def test_quotes_and_backslashes_escaped(self, tmp_path: Path):
        cfg = Config(user_agent='agent "quoted" C:\\path')
        path = tmp_path / "poe2arb.toml"
        save_config(cfg, path)
        assert load_config(path).user_agent == 'agent "quoted" C:\\path'
