"""Render: a game picture into the form a webapp folder uses (size, crop, file format).

    items/, heroes/   144 x 144 PNG
    events/           WebP (quality `WEBP_QUALITY`): a banner of about 2:1 (`KEEP_ASPECT`) keeps the game's own size
                      (726 x 346, 706 x 360, ...: the page shows it in a 2:1 box with `object-fit: cover` anyway), anything
                      else is cropped and resized to 720 x 360; `force_size` takes 720 x 360 for a near-2:1 one too
    packages/         a weekday offer's own picture, `<pack id>.webp`: the game's picture as it is (320 x 240, ...), WebP
    anything else     the picture as it is, PNG (WebP if the file name says .webp)

A picture whose aspect ratio is not the folder's is cropped to it, not stretched: `focus` says where the window sits in
the free space, (x, y) from 0 (left / top) to 1 (right / bottom), default centred horizontally and at the top (a tall
poster keeps its upper part). A picture that has to be enlarged by more than 10 % gets a warning. Transparency is kept.

An `overlay` puts a second picture (a trophy, say) on top of the result: `{"path", "scale", "at"}`, its height `scale` times
the result's, centred at `at` = (x, y) from 0 to 1 of the result, its transparency respected.
"""

from __future__ import annotations

import io
from pathlib import Path, PurePosixPath

from PIL import Image

FOLDER_SIZES = {"items": (144, 144), "heroes": (144, 144), "events": (720, 360)}
FOLDER_FORMAT = {"events": ".webp", "packages": ".webp"}  # the extension a new file of the folder gets; the others are .png
KEEP_ASPECT = {"events": (1.8, 2.3)}  # folder -> range of width / height whose pictures keep their own size
WEBP_QUALITY = 85
DEFAULT_FOCUS = (0.5, 0.0)
ASPECT_TOLERANCE = 0.02
OVERLAY_SCALE, OVERLAY_AT = 0.8, (0.5, 0.5)  # an overlay picture's defaults: height as a fraction of the result's, centre
ENLARGE_WARNING = 1.1  # a picture stretched by more than this (10 %) to reach the target is called out


def target_size(dest: str) -> tuple[int, int] | None:
    return FOLDER_SIZES.get(PurePosixPath(dest).parts[0])


def keeps_size(dest: str, size: tuple[int, int]) -> bool:
    """Does the folder of `dest` let a picture of this size keep it (an aspect close to the folder's)?"""
    low_high = KEEP_ASPECT.get(PurePosixPath(dest).parts[0])
    return bool(low_high) and low_high[0] <= size[0] / size[1] <= low_high[1]


def default_extension(folder: str) -> str:
    return FOLDER_FORMAT.get(folder, ".png")


def fit(img: Image.Image, size: tuple[int, int] | None, focus=DEFAULT_FOCUS) -> tuple[Image.Image, str]:
    """`img` cropped (if its aspect differs) and resized to `size`; the note says what was done."""
    w, h = img.size
    if size is None or img.size == size:
        return img, f"{w}x{h}, as it is"
    tw, th = size
    notes = []
    if abs(w / h - tw / th) > ASPECT_TOLERANCE * (tw / th):
        fx, fy = (min(max(v, 0.0), 1.0) for v in focus)
        if w / h > tw / th:  # too wide: cut the sides
            new_w = round(h * tw / th)
            x = round((w - new_w) * fx)
            img, notes = img.crop((x, 0, x + new_w, h)), [f"cropped {w}x{h} to {tw}:{th}"]
        else:  # too tall: cut top / bottom
            new_h = round(w * th / tw)
            y = round((h - new_h) * fy)
            img, notes = img.crop((0, y, w, y + new_h)), [f"cropped {w}x{h} to {tw}:{th}"]
    if tw / img.width > ENLARGE_WARNING or th / img.height > ENLARGE_WARNING:
        notes.append(f"WARNING: enlarged from {img.width}x{img.height}")
    return img.resize(size, Image.LANCZOS), ", ".join(notes + [f"resized to {tw}x{th}"])


def compose(img: Image.Image, overlay: dict) -> tuple[Image.Image, str]:
    """`img` with the picture of `overlay` on top; the note names it."""
    with Image.open(overlay["path"]) as src:
        top = src.convert("RGBA")
    height = max(1, round(img.height * overlay.get("scale", OVERLAY_SCALE)))
    top = top.resize((max(1, round(top.width * height / top.height)), height), Image.LANCZOS)
    ax, ay = overlay.get("at", OVERLAY_AT)
    layer = Image.new("RGBA", img.size)
    layer.paste(top, (round(img.width * ax - top.width / 2), round(img.height * ay - top.height / 2)))
    return Image.alpha_composite(img.convert("RGBA"), layer), f"{Path(overlay['path']).stem} on top"


def encode(img: Image.Image, dest: str) -> bytes:
    buf = io.BytesIO()
    if dest.lower().endswith(".webp"):
        img.save(buf, "WEBP", quality=WEBP_QUALITY, method=6)
    else:
        img.convert("RGBA").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def same_pixels(data: bytes, existing: Path) -> bool:
    """Does the file `existing` show exactly what `data` shows (whatever encoder wrote it)?"""
    try:
        with Image.open(io.BytesIO(data)) as a, Image.open(existing) as b:
            return a.size == b.size and a.convert("RGBA").tobytes() == b.convert("RGBA").tobytes()
    except OSError:
        return False


def render(source: Path, dest: str, focus=None, force_size: bool = False, overlay: dict | None = None) -> tuple[bytes, str]:
    """The bytes of the file `dest` (relative path in the assets folder, e.g. events/x.webp) made from the picture `source`
    (and the `overlay` picture on top of it, if any)."""
    with Image.open(source) as src:
        img = src.convert("RGBA")
    if not force_size and keeps_size(dest, img.size):
        note = f"{img.width}x{img.height}, the game's size kept"
    else:
        img, note = fit(img, target_size(dest), tuple(focus) if focus else DEFAULT_FOCUS)
    if overlay:
        img, over = compose(img, overlay)
        note += f", {over}"
    return encode(img, dest), note
