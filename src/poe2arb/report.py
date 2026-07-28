"""Terminal output formatting (rich tables)."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .client import NinjaOverview
from .format import fmt_depth, fmt_pct, fmt_rate, fmt_skew, fmt_value, fmt_volume
from .graph import Edge, Opportunity

console = Console()


def route_str(op: Opportunity, names: dict[str, str]) -> str:
    hops = [names.get(c, c) for c in op.cycle] + [names.get(op.cycle[0], op.cycle[0])]
    return " → ".join(hops)


def print_opportunities(
    ops: list[Opportunity],
    names: dict[str, str],
    *,
    league: str,
    threshold_pct: float,
    longer_cycle: Opportunity | None = None,
) -> None:
    if not ops:
        console.print(
            f"[dim]No arbitrage loops ≥ {threshold_pct:.1f}% in {league} right now.[/dim]"
        )
        if longer_cycle is not None:
            console.print(
                f"[yellow]Note:[/yellow] Bellman-Ford found a profitable loop outside the "
                f"reported window: [bold]{route_str(longer_cycle, names)}[/bold] at "
                f"{fmt_pct(longer_cycle.profit_pct)} "
                f"(depth {fmt_depth(longer_cycle.min_depth_divines)} div). "
                f"Raise max_cycle_len or lower the threshold to have it reported."
            )
        return
    table = Table(title=f"Arbitrage loops — {league}")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Route")
    table.add_column("Profit/loop", justify="right", style="green")
    table.add_column("Depth (div)", justify="right")
    table.add_column("Spread", justify="right", style="dim")
    for i, op in enumerate(ops, 1):
        table.add_row(
            str(i),
            route_str(op, names),
            fmt_pct(op.profit_pct),
            fmt_depth(op.min_depth_divines),
            fmt_skew(op.skew_s),
        )
    console.print(table)
    console.print(
        "[dim]Depth = bottleneck order-book depth: max value the loop supports at these "
        "rates. Spread = time between the oldest and newest price in the loop; a scan "
        "checks one currency at a time, so nothing is ever seen simultaneously. "
        "Analysis only — execute (or don't) by hand in game.[/dim]"
    )


def print_rates(
    currency: str,
    overview: NinjaOverview,
    edges: dict[tuple[str, str], Edge],
) -> None:
    name = overview.names.get(currency, currency)
    value = overview.values.get(currency)
    vol = overview.volumes.get(currency)
    console.print(f"[bold]{name}[/bold] ({currency})")
    if value is not None:
        console.print(
            f"  poe.ninja value: {fmt_value(value)} divine   "
            f"daily volume: {fmt_volume(vol)} div"
        )
    sell = sorted(
        (e for (s, _), e in edges.items() if s == currency), key=lambda e: e.dst
    )
    buy = sorted(
        (e for (_, d), e in edges.items() if d == currency), key=lambda e: e.src
    )
    if not sell and not buy:
        console.print("[dim]  no order-book edges above the liquidity/depth floor[/dim]")
        return
    table = Table(show_header=True)
    table.add_column("Direction")
    table.add_column("Pair")
    table.add_column("Book rate", justify="right")
    table.add_column("After margin", justify="right")
    table.add_column("Depth (div)", justify="right")
    for e in sell:
        table.add_row(
            "pay", f"{currency} → {e.dst}", fmt_rate(e.raw_rate), fmt_rate(e.rate),
            fmt_depth(e.depth_filled_divines),
        )
    for e in buy:
        table.add_row(
            "receive", f"{e.src} → {currency}", fmt_rate(e.raw_rate), fmt_rate(e.rate),
            fmt_depth(e.depth_filled_divines),
        )
    console.print(table)
