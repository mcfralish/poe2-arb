"""Row filtering on the Market and Book Edges tables."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem  # noqa: E402

from poe2arb.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def table(app):
    rows = [
        ("Divine Orb", "1.0000", "9999"),
        ("Chaos Orb", "0.1100", "5000"),
        ("Mirror of Kalandra", "4886.0000", "12"),
    ]
    t = QTableWidget(len(rows), 3)
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            t.setItem(r, c, QTableWidgetItem(text))
    return t


def visible(table):
    return [
        table.item(r, 0).text()
        for r in range(table.rowCount())
        if not table.isRowHidden(r)
    ]


class TestFilter:
    def test_matches_are_kept(self, table):
        MainWindow._apply_filter(table, "orb", (0,))
        assert visible(table) == ["Divine Orb", "Chaos Orb"]

    def test_case_insensitive(self, table):
        MainWindow._apply_filter(table, "MIRROR", (0,))
        assert visible(table) == ["Mirror of Kalandra"]

    def test_empty_query_shows_everything(self, table):
        MainWindow._apply_filter(table, "chaos", (0,))
        MainWindow._apply_filter(table, "", (0,))
        assert len(visible(table)) == 3

    def test_whitespace_counts_as_empty(self, table):
        MainWindow._apply_filter(table, "   ", (0,))
        assert len(visible(table)) == 3

    def test_numbers_are_not_matched(self, table):
        """Market's column 1 is a value; searching it would be nonsense."""
        MainWindow._apply_filter(table, "4886", (0,))
        assert visible(table) == []

    def test_second_column_also_matched(self, app):
        """Book Edges puts the receive currency in column 1."""
        t = QTableWidget(1, 2)
        t.setItem(0, 0, QTableWidgetItem("Divine Orb"))
        t.setItem(0, 1, QTableWidgetItem("Chaos Orb"))
        MainWindow._apply_filter(t, "chaos", (0, 1))
        assert not t.isRowHidden(0)

    def test_no_match_hides_everything(self, table):
        MainWindow._apply_filter(table, "zzzz", (0,))
        assert visible(table) == []

    def test_empty_cells_are_survivable(self, app):
        t = QTableWidget(1, 2)  # no items set at all
        MainWindow._apply_filter(t, "anything", (0, 1))
        assert t.isRowHidden(0)
