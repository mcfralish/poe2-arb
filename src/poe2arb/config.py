"""Configuration: defaults, TOML file loading/saving, CLI overrides."""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tomllib
from dataclasses import MISSING, dataclass, field, fields
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_CONFIG_NAME = "poe2arb.toml"


def user_config_path() -> Path:
    """Per-user config location, used by the GUI (CLI reads ./poe2arb.toml)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "poe2-arb" / DEFAULT_CONFIG_NAME


def user_cache_path() -> Path:
    """Per-user cache location, following each platform's own convention.

    `~/.cache` is a Linux/XDG idea; on Windows it leaves a stray dotfolder in
    the profile root, where LOCALAPPDATA is the native home for regenerable
    data like this.
    """
    if sys.platform == "win32":
        base = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        )
        return base / "poe2-arb"
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "poe2-arb"


def legacy_cache_path() -> Path:
    """Where versions up to 0.2.1 kept the cache on every platform."""
    return Path.home() / ".cache" / "poe2-arb"


def migrate_legacy_cache() -> Path | None:
    """Move a pre-0.2.2 cache directory to the platform-native location.

    Returns the destination if anything moved. Best-effort: a failure here
    costs a re-fetch and a gap in history, never a crash on startup.
    """
    old, new = legacy_cache_path(), user_cache_path()
    if old == new or not old.is_dir() or new.exists():
        return None
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(new))
        return new
    except OSError:
        log.warning("could not migrate cache from %s to %s", old, new, exc_info=True)
        return None


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

    # Currencies to keep out of the graph regardless of how liquid they look.
    # Mirrors are excluded by default: a single one costs thousands of divines,
    # so any "opportunity" through one is unreachable for most players and just
    # crowds out loops they could actually trade.
    exclude_currencies: list[str] = field(default_factory=lambda: ["mirror"])
    # Also drop anything worth more than this many divines per unit (0 = off).
    max_currency_value_divines: float = 0.0

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
    # Spacing between GGG requests. Must stay above 10s: at exactly 10s a 300s
    # window can catch 31 requests against a limit of 30, and the penalty for
    # crossing it is a 30-minute IP ban. See rate_limit.py.
    request_interval_s: float = 13.0
    # Share of each rate-limit window this app will use, leaving the rest for
    # anything else hitting the trade API from the same IP.
    rate_limit_safety_fraction: float = 0.8
    user_agent: str = "poe2-arb/0.2 (analysis-only arbitrage scanner; +https://github.com/mcfralish/poe2-arb)"

    # Paths
    cache_dir: Path = field(default_factory=user_cache_path)
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
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(item) for item in v) + "]"
    text = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _default_for(f) -> object:
    if f.default is not MISSING:
        return f.default
    if f.default_factory is not MISSING:  # type: ignore[misc]
        return f.default_factory()  # type: ignore[misc]
    return MISSING


def save_config(cfg: Config, path: Path) -> None:
    """Write a flat TOML file that load_config can read back (stdlib only).

    Fields still at their default are omitted. That keeps saved files short,
    and — more importantly — lets defaults change in a later version instead
    of being frozen into every user's config the first time they hit Save.
    Paths were the painful case: a saved cache_dir would pin the old location
    forever.
    """
    reference = Config()
    lines = []
    for f in fields(Config):
        value = getattr(cfg, f.name)
        if value is None:
            continue
        # history_path is derived from cache_dir in __post_init__, so compare
        # against a Config built the same way rather than the raw default.
        if value == getattr(reference, f.name):
            continue
        if isinstance(value, Path):
            value = str(value)
        lines.append(f"{f.name} = {_toml_value(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
