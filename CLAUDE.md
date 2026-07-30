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
caught seven real bugs the test suite did not, including a startup `NameError`, stale cell
widgets painting over other rows, and a whisper quoting the wrong currency. Use it rather
than assuming a widget renders correctly because it constructs.

Releases are tag-driven: push `vX.Y.Z` and `.github/workflows/release.yml` runs the tests,
builds the Windows exe with PyInstaller, and cuts release notes from `CHANGELOG.md`. The
build **fails** if the tag has no matching changelog section, so write the entry first.
`__init__.py:__version__` and `pyproject.toml:version` must agree with the tag.

## Architecture

### The thesis the whole app rests on

PoE2 has two markets. The **Currency Exchange** (in-game, pooled orders, ~1% spreads) is
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

poe2scout runs 0.4%–4.7% low against in-game spot checks. That measured error is *why*
discounts under ~5% are banded uncertain rather than reported as profit — the threshold is
derived, not tuned.

### The pipeline

`scout.snapshot()` → `sweep.select_sweep_items()` (liquidity-ranked, floored by the whole-unit
settlement problem) → `client.GggExchangeClient.fetch_listings()` per item, paced →
`listings.build_candidates()` → `listings.rank_candidates()` → `trade_queue` offers them one
at a time → `hotkey` puts a whisper on the clipboard → `outcomes.jsonl` records what happened.

Two results from field tests are load-bearing in `listings.py` and must not be re-derived
(full evidence in [docs/FINDINGS.md](docs/FINDINGS.md), "Negative results"):

1. **Deep discounts do not fill.** ~10 whispers at 3.8x–12.5x gaps produced zero replies;
   both fills came from the two smallest gaps sampled. Large gaps are therefore *demoted*,
   and the `GHOST` band keeps them visible without wasting whispers.
2. **Settlement denomination decides the haircut.** Partial currency can't be traded, so
   proceeds floor to a whole unit of the settlement currency. Exalted is ~432× finer than
   divine; on the one trade that filled, settling in exalted turned 1.00 divine of profit
   into 1.79. Profit floors to `sale_unit_divines` — never to a whole divine, never unfloored.

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

Keep this file and TODO.md current the same way: update the affected section in the change
that caused it, not afterwards. A stale CLAUDE.md is worse than none, because it is read as
authoritative at the start of every session.

Config keys retired by a release go in `config.RETIRED_KEYS`, which drops them on load
rather than erroring — upgrading users have files full of them.

The league is auto-detected from poe.ninja each run. League names rotate every few months;
never hardcode one.
