"""Which of the game's sprites does the webapp already use? A perceptual hash tells.

`dhash` is a 256-bit difference hash (brightness gradients of a 17x16 thumbnail, transparent areas on neutral grey), so
a screenshot-made icon and the game's original land close together even when their size, framing or colours differ a
bit. `match` hashes every PNG and WebP of `webapp/public/assets` and lists, for each, the three closest sprites of
`out/index.json` with their distance (0-256; `CLOSE` or less is the same picture in practice) in `out/matches.json`.
The sprites' own hashes are computed while extracting and stored in the index.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

import config as C
import state as S

HASH_W, HASH_H = 17, 16  # 16 gradients per row, 16 rows = 256 bits
CLOSE = 40  # distance up to which two images count as the same picture
TOP = 3  # candidates kept per webapp image
POPCOUNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def dhash(img: Image.Image) -> str:
    base = Image.new("RGBA", img.size, (128, 128, 128, 255))
    base.alpha_composite(img.convert("RGBA"))
    grey = np.asarray(base.convert("L").resize((HASH_W, HASH_H), Image.LANCZOS), dtype=np.int16)
    return np.packbits(grey[:, :-1] > grey[:, 1:]).tobytes().hex()


def distances(needle: str, hashes: np.ndarray) -> np.ndarray:
    """Hamming distance of one hash to every row of `hashes` ((N, 32) uint8)."""
    return POPCOUNT[np.bitwise_xor(hashes, np.frombuffer(bytes.fromhex(needle), dtype=np.uint8))].sum(axis=1, dtype=np.int32)


def closest(needle: str, ids: list[str], hashes: np.ndarray, top: int = TOP) -> list[dict]:
    dist = distances(needle, hashes)
    order = np.argsort(dist, kind="stable")[:top]
    return [{"id": ids[i], "dist": int(dist[i])} for i in order]


def webapp_images(assets: Path = C.WEBAPP_ASSETS) -> list[Path]:
    """Every PNG and WebP of the assets folder (the SVG is not a game picture)."""
    C.require_webapp(assets)
    return sorted(p for p in assets.rglob("*") if p.suffix.lower() in (".png", ".webp"))


def match(index: dict, assets: Path = C.WEBAPP_ASSETS) -> dict:
    """{webapp path relative to the assets folder: [{id, dist}, ...]} against the sprites of `index`."""
    sprites = [s for s in index["sprites"].values() if s.get("dhash")]
    if not sprites:
        return {}
    ids = [s["id"] for s in sprites]
    hashes = np.array([np.frombuffer(bytes.fromhex(s["dhash"]), dtype=np.uint8) for s in sprites])
    found = {}
    for path in webapp_images(assets):
        with Image.open(path) as img:
            found[path.relative_to(assets).as_posix()] = closest(dhash(img), ids, hashes)
    return found


def run() -> dict:
    found = match(S.load_index())
    S.write_json(C.OUT / "matches.json", found, indent=None)
    return found
