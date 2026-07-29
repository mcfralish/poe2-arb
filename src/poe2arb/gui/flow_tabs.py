"""A tab strip that wraps onto as many rows as it needs.

QTabBar cannot wrap. Given more tabs than fit, it hides the overflow behind
scroll arrows — so with fifteen market categories the last few were unreachable
unless the window was dragged past 1100px wide. Shrinking the font bought some
room but not enough, and made the labels hard to read.

This is the same thing built from checkable buttons in a flow layout: every tab
is visible at any window width, the strip just grows taller as the window gets
narrower. Only the small slice of QTabBar's API that MarketPanel uses is
reproduced here.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QLayout,
    QPushButton,
    QSizePolicy,
    QStyle,
    QWidget,
)


class FlowLayout(QLayout):
    """Left-to-right, top-to-bottom, wrapping when the row runs out of width.

    Qt ships this as an example rather than a class, so it lives here.
    """

    def __init__(self, parent=None, spacing: int = 3):
        super().__init__(parent)
        self._items: list = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def __del__(self):
        while self.count():
            self.takeAt(0)

    def addItem(self, item) -> None:      # noqa: N802 - Qt override
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):         # noqa: N802 - Qt override
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):         # noqa: N802 - Qt override
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):        # noqa: N802 - Qt override
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width: int) -> int:   # noqa: N802 - Qt override
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:    # noqa: N802 - Qt override
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self) -> QSize:          # noqa: N802 - Qt override
        return self.minimumSize()

    def minimumSize(self) -> QSize:       # noqa: N802 - Qt override
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )

    def _layout(self, rect: QRect, *, apply: bool) -> int:
        """Place the items, returning the total height used."""
        margins = self.contentsMargins()
        area = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x, y, row_height = area.x(), area.y(), 0
        space = self.spacing()

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + space
            if next_x - space > area.right() and row_height > 0:
                x = area.x()
                y = y + row_height + space
                next_x = x + hint.width() + space
                row_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            row_height = max(row_height, hint.height())

        return y + row_height - rect.y() + margins.bottom()


class TabStrip(QWidget):
    """Checkable buttons that behave like a tab bar, but wrap.

    Mirrors the part of QTabBar that MarketPanel touches: addTab, removeTab,
    count, tabText, currentIndex, setCurrentIndex and currentChanged.
    """

    currentChanged = Signal(int)          # noqa: N815 - matches QTabBar

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: list[QPushButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self._clicked)

        self._flow = FlowLayout(self)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    # -- construction

    def addTab(self, text: str) -> int:   # noqa: N802 - matches QTabBar
        button = QPushButton(text, self)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setStyleSheet(_TAB_STYLE)
        # Buttons default to a minimum width wide enough for "Cancel"; without
        # this, "Maps" and "Fragments" would take the same amount of room.
        button.setMinimumWidth(0)
        width = button.fontMetrics().horizontalAdvance(text) + _PADDING
        button.setFixedWidth(width)
        button.setFixedHeight(
            button.fontMetrics().height()
            + 2 * self.style().pixelMetric(QStyle.PixelMetric.PM_ButtonMargin)
        )

        index = len(self._buttons)
        self._buttons.append(button)
        self._group.addButton(button, index)
        self._flow.addWidget(button)
        if index == 0:
            button.setChecked(True)
        return index

    def removeTab(self, index: int) -> None:      # noqa: N802 - matches QTabBar
        if not 0 <= index < len(self._buttons):
            return
        button = self._buttons.pop(index)
        self._group.removeButton(button)
        self._flow.removeWidget(button)
        button.setParent(None)
        button.deleteLater()
        # Ids must stay equal to positions, or currentIndex lies after a removal.
        for i, remaining in enumerate(self._buttons):
            self._group.setId(remaining, i)

    def clear(self) -> None:
        while self._buttons:
            self.removeTab(len(self._buttons) - 1)

    # -- state

    def count(self) -> int:
        return len(self._buttons)

    def tabText(self, index: int) -> str:         # noqa: N802 - matches QTabBar
        if 0 <= index < len(self._buttons):
            return self._buttons[index].text()
        return ""

    def currentIndex(self) -> int:                # noqa: N802 - matches QTabBar
        for i, button in enumerate(self._buttons):
            if button.isChecked():
                return i
        return -1

    def setCurrentIndex(self, index: int) -> None:   # noqa: N802 - matches QTabBar
        if not 0 <= index < len(self._buttons):
            return
        if self._buttons[index].isChecked():
            return
        self._buttons[index].setChecked(True)
        self.currentChanged.emit(index)

    def _clicked(self, index: int) -> None:
        self.currentChanged.emit(index)


_PADDING = 16

# Flat, tab-like, and theme-neutral: named colours would fight the user's
# palette in the other direction from whichever one we picked.
_TAB_STYLE = """
QPushButton {
    border: 1px solid palette(mid);
    border-radius: 3px;
    padding: 2px 6px;
    background: palette(button);
}
QPushButton:hover { background: palette(midlight); }
QPushButton:checked {
    background: palette(highlight);
    color: palette(highlighted-text);
    border-color: palette(highlight);
}
"""
