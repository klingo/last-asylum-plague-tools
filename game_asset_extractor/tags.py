"""Tags: what you call a picture, kept in `tags.json` (next to `mapping.json`, committed).

    "pictures/Zombie_ItemIcon144/icon_gold": ["gold", "resource"]

Keyed by the picture's id (`out/index.json`; it stays the same across extracts). Only you give them, in the gallery (it edits
`tags.json` through its local server, `apply`); nothing is tagged automatically. A picture without an entry has none.
"""

from __future__ import annotations

import json
from pathlib import Path

import config as C
import state as S

PATH = C.HERE / "tags.json"


def normalize(tag: str) -> str:
    """A tag as it is stored: lower case, one space between words (empty when there is nothing)."""
    return " ".join(str(tag).lower().split())


def load(path: Path = PATH) -> dict[str, list[str]]:
    """{picture id: [tags]}; {} when there is no file yet. A file that cannot be read as tags (a merge conflict, a half-edited
    file) raises ValueError: it is never taken for an empty one, which the next edit would save over."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        tags = json.loads(text)
    except ValueError as e:
        raise ValueError(f"{path.name} is not valid JSON ({e}): fix it or delete it") from e
    if not isinstance(tags, dict):
        raise ValueError(f"{path.name} is not a tags file: it holds {{picture id: [tags]}}")
    return tags


def save(tags: dict[str, list[str]], path: Path = PATH) -> None:
    """Sorted, and without the pictures that have nothing left."""
    S.write_json(path, {pid: sorted(set(found)) for pid, found in sorted(tags.items()) if found})


def apply(ids: list[str], add: list[str], remove: list[str], known: set[str], path: Path = PATH) -> dict[str, list[str]]:
    """Take `remove` off and put `add` on every picture of `ids`, save, and return {id: its tags now}. A picture that is not
    in `known` (the ids of the index) raises ValueError, and nothing is saved."""
    for pid in ids:
        if pid not in known:
            raise ValueError(f"unknown picture: {pid}")
    add, remove = [t for t in map(normalize, add) if t], [t for t in map(normalize, remove) if t]
    tags = load(path)
    for pid in ids:
        tags[pid] = sorted((set(tags.get(pid, [])) - set(remove)) | set(add))
    save(tags, path)
    saved = load(path)
    return {pid: saved.get(pid, []) for pid in ids}
