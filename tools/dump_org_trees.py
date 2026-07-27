"""Write each category's live menu structure out as an OrgTrees text file.

The OrgTrees files are the hand-edited source of truth for how the pickers
*should* group things. This dumps how they're grouped *now* — straight from
`Universe.by_category_and_tier`, the same call the menus are built from — so
editing starts from what the app actually does rather than from a blank page.

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
from poe2arb.market import CATEGORIES, category_label

TREES_DIR = Path(__file__).resolve().parent.parent / "src" / "poe2arb" / "gui" / "OrgTrees"

# Files whose contents are hand-written and must not be clobbered.
PROTECTED = {"Currency.txt"}


def render(category: str, groups: dict[str, list]) -> str:
    """One category as a box-drawing tree, in the format already in use."""
    lines = [category_label(category), "│"]

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
    parser.add_argument("--only", action="append", help="category to dump (repeatable)")
    parser.add_argument("--league", help="default: current temp league")
    parser.add_argument(
        "--force", action="store_true", help="overwrite hand-written files too"
    )
    args = parser.parse_args(argv)

    cfg = Config()
    client = NinjaClient(cfg)
    try:
        league = args.league or cfg.league or client.current_league()
        universe = client.universe(league)
    finally:
        client.close()

    grouped = universe.by_category_and_tier()
    wanted = args.only or list(CATEGORIES)
    TREES_DIR.mkdir(parents=True, exist_ok=True)

    for category in wanted:
        groups = grouped.get(category)
        if not groups:
            print(f"  {category}: nothing priced in {league}, skipped")
            continue
        path = TREES_DIR / f"{category}.txt"
        if path.name in PROTECTED and not args.force:
            print(f"  {category}: hand-written, left alone (--force to overwrite)")
            continue
        path.write_text(render(category, groups), encoding="utf-8")
        count = sum(len(items) for items in groups.values())
        print(f"  {category}: {len(groups)} group(s), {count} items -> {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
