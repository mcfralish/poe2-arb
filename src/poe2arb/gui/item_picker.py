"""Item pickers backed by a category menu, with type-to-search over the top.

A flat list of 636 items is unusable, so both pickers present poe.ninja's own
categories at the top level and expand each into its items on hover — which is
plain QMenu submenu behaviour, no custom popup handling required.

Everything is sorted alphabetically: categories by their display name, items by
their in-game name. Searching layers on top rather than replacing the tree:
type to see a flat list of matches, clear the box to get the categories back.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QLineEdit,
    QMenu,
    QProxyStyle,
    QPushButton,
    QStyle,
    QWidgetAction,
)

from ..format import fmt_num
from ..market import (
    ADAPTIVE_BASE,
    Item,
    Universe,
    base_abbreviation,
    category_label,
    natural_key,
)


def _item_label(name: str, value_in_base: float | None, base_name: str) -> str:
    if value_in_base is None:
        return name
    return f"{name}   ({fmt_num(value_in_base, 2)} {base_name})"


def _priced_label(universe: Universe, item, base_id: str) -> str:
    """Item label with its price, in the chosen unit or a per-item sensible one."""
    if base_id == ADAPTIVE_BASE:
        unit = universe.adaptive_unit(item.id)
    else:
        unit = base_id
    return _item_label(
        item.name, universe.convert(item.id, unit), base_abbreviation(unit)
    )


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


# How many matches the search shows. Enough to find what you meant, few enough
# that the menu doesn't turn back into the flat list this all exists to avoid.
SEARCH_RESULT_SLOTS = 25


def rank_matches(
    universe: Universe | None, query: str, limit: int = SEARCH_RESULT_SLOTS
) -> list[Item]:
    """Items matching `query`, best first.

    Ranked by *where* the match lands, not just whether it does: a name
    starting with what you typed beats one where it starts a later word, which
    beats a match buried mid-word. So "ess" leads with Essence of… rather than
    with a Lesser anything.
    """
    text = query.strip().lower()
    if not text or universe is None:
        return []
    scored: list[tuple[int, tuple, Item]] = []
    for item in universe.items.values():
        name = item.name.lower()
        at = name.find(text)
        if at < 0:
            continue
        rank = 0 if at == 0 else (1 if name[at - 1] == " " else 2)
        scored.append((rank, natural_key(item.name), item))
    scored.sort(key=lambda s: (s[0], s[1]))
    return [item for _, _, item in scored[:limit]]


class _SearchSection:
    """A flat, type-to-filter view sitting above a category menu.

    The result actions are created once and re-labelled as the query changes.
    Adding and removing actions from a menu that's already on screen is what
    makes Qt menus flicker and resize under the cursor; setting text on
    existing ones doesn't.
    """

    def __init__(self, owner: QPushButton, menu: QMenu, *, checkable: bool, on_pick):
        self._on_pick = on_pick
        self.field = QLineEdit()
        self.field.setPlaceholderText("Search…")
        self.field.setClearButtonEnabled(True)
        self.field.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._holder = QWidgetAction(menu)
        self._holder.setDefaultWidget(self.field)
        menu.addAction(self._holder)

        self._results: list[QAction] = []
        for _ in range(SEARCH_RESULT_SLOTS):
            action = menu.addAction("")
            action.setCheckable(checkable)
            action.setVisible(False)
            # `triggered` rather than `toggled`: these actions get their checked
            # state rewritten as the query changes, and `toggled` would report
            # every one of those as a click by the user.
            action.triggered.connect(
                lambda checked=False, a=action: self._on_pick(a.data(), checked)
            )
            self._results.append(action)

        self._empty = menu.addAction("No matching items")
        self._empty.setEnabled(False)
        self._empty.setVisible(False)
        self._separator = menu.addSeparator()

    def owns(self, action: QAction) -> bool:
        return (
            action is self._holder
            or action is self._empty
            or action is self._separator
            or action in self._results
        )

    def update(
        self,
        universe: Universe | None,
        query: str,
        label_for,
        checked_ids: set[str] = frozenset(),
    ) -> list[str]:
        """Re-point the result slots at the current matches. Returns their ids."""
        matches = rank_matches(universe, query)
        for i, action in enumerate(self._results):
            if i >= len(matches):
                action.setVisible(False)
                continue
            item = matches[i]
            action.setText(label_for(item))
            action.setData(item.id)
            if action.isCheckable():
                action.setChecked(item.id in checked_ids)
            action.setVisible(True)
        self._empty.setVisible(bool(query.strip()) and not matches)
        return [item.id for item in matches]

    def visible_ids(self) -> list[str]:
        return [a.data() for a in self._results if a.isVisible()]


def _set_tree_visible(menu: QMenu, search: _SearchSection, visible: bool) -> None:
    """Hide the category tree while a search is active, and vice versa."""
    for action in menu.actions():
        if not search.owns(action):
            action.setVisible(visible)


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
        self._search: _SearchSection | None = None
        self.setMenu(self._menu)
        self._menu.aboutToShow.connect(self._reset_search)
        self.rebuild(universe)

    def rebuild(self, universe: Universe | None) -> None:
        self._universe = universe
        self._menu.clear()  # takes the old search widgets with it
        self._search = None
        for old in self._submenus:
            old.deleteLater()
        self._submenus.clear()
        if universe is None or not len(universe):
            self._menu.addAction("Loading economy data…").setEnabled(False)
            self._refresh_text()
            return

        self._search = _SearchSection(
            self, self._menu, checkable=True, on_pick=self._picked_from_search
        )
        self._search.field.textChanged.connect(self._search_changed)

        known = set(universe.items)
        selected = set(self._selected)
        for category, groups in universe.by_category_and_tier().items():
            # A bullet marks branches holding a selection — without it, finding
            # what you ticked means opening every category in turn.
            in_category = sum(
                1 for items in groups.values() for i in items if i.id in selected
            )
            cat_title = category_label(category)
            if in_category:
                cat_title += f"  • {in_category}"
            cat_menu = _new_submenu(self, self._menu, cat_title, self._submenus)
            for group, items in groups.items():
                # A lone "Standard" group means the category isn't worth
                # splitting; list its items straight under the category.
                in_group = sum(1 for i in items if i.id in selected)
                group_title = f"{group}  • {in_group}" if in_group else group
                target = (
                    cat_menu if len(groups) == 1
                    else _new_submenu(self, cat_menu, group_title, self._submenus)
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

    # ---------------------------------------------------------------- searching

    def _reset_search(self) -> None:
        """Every opening starts on the category tree, not on the last query."""
        if self._search is None:
            return
        self._search.field.clear()
        # Deferred: the menu isn't on screen yet, so there's nothing to focus.
        QTimer.singleShot(0, self._search.field.setFocus)

    def _search_changed(self, text: str) -> None:
        if self._search is None:
            return
        self._search.update(
            self._universe, text, lambda item: item.name, set(self._selected)
        )
        _set_tree_visible(self._menu, self._search, not text.strip())

    def _picked_from_search(self, item_id: str | None, checked: bool) -> None:
        if item_id is not None:
            self._set(item_id, checked)

    def _sync_tree_checks(self) -> None:
        """Mirror a search-list tick onto the same item in the category tree.

        Signals are blocked while doing it: these are the same `toggled`
        connections that record a user's click, and firing them here would
        immediately undo the change that triggered the sync.
        """
        selected = set(self._selected)
        for menu in self._submenus:
            for action in menu.actions():
                item_id = action.data()
                if item_id is None or action.menu():
                    continue
                if action.isChecked() != (item_id in selected):
                    action.blockSignals(True)
                    action.setChecked(item_id in selected)
                    action.blockSignals(False)

    def _set(self, item_id: str, checked: bool) -> None:
        if checked and item_id not in self._selected:
            self._selected.append(item_id)
        elif not checked and item_id in self._selected:
            self._selected.remove(item_id)
        self._refresh_text()
        self._refresh_markers()
        self._sync_tree_checks()
        self.changed.emit()

    def _refresh_markers(self) -> None:
        """Update the branch bullets without rebuilding the open menu."""
        if self._universe is None:
            return
        selected = set(self._selected)
        for menu in self._submenus:
            own = sum(
                1 for a in menu.actions()
                if not a.menu() and a.data() in selected
            )
            title = menu.title().split("  •")[0]
            menu.setTitle(f"{title}  • {own}" if own else title)

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
        """Kept short and fixed-width-ish so the settings form stops growing."""
        count = len(self._selected)
        if not count:
            return "Nothing excluded"
        if count == 1:
            return self._display_names()[0]
        return f"{count} items excluded"

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
        self._search: _SearchSection | None = None
        self.setMenu(self._menu)
        self._menu.aboutToShow.connect(self._reset_search)
        self.rebuild(universe, base_id)

    def rebuild(self, universe: Universe | None, base_id: str | None = None) -> None:
        self._universe = universe
        if base_id is not None:
            self._base_id = base_id
        self._menu.clear()  # takes the old search widgets with it
        self._search = None
        for old in self._submenus:
            old.deleteLater()
        self._submenus.clear()
        if universe is None or not len(universe):
            self._menu.addAction("Loading economy data…").setEnabled(False)
            self._refresh_text()
            return
        self._search = _SearchSection(
            self, self._menu, checkable=False, on_pick=self._picked_from_search
        )
        self._search.field.textChanged.connect(self._search_changed)
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
                    action = target.addAction(
                        _priced_label(universe, item, self._base_id)
                    )
                    action.setData(item.id)
                    action.triggered.connect(
                        lambda _=False, cid=item.id: self.set_current(cid)
                    )
        if self._current is not None and self._current not in universe.items:
            self._current = None
        self._refresh_text()

    # ---------------------------------------------------------------- searching

    def _reset_search(self) -> None:
        """Every opening starts on the category tree, not on the last query."""
        if self._search is None:
            return
        self._search.field.clear()
        # Deferred: the menu isn't on screen yet, so there's nothing to focus.
        QTimer.singleShot(0, self._search.field.setFocus)

    def _search_changed(self, text: str) -> None:
        if self._search is None or self._universe is None:
            return
        self._search.update(
            self._universe,
            text,
            lambda item: _priced_label(self._universe, item, self._base_id),
        )
        _set_tree_visible(self._menu, self._search, not text.strip())

    def _picked_from_search(self, item_id: str | None, _checked: bool = False) -> None:
        if item_id is not None:
            self.set_current(item_id)

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
