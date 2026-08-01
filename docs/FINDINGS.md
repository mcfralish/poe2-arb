# Measured findings and standing decisions

Expensive knowledge: things established by measurement that must not be re-derived,
and choices that look like oversights but are deliberate. Read the relevant section
before changing that subsystem. Open work is in [TODO.md](../TODO.md).

---

## The two markets

PoE2 has **two currency economies that do not share prices.**

| | Currency Exchange | Bulk Item Exchange |
|---|---|---|
| where | in game | `trade2/exchange`, site's "Bulk Item Exchange" tab |
| mechanism | pooled, automated | player listings, whisper + party |
| works offline? | yes | no |
| spread | ~1% on a liquid pair (3.75 / 3.79, Core Destabiliser) — **but see below** | meaningless |
| depth | millions of units | single digits |
| who uses it | effectively everyone | effectively nobody |

**The spread is now measured on more than one item, and it is tight.** Read 2026-08-01
from both sides of the in-game book: **2.1%** on Faded Crisis Fragment, **2.25%** on Omen
of Whittling, against **1.7%** on the Divine↔Exalted control. So the whole edge — "buy on
Bulk, resell into the CE" — does survive contact with the book on items in the ~1M+
`ValueTraded` range, and the ~26% shortfall measured on two real trades on 2026-07-30 is
**not** spread. See "The reference price does not match what a sale realises", whose
2026-08-01 subsection settles this and reassigns the cause to price movement. Still
unmeasured, and the one place the old worry may survive: genuinely thin pairs around 100k
`ValueTraded`, where nothing has been read off the book.

**`POST /api/trade2/exchange/{league}` serves the abandoned one.** The pooled book is
not exposed on it at all. Three structural proofs:

- **The reverse direction is empty.** `want=divine, have=core-destabiliser` returns
  `total=0` where the game shows 1,110 depth. Same for `want=divine, have=chaos`, the
  deepest pair in the game.
- **Prices are integers.** Every listing is `pay N : get 1` — it can express 3, 4, 5,
  10, 55 divine per Core Destabiliser; it cannot express 3.79.
- **Depth is off by 10³.** Game stock 1,110 / 4,662 / 13,035 versus 1, 2, 3, 10.

Ruled out: pagination (all 272 cached divine/core-destabiliser offers were 1:1 at every
page), the `engine: new` flag, and the realm-qualified URL
`/api/trade2/exchange/poe2/{league}` (byte-identical response).

**Always send `status: online`.** Without it 96% of results are dead listings, and GGG's
best-ratio-first ordering fills page 1 with 1:1 junk:

```
want=core-destabiliser have=divine
  no status filter   total=252, all 100 fetched are 1:1
  + status:online    total=11,  ratios 1, 3, 4, 5, 10, 20, 25, 40, 50, 55
```

98% of unfiltered listings are offline and 74% over a week old. Offline listings carry no
`whisper` or `lastCharacterName` field, so they are unwhisperable anyway.

## The two price sources

Measured 2026-07-29 in Runes of Aldur, matched leagues:

- poe.ninja prices **all 637** catalogue items; poe2scout prices **226** of them.
- Where both have a price they agree to a **median 3.3%** — 1.4% above 100k traded, 0.8%
  above 1M. They are not in conflict.
- poe2scout adds no item poe.ninja lacks, so it can never be a full replacement.

The app prefers the CE price where it exists and falls back to poe.ninja, via
`Universe.with_ce_prices`. `ce_priced` records which is which, and the Market status line
and Quick Lookup both say so — silently swapping the meaning of a displayed number is
worse than either source alone.

**Beware comparing across leagues.** An earlier pass read poe2scout for Standard against
poe.ninja for the temp league and produced a median disagreement of 90% with individual
items 30× apart — entirely an artefact. Standard has years of accumulated currency.
Always pass the same league to both.

### poe2scout API

`https://api.poe2scout.com` — public REST, no OAuth, not on GGG's rate limiter. Spec at
`/openapi/v1.json`, Swagger at `/swagger`. Realm `poe2`.

```
GET /{realm}/Leagues/{leagueName}/SnapshotPairs    ~1,545 pairs, ~2 MB
```

**Exactly one derivation is verified:** `item.RelativePrice / divine.RelativePrice`, from
a pair where both sides have real traded value. Against in-game screenshots: −0.4%,
−0.7%, −1.7%, −1.0%, −4.7% across five items, versus poe.ninja's −5.2% to +9.0%. Every
error is slightly negative, consistent with a volume-weighted traded price rather than
best-of-book — which is the better estimate of what a sale realises anyway.

Everything else about this API was tested and is untrustworthy:

- `RelativePrice` is **not** a price in the base currency. Exalted's own value should be
  1.0; the median is 1.185, and gating to high volume makes it *worse* (1.258). Deriving
  via exalted pairs disagrees with the divine derivation by a median of **49.6%** — and
  the divine one is what matches the game.
- Treating `RelativePrice` as base-denominated across all pairs gives −4% to −11.5%
  errors and a 1.51× median spread within a single item, for 12% more coverage. Not worth it.
- **Thin pairs are noise.** A pair with 1–5 lifetime trades prices items 25× wrong.
  `MIN_PAIR_VALUE` exists for exactly this.
- **No bid, no ask, no depth anywhere in this API.** CE order-book arbitrage is not
  detectable from it by anyone.
- **No triangular arbitrage inside the CE.** 3-cycle products sit at a median of exactly
  1.0000 at every volume gate with a symmetric tail — the signature of noise in an
  averaged statistic, not arbitrage. The apparent 10× cycles all ran through pairs with
  1–5 lifetime trades.

`value_traded` is used for **ranking only** — the same unit for every item, so "which
items trade" is answerable even though "how many divines" is not.

### The reference price does not match what a sale realises — measured on two real losses, revised 2026-08-01

> **Read the 2026-08-01 subsection at the end before acting on this one.** The ~26%
> overstatement below is real and measured, but it did **not** reproduce two days later,
> and the spread explanation offered for it has since been disproved directly. The heading
> used to read "overstates thin items by ~26%"; it was renamed because that framing was
> load-bearing in two other files and is now known to be too general.

**Measured 2026-07-30, Runes of Aldur, on the first two trades ever completed through the
app. Both lost money.** This is the most consequential finding in this file: the derivation
above is sound, and it is still not the number a sale realises.

| item | app showed | poe2scout published | live CE at trade time | app over live |
|---|---|---|---|---|
| Omen of Whittling | 4,605 ex | 4,436–4,573 ex (07-29) | **3,361 ex** | **+37%** |
| Astrid's Creativity | 1,156 ex | 926–994 ex (07-29) | **700 ex** | **+65%** |

Re-measured against the live API on 2026-07-30 with the app's own parser: Whittling 4,547
ex, Astrid's 993 ex.

Three things follow, and the second is the one that matters:

1. **The app is not misparsing poe2scout.** `rel/base` reproduces poe2scout's own published
   `CurrentPrice` to **1.006×** (Whittling) and **1.110×** (Astrid's). Do not go looking for
   a conversion bug — there isn't one. The pipeline faithfully reports its source.
2. **The source itself sits ~26–27% above what the CE actually pays for a thin item.**
   poe2scout's price never went near 3,361 or 700 at any point in 07-28 → 07-30
   (Whittling 4,304→4,518; Astrid's 953→895), so this is a *level* difference, not
   staleness. Most likely we quote a traded/mid price while a seller crossing the spread
   receives the bid — consistent with this file's own "no bid, no ask, no depth anywhere in
   this API". On a thin item that spread is wide enough to eat the entire edge.
3. **Liquidity is the discriminator, not the method.** The five items that validated at
   −0.4% to −4.7% were liquid currency. These two are not: Astrid's trades ~130–240 units
   a day and its divine pair carries 67k `ValueTraded` — barely above `MIN_PAIR_VALUE`'s
   1,000. The reference price is trustworthy for liquid currency and optimistic for
   everything else, which is exactly the half of the universe the sweep selects for.

**`min_gap_ratio = 1.05` is therefore calibrated an order of magnitude too tight.** It
encodes a 5% price error derived from liquid currency, against a measured 26% error on the
items actually being traded. A 1.2× gap on a thin item is not a 20% edge; it is inside the
noise, and the app presented two such trades as profitable. `MIN_PAIR_VALUE = 1000` is also
far too low — Astrid's cleared it by 67× and was still 65% wrong.

#### Resolved 2026-08-01: the book is tight, and the error is movement — not spread

**The fork above is settled, and it is not the branch this section assumed.** The maintainer
read both sides of the in-game Currency Exchange book while the app's own snapshot was
pulled minutes later. In-game quotes are "I want : I have"; the first row of each pair is
what you **pay** to buy, the second what you **receive** to sell.

| item | in-game buy | in-game sell | **book spread** | app (poe2scout) | app vs sell | pair `ValueTraded` |
|---|---|---|---|---|---|---|
| Faded Crisis Fragment | 9.5 div | 9.3 div | **2.1%** | 8.754 div | **−5.9%** (low) | 1.60M |
| Omen of Whittling | 10.33 div | 10.10 div | **2.25%** | 10.760 div | **+6.5%** (high) | 10.0M |
| Divine ↔ Exalted *(control)* | 407 ex | 400 ex | **1.7%** | — | — | — |

Three things follow, and they overturn point 2 above:

1. **Spread is not the explanation.** The book is ~2% wide on these items — barely wider
   than the liquid-currency control at 1.7%, and nowhere near 26%. A haircut scaled by
   liquidity would be correcting for something that is not there. **Do not build it.**
2. **The error is not systematic, and not one-directional.** Two items measured minutes
   apart came out **−5.9% and +6.5%** — opposite signs. "The reference price overstates"
   is the wrong shape for this; it is *noise about the mid*, roughly ±6% at this liquidity.
3. **The 26% did not reproduce.** Omen of Whittling was +37% on 07-30 and is +6.5% today,
   same item, same derivation, same parser. A level difference that vanishes in two days
   is **movement**, not level. So the fix is **freshness** — show the price's age, and
   distrust a stale one — which is the cheapest of the three branches this file was
   holding open.

#### The maintainer attributes the original losses to user error — partly supported

Recorded 2026-08-01, in the maintainer's words: the RuinousLuck loss was "user error +
ambiguous naming" — the `Buy / Each / Cost` columns misread — and the Omen of Whittling and
Astrid's Creativity losses are chalked up to the same thing. Since the last day of use has
produced **only successful trades**, the app's own arithmetic is not the suspect it was.

**This is very likely right about the losses and does not account for the price table.**
Keeping both on the record, because the distinction changes what gets built:

- *It explains the losses.* Misreading a lot quantity ("5 for 5 div" read as "1 for 5 div")
  changes what you believe you are paying per unit, which is exactly how a trade at a fair
  price feels like a loss. Confirmed on RuinousLuck from `Client.txt`. **This is the
  strongest argument for the column renames** in the UI section — they are not cosmetic.
- *It does not explain the 07-30 numbers.* That table compares **two prices** — the app's
  CE figure against an in-game CE reading — and a misread quantity moves neither. Nor can
  reading the wrong side of the book: the book is ~2% wide, and the gaps were 37% and 65%.
  Whatever produced 3,361 against 4,605 was a different price *level*, not a different
  column and not a different side.
- *So the cause of the price gap is still movement*, which is what the 2026-08-01 readings
  independently support, and what the freshness work is aimed at. **Do not delete the
  07-30 table on the strength of the attribution** — if it was a bad in-game reading rather
  than a real 37% move, the thing that establishes that is the missing Astrid's measurement
  below, not a recollection.

**What this does *not* settle.** Both items measured are liquid: Omen of Whittling carries
the highest `ValueTraded` in the sample at 10.0M. **Astrid's Creativity — the 110k item that
was 65% wrong — was not re-measured**, and it is the only genuinely thin case the project
has ever had. The tight-book result is established for ~1M+ pairs and **assumed, not
measured, below that**. Get an Astrid's reading before concluding that thin items behave
like liquid ones.

**`min_gap_ratio = 1.05` is still wrong, for a new reason.** The old argument was that 5%
is tight against a 26% bias. The measurement replaces it with a better one: the reference
price carries **±6% of noise**, so a 1.05 threshold selects trades whose entire edge is
smaller than the error bar on the number that found them. That is not a bias to subtract —
it is a floor below which a gap means nothing. The conclusion survives; the reasoning
behind it has changed completely, and the constant should be set from the noise, not from
a haircut.

### Gold is a real constraint and the app does not model it

**Measured 2026-07-30 in game:** the Currency Exchange charges roughly **120 gold per
exalted** and **800 gold per divine** traded. The maintainer ran out of gold mid-session
settling a high-value item in exalted.

**Confirmed flat, 2026-08-01.** The open question was whether those rates held across price
points or scaled with trade size; the maintainer reports they are **static** — 120/ex and
800/div when liquidating, whatever the quantity. So the gold bill is a plain multiplication
of units settled, and the recommendation in TODO needs no rate table, only the gold on hand.

This **directly opposes** the denomination finding below. Exalted minimises the rounding
floor, and it also multiplies the gold cost: settling ~3,000 exalted costs ~360,000 gold,
where the same value as ~7 divine costs ~5,600 gold — **64× more gold for the finer floor.**
"Settle in exalted" is therefore correct only while gold lasts, and the app currently
recommends it unconditionally with no notion that gold exists.

Gold cannot be bought for currency, so it is a **budget constraint, not a cost in divines**:
the right rule is the finest denomination whose gold cost fits the gold you hold, not a
term subtracted from profit.

## Which items to sweep

Selection is **CE exit liquidity**: an underpriced listing is worthless if the Exchange
won't absorb the item afterwards. Rank by `ValueTraded`, gate on value.

```
value >= 2 div AND CE volume >= 100k  ->  65 items, ~14 min/sweep
   top 25 -> 5.4 min, 84.7% of candidate CE volume
```

Comfortably inside the observed churn window. **Only 5 of the 65 are currency** — the
bulk is Lineage Support Gems, Fragments, Ritual omens and Abyss. The app spent its first
eight versions scanning ten currency items, which is close to exactly the wrong place.

## Negative results

**1. Deep discounts fill rarely, not never — and they still earned most of the money.**

**Superseded twice. Current reading is 2026-08-01 at n=789**, five times the sample the
last revision had. The two earlier readings are kept because the size of each correction is
the point:

> At n=14 (2 fills, both at the smallest gaps sampled, ~10 attempts at 3.8×–12.5× producing
> zero): *"Deep discounts do not fill. A listing far below market is a mistake, an
> abandonment, or already sold — its continued visibility is evidence it cannot be taken."*

> At n=156 (2026-07-31): plausible 24 whispers / 21% fill / **0.40 div per whisper**; ghost
> 131 whispers / 2.3% fill / **0.113 div per whisper**; ratio ~0.28 on value per whisper.
> "Ghosts fill rarely but are worth roughly a quarter of a plausible whisper."

**Both were under-sampled, and both under-rated ghosts.** Every whisper the app has ever
sent is logged. All 789 attempts in `outcomes.jsonl` carry a resolved outcome, and the log
now reads:

| band | whispers | filled | fill rate | sold | exp. profit (div) | **div per whisper** |
|---|---|---|---|---|---|---|
| plausible | 178 | 22 | **12.4%** | 5 | 68.0 | **0.382** |
| thin | 10 | 2 | 20% (n=10) | 1 | 2.0 | 0.200 |
| ghost | 601 | 13 | **2.16%** | 2 | 286.7 | **0.477** |

> **Revised later the same day, by one trade, and the direction is the same one as every
> other revision of this finding.** The ghost row above read 12 fills / 2.0% / 150.7 div /
> 0.251 per whisper until the **Rigwald's Ferocity** record was corrected. It was a
> **137.86× ghost** logged at 06:06Z on 01 Aug for 1.00 divine against a 137.86 divine
> reference, and it sat as `no_reply` because the pre-0.8.0 timer wrote a verdict over a
> trade that had completed. The maintainer confirmed (2026-08-01) it **filled at the listed
> price**; the correction is in the log as an appended `filled` with
> `actual_profit_divines: 136.0`. **This is the fourth time this finding has been revised
> and the fourth time the correction favoured ghosts.**

Fill rates fell as the sample grew (plausible 21% → 12.4%) and the **value ratio rose past
parity: a ghost whisper is now worth 1.25 plausible whispers in divines** (0.477 against
0.382), having read 0.28 at n=156 and 0.66 an hour earlier. `FILL_PRIOR[GHOST] = 0.0` is
wrong by a wide, well-powered margin (n=601). Measured ratios: **0.175 on fill rate, 1.25
on value per whisper**.

**But the ranking still uses the fill-rate ratio, and it barely moved: 0.162 → 0.175.**
`FILL_PRIOR[GHOST]` is 0.17. Do not raise it to the value ratio — the weight multiplies
profit, so the fat tail would be counted twice; the reasoning is under *Cross-venue ranking*
and is unchanged by this revision.

**Read the profit column as an upper bound, and most loosely on ghosts — the tail is now
one trade.** It is `expected_profit_divines`, the app's own estimate, which carries ±6% on
liquid pairs and is least trustworthy exactly where the gap is largest. **136 of the ghost
column's 286.7 divines — 47% — are the single Rigwald's fill**, and 254 of them come from
four fills at 8.75×, 14.09×, 42.91× and 137.86×. Three of the four are independently
corroborated and one is a known loss — see *Ghost fills are real fills* below. A conclusion
resting 47% on one observation is a reason to keep measuring, not a reason to re-weight.

Fill rate by gap, all 789 whispers — the curve the thresholds should be fitted to:

| gap | whispers | filled | fill rate | exp. profit (div) | div/whisper |
|---|---|---|---|---|---|
| 1.00–1.10× | 56 | 8 | 14% | 22.0 | 0.393 |
| 1.10–1.20× | 39 | 6 | 15% | 23.0 | 0.590 |
| 1.20–1.35× | 53 | 5 | 9% | 7.9 | 0.148 |
| 1.35–1.50× | 40 | 5 | 12% | 17.2 | 0.430 |
| 1.50–2.00× | 86 | 3 | 3% | 17.0 | 0.198 |
| 2.00–4.00× | 152 | 4 | 3% | 13.0 | 0.086 |
| >4× | 363 | 5 | 1% | 120.7 | 0.333 |

**The cliff is confirmed and it sits between 1.35× and 1.50×, not at 2×** — everything
below 1.5× fills at 9%–15%, everything above at 1%–3%. `max_gap_ratio = 1.50` lands on it.
Every bucket is now over `MIN_SAMPLES`.

**`min_gap_ratio = 1.05` is no longer unmeasured.** The 1.00–1.10× bucket was 2 whispers at
n=156 and is 56 whispers at n=789: it fills at **14%**, as well as any bucket below the
cliff, and returns 0.393 div per whisper. Fill *behaviour* gives no reason to raise the
floor. The reason to raise it is unchanged and is not about fills: at a 1.05 gap the entire
edge is inside the ±6% error bar on the reference price that found it, so those 8 fills may
not have been profitable at all. **Do not read this bucket as vindicating 1.05** — read it
as showing that the question is a pricing question, exactly as the pricing item says.

**The uncomfortable part holds and got stronger: the whisper is nearly free.** 601 ghost
whispers across ~5 hours of play returned 0.251 div each against 0.382 for a plausible one,
on a 2% hit rate carried by a fat tail. A 6× cheaper hit rate stayed within 35% of the
value per message. The binding constraint is attention, not opportunity — "is this worth
whispering?" has no answer independent of how many whispers are left in the session, and
the app models none of that.

**Sample provenance.** 789 attempts over 2026-07-29 to 2026-08-01: 189 pre-0.7.0 records
with no `session_id`, then seven sessions. `11fc03d0a4f3` (2026-08-01 20:49–21:29Z, 227
attempts, 14 fills) is a **fifth** field-test session, run on 0.8.0 — it is the first to
write `expired` rather than `no_reply` (209 of them), and it postdates the *fourth session*
write-up below, which does not include it.

**2. There are no bulk sellers on the Bulk Item Exchange.** Probed 8 items for the "real
seller shaving price to move volume" profile:

```
listings below CE, by gap x stock
       gap   stock 1-2   stock 3-9   stock 10+
  1.0-1.2x          12           1           0
  1.2-1.5x           4           0           0
    1.5-3x           2           1           1
       >3x           8           2           0
```

The plausible-gap / real-depth quadrant is empty. Profit does **not** scale with quantity;
the ceiling is about a divine per fill.

**3. Cheap items yield nothing.** Probed live: chaos (0.11 div) and greater-chaos-orb
(0.34 div) had *zero* listings below CE. The value gate stays, but for this reason — not
for the rounding reason it originally had.

**4. The second field test cleared ~20 divines in 63 minutes (2026-07-30 10:29–11:32Z).**
The first session to end ahead. 147 whispers, 6 filled and 1 sold, **20.80 divines of
*expected* profit** — the app's own estimate, which is the ~26% -optimistic number, so the
realised figure is lower and was not separately recorded. It is the source of the band and
gap tables in finding 1 above.

**Where this data lives, because it was nearly lost twice:** `outcomes.jsonl` in the
platform cache directory — on Windows `%LOCALAPPDATA%\poe2-arb\outcomes.jsonl`, reachable
from WSL at `/mnt/c/Users/<user>/AppData/Local/poe2-arb/`. It is written automatically on
every whisper and every verdict, needs nothing from the operator, and **156 of 156 attempts
carry a resolved outcome** — mostly because `awaiting_timeout_s` self-records the silence.
Two records per attempt (`kind: "attempt"` carrying band/gap/cost, then `kind: "outcome"`
carrying only the id), so any analysis has to join on `id`.

The trap: a session summarised in conversation as "made about 20 divines" reads as though
no measurement was taken, and was written up that way here before anyone opened the file.
**The log is the record; the operator's recollection is not.** Read it before concluding
that a session produced no data.

### Ghost fills are real fills, not counteroffers — measured 2026-08-01, n=37 fills

> **Updated later the same day: 37 fills, 36 at the listed price.** The Rigwald's Ferocity
> record was corrected from `no_reply` to `filled` after this join was run, so it was not
> in the 36. It was then checked against `Client.txt` the same way and is **corroborated
> independently of the maintainer's recall**, which matters because it is now 47% of all
> ghost realised value:
>
> ```
> 23:06:04  @To Ciosss: Hi, I'd like to buy your 1 Rigwald's Ferocity for my 1 Divine Orb
> 23:07:25  : Trade accepted.
> 23:07:30  @To Ciosss: ty
> ```
>
> The trade is accepted **81 seconds** after the whisper and the thank-you goes to Ciosss
> five seconds later. `Trade accepted.` carries no name, so the join is by elimination:
> five sellers were whispered in that window (BADL, Ciosss, Xigemalulu, 胖胖嚛,
> Peto_Rovente) and **Ciosss is the only one that ever resolved as anything but
> `no_reply`** — the other four were whispered 20–30 times each across six sessions and
> never once replied. Ciosss appears in the log exactly once: one whisper, one fill. And
> per *"Reply to the last whisper received"* below, `@To Ciosss` as a reply target means
> Ciosss had whispered *back*, which no other candidate did.
>
> At **137.86×** it is now by far the largest gap ever observed to fill — 3.2× the previous
> record of 42.91× — and the listing was **six minutes old** with the seller not AFK.

**The question, and why it mattered.** On 2026-08-01 the one ghost fill observed by hand
was a **counteroffer at 10× the listed price** that lost money while logging +38.00 divines
of expected profit. If the fat-tail fills behind the ghost correction were all seller
haggling, the correction was measuring negotiation rather than fills and ghost value per
whisper was overstated or negative. That would have invalidated the largest revision the
project has made.

**It did not.** Every one of the 36 fills in `outcomes.jsonl` was joined to the seller's
`@From` lines in `Client.txt` (attempt `id` → character → whispers within −1/+25 min of the
logged `@To`). Result: **35 of 36 fills went through at the listed price. One was a
counteroffer** — `9adaaa859e10`, the already-known one. Of the 12 ghost fills, **11 were at
the listed price**, including both fills the 0.7.0 correction rested on:

| id | item | ask | gap | seller's reply |
|---|---|---|---|---|
| `fa91398cc414` | Ancient Rib | 2 @ 1 div | 3.92× | `ty` — traded 51s after the whisper |
| `0980dfa320d3` | Uhtred's Saga | 2 @ 80 ex | 10.94× | *nothing* — joined, traded, done |
| `9adaaa859e10` | Faded Crisis Fragment | 5 @ 1 div | 8.75× | `10 div` … `so 50 div total 5x 10` |

The replies to the other 33 are pleasantries (`ty`, `oki`, `1min`), GGG's own auto-thank, or
GGG's **"Ready to be picked up: 10 Ancient Crisis Fragment listed for 10 Divine Orb"**
template — which is itself confirmation the price was the listed one, since the game
generates it from the listing. **The 0.7.0 correction stands.** Do not re-open this.

**Two extreme gaps are independently corroborated, which is the stronger result.** The
concern behind the counteroffer question was really "is a 40× gap ever real?", and the log
answers it without a trade:

- **Aldur's Saga**, bought at 1 div against a CE reference of 42.9 (42.91×). A *different*
  Bulk seller was asking **42.0 divine** for the same item in the same sweep. Two
  independent sources agree; the 1-div listing was genuinely mispriced and the fill was a
  real ~41 div gain.
- **Preserved Cranium**, bought 3 @ 1 div against a CE of 14.1 (14.09×). Across 66 attempts
  on that item, sellers ask 9–10 div, and the same seller re-listed at 9 div eleven minutes
  later. The gain was real, though nearer ~24 div than the logged 39.

So the fat tail is a **real property of the Bulk Item Exchange**, not an artefact of the
reference price. The counteroffer risk is real but rare (1 in 36) and is a reason to make a
row's **price** amendable, not a reason to distrust the band.

### The three-way verdict split has never once been used by hand — measured 2026-08-01, n=227

0.8.0 replaced the single *No Reply* button with **AFK** and **Offline**, on the reasoning
that those were the two things the maintainer ever actually meant, and left the timer to
write **Expired** on its own. TODO flagged the risk in advance: *"if the three buttons feel
like more work than the one they replaced, that is worth knowing before the log fills up
with a split nobody uses."*

Session `11fc03d0a4f3` (01 Aug 20:49–21:29Z) is the only session that has ever run 0.8.0 —
it is the only one writing `expired` rather than `no_reply`, which is how to identify it.
Its 227 whispers resolved as:

| verdict | n | written by |
|---|---|---|
| `expired` | 209 | the timer, on its own |
| `filled` | 14 | the user |
| `sold` | 4 | the user |
| `afk` | **0** | — |
| `offline` | **0** | — |
| `declined` | **0** | — |

**Across the whole log — 789 whispers — AFK, Offline and Refused have been pressed zero
times between them.** Every unanswered whisper in the 0.8.0 session went to the timer.

What this does *not* say: that the split was a mistake. `expired` is honest where
`no_reply` was not, and that half of the change is doing its job — a verdict is no longer
claimed that nobody observed. What it says is that **the manual half is so far unused**,
and therefore that the plan to split `NO_REPLY` by reading `Client.txt` (below) is now the
*only* live route to the AFK/offline distinction rather than a supplement to a button.
Before adding a fourth button anywhere, check this table again.

One session is not a habit, and the maintainer had not been told the buttons were the
thing to exercise. Ask before treating it as settled.

### A listing older than ~3 days has never filled — measured 2026-08-01, n=789

Fill rate against `listing_age_s` at the moment of the whisper, all resolved attempts:

| listing age | whispers | filled | fill rate |
|---|---|---|---|
| < 1 h | 283 | 18 | 6.4% |
| 1–6 h | 177 | 8 | 4.5% |
| 6–24 h | 159 | 5 | 3.1% |
| 1–3 d | 68 | 5 | 7.4% |
| **≥ 3 d** | **102** | **0** | **0%** |

**The oldest listing that ever filled was 62.9 hours (2.62 days) old.** At ≥2 days it is 1
fill in 125; at ≥3 days, 0 in 102. Against the 4.56% base rate, P(0 fills in 102) ≈ 0.008,
so this is not sampling noise. The effect holds in both large bands separately (ghost 0/79,
plausible 0/23), so it is **age, not gap** — an old listing means an absent or uninterested
seller whichever band it sits in.

**This is the cheapest ranking signal the project has found.** 102 of 789 whispers — 13% of
the whole budget — went to listings that have never once produced a trade. Nothing in
`listings.py` reads `listing_age_s` today. Note the shape: below 3 days age barely predicts
anything (6.4% → 3.1% → 7.4%, non-monotonic), so this is a **cliff to gate on, not a decay
curve to weight by**. Do not build a continuous freshness discount from these numbers.

### Fixed in 0.6.0, all found by one session of real use (2026-07-31)

Kept because each is a class of bug the test suite could not see, and the pattern is
worth more than the individual fixes:

- **The global hotkey had never worked.** `nativeEventFilter` read `ctypes.wintypes.MSG`
  without `import ctypes.wintypes` — a submodule, not an attribute — so every keypress
  raised `AttributeError` inside the filter's own catch-all and was logged at *debug*.
  Registration succeeded and reported success, so the log said the hotkey was live.
  Two lessons: a `except Exception: log.debug(...)` around a feature's only code path can
  hide the feature being entirely absent, and it was invisible to tests because the whole
  branch is Windows-only. It is now logged at warning and reported to the user once.
- **The bankroll was a per-trade allowance, not a total.** `build_candidates` sizes each
  candidate against the whole pot, which is correct in isolation and wrong across a queue:
  four separate 400-exalted trades are each affordable with 500 exalted. The queue held
  committed currency back until the whisper was answered for. **Reverted in 0.7.0** — see
  *The holdback was the wrong fix* below. The observation stands; the remedy did not.
- **Costs were displayed in divines for exalted-priced listings.** A listing whispered as
  "2412 exalted" appeared as "5.6 div". Same money, but the user has to recognise the
  offer when a reply arrives an hour later, often in a language they do not read. Money is
  now shown in the seller's own currency everywhere.
- **The Trades history filters were structurally empty.** "Ones I messaged" and "Ones I
  bought" only learned about whispers copied from that table, and every whisper comes from
  the queue. They were also cleared on each sweep — and a listing you *bought* is absent
  from the next sweep by definition, so the one case the filter exists for was the one it
  could never show.
- **A collapsed splitter pane persists and looks like a missing feature.** A `QSplitter`
  takes a collapsible pane to zero regardless of its minimum size, and the position is
  saved: a stray drag left the Opportunities tab showing only Quick Lookup, across
  restarts, with only a handle jammed against the top edge to explain it. Found by
  screenshot, from a real saved `ops_split` of `[0, 476]`. Neither splitter is
  collapsible now, and a saved zero is rejected rather than clamped.

### Found in the third session of real use (2026-07-31), fixed in 0.7.0

- **The hotkey still did nothing, with the app itself focused.** The 0.6.0 fix — the
  missing `import ctypes.wintypes` — was real and was not the whole story. Tested in game
  *and* with the app as the active window, so this is not foreground-window or elevation
  behaviour: the message was never being seen. The remaining suspect is the delivery path
  itself. `GlobalHotkey` inherited from both `QObject` and `QAbstractNativeEventFilter`,
  and PySide6 does not reliably construct the C++ half of a second wrapper base, so the
  filter Qt was handed may never have been called at all. **Qt is now out of the path
  entirely**: `RegisterHotKey(NULL, …)` posts WM_HOTKEY to the thread that registered it,
  so a dedicated thread registers the key and runs its own `GetMessage` loop. Nothing has
  to reach Qt's event dispatcher for a press to be noticed. *Two failed fixes in two
  releases is the lesson here:* the feature is Windows-only and no test could see it, so
  0.7.0 also adds a press counter to the Settings dialog — pressing the key with the
  dialog open now says so on screen, which makes the next report diagnosable in seconds
  rather than needing another release to find out.
- **The holdback was the wrong fix.** 0.6.0 treated a copied whisper as money spent until
  the user said otherwise. Against the measured fill rates — 21% plausible, 2.3% ghost,
  so 79%+ of whispers never touch the bankroll — the guard withheld far more real trades
  than it prevented double-spends. Reverted on the maintainer's call. *The n=789 refit
  (2026-08-01) makes the case stronger, not weaker: 12.4% and 2.0%, so 95% of whispers
  never touch it.* **The general
  lesson:** a correctness argument that ignores the base rate can be locally sound and
  still net negative. Sizing every candidate against the whole bankroll is the accurate
  model when whispers rarely fill.
- **Bulk listings are ratios, not bundles.** A listing advertising "10 Faded Crisis
  Fragments for 100 divine" can be traded along at any point that divides — the trade site
  allows it, and the maintainer reports sellers answer such asks; they are only "less
  likely to reply". The app treated the advertised amounts as an indivisible lot, so a
  100-divine listing was invisible to anyone holding 20 divines, which is most of the
  time. Now reduced to lowest terms (`listings.smallest_lot`): 100:10 divides at 10:1, so
  20 divines buys 2. The floor on how finely it divides is that **partial currency cannot
  be traded** — the same fact behind the settlement haircut — so a 7:3 ratio divides at
  nothing smaller than 7:3.
- **Sellers list stock they do not have, and buyers cannot always afford the ask.** Two
  cases in one session: a whisper for 18 Faded Crisis Fragments where only 3 were
  affordable at the time, and a seller advertising 2 Omens of Whittling who held 1. Both
  were logged at the quantity asked for, so the outcome log carried a cost and a profit
  that never happened — in a file whose entire purpose is being the honest record. The
  quantity is now correctable after the fact, appended as an amendment so **the original
  ask survives in `asked_units`**: the gap between what was listed and what was there is
  itself a measurement, and one worth accumulating.
- **A fifteen-minute sweep that reports only at the end is worse than a slower one that
  reports as it goes.** Candidates were built from the whole listing set after the last
  fetch, so a sweep was silent for its entire run and then queued everything at once.
  Each item's candidates are now emitted as that item is priced. This is also more
  accurate, not just calmer: the first item's listings are already a quarter of an hour
  stale by the time the last one is fetched.
- **Hovering an in-row button lit the whole row.** Added in 0.6.0 on the reasoning that
  the row tint says which trade a click acts on. Reported as noise: by the time the
  cursor is on the button that question is already answered. Buttons now report no row;
  the rest of the row, including the gaps between the buttons, still lights up.

### Found in the fourth session of real use (2026-08-01)

**Half of this is fixed in 0.8.0** — the false expiries, the repeated whispers, the
silent hotkey refusal, the column names and the truncated headings. The evidence below is
kept in full regardless of what was built from it, and what is *not* yet fixed is called
out at the end of each entry. What 0.8.0 decided while fixing them is in
*Deliberate decisions*, below.

Measured from `outcomes.jsonl` (969 records, 4 sessions: `5731c10c7246`, `d8a2b67634ef`,
`c7ae70bf0310`, `4340682082ea`) joined against `LatestClient.txt`. **The local-time offset
on this machine was UTC−7** on this date, derived by correlating `@To` lines against logged
attempts — 06:05:45Z ↔ `2026/07/31 23:05:47`.

- **The hotkey still does nothing. Third fix, third failure.** Tested in 0.7.0 — the build
  that took Qt out of the delivery path entirely — with the game focused *and* with the app
  focused. No press has ever been observed in any release. The report does not say whether
  the Settings **press counter** moved, and that is the single diagnostic 0.7.0 added for
  exactly this situation: it separates "the key never reached us" from "the queue had
  nothing to take". **Collect it before writing a fourth fix.** Three derivations from the
  Win32 docs have now produced three non-working builds, so the next move is to read how a
  shipped tool actually does it (Sidekick, Awakened PoE Trade) rather than deriving again.
- **The hotkey was never bound at all, and three releases were spent fixing the wrong
  half.** Root-caused 2026-08-01 from the Settings line the maintainer reported: with the
  box ticked, a fresh binding and the settings saved, it still read *"Not listening. Tick
  the box above and press OK to bind it."* That text is the `not hk.active` branch
  (`settings_dialog.py:352`), and `active` is `self._pump is not None and self._pump.ok`
  — so **`RegisterHotKey` returned 0**. No press could ever have arrived, and every fix
  since 0.5.0 (the missing `ctypes.wintypes` import, then taking Qt out of the delivery
  path) addressed what happens *after* a press. Both were real bugs; neither was this one.
  **Why it stayed invisible for three releases:** on a false return the pump sets
  `ok = False` and returns silently (`hotkey.py:176-183`) — it never calls `GetLastError`,
  and `failed` is only emitted from the `except` branch, so a refused registration writes
  nothing to the log and shows nothing on screen. *The lesson is about the diagnostic, not
  the API:* 0.7.0 added a press counter to tell "the key never reached us" from "the queue
  had nothing to take", and the real answer was a third thing neither branch could express.
  A status line that reports success or silence cannot distinguish silence from refusal.
  Registration must report **why** it failed. Most likely cause is another process already
  owning the combination — the maintainer runs Sidekick — which `GetLastError` returns as
  `ERROR_HOTKEY_ALREADY_REGISTERED` (1409) and which a second binding would not escape if
  that process grabs a range.

  ~~**Confirmed the same day: it was Sidekick.**~~ **Withdrawn 2026-08-01 (later the same
  day). The Sidekick attribution was a confound and is not supported.** What was recorded
  originally: "quitting Sidekick **and rebinding** made the hotkey fire — in the app *and*
  in game, the first time it has ever worked in any release. Restarting Sidekick afterwards
  did not take it back." The error is visible in that sentence — **two variables were
  changed and the fix was credited to one of them.** Rebinding is the other, and it
  explains the result on its own if the problem was the *combination* rather than the
  *program*.

  **The test that isolates it, on v0.7.0 from Releases:** poe2-arb quit, game quit,
  **Sidekick running throughout**, game restarted, then poe2-arb restarted — so Sidekick
  called `RegisterHotKey` first, by a wide margin, which is precisely the order predicted
  to fail. **It registered fine and the hotkey works.** Sidekick is therefore not holding
  the binding now in use, and the "first-come-first-served, so this will regress"
  prediction is falsified for that binding.

  **What survives, and it is the part that matters.** `RegisterHotKey` *was* returning 0 —
  that is derived from the `not hk.active` branch and is not in question. What is unknown
  again is **why**. Two live hypotheses, and no evidence yet separating them:
  - *The specific combination was taken*, by Sidekick or by anything else, and rebinding
    is what fixed it. Consistent with everything observed.
  - *A stale poe2-arb process still held the key.* `RegisterHotKey(NULL, …)` is owned by
    the thread, released when the process exits — an earlier instance that had not fully
    exited, or a pump thread that outlived its window, would refuse the next instance with
    1409 and would have nothing to do with Sidekick at all. Note the app has shipped a
    `terminate()` fallback in `_HotkeyPump.stop` for exactly the case where the thread
    will not go quietly.

  **One cheap experiment settles it:** with Sidekick running, bind `ctrl+shift+c`
  specifically — the combination from the original failure — and see whether it is refused.
  If it is, the cause is that combination. If it is not, the original refusal was
  transient, and a stale process is the leading candidate.

  **RESOLVED 2026-08-01, and the experiment above was never needed — the second
  hypothesis is right, and the stale process is one poe2-arb starts itself.** The 0.8.0
  build was run on Windows for the first time and refused a hotkey within four seconds,
  with `GetLastError` finally saying why. From `poe2-arb.log`, four lines, unedited:

  | time | line |
  |---|---|
  | 06:32:16 | `gui.app: poe2-arb starting` |
  | 06:32:16 | `gui.hotkey: global hotkey registered: CTRL + SHIFT + C` |
  | 06:32:18 | `gui.install_prompt: updated installed copy from 0.7.0 to 0.8.0` |
  | 06:32:19 | `gui.app: poe2-arb starting` |
  | 06:32:20 | `gui.hotkey: RegisterHotKey refused (GetLastError=1409 …)` |

  **The app was locking itself out of its own hotkey, on every update.** `_update_in_place`
  replaces the installed exe, calls `launch()` on it and returns True so `main` exits — but
  `MainWindow.__init__` had already registered the hotkey *two seconds earlier*, and a
  `RegisterHotKey(NULL, …)` is held until its process dies. So the copy that was leaving
  owned the key and the copy that was staying asked second and was refused. The leaving
  copy was gone by 06:32:46 (the rebind to `CTRL + ALT + D` succeeded then, and
  `CTRL + SHIFT + C` again at 06:32:52), so the window is only a few seconds wide — and
  permanent, because nothing before 0.8.0 ever asked again.

  **This is very likely the whole three-release story.** The upgrade path *is* the test
  path: download the new exe, run it, it updates the installed copy and hands over, and the
  surviving process has no hotkey. Every field test began that way. It also explains the
  two facts that made the Sidekick answer look right and then wrong — quitting Sidekick
  involved restarting poe2-arb (which is what actually fixed it), and the isolating test on
  2026-08-01 restarted poe2-arb *without* an update pending, so nothing was holding the key
  and it registered fine. Not proven for the earlier releases, which logged nothing; stated
  as the leading explanation, not as measurement.

  **Fixed by ordering, not by anything in `hotkey.py`.** `MainWindow._setup_hotkey` now only
  wires the object up; registration moved to `MainWindow.start_hotkey`, which `app.main`
  calls **after** `maybe_offer_install` returns. A process about to hand over never claims
  the key. `tests/test_app.py` pins the call order; `test_main_window.py` pins the split
  between constructing the window and claiming the key.

  **The update *onto* the first fixed build can still race, and that is not a regression.**
  The fix constrains the copy that is *leaving*, so it only helps once the leaving copy has
  it. Upgrading from any build ≤0.8.0-artifact means the old code registers at construction
  as before, and the arriving fixed copy may still find the key taken — it asks slightly
  later now (after the install check rather than during construction), which narrows the
  window but does not close it. Every update *after* that one is clean. If the hotkey is
  refused on exactly one upgrade and never again, this is why; the retry is the backstop.

  **Two things this does not fix, deliberately.** A poe2-arb that crashed or hung with a
  live pump thread still holds the key for the next launch — that is what the 60-second
  retry is for. And the retry *would* have recovered this case on its own at ~06:33:20;
  the maintainer rebound by hand at 06:32:46 first, **so the retry has still never been
  observed firing.** It remains unverified.

  **`describe_error(1409)` now names poe2-arb** as the usual culprit, and only poe2-arb.
  That is not a reversal of "do not name a program": a third-party guess sends people to
  close something innocent, whereas our own second copy was caught in the log holding the
  key and is the one thing the user can check immediately.

  - **Do not tell the user it is Sidekick.** The shipped wording said so and has been
    softened to name overlays as *a* common cause, because naming a specific program on
    this evidence would send people to close something innocent.
  - **Fixing the silence matters more than fixing the conflict**, and this episode is the
    argument for it rather than against it. Three releases were lost because a refusal was
    indistinguishable from success; a fourth conclusion was then drawn from a confounded
    one-shot test and lasted half a day. `GetLastError` on the false return is what would
    have answered this immediately, and is what will answer it next time.

  **What 0.8.0 built, and three traps in it.** The pump now calls `GetLastError` on a
  false return and reports it; Settings gained *Refused* as a third state, because
  "listening / not listening" is exactly the vocabulary that could not express this.
  `GlobalHotkey.probe` trial-registers a binding before Settings saves it, and
  `_try_again` retries a refused one every 60s so a key lost to startup order comes back
  when the other program closes. The traps, in the order they bite:
  1. **Probing the key we already hold reports it as taken** — by us. `probe` answers
     "free" for the live binding rather than testing it, or every working hotkey fails
     its own pre-check.
  2. **The pre-check is a race and cannot be a guarantee.** Another program can claim the
     key between the answer and the save, so `register` still has to report failure. The
     probe buys a better message, nothing more.
  3. **The trial must run on the pump thread.** `RegisterHotKey` is thread-affine, so a
     key registered from the GUI thread posts `WM_HOTKEY` where nothing is listening —
     which is one line away from the bug this whole item is about. `probe` posts `WM_NULL`
     to wake the pump's blocked `GetMessage` and waits on an event for the answer.

  Still unverified on Windows: everything above is Windows-only and untestable here, which
  is the exact shape of code that shipped broken twice. The tests fake the Win32 layer.
- **A real fill was logged as `no_reply` — and it was the largest gap the project has
  seen.** Rigwald's Ferocity, whispered 23:06:04 for 1 divine against a CE reference of
  137.86 (`d218084e2ae6`). `@To Ciosss: ty` follows at 23:07:30 — 86 seconds later, so it
  traded. The queue's five-minute auto-expiry wrote `no_reply` at 23:11:03, **three and a
  half minutes after the trade had already completed**, and nothing asked afterwards. An
  auto-expiry that fires while a fill is still in progress does not just lose a click, it
  writes a false verdict into the file the fill rates are computed from. The log *format*
  is fine — verdicts apply in file order, so a later correction wins, and `9adaaa859e10`
  carries `no_reply` then `filled` from a real correction the same evening. The gap is the
  UI: once a row auto-expires there is no way back to it.
- **The one ghost that filled, filled at a counteroffer 10× the listed price.** The app
  read RuinousLuck's listing as 5 Faded Crisis Fragments for 5 divine — 1 div each against
  a CE reference of 8.75, ghost band, logged `expected_profit_divines: 38.0`. The seller's
  reply was `10 div`, then `so 50 div total 5x 10`. Taken at 10 div each against a real CE
  of ~9.4, it was a **small loss** on a record that claims +38. It was raised here as a
  candidate explanation for the entire ghost result — if the 3.92× and 10.94× fills were
  also counteroffers, ghost value-per-whisper would be overstated or negative.
  **Checked 2026-08-01 and it is not the explanation: 35 of 36 fills were at the listed
  price, this one included as the sole exception.** See *Ghost fills are real fills, not
  counteroffers* above. What survives is the narrow version: a counteroffer happens about
  1 fill in 36, and the app has no way to record one, so **a row must be amendable in
  price and not only in quantity.**
- **The second false expiry that evening was a seller finishing a map — the case a pin
  solves.** Same listing, `9adaaa859e10`: whispered 02:32:27, seller replied `map` then
  `finish` at 02:33:23, auto-expired to `no_reply` at 02:37:25, **traded at ~02:43** and
  hand-corrected to `filled` at 02:46. So the timeout fired six minutes before the trade,
  on a row whose seller had already said in writing that they were coming. Two of the two
  false expiries measured this session were live conversations, not silence: **an answered
  whisper is exactly the row that should stop counting down.**
- **The same stale listing was whispered five times across four sessions in 3½ hours.**
  RuinousLuck's Faded Crisis Fragment listing at 23:05:47, 23:24:18, 23:39:21, 02:21:58 and
  02:32:27; two of those were answered `RuinousLuck is not online`. Bulk listings do not
  delist when the stock is gone or when the seller stops honouring the price, so
  **re-finding a listing you have already resolved is the normal case, not an edge case**,
  and the app keeps no memory of what it has already asked for. Restarting *Find trades*
  re-whispers the same sellers immediately, which is also how the maintainer pauses the app.
- **A Ready-to-whisper row cost 84 div against a 39 div bankroll** (screenshot, 0.7.0). Not
  yet diagnosed; the bankroll spin box had been lowered during the session, so the first
  suspect is that queued candidates are not re-checked when the bankroll changes.
- **Column headers were misread by their own author.** `Buy 5 / Each 1 div / Cost 5 div /
  Profit +38` was read back as "I bought 1 for 5 div". Three of the four words are doing a
  job the reader has to be told; *Amount / Price per / Total* is what the maintainer reached
  for unprompted, and it is the same vocabulary the in-game trade UI uses.

### What the game's own log can and cannot tell us — measured 2026-07-31

Asked whether trade or party history could auto-mark outcomes. Measured by joining the
maintainer's real `…/Path of Exile 2/logs/Client.txt` (194 MB, append-only;
`LatestClient.txt` beside it is the current session) against the 189 attempts in
`outcomes.jsonl`, over the 2026-07-29..31 sessions. **Not implemented** — this is the
evidence for deciding whether to.

**The lines that exist**, `[INFO Client NNNNN]` prefix stripped:

```
… @To Xithira: Hi, I'd like to buy your 1 Architect's Orb for my 4 Divine Orb in Runes of Aldur
… @From Ti_ny: This player is AFK.
… : Xithira has joined the area.
… : Trade accepted.          (and : Trade cancelled.)
… @To Xithira: ty
```

Party invites are **not logged at all**, and `has joined the area` fires only when someone
enters *your* hideout — half the trades are the other way round. Neither is a foundation.

**Attribution works, and by a route that is not obvious.** `Trade accepted.` carries no
character. Matching it to "the last seller we whispered" fails badly, because whispers go
out at ~2/minute and the wrong neighbour is usually nearer. Three rules in order —
(1) whoever most recently *joined the area*, (2) else whoever we sent a **non-template**
whisper to within two minutes afterwards (the "ty"; the app's own whisper always names the
league, a thank-you never does), (3) else the last seller asked — score **10 of 11**
hand-marked fills, the one error being two trades 90 seconds apart assigned to each
other's sellers.

**But auto-marking fills buys almost nothing.** Of 18 `Trade accepted.` lines in that
window, 11 attribute to app whispers and **all 11 are trades the maintainer had already
marked by hand**; the other 7 fall outside session hours and are ordinary trading. *No fill
was missed.* An earlier pass of this analysis claimed four were — that was the naive
last-whisper matcher misattributing accepts, and it is recorded here because it is exactly
the mistake the better matcher exists to avoid.

**The value is in the NO_REPLY bucket, which is not one thing.** Of 176 whispers the app
recorded as `no_reply`:

| what the game log shows | n | share |
|---|---|---|
| genuinely silent | 134 | 76% |
| seller AFK (GGG's own auto-reply) | 39 | 22% |
| a human answered | 2 | 1% |
| "already gone" — i.e. `SOLD` | 1 | 1% |

So roughly **a quarter of the fill-rate denominator is a state the app has no category
for**, and the AFK auto-reply arrives within a second of the whisper — it is knowable
immediately, not after a ten-minute timeout.

**Bonus, and it undermines a feature we already ship:** of the 40 whispers that hit an AFK
auto-reply, GGG's exchange API had flagged the seller AFK beforehand in only **29**. The
other **11 (28%)** were reported present and were not. The Results tab's *By seller state*
split is measured against a flag that is wrong more than a quarter of the time in the
direction that matters.

**Implementation notes, so nobody re-derives them:** timestamps are local, not UTC (derive
the offset by correlating `@To` lines against logged attempts rather than trusting the
machine's zone); the file is append-only, so tail from a stored offset; and the AFK reply
is localised — this log alone carries it in English, Korean, French, Portuguese, Chinese
and Russian, so match on the set, never on one string.

**NO_REPLY is four states, not two.** Besides the AFK auto-reply the log carries
`: <char> is not online.` — 19 of them since 2026-07-29. That one is a **freshness
measurement**, not just a category: the sweep filters to `status: online`, so every one of
these is a listing that went stale between the fetch and the whisper. Silent / AFK / not
online / already gone are four different problems with four different fixes.

### GGG's trade site sends whispers server-side, with no client input — measured 2026-07-31

**Corrects an earlier claim in this file that the site's whisper button only fills the
clipboard. It does not.** The maintainer sent one from the browser as a test; the game
logged it while the browser still had focus:

```
2026/07/31 20:49:04  @To Oooosung: Hi, I would like to buy your Undiluted Greater Mana
                     Flask of the Constant listed for 1 exalted in Runes of Aldur …
2026/07/31 20:49:07  [WINDOW] Gained focus
```

Focus arrives **three seconds after** the whisper is already in the log. Across 188
buy-whispers since 07-29, exactly one was sent while the client was unfocused, and it is
that test. So the message is delivered by GGG's servers to the client; nothing types into
the game.

**Why this matters more than any macro question.** If the same path is available to us, the
app can send whispers with *no synthetic input at all*: no foreground check, no
wrong-window hazard, no `Ctrl+A` clobbering whatever the user was typing, works while
alt-tabbed, and it is GGG's own mechanism rather than a macro sitting inside a rule. It
also dissolves the "which trade is the thank-you for?" problem, because the send is
initiated from the app where the row is unambiguous.

**What is not known yet.** The whisper the maintainer tested came from the *item search*
page. Our cached `/api/trade2/exchange` responses carry **no whisper token** of any kind —
only the localised `whisper` template — so either the token is issued only to an
authenticated session, or only item search offers it and the bulk exchange does not. The
cheap experiment, before any code: open the **Bulk Item Exchange** tab on the trade site
with the game unfocused, whisper a listing, and see whether it arrives. That is the only
blocking unknown.

**Confirmed on the bulk exchange too** (2026-07-31, one exalted for an armour scrap from
a Korean seller), so the path is not item-search-only.

**But it is not a sanctioned path, and that reverses the recommendation.** Checked against
GGG's own developer documentation the same day:

- The OAuth scope list is `account:profile`, `account:leagues`, `account:stashes`,
  `account:characters`, `account:league_accounts`, `account:item_filter`, plus
  confidential-only `service:*`. **There is no trade, whisper or messaging scope, and the
  documented API has no trade-search or whisper endpoint at all.**
- Desktop apps are "public clients" in GGG's terms — Authorization Code with PKCE, a local
  redirect, shared rate limits — and public clients **cannot hold `service:*` scopes**.

So the site's whisper button is a *first-party* endpoint driven by the web session. For
this app to use it, it would have to impersonate the website with the user's `POESESSID` —
a full account session, undocumented, living inside a distributed exe. Meanwhile the
keystroke route is *explicitly* blessed (one action per key press, "totally fine to use a
macro to say thanks for the trade"). **On the axis that matters most — is this sanctioned
— the ranking is the reverse of what this section first concluded.** Synthesised input is
documented as allowed; the API route is merely undetectable.

### "Reply to the last whisper received" is right 7 times in 11 — measured 2026-07-31

The maintainer intends to use Sidekick's auto-thank, which answers the last whisper
*received*. Scored against the 11 completed trades: **7 correct**, which is far better
than answering the last whisper *sent* (2 of 11) and still not reliable. The failure mode
is specific and worth knowing: two of the four misses would have thanked a seller whose
last message was `This player is AFK.` — an auto-reply from an unrelated listing that
landed between the trade and the keypress. Harmless as a message, but it means **a "ty" in
the log is not proof of a trade with that person**, so those lines cannot be parsed back
as fill markers.

### GGG publishes an official Currency Exchange API, and it has both sides of the book

Found 2026-07-31 while checking the OAuth scopes. `service:cxapi` — "Get Exchange
Markets" — returns aggregate CE trade history in hourly digests, per market pair:

```
market_pair, volume_traded, lowest_stock, highest_stock, lowest_ratio, highest_ratio
```

**`lowest_ratio` / `highest_ratio` is the thing this project has never had.** The standing
#1 item is that the reference price runs ~26% high on thin items, and the fork that
decides the fix is whether that gap is *spread* — which needs both sides of the book, and
FINDINGS records elsewhere that poe2scout has "no bid, no ask, no depth anywhere". A
per-pair ratio range over an hour measures exactly that, from GGG rather than from a
third-party derivation.

**It is out of reach for now, and the exact reason matters.** `service:cxapi` is a
**confidential-client-only** scope, and a distributed desktop exe is a public client by
GGG's own definition. The public CDN URL in the docs,
`https://web.poecdn.com/api/currency-exchange`, answers HTTP 200 with 90 KB — but it is a
**stale July-2024 PoE1 snapshot**: `next_change_id` is pinned at 1722027600, the leagues
are Settlers and Hardcore Settlers, and adding `realm=poe2` or an `id=` for the current
hour changes nothing. 14 of its 109 markets carry non-zero ratios, so the shape is real
even though the data is not current.

So: **only a backend could use this**, and it would settle the project's biggest open
question if one ever existed. Worth re-testing when GGG's PoE2 API coverage widens — the
docs already note "limited APIs return PoE2 game information".

### There is no party roster in the log — checked 2026-07-31

Asked whether the trade partner could be identified by scanning party members. **No.** The
whole 194 MB log contains one party-related line, `InstanceClientSetSelfPartyInvitation
SecurityCode`, which carries no names; every other occurrence of the word is chat spam.
The only name-carrying events are `has joined the area` / `has left the area` and
whispers — and those fire only when someone enters *your* hideout. Most of these trades
went the other way, and when the buyer travels to the seller nothing in the log names
them. Reading the party UI or game memory is the other side of the line the app does not
cross.

## Denomination — the correction that mattered most

**Exalted is the *more* common denomination.** 3,502 cached listings priced in exalted
against 2,882 in divine, with 65% more distinct price points (135 vs 82) — 1 divine is a
coarse unit, which is part of why divine-priced listings quantise into 1:1 junk. GGG
accepts a list of `have` currencies, so asking for both costs one request. The first sweep
after the change surfaced a plausible-band candidate that was exalted-priced and invisible
before it.

**The settlement currency decides the rounding haircut.** Proceeds floor to whatever you
take payment in, and exalted is ~432× finer:

```
bought 1 Core Destabiliser for 2 divines, CE value 3.79
   settle in divines   -> 3.0000   profit 1.00   lost 0.79
   settle in exalted   -> 3.7894   profit 1.79   lost 0.0006
```

**The one trade that filled was settled in divines and gave up 44% of the realisable
profit to rounding.** The CE trades these items against exalted, chaos *and* divine, so it
is a free choice at sale time. Items whose lots can clear the floor go from **89 of 635
(14%) to 528 (83%)** on this change alone.

**It is not, however, a *costless* choice — see "Gold is a real constraint" above.** Gold is
charged per orb traded, so the finer denomination that saves the rounding also multiplies the
gold bill, and on 2026-07-30 that ran the maintainer out of gold mid-session. Both findings
are correct and they pull opposite ways: exalted maximises what you keep *per trade* and
minimises how many trades you can afford to make. Neither one alone is the rule.

## Taxonomies that don't agree

**The UI models the in-game selection**, not poe.ninja's categories and not GGG's API
groups. In-game tab order is authoritative: All, Currency, Essences, Delirium, Breach,
Abyss, Atziri's Temple, Fragments, Runes, Ritual, Soul Cores, Idols, Uncut Gems,
Expedition, Gems.

| poe.ninja | in-game tab |
|---|---|
| Currency, minus the 15 Vaal items | Currency |
| those 15 Vaal items | **Atziri's Temple** |
| Essences / Delirium / Breach / Abyss / Runes / Ritual / SoulCores / Idols / UncutGems / Fragments | same name |
| Expedition **+ Verisium** | **Expedition** |
| LineageSupportGems | **Gems** |

**GGG's API groups are for trading only, never display.** `Vaal` holds SoulCores +
Currency; `Ritual` holds Ritual + Idols + Fragments + SoulCores; `Expedition` holds
Expedition + Idols + Runes; `Delirium` holds Delirium + Fragments. Mapping the UI to them
would merge tabs the game keeps apart. poe2scout uses a **fourth** taxonomy (adds
`incursion`, `vaultkeys`, `ultimatum`, `idol`) — it is a pricing source, never wire it to
the UI.

Also worth not rediscovering:

- **`sep` is a separator, not an item.** Filter GGG's `sep` rows out or they become
  phantom items.
- **Waystones are tradeable but entirely unpriced by poe.ninja** (0 of 16).
- **76 of 213 runes are unpriced**, mostly `lesser-*`; ~137 are usable.

---

## Deliberate decisions — do not "fix" these

### The line the app does not cross

- **Analysis only.** Never automates any in-game action, trade, whisper or input.
  Automating trading violates GGG's ToS. Hard requirement, not a gap.
- **The hotkey writes to the clipboard and nothing else.** No synthetic input, no reading
  game state, no watching chat, never auto-Enter — the same thing the trade site's own
  copy-whisper button does. An optional Ctrl+V auto-paste may ship off by default;
  reacting to a reply may not.

### Measurement over guessing

- **No fill rate is claimed below `outcomes.MIN_SAMPLES`.** The Results tab shows an
  em-dash and says how many more answered whispers it needs. A rate from three whispers is
  an estimate wearing a percent sign. Do not soften this to "show it greyed out".
- **`suggested_gap_band` is advisory and stays advisory.** A band fitted to one league on
  one account is not a fact about the game. Show it; let the user apply it.
- **Ghosts are ranked last, never hidden**, at every long-shots setting including 1.0.
  Hiding them would make the ranking unfalsifiable.
- **Never rank by gap alone — but the reason is unsettled.** On Core Destabiliser the
  cheapest listings vanished within 25 minutes while 4–55× listings persisted for days; on
  Faded Crisis Fragment the 1-div listings were still live at 2d19h. Record freshness and
  AFK; let the outcome log decide their weight. Do **not** hard-code "fresh beats big".

### The offer queue

- **Exactly one trade is OFFERED at a time.** A second toast arriving while the first is
  unread makes both of them noise.
- **An unclaimed offer lapses into AVAILABLE rather than vanishing.** Still a good trade,
  just not worth a second interruption — that is what makes interrupting acceptable at all.
- **The three windows are independent, user-settable, and must stay ordered
  alert < listed < auto-resolve.** `offer_window_s` (20s) gates how fast the queue drains,
  *not* how long the user has to decide; `available_ttl_s` (5 min); then
  `awaiting_timeout_s` (10 min) before a whisper self-records as NO_REPLY. Settings changes
  take effect immediately — needing a restart for a countdown you just shortened looks broken.
  The latter two are **entered in minutes and stored in seconds**; the conversion lives in
  the Settings dialog and nowhere else.
- **The alert window and the listed window are two clocks on one lifetime, not two
  lifetimes.** `expires_at` is set once when a trade is first shown and never restarted;
  `alert_until` is the shorter one, and is deliberately not displayed. Until 0.6.0 the
  Expires column showed whichever applied, so a live offer claimed 20 seconds of life and
  then silently gained five minutes — and the seconds it spent flashing came out of the
  listed time the user had configured. `expires_at` is floored at the alert window so a
  short TTL cannot retire a trade whose own toast is still up.
- **An unanswered whisper self-marks as `Outcome.EXPIRED`** — *not* `NO_REPLY`, since
  0.8.0. Leaving rows pending forever would bias the log toward whatever the user came
  back and clicked, but the timer knows only that its deadline passed: on 2026-08-01 it
  wrote `no_reply` three and a half minutes *after* a trade completed, and **both** false
  expiries that evening were sellers who had answered. Timeout 0 answers every one by hand.
- **`NO_REPLY` stays in the enum and is never written again.** `outcomes.jsonl` returns
  records under it forever, so the value has to keep resolving — the same constraint as
  `bands.symbol_for_name`. It was retired as a *button* because by hand it meant one of
  two different things, which is now **AFK** and **Offline**; those two plus **Expired**
  are the three-way split the game log independently derives (76% silent / 22% AFK / the
  rest replies). Anything asking "did they answer at all" must use `Outcome.is_silence`,
  which covers all four, rather than testing members by name.
- **A pinned row never expires, and unpinning restarts nothing.** Pinning is what the user
  does when a seller speaks, so a pinned row sorts above everything else in Waiting on a
  reply and holds a highlight of its own — deliberately *not* a band colour, because it is
  state rather than risk. `expires_at` is left untouched throughout, so a row released past
  its deadline resolves on the next tick: the deadline was real, the pin only held it, and
  restarting the clock would make a row immortal by pin-and-unpin. Pin state is per-session
  UI and is deliberately **absent from `outcomes.jsonl`** — it says what the user is doing
  now, not what happened to the trade.
- **Only some verdicts suppress the listing for the session** (`SETTLED_OUTCOMES`):
  FILLED, SOLD, OFFLINE and DECLINED. `EXPIRED` and `AFK` deliberately do **not** — an
  away seller comes back, and a deadline passing says nothing about the listing at all.
  The suppression exists because a Bulk listing does not delist when its stock goes, so
  every later sweep re-finds it; `forget_resolved` drops the row that would otherwise
  deduplicate it, which is why the key is remembered separately. Keyed on `Candidate.key`
  (seller + item + ratio), because the queue row's id is regenerated each sweep.
- **Every action is one click on the row itself**, so the tables carry no selection — a
  highlight would imply a second step that doesn't exist. This constrains the redraw:
  countdowns tick every second, and rebuilding a row would destroy the button under the
  cursor mid-click, so `refresh` rebuilds only when the set of trades changes.
- **Rows do highlight on *hover*, which is not the same thing** — it is feedback about
  what a click would act on, not a state to clear. Two traps, both found by screenshot:
  in-row buttons are widgets parented to the viewport, so the view receives no mouse
  event at all while the pointer is over one (`RowHoverTable.watch` reports it instead);
  and setting `State_MouseOver` alone paints nothing under the styles this ships with, so
  the delegate fills the row itself with a translucent tint from the palette's highlight.
  **The buttons themselves report no row** (0.7.0): pointing at Accept highlights Accept,
  because by then which trade it acts on is not in question.
- **Action widgets must be unparented, not just removed, on rebuild.** `removeCellWidget`
  only schedules deletion; the orphan keeps painting at its old geometry until the event
  loop catches up, which put a live Accept/Decline on top of another row's Item column.
- **The two sections are ordered oppositely, and by presentation, not by rank.** Ready to
  whisper is oldest-first so a new arrival appends at the bottom and nothing already on
  screen moves; Waiting on a reply is newest-first because a reply is almost always to the
  whisper just sent. The queue tables are **not sortable** for the same reason a row must
  not move: a row that shifts between the glance and the click is a row clicked by mistake.
  The live offer is **no longer pinned to the top** (it was until 0.6.0, which reshuffled
  the list every alert window) — it carries the ● marker and is named in the headline,
  which is where someone mid-map is looking.
- **The hotkey falls through to the top of Ready when nothing is live.** The alert window
  is seconds and the listed window is minutes, so most of the time there is no OFFERED
  trade and the key did nothing while the panel was full of takeable rows.
- **Submissions are deduplicated against everything unfinished**, including already-
  whispered trades. Sweeps overlap, and re-offering would have the user message the same
  seller twice.
- **A declined trade is suppressed for the session; an app-initiated drop is not.**
  `decline` remembers the key, `drop` does not. Declining is a judgement the user made and
  a sweep ten minutes later re-finds the same listing; dropping a listing with no whisper
  template is a fact about that fetch, and suppressing it would hide the listing if a
  later fetch returned it complete. Deliberately **not persisted** — the reason for
  declining is usually "not right now", which does not survive a restart.
- **Currency promised to an outstanding whisper is *not* held back.** 0.6.0 held it
  back; 0.7.0 reverted that on the maintainer's call, because 79%+ of whispers go
  unanswered and the guard suppressed more real trades than it prevented double-spends.
  Do not re-add it without a fill rate that justifies it. A pot left at 0 still means
  "I didn't say", not "I have nothing" — capping it would silently hide trades.
- **The quantity on a whispered trade can be corrected afterwards, and only downwards.**
  `TradeQueue.revise` → `listings.replan_units`, appended to the log as an amendment. The
  correction is deliberately *not* re-optimised: the user is reporting what they bought,
  not asking for the best trade at that size.
- **Ghosts are never queued** (`queue_ghosts=False`). Interrupting a map for something
  measured never to fill is pure cost. They stay visible in Trades.
- **A whispered trade cannot be dismissed, only resolved.** It is already recorded as an
  attempt; deleting it would bias the outcome log toward whatever the user answered.
- **Stopping the sweep drops the QUEUED backlog and nothing else** (`cancel_pending`, added
  0.5.0). `tick` promotes the backlog whether or not a sweep is running, so switching *Find
  trades* off used to keep producing offers for minutes — reported from the field
  2026-07-30. It deliberately leaves OFFERED, AVAILABLE and AWAITING alone: retracting an
  offer mid-decision, or deleting a whisper still owed an answer, loses both the trade and
  its outcome record. Cancelled rows go to EXPIRED, not a permanent blacklist, so a later
  sweep can re-find the same listing.
- **A sweep that lands after the toggle went off does not refill the queue**, but its
  candidates still appear in Trades. Stopping suppresses interruptions, not information.

### Cross-venue ranking

- **Profit is floored to the settlement unit, over whole lots.** Never report
  `gap × quantity`.
- **`Candidate.key` is content-derived, never `id()`.** A candidate stored in a Qt item
  and read back is not guaranteed to be the same Python object; `id()` silently fails to
  match and the queue re-offers listings already whispered.
- **`pay_currency` must not be "simplified" away.** A sweep mixes denominations in one
  table: `Listing.price_per_unit` is in the seller's currency and
  `Candidate.unit_price_divines` is the comparable one. Conflating them produced a whisper
  offering 5.58 exalted for a listing wanting 2400.
- **An attempt is logged when the whisper is copied, not when it succeeds.** Logging only
  successes would produce a file in which everything fills.
- **`SOLD` and `NO_REPLY` stay distinct** even though both mean "no trade". A seller who
  answers was reachable; silence may mean either. Collapsing them hides which problem
  freshness filtering actually solves.
- **A failed re-check counts as "go ahead".** Unknown is not evidence of absence; don't
  talk the user out of a real trade because a request failed.
- **`FILL_PRIOR` holds the *fill-rate* ratio (ghost 0.16), not the value-per-whisper ratio
  (0.66) — and this looks like a transcription error.** Both numbers are measured, both are
  in *Negative results* 1, and the smaller one is the one in the code. It is deliberate:
  `fill_weight` **multiplies profit**, so `profit × weight` is already an estimate of
  divines per whisper. Feeding it the value ratio would apply the fat tail twice, since a
  ghost's value per whisper is high *because* its profit is large. Decided 2026-08-01,
  resolving a question TODO.md had carried open since 0.7.0.
- **Nothing is hidden from the queue by default — not ghosts, not stale listings.** Both
  are demoted by a measured weight. A hidden row cannot be falsified, and that is exactly
  how `FILL_PRIOR[GHOST] = 0.0` survived four field tests while being wrong. A *user*
  filter is fine and one is planned for stale rows; it must ship off by default.
- **Staleness is a cliff, not a curve.** Gate at `STALE_LISTING_S`; do not build a
  continuous freshness discount. Below three days, age barely predicts anything
  (6.4% → 3.1% → 7.4%, non-monotonic), so any decay curve would be fitting noise.

### Correcting a trade after the fact — decided 2026-08-01

- **An amendment never rewrites `gap` or `unit_price_divines` in the log, and this is not
  an oversight.** A price correction writes `cost_divines`, `pay_units` and
  `expected_profit_divines` and nothing else. The gap is the feature every fill rate in the
  project is fitted against, and the one that predicts a fill is **the gap we whispered at**
  — not the one that was negotiated afterwards. The realised gap is still recoverable from
  `cost_divines ÷ units`, so nothing is lost by keeping the whispered one. `listings.repriced`
  *does* move `Candidate.unit_price_divines`, because a row on screen showing a negotiated
  total beside an advertised gap is a row disagreeing with itself; the two are deliberately
  different, and the log is the one that must not move.
- **Profit is allowed to be negative, and every display of it must say so.** Nothing out of
  `plan_trade` ever loses money — it refuses a losing quantity — so every profit figure in
  the app was written `f"+{value:.2f}"`, which renders `+-2.80`. An amended trade *can* lose
  money; that is the case this feature exists for. `format.fmt_profit` owns the sign now.
  Do not reintroduce a hand-written `+`.
- **`sale_unit_divines` and `settle_currency` are recorded per attempt from 0.8.0.** They
  were not, and could not be recovered, so a correction to a *quantity* had no way to
  re-apply the rounding floor that decided the original profit. Records written before this
  fall back to a whole divine in `outcomes.plan_correction` — the pessimistic reading, and
  the same default `plan_trade` takes.
- **The Trades tab edits in place; the Opportunities queue uses a dialog.** Not an
  inconsistency: the queue tables rebuild on a one-second timer for the countdowns, which
  destroys an open editor mid-keystroke, and they are used with a map on screen. The Trades
  tab reads from the log, redraws only on a user action, and is where a row is corrected
  hours later. Editing there is confined to **history rows** — a live sweep row is a
  listing nobody has acted on, there is nothing to correct about it, and the same
  double-click has to keep copying its whisper.
- **A whispered row is editable in the queue while it is live, and on the Trades tab
  afterwards — not on the live sweep table.** Decided 2026-08-01. A listing you whispered
  this session is *carried* on the live Trades table so a verdict has a row to land on, and
  those rows are deliberately **not** editable there: the queue's *Adjust…* covers a trade
  in flight, and Trades → *All time* covers it once the session has moved on. The
  alternative — a live table holding two kinds of row with two sets of edit rules, one of
  which also has to keep double-click-to-copy — is the shape of a bug rather than a feature.
- **A verdict change goes through `record_outcome`, not through the amendment record.**
  Verdicts already fold in order and a later record already wins — `9adaaa859e10` carries
  `no_reply` then `filled` from a real correction made by hand. Nothing new was needed in
  the file format; what was missing was a route to it from the UI.

### Operational

- **`request_interval_s` must stay above 10s.** At exactly 10s a 300s window catches 31
  requests against a limit of 30; the penalty is a 30-minute IP ban.
- **Per-user install, never Program Files.** Elevating an unsigned binary into a system
  directory is the dropper pattern we're avoiding.
- **Release notes come from `CHANGELOG.md`**, and a tag without a section fails the build
  before anything is compiled.
- **UI state lives in a JSON file in the cache dir**, not in the TOML config (meant to stay
  hand-editable) and not in QSettings (which would write to the registry, contradicting
  "delete the folder to remove it"). Column order and widths are part of it, as the
  header's own `saveState` blob.
- **Columns are `Interactive` plus arithmetic, not `Stretch` or `ResizeToContents`.** Qt
  offers reorderable, resizable and growing two at a time and never all three, so
  `table_items.ColumnLayout` sizes to contents once, squeezes that to the window, and
  hands out each later resize in proportion. The action column is exempt from shrinking:
  a row of buttons does not get smaller when squeezed, it gets clipped, and an action you
  cannot reach is worse than one you have to scroll to.
- **Each column's floor is its own heading, not one shared number** (0.8.0). At the narrow
  end of the window a single `MIN_WIDTH = 28` let `Profit` truncate to "rofit" and
  `Expires` to "xpire", which is a header lying about which column you are reading. Below
  the sum of the floors the table scrolls sideways instead, and the window's minimum width
  was raised to 960 to make that rare — measured with `ColumnLayout.minimum_row_width()`:
  *Waiting on a reply* wants 916 and the Trades table 896. Item and Seller get a flat 120
  regardless of their four- and six-letter headings, because their contents are names.
  Three things this uncovered, all measured by screenshot and all easy to reintroduce:
  - **`resizeColumnsToContents` measures the cells and ignores the heading.** "Buy" came
    back at 30px against a 49px title, so the floors have to be applied *after* it or the
    first paint is already truncated.
  - **It does not measure a cell widget at all**, so an action column's width is a guess —
    314px for a row of buttons whose `sizeHint` is 226. That 88px of nothing came straight
    off the columns that do hold something, because the action column is exempt from the
    squeeze. `_fit_protected` asks the widget instead.
  - **Growth must hand out the space the row does not fill, not the space the window
    gained.** A row can already be wider than the window — the squeeze stops at the floors,
    and the first sizing runs against a pre-show viewport narrower than the real one.
    Adding the window's delta on top of that *compounds* the overflow: measured, a 638px
    sizing that had settled at 897 grew to 1235 in a 976px window, and what fell off the
    end was the action buttons.
- **The row action buttons are dingbats, not emoji** (0.8.0). 👍 / 👎 / 📌 were what was
  asked for and they are the wrong bet in a shipped exe: they need a colour emoji font,
  and where one is missing *every* button renders as the same empty box — verified by
  screenshot, which is also how the replacements (✔ ✖ ⚑ ⚐ ❐ ✎ ☾ ⊘ ✕) were checked to draw
  in a plain text font. The wording survives as the tooltip and as the button's `action`
  property, which is what `click_action` and the tests match on. Proper PoE2-styled icon
  assets remain the right answer and are still open.
- **A session is defined by the queue draining, not by a clock.** `session.py`: it starts
  on *Find trades* and ends only when nothing is running *and* nothing is outstanding, so
  pressing the toggle again mid-session continues it. Between sweeps the queue is
  routinely empty for minutes — ending there would close a session in the middle of one
  and leave the whispers afterwards belonging to nothing. Stamped on every attempt,
  along with the league, because neither is recoverable from the log afterwards.
- **Nothing is excluded by default** — that's the user's call. **Exclusions don't apply to
  Quick Lookup**: excluding something from the sweep shouldn't stop you pricing it.
- **Tier ordering is by measured price, not the alphabet.** Numbers in `market.py`.
- **Menus cap at `MAX_ITEMS_PER_MENU` entries per submenu**; oversized groups split via
  `chunk_group` rather than relying on Qt to scroll off-screen.
- **The league is never a literal fallback.** `sweep.resolve_league` auto-detects and raises
  if it cannot; sweeping the wrong league is worse than not sweeping. `cfg.league or
  "Standard"` shipped through 0.4.0 and priced one measured item 5.7× high.
- **The Trades *Settle in* column shows the currency the displayed profits were computed
  against, not the current dropdown.** Settlement only takes effect on the next sweep, so
  relabelling rows the moment the dropdown moves would attach a currency to figures never
  computed against it.
- **Quick Lookup prices one item against a currency; it is not an any-pair converter**
  (changed 0.5.0). Converting arbitrary item→item implied those two things trade against
  each other. Almost none do — the Exchange is organised as items against a few currencies,
  so an Omen-for-Rune ratio was arithmetic we performed, not a market anyone makes.
- **Internal band names and UI wording differ on purpose.** The enum stays
  `PLAUSIBLE`/`THIN`/`GHOST` because `outcomes.jsonl` stores those strings and old records
  must keep resolving; the UI says *worth trying* / *uncertain* / *too good to be true*.
  `gui/bands.py` is the single source for the glyph and both labels, because Trades and
  Results previously kept separate copies and drifted apart.
- **A `QTableWidget` check indicator needs a delegate to centre.** `setTextAlignment` centres
  only the text; Qt draws the indicator on the leading edge regardless. See
  `table_items.CentredCheckDelegate`.

### Rejected approaches

- **Currency Exchange API (`service:cxapi`) — not pursuing.** Requires a confidential
  OAuth client on an HTTPS domain the maintainer controls; public/desktop clients cannot
  use `service:*` scopes at all, so it can never ship inside the exe. It also serves hourly
  *historical* digests only. poe2scout covers the reference-price need.
- **No peer-to-peer data sharing between clients.** Federated edges arrive at different
  timestamps, so any cross-client assembly can produce opportunities that were never
  simultaneously true. If ever revisited, it is a central relay the maintainer operates.
