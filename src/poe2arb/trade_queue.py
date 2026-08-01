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

**AVAILABLE** is where an unclaimed offer lands. Still perfectly good, no longer
worth a second interruption.

`available_ttl_s` is measured from the moment a trade is **first shown**, not
from the moment it stops being the live offer, and `expires_at` is set once at
that point rather than being restarted on the transition. Reported from the
field 2026-07-31: the alert window was being spent before the listed window
began, so "trade stays listed for 5 minutes" meant 20 seconds of alert plus five
minutes, and the countdown a row showed while live described the alert rather
than when it would actually drop off. A row now gets its configured time in
*Ready to whisper* whatever happened to it beforehand, and the Expires column
means the same thing on every row.

**AWAITING** is the honest cost of the whole scheme: the app cannot see whether
a seller replied, so the user has to say. It gets its own section rather than
being mixed in with work still to do. After `awaiting_timeout_s` an unanswered
trade resolves itself to `Outcome.EXPIRED` — leaving it pending forever would
bias the outcome log toward whatever the user bothered to come back and click.

It writes `EXPIRED` rather than `NO_REPLY` because the timer does not know the
seller stayed silent; it knows only that the deadline passed. Measured
2026-08-01: **both** false expiries that evening were sellers who had *answered*,
one of them already mid-trade, and the record it wrote over the top was the
biggest trade the project has made. A row the user has heard from can be
**pinned**, which takes it off the clock entirely — that, rather than a longer
timeout, is the fix for a seller who is talking to you.

Deliberately Qt-free — all the timing is passed-in `now`, so the transitions can
be tested without waiting for real clocks.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from .listings import Band, Candidate, replan_units, whisper_text
from .outcomes import Outcome

log = logging.getLogger(__name__)

# Verdicts that finish a *listing*, not just a row. After one of these, whatever
# the sweep keeps finding is stock that is gone, a seller who is not there, or a
# price that will not be honoured — so the key is suppressed for the rest of the
# session. `EXPIRED` and `AFK` are deliberately absent: an away seller comes
# back, and a deadline passing says nothing about the listing at all.
SETTLED_OUTCOMES = frozenset(
    {Outcome.FILLED, Outcome.SOLD, Outcome.OFFLINE, Outcome.DECLINED}
)


class QueueState(Enum):
    QUEUED = "queued"        # found, not yet offered
    OFFERED = "offered"      # toast fired, hotkey armed, clock running
    AVAILABLE = "available"  # offer lapsed; still takeable from the panel
    AWAITING = "awaiting"    # whisper copied, waiting on the user to say what happened
    RESOLVED = "resolved"    # verdict recorded
    # Nobody took it in time. Not to be confused with `Outcome.EXPIRED`, which
    # is a verdict on a whisper that *was* sent; this row never became one.
    EXPIRED = "expired"


@dataclass
class QueuedTrade:
    id: str
    candidate: Candidate
    state: QueueState
    queued_at: datetime
    offered_at: datetime | None = None
    # When this row drops off the list. Set once, when the trade is first shown,
    # and not touched again as it moves from OFFERED to AVAILABLE — the two
    # states are one visible lifetime with one deadline.
    expires_at: datetime | None = None
    # When the *alert* stops: the toast has been up long enough and the hotkey
    # should move on. Strictly shorter than `expires_at`, and deliberately not
    # shown anywhere — the user has no decision that hangs on it.
    alert_until: datetime | None = None
    taken_at: datetime | None = None
    attempt_id: str | None = None
    outcome: Outcome | None = None
    # Held out of the auto-expiry, at the user's request. Session UI state, not
    # a fact about the trade — deliberately absent from `outcomes.jsonl`.
    pinned: bool = False

    @property
    def key(self) -> tuple:
        return self.candidate.key

    def seconds_left(self, now: datetime) -> float | None:
        """Time until this row expires. None when nothing is counting down."""
        if self.pinned or self.expires_at is None:
            return None
        return max(0.0, (self.expires_at - now).total_seconds())


@dataclass
class QueueTick:
    """What changed on this tick, so the UI knows what to announce."""

    newly_offered: QueuedTrade | None = None
    lapsed_to_available: list[QueuedTrade] = field(default_factory=list)
    expired: list[QueuedTrade] = field(default_factory=list)
    # Whispers that timed out and were recorded as `Outcome.EXPIRED`. The caller
    # must write these to the outcome log, so they are reported rather than
    # silent.
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
        # Keys the user actively declined. Never re-offered for the life of the
        # process: a sweep every ten minutes re-finds the same listing, and
        # being shown a trade you have already said no to costs exactly as much
        # attention as a new one while carrying none of the information.
        # Deliberately not persisted — the reason for declining is usually "not
        # right now", which does not survive a restart.
        self._declined: set[tuple] = set()
        # Listings this session has finished with: bought, told they were gone,
        # told the seller is offline, or refused on price. A Bulk listing does
        # **not** delist when the stock goes, so every later sweep re-finds it —
        # measured 2026-08-01, the same stale listing was whispered five times
        # across four sessions in 3½ hours, twice to a seller the game had
        # answered "is not online" for and once to a seller already traded with.
        # Keyed on the candidate key (seller + item + ratio) rather than on the
        # row, because the row id is regenerated by every sweep.
        self._settled: set[tuple] = set()

    # --- inspection --------------------------------------------------------

    @property
    def offered(self) -> QueuedTrade | None:
        return next((t for t in self._trades if t.state is QueueState.OFFERED), None)

    @property
    def available(self) -> list[QueuedTrade]:
        """Takeable now, oldest first — the newest arrival lands at the bottom.

        Presentation order, not ranking order, and that is the point. This list
        is read while playing, so a row that jumps position between one glance
        and the next is a row you click by mistake. Appending at the bottom
        leaves everything already on screen exactly where it was, and the row
        nearest expiry is the one at the top where it can be dealt with first.

        The live offer is *not* pinned to the top any more. It sorts to the
        bottom like anything else, carries the ● marker, and is named in the
        headline above the table — which is where someone mid-map is looking.
        """
        rows = [
            t for t in self._trades
            if t.state in (QueueState.OFFERED, QueueState.AVAILABLE)
        ]
        return sorted(rows, key=lambda t: (t.offered_at or t.queued_at, t.id))

    @property
    def awaiting(self) -> list[QueuedTrade]:
        """Whispered, waiting on the user. **Pinned first, then newest first.**

        The opposite order to `available`, on purpose. A reply arrives seconds
        to minutes after the whisper, so the row you need is almost always the
        one you just sent; the ones at the bottom are the ones going cold, and
        they self-resolve without being touched.

        Pinned rows sit above all of that. Pinning means a seller has spoken, so
        the row has stopped being one of many and become the trade in progress —
        and it no longer self-resolves, so nothing else will bring it back to
        the user's attention.
        """
        rows = [t for t in self._trades if t.state is QueueState.AWAITING]
        return sorted(
            rows,
            key=lambda t: (t.pinned, t.taken_at or t.queued_at, t.id),
            reverse=True,
        )

    @property
    def pending(self) -> list[QueuedTrade]:
        return [t for t in self._trades if t.state is QueueState.QUEUED]

    @property
    def outstanding(self) -> int:
        """Trades the user could still act on or owes an answer for.

        What decides whether a trading session is over — see `session.py`.
        Resolved and expired rows are done with and don't hold one open.
        """
        return sum(
            1
            for t in self._trades
            if t.state in (
                QueueState.QUEUED,
                QueueState.OFFERED,
                QueueState.AVAILABLE,
                QueueState.AWAITING,
            )
        )

    def get(self, trade_id: str) -> QueuedTrade | None:
        return next((t for t in self._trades if t.id == trade_id), None)

    # --- filling -----------------------------------------------------------

    def submit(self, candidates: list[Candidate], now: datetime | None = None) -> int:
        """Add candidates not already in flight. Returns how many were new.

        Deduplicated against every trade that isn't finished, including ones the
        user already whispered: a sweep repeated ten minutes later will re-find
        the same listing, and re-offering it would have them message the same
        seller twice. Declined and settled keys are filtered the same way, for
        the same reason — see `_declined` and `_settled`. Those two outlive
        `forget_resolved`, which is what makes them necessary: dropping a
        finished row from `_trades` also drops the only record that the listing
        had been dealt with, and the next sweep offered it again.
        """
        now = now or _now()
        known = {
            t.key for t in self._trades
            if t.state not in (QueueState.EXPIRED,)
        }
        added = 0
        for c in candidates:
            if c.key in known or c.key in self._declined or c.key in self._settled:
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
            # The alert lapsing and the row expiring are separate clocks, and a
            # short listing window can retire a trade that is still the live
            # offer — so both are checked, in that order, on the same tick.
            if (
                t.state is QueueState.OFFERED
                and t.alert_until is not None
                and now >= t.alert_until
            ):
                t.state = QueueState.AVAILABLE
                result.lapsed_to_available.append(t)
            if t.pinned or t.expires_at is None or now < t.expires_at:
                continue
            if t.state in (QueueState.OFFERED, QueueState.AVAILABLE):
                t.state = QueueState.EXPIRED
                t.expires_at = None
                result.expired.append(t)
            elif t.state is QueueState.AWAITING:
                # No answer arrived before the deadline, which is all this
                # knows — `Outcome.EXPIRED`, not `NO_REPLY`. Recording it beats
                # letting the row sit unanswered forever, but it is a statement
                # about the clock and the verdict says so.
                t.state = QueueState.RESOLVED
                t.outcome = Outcome.EXPIRED
                t.expires_at = None
                result.auto_resolved.append(t)

        if self.offered is None:
            nxt = self._next_to_offer()
            if nxt is not None:
                nxt.state = QueueState.OFFERED
                nxt.offered_at = now
                nxt.alert_until = now + timedelta(seconds=self.offer_window_s)
                # The listed window starts here and is never restarted. Floored
                # at the alert window so a short TTL cannot retire a trade
                # before its own toast has finished.
                nxt.expires_at = now + timedelta(
                    seconds=max(self.available_ttl_s, self.offer_window_s)
                )
                result.newly_offered = nxt
        return result

    def _next_to_offer(self) -> QueuedTrade | None:
        """Best pending trade.

        Nothing is held back against outstanding whispers. v0.6.0 treated a
        copied whisper as money spent until the user said otherwise, so a
        second trade in the same currency was withheld while the first went
        unanswered. Reverted 2026-07-31 on the maintainer's call: whispers
        resolve as no-reply ~79% of the time, so the money is almost never
        actually committed, and the guard mostly suppressed offers the user
        could have taken. Sizing against the whole bankroll — which
        `build_candidates` already does — is the accurate model at that fill
        rate.
        """
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

    def revise(self, trade_id: str, units: float) -> QueuedTrade | None:
        """Correct the quantity on a trade to what was actually available.

        Returns the trade if anything changed. The candidate's `key` is derived
        from the listing rather than the quantity, so a revised trade keeps its
        identity and is still recognised as already-whispered by the next sweep.
        """
        t = self.get(trade_id)
        if t is None:
            return None
        revised = replan_units(t.candidate, units)
        if revised.plan.units == t.candidate.plan.units:
            return None
        t.candidate = revised
        return t

    def resolve(
        self, trade_id: str, outcome: Outcome, now: datetime | None = None
    ) -> QueuedTrade | None:
        t = self.get(trade_id)
        if t is None or t.state is not QueueState.AWAITING:
            return None
        t.state = QueueState.RESOLVED
        t.outcome = outcome
        t.pinned = False
        if outcome in SETTLED_OUTCOMES:
            self._settled.add(t.key)
        return t

    def pin(self, trade_id: str, pinned: bool = True) -> QueuedTrade | None:
        """Hold a whispered row out of the auto-expiry, or let it back in.

        For the case the timeout gets wrong: a seller who has answered is not on
        a clock any more, and the five-minute deadline going off behind a live
        conversation is how a completed trade got written down as no reply.
        Unpinning restarts nothing — `expires_at` is untouched throughout, so a
        row pinned past its deadline resolves on the next tick after it is
        released, which is the honest reading of "this went unanswered after
        all".
        """
        t = self.get(trade_id)
        if t is None or t.state is not QueueState.AWAITING:
            return None
        t.pinned = bool(pinned)
        return t

    @property
    def settled(self) -> frozenset[tuple]:
        return frozenset(self._settled)

    def drop(self, trade_id: str, *, remember: bool = False) -> bool:
        """Dismiss a trade the user doesn't want, without recording an attempt.

        `remember` marks the offer as declined for the rest of the session, so
        later sweeps stop re-finding it. Set it for a deliberate Decline and
        leave it off for a drop the app performed itself — a listing with no
        whisper template, say — which is a fact about this fetch rather than a
        judgement the user made.
        """
        t = self.get(trade_id)
        if t is None or t.state in (QueueState.AWAITING, QueueState.RESOLVED):
            return False
        if remember:
            self._declined.add(t.key)
        t.state = QueueState.EXPIRED
        t.expires_at = None
        return True

    def decline(self, trade_id: str) -> bool:
        """Drop this trade and never offer it again this session."""
        return self.drop(trade_id, remember=True)

    @property
    def declined(self) -> frozenset[tuple]:
        return frozenset(self._declined)

    def cancel_pending(self) -> int:
        """Discard the un-offered backlog. Returns how many were dropped.

        What *Find trades* switching off has to mean. Cancelling the sweep only
        stops finding new listings; the backlog it already found keeps being
        promoted by `tick`, one every `offer_window_s`, so stopping produced
        toasts for minutes afterwards (reported from the field 2026-07-30).

        Deliberately only touches QUEUED. A trade that has been offered,
        lapsed to available, or been whispered is the user's to finish — a stop
        button that retracted an offer mid-decision, or dropped a whisper still
        awaiting its answer, would lose both the trade and its outcome record.
        Those are exactly the rows they asked to keep.
        """
        pending = self.pending
        for t in pending:
            t.state = QueueState.EXPIRED
            t.expires_at = None
        return len(pending)

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
