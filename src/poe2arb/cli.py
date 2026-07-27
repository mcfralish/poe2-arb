"""poe2-arb command line interface.

Decision-support only: prints signals, never touches the game or executes trades.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .client import ClientError
from .config import Config, load_config
from .report import console, print_opportunities, print_rates, route_str
from .scan import run_scan

log = logging.getLogger(__name__)

_INTERVAL_UNITS = {"s": 1, "m": 60, "h": 3600}


def parse_interval(text: str) -> float:
    text = text.strip().lower()
    unit = 1.0
    if text and text[-1] in _INTERVAL_UNITS:
        unit = _INTERVAL_UNITS[text[-1]]
        text = text[:-1]
    try:
        seconds = float(text) * unit
    except ValueError:
        raise argparse.ArgumentTypeError(f"bad interval (use e.g. 10m, 300s, 1h)")
    if seconds < 60:
        raise argparse.ArgumentTypeError("interval must be at least 60s (be polite to the APIs)")
    return seconds


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="poe2-arb",
        description="Detect currency arbitrage cycles in the PoE2 economy (analysis only).",
    )
    p.add_argument("--config", type=Path, help="TOML config file (default: ./poe2arb.toml)")
    p.add_argument("--league", help="league name (default: auto-detect current league)")
    p.add_argument("--threshold", type=float, help="min profit %% per loop to report")
    p.add_argument("--fee", type=float, help="fee/slippage haircut %% per hop")
    p.add_argument("--max-currencies", type=int, help="graph size cap (top-N by volume)")
    p.add_argument("--max-cycle-len", type=int, choices=(3, 4), help="max loop length")
    p.add_argument("--cache-dir", type=Path)
    p.add_argument("-v", "--verbose", action="store_true")

    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="one-shot: fetch (or use cache), analyze, print ranked loops")
    watch = sub.add_parser("watch", help="re-scan on an interval; print only changes")
    watch.add_argument("--interval", type=parse_interval, default=600.0, help="e.g. 10m (default)")
    rates = sub.add_parser("rates", help="pay/receive book rates for one currency")
    rates.add_argument("currency", help="currency id, e.g. chaos, exalted, annul")
    return p


def apply_overrides(cfg: Config, args: argparse.Namespace) -> Config:
    if args.league:
        cfg.league = args.league
    if args.threshold is not None:
        cfg.profit_threshold_pct = args.threshold
    if args.fee is not None:
        cfg.fee_pct = args.fee
    if args.max_currencies is not None:
        cfg.max_currencies = args.max_currencies
    if args.max_cycle_len is not None:
        cfg.max_cycle_len = args.max_cycle_len
    if args.cache_dir is not None:
        cfg.cache_dir = args.cache_dir
        cfg.__post_init__()
    return cfg


def cmd_scan(cfg: Config) -> int:
    result = run_scan(cfg)
    print_opportunities(
        result.opportunities,
        result.overview.names,
        league=result.league,
        threshold_pct=cfg.profit_threshold_pct,
        longer_cycle=result.longer_cycle,
    )
    return 0


def cmd_watch(cfg: Config, interval_s: float) -> int:
    console.print(
        f"[bold]watch[/bold]: scanning every {interval_s / 60:.0f}m — Ctrl-C to stop"
    )
    known: dict[tuple[str, ...], float] = {}
    while True:
        try:
            result = run_scan(cfg)
        except ClientError as e:
            console.print(f"[red]scan failed:[/red] {e} — retrying next interval")
        else:
            current = {op.key: op.profit_pct for op in result.opportunities}
            names = result.overview.names
            ts = time.strftime("%H:%M:%S")
            for op in result.opportunities:
                if op.key not in known:
                    console.print(
                        f"[green][{ts}] NEW[/green]  {route_str(op, names)}: "
                        f"+{op.profit_pct:.2f}% (depth {op.min_depth_divines:.1f} div)"
                    )
            for gone_key in set(known) - set(current):
                gone_route = " → ".join(gone_key) + f" → {gone_key[0]}"
                console.print(f"[dim][{ts}] gone[/dim] {gone_route} (was +{known[gone_key]:.2f}%)")
            if not result.opportunities and not known:
                console.print(f"[dim][{ts}] nothing above threshold[/dim]")
            known = current
        time.sleep(interval_s)


def cmd_rates(cfg: Config, currency: str) -> int:
    result = run_scan(cfg, log_history=False)
    if currency not in result.overview.values:
        known_ids = ", ".join(sorted(result.overview.values))
        console.print(f"[red]unknown currency id {currency!r}[/red]\nknown ids: {known_ids}")
        return 1
    print_rates(currency, result.overview, result.edges)
    if currency not in result.nodes:
        console.print(
            "[yellow]note:[/yellow] currency is below the liquidity floor / top-N cap, "
            "so no order-book edges were fetched for it"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        cfg = apply_overrides(load_config(args.config), args)
        if args.command == "scan":
            return cmd_scan(cfg)
        if args.command == "watch":
            return cmd_watch(cfg, args.interval)
        if args.command == "rates":
            return cmd_rates(cfg, args.currency)
        raise AssertionError(args.command)
    except KeyboardInterrupt:
        console.print("\n[dim]stopped[/dim]")
        return 130
    except (ClientError, ValueError) as e:
        console.print(f"[red]error:[/red] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
