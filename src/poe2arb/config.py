"""Configuration: defaults, TOML file loading/saving, CLI overrides."""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

DEFAULT_CONFIG_NAME = "poe2arb.toml"


def user_config_path() -> Path:
    """Per-user config location, used by the GUI (CLI reads ./poe2arb.toml)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "poe2-arb" / DEFAULT_CONFIG_NAME


@dataclass
class Config:
    # League. None means auto-detect: first league returned by
    # poe.ninja's /poe2/api/economy/leagues (the current temp league).
    league: str | None = None

    # Signal filtering
    profit_threshold_pct: float = 3.0   # min net profit per loop to report
    fee_pct: float = 1.5                # haircut per hop (gold fee + fill slippage)
    liquidity_floor_divines: float = 20.0  # min daily volume (poe.ninja volumePrimaryValue)
    max_currencies: int = 10            # top-N by volume included in the graph
    max_cycle_len: int = 4              # 3 or 4

    # Order-book pricing (GGG trade2 exchange)
    depth_divines: float = 5.0          # edge rate = marginal rate to fill this much value
    bait_filter_ratio: float = 1.10     # drop offers better than fair * this (scam bait)
    min_accounts: int = 2               # fill must span this many lister accounts
    have_chunk: int = 6                 # currencies per `have` list in one exchange request

    # Watch / GUI
    watch_interval_minutes: int = 10    # re-scan cadence for watch mode and the GUI
    alert_sound: bool = True            # GUI: play a sound with the toast notification

    # Politeness / caching
    refresh_minutes: int = 10           # min age before re-fetching any remote data
    request_interval_s: float = 10.0    # min spacing between GGG requests (5/15s, 10/90s, 30/300s limits)
    user_agent: str = "poe2-arb/0.2 (analysis-only arbitrage scanner; +https://github.com/mcfralish/poe2-arb)"

    # Paths
    cache_dir: Path = field(default_factory=lambda: Path.home() / ".cache" / "poe2-arb")
    history_path: Path | None = None    # default: <cache_dir>/history.jsonl

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir).expanduser()
        if self.history_path is None:
            self.history_path = self.cache_dir / "history.jsonl"
        else:
            self.history_path = Path(self.history_path).expanduser()
        if self.max_cycle_len not in (3, 4):
            raise ValueError("max_cycle_len must be 3 or 4")


def load_config(path: Path | None = None) -> Config:
    """Load config from a TOML file. Missing file (when not explicitly given) = defaults."""
    if path is None:
        candidate = Path.cwd() / DEFAULT_CONFIG_NAME
        if not candidate.exists():
            return Config()
        path = candidate
    with open(path, "rb") as f:
        data = tomllib.load(f)
    known = {f.name for f in fields(Config)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"unknown config keys in {path}: {sorted(unknown)}")
    return Config(**data)


def _toml_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    text = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def save_config(cfg: Config, path: Path) -> None:
    """Write a flat TOML file that load_config can read back (stdlib only)."""
    lines = []
    for f in fields(Config):
        value = getattr(cfg, f.name)
        if value is None:
            continue
        if isinstance(value, Path):
            value = str(value)
        lines.append(f"{f.name} = {_toml_value(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
