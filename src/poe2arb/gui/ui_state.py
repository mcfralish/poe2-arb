"""Window geometry and layout, remembered between runs.

Kept in the cache directory as plain JSON rather than in the TOML config or in
QSettings. The config file is meant to be readable and hand-editable, and a
base64 geometry blob in it is neither; QSettings would put this in the Windows
registry, which contradicts the install prompt's promise that removing the
install folder removes the app.

Everything here is best-effort. A missing, corrupt or stale state file costs a
default-sized window, never a failed launch.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

UI_STATE_NAME = "ui-state.json"


def ui_state_path(cache_dir: Path) -> Path:
    return Path(cache_dir) / UI_STATE_NAME


def load_ui_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_ui_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    except OSError:
        log.debug("could not save UI state to %s", path, exc_info=True)


def encode_geometry(data) -> str:
    """Qt's saveGeometry() blob as text, so it can live in JSON."""
    return base64.b64encode(bytes(data)).decode("ascii")


def decode_geometry(text: object) -> bytes | None:
    if not isinstance(text, str):
        return None
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError):
        return None
