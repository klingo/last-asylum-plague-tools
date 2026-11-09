"""Ground truth from a recorded game: what really lay where, frame by frame.

Tiles never move and never come back; a tile can only leave the board after it was free, and free tiles are read
reliably (bright face, full icon). So every tile that is free in some frame tells, for *all earlier frames*, that a
tile with this icon lay at this position, and stacking follows from the order: of two overlapping tiles, the one
that was free first lay on top (the other could not be free while it was there).

Tiles that never became free (the game was lost before they were uncovered) are unknown. They always lie *below*
every known tile they overlap (otherwise that tile could never have been free), so they hide nothing that is
known: the visible share of every known tile in every frame is exact.

Tiles are tracked within one segment only. A shuffle (Refresh) or a new game starts the next one. A shuffle keeps
the tiles where they are and swaps their icons, so it is recognised by itself: several free tiles show another icon
on the same spot from one frame to the next. A screen without a board (a dialog) does not end a segment: the board
is usually back unchanged afterwards; it is a new game only if most free tiles are gone. A tile put back from the
tray (Recall) reappears on its old spot with its icon within a few frames; it is the same tile again, not a new one.

Cards parked above the tray (Remove) appear in the middle of a game; they lie on the board from then on only. A
second Remove puts 3 new cards a bit higher on the parked ones, which hides them (they are not gone) until the card
on top is used.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

import vision as V

SAME_TILE = 6.0  # px: a free tile in the next frame within this distance is the same tile
SHUFFLE_MIN = 4  # free tiles that change icon on the spot between two frames ...
SHUFFLE_SHARE = 0.5  # ... and their share of the free tiles there before: the board was shuffled (Refresh). A Remove
# that stacks 3 cards on the 3 parked ones changes 3 spots only, and is no shuffle
RECALL_FRAMES = 3  # a tile back on its spot with its icon within this many frames was put back (Recall)
NEW_GAME_SHARE = 0.5  # fewer of the free tiles still there: a new game (after a dialog, or with this many ...)
NEW_GAME_MIN = 4  # ... free tiles at least without one: a tap or two never remove half of them)
PARK_ROW = 2  # new free cards in one row, with nothing taken off them: parked by a Remove
RESTACK_DY = (12.0, 30.0)  # px: Remove puts new cards this much higher (same x) on the cards parked before
STACK_REACH = 70.0  # px above a parked card in which the cards on it lie
EDGE = 3  # px around a covering tile that do not show the tile below (its outline, gaps between tiles)


@dataclass
class TruthTile:
    x: float  # ring-match corner as detected while free (exact, also off the lattice in piles), canonical px
    y: float
    kind: int | None  # the icon read while it was free (majority)
    first_free: int  # frame index (within the recording) where it is free first
    last_free: int
    removed: int | None  # first frame in which it is gone, None if still there at the end of its segment
    segment: int
    kinds: list[int | None] = field(default_factory=list)
    appeared: int | None = None  # put down in the middle of the game (Remove): the frame from which it is there

    def present(self, k: int) -> bool:
        return (self.appeared is None or k >= self.appeared) and (self.removed is None or k < self.removed)

    def rect(self) -> tuple[int, int, int, int]:
        return V.footprint(self.x, self.y)


def overlaps(a: TruthTile, b: TruthTile) -> bool:
    ax0, ay0, ax1, ay1 = a.rect()
    bx0, by0, bx1, by1 = b.rect()
    return ax0 < bx1 - 4 and bx0 < ax1 - 4 and ay0 < by1 - 4 and by0 < ay1 - 4


def in_pile(t: TruthTile, tiles: list[TruthTile]) -> bool:
    """Part of a pile (tiles stacked a few px apart, sideways or vertically, outside the lattice)? Board neighbours
    are half a tile apart; cards a Remove stacks on parked ones lie 20 px apart."""
    return any(u is not t and u.segment == t.segment and (abs(u.y - t.y) <= 3 and 4 <= abs(u.x - t.x) <= 16
                                                          or abs(u.x - t.x) <= 3 and 4 <= abs(u.y - t.y) <= 16) for u in tiles)


def above(a: TruthTile, b: TruthTile) -> bool:
    """Was `a` on top of `b`? Only meaningful for overlapping tiles of the same segment. Cards put down later
    (Remove) lie on everything that was there before."""
    if (a.appeared or -1) != (b.appeared or -1):
        return (a.appeared or -1) > (b.appeared or -1)
    return a.first_free < b.first_free


@dataclass
class GameTruth:
    frames: list[str]
    segments: list[int | None]  # per frame: segment id, None = no board in that frame
    tiles: list[TruthTile]

    def at(self, k: int) -> list[TruthTile]:
        """Known tiles on the board in frame k."""
        seg = self.segments[k]
        return [t for t in self.tiles if t.segment == seg and t.present(k)] if seg is not None else []

    def covering(self, t: TruthTile, k: int) -> list[TruthTile]:
        """Known tiles lying on top of t in frame k."""
        return [u for u in self.at(k) if u is not t and overlaps(u, t) and above(u, t)]

    def visible_share(self, t: TruthTile, k: int) -> float:
        """Share of t's footprint not hidden by known tiles above it in frame k (exact, see module doc)."""
        x0, y0, x1, y1 = t.rect()
        mask = np.ones((y1 - y0, x1 - x0), bool)
        e = EDGE  # a covering tile's outline and the 1 px gaps between neighbours are no view of the tile below
        for u in self.covering(t, k):
            ux0, uy0, ux1, uy1 = u.rect()
            mask[max(0, uy0 - y0 - e) : max(0, uy1 - y0 + e), max(0, ux0 - x0 - e) : max(0, ux1 - x0 + e)] = False
        return float(mask.mean())


def _same(t: TruthTile, f: tuple[float, float, int | None]) -> bool:
    """Is the free tile f (x, y, kind) read in a frame tile t on its spot? (Another icon there: the tile below.)"""
    same_icon = f[2] is None or t.kinds[-1] is None or f[2] == t.kinds[-1]
    return abs(f[0] - t.x) <= SAME_TILE and abs(f[1] - t.y) <= SAME_TILE and same_icon


def build(frames: list[str], free_per_frame: list[list[tuple[float, float, int | None]] | None],
          breaks: set[int] | None = None) -> GameTruth:
    """`free_per_frame[k]`: the free tiles (x, y, kind) read in frame k, None if no board; `breaks`: frames that
    start a new segment for sure (shuffles and new games are recognised without)."""
    breaks = set(breaks or ())
    tiles: list[TruthTile] = []
    segments: list[int | None] = []
    seg, start = -1, 0
    open_: list[TruthTile] = []
    parked: list[TruthTile] = []  # parked cards hidden under newer ones (Remove)
    lone: list[TruthTile] = []  # tiles that showed up free on their own: parked alone, or not seen free before
    for k, free in enumerate(free_per_frame):
        if free is None:  # a dialog or another screen: the board can come back as it was
            segments.append(None)
            continue
        same_spot = [(t, f) for t in open_ for f in free
                     if abs(f[0] - t.x) <= SAME_TILE and abs(f[1] - t.y) <= SAME_TILE and None not in (f[2], t.kinds[-1])]
        changed_icons = sum(f[2] != t.kinds[-1] for t, f in same_spot)
        if changed_icons >= SHUFFLE_MIN and changed_icons >= SHUFFLE_SHARE * len(same_spot):
            breaks.add(k)  # shuffled: what is known from now on says nothing about the boards before
        gap = bool(segments) and segments[-1] is None
        continued = sum(any(_same(t, f) for f in free) for t in open_)
        if continued < NEW_GAME_SHARE * len(open_) and (gap or len(open_) >= NEW_GAME_MIN) or gap and not open_:
            breaks.add(k)  # most free tiles are gone: another game
        if k in breaks or seg < 0:
            for t in open_:
                t.removed = None  # the segment ends with them still on the board
            seg, start, open_, parked = seg + 1, k, [], []
        segments.append(seg)
        still = []
        unmatched = list(free)
        for t in open_:
            match = next((f for f in unmatched if _same(t, f)), None)
            if match is None:
                if any(abs(f[0] - t.x) <= SAME_TILE and RESTACK_DY[0] <= t.y - f[1] <= RESTACK_DY[1] for f in unmatched):
                    parked.append(t)  # a card put down on this parked one: it is hidden, not gone
                else:
                    t.removed = k  # it was free in the previous frame and is gone now: tapped
            else:
                unmatched.remove(match)
                t.last_free = k
                t.kinds.append(match[2])
                still.append(t)
        new: list[TruthTile] = []
        for x, y, kind in unmatched:
            back = next((t for t in parked if abs(x - t.x) <= SAME_TILE and abs(y - t.y) <= SAME_TILE and kind == t.kinds[-1]), None)
            if back is not None:  # the card on this parked one was used: it shows again
                parked.remove(back)
            else:
                back = next((t for t in tiles if t.segment == seg and t.removed is not None and k - t.removed <= RECALL_FRAMES
                             and abs(x - t.x) <= SAME_TILE and abs(y - t.y) <= SAME_TILE and kind == t.kinds[-1]), None)
            if back is not None:  # put back from the tray: the same tile, it never really left the board
                back.removed, back.last_free = None, k
                back.kinds.append(kind)
                still.append(back)
                continue
            t = TruthTile(x, y, None, k, k, None, seg, [kind])
            if k > start and not any(u.segment == seg and u.removed is not None and k - u.removed <= RECALL_FRAMES
                                     and u.appeared is None and u not in lone and overlaps(u, t) for u in tiles):
                new.append(t)  # nothing taken off it just now: put down just now (or missed before). (A tile that
                # was taken long ago uncovers nothing now, e.g. a used parked card: it leaves an empty spot)
            tiles.append(t)
            still.append(t)
        for t in new:  # Remove parks a row of cards; a single one is more likely a tile not seen free before
            if any(abs(t.x - p.x) <= SAME_TILE and RESTACK_DY[0] <= p.y - t.y <= RESTACK_DY[1] for p in parked) or sum(
                abs(u.y - t.y) <= 3 for u in new
            ) >= PARK_ROW:
                t.appeared = k
            else:
                lone.append(t)
        for p in [p for p in parked if not any(abs(u.x - p.x) <= SAME_TILE and 0 < p.y - u.y <= STACK_REACH
                                                for u in still + parked)]:
            parked.remove(p)  # nothing on it any more, and it does not show: it was used right after
            p.removed = k
        open_ = still
    rows = {(t.segment, round(t.y)) for t in tiles if t.appeared is not None}
    for t in lone:  # in the row where cards were parked (a Remove with one card in the tray): parked, too
        if any(seg == t.segment and abs(t.y - y) <= 3 for seg, y in rows):
            t.appeared = t.first_free
    for t in tiles:
        known = [k for k in t.kinds if k is not None]
        t.kind = max(set(known), key=known.count) if known else None
    return GameTruth(frames, segments, tiles)
