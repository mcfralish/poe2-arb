# poe2-arb — TODO

What is **not** done. Shipped work is in [CHANGELOG.md](CHANGELOG.md); measured findings
and standing invariants are in [docs/FINDINGS.md](docs/FINDINGS.md). Completed items are
deleted rather than ticked, so this file stays worth reading start to finish.

## State of play

**Shipped:** v0.5.0 (2026-07-30) — the first field test and what it exposed. Two real
trades, both losses.

**v0.6.0 is on `main`, unreleased.** The second field test (2026-07-31) was the first
profitable session — **about 20 divines cleared** — and produced a defect list rather
than a measurement. Everything on it is now fixed: the global hotkey had never once
worked (a missing `import ctypes.wintypes` swallowed at debug level), the bankroll was
a per-trade allowance rather than a total, costs were shown in divines for
exalted-priced listings, both Trades history filters were structurally empty, *Ready to
whisper* was losing its alert seconds out of its listed time, and a dragged-shut
splitter could hide half the Opportunities tab permanently. Plus the queue reordering,
Decline-means-never, Copy again, per-unit and settlement columns, minutes in Settings,
always-on-top, and a swappable Quick Lookup. Full list in
[CHANGELOG.md](CHANGELOG.md); the durable half in [docs/FINDINGS.md](docs/FINDINGS.md).

**That session left 147 fully-resolved whispers in `outcomes.jsonl`**, read on
2026-07-31, and they **overturn the project's second-biggest finding**: ghosts fill at
2.3% (n=131), not at 0% — including one at 10.94× — and they earned 71% of the
session's divines on a fat tail. Plausible still wins per whisper sent (0.40 div vs
0.113), so the ranking stands, but `FILL_PRIOR[GHOST] = 0.0` is now measurably wrong.
Full tables in [docs/FINDINGS.md](docs/FINDINGS.md), *Negative results* 1. **This
unblocks "Fit the ranking to the outcome log" in *Next*, which no longer needs another
field test to start.**

*What the next field test must measure* below still blocks the **pricing** item — that
one needs a human in game and cannot be recovered from any log.

> **The app is not trustworthy for live trading on thin items.** It overstates resale by
> ~26% on anything that isn't liquid currency, and it doesn't know gold exists. Both are
> quantified in [docs/FINDINGS.md](docs/FINDINGS.md). The UI says so in the *uncertain* band
> tooltip and in Quick Lookup; the arithmetic underneath is still wrong.

**The shape of the app.** Toolbar: *Find trades* (a toggle — sweeps, waits, sweeps again)
and *Settings*. Tabs: *Opportunities* (the queue, plus bankroll, settlement, long-shots and
Quick Lookup), *Market* (the whole economy from poe.ninja), *Trades* (what the last sweep
found, filterable down to what you messaged or bought), *Results* (the whisper log — fill
rates and takings), *Log*.

## What the next field test must measure

The top item in *Next* is blocked on one observation, and it is cheap to collect but only
**while in game with a trade in front of you** — it cannot be recovered afterwards from any
API. If a trade is made in v0.5.0, record all four in the same session:

1. The **CE rate the app showed** for the item, and the settlement currency.
2. What the CE **actually paid** on the sale.
3. Both sides of the in-game book for that item if visible — the rate to **buy** it and the
   rate to **sell** it. This is the discriminator: a ~26% gap between those two says the
   error is *spread*, and a tight book says it is not.
4. The **time** of each reading, since one candidate explanation is a same-day price move.

Also worth confirming, because v0.6.0 changed them and nothing but a human can check:

- **The hotkey actually fires now** — this is the important one, since it has never
  worked in any shipped build and the fix is Windows-only, so no test covers it. Bind
  it, tick the box, press it in game, and confirm a whisper lands on the clipboard both
  while a trade is flashing and while one is merely sitting in *Ready to whisper*.
- Costs read in the seller's currency everywhere, and match what the whisper actually
  offered.
- Committed currency appears beside the bankroll boxes, and a trade you cannot afford
  is not offered until you answer for the one holding the money.
- Always-on-top floats over the game in borderless windowed.

**If the install error recurs:** `%LOCALAPPDATA%\poe2-arb\poe2-arb.log`, grep for
`install to ... failed` or `Start Menu shortcut`. The `--windowed` exe has no console,
which is why the original occurrence left no trace.

## Next

- [ ] **The reference price is ~26% high on thin items, and that is why the first two real
      trades lost money.** Full evidence in [docs/FINDINGS.md](docs/FINDINGS.md), "The
      reference price overstates thin items by ~26%". Not a parsing bug — we reproduce
      poe2scout's own number to 1.006×; the source is above what a thin sale realises.
      **Blocked on one question before any code:** the maintainer's later spot-check found
      poe2scout within ~10 ex of live, which can't be squared with the 3,361 seen at trade
      time unless the two readings were different sides of the book, or the price genuinely
      moved 34% in a day. That fork decides the fix:
      - *spread* → haircut proceeds, scaled by the item's own liquidity, and raise
        `MIN_PAIR_VALUE` (Astrid's cleared 1,000 by 67× and was still 65% wrong);
      - *which side was read in game* → guidance only, no pricing change;
      - *movement* → freshness, and show the price's age.
      Do **not** tune a constant before that is settled. Interim honesty is cheap and worth
      doing regardless: Quick Lookup already calls a thin figure a ceiling, and the
      *uncertain* band tooltip says the estimate has run 25% high.
- [ ] **Model gold, then let the app pick the settlement currency.** Measured 2026-07-30:
      ~120 gold per exalted, ~800 per divine. Exalted minimises the rounding floor and
      maximises the gold bill — settling ~3,000 exalted costs ~360,000 gold where the same
      value as ~7 divine costs ~5,600, and the maintainer ran dry mid-session. So the *Settle
      in* dropdown asks the user to solve a two-variable problem the app has the numbers for.
      Replace it with a recommendation: **the finest denomination whose gold cost fits the
      gold you hold.** Gold can't be bought for currency, so it is a constraint, not a term
      subtracted from profit — do not "convert gold to divines". Needs a gold-on-hand input
      (there is no API for it; the user must type it) and the per-orb rates confirmed across
      more than one price point, since 120/ex and 800/div may not be flat.
- [ ] **Fit the ranking to the outcome log. Unblocked — the data is already on disk**
      (156 resolved whispers in `outcomes.jsonl`; tables in
      [docs/FINDINGS.md](docs/FINDINGS.md), *Negative results* 1). Three separate pieces,
      in order of how well the evidence supports them:
      - *`FILL_PRIOR[GHOST] = 0.0` is measurably wrong* and is the one clear fix. Measured
        ratio is ~0.11 on fill rate, ~0.28 on value per whisper. n=131, so this is the
        best-powered number the project has. Pick which of the two the prior should
        express — `fill_weight` currently reads as a probability but is used to discount
        profit, which is the value-per-whisper question.
      - *`max_gap_ratio = 1.50` survives.* The fill-rate cliff sits between 1.5× and 2×.
        Leave it alone; the error was in what happens beyond it, not where it is.
      - *`min_gap_ratio = 1.05` is still unmeasured* — 2 whispers below 1.10×. It comes
        from our own price error and stays there until the pricing item lands.
      Then let the user apply `suggested_gap_band` from the Results tab, which already
      computes `value_per_attempt` — the right objective, and the one that reveals the
      ghost result. **Do not fit `min_gap` and the pricing correction independently:** both
      are the same measurement error wearing different hats.
- [ ] **The whisper budget is the real constraint, and nothing models it.** 131 ghost
      whispers in 63 minutes is ~2/minute, and that is why chasing a 2.3% fill rate paid:
      the message is nearly free. So "is this worth whispering?" has no answer that doesn't
      depend on how much session is left — a ghost is worth sending when the queue is empty
      and worth skipping when three plausible trades are waiting. `risk_appetite` is the
      user hand-solving this. Consider making it a rate ("whispers per minute I'm willing
      to send") that the ranking spends, rather than a taste slider.
- [ ] **Optional auto-paste on the hotkey.** One `SendInput` for Ctrl+V, as a setting
  defaulting to **off**. Never auto-Enter, never read chat.

## Open — UX

- [ ] **Items the exchange trades but poe.ninja doesn't price are missing.** The game
  shows five Zarokh's Reliquary Keys; we show one. **126 of GGG's 753 tradeable items have
  no poe.ninja price** (Runes 70, Waystones 16, Fragments 9, Essences 8, Expedition 6,
  Breach 5, Verisium 4, Ritual 4, Currency 2, Abyss 1, Gems 1). *Fix:* merge GGG's
  `/api/trade2/data/static` catalogue into the universe, unpriced rows showing an em-dash.
  **Not quick** — `Item.value_divine` is a float that sorting, adaptive units and
  `convert()` all assume is real, so unpriced items need a `priced` flag and a guard at
  each. Also: GGG's `sep` entries are separators, not items; and its groups don't map to
  in-game tabs for items poe.ninja doesn't categorise.
- [ ] **Org tree structures** in `src/poe2arb/gui/OrgTrees/*.txt`, one file per in-game
  tab, regenerated by `tools/dump_org_trees.py`. **Manual pass in progress** — the
  generated output is flat two-level, and each file is being hand-nested by group.
  `Currency.txt` is done and is the reference for the intended shape; the rest are
  partially through. Known weakness still to fix: `AtzirisTemple.txt` splits on the word
  "Vaal", which isn't a real distinction.
- [ ] **Hover tooltips explaining each item.** *Blocked on a source:* the exchange
  endpoint exposes only `id`, `name`, `image`, `category`, `detailsId` — no description
  text. Investigate a poe.ninja detail endpoint keyed on `detailsId`, or poedb. Decide
  before building.
- [ ] Large values read oddly in fixed non-adaptive units (a Mirror in `ex`). Adaptive
  mode covers the default case; decide whether fixed modes need scaling.
- [ ] **Quick Lookup's four denominations are hardcoded** (`lookup.DENOMINATIONS`). They are
  the ones the Exchange has depth in, which is a judgement that will age. poe2scout's
  `/ReferenceCurrencies` endpoint publishes the real reference set — exalted at exactly 1.0,
  chaos and divine alongside it — and would be the honest source.
- [ ] **poe2scout endpoints we never used.** `/openapi/v1.json` lists
  `Currencies/ByCategory` (paged, and it takes a `referenceCurrency`, so it answers "what is
  this worth in annul?" directly), `Currencies/{apiId}` with `PriceLogs` and `CurrentPrice`,
  `ReferenceCurrencies`, and `Items/PriceHistory`. `SnapshotPairs` is the only one the app
  reads, and it is the one that needs a derivation to be trusted. Worth evaluating as a
  replacement — `CurrentPrice` needs no `rel/base` arithmetic at all.
- [ ] Windows 11 hides new tray icons in the overflow, so closing the window while
  watching can look like the app vanished.

## Open — distribution

- [ ] Install flow unverified end-to-end on a real frozen exe. The v0.2.4 crash was
  exactly this gap — worth a manual run before relying on it.
- [ ] **Distribution hardening**: Microsoft false-positive submission (free), code-signing
  certificate (~$100–400/yr), `--onedir` as the free fallback.
- [ ] **Mobile push on a good trade.** Needs a delivery path — ntfy, Pushover, Telegram —
  plus a decision on whether the desktop app pushes directly.
- [ ] Packaging beyond one exe — PyPI for the CLI, Scoop/winget manifests.
