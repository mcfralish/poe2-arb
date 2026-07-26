# poe2-arb

Detects profitable currency arbitrage cycles in the Path of Exile 2 player economy.
Desktop app + CLI.

## Download (Windows)

Grab `poe2-arb.exe` from the [latest release](https://github.com/mcfralish/poe2-arb/releases/latest) — no install, just run it.

- Windows SmartScreen will warn because the exe is unsigned: click **More info → Run anyway**.
- The app checks GitHub for new versions on startup and shows a download banner when one exists.
- **Watch** re-scans every 10 minutes and pops a toast notification (with sound) when an
  arbitrage loop crosses your profit threshold. Closing the window while watching sends it
  to the system tray; right-click the tray icon to quit.

### If antivirus flags it

Windows Defender may report `Trojan:Win32/Wacatac.C!ml` or similar and quarantine the exe,
sometimes killing it mid-run. This is a **false positive**, and a well-known one: the `!ml`
suffix marks a machine-learning guess, and unsigned PyInstaller apps that unpack themselves
at startup and then make network requests match the shape of a dropper. Detection is
inconsistent — the same build may be flagged on one machine and not another, or flagged one
day and not the next, as Defender's models update.

Nothing here justifies the verdict: this app only makes HTTPS requests to `poe.ninja` and
`pathofexile.com`. The source is public, and each release exe is built from a tagged commit
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

**Data (hybrid, two sources):**

- **poe.ninja** (`/poe2/api/economy/...`, documented at poe.ninja/docs/api) provides the
  currency universe, one consensus value per currency (in divines), daily traded volume,
  and the current league list. PoE2 data refreshes hourly. Note: poe.ninja publishes a
  *single consistent price* per currency — no pay/receive spread — so on its own it can
  never show arbitrage (all cross-rates multiply to exactly 1 by construction; verified
  live at ~0.03% median deviation).
- **GGG's official trade2 exchange API** (`pathofexile.com/api/trade2/exchange/{league}`)
  provides the real order book: actual listed offers, both directions per pair, with
  stock. This is where spreads — and arbitrage — actually live.

**Pricing an edge A→B** ("pay 1 A, how many B do I really get?"):

1. Take all book offers selling B for A.
2. Drop bait/scam listings: anything priced implausibly *better* than poe.ninja
   consensus by more than `bait_filter_ratio` (top-of-book is full of 1 exalt ⇄ 1 divine
   traps with stock 2).
3. Walk the book best-rate-first until `depth_divines` worth of stock is accumulated
   **and** the fill spans at least `min_accounts` distinct lister accounts — a single
   account posting a huge fake wall at a too-good rate (price-fixing, endemic on the
   trade site) can't set the rate on its own. The **marginal** (worst included) rate is
   the edge rate — the rate you could actually fill at that size. Books too thin to
   fill the depth are dropped entirely (thin markets produce phantom arbs that never
   fill).
4. Apply a per-hop haircut of `fee_pct` (the in-game Currency Exchange gold fee plus
   fill slippage).

**Finding cycles:** the currencies form a directed graph with those effective rates.
A loop A→B→…→A whose rates multiply to more than 1 is free money (in expectation).
Two independent detectors cross-check each other:

- **Bellman-Ford** on `-log(rate)` weights — a negative-weight cycle is exactly a
  profitable loop (log turns rate products into weight sums; profit > 1 ⇔ sum < 0).
  Detects loops of *any* length; used as the completeness check.
- **Brute force** over all 2-, 3- and 4-cycles (the graph is small, ≤ ~15 nodes) —
  reports exact profit per loop. 2-cycles are included deliberately: a "crossed book"
  on a single pair is the most common real arb. If Bellman-Ford fires and brute force
  found nothing, the tool tells you the profit lives in a longer loop or below your
  threshold.

Surviving loops are filtered by `profit_threshold_pct` (default 3%, clearing fees and
slippage) and ranked. Depth shown per loop is the bottleneck edge — the most value the
loop supports at the quoted rates.

## Install from source

Python 3.11+.

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev,gui]"
poe2-arb-gui   # desktop app
```

## Usage

```sh
poe2-arb scan                    # one-shot: fetch (or use cache), print ranked loops
poe2-arb watch --interval 10m    # re-scan on an interval, print only changes
poe2-arb rates chaos             # pay/receive book rates for one currency
poe2-arb --league "Standard" --threshold 5 scan
```

Currency ids are poe.ninja's (`chaos`, `exalted`, `annul`, …); `poe2-arb rates x`
prints the full known list on a bad id.

## Configuration

Optional `poe2arb.toml` in the working directory (or `--config path`). All keys with
their defaults are in [poe2arb.example.toml](poe2arb.example.toml). CLI flags override
the file. The league is auto-detected from poe.ninja's league list each run unless
pinned in config — league names rotate every few months, never hardcode one.

The desktop app keeps its own settings file instead, written by the Settings dialog:
`%APPDATA%\poe2-arb\poe2arb.toml` on Windows, `~/.config/poe2-arb/poe2arb.toml` elsewhere.

**Excluding currencies.** `exclude_currencies` keeps named currencies out of the search
entirely. Mirrors are excluded by default: one costs thousands of divines, so loops
through them are unreachable for most players and would crowd out tradeable ones.
`max_currency_value_divines` does the same by price rather than by name — anything worth
more than the cap is skipped (`0` disables it). Excluded currencies still appear in the
app's Market tab for reference, just without a tick in the **In graph** column.

## Politeness / API citizenship

- Every remote response is cached to disk; nothing is re-fetched within
  `refresh_minutes` (default 10 — poe.ninja PoE2 data only changes hourly anyway).
- `Retry-After` on 429 is honored, 5xx retries use exponential backoff, and a
  descriptive User-Agent is sent.
- A default scan (10 currencies) makes 20 exchange requests. Keep `max_currencies`
  modest; it's the main request-budget knob.

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
| Cache + scan history | `%LOCALAPPDATA%\poe2-arb\` | `$XDG_CACHE_HOME/poe2-arb` or `~/.cache/poe2-arb` |
| Desktop app settings | `%APPDATA%\poe2-arb\poe2arb.toml` | `$XDG_CONFIG_HOME/poe2-arb/poe2arb.toml` or `~/.config/…` |

Nothing is ever written next to the executable, so it can live in a read-only
location like `C:\Program Files\`. Caches from versions up to 0.2.1 (which used
`~/.cache` on every platform, leaving a stray dotfolder in Windows profiles) are
moved automatically on first run.

## History

Every scan appends one JSONL record to `history.jsonl` (timestamp, full rates snapshot,
book edges, detected opportunities) — raw data deliberately kept for a future
trend-analysis phase.

## Failure behavior

- Unknown league → explicit error listing available leagues (poe.ninja returns
  HTTP 200 with empty data for bad leagues; this is detected, not silently reported
  as "no arbs").
- Schema drift on either API → loud failure, raw response saved to the cache dir as
  `bad_response_*.json` for inspection.

## Development

```sh
python -m pytest
```

Tests cover the cycle math on synthetic graphs with planted cycles (including one whose
gross profit sits just below the fee haircut and must not be reported) and the parsers
against saved real API responses in `tests/fixtures/`.
