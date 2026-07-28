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


class TestLegacyKeyRename:
    """`load_config` rejects unknown keys, so a rename must be translated."""

    def test_old_fee_pct_still_loads(self, tmp_path: Path):
        path = tmp_path / "poe2arb.toml"
        path.write_text("fee_pct = 1.5\n", encoding="utf-8")
        assert load_config(path).safety_margin_pct == 1.5

    def test_old_key_does_not_survive_a_resave(self, tmp_path: Path):
        path = tmp_path / "poe2arb.toml"
        path.write_text("fee_pct = 2.5\n", encoding="utf-8")
        cfg = load_config(path)
        save_config(cfg, path)
        text = path.read_text(encoding="utf-8")
        assert "fee_pct" not in text
        assert "safety_margin_pct = 2.5" in text

    def test_new_key_wins_when_both_are_present(self, tmp_path: Path):
        path = tmp_path / "poe2arb.toml"
        path.write_text("fee_pct = 1.5\nsafety_margin_pct = 0.25\n", encoding="utf-8")
        assert load_config(path).safety_margin_pct == 0.25

    def test_the_default_is_now_nothing(self):
        """Neither justification for the old 1.5% survives — see config.py."""
        assert Config().safety_margin_pct == 0.0

    def test_a_genuine_typo_is_still_an_error(self, tmp_path: Path):
        path = tmp_path / "poe2arb.toml"
        path.write_text("fee_pcnt = 1.5\n", encoding="utf-8")
        with pytest.raises(ValueError, match="unknown config keys"):
            load_config(path)


class TestConfigRoundTrip:
    def test_save_then_load_preserves_values(self, tmp_path: Path):
        cfg = Config(
            league="Test League",
            profit_threshold_pct=4.5,
            safety_margin_pct=2.0,
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
        assert loaded.safety_margin_pct == 2.0
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
