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
