"""Generate the Windows version resource embedded in the exe.

Without this, Windows has no metadata for the binary and falls back to the
raw filename — so Task Manager, shortcut names and the Start Menu all show
"poe2-arb.exe" instead of a proper product name. Generated from
poe2arb.__version__ at build time so it can't drift from the release tag.

Usage: python packaging/make_version_file.py <output-path>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from poe2arb import __version__  # noqa: E402

APP_NAME = "poe2-arb"
DESCRIPTION = "PoE2 currency arbitrage watch (analysis only)"
COMPANY = "mcfralish"
COPYRIGHT = "Open source — github.com/mcfralish/poe2-arb"

TEMPLATE = """\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v0}, {v1}, {v2}, 0),
    prodvers=({v0}, {v1}, {v2}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
         StringStruct('CompanyName', '{company}'),
         StringStruct('FileDescription', '{name}'),
         StringStruct('FileVersion', '{version}'),
         StringStruct('InternalName', '{name}'),
         StringStruct('LegalCopyright', '{copyright}'),
         StringStruct('OriginalFilename', '{name}.exe'),
         StringStruct('ProductName', '{name}'),
         StringStruct('ProductVersion', '{version}'),
         StringStruct('Comments', '{description}'),
        ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def build(version: str = __version__) -> str:
    parts = [int(p) for p in version.split(".")[:3]]
    while len(parts) < 3:
        parts.append(0)
    return TEMPLATE.format(
        v0=parts[0], v1=parts[1], v2=parts[2],
        version=version,
        name=APP_NAME,
        description=DESCRIPTION,
        company=COMPANY,
        copyright=COPYRIGHT,
    )


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "version_info.txt")
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out} for version {__version__}")
