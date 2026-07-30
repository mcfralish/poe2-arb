# poe2-arb — TODO

What is **not** done. Shipped work is in [CHANGELOG.md](CHANGELOG.md); measured findings
and standing invariants are in [docs/FINDINGS.md](docs/FINDINGS.md). Completed items are
deleted rather than ticked, so this file stays worth reading start to finish.

## State of play

**Shipped:** v0.4.0 — triangular scan removed outright, continuous *Find trades* toggle,
Results tab, per-currency bankroll, long-shots slider, wrapping market tabs, rate-limit
readout.

**Unreleased on `main`:** the first field test happened on 2026-07-30 and produced two real
trades, both losses. Fixed since: the sweep's `cfg.league or "Standard"` fallback, stopping
the sweep now cancelling the un-offered backlog, the hotkey shipping greyed out, Market
exclusion ticks going stale, plus the UI pass below. **The reason both trades lost money is
not fixed** — see the next section.

> **The app is not currently trustworthy for live trading on thin items.** It overstates
> resale by ~26% on anything that isn't liquid currency, and it doesn't know gold exists.
> Both are quantified in [docs/FINDINGS.md](docs/FINDINGS.md).

**The shape of the app.** Toolbar: *Find trades* (a toggle — sweeps, waits, sweeps again)
and *Settings*. Tabs: *Opportunities* (the queue, plus bankroll, settlement and
long-shots), *Market* (the whole economy from poe.ninja), *Trades* (everything the last
sweep found, browsable), *Results* (the whisper log — fill rates and takings), *Log*.

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
- [ ] **Fit the ranking to the outcome log.** Every threshold is provisional:
  `min_gap_ratio` comes from our own price error, `max_gap_ratio` from 14 whispers with 2
  fills, and `listings.FILL_PRIOR` is three round numbers. The Results tab surfaces
  `suggested_gap_band` once buckets clear `MIN_SAMPLES` — the next step is letting the
  user apply it, and fitting `FILL_PRIOR` to measured fill rates instead of guessing.
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
