# Changelog

Written for people using the app, not for people reading the diff. Each release
says what changed for you and, where it matters, why.

Versions follow `MAJOR.MINOR.PATCH`. Until 1.0 the minor number moves for
anything user-visible.

## [0.6.0] — 2026-07-31

The second field test, and the first profitable one — about 20 divines cleared. Almost
everything here comes from that session. The pricing warning below still stands.

> **Prices are still optimistic on rarely-traded items.** Nothing in this release
> changes the arithmetic; see the 0.5.0 note. Liquid currency is fine, thin items are
> not, and the *uncertain* rating says so.

### Fixed

- **The global hotkey did nothing when pressed.** It registered, said so in the log,
  and then silently ignored every keypress — the code that reads Windows key events
  was missing an import, and the resulting error was being swallowed. Fixed, and if
  it ever fails again the app now says so instead of going quiet.
- **The hotkey now works whenever a trade is takeable**, not only during the few
  seconds a new trade is flashing. If nothing is flashing it takes the top row of
  *Ready to whisper* — the one closest to expiring.
- **Trades could cost more than you have.** Each one was sized against your whole
  bankroll, so with 500 exalted you could be offered, and accept, four separate
  400-exalted trades. Currency promised to a whisper you're still waiting on is now
  held back, and shown next to the bankroll boxes. Say what happened — or let it time
  out — and the money frees up again.
- **"Ones I messaged" and "Ones I bought" on the Trades tab were always empty.** They
  only knew about whispers copied from that table, and almost every whisper comes from
  the Opportunities queue instead. They also forgot everything on each new pass — and
  a listing you *bought* is gone from the next pass by definition. Both now follow
  whatever you actually did, and keep it for the session.
- **Ready to whisper now gets the full time you set.** The few seconds a trade spent
  flashing were being spent out of its listed time, and the countdown on a flashing
  row was describing the alert rather than when it would really drop off. One clock
  now, meaning the same thing on every row.
- **Neither half of the Opportunities tab can be lost any more.** Dragging a divider
  all the way shut collapsed a section to nothing and remembered it, so it stayed
  collapsed after a restart with nothing to explain it.
- **The verdict buttons on the Trades tab could stay live after a new pass**, against
  a listing you had never messaged.

### Changed

- **Costs are shown in the currency the seller asked for**, everywhere — the queue,
  the alert, the log, the status bar. A listing whispered as "2412 exalted" used to
  appear as "5.6 div", which is unrecognisable as the offer you made when a reply
  arrives an hour later in a language you don't read. Both tables now also show the
  price per item and which currency the trade settles in.
- **Ready to whisper puts new trades at the bottom; Waiting on a reply puts them at
  the top.** Ready is read top-down and shouldn't reshuffle under your cursor; a reply
  is almost always to the whisper you just sent.
- **Declining a trade means it won't come back.** It used to reappear on the next
  pass, ten minutes later.
- **Copy again** on a whisper you're waiting on, for when a seller answers and you
  need the offer repeated. It doesn't count as a second attempt.
- **The two Opportunities sections have a divider between them**, like Quick Lookup.
- **Quick Lookup swaps round.** "1 Omen of Whittling is worth 2,987 ex" or "1 div is
  worth 0.145 Omens" — the second is how you size a purchase. One side is still always
  a currency the Exchange has depth in; this is not the any-pair converter that was
  removed in 0.4.0. It also can't be squeezed shorter than its price note now.
- **Hovering any button in a row highlights that row**, so it's clear which trade
  Accept, Decline or a verdict is about to act on.
- **Settings: "Trade stays listed for" and "Mark as no reply after" are in minutes.**
- **Settings: keep the window above other windows**, for heavy trading sessions.
  Off by default. Use borderless windowed — full-screen games ignore it.

## [0.5.0] — 2026-07-30

The first real field test. Two trades went through and both lost money, which found
one serious bug, several smaller ones, and one thing the app gets wrong that is
**not fixed yet** — read the warning below before trading on this build.

> **Prices are optimistic on rarely-traded items.** Our Currency Exchange figure ran
> about 26% above what a sale actually fetched on both items traded, which was enough
> to turn two apparent profits into losses. Liquid currency is fine; Omens, Runes and
> anything thin is not. Until that is fixed, treat the profit on a thin item as a
> best case, not an estimate. The *uncertain* rating and Quick Lookup now say so.

### Fixed

- **The app could price your trades against the wrong league.** With no league set —
  the default — the search fell back to Standard while the rest of the app followed
  the current league. Standard has years of accumulated currency, so one measured item
  priced 5.7× higher there: every listing looked like a windfall, and no seller could
  ever reply, because they were in a different league. The league is now detected
  properly and never guessed.
- **Switching off Find trades now actually stops.** Offers kept arriving for minutes
  afterwards, because the queue kept working through the backlog it had already found.
  Stopping now clears what hasn't been offered yet, and leaves anything you're
  mid-way through — offers on screen and whispers waiting on a reply — alone.
- **The hotkey couldn't be set.** The field was greyed out until you ticked the
  checkbox above it, and that checkbox ships off, so on a fresh install it looked
  broken. It's always editable now.
- **Exclusion ticks went stale.** Changing the excluded items in Settings updated the
  count on the button but not the ticks in the Market table.

### Changed

- **Set the hotkey by pressing it.** Click the field and press the combination
  instead of typing `ctrl+shift+f9` and hoping the spelling matches.
- **League is a dropdown**, listing the real leagues with the current one named, rather
  than a text box where a typo silently priced everything against another economy.
- **Quick Lookup asks one question.** It used to convert any item into any other, which
  implied those two things trade against each other — almost none of them do. Now it
  shows what one item is worth in a currency you pick: exalted, divine, chaos or annul.
  The sentence restating the number is gone, and the panel takes about a quarter of the
  tab instead of half, so the trade queues are bigger.
- **The Trades tab can show what you did**, not just what was found: filter to the ones
  you messaged or the ones you bought. It was hard to go back afterwards and see what a
  trade you actually made had been valued at.
- **Trades shows which currency you pay in and which you'd settle in**, per row.
- **The Odds symbols have a key**, on both Trades and Results, and both tabs use the
  same symbols — Results used to spell the rating out in different words.
- **Plainer wording throughout Settings.** The tooltips explained the measurements
  behind each setting rather than what it does, and quoted figures that have since
  changed.
- Settling in exalted is no longer recommended without comment: it saves rounding and
  costs far more gold, which can leave you unable to trade at all.

### Fixed (display)

- "No limit" is no longer cut off in the bankroll boxes, and the two boxes now say
  which currency they are when both read no limit.
- The long-shots percentage is no longer clipped by the slider on a narrow window.
- The Excluded tick is centred under its heading.
- The Trades search box is wider and says what it searches.

## [0.4.0] — 2026-07-29

0.3.0 established that the triangular loop search was reading the wrong market.
This release removes it. Everything that existed to serve it — the Scan and
Watch buttons, the Book Edges tab, the Trends charts, half the Settings dialog —
is gone, and what's left is the part that actually finds trades.

### Removed

- **Scan now and Watch.** They ran the loop search. It never found a real trade
  in nine versions, because the prices it was reading describe a market nobody
  uses. One toolbar toggle, **Find trades**, replaces both.
- **The Book Edges tab.** A raw dump of the loop search's graph. Quick Lookup
  answers "what is this pair worth" without it.
- **The Trends tab**, replaced by **Results** — see below. It charted the scan
  history, so on a sweep-only workflow it plotted a flat line at zero.
- **Eight settings** that only tuned the loop search: profit threshold, safety
  margin per hop, watch interval, currencies in graph, max loop length,
  liquidity floor, skip currencies worth over, fill depth per edge.
- **The `scan`, `watch` and `rates` CLI commands.** `poe2-arb sweep` remains.

If your config file has any of the removed settings in it, they're ignored with
a note in the log — the app will not refuse to start over them.

### Added

- **Find trades is a toggle, not a button.** Switch it on and it sweeps, waits,
  and sweeps again until you switch it off. Listings go stale in minutes, so
  "keep looking" is the useful mode; the gap between sweeps is settable.
- **A Results tab**, over the log of every whisper you've copied. Fill rates and
  divines earned, broken down by discount size, listing age and whether the
  seller was AFK — the three things that might predict whether a whisper gets
  answered. **It refuses to quote a rate from fewer than 10 attempts**, because
  a fill rate from three whispers is noise with a percent sign on it. Once
  there's enough, it names the discount range earning you the most per whisper.
- **Your request budget, bottom right.** GGG reports how much of the rate limit
  your IP has spent on every reply — including requests from other trade tools
  you're running. It goes amber near the limit and red during a lockout.
- **Market tabs wrap onto a second row** instead of hiding the last few behind
  scroll arrows, and the group filter takes more than one selection at a time.
- **Prices now come from the in-game Currency Exchange** wherever it trades the
  item — 226 of the 637 in the catalogue — with poe.ninja's consensus as the
  fallback for the rest. The Currency Exchange is the venue you'd actually sell
  into, and the only source that's been checked against the game itself. The
  Market tab's status line says how many came from each; Quick Lookup names its
  source per pair. (Where both have a price they agree closely — median 3.3%,
  and under 1% on the busiest items — so expect small changes, not upheaval.)

### Changed

- **Bankroll is split into divines and exalted**, and lives on the Opportunities
  tab next to the trades it constrains. One pooled divine figure was wrong: a
  seller wanting exalted can only be paid in exalted, and converting on the
  Currency Exchange costs the spread — so a single number promised quantities
  you couldn't actually buy.
- **A Long shots slider**, also on Opportunities. Left ranks by what has actually
  been seen to fill and buries the huge discounts; right ranks on profit alone
  and puts them first. Nothing is ever hidden — only the order changes.
- **Settlement currency moved out of Settings** onto the Opportunities tab. It
  changes every Profit figure by a large factor, which is not something to bury
  in a dialog.
- Sweep progress **names the item being fetched** rather than counting to 69.
- The Trades tab's first column is now labelled **Odds**, and its tooltip says
  what ●, ○ and × mean.
- Market drops the "In graph" column, and centres everything but the item name.

### Fixed

- **The app would not start a second time once the hotkey was enabled.** The
  hotkey setup logs a line, and it ran before the Log tab existed. First launch
  was fine because the hotkey is off by default — so the crash only appeared
  after you turned it on, and then on every launch after that. There are now
  tests that build the whole window; previously nothing did, which is how this
  shipped.

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
