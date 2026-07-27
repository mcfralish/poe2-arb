# poe2-arb — TODO

Merged list (yours + mine). Shipped version: **v0.2.5**.

**Landed in v0.2.5** — Bellman-Ford now names the loop it found instead of
just asserting one exists; Quick Lookup prefers live order-book rates and says
which source it used, laid out like the in-game Currency Exchange; type-to-
search in both item pickers; filter boxes on Market and Book Edges; Clear and
Save on the Log tab; window position, splitter and tab remembered between runs;
history file pruned on a retention setting; a restart no longer re-alerts loops
it already announced; hardcoded colours replaced with theme-aware ones.

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
- [x] ~~Smart search in the exclusion list and Quick Lookup~~ — a search box at the top
  of each picker menu; typing shows a flat ranked list of matches, clearing it brings
  the category tree back. Ranked by where the match lands, so "orb" leads with
  *Orb of Annulment* over *Divine Orb*.
- [x] ~~Quick Lookup laid out like the in-game Currency Exchange~~ — "I Want" left,
  "I Have" right, "Market Ratio" centred with `x : y` beneath, reading left-to-right
  in the same order as the columns.
- [x] ~~Quick Lookup note should say live data is used when available~~ — it now names
  the source and, for live rates, how old the scan was.
- [ ] **Org tree structures** from `src/poe2arb/gui/OrgTrees/*.txt`. Every file now
  holds the app's *current* grouping, dumped by `tools/dump_org_trees.py` from the
  same `by_category_and_tier` call the menus use — so edits start from what the app
  really does. `Currency.txt` is hand-written and the tool refuses to touch it
  without `--force`. Files are named for poe.ninja's own categories (Ritual,
  Delirium, Breach, LineageSupportGems), not the in-game display names.
  Base category order, verbatim: Currency, Essences, Runes, Abyss, Omens, Soul
  Cores, Idols, Liquid Emotions, Catalysts, Fragments, Uncut Gems, Lineage Gems,
  Expedition, Verisium. **Waiting on the edited trees.**
- [ ] **Extend the selection marker to parent sections in the exclusion picker.**
  *Root cause found:* `rebuild` counts a category's selections across all its groups,
  but `_refresh_markers` recounts from each menu's *direct* item children only. A
  category whose children are group submenus therefore scores 0 and loses its `• N`
  the moment anything is ticked. Both levels need a recursive count.
- [ ] Large values still read oddly in fixed non-adaptive units (a Mirror in `ex`).
  Adaptive mode covers the default case; decide whether fixed modes need scaling too.
- [x] ~~Window position not remembered~~ — geometry, splitter and active tab are kept
  in `ui-state.json` in the cache dir, with a guard against restoring onto a monitor
  that's been unplugged.
- [x] ~~Log tab has no clear/export~~ — Clear and "Save to file…".
- [x] ~~Book Edges has no filter~~ — filter boxes on Book Edges and Market. They hide
  rows rather than rebuilding, so sort order and scroll position survive typing.
- [x] ~~No dark-mode check on the hardcoded banner/validation colours~~ — `gui/theme.py`
  picks per-role colours off the palette's lightness.
- [ ] No type-to-find *within* a table (the filter boxes cover the same need; revisit
  only if they turn out not to).

## Functional

- [x] ~~Install prompt crashed on first click~~ — `setOverrideCursor(None)`. Fixed in
  v0.2.4 and regression-tested.
- [ ] **Put all items in the arbitrage graph**, choosing what to actually track
  algorithmically since request budget can't cover 636 items. *Inputs available:*
  `volumePrimaryValue` (daily volume in divines) and `sparkline` (7-day trend:
  `totalChange` plus 7 daily points) per item, both already fetched. Volume/hour isn't
  published but can be derived. **Needs a design conversation** — scoring function,
  how many slots, whether the set is stable between scans or churns, and how it
  interacts with `max_currencies` and the rate-limit budget.
- [x] ~~Extract the actual route from Bellman-Ford~~ — `find_negative_cycle` walks
  predecessor pointers and returns the loop; it's priced like any other opportunity
  and logged by name, with the profit and depth, so it can be judged rather than
  merely believed.
- [x] ~~Quick Lookup should prefer live order-book rates~~ — uses the last scan's book
  for the pair when it's under 45 minutes old, poe.ninja otherwise, and says which.
- [x] ~~History file grows unbounded~~ — `history_retention_days` (default 30, 0 = keep
  everything), pruned after append once the file passes 2 MB. Rewrite goes via a temp
  file so an interruption can't truncate real data.
- [ ] The banked history still has no reader — no trends, no "this loop appeared 6
  times this week". This was the stated reason for storing raw rates.
- [x] ~~Restarting re-notifies opportunities that are still live~~ — the newest restored
  scan's loops count as already announced, but only while it's under an hour old;
  older than that, a loop reappearing is genuinely news.
- [ ] `depth_divines` is one global number; 5 divines means something different for
  chaos than for mirrors.
- [ ] Fee model is a flat per-hop percentage; the real exchange fee is gold-denominated.
- [ ] Install flow still unverified end-to-end on a real frozen exe (the v0.2.4 crash
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
  shouldn't stop you pricing it. It gets the unfiltered order book too.
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
- **Quick Lookup shows the book rate, not the after-fee rate.** A lookup asks what a
  pair is offered at; the haircut belongs to the profit calculation.
- **UI state lives in a JSON file in the cache dir**, not in the TOML config (which is
  meant to stay hand-editable) and not in QSettings (which would write to the Windows
  registry, contradicting "delete the folder to remove it").
  - **No peer-to-peer data sharing between clients.** Considered and rejected.
  Request cost is ~n²/have_chunk, so pooling budget across P peers buys only
  √P graph width — 4,000× peers to reach 636 items. Federated edges also
  arrive at different timestamps, and Bellman-Ford will happily find a cycle
  assembled from edges that were never simultaneously true: a phantom-arb
  generator that looks legitimate. GGG's rate-limit rules include `client`,
  so aggregate per-application throttling already exists and can be applied
  at any time. If sharing is ever revisited, it is a central relay the
  maintainer operates, not P2P.
- **Currency Exchange API (`service:cxapi`) — not pursuing.** Requires a
  confidential OAuth client, which requires a server on an HTTPS domain the
  maintainer controls. Public/desktop clients cannot use `service:*` scopes
  at all, so it can never ship inside the exe. Out of scope for a local tool.
  For the record if this is ever revisited: hourly *historical* digests only,
  no current-hour data, so it wouldn't replace the live book anyway — the
  value was per-pair traded volume and hourly low/high ratios economy-wide
  for one request an hour.
