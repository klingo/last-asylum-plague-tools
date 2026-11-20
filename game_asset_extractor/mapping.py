"""Mapping: which game picture each webapp image comes from, and keeping the webapp's files in step with the game.

`mapping.json` (next to this file, committed) maps a webapp image (path inside `webapp/public/assets`, with its
extension) to the game picture it is made from:

    "items/chest/chiefs_coin_chest.png": {"source": "Zombie_ItemIcon144/Icon_Item_Box_Explorer_2", "synced": "<md5>"}
    "events/demon_king_ranger_blight.webp": {"source": "Zombie_Act_WorldBoss2/pic_sjboss_haibao", "focus": [0.5, 0.1], ...}
    "events/some_banner.webp": {"source": "...", "resize": true}   720x360 even though the picture is near 2:1
    "items/some_made_up_icon.png": {"source": null}        the game has no original: stays unofficial on purpose

    "events/canyon_conquest.webp": {"source": "...", "overlay": {"source": "...", "scale": 0.8, "at": [0.5, 0.5]}, ...}
                                                       a second picture (a trophy) on top of the first
    "events/x.webp": {"source": "A", "focus": [0.3, 0.0], "beside": [{"source": "B"}, {"source": "C", "focus": [0.7, 0.1]}]}
                                                       three pictures next to each other (one `beside` entry: two)

`source` is a picture id of `out/index.json`; `focus` is the crop window of `render.py`; `resize` makes an event
banner 720x360 although it is close to 2:1 (otherwise it keeps the game's size); `overlay` puts another picture on top
(`render.compose`: its height `scale` times the image's, centred at `at`); `beside` puts the pictures after the first
next to it in equal columns (`render.side_by_side`, each with its own `focus`; the editor writes `overlay` or `beside`,
not both); `synced` is the fingerprint (`fingerprint`: the md5 of the game picture, of all its pictures together with an
overlay or `beside`) the file was last made from. An image is

    official    mapped, and the file was made from the game's current picture
    to sync     mapped, but never synced or the game changed the picture since (`sync` rebuilds the file)
    missing     mapped to a picture the index does not have (extract it again, or map something else)
    gone        was official (`synced`), but the game's picture is now missing or a blank placeholder (a PNG under
                `MIN_BYTES`, or fully transparent): the game dropped it. The file stays as it is, `sync` never replaces
                it (not even with `--force`); the status ends when the game has a real picture again, or by mapping another
    suggested   not mapped, the hash match found a close picture (`CLOSE`) - to be confirmed
    unmapped    not mapped, nothing close
    none        marked as having no original in the game

Only `official` images are the game's own (a `gone` one was, and its file is still the game's last picture). `sync` writes
nothing without `apply`; it lists what it would do.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from PIL import Image

import config as C
import match as M
import render as R
import state as S

PATH = C.HERE / "mapping.json"
STATUSES = ("official", "to sync", "gone", "missing", "suggested", "unmapped", "none")
MIN_BYTES = 1024  # a game picture's PNG under this is a blank placeholder, not a picture


def load(path: Path = PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(mapping: dict, path: Path = PATH) -> None:
    S.write_json(path, dict(sorted(mapping.items())))


def load_matches(out: Path = C.OUT) -> dict:
    try:
        return json.loads((out / "matches.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def best_candidate(matches: dict, rel: str) -> dict | None:
    found = matches.get(rel)
    return found[0] if found else None


def sources(entry: dict) -> list[str]:
    """The ids of every game picture the entry is made from: its own, the overlay, then the `beside` ones."""
    over = entry.get("overlay")
    return [entry.get("source"), *([over["source"]] if over else []), *(b["source"] for b in entry.get("beside") or [])]


def fingerprint(entry: dict, sprites: dict) -> str | None:
    """What `synced` records: the md5 of the entry's game picture (with more pictures, of all together); None if one is not extracted."""
    found = [sprites.get(i) for i in sources(entry)]
    if any(f is None for f in found):
        return None
    if len(found) == 1:
        return found[0]["md5"]
    return hashlib.md5("".join(f["md5"] for f in found).encode()).hexdigest()


@lru_cache(maxsize=None)
def _transparent(path: str, size: int, mtime: int) -> bool:
    with Image.open(path) as img:
        return "A" in img.getbands() and img.getchannel("A").getextrema()[1] == 0


def blank(png: Path) -> bool:
    """Is this extracted picture a placeholder: missing, a PNG under `MIN_BYTES`, or fully transparent?"""
    try:
        stat = png.stat()
        return stat.st_size < MIN_BYTES or _transparent(str(png), stat.st_size, stat.st_mtime_ns)
    except (OSError, ValueError):
        return True


def lost_source(entry: dict, sprites: dict, out: Path = C.OUT) -> str | None:
    """The id of a picture the game dropped from an entry that was made from it: not in the index, or `blank`.
    None if the entry never was synced (it was not official) or all its pictures are fine."""
    if not entry.get("synced"):
        return None
    return next((i for i in sources(entry) if i not in sprites or blank(out / f"{i}.png")), None)


def overlay_of(entry: dict, out: Path = C.OUT) -> dict | None:
    """The entry's overlay as `render.render` takes it (the picture's path instead of its id)."""
    over = entry.get("overlay")
    return over and {**over, "path": out / f"{over['source']}.png"}


def beside_of(entry: dict, out: Path = C.OUT) -> list[dict] | None:
    """The entry's `beside` pictures as `render.render` takes them (the picture's path instead of its id)."""
    return [{**b, "path": out / f"{b['source']}.png"} for b in entry["beside"]] if entry.get("beside") else None


def status_of(rel: str, mapping: dict, sprites: dict, matches: dict, assets: Path = C.WEBAPP_ASSETS, out: Path = C.OUT) -> str:
    entry = mapping.get(rel)
    if entry is None:
        best = best_candidate(matches, rel)
        return "suggested" if best and best["dist"] <= M.CLOSE else "unmapped"
    if entry.get("source") is None:
        return "none"
    if lost_source(entry, sprites, out):
        return "gone"
    current = fingerprint(entry, sprites)
    if current is None:
        return "missing"
    return "official" if entry.get("synced") == current and (assets / rel).is_file() else "to sync"


def rows(mapping: dict, index: dict, matches: dict, assets: Path = C.WEBAPP_ASSETS, out: Path = C.OUT) -> list[dict]:
    """One row per webapp image: {rel, status, source, dist (of the best candidate)}."""
    result = []
    for path in M.webapp_images(assets):
        rel = path.relative_to(assets).as_posix()
        best = best_candidate(matches, rel)
        result.append({
            "rel": rel,
            "status": status_of(rel, mapping, index["sprites"], matches, assets, out),
            "source": (mapping.get(rel) or {}).get("source") or (best["id"] if best else None),
            "dist": best["dist"] if best else None,
        })
    return result


def counts(table: list[dict]) -> dict[str, int]:
    return {s: sum(1 for r in table if r["status"] == s) for s in STATUSES}


def summary(table: list[dict]) -> str:
    c = counts(table)
    return (f"Official {c['official']} of {len(table)} webapp images - to sync {c['to sync']}, suggested {c['suggested']}, "
            f"unmapped {c['unmapped']}, no original {c['none']}" + "".join(f", {s} {c[s]}" for s in ("gone", "missing") if c[s]))


def set_source(rel: str, source: str | None, focus=None, synced: str | None = None, resize: bool = False,
               path: Path = PATH, overlay: dict | None = None, beside: list[dict] | None = None) -> dict:
    """Map `rel` (re-read from the file first, so nothing another window wrote is lost); None = no original.
    Without `synced` (the fingerprint of what the file was just made from) the entry needs a sync. `overlay`
    is {source, scale, at}, `beside` a list of {source, focus} (a default focus is left out)."""
    mapping = load(path)
    entry = {"source": source}
    if source is not None and overlay:
        entry["overlay"] = overlay
    if source is not None and beside:
        entry["beside"] = [{"source": b["source"], **({"focus": [round(float(v), 3) for v in b["focus"]]}
                                                       if b.get("focus") and tuple(b["focus"]) != R.DEFAULT_FOCUS else {})}
                           for b in beside]
    if source is not None and focus and tuple(focus) != R.DEFAULT_FOCUS:
        entry["focus"] = [round(float(v), 3) for v in focus]
    if source is not None and resize:
        entry["resize"] = True
    if synced:
        entry["synced"] = synced
    mapping[rel] = entry
    save(mapping, path)
    return entry


def clear(rel: str, path: Path = PATH) -> None:
    mapping = load(path)
    if mapping.pop(rel, None) is not None:
        save(mapping, path)


def accept_suggestions(table: list[dict], max_dist: int, path: Path = PATH) -> int:
    """Map every unmapped webapp image to its best candidate when that is within `max_dist`; returns how many."""
    mapping = load(path)
    taken = 0
    for r in table:
        if r["rel"] not in mapping and r["source"] and r["dist"] is not None and r["dist"] <= max_dist:
            mapping[r["rel"]] = {"source": r["source"]}
            taken += 1
    if taken:
        save(mapping, path)
    return taken


def sync(index: dict, apply: bool = False, force: bool = False, out: Path = C.OUT, assets: Path = C.WEBAPP_ASSETS,
         path: Path = PATH) -> list[dict]:
    """Make the webapp's files from the game pictures they are mapped to. Without `apply` nothing is written.

    A file is rebuilt when it was never synced from the current picture (or `force`); the result is a list of
    {rel, action: write / same / skipped, note}. An entry whose game picture is gone (`lost_source`) is skipped and its
    file kept, `force` or not. `same`: the file already shows exactly the rebuilt picture (it is
    left alone and only marked synced, so a re-encoded copy does not make a needless change)."""
    mapping = load(path)
    done = []
    for rel, entry in sorted(mapping.items()):
        source = entry.get("source")
        if source is None:
            continue
        lost = lost_source(entry, index["sprites"], out)
        if lost:
            done.append({"rel": rel, "action": "skipped", "note": f"{lost} is gone from the game or only a blank placeholder: the file is kept"})
            continue
        picture = out / f"{source}.png"
        overlay = overlay_of(entry, out)
        current = fingerprint(entry, index["sprites"])
        missing = [i for i in sources(entry) if not (out / f"{i}.png").is_file()]
        if current is None or missing:
            done.append({"rel": rel, "action": "skipped", "note": f"{(missing or [source])[0]} is not extracted"})
            continue
        target = assets / rel
        if not force and entry.get("synced") == current and target.is_file():
            continue
        data, note = R.render(picture, rel, entry.get("focus"), entry.get("resize", False), overlay, beside_of(entry, out))
        same = target.is_file() and R.same_pixels(data, target)
        if apply:
            if not same:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            entry["synced"] = current
        done.append({"rel": rel, "action": "same" if same else "write", "note": note})
    if apply and done:
        save(mapping, path)
    return done
