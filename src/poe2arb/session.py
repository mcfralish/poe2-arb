"""What counts as one trading session.

A session is the unit the user reviews their trading in — "what did I make
tonight" — and it is not a clock interval. It starts when *Find trades* is
switched on and ends when the last opportunity has left the queue with the
loop switched off. Pressing *Find trades* again while anything is still in
flight continues the same session rather than starting a new one, because the
whispers either side of that press are the same evening's work.

**The queue emptying is not on its own the end.** Between sweeps the queue is
routinely empty for minutes with the loop still running; ending there would
close a session in the middle of one and leave every whisper afterwards
belonging to nothing. So both conditions have to hold: nothing outstanding, and
nothing looking for more.

Qt-free and clock-injected like the rest of the core, so the transitions test
without a display.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SessionTracker:
    """The id stamped on every whisper, and when it turns over."""

    id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.id is not None

    def begin(self, now: datetime | None = None) -> str:
        """Start a session, or carry on with the one already running."""
        if self.id is None:
            self.id = uuid.uuid4().hex[:12]
            self.started_at = now or _now()
            self.ended_at = None
        return self.id

    def note_state(
        self,
        *,
        looking: bool,
        outstanding: int,
        now: datetime | None = None,
    ) -> str | None:
        """Close the session if the loop is off and nothing is left in flight.

        `outstanding` counts everything the user could still act on or answer
        for — queued, offered, available and awaiting a reply. Returns the id of
        the session that just ended, or None if nothing changed.
        """
        if self.id is None or looking or outstanding > 0:
            return None
        ended, self.id = self.id, None
        self.ended_at = now or _now()
        return ended
