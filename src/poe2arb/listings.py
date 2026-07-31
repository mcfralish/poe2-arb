"""Cross-venue candidates: Bulk Item Exchange listings priced against the CE.

The trade is: buy an underpriced listing by whisper on the Bulk Item Exchange,
sell into the in-game Currency Exchange. Two field tests (docs/FINDINGS.md,
"Negative results") shape everything here:

1. **Deep discounts fill rarely, not never.** Corrected 2026-07-31 from 156
   logged whispers; the earlier claim, from n=14 with ~10 large-gap attempts,
   was that they never fill at all. Measured: plausible 21% (n=24), ghost
   **2.3%** (n=131) — with fills at 3.92x and 10.94x, gaps the old reading
   called uncatchable. Large gaps are still *demoted*, because plausible
   returns ~3.5x more **per whisper sent** (0.40 div against 0.113), and
   `GHOST` still keeps them visible rather than hidden. They are not worthless
   though: ghosts earned 71% of the one profitable session's divines, because
   the rare fill is a large one. See `FILL_PRIOR`, whose 0.0 for ghosts is the
   part now known to be wrong.

2. **Partial currency cannot be traded, so the settlement currency decides the
   haircut.** A 3.79 CE rate pays 3 if you take divines and 1636 exalted — 3.789
   divines — if you take exalted, because exalted is ~432x finer. Measured on
   the one trade that filled, settling in exalted turns a 1.00 divine profit
   into 1.79. Profit is therefore floored to `sale_unit_divines`, never to a
   whole divine and never left unfloored.

`max_gap_ratio` is now supported by the log — the fill-rate cliff sits between
1.5x and 2x, where it already is. `min_gap_ratio` is not: only 2 whispers have
ever been sent below 1.10x, and it is entangled with the reference price's own
~26% error on thin items, so the two have to be fitted together or not at all.
"""

from __future__ import annotations

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
    """The best whole-lot trade against one listing."""

    lots: int
    units: float             # items received
    cost_divines: float      # divines paid
    proceeds_divines: float  # divines realised, after the floor
    profit_divines: float
    units_value: float       # what `units` is worth before the floor

    @property
    def rounding_loss(self) -> float:
        """Divines lost to the integer floor. Large on small trades."""
        return self.units_value - self.proceeds_divines


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

        cost(k)     = k * pay_amount * pay_unit_divines      (exact — listing
                        amounts are whole units of the seller's currency)
        proceeds(k) = floor(k * get_amount * ce_divines / sale_unit_divines)
                        * sale_unit_divines

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
    unbounded. Iterating rather than solving
    analytically because the floor makes profit non-monotonic in k: with a
    3.79 rate and a 3.5 cost, successive lots add 3 or 4 divines alternately,
    so the largest affordable k is not always the best one.
    """
    if pay_amount <= 0 or get_amount <= 0 or ce_divines <= 0 or stock <= 0:
        return None
    if pay_unit_divines <= 0 or sale_unit_divines <= 0:
        return None
    lot_cost = pay_amount * pay_unit_divines
    # Sell value of one lot must exceed its cost, or no k can profit: proceeds
    # are floored, so they never exceed k * get_amount * ce_divines.
    if get_amount * ce_divines <= lot_cost:
        return None

    max_by_stock = int(stock // get_amount)
    if bankroll_units > 0:
        max_by_bankroll = int(bankroll_units // pay_amount)
    else:
        max_by_bankroll = MAX_LOTS
    k_max = min(max_by_stock, max_by_bankroll, MAX_LOTS)
    if k_max < 1:
        return None

    best: TradePlan | None = None
    for k in range(1, k_max + 1):
        units = k * get_amount
        raw = units * ce_divines
        proceeds = math.floor(raw / sale_unit_divines) * sale_unit_divines
        profit = proceeds - k * lot_cost
        if best is None or profit > best.profit_divines:
            best = TradePlan(
                lots=k,
                units=units,
                cost_divines=k * lot_cost,
                proceeds_divines=float(proceeds),
                profit_divines=profit,
                units_value=raw,
            )
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
        return self.plan.lots * self.listing.pay_amount

    @property
    def pay_per_unit(self) -> float:
        """Per-item price in the seller's currency, to match `pay_total`."""
        return self.listing.price_per_unit

    @property
    def affordable(self) -> bool:
        return self.plan.lots >= 1


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
# **Known wrong and not yet fixed (2026-07-31).** These three round numbers came
# from 14 whispers. The log now holds 156, and says ghosts fill at 2.3% against
# plausible's 21% — a ratio of ~0.11 on fill rate, or ~0.28 on divines per
# whisper sent, which is the quantity this actually weights. Either way it is
# not 0.0: ghosts earned 71% of the one profitable session's take. Thin is still
# n=1 and uncallable.
#
# Deliberately left alone until fitted properly rather than nudged to a guess —
# see TODO.md, "Fit the ranking to the outcome log", which also has to decide
# which of the two ratios `fill_weight` is meant to express.
FILL_PRIOR = {
    Band.PLAUSIBLE: 1.0,
    Band.THIN: 0.5,
    Band.GHOST: 0.0,
}


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


def rank_candidates(
    candidates: list[Candidate], *, risk_appetite: float = 0.0
) -> list[Candidate]:
    """Whisper order, by profit discounted for how likely the band is to fill.

    Ghosts sort to the bottom rather than being hidden. They are the visible
    evidence for why the ranking works this way, and a user who wants to test a
    12x listing should be able to find it — at appetite 0, just not be led to
    it first.

    Sorted on explicit tiebreaks down to the account name so the order is stable
    between runs; anything derived from set or dict iteration would reshuffle,
    since Python randomises string hashing per process.
    """
    return sorted(
        candidates,
        key=lambda c: (
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

    The paid amount is in the **seller's** currency — `lots * pay_amount` — not
    `plan.cost_divines`. Those coincide only when the listing is priced in
    divines, so using the divine figure produced messages offering 5.58 exalted
    for something listed at 2412.
    """
    listing = candidate.listing
    if not (listing.whisper and listing.item_whisper and listing.pay_whisper):
        return None
    plan = candidate.plan
    buying = listing.item_whisper.replace("{0}", _fmt_qty(plan.units))
    paying = listing.pay_whisper.replace("{0}", _fmt_qty(plan.lots * listing.pay_amount))
    return listing.whisper.replace("{0}", buying).replace("{1}", paying)
