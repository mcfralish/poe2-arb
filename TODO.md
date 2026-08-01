# poe2-arb — TODO

What is **not** done. Shipped work is in [CHANGELOG.md](CHANGELOG.md); measured findings
and standing invariants are in [docs/FINDINGS.md](docs/FINDINGS.md). Completed items are
deleted rather than ticked, so this file stays worth reading start to finish.

## State of play

**Shipped:** v0.7.0 (2026-07-31). **Four field tests behind it.** The fourth ran on
2026-08-01 across four sessions and 969 log records; its defect list is below and **none of
it is built** — the session was intake only. Evidence for all of it is in
[docs/FINDINGS.md](docs/FINDINGS.md), *Found in the fourth session of real use*.

**Start here next session.** In order of what unblocks what:

1. **A real fill is being logged as `no_reply`** (*Next*) — the five-minute auto-expiry
   wrote a false verdict three and a half minutes *after* the trade completed, on the
   biggest gap the project has ever hit. It corrupts the file every fill rate is computed
   from, so every measurement below inherits it. Fix this before fitting anything.
2. **Did the ghost fills fill at the listed price, or at a counteroffer?** (*Next*) — the
   one ghost fill observed on 2026-08-01 was a counteroffer at **10× the listed price** and
   lost money on a record claiming +38 div. If the n=131 sample's fills were the same, the
   ghost result is overstated and possibly negative. `Client.txt` can answer it without a
   field test. **This now blocks the ranking item**, which was previously unblocked.
3. **The hotkey works, and the fix left to build is the diagnostic** (*Next*) — root-caused
   and confirmed 2026-08-01: `RegisterHotKey` was being refused because **Sidekick owns the
   combination**, and it fired for the first time ever once Sidekick was quit. It is
   first-come-first-served, so it regresses the moment Sidekick starts first. Report the
   refusal and retry; do not touch the delivery path.
4. **Pricing is unblocked and one branch of it is dead** (*Next*) — the book is tight
   (~2%), so the liquidity haircut must not be built; the error is movement, so build
   freshness. One un-measured cell left: a genuinely thin item.
5. **The Send button** (*Next*) — route **decided: keystrokes**. Unblocked, ordinary work.

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

**— and 2026-08-01 put that correction itself in doubt.** The single ghost fill observed
that day was a **counteroffer at 10× the listed price** that lost money while logging
+38.00 divines of expected profit. If the 3.92× and 10.94× fills in the n=131 sample were
counteroffers too, ghost value-per-whisper is overstated and may be negative. Neither the
original claim nor its correction is safe to restate until `Client.txt` is checked for
those specific attempts.

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

**Mostly answered on 2026-08-01, and it needed no trade at all** — reading both sides of
the book while standing still was enough, which is worth remembering next time this file
says something is blocked on a completed trade. Results in
[docs/FINDINGS.md](docs/FINDINGS.md). **One cell is still empty:**

1. **Astrid's Creativity** — both sides of the in-game book, plus the app's Quick Lookup
   figure read within a minute, plus the clock time. It carries 110k `ValueTraded` against
   1.6M and 10.0M for the two items already measured, and it is the item that was **65%
   wrong** on 07-30. Every "tight book" conclusion currently stops at ~1M and is assumed
   below it; this is the only genuinely thin reading the project would have. Any other
   ~100k pair does the same job if Astrid's has moved.

The method, for reuse: in-game quotes read **"I want : I have"**, so the first row of a
pair is what you pay to **buy** and the second is what you **receive** to sell. Take the
app's number within a minute of the game's — the whole point is that they move.

Also worth confirming, because v0.7.0 changed them and nothing but a human can check:

- ~~The Settings press counter, for the hotkey.~~ **Answered 2026-08-01 and no longer
  needs a field test.** The line read *"Not listening…"* with the box ticked and the
  binding saved, which root-causes it to a refused `RegisterHotKey` — a desk problem now,
  not an in-game one. See the hotkey item in *Next*.
- **Partial asks get answered.** Listings bigger than the bankroll are now whispered for
  the affordable fraction. Worth knowing whether the reply rate on those is materially
  worse than on whole-lot asks — it is a new class of whisper and the log can measure it,
  but only once some have been sent.
- Always-on-top floats over the game in borderless windowed.

**If the install error recurs:** `%LOCALAPPDATA%\poe2-arb\poe2-arb.log`, grep for
`install to ... failed` or `Start Menu shortcut`. The `--windowed` exe has no console,
which is why the original occurrence left no trace.

## Next

- [ ] **Auto-expiry writes false verdicts into the outcome log, and it did it to the
      biggest trade the project has made.** Measured 2026-08-01: Rigwald's Ferocity, 1
      divine against a CE reference of 137.86, whispered 23:06:04, traded 23:07:30 (`ty` in
      `Client.txt`), auto-marked `no_reply` at 23:11:03 — **three and a half minutes after
      the trade completed**. Every fill rate in the project is computed from this file, so
      this is not a display bug. Three things to decide, and they are separable:
      - *An expired row must stay reachable.* The log already handles it — verdicts apply
        in file order, so a later record wins, and `9adaaa859e10` carries `no_reply` then
        `filled` from a real correction. The UI offers no route back. Editing the result
        from the Trades tab (see the UI section) is the same fix and probably the whole fix.
      - *Retire `NO_REPLY` as a button.* **Decided 2026-08-01 with the maintainer**, who
        never presses it meaning "silence": the timeout writes **Expired**, and the manual
        buttons become **AFK** and **Offline**, which is the only reason it gets pressed by
        hand. That is the same three-way split the *Split NO_REPLY* item below derives from
        the game log (76% silent / 22% AFK / the rest replies), arrived at independently
        from the button the user actually wanted — and `Client.txt` can mark Offline
        automatically, since `: <char> is not online.` is already there.
        **`outcomes.jsonl` keeps returning `no_reply` records forever**, so the enum gains
        members rather than renaming one, and every reader resolves the old value — the
        same constraint as `bands.symbol_for_name`.
      - *Whether five minutes is right* — but see the pin item below, which is the better
        answer. Both false expiries measured this session were **answered** whispers.
- [ ] **Did the ghost fills fill at the listed price, or at a counteroffer? Answerable
      today, from `Client.txt`, with no field test.** On 2026-08-01 the one ghost fill was
      a counteroffer at **10× the listed price**: the app offered 5 Faded Crisis Fragments
      for 5 divine (CE 8.75), the seller answered `10 div` / `so 50 div total 5x 10`, and
      the trade lost money against a real CE of ~9.4 while the log recorded
      `expected_profit_divines: 38.0`. If the 3.92× and 10.94× fills behind the n=131 ghost
      result were the same thing, **the headline correction of 0.7.0 is measuring seller
      haggling, not fills**, and ghost value-per-whisper is overstated or negative. Join
      those attempt ids to `@From` lines in `Client.txt` and read what the seller actually
      quoted. Two consequences either way: a counteroffered trade must be **amendable in
      price, not just quantity** (the existing amendment record already carries
      `cost_divines`), and a ghost listing that has sat for hours is evidence the seller
      will not honour it — which is a rankable signal, not just noise.
- [ ] **Pin a row so it stops counting down.** Requested 2026-08-01, and the log had
      already produced the case twice that evening: **both false expiries were sellers who
      had answered.** One replied `map` / `finish`, was expired six minutes before the
      trade, and was hand-corrected afterwards; the other was mid-trade when the timer
      fired. A pinned row **sorts to the top, holds a distinct highlight** (not the band
      colour — this is state, not risk) and never auto-expires. It is the honest fix for
      "is five minutes right?": the answer is that a seller who has spoken is no longer on
      a clock. Cheap and worth doing before any timeout tuning. Pin state is per-session UI
      and does not belong in `outcomes.jsonl`.
- [ ] **Stop re-whispering listings already resolved this session, and give the sweep a
      real pause.** Measured 2026-08-01: the same stale listing went out **five times
      across four sessions in 3½ hours**, twice to a seller the game answered `is not
      online` for, and once to a seller already traded with — because a Bulk listing does
      not delist when the stock is gone. Two requests, and they are one design:
      - *Suppress a listing marked Traded or Already sold* for the rest of the session.
        Key on the listing, not the row: seller account + item + ratio, since the id is
        regenerated each sweep.
      - *A restart of Find trades must not re-scan the same items immediately.* The
        maintainer uses the toggle as a pause when replies pile up, and gets a fresh round
        of duplicate whispers for it. Either resume the sweep where it stopped, or build an
        explicit **Pause** that holds the queue without ending the session. Note
        `session.py` already treats a toggle mid-session as *continue*, so the session
        boundary is not the thing that needs changing.
- [ ] **The hotkey is never bound — `RegisterHotKey` is returning 0. Diagnosed 2026-08-01;
      the previous three fixes were all in the wrong half of the path.** Settings reports
      *"Not listening…"* with the box ticked and a fresh binding saved, which is the
      `not hk.active` branch, which means `_pump.ok is False`. Full reasoning in
      [docs/FINDINGS.md](docs/FINDINGS.md), 2026-08-01. **Do not write another delivery-path
      fix.** In order:
      - *Make the failure speak.* On a false return, call `GetLastError`, log it, and emit
        `error` — `hotkey.py:176-183` currently returns silently, which is why three
        releases could not see this. Surface it in Settings as its own status: *refused*
        is a third state the line cannot currently express, and shipping only this much
        would already have saved two releases.
      - *The cause is confirmed: **Sidekick owns the combination**.* Quitting Sidekick and
        rebinding made the hotkey fire, in the app and in game — **the first time it has
        ever worked in any release** (2026-08-01). Restarting Sidekick afterwards did not
        take it back. Note the maintainer has **no `ctrl+shift+c` binding in Sidekick's own
        config**, so no amount of looking would have found this.
      - *Test the binding **before** saving it — the maintainer's call, 2026-08-01, and the
        primary fix.* There is no Win32 "who owns this key?" query, so the test is a trial
        `RegisterHotKey` followed immediately by `UnregisterHotKey`: if it is refused, tell
        the user in the dialog and do not let the setting save clean. Three traps:
        (a) **unregister our own binding first**, or the trial collides with the app's live
        hotkey and reports every existing binding as taken; (b) it is a **race** — another
        program can take the key between the check and the save — so the real registration
        must still report failure, the pre-check is a better message and not a guarantee;
        (c) run the trial **on the pump thread**, since `RegisterHotKey` is thread-affine
        and a key registered from the GUI thread posts `WM_HOTKEY` somewhere nothing is
        listening. That third one is close to the bug this whole item is about.
      - *It is first-come-first-served, so it will regress and the fix must assume that.*
        The working order is poe2-arb before Sidekick, which is the opposite of the normal
        one — Sidekick launches with the game, so a reboot is enough to lose it silently.
        So the pre-check is necessary but **not sufficient**: also retry registration on a
        timer or when the window is next shown, so a hotkey lost to startup order comes
        back on its own, and offer to pick a free combination.
      - *Overlay research is now optional, not blocking.* Focus was never implicated, so
        the maintainer's overlay question stands on its own merits rather than as a hotkey
        workaround. Keep it as research: always-on-top borderless already works, and a
        click-through DirectX overlay is a different program.
      The Settings press counter is **not** the diagnostic that mattered — a key that was
      never registered cannot count presses. Its successor is a *refused* state.
- [ ] **The reference price question is UNBLOCKED — the fork resolved to *movement*, and
      the spread branch is disproved.** Measured 2026-08-01 off both sides of the in-game
      book against the app's own snapshot minutes later; table in
      [docs/FINDINGS.md](docs/FINDINGS.md), "The reference price does not match what a sale
      realises", 2026-08-01 subsection. The book is **~2% wide** on Faded Crisis Fragment
      and Omen of Whittling against a 1.7% liquid control, and the app's error on those two
      was **−5.9% and +6.5% — opposite signs, minutes apart.** Omen of Whittling was +37% on
      07-30 and +6.5% today. So:
      - **Do not build the liquidity-scaled haircut.** It corrects for a spread that is not
        there. This was the leading candidate and it is dead.
      - **Build freshness instead.** Show the reference price's age, and distrust or refuse
        a stale one. `snapshot_age_s` already exists and nothing surfaces it.
      - **Reset `min_gap_ratio` from the noise, not from a bias.** ±6% of error around the
        mid means a 1.05 threshold admits trades whose whole edge is inside the error bar
        on the number that found them. The old conclusion ("1.05 is too tight") survives;
        every step of the reasoning under it has been replaced.
      - **`MIN_PAIR_VALUE = 1000` still looks far too low**, but the argument for raising
        it now rests on the un-measured cell below rather than on the spread claim.
      **The one gap left is genuinely thin items.** Both items measured carry ~1.6M and
      10.0M `ValueTraded`; **Astrid's Creativity (110k), the item that was 65% wrong, was
      not re-read.** Tight books are established for ~1M+ pairs and *assumed* below that.
      One in-game reading closes it — see *What the next field test must measure*.
      Interim honesty stays cheap and correct regardless: Quick Lookup calls a thin figure
      a ceiling, and the *uncertain* band tooltip says the estimate has run high — though
      that tooltip's "25% high" wording is now over-specific and one-directional, and
      should say the estimate carries ~±6% and more on thin items.
- [ ] **Model gold, then let the app pick the settlement currency.** Measured 2026-07-30:
      ~120 gold per exalted, ~800 per divine. Exalted minimises the rounding floor and
      maximises the gold bill — settling ~3,000 exalted costs ~360,000 gold where the same
      value as ~7 divine costs ~5,600, and the maintainer ran dry mid-session. So the *Settle
      in* dropdown asks the user to solve a two-variable problem the app has the numbers for.
      Replace it with a recommendation: **the finest denomination whose gold cost fits the
      gold you hold.** Gold can't be bought for currency, so it is a constraint, not a term
      subtracted from profit — do not "convert gold to divines". Needs a gold-on-hand input
      (there is no API for it; the user must type it). **The rates are confirmed flat
      (2026-08-01)** — 120/ex and 800/div whatever the quantity — so the gold bill is
      units-settled × rate, no rate table required. Blocked on nothing but the work now.
- [ ] **Fit the ranking to the outcome log. Data is on disk, but this is now blocked on
      the counteroffer question above** — the ghost number it turns on may be measuring
      counteroffers rather than fills, and two of the three pieces below rest on it
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

      **Decided 2026-08-01: keystrokes.** The maintainer chose it over the endpoint, so
      `POESESSID` is off the table and the trade site's endpoint needs no further research
      — drop it if it comes up again. What the endpoint would have bought us is worth
      remembering rather than re-arguing: it logs a true attempt (4 of 189 logged attempts
      were never actually sent) and a failed whisper doubles as a listing re-check. Both
      are now problems the keystroke route has to solve some other way, or accept.

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

## Open — UI, from field test 4 (2026-08-01)

The maintainer's list from the fourth session, grouped by surface. Small individually;
several are the same change made in two places, and the two renames below collide, so read
the whole section before starting. Screenshots of the minimum-width and bankroll problems
were supplied in the intake conversation and are not in the repo.

**Two tabs are being renamed past each other.** *Trades* (`sweep_panel.py`) becomes
**Results**, and today's *Results* (`results.py`) becomes **Trends**. So "Results" means a
different tab before and after this change, and `results.py` will be the Trends tab while
`sweep_panel.py` is the Results tab. Rename the modules in the same commit or the next
session will read them backwards. *Trades* also moves to **second** tab position, with
*Market* third: order becomes Opportunities, Results, Market, Trends, Log.

### Global

- [ ] **Title Case every piece of user-facing text** — "no reply" → "No Reply", and the
  same through buttons, headers, dropdown entries and status lines. **Does not extend to
  the band vocabulary**: *worth trying* / *uncertain* / *too good to be true* are sentence
  fragments used inline, and the `PLAUSIBLE`/`THIN`/`GHOST` enum stays untouched (CLAUDE.md,
  *Internal band names and user-facing words are deliberately different*).
- [ ] **Per-column minimum widths, so headers stop truncating at narrow window widths.**
  Today they scrunch to `Profit`→`rofit`, `Expires`→`xpire`. Each column's floor should be
  its own header text plus padding; **Item and Seller need generously more than that**, for
  long item names and long seller names. Raise the window's minimum width if the sum
  demands it. This is `table_items.ColumnLayout` — note it already exempts the action
  column from shrinking for the same class of reason, so this is an extension of an
  existing rule, not a new mechanism.

### Opportunities

- [ ] **A session timer at the top, across from the action headline** (opposite "Nothing to
  do" / "1 trade ready · 3 waiting on a reply"). `session.py` already has the start.
- [ ] **Bankroll bar layout.** *Long shots* drops to a second line at minimum window width
  while there is still free right margin — the wrap threshold in `bankroll_bar.py` is
  firing early, and the screenshots show the width at which it genuinely stops fitting.
- [ ] **The currency letter belongs outside the spin box**, to the right of the arrows: in
  the field there should be **only the number**. Today `setSuffix(" div")` puts it inside,
  which reads as editable text. Note this collides with `_fits`/`setSpecialValueText`, which
  currently sizes the box around `"no limit (div)"` — and the special value should become an
  **infinity sign** rather than the words "no limit".
- [ ] **A queued row can cost more than the bankroll.** Screenshot: 84 div ready to whisper
  against a 39 div bankroll. First suspect is that candidates are sized when queued and not
  re-checked when the bankroll spin box changes.

### Both queue sections

- [ ] **Rename the columns.** `Buy` → **Amount**, `Each` → **Price per**, `Cost` →
  **Total**. The headers were misread by their own author on 2026-08-01 (`Buy 5 / Each 1
  div / Cost 5 div` read back as "I bought 1 for 5 div"), which is how a lost trade got
  explained as a profit-column bug. Both header tuples are in `queue_panel.py`.
- [ ] **Icon buttons instead of words**, smaller, styled as close to PoE2 as possible, with
  the full wording kept as the hover tooltip: Accept 👍, Decline 👎, Copy Again the
  two-pages glyph, Traded a check, No Reply a dash, Already Sold a cross. Sizing matters
  beyond taste — the row of word-buttons is why the action column can't shrink and why
  *Already sold* is clipped at narrow widths in the screenshots.

### Waiting on a reply

- [ ] **Every non-derived value editable, not just the quantity.** Price and total as well,
  since a seller who counteroffers changes the price rather than the amount — see the
  counteroffer item in *Next*, which needs the same field. Derived values (profit, band,
  the CE reference) stay read-only.

### Trades → Results

- [ ] **Rename the tab to Results and move it to second position** (see the collision note
  above). *Market* becomes third.
- [ ] **Rename the columns**: `Listed` → **Price per**, `Buy` → **Amount**, `Cost` →
  **Total** — the same vocabulary as the queue, in `sweep_panel.py`.
- [ ] **Rename the filter options**: *Everything found* → **All Results**, *Ones I
  messaged* → **Attempts**, *Ones I bought* → **Trades**.
- [ ] **"This session" is neither this session nor all of it.** Rename to **Current
  Session** and offer it *only while a session is in progress*. The likely cause is in the
  name: `SESSION_LIVE` means "what the last sweep found" (its own tooltip says so), which
  is a different set from "what this session attempted" — a sweep boundary is not a session
  boundary, and 2026-08-01 ran four sessions in one evening.
- [ ] **The Result column can be edited, along with every non-derived value.** This is the
  route back to the auto-expired row in *Next*, and the only way the Rigwald's Ferocity
  record gets corrected. Numeric fields edit on a **double-click** in place. **Confirm
  before amending a record more than an hour old.** Writes go through the existing
  amendment record, which preserves the original ask in `asked_units` — extend it rather
  than mutating the attempt.
- [ ] **Centre every column except Item and Seller.**

### Results → Trends

- [ ] **Rename the tab to Trends.** Contents unchanged.

### Market

- [ ] **Add 7-Day Trend, Volume/hour and Most Popular columns from poe.ninja.** Check what
  the endpoint the app already calls returns before designing the columns — the universe
  fetch may carry the sparkline and volume fields already, in which case this is display
  only. "Most Popular" needs defining against whatever poe.ninja actually publishes.

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
