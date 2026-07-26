"""Number formatting: consistent decimals, no scientific notation."""

from __future__ import annotations

import math

from poe2arb.format import fmt_depth, fmt_num, fmt_pct, fmt_rate, fmt_value, fmt_volume


class TestFmtNum:
    def test_standard_decimals(self):
        assert fmt_num(8.77) == "8.7700"
        assert fmt_num(1.0) == "1.0000"
        assert fmt_num(0.1127) == "0.1127"

    def test_thousands_separator(self):
        assert fmt_num(4886.0) == "4,886.0000"
        assert fmt_num(1234567.5) == "1,234,567.5000"

    def test_never_scientific_notation(self):
        """`%g` used to emit 1.88679e-06, which made columns unreadable."""
        for v in (1.88679e-06, 0.000001, 1e-9, 123456789.0):
            assert "e" not in fmt_num(v).lower()

    def test_tiny_values_keep_significance(self):
        # Would round to "0.0000" at the standard 4 decimals.
        assert fmt_num(1.88679e-06).strip("0.") != ""
        assert float(fmt_num(0.0000123).replace(",", "")) > 0

    def test_zero_and_negative(self):
        assert fmt_num(0.0) == "0.0000"
        assert fmt_num(-2.5) == "-2.5000"

    def test_non_finite(self):
        assert fmt_num(math.inf) == "∞"
        assert fmt_num(math.nan) == "—"


class TestSpecificFormatters:
    def test_value_and_rate_share_a_format(self):
        assert fmt_value(8.77) == fmt_rate(8.77)

    def test_volume_is_whole_numbers(self):
        assert fmt_volume(43875.4) == "43,875"
        assert fmt_volume(math.inf) == "∞"

    def test_depth_one_decimal(self):
        assert fmt_depth(29.04) == "29.0"

    def test_pct_signed(self):
        assert fmt_pct(4.712) == "+4.71%"
        assert fmt_pct(-1.5) == "-1.50%"
        assert fmt_pct(4.712, signed=False) == "4.71%"


class TestSortabilityRegression:
    def test_string_sort_of_formatted_values_is_wrong(self):
        """Why NumericItem exists: text order != numeric order."""
        formatted = [fmt_value(8.77), fmt_value(4886.0)]
        assert sorted(formatted) == ["4,886.0000", "8.7700"]  # string order
        assert sorted([8.77, 4886.0]) == [8.77, 4886.0]       # true order differs
