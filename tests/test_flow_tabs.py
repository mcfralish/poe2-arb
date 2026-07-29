"""The wrapping tab strip, and the multi-select dropdown beside it."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from poe2arb.gui.flow_tabs import TabStrip  # noqa: E402
from poe2arb.gui.multi_select import MultiSelect  # noqa: E402

# The real in-game categories, which is what makes one row impossible.
TABS = [
    "All", "Currency", "Fragments", "Runes", "Delirium", "Essences",
    "Expedition", "Ritual", "Breach", "Ultimatum", "Talismans", "Waystones",
    "Omens", "Catalysts", "Lineage Support Gems",
]


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def strip(qapp):
    s = TabStrip()
    for name in TABS:
        s.addTab(name)
    return s


def rows_used(strip, width):
    strip.resize(width, strip.layout().heightForWidth(width))
    strip.show()
    QApplication.processEvents()
    return sorted({b.y() for b in strip.findChildren(QPushButton)})


class TestWrapping:
    def test_fifteen_tabs_wrap_at_the_default_window_width(self, strip):
        """The whole point: QTabBar hid the last few behind scroll arrows."""
        assert len(rows_used(strip, 900)) > 1

    def test_every_tab_stays_inside_the_width(self, strip):
        rows_used(strip, 900)
        for button in strip.findChildren(QPushButton):
            assert button.x() + button.width() <= 900

    def test_a_wide_window_uses_one_row(self, strip):
        assert len(rows_used(strip, 1600)) == 1

    def test_narrowing_adds_rows_rather_than_hiding_tabs(self, strip):
        wide = len(rows_used(strip, 1600))
        narrow = len(rows_used(strip, 500))
        assert narrow > wide
        for button in strip.findChildren(QPushButton):
            assert button.isVisible()


class TestTabBarBehaviour:
    def test_the_first_tab_starts_selected(self, strip):
        assert strip.currentIndex() == 0
        assert strip.tabText(0) == "All"

    def test_selecting_emits_once(self, strip):
        seen = []
        strip.currentChanged.connect(seen.append)
        strip.setCurrentIndex(3)
        assert seen == [3]
        assert strip.currentIndex() == 3

    def test_reselecting_the_current_tab_is_silent(self, strip):
        seen = []
        strip.currentChanged.connect(seen.append)
        strip.setCurrentIndex(0)
        assert seen == []

    def test_only_one_tab_is_ever_checked(self, strip):
        strip.setCurrentIndex(5)
        checked = [b for b in strip.findChildren(QPushButton) if b.isChecked()]
        assert len(checked) == 1

    def test_removing_a_tab_keeps_indices_and_text_aligned(self, strip):
        """Button ids must track positions, or currentIndex starts lying."""
        strip.removeTab(0)
        assert strip.count() == len(TABS) - 1
        assert strip.tabText(0) == "Currency"
        strip.setCurrentIndex(2)
        assert strip.tabText(strip.currentIndex()) == strip.tabText(2)

    def test_clear_empties_the_strip(self, strip):
        strip.clear()
        assert strip.count() == 0
        assert strip.currentIndex() == -1


class TestMultiSelect:
    @pytest.fixture
    def picker(self, qapp):
        m = MultiSelect("All groups")
        m.set_options(["Essences", "Omens", "Catalysts"])
        return m

    def test_nothing_selected_reads_as_all(self, picker):
        assert picker.selected() == []
        assert picker.text() == "All groups"

    def test_one_choice_is_named(self, picker):
        picker.set_selected(["Omens"])
        assert picker.text() == "Omens"

    def test_several_choices_are_counted(self, picker):
        picker.set_selected(["Omens", "Essences"])
        assert picker.text() == "2 selected"

    def test_selection_is_returned_in_menu_order(self, picker):
        picker.set_selected(["Catalysts", "Essences"])
        assert picker.selected() == ["Essences", "Catalysts"]

    def test_ticking_a_menu_entry_selects_it(self, picker):
        seen = []
        picker.selection_changed.connect(lambda: seen.append(picker.selected()))
        action = [a for a in picker.menu().actions() if a.data() == "Omens"][0]
        action.trigger()          # a checkable action toggles itself on trigger
        assert seen == [["Omens"]]

    def test_the_all_entry_clears_everything(self, picker):
        picker.set_selected(["Omens", "Essences"])
        clear = picker.menu().actions()[0]
        clear.trigger()
        assert picker.selected() == []

    def test_changing_options_drops_choices_that_are_gone(self, picker):
        """Switching market tab replaces the group list underneath the picker."""
        picker.set_selected(["Omens", "Essences"])
        picker.set_options(["Omens", "Runes"])
        assert picker.selected() == ["Omens"]

    def test_blocked_signals_stay_blocked(self, picker):
        seen = []
        picker.selection_changed.connect(seen.append)
        picker.blockSignals(True)
        picker.set_selected(["Omens"])
        picker.blockSignals(False)
        assert seen == []
