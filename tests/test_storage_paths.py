"""Cache location, legacy migration, and config persistence of defaults."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from poe2arb import config as config_mod
from poe2arb.config import (
    Config,
    load_config,
    migrate_legacy_cache,
    save_config,
    user_cache_path,
    user_config_path,
)


class TestPlatformPaths:
    def test_windows_uses_localappdata(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
        path = user_cache_path()
        assert path == tmp_path / "AppData" / "Local" / "poe2-arb"
        assert ".cache" not in str(path)  # the Linux-ism we moved away from

    def test_windows_config_uses_roaming(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        assert user_config_path().parent == tmp_path / "Roaming" / "poe2-arb"

    def test_linux_honours_xdg(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        assert user_cache_path() == tmp_path / "xdg" / "poe2-arb"

    def test_linux_default_without_xdg(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
        assert user_cache_path() == tmp_path / ".cache" / "poe2-arb"


class TestMigration:
    def _patch_paths(self, monkeypatch, old: Path, new: Path):
        monkeypatch.setattr(config_mod, "legacy_cache_path", lambda: old)
        monkeypatch.setattr(config_mod, "user_cache_path", lambda: new)

    def test_moves_existing_data(self, monkeypatch, tmp_path):
        old, new = tmp_path / "old", tmp_path / "new" / "poe2-arb"
        old.mkdir()
        (old / "history.jsonl").write_text("{}\n")
        self._patch_paths(monkeypatch, old, new)

        assert migrate_legacy_cache() == new
        assert (new / "history.jsonl").read_text() == "{}\n"
        assert not old.exists()

    def test_no_op_when_nothing_to_migrate(self, monkeypatch, tmp_path):
        self._patch_paths(monkeypatch, tmp_path / "missing", tmp_path / "new")
        assert migrate_legacy_cache() is None

    def test_never_overwrites_existing_destination(self, monkeypatch, tmp_path):
        old, new = tmp_path / "old", tmp_path / "new"
        old.mkdir()
        (old / "a.json").write_text("old")
        new.mkdir()
        (new / "a.json").write_text("new")
        self._patch_paths(monkeypatch, old, new)

        assert migrate_legacy_cache() is None
        assert (new / "a.json").read_text() == "new"
        assert old.exists()

    def test_same_path_is_a_no_op(self, monkeypatch, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        self._patch_paths(monkeypatch, tmp_path, tmp_path)
        assert migrate_legacy_cache() is None


class TestConfigPersistence:
    def test_defaults_are_not_written(self, tmp_path):
        """Otherwise a saved config pins today's defaults forever."""
        path = tmp_path / "poe2arb.toml"
        save_config(Config(), path)
        assert "cache_dir" not in path.read_text()
        assert "history_path" not in path.read_text()
        assert "request_interval_s" not in path.read_text()

    def test_changed_values_are_written(self, tmp_path):
        path = tmp_path / "poe2arb.toml"
        save_config(Config(min_profit_divines=1.0, sweep_items=15), path)
        text = path.read_text()
        assert "min_profit_divines = 1.0" in text
        assert "sweep_items = 15" in text

    def test_saved_config_follows_new_defaults(self, tmp_path):
        """A user who never touched pacing picks up a safer default later."""
        path = tmp_path / "poe2arb.toml"
        save_config(Config(min_profit_divines=2.0), path)
        assert load_config(path).request_interval_s == Config().request_interval_s

    def test_explicit_custom_path_survives(self, tmp_path):
        custom = tmp_path / "elsewhere"
        path = tmp_path / "poe2arb.toml"
        save_config(Config(cache_dir=custom), path)
        assert load_config(path).cache_dir == custom

    def test_all_defaults_produces_loadable_file(self, tmp_path):
        path = tmp_path / "poe2arb.toml"
        save_config(Config(), path)
        assert load_config(path) == Config()


class TestExampleConfig:
    """The shipped example must stay loadable and stay true.

    It drifted silently before: it still documented `max_cycle_len` and
    `profit_threshold_pct` after both were removed.
    """

    PATH = Path(__file__).resolve().parent.parent / "poe2arb.example.toml"

    def test_it_loads(self):
        assert load_config(self.PATH).sweep_items > 0

    def test_it_documents_no_setting_that_no_longer_exists(self):
        import tomllib

        from poe2arb.config import RETIRED_KEYS

        with open(self.PATH, "rb") as f:
            keys = set(tomllib.load(f))
        assert not (keys & RETIRED_KEYS)

    def test_its_values_match_the_shipped_defaults(self):
        """An example that disagrees with the code teaches the wrong thing."""
        import tomllib

        with open(self.PATH, "rb") as f:
            written = tomllib.load(f)
        default = Config()
        for key, value in written.items():
            if key in ("cache_dir", "outcomes_path", "user_agent", "league"):
                continue
            assert getattr(default, key) == value, key
