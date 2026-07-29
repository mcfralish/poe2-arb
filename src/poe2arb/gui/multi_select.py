"""A dropdown that takes more than one answer.

Qt has no multi-select combo box. This is a button that opens a menu of
checkable actions and summarises the choice on its face — "All groups",
"Essences", or "3 groups" once the list is too long to name.

Selecting nothing means no filter at all, which is the same thing as selecting
everything and is a great deal easier to arrive at by accident-free clicking.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu, QPushButton, QSizePolicy


class MultiSelect(QPushButton):
    selection_changed = Signal()

    def __init__(self, empty_label: str, parent=None):
        super().__init__(parent)
        self._empty_label = empty_label
        self._options: list[str] = []
        self._selected: set[str] = set()

        self._menu = QMenu(self)
        # Without this the menu closes on the first tick, which defeats the
        # entire point of a multi-select.
        self._menu.triggered.connect(self._toggled)
        self.setMenu(self._menu)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._refresh_text()

    # -- options

    def set_options(self, options: list[str]) -> None:
        """Replace the list. Anything selected that is gone is dropped."""
        self._options = list(options)
        self._selected &= set(self._options)
        self._rebuild_menu()
        self._refresh_text()

    def _rebuild_menu(self) -> None:
        self._menu.clear()
        clear = self._menu.addAction(self._empty_label)
        clear.setData("")
        if self._options:
            self._menu.addSeparator()
        for option in self._options:
            action = self._menu.addAction(option)
            action.setCheckable(True)
            action.setChecked(option in self._selected)
            action.setData(option)

    # -- state

    def selected(self) -> list[str]:
        """Chosen options in menu order; empty means "no filter"."""
        return [o for o in self._options if o in self._selected]

    def set_selected(self, options: list[str]) -> None:
        self._selected = set(options) & set(self._options)
        self._rebuild_menu()
        self._refresh_text()
        if not self.signalsBlocked():
            self.selection_changed.emit()

    def clear_selection(self) -> None:
        self.set_selected([])

    def _toggled(self, action) -> None:
        name = action.data()
        if not name:                       # the "all" entry
            self._selected.clear()
        elif action.isChecked():
            self._selected.add(name)
        else:
            self._selected.discard(name)
        self._rebuild_menu()
        self._refresh_text()
        if not self.signalsBlocked():
            self.selection_changed.emit()

    def _refresh_text(self) -> None:
        chosen = self.selected()
        if not chosen:
            self.setText(self._empty_label)
        elif len(chosen) == 1:
            self.setText(chosen[0])
        else:
            self.setText(f"{len(chosen)} selected")
