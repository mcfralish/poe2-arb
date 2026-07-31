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

    # Items kept out of the sweep and marked as excluded on the Market tab.
    # Empty by default — excluding anything is the user's call, not ours.
    exclude_currencies: list[str] = field(default_factory=list)

    # --- Cross-venue sweep (Bulk Item Exchange listings vs Currency Exchange) ---
    # How many items each sweep covers, most-CE-traded first. 69 items is
    # ~15 minutes at the default request interval, which fits inside the
    # observed listing churn window; a wider sweep would serve results older
    # than the listings they describe.
    sweep_items: int = 69
    # Skip items worth less than this per unit. **Not** a rounding constraint —
    # settling in exalted makes the floor negligible. It is about whether a
    # trade is worth sending a message for: stock on this venue is single
    # digits, so at a plausible ~1.2x gap an item has to be worth a couple of
    # divines before one lot clears min_profit_divines. Probed live: chaos and
    # greater-chaos-orb had zero listings below CE at all.
    sweep_min_value_divines: float = 1.0
    # Currency to settle CE sales in. Exalted is ~432x finer than divine, and
    # on the one trade that filled that is the difference between 1.00 and 1.79
    # divines of profit. Set to "divine" to price the pessimistic case.
    sale_currency: str = "exalted"
    # Drop candidates below this. Settling in exalted makes tiny trades
    # arithmetically profitable; +0.02 divines is real and still not worth a
    # whisper.
    min_profit_divines: float = 0.25
    # Skip items the Currency Exchange barely trades — a discount is worthless
    # if you cannot sell the item afterwards. Units are poe2scout's ValueTraded,
    # which is comparable between items but not convertible to divines.
    sweep_min_ce_traded: float = 100_000.0
    # What you actually hold, per currency. 0 = unbounded in that currency.
    # Kept separate rather than pooled into one divine figure: a seller asking
    # for exalted can only be paid in exalted, and converting divines across on
    # the Currency Exchange costs the spread — so a pooled number would plan
    # quantities you cannot buy. Caps the lots a candidate can plan for;
    # ranking listings you cannot afford is noise.
    bankroll_divines: float = 0.0
    bankroll_exalted: float = 0.0
    # How far to chase long shots, 0 to 1. Bands are always labelled honestly;
    # this decides how much a band's measured fill rate is allowed to suppress
    # its profit when ranking. 0 ranks by what actually fills and buries the
    # 12x listings; 1 ranks on profit alone and puts them at the top. Defaults
    # to 0 because that is what the field tests support — the long shots
    # returned nothing across ~10 whispers.
    risk_appetite: float = 0.0
    # The gap band worth whispering.
    # Lower bound is our own measurement error: the poe2scout reference ran
    # 0.4%-4.7% below the live game across five checked items, so below ~1.05
    # a "discount" is indistinguishable from noise and so is its profit figure.
    # Upper bound is the measured fill pattern: over 14 whispers both fills came
    # from gaps of 1.13x and 1.9x, while roughly ten attempts at 3.8x-12.5x
    # produced none. Beyond it a listing is a ghost — demoted, not hidden.
    # Provisional; outcome logging is meant to replace both with a fitted curve.
    min_gap_ratio: float = 1.05
    max_gap_ratio: float = 1.50
    # Global hotkey that advances the trade queue and copies the next whisper.
    # Clipboard only — it never sends input to the game. Windows-only; ignored
    # elsewhere. Empty disables it.
    trade_hotkey: str = "ctrl+alt+d"
    trade_hotkey_enabled: bool = False
    # How long a new trade stays "live": a toast fires and the hotkey is armed.
    # Short on purpose — it gates how fast the queue drains, not how long the
    # user has to decide, because an unclaimed offer is not lost, it just drops
    # into the list below. Only one trade is ever live at a time.
    offer_window_s: float = 20.0
    # How long a lapsed offer stays takeable from the Opportunities tab before
    # it is dropped. Generous relative to the alert window: an offer you didn't
    # catch mid-pack is still perfectly good five minutes later.
    available_ttl_s: float = 300.0
    # How long a whispered trade waits for a verdict before recording itself as
    # "no reply" — which is almost always what happened. 0 disables it, at the
    # cost of a list that grows until every row is answered by hand.
    awaiting_timeout_s: float = 600.0

    # The currency prices are displayed in. Internal maths stays in divines;
    # this only affects what the UI shows.
    base_currency: str = "adaptive"

    # GUI
    # Gap between sweeps while "Find trades" is on. Listings churn slower than
    # a sweep runs, and back-to-back sweeps would spend the whole rate-limit
    # budget re-reading listings that have not changed.
    sweep_interval_minutes: float = 10.0
    alert_sound: bool = True            # GUI: play a sound with the toast notification
    skip_install_prompt: bool = False   # set once the user declines the install offer
    # Keep the window above other windows, including the game. Off by default
    # because it is only wanted during a heavy trading session — the rest of the
    # time a window that will not go behind anything is an obstruction.
    always_on_top: bool = False

    # Politeness / caching
    refresh_minutes: int = 10           # min age before re-fetching any remote data
    # Currency Exchange reference prices (poe2scout). Longer than
    # refresh_minutes because it's a ~2 MB snapshot of a market that moves in
    # percent-per-hour, and it's one volunteer-run host we shouldn't hammer.
    ce_refresh_minutes: int = 60
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
    # Whisper attempts and what came of them — the app's only permanent record.
    outcomes_path: Path | None = None   # default: <cache_dir>/outcomes.jsonl
    # How long attempts are kept. 0 = keep forever, which is the honest default
    # for a log whose whole value is accumulating enough of it to fit a model.
    history_retention_days: float = 0.0

    def __post_init__(self) -> None:
        self.cache_dir = Path(self.cache_dir).expanduser()
        if self.outcomes_path is None:
            self.outcomes_path = self.cache_dir / "outcomes.jsonl"
        else:
            self.outcomes_path = Path(self.outcomes_path).expanduser()

    def bankroll(self) -> dict[str, float]:
        """Holdings by currency id, for build_candidates. Zeroes are omitted.

        An absent currency means unconstrained, so dropping the zeroes here is
        what makes "0 = no limit" work at the far end.
        """
        pots = {"divine": self.bankroll_divines, "exalted": self.bankroll_exalted}
        return {currency: held for currency, held in pots.items() if held > 0}


def load_config(path: Path | None = None) -> Config:
    """Load config from a TOML file. Missing file (when not explicitly given) = defaults."""
    if path is None:
        candidate = Path.cwd() / DEFAULT_CONFIG_NAME
        if not candidate.exists():
            return Config()
        path = candidate
    with open(path, "rb") as f:
        data = tomllib.load(f)
    _drop_retired_keys(data)
    known = {f.name for f in fields(Config)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"unknown config keys in {path}: {sorted(unknown)}")
    _unpin_legacy_paths(data)
    return Config(**data)


# Settings that no longer exist. Unknown keys are a hard error, because they are
# usually typos — but a key we removed ourselves is not the user's mistake, and
# refusing to start over it would strand everyone upgrading from 0.3.x with a
# config full of triangular-scan knobs. Dropped quietly, logged once.
RETIRED_KEYS = frozenset({
    # The triangular cycle search and everything that tuned it (removed 0.4.0).
    "fee_pct", "safety_margin_pct", "profit_threshold_pct",
    "liquidity_floor_divines", "max_currencies", "max_cycle_len",
    "max_currency_value_divines", "depth_divines", "bait_filter_ratio",
    "min_accounts", "have_chunk", "watch_interval_minutes", "history_path",
})


def _drop_retired_keys(data: dict) -> None:
    retired = sorted(RETIRED_KEYS & set(data))
    for key in retired:
        del data[key]
    if retired:
        log.info(
            "ignoring settings that no longer exist: %s", ", ".join(retired)
        )


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
