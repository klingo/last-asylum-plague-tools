"""One frame of the Rank screen -> its ranking rows.

Every row card shows the rank (a medal picture for 1-3), the player's name above the alliance (`[tag]AllianceName`) and
the day's points on the right. The points are the most reliable text, so a row is anchored on them and the rest is
looked for around them. Only cards that are entirely inside the list are used; a card cut off by the column heads or by
the pinned own row (green, below the list) is read on the next page. The pinned row is returned separately as `me`.
Ranks come from the numbers shown, corrected by the cards' regular spacing (a card the OCR missed does not shift the
ranks below it); the medal rows 1-3 get theirs from the card that follows. Far down the list (about rank 105 on) the
game shows "Not ranked" instead of a number: those cards are placed by a card the earlier pages already read.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import config as C
from ocr import Word

POINTS = re.compile(r"^\d{1,3}(?:[,.' ]\d{3})*$")
ALLIANCE = re.compile(r"^\[(.*?)\]\s*(.*)$")
NAME_ABOVE, NAME_BELOW = 0.040, 0.006  # name's centre is this far (of height) above the points', alliance's below
TOLERANCE = 0.004  # of height: how far a card may reach out of the list area and still count as inside
LOOKUP = (0.2, 0.91)  # the part of the frame (of height) the OCR reads: the list and the pinned row


@dataclass
class Row:
    rank: int | None
    name: str
    alliance: str
    tag: str
    points: int
    cy: float  # the card's centre line in the frame
    confidence: float
    rank_read: int | None = None  # what the OCR saw, before the spacing corrected it
    flags: list[str] = field(default_factory=list)
    anchor: Word | None = field(default=None, repr=False)  # the points word the row hangs on

    def as_dict(self) -> dict:
        return {"rank": self.rank, "name": self.name, "alliance": self.alliance, "tag": self.tag, "points": self.points}


@dataclass
class Page:
    rows: list[Row]
    me: Row | None


def parse_points(text: str) -> int | None:
    text = text.strip()
    return int(re.sub(r"\D", "", text)) if POINTS.match(text) else None


def join(words: list[Word]) -> str:
    return " ".join(word.text for word in sorted(words, key=lambda word: word.x0)).strip()


def build_row(anchor: Word, points: int, words: list[Word], width: int, height: int) -> Row:
    near_name = [w for w in words if w.cx < C.POINTS_COLUMN[0] * width and w.cx > C.NAME_COLUMN[0] * width]
    name = [w for w in near_name if anchor.cy - NAME_ABOVE * height <= w.cy < anchor.cy - NAME_BELOW * height]
    alliance = [w for w in near_name if anchor.cy + NAME_BELOW * height < w.cy <= anchor.cy + NAME_ABOVE * height]
    rank = [w for w in words if w.cx < C.RANK_COLUMN[1] * width and abs(w.cy - anchor.cy) < 0.02 * height]
    rank_read = int(rank[0].text) if rank and rank[0].text.isdigit() else None
    split = ALLIANCE.match(join(alliance))
    tag, alliance_name = (split.group(1), split.group(2)) if split else ("", join(alliance))
    used = [anchor, *name, *alliance]
    flags = []
    if not name:
        flags.append("no name")
    if not alliance_name:
        flags.append("no alliance")
    confidence = min(word.score for word in used)
    if confidence < C.MIN_CONFIDENCE:
        flags.append(f"low confidence {confidence:.2f}")
    return Row(None, join(name), alliance_name, tag, points, anchor.cy, confidence, rank_read, flags, anchor)


def refine(row: Row, read, width: int, height: int) -> Row:
    """A row the first engine could not read well, read again by `read(region)` (the second engine) from its card.

    The better reading of name and alliance wins; the rank and the points stay as they were."""
    half = C.ROW_PITCH * height / 2
    region = (C.NAME_COLUMN[0], (row.cy - half) / height, C.NAME_COLUMN[1], (row.cy + half) / height)
    again = build_row(row.anchor, row.points, read(region), width, height)
    if again.name and (not row.name or again.confidence > row.confidence):
        again.rank, again.rank_read = row.rank, row.rank_read
        again.flags += [flag for flag in row.flags if flag.startswith("rank read")]
        return again
    return row


def parse_page(words: list[Word], width: int, height: int) -> Page:
    """The rows of a frame, top to bottom, with their ranks worked out where the numbers allow."""
    half = C.CARD_HALF * height
    top = C.LIST_TOP * height + half - TOLERANCE * height
    bottom = C.LIST_BOTTOM * height - half + TOLERANCE * height
    rows: list[Row] = []
    me: Row | None = None
    for anchor in words:
        points = parse_points(anchor.text) if anchor.cx > C.POINTS_COLUMN[0] * width else None
        if points is None:
            continue
        row = build_row(anchor, points, words, width, height)
        if anchor.cy > C.LIST_BOTTOM * height:
            me = row
            me.rank = me.rank_read
        elif top <= anchor.cy <= bottom:
            rows.append(row)
    rows.sort(key=lambda row: row.cy)
    assign_ranks(rows, C.ROW_PITCH * height)
    return Page(rows, me)


def assign_ranks(rows: list[Row], pitch: float) -> bool:
    """Ranks from the numbers the OCR read and the cards' spacing. False if no number was read on the page."""
    if not rows:
        return False
    steps = [round((row.cy - rows[0].cy) / pitch) for row in rows]
    votes = Counter(row.rank_read - step for row, step in zip(rows, steps) if row.rank_read is not None)
    if not votes:
        return False
    offset = votes.most_common(1)[0][0]
    for row, step in zip(rows, steps):
        row.rank = offset + step
        if row.rank_read is not None and row.rank_read != row.rank:
            row.flags.append(f"rank read as {row.rank_read}")
    return True


def number_from_overlap(rows: list[Row], known: dict[int, dict], pitch: float) -> bool:
    """Ranks for a page without a readable number: an earlier page's row with the same name and points sets them."""
    steps = [round((row.cy - rows[0].cy) / pitch) for row in rows]
    for row, step in zip(rows, steps):
        for rank, earlier in known.items():
            if earlier["name"] == row.name and earlier["points"] == row.points:
                for other, other_step in zip(rows, steps):
                    other.rank = rank + other_step - step
                return True
    return False
