"""What the tool remembers between runs (state/*.json), as small JSON files written in one go.

    pulled.json     {file name: {md5, path}}  bundles downloaded into cache/ (the scan compares the manifest with this)
    extracted.json  {file name: md5}  bundles whose sprites are in out/
    scan.json       the last scan (what is new / changed / removed), for the window
    version.txt     the game's resource version at the last pull
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import config as C


def load(name: str, default=None):
    path = C.STATE / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default


def save(name: str, data) -> None:
    write_json(C.STATE / name, data)


def load_index() -> dict:
    """out/index.json: {"meta": {"run", "baseline", "runs": {run: {version, time}}}, "sprites": {id: entry}} (see extract.py)."""
    try:
        return json.loads((C.OUT / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"meta": {"run": 0, "baseline": 0, "runs": {}}, "sprites": {}}


def save_index(index: dict) -> None:
    write_json(C.OUT / "index.json", index, indent=None)


def write_json(path: Path, data, indent: int | None = 1) -> None:
    """Write through a temp file, so a stopped run never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8")
    os.replace(tmp, path)
