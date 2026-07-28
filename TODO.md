# poe2-arb — TODO

Merged list (yours + mine). Shipped version: **v0.2.6**.

**Landed in v0.2.5** — Bellman-Ford now names the loop it found instead of
just asserting one exists; Quick Lookup prefers live order-book rates and says
which source it used, laid out like the in-game Currency Exchange; type-to-
search in both item pickers; filter boxes on Market and Book Edges; Clear and
Save on the Log tab; window position, splitter and tab remembered between runs;
history file pruned on a retention setting; a restart no longer re-alerts loops
it already announced; hardcoded colours replaced with theme-aware ones.

---

## Aesthetic / UX

- [x] ~~Item icons from poe.ninja~~ — in Market, Book Edges, Quick Lookup and both
  pickers. Fetched from `web.poecdn.com` (GGG's static host, not the rate-limited
  trade API) on demand, cached to `<cache_dir>/icons` keyed on a hash of the CDN
  path, with a transparent placeholder until each arrives. **Measured on a real
  first run: 570 icons / 5.9 MB in ~20s** — the Market table lists every priced
  item, so the first render effectively asks for all of them. One-time: item art
  doesn't change between leagues, so the cache never expires.
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
- [x] ~~Extend the selection marker to parent sections in the exclusion picker~~ —
  `_refresh_markers` now counts recursively, so a category keeps its `• N` when the
  selection lives in a group submenu beneath it.
- [x] ~~Market tab: tabs instead of one very long list~~ — a QTabBar in the game's own
  order, plus **All**. Empty tabs are omitted.
- [x] ~~Market tab: real filters over the first and second level of categorisation~~ —
  tab (first level) and a group dropdown (second level) compose with search; all
  three narrow together. `Universe.groups_in_tab` merges the categories that share
  a tab (Expedition + Verisium) while keeping their groups distinguishable.
  Swap in the hand-written OrgTrees when they land.
- [x] ~~Exclusions become a Market column, not a Settings field~~ — checkbox column,
  excluded items stay visible, picker gone from Settings, `Excluded (n)` button opens
  the full list with Clear all. Saves on tick, with no re-render so the row stays put
  under the cursor. Book Edges still hides them: an excluded item is never a graph
  node, so that filter only ever acts on stale data, which is when it should.
- [x] ~~Rename the Market "Filter currencies…" box to "Search"~~.
- [x] ~~Restore Defaults button in Settings~~ — resets the widgets only, so Cancel
  still undoes it, and deliberately leaves the exclusion list alone (that's the
  user's curation, not a setting with a default).
- [x] ~~Split the Vaal / Atziri's Temple items out of Currency~~ — `VAAL_CURRENCY_IDS`
  in `market.py`, taken from GGG's static data rather than guessed from names
  ("Orb of Extraction" and "Ancient Infuser" carry no Vaal wording but belong;
  Vaal Orb itself does not). `Currency.txt` still needs regenerating.
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
  algorithmically since request budget can't cover 636 items.
  **Scope question answered (2026-07-27, one unmetered request to
  `/api/trade2/data/static`):** GGG's exchange accepts **754 items across 15
  groups**, including Runes (213), Essences (84), LineageSupportGems (76),
  Ritual (75), UncutGems (45) — plus Vaal and Waystones, which poe.ninja
  doesn't carry. **634 of poe.ninja's 642 ids match GGG's exactly**, so no
  mapping layer is needed. Live probes confirmed real books with real depth
  outside Currency: Uncut Skill Gem (Level 20) 96 offers/96 accounts,
  Essence of Delirium 85/85, Simulacrum 90/90. Rates reconcile against
  poe.ninja consensus, and the top-of-book "1:1" listings on cheap items are
  ordinary bait that `bait_filter_ratio` already removes. So "all items"
  means ~634, not ~50 — the ceiling is the request budget, nothing else.
  *Inputs available:*
  `volumePrimaryValue` (daily volume in divines) and `sparkline` (7-day trend:
  `totalChange` plus 7 daily points) per item, both already fetched. Volume/hour isn't
  published but can be derived. **Design agreed, awaiting the go-ahead:**
  - *Liquidity is a gate, not a term* — below the floor `effective_rate` drops the
    edge anyway, so scoring it lets volatility buy past a mechanical constraint.
  - *Volatility is the signal, and `totalChange` measures it wrongly* — that's net
    drift, so an item that rose 10% and fell back scores ~0 despite having been
    maximally volatile, which is exactly the item whose books are stale. Use the
    stdev of daily deltas from `sparkline.data` (cumulative, so `diff` it),
    exponentially weighted toward recent days.
  - *Volume is a tiebreaker with diminishing returns* — `log1p`, not raw. Raw volume
    as a driver is what produces today's "same ten currencies forever".
  - *Connectivity is why a fixed core exists* — cycles need shared counterparties;
    ten exotic items with no common bridge form no cycles at all. Divine/exalted/
    chaos are structural, not volatile.
  - So: `score = ewma_volatility × log1p(volume / floor)`, gated on the floor,
    filling rotating slots only. ~60% stable core (top-K by volume, always PRIMARY),
    ~40% rotating, with hysteresis so a 2% score difference doesn't cause churn.
    Volume behind a `VolumeSource` protocol so the cx API can swap in later.
  - **Caveat: "volatile items have stale books" is a hypothesis I can't validate
    from the data at hand.** Pair this with the history reader below, or we've
    replaced a defensible heuristic with an undefensible one that merely feels
    more sophisticated.
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
- [x] ~~Fee model is a flat per-hop percentage and both its justifications fail~~ —
  gold isn't divine-denominated so charging it as a percentage of divine value was a
  category error, and slippage was already captured by the depth walk. Now
  `safety_margin_pct`, defaulting to 0, documented as covering fill risk only.
  `fee_pct` is still accepted and translated on load, since `load_config` rejects
  unknown keys. Raises reported profit ~4.4% on a 3-hop loop: the noise floor moved.
- [x] ~~Temporal integrity: edges within one cycle are never observed at the same
  moment~~ — `Edge.observed_at` (from the cache's fetch time, not `now`) and
  `Opportunity.skew_s`, surfaced as a **Spread** column in both UIs and persisted to
  history. Deliberately *reported, not filtered* — see the measured numbers under
  "Deliberate decisions". Verified end to end on a live scan: all 38 edges stamped,
  observations spread over 4.7 minutes.
- [ ] **Re-verify candidates instead of filtering on skew.** When a cycle clears the
  threshold, re-fetch just its 2–4 edges back-to-back (~26–52s) and report only if it
  survives. Opportunities are rare so the request cost is near zero, and it upgrades
  "these existed sometime in a 4-minute window" to "confirmed within 39 seconds".
- [x] ~~Installer should update in place rather than prompt~~ — `decide_install_action`
  returns NONE / OFFER / UPDATE. A version marker beside the installed exe says what's
  there; a *newer* installed version is never downgraded by an old exe run out of
  Downloads, and declining the first-run offer doesn't suppress later updates.
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

## Reference: three taxonomies that don't agree

Measured 2026-07-27 from GGG's static data plus poe.ninja's categories. Any
category work has to pick one and map to it deliberately.

**In-game tab order** (from the Currency Exchange, authoritative for the UI):
All, Currency, Essences, Delirium, Breach, Abyss, Atziri's Temple, Fragments,
Runes, Ritual, Soul Cores, Idols, Uncut Gems, Expedition, Gems.

**Decision: the UI models the in-game selection**, not poe.ninja's categories and
not GGG's API groups. The mapping is fully determined — poe.ninja category (or
item) on the left, in-game tab on the right:

| poe.ninja | in-game tab |
|---|---|
| Currency, minus the 15 Vaal items below | Currency |
| those 15 Vaal items | **Atziri's Temple** |
| Essences / Delirium / Breach / Abyss / Runes / Ritual / SoulCores / Idols / UncutGems / Fragments | same name |
| Expedition **+ Verisium** | **Expedition** |
| LineageSupportGems | **Gems** |

Verisium has no tab of its own — the game files it under Expedition. Waystones
would sit under Fragments, but poe.ninja prices none of them so they never reach
our UI anyway.

**GGG's API groups are for trading only, never for display.** The API lumps
things the game separates:

| GGG API group | poe.ninja categories inside it |
|---|---|
| `Vaal` | SoulCores (34) + Currency (15) — the game splits these into *Soul Cores* and *Atziri's Temple* |
| `Ritual` | Ritual (38) + Idols (28) + Fragments (1) + SoulCores (1) — the game splits Ritual and Idols |
| `Expedition` | Expedition (24) + Idols (4) + Runes (4) |
| `Delirium` | Delirium (26) + Fragments (2) |

So: **group by poe.ninja category for display, and use GGG ids only for
trading.** Mapping the UI to GGG's groups would merge tabs the game keeps apart.

Other findings worth not rediscovering:

- **`sep` is a separator, not an item.** GGG's static entries include repeated
  `sep` rows for UI spacing. Filter them out or they become phantom items.
- **Waystones are tradeable but entirely unpriced by poe.ninja** (0 of 16). No
  consensus value means no fair rate, so the bait filter can't run — they can't
  be graph nodes as things stand.
- **76 of 213 runes are unpriced**, mostly `lesser-*` variants; ~137 are usable.
- **Verisium has no in-game tab** in the screenshot, though GGG groups it and
  poe.ninja prices 24 items. Worth confirming where the game puts them.

---

## Deliberate decisions — do not "fix" these

- **Release notes come from `CHANGELOG.md`, and a tag without a section fails the
  build.** `packaging/changelog_section.py` cuts the entry for the tag; the test
  job runs it before anything is built, so a release whose notes nobody wrote
  can't ship. GitHub's generated commit list is still appended underneath.
- **Skew is reported, never used to reject a cycle.** Measured on a real scan
  (Runes of Aldur, 2026-07-27, 38 edges over 15 observation times spanning
  4.7 min): of the 23 complete 3-cycles present, skew ran 60s / 220s / 263s
  (min / median / max). A 90s cap would have kept **1 of 23**; 180s keeps 6.
  A simulation of the request schedule agreed and was, if anything, optimistic.
  What survives such a cap is decided by iteration order in `fetch_books`, not
  by data quality. Re-verification is the answer, not filtering.

- **Analysis only.** Never automates any in-game action, trade, whisper or input.
  Automating trading violates GGG's ToS. Hard requirement, not a gap.
- **Exclusions don't apply to Quick Lookup.** Excluding something from the scan
  shouldn't stop you pricing it. It gets the unfiltered order book too.
  (Note: exclusions hiding rows from the *Market* tab is being reversed — see the
  Market items above. Quick Lookup's independence is the part that stands.)
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
