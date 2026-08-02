"""How a band is shown, in one place so every tab shows it the same way.

The Trades tab and the Results tab both display the band a listing was ranked
in, and they used different vocabularies for it — glyphs in one, the raw enum
name in the other — so the same fact read as two unrelated columns. This module
is the single source for the symbol, the short label and the long explanation.

Kept separate from either panel because both import it; putting it in one panel
would make the other depend on its sibling.

`from_name` exists because the outcome log stores the band as a bare string.
Records written months ago must still resolve, and an unknown name has to degrade
to something printable rather than raising inside a table redraw.
"""

from __future__ import annotations

from ..listings import Band

BAND_LABEL = {
    Band.PLAUSIBLE: "●",
    Band.THIN: "○",
    Band.GHOST: "×",
}

# Short enough for a legend line. The long form is BAND_TIP.
BAND_LEGEND = {
    Band.PLAUSIBLE: "worth trying",
    Band.THIN: "uncertain",
    Band.GHOST: "too good to be true",
}

# Every number here is measured and dated, because all three of these tooltips
# were wrong at once before 2026-08-01 — one said ghosts had never been answered
# when 12 had, and one said the price estimate ran 25% high when it runs ~6%
# either way. A tooltip is where a stale finding is least likely to be noticed
# and most likely to be believed. Sources: docs/FINDINGS.md, "Negative results"
# 1 and "The reference price does not match what a sale realises".
BAND_TIP = {
    Band.PLAUSIBLE: (
        "Worth trying — a real seller pricing under market. About 1 whisper in 8 "
        "leads to a trade (12% of 178), the best rate of any band."
    ),
    Band.THIN: (
        "Uncertain — the discount is no bigger than the error in our own price "
        "estimate, so the profit shown may not be real. That estimate has been "
        "measured about 6% out in either direction, and further on rarely-traded "
        "items."
    ),
    Band.GHOST: (
        "Too good to be true — far below market. Most are mistakes, abandoned "
        "listings or already sold, and only 1 whisper in 50 leads to a trade "
        "(2% of 601) — but the ones that land are large, so these are ranked "
        "below a plausible trade rather than last. Never hidden."
    ),
}

ORDER = (Band.PLAUSIBLE, Band.THIN, Band.GHOST)


def from_name(name: str) -> Band | None:
    """The Band a stored string refers to, or None if it isn't one we know."""
    try:
        return Band(name)
    except ValueError:
        return None


def symbol_for_name(name: str) -> str:
    """The glyph for a band recorded in the outcome log.

    Falls back to the stored text so an unrecognised record still shows what it
    said, rather than an empty cell that looks like data loss.
    """
    band = from_name(name)
    return BAND_LABEL[band] if band is not None else (name or "?")


def tip_for_name(name: str) -> str:
    band = from_name(name)
    return BAND_TIP[band] if band is not None else ""


def legend_text(prefix: str = "Odds:") -> str:
    """The key, as one line, shared by every tab that shows the glyphs."""
    body = "      ".join(f"{BAND_LABEL[b]}  {BAND_LEGEND[b]}" for b in ORDER)
    return f"{prefix}   {body}" if prefix else body


def legend_tooltip() -> str:
    return "\n\n".join(BAND_TIP[b] for b in ORDER)
