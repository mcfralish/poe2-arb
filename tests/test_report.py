"""The CLI's one table.

Two NameErrors survived a refactor here and only surfaced on a live run: the
module imports fine and the failure is inside the function body. So this calls
it for real.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from poe2arb.listings import Band, Listing, build_candidates
from poe2arb.report import print_candidates
from poe2arb.sweep import SweepResult

T0 = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def candidates(*prices):
    listings = [
        Listing(
            item_id="omen", account=f"s{i}#1", character=f"Seller{i}",
            pay_amount=price, get_amount=1.0, stock=3.0, indexed=T0,
            whisper="@{2} buy {0} for {1}", item_whisper="{0} Omen",
            pay_whisper="{0} Divine", pay_currency="divine",
        )
        for i, price in enumerate(prices)
    ]
    return build_candidates(
        listings, {"omen": 12.0, "divine": 1.0}, {"omen": "Omen of Light"},
        min_gap=1.05, max_gap=1.5,
    )


def result(cands):
    return SweepResult(
        league="Standard", started_at=T0, finished_at=T0 + timedelta(seconds=42),
        items=["omen"], listings_seen=len(cands), candidates=cands, errors={},
    )


def test_it_prints_a_table(capsys):
    print_candidates(result(candidates(10.0, 1.0)), limit=10)
    out = capsys.readouterr().out
    # Rich ellipsises long names to fit the column, so match a prefix.
    assert "Omen" in out
    assert "Standard" in out


def test_every_band_renders(capsys):
    """One missing label would only show on whichever band happened to appear."""
    cands = candidates(11.8, 10.0, 1.0)
    assert {c.band for c in cands} == set(Band)
    print_candidates(result(cands), limit=10)
    assert capsys.readouterr().out


def test_an_empty_sweep_is_survivable(capsys):
    print_candidates(result([]), limit=10)
    assert capsys.readouterr().out


def test_the_limit_is_honoured(capsys):
    print_candidates(result(candidates(10.0, 10.1, 10.2, 10.3)), limit=2)
    out = capsys.readouterr().out
    assert out.count("Seller") <= 3      # 2 rows, plus any in the footer
