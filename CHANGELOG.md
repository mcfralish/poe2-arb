# Changelog

Written for people using the app, not for people reading the diff. Each release
says what changed for you and, where it matters, why.

Versions follow `MAJOR.MINOR.PATCH`. Until 1.0 the minor number moves for
anything user-visible.

## [0.3.0] — 2026-07-29

The app was looking at the wrong market. This release moves it to the right one,
and the way you use it changes completely.

### The short version

Path of Exile 2 has **two currency markets**. The in-game **Currency Exchange**
is where essentially all trading happens: pooled, automatic, works while you're
offline, spreads around 1%. The **Bulk Item Exchange** — the one the official
trade API serves, and the one this app has been reading since v0.1 — is the old
whisper-and-party system, and it is effectively abandoned.

That is why the app never found anything. Arbitrage loops inside a dead market
don't exist. But the *gap between* the two markets is large and real: people
still list items on the abandoned exchange at prices the live one moved away
from months ago.

So poe2-arb no longer hunts for trading loops. It watches for listings priced
below Currency Exchange value, and tells you about them one at a time.

### Added
- **A Trades tab.** Checks live listings for the items the Currency Exchange
  actually trades, and shows what each one would cost and clear. Around 65 items
  per sweep, roughly 15 minutes, paced to stay well inside the trade API's
  limits.
- **The Opportunities tab is now a queue.** One trade is offered at a time with
  a notification and a countdown. Take it and it moves to "Waiting on a reply";
  ignore it and it drops into a list below for a few minutes before expiring. A
  second alert never fires over an unread one.
- **A global hotkey** (off by default; Settings). Press it anywhere, including
  in game, and the trade's whisper goes to your clipboard — paste with Ctrl+V
  and press Enter. **The app never types into the game or sends anything for
  you.** The whisper is GGG's own, already translated into the seller's
  language.
- **One-click outcomes.** Traded, No reply, or Already sold, straight on the
  row. Anything left unanswered marks itself as "no reply" after ten minutes.
  These are recorded so the app can learn which kinds of listing actually fill —
  right now that judgement rests on 14 real attempts, and it shows.
- **A "check first" step.** Before copying a whisper, the app re-checks that the
  listing still exists. Listings disappear within minutes, and this was the
  single most common wasted message.
- **Currency Exchange prices, from poe2scout.** Around five times more accurate
  than the previous source: measured against the live game, within 1% on average
  instead of 5%.

### Changed
- **Take payment in Exalted Orbs when you sell, not Divine.** You cannot trade
  partial currency, so a sale worth 3.79 divines pays you 3 if you ask for
  divines — and 3.789 if you ask for exalted, which is over 400 times finer. On
  a real trade that was 44% of the profit, given away to rounding. The app now
  assumes exalted settlement; you can change it in Settings.
- **The arbitrage loop detector is still there but no longer has a tab.** Scan
  and Watch still run it. It is kept in case the Currency Exchange ever opens up
  a proper order book, which is the only situation where it could work.

### Fixed
- **Only online listings are fetched now.** Previously 96% of results were dead
  listings from players who logged off weeks ago, and because the trade site
  sorts by best price first, they filled the whole first page — so the app was
  usually looking at a wall of junk offers and nothing else.

### Known limits
- Deep discounts mostly don't fill. Across 14 real attempts, the only two that
  worked were the *smallest* discounts; every attempt at a 4x–12x "bargain" was
  ignored or already sold. Those listings are shown, and ranked last, on
  purpose.
- Profit per trade is around a divine. This is a tool for making a keypress
  worth it, not for getting rich.

## [0.2.8] — 2026-07-28

### Fixed
- **The Market tab collapsed to about 50 items after every scan.** A scan only
  looks up the Currency category, and the Market tab was being rebuilt from
  that, so everything else vanished until you restarted the app — and excluded
  items showed their internal ids ("soul-core-of-zalatl") instead of their
  names. Market now always shows the full economy, with the scan's fresher
  numbers layered on top.
- **The install prompt kept appearing even when the app was already installed.**
  Versions before 0.2.7 didn't record which version they installed, so 0.2.7
  read an existing install as an empty folder and offered to install again every
  launch. An unmarked install is now recognised and quietly updated.
- **The app now keeps a log file**, at `poe2-arb.log` next to your cached data.
  The windowed exe has no console, so until now every internal log message was
  thrown away — including the details of an install failure, which is exactly
  the message you'd want after clicking past the dialog. A failed Start Menu
  shortcut also now says *why* it failed rather than just reporting a number.

### Changed
- **The window is narrower and no longer wastes space.** Market columns size to
  their contents rather than stretching, and the tabs are tighter, so all 15 fit
  at 900px wide instead of needing 1100px.

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
