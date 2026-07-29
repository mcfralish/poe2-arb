"""Terminal output formatting (rich tables)."""

from __future__ import annotations

from collections import Counter

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


def _fmt_div(value: float) -> str:
    """Divine amounts, compact. These sit in narrow columns beside each other."""
    if value >= 1000:
        return f"{value:,.0f}"
    if value >= 10:
        return f"{value:.1f}"
    return f"{value:.3g}"


def print_candidates(result, limit: int = 25) -> None:
    """Ranked cross-venue candidates: buy by whisper, sell into the Currency Exchange.

    Bands are shown rather than filtered. A ghost is a listing far enough below
    market that the evidence says it will not fill (see TODO.md, "Negative
    results"); it stays visible so the ranking can be judged, and so anyone who
    wants to test one can find it.

    Columns are pinned no-wrap so the numbers stay comparable down the page —
    an 80-column terminal will drop the seller before it mangles the maths.
    """
    from .listings import Band, whisper_text

    table = Table(
        title=f"cross-venue candidates — {result.league} "
              f"({result.listings_seen} listings / {len(result.items)} items / "
              f"{result.duration_s:.0f}s)",
        pad_edge=False,
        padding=(0, 1),
    )
    table.add_column("band", no_wrap=True)
    table.add_column("item", overflow="ellipsis", max_width=22, no_wrap=True)
    table.add_column("listed", justify="right", no_wrap=True, min_width=6)
    table.add_column("pay", no_wrap=True, min_width=3)
    table.add_column("CE", justify="right", no_wrap=True, min_width=6)
    table.add_column("gap", justify="right", no_wrap=True)
    table.add_column("buy", justify="right", no_wrap=True, min_width=4)
    table.add_column("cost", justify="right", no_wrap=True, min_width=6)
    table.add_column("profit", justify="right", no_wrap=True, min_width=6)
    table.add_column("age", justify="right", no_wrap=True)
    table.add_column("seller", overflow="ellipsis", max_width=18, no_wrap=True)

    colour = {Band.PLAUSIBLE: "green", Band.THIN: "yellow", Band.GHOST: "dim"}
    for c in result.candidates[:limit]:
        age = c.listing.age_s()
        if age is None:
            age_s = "?"
        elif age >= 3600:
            age_s = f"{age / 3600:.0f}h"
        else:
            age_s = f"{age / 60:.0f}m"
        style = colour[c.band]
        seller = c.listing.character or c.listing.account
        table.add_row(
            f"[{style}]{c.band.value}[/{style}]",
            c.item_name,
            _fmt_div(c.unit_price_divines),
            {"exalted": "ex", "divine": "div", "chaos": "ch"}.get(c.listing.pay_currency, c.listing.pay_currency[:4]),
            _fmt_div(c.ce_divines),
            # A 4815x gap is a scam listing, not a number worth reading precisely.
            ">99x" if c.gap > 99 else f"{c.gap:.2f}x",
            f"{c.plan.units:g}",
            _fmt_div(c.plan.cost_divines),
            f"[bold]{_fmt_div(c.profit_divines)}[/bold]",
            f"{age_s}{'*' if c.listing.afk else ''}",
            seller,
        )
    console.print(table)
    if not result.candidates:
        console.print("[dim]no listings below Currency Exchange value this sweep[/dim]")
        return

    counts = Counter(c.band for c in result.candidates)
    console.print(
        f"[green]{counts[Band.PLAUSIBLE]} plausible[/green] · "
        f"[yellow]{counts[Band.THIN]} thin[/yellow] · "
        f"[dim]{counts[Band.GHOST]} ghost[/dim]   (* = AFK)"
    )
    top = result.candidates[0]
    text = whisper_text(top)
    if text:
        console.print(f"\n[bold]whisper for the top candidate[/bold]\n{text}")
    console.print(
        "\n[dim]Profit is floored — partial currency can't be traded, so a 3.79 rate "
        "pays 3 on one unit. Ghosts are listings far enough below market that the "
        "measured fill rate is zero; they rank last on purpose. "
        "Analysis only — whisper and trade by hand.[/dim]"
    )
    if result.errors:
        console.print(f"[yellow]{len(result.errors)} item(s) failed:[/yellow] "
                      f"{', '.join(sorted(result.errors))}")
