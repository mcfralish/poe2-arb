"""Write each in-game tab's live structure out as an OrgTrees text file.

The OrgTrees files are the hand-edited source of truth for how the app *should*
group things. This dumps how it groups them *now* — straight from
`Universe.by_tab` / `groups_in_tab`, the same calls the Market tab is built
from — so editing starts from what the app actually does rather than a blank
page.

One file per in-game Currency Exchange tab, named after it: Atziri's Temple
becomes AtzirisTemple.txt. Files for tabs that no longer exist are removed.

Run it from the repo root:  python tools/dump_org_trees.py [--only Runes]

Not part of the app. It talks to poe.ninja and writes into the source tree, so
it stays a developer tool rather than something the packaged exe can reach.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from poe2arb.client import NinjaClient
from poe2arb.config import Config
from poe2arb.market import INGAME_TABS

TREES_DIR = Path(__file__).resolve().parent.parent / "src" / "poe2arb" / "gui" / "OrgTrees"


def file_stem(tab: str) -> str:
    """'Atziri\'s Temple' -> 'AtzirisTemple'. Tab names have spaces and quotes."""
    return "".join(part.capitalize() for part in tab.replace("'", "").split())


def render(tab: str, groups: dict[str, list]) -> str:
    """One tab as a box-drawing tree, in the format already in use."""
    lines = [tab, "│"]

    # A single group means the menu skips the group level entirely and lists
    # items straight under the category — so the file should too.
    if len(groups) == 1:
        items = next(iter(groups.values()))
        for i, item in enumerate(items):
            lines.append(f"{'└─' if i == len(items) - 1 else '├─'} {item.name}")
        return "\n".join(lines) + "\n"

    names = list(groups)
    for g, group in enumerate(names):
        last_group = g == len(names) - 1
        lines.append(f"{'└─' if last_group else '├─'} {group}")
        indent = "  " if last_group else "│ "
        items = groups[group]
        for i, item in enumerate(items):
            branch = "└─" if i == len(items) - 1 else "├─"
            lines.append(f"{indent}{branch} {item.name}")
        if not last_group:
            lines.append("│")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", help="tab to dump (repeatable)")
    parser.add_argument("--league", help="default: current temp league")
    args = parser.parse_args(argv)

    cfg = Config()
    client = NinjaClient(cfg)
    try:
        league = args.league or cfg.league or client.current_league()
        universe = client.universe(league)
    finally:
        client.close()

    present = universe.by_tab()
    wanted = args.only or [t for t in INGAME_TABS if t in present]
    TREES_DIR.mkdir(parents=True, exist_ok=True)

    written = set()
    for tab in wanted:
        groups = universe.groups_in_tab(tab)
        if not groups:
            print(f"  {tab}: nothing priced in {league}, skipped")
            continue
        path = TREES_DIR / f"{file_stem(tab)}.txt"
        path.write_text(render(tab, groups), encoding="utf-8")
        written.add(path.name)
        count = sum(len(items) for items in groups.values())
        print(f"  {tab}: {len(groups)} group(s), {count} items -> {path.name}")

    if not args.only:
        # Tabs come and go as the game reorganises; a file for a tab that no
        # longer exists is worse than no file, because it looks authoritative.
        for stale in sorted(TREES_DIR.glob("*.txt")):
            if stale.name not in written:
                stale.unlink()
                print(f"  removed {stale.name} (no longer a tab)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
