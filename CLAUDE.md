# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Interpreter is the project venv — the system Python has no dependencies installed:

```sh
~/.venvs/poe2-arb/bin/python -m pytest -q          # full suite (~6s, 600+ tests)
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
caught eight real bugs the test suite did not, including a startup `NameError`, stale cell
widgets painting over other rows, a whisper quoting the wrong currency, and
`MarketPanel.set_exclusions` never syncing the table's ticks. Use it rather than assuming a
widget renders correctly because it constructs.

Traps when driving panels from a script: `MarketPanel` needs `set_universe(...)` **and**
`render(names=..., values=..., volumes=...)` before any row exists; a `QTableWidget`
check indicator is drawn on the leading edge whatever `setTextAlignment` says — centring one
needs a delegate (`table_items.CentredCheckDelegate`); and a `QSplitter` collapses a
collapsible pane to zero *regardless of its minimum size*, which is saved to `ui-state.json`
and reproduced on the next launch. Both splitters on the Opportunities tab therefore set
`setChildrenCollapsible(False)`, and `_restore_ui_state` rejects a saved zero rather than
clamping it.

Releases are tag-driven: push `vX.Y.Z` and `.github/workflows/release.yml` runs the tests,
builds the Windows exe with PyInstaller, and cuts release notes from `CHANGELOG.md`. The
build **fails** if the tag has no matching changelog section, so write the entry first.
`__init__.py:__version__` and `pyproject.toml:version` must agree with the tag.

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
where `min_gap_ratio = 1.05` came from. **That figure does not generalise.** Measured
2026-07-30 on the first two trades ever completed through the app — both losses — the same
derivation ran **26%–27% high** on thin items (Omen of Whittling, Astrid's Creativity). The
error is not a parsing bug: `rel/base` reproduces poe2scout's own published price to 1.006×,
so the source itself sits above what a thin sale realises. Liquidity is the discriminator.
**Treat the 1.05 threshold as known-wrong for anything but currency** until the fix in
TODO.md lands; see [docs/FINDINGS.md](docs/FINDINGS.md), "The reference price overstates thin
items".

### The pipeline

`scout.snapshot()` → `sweep.select_sweep_items()` (liquidity-ranked, floored by the whole-unit
settlement problem) → `client.GggExchangeClient.fetch_listings()` per item, paced →
`listings.build_candidates()` → `listings.rank_candidates()` → `trade_queue` offers them one
at a time → `hotkey` puts a whisper on the clipboard → `outcomes.jsonl` records what happened.

Two results from field tests are load-bearing in `listings.py` and must not be re-derived
(full evidence in [docs/FINDINGS.md](docs/FINDINGS.md), "Negative results"):

1. **Deep discounts fill rarely — not never.** *Corrected 2026-07-31 at n=156; the old
   claim was "they do not fill at all", from n=14.* Measured from `outcomes.jsonl`:
   plausible fills at **21%** (24 whispers), ghost at **2.3%** (131 whispers, including
   fills at 3.92x and 10.94x). Large gaps stay *demoted*, because plausible returns ~3.5x
   more **per whisper sent** — but `FILL_PRIOR[GHOST] = 0.0` is now known to be wrong, and
   ghosts earned **71% of the one profitable session's divines** on a fat tail. Do not
   re-assert that big gaps never fill, and do not hide them.
2. **Settlement denomination decides the haircut.** Partial currency can't be traded, so
   proceeds floor to a whole unit of the settlement currency. Exalted is ~432× finer than
   divine; on the one trade that filled, settling in exalted turned 1.00 divine of profit
   into 1.79. Profit floors to `sale_unit_divines` — never to a whole divine, never unfloored.
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

The league is resolved by `sweep.resolve_league`, which auto-detects and **never falls back
to a literal name**. It used to read `cfg.league or "Standard"`; Standard priced one measured
item 5.7× above the temp league, so a default install valued every listing against the wrong
economy and whispered sellers who could not answer.

### Layering

The core package is **Qt-free on purpose** — `trade_queue`, `rate_limit`, `outcomes`,
`icons`, `listings` and `install` all take injected clocks/clients so they test without a
display or a network. Keep it that way; the GUI wraps them, they never import from `gui/`.
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
- **Ghosts rank last, never hidden.** Hiding them would make the ranking unfalsifiable.

[docs/FINDINGS.md](docs/FINDINGS.md), "Deliberate decisions — do not 'fix' these", is the
full list. Read it before changing queue timing, banding, or anything that looks like an
oversight.

## Working in this repo

Three documents, deliberately split by how often they need reading:

- **This file** — architecture, commands, invariants. Loaded every session.
- **[TODO.md](TODO.md)** — what is not done, and the current state of play. Read it when
  picking up work. It takes priority over this file for anything in flight. Completed
  items are deleted rather than ticked.
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
`/mnt/c/Users/<user>/AppData/Local/poe2-arb/`. Join the `kind: "attempt"` and
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
