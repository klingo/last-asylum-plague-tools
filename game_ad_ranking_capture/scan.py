"""One day's whole ranking list: scroll to the top, read a page, swipe, repeat until the list ends.

Pages are merged by rank. Far down the list the game shows no rank numbers ("Not ranked"): a card is then placed by
one the earlier pages read (same name and points), so a swipe must always leave a card of the old page on the new one.
How far a swipe really moves the list is measured from where the same cards sit on two pages and the next swipe is sized
by it. A swipe that skipped cards (the next page starts after the last known rank + 1) is undone by a swipe back to just
above them, a page that cannot be placed is looked at again from further up, so the list is read without gaps. The end
is reached when two swipes in a row bring no new rank on pages that could be read, or at `MAX_ROWS`. Rows the OCR was
unsure about (or had to read with the second engine) are returned with a
picture of their card, so they can be looked at. Nothing here taps anything but the list itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

import config as C
import rows as R
import symbols
from device import STABLE, difference

MAX_UP_SWIPES = 80  # from the bottom of a 200 row list, four rows a swipe, is about 50
READ_TRIES = 3  # times a page without readable ranks is looked at before it is given up
MAX_UNREADABLE = 4  # such pages per day before the scan stops as incomplete
MAX_RECOVERIES = 8  # swipes back per day after a skipped card (the first swipe is a guess, the rest are measured)


@dataclass
class Review:
    rank: int
    flags: list[str]
    crop: np.ndarray


@dataclass
class DayScan:
    rows: list[dict]
    me: dict | None
    complete: bool
    warnings: list[str] = field(default_factory=list)
    review: list[Review] = field(default_factory=list)
    unreadable: list[np.ndarray] = field(default_factory=list)  # whole frames of pages whose ranks could not be read


class Scanner:
    def __init__(
        self,
        device,
        primary,
        secondary,
        progress: Callable[[str], None] = print,
        should_stop: Callable[[], bool] = lambda: False,
    ):
        self.device, self.primary, self.secondary = device, primary, secondary
        self.progress, self.should_stop = progress, should_stop

    # -- reading
    def read_page(self, frame: np.ndarray) -> R.Page:
        height, width = frame.shape[:2]
        words = self.primary.read(frame, (0, R.LOOKUP[0], 1, R.LOOKUP[1]))
        page = R.parse_page(words, width, height)
        again = lambda region: self.secondary.read(frame, region)  # noqa: E731
        page.rows = [
            R.refine(row, again, width, height) if "no name" in row.flags or row.confidence < C.MIN_CONFIDENCE else row
            for row in page.rows
        ]
        for row in page.rows:
            if "no name" in row.flags and (squares := symbols.read_squares(frame, row.cy)):
                row.name = squares  # a name made of square symbols: no OCR model sees those as text
                row.flags.remove("no name")
        return page

    def read_numbered(self, frame: np.ndarray, found: dict[int, dict]) -> tuple[R.Page, np.ndarray]:
        """A page whose cards have ranks. A page without readable ranks is read again (the list may still have been
        moving) a couple of times; if it stays so, its rows come back without ranks."""
        for attempt in range(READ_TRIES):
            page = self.read_page(frame)
            if not page.rows or page.rows[0].rank is not None:
                return page, frame
            if R.number_from_overlap(page.rows, found, C.ROW_PITCH * frame.shape[0]):
                return page, frame
            if attempt < READ_TRIES - 1:
                frame = self.device.settled()
        return page, frame

    # -- moving
    def swipe(self, frame: np.ndarray, rows: float) -> None:
        """Moves the list by about `rows` cards (negative: back towards the top)."""
        height, width = frame.shape[:2]
        start = (C.LIST_BOTTOM - 0.05) * height if rows > 0 else (C.LIST_TOP + 0.05) * height
        self.device.swipe(width / 2, start, width / 2, start - rows * C.ROW_PITCH * height)

    def to_top(self) -> np.ndarray:
        previous = self.device.settled()
        for _ in range(MAX_UP_SWIPES):
            self.swipe(previous, -(C.SWIPE_ROWS + 1))
            frame = self.device.settled()
            if difference(previous, frame) < STABLE:
                return frame
            previous = frame
        return previous

    # -- the day
    def scan_day(self) -> DayScan:
        frame = self.to_top()
        found: dict[int, dict] = {}
        review: dict[int, Review] = {}
        warnings: list[str] = []
        me: dict | None = None
        stalled = recoveries = 0
        gain = 1.0  # cards the list really moves per card asked for, measured from where the same cards are
        asked: float | None = None  # what the last swipe asked for
        previous_at: dict[int, float] = {}  # rank -> y of its card on the previous page
        previous_lowest: int | None = None
        unreadable: list[np.ndarray] = []
        complete = False
        while not self.should_stop():
            page, frame = self.read_numbered(frame, found)
            height = frame.shape[0]
            if page.me:
                me = page.me.as_dict()
            if page.rows and page.rows[0].rank is None:
                # a page that cannot be read says nothing about the list's end: keep its picture, move on
                unreadable.append(frame)
                warnings.append(f"a page without a readable rank was skipped (after rank {max(found, default=0)})")
                if len(unreadable) > MAX_UNREADABLE:
                    break  # incomplete: something is wrong with the screen
                self.swipe(frame, -2 / gain)  # back, so that a card read before is on the page again to place it by
                frame = self.device.settled()
                continue
            lowest = min((row.rank for row in page.rows), default=None)
            at = {row.rank: row.cy for row in page.rows}
            pitch = C.ROW_PITCH * height
            moved = [(previous_at[rank] - cy) / pitch for rank, cy in at.items() if rank in previous_at]
            if asked and moved and sum(moved) / len(moved) >= 0.5:
                gain = sum(moved) / len(moved) / asked  # the same cards, a few pixels apart: the swipe's real length
            elif asked and lowest is not None and previous_lowest is not None and lowest > previous_lowest:
                gain = (lowest - previous_lowest) / asked  # no card in common: only the ranks tell, to a card
            previous_at = at or previous_at
            previous_lowest = lowest if lowest is not None else previous_lowest
            asked = None
            if found and lowest is not None and lowest > max(found) + 1 and recoveries < MAX_RECOVERIES:
                recoveries += 1  # cards were skipped: back to just above them and read again
                self.swipe(frame, -(lowest - max(found) - 1 + 1.5) / gain)
                frame = self.device.settled()
                continue
            new = 0
            for row in page.rows:
                if row.rank is None or row.rank in found:
                    continue
                found[row.rank] = row.as_dict()
                new += 1
                if row.flags:
                    half = round(C.ROW_PITCH * height / 2)
                    crop = frame[max(round(row.cy) - half, 0) : round(row.cy) + half]
                    review[row.rank] = Review(row.rank, row.flags, crop.copy())
            self.progress(f"{len(found)} rows, up to rank {max(found, default=0)}")
            stalled = 0 if new else stalled + 1
            if found and max(found) >= C.MAX_ROWS or stalled >= 2:
                complete = True
                break
            asked = C.SWIPE_ROWS / gain
            self.swipe(frame, asked)
            frame = self.device.settled()
        rows = [found[rank] for rank in sorted(found)]
        if me and me["rank"] not in found and me["rank"] and me["rank"] <= C.MAX_ROWS:
            warnings.append(f"the own row (rank {me['rank']}) was not read in the list")
        warnings += check(rows)
        return DayScan(rows, me, complete, warnings, [review[rank] for rank in sorted(review)], unreadable)


def check(rows: list[dict]) -> list[str]:
    """Problems a clean list does not have: a missing rank, points that go up further down."""
    warnings = []
    ranks = [row["rank"] for row in rows]
    missing = sorted(set(range(1, max(ranks, default=0) + 1)) - set(ranks))
    if missing:
        warnings.append(f"missing ranks: {', '.join(map(str, missing[:20]))}{' ...' if len(missing) > 20 else ''}")
    if rows and rows[0]["rank"] != 1:
        warnings.append(f"the list starts at rank {rows[0]['rank']}")
    for above, below in zip(rows, rows[1:]):
        if below["points"] > above["points"]:
            warnings.append(f"rank {below['rank']} has more points than rank {above['rank']}: a misread number?")
    return warnings
