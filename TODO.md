# poe2-arb — TODO

What is **not** done. Shipped work is in [CHANGELOG.md](CHANGELOG.md); measured findings
and standing invariants are in [docs/FINDINGS.md](docs/FINDINGS.md). Completed items are
deleted rather than ticked, so this file stays worth reading start to finish.

## State of play

**Shipped:** v0.7.0 (2026-07-31). Three field tests behind it; the last two sessions were
profitable, and 0.7.0 is mostly the defect list the third one produced.

**Start here next session.** In order of what unblocks what:

1. **Confirm the hotkey finally fires** — third attempt, Windows-only, no test can cover
   it, and it is the cheapest check on the list. Bind it, tick the box, press OK, reopen
   Settings and press the key: the line under the field says whether it fired. That
   separates "the key never reached us" from "the queue had nothing to take", which the
   two previous attempts could not.
2. **The Send button / hotkey** (*Next*, first item) — agreed for this patch, researched,
   with a route decision waiting on the maintainer: sanctioned keystrokes versus the
   trade site's own endpoint and a session cookie. The table in that item is the whole
   argument; nothing else needs re-deriving.
3. **Fit the ranking to the outcome log** — still unblocked, still the best-powered data
   the project has (n=131 on the ghost result).

**What 0.7.0 changed, in one paragraph.** Two of 0.6.0's fixes were wrong rather than
incomplete: the hotkey had still never fired (Qt is now out of the delivery path
entirely), and the bankroll holdback is reverted because 79%+ of whispers go unanswered so
it suppressed more real trades than double-spends it prevented. Plus: listings are ratios
rather than bundles, so a 100-divine listing is buyable on a 20-divine bankroll;
opportunities queue as they are found rather than all at once; quantities are correctable
after the fact without erasing the original ask; sessions and leagues are stamped on every
whisper and the Trades tab reviews any of them; Results gained *Every trade*; columns
reorder, resize and persist. Full list in [CHANGELOG.md](CHANGELOG.md).

**The 147 fully-resolved whispers from the second session still stand** and still
**overturn the project's second-biggest finding**: ghosts fill at 2.3% (n=131), not at 0%
— including one at 10.94× — and they earned 71% of that session's divines on a fat tail.
Plausible still wins per whisper sent (0.40 div vs 0.113), so the ranking stands, but
`FILL_PRIOR[GHOST] = 0.0` is measurably wrong. Full tables in
[docs/FINDINGS.md](docs/FINDINGS.md), *Negative results* 1.

**What the 2026-07-31 log analysis added, so it is not re-derived.** `Client.txt` was read
end to end and joined against `outcomes.jsonl` — details in FINDINGS, the sections dated
2026-07-31. The short version: auto-marking *fills* is not worth building (all 11 were
already hand-marked correctly), splitting *NO_REPLY* is (76% silent / 22% AFK / the rest
replies and stale listings), GGG's API called 11 of 40 AFK sellers present, there is no
party roster in the log, and GGG publishes a Currency Exchange API carrying both sides of
the book that a desktop client cannot reach.

*What the next field test must measure* below still blocks the **pricing** item — that
one needs a human in game and cannot be recovered from any log.

> **The app is not trustworthy for live trading on thin items.** It overstates resale by
> ~26% on anything that isn't liquid currency, and it doesn't know gold exists. Both are
> quantified in [docs/FINDINGS.md](docs/FINDINGS.md). The UI says so in the *uncertain* band
> tooltip and in Quick Lookup; the arithmetic underneath is still wrong.

**The shape of the app.** Toolbar: *Find trades* (a toggle — sweeps, waits, sweeps again)
and *Settings*. Tabs: *Opportunities* (the queue, plus bankroll, settlement, long-shots and
Quick Lookup), *Market* (the whole economy from poe.ninja), *Trades* (what the current
session found, or any past session read back from the log), *Results* (the whisper log —
fill rates, takings, and every trade), *Log*.

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

Also worth confirming, because v0.7.0 changed them and nothing but a human can check:

- **The hotkey actually fires now.** Third attempt; it has never worked in any build, and
  the code is Windows-only so no test can cover it. **Check it in Settings first** — bind
  it, tick the box, press OK, reopen Settings and press the key: the line under the field
  says whether it fired. That separates "the key isn't reaching us" from "the queue had
  nothing to take", which the last two attempts could not.
- **Partial asks get answered.** Listings bigger than the bankroll are now whispered for
  the affordable fraction. Worth knowing whether the reply rate on those is materially
  worse than on whole-lot asks — it is a new class of whisper and the log can measure it,
  but only once some have been sent.
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
- [ ] **Split NO_REPLY using the game's own log.** Measured 2026-07-31 against 189 real
      attempts — full numbers in [docs/FINDINGS.md](docs/FINDINGS.md), "What the game's own
      log can and cannot tell us". The maintainer has lifted the "no reading game state"
      constraint for passive log reading (2026-07-31); what remains is worth deciding on
      the evidence, because the obvious feature is the worthless one:
      - *Auto-marking fills is not worth building.* All 11 fills in the sample were already
        hand-marked correctly; the log adds no trade the user missed. It would save clicks
        and nothing else.
      - *Splitting NO_REPLY is worth building.* 22% of it is GGG's AFK auto-reply, which
        lands within a second of the whisper rather than after a ten-minute timeout, and
        another ~2% is a reply or an "already gone". A quarter of the denominator under
        every fill rate in the project is currently one bucket that is really three.
      - *It also audits a source we already trust.* GGG's API called 11 of 40 AFK sellers
        present — 28% wrong, in the direction that matters — so the Results tab's *By
        seller state* split rests on a bad flag. Worth confirming on a bigger sample
        before changing anything that reads `afk`.
      Keep it **read-only and advisory**: mark a suggestion the user confirms, never write
      a verdict straight to the log. Tail from a stored offset (194 MB, append-only),
      prefer `LatestClient.txt` for a live session, derive the local-time offset by
      correlating rather than trusting the machine's zone, and match the AFK reply against
      the localised set — one log alone carries it in six languages.
- [ ] **A Send button that whispers the seller, instead of only filling the clipboard.**
      Agreed 2026-07-31 for the next patch; **research done, nothing built.** Evidence in
      [docs/FINDINGS.md](docs/FINDINGS.md), "GGG's trade site sends whispers server-side".

      **The route is a real decision and the research reversed the obvious answer.**
      Confirmed: the trade site delivers whispers server-side, on the Bulk Item Exchange
      as well as item search — the maintainer's tests appear in `Client.txt` before the
      game regains focus. But GGG's developer docs have **no trade, whisper or messaging
      scope, and no trade endpoint at all**, and `service:*` scopes are closed to public
      clients, which is what a desktop exe is. So:

      | | keystrokes | the site's endpoint |
      |---|---|---|
      | sanctioned | **yes** — "one action per key press", staff-confirmed | undocumented; impersonates the website |
      | credentials | none | `POESESSID`, a full account session, inside a shipped exe |
      | needs focus | yes — and from a *button*, needs `SetForegroundWindow` | no |
      | wrong-window risk | real | none |
      | logs a true attempt | only if the paste lands | always (4 of 189 logged attempts were never actually sent) |
      | tells you the listing died | no | yes — a failed whisper *is* the re-check, for free |

      **Recommendation: keystrokes, unless the maintainer is comfortable shipping a
      session cookie.** The UX of the endpoint is better on every axis except the one that
      decides whether it should exist. If it is chosen anyway: never write `POESESSID` to
      the TOML config or any log, keep it in Windows Credential Manager / DPAPI, and treat
      a 401 as "re-authenticate", not as a failed trade.

      *If keystrokes:* a button in the app means the app has focus, so this is the case
      that needs `SetForegroundWindow` — Windows grants it only to a process that received
      the last input event, it is asynchronous, and sending before the switch lands is
      exactly how these tools type into the wrong window. Verify the foreground actually
      changed, with a timeout, and abort rather than send blind. Then Enter → Ctrl+A →
      paste → Enter, pasting rather than typing because the whisper is GGG's own localised
      template (this log carries Korean, Chinese, Russian, Portuguese and Spanish).
      A hotkey pressed *in game* needs none of this — the game is already in front — so
      button and hotkey are two different problems and the hotkey is the easy one.

      **Either way it changes a hard constraint.** Rewrite CLAUDE.md and FINDINGS'
      *The line the app does not cross* in the same change, to:

      > one keypress or one click → exactly one message. Never on a timer, never in
      > reaction to a reply, never more than one action per press.

      Default **off**, `trade_hotkey_action = "copy" | "send"`, copy stays the shipped
      behaviour. And it is Windows-only and untestable here — the shape of code that
      shipped broken twice — so carry the Settings press-counter idea forward and log
      every message the app sends.

- [ ] **Thanking a seller to mark the trade — parked, and here is why.** The maintainer
      will use Sidekick's auto-thank rather than build this. Worth knowing before relying
      on it: measured 2026-07-31, "answer the last whisper **received**" is right in
      **7 of 11** real trades — much better than "last whisper sent" (2 of 11), and two of
      the four misses would thank a seller whose last message was `This player is AFK.`,
      an auto-reply that landed in between. Harmless as a message; it does mean **a "ty"
      in the log is not proof of a trade**, so those lines must not be parsed back as fill
      markers. Party scanning cannot fix it either — there is no party roster in
      `Client.txt` (checked). If this is ever built in-app, initiating it from the clicked
      row is the only unambiguous option.

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
- [ ] **GGG's own Currency Exchange API has both sides of the book — and we cannot reach
  it yet.** Found 2026-07-31; full detail in [docs/FINDINGS.md](docs/FINDINGS.md), "GGG
  publishes an official Currency Exchange API". `service:cxapi` returns per-pair
  `lowest_ratio` / `highest_ratio` / stock / volume, which is **exactly the both-sides
  measurement the pricing item above is blocked on** — poe2scout has no bid, no ask and no
  depth. Blocked on client type, not on effort: it is a confidential-client scope and a
  distributed exe is a public client. The public CDN URL in the docs serves a stale
  July-2024 PoE1 snapshot whatever `realm` or `id` you pass. Re-test when GGG widens PoE2
  API coverage; a small backend would unblock the project's biggest open question.
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
- [ ] **Bump the release workflow's actions off Node 20.** GitHub warned on the v0.7.0
  build (2026-08-01): `actions/checkout@v4` and `actions/setup-python@v5` target Node 20
  and are being forced onto Node 24, per
  [the deprecation notice](https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/).
  Four `uses:` lines in `.github/workflows/release.yml` — checkout and setup-python appear
  once each in both the `test` and `build-windows-exe` jobs; `softprops/action-gh-release@v2`
  was not flagged. Warning only today, so the release still builds; it becomes a broken
  release the day the forcing stops, and the only way to find out is to tag. Worth doing
  on a quiet day rather than discovering it mid-release.
- [ ] Packaging beyond one exe — PyPI for the CLI, Scoop/winget manifests.
