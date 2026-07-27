# Changelog

Written for people using the app, not for people reading the diff. Each release
says what changed for you and, where it matters, why.

Versions follow `MAJOR.MINOR.PATCH`. Until 1.0 the minor number moves for
anything user-visible.

## [Unreleased]

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
