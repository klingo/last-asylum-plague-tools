"""Names made of square symbols (`■□■`): read by their shape, because no OCR model sees them as text.

The game draws characters its font does not have as plain squares, solid or outlined. When the OCR found no name on a
card, the name line is searched for square blobs: a solid one is `■`, an outline whose inside is background is `□`.
Anything else in the line (a blob that is not square, a mix with other shapes) makes it return nothing: the name then
stays unreadable (`?`) and is fixed by hand in `corrections.json`.
"""

from __future__ import annotations

import cv2
import numpy as np

import config as C

CONTRAST = 35  # grey levels darker than the card's background that count as ink
SIZE = (0.012, 0.05)  # a glyph's side, as a fraction of the frame width (about 26 px of 1080)
SQUARE = (0.8, 1.25)  # allowed width / height of a glyph
SOLID = 0.8  # share of the box that is ink in a `■`
OUTLINE = (0.12, 0.6)  # ... in a `□`
MIN_BLOB = 0.004  # blobs smaller than this fraction of the width are specks, not glyphs


def read_squares(frame: np.ndarray, card_cy: float) -> str:
    """The square symbols on the name line of the card centred at `card_cy`, '' if it is not made only of them."""
    height, width = frame.shape[:2]
    top = max(round(card_cy - 0.040 * height), 0)
    left, right = round(C.NAME_COLUMN[0] * width), round(C.NAME_COLUMN[1] * width)
    line = frame[top : round(card_cy - 0.006 * height), left:right]
    if line.size == 0:
        return ""
    grey = cv2.cvtColor(line, cv2.COLOR_BGR2GRAY)
    ink = (grey < np.median(grey) - CONTRAST).astype(np.uint8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    glyphs = []
    for x, y, w, h, area in stats[1:]:
        if max(w, h) < MIN_BLOB * width:
            continue  # a speck
        if x == 0 or y == 0 or x + w >= ink.shape[1] or y + h >= ink.shape[0]:
            continue  # cut by the line's edge: the avatar's frame or the card's border, not a glyph
        if not (SIZE[0] * width <= w <= SIZE[1] * width and SQUARE[0] <= w / h <= SQUARE[1]):
            return ""  # something that is not a square symbol: not a name made of them
        fill = area / (w * h)
        inside = ink[y + h // 4 : y + h - h // 4, x + w // 4 : x + w - w // 4]
        if fill >= SOLID:
            glyphs.append((x, "■"))
        elif OUTLINE[0] <= fill <= OUTLINE[1] and inside.mean() < 0.1:
            glyphs.append((x, "□"))
        else:
            return ""
    return "".join(symbol for _, symbol in sorted(glyphs))
