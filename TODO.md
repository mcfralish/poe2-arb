# poe2-arb — TODO

What is **not** done. Shipped work is in [CHANGELOG.md](CHANGELOG.md); measured findings
and standing invariants are in [docs/FINDINGS.md](docs/FINDINGS.md). Completed items are
deleted rather than ticked, so this file stays worth reading start to finish.

## State of play

**Shipped:** v0.7.0 (2026-07-31). **v0.8.0 is written and untagged** on `field-test-4`:
the outcome-log integrity half of the fourth session's defect list, plus the hotkey
diagnostic, the column work, the ranking refit and the editable rows. **It has now been
run on Windows once**, via a manual `workflow_dispatch` build, and that single run paid
for the whole diagnostic: it caught the hotkey refusal in the act and root-caused four
releases of failure to the app's own updater. That fix is in 0.8.0 too. Nothing else in
it has been used in game.

> **The 0.8.0 exe that was built is no longer what 0.8.0 will tag as.** Decided
> 2026-08-01: the ranking refit was folded into 0.8.0 rather than cut as 0.9.0, because
> nothing has shipped to users and two unreleased versions is worse bookkeeping than one.
> The editable rows went in on the same reasoning. `__version__` and `pyproject.toml` stay
> at 0.8.0; no bump.
>
> **A current exe exists and has not been run.** Built 2026-08-02 from `b8d43a8` on
> `field-test-4`: [run 30727645833](https://github.com/mcfralish/poe2-arb/actions/runs/30727645833),
> artifact `poe2-arb-field-test-4-b8d43a8b…`, **14-day retention — expires 2026-08-16.**
> It carries everything in 0.8.0 — the ranking refit, the editable rows,
> `FILL_PRIOR[GHOST]`, and the `stock` / `ce_age_s` instrumentation the next field
> test needs. **Nothing in it has been used in game.** If the artifact has expired, re-run
> the workflow rather than trusting this link.

**Stop counting field tests by ordinal — they no longer agree.** This file has called the
20:49–21:29Z run of 2026-08-01 "the fifth"; the maintainer calls it the sixth, and both are
defensible because the log holds **six session ids on 01 Aug alone** while a "field test"
has meant a sitting, an evening, or a build depending on the paragraph. **Identify a
session by its id.** The one that matters is `11fc03d0a4f3` (01 Aug 20:49–21:29Z, 227
attempts, 14 fills) — **the only session that has ever run 0.8.0**, identifiable because it
is the only one writing `expired` rather than `no_reply`, and the one that took the ranking
sample from 156 to 789. Earlier sessions and their 969 log records are in
[docs/FINDINGS.md](docs/FINDINGS.md), *Found in the fourth session of real use*.

**That session's defect gap is now partly closed, from the log rather than from memory.**
Nobody was ever asked what went wrong in it. Asked on 2026-08-01, the maintainer did not
recall — but the log answered the question the write-up would have: **AFK, Offline and
Refused have been pressed zero times in 789 whispers**, so the manual half of 0.8.0's
three-way verdict split is unused. Written up in [docs/FINDINGS.md](docs/FINDINGS.md),
*The three-way verdict split has never once been used by hand*. What is still unrecorded is
anything that went wrong which the log cannot see — worth one question after the next run
rather than reconstructing this one.

**As of 2026-08-02 the log holds 872 attempts. RE-READ IT BEFORE BELIEVING ANY NUMBER IN
THIS FILE.** It went 789 → 872 *during the session that wrote these paragraphs*: three more
sessions (`f0351bcc86af`, `3c0e46bcfb21`, `d9b8d1359894`, 02 Aug 00:02–03:28Z, 83 attempts,
4 fills) landed after an explicit "nothing unread" check. That check was true when it was
made and stale an hour later. The correction changed two findings — the ghost ratios and
the verdict-split result — and this is now **the third time** the project has written a
conclusion over the top of data it had not read. `read_attempts(path)` and a count is
fifteen seconds; do it first, every time.

**What 0.8.0 built, so it is not rebuilt.** The auto-expiry writes `Outcome.EXPIRED`
instead of `no_reply` and the manual buttons are now **AFK** / **Offline**; a waiting row
can be **pinned** off the clock; a listing resolved as Traded / Already Sold / Offline /
Refused is suppressed for the session; the money columns are *Amount / Price per / Total*
and the Trades filters *All Results / Attempts / Trades*; every column refuses to shrink
below its own heading and the row actions are icons; and the hotkey reports a refused
`RegisterHotKey` with `GetLastError`, shows *Refused* in Settings, tests a binding before
saving it and retries in the background. Full list in [CHANGELOG.md](CHANGELOG.md).

**Start here next session.** **The pricing item (6) is now the most valuable thing on this
list** — it explains both real losses the project has made and one of them was banded
*plausible* — but it wants one more thin-pair reading first, which needs a human in game.
Items 2 and 3 are both maintainer decisions from using 0.8.0 and are ordinary work.

1. ~~Make every non-derived value on a row editable — price included.~~ **Done
   2026-08-01.** Amount, Total and Result are all correctable, in the queue via *Adjust…*
   and on a Trades-tab history row by double-click. Details under *Done since this file was
   last written*.
2. **Replace AFK / Offline / Refused with one "Seller not available" button.** *(Decided
   2026-08-02 from a measurement and the maintainer's answer to it: zero presses in 789
   whispers, because the queue arrives faster than a three-way judgement can be made.)*
   Its only job is to drop the row from the queue; the AFK/offline/silent split moves to
   the `Client.txt` reader, which is where the evidence already is. Keep `Outcome.AFK` and
   `Outcome.OFFLINE` in the enum — the log holds records under both — and add whatever the
   new button writes. Evidence and the "what are these metrics for?" answer are in
   [docs/FINDINGS.md](docs/FINDINGS.md), *The three-way verdict split has never once been
   used by hand*.
3. **Rework the counteroffer editing to inline spin-arrow fields.** *(Maintainer feedback
   2026-08-02, after using the dialog.)* Inline with up/down arrows rather than
   *Adjust…*, and **Total and Price per both editable, each moving the other**. The
   obstacle is real and was the reason for the dialog: the queue tables rebuild every
   second for the countdowns and that kills an open editor. Solve it — suppress the
   rebuild while an editor is open, or have the tick write only the countdown cells —
   rather than reverting to a dialog.
4. **A "hide listings over 3 days old" toggle, off by default.** *(Decided 2026-08-01 —
   see the *Both queue sections* item below for the full spec.)* Small, and the next piece
   of queue-table work.
5. **The Send button** (*Next*) — route **decided: keystrokes**. Unblocked, ordinary work.
6. **Pricing** (*Next*) — **unblocked 2026-08-02, and the answer reversed the plan.** The
   thin reading finally exists: Astrid's Creativity, a **22.2%-wide book** with the app
   **+53% above the bid**. So the liquidity-scaled haircut is **back on** — it was killed
   on liquid pairs, which is not where the money is lost — and freshness is a second,
   smaller effect rather than the whole story. This is now the **biggest open item in the
   project**: it explains both known real losses, one of them banded *plausible*. Take one
   more thin reading before fitting a curve (n=1 today). Full write-up in
   [docs/FINDINGS.md](docs/FINDINGS.md), *The reference price does not match what a sale
   realises*.

**Next time you are in game, whatever else is happening.** This is not session work and
does not compete with the list above; it is the queue of things only playing can answer.

- **The rest of 0.8.0 has never been used.** The hotkey half is done and the answer was
  worth the four releases it cost: the diagnostic fired within four seconds of the first
  Windows run and caught **poe2-arb itself** holding the key — the updater launches the
  installed copy while this one is still alive, so an upgrade always refused the surviving
  process with 1409. Fixed by claiming the key after the install handover (`app.main` →
  `MainWindow.start_hotkey`). Evidence in [docs/FINDINGS.md](docs/FINDINGS.md),
  2026-08-01, *RESOLVED*. **Still unchecked on Windows:** whether the icon buttons render,
  whether pinning is reachable mid-map, and whether the 60-second retry actually fires.
  **The ranking refit and the editable rows join this list** — an exe carrying both is
  built and waiting; see the version note above for the link.
- ~~**Press AFK / Offline / Refused at least once.**~~ **Answered 2026-08-02: they are
  not worth having.** The queue arrives faster than a three-way judgement can be made, so
  the split reads as zero whatever the labels are. Replaced by item 2 of *Start here*.
- ~~**Astrid's Creativity**, both sides of the book.~~ **Done 2026-08-02 and it reversed
  the plan** — 22.2% wide, app +53% above the bid. What is wanted now is **a second thin
  pair**, so the haircut can be fitted to a curve rather than a point. Same method: read
  both rows of the book and the app's Quick Lookup within the same minute, and note the
  clock time.

**Done since this file was last written (2026-08-01, no game time needed).** The editable
rows, the counteroffer question and the ranking fit — the last two from data already on
disk:

- **Every non-derived value on a row is editable, price included.** Both halves of the
  change landed together, as planned. In *Waiting on a reply*, **Adjust…** now sets the
  quantity **and** the total, and the total follows the quantity at the listed price until
  you touch it. On a Trades-tab **history row**, Amount, Total and Result edit in place on
  a double-click — Result through a drop-down, and anything over an hour old asks first.
  Writes go through the amendment record (`outcomes.plan_correction` /
  `record_correction`, which work from a logged `Attempt` with no candidate behind it), so
  the original ask survives in `asked_units` / `asked_pay_units` / `asked_cost_divines`.
  Profit can now be negative and `format.fmt_profit` owns the sign everywhere. Verified by
  screenshot as well as by tests. Standing decisions in
  [docs/FINDINGS.md](docs/FINDINGS.md), *Correcting a trade after the fact* — including why
  a whispered row on the *live* Trades table is deliberately not editable there.
- **The Rigwald's Ferocity record is corrected, and it moved the ghost finding again.**
  The maintainer confirmed it filled at the listed price; an appended `filled` with
  `actual_profit_divines: 136.0` is in `outcomes.jsonl` (a backup of the pre-correction
  file is not kept in the repo — the log is append-only and the original verdict is still
  in it). Consequences, all in [docs/FINDINGS.md](docs/FINDINGS.md) *Negative results* 1:
  ghost fills 12 → 13. **The prior briefly went to 0.17 and is back at 0.16** — 83 more
  whispers, read later the same session, put the fill-rate ratio at 0.146 against the 0.175
  that justified the move, so that was over-fitting. The value ratio went 0.66 → 1.25 →
  0.82 in one day, crossing parity and returning on whispers containing no new ghost fills.
  **The durable finding is that the estimate is unstable at ±0.02 and must not be chased**;
  one trade is 47% of all ghost realised value. Full table in
  [docs/FINDINGS.md](docs/FINDINGS.md) *Negative results* 1.
- **The release workflow is off Node 20.** `checkout@v4→v5`, `setup-python@v5→v6`,
  `upload-artifact@v4→**v7**`. Proved on dispatch runs, no tag, no release — and the
  proving earned its keep: **`upload-artifact` v5 and v6 are still Node 20**, so the
  obvious one-major-version bump left the warning in place and only v7.0.1 clears it.
  `softprops/action-gh-release@v2` was never flagged and is untouched.
- **The counteroffer worry is closed, and the Rigwald's fill is corroborated.** 36 of 37
  fills went through at the **listed
  price**, joined attempt-by-attempt to `Client.txt`. Both fat-tail fills the 0.7.0
  correction rested on were unnegotiated, and two extreme gaps are corroborated by
  independent listings on the same item. The correction stands; do not re-open it.
- **The ranking is fitted at n=872** (was n=789 when first written this session) — many
  times the last sample, because a **further**
  field-test session (`11fc03d0a4f3`, 227 attempts, 14 fills, the first run on 0.8.0) was
  sitting in `outcomes.jsonl` unread. `FILL_PRIOR[GHOST]` is 0.16 rather than 0.0, and a
  listing three days old now sorts last — 0 fills in 102 whispers, 13% of every message
  the app has ever suggested. Both in `listings.py`, both in FINDINGS.
- The lesson from last time repeated itself exactly: **read `outcomes.jsonl` before
  believing this file about what has been measured.**

**What 0.7.0 changed, in one paragraph.** Two of 0.6.0's fixes were wrong rather than
incomplete: the hotkey had still never fired (Qt is now out of the delivery path
entirely), and the bankroll holdback is reverted because 79%+ of whispers go unanswered so
it suppressed more real trades than double-spends it prevented. Plus: listings are ratios
rather than bundles, so a 100-divine listing is buyable on a 20-divine bankroll;
opportunities queue as they are found rather than all at once; quantities are correctable
after the fact without erasing the original ask; sessions and leagues are stamped on every
whisper and the Trades tab reviews any of them; Results gained *Every trade*; columns
reorder, resize and persist. Full list in [CHANGELOG.md](CHANGELOG.md).

**The ghost correction has now survived being doubted four times, and got bigger every
time.** At n=131 it read "ghosts fill at 2.3%, worth 0.28 of a plausible whisper". At
**n=872** it reads: ghosts fill at **1.95%** (n=666) against plausible's 13.4% (n=194).
Every reading has said the same qualitative thing — the 0.0 is badly wrong and ghosts are
worth a real fraction of a plausible whisper — while the *quantity* has swung on single
fills (fill-rate ratio 0.162 / 0.175 / 0.146 within one day; value ratio 0.66 / 1.25 / 0.82).
Take the direction as settled and the decimal as noise. The 2026-08-01 counteroffer
scare is resolved against the game's own log (35 of 36 fills at the listed price), and
`FILL_PRIOR[GHOST] = 0.0` is now fixed rather than merely known-wrong. Full tables in
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

> **The app is not trustworthy for live trading on thin items** — but the reason changed on
> 2026-08-01 and the old wording here was wrong. It is **not** a ~26% overstatement: read
> against both sides of the in-game book, the error was **−5.9% and +6.5% on two items
> minutes apart**, so the reference price is **noisy at roughly ±6%, not biased**, and the
> cause is the price *moving* rather than a spread. It still doesn't know gold exists. Both
> are quantified in [docs/FINDINGS.md](docs/FINDINGS.md). The *uncertain* band tooltip and
> Quick Lookup still say "runs high", which is now over-specific and one-directional —
> fixing that wording is part of the pricing item. Genuinely thin pairs (~100k
> `ValueTraded`) remain unmeasured.

**The shape of the app.** Toolbar: *Find trades* (a toggle — sweeps, waits, sweeps again)
and *Settings*. Tabs: *Opportunities* (the queue, plus bankroll, settlement, long-shots and
Quick Lookup), *Market* (the whole economy from poe.ninja), *Trades* (what the current
session found, or any past session read back from the log), *Results* (the whisper log —
fill rates, takings, and every trade), *Log*.

## What the next field test must measure

**Answered 2026-08-01 and 2026-08-02, and neither needed a trade** — reading both sides of
the book while standing still was enough both times, which is worth remembering next time
this file says something is blocked on a completed trade. Results in
[docs/FINDINGS.md](docs/FINDINGS.md).

**The thin cell is filled and it reversed the conclusion.** Astrid's Creativity, 110k
`ValueTraded`, 2026-08-01 18:35 PDT: **ask 2.00 / bid 1.60 / app 2.45** — a **22.2%-wide
book** against 1.7% on the liquid control, with the app **+53% above the bid and above even
the ask**. The liquidity haircut is back on. **What is wanted now:**

1. **A second thin pair, any ~100k `ValueTraded` item.** One point cannot be fitted to a
   curve, and a haircut scaled on `ValueTraded` needs at least two. Same method, same
   minute, note the clock time.
2. **Ideally a third at ~500k**, between the thin and liquid clusters, since everything
   between 110k and 1.6M is currently interpolation.

The method, for reuse: in-game quotes read **"I want : I have"**, so the first row of a
pair is what you pay to **buy** and the second is what you **receive** to sell. Take the
app's number within a minute of the game's — the whole point is that they move.

Also worth confirming, because nothing but a human can check them.

**New in 0.8.0, and none of it has run on Windows.** This is the list to work through
first — see item 1 of *Start here*:

- ~~**The hotkey — and first, find a binding that actually gets refused.**~~ **Answered
  2026-08-01, and the refusal reproduced itself.** Running the 0.8.0 artifact triggered the
  in-place update, which launches the installed copy while the downloaded one is still
  alive; the survivor was refused with 1409 because *the other poe2-arb had the key*. The
  Sidekick hypothesis stays withdrawn and the "stale process" one is confirmed with a
  mechanism the app creates itself on every update. Fixed; full write-up in FINDINGS.
  **What is left of this bullet is one line: the 60-second retry has still never been
  observed firing.** It would have recovered the refusal at ~06:33:20 on its own, but the
  key was rebound by hand at 06:32:46 first. To see it: with the hotkey refused, leave
  Settings closed, free the key, and wait — it must start working **without reopening
  Settings**. No test here means anything about that path.
- **The icon buttons render**, in the game's own font environment. They are dingbats
  rather than emoji precisely because emoji fall back to identical empty boxes, but that
  was verified on Linux only.
- **Pinning is reachable mid-map** — the flag button is 30px, and the whole point of the
  row is that it is used while playing.
- **Expired versus AFK versus Offline is a distinction worth making by hand.** If the
  three buttons feel like more work than the one they replaced, that is worth knowing
  before the log fills up with a split nobody uses.
- **The in-place editors on the Trades tab.** Verified by screenshot on Linux only: the
  Result cell's drop-down had to be widened past its own column to stop reading "No Repl",
  and that measurement comes from the font. Worth one look on Windows — and worth checking
  that double-clicking a *live* row still copies its whisper rather than opening an editor.

**Older, still unconfirmed:**

- **Partial asks get answered.** Listings bigger than the bankroll are whispered for the
  affordable fraction. Worth knowing whether the reply rate on those is materially worse
  than on whole-lot asks — it is a new class of whisper and the log can measure it, but
  only once some have been sent.
- Always-on-top floats over the game in borderless windowed.

**If the install error recurs:** `%LOCALAPPDATA%\poe2-arb\poe2-arb.log`, grep for
`install to ... failed` or `Start Menu shortcut`. The `--windowed` exe has no console,
which is why the original occurrence left no trace.

## Next

- [ ] **The three-way split is built and editable; the log-reading half is not.** Done in
      0.8.0: the timeout writes `Outcome.EXPIRED`, the manual buttons are **AFK** and
      **Offline**, a pinned row never expires, and — since the editable-rows change — a
      verdict is correctable from the Trades tab, which was the missing route back.
      **What is left is automation from `Client.txt`**: it can mark Offline on its own,
      since `: <char> is not online.` is already in it. See *Split NO_REPLY* below, which
      is the log-reading half of the same three-way split.
      **One record is waiting on the maintainer, not on code**: the Rigwald's Ferocity
      row still reads `no_reply`, and only you know what really happened to it. Trades →
      *All time*, double-click its Result.
- [ ] **A restart of *Find trades* still re-scans the same items immediately.** The other
      half of the duplicate-whisper problem; the *suppress a resolved listing* half shipped
      in 0.8.0 and covers a listing that was Traded, Already Sold, Offline or Refused. What
      is left: the maintainer uses the toggle as a pause when replies pile up, and gets a
      fresh sweep of the same items for it. Either resume the sweep where it stopped, or
      build an explicit **Pause** that holds the queue without ending the session. Note
      `session.py` already treats a toggle mid-session as *continue*, so the session
      boundary is not the thing that needs changing.
- [ ] **The hotkey is root-caused and fixed. What is left is one unobserved code path.**
      0.8.0's diagnostic worked exactly as intended: within four seconds of its first
      Windows run it reported `GetLastError=1409` and named the launch that caused it.
      **The program holding the key was poe2-arb** — `_update_in_place` launches the
      installed copy and lets this one exit, and `MainWindow.__init__` had already
      registered the key, so every update handed the hotkey to the process that was
      leaving. Since running the new exe *is* how you update, the hotkey was dead on
      precisely the launch anyone would test it on, which is the likeliest explanation for
      all three earlier failures (not proven — those releases logged nothing). Fixed by
      moving registration out of construction into `MainWindow.start_hotkey`, called from
      `app.main` after the install handover; `tests/test_app.py` pins the order. Log
      extract and reasoning in [docs/FINDINGS.md](docs/FINDINGS.md), 2026-08-01.
      **Still open:** the 60-second retry has never been seen to fire (see the verification
      list above), and a crashed poe2-arb holding a live pump thread is the case it exists
      for. *Overlay research remains optional, not blocking.* Focus was never implicated.
- [ ] **The reference price question is UNBLOCKED — the fork resolved to *movement*, and
      the spread branch is disproved.** Measured 2026-08-01 off both sides of the in-game
      book against the app's own snapshot minutes later; table in
      [docs/FINDINGS.md](docs/FINDINGS.md), "The reference price does not match what a sale
      realises", 2026-08-01 subsection. The book is **~2% wide** on Faded Crisis Fragment
      and Omen of Whittling against a 1.7% liquid control, and the app's error on those two
      was **−5.9% and +6.5% — opposite signs, minutes apart.** Omen of Whittling was +37% on
      07-30 and +6.5% today. So:
      - ~~**Do not build the liquidity-scaled haircut.**~~ **Un-killed 2026-08-02.** It was
        declared dead on two pairs at 1.6M and 10.0M `ValueTraded`, where the book really
        is ~2% wide. At 110k it is **22.2%** wide and the app quotes above the ask. Build
        it, scaled on `ValueTraded`; the liquid pairs simply land near a haircut of zero.
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
- [ ] **Fitting the ranking to the outcome log: three of four pieces are DONE
      (2026-08-01, refitted at n=872 on 2026-08-02).** Tables
      in [docs/FINDINGS.md](docs/FINDINGS.md), *Negative results* 1. Shipped in
      `listings.py`:
      - *`FILL_PRIOR[GHOST]` is 0.16*, not 0.0. Ghosts fill at 1.95% (n=666) against
        plausible's 13.4% (n=194), and the ratio is unstable at ±0.02 — do not chase it. **The open question of which ratio the prior expresses
        is answered: the fill-rate one.** `fill_weight` multiplies profit, so
        `profit × weight` is already the divines-per-whisper estimate; feeding it the
        value ratio (now 1.25) would count the fat tail twice. Consequence, deliberate: a ghost
        worth more than ~6 plausibles now sorts above them.
      - *`max_gap_ratio = 1.50` survives, and the cliff is now located precisely* — fills
        run 9%–15% below 1.5× and 1%–3% above it. 1.50 sits on the edge. Leave it.
      - *A listing ≥3 days old sorts below everything fresh* (`STALE_LISTING_S`). 0 fills
        in 102 whispers; a cliff, not a decay curve. This was the "a listing that has sat
        for hours is a rankable signal" hunch — it is real, but it is **days, not hours**.
      **What is left:**
      - *`min_gap_ratio = 1.05` is no longer unmeasured but is still not settled.* 56
        whispers below 1.10× fill at 14%, as well as any bucket under the cliff — so
        *fill behaviour* gives no reason to raise it. The reason to raise it is that at a
        1.05 gap the whole edge is inside the reference price's ±6% error. **Do not read
        the 14% as vindicating 1.05.** It stays blocked on the pricing item; both are the
        same measurement error wearing different hats.
      - Let the user apply `suggested_gap_band` from the Results tab, which already
        computes `value_per_attempt` — the right objective, and the one that revealed the
        ghost result in the first place.
      - *`FILL_PRIOR[Band.THIN] = 0.5` is still a guess.* n=10, under `MIN_SAMPLES`, and
        its raw 20% fill rate would imply a weight above 1.0, which is plainly two fills'
        worth of noise.
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
were supplied in the intake conversation and are not in the repo. **The column headings and
the row buttons were done in 0.8.0**, which also raised the window's minimum width to 960
— below that the queue tables now scroll sideways rather than truncating a heading.

**Two tabs are being renamed past each other.** *Trades* (`sweep_panel.py`) becomes
**Results**, and today's *Results* (`results.py`) becomes **Trends**. So "Results" means a
different tab before and after this change, and `results.py` will be the Trends tab while
`sweep_panel.py` is the Results tab. Rename the modules in the same commit or the next
session will read them backwards. *Trades* also moves to **second** tab position, with
*Market* third: order becomes Opportunities, Results, Market, Trends, Log.

### Global

- [ ] **Title Case every piece of user-facing text** — the same through buttons, headers,
  dropdown entries and status lines. **Partly done in 0.8.0**: the verdict vocabulary
  (`outcomes.LABELS`), the queue and Trades column headings, the row action names and the
  Trades filter options. What is left is everything else — section labels, status-bar
  lines, Settings rows, the Market and Results tabs. **Does not extend to the band
  vocabulary**: *worth trying* / *uncertain* / *too good to be true* are sentence fragments
  used inline, and the `PLAUSIBLE`/`THIN`/`GHOST` enum stays untouched (CLAUDE.md,
  *Internal band names and user-facing words are deliberately different*).

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

- [ ] **A "Hide listings over 3 days old" toggle, off by default.** *Decided 2026-08-01,
  after the measurement that produced it: 0 fills in 102 whispers at that age, in every
  band — see [docs/FINDINGS.md](docs/FINDINGS.md), "A listing older than ~3 days has never
  filled". Those whispers were **13% of every message the app has ever suggested.***
  Ranking already demotes them (`STALE_LISTING_S`, `rank_candidates` sorts them below
  everything fresh) and the Age column already shows `6d`, so this is purely about
  reclaiming the 13% on a busy session. Mirror the existing *Hide the too-good-to-be-true
  ones* checkbox exactly — same place, same shape, same off-by-default. **Off by default is
  the load-bearing part**, not a nicety: a hidden row cannot be falsified, which is how
  `FILL_PRIOR[GHOST] = 0.0` survived four field tests, so the app must never hide these on
  its own. Needs a config key; `config.RETIRED_KEYS` is the pattern if it is ever dropped.
- [ ] **The action buttons are icons but not PoE2-styled.** Done in 0.8.0: glyph buttons at
  a fixed 30px with the full wording on hover, which is what made a seven-action row fit.
  **Not done: the styling.** They are stock Qt buttons carrying dingbats
  (✔ ✖ ⚑ ⚐ ❐ ✎ ☾ ⊘ ✕), chosen because emoji need a colour font and render as identical
  empty boxes without one — see [docs/FINDINGS.md](docs/FINDINGS.md), *Operational*. Doing
  this properly means bundled icon assets, not a different character.

### Trades → Results

- [ ] **Rename the tab to Results and move it to second position** (see the collision note
  above). *Market* becomes third.
- [ ] **"This session" is neither this session nor all of it.** Rename to **Current
  Session** and offer it *only while a session is in progress*. The likely cause is in the
  name: `SESSION_LIVE` means "what the last sweep found" (its own tooltip says so), which
  is a different set from "what this session attempted" — a sweep boundary is not a session
  boundary, and 2026-08-01 ran four sessions in one evening.
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
- [ ] Packaging beyond one exe — PyPI for the CLI, Scoop/winget manifests.
