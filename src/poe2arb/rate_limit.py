"""Request-budget math against GGG's published trade API rate limits.

Getting this wrong is expensive: the widest window carries a 1800-second
penalty, so a single overshoot locks the whole IP out for 30 minutes — and
the IP is shared with anything else the player runs (other trade tools, the
website itself, a second copy of this app).

Pure functions only, so the settings dialog, the CLI and the tests can all
agree on the same numbers without a Qt or network dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class Window:
    """One rate-limit rule: `max_hits` requests per `period_s`, else banned."""

    max_hits: int
    period_s: int
    penalty_s: int

    @property
    def label(self) -> str:
        return f"{self.max_hits} per {self.period_s}s"


# Observed live on the X-Rate-Limit-Ip header: "5:15:60,10:90:300,30:300:1800".
# Treated as a fallback default — the client overrides these from the live
# headers, since GGG can change them without notice.
DEFAULT_WINDOWS = (
    Window(5, 15, 60),
    Window(10, 90, 300),
    Window(30, 300, 1800),
)

# Fraction of each window this app will use before complaining. The remainder
# is deliberate headroom for everything else sharing the player's IP.
DEFAULT_SAFETY_FRACTION = 0.8


class Severity(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class BudgetIssue:
    severity: Severity
    window: Window
    projected_hits: int
    message: str


def format_penalty(seconds: int) -> str:
    """'90 seconds' / '1 minute' / '30 minutes' — for user-facing warnings."""
    if seconds < 60:
        return f"{seconds} second{'' if seconds == 1 else 's'}"
    minutes = seconds // 60
    return f"{minutes} minute{'' if minutes == 1 else 's'}"


def parse_windows(header: str) -> tuple[Window, ...]:
    """Parse an X-Rate-Limit-Ip header: 'hits:period:penalty,...'."""
    windows: list[Window] = []
    for part in header.split(","):
        bits = part.strip().split(":")
        if len(bits) != 3:
            continue
        try:
            windows.append(Window(int(bits[0]), int(bits[1]), int(bits[2])))
        except ValueError:
            continue
    return tuple(windows)


def parse_state(header: str) -> dict[int, tuple[int, int]]:
    """Parse X-Rate-Limit-Ip-State into {period_s: (hits_used, restricted_for_s)}."""
    state: dict[int, tuple[int, int]] = {}
    for part in header.split(","):
        bits = part.strip().split(":")
        if len(bits) != 3:
            continue
        try:
            hits, period, restricted = (int(b) for b in bits)
        except ValueError:
            continue
        state[period] = (hits, restricted)
    return state


@dataclass(frozen=True)
class BudgetState:
    """How much of a rate-limit window the IP has spent, per the last response.

    GGG reports usage on every reply, so this is measured rather than
    predicted — it also counts requests made by anything else on the same IP.
    """

    used: int
    limit: int
    period_s: int
    restricted_for_s: int = 0

    @property
    def fraction(self) -> float:
        return self.used / self.limit if self.limit else 0.0

    @property
    def label(self) -> str:
        if self.restricted_for_s > 0:
            return f"Rate limited — {format_penalty(self.restricted_for_s)} left"
        return f"{self.used}/{self.limit} requests per {self.period_s}s"


def tightest_window(
    windows: tuple[Window, ...], state: dict[int, tuple[int, int]]
) -> BudgetState | None:
    """The window closest to its limit — the one that will bite first.

    A penalty already in force outranks everything, since that is no longer a
    forecast. Otherwise it's whichever window has the largest fraction spent.
    """
    best: BudgetState | None = None
    for w in windows:
        used, restricted = state.get(w.period_s, (0, 0))
        current = BudgetState(used, w.max_hits, w.period_s, restricted)
        if best is None:
            best = current
        elif (current.restricted_for_s, current.fraction) > (
            best.restricted_for_s, best.fraction
        ):
            best = current
    return best


def max_hits_in_window(period_s: int, interval_s: float) -> int:
    """Worst-case requests landing in `period_s` when spaced `interval_s` apart.

    Requests at t = 0, I, 2I ... so a window of length P can contain
    floor(P/I) + 1 of them if it lines up with a request. Counting the
    boundary matters: at 10s spacing that's 31 requests per 300s window,
    which is over the 30-per-300s limit even though 300/10 == 30 suggests
    it just fits.
    """
    if interval_s <= 0:
        return math.inf  # type: ignore[return-value]
    return math.floor(period_s / interval_s) + 1


def min_safe_interval(
    windows: tuple[Window, ...] = DEFAULT_WINDOWS,
    safety_fraction: float = DEFAULT_SAFETY_FRACTION,
) -> float:
    """Smallest spacing that keeps every window inside its safety budget."""
    required = 0.0
    for w in windows:
        budget = max(1, math.floor(w.max_hits * safety_fraction))
        # Need floor(P/I) + 1 <= budget  ->  I > P / budget
        required = max(required, w.period_s / budget)
    # Nudge past the strict inequality so the boundary case is safe.
    return math.ceil((required + 0.05) * 10) / 10


def check_pacing(
    interval_s: float,
    windows: tuple[Window, ...] = DEFAULT_WINDOWS,
    safety_fraction: float = DEFAULT_SAFETY_FRACTION,
) -> list[BudgetIssue]:
    """Assess a request interval against every window.

    ERROR means this pacing can exceed a hard limit and get the IP banned.
    WARNING means it stays legal but leaves little room for other tools
    sharing the connection.
    """
    issues: list[BudgetIssue] = []
    for w in windows:
        projected = max_hits_in_window(w.period_s, interval_s)
        budget = max(1, math.floor(w.max_hits * safety_fraction))
        if projected > w.max_hits:
            issues.append(
                BudgetIssue(
                    Severity.ERROR,
                    w,
                    projected,
                    f"{projected} requests would land in a {w.period_s}s window, "
                    f"over GGG's limit of {w.max_hits}. Exceeding it locks your IP "
                    f"out of the trade API for {format_penalty(w.penalty_s)}.",
                )
            )
        elif projected > budget:
            issues.append(
                BudgetIssue(
                    Severity.WARNING,
                    w,
                    projected,
                    f"{projected} of {w.max_hits} requests per {w.period_s}s — legal, "
                    f"but little headroom if you run other trade tools on the same "
                    f"connection.",
                )
            )
    return issues


def worst_severity(issues: list[BudgetIssue]) -> Severity:
    if any(i.severity is Severity.ERROR for i in issues):
        return Severity.ERROR
    if any(i.severity is Severity.WARNING for i in issues):
        return Severity.WARNING
    return Severity.OK
