# <img src="docs/icon.png" alt="" width="32" height="32" valign="middle"> poe2-arb

Finds Path of Exile 2 trade listings priced below what the in-game Currency Exchange
pays for the same item, so you can buy one and resell the other side. Desktop app + CLI.

**Analysis only.** It reads public market data and puts a whisper on your clipboard.
It never types into the game, sends anything for you, or automates any in-game action.

## Download (Windows)

Grab `poe2-arb.exe` from the [latest release](https://github.com/mcfralish/poe2-arb/releases/latest) — no install, just run it.

On first launch it offers to install itself to `%LOCALAPPDATA%\Programs\poe2-arb\` and add
a Start Menu shortcut, so it doesn't have to live in Downloads. Say no and it keeps running
where it is; tick "Don't ask again" and it won't raise the subject twice. This is a
**per-user install**: no administrator prompt, nothing outside your own profile is touched,
and uninstalling means deleting that folder. Program Files is deliberately avoided — writing
there needs elevation, and an unsigned app that elevates to copy itself into a system
directory looks exactly like malware to antivirus heuristics.

- Windows SmartScreen will warn because the exe is unsigned: click **More info → Run anyway**.
- The app checks GitHub for new versions on startup and shows a download banner when one exists.
- **Find trades** is a toggle: switch it on and the app checks listings, waits, and checks
  again until you switch it off. When it finds something worth acting on, it pops a toast
  (with sound) and offers you the trade. Closing the window while it's running sends it to
  the system tray; right-click the tray icon to quit.

### If antivirus flags it

Windows Defender may report `Trojan:Win32/Wacatac.C!ml` or similar and quarantine the exe,
sometimes killing it mid-run. This is a **false positive**, and a well-known one: the `!ml`
suffix marks a machine-learning guess, and unsigned PyInstaller apps that unpack themselves
at startup and then make network requests match the shape of a dropper. Detection is
inconsistent — the same build may be flagged on one machine and not another, or flagged one
day and not the next, as Defender's models update.

Nothing here justifies the verdict: this app only makes HTTPS requests to `poe.ninja`,
`poe2scout.com` and `pathofexile.com`. The source is public, and each release exe is built from a tagged commit
by GitHub Actions — the build log is linked on every release, so the binary's provenance is
checkable rather than a matter of trust.

If it happens to you:

1. Put the exe in its own folder — `C:\Program Files\poe2-arb\` is a good choice, because
   only administrators can write there, so excluding it doesn't create a hole that ordinary
   programs can drop files into.
2. Windows Security → **Virus & threat protection** → **Manage settings** → **Exclusions** →
   **Add an exclusion** → **Folder** → pick that folder.
3. Re-download the exe into it (a quarantined copy is easier to replace than restore).

Prefer a narrow, admin-only folder over excluding `Downloads` or your user profile — those
are exactly where genuinely hostile files land.

> **Analysis only.** This tool fetches public market data, analyzes it, and prints
> signals. It never automates any in-game action, trade execution, whisper, or input —
> automating gameplay/trading violates GGG's Terms of Service. What you do with the
> printed signals, you do by hand, in game, at your own judgment.

## How it works

### The two markets

Path of Exile 2 has two of them, and the difference is the whole point of this app.

The **Currency Exchange** is the in-game vendor: pooled orders, matched automatically,
works while you're offline. Essentially all trading happens there, and its spreads are
about 1% — far too tight to arbitrage against itself.

The **Bulk Item Exchange** is the older whisper-and-party system, and it's what GGG's
official trade API serves. Hardly anyone uses it any more. Listings sit there for days at
prices the live market moved away from months ago.

So there is no profitable loop to find *inside* either market. The opportunity is the gap
*between* them: buy an underpriced listing on the abandoned venue by whispering the seller,
then sell the item into the Currency Exchange at the real price.

(Versions up to 0.3.0 searched for arbitrage cycles within a single market. That search was
reading Bulk Item Exchange prices and treating them as the live market. It never found a
real trade, and it was removed in 0.4.0.)

### Data

- **poe2scout** (`api.poe2scout.com`) provides **Currency Exchange** prices — the live
  market, and the number you'd actually resell at. Spot-checked against five items in
  game: it ran 0.4%–4.7% low. That error is why a discount under ~5% is reported as
  uncertain rather than as profit.
- **poe.ninja** provides the item universe: names, categories, daily traded volume, and
  a consensus value per item. It powers the Market tab and Quick Lookup.
- **GGG's official trade2 API** provides the live **listings** — who is selling what, for
  how much, in which currency, and whether they're online.

### Pricing a trade

1. Pick the items worth checking: most-traded on the Currency Exchange first, skipping
   anything too cheap or too illiquid to resell.
2. Fetch live listings for each, online sellers only, best price first.
3. Cost each listing **in the currency the seller is asking for**. Sellers quote in divines
   or in exalted, and you can only pay in what you hold.
4. Work out how many you can buy, capped by their stock and by your bankroll in that
   currency.
5. Work out what the Currency Exchange would pay, **rounded down to a whole unit of the
   settlement currency**. This matters more than it sounds: exalted is about 432× finer
   than divine, and on the first trade that actually filled, settling in exalted was the
   difference between 1.00 and 1.79 divines of profit.

### Which discounts are worth a message

A listing far below market looks like the best row in the table and is the one that never
fills — it's a mistake, an abandoned listing, or already sold. So each candidate is banded:

| | | |
|---|---|---|
| ● | plausible | A real seller under market. These are the ones that fill. |
| ○ | thin | The discount is inside the price reference's own margin of error. |
| × | ghost | Far below market. Measured fill rate: zero across ~10 whispers. |

Ghosts are **ranked last, never hidden** — hiding them would make the ranking
unfalsifiable. The **Long shots** slider on the Opportunities tab decides how hard the
band suppresses profit when ranking: left ranks by what actually fills, right ranks on
profit alone and puts the big discounts first.

These bands come from a few dozen real whispers, which is not many. Every whisper you copy
is logged with its discount, the listing's age and whether the seller was AFK, and the
**Results** tab reports fill rates against all three — refusing to quote a rate from fewer
than 10 attempts. The intent is to replace the guessed bands with fitted ones.

## Install from source

Python 3.11+.

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev,gui]"
poe2-arb-gui   # desktop app
```

## Usage

The desktop app is the primary surface. The CLI runs one sweep and prints it:

```sh
poe2-arb sweep                        # check listings, print ranked candidates
poe2-arb sweep --items 30 --limit 10  # fewer items, shorter table
poe2-arb --league "Standard" sweep
```

A sweep is minutes of deliberately paced requests — see rate limits below.

## Configuration

Optional `poe2arb.toml` in the working directory (or `--config path`). All keys with
their defaults are in [poe2arb.example.toml](poe2arb.example.toml). CLI flags override
the file. The league is auto-detected from poe.ninja's league list each run unless
pinned in config — league names rotate every few months, never hardcode one.

The desktop app keeps its own settings file instead, written by the Settings dialog:
`%APPDATA%\poe2-arb\poe2arb.toml` on Windows, `~/.config/poe2-arb/poe2arb.toml` elsewhere.

**Excluding items.** Tick the **Excluded** column on the Market tab. Excluded items stay
visible there — you judge an item while looking at its price — and the tick is how you add
and remove them. Config files use short ids (`mirror`). Nothing is excluded by default.

**Showing prices in another currency.** The **Show prices in** selector at the top right
of the window (`base_currency` in config) switches every price in the app between Divine,
Exalted, Chaos and Annulment — the Market column, the picker menus and the lookup. Internal
maths always works in divines; this only changes what you read. The choice is saved.

**Menu ordering.** Categories and item names sort alphabetically, but **tiers sort by
strength, not by name** — alphabetically "Greater" precedes "Lesser" while outranking it.
The ranking was checked against live median prices rather than assumed: Essences run
Lesser 0.0030 < Greater 0.0034 < Perfect 0.0122 divines, and Delirium runs
Diluted < base < Concentrated < Potent. "Ancient" variants consistently price *below*
their plain counterparts, so they sort low. Anything level-graded (Uncut Gems) sorts
numerically, because "Level 11" must not come before "Level 6".

## Politeness / API citizenship

- Every remote response is cached to disk; nothing is re-fetched within
  `refresh_minutes` (default 10 — poe.ninja PoE2 data only changes hourly anyway).
- `Retry-After` on 429 is honored, 5xx retries use exponential backoff, and a
  descriptive User-Agent is sent.
- A default sweep makes one request per item — 69 of them, about 15 minutes at the
  default spacing. `sweep_items` is the main request-budget knob.
- The app shows how much of GGG's rate limit your IP has spent in the bottom-right corner
  of the window, straight from their own headers.

### Rate limits are taken seriously

GGG publishes three per-IP windows on every response — currently `5/15s`, `10/90s`
and `30/300s` — and the widest one carries an **1800-second penalty**. Overshoot it
and the whole IP loses trade API access for 30 minutes, including the trade website
and any other tool you run.

Two independent guards:

**Before the fact**, `request_interval_s` is checked against every window using
worst-case arithmetic. The subtlety is the boundary: requests spaced 10s apart put
*31* of them in a 300s window (t=0, 10, … 300), not 30, so the seemingly-exact 10s
spacing was actually over the limit — that's why the default is now 13s. The
Settings dialog runs this check live and **refuses to save** a value that could get
you banned, warning separately when a setting is legal but leaves no headroom.

**During the fact**, the client reads `X-Rate-Limit-Ip-State` from each response and
slows down when the IP is already loaded. This is the one that matters if you play
with other trade tools open: the configured interval only knows about this app,
whereas the header reflects everything sharing your connection. If a restriction is
already active, the client waits it out rather than hammering a blocked endpoint.

`rate_limit_safety_fraction` (default 0.8) sets how much of each window this app is
willing to occupy, leaving the rest for everything else.

### Where data is stored

| What | Windows | Linux / macOS |
|---|---|---|
| Cache + trade log | `%LOCALAPPDATA%\poe2-arb\` | `$XDG_CACHE_HOME/poe2-arb` or `~/.cache/poe2-arb` |
| Desktop app settings | `%APPDATA%\poe2-arb\poe2arb.toml` | `$XDG_CONFIG_HOME/poe2-arb/poe2arb.toml` or `~/.config/…` |

Nothing is ever written next to the executable, so it can live in a read-only
location like `C:\Program Files\`. Caches from versions up to 0.2.1 (which used
`~/.cache` on every platform, leaving a stray dotfolder in Windows profiles) are
moved automatically on first run.

## The trade log

Every whisper you copy appends a line to `outcomes.jsonl` — the item, the discount, the
listing's age, whether the seller was AFK, and what you expected to make. Every verdict
you give ("traded", "no reply", "already sold") appends another, resolving it. Unanswered
whispers mark themselves as no reply after ten minutes, because silence is the usual
outcome and leaving them pending forever would bias the record toward whatever you
happened to come back and click.

This is the only file worth accumulating: it's the evidence that decides which discounts
are worth messaging about. Kept forever by default. The **Results** tab reads it.

## Failure behavior

- Unknown league → explicit error listing available leagues (poe.ninja returns
  HTTP 200 with empty data for bad leagues; this is detected, not silently reported
  as "nothing found").
- One item failing mid-sweep is logged and skipped, not fatal — losing item 40 of 69 is
  no reason to discard the 39 already priced.
- Schema drift on either API → loud failure, raw response saved to the cache dir as
  `bad_response_*.json` for inspection.

## Development

```sh
python -m pytest
```

GUI tests need `QT_QPA_PLATFORM=offscreen`. Tests cover the profit maths (lot sizing and
the settlement rounding that's worth ~44% of a real trade), the queue state machine, the
parsers against saved real API responses in `tests/fixtures/`, and window construction —
that last one exists because a startup crash once shipped with every panel individually
tested and nothing assembling them.

## Legal

This product isn't affiliated with or endorsed by Grinding Gear Games in any way.

Path of Exile 2 and all associated names, images and data are the property of Grinding
Gear Games. poe2-arb reads publicly available market data and analyses it; it never
automates any in-game action.
