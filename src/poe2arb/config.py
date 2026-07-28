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
    # Conservatism margin taken off every hop. **Not** a fee, despite what the
    # old `fee_pct` name claimed. The two things that name pointed at both fail:
    # the exchange fee is gold-denominated, and gold isn't tradeable or priced in
    # divines, so charging it as a percentage of divine value is a category
    # error; and slippage is already captured by walking the book to
    # depth_divines, so charging it again double-counts.
    # What's left is genuine but different: fill risk. The offer you found may
    # be gone by the time you get there, and a partial fill strands you holding
    # the wrong currency mid-loop. That's worth a margin if you want one, so the
    # knob stays — but it defaults to nothing rather than to a guess.
    safety_margin_pct: float = 0.0
    liquidity_floor_divines: float = 20.0  # min daily volume (poe.ninja volumePrimaryValue)
    max_currencies: int = 10            # top-N by volume included in the graph
    max_cycle_len: int = 4              # 3 or 4

    # Items kept out of the graph, and hidden from the Market and Book edges
    # views, regardless of how liquid they look. Empty by default — excluding
    # anything is the user's call, not ours.
    exclude_currencies: list[str] = field(default_factory=list)
    # Also drop anything worth more than this many divines per unit (0 = off).
    max_currency_value_divines: float = 0.0

    # Order-book pricing (GGG trade2 exchange)
    depth_divines: float = 5.0          # edge rate = marginal rate to fill this much value
    bait_filter_ratio: float = 1.10     # drop offers better than fair * this (scam bait)
    min_accounts: int = 2               # fill must span this many lister accounts
    have_chunk: int = 6                 # currencies per `have` list in one exchange request

    # The currency prices are displayed in. Internal maths stays in divines;
    # this only affects what the UI shows.
    base_currency: str = "adaptive"

    # Watch / GUI
    watch_interval_minutes: float = 10.0  # re-scan cadence for watch mode and the GUI
    alert_sound: bool = True            # GUI: play a sound with the toast notification
    skip_install_prompt: bool = False   # set once the user declines the install offer

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
    # How long scan records are kept. A watch loop appends one every few
    # minutes indefinitely, so something has to age them out. 0 = keep forever.
    history_retention_days: float = 30.0

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
    _rename_legacy_keys(data)
    known = {f.name for f in fields(Config)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"unknown config keys in {path}: {sorted(unknown)}")
    _unpin_legacy_paths(data)
    return Config(**data)


# Old key -> current key. Unknown keys are a hard error (they're usually typos),
# so a rename has to be translated here or every existing config stops loading.
LEGACY_KEYS = {"fee_pct": "safety_margin_pct"}


def _rename_legacy_keys(data: dict) -> None:
    for old, new in LEGACY_KEYS.items():
        if old not in data:
            continue
        value = data.pop(old)
        # An explicitly-set new key wins; the old one is just dropped.
        data.setdefault(new, value)
        log.info("config key %r has been renamed to %r", old, new)


def _unpin_legacy_paths(data: dict) -> None:
    """Drop stored paths that merely repeat the old built-in default.

    Versions before 0.2.2 wrote every field out, so a config can pin
    ~/.cache/poe2-arb even though the user never chose it. Left in place that
    pin silently defeats the move to the platform-native location — the
    migration runs, then the config drags the app back to the old path.
    """
    legacy = legacy_cache_path()
    if "cache_dir" in data and Path(data["cache_dir"]).expanduser() == legacy:
        del data["cache_dir"]
        if "history_path" in data and (
            Path(data["history_path"]).expanduser() == legacy / "history.jsonl"
        ):
            del data["history_path"]


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
