# poe2-arb — TODO

What is **not** done, batched into session-sized units. Shipped work is in
[CHANGELOG.md](CHANGELOG.md); measured evidence and standing decisions are in
[docs/FINDINGS.md](docs/FINDINGS.md). **Completed items are deleted rather than ticked** —
if it is still here, it is still open.

> **Before quoting any number in this file, re-read `outcomes.jsonl`.** `read_attempts(path)`
> and a count is fifteen seconds. The project has three times written a conclusion over the
> top of data it had not read — most recently on 2026-08-02, when the log went 789 → 872
> *during* the session that had just checked it was current. The operator's summary is not
> the record, and neither is this file.

## State of play

**Shipped:** v0.8.0 (2026-08-02) — tagged from `main` after merging `field-test-4`, exe
published, release job green. **0.9.0 is open**: `__init__.py` and `pyproject.toml` read
`0.9.0`, `CHANGELOG.md` has an `[Unreleased]` section to fill, and work is on
`field-test-5` off `main`. Rename that heading to `## [0.9.0] — <date>` before tagging or
the release job fails, which is the point of it.

**Start with Batch 1** (decided 2026-08-02, over pulling Batch 6's `ce_age_s` analysis
forward — that stays where it is).

Two field-test sessions have landed since 0.7.0 and both are fully written up in FINDINGS:
*Found in the fourth session of real use* (2026-08-01) and *The first real play session on
0.8.0* (2026-08-02). The log holds **872 attempts** as of 2026-08-02. Identify a session by
its **id**, not by an ordinal — "field test N" has meant a sitting, an evening and a build
in different paragraphs, and the log holds six session ids on 01 Aug alone.

**Two premises were overturned on 2026-08-02 and a lot of design rested on them:**

1. **The app is not used mid-map.** It is a sit-in-town tool with the user's full
   attention. The toast, the alert window, the 30px buttons and `risk_appetite`-as-
   interruption-tolerance were all built for a player who is busy. Throughput beats
   glanceability.
2. **The reference-price error does not scale with liquidity.** Thin items really are
   overstated, but not by an amount `ValueTraded` or book width predicts. There is no curve
   to fit.

## Decisions taken 2026-08-02 — do not re-open

Each was a fork the work would otherwise have guessed at.

1. **0.8.0 tags now; the FT5 UI batch is 0.9.0.** *Done — v0.8.0 shipped 2026-08-02.* One
   release branch per field-test cycle, merged into `main` at the tag: 0.9.0's is
   `field-test-5`.
2. **The toast and the alert window are removed; the ● marker stays, re-defined.** ● stops
   being a state (`OFFERED`) and becomes a position — **row 1 of *Ready*, which after the
   re-sort is the trade the hotkey takes**. `offer_window_s` and `alert_until` go; retire
   the config key via `config.RETIRED_KEYS` and drop its Settings row. `expires_at` starts
   when a candidate enters *Ready* rather than at promotion, and the
   floor-at-the-alert-window rule goes with the window. **Rows still expire** —
   `available_ttl_s` and `awaiting_timeout_s` are untouched. Superseded rules are kept with
   their original reasoning in [docs/FINDINGS.md](docs/FINDINGS.md), *The offer queue*, so
   nobody re-derives them as arguments to restore the toast.
3. **A Ready row whose cost outgrows the bankroll is re-sized down, not dropped** — dropped
   only if it falls below `min_profit_divines`. Whispered rows are never re-planned.
4. **Row icons become vendored Lucide SVGs (MIT).** Copy the files in with the licence
   rather than adding a dependency, and **confirm QtSvg survives the PyInstaller bundle** —
   an SVG that renders in dev and not in the exe is the same failure as the dingbats, and
   only a Windows build proves it.
5. **The merged verdict button writes `Outcome.UNAVAILABLE`.** Chosen over `NOT_AVAILABLE`,
   `NO_TRADE` and `SELLER_GONE`: it matches the button's wording and claims nothing about
   *why*, which is all a single press establishes. `NO_TRADE` was rejected as wide enough to
   swallow `DECLINED`. **This is permanent** — the log stores the enum value and `Outcome`
   never renames members.

## The batches

Ordered by dependency, not importance. **Batch 1 must come first** — the button count it
settles drives every width decision in Batch 3. Batch 6 is desk work and does not compete
with the UI batches for game time; do not let the UI list crowd it out entirely.

| # | Batch | Main files |
|---|---|---|
| 1 | The queue rework | `trade_queue.py`, `queue_panel.py`, `main_window.py`, `config.py` |
| 2 | Bankroll correctness | `main_window.py`, `sweep_panel.py`, `trade_queue.py` |
| 3 | Table and window layout | `table_items.py`, `queue_panel.py`, `bankroll_bar.py` |
| 4 | Icons and row polish | new assets, `queue_panel.py`, `settings_dialog.py` |
| 5 | The tab shuffle | `sweep_panel.py`, `results.py`, `main_window.py` |
| 6 | Pricing — desk work | `scout.py`, `listings.py`, analysis |

---

### Batch 1 — The queue rework

The largest single change and the one the rest sits on. Decision 2 above is the spec.

- [ ] **Replace AFK / Offline / Refused with one "Seller not available" button.** *(Decided
      2026-08-02: zero presses in 789 whispers, because the queue arrives faster than a
      three-way judgement can be made.)* Its only job is to drop the row; the
      AFK/offline/silent split moves to the `Client.txt` reader, where the evidence already
      is. **Keep `Outcome.AFK` and `Outcome.OFFLINE` in the enum** — the log holds records
      under both and `Outcome` never renames members. The new member is
      **`Outcome.UNAVAILABLE`** (decision 5 above; permanent). It is a silence for
      `is_silence` purposes and belongs in `trade_queue.SETTLED_OUTCOMES` only if a press
      should suppress the listing for the session — decide that against `AFK`, which is
      deliberately *not* in the set because an away seller comes back. Evidence in
      [docs/FINDINGS.md](docs/FINDINGS.md), *The three-way verdict split has never once been
      used by hand*.
- [ ] **Rework *Ready to whisper* into a visible FIFO.** Goal: **row 1 is always the trade
      the hotkey will take, row 2 is the one after it.** The maintainer keeps the pane small
      to give room to *Waiting on a reply* and cannot see what is next.
      - *Stop the drip.* `tick` promotes one QUEUED trade per `offer_window_s`, so a sweep's
        candidates trickle in over minutes and sit invisible meanwhile. **Put every candidate
        into Ready as it is found.** Check `cancel_pending`, which exists to drop the QUEUED
        backlog when *Find trades* stops — with no backlog, stopping simply stops adding,
        which is the intended behaviour anyway.
      - *Sort Ready by the hotkey's own order.* The hotkey takes `trade_queue.offered`,
        picked by `_next_to_offer` **by rank**, while `available` sorts by
        `offered_at or queued_at`. That mismatch is the whole complaint.
      - *Drop the toast and the alert window with it* — decision 2.
      - **The cost is real and was the reason for the old rule:** rank order reshuffles when
        a better candidate arrives, so rows move under the cursor. **Mitigate rather than
        revert** — row 1 is the hotkey's row so it is the least click-sensitive; consider
        holding a reshuffle while the pointer is over the table.
- [ ] **Rework the counteroffer editing to inline spin-arrow fields.** *(Maintainer
      feedback 2026-08-02, after using the dialog.)* Inline up/down arrows rather than
      *Adjust…*, with **Total and Price per both editable, each moving the other**. The
      obstacle is real and was the reason for the dialog: the queue tables rebuild every
      second for the countdowns and that kills an open editor. Solve it — suppress the
      rebuild while an editor is open, or have the tick write only the countdown cells —
      rather than reverting to a dialog.
- [ ] **A restart of *Find trades* re-scans the same items immediately.** The remaining half
      of the duplicate-whisper problem; suppressing a *resolved* listing shipped in 0.8.0.
      The maintainer uses the toggle as a pause when replies pile up and gets a fresh sweep
      of the same items for it. Either resume the sweep where it stopped or build an explicit
      **Pause** that holds the queue without ending the session. `session.py` already treats
      a mid-session toggle as *continue*, so the session boundary is not what needs changing.

---

### Batch 2 — Bankroll correctness

Small, subtle, and it cost a real trade — fold into Batch 1 if it lands early.

- [ ] **Changing the bankroll re-sizes nothing that already exists.** Root-caused from the
      code 2026-08-02, no game test needed. `_bankroll_changed` (`main_window.py:1124`)
      assigns `cfg.bankroll_divines` and starts the save timer; that is the whole handler.
      Sizing lives in `build_candidates` (`max_by_bankroll = int(bankroll_units // lot_pay)`,
      `listings.py:264`) from `cfg.bankroll()` at `sweep.py:179`. **The handler's docstring
      presents this as correct**, which is why it survived — it reads as decided rather than
      missed. Consequence measured 2026-08-02: a **599 div** row against a **260 div**
      bankroll, whispered, and the order could not be filled.
      - `cfg.bankroll()` is read **inside the per-item loop**, so the change lands
        progressively — a stale row's exposure is up to a full ~15-minute cycle. **Removing
        the drip does not fix this.**
      - **Re-size, do not drop** (decision 3): re-plan to what the new bankroll affords, drop
        only if that falls below `min_profit_divines`. `smallest_lot` / `replan_units`
        already do it and a partial ask is already a supported class of whisper.
      - **Both surfaces need it.** `trade_queue` holds submitted candidates independently of
        the sweep panel, and *Ready* is where the bad row was. `set_result` re-*ranks* where
        this needs re-*sizing*; `SweepResult` keeps candidates rather than listings, but
        `Candidate` carries its own `listing`, so re-planning from
        `[c.listing for c in result.candidates]` is cheap.
      - **Whispered rows must be left alone** — they record what was actually asked for.
      - *Precedent:* `_appetite_changed`, one method below, already re-ranks what is on
        screen rather than making the user wait fifteen minutes for a slider.

---

### Batch 3 — Table and window layout

- [ ] **The action buttons must never need a horizontal scroll.** Fixed width for the action
      section on both queue tables, fully visible at the window minimum. Shrinking comes out
      of **Item** and **Seller**, which keep content-derived floors rather than their four-
      and six-letter heading floors. **This amends the 0.8.0 rule** that a table scrolls
      sideways below the sum of its floors: right for a name column, wrong for buttons.
- [ ] **Reduce the window's minimum width** from 960 (`main_window.py:119`). The driver was
      *Long shots* wrapping in the bankroll bar, and there is free margin to its left — move
      it rather than keeping the window wide. Defines the real floor together with the item
      above.
- [ ] **Column widths mirror between the two queue tables.** Widening *Item* in one widens it
      in the other, so they read as one table split in half. Couples two `ColumnLayout`
      instances that are currently independent and both persist through `saveState` in
      `ui-state.json` — decide whether one blob is shared or two are kept in sync, and beware
      a feedback loop where each table's resize re-triggers the other's.
- [ ] **Add a *Found* column to *Ready to whisper*** showing when the opportunity entered the
      queue, in the same shape as *Sent* (`2m ago`). Makes the two column sets line up almost
      exactly, which is what makes the mirroring worth having.
- [ ] **Rename the *Auto* column to *Expires*.**
- [ ] **A minimum height for each queue section**, so neither collapses when the window is
      shortened. *Not* the `QSplitter` collapse-to-zero trap — `setChildrenCollapsible(False)`
      is already set and `_restore_ui_state` already rejects a saved zero. The floor is
      simply too low, and it matters more now the maintainer deliberately shrinks *Ready*.
- [ ] **The API-usage indicator stays yellow/red while idle.** The status bar's request
      counter should return to neutral once the window has drained and nothing has been used;
      today it holds the last burst's warning colour, which reads as a live rate-limit
      problem when the app is doing nothing.
- [ ] **The currency letter belongs outside the spin box**, right of the arrows — only the
      number in the field. `setSuffix(" div")` puts it inside, which reads as editable text.
      Collides with `_fits`/`setSpecialValueText`, which sizes the box around
      `"no limit (div)"`; the special value should become an **infinity sign**.
- [ ] **A session timer at the top, across from the action headline.** `session.py` already
      has the start.
- [ ] **A "Hide Listings Over 3 Days Old" toggle, off by default.** *Decided 2026-08-01 from
      the measurement behind it: 0 fills in 102 whispers at that age, in every band — 13% of
      every message the app has ever suggested.* Ranking already demotes them and the Age
      column already shows `6d`, so this is purely about reclaiming that 13% on a busy
      session. Mirror the *Hide the too-good-to-be-true ones* checkbox exactly. **Off by
      default is load-bearing, not a nicety:** a hidden row cannot be falsified, which is how
      `FILL_PRIOR[GHOST] = 0.0` survived four field tests. Needs a config key.

---

### Batch 4 — Icons and row polish

- [ ] **Replace the dingbat glyphs with vendored Lucide SVGs.** On Windows the detail is
      lost — *Ready to whisper* is tolerable, the seven-action *Waiting on a reply* row is
      **illegible**. **Matching the game's font environment is abandoned** (decision 4); the
      goal is clean and legible. The dingbats were verified by screenshot on **Linux only**,
      which is why this shipped — the next verification has to be a Windows screenshot.
      Confirm QtSvg survives the PyInstaller bundle.
- [ ] **Hovering one button highlights the whole button group for that row.** **A regression,
      not an unfinished fix** — 0.7.0's changelog ships it as user-visible ("It now
      highlights the button you're pointing at"), so it worked and broke under the 0.8.0
      icon-button rework, where the row's action widget was rebuilt. Look there first.
- [ ] **One-word tooltips on the row buttons** — *Re-copy*, *Accept*, *Decline*, … 0.8.0 put
      the full wording on hover; this shortens it. Change only the tooltip: `click_action`
      and the tests match on the button's `action` property.
- [ ] **Right-click → copy just `@username`** in *Waiting on a reply*, for following up with
      a seller who said "give me a couple of minutes" without re-sending the whisper. The
      existing *Re-copy* stays as-is for the full template.
- [ ] **Warn in Settings that another app's hotkey will silently win.** A label under the
      hotkey field: an overlapping binding in any other application, first or third party,
      blocks ours **with no error**. Measured against Sidekick 2026-08-02 — it simply takes
      precedence and the 0.8.0 diagnostic sees nothing, probably a low-level keyboard hook
      ahead of `WM_HOTKEY`. This replaces further detection work, which is called off.

---

### Batch 5 — The tab shuffle

**Two tabs are renamed past each other, so "Results" means different things before and
after.** *Trades* (`sweep_panel.py`) becomes **Results**; today's *Results* (`results.py`)
becomes **Trends**. So `results.py` will be the Trends tab while `sweep_panel.py` is the
Results tab. **Rename the modules in the same commit** or the next session reads them
backwards. Order becomes Opportunities, Results, Market, Trends, Log.

- [ ] **Rename *Trades* → *Results* and move it to second position**; *Market* becomes third.
- [ ] **Rename *Results* → *Trends*.** Contents otherwise unchanged.
- [ ] **"This session" is neither this session nor all of it, and it does not update live.**
      Rename to **Current Session**, offer it *only while a session is in progress*, and fix
      the staleness — new rows appear only after navigating away and back. Likely one root
      cause: `SESSION_LIVE` means "what the last sweep found" (its own tooltip says so),
      which is a different set from "what this session attempted", and it is rebuilt on show
      rather than on a queue/outcome signal. **Fix both together.**
- [ ] **Centre every column except Item and Seller** on the Results tab.
- [ ] **Remove the *Every trade* and *Every whisper* tabs.** The renamed *Results* tab now
      presents the same rows in a better structure. **This reverses a field request from
      2026-07-31**, and `results.py` carries a comment explaining why *Every trade* was added
      — **delete that comment with the tabs**, or the next reader restores them from it.
      Sequence after the rename, so the replacement exists before the copy goes.
- [ ] **Title Case every remaining piece of user-facing text** — section labels, status-bar
      lines, Settings rows, the Market and Trends tabs. 0.8.0 did the verdict vocabulary, the
      column headings, the row action names and the Trades filters. **Does not extend to the
      band vocabulary**: *worth trying* / *uncertain* / *too good to be true* are sentence
      fragments used inline, and the enum stays untouched.
- [ ] **Add 7-Day Trend, Volume/hour and Most Popular columns to Market from poe.ninja.**
      Check what the endpoint the app already calls returns first — the universe fetch may
      carry the sparkline and volume fields already, in which case this is display only.
      "Most Popular" needs defining against whatever poe.ninja actually publishes.

**Keep all three Trends breakdowns.** As of 2026-08-02 *By discount* is telling where it was
not on the smaller sample — the two tighter bands fill well above the stretch bands. Two
qualifications: it **corroborates rather than adds** (same log, same split `FILL_PRIOR` is
already fitted to, so **not** grounds to re-tune the prior), and ***By seller state* rests on
a flag measured 28% wrong** — GGG's API called 11 of 40 AFK sellers present. Keep the tab;
do not act on its numbers until the flag is audited.

---

### Batch 6 — Pricing (desk work, no game time)

**The biggest open item in the project.** It explains both known real losses, one of them
banded *plausible*. Full table in [docs/FINDINGS.md](docs/FINDINGS.md), *The reference price
does not match what a sale realises* → *Four more pairs, 2026-08-02*.

Seven pairs now span 110k–10.0M `ValueTraded`. Below ~600k the app quotes **at or above the
bid on 5 of 5** readings and above the *ask* on 4; above 1.6M it goes both ways. Median error
over the bid **+9.4%**. But the error is **not monotone** in liquidity (110k → +53%,
115k → −0.1%, 173k → +8.1%, 568k → +9.4%, 580k → +21.5%) and **book width does not predict
it** — Cowardly Fate has the tightest book ever measured here (0.6%) alongside the
second-largest error.

- [ ] **Analyse `ce_age_s` against `outcomes.jsonl`. Do this first.** 0.8.0 records it on
      every whisper and nobody has read it. A wrong *level* on a tight book is exactly what a
      stale reference price looks like, and it is the only axis the readings have not ruled
      out. Cheapest remaining test of the whole question.
- [ ] **Build a flat conservative floor below ~1M `ValueTraded`** — believe the bid, not the
      quote (+9.4% median, +21.5% observed worst case short of Astrid's), or refuse to band a
      thin item *plausible* at all. **Do not fit `haircut = f(ValueTraded)`; there is nothing
      to fit.**
- [ ] **Surface reference-price freshness.** `snapshot_age_s` exists and nothing shows it.
      Distrust or refuse a stale one.
- [ ] **Reset `min_gap_ratio` from the noise.** 56 whispers below 1.10× fill at 14%, so *fill
      behaviour* gives no reason to raise it — **do not read that 14% as vindicating 1.05.**
      The reason to raise it is that at a 1.05 gap the whole edge is inside the reference
      price's error bar. Same measurement problem wearing a different hat.
- [ ] **`MIN_PAIR_VALUE = 1000` still looks far too low.** Astrid's cleared it by 110× and
      was 53% wrong.
- [ ] **Fix the one-directional wording.** The *uncertain* band tooltip and Quick Lookup say
      the estimate "runs high" / "25% high", which is over-specific. It carries ~±6% on liquid
      pairs and more, one-directional, on thin ones.
- [ ] **`FILL_PRIOR[Band.THIN] = 0.5` is still a guess.** n=10, under `MIN_SAMPLES`, and its
      raw 20% fill rate would imply a weight above 1.0 — two fills' worth of noise.
- [ ] **Let the user apply `suggested_gap_band` from the Trends tab**, which already computes
      `value_per_attempt` — the right objective, and the one that revealed the ghost result.

> **Do not re-tune `FILL_PRIOR[GHOST]` on new fills without reading the stability warning in
> FINDINGS.** The ratio read 0.162 / 0.175 / 0.146 in one day, all resting on thirteen ghost
> fills; the estimate is worth ±0.02 and moving the constant on the middle reading was
> over-fitting. The **value** ratio is worse (0.66 → 1.25 → 0.82 in a day, crossing parity
> and returning on 83 whispers with no new ghost fills) and must never be quoted without its
> range.

---

## Backlog — not batched

Real work, none of it blocking the batches above.

- [ ] **Model gold, then let the app pick the settlement currency.** Measured 2026-07-30:
      ~120 gold per exalted, ~800 per divine, **confirmed flat 2026-08-01** whatever the
      quantity — so the bill is units-settled × rate, no rate table needed. Exalted minimises
      the rounding floor and maximises the gold bill: settling ~3,000 exalted costs ~360,000
      gold where the same value as ~7 divine costs ~5,600, and the maintainer ran dry
      mid-session. The *Settle in* dropdown asks the user to solve a two-variable problem the
      app has the numbers for. Replace it with a recommendation: **the finest denomination
      whose gold cost fits the gold you hold.** Gold cannot be bought for currency, so it is a
      constraint, not a term subtracted from profit — do not "convert gold to divines". Needs
      a gold-on-hand input; there is no API for it, the user must type it.
- [ ] **A Send button that whispers the seller, instead of only filling the clipboard.**
      **Route decided 2026-08-01: keystrokes.** `POESESSID` and the trade site's endpoint are
      off the table — drop that branch if it resurfaces. What the endpoint would have bought
      is worth remembering rather than re-arguing: it logs a *true* attempt (4 of 189 logged
      attempts were never actually sent) and a failed whisper doubles as a listing re-check.
      Both are now problems the keystroke route must solve another way, or accept.
      Evidence in [docs/FINDINGS.md](docs/FINDINGS.md), *GGG's trade site sends whispers
      server-side*.

      *Implementing it:* a button in the app means the app has focus, so this is the case
      needing `SetForegroundWindow` — Windows grants it only to a process that received the
      last input event, it is asynchronous, and sending before the switch lands is exactly how
      these tools type into the wrong window. **Verify the foreground actually changed, with a
      timeout, and abort rather than send blind.** Then Enter → Ctrl+A → paste → Enter,
      pasting rather than typing because the whisper is GGG's own localised template (the log
      carries Korean, Chinese, Russian, Portuguese and Spanish). A hotkey pressed *in game*
      needs none of this — the game is already in front — so button and hotkey are two
      different problems and the hotkey is the easy one.

      **It changes a hard constraint.** Rewrite CLAUDE.md and FINDINGS' *The line the app does
      not cross* in the same change, to: *one keypress or one click → exactly one message.
      Never on a timer, never in reaction to a reply, never more than one action per press.*
      Default **off**, `trade_hotkey_action = "copy" | "send"`, copy stays the shipped
      behaviour. Windows-only and untestable here — the shape of code that shipped broken
      twice — so carry the Settings press-counter idea forward and log every message sent.
- [ ] **Split NO_REPLY using the game's own log.** Measured 2026-07-31 against 189 attempts;
      numbers in [docs/FINDINGS.md](docs/FINDINGS.md), *What the game's own log can and cannot
      tell us*. The maintainer lifted the "no reading game state" constraint for passive log
      reading. The obvious feature is the worthless one:
      - *Auto-marking fills is not worth building.* All 11 fills were already hand-marked
        correctly; it would save clicks and nothing else.
      - *Splitting NO_REPLY is.* 22% of it is GGG's AFK auto-reply, landing within a second
        of the whisper rather than after a ten-minute timeout, and ~2% is a reply or an
        "already gone". A quarter of the denominator under every fill rate in the project is
        one bucket that is really three.
      - *It also audits a source we trust.* GGG's API called 11 of 40 AFK sellers present.
      Keep it **read-only and advisory** — mark a suggestion the user confirms, never write a
      verdict straight to the log. Tail from a stored offset (194 MB, append-only), prefer
      `LatestClient.txt` for a live session, derive the local-time offset by correlating
      rather than trusting the machine's zone, and match the AFK reply against the localised
      set — one log alone carries it in six languages.
- [ ] **The whisper budget is the real constraint and nothing models it.** ~2 whispers a
      minute is why chasing a 2% fill rate pays: the message is nearly free. So "is this worth
      whispering?" depends on how much session is left. **Reframed 2026-08-02:** the scarce
      resource is *not* interruption tolerance — that premise is dead — it is **throughput**,
      whispers sent per minute of sitting there. The rate framing is right, but as a *floor
      the app keeps the queue above*, rather than a ceiling it spends down.
- [ ] **Thanking a seller to mark the trade — parked.** The maintainer will use Sidekick's
      auto-thank. Worth knowing before relying on it: "answer the last whisper **received**"
      is right in 7 of 11 real trades (vs 2 of 11 for "last sent"), and two misses would thank
      a seller whose last message was `This player is AFK.` Harmless as a message, but **a
      "ty" in the log is not proof of a trade** — those lines must not be parsed back as fill
      markers. There is no party roster in `Client.txt` (checked), so party scanning cannot
      fix it either.

## Open — UX

- [ ] **Items the exchange trades but poe.ninja doesn't price are missing.** The game shows
      five Zarokh's Reliquary Keys; we show one. **126 of GGG's 753 tradeable items have no
      poe.ninja price** (Runes 70, Waystones 16, Fragments 9, Essences 8, Expedition 6, Breach
      5, Verisium 4, Ritual 4, Currency 2, Abyss 1, Gems 1). *Fix:* merge GGG's
      `/api/trade2/data/static` catalogue into the universe, unpriced rows showing an em-dash.
      **Not quick** — `Item.value_divine` is a float that sorting, adaptive units and
      `convert()` all assume is real, so unpriced items need a `priced` flag and a guard at
      each. Also: GGG's `sep` entries are separators, not items, and its groups don't map to
      in-game tabs for items poe.ninja doesn't categorise.
- [ ] **Org tree structures** in `src/poe2arb/gui/OrgTrees/*.txt`, one file per in-game tab,
      regenerated by `tools/dump_org_trees.py`. **Manual pass in progress** — generated output
      is flat two-level and each file is being hand-nested by group. `Currency.txt` is done
      and is the reference shape. Known weakness: `AtzirisTemple.txt` splits on the word
      "Vaal", which isn't a real distinction.
- [ ] **Hover tooltips explaining each item.** *Blocked on a source:* the exchange endpoint
      exposes only `id`, `name`, `image`, `category`, `detailsId` — no description text.
      Investigate a poe.ninja detail endpoint keyed on `detailsId`, or poedb. Decide before
      building.
- [ ] **Quick Lookup's four denominations are hardcoded** (`lookup.DENOMINATIONS`) — a
      judgement about where the Exchange has depth, and it will age. poe2scout's
      `/ReferenceCurrencies` publishes the real reference set and would be the honest source.
- [ ] **poe2scout endpoints we never used.** `/openapi/v1.json` lists `Currencies/ByCategory`
      (paged, takes a `referenceCurrency`, so it answers "what is this worth in annul?"
      directly), `Currencies/{apiId}` with `PriceLogs` and `CurrentPrice`,
      `ReferenceCurrencies`, and `Items/PriceHistory`. `SnapshotPairs` is the only one the app
      reads and the only one needing a derivation to be trusted — `CurrentPrice` needs no
      `rel/base` arithmetic at all.
- [ ] **GGG's own Currency Exchange API has both sides of the book — and we cannot reach it.**
      `service:cxapi` returns per-pair `lowest_ratio` / `highest_ratio` / stock / volume,
      exactly the both-sides measurement Batch 6 wants. **Blocked on client type, not effort:**
      it is a confidential-client scope and a distributed exe is a public client. The public
      CDN URL in the docs serves a stale July-2024 PoE1 snapshot whatever `realm` or `id` you
      pass. Re-test when GGG widens PoE2 coverage.
- [ ] Large values read oddly in fixed non-adaptive units (a Mirror in `ex`). Adaptive mode
      covers the default; decide whether fixed modes need scaling.
- [ ] Windows 11 hides new tray icons in the overflow, so closing the window while watching
      can look like the app vanished.

## Open — distribution

- [ ] Install flow unverified end-to-end on a real frozen exe. The v0.2.4 crash was exactly
      this gap. **If it recurs:** `%LOCALAPPDATA%\poe2-arb\poe2-arb.log`, grep for
      `install to ... failed` or `Start Menu shortcut`. The `--windowed` exe has no console,
      which is why the original occurrence left no trace.
- [ ] **Distribution hardening**: Microsoft false-positive submission (free), code-signing
      certificate (~$100–400/yr), `--onedir` as the free fallback.
- [ ] **Mobile push on a good trade.** Needs a delivery path — ntfy, Pushover, Telegram —
      plus a decision on whether the desktop app pushes directly.
- [ ] Packaging beyond one exe — PyPI for the CLI, Scoop/winget manifests.

## Next time you are in game

Not session work; the queue of things only playing can answer.

- **Just play, so the instrumentation fills up.** `stock` and `ce_age_s` are recorded on every
  whisper since 0.8.0 and both are unanalysed. `ce_age_s` is the live hypothesis for the
  pricing error and needs volume rather than attention. The published v0.8.0 exe is the build
  to play — no manual workflow run needed for this one.
- **No in-game pricing readings are wanted right now.** Seven pairs across 110k–10.0M do not
  resolve into a curve and more of the same will not change that. If `ce_age_s` points at
  staleness, the experiment is a **repeat of one item at two known reference-price ages** —
  a different design, to be specified when wanted.
  *Method, for reuse:* in-game quotes read **"I want : I have"**, so the first row is what you
  pay to **buy** and the second what you **receive** to sell. Take the app's number within a
  minute of the game's and note the clock time. `ValueTraded` can be recovered afterwards from
  a live `scout.snapshot()`.
- **The in-place editors on the Trades tab** are verified by screenshot on **Linux only**. The
  Result drop-down was widened past its own column to stop reading "No Repl", and that
  measurement comes from the font — the same assumption that just failed on the icons, so
  treat it as likely wrong. Also check that double-clicking a *live* row still copies its
  whisper rather than opening an editor.
- **Partial asks get answered?** Listings bigger than the bankroll are whispered for the
  affordable fraction. Worth knowing whether the reply rate is materially worse than on
  whole-lot asks — a new class of whisper the log can measure, once some have been sent.
- **Always-on-top floats over the game** in borderless windowed.
