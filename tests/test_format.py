"""Number formatting: consistent decimals, no scientific notation."""

from __future__ import annotations

import math

from poe2arb.format import (
    currency_label,
    fmt_amount,
    fmt_depth,
    fmt_num,
    fmt_pct,
    fmt_qty,
    fmt_rate,
    fmt_value,
    fmt_volume,
)


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


# --- amounts in the seller's own currency ----------------------------------

class TestAmounts:
    def test_whole_numbers_stay_whole(self):
        """The figure in a whisper is a whole number of orbs; ".0" reads wrong."""
        assert fmt_qty(2412) == "2,412"
        assert fmt_qty(155.0) == "155"
        assert fmt_qty(9) == "9"

    def test_fractions_keep_enough_to_be_useful(self):
        assert fmt_qty(0.0046) == "0.0046"
        assert fmt_qty(12.5) == "12.5"

    def test_an_amount_names_its_currency(self):
        assert fmt_amount(2412, "exalted") == "2,412 ex"
        assert fmt_amount(5.5, "divine") == "5.5 div"

    def test_an_unknown_currency_keeps_its_id(self):
        """Better a raw id than a number with no unit at all."""
        assert fmt_amount(3, "regal") == "3 regal"
        assert currency_label("regal") == "regal"
