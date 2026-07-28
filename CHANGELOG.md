# Changelog

Written for people using the app, not for people reading the diff. Each release
says what changed for you and, where it matters, why.

Versions follow `MAJOR.MINOR.PATCH`. Until 1.0 the minor number moves for
anything user-visible.

## [0.2.7] — 2026-07-27

### Changed
- **The Market tab now follows the in-game Currency Exchange.** Tabs in the
  game's own order — Currency, Essences, Delirium, Breach, Abyss, Atziri's
  Temple, Fragments, Runes, Ritual, Soul Cores, Idols, Uncut Gems, Expedition,
  Gems — plus an **All** tab for the full list. A second dropdown narrows to a
  group within the tab, and the search box (renamed from "Filter currencies")
  works on top of both.
- **Excluding an item moved out of Settings and into the Market tab.** Excluded
  items are no longer hidden from Market; they stay visible with a tick in a new
  **Excluded** column, and that tick is how you add and remove them — so you can
  see an item's price and volume while deciding. An **Excluded (n)** button
  shows the whole list in one place, with a Clear all. Changes save immediately.
- Atziri's Temple items (Architect's Orb, the Infusers, the Orbs of Sacrifice
  and the rest) now sit on their own tab rather than being buried in Currency,
  matching the game. Vaal Orb itself stays in Currency, as it does in game.

### Added
- **Item icons everywhere** — Market, Book Edges, Quick Lookup and both item
  pickers. They're fetched from the game's own asset CDN as items are shown and
  kept on disk, so the cost is paid once (about 5.9 MB) and never again. The
  cache sits alongside your other saved data, not inside the app folder, so
  updating the app never throws it away.
- **Trends tab.** What the saved scan history actually says over time: which
  loops keep coming back and how often, and which currencies are earning their
  place in the search versus occupying a slot without ever paying for it.
- **Restore Defaults** in Settings. Puts every setting back to its shipped
  value; your exclusion list is deliberately left alone, and nothing is saved
  until you press OK.

### Changed
- **Updating no longer asks.** If you already have an older version installed,
  launching a newer one replaces it silently and hands over — you chose to
  install it once, so being asked every release is a nag. Your settings, cached
  data and scan history are untouched, and an older copy can never overwrite a
  newer install.

### Fixed
- Category names in the exclusion list lost their `• N` marker the moment you
  ticked something inside them — which is exactly when it should have appeared.

## [0.2.6] — 2026-07-27

### Changed
- **The per-hop "fee" is gone, and profits will read higher as a result.** It was
  charging 1.5% per hop for two things that don't hold up: the Currency Exchange
  fee is paid in gold, which isn't tradeable or priced in Divine Orbs, so taking
  it as a percentage of divine value was a category error; and slippage was
  already handled by pricing each edge at the depth you set, so charging it again
  double-counted. A 3-hop loop was losing about 4.4% to this.
  The setting survives as **Safety margin per hop**, now defaulting to 0, for the
  cost that *is* real: the offer may be gone when you get there, and a partial
  fill can strand you mid-loop. Existing configs keep working — `fee_pct` is read
  as `safety_margin_pct`. Expect to see smaller opportunities that were previously
  being suppressed.
- The **After fee** column is now **After margin**, and matches the book rate
  exactly while the margin is 0.

### Added
- **Spread column on Opportunities.** A scan checks one currency at a time,
  several seconds apart, so no loop is ever priced all at once. This column says
  how far apart the prices in a chain were actually observed. A small spread
  means near-simultaneous prices and a more believable loop; a large one means
  the far end may already have moved. Shown in the CLI table too.
- Order books now carry the time they were fetched, which is what makes the
  above honest — including for cached responses, which can be several minutes
  old and previously looked as current as anything else.

## [0.2.5] — 2026-07-27

### Added
- **Bellman-Ford now names the loop it found.** Previously it could only tell
  you a profitable cycle existed somewhere outside your search window. It now
  reports the actual route, its profit and its depth, so you can judge it.
- **Quick Lookup prefers live order-book rates.** When the last scan covered the
  pair and is under 45 minutes old it uses real listings; otherwise it falls back
  to poe.ninja's consensus. It always says which one you're looking at.
- **Type-to-search in both item pickers.** A search box at the top of the menu
  shows a ranked flat list as you type; clear it and the category tree returns.
- **Filter boxes on Market and Book Edges**, and **Clear / Save to file** on the
  Log tab.
- **Window position, splitter and active tab are remembered** between runs.
- **`history_retention_days`** (Settings, default 30) prunes the saved scan log
  so it stops growing forever.

### Changed
- Quick Lookup is laid out like the in-game Currency Exchange: "I Want" left,
  "I Have" right, "Market Ratio" centred.
- Colours that were only legible on a light background now follow your theme.

### Fixed
- Restarting no longer re-notifies you about opportunities it already announced,
  as long as the last scan was under an hour ago.

## [0.2.4] — 2026-07-27

### Fixed
- **The first-run install prompt crashed when you clicked Install.** The whole
  dialog only runs from a packaged exe, which is why it escaped testing; it now
  has regression coverage.

### Added
- **Adaptive price units**, now the default: each item is shown in whichever
  currency reads most clearly, so a Mirror isn't quoted in hundreds of thousands
  of Exalted Orbs and a Wisdom Scroll isn't quoted as `0.00 div`.

### Changed
- The exclusion button shows a count instead of growing without limit, and marks
  which categories hold a selection.

## [0.2.3] — 2026-07-26

### Added
- **The full economy**, not just currency: 636 items across 14 poe.ninja
  categories, grouped into browsable menus.
- **Quick Lookup** — price any item against any other.
- **Per-user install** with a Start Menu shortcut, offered on first run.
- **Stop button** to cancel a scan in progress instead of waiting it out.

## [0.2.2] — 2026-07-26

### Added
- **Rate-limit guards.** Settings refuses request pacing that would get your IP
  temporarily banned, and warns when you get close. Throttling also adapts to
  GGG's own rate-limit headers, so other trade tools on the same connection are
  accounted for.

### Changed
- Cached data moved to the platform-native location (`%LOCALAPPDATA%` on
  Windows) instead of a stray dotfolder in your profile root.

## [0.2.1] — 2026-07-26

### Fixed
- Closing the window could hang the app on desktops with no system tray.

## [0.2.0] — 2026-07-26

Initial public release: arbitrage scanner CLI plus the PySide6 desktop app.
