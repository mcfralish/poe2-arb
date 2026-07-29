"""One trade offered at a time, so the app can interrupt a map without ruining it.

A sweep finds a dozen candidates at once. Presenting them all is useless to
someone who is mid-pack: they need *one* thing, briefly, that costs a keypress
to accept and nothing to ignore. So trades are queued and offered singly:

    QUEUED -> OFFERED -> AWAITING -> RESOLVED
                 |
                 +--> AVAILABLE -> AWAITING -> RESOLVED
                          |
                          +--> EXPIRED

**OFFERED** is the live one: a toast has fired and the hotkey is armed for
`offer_window_s`. Exactly one trade is ever in this state — a second toast
arriving while the first is unread would make both of them noise. The window is
short on purpose: it gates how fast the *queue* drains, not how long the user
has to decide, because an unclaimed offer is not lost — it just stops
interrupting.

**AVAILABLE** is where an unclaimed offer lands, for `available_ttl_s`. Still
perfectly good, no longer worth a second interruption.

**AWAITING** is the honest cost of the whole scheme: the app cannot see whether
a seller replied, so the user has to say. It gets its own section rather than
being mixed in with work still to do. After `awaiting_timeout_s` an unanswered
trade resolves itself to `NO_REPLY` — which is almost always what happened, and
leaving it pending forever would bias the outcome log toward whatever the user
bothered to come back and click.

Deliberately Qt-free — all the timing is passed-in `now`, so the transitions can
be tested without waiting for real clocks.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from .listings import Band, Candidate, whisper_text
from .outcomes import Outcome

log = logging.getLogger(__name__)


class QueueState(Enum):
    QUEUED = "queued"        # found, not yet offered
    OFFERED = "offered"      # toast fired, hotkey armed, clock running
    AVAILABLE = "available"  # offer lapsed; still takeable from the panel
    AWAITING = "awaiting"    # whisper copied, waiting on the user to say what happened
    RESOLVED = "resolved"    # verdict recorded
    EXPIRED = "expired"      # nobody took it in time


@dataclass
class QueuedTrade:
    id: str
    candidate: Candidate
    state: QueueState
    queued_at: datetime
    offered_at: datetime | None = None
    # When the current state lapses. Only meaningful for OFFERED and AVAILABLE.
    expires_at: datetime | None = None
    taken_at: datetime | None = None
    attempt_id: str | None = None
    outcome: Outcome | None = None

    @property
    def key(self) -> tuple:
        return self.candidate.key

    def seconds_left(self, now: datetime) -> float | None:
        if self.expires_at is None:
            return None
        return max(0.0, (self.expires_at - now).total_seconds())


@dataclass
class QueueTick:
    """What changed on this tick, so the UI knows what to announce."""

    newly_offered: QueuedTrade | None = None
    lapsed_to_available: list[QueuedTrade] = field(default_factory=list)
    expired: list[QueuedTrade] = field(default_factory=list)
    # Whispers that timed out and were recorded as NO_REPLY. The caller must
    # write these to the outcome log, so they are reported rather than silent.
    auto_resolved: list[QueuedTrade] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.newly_offered
            or self.lapsed_to_available
            or self.expired
            or self.auto_resolved
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TradeQueue:
    """Holds trades through their lifecycle. No Qt, no timers of its own."""

    def __init__(
        self,
        *,
        offer_window_s: float = 20.0,
        available_ttl_s: float = 300.0,
        awaiting_timeout_s: float = 600.0,
        queue_ghosts: bool = False,
    ):
        self.offer_window_s = offer_window_s
        self.available_ttl_s = available_ttl_s
        self.awaiting_timeout_s = awaiting_timeout_s
        # Ghosts are measured never to fill, so interrupting a map for one is
        # strictly a cost. They stay visible in the Trades tab either way.
        self.queue_ghosts = queue_ghosts
        self._trades: list[QueuedTrade] = []

    # --- inspection --------------------------------------------------------

    @property
    def offered(self) -> QueuedTrade | None:
        return next((t for t in self._trades if t.state is QueueState.OFFERED), None)

    @property
    def available(self) -> list[QueuedTrade]:
        """Takeable now: the live offer first, then the rest best-first.

        The live one is pinned to the top even when a lapsed trade is worth
        more. It is the one the hotkey acts on and the one the countdown
        belongs to, so burying it under a better row would be actively
        misleading about what pressing the key does.
        """
        rows = [
            t for t in self._trades
            if t.state in (QueueState.OFFERED, QueueState.AVAILABLE)
        ]
        return sorted(
            rows, key=lambda t: (t.state is not QueueState.OFFERED, *_ranking_key(t))
        )

    @property
    def awaiting(self) -> list[QueuedTrade]:
        """Whispered, waiting on the user. Oldest first — those went cold soonest."""
        rows = [t for t in self._trades if t.state is QueueState.AWAITING]
        return sorted(rows, key=lambda t: (t.taken_at or t.queued_at, t.id))

    @property
    def pending(self) -> list[QueuedTrade]:
        return [t for t in self._trades if t.state is QueueState.QUEUED]

    def get(self, trade_id: str) -> QueuedTrade | None:
        return next((t for t in self._trades if t.id == trade_id), None)

    # --- filling -----------------------------------------------------------

    def submit(self, candidates: list[Candidate], now: datetime | None = None) -> int:
        """Add candidates not already in flight. Returns how many were new.

        Deduplicated against every trade that isn't finished, including ones the
        user already whispered: a sweep repeated ten minutes later will re-find
        the same listing, and re-offering it would have them message the same
        seller twice.
        """
        now = now or _now()
        known = {
            t.key for t in self._trades
            if t.state not in (QueueState.EXPIRED,)
        }
        added = 0
        for c in candidates:
            if c.key in known:
                continue
            if c.band is Band.GHOST and not self.queue_ghosts:
                continue
            if whisper_text(c) is None:
                continue  # nothing to copy, so nothing to offer
            self._trades.append(
                QueuedTrade(
                    id=uuid.uuid4().hex[:12],
                    candidate=c,
                    state=QueueState.QUEUED,
                    queued_at=now,
                )
            )
            known.add(c.key)
            added += 1
        return added

    # --- the clock ---------------------------------------------------------

    def tick(self, now: datetime | None = None) -> QueueTick:
        """Advance every timer, then offer the next trade if the slot is free."""
        now = now or _now()
        result = QueueTick()

        for t in self._trades:
            if t.expires_at is None or now < t.expires_at:
                continue
            if t.state is QueueState.OFFERED:
                t.state = QueueState.AVAILABLE
                t.expires_at = now + timedelta(seconds=self.available_ttl_s)
                result.lapsed_to_available.append(t)
            elif t.state is QueueState.AVAILABLE:
                t.state = QueueState.EXPIRED
                t.expires_at = None
                result.expired.append(t)
            elif t.state is QueueState.AWAITING:
                # Silence is the overwhelmingly common outcome; recording it
                # beats letting the row sit unanswered forever.
                t.state = QueueState.RESOLVED
                t.outcome = Outcome.NO_REPLY
                t.expires_at = None
                result.auto_resolved.append(t)

        if self.offered is None:
            nxt = self._next_to_offer()
            if nxt is not None:
                nxt.state = QueueState.OFFERED
                nxt.offered_at = now
                nxt.expires_at = now + timedelta(seconds=self.offer_window_s)
                result.newly_offered = nxt
        return result

    def _next_to_offer(self) -> QueuedTrade | None:
        pending = self.pending
        if not pending:
            return None
        return min(pending, key=_ranking_key)

    # --- user actions ------------------------------------------------------

    def take(self, trade_id: str, now: datetime | None = None) -> QueuedTrade | None:
        """Mark a trade as whispered. Returns it, or None if it isn't takeable."""
        now = now or _now()
        t = self.get(trade_id)
        if t is None or t.state not in (QueueState.OFFERED, QueueState.AVAILABLE):
            return None
        t.state = QueueState.AWAITING
        t.taken_at = now
        t.expires_at = (
            now + timedelta(seconds=self.awaiting_timeout_s)
            if self.awaiting_timeout_s > 0
            else None
        )
        return t

    def take_offered(self, now: datetime | None = None) -> QueuedTrade | None:
        """What the hotkey does. None when nothing is armed."""
        current = self.offered
        return self.take(current.id, now) if current is not None else None

    def resolve(
        self, trade_id: str, outcome: Outcome, now: datetime | None = None
    ) -> QueuedTrade | None:
        t = self.get(trade_id)
        if t is None or t.state is not QueueState.AWAITING:
            return None
        t.state = QueueState.RESOLVED
        t.outcome = outcome
        return t

    def drop(self, trade_id: str) -> bool:
        """Dismiss a trade the user doesn't want, without recording an attempt."""
        t = self.get(trade_id)
        if t is None or t.state in (QueueState.AWAITING, QueueState.RESOLVED):
            return False
        t.state = QueueState.EXPIRED
        t.expires_at = None
        return True

    def forget_resolved(self) -> int:
        """Drop finished rows so the queue doesn't grow across a long session."""
        before = len(self._trades)
        self._trades = [
            t for t in self._trades
            if t.state not in (QueueState.RESOLVED, QueueState.EXPIRED)
        ]
        return before - len(self._trades)


def _ranking_key(t: QueuedTrade) -> tuple:
    """Best first: plausible before thin, then most profitable.

    Same ordering as the Trades table, so the queue never offers something the
    user can see is worse than the row above it.
    """
    c = t.candidate
    return (c.band.rank, -c.profit_divines, c.gap, t.id)
