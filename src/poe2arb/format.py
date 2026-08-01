"""Shared number formatting, so every number reads the same everywhere.

Currency values in PoE2 span a huge range — a Mirror is worth thousands of
divines, a Wisdom Scroll a fraction of one — so a single fixed format either
rounds small values to "0.0000" or drowns big ones in noise. The rule here:
a standard number of decimals for everything, expanded only when rounding
would otherwise destroy the value entirely. Never scientific notation, which
is what `%g` produced and what made the tables ragged.
"""

from __future__ import annotations

import math

STANDARD_DECIMALS = 4
MAX_DECIMALS = 10


def fmt_num(value: float, decimals: int = STANDARD_DECIMALS) -> str:
    """Fixed-decimal number with thousands separators.

    Values too small to survive `decimals` rounding get extra places rather
    than displaying as zero (a 0.000002 rate is meaningful; "0.0000" isn't).
    """
    if value is None or not math.isfinite(value):
        return "∞" if value == math.inf else "—"
    if value != 0:
        magnitude = math.floor(math.log10(abs(value)))
        if magnitude < -decimals:
            # Keep ~2 significant figures for very small numbers.
            decimals = min(MAX_DECIMALS, -magnitude + 1)
    return f"{value:,.{decimals}f}"


def fmt_value(value: float) -> str:
    """A currency's worth, in divines."""
    return fmt_num(value)


def fmt_rate(rate: float) -> str:
    """An exchange rate (units received per 1 paid)."""
    return fmt_num(rate)


def fmt_volume(value: float) -> str:
    """Daily traded volume in divines — whole numbers are plenty."""
    if value is None or not math.isfinite(value):
        return "∞" if value == math.inf else "—"
    return f"{value:,.0f}"


def fmt_depth(value: float) -> str:
    """Order-book depth in divines."""
    return fmt_num(value, decimals=1)


def fmt_pct(value: float, *, signed: bool = True) -> str:
    """A percentage, always with two decimals."""
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:,.2f}%"


# Short suffixes for the currencies the app quotes in. One table, because three
# panels show these and they had drifted into three private copies.
CURRENCY_SUFFIX = {
    "exalted": "ex",
    "divine": "div",
    "chaos": "chaos",
    "annul": "annul",
}


def currency_label(currency: str) -> str:
    """Short suffix for a currency id, or the id itself if we don't know it."""
    return CURRENCY_SUFFIX.get(currency, currency)


def fmt_qty(value: float) -> str:
    """A quantity of orbs, at the precision that quantity deserves.

    Amounts in this app span "0.0046 divine" to "2,412 exalted", and a fixed
    format makes one end of that unreadable. Whole numbers stay whole, because
    listing prices are whole units of the seller's currency and a trailing
    ".0" on the figure that went into a whisper reads as a different number.
    """
    if value is None or not math.isfinite(value):
        return "—"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    if float(value).is_integer():
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.3g}"


def fmt_amount(value: float, currency: str) -> str:
    """An amount in a named currency: "2,412 ex"."""
    return f"{fmt_qty(value)} {currency_label(currency)}"


def fmt_profit(value: float, decimals: int = 2) -> str:
    """Divines cleared, with the sign always shown.

    Every profit figure in the app used to be written `f"+{value:.2f}"`, which
    was safe only while profit could not be negative — `plan_trade` refuses a
    losing quantity. It can be negative now: a trade amended to a counteroffered
    price can turn out to have lost money, which is the whole reason the price
    became editable. `"+-1.20"` is exactly the sort of thing a hand-written
    format produces, so this owns the sign.
    """
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value:+,.{decimals}f}"


def fmt_skew(seconds: float | None) -> str:
    """How far apart a loop's edges were observed, as a duration.

    Minutes and seconds rather than raw seconds: "3m 54s" lands as "most of a
    scan ago" in a way that "234s" does not.
    """
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}m {rest:02d}s"
