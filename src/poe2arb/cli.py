"""poe2-arb command line interface.

Decision-support only: prints signals, never touches the game or executes trades.

One command: `sweep`. The `scan`, `watch` and `rates` commands went with the
triangular cycle search — see TODO.md for why that search was reading the wrong
market. The GUI is the primary surface; this exists for scripting and for
checking a sweep without a display.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .client import ClientError
from .config import Config, load_config
from .report import console, print_candidates
from .sweep import run_sweep

log = logging.getLogger(__name__)

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="poe2-arb",
        description="Find underpriced PoE2 trade listings to resell on the "
                "Currency Exchange (analysis only).",
    )
    p.add_argument("--config", type=Path, help="TOML config file (default: ./poe2arb.toml)")
    p.add_argument("--league", help="league name (default: auto-detect current league)")
    p.add_argument("--cache-dir", type=Path)
    p.add_argument("-v", "--verbose", action="store_true")

    sub = p.add_subparsers(dest="command", required=True)
    sweep = sub.add_parser(
        "sweep",
        help="cross-venue: Bulk Item Exchange listings priced against the Currency Exchange",
    )
    sweep.add_argument("--items", type=int, help="how many items to sweep (default 69)")
    sweep.add_argument("--bankroll", type=float, help="divines available to spend (0 = unbounded)")
    sweep.add_argument("--limit", type=int, default=25, help="rows to print (default 25)")
    return p


def apply_overrides(cfg: Config, args: argparse.Namespace) -> Config:
    if args.league:
        cfg.league = args.league
    if args.cache_dir is not None:
        cfg.cache_dir = args.cache_dir
        cfg.__post_init__()
    if args.items is not None:
        cfg.sweep_items = args.items
    if args.bankroll is not None:
        cfg.bankroll_divines = args.bankroll
    return cfg


def cmd_sweep(cfg: Config, limit: int) -> int:
    """One cross-venue sweep, printed ranked.

    Progress is reported per item because the sweep is ~15 minutes of paced
    requests — silent for that long looks like a hang.
    """
    total_hint = cfg.sweep_items

    def progress(n: int, total: int, item: str) -> None:
        console.print(f"[dim]  {n}/{total}  {item}[/dim]", end="\r", highlight=False)

    log.info("sweeping up to %d items", total_hint)
    result = run_sweep(cfg, progress=progress)
    console.print(" " * 60, end="\r")
    print_candidates(result, limit=limit)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        cfg = apply_overrides(load_config(args.config), args)
        if args.command == "sweep":
            return cmd_sweep(cfg, args.limit)
        raise AssertionError(args.command)
    except KeyboardInterrupt:
        console.print("\n[dim]stopped[/dim]")
        return 130
    except (ClientError, ValueError) as e:
        console.print(f"[red]error:[/red] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
