"""Colours that survive both light and dark themes.

The app hardcoded a handful of hex values — a dark amber banner, a near-black
red for validation errors, plain "gray" for hints. All three were picked
against a light background and go unreadable when Windows is in dark mode,
which is where most people run a game overlay tool.

Qt doesn't offer semantic colours (there's no "error" role), so the choice is
made here off the window colour's lightness and everything asks for it by name.
"""

from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QWidget

# (light theme, dark theme) for each role.
_ERROR = ("#b00020", "#ff6b6b")
_WARNING = ("#8a6d1a", "#e0b74a")
_MUTED = ("#606060", "#a0a0a0")
_BANNER_BG = ("#8a6d1a", "#4a3a10")
_BANNER_FG = ("#ffffff", "#f0dca0")


def is_dark(widget: QWidget | None = None) -> bool:
    """True when the widget (or the app) is painting on a dark background."""
    palette = widget.palette() if widget is not None else QApplication.palette()
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def _pick(pair: tuple[str, str], widget: QWidget | None) -> str:
    return pair[1] if is_dark(widget) else pair[0]


def error_color(widget: QWidget | None = None) -> str:
    return _pick(_ERROR, widget)


def warning_color(widget: QWidget | None = None) -> str:
    return _pick(_WARNING, widget)


def muted_color(widget: QWidget | None = None) -> str:
    return _pick(_MUTED, widget)


def budget_style(widget: QWidget | None, budget) -> str:
    """Colour the rate-limit readout by how much of the window is left.

    Muted until three quarters spent, amber past that, red once the penalty
    is actually in force — which is the only state worth interrupting for.
    """
    if budget.restricted_for_s > 0:
        return f"color: {error_color(widget)};"
    if budget.fraction >= 0.75:
        return f"color: {warning_color(widget)};"
    return f"color: {muted_color(widget)};"


def banner_style(widget: QWidget | None = None) -> str:
    """Stylesheet for the update banner, legible either way round."""
    return (
        f"background: {_pick(_BANNER_BG, widget)}; border-radius: 4px; "
        f"color: {_pick(_BANNER_FG, widget)};"
    )
