"""Cross-venue candidates: Bulk Item Exchange listings priced against the CE.

The trade is: buy an underpriced listing by whisper on the Bulk Item Exchange,
sell into the in-game Currency Exchange. Two field tests (docs/FINDINGS.md,
"Negative results") shape everything here:

1. **Deep discounts fill rarely, not never.** Fitted 2026-08-01 from 789 logged
   whispers, after two under-sampled readings said first that they never fill
   (n=14) and then that they are worth about a quarter of a plausible whisper
   (n=156). Measured: plausible 12.4% (n=178), ghost **2.0%** (n=601), and the
   fills at 3.92x and 10.94x that overturned the first reading are confirmed to
   have gone through **at the listed price**, not as counteroffers. Ghosts are
   worth 0.66 of a plausible whisper in divines, not 0.28, so they are demoted
   rather than buried — see `FILL_PRIOR`, now 0.16 for ghosts rather than 0.0.

2. **A listing that has sat three days does not sell.** 0 fills in 102 whispers;
   the oldest that ever filled was 62.9 hours old. It holds in every band, so it
   is age rather than gap, and it is the only signal in the log that predicts a
   flat zero. `STALE_LISTING_S` gates on it; `rank_candidates` sorts those
   listings below everything fresh without hiding any of them.

3. **Partial currency cannot be traded, so the settlement currency decides the
   haircut.** A 3.79 CE rate pays 3 if you take divines and 1636 exalted — 3.789
   divines — if you take exalted, because exalted is ~432x finer. Measured on
   the one trade that filled, settling in exalted turns a 1.00 divine profit
   into 1.79. Profit is therefore floored to `sale_unit_divines`, never to a
   whole divine and never left unfloored.

`max_gap_ratio` is supported by the log and the cliff is now located more
precisely than before: fills run 9%-15% below 1.5x and 1%-3% above it, so 1.50
sits on the edge. `min_gap_ratio` is no longer unmeasured — 56 whispers below
1.10x fill at 14%, as well as any bucket under the cliff — but it is still not
*settled*, because at a 1.05 gap the whole edge is inside the reference price's
own ~6% error. That is a pricing question, not a fill question, and the two
still have to be fitted together.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

# A listing can't offer more lots than this. Stock on this venue is single
# digits in practice (see TODO.md: the bulk-seller quadrant is empty), so the
# cap only guards against a malformed response driving an unbounded loop.
MAX_LOTS = 10_000

# The unit of account. Matches client.PRIMARY, duplicated rather than imported
# so this module stays free of the HTTP layer.
UNIT_CURRENCY = "divine"


class Band(Enum):
    """How much the gap itself says about whether the listing is worth a whisper.

    `THIN` is not "too small to bother with" — everything here has already been
    checked for positive profit. It means **the gap is inside our own error
    bars**: the CE reference ran 0.4%-4.7% below the live game across five
    measured items, so a 1.04x gap is indistinguishable from no gap at all, and
    the profit figure attached to it is equally uncertain. Shown, ranked below
    plausible, and worth a whisper only if nothing better is on offer.
    """

    PLAUSIBLE = "plausible"  # a real seller shaving price — these are the ones that fill
    GHOST = "ghost"          # too good to be true, and measured as such
    THIN = "thin"            # discount is within the reference price's own error

    @property
    def rank(self) -> int:
        return {Band.PLAUSIBLE: 0, Band.THIN: 1, Band.GHOST: 2}[self]


@dataclass(frozen=True)
class Listing:
    """One whisperable Bulk Item Exchange offer.

    `whisper`, `item_whisper` and `pay_whisper` are GGG's own templates, which
    arrive pre-localised to the seller's language. Compose them rather than
    building an English sentence: a Chinese or Korean seller getting a message
    they can read matters more to the response rate than anything we can tune.
    They are present on every online listing and absent on every offline one,
    which is fine because only online listings are ever fetched.
    """

    item_id: str
    account: str
    character: str | None
    pay_amount: float      # units of pay_currency per lot
    get_amount: float      # items received per lot
    stock: float           # units of item_id the seller has
    # What the seller wants paying in. Exalted is the *more* common denomination
    # on this venue (3,502 cached listings against divine's 2,882) and carries
    # 65% more distinct price points, so querying divine alone missed most of
    # the market and all of its price granularity.
    pay_currency: str = "divine"
    indexed: datetime | None = None
    afk: bool = False
    whisper: str | None = None
    item_whisper: str | None = None
    pay_whisper: str | None = None

    @property
    def price_per_unit(self) -> float:
        """Units of `pay_currency` per item. Not comparable across currencies."""
        return self.pay_amount / self.get_amount

    def unit_price_divines(self, pay_unit_divines: float) -> float:
        """Price per item in divines, given what one `pay_currency` is worth."""
        return self.price_per_unit * pay_unit_divines

    def age_s(self, now: datetime | None = None) -> float | None:
        if self.indexed is None:
            return None
        return ((now or datetime.now(timezone.utc)) - self.indexed).total_seconds()


@dataclass(frozen=True)
class TradePlan:
    """The best whole-lot trade against one listing.

    A "lot" is the listing's ratio **in lowest terms**, not the bundle the
    seller advertised — see `smallest_lot`. The plan carries the two divine
    rates it was computed against so a trade can be re-planned at a different
    quantity afterwards without the caller having to remember them.
    """

    lots: int
    units: float             # items received
    pay_units: float         # paid, in the seller's own currency
    cost_divines: float      # divines paid
    proceeds_divines: float  # divines realised, after the floor
    profit_divines: float
    units_value: float       # what `units` is worth before the floor
    # What one unit of each side was worth in divines when this was planned.
    pay_unit_divines: float = 1.0
    sale_unit_divines: float = 1.0

    @property
    def rounding_loss(self) -> float:
        """Divines lost to the integer floor. Large on small trades."""
        return self.units_value - self.proceeds_divines

    @property
    def get_per_lot(self) -> float:
        """Items in one whole-currency lot — the quantity step you can buy in."""
        return self.units / self.lots if self.lots else 0.0


def smallest_lot(pay_amount: float, get_amount: float) -> tuple[float, float]:
    """The listing's ratio in lowest terms: the smallest tradeable quantity.

    A listing advertising "10 Faded Crisis Fragments for 100 divine" is a
    *ratio*, not a bundle — the trade site lets you ask for any quantity along
    it, and sellers answer those asks. Buying the whole advertised lot or
    nothing meant a 100-divine listing was invisible to anyone holding 20
    divines, which is most of the time (reported from the field 2026-07-31).

    The floor on how finely it divides is that partial currency cannot be
    traded: 3 of the 10 above would cost 30 divine, which is whole and fine,
    while a 3-for-7 ratio only divides at 3 and 7. Dividing by the GCD gives
    exactly the smallest step whose price is still a whole number of the
    seller's currency. Non-integer amounts are left alone — GGG's exchange
    quotes whole units, so that case is a malformed response rather than a
    finer market.
    """
    if not (float(pay_amount).is_integer() and float(get_amount).is_integer()):
        return pay_amount, get_amount
    divisor = math.gcd(int(pay_amount), int(get_amount))
    if divisor <= 1:
        return pay_amount, get_amount
    return pay_amount / divisor, get_amount / divisor


def _plan_for_lots(
    lots: int,
    *,
    lot_pay: float,
    lot_get: float,
    ce_divines: float,
    pay_unit_divines: float,
    sale_unit_divines: float,
) -> TradePlan:
    units = lots * lot_get
    raw = units * ce_divines
    proceeds = math.floor(raw / sale_unit_divines) * sale_unit_divines
    return TradePlan(
        lots=lots,
        units=units,
        pay_units=lots * lot_pay,
        cost_divines=lots * lot_pay * pay_unit_divines,
        proceeds_divines=float(proceeds),
        profit_divines=proceeds - lots * lot_pay * pay_unit_divines,
        units_value=raw,
        pay_unit_divines=pay_unit_divines,
        sale_unit_divines=sale_unit_divines,
    )


def plan_trade(
    *,
    pay_amount: float,
    get_amount: float,
    stock: float,
    ce_divines: float,
    pay_unit_divines: float = 1.0,
    sale_unit_divines: float = 1.0,
    bankroll_units: float = 0.0,
) -> TradePlan | None:
    """Best number of whole lots to buy, or None if no quantity profits.

    Everything is accounted in divines, but neither side of the trade is
    denominated in them:

        cost(k)     = k * lot_pay * pay_unit_divines      (exact — listing
                        amounts are whole units of the seller's currency)
        proceeds(k) = floor(k * lot_get * ce_divines / sale_unit_divines)
                        * sale_unit_divines

    `lot_pay` and `lot_get` are the listing's ratio in lowest terms rather than
    the amounts it advertises — see `smallest_lot`.

    `sale_unit_divines` is what one unit of the currency you settle in is worth.
    It is the single most consequential number here. Selling the same item for
    divines floors to whole divines; selling for exalted floors to ~1/432 of
    one. On the trade that actually filled — 1 Core Destabiliser at 2 divines
    against a 3.79 CE rate — that is the difference between 1.00 and 1.79
    profit. Defaults to 1.0 (settle in divines) because that is the pessimistic
    reading, and understating profit is the safe direction to be wrong in.

    `bankroll_units` is how much of the *seller's* currency you hold — not a
    divine total. A seller wanting exalted can only be paid in exalted, and
    converting divines to exalted on the CE costs the spread, so a pooled
    divine figure would promise quantities you cannot actually buy. 0 means
    unbounded — and it caps the *quantity asked for* rather than dropping the
    listing, which is what makes a 100-divine listing usable on a 20-divine
    bankroll.

    Searched rather than solved analytically because the floor makes profit
    non-monotonic in k: with a 3.79 rate and a 3.5 cost, successive lots add 3
    or 4 divines alternately, so the largest affordable k is not always the best
    one. Only the tail of the range is searched — see `_WINDOW` below.
    """
    if pay_amount <= 0 or get_amount <= 0 or ce_divines <= 0 or stock <= 0:
        return None
    if pay_unit_divines <= 0 or sale_unit_divines <= 0:
        return None
    lot_pay, lot_get = smallest_lot(pay_amount, get_amount)
    lot_cost = lot_pay * pay_unit_divines
    # Sell value of one lot must exceed its cost, or no k can profit: proceeds
    # are floored, so they never exceed k * lot_get * ce_divines.
    gain = lot_get * ce_divines - lot_cost
    if gain <= 0:
        return None

    max_by_stock = int(stock // lot_get)
    if bankroll_units > 0:
        max_by_bankroll = int(bankroll_units // lot_pay)
    else:
        max_by_bankroll = MAX_LOTS
    k_max = min(max_by_stock, max_by_bankroll, MAX_LOTS)
    if k_max < 1:
        return None

    # profit(k) lies in (k*gain - sale_unit, k*gain], so any k more than
    # sale_unit/gain lots below k_max is strictly worse than k_max and needn't
    # be tried. Without this, reducing the ratio to lowest terms would turn a
    # handful of iterations per listing into thousands.
    window = min(k_max, math.ceil(sale_unit_divines / gain) + 1)
    best: TradePlan | None = None
    for k in range(k_max - window + 1, k_max + 1):
        plan = _plan_for_lots(
            k,
            lot_pay=lot_pay,
            lot_get=lot_get,
            ce_divines=ce_divines,
            pay_unit_divines=pay_unit_divines,
            sale_unit_divines=sale_unit_divines,
        )
        if best is None or plan.profit_divines > best.profit_divines:
            best = plan
    if best is None or best.profit_divines <= 0:
        return None
    return best


@dataclass(frozen=True)
class Candidate:
    """A listing, its CE reference price, and the trade we'd actually make."""

    listing: Listing
    item_name: str
    ce_divines: float
    plan: TradePlan
    band: Band
    # Listing price per item in divines. Stored rather than derived because
    # `Listing.price_per_unit` is in the seller's currency, and a sweep mixes
    # divine- and exalted-priced listings in one table.
    unit_price_divines: float = 0.0
    # What the resale is settled in. Carried on the candidate rather than looked
    # up from the config at display time because it is an *input* to
    # `plan.profit_divines` — the floor is a whole unit of this — so a row must
    # be able to say which currency its own profit figure was computed against,
    # even after the setting has since been changed.
    settle_currency: str = UNIT_CURRENCY

    @property
    def key(self) -> tuple:
        """Stable identity for this offer, for tracking what's been whispered.

        Content-derived on purpose. Python object identity is not usable here:
        a candidate stored in a Qt item and read back is not guaranteed to be
        the same object, so `id()` silently fails to match and the queue
        re-offers listings that were already messaged.

        The exchange gives listings no id that survives a re-fetch, so this is
        also what `recheck` matches on: same seller, same price, same
        denomination is the same trade; anything else is a different one.
        """
        return (
            self.listing.item_id,
            self.listing.account,
            self.listing.pay_currency,
            self.listing.pay_amount,
            self.listing.get_amount,
        )

    @property
    def gap(self) -> float:
        """CE price divided by listing price. 1.2 means 20% under market."""
        return self.ce_divines / self.unit_price_divines

    @property
    def profit_divines(self) -> float:
        return self.plan.profit_divines

    @property
    def pay_total(self) -> float:
        """What the whisper offers, in the seller's own currency.

        The number the user has to recognise when a reply arrives — often hours
        later, often in a language they don't read. `plan.cost_divines` is the
        same money in a different unit, and showing only that meant a listing
        whispered as "2412 exalted" appeared on screen as "5.6 div", which is
        unrecognisable as the offer that was made.
        """
        return self.plan.pay_units

    @property
    def pay_per_unit(self) -> float:
        """Per-item price in the seller's currency, to match `pay_total`.

        Read off the **plan** rather than the listing, so a trade amended to a
        counteroffered price reports the price actually agreed. The two are the
        same number on an unamended plan — `pay_units / units` reduces to
        `lot_pay / lot_get`, which is the listing's own ratio in lowest terms.
        """
        if self.plan.units > 0:
            return self.plan.pay_units / self.plan.units
        return self.listing.price_per_unit

    @property
    def affordable(self) -> bool:
        return self.plan.lots >= 1


def replan_units(candidate: Candidate, units: float) -> Candidate:
    """The same listing bought at a different quantity, rounded to a whole lot.

    For correcting a trade after the fact. A whisper asking for 18 is answered
    with "I've only got 3", or the seller turns out to hold one of the two they
    advertised — and until that correction can be made, the outcome log records
    a trade that never happened at a profit nobody earned, which is the one
    thing this file's numbers are meant to be good for.

    Deliberately **not** re-optimised: the user is reporting what they bought,
    so the quantity is taken as given even where a different one would have paid
    better. Clamped to at least one lot and at most what the plan originally
    asked for — a correction can only ever shrink a trade, since the extra was
    never on offer.
    """
    plan = candidate.plan
    lot_get = plan.get_per_lot
    if lot_get <= 0:
        return candidate
    lots = max(1, min(plan.lots, round(units / lot_get)))
    if lots == plan.lots:
        return candidate
    return dataclasses.replace(
        candidate,
        plan=_plan_for_lots(
            lots,
            lot_pay=plan.pay_units / plan.lots,
            lot_get=lot_get,
            ce_divines=candidate.ce_divines,
            pay_unit_divines=plan.pay_unit_divines,
            sale_unit_divines=plan.sale_unit_divines,
        ),
    )


def repriced(candidate: Candidate, pay_units: float) -> Candidate:
    """The same quantity at a different total price — a counteroffer.

    Measured 2026-08-01 against `Client.txt`: **35 of 36 fills went through at
    the listed price**, so this is rare and the worry that the ranking rested on
    negotiated prices is closed. The one that was counteroffered is why this
    exists anyway — it logged +38.00 divines on a trade that lost money, because
    the app could record a changed *quantity* and not a changed *price*.

    Deliberately **not** clamped the way `replan_units` is. A correction to the
    quantity can only ever shrink a trade, since the extra was never on offer; a
    correction to the price usually moves it the other way, because a seller who
    counteroffers is asking for more. Nothing here re-optimises either: the user
    is reporting what they paid.

    Only `pay_units` is given, because the proceeds are a fact about the
    quantity and the Currency Exchange rather than about what the seller
    charged. Profit is therefore free to come out negative, and every display of
    it has to be able to say so — see `format.fmt_profit`.
    """
    plan = candidate.plan
    if pay_units <= 0 or plan.units <= 0 or pay_units == plan.pay_units:
        return candidate
    cost = pay_units * plan.pay_unit_divines
    return dataclasses.replace(
        candidate,
        plan=dataclasses.replace(
            plan,
            pay_units=pay_units,
            cost_divines=cost,
            profit_divines=plan.proceeds_divines - cost,
        ),
        # The row has to stay self-consistent: gap is derived from this, and a
        # gap quoting the advertised price beside a total showing the negotiated
        # one is how the log came to disagree with itself in the first place.
        # The *logged* attempt keeps the whispered gap — an amendment record
        # carries no gap — because that is the feature the ranking is fitted on.
        unit_price_divines=cost / plan.units,
    )


def classify(gap: float, *, min_gap: float, max_gap: float) -> Band:
    if gap > max_gap:
        return Band.GHOST
    if gap < min_gap:
        return Band.THIN
    return Band.PLAUSIBLE


def build_candidates(
    listings: list[Listing],
    ce_price: dict[str, float],
    names: dict[str, str],
    *,
    min_gap: float,
    max_gap: float,
    bankroll: dict[str, float] | None = None,
    sale_unit_divines: float = 1.0,
    settle_currency: str = UNIT_CURRENCY,
    min_profit_divines: float = 0.0,
) -> list[Candidate]:
    """Price every listing against the CE and keep the ones worth a whisper.

    Listings for items with no CE price are dropped rather than assumed
    worthless: an unpriced item is one we cannot value, not one worth nothing.
    The same applies to the *pay* currency — a listing wanting something we
    cannot value cannot be costed, so it is skipped rather than guessed at.

    `min_profit_divines` exists because settling in exalted makes tiny trades
    arithmetically profitable. A candidate worth +0.02 divines is real and still
    not worth the message; the floor no longer filters those out, so something
    has to.

    `bankroll` maps currency id to how many of that currency you hold. A
    currency absent from it is unconstrained — you are assumed to have enough
    for anything the seller asks. That is the right default: capping a currency
    you never told the app about would silently hide trades.
    """
    bankroll = bankroll or {}
    out: list[Candidate] = []
    for listing in listings:
        ce = ce_price.get(listing.item_id)
        pay_unit = ce_price.get(listing.pay_currency)
        if pay_unit is None and listing.pay_currency == UNIT_CURRENCY:
            pay_unit = 1.0  # divine is the unit of account, by definition
        if not ce or ce <= 0 or not pay_unit or pay_unit <= 0:
            continue
        plan = plan_trade(
            pay_amount=listing.pay_amount,
            get_amount=listing.get_amount,
            stock=listing.stock,
            ce_divines=ce,
            pay_unit_divines=pay_unit,
            sale_unit_divines=sale_unit_divines,
            bankroll_units=bankroll.get(listing.pay_currency, 0.0),
        )
        if plan is None or plan.profit_divines < min_profit_divines:
            continue
        unit_price = listing.unit_price_divines(pay_unit)
        gap = ce / unit_price
        out.append(
            Candidate(
                listing=listing,
                item_name=names.get(listing.item_id, listing.item_id),
                ce_divines=ce,
                plan=plan,
                band=classify(gap, min_gap=min_gap, max_gap=max_gap),
                unit_price_divines=unit_price,
                settle_currency=settle_currency,
            )
        )
    return out


# How much of a band's profit to believe when ranking. Relative weights, not
# probabilities — do not quote them as fill rates.
#
# **Fitted 2026-08-01 from 789 logged whispers**, replacing three round numbers
# that came from 14. Ghosts fill at 2.16% (n=601) against plausible's 12.4%
# (n=178): a ratio of **0.17**, which is what GHOST now carries.
#
# *Revised the same day, by one trade.* The Rigwald's Ferocity record — a
# 137.86x ghost, the biggest the project has found — was sitting as `no_reply`
# because the pre-0.8.0 timer wrote a verdict over it; the maintainer confirmed
# it filled at the listed price. Ghost fills go 12 -> 13 and the prior 0.162 ->
# 0.175. **The prior barely moves and the value ratio doubles**: ghost value per
# whisper goes 0.251 -> 0.477 divines against plausible's 0.382, so a ghost
# whisper is now worth *more* per message than a plausible one (ratio 1.25, was
# 0.66). That does not change what this table holds — see below — and it rests
# on a single observation worth 47% of all ghost realised value, so it is a
# reason to keep measuring rather than to re-weight.
#
# *Why the fill-rate ratio and not the value-per-whisper ratio (0.66).* This
# weight multiplies a candidate's **profit**, so `profit x weight` is already an
# estimate of divines per whisper — the objective the ranking wants to maximise.
# Feeding it the value ratio would apply the fat tail twice, since a ghost's
# value per whisper is high *because* its profit is large. The consequence is
# deliberate and worth stating: a 39-div ghost now scores 6.3 and outranks a
# 3-div plausible, because 2.0% x 39 really does beat 12.4% x 3. Ghosts are no
# longer pinned to the bottom by a 0.0 they were never worth.
#
# THIN stays 0.5 and stays a guess: n=10, under `outcomes.MIN_SAMPLES`, and its
# raw 20% fill rate would imply a weight above 1.0, which is obviously an
# artefact of two fills.
#
# Full tables in docs/FINDINGS.md, "Negative results" 1.
FILL_PRIOR = {
    Band.PLAUSIBLE: 1.0,
    Band.THIN: 0.5,
    Band.GHOST: 0.17,
}

# A listing this old has never once been traded: 0 fills in 102 whispers, and
# the oldest listing that ever filled was 62.9 hours (2.62 days). Measured
# 2026-08-01 over all 789 logged attempts; P(0 fills in 102) at the 4.56% base
# rate is ~0.008, and it holds in both large bands separately, so it is age
# rather than gap. Full table in docs/FINDINGS.md, "A listing older than ~3 days
# has never filled".
#
# A **cliff, not a decay curve.** Below three days age barely predicts anything
# (6.4% -> 3.1% -> 7.4%, non-monotonic), so do not turn this into a continuous
# freshness discount — there is no evidence for the shape it would need.
STALE_LISTING_S = 3 * 24 * 60 * 60


def fill_weight(band: Band, risk_appetite: float) -> float:
    """How much of a band's profit to believe, at a given risk appetite.

    At 0 the priors apply in full, so ghosts score nothing and sink. At 1 they
    are flattened away entirely and ranking is pure expected profit — which is
    what someone chasing the rare 12x listing actually wants. In between, the
    long shots climb gradually rather than appearing all at once.
    """
    appetite = min(1.0, max(0.0, risk_appetite))
    prior = FILL_PRIOR.get(band, 0.0)
    return prior + appetite * (1.0 - prior)


def is_stale(candidate: Candidate, now: datetime | None = None) -> bool:
    """Has this listing sat unsold past the age at which nothing ever fills?

    Unknown age counts as fresh. `indexed` is absent on some responses, and a
    missing timestamp is not evidence of abandonment.
    """
    age = candidate.listing.age_s(now)
    return age is not None and age >= STALE_LISTING_S


def rank_candidates(
    candidates: list[Candidate],
    *,
    risk_appetite: float = 0.0,
    now: datetime | None = None,
) -> list[Candidate]:
    """Whisper order, by profit discounted for how likely it is to fill.

    Two discounts, in order. **Stale listings sort below everything fresh**,
    whatever their band or profit — three days without a sale is the one signal
    in the log that predicts a flat zero, so a stale plausible is worth less
    than a fresh ghost. Within that, profit is weighted by `FILL_PRIOR`.

    Nothing is hidden. A user who wants to test a 12x listing, or a listing that
    has sat for a week, should be able to find it — just not be led to it first.
    Hiding either would make the ranking unfalsifiable, which is how the 0.0
    ghost prior survived four field tests.

    Sorted on explicit tiebreaks down to the account name so the order is stable
    between runs; anything derived from set or dict iteration would reshuffle,
    since Python randomises string hashing per process. `now` is injected for
    the same reason the clocks elsewhere are: a sort must not read the wall
    clock per comparison.
    """
    at = now or datetime.now(timezone.utc)
    return sorted(
        candidates,
        key=lambda c: (
            is_stale(c, at),
            -c.profit_divines * fill_weight(c.band, risk_appetite),
            c.band.rank,
            -c.profit_divines,
            c.gap,
            c.item_name,
            c.listing.account,
        ),
    )


def _fmt_qty(value: float) -> str:
    """Whole numbers without a trailing .0 — these go into a chat message."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def whisper_text(candidate: Candidate) -> str | None:
    """Compose GGG's localised whisper for the planned quantity.

    `{0}` in the listing template is what you receive, `{1}` what you pay; each
    of those is itself a template taking the quantity. Returns None when the
    listing predates the fields (offline listings carry none of them), so the
    caller can disable the copy action rather than paste a broken message.

    The paid amount is in the **seller's** currency — `plan.pay_units` — not
    `plan.cost_divines`. Those coincide only when the listing is priced in
    divines, so using the divine figure produced messages offering 5.58 exalted
    for something listed at 2412.
    """
    listing = candidate.listing
    if not (listing.whisper and listing.item_whisper and listing.pay_whisper):
        return None
    plan = candidate.plan
    buying = listing.item_whisper.replace("{0}", _fmt_qty(plan.units))
    paying = listing.pay_whisper.replace("{0}", _fmt_qty(plan.pay_units))
    return listing.whisper.replace("{0}", buying).replace("{1}", paying)
