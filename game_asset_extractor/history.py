"""History: which game version added or changed each picture and text, kept outside the cache.

`out/index.json` and `out/texts.json` (the cache, git-ignored, rebuilt by Download & extract) say per picture and text in which
extract run it appeared (`added`) and last changed (`changed`); `meta.runs` says which resource version a run was. That is
the one thing the game cannot tell later, so it is also kept in `history.json` (next to this file, committed), written at
the end of every extract run (and by `main.py history`):

    "runs": {"1": {"version": "1.0.805", "time": "..."}, ...}
    "pictures": {"first": 1, "changes": {"pictures/Grp/gold": [3, 0], ...}}     [added, changed] (0 = never)
    "texts": {"first": 8, "changes": {"tables/Item:gold.name": {"de": [9, 0]}, ...}}

Runs of one resource version are merged into the first of them (extracting again, or more kinds, within a version only says when
you looked). `first` is the run that held everything there was from the start (its version means "this or earlier"); only the
pictures and texts that differ from "added in the first run, never changed" are listed, so the file stays small and a game
update adds a few lines; a change in the version that added a picture is no change. The "seen" pointer (`meta.baseline`) is not kept: it only says what you looked at.

After the cache is deleted, the next Download & extract starts from this file: it continues the run numbers, gives every
picture and text its recorded run, and counts what the history does not list as from the first run. So rebuild with a
complete Download & extract (every bundle); what the game added since the last record shows as "or earlier".
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import config as C

PATH = C.HERE / "history.json"


def empty() -> dict:
    return {"runs": {}, "pictures": {"first": None, "changes": {}}, "texts": {"first": None, "changes": {}}}


def load(path: Path | None = None) -> dict:
    """The saved history (the empty one without a file)."""
    history = empty()
    try:
        data = json.loads((path or PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return history
    if isinstance(data, dict):
        for key, value in history.items():
            if isinstance(data.get(key), dict):
                value.update(data[key])
    return history


def dumps(history: dict) -> str:
    """The file's text: one line per run, picture and text, so a git diff shows what a game update added."""
    def entries(mapping: dict, depth: int) -> str:
        pad = " " * depth
        body = ",\n".join(f"{pad}{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}" for key, value in mapping.items())
        return "{\n" + body + "\n" + " " * (depth - 1) + "}" if mapping else "{}"

    def section(name: str) -> str:
        part = history[name]
        return f'{{\n  "first": {json.dumps(part["first"])},\n  "changes": {entries(dict(sorted(part["changes"].items())), 3)}\n }}'

    runs = dict(sorted(history["runs"].items(), key=lambda item: int(item[0])))
    return f'{{\n "runs": {entries(runs, 2)},\n "pictures": {section("pictures")},\n "texts": {section("texts")}\n}}\n'


def save(history: dict, path: Path | None = None) -> None:
    """Write through a temp file, so a stopped run never leaves half a file."""
    path = path or PATH
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(dumps(history), encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def versions(runs: dict) -> dict[str, int]:
    """{run: the first run of the same resource version}: the history keeps one run per version (several extracts of one version
    only say when you looked, not what the game changed). A run of unknown version (`?`) stays its own."""
    first: dict[str, int] = {}
    return {run: first.setdefault(runs[run]["version"] if runs[run]["version"] != "?" else run, int(run)) for run in sorted(runs, key=int)}


def picture_changes(sprites: dict, merge: dict[str, int]) -> dict[str, list[int]]:
    """{id: [added, changed]} (runs merged per version) of the pictures that were not simply there from the first run. A
    change in the version that added the picture is no change."""
    first = min(merge.values())
    found = {}
    for s in sprites.values():
        added = merge.get(str(s["added"]), s["added"])
        changed = merge.get(str(s["changed"]), s["changed"]) if s["changed"] else 0
        if added > first or changed > added:
            found[s["id"]] = [added, changed if changed > added else 0]
    return found


def text_changes(texts: dict, merge: dict[str, int], first: int) -> dict[str, dict[str, list[int]]]:
    """{text id: {language: [added, changed]}} (runs merged per version) of the texts that were not simply there from the first run."""
    found = {}
    for text_id, languages in texts.items():
        odd = {}
        for lang, mark in languages.items():
            added, changed = merge.get(str(mark[1]), mark[1]), merge.get(str(mark[2]), mark[2]) if mark[2] else 0
            if added > first or changed > added:
                odd[lang] = [added, changed if changed > added else 0]
        if odd:
            found[text_id] = odd
    return found


def record(index: dict, text_index: dict | None = None, path: Path | None = None) -> dict | None:
    """Write history.json from the cache: `index` is out/index.json, `text_index` out/texts.json. Runs of one resource version are
    merged into the first of them. Nothing is written before the first extract run, and the texts are kept as they were when
    there is no text index. While a rebuilt cache is not complete (`meta.restoring`) what the history already knew about
    pictures not extracted yet stays."""
    meta = index["meta"]
    if not meta["runs"]:
        return None
    history = load(path)
    merge = versions(meta["runs"])
    history["runs"] = {run: dict(info) for run, info in meta["runs"].items() if merge[run] == int(run)}
    kept = history["pictures"]["changes"] if meta.get("restoring") else {}
    history["pictures"] = {"first": min(merge.values()), "changes": {**kept, **picture_changes(index["sprites"], merge)}}
    if text_index and text_index["texts"]:
        first = merge.get(str(text_index["first"]), text_index["first"])
        history["texts"] = {"first": first, "changes": text_changes(text_index["texts"], merge, first)}
    save(history, path)
    return history


def restore_run(index: dict, history: dict) -> bool:
    """A cache with no extract run yet and a history: continue the history's run numbers (no new run: this one rebuilds the
    old ones) and count everything as seen. `meta.restoring` stays until `apply_pictures` has seen every bundle. True when it
    restored."""
    meta = index["meta"]
    if meta["run"] or not history["runs"]:
        return False
    meta["runs"] = {run: dict(info) for run, info in history["runs"].items()}
    meta["run"] = meta["baseline"] = max(int(run) for run in history["runs"])
    meta["restoring"] = True
    return True


def apply_pictures(index: dict, history: dict) -> None:
    """Give the extracted pictures the run the history recorded for them, else the first run."""
    first, changes = history["pictures"]["first"], history["pictures"]["changes"]
    if first is None:
        return
    for sprite in index["sprites"].values():
        added, changed = changes.get(sprite["id"], [first, 0])
        sprite["added"], sprite["changed"] = added, changed or None
