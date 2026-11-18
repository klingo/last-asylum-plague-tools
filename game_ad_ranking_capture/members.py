"""The alliance's member list, read from the Alliance Members screen: who is in the alliance, for the zero-point days.

A member with 0 points on a day is not in the Duel's ranking at all, so the ranking alone cannot tell who was missing.
The screen shows the leader (R5) pinned at the top and the other members as cards in two columns, grouped by rank
(R4, R3, ...); every group has a header with its online / total count and an arrow that folds it. A folded group shows
no cards, so every folded header on the way is tapped open first. The numbers shown are the checks: the cards of a
group must add up to its total, and the leader plus all the cards to the member count at the top of the screen.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

import config as C
import symbols
from device import difference
from ocr import Word

CONTENT_TOP, CONTENT_BOTTOM = 0.422, 0.964  # the scrolling part of the screen, of height: the leader stays above it
COLUMNS = ((0.185, 0.50), (0.64, 0.96))  # x range (of width) of a card's text in the left and the right column
LV = re.compile(r"Lv\.?\s*\d+")
POWER = re.compile(r"^\d{1,3}(?:,\d{3})+$")
HEADER = re.compile(r"^R([1-5])$")
COUNT = re.compile(r"^(\d+)\s*/\s*(\d+)$")
NAME_ABOVE, NAME_BELOW = 0.046, 0.014  # a card's name line is this far (of height) above its Lv. line
CARD_ABOVE, CARD_BELOW = 0.058, 0.040  # the card reaches this far above the name line / below the Lv. line (power row)
ARROW_X = 0.915  # the header's fold arrow
ICON = 0.06  # width (of the frame) of the gender icon in front of a name
SWIPE_X, SWIPE_LENGTH = 0.25, 0.33  # where a swipe is (of the frame's width) and how long: about 3.5 cards
# The screen only takes a drag that starts on a card, not in the gap between two rows: a swipe that moved nothing is
# tried again from these other heights (of the frame, where the drag starts when it goes up) before it counts.
STARTS = (0.90, 0.86, 0.94, 0.82)
SCROLLED = 1.5  # grey levels the scrolling part differs by after a swipe that moved it
MAX_PAGES = 60
MAX_UP_BATCHES = 15  # one swipe from each start height per batch
MAX_EXPANDS = 8
MIN_SCORE = 0.5  # OCR boxes below this are noise (the gender icon, the card's border)


@dataclass
class Header:
    group: int  # 5 .. 1
    total: int | None
    cy: float
    collapsed: bool


@dataclass
class Card:
    name: str
    power: int | None
    cy: float
    column: int = 0  # 0 left, 1 right
    flags: list[str] = field(default_factory=list)


@dataclass
class Page:
    headers: list[Header]
    cards: list[Card]
    leader: str
    total: int | None  # the member count at the top right


@dataclass
class MemberScan:
    members: list[dict]  # {"name", "rank"} with rank "R5" .. "R1"
    total: int | None
    complete: bool
    warnings: list[str] = field(default_factory=list)
    expanded: list[str] = field(default_factory=list)
    joined: list[str] = field(default_factory=list)  # compared with the list that applied before (set when stored)
    left: list[str] = field(default_factory=list)


def moved(before: np.ndarray, after: np.ndarray) -> bool:
    """Whether the scrolling part of the screen changed (the pinned part has blinking `Online` texts)."""
    top = round(CONTENT_TOP * before.shape[0])
    return difference(before[top:], after[top:]) >= SCROLLED


def is_collapsed(frame: np.ndarray, cy: float) -> bool:
    """The header's arrow points up when the group is folded, down when it is open (the white triangle's mass is where
    the triangle is wide: below the middle for a triangle pointing up)."""
    height, width = frame.shape[:2]
    x, half = round(ARROW_X * width), round(0.02 * height)
    patch = frame[max(round(cy) - half, 0) : round(cy) + half, x - half : x + half]
    white = ((patch.min(axis=2) > 205) & (patch.max(axis=2) - patch.min(axis=2) < 40)).astype(np.uint8)
    rows = np.where(white.any(axis=1))[0]
    if len(rows) < 4:
        return False
    centre = (white[rows[0] : rows[-1] + 1].sum(axis=1) * np.arange(len(rows))).sum() / white.sum()
    return centre / (len(rows) - 1) > 0.5


def read_name(frame: np.ndarray, words: list[Word], lv: Word, column: int, secondary) -> tuple[str, list[str]]:
    """A card's name: the first engine's words on its name line. Where it found none, or is unsure, the Cyrillic engine
    reads the card too and the more confident reading wins; else square symbols."""
    height, width = frame.shape[:2]
    left, right = COLUMNS[column]
    top, bottom = lv.cy - NAME_ABOVE * height, lv.cy - NAME_BELOW * height

    def line_of(found: list[Word]) -> tuple[str, float]:
        line = [w for w in found if top <= w.cy <= bottom and w.score >= MIN_SCORE and not LV.search(w.text)]
        line = [w for w in line if left * width <= w.cx <= right * width]
        text = " ".join(w.text for w in sorted(line, key=lambda w: w.x0)).strip()
        return text, min((w.score for w in line), default=0)

    name, score = line_of(words)
    if name and score >= C.MIN_CONFIDENCE:
        return name, []
    if secondary is not None:  # the whole card, not just the line: the model needs the context to find the text
        card = secondary.read(
            frame, (left, (lv.cy - CARD_ABOVE * height) / height, right, (lv.cy + CARD_BELOW * height) / height)
        )
        again, again_score = line_of(card)
        if again and again_score > score:
            return again, ["second engine"]
    if name:
        return name, ["low confidence"]
    squares = symbols.read_squares_in(
        frame, round(top), round(bottom), round(left * width), round(right * width), round(ICON * width)
    )
    return (squares, []) if squares else ("?", ["no name"])


def parse_page(frame: np.ndarray, words: list[Word], secondary=None) -> Page:
    height, width = frame.shape[:2]
    top, bottom = CONTENT_TOP * height, CONTENT_BOTTOM * height
    headers = []
    for word in words:
        match = HEADER.match(word.text.strip())
        if match and word.cx < 0.2 * width and top < word.cy < 0.95 * height:
            count = [c for c in words if COUNT.match(c.text.strip()) and abs(c.cy - word.cy) < 0.015 * height]
            total = int(COUNT.match(count[0].text.strip()).group(2)) if count else None
            headers.append(Header(int(match.group(1)), total, word.cy, is_collapsed(frame, word.cy)))
    cards = []
    for lv in [w for w in words if LV.search(w.text)]:
        column = 0 if lv.cx < width / 2 else 1
        card_top, card_bottom = lv.cy - CARD_ABOVE * height, lv.cy + CARD_BELOW * height
        if card_top < top or card_bottom > bottom:
            continue  # cut off by the pinned part or the screen's bottom: read on another page
        left, right = COLUMNS[column]
        power = [
            w
            for w in words
            if POWER.match(w.text.strip()) and left * width <= w.cx <= right * width and lv.cy < w.cy < card_bottom
        ]
        name, flags = read_name(frame, words, lv, column, secondary)
        cards.append(Card(name, int(power[0].text.replace(",", "")) if power else None, lv.cy, column, flags))
    cards.sort(key=lambda card: (round(card.cy / (0.03 * height)), card.column))  # row by row, left to right
    named = [w for w in words if 0.38 * width < w.cx < 0.7 * width and 0.195 * height < w.cy < 0.24 * height]
    leader = " ".join(w.text for w in named if not HEADER.match(w.text.strip()))  # not the R5 badge beside it
    total = [
        w for w in words if w.text.strip().isdigit() and w.cx > 0.8 * width and 0.08 * height < w.cy < 0.14 * height
    ]
    return Page(headers, cards, leader.strip(), int(total[0].text) if total else None)


class MemberScanner:
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

    def page(self, frame: np.ndarray) -> Page:
        return parse_page(frame, self.primary.read(frame), self.secondary)

    def push(self, frame: np.ndarray, down: bool = False) -> tuple[np.ndarray, bool]:
        """Swipes the list (down: towards the top) from one start height after the other until it moves; the new frame
        and whether it moved. It did not move at all only when every start was tried: the end of the list."""
        height, width = frame.shape[:2]
        after = frame
        for start in STARTS:
            end = start - SWIPE_LENGTH
            y0, y1 = (end, start) if down else (start, end)
            self.device.swipe(SWIPE_X * width, y0 * height, SWIPE_X * width, y1 * height, 500)
            after = self.device.settled()
            if moved(frame, after):
                return after, True
        return after, False

    def to_top(self) -> np.ndarray:
        """Fast swipes from every start height in turn, then one look at the screen: nothing is read on the way up. A
        batch that moved nothing means every start was tried: the top."""
        frame = self.device.settled()
        height, width = frame.shape[:2]
        x = SWIPE_X * width
        for _ in range(MAX_UP_BATCHES):
            for start in STARTS:
                self.device.swipe(x, (start - SWIPE_LENGTH) * height, x, start * height, C.FLING_MS)
            after = self.device.settled()
            if not moved(frame, after):
                return after
            frame = after
        return frame

    def scan(self) -> MemberScan:
        frame = self.to_top()
        height, width = frame.shape[:2]
        found: dict[int, dict] = {}
        names: set[str] = set()
        powers: set[int | None] = set()
        group_totals: dict[int, int] = {}
        warnings: list[str] = []
        expanded: list[str] = []
        leader, total, group = "", None, None
        complete = False
        for _ in range(MAX_PAGES):
            if self.should_stop():
                break
            page = self.page(frame)
            leader, total = leader or page.leader, total or page.total
            # a folded group is told by its arrow, not by its count (which the OCR may misread)
            folded = [h for h in page.headers if h.collapsed and len(expanded) < MAX_EXPANDS]
            if folded:  # open it and read the page again: its cards are below
                self.device.tap(ARROW_X * width, folded[0].cy)
                expanded.append(f"R{folded[0].group}")
                self.progress(f"Opened the folded group R{folded[0].group}.")
                frame = self.device.settled()
                continue
            for item in sorted([*page.headers, *page.cards], key=lambda i: i.cy):
                if isinstance(item, Header):
                    group = item.group
                    if item.total:
                        group_totals[group] = item.total
                    continue
                # the same card seen on two pages: the same name, or (a name read twice differently) the same power
                if (item.name != "?" and item.name in names) or (item.power is not None and item.power in powers):
                    continue
                names.add(item.name)
                powers.add(item.power)
                found[len(found)] = {"name": item.name, "rank": f"R{group}"}
                if item.flags and item.flags != ["low confidence"]:
                    warnings.append(f"a card's name was read with: {', '.join(item.flags)} ({item.name})")
            self.progress(f"{len(found) + 1} members so far")
            frame, scrolled = self.push(frame)
            if not scrolled:  # the end: not a single start height moved the list
                complete = True
                break
        members = [{"name": leader or "?", "rank": "R5"}, *found.values()]
        if total is not None and len(members) != total:
            warnings.append(f"{len(members)} members read, the screen says {total}")
        for number, expected in sorted(group_totals.items(), reverse=True):
            read = sum(1 for m in members if m["rank"] == f"R{number}")
            if read != expected:
                warnings.append(f"R{number}: {read} cards read, the header says {expected}")
        return MemberScan(members, total, complete, warnings, expanded)
