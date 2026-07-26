"""Item pickers backed by a category menu.

A flat list of 636 items is unusable, so both pickers present poe.ninja's own
categories at the top level and expand each into its items on hover — which is
plain QMenu submenu behaviour, no custom popup handling required.

Everything is sorted alphabetically: categories by their display name, items by
their in-game name.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu, QProxyStyle, QPushButton, QStyle

from ..format import fmt_num
from ..market import Universe, category_label


def _item_label(name: str, value_in_base: float | None, base_name: str) -> str:
    if value_in_base is None:
        return name
    return f"{name}   ({fmt_num(value_in_base, 2)} {base_name})"


class _MultiColumnMenuStyle(QProxyStyle):
    """Make over-long menus wrap into columns instead of scrolling.

    Qt's default for a menu taller than the screen is a scrolling list with
    tiny arrows at top and bottom, which is miserable for the 82-item groups
    here. Turning off SH_Menu_Scrollable makes Qt lay the menu out in extra
    columns, so everything stays visible at once.
    """

    def styleHint(self, hint, option=None, widget=None, returnData=None):  # noqa: N802
        if hint == QStyle.StyleHint.SH_Menu_Scrollable:
            return 0
        return super().styleHint(hint, option, widget, returnData)


_COLUMN_STYLE: _MultiColumnMenuStyle | None = None


def _column_style() -> _MultiColumnMenuStyle:
    """One shared style instance, kept alive for the process."""
    global _COLUMN_STYLE
    if _COLUMN_STYLE is None:
        _COLUMN_STYLE = _MultiColumnMenuStyle()
    return _COLUMN_STYLE


def _new_menu(owner, title: str = "") -> QMenu:
    menu = QMenu(title, owner) if title else QMenu(owner)
    menu.setStyle(_column_style())
    return menu


def _new_submenu(owner, parent_menu, title, keep):
    """Create a submenu owned by a long-lived widget, not the menu being cleared.

    `QMenu.addMenu(str)` hands back a menu PySide is willing to garbage-collect,
    which deletes the underlying C++ object and leaves an empty category. Owning
    it explicitly and holding a Python reference keeps it alive.
    """
    submenu = _new_menu(owner, title)
    parent_menu.addMenu(submenu)
    keep.append(submenu)
    return submenu


class ExclusionPicker(QPushButton):
    """Multi-select: tick items to exclude, grouped by category."""

    changed = Signal()

    def __init__(self, selected_ids: list[str], universe: Universe | None = None,
                 parent=None):
        super().__init__(parent)
        self._selected = list(dict.fromkeys(selected_ids))
        self._universe = universe
        self._menu = _new_menu(self)
        # PySide will garbage-collect submenus that nothing on the Python side
        # references, taking the C++ object with them; keeping this list is what
        # stops the category submenus vanishing after a rebuild.
        self._submenus: list[QMenu] = []
        self.setMenu(self._menu)
        self.rebuild(universe)

    def rebuild(self, universe: Universe | None) -> None:
        self._universe = universe
        self._menu.clear()
        for old in self._submenus:
            old.deleteLater()
        self._submenus.clear()
        if universe is None or not len(universe):
            self._menu.addAction("Loading economy data…").setEnabled(False)
            self._refresh_text()
            return

        known = set(universe.items)
        for category, groups in universe.by_category_and_tier().items():
            cat_menu = _new_submenu(
                self, self._menu, category_label(category), self._submenus
            )
            for group, items in groups.items():
                # A lone "Standard" group means the category isn't worth
                # splitting; list its items straight under the category.
                target = (
                    cat_menu if len(groups) == 1
                    else _new_submenu(self, cat_menu, group, self._submenus)
                )
                for item in items:
                    action = target.addAction(item.name)
                    action.setCheckable(True)
                    action.setChecked(item.id in self._selected)
                    action.setData(item.id)
                    action.toggled.connect(
                        lambda checked, cid=item.id: self._set(cid, checked)
                    )
        # Selections for items missing from the current league still count, so
        # keep them reachable rather than dropping them on the floor.
        orphans = [cid for cid in self._selected if cid not in known]
        if orphans:
            submenu = _new_submenu(
                self, self._menu, "Not in this league", self._submenus
            )
            for cid in orphans:
                action = submenu.addAction(cid)
                action.setCheckable(True)
                action.setChecked(True)
                action.setData(cid)
                action.toggled.connect(
                    lambda checked, c=cid: self._set(c, checked)
                )

        self._menu.addSeparator()
        clear = self._menu.addAction("Clear all")
        clear.triggered.connect(self.clear)
        self._refresh_text()

    def _set(self, item_id: str, checked: bool) -> None:
        if checked and item_id not in self._selected:
            self._selected.append(item_id)
        elif not checked and item_id in self._selected:
            self._selected.remove(item_id)
        self._refresh_text()
        self.changed.emit()

    def clear(self) -> None:
        self._selected.clear()
        self.rebuild(self._universe)
        self.changed.emit()

    def selected_ids(self) -> list[str]:
        return list(self._selected)

    def _display_names(self) -> list[str]:
        if self._universe is None:
            return list(self._selected)
        return [self._universe.name(cid) for cid in self._selected]

    def summary_text(self) -> str:
        names = self._display_names()
        if not names:
            return "Nothing excluded"
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return " and ".join(names)
        return f"{names[0]}, {names[1]} and {len(names) - 2} more"

    def _refresh_text(self) -> None:
        self.setText(self.summary_text())


class ItemPicker(QPushButton):
    """Single-select: choose one item, grouped by category."""

    selected = Signal(str)

    def __init__(self, placeholder: str = "Choose…", universe: Universe | None = None,
                 base_id: str = "divine", parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self._universe = universe
        self._base_id = base_id
        self._current: str | None = None
        self._menu = _new_menu(self)
        self._submenus: list[QMenu] = []  # see ExclusionPicker for why
        self.setMenu(self._menu)
        self.rebuild(universe, base_id)

    def rebuild(self, universe: Universe | None, base_id: str | None = None) -> None:
        self._universe = universe
        if base_id is not None:
            self._base_id = base_id
        self._menu.clear()
        for old in self._submenus:
            old.deleteLater()
        self._submenus.clear()
        if universe is None or not len(universe):
            self._menu.addAction("Loading economy data…").setEnabled(False)
            self._refresh_text()
            return
        base_name = universe.name(self._base_id)
        for category, groups in universe.by_category_and_tier().items():
            cat_menu = _new_submenu(
                self, self._menu, category_label(category), self._submenus
            )
            for group, items in groups.items():
                target = (
                    cat_menu if len(groups) == 1
                    else _new_submenu(self, cat_menu, group, self._submenus)
                )
                for item in items:
                    value = universe.convert(item.id, self._base_id)
                    action = target.addAction(_item_label(item.name, value, base_name))
                    action.setData(item.id)
                    action.triggered.connect(
                        lambda _=False, cid=item.id: self.set_current(cid)
                    )
        if self._current is not None and self._current not in universe.items:
            self._current = None
        self._refresh_text()

    def set_current(self, item_id: str | None) -> None:
        self._current = item_id
        self._refresh_text()
        if item_id is not None:
            self.selected.emit(item_id)

    def current_id(self) -> str | None:
        return self._current

    def _refresh_text(self) -> None:
        if self._current is None:
            self.setText(self._placeholder)
        elif self._universe is not None:
            self.setText(self._universe.name(self._current))
        else:
            self.setText(self._current)
