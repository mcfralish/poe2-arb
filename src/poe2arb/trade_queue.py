"""Everything found, takeable at once, best first.

    AVAILABLE -> AWAITING -> RESOLVED
         |
         +--> EXPIRED

**AVAILABLE** is every candidate the sweep has found and not finished with. A
trade enters it the moment it is found and starts its `available_ttl_s` clock
there; `expires_at` is set once, at that point, and never restarted.

**This replaced an interruption model in 0.9.0, and the reversal is the point.**
Up to 0.8.0 a trade sat in QUEUED until `tick` promoted it, one per
`offer_window_s`, into an OFFERED state that fired a toast and armed the hotkey
— built for a user mid-map who could be shown exactly one thing at a time. That
premise was measured false (FINDINGS, *The first real play session on 0.8.0*):
the app is used sitting in town with full attention, so the scarce resource is
whispers sent per minute, not the user's patience. The drip made a sweep's
candidates appear over minutes and left them invisible meanwhile. So: no
QUEUED, no OFFERED, no toast, no alert window, and `available` is sorted by the
**ranking key** rather than by arrival, because the hotkey takes the best row
and the user needs to see which one that is. The cost of that sort is real and
was the old rule's reason: a better candidate arriving reshuffles the rows.
Row 1 is the hotkey's row, so it is the one least likely to be clicked by
mistake, and the panel holds a reshuffle while the pointer is over the table.

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

from .listings import Band, Candidate, replan_units, repriced, whisper_text
from .outcomes import Outcome

log = logging.getLogger(__name__)

# Verdicts that finish a *listing*, not just a row. After one of these, whatever
# the sweep keeps finding is stock that is gone, a seller who is not there, or a
# price that will not be honoured — so the key is suppressed for the rest of the
# session. `EXPIRED` and `AFK` are deliberately absent: an away seller comes
# back, and a deadline passing says nothing about the listing at all.
#
# `UNAVAILABLE` is absent for the same reason, and it was a real decision rather
# than an omission. The one button that writes it replaced AFK *and* Offline,
# and those two sat on opposite sides of this set — so the merged verdict is
# read as the weaker of the two claims, which is the only honest reading of a
# press that deliberately says nothing about why. A seller who was away when the
# sweep found them is a seller worth re-finding fifteen minutes later.
SETTLED_OUTCOMES = frozenset(
    {Outcome.FILLED, Outcome.SOLD, Outcome.OFFLINE, Outcome.DECLINED}
)


class QueueState(Enum):
    AVAILABLE = "available"  # found, takeable from the panel, clock running
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
    # When the trade was found, which is also when it became takeable and when
    # its clock started. There is no promotion step any more, so the three are
    # the same moment.
    queued_at: datetime
    # When this row drops off the list. Set once, at `submit`, and not touched
    # again until the whisper goes out and the awaiting timeout replaces it.
    expires_at: datetime | None = None
    taken_at: datetime | None = None
    attempt_id: str | None = None
    # The trade as it was whispered. Corrections re-derive from this rather
    # than compounding on the last one, so an inline editor can be walked back
    # up as well as down — `replan_units` can only ever shrink what it is given,
    # and applied to its own output it would ratchet.
    asked: Candidate | None = None
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
    """What the clock changed on this tick, so the caller can record it.

    Nothing is *promoted* any more — a trade is takeable from the moment it is
    submitted — so a tick only ever retires rows.
    """

    expired: list[QueuedTrade] = field(default_factory=list)
    # Whispers that timed out and were recorded as `Outcome.EXPIRED`. The caller
    # must write these to the outcome log, so they are reported rather than
    # silent.
    auto_resolved: list[QueuedTrade] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.expired or self.auto_resolved)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TradeQueue:
    """Holds trades through their lifecycle. No Qt, no timers of its own."""

    def __init__(
        self,
        *,
        available_ttl_s: float = 300.0,
        awaiting_timeout_s: float = 600.0,
        queue_ghosts: bool = False,
    ):
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
    def available(self) -> list[QueuedTrade]:
        """Takeable now, **best first — row 1 is what the hotkey takes.**

        Ranking order, not presentation order, reversing the rule that held
        until 0.9.0. Two premises under the old one failed in the first real
        play session on 0.8.0: the app is not read mid-map, and the maintainer
        deliberately shrinks this pane to a few rows to give the room to
        *Waiting on a reply* — at which point an order that is not the hotkey's
        order means the visible rows are not the ones the key will act on.

        The old rule's cost is now this one's: a better candidate arriving
        moves every row below it. `_ranking_key` is the same order the Results
        table sorts by, so the queue never offers something visibly worse than
        the row above it.
        """
        rows = [t for t in self._trades if t.state is QueueState.AVAILABLE]
        return sorted(rows, key=_ranking_key)

    @property
    def next_up(self) -> QueuedTrade | None:
        """Row 1 of *Ready* — what the hotkey takes and what ● marks."""
        rows = self.available
        return rows[0] if rows else None

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
    def outstanding(self) -> int:
        """Trades the user could still act on or owes an answer for.

        What decides whether a trading session is over — see `session.py`.
        Resolved and expired rows are done with and don't hold one open.
        """
        return sum(
            1
            for t in self._trades
            if t.state in (QueueState.AVAILABLE, QueueState.AWAITING)
        )

    def get(self, trade_id: str) -> QueuedTrade | None:
        return next((t for t in self._trades if t.id == trade_id), None)

    # --- filling -----------------------------------------------------------

    def submit(self, candidates: list[Candidate], now: datetime | None = None) -> int:
        """Add candidates not already in flight. Returns how many were new.

        **Everything lands takeable, with its clock already running.** There is
        no backlog and no promotion: a candidate found is a candidate on screen,
        which is what removing the drip means in one line.

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
                    state=QueueState.AVAILABLE,
                    queued_at=now,
                    expires_at=now + timedelta(seconds=self.available_ttl_s),
                )
            )
            known.add(c.key)
            added += 1
        return added

    # --- the clock ---------------------------------------------------------

    def tick(self, now: datetime | None = None) -> QueueTick:
        """Advance every timer. Retires rows; nothing else moves on a clock."""
        now = now or _now()
        result = QueueTick()

        for t in self._trades:
            if t.pinned or t.expires_at is None or now < t.expires_at:
                continue
            if t.state is QueueState.AVAILABLE:
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

        return result

    # --- user actions ------------------------------------------------------

    def take(self, trade_id: str, now: datetime | None = None) -> QueuedTrade | None:
        """Mark a trade as whispered. Returns it, or None if it isn't takeable.

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
        now = now or _now()
        t = self.get(trade_id)
        if t is None or t.state is not QueueState.AVAILABLE:
            return None
        t.state = QueueState.AWAITING
        t.taken_at = now
        # What was actually asked for, kept so a later correction is measured
        # against the ask rather than against the last correction.
        t.asked = t.candidate
        t.expires_at = (
            now + timedelta(seconds=self.awaiting_timeout_s)
            if self.awaiting_timeout_s > 0
            else None
        )
        return t

    def take_next(self, now: datetime | None = None) -> QueuedTrade | None:
        """What the hotkey does: take row 1 of *Ready*. None when it is empty."""
        current = self.next_up
        return self.take(current.id, now) if current is not None else None

    def revise(
        self,
        trade_id: str,
        units: float | None = None,
        pay_units: float | None = None,
    ) -> QueuedTrade | None:
        """Correct a trade to the quantity and price it actually happened at.

        Returns the trade if anything changed. The candidate's `key` is derived
        from the listing rather than the quantity or the price, so a revised
        trade keeps its identity and is still recognised as already-whispered by
        the next sweep.

        Quantity is applied before price: shrinking the quantity re-prices the
        trade at the listing's own rate, and an explicit `pay_units` is the user
        overriding *that* with what the seller actually asked for.

        **Both are re-applied to the ask, not to the last correction.**
        `replan_units` can only shrink what it is given, so compounding one
        correction onto another would ratchet — an inline spin box nudged down
        one lot too far could never be nudged back up, and 0.8.0's dialog only
        avoided that by being opened fresh each time. A `pay_units` of None
        therefore means "at the listed rate for this quantity" rather than
        "keep whatever the last correction said" — the two editors that call
        this always send both, and inferring the second from a stale one is how
        a corrected price would silently reappear on a corrected quantity.
        """
        t = self.get(trade_id)
        if t is None:
            return None
        was = t.candidate
        revised = t.asked or was
        revised = replan_units(
            revised, was.plan.units if units is None else units
        )
        if pay_units is not None:
            revised = repriced(revised, pay_units)
        if (
            revised.plan.units == was.plan.units
            and revised.plan.pay_units == was.plan.pay_units
        ):
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
    user can see is worse than the row above it — and, since 0.9.0, the order
    *Ready to whisper* is drawn in, so row 1 is the row the hotkey takes.
    """
    c = t.candidate
    return (c.band.rank, -c.profit_divines, c.gap, t.id)
