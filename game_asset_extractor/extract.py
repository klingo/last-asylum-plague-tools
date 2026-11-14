"""Extract: turn the pulled bundles into PNGs, out/<type>/<group>/<name>.png, and keep out/index.json up to date.

The PNGs of each type (pictures, effects, models, ... as `config.TYPES`) sit below a folder of the type's name, so a type
can be deleted as one folder; the gallery and the hash match only take the pictures (`config.is_picture`). A bundle
without a picture leaves no folder.

The bundles of `config.TEXT_TYPES` (game texts, tables, scripts) hold TextAssets, not textures: each is written as a file
below `out/<type>/<the bundle's whole path>/` (`.txt` when it reads as UTF-8, `.bin` when not: the game's tables and Lua
scripts are obfuscated, the language tables, `.proto` files and atlas lists are plain text). They are not in `out/index.json`;
a bundle's files are rewritten whenever the bundle changes. When a run wrote texts, `texts.update_index` records in
`out/texts.json` which texts it added or changed (for the text browser), under the same run number as the pictures.

Three kinds of pictures are in a bundle:
  - NGUI atlases (the game's UI): a MonoBehaviour with `mSprites` (name, x, y, width, height, padding; from the top
    left) and a material whose `_MainTex` is the atlas texture. Every sprite is cut out of it.
  - Unity `Sprite` objects: exported as UnityPy cuts them.
  - Any other Texture2D (banners, backgrounds, loose icons): exported whole.

`out/index.json` has one entry per picture (id = `type/group/name`, size, bundle, type, md5 of the PNG, dhash for `match.py`) and
which extract run added it (`added`) or last changed it (`changed`); `meta.runs` says when each run was and for which
resource version. `meta.baseline` is the run up to which everything counts as seen (`mark_seen`): the gallery marks what
was added or changed after it. The runs and each picture's and text's run are also written to `history.json` (`history.py`,
committed) at the end of every run; a cache that starts empty is rebuilt from it (`meta.restoring` until every bundle is back).
"""

from __future__ import annotations

import hashlib
import io
import re
import time
from pathlib import Path

import UnityPy
from PIL import Image

import config as C
import history as H
import match as M
import scan as Sc
import state as S
import texts as T

SAFE = re.compile(r"[^\w.\-]+")


def safe_name(name: str) -> str:
    return SAFE.sub("_", name).strip("._") or "unnamed"


def crop_ngui(atlas: Image.Image, sprite: dict) -> Image.Image | None:
    """One sprite out of an NGUI atlas picture (x and y count from the top left, as in the picture)."""
    x, y, w, h = sprite["x"], sprite["y"], sprite["width"], sprite["height"]
    if w <= 0 or h <= 0:
        return None
    crop = atlas.crop((x, y, x + w, y + h))
    pads = [sprite.get(k, 0) for k in ("paddingLeft", "paddingRight", "paddingTop", "paddingBottom")]
    if any(pads):  # the sprite was trimmed: put it back into its full box
        full = Image.new("RGBA", (w + pads[0] + pads[1], h + pads[2] + pads[3]))
        full.paste(crop, (pads[0], pads[2]))
        return full
    return crop


def export_bundle(path: Path) -> list[tuple[str, Image.Image]]:
    """[(name, RGBA image)] of everything a bundle holds."""
    env = UnityPy.load(str(path))
    objects = {o.path_id: o for o in env.objects}
    textures = {pid: o for pid, o in objects.items() if o.type.name == "Texture2D"}
    used: set[int] = set()
    images: list[tuple[str, Image.Image]] = []

    def texture_image(pid: int) -> Image.Image | None:
        try:
            return textures[pid].read().image.convert("RGBA")
        except Exception as e:  # noqa: BLE001 - an unsupported texture format must not stop the bundle
            print(f"!! {path.name}: texture {pid}: {e}", flush=True)
            return None

    for o in objects.values():
        if o.type.name == "MonoBehaviour":
            try:
                data = o.read_typetree()
            except Exception:  # noqa: BLE001 - no type tree / not readable: not an atlas we know
                continue
            if not isinstance(data, dict) or "mSprites" not in data:
                continue
            pid = main_texture(data, objects, textures)
            atlas = texture_image(pid) if pid is not None else None
            if atlas is None:
                continue
            used.add(pid)
            images += [(s["name"], img) for s in data["mSprites"] if (img := crop_ngui(atlas, s)) is not None]
        elif o.type.name == "Sprite":
            try:
                sprite = o.read()
                images.append((sprite.m_Name, sprite.image.convert("RGBA")))
                used.add(sprite.m_RD.texture.path_id)
            except Exception as e:  # noqa: BLE001
                print(f"!! {path.name}: sprite: {e}", flush=True)

    for pid, o in textures.items():
        if pid not in used and (img := texture_image(pid)) is not None:
            images.append((o.read().m_Name, img))
    return images


def export_texts(path: Path) -> list[tuple[str, bytes]]:
    """[(name, bytes)] of the TextAssets of a bundle."""
    files = []
    for o in UnityPy.load(str(path)).objects:
        if o.type.name == "TextAsset":
            asset = o.read()
            raw = asset.m_Script
            files.append((asset.m_Name, raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else bytes(raw)))
    return files


def write_texts(kind: str, path_name: str, files: list[tuple[str, bytes]]) -> int:
    """Write a bundle's TextAssets into `out/<kind>/<its path>/`, replacing what an earlier version of it wrote there
    (only the files directly in the folder: the folders of other bundles below it stay); returns how many."""
    folder = C.OUT.joinpath(kind, *(safe_name(part) for part in path_name.split("/")))
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.iterdir():
        if old.is_file():
            old.unlink()
    taken: set[str] = set()
    for raw, data in files:
        base = safe_name(raw)
        if not base.endswith(".proto"):
            try:
                data.decode("utf-8")
                base += ".txt"
            except UnicodeDecodeError:
                base += ".bin"
        stem, dot, ext = base.rpartition(".")
        unique, n = base, 1
        while unique.lower() in taken:  # Windows folds the case: Foo and foo are one file
            n += 1
            unique = f"{stem}_{n}{dot}{ext}"
        taken.add(unique.lower())
        (folder / unique).write_bytes(data)
    return len(files)


def main_texture(atlas_data: dict, objects: dict, textures: dict) -> int | None:
    """The path id of an atlas's texture: its material's `_MainTex`, else the bundle's only texture."""
    try:
        material = objects[atlas_data["material"]["m_PathID"]].read_typetree()
        for key, env in material["m_SavedProperties"]["m_TexEnvs"]:
            if key == "_MainTex" and env["m_Texture"]["m_PathID"] in textures:
                return env["m_Texture"]["m_PathID"]
    except (KeyError, TypeError, ValueError):
        pass
    return next(iter(textures)) if len(textures) == 1 else None


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def extract_bundle(name: str, group: str, images: list[tuple[str, Image.Image]], index: dict, run: int, kind: str) -> int:
    """Write a bundle's pictures (of the type `kind`) and update its index entries; returns how many are new or changed."""
    group = f"{kind}/{safe_name(group)}"  # the id's group is the folder's path below out/
    sprites = index["sprites"]
    old = {i: sprites.pop(i) for i in [i for i, s in sprites.items() if s["bundle"] == name]}
    taken = {s["id"] for s in sprites.values()}
    folder = C.OUT / group
    news = 0
    kept = set()
    for raw, img in images:
        base = safe_name(raw)
        unique, n = base, 1
        while f"{group}/{unique}" in taken:
            n += 1
            unique = f"{base}_{n}"
        sid = f"{group}/{unique}"
        taken.add(sid)
        data = png_bytes(img)
        md5 = hashlib.md5(data).hexdigest()
        before = old.get(sid)
        differs = before is not None and before["md5"] != md5
        if before is None or differs:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{unique}.png").write_bytes(data)
            news += 1
        sprites[sid] = {
            "id": sid, "group": group, "name": unique, "w": img.width, "h": img.height, "bundle": name, "type": kind,
            "md5": md5, "dhash": M.dhash(img),
            "added": before["added"] if before else run,
            "changed": run if differs else (before or {}).get("changed"),
        }
        kept.add(sid)
    for sid in old.keys() - kept:  # no longer in the bundle
        (C.OUT / old[sid]["group"] / f"{old[sid]['name']}.png").unlink(missing_ok=True)
    return news


def mark_seen() -> int:
    """Everything extracted so far counts as seen: the gallery's NEW / CHANGED only show what comes after. Returns the run."""
    index = S.load_index()
    index["meta"]["baseline"] = index["meta"]["run"]
    S.save_index(index)
    return index["meta"]["baseline"]


def run(force: bool = False) -> dict:
    """Extract every pulled bundle whose pictures are missing or out of date; returns the counts."""
    pulled, done = S.load("pulled.json"), S.load("extracted.json")
    todo = sorted(n for n, p in pulled.items() if (force or done.get(n) != p["md5"]) and (C.CACHE / n).exists())
    index = S.load_index()
    counts = {"bundles": len(todo), "pictures": 0, "texts": 0, "new_or_changed": 0, "failed": 0}
    if not todo:
        return counts
    meta, history = index["meta"], H.load()
    if not (H.restore_run(index, history) or meta.get("restoring")):  # else: a cache rebuilt from history.json, no new run
        meta["run"] += 1
        version = (C.STATE / "version.txt").read_text(encoding="utf-8").strip() if (C.STATE / "version.txt").exists() else "?"
        meta["runs"][str(meta["run"])] = {"version": version, "time": time.strftime("%Y-%m-%d %H:%M")}
    try:
        for i, name in enumerate(todo, 1):
            path, kind = pulled[name]["path"], Sc.type_of(pulled[name]["path"])
            try:
                if kind in C.TEXT_TYPES:
                    counts["texts"] += write_texts(kind, path, export_texts(C.CACHE / name))
                else:
                    images = export_bundle(C.CACHE / name)
            except Exception as e:  # noqa: BLE001 - one broken bundle must not stop the rest
                counts["failed"] += 1
                print(f"!! {name}: {e}", flush=True)
                continue
            if kind not in C.TEXT_TYPES:
                counts["pictures"] += len(images)
                counts["new_or_changed"] += extract_bundle(name, Sc.group_of(path), images, index, meta["run"], kind)
            done[name] = pulled[name]["md5"]
            if i % 20 == 0:
                print(f"progress extract: {i * 100 // len(todo)} %", flush=True)
    finally:
        if meta.get("restoring"):  # a rebuilt cache: the pictures get the runs the history recorded, until every bundle is back
            H.apply_pictures(index, history)
            if all(done.get(n) == p["md5"] for n, p in pulled.items() if (C.CACHE / n).exists()):
                del meta["restoring"]
        S.save_index(index)
        S.save("extracted.json", done)
        if counts["texts"]:
            T.update_index(meta["run"])
        H.record(index, T.load_index())
    return counts
