# poe2-arb — TODO

What is **not** done, and the findings that must not be re-derived. Shipped
work lives in [CHANGELOG.md](CHANGELOG.md); completed items are deleted from
here rather than ticked, so this file stays worth reading start to finish.

---

## State of play

**Shipped:** v0.2.8. Unreleased on `main`: the whole cross-venue feature below.

**What the app is now.** The original premise — same-venue arbitrage cycles —
is dead, and the evidence is under "The two markets". The live feature is
**cross-venue**: buy underpriced Bulk Item Exchange listings by whisper, sell
into the in-game Currency Exchange. Built and tested (612 tests): sweep,
candidate ranking, Trades tab, outcome logging, pre-whisper re-check, global
hotkey, and the offer queue. Also on the CLI as `poe2-arb sweep`, but the GUI is
the primary surface.

**The shape of the app.** *Trades* tab = everything a sweep found, browsable.
*Opportunities* tab = the queue, which offers one trade at a time with a toast
and an armed hotkey, and holds a second list of whispers awaiting a verdict.
The queue is where the workflow lives; the Trades table is for looking around.

**The cycle detector is demoted, not deleted.** `graph.py` and `scan.py` still
work and still pass their tests, and Scan/Watch still run them. It lost its tab
— the queue took that space — so `MainWindow.ops_table` is now built but never
parented; the history backload and `_refresh_tables` still populate it, which
keeps that code path alive and testable without showing an empty table nobody
needs. It is kept because it is correct code that becomes valuable if the
Currency Exchange ever exposes an order book. Anything below mentioning node
selection, skew, `depth_divines` or Bellman-Ford is about that dormant path.

**Venv:** `~/.venvs/poe2-arb/bin/python`. Tests: `python -m pytest -q`.
GUI tests need `QT_QPA_PLATFORM=offscreen`.

**How to verify GUI work without a display:** `QT_QPA_PLATFORM=offscreen`,
construct the widget, `app.processEvents()`, `widget.grab().save(path)`. This
has caught five real bugs the test suite did not — a startup `NameError`, a
Trends note that lied on thin data, the icon cache being 10x the predicted size,
`muted_color()` used as if it returned a `QColor`, and a whisper quoting the
wrong currency. Use it.

**If the install error recurs:** `%LOCALAPPDATA%\poe2-arb\poe2-arb.log`, grep
for `install to ... failed` or `Start Menu shortcut`. The `--windowed` exe has
no console, which is why the original occurrence left no trace.

---

## Queued

- [ ] **Bankroll should hold separate exalted and divine amounts.** One pooled
  figure in divines is wrong on both sides: listings are priced in either
  currency (exalted is the *more* common), and converting between them on the
  Currency Exchange costs a spread and a round trip. Someone holding 400 exalted
  and 2 divines can afford different trades than someone holding 3 divines, and
  the app currently cannot tell them apart. Needs the affordability cap in
  `plan_trade` to work per-currency rather than against one total.
- [ ] **User-settable deviation threshold**, so high-reward / low-probability
  trades surface at whatever rate the user wants. Today `max_gap_ratio` is a
  hard cutoff at 1.5x and everything past it is demoted to `GHOST` uniformly.
  The user should be able to ask for the long shots and have them ranked in,
  not merely visible at the bottom. Best expressed as a risk appetite
  (0 = only what reliably fills, 1 = rank purely on expected profit) weighting
  the band rather than replacing it. Once the outcome log has data the weighting
  can be fitted instead of guessed.

## Next

- [ ] **Fit the ranking to the outcome log.** Every threshold in the gap band is
  provisional: `min_gap_ratio` comes from our own price error, `max_gap_ratio`
  from 14 whispers with 2 fills. `outcomes.suggested_gap_band` already computes
  the band earning most per whisper and is deliberately advisory — surface it
  once buckets clear `MIN_SAMPLES`, then let the user apply it.
- [ ] **A Trades history view.** The outcome log has no reader in the UI: no
  "you've made 14 divines this week", no fill rate by band or by age.
  `outcomes.summarise` returns all of it; nothing displays it.
- [ ] **Optional auto-paste on the hotkey.** One `SendInput` for Ctrl+V, as a
  setting defaulting to **off**. Never auto-Enter, never read chat.

## Open — UX

- [ ] **Items the exchange trades but poe.ninja doesn't price are missing.**
  The game shows five Zarokh's Reliquary Keys; we show one. **126 of GGG's 753
  tradeable items have no poe.ninja price** (Runes 70, Waystones 16, Fragments 9,
  Essences 8, Expedition 6, Breach 5, Verisium 4, Ritual 4, Currency 2, Abyss 1,
  Gems 1). *Fix:* merge GGG's `/api/trade2/data/static` catalogue into the
  universe, unpriced rows showing an em-dash. **Not quick** — `Item.value_divine`
  is a float that sorting, adaptive units and `convert()` all assume is real, so
  unpriced items need a `priced` flag and a guard at each. Also: GGG's `sep`
  entries are separators, not items; and its groups don't map to in-game tabs
  for items poe.ninja doesn't categorise.
- [ ] **Org tree structures** in `src/poe2arb/gui/OrgTrees/*.txt`, one file per
  in-game Currency Exchange tab, regenerated by `tools/dump_org_trees.py`.
  **Waiting on the user's manual pass.** Two known weaknesses in the generated
  versions: `Currency.txt` lost its hand-written grouping (old version at commit
  `86a5bac`), and `AtzirisTemple.txt` splits on the word "Vaal", which isn't a
  real distinction.
- [ ] **Hover tooltips explaining each item.** *Blocked on a source:* the
  exchange endpoint exposes only `id`, `name`, `image`, `category`, `detailsId`
  — no description text. Investigate a poe.ninja detail endpoint keyed on
  `detailsId`, or poedb. Decide before building.
- [ ] Market tab bar scrolls at narrow widths (Expedition and Gems hide behind
  arrows at ~1000px). Options offered: smaller tab font, or wrap to two rows.
  Awaiting the user's preference.
- [ ] Large values read oddly in fixed non-adaptive units (a Mirror in `ex`).
  Adaptive mode covers the default case; decide whether fixed modes need scaling.
- [ ] Windows 11 hides new tray icons in the overflow, so closing the window
  while watching can look like the app vanished.

## Open — distribution

- [ ] Install flow unverified end-to-end on a real frozen exe. The v0.2.4 crash
  was exactly this gap — worth a manual run before relying on it.
- [ ] **Distribution hardening**: Microsoft false-positive submission (free),
  code-signing certificate (~$100-400/yr), `--onedir` as the free fallback.
- [ ] **Mobile push on a good trade.** Needs a delivery path — ntfy, Pushover,
  Telegram — plus a decision on whether the desktop app pushes directly.
- [ ] Packaging beyond one exe — PyPI for the CLI, Scoop/winget manifests.

---

## The two markets

Path of Exile 2 has **two currency economies that do not share prices.**

| | Currency Exchange | Bulk Item Exchange |
|---|---|---|
| where | in game | `trade2/exchange`, and the site's "Bulk Item Exchange" tab |
| mechanism | pooled, automated | player listings, whisper + party |
| works offline? | yes | no |
| spread | ~1% (measured 3.75 / 3.79 on Core Destabiliser) | meaningless |
| depth | millions of units | single digits |
| who uses it | effectively everyone | effectively nobody |

**`POST /api/trade2/exchange/{league}` serves the abandoned one.** The pooled
book is not exposed on it at all. Three structural proofs, so nobody re-tests:

- **The reverse direction is empty.** `want=divine, have=core-destabiliser`
  returns `total=0` where the game shows 1,110 depth. Same for
  `want=divine, have=chaos`, the deepest pair in the game.
- **Prices are integers.** Every listing is `pay N : get 1`. It can express 3,
  4, 5, 10, 55 divine per Core Destabiliser; it cannot express 3.79.
- **Depth is off by 10^3.** Game stock 1,110 / 4,662 / 13,035 versus 1, 2, 3, 10.

Ruled out along the way: pagination (all 272 cached divine/core-destabiliser
offers were 1:1 at every page), the `engine: new` flag, and the realm-qualified
URL `/api/trade2/exchange/poe2/{league}` (byte-identical response).

**Always send `status: online`.** Without it, 96% of results are dead listings
and GGG's best-ratio-first ordering fills page 1 with 1:1 junk:

```
want=core-destabiliser have=divine
  no status filter   total=252, all 100 fetched are 1:1
  + status:online    total=11,  ratios 1, 3, 4, 5, 10, 20, 25, 40, 50, 55
```

98% of unfiltered listings are offline and 74% over a week old. Offline
listings are also unwhisperable — they carry no `whisper` or
`lastCharacterName` — so there is nothing to lose by excluding them.

### poe2scout is the Currency Exchange price source

**`https://api.poe2scout.com`** — public REST, no OAuth, not on GGG's rate
limiter. Spec at `/openapi/v1.json`, Swagger UI at `/swagger`. Realm `poe2`.

```
GET /{realm}/Leagues/{leagueName}/SnapshotPairs    ~1,545 pairs, ~2 MB
```

**Exactly one derivation is verified:** `item.RelativePrice /
divine.RelativePrice`, from a pair where both sides have real traded value.
Measured against in-game screenshots: −0.4%, −0.7%, −1.7%, −1.0%, −4.7% across
five items, versus poe.ninja's −5.2% to +9.0%. Every error is slightly negative,
consistent with a volume-weighted traded price rather than best-of-book — which
is the better estimate of what a sale realises anyway.

**Everything else about this API was tested and is untrustworthy:**

- `RelativePrice` is **not** a price in the base currency. Exalted's own value
  should be 1.0; the median is 1.185, and gating to high volume makes it *worse*
  (1.258). Deriving prices via exalted pairs instead of divine disagrees with the
  divine derivation by a median of **49.6%** — and the divine one is what matches
  the game.
- Treating `RelativePrice` as base-denominated across all pairs gives −4% to
  −11.5% errors and a 1.51x median spread within a single item, for 12% more
  coverage. Not worth it.
- **Thin pairs are noise.** A pair with 1–5 lifetime trades prices items 25x
  wrong. `MIN_PAIR_VALUE` exists for exactly this.
- **There is no bid, no ask and no depth anywhere in this API.** CE order-book
  arbitrage is not detectable from it by anyone, us included.
- **No triangular arbitrage inside the CE.** 3-cycle products sit at a median of
  exactly 1.0000 at every volume gate with a symmetric tail — the signature of
  noise in an averaged statistic, not arbitrage. The apparent 10x cycles all ran
  through pairs with 1–5 lifetime trades.

`value_traded` is used for **ranking only** — the same unit for every item, so
"which items trade" is answerable even though "how many divines" is not.

### Which items to sweep

Selection is **CE exit liquidity**: an underpriced listing is worthless if the
Exchange won't absorb the item afterwards. Rank by `ValueTraded`, gate on value.

```
value >= 2 div AND CE volume >= 100k  ->  65 items, ~14 min/sweep
   top 25 -> 5.4 min, 84.7% of candidate CE volume
```

Comfortably inside the observed churn window. **Only 5 of the 65 are currency**
— the bulk is Lineage Support Gems, Fragments, Ritual omens and Abyss. The app
spent its first eight versions scanning ten currency items, which is close to
exactly the wrong place.

### Negative results — do not re-derive

**1. Deep discounts do not fill. Gap size is an inverse credibility signal.**

| test | whispers | filled | gap on the fills |
|---|---|---|---|
| Core Destabiliser | 4 | 1 | 1.9x |
| Omen / Fragment | 10 | 1 | 1.13x |
| **total** | **14** | **2 (14%)** | both the smallest gaps sampled |

Roughly ten attempts at 3.8x–12.5x produced **zero** fills. A listing far below
market is a mistake, an abandonment, or already sold — its continued visibility
is evidence it *cannot* be taken. **Rank ascending by gap, not descending.** Any
large-gap profit total is fiction until a fill proves otherwise.

**2. There are no bulk sellers on the Bulk Item Exchange.** Probed 8 items for
the "real seller shaving price to move volume" profile:

```
listings below CE, by gap x stock
       gap   stock 1-2   stock 3-9   stock 10+
  1.0-1.2x          12           1           0
  1.2-1.5x           4           0           0
    1.5-3x           2           1           1
       >3x           8           2           0
```

The plausible-gap / real-depth quadrant is empty. Profit does **not** scale with
quantity here; the ceiling is about a divine per fill.

**3. Cheap items yield nothing.** Probed live: chaos (0.11 div) and
greater-chaos-orb (0.34 div) had *zero* listings below CE. The value gate stays,
but for this reason — not for the rounding reason it originally had.

### Denomination — the correction that mattered most

**Exalted is the *more* common denomination.** 3,502 cached listings priced in
exalted against 2,882 in divine, with 65% more distinct price points (135 vs 82)
— 1 divine is a coarse unit, which is part of why divine-priced listings
quantise into 1:1 junk. GGG accepts a list of `have` currencies, so asking for
both costs one request. The first sweep after the change surfaced a
plausible-band candidate that was exalted-priced and invisible before it.

**The settlement currency decides the rounding haircut.** Proceeds floor to
whatever you take payment in, and exalted is ~432x finer:

```
bought 1 Core Destabiliser for 2 divines, CE value 3.79
   settle in divines   -> 3.0000   profit 1.00   lost 0.79
   settle in exalted   -> 3.7894   profit 1.79   lost 0.0006
```

**The one trade that filled was settled in divines and gave up 44% of the
realisable profit to rounding.** The CE trades these items against exalted,
chaos *and* divine, so it is a free choice at sale time. Items whose lots can
clear the floor go from **89 of 635 (14%) to 528 (83%)** on this change alone.

---

## Reference: taxonomies that don't agree

**Decision: the UI models the in-game selection**, not poe.ninja's categories
and not GGG's API groups.

In-game tab order (authoritative for the UI): All, Currency, Essences, Delirium,
Breach, Abyss, Atziri's Temple, Fragments, Runes, Ritual, Soul Cores, Idols,
Uncut Gems, Expedition, Gems.

| poe.ninja | in-game tab |
|---|---|
| Currency, minus the 15 Vaal items | Currency |
| those 15 Vaal items | **Atziri's Temple** |
| Essences / Delirium / Breach / Abyss / Runes / Ritual / SoulCores / Idols / UncutGems / Fragments | same name |
| Expedition **+ Verisium** | **Expedition** |
| LineageSupportGems | **Gems** |

**GGG's API groups are for trading only, never display.** `Vaal` holds SoulCores
+ Currency; `Ritual` holds Ritual + Idols + Fragments + SoulCores; `Expedition`
holds Expedition + Idols + Runes; `Delirium` holds Delirium + Fragments. Mapping
the UI to them would merge tabs the game keeps apart.

poe2scout uses a **fourth** taxonomy (adds `incursion`, `vaultkeys`,
`ultimatum`, `idol`). It is a pricing source; do not wire it to the UI.

Also worth not rediscovering:

- **`sep` is a separator, not an item.** Filter GGG's `sep` rows out or they
  become phantom items.
- **Waystones are tradeable but entirely unpriced by poe.ninja** (0 of 16).
- **76 of 213 runes are unpriced**, mostly `lesser-*`; ~137 are usable.

---

## Deliberate decisions — do not "fix" these

**The line the app does not cross**

- **Analysis only.** Never automates any in-game action, trade, whisper or
  input. Automating trading violates GGG's ToS. Hard requirement, not a gap.
- **The hotkey writes to the clipboard and nothing else.** No synthetic input,
  no reading game state, no watching chat, never auto-Enter. The user pastes and
  sends — the same thing the trade site's own copy-whisper button does. An
  optional Ctrl+V auto-paste may ship as an off-by-default setting; reacting to
  a reply may not.

**The offer queue**

- **Exactly one trade is OFFERED at a time.** A second toast arriving while the
  first is unread makes both of them noise. The queue enforces this; the window
  simply announces whatever `tick()` promotes.
- **An unclaimed offer lapses into AVAILABLE rather than vanishing.** It is
  still a good trade — it just isn't worth a second interruption. That is what
  makes interrupting acceptable at all: ignoring a toast costs nothing.
- **The three windows are independent and all user-settable**, and must stay
  ordered alert < listed < auto-resolve. The alert window (`offer_window_s`,
  20s) gates how fast the queue drains, *not* how long the user has to decide —
  an unclaimed offer isn't lost, it drops into the list below for
  `available_ttl_s` (5 min). A whisper then has `awaiting_timeout_s` (10 min)
  before it records itself as NO_REPLY. Changing any of them in Settings
  takes effect immediately; needing a restart for a countdown you just shortened
  looks broken.
- **An unanswered whisper self-marks as NO_REPLY.** Silence is the overwhelming
  majority outcome, and leaving rows pending forever would bias the log toward
  whatever the user came back and clicked. Set the timeout to 0 to answer every
  one by hand.
- **Every action is one click on the row itself**, so the tables carry no
  selection at all — a highlight would imply a second step that doesn't exist.
  This constrains the redraw: the countdowns tick every second, and rebuilding a
  row would destroy the button under the cursor mid-click, so `refresh` rebuilds
  only when the set of trades changes.
- **Action widgets must be unparented, not just removed, on rebuild.**
  `removeCellWidget` only schedules deletion; the orphan keeps painting at its
  old geometry until the event loop catches up, which put a live Accept/Decline
  on top of another row's Item column.
- **The live offer is pinned to the top of the list even when a lapsed trade is
  worth more.** It is what the hotkey acts on and what the countdown refers to;
  burying it would misrepresent what pressing the key does.
- **The queue tables are deliberately not sortable.** A click that reordered
  them would move the live offer away from the top.
- **Submissions are deduplicated against everything unfinished, including
  already-whispered trades.** Sweeps overlap, and re-offering would have the
  user message the same seller twice.
- **Ghosts are never queued** (`queue_ghosts=False`). Interrupting a map for
  something measured never to fill is pure cost. They stay visible in Trades.
- **A whispered trade cannot be dismissed, only resolved.** It is already
  recorded as an attempt; deleting it would silently bias the outcome log
  toward whatever the user bothered to answer.

**Cross-venue ranking**

- **`bait_filter_ratio` is inverted for cross-venue work, not deleted.** For
  same-venue cycles an offer far better than fair really is bait; for
  cross-venue it is the entire signal. Whichever mode runs decides whether the
  rule rejects or ranks — do not collapse it to one behaviour.
- **Never rank by gap alone — but the reason is unsettled.** On Core
  Destabiliser the cheapest listings vanished within 25 minutes while 4–55x
  listings persisted for days; on Faded Crisis Fragment the 1-div listings were
  still live at 2d19h. Record freshness and AFK; let the outcome log decide
  their weight. Do **not** hard-code "fresh beats big" until the data says so.
- **Ghosts are shown and sorted last, never hidden by default.** Hiding them
  would make the ranking unfalsifiable.
- **Profit is floored to the settlement unit, over whole lots.** Never report
  `gap x quantity`.
- **`Candidate.key` is content-derived, never `id()`.** A candidate stored in a
  Qt item and read back is not guaranteed to be the same Python object; `id()`
  silently fails to match and the queue re-offers listings already whispered.
- **`pay_currency` must not be "simplified" away.** A sweep mixes denominations
  in one table: `Listing.price_per_unit` is in the seller's currency and
  `Candidate.unit_price_divines` is the comparable one. Conflating them produced
  a whisper offering 5.58 exalted for a listing wanting 2400.
- **An attempt is logged when the whisper is copied, not when it succeeds.**
  Logging only successes would produce a file in which everything fills.
- **`SOLD` and `NO_REPLY` stay distinct** even though both mean "no trade". A
  seller who answers was reachable; silence may mean either. Collapsing them
  hides which problem freshness filtering actually solves.
- **A failed re-check counts as "go ahead".** Unknown is not evidence of
  absence; don't talk the user out of a real trade because a request failed.
- **No fill rate is claimed below `MIN_SAMPLES`.** 2 of 14 was enough to see a
  direction and nowhere near enough to state a rate.

**Operational**

- **`request_interval_s` must stay above 10s.** At exactly 10s a 300s window
  catches 31 requests against a limit of 30; the penalty is a 30-minute IP ban.
- **Per-user install, never Program Files.** Elevating an unsigned binary into a
  system directory is the dropper pattern we're avoiding.
- **Release notes come from `CHANGELOG.md`**, and a tag without a section fails
  the build before anything is compiled.
- **UI state lives in a JSON file in the cache dir**, not in the TOML config
  (meant to stay hand-editable) and not in QSettings (which would write to the
  registry, contradicting "delete the folder to remove it").
- **Nothing is excluded by default** — that's the user's call.
- **Exclusions don't apply to Quick Lookup.** Excluding something from the scan
  shouldn't stop you pricing it.
- **Tier ordering is by measured price, not the alphabet.** "Greater" sorts
  before "Lesser" while outranking it; "Ancient" measures *below* its plain
  counterpart. Numbers in `market.py`.
- **Menus cap at 30 entries per submenu**; oversized groups split rather than
  relying on Qt to scroll off-screen.

**Rejected approaches**

- **Currency Exchange API (`service:cxapi`) — not pursuing.** Requires a
  confidential OAuth client on an HTTPS domain the maintainer controls;
  public/desktop clients cannot use `service:*` scopes at all, so it can never
  ship inside the exe. It also serves hourly *historical* digests only, so it
  would not replace a live book. poe2scout covers the reference-price need.
- **No peer-to-peer data sharing between clients.** Cost is ~n^2/have_chunk, so
  pooling across P peers buys only sqrt(P) graph width. Federated edges also
  arrive at different timestamps, and Bellman-Ford will happily assemble a cycle
  from edges that were never simultaneously true — a phantom-arb generator that
  looks legitimate. If ever revisited, it is a central relay the maintainer
  operates, not P2P.

**Dormant cycle-detector decisions** (relevant only if the CE exposes a book)

- **Skew is reported, never used to reject a cycle.** Measured on a real scan
  (38 edges over 4.7 min): of 23 complete 3-cycles, skew ran 60s / 220s / 263s
  (min / median / max). A 90s cap keeps 1 of 23. What survives such a cap is
  decided by iteration order in `fetch_books`, not by data quality.
- **Node selection by volatility score was designed and never built.** It
  optimises a same-venue detector running on the wrong market's prices. The
  reasoning — volatility is not `totalChange`; volume is a `log1p` tiebreaker,
  not a driver; cycles need a connected core — is in git history at the commit
  that removed this section. **Do not implement as written.**
