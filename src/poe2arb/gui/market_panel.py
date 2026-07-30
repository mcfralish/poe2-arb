"""The Market tab: the economy laid out the way the game lays it out.

Tabs mirror the in-game Currency Exchange, plus an "All" tab for the full list.
A second dropdown narrows to a group inside the current tab, and a search box
filters by name on top of both.

Exclusions live here rather than in Settings. Excluding something is a judgement
about a specific item, and it was previously done from a menu that hid the very
prices you'd want to look at while deciding. Now excluded items stay visible
with a ticked checkbox, and the tick is how you add and remove them.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ..market import ALL_TAB, ADAPTIVE_BASE, Universe, base_abbreviation, ingame_tab
from ..format import fmt_volume
from .flow_tabs import TabStrip
from .multi_select import MultiSelect
from .table_items import CentredCheckDelegate, NumericItem, TextItem
from .theme import muted_color

ANY_GROUP = "All groups"

COLUMNS = [
    ("Currency", "The item, as poe.ninja names it."),
    (
        "Value",
        "What one of these is worth. Taken from the in-game Currency Exchange "
        "where it trades there, and from poe.ninja's consensus otherwise — the "
        "count at the bottom says how many of each. Change the unit in the "
        "toolbar.",
    ),
    (
        "Daily volume (div)",
        "How much of this changes hands in a day, measured in Divine Orbs of "
        "value. Higher means a busier market, so your trades are likelier to fill.",
    ),
    (
        "Excluded",
        "Tick to keep this out of the sweep. Excluded items still show here "
        "and still work in Quick Lookup — they're only kept out of the search "
        "for trades.",
    ),
]

EXCLUDED_COLUMN = 3
# Everything but the name reads as a figure, and figures compare far better
# down a centred column than ragged against the left edge.
NAME_COLUMN = 0


class ExclusionListDialog(QDialog):
    """Everything currently excluded, in one place, with a way to undo it."""

    def __init__(self, excluded: list[str], names: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Excluded from the search")
        self.resize(360, 380)
        self._result = list(excluded)

        layout = QVBoxLayout(self)
        if excluded:
            layout.addWidget(QLabel(
                f"<b>{len(excluded)} item(s)</b> are kept out of the arbitrage "
                f"search. Untick anything to put it back."
            ))
        else:
            layout.addWidget(QLabel(
                "Nothing is excluded. Tick the <b>Excluded</b> column in the "
                "Market tab to keep an item out of the search."
            ))

        self.list = QListWidget()
        for item_id in sorted(excluded, key=lambda i: names.get(i, i).lower()):
            entry = QListWidgetItem(names.get(item_id, item_id))
            entry.setData(Qt.ItemDataRole.UserRole, item_id)
            entry.setFlags(entry.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            entry.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(entry)
        layout.addWidget(self.list)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        clear = buttons.addButton("Clear all", QDialogButtonBox.ButtonRole.ResetRole)
        clear.setEnabled(bool(excluded))
        clear.clicked.connect(self._clear_all)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _clear_all(self) -> None:
        for row in range(self.list.count()):
            self.list.item(row).setCheckState(Qt.CheckState.Unchecked)

    def selected_ids(self) -> list[str]:
        """Whatever is still ticked when OK is pressed."""
        return [
            self.list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.list.count())
            if self.list.item(row).checkState() == Qt.CheckState.Checked
        ]


class MarketPanel(QWidget):
    exclusions_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._universe: Universe | None = None
        self._icons = None
        self._excluded: list[str] = []
        self._names: dict[str, str] = {}
        self._values: dict[str, float] = {}
        self._volumes: dict[str, float] = {}
        self._base_id = ADAPTIVE_BASE
        # Set while filling the table so programmatic check-state changes aren't
        # mistaken for the user ticking a box.
        self._populating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # A wrapping strip rather than a QTabBar: fifteen categories never fit
        # on one row at a sane window width, and QTabBar's answer to that is to
        # hide the overflow behind scroll arrows.
        self.tabs = TabStrip()
        self.tabs.addTab(ALL_TAB)
        self.tabs.currentChanged.connect(self._tab_changed)
        layout.addWidget(self.tabs)

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filters)
        controls.addWidget(self.search, stretch=2)

        self.group_box = MultiSelect(ANY_GROUP)
        self.group_box.setToolTip("Narrow to one or more groups inside this tab.")
        self.group_box.selection_changed.connect(self._apply_filters)
        controls.addWidget(self.group_box, stretch=1)

        self.exclusions_button = QPushButton()
        self.exclusions_button.setToolTip(
            "See everything currently kept out of the arbitrage search."
        )
        self.exclusions_button.clicked.connect(self.open_exclusion_list)
        controls.addWidget(self.exclusions_button)
        layout.addLayout(controls)

        self.table = self._make_table()
        self.table.itemChanged.connect(self._item_changed)
        layout.addWidget(self.table)

        self.status = QLabel()
        self.status.setStyleSheet(f"color: {muted_color(self)};")
        layout.addWidget(self.status)

        self._refresh_button_text()

    @staticmethod
    def _make_table() -> QTableWidget:
        table = QTableWidget(0, len(COLUMNS))
        table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        header = table.horizontalHeader()
        # Nothing stretches. Stretching the name column left a hand's width of
        # dead space beside every item once the window was wide enough to show
        # all the tabs; sizing to content means the column is exactly as wide as
        # the longest name ("Zarokh's Reliquary Key: Against the Darkness") and
        # the window can be much narrower.
        header.setStretchLastSection(False)
        for i in range(len(COLUMNS)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        for i, (_, tip) in enumerate(COLUMNS):
            table.horizontalHeaderItem(i).setToolTip(tip)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSortingEnabled(True)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        # The tick sits under a centred header, so it has to be centred too;
        # item alignment alone leaves it on the leading edge.
        table.setItemDelegateForColumn(EXCLUDED_COLUMN, CentredCheckDelegate(table))
        return table

    # ------------------------------------------------------------------ inputs

    def set_icons(self, provider) -> None:
        self._icons = provider

    def set_universe(self, universe: Universe) -> None:
        self._universe = universe
        self._rebuild_tabs()

    def set_exclusions(self, excluded: list[str]) -> None:
        self._excluded = list(dict.fromkeys(excluded))
        self._refresh_button_text()
        # Also push them onto the table. Settings can change the list long after
        # the table was built, and without this the ticks kept showing the old
        # set while the count in the button showed the new one.
        self._sync_checkboxes()

    def set_base_currency(self, base_id: str) -> None:
        self._base_id = base_id
        self._update_value_header()

    def render(
        self,
        *,
        names: dict[str, str],
        values: dict[str, float],
        volumes: dict[str, float],
    ) -> None:
        self._names = names
        self._values = values
        self._volumes = volumes
        self._fill_table()

    # ------------------------------------------------------------------ tabs

    def _rebuild_tabs(self) -> None:
        current = self.tabs.tabText(self.tabs.currentIndex())
        blocked = self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        self.tabs.addTab(ALL_TAB)
        if self._universe is not None:
            for tab in self._universe.by_tab():
                self.tabs.addTab(tab)
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == current:
                self.tabs.setCurrentIndex(i)
                break
        self.tabs.blockSignals(blocked)
        self._rebuild_groups()

    def _current_tab(self) -> str:
        index = self.tabs.currentIndex()
        return self.tabs.tabText(index) if index >= 0 else ALL_TAB

    def _tab_changed(self) -> None:
        self._rebuild_groups()
        self._apply_filters()

    def _rebuild_groups(self) -> None:
        """Repopulate the group picker for whichever tab is showing."""
        tab = self._current_tab()
        groups: list[str] = []
        if self._universe is not None and tab != ALL_TAB:
            groups = list(self._universe.groups_in_tab(tab))
        blocked = self.group_box.blockSignals(True)
        self.group_box.set_options(groups)
        # A tab with one group offers no choice worth making.
        self.group_box.setEnabled(len(groups) > 1)
        self.group_box.blockSignals(blocked)

    def _group_members(self) -> set[str] | None:
        """Item ids in the chosen groups, or None when none are selected."""
        chosen = self.group_box.selected()
        tab = self._current_tab()
        if not chosen or tab == ALL_TAB or self._universe is None:
            return None
        in_tab = self._universe.groups_in_tab(tab)
        members: set[str] = set()
        for group in chosen:
            members.update(i.id for i in in_tab.get(group, []))
        return members

    # ------------------------------------------------------------------ table

    def _update_value_header(self) -> None:
        item = self.table.horizontalHeaderItem(1)
        if self._base_id == ADAPTIVE_BASE:
            item.setText("Value")
            return
        item.setText(f"Value ({base_abbreviation(self._base_id)})")

    def _fill_table(self) -> None:
        rows = sorted(self._values, key=lambda cid: -self._values[cid])
        excluded = set(self._excluded)
        adaptive = self._base_id == ADAPTIVE_BASE
        base_rate = 1.0 if adaptive else (self._values.get(self._base_id) or 1.0)

        self._populating = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, cid in enumerate(rows):
            divine_value = self._values[cid]
            if adaptive and self._universe is not None and self._universe.get(cid):
                unit = self._universe.adaptive_unit(cid)
                shown = self._universe.convert(cid, unit) or 0.0
                text = f"{shown:,.2f} {base_abbreviation(unit)}"
            else:
                text = f"{divine_value / base_rate:,.2f}"

            name_cell = TextItem(self._names.get(cid, cid))
            name_cell.setData(Qt.ItemDataRole.UserRole, cid)
            if self._icons is not None:
                name_cell.setIcon(self._icons.icon(cid))

            exclude = TextItem("")
            exclude.setFlags(exclude.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            exclude.setCheckState(
                Qt.CheckState.Checked if cid in excluded else Qt.CheckState.Unchecked
            )
            exclude.setData(Qt.ItemDataRole.UserRole, cid)
            exclude.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            volume = self._volumes.get(cid, 0.0)
            for col, cell in enumerate([
                name_cell,
                NumericItem(text, divine_value),
                NumericItem(fmt_volume(volume), volume),
                exclude,
            ]):
                if col != NAME_COLUMN:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, col, cell)
        self.table.setSortingEnabled(True)
        self._populating = False
        self._update_value_header()
        self._apply_filters()

    def _apply_filters(self) -> None:
        """Tab, group and search compose — a row must satisfy all three."""
        query = self.search.text().strip().lower()
        tab = self._current_tab()
        members = self._group_members()
        shown = 0
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, 0)
            if cell is None:
                continue
            item_id = cell.data(Qt.ItemDataRole.UserRole)
            visible = True
            if tab != ALL_TAB and self._universe is not None:
                item = self._universe.get(item_id)
                visible = item is not None and ingame_tab(item) == tab
            if visible and members is not None:
                visible = item_id in members
            if visible and query:
                visible = query in cell.text().lower()
            self.table.setRowHidden(row, not visible)
            shown += visible
        self._update_status(shown)

    def _update_status(self, shown: int) -> None:
        total = self.table.rowCount()
        counted = f"{total} item(s)" if shown == total else f"{shown} of {total} item(s)"
        ce = len(self._universe.ce_priced) if self._universe is not None else 0
        if ce:
            counted += (
                f"  ·  {ce} priced from the Currency Exchange, "
                f"{total - ce} from poe.ninja"
            )
        self.status.setText(counted)

    # ------------------------------------------------------------------ exclusions

    def _item_changed(self, item) -> None:
        if self._populating or item.column() != EXCLUDED_COLUMN:
            return
        item_id = item.data(Qt.ItemDataRole.UserRole)
        if item_id is None:
            return
        checked = item.checkState() == Qt.CheckState.Checked
        if checked and item_id not in self._excluded:
            self._excluded.append(item_id)
        elif not checked and item_id in self._excluded:
            self._excluded.remove(item_id)
        else:
            return
        self._refresh_button_text()
        self.exclusions_changed.emit(list(self._excluded))

    def _refresh_button_text(self) -> None:
        count = len(self._excluded)
        self.exclusions_button.setText(
            f"Excluded ({count})" if count else "Excluded"
        )

    def open_exclusion_list(self) -> None:
        dialog = ExclusionListDialog(self._excluded, self._names, self)
        if not dialog.exec():
            return
        kept = dialog.selected_ids()
        if kept == self._excluded:
            return
        self._excluded = kept
        self._refresh_button_text()
        self._sync_checkboxes()
        self.exclusions_changed.emit(list(self._excluded))

    def _sync_checkboxes(self) -> None:
        """Mirror the list back onto the table without re-firing itemChanged."""
        excluded = set(self._excluded)
        self._populating = True
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, EXCLUDED_COLUMN)
            if cell is None:
                continue
            item_id = cell.data(Qt.ItemDataRole.UserRole)
            cell.setCheckState(
                Qt.CheckState.Checked if item_id in excluded else Qt.CheckState.Unchecked
            )
        self._populating = False
