"""Columns you can drag, resize, and that grow with the window.

Qt gives you two of those three at a time and never all three — see
`table_items.ColumnLayout`. These pin the behaviour that replaces the old
`Stretch`-one-column arrangement.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

from poe2arb.gui.table_items import flexible_columns  # noqa: E402

LONG = "Zarokh's Reliquary Key: Against the Darkness"

# Tables outlive the test that made them: a collected QTableWidget can still be
# handed an event, and the filter then runs against a half-deleted object.
_KEEP = []


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def table(qapp, width=600, rows=(("Item", LONG), ("Buy", "3"), ("Cost", "1200 ex"),
                                 ("Seller", "SomeSeller")), protected=()):
    t = QTableWidget(0, len(rows))
    t.setHorizontalHeaderLabels([title for title, _ in rows])
    layout = flexible_columns(t, protected=protected)
    t.setRowCount(1)
    for col, (_, text) in enumerate(rows):
        t.setItem(0, col, QTableWidgetItem(text))
    t.resize(width, 200)
    t.show()
    qapp.processEvents()
    layout.size_to_contents()
    _KEEP.append(t)
    return t, layout


def widths(t):
    header = t.horizontalHeader()
    return [header.sectionSize(i) for i in range(header.count())]


def test_columns_are_draggable_and_resizable(qapp):
    t, _ = table(qapp)
    header = t.horizontalHeader()
    assert header.sectionsMovable()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive


def test_the_first_sizing_fits_the_window(qapp):
    """Sizing to contents alone overflows, and what falls off the right-hand
    edge is the actions column."""
    t, _ = table(qapp, width=400)
    assert sum(widths(t)) <= t.viewport().width()


def test_widening_grows_every_column(qapp):
    """It used to grow only the one column that was set to Stretch."""
    t, _ = table(qapp, width=500)
    before = widths(t)
    t.resize(900, 200)
    qapp.processEvents()
    after = widths(t)
    assert all(a > b for a, b in zip(after, before))
    ratios = [a / b for a, b in zip(after, before)]
    assert max(ratios) - min(ratios) < 0.05


def test_a_protected_column_keeps_its_width_when_narrowed(qapp):
    """A row of buttons does not get smaller when squeezed — it gets clipped,
    and an action you cannot reach is worse than one you scroll to."""
    t, _ = table(qapp, width=800, protected=(3,))
    before = widths(t)
    t.resize(400, 200)
    qapp.processEvents()
    after = widths(t)
    assert after[3] == before[3]
    assert after[0] < before[0]


def test_order_and_widths_survive_a_restart(qapp):
    t, layout = table(qapp)
    t.horizontalHeader().resizeSection(1, 123)
    t.horizontalHeader().moveSection(0, 3)
    saved = layout.state()

    fresh, other = table(qapp)
    assert other.restore(saved) is True
    assert fresh.horizontalHeader().sectionSize(1) == 123
    assert fresh.horizontalHeader().visualIndex(0) == 3


def test_unreadable_saved_state_is_ignored(qapp):
    _, layout = table(qapp)
    assert layout.restore(None) is False
    assert layout.restore("not base64 !!") is False


def test_a_restored_layout_is_not_resized_to_contents(qapp):
    """Otherwise the first rows to arrive would wipe the saved arrangement."""
    t, layout = table(qapp)
    t.horizontalHeader().resizeSection(1, 123)
    saved = layout.state()

    fresh, other = table(qapp)
    other.restore(saved)
    other._sized = True
    other.size_to_contents()
    assert fresh.horizontalHeader().sectionSize(1) == 123


# --- per-column minimum widths ----------------------------------------------
# From the fourth field test: at narrow window widths the headings truncated to
# `Profit`->"rofit" and `Expires`->"xpire", which is a header lying about which
# column you are reading.


def test_a_column_never_shrinks_below_its_own_heading(qapp):
    t, layout = table(qapp, width=800)
    t.resize(200, 200)
    qapp.processEvents()
    header = t.horizontalHeader()
    for i in range(header.count()):
        assert header.sectionSize(i) >= layout.min_width(i)


def test_a_name_column_gets_more_room_than_its_heading(qapp):
    """"Item" is four characters; its contents run to a Reliquary Key."""
    _, layout = table(qapp)
    assert layout.min_width(0) >= layout.ROOMY_MIN   # Item
    assert layout.min_width(3) >= layout.ROOMY_MIN   # Seller
    assert layout.min_width(1) < layout.ROOMY_MIN    # Buy


def test_sizing_to_contents_still_clears_the_heading(qapp):
    """resizeColumnsToContents measures the cells and ignores the title."""
    t, layout = table(qapp, rows=(("Item", "x"), ("Expires", "5m")))
    header = t.horizontalHeader()
    assert header.sectionSize(1) >= layout.min_width(1)


def test_an_unheaded_column_keeps_the_bare_floor(qapp):
    """A marker or action column has no title to fit."""
    _, layout = table(qapp, rows=(("", "●"), ("Item", LONG)))
    assert layout.min_width(0) == layout.MIN_WIDTH
