"""When one trading session ends and the next begins."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from poe2arb.session import SessionTracker

T0 = datetime(2026, 7, 31, 20, 0, tzinfo=timezone.utc)


def test_a_session_starts_on_the_first_press():
    s = SessionTracker()
    assert not s.active
    first = s.begin(T0)
    assert s.active and s.started_at == T0
    assert first


def test_pressing_find_trades_again_continues_the_same_session():
    """Asked for explicitly: two sweeps in one sitting are one sitting."""
    s = SessionTracker()
    first = s.begin(T0)
    assert s.begin(T0 + timedelta(minutes=10)) == first
    assert s.started_at == T0


def test_it_ends_only_when_nothing_is_running_and_nothing_is_left():
    s = SessionTracker()
    started = s.begin(T0)
    # Still sweeping, queue empty — the gap between two sweeps, not the end.
    assert s.note_state(looking=True, outstanding=0, now=T0) is None
    # Stopped, but a whisper is still waiting on an answer.
    assert s.note_state(looking=False, outstanding=1, now=T0) is None
    assert s.active
    ended = s.note_state(looking=False, outstanding=0, now=T0 + timedelta(hours=1))
    assert ended == started
    assert not s.active
    assert s.ended_at == T0 + timedelta(hours=1)


def test_ending_twice_reports_nothing_the_second_time():
    s = SessionTracker()
    s.begin(T0)
    assert s.note_state(looking=False, outstanding=0, now=T0) is not None
    assert s.note_state(looking=False, outstanding=0, now=T0) is None


def test_the_next_press_starts_a_new_one():
    s = SessionTracker()
    first = s.begin(T0)
    s.note_state(looking=False, outstanding=0, now=T0)
    assert s.begin(T0 + timedelta(hours=2)) != first
