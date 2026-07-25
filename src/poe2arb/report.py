"""Terminal output formatting (rich tables)."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .client import NinjaOverview
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
    longer_cycle_hint: bool,
) -> None:
    if not ops:
        console.print(
            f"[dim]No arbitrage loops ≥ {threshold_pct:.1f}% in {league} right now.[/dim]"
        )
        if longer_cycle_hint:
            console.print(
                "[yellow]Note:[/yellow] Bellman-Ford detects a profitable loop outside the "
                "reported length/threshold window — consider raising max_cycle_len or "
                "lowering the threshold."
            )
        return
    table = Table(title=f"Arbitrage loops — {league}")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Route")
    table.add_column("Profit/loop", justify="right", style="green")
    table.add_column("Depth (div)", justify="right")
    for i, op in enumerate(ops, 1):
        table.add_row(
            str(i),
            route_str(op, names),
            f"+{op.profit_pct:.2f}%",
            f"{op.min_depth_divines:.1f}",
        )
    console.print(table)
    console.print(
        "[dim]Depth = bottleneck order-book depth: max value the loop supports at these "
        "rates. Analysis only — execute (or don't) by hand in game.[/dim]"
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
        console.print(f"  poe.ninja value: {value:.4f} divine   daily volume: {vol:,.0f} div")
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
    table.add_column("Effective (after fee)", justify="right")
    table.add_column("Depth (div)", justify="right")
    for e in sell:
        table.add_row(
            "pay", f"{currency} → {e.dst}", f"{e.raw_rate:.6g}", f"{e.rate:.6g}",
            f"{e.depth_filled_divines:.1f}",
        )
    for e in buy:
        table.add_row(
            "receive", f"{e.src} → {currency}", f"{e.raw_rate:.6g}", f"{e.rate:.6g}",
            f"{e.depth_filled_divines:.1f}",
        )
    console.print(table)
