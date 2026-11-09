"""Import: add one extracted picture to the webapp's assets as a new image, and map it.

    python main.py import Zombie_ItemIcon144/icon_gold items/material/gold
    python main.py import Zombie_Act_WorldBoss2/pic_sjboss_haibao events/new_boss --focus 0.5,0.1

The file is made as `render.py` does for its folder (items and heroes 144x144 PNG, events WebP: a near-2:1 banner keeps
the game's size unless `--resize`, anything else is cropped to 720x360 by `--focus`) and recorded in `mapping.json`, so
it counts as official and `sync` keeps it in step with the game. Nothing is overwritten without `force`.
"""

from __future__ import annotations

from pathlib import PurePosixPath

import config as C
import mapping as Mp
import render as R
import state as S


def import_picture(sprite_id: str, dest: str, force: bool = False, focus=None, resize: bool = False, out=C.OUT,
                   assets=C.WEBAPP_ASSETS, index: dict | None = None, mapping_path=Mp.PATH) -> tuple[object, str]:
    """Make `assets/<dest>` from `out/<sprite_id>.png` and map it; returns (the new file, what was done to the size)."""
    source = out / f"{sprite_id}.png"
    if not source.is_file():
        swapped = (out / f"{dest.strip().removesuffix('.png')}.png").is_file()  # the destination is a picture id
        raise FileNotFoundError(
            f"no extracted picture {sprite_id} (see the gallery for the ids)"
            + (f" - but {dest} is one: the two look swapped (first the game picture, then the webapp file to make)" if swapped else "")
        )
    rel = PurePosixPath(dest.strip().replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or len(rel.parts) < 2:
        raise ValueError(f"destination must be <folder>/<name> inside the assets folder, e.g. items/chest/gold: {dest}")
    if rel.suffix.lower() not in (".png", ".webp"):
        rel = rel.with_name(rel.name + R.default_extension(rel.parts[0]))
    target = assets / rel
    if target.exists() and not force:
        raise FileExistsError(f"{target} exists (use --force to replace it)")
    sprite = (index or S.load_index())["sprites"].get(sprite_id)
    data, note = R.render(source, rel.as_posix(), focus, resize)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    # made from the picture as it is now
    Mp.set_source(rel.as_posix(), sprite_id, focus, sprite["md5"] if sprite else None, resize, mapping_path)
    return target, note
