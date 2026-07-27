# poe2-arb — TODO

Merged list (yours + mine). Shipped version: **v0.2.4**.

**Landed in v0.2.4**: install-prompt crash fixed; Market value at 2dp
with an Adaptive unit mode; toolbar unit selector reordered with abbreviations;
exclusion button shows a count instead of growing, with `•` markers on branches
holding a selection; bigger centred ticks in **In Graph**; "Quick Lookup" and
"Book Edges" capitalised.

---

## Aesthetic / UX

- [ ] **Item icons from poe.ninja** in Quick Lookup, Market and Book Edges, including
  during selection. *Feasible:* the overview response carries an `image` path per item
  (e.g. `/gen/image/…/CurrencyRerollRare.png`). Needs a disk image cache — 636 items —
  and a placeholder while loading.
- [ ] **Hover tooltips explaining each item**, same three tabs plus selection.
  *Blocked on a source:* the exchange endpoint exposes only `id`, `name`, `image`,
  `category`, `detailsId` — no description text. Options to investigate: a poe.ninja
  detail endpoint keyed on `detailsId`, or another source (poedb, CDR). Decide before
  building.
- [ ] **Smart search in the exclusion list and Quick Lookup**, working alongside the
  tree menus rather than replacing them. Type-to-filter with the tree still available.
- [ ] **Quick Lookup laid out like the in-game Currency Exchange**: "I Want" on the
  left with its picker beneath, "I Have" on the right with its picker beneath,
  "Market Ratio" centred with `x:y` below it.
- [ ] **Quick Lookup note should say live data is used when available.** Requires the
  functional change below — the note must not claim something the code doesn't do.
- [ ] **Org tree structures** from `src/poe2arb/gui/OrgTrees/*.txt` (Currency and
  Fragments filled in; others still templates). Base category order, verbatim:
  Currency, Essences, Runes, Abyss, Omens, Soul Cores, Idols, Liquid Emotions,
  Catalysts, Fragments, Uncut Gems, Lineage Gems, Expedition, Verisium.
  Note the renames vs poe.ninja's own names: Omens=Ritual, Liquid Emotions=Delirium,
  Catalysts=Breach, Lineage Gems=LineageSupportGems. **Last item — trees still being
  written.**
- [ ] Large values still read oddly in fixed non-adaptive units (a Mirror in `ex`).
  Adaptive mode covers the default case; decide whether fixed modes need scaling too.
- [ ] No type-to-find, window position not remembered, Log tab has no clear/export,
  Book Edges has no filter, no dark-mode check on the hardcoded banner/validation
  colours.

## Functional

- [x] ~~Install prompt crashed on first click~~ — `setOverrideCursor(None)`. Fixed and
  regression-tested; the whole dialog path had no coverage because it only runs from a
  frozen build.
- [ ] **Put all items in the arbitrage graph**, choosing what to actually track
  algorithmically since request budget can't cover 636 items. *Inputs available:*
  `volumePrimaryValue` (daily volume in divines) and `sparkline` (7-day trend:
  `totalChange` plus 7 daily points) per item, both already fetched. Volume/hour isn't
  published but can be derived. **Needs a design conversation** — scoring function,
  how many slots, whether the set is stable between scans or churns, and how it
  interacts with `max_currencies` and the rate-limit budget.
- [ ] **Extract the actual route from Bellman-Ford** when a longer cycle exists.
  Today it only proves one exists. Walk predecessor pointers to name it.
- [ ] **Quick Lookup should prefer live order-book rates** where a recent scan covered
  the pair, falling back to poe.ninja consensus otherwise — and label which it used.
- [ ] History file grows unbounded; no rotation or pruning.
- [ ] The banked history still has no reader — no trends, no "this loop appeared 6
  times this week". This was the stated reason for storing raw rates.
- [ ] Restarting re-notifies opportunities that are still live (backload restores the
  log and first-seen times, but not the "already told you" state).
- [ ] `depth_divines` is one global number; 5 divines means something different for
  chaos than for mirrors.
- [ ] Fee model is a flat per-hop percentage; the real exchange fee is gold-denominated.
- [ ] Install flow still unverified end-to-end on a real frozen exe (the crash above
  was exactly this gap — worth a manual run before relying on it).
- [ ] Windows 11 hides new tray icons in the overflow, so closing the window while
  watching can look like the app vanished.

## Future planning / discussion

- [ ] **Mobile push notification on opportunity alert.** Needs a delivery path — ntfy,
  Pushover, Telegram bot, or similar — plus a decision on whether the desktop app
  pushes directly or something runs headless.
- [ ] **Distribution hardening**: Microsoft false-positive submission (free, global),
  code-signing certificate (~$100–400/yr), `--onedir` as the free fallback.
- [ ] Longer cycles: brute force is O(n^k) and gets expensive if the graph widens,
  which would make Bellman-Ford the primary detector rather than the cross-check.
- [ ] Multi-league / Standard comparison.
- [ ] Packaging beyond one exe — PyPI for the CLI, Scoop/winget manifests.

---

## Deliberate decisions — do not "fix" these

- **Analysis only.** Never automates any in-game action, trade, whisper or input.
  Automating trading violates GGG's ToS. Hard requirement, not a gap.
- **Exclusions don't apply to Quick Lookup.** Excluding something from the scan
  shouldn't stop you pricing it.
- **Per-user install, never Program Files.** Elevating an unsigned binary to copy
  itself into a system directory is the dropper pattern we're avoiding.
- **`request_interval_s` must stay above 10s.** At exactly 10s a 300s window catches
  31 requests against a limit of 30; the penalty is a 30-minute IP ban.
- **Tier ordering is by measured price, not the alphabet.** "Greater" sorts before
  "Lesser" while outranking it; "Ancient" measures *below* its plain counterpart.
  Justifying numbers are in `market.py`.
- **Nothing is excluded by default** — that's the user's call.
- **Menus cap at 30 entries per submenu**; oversized groups split rather than relying
  on Qt to scroll or spill off-screen.
