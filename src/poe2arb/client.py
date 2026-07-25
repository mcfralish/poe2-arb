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

import httpx

from .config import Config

log = logging.getLogger(__name__)

NINJA_BASE = "https://poe.ninja/poe2/api/economy"
GGG_EXCHANGE_URL = "https://www.pathofexile.com/api/trade2/exchange/{league}"

# The wealth unit poe.ninja prices everything in (verified live: core.primary).
PRIMARY = "divine"


class ClientError(RuntimeError):
    pass


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

def _request_with_backoff(
    client: httpx.Client, method: str, url: str, *, max_tries: int = 4, **kwargs
) -> httpx.Response:
    delay = 2.0
    for attempt in range(1, max_tries + 1):
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
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                if attempt == max_tries:
                    raise ClientError(f"{url} failed with HTTP {resp.status_code}")
                log.warning("HTTP %d from %s, retrying in %.0fs", resp.status_code, url, delay)
            else:
                return resp
        time.sleep(delay)
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

    def close(self) -> None:
        self._http.close()


class GggExchangeClient:
    """Client for the official trade2 currency-exchange order book.

    Read-only, decision support only. Paces requests to stay inside the
    published limits (5/15s, 10/90s, 30/300s per IP at time of writing) and
    honors rate-limit headers.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.cache = DiskCache(cfg.cache_dir)
        self._http = httpx.Client(
            headers={"User-Agent": cfg.user_agent, "Content-Type": "application/json"},
            timeout=30,
        )
        self._last_request_t = 0.0

    def _pace(self) -> None:
        wait = self.cfg.request_interval_s - (time.monotonic() - self._last_request_t)
        if wait > 0:
            time.sleep(wait)

    def fetch_offers(self, league: str, want: str, have: list[str]) -> list[Offer]:
        """All order-book offers selling `want` for any currency in `have`."""
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
            )
            self._last_request_t = time.monotonic()
            self._log_rate_state(resp)
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
