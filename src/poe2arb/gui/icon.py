"""App icon: the bundled divine orb .ico, with a drawn fallback.

The .ico ships alongside this module and is collected into the PyInstaller
bundle, where `__file__` resolves inside the extraction dir — so the same
path logic works frozen and from source. If the file is ever missing the
drawn fallback keeps the app iconed rather than blank.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap

log = logging.getLogger(__name__)

ICON_FILENAME = "divine_orb_icon.ico"
_ICON: QIcon | None = None


def icon_path() -> Path:
    return Path(__file__).resolve().parent / ICON_FILENAME


def make_app_icon() -> QIcon:
    """The application icon — loaded once and cached."""
    global _ICON
    if _ICON is not None:
        return _ICON
    path = icon_path()
    if path.exists():
        icon = QIcon(str(path))
        if not icon.isNull():
            _ICON = icon
            return _ICON
        log.warning("icon file %s could not be loaded; using drawn fallback", path)
    else:
        log.warning("icon file %s not found; using drawn fallback", path)
    _ICON = _drawn_fallback_icon()
    return _ICON


def _drawn_fallback_icon() -> QIcon:
    """Gold coin with a cycle arrow, drawn programmatically."""
    icon = QIcon()
    for size in (16, 32, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = size * 0.06
        rect = QRectF(m, m, size - 2 * m, size - 2 * m)
        p.setBrush(QBrush(QColor("#c9a227")))
        p.setPen(QPen(QColor("#7a5c12"), max(1.0, size * 0.04)))
        p.drawEllipse(rect)
        pen = QPen(QColor("#2b2103"), max(1.5, size * 0.09))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        arc = rect.adjusted(size * 0.18, size * 0.18, -size * 0.18, -size * 0.18)
        p.drawArc(arc, 30 * 16, 280 * 16)
        ah = size * 0.14
        tip = QPointF(
            arc.center().x() + arc.width() / 2 * 0.93,
            arc.center().y() - arc.height() * 0.28,
        )
        p.setBrush(QBrush(QColor("#2b2103")))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(
            [
                tip,
                QPointF(tip.x() - ah, tip.y() - ah * 0.35),
                QPointF(tip.x() - ah * 0.2, tip.y() - ah),
            ]
        )
        p.end()
        icon.addPixmap(pm)
    return icon
