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
| spread | ~1% (measured 3.75 / 3.79 on Core Destabiliser) | meaningless |
| depth | millions of units | single digits |
| who uses it | effectively everyone | effectively nobody |

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

**1. Deep discounts do not fill. Gap size is an inverse credibility signal.**

| test | whispers | filled | gap on the fills |
|---|---|---|---|
| Core Destabiliser | 4 | 1 | 1.9× |
| Omen / Fragment | 10 | 1 | 1.13× |
| **total** | **14** | **2 (14%)** | both the smallest gaps sampled |

Roughly ten attempts at 3.8×–12.5× produced **zero** fills. A listing far below market is
a mistake, an abandonment, or already sold — its continued visibility is evidence it
*cannot* be taken. **Rank ascending by gap, not descending.** Any large-gap profit total
is fiction until a fill proves otherwise.

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
- **An unanswered whisper self-marks as NO_REPLY.** Silence is the majority outcome;
  leaving rows pending forever would bias the log toward whatever the user came back and
  clicked. Timeout 0 answers every one by hand.
- **Every action is one click on the row itself**, so the tables carry no selection — a
  highlight would imply a second step that doesn't exist. This constrains the redraw:
  countdowns tick every second, and rebuilding a row would destroy the button under the
  cursor mid-click, so `refresh` rebuilds only when the set of trades changes.
- **Action widgets must be unparented, not just removed, on rebuild.** `removeCellWidget`
  only schedules deletion; the orphan keeps painting at its old geometry until the event
  loop catches up, which put a live Accept/Decline on top of another row's Item column.
- **The live offer is pinned to the top even when a lapsed trade is worth more** — it is
  what the hotkey acts on. For the same reason the queue tables are **not sortable**.
- **Submissions are deduplicated against everything unfinished**, including already-
  whispered trades. Sweeps overlap, and re-offering would have the user message the same
  seller twice.
- **Ghosts are never queued** (`queue_ghosts=False`). Interrupting a map for something
  measured never to fill is pure cost. They stay visible in Trades.
- **A whispered trade cannot be dismissed, only resolved.** It is already recorded as an
  attempt; deleting it would bias the outcome log toward whatever the user answered.

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

### Operational

- **`request_interval_s` must stay above 10s.** At exactly 10s a 300s window catches 31
  requests against a limit of 30; the penalty is a 30-minute IP ban.
- **Per-user install, never Program Files.** Elevating an unsigned binary into a system
  directory is the dropper pattern we're avoiding.
- **Release notes come from `CHANGELOG.md`**, and a tag without a section fails the build
  before anything is compiled.
- **UI state lives in a JSON file in the cache dir**, not in the TOML config (meant to stay
  hand-editable) and not in QSettings (which would write to the registry, contradicting
  "delete the folder to remove it").
- **Nothing is excluded by default** — that's the user's call. **Exclusions don't apply to
  Quick Lookup**: excluding something from the sweep shouldn't stop you pricing it.
- **Tier ordering is by measured price, not the alphabet.** Numbers in `market.py`.
- **Menus cap at `MAX_ITEMS_PER_MENU` entries per submenu**; oversized groups split via
  `chunk_group` rather than relying on Qt to scroll off-screen.

### Rejected approaches

- **Currency Exchange API (`service:cxapi`) — not pursuing.** Requires a confidential
  OAuth client on an HTTPS domain the maintainer controls; public/desktop clients cannot
  use `service:*` scopes at all, so it can never ship inside the exe. It also serves hourly
  *historical* digests only. poe2scout covers the reference-price need.
- **No peer-to-peer data sharing between clients.** Federated edges arrive at different
  timestamps, so any cross-client assembly can produce opportunities that were never
  simultaneously true. If ever revisited, it is a central relay the maintainer operates.
