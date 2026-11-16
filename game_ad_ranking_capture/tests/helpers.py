"""Test helpers: OCR words laid out like the Rank screen, and a fake game that scrolls a virtual ranking list."""

import numpy as np

import config as C
from ocr import Word

WIDTH, HEIGHT = 1080, 1920
PITCH = C.ROW_PITCH * HEIGHT
FIRST_CY = 550  # centre of the first card of a list scrolled to the top


def word(text, x0, cy, score=1.0, x1=None, half=20) -> Word:
    return Word(text, score, x0, round(cy - half), x1 if x1 is not None else x0 + 40 + 12 * len(text), round(cy + half))


def card(cy, rank, name, alliance, points, score=1.0, tag="SoIM") -> list[Word]:
    """The words of one row card as the OCR returns them: rank (not for medals), name, [tag]alliance, points."""
    words = [
        word(name, 370, cy - 32, score),
        word(f"[{tag}]{alliance}", 370, cy + 33, score),
        word(f"{points:,}", 804, cy),
    ]
    if rank is not None:
        words.append(word(str(rank), 104, cy, x1=141))
    return words


class VirtualList:
    """A ranking of `size` players, scrolled by a fake device. `overshoot` > 1 moves the list further than asked."""

    def __init__(self, size=60, overshoot=1.0, unnumbered_from=None):
        self.size, self.overshoot, self.offset = size, overshoot, 0.0
        self.unnumbered_from = unnumbered_from  # from this rank on, the game shows "Not ranked" (no number)
        self.players = [(rank, f"Player{rank}", 10_000_000 - rank * 1000) for rank in range(1, size + 1)]
        self.swipes = 0

    # -- the device
    def frame(self) -> np.ndarray:
        return np.full((HEIGHT, WIDTH, 3), min(255, round(self.offset * 4)), np.uint8)

    def settled(self) -> np.ndarray:
        return self.frame()

    def swipe(self, x0, y0, x1, y1, ms=0) -> None:
        self.swipes += 1
        self.offset = min(max(self.offset + (y0 - y1) / PITCH * self.overshoot, 0.0), self.size - 5.5)

    # -- the OCR
    def read(self, frame, region=None) -> list[Word]:
        offset = float(frame[0, 0, 0]) / 4
        words = []
        for rank, name, points in self.players:
            cy = FIRST_CY + (rank - 1 - offset) * PITCH
            if 0.2 * HEIGHT < cy < 0.8 * HEIGHT + PITCH / 2:
                numbered = 3 < rank and (self.unnumbered_from is None or rank < self.unnumbered_from)
                words += card(cy, rank if numbered else None, name, "Mice", points)
        words += card(1622, 28, "Klingo", "Mice", 15_000_000)  # the pinned own row
        return words


class NoWords:
    def read(self, frame, region=None) -> list[Word]:
        return []
