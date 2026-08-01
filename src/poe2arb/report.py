"""Terminal output for the CLI (rich tables).

Only the sweep prints anything now. The cycle-report and order-book tables went
with the triangular search they described.
"""

from __future__ import annotations

from collections import Counter

from rich.console import Console
from rich.table import Table

from .format import fmt_value

console = Console()


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
        "pays 3 on one unit. Ghosts are listings far enough below market that only "
        "about 1 whisper in 50 leads to a trade; they are demoted, not hidden. "
        "Analysis only — whisper and trade by hand.[/dim]"
    )
    if result.errors:
        console.print(f"[yellow]{len(result.errors)} item(s) failed:[/yellow] "
                      f"{', '.join(sorted(result.errors))}")
