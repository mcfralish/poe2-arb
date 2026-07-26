"""HTTP clients for poe.ninja (values/liquidity) and GGG trade2 exchange (order books).

Both clients cache responses to disk with a timestamp and refuse to re-fetch
before `refresh_minutes` has passed. The GGG client additionally paces requests
and honors the X-Rate-Limit / Retry-After headers.

Parse functions are pure (dict in, dataclasses out) so they can be tested
against saved fixture responses.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from .config import Config
from .market import CATEGORIES, Universe, merge_overviews
from .rate_limit import parse_state, parse_windows

log = logging.getLogger(__name__)

NINJA_BASE = "https://poe.ninja/poe2/api/economy"
GGG_EXCHANGE_URL = "https://www.pathofexile.com/api/trade2/exchange/{league}"

# The wealth unit poe.ninja prices everything in (verified live: core.primary).
PRIMARY = "divine"


class ClientError(RuntimeError):
    pass


class ScanCancelled(Exception):
    """Raised to abort an in-flight scan when the caller asks it to stop.

    Deliberately not a ClientError: cancellation is a normal control-flow
    event (the app is quitting), not a failure to report to the user.
    """


class LeagueNotFoundError(ClientError):
    def __init__(self, league: str, available: list[str]):
        super().__init__(
            f"league {league!r} returned no data; available leagues: {available}"
        )
        self.available = available


class SchemaError(ClientError):
    """The remote response didn't match the expected shape. Raw saved for inspection."""

    def __init__(self, message: str, raw_path: Path | None = None):
        suffix = f" (raw response saved to {raw_path})" if raw_path else ""
        super().__init__(message + suffix)
        self.raw_path = raw_path


@dataclass(frozen=True)
class NinjaOverview:
    """Parsed poe.ninja exchange overview: one consistent value per currency."""

    league: str
    fetched_at: datetime
    values: dict[str, float]   # currency id -> value in divines
    volumes: dict[str, float]  # currency id -> daily traded volume in divines
    names: dict[str, str]      # currency id -> display name


@dataclass(frozen=True)
class Offer:
    """One order-book listing: pay `pay_amount` of pay_currency, receive `get_amount` of get_currency."""

    pay_currency: str
    pay_amount: float
    get_currency: str
    get_amount: float
    stock: float  # available stock, in units of get_currency
    account: str | None = None  # lister account — used to resist single-account fake walls

    @property
    def rate(self) -> float:
        """Units of get_currency received per 1 pay_currency."""
        return self.get_amount / self.pay_amount


# ---------------------------------------------------------------------------
# Pure parsers (fixture-testable)
# ---------------------------------------------------------------------------

def parse_overview(data: dict, league: str, fetched_at: datetime) -> NinjaOverview:
    try:
        core = data["core"]
        lines = data["lines"]
        items = data["items"]
    except (KeyError, TypeError) as e:
        raise SchemaError(f"unexpected poe.ninja response shape: missing {e}") from e
    if core.get("primary") != PRIMARY:
        raise SchemaError(
            f"poe.ninja changed its primary unit: expected {PRIMARY!r}, got {core.get('primary')!r}"
        )
    values: dict[str, float] = {}
    volumes: dict[str, float] = {}
    for line in lines:
        cid = line.get("id")
        value = line.get("primaryValue")
        if not cid or not isinstance(value, (int, float)) or value <= 0:
            continue
        values[cid] = float(value)
        volumes[cid] = float(line.get("volumePrimaryValue") or 0.0)
    names = {it["id"]: it["name"] for it in items if it.get("id") and it.get("name")}
    # The primary unit itself is priced implicitly at 1.0 and has no line entry.
    values.setdefault(PRIMARY, 1.0)
    volumes.setdefault(PRIMARY, float("inf"))
    names.setdefault(PRIMARY, "Divine Orb")
    return NinjaOverview(
        league=league, fetched_at=fetched_at, values=values, volumes=volumes, names=names
    )


def parse_exchange(data: dict) -> list[Offer]:
    try:
        result = data["result"]
    except (KeyError, TypeError) as e:
        raise SchemaError("unexpected GGG exchange response shape: missing 'result'") from e
    # A result set with no matches arrives as an empty *list* (PHP-style empty
    # assoc array), not an empty object. Seen live 2026-07-25.
    entries = result if isinstance(result, list) else result.values()
    offers: list[Offer] = []
    for entry in entries:
        listing = entry.get("listing") or {}
        account = (listing.get("account") or {}).get("name")
        for o in listing.get("offers") or []:
            try:
                exchange, item = o["exchange"], o["item"]
                offer = Offer(
                    pay_currency=exchange["currency"],
                    pay_amount=float(exchange["amount"]),
                    get_currency=item["currency"],
                    get_amount=float(item["amount"]),
                    stock=float(item.get("stock") or 0.0),
                    account=account,
                )
            except (KeyError, TypeError, ValueError):
                continue  # one malformed listing shouldn't kill the scan
            if offer.pay_amount <= 0 or offer.get_amount <= 0:
                continue
            offers.append(offer)
    return offers


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------

class DiskCache:
    def __init__(self, cache_dir: Path):
        self.dir = cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _slug(key: str) -> str:
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in key.lower())

    def load(self, key: str, max_age_s: float) -> tuple[dict, datetime] | None:
        path = self.dir / f"{self._slug(key)}.json"
        if not path.exists():
            return None
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(wrapper["fetched_at"])
        except (json.JSONDecodeError, KeyError, ValueError):
            return None
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age > max_age_s:
            return None
        return wrapper["data"], fetched_at

    def store(self, key: str, data: dict) -> datetime:
        now = datetime.now(timezone.utc)
        path = self.dir / f"{self._slug(key)}.json"
        path.write_text(
            json.dumps({"fetched_at": now.isoformat(), "data": data}), encoding="utf-8"
        )
        return now

    def dump_bad_response(self, key: str, body: str) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.dir / f"bad_response_{self._slug(key)}_{ts}.json"
        path.write_text(body, encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# HTTP with backoff
# ---------------------------------------------------------------------------

def interruptible_sleep(
    seconds: float, should_cancel: Callable[[], bool] | None = None, slice_s: float = 0.25
) -> None:
    """Sleep in slices so cancellation is noticed promptly.

    A rate-limit Retry-After can be several minutes. Sleeping it in one call
    would make the Stop button do nothing until it elapsed — exactly the moment
    a user most wants out.
    """
    if should_cancel is None:
        time.sleep(seconds)
        return
    deadline = time.monotonic() + seconds
    while True:
        if should_cancel():
            raise ScanCancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, slice_s))


def _request_with_backoff(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_tries: int = 4,
    should_cancel: Callable[[], bool] | None = None,
    **kwargs,
) -> httpx.Response:
    delay = 2.0
    for attempt in range(1, max_tries + 1):
        if should_cancel is not None and should_cancel():
            raise ScanCancelled()
        try:
            resp = client.request(method, url, **kwargs)
        except httpx.TransportError as e:
            if attempt == max_tries:
                raise ClientError(f"network error talking to {url}: {e}") from e
            log.warning("network error (%s), retrying in %.0fs", e, delay)
        else:
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", delay))
                log.warning("rate limited (429), sleeping %.0fs", wait)
                interruptible_sleep(wait, should_cancel)
                continue
            if resp.status_code >= 500:
                if attempt == max_tries:
                    raise ClientError(f"{url} failed with HTTP {resp.status_code}")
                log.warning("HTTP %d from %s, retrying in %.0fs", resp.status_code, url, delay)
            else:
                return resp
        interruptible_sleep(delay, should_cancel)
        delay *= 2
    raise ClientError(f"{url}: exhausted retries")


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

class NinjaClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.cache = DiskCache(cfg.cache_dir)
        self._http = httpx.Client(
            headers={"User-Agent": cfg.user_agent}, timeout=30, follow_redirects=True
        )

    def leagues(self) -> list[str]:
        key = "ninja_leagues"
        cached = self.cache.load(key, self.cfg.refresh_minutes * 60)
        if cached:
            data, _ = cached
        else:
            resp = _request_with_backoff(self._http, "GET", f"{NINJA_BASE}/leagues")
            if resp.status_code != 200:
                raise ClientError(f"leagues endpoint returned HTTP {resp.status_code}")
            data = {"leagues": resp.json()}
            self.cache.store(key, data)
        try:
            return [entry["id"] for entry in data["leagues"]]
        except (KeyError, TypeError) as e:
            raw = self.cache.dump_bad_response(key, json.dumps(data))
            raise SchemaError("unexpected leagues response shape", raw) from e

    def current_league(self) -> str:
        leagues = self.leagues()
        if not leagues:
            raise ClientError("poe.ninja returned an empty league list")
        return leagues[0]

    def overview(self, league: str, type_: str = "Currency") -> NinjaOverview:
        key = f"ninja_overview_{league}_{type_}"
        cached = self.cache.load(key, self.cfg.refresh_minutes * 60)
        if cached:
            data, fetched_at = cached
        else:
            resp = _request_with_backoff(
                self._http,
                "GET",
                f"{NINJA_BASE}/exchange/current/overview",
                params={"league": league, "type": type_},
            )
            if resp.status_code != 200:
                raise ClientError(f"overview endpoint returned HTTP {resp.status_code}")
            data = resp.json()
            fetched_at = self.cache.store(key, data)
        if not data.get("lines"):
            # poe.ninja answers HTTP 200 with empty lines for unknown leagues.
            raise LeagueNotFoundError(league, self.leagues())
        try:
            return parse_overview(data, league, fetched_at)
        except SchemaError as e:
            raw = self.cache.dump_bad_response(key, json.dumps(data))
            raise SchemaError(str(e), raw) from e

    def universe(self, league: str, categories: tuple[str, ...] = CATEGORIES) -> Universe:
        """Every priced item across the given categories.

        One request per category, each disk-cached. poe.ninja is not the
        rate-limited API — GGG's exchange endpoint is — so this is cheap
        compared with a scan.
        """
        per_category = {}
        newest = None
        for category in categories:
            try:
                overview = self.overview(league, category)
            except ClientError:
                log.info("category %s unavailable, skipping", category, exc_info=True)
                continue
            per_category[category] = overview
            if newest is None or overview.fetched_at > newest:
                newest = overview.fetched_at
        if not per_category:
            raise ClientError(f"no economy data available for league {league!r}")
        return merge_overviews(league, newest or datetime.now(timezone.utc), per_category)

    def close(self) -> None:
        self._http.close()


class GggExchangeClient:
    """Client for the official trade2 currency-exchange order book.

    Read-only, decision support only. Paces requests to stay inside the
    published limits (5/15s, 10/90s, 30/300s per IP at time of writing) and
    honors rate-limit headers.
    """

    def __init__(self, cfg: Config, should_cancel: Callable[[], bool] | None = None):
        self.cfg = cfg
        self.cache = DiskCache(cfg.cache_dir)
        self._http = httpx.Client(
            headers={"User-Agent": cfg.user_agent, "Content-Type": "application/json"},
            timeout=30,
        )
        self._last_request_t = 0.0
        self._should_cancel = should_cancel
        # Extra spacing demanded by the live rate-limit headers, on top of the
        # configured interval. Zero until the server tells us otherwise.
        self._header_backoff_s = 0.0

    def _check_cancelled(self) -> None:
        if self._should_cancel is not None and self._should_cancel():
            raise ScanCancelled()

    def _apply_rate_limit_headers(self, resp: httpx.Response) -> None:
        """Slow down based on what the server says the IP has already used.

        The configured interval only accounts for this app. The IP is shared
        with anything else the player runs against the trade API, and the
        X-Rate-Limit-Ip-State header reflects that combined usage — so it is
        the only signal that can keep a busy IP out of a ban.
        """
        limit_header = resp.headers.get("X-Rate-Limit-Ip")
        state_header = resp.headers.get("X-Rate-Limit-Ip-State")
        if not limit_header or not state_header:
            return
        windows = parse_windows(limit_header)
        state = parse_state(state_header)
        backoff = 0.0
        for w in windows:
            used, restricted_for = state.get(w.period_s, (0, 0))
            if restricted_for > 0:
                log.warning(
                    "trade API restricted for %ds (%s window) — waiting it out",
                    restricted_for, w.label,
                )
                backoff = max(backoff, float(restricted_for))
                continue
            budget = max(1, int(w.max_hits * self.cfg.rate_limit_safety_fraction))
            if used >= budget:
                # Drop to that window's sustainable rate until it drains.
                pace = w.period_s / max(1, w.max_hits)
                log.info(
                    "rate-limit headroom low (%d/%d in %s) — spacing requests %.1fs",
                    used, w.max_hits, w.label, pace,
                )
                backoff = max(backoff, pace)
        self._header_backoff_s = backoff

    def _pace(self) -> None:
        """Sleep out the request interval, staying responsive to cancellation.

        Sliced rather than one long sleep so quitting the app doesn't have to
        wait out a full pacing interval.
        """
        interval = max(self.cfg.request_interval_s, self._header_backoff_s)
        remaining = (self._last_request_t + interval) - time.monotonic()
        self._check_cancelled()
        if remaining > 0:
            interruptible_sleep(remaining, self._should_cancel)

    def fetch_offers(self, league: str, want: str, have: list[str]) -> list[Offer]:
        """All order-book offers selling `want` for any currency in `have`."""
        self._check_cancelled()
        key = f"ggg_exchange_{league}_{want}_" + "_".join(sorted(have))
        cached = self.cache.load(key, self.cfg.refresh_minutes * 60)
        if cached:
            data, _ = cached
        else:
            self._pace()
            resp = _request_with_backoff(
                self._http,
                "POST",
                GGG_EXCHANGE_URL.format(league=league),
                json={"query": {"want": [want], "have": have}, "engine": "new"},
                should_cancel=self._should_cancel,
            )
            self._last_request_t = time.monotonic()
            self._log_rate_state(resp)
            self._apply_rate_limit_headers(resp)
            if resp.status_code == 404:
                raise LeagueNotFoundError(league, [])
            if resp.status_code != 200:
                raw = self.cache.dump_bad_response(key, resp.text)
                raise ClientError(
                    f"trade2 exchange returned HTTP {resp.status_code} (raw saved to {raw})"
                )
            data = resp.json()
            self.cache.store(key, data)
        try:
            return parse_exchange(data)
        except SchemaError as e:
            raw = self.cache.dump_bad_response(key, json.dumps(data))
            raise SchemaError(str(e), raw) from e

    @staticmethod
    def _log_rate_state(resp: httpx.Response) -> None:
        state = resp.headers.get("X-Rate-Limit-Ip-State")
        limit = resp.headers.get("X-Rate-Limit-Ip")
        if state:
            log.debug("GGG rate limit state %s (limit %s)", state, limit)

    def close(self) -> None:
        self._http.close()
