# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Interpreter is the project venv — the system Python has no dependencies installed:

```sh
~/.venvs/poe2-arb/bin/python -m pytest -q          # full suite (~6s, 770+ tests)
~/.venvs/poe2-arb/bin/python -m pytest tests/test_listings.py -q
~/.venvs/poe2-arb/bin/python -m pytest tests/test_listings.py::TestBands::test_ghost -q
```

`QT_QPA_PLATFORM=offscreen` is required for the GUI tests, which are most of the suite.

```sh
poe2-arb-gui                          # desktop app (the primary surface)
poe2-arb sweep --items 30 --limit 10  # CLI: one sweep, printed
python tools/dump_org_trees.py --only Runes   # regenerate OrgTrees reference files
```

**Verifying GUI work without a display** — set `QT_QPA_PLATFORM=offscreen`, construct the
widget, `app.processEvents()`, then `widget.grab().save(path)` and read the image. This has
caught thirteen real bugs the test suite did not, including a startup `NameError`, stale
cell widgets painting over other rows, a whisper quoting the wrong currency,
`MarketPanel.set_exclusions` never syncing the table's ticks, and — in 0.7.0, with a green
suite — half the Trades columns falling off the right-hand edge of the window. In 0.8.0,
again with a green suite, it caught all three of: an action column sized to a guess rather
than to its buttons, column growth compounding an overflow instead of absorbing it, and
every emoji button rendering as the same empty box. **A screenshot is the only thing that
sees any of these** — none of them raise, and none of them change a widget's API. Use it
rather than assuming a widget renders correctly because it constructs.

**What a Linux screenshot does not see: the fonts users actually have.** The 0.8.0 dingbat
buttons (✔ ✖ ⚑ ⚐ ❐ ✎ ☾ ⊘ ✕) were checked this way, drew cleanly, and shipped **illegible on
Windows** — verified in game 2026-08-02, worst in the seven-action *Waiting on a reply* row.
Anything whose correctness is a *glyph or a text measurement* — icon characters, a
`sizeHint` derived from a font, a drop-down widened to fit its longest label — is verified
here only provisionally, and needs a Windows build to confirm. The offscreen screenshot
proves layout and paint order; it does not prove legibility.

Traps when driving panels from a script: `MarketPanel` needs `set_universe(...)` **and**
`render(names=..., values=..., volumes=...)` before any row exists; a `QTableWidget`
check indicator is drawn on the leading edge whatever `setTextAlignment` says — centring one
needs a delegate (`table_items.CentredCheckDelegate`); and a `QSplitter` collapses a
collapsible pane to zero *regardless of its minimum size*, which is saved to `ui-state.json`
and reproduced on the next launch. Both splitters on the Opportunities tab therefore set
`setChildrenCollapsible(False)`, and `_restore_ui_state` rejects a saved zero rather than
clamping it.

**Columns on Opportunities and Trades go through `table_items.flexible_columns`.** Qt's
header offers reorderable, resizable and growing-with-the-window two at a time and never
all three, so `ColumnLayout` keeps the sections `Interactive` and does the growth itself:
size to contents once, squeeze that to fit the window, then hand out each later resize in
proportion. Four things it gets right that are easy to undo — the resize filter is on the
**viewport** and reads `event.size()` (a filter runs before the widget handles the event,
so the viewport's own width is still the old one); the action column is exempt from
shrinking, because a row of buttons squeezed does not get smaller, it gets clipped;
**every column's floor is its own heading text** (`min_width`), because one shared floor
truncated `Profit` into "rofit"; and **growth hands out the space the row does not fill,
not the space the window gained** — a row can already be wider than the window, and adding
the window's delta on top of that compounds the overflow instead of fixing it.
`resizeColumnsToContents` measures neither headings nor cell widgets, so both are corrected
after it runs. Order and widths persist through `saveState` in `ui-state.json`, and the
window's 960px minimum comes from `minimum_row_width()` rather than from taste.

Releases are tag-driven: push `vX.Y.Z` and `.github/workflows/release.yml` runs the tests,
builds the Windows exe with PyInstaller, and cuts release notes from `CHANGELOG.md`. The
build **fails** if the tag has no matching changelog section, so write the entry first.
`__init__.py:__version__` and `pyproject.toml:version` must agree with the tag.

**To get a testable exe without publishing one, run that workflow manually**
(Actions → Build & Release → Run workflow, against any branch). Same tests, same
PyInstaller build; it stops before the release step and leaves the exe as a build
artifact on the run. Added because this project is verified by playing the game — the
hotkey, the glyph rendering and the tray all behave differently on Windows — and until
0.8.0 the only way to get a build was to publish it to users, which is how a broken
hotkey shipped three times. **`workflow_dispatch` is only offered if the workflow file
is on the default branch**, so a change to the trigger has to reach `main` before it can
be used, whatever branch you then build.

The `dev` extra installs **PySide6**, which looks redundant next to `gui` and is not: 13
of the 30 test modules open with `pytest.importorskip("PySide6")`, so without it the
release gate silently skipped 313 of 682 tests while staying green (found 2026-07-31).
The workflow asserts the import separately, because a skipped test is not a passing one.
`build-windows-exe` has `needs: test`, so a failing gate blocks the release rather than
shipping past it.

## Architecture

### The thesis the whole app rests on

PoE2 has two markets. The **Currency Exchange** (in-game, pooled orders; ~1% spread measured
on one *liquid* pair, and not to be assumed for thin items — see FINDINGS) is
where essentially all trading happens. The **Bulk Item Exchange** (whisper-and-party, what
GGG's trade2 API serves) is largely abandoned, with listings sitting for days at stale
prices. There is no profitable loop *inside* either market — the edge is the gap *between*
them: buy an underpriced Bulk listing by whisper, resell into the Currency Exchange.

Versions ≤0.3.0 searched for arbitrage cycles within a single market, reading Bulk prices as
if they were live. That search never found a real trade and was deleted in 0.4.0 along with
`scan.py`, `graph.py`, `history.py`, `ScanWorker` and the `scan`/`watch`/`rates` CLI
commands. **Anything referencing cycles, Bellman-Ford, skew, node selection or
`depth_divines` is history, not a feature to restore.**

### Three data sources, each trusted for exactly one thing

| Source | Provides | Do not use it for |
|---|---|---|
| **poe2scout** (`scout.py`) | Currency Exchange reference price — the number you'd resell at | Anything but same-pair ratios; `RelativePrice` is *not* a base-currency price |
| **poe.ninja** (`client.py`, `market.py`) | Item universe: names, categories, volume, consensus value | The resale price — it isn't the CE |
| **GGG trade2** (`client.py`) | Live listings: who sells what, at what price, online or not | Display taxonomy (see below) |

poe2scout runs 0.4%–4.7% low against in-game spot checks **on liquid currency**, which is
where `min_gap_ratio = 1.05` came from, and **that figure does not generalise.** Measured
2026-07-30 on the first two trades ever completed — both losses — the same derivation ran
**26%–27% high** (Omen of Whittling, Astrid's Creativity). It is not a parsing bug:
`rel/base` reproduces poe2scout's own published price to 1.006×.

**Revised 2026-08-01, and the revision matters more than the original.** Both sides of the
in-game book were read against the app's own snapshot minutes later: the book is **~2%
wide** (Faded Crisis Fragment, Omen of Whittling) against a 1.7% liquid control, and the
app's error on those two was **−5.9% and +6.5% — opposite signs**. Omen of Whittling was
+37% on 07-30 and +6.5% today. So **on liquid pairs** the reference price is **noisy
(~±6%), not biased**, the spread explanation is disproved *there*, and the cause is price
*movement*. (Below ~1M `ValueTraded` none of that holds — see the next paragraph, which
was measured after this one and reverses it.) Consequences for
anyone touching this: build freshness, and `min_gap_ratio = 1.05` is still known-wrong but
now because 5% is *inside the noise*, not because of a 26% bias.

**All of the above is true of liquid pairs only, and 2026-08-02 reversed it below them.**
Astrid's Creativity (~110k `ValueTraded`) was read off both sides of the book: the book is
**22.2% wide** against a 1.7% liquid control, and the app sits **+53% above the bid** —
above even the *ask*. It explains both known real losses, one of which was banded
*plausible*. **Do not re-kill "thin items are overstated" by quoting the liquid numbers**;
1.6M and 10.0M `ValueTraded` is not where the app loses money.

**But the haircut is a floor, not a curve — four more pairs, same day, settled that.**
Tecrod's Gaze (115k), Uhtred's Saga (173k), Expedition Logbook (568k) and Cowardly Fate
(580k) were read the same way. Two results, and the second is the one that constrains code:

- **The direction holds.** Below ~600k `ValueTraded` the app quotes **at or above the bid on
  5 of 5** readings and above the *ask* on 4; above 1.6M it goes both ways. Median error over
  the bid **+9.4%**.
- **`ValueTraded` does not predict the size of it.** The error is non-monotone in liquidity
  (110k → +53%, 115k → **−0.1%**, 173k → +8.1%, 568k → +9.4%, 580k → +21.5%) and **book
  width does not predict it either** — Cowardly Fate has the tightest book ever measured
  here (0.6%) and the second-largest error. **Do not fit `haircut = f(ValueTraded)`.** Build
  a flat conservative floor below ~1M instead: believe the bid, not the quote.

A wrong *level* on a tight book is what a **stale** reference price looks like, so age is
the untested axis — `ce_age_s` is recorded on every whisper since 0.8.0 and has never been
analysed. See [docs/FINDINGS.md](docs/FINDINGS.md), "The reference price does not match what
a sale realises" → "Four more pairs, 2026-08-02".

### The pipeline

`scout.snapshot()` → `sweep.select_sweep_items()` (liquidity-ranked, floored by the whole-unit
settlement problem) → `client.GggExchangeClient.fetch_listings()` per item, paced →
`listings.build_candidates()` → `listings.rank_candidates()` → `trade_queue` offers them one
at a time → `hotkey` puts a whisper on the clipboard → `outcomes.jsonl` records what happened.

**Candidates are emitted per item, not per sweep** (`run_sweep(on_candidates=...)`). A sweep
is ~15 minutes; batching to the end meant silence followed by every offer at once, and made
the first item's listings a quarter of an hour stale before anyone saw them. `session.py`
brackets the whole loop: a session starts on *Find trades* and ends only when nothing is
running **and** nothing is outstanding, so pressing the toggle again mid-session continues
it. Its id and the league go on every attempt — neither is recoverable from the log
afterwards, and league names rotate.

**The app is used sitting in town with full attention, not glanced at mid-map** (measured
2026-08-02, the first real play session on 0.8.0). This corrects a premise that several
decisions were built on — the toast and alert-window model, the 30px buttons, "where someone
mid-map is looking", and `risk_appetite` as a tolerance for interruption. **Density and
throughput beat glanceability**; the scarce resource is whispers sent per minute of sitting
there, not the user's patience. **The whole interruption model is being removed as a
result** — decided 2026-08-02, **not yet built**, so read TODO before touching
`trade_queue` or `queue_panel`:

- *Ready to whisper* loses its one-per-`offer_window_s` drip; everything found lands in the
  queue immediately.
- It sorts by the hotkey's own ranking order, so **row 1 is always the trade the hotkey will
  take**. The old rule — oldest-first so nothing on screen moves — is reversed, with its
  cost recorded.
- **The toast and the alert window go.** `offer_window_s` and `alert_until` are removed and
  the config key retired; `OFFERED` stops gating visibility. The **● marker survives but
  stops being a state** — it means "row 1", which is now the same thing as "what the hotkey
  takes".
- **`expires_at` starts when a candidate enters *Ready***, not at promotion, and the
  floor-at-the-alert-window rule goes with the window. `available_ttl_s` and
  `awaiting_timeout_s` are untouched — **rows still expire.**

Full spec and the superseded rules with their original reasoning are in
[docs/FINDINGS.md](docs/FINDINGS.md), *The offer queue*.

Four results from field tests are load-bearing in `listings.py` and must not be re-derived
(full evidence in [docs/FINDINGS.md](docs/FINDINGS.md), "Negative results"):

1. **Deep discounts fill rarely — not never.** *Fitted at n=872 (2026-08-02), superseding
   n=789, n=156 and "they do not fill at all" from n=14.* Measured from `outcomes.jsonl`:
   plausible **13.4%** (n=194), ghost **1.95%** (n=666). `FILL_PRIOR[GHOST]` is **0.16** —
   the *fill-rate* ratio, **not** the value-per-whisper ratio, because the weight
   multiplies profit and the value ratio would count the fat tail twice. Consequence, and
   it is deliberate: a big enough ghost outranks a plausible. Do not re-assert that big
   gaps never fill, do not restore the 0.0, and do not hide them.
   **Do not re-tune the prior on new fills without reading the stability warning in
   FINDINGS.** The ratio was read three times in one day — 0.162 / 0.175 / 0.146 — and
   moving the constant to 0.17 on the middle reading was over-fitting. All three rest on
   thirteen ghost fills; the estimate is worth ±0.02. The **value** ratio is worse still
   (0.66 → 1.25 → 0.82 in a day, crossing parity and returning on 83 whispers with no new
   ghost fills) and must never be quoted without its range.
   **The counteroffer worry is closed** (2026-08-01): 36 of 37 fills went through at the
   listed price, checked against `Client.txt`, including both fat-tail fills the
   correction rested on and the 137.86× one, whose `Trade accepted.` lands 81 seconds
   after the whisper.

2. **A listing three days old has never filled** — 0 in 102 whispers, in every band,
   against a 4.56% base rate. `STALE_LISTING_S` gates on it and `rank_candidates` sorts
   those listings below everything fresh. It is a **cliff, not a decay curve**: below three
   days age barely predicts anything, so do not build a continuous freshness discount from
   it. Unknown age counts as fresh — `indexed` is missing on some responses, and that is
   not evidence of abandonment.
3. **A listing is a ratio, not a bundle.** `listings.smallest_lot` reduces
   `pay_amount:get_amount` to lowest terms, so "10 for 100 divine" is buyable 1-at-10 and a
   20-divine bankroll asks for 2 rather than being shown nothing. The floor on how finely
   it divides is the same one as below: partial currency cannot be traded, so 7:3 divides
   at nothing smaller. `TradePlan.pay_units` is what the whisper offers;
   `plan.lots × listing.pay_amount` is **wrong** now that a lot is the reduced one.
4. **Settlement denomination decides the haircut.** Partial currency can't be traded, so
   proceeds floor to a whole unit of the settlement currency. Exalted is ~432× finer than
   divine; on the one trade that filled, settling in exalted turned 1.00 divine of profit
   into 1.79. Profit floors to `sale_unit_divines` — never to a whole divine, never unfloored.
   Every attempt records `sale_unit_divines` and `settle_currency` from 0.8.0, so a
   correction can re-apply the same floor; older records fall back to a whole divine.
   **But exalted is not free:** the Exchange charges ~120 gold per exalted against ~800 per
   divine (measured 2026-07-30), so settling a high-value item in exalted can cost tens of
   times more gold and strand the user unable to trade at all. Gold is a budget constraint,
   not a cost in divines, and the app does not model it yet.

**Money is displayed in the currency the seller asked for, not in divines.** `Candidate`
exposes `pay_total` and `pay_per_unit` in `listing.pay_currency`, and the queue, the toast,
the log and the status bar all use them. `plan.cost_divines` is the same money in the unit
the arithmetic runs in and appears nowhere in the trade itself — shown alone, a listing
whispered as "2412 exalted" reads as "5.6 div", which the user cannot match to a reply that
arrives an hour later in a language they don't read. Profit stays in divines, because it is
the only unit the two sides can be compared in. `Candidate.settle_currency` records what a
row's profit was floored to, so the figure survives the setting being changed afterwards.
**Profit is signed and goes through `format.fmt_profit`** — an amended trade can have lost
money, and a hand-written `f"+{v:.2f}"` renders that as `+-2.80`.

**A trade is correctable in quantity *and* price, and neither correction mutates the
attempt.** `listings.replan_units` shrinks a trade to what the seller actually had;
`listings.repriced` moves the total to what they actually charged (a counteroffer — 1 fill
in 36, and the one that happened logged +38.00 divines while losing money). Both write an
**amendment record**, appended, so `asked_units` / `asked_pay_units` / `asked_cost_divines`
keep the original ask. Two entry points, because they reach different rows:
`outcomes.record_amendment` takes a live candidate and serves the Opportunities queue's
*Adjust…* dialog; `outcomes.plan_correction` + `record_correction` work from the logged
`Attempt` alone and serve the Trades tab, which is the only route back to a trade whose
listing is long gone. Do not "unify" them by making the Trades tab re-plan a candidate —
there isn't one. Changing a **verdict** needs neither: `record_outcome` already appends and
a later record already wins. Why one surface is a dialog and the other edits in place, and
why the log keeps the *whispered* gap after a reprice, are in
[docs/FINDINGS.md](docs/FINDINGS.md), *Correcting a trade after the fact*.

The league is resolved by `sweep.resolve_league`, which auto-detects and **never falls back
to a literal name**. It used to read `cfg.league or "Standard"`; Standard priced one measured
item 5.7× above the temp league, so a default install valued every listing against the wrong
economy and whispered sellers who could not answer.

### Layering

The core package is **Qt-free on purpose** — `trade_queue`, `rate_limit`, `outcomes`,
`session`, `icons`, `listings` and `install` all take injected clocks/clients so they test
without a display or a network. Keep it that way; the GUI wraps them, they never import from `gui/`.
`version.py` sits at package root rather than under `gui/` because the installer needs it
and the installer must not depend on the GUI layer.

Clients are injectable throughout (`run_sweep(ggg=..., snapshot=...)`) so whole flows run
offline. Parse functions are pure dict→dataclass and are tested against saved real API
responses in `tests/fixtures/`.

`tests/test_main_window.py` builds the real window against a throwaway config dir with only
the network workers stubbed. It exists because a startup crash shipped in 0.3.0 while every
panel was individually tested and nothing assembled them. Extend it whenever you touch
window assembly order.

**Anything two panels both display lives in one module.** `gui/bands.py` owns the band glyph,
short label and long tooltip because Trades and Results each had their own and showed the
same fact in two vocabularies. Import from it rather than restating a symbol. `format.py`
owns `currency_label` / `fmt_qty` / `fmt_amount` for the same reason — three panels had
drifted into three private copies of the currency suffix table.

**Internal band names and user-facing words are deliberately different.** The enum stays
`PLAUSIBLE` / `THIN` / `GHOST` — the code, the outcome log and `FINDINGS` all speak that
language — while the UI says *worth trying* / *uncertain* / *too good to be true*. Do not
"fix" the mismatch by renaming the enum: `outcomes.jsonl` stores the enum value, and
`bands.symbol_for_name` has to keep resolving records written months ago.

**`Outcome` gains members; it never renames them, for the same reason.**
`Outcome.NO_REPLY` is written by nothing since 0.8.0 and must keep resolving forever. It
was retired because it meant two different things depending on who wrote it: the timer
now writes `EXPIRED` (all it knows is that its deadline passed) and the user presses
**AFK** or **Offline**. Test "did they answer at all" with `Outcome.is_silence`, which
covers all four, rather than by naming members. User-facing wording for every verdict is
`outcomes.LABELS` / `label_for` — one map, because Opportunities, Trades and Results each
had their own copy and it is precisely the drift this file warns about elsewhere.

**A pinned row never expires, and unpinning does not restart its clock.** Pinning is the
answer to "is five minutes long enough?" — a seller who has spoken is not on a clock at
all. `expires_at` is untouched throughout, so a row released past its deadline resolves on
the next tick; anything else would make a row immortal by pin-and-unpin. Pin state is
per-session UI and is deliberately absent from `outcomes.jsonl`.

**A resolved listing is suppressed for the session** (`trade_queue.SETTLED_OUTCOMES`:
FILLED, SOLD, OFFLINE, DECLINED). A Bulk listing does not delist when its stock goes, so
every later sweep re-finds it, and `forget_resolved` drops the row that would otherwise
deduplicate it. `EXPIRED` and `AFK` are deliberately *not* in that set — an away seller
comes back, and a deadline passing says nothing about the listing.

### Four taxonomies that disagree

The UI models **the in-game Currency Exchange tabs** — not poe.ninja's categories, not GGG's
API groups. `market.INGAME_TABS` is authoritative for display order. The mapping lives in
`_CATEGORY_TO_TAB`, plus one split poe.ninja doesn't express: the 15 ids in
`VAAL_CURRENCY_IDS` sit in its Currency category but have their own Atziri's Temple tab in
game. That list came from GGG's static trade data, not from name-guessing — "Orb of
Extraction" carries no Vaal wording but belongs, and Vaal Orb itself does not.

GGG's API groups are for *trading only*; they merge tabs the game keeps apart. poe2scout has
a fourth taxonomy — it is a pricing source, never wire it to the UI.

`src/poe2arb/gui/OrgTrees/*.txt` are hand-edited reference files describing how grouping
*should* look; `tools/dump_org_trees.py` dumps how it looks *now*. They are documentation,
not runtime data — nothing in the app reads them.

Tiers sort by **strength, not alphabetically** (`TIER_RANKS`) — "Greater" precedes "Lesser"
alphabetically while outranking it. Ranks were checked against live medians, which is also
why "Ancient" sorts low: it consistently prices *below* its plain counterpart.

### Rate limiting is a safety system, not a nicety

GGG's widest per-IP window carries an **1800-second penalty**, and the IP is shared with the
trade website and any other tool the player runs. Overshooting locks all of it out for 30
minutes. Two independent guards: `rate_limit.py` does worst-case arithmetic *before* the
fact (the Settings dialog refuses to save a value that could get the user banned), and the
client reads `X-Rate-Limit-Ip-State` from every response to slow down *during* it. Note the
boundary subtlety encoded in the 13s default: requests 10s apart put **31** in a 300s window,
not 30.

## Hard constraints

- **Analysis only.** The app never automates any in-game action, trade, whisper or input —
  automating trading violates GGG's ToS. This is a requirement, not an unfinished feature.
- **The hotkey writes to the clipboard and nothing else.** No synthetic input, no reading
  game state, no watching chat, never auto-Enter. An optional off-by-default Ctrl+V paste may
  ship; reacting to a reply may not.
- **No fill rate is claimed below `outcomes.MIN_SAMPLES`.** The Results tab shows an em-dash
  and says how many more whispers it needs. Do not soften this to "show it greyed out".
- **Nothing is ever hidden from the queue** — not ghosts, not stale listings. Both are
  *demoted*, by a measured weight rather than a rule. Hiding either would make the ranking
  unfalsifiable, which is exactly how `FILL_PRIOR[GHOST] = 0.0` survived four field tests.
  ("Ghosts rank last" was the rule until 2026-08-01 and is no longer true: a big enough
  ghost outranks a plausible, because at a ~2% fill rate it should.) **One exception, and
  it is the user's own switch:** `queue_ghosts = risk_appetite > 0.0`, so at *Long shots* 0
  ghosts are not queued at all. Above zero **every** ghost is; the slider then only
  re-weights them (`fill_weight`: 0.16 → 0.58 at 50% → 1.0). Raising it past 50% pulls in
  nothing new. The app must never make that call on its own.

[docs/FINDINGS.md](docs/FINDINGS.md), "Deliberate decisions — do not 'fix' these", is the
full list. Read it before changing queue timing, banding, or anything that looks like an
oversight.

## Working in this repo

Three documents, deliberately split by how often they need reading:

- **This file** — architecture, commands, invariants. Loaded every session.
- **[TODO.md](TODO.md)** — what is not done, and the current state of play. Read it when
  picking up work. It takes priority over this file for anything in flight. Completed
  items are deleted rather than ticked. **Open work is grouped into numbered batches, each
  a session-sized unit ordered by dependency** — take the lowest-numbered unfinished batch
  unless told otherwise, and finish one before starting the next rather than cherry-picking
  across them. It also carries a *Decisions taken* section: read it before re-litigating
  anything that looks like an open question. **Keep the file short.** Anything measured
  belongs in FINDINGS and anything shipped in CHANGELOG; TODO holds a pointer, not a copy.
  It reached 900 lines of mostly-historical narrative once and was cut in half on
  2026-08-02 without losing a single open item.
- **[docs/FINDINGS.md](docs/FINDINGS.md)** — measured evidence and standing decisions.
  Read the relevant section before changing that subsystem; do not load it wholesale.

`CHANGELOG.md` holds shipped work and feeds the release notes.

### Recording findings — do this unprompted

**When something is established by measurement, append it to
[docs/FINDINGS.md](docs/FINDINGS.md) before moving on.** Do not wait to be asked, do not
batch it to the end of the session, and do not assume the maintainer will remember to file
it — the entire value of that file is that these facts cost real time to obtain and are
almost free to lose. The triggers, in full:

- A number was measured against a live API, the game itself, or a real trade.
- A probe returned a **negative** result — something that looked promising and was not.
  These are the easiest to lose and the most expensive to re-derive.
- A choice was made that a later reader would mistake for an oversight or a bug.
- An approach was tried and rejected for a reason that would otherwise get re-tried.

Append to the section it belongs in, carrying **the date and the sample size** — a finding
without its evidence is an opinion, and a fill rate from three whispers is not a rate. When
a new measurement supersedes an old one, replace the number and say what changed; never
silently drop the earlier figure, because the size of the correction is itself information.

**Read `outcomes.jsonl` before writing up a field test.** Every whisper and every verdict
is logged automatically, with band, gap, cost and expected profit — on Windows at
`%LOCALAPPDATA%\poe2-arb\outcomes.jsonl`, from WSL at
`/mnt/c/Users/<user>/AppData/Local/poe2-arb/`. **The game's own log is readable too** and
answers things ours cannot: `…/steamapps/common/Path of Exile 2/logs/Client.txt` (194 MB,
append-only; `LatestClient.txt` is the current session). It carries our `@To` whispers
verbatim, every `@From`, `Trade accepted.`/`Trade cancelled.`, `: <char> is not online.`
and `has joined the area` — joined against `outcomes.jsonl` on 2026-07-31 it produced most
of that day's findings. Its timestamps are **local, not UTC**; derive the offset by
correlating `@To` lines against logged attempts rather than trusting the machine's zone. Join the `kind: "attempt"` and
`kind: "outcome"` records on `id`. A session described in conversation as "made about 20
divines" sounds like an anecdote and is actually 147 fully-resolved whispers; that exact
mistake was made on 2026-07-31 and put "no fill-rate data was recorded" into this file over
the top of the data that overturned its biggest finding. **The operator's summary is not
the record.**

Keep this file and TODO.md current the same way: update the affected section in the change
that caused it, not afterwards. A stale CLAUDE.md is worse than none, because it is read as
authoritative at the start of every session.

Config keys retired by a release go in `config.RETIRED_KEYS`, which drops them on load
rather than erroring — upgrading users have files full of them.

The league is auto-detected from poe.ninja each run. League names rotate every few months;
never hardcode one.
