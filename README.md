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

## Politeness / API citizenship

- Every remote response is cached to disk (`~/.cache/poe2-arb`); nothing is re-fetched
  within `refresh_minutes` (default 10 — poe.ninja PoE2 data only changes hourly anyway).
- GGG requests are paced (`request_interval_s`, default 10s) to sit far inside the
  published `5/15s, 10/90s, 30/300s` per-IP limits; `Retry-After` on 429 is honored,
  5xx retries use exponential backoff, and a descriptive User-Agent is sent.
- A default scan (10 currencies) makes ~20 exchange requests ≈ 3–4 minutes. Keep
  `max_currencies` modest; it's the main request-budget knob.

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
