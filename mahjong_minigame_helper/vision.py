"""Mahjong minigame vision: finds the tiles on a screenshot of the game area.

Everything works in a canonical space where the game area is CANON_W pixels wide (the capture is rescaled once, so
all constants below are in canonical pixels). The game-specific ones (colours, tile geometry, tray) are the
Halloween Ball values; `game_profile.activate` replaces them with another profile's.

The board sits on a half-tile lattice: a tile covers 2x2 lattice cells and tiles of different layers are offset by
whole cells. It is the same lattice in every stage (only the tiles on it differ), so it is learned once from the
recordings (`train`, the profile's `grid`) and only moved, never stretched, on a board; fitting it anew from the few
free tiles of each board let its pitch wobble by half a pixel, i.e. several pixels across the board. A *free* tile is drawn bright (lavender face); a covered tile is drawn with a grey face and is partly
hidden by the tiles above it. Free tiles are found by matching the ring of face colour along a tile's border; covered
tiles are found by "peeling": the best explained candidate (dark outline along its visible border, grey face inside)
is accepted, its footprint stops counting as visible for the rest, and the search repeats for the layer below.
That order is the layer order, which gives the cover graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

CANON_W = 760

FACE_FREE = np.array((213, 217, 247), np.float32)  # RGB of a free tile's face
FACE_DIM = np.array((123, 126, 139), np.float32)  # RGB of a covered tile's face
FACE_TOL = 14
LIP_DIM = np.array((95, 93, 126), np.float32)  # RGB of the shaded band along the bottom of a covered tile
DIM_FACTOR = FACE_DIM / FACE_FREE  # how much the game darkens a covered tile

PITCH_X = 101.0  # tile-to-tile distance, free tiles side by side
PITCH_Y = 106.7
TILE_W = 100  # footprint of one tile, outline included (starts 3 px before the ring-match corner)
TILE_H = 106
RING_W, RING_H = 94, 92  # face box used for the free-tile ring match
RING_INSET = (2, 9)  # the ring is the face box between these insets
CORNER_DX, CORNER_DY = 3, 3  # a tile's footprint starts this far left / above its ring-match corner
TRAY_COLOR = np.array((123, 65, 57), np.float32)  # RGB of the tray bar
FREE_MIN_SCORE = 0.68
DIM_MIN_FACE = 0.12  # share of a covered candidate's visible interior that must be grey face
DIM_MIN_EDGE = 0.78  # share of its visible border that must show an outline (0.8 made a tile at 0.798 a coin flip)
DIM_MIN_VISIBLE = 0.2  # share of a covered candidate's interior that must be visible
CROSS_MIN_SPAN = 20  # visible px along a foreign border before it can be judged
CROSS_SHARE = 0.85  # share of that span the border must fill
BLOB = 9  # px: dark areas thicker than this are icon bodies, not tile borders
LINE_RUN = 22  # straight outline run (px) that counts as a tile border
STACK_MIN_PX = 15  # border px that must be visible to tell which of two overlapping tiles is on top
STACK_MIN_SHARE = 0.6  # share of them that must be outline
LIP_MIN_PX = 20  # lip pixels that must be visible to judge
LIP_SHARE = 0.6  # share of them with the lip colour for a visible lip
DIM_MIN_SEGMENT = 24  # px of visible border needed on both axes (pins the position down)
OUTLINE_MAX_V = 112  # brightness below which a pixel is outline (face is >= 123)


def to_canon(img_bgr: np.ndarray) -> tuple[np.ndarray, float]:
    """Rescale a capture to CANON_W wide. Returns (image, scale = canonical px per capture px)."""
    scale = CANON_W / img_bgr.shape[1]
    if abs(scale - 1) < 1e-3:
        return img_bgr, 1.0
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(img_bgr, None, fx=scale, fy=scale, interpolation=interp), scale


def _color_mask(rgb: np.ndarray, color: np.ndarray, tol: int) -> np.ndarray:
    return np.abs(rgb.astype(np.float32) - color).max(axis=2) <= tol


@dataclass
class Tile:
    """One tile on the board. (i, j) are lattice cells; (x, y) the top-left of the footprint in canonical px."""

    i: int
    j: int
    x: float
    y: float
    free: bool
    kind: int | None = None  # kind id, None = unknown
    rx: float | None = None  # free tiles: ring-match corner as detected (piles put tiles off the lattice)
    ry: float | None = None
    score: float = 0.0
    kind_conf: float = 0.0
    pile: bool = False  # behind the front tile of a pile (shares its lattice cell; icon unknown)
    parked: bool = False  # put aside above the tray by a Remove (see board.mark_parked)
    covered_by: list[int] = field(default_factory=list)  # indices of tiles above this one (best guess)
    maybe_covered_by: list[int] = field(default_factory=list)  # ... plus those not proven to be below it


@dataclass
class Lattice:
    x0: float
    y0: float
    hx: float = PITCH_X / 2
    hy: float = PITCH_Y / 2

    def cell(self, x: float, y: float) -> tuple[int, int]:
        return round((x - self.x0) / self.hx), round((y - self.y0) / self.hy)

    def pos(self, i: int, j: int) -> tuple[float, float]:
        return self.x0 + i * self.hx, self.y0 + j * self.hy


FREE_OVERLAP = 0.25  # share of a found free tile that a weaker match may overlap


def find_free_tiles(img_bgr: np.ndarray, min_score: float = FREE_MIN_SCORE) -> list[tuple[int, int, float]]:
    """Top-left corners (x, y, score) of every bright tile, via the ring of face colour along its border."""
    rgb = img_bgr[:, :, ::-1]
    face = _color_mask(rgb, FACE_FREE, FACE_TOL).astype(np.float32)
    ring = np.zeros((RING_H, RING_W), np.float32)
    a, b = RING_INSET
    ring[a : RING_H - a, a : RING_W - a] = 1
    ring[b : RING_H - b, b : RING_W - b] = 0
    nms = int(0.42 * RING_W)  # suppression radius: no two tiles closer than this
    score = cv2.matchTemplate(face, ring, cv2.TM_CCORR) / ring.sum()
    found = []
    while True:
        _, best, _, (x, y) = cv2.minMaxLoc(score)
        if best < min_score:
            break
        overlap = max((max(0, RING_W - abs(x - fx)) * max(0, RING_H - abs(y - fy)) for fx, fy, _ in found), default=0)
        if overlap <= FREE_OVERLAP * RING_W * RING_H:  # two free tiles never overlap (one would lie on the other): a
            found.append((x, y, float(best)))  # weaker match straddling two tiles that touch (the parked row) is none
        score[max(0, y - nms) : y + nms, max(0, x - nms) : x + nms] = 0
    return sorted(found, key=lambda f: (f[1], f[0]))


OFF_LATTICE = 6.0  # px: a free tile further than this from the lattice is not on it (piles, parked cards)
GRID: tuple[float, float, float, float] | None = None  # the profile's lattice (x0, y0, hx, hy), learned by `train`
GRID_NEAR = 3.0  # px: free tiles this close to the profile's lattice tell its shift on a board (they lie within 1-2)
GRID_FIT = (3, 0.5)  # free tiles on the profile's lattice that show it fits: this many, or this share of them (a
# wrong lattice meets a tile by chance 1 time in 20; piles and parked cards lie off it by design), else fitted anew


def board_lattice(corners: list[tuple[int, int, float]]) -> tuple[Lattice, bool | None]:
    """(lattice, does the profile's fit). The profile's lattice moved by the offset its free tiles agree on (a pixel
    or so); fitted from the free tiles when the profile has none, or when it does not fit this board (False)."""
    if GRID is None:
        return fit_lattice(corners), None
    x0, y0, hx, hy = GRID
    xs = np.array([c[0] for c in corners], float)
    ys = np.array([c[1] for c in corners], float)
    rx = (xs - x0 + hx / 2) % hx - hx / 2  # each free tile's offset from the nearest lattice position
    ry = (ys - y0 + hy / 2) % hy - hy / 2
    on = (np.abs(rx) <= OFF_LATTICE) & (np.abs(ry) <= OFF_LATTICE)
    if not on.any() or (on.sum() < GRID_FIT[0] and on.sum() < GRID_FIT[1] * len(corners)):
        return fit_lattice(corners), False
    near = (np.abs(rx) <= GRID_NEAR) & (np.abs(ry) <= GRID_NEAR)  # the shift: from the tiles right on it (a pile
    near = near if near.any() else on  # card a few px off a lattice position would pull it)
    return Lattice((x0 + float(np.median(rx[near]))) % hx, (y0 + float(np.median(ry[near]))) % hy, hx, hy), True




def fit_lattice(corners: list[tuple[int, int, float]]) -> Lattice:
    """Half-tile lattice through the free tiles. The origin is reduced modulo the cell size, so a cell index means
    the same screen position in every frame."""
    xs = np.array([c[0] for c in corners], float)
    ys = np.array([c[1] for c in corners], float)

    def fit(v: np.ndarray, step: float) -> tuple[float, float]:
        o = float(v[0])
        for _ in range(3):
            o = float(np.median(v - step * np.round((v - o) / step)))
        idx = np.round((v - o) / step)
        on = np.abs(v - o - step * idx) <= OFF_LATTICE  # the front tiles of piles lie off the lattice, often at the
        idx, v = idx[on], v[on]  # far left / right, where they would tilt the pitch most
        if len(set(idx)) >= 3:  # refine the pitch when the tiles span a few cells
            slope, offset = np.polyfit(idx, v, 1)
            if abs(slope / step - 1) < 0.015:
                step, o = float(slope), float(offset)
        return o % step, step

    x0, hx = fit(xs, PITCH_X / 2)
    y0, hy = fit(ys, PITCH_Y / 2)
    return Lattice(x0, y0, hx, hy)


def footprint(x: float, y: float) -> tuple[int, int, int, int]:
    x0, y0 = int(round(x)) - CORNER_DX, int(round(y)) - CORNER_DY
    return x0, y0, x0 + TILE_W, y0 + TILE_H


def _paint(mask: np.ndarray, rect: tuple[int, int, int, int], value: bool = True, shrink: int = 0) -> None:
    x0, y0, x1, y1 = rect
    h, w = mask.shape
    mask[max(0, y0 + shrink) : max(0, min(h, y1 - shrink)), max(0, x0 + shrink) : max(0, min(w, x1 - shrink))] = value


class _DimScorer:
    """Scores a covered-tile candidate against the pixels that are still unexplained."""

    def __init__(self, img_bgr: np.ndarray):
        rgb = img_bgr[:, :, ::-1]
        self.h, self.w = img_bgr.shape[:2]
        self.rgb = rgb
        self.dim_face = _color_mask(rgb, FACE_DIM, 10)
        self.lip = _color_mask(rgb, LIP_DIM, 10)
        self.outline = img_bgr.max(axis=2) < OUTLINE_MAX_V
        # outline pixels within 3 px (perpendicular tolerance) -- for a horizontal / vertical edge sample
        self.outline_v = cv2.dilate(self.outline.astype(np.uint8), np.ones((7, 1), np.uint8)) > 0
        self.outline_h = cv2.dilate(self.outline.astype(np.uint8), np.ones((1, 7), np.uint8)) > 0
        # long straight *thin* outline runs: another tile's border. A dark icon body (spider, cauldron) is a blob,
        # not a line, so whatever survives a 9 px opening is taken out first.
        o8 = self.outline.astype(np.uint8)
        blob = cv2.dilate(cv2.morphologyEx(o8, cv2.MORPH_OPEN, np.ones((BLOB, BLOB), np.uint8)), np.ones((5, 5), np.uint8))
        thin = o8 & (1 - blob)
        self.line_h = cv2.morphologyEx(thin, cv2.MORPH_OPEN, np.ones((1, LINE_RUN), np.uint8)) > 0
        self.line_v = cv2.morphologyEx(thin, cv2.MORPH_OPEN, np.ones((LINE_RUN, 1), np.uint8)) > 0
        # straight borders with the same 3 px tolerance as above, for the stacking test
        self.border_h = cv2.dilate(self.line_h.astype(np.uint8), np.ones((7, 1), np.uint8)) > 0
        self.border_v = cv2.dilate(self.line_v.astype(np.uint8), np.ones((1, 7), np.uint8)) > 0

    def crossing(self, rect: tuple[int, int, int, int], seen: np.ndarray) -> bool:
        """Does another tile's border run through the visible interior? Tiles are offset by whole lattice cells, so a
        foreign border can only run through the middle of the footprint, and it spans everything visible there
        (an icon's dark stroke does not)."""
        x0, y0, x1, y1 = rect
        cx, cy = x0 + int(PITCH_X / 2), y0 + int(PITCH_Y / 2)
        vis_v = ~seen[y0 + 8 : y1 - 8, cx - 3 : cx + 4]
        vis_h = ~seen[cy - 3 : cy + 4, x0 + 8 : x1 - 8]
        run_v = (self.line_v[y0 + 8 : y1 - 8, cx - 3 : cx + 4] & vis_v).any(axis=1).sum()
        run_h = (self.line_h[cy - 3 : cy + 4, x0 + 8 : x1 - 8] & vis_h).any(axis=0).sum()
        rows_v = vis_v.any(axis=1).sum()
        cols_h = vis_h.any(axis=0).sum()
        return (rows_v >= CROSS_MIN_SPAN and run_v >= CROSS_SHARE * rows_v) or (
            cols_h >= CROSS_MIN_SPAN and run_h >= CROSS_SHARE * cols_h
        )

    def score(
        self, rect: tuple[int, int, int, int], covered: np.ndarray, seen: np.ndarray, check_crossing: bool = True
    ) -> tuple[float, float, bool]:
        """(face share of the visible interior, outline share of the visible border, border pins the position)."""
        x0, y0, x1, y1 = rect
        if x0 < 0 or y0 < 0 or x1 > self.w or y1 > self.h:
            return 0.0, 0.0, False
        interior = ~seen[y0 + 8 : y1 - 8, x0 + 8 : x1 - 8]
        n = interior.sum()
        if n < DIM_MIN_VISIBLE * interior.size:
            return 0.0, 0.0, False
        if check_crossing and self.crossing(rect, seen):
            return 0.0, 0.0, False
        face = float((self.dim_face[y0 + 8 : y1 - 8, x0 + 8 : x1 - 8] & interior).sum() / n)
        hit = tot = 0
        seg = {"h": 0, "v": 0}
        edges = (
            ("h", self.outline_v[y0 + 1, x0 + 8 : x1 - 8], covered[y0 + 1, x0 + 8 : x1 - 8]),
            ("h", self.outline_v[y1 - 2, x0 + 8 : x1 - 8], covered[y1 - 2, x0 + 8 : x1 - 8]),
            ("v", self.outline_h[y0 + 8 : y1 - 8, x0 + 1], covered[y0 + 8 : y1 - 8, x0 + 1]),
            ("v", self.outline_h[y0 + 8 : y1 - 8, x1 - 2], covered[y0 + 8 : y1 - 8, x1 - 2]),
        )
        for axis, line, cov in edges:
            vis = ~cov
            n_vis = int(vis.sum())
            tot += n_vis
            seg[axis] += n_vis
            hit += int((line & vis).sum())
        if tot == 0:
            return face, 0.0, False
        return face, hit / tot, min(seg.values()) >= DIM_MIN_SEGMENT


def find_dim_tiles(
    img_bgr: np.ndarray,
    lattice: Lattice,
    free: list[Tile],
    region: tuple[int, int, int, int],
    existing: list[Tile] | None = None,
    lenient: bool = False,
    scorer: _DimScorer | None = None,
) -> list[Tile]:
    """Peel covered tiles layer by layer. Returned in acceptance order (top layer first); `covered_by` is filled
    with indices into `free + result`. `existing` are covered tiles already accepted (kept as they are, and
    counted as covering what they cover); the peel then only looks for further tiles. `lenient` does not reject
    a candidate because a border runs through it: a tile showing one quarter only is bounded by its neighbours'
    outlines, so the caller must verify such tiles another way (by reading their icon)."""
    scorer = scorer or _DimScorer(img_bgr)
    covered = np.zeros(img_bgr.shape[:2], bool)  # footprints shrunk: their border still counts as visible
    seen = np.zeros(img_bgr.shape[:2], bool)  # full footprints
    for t in free:
        _paint(covered, footprint(t.x, t.y), shrink=3)
        _paint(seen, footprint(t.x, t.y), shrink=-3)
    result: list[Tile] = list(existing or [])
    for t in result:
        _paint(covered, footprint(t.x, t.y), shrink=3)
        _paint(seen, footprint(t.x, t.y), shrink=-3)
    taken = {(t.i, t.j) for t in free + result}
    rx0, ry0, rx1, ry1 = region
    i_lo, j_lo = lattice.cell(rx0, ry0)
    i_hi, j_hi = lattice.cell(rx1, ry1)
    while True:
        best = None
        for i in range(i_lo - 2, i_hi + 1):
            for j in range(j_lo - 2, j_hi + 1):
                if (i, j) in taken:
                    continue
                x, y = lattice.pos(i, j)
                rect = footprint(x, y)
                if rect[0] < rx0 - 4 or rect[1] < ry0 - 4 or rect[2] > rx1 + 4 or rect[3] > ry1 + 4:
                    continue
                face, edge, pinned = scorer.score(rect, covered, seen, check_crossing=not lenient)
                if face < DIM_MIN_FACE or not pinned or edge < DIM_MIN_EDGE:
                    continue
                s = edge + face
                if best is None or s > best[0]:
                    best = (s, i, j, x, y, edge)
        if best is None:
            break
        s, i, j, x, y, edge = best
        result.append(Tile(i, j, x, y, False, score=edge))
        taken.add((i, j))
        _paint(covered, footprint(x, y), shrink=3)
        _paint(seen, footprint(x, y), shrink=-3)
    assign_stacking(free + result, len(free), img_bgr, scorer)
    return result


def assign_stacking(tiles: list[Tile], n_free: int, img_bgr: np.ndarray, scorer: _DimScorer | None = None) -> None:
    """Fill `covered_by` / `maybe_covered_by` of the covered tiles (`tiles[n_free:]`, in peel order)."""
    scorer = scorer or _DimScorer(img_bgr)
    free_cover = np.zeros(img_bgr.shape[:2], bool)
    for t in tiles[:n_free]:
        _paint(free_cover, footprint(t.x, t.y))
    for n in range(n_free, len(tiles)):
        t = tiles[n]
        proven: list[int] = []  # the pixels show that this tile lies above t
        unknown: list[int] = []  # overlaps t, but nothing visible says which of the two is on top
        for m, u in enumerate(tiles):
            if m == n or abs(u.i - t.i) >= 2 or abs(u.j - t.j) >= 2:
                continue
            verdict = _is_above(u, t, tiles, scorer, free_cover)
            if verdict is True:
                proven.append(m)
            elif verdict is None:
                unknown.append(m)
        # A covered tile needs at least one coverer, no more. Where the order is unknowable (often because the
        # overlap lies under a free tile), guess "found earlier is above" only if nothing proven covers the tile.
        t.covered_by = sorted(proven or [m for m in unknown if m < n])
        t.maybe_covered_by = sorted(proven + unknown)


def _edge_evidence(top: Tile, under: Tile, scorer: _DimScorer, blocked: np.ndarray) -> tuple[int, int]:
    """(border px, sampled px) along the borders of `top` that run through the face of `under`. Only straight
    outline runs count, a dark icon stroke is not a border."""
    ax0, ay0, ax1, ay1 = footprint(top.x, top.y)
    bx0, by0, bx1, by1 = footprint(under.x, under.y)
    hit = tot = 0
    y_lo, y_hi, x_lo, x_hi = max(ay0, by0) + 8, min(ay1, by1) - 8, max(ax0, bx0) + 8, min(ax1, bx1) - 8
    for x in (ax0 + 1, ax1 - 2):  # vertical borders strictly inside the other footprint
        if bx0 + 4 < x < bx1 - 4 and y_hi > y_lo:
            vis = ~blocked[y_lo:y_hi, x]
            tot += int(vis.sum())
            hit += int((scorer.border_v[y_lo:y_hi, x] & vis).sum())
    for y in (ay0 + 1, ay1 - 2):
        if by0 + 4 < y < by1 - 4 and x_hi > x_lo:
            vis = ~blocked[y, x_lo:x_hi]
            tot += int(vis.sum())
            hit += int((scorer.border_h[y, x_lo:x_hi] & vis).sum())
    return hit, tot


def _lip_box(t: Tile) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = footprint(t.x, t.y)
    return x0 + 12, y1 - 12, x1 - 12, y1 - 5


def _lip_verdict(t: Tile, u: Tile, tiles: list[Tile], scorer: _DimScorer, free_cover: np.ndarray) -> bool | None:
    """Is `t` above `u`, judging by the shaded lip along t's bottom edge where u overlaps it? A visible lip means
    nothing covers that part of t; a hidden lip with `u` as the only tile there means u does. None = no verdict."""
    bx0, by0, bx1, by1 = _lip_box(t)
    ux0, uy0, ux1, uy1 = footprint(u.x, u.y)
    x0, y0, x1, y1 = max(bx0, ux0), max(by0, uy0), min(bx1, ux1), min(by1, uy1)
    if x1 - x0 < 10 or y1 <= y0:
        return None
    region = ~free_cover[y0:y1, x0:x1]
    n = int(region.sum())
    if n < LIP_MIN_PX:
        return None
    share = (scorer.lip[y0:y1, x0:x1] & region).sum() / n
    if share >= LIP_SHARE:
        return True
    if share <= 1 - LIP_SHARE:
        others = [w for w in tiles if w is not t and w is not u and _overlaps_box(w, (x0, y0, x1, y1))]
        if not others:
            return False
    return None


def _overlaps_box(t: Tile, box: tuple[int, int, int, int]) -> bool:
    x0, y0, x1, y1 = footprint(t.x, t.y)
    return x0 < box[2] - 4 and x1 > box[0] + 4 and y0 < box[3] and y1 > box[1]


def _is_above(u: Tile, t: Tile, tiles: list[Tile], scorer: _DimScorer, free_cover: np.ndarray) -> bool | None:
    """Is `u` on top of `t`? Free tiles always are. Otherwise: the visible / hidden bottom lips decide; then the
    straight outline across the other tile's face. None when neither says."""
    if u.free:
        return True
    lip_t = _lip_verdict(t, u, tiles, scorer, free_cover)  # t above u?
    lip_u = _lip_verdict(u, t, tiles, scorer, free_cover)  # u above t?
    if lip_t is not None and lip_u is not None and lip_t != (not lip_u):
        lip_t = lip_u = None  # contradicting
    if lip_u is not None:
        return lip_u
    if lip_t is not None:
        return not lip_t
    hu, nu = _edge_evidence(u, t, scorer, free_cover)
    ht, nt = _edge_evidence(t, u, scorer, free_cover)
    su = hu / nu if nu >= STACK_MIN_PX else None
    st = ht / nt if nt >= STACK_MIN_PX else None
    if su is not None and su >= STACK_MIN_SHARE and (st is None or su > st + 0.2):
        return True
    if st is not None and st >= STACK_MIN_SHARE and (su is None or st > su + 0.2):
        return False
    return None


def find_tray(img_bgr: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bounding box (x0, y0, x1, y1) of the brown tray bar, or None."""
    brown = _color_mask(img_bgr[:, :, ::-1], TRAY_COLOR, 22).astype(np.uint8)
    brown = cv2.morphologyEx(brown, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(brown)
    if n < 2:
        return None
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h, area = stats[k]
    return (int(x), int(y), int(x + w), int(y + h)) if area > 0.25 * img_bgr.shape[1] * 0.6 * RING_H else None


TRAY_SLOTS = 7
TRAY_PAD = 13  # bar edge to the first tile's ring-match corner


def tray_slot(x: float, tray: tuple[int, int, int, int]) -> int:
    return round((x - (tray[0] + TRAY_PAD)) / PITCH_X)


def find_tray_tiles(img_bgr: np.ndarray, tray: tuple[int, int, int, int]) -> list[tuple[int, float, float]]:
    """(slot, x, y) of each tile in the tray, left to right."""
    x0, y0, x1, y1 = tray
    pad = 25
    strip = img_bgr[max(0, y0 - pad) : y1 + pad, x0:x1]
    found = [(tray_slot(x + x0, tray), x + x0, y + max(0, y0 - pad)) for x, y, _ in find_free_tiles(strip, 0.7)]
    return sorted(f for f in found if 0 <= f[0] < TRAY_SLOTS)


@dataclass
class Frame:
    """What one screenshot shows."""

    tiles: list[Tile]  # free tiles first, then covered ones in peel order
    tray: list[tuple[int, float, float]]  # (slot, x, y)
    tray_rect: tuple[int, int, int, int]
    lattice: Lattice | None
    image: np.ndarray  # canonical-size capture
    region: tuple[int, int, int, int] = (0, 0, 0, 0)  # where covered tiles are searched
    scorer: _DimScorer | None = None  # per-image masks, built once and shared by every pass
    grid_ok: bool | None = None  # did the profile's lattice fit (None: the profile has none)


def read_frame(img_bgr: np.ndarray, tray_rect: tuple[int, int, int, int] | None = None) -> Frame | None:
    """Locate every tile. `tray_rect` is in canonical px (auto-detected when missing). None if the board is not
    on screen."""
    img, _ = to_canon(img_bgr)
    tray_rect = tray_rect or find_tray(img)
    if tray_rect is None:
        return None
    board = img[: tray_rect[1] - 6]
    corners = find_free_tiles(board)
    tray = find_tray_tiles(img, tray_rect)
    if not corners:
        return Frame([], tray, tray_rect, None, img)
    lat, grid_ok = board_lattice(corners)
    free = []
    for x, y, score in corners:
        i, j = lat.cell(x, y)
        fx, fy = lat.pos(i, j)
        free.append(Tile(i, j, fx, fy, True, score=score, rx=x, ry=y))
    top = int(0.11 * img.shape[0])
    region = (0, top, img.shape[1], tray_rect[1] - 6)
    scorer = _DimScorer(board)
    covered = find_dim_tiles(board, lat, free, region, scorer=scorer)
    return Frame(free + covered, tray, tray_rect, lat, img, region, scorer, grid_ok)


PILE_STEP = (6, 15)  # px between the edges of neighbouring tiles in a pile (reference tile size)
PILE_MAX = 14  # tiles behind one front tile at most
PILE_LINE = 0.6  # share of a strip's height its edge line must cover
PILE_MIN = 1  # cards behind a front tile needed to call it a pile (2 lost ~600 real pile cards of 23k on the recordings
# to drop 0.1 false ones per board)


def find_piles(frame: Frame) -> list[tuple[int, list[tuple[float, float]]]]:
    """Piles: tiles stacked a few px apart behind a free front tile, each showing only a narrow strip with its own
    straight edge line. They fan out sideways (edges to the left / right of the front tile) or, lower on the board,
    vertically (edges below / above it). Returns (index of the front tile, ring-match corners of the tiles behind
    it, nearest first). Board neighbours lie half a tile away, so their edges are never within PILE_STEP."""
    sc = frame.scorer
    if sc is None:
        return []
    h, w = sc.line_v.shape
    s = PITCH_X / 101.0
    lo, hi = max(3, round(PILE_STEP[0] * s)), round(PILE_STEP[1] * s)
    rects = [footprint(*((u.rx, u.ry) if u.rx is not None else (u.x, u.y))) for u in frame.tiles]

    def border_of_another(n: int, axis: str, c: int, span: slice) -> bool:
        """Is the line at c the outline of another known tile right beside (a neighbour about a tile away)? The
        cards of the pile itself lie a few px behind the front tile, and the peel sometimes takes their strips for a
        covered tile half a tile off: neither counts."""
        fx0, fy0, _, _ = rects[n]
        for m, (ux0, uy0, ux1, uy1) in enumerate(rects):
            if m == n or (abs(ux0 - fx0) < 0.8 * TILE_W if axis == "x" else abs(uy0 - fy0) < 0.8 * TILE_H):
                continue
            a0, a1, e0, e1 = (uy0, uy1, ux0 + 1, ux1 - 2) if axis == "x" else (ux0, ux1, uy0 + 1, uy1 - 2)
            if min(a1, span.stop) - max(a0, span.start) > 0.5 * (span.stop - span.start) and min(abs(c - e0), abs(c - e1)) <= 3:
                return True
        return False

    out = []
    for n, t in enumerate(frame.tiles):
        if not t.free:
            continue
        x = t.rx if t.rx is not None else t.x
        y = t.ry if t.ry is not None else t.y
        x0, y0, x1, y1 = footprint(x, y)
        rows = slice(max(0, y0 + 12), min(h, y1 - 12))
        cols = slice(max(0, x0 + 12), min(w, x1 - 12))
        if rows.stop - rows.start < 20 or cols.stop - cols.start < 20:
            continue
        # (axis, direction, the front tile's own outline): sideways the edges are vertical lines, else horizontal
        for axis, direction, start in (("x", -1, x0 + 1), ("x", 1, x1 - 2), ("y", -1, y0 + 1), ("y", 1, y1 - 2)):
            size = w if axis == "x" else h
            prev, edges = start, []
            while len(edges) < PILE_MAX:
                nxt = None
                for d in range(lo, hi + 1):
                    c = prev + direction * d
                    if c < 1 or c >= size - 1:
                        break
                    if axis == "x":
                        found = sc.line_v[rows, c - 1 : c + 2].any(axis=1).mean() >= PILE_LINE
                    else:
                        found = sc.line_h[c - 1 : c + 2, cols].any(axis=0).mean() >= PILE_LINE
                    if found and not border_of_another(n, axis, c, rows if axis == "x" else cols):
                        nxt = c
                        break
                if nxt is None:
                    break
                edges.append(nxt)
                prev = nxt
            if len(edges) < PILE_MIN:
                continue
            if axis == "x":  # left edges (direction -1) or right edges of the tiles behind
                behind = [((c - 1 if direction < 0 else c + 2 - TILE_W) + CORNER_DX, y) for c in edges]
            else:  # top edges or bottom edges
                behind = [(x, (c - 1 if direction < 0 else c + 2 - TILE_H) + CORNER_DY) for c in edges]
            out.append((n, behind))
    return out
