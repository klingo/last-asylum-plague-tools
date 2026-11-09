"""The mental map: reads a frame, remembers what earlier frames showed, asks the solver and builds the drawing.

A frame (`vision.read_frame`) gives the tiles with their cover relations. Memory keeps what a single frame can
lose: the kind of a tile whose icon is currently too hidden to read is taken from an earlier frame (tiles only
ever get more visible, so an old reading stays valid), and a new stage (most tiles at positions never seen) wipes it.
Cards parked above the tray (Remove) that a later Remove hides under new ones are kept, with their icons.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field

import numpy as np

import kinds as K
import solver as S
import vision as V

NEW_STAGE_MIN = 8  # unseen positions needed to call a frame a new stage ...
NEW_STAGE_SHARE = 0.5  # ... and their share of all tiles
SHUFFLE_MIN = 4  # free tiles that show another icon on the same spot than a frame ago ...
SHUFFLE_SHARE = 0.5  # ... and their share of those spots: the board was shuffled (a Remove changes 3 spots only)
PARK_SAME = 6.0  # px: a free card this close to one of the previous frame is the same card
RESTACK_DY = (12.0, 30.0)  # px: Remove puts new cards this much higher (same x) on the cards parked before
STACK_REACH = 70.0  # px above a hidden parked card in which the cards on it lie
MAX_RISK = 0.25  # auto-click stops above this risk. The figure comes from the few guesses of the unread icons that
# fit in the time (often 8-10): on one board it varies by 10 % from run to run, and it is the same danger for every
# tap, so a small one is no reason to stop. A high one is: the player may want a booster
LOOK_CAP = 20.0  # s: safety cap of the look-ahead (it normally finishes all its guessed boards long before; the
# biggest recorded board, Stage 13's start, takes ~8 s)
PARK_ZONE = 1.5  # tile heights above the tray: cards there were parked by a Remove (the board never reaches down there)
GREEN, YELLOW, RED, WHITE, CYAN = (0, 255, 0), (0, 220, 255), (0, 0, 255), (255, 255, 255), (255, 255, 0)  # BGR


@dataclass
class Analysis:
    frame: V.Frame
    tray_kinds: list[int]
    moves: list[S.Move]
    n_unknown: int  # covered tiles whose icon could not be read
    hidden: dict[int, int]  # copies per kind that must still be hidden, if kinds come in triples
    new_stage: bool = False
    marks: list[dict] = field(default_factory=list)  # filled by build_marks
    frame_width: int = 0  # px width of the capture analysed (to map canonical px back onto it)
    n_kinds: int = 0  # icons the library knows (for further solver runs on this board)


def spot(t: V.Tile) -> tuple[float, float]:
    return (t.x if t.rx is None else t.rx, t.y if t.ry is None else t.ry)


def _same_spot(a: V.Tile, b: V.Tile) -> bool:
    (ax, ay), (bx, by) = spot(a), spot(b)
    return abs(ax - bx) <= PARK_SAME and abs(ay - by) <= PARK_SAME


def _put_on(top: V.Tile, below: V.Tile) -> bool:
    """Was `top` put down on the parked card `below` by a Remove?"""
    (tx, ty), (bx, by) = spot(top), spot(below)
    return abs(tx - bx) <= PARK_SAME and RESTACK_DY[0] <= by - ty <= RESTACK_DY[1]


def mark_parked(frame: V.Frame) -> None:
    """Flag the cards parked above the tray (Remove)."""
    top = frame.tray_rect[1] - PARK_ZONE * V.TILE_H
    for t in frame.tiles:
        t.parked = spot(t)[1] >= top


def kind_letter(k: int | None) -> str:
    return "?" if k is None else chr(ord("A") + k) if k < 26 else str(k)


class BoardMemory:
    """Icons read in earlier frames, by lattice cell, for tiles that are too hidden to read now.

    A cell can hold several tiles on top of each other (stacked layouts; a pile's tiles share the front tile's cell),
    so an entry is forgotten as soon as the free tile of that cell is tapped, pile tiles never take icons from it,
    and only earlier frames fill the current one (not the other tiles of the same frame)."""

    def __init__(self, lib: K.KindLibrary):
        self.lib = lib
        self.cells: dict[tuple[int, int], int] = {}
        self.free_cells: set[tuple[int, int]] = set()  # cells with a free tile in the previous frame
        self.free_kinds: dict[tuple[int, int], int] = {}  # ... and their icons
        self.free_tiles: list[V.Tile] = []  # ... and the tiles themselves
        self.parked: list[V.Tile] = []  # parked cards hidden under newer ones (Remove), as read while free

    def reset(self) -> None:
        self.cells.clear()
        self.free_cells.clear()
        self.free_kinds.clear()
        self.free_tiles.clear()
        self.parked.clear()

    def update(self, frame: V.Frame) -> bool:
        """Merge a frame into memory (fills unreadable kinds). Returns True when it looked like a new stage."""
        new_stage = False
        if self.cells and frame.tiles:
            fresh = sum((t.i, t.j) not in self.cells for t in frame.tiles)
            if fresh >= NEW_STAGE_MIN and fresh > NEW_STAGE_SHARE * len(frame.tiles):
                self.reset()
                new_stage = True
        kinds_now = {(t.i, t.j): t.kind for t in frame.tiles if t.free and t.kind is not None}
        compared = [cell for cell in kinds_now if cell in self.free_kinds]
        swapped = sum(kinds_now[cell] != self.free_kinds[cell] for cell in compared)
        if swapped >= SHUFFLE_MIN and swapped >= SHUFFLE_SHARE * len(compared):  # the board was shuffled (Refresh): every remembered icon is out of date
            self.reset()
            new_stage = True
        free_now = {(t.i, t.j) for t in frame.tiles if t.free}
        for cell in self.free_cells - free_now:  # that free tile was tapped: whatever lies there now is another
            self.cells.pop(cell, None)
        earlier = dict(self.cells)
        for t in frame.tiles:
            if t.pile:
                continue
            if t.kind is None:
                t.kind = earlier.get((t.i, t.j))
            elif t.free or t.kind_conf >= 0.5:
                self.cells[(t.i, t.j)] = t.kind
        self.free_cells = free_now
        self.free_kinds = kinds_now
        self._add_parked(frame)
        return new_stage

    def _add_parked(self, frame: V.Frame) -> None:
        """A second or third Remove puts its cards a bit higher on the parked ones, which hides those. They are
        added to the frame as covered tiles with the icons read before, so the solver knows what comes next."""
        free = [t for t in frame.tiles if t.free]
        self.parked = [p for p in self.parked if not any(_same_spot(p, t) and t.kind == p.kind for t in free)]
        for old in self.free_tiles:  # a free card gone, and a new one just above it: it is under that one now
            if old.kind is None or any(_same_spot(old, t) for t in free):
                continue
            if any(_put_on(t, old) and not any(_same_spot(t, o) for o in self.free_tiles) for t in free):
                self.parked.append(old)
        self.free_tiles = free
        for p in sorted(self.parked, key=lambda p: spot(p)[1]):  # the top of a stack first
            x, y = spot(p)
            on_it = [n for n, t in enumerate(frame.tiles) if abs(spot(t)[0] - x) <= PARK_SAME and 0 < y - spot(t)[1] <= STACK_REACH]
            t = next((t for t in frame.tiles if not t.free and _same_spot(t, p)), None)  # found by the peel already
            if t is None:
                t = V.Tile(p.i, p.j, p.x, p.y, False, rx=x, ry=y, parked=True)
                frame.tiles.append(t)
            t.kind, t.kind_conf = p.kind, 1.0
            t.covered_by, t.maybe_covered_by = list(on_it), list(on_it)


RELOCATE_DIST = 12.0  # a moved tile must match its kind this well ...
RELOCATE_RATIO = 0.4  # ... and clearly better than every other kind
RELOCATE_RANGE = 2  # lattice cells searched around an unreadable tile


def relocate_unread(frame: V.Frame, lib: K.KindLibrary) -> dict[int, int]:
    """Mostly hidden tiles are sometimes placed a cell off (or found twice). A covered tile that cannot be read
    where it is, but is an excellent match for a kind one or two cells away, is moved there; if that spot is
    taken by a tile that was just moved there it was a duplicate and is dropped. Returns {id(tile): kind}
    of the tiles whose kind this settled (empty if nothing changed)."""
    tiles, lat = frame.tiles, frame.lattice
    free_mask = np.zeros(frame.image.shape[:2], bool)
    for t in tiles:
        if t.free:
            V._paint(free_mask, V.footprint(t.x, t.y), shrink=-K.EDGE_MARGIN)
    at = {(t.i, t.j): t for t in tiles}
    settled: dict[int, int] = {}
    dropped = []
    for t in tiles:
        if t.free or t.kind is not None:
            continue
        here = K.tile_candidates(frame.image, t.x, t.y, K.hidden_mask(frame.image.shape[:2], tiles, t), dimmed=True)
        d_here = min(lib.quadrant_distances(here), default=np.inf) if here is not None else np.inf  # best over the shifts
        best = None
        for di in range(-RELOCATE_RANGE, RELOCATE_RANGE + 1):
            for dj in range(-RELOCATE_RANGE, RELOCATE_RANGE + 1):
                i, j = t.i + di, t.j + dj
                other = at.get((i, j))
                if (di, dj) == (0, 0) or (other is not None and id(other) not in settled):
                    continue  # only free cells, or a spot a tile was just moved to (then this one is a duplicate)
                x, y = lat.pos(i, j)
                cands = K.tile_candidates(frame.image, x, y, free_mask, dimmed=True)
                if cands is None:
                    continue
                d = lib.quadrant_distances(cands[K.CENTER : K.CENTER + 1], allow_single=False)
                if len(d) < 2:
                    continue
                order = np.argsort(d)
                if d[order[0]] < RELOCATE_DIST and d[order[0]] < RELOCATE_RATIO * d[order[1]] and d[order[0]] < 0.5 * d_here:
                    if best is None or d[order[0]] < best[0]:
                        best = (d[order[0]], int(order[0]), i, j, x, y)
        if best is None:
            continue
        _, kind, i, j, x, y = best
        other = at.get((i, j))
        if other is not None and other is not t:
            if id(other) in settled and other.kind == kind:
                dropped.append(t)  # found twice: another tile was moved to this spot just now
            continue
        del at[(t.i, t.j)]
        t.i, t.j, t.x, t.y, t.kind, t.kind_conf = i, j, x, y, kind, 0.5
        at[(i, j)] = t
        settled[id(t)] = kind
    if dropped:
        frame.tiles[:] = [t for t in tiles if all(t is not d for d in dropped)]
    return settled or ({0: -1} if dropped else {})


def refine_tiles(frame: V.Frame, lib: K.KindLibrary, rounds: int = 3) -> None:
    """Read the kinds, then let what was read correct the detection: move / drop misplaced covered tiles, and peel
    again, since removing a wrong tile can free the spot of a real one. Repeats until nothing changes."""
    board = frame.image[: frame.tray_rect[1] - 6]
    pinned: dict[int, int] = {}  # kinds settled by relocation stay even if the standard read is less sure
    for _ in range(rounds):
        K.identify(frame.image, frame.tiles, lib)
        moved = relocate_unread(frame, lib)
        pinned.update(moved)
        free = [t for t in frame.tiles if t.free]
        covered = [t for t in frame.tiles if not t.free]
        V.assign_stacking(frame.tiles, sum(t.free for t in frame.tiles), frame.image, frame.scorer)  # a drop shifted the indices
        extra = explain_polluted(frame, lib)
        for t in extra:
            pinned[id(t)] = t.kind
        covered += extra
        grown = V.find_dim_tiles(board, frame.lattice, free, frame.region, existing=covered, scorer=frame.scorer)
        changed = bool(moved) or bool(extra) or len(grown) != len(covered)
        frame.tiles[:] = free + grown
        V.assign_stacking(frame.tiles, len(free), frame.image, frame.scorer)
        for t in frame.tiles:
            if not t.free and id(t) in pinned:
                t.kind = pinned[id(t)]
        if not changed:
            break
    K.identify(frame.image, frame.tiles, lib)
    for t in frame.tiles:
        if t.kind is None and id(t) in pinned:
            t.kind, t.kind_conf = pinned[id(t)], 0.5
    add_quarter_tiles(frame, lib, board)
    add_piles(frame)


def add_piles(frame: V.Frame) -> None:
    """Tiles behind the free front tile of a pile: covered by the one in front of each, icon unknown."""
    taken = [(t.x if t.rx is None else t.rx, t.y if t.ry is None else t.ry) for t in frame.tiles]
    for front, behind in V.find_piles(frame):
        in_front = [front]  # every tile in front of a pile tile lies on it
        for x, y in behind:
            known = next((n for n, (a, b) in enumerate(taken) if abs(x - a) < 4 and abs(y - b) < 4), None)
            if known is not None:  # found already (e.g. by the peel): it stays, and lies under the ones in front
                in_front.append(known)
                continue
            i, j = frame.lattice.cell(x, y)
            t = V.Tile(i, j, x, y, False, rx=x, ry=y, pile=True)
            t.covered_by, t.maybe_covered_by = list(in_front), list(in_front)
            frame.tiles.append(t)
            in_front.append(len(frame.tiles) - 1)
            taken.append((x, y))


def add_quarter_tiles(frame: V.Frame, lib: K.KindLibrary, board: np.ndarray) -> None:
    """Tiles showing only a quarter are bounded by their neighbours' outlines, which the normal peel takes for a
    foreign border and rejects. Look for them again without that rule and keep only those whose icon is read."""
    free = [t for t in frame.tiles if t.free]
    covered = [t for t in frame.tiles if not t.free]
    grown = V.find_dim_tiles(board, frame.lattice, free, frame.region, existing=covered, lenient=True, scorer=frame.scorer)
    new = grown[len(covered) :]
    if not new:
        return
    trial = free + covered + new
    V.assign_stacking(trial, len(free), frame.image, frame.scorer)
    K.identify(frame.image, trial, lib, learn=False)
    keep = [t for t in new if t.kind is not None]
    if keep:
        frame.tiles[:] = free + covered + keep
        V.assign_stacking(frame.tiles, len(free), frame.image, frame.scorer)
        K.identify(frame.image, frame.tiles, lib)
    else:
        V.assign_stacking(frame.tiles, len(free), frame.image, frame.scorer)


POLLUTED = 20.0  # a quadrant this far from the tile's own kind shows something else
EXPLAIN_DIST = 12.0


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(w, 0) * max(h, 0) / ((a[2] - a[0]) * (a[3] - a[1]))


def explain_polluted(frame: V.Frame, lib: K.KindLibrary) -> list[V.Tile]:
    """A covered tile whose clean quadrants match its kind but whose other quadrants show a different icon is
    partly covered by a tile the peel never found (it assumes every accepted tile lies above all others, which a
    staircase of overlapping tiles breaks). Add the neighbouring tile that reads as that other icon on exactly the
    polluted pixels. Returns the added tiles."""
    tiles, lat, img = frame.tiles, frame.lattice, frame.image
    free_mask = np.zeros(img.shape[:2], bool)
    for t in tiles:
        if t.free:
            V._paint(free_mask, V.footprint(t.x, t.y), shrink=-K.EDGE_MARGIN)
    at = {(t.i, t.j) for t in tiles}
    added: list[V.Tile] = []
    for t in [t for t in tiles if not t.free and t.kind is not None]:
        cands = K.tile_candidates(img, t.x, t.y, K.hidden_mask(img.shape[:2], tiles, t), dimmed=True)
        if cands is None:
            continue
        feat, valid = cands[K.CENTER]
        err = lib.quadrant_errors(feat, valid)[t.kind]
        good = [q for q in range(4) if err[q] < EXPLAIN_DIST]
        bad = [q for q in range(4) if np.isfinite(err[q]) and err[q] > POLLUTED]
        if not good or not bad:
            continue
        bad_boxes = [K.quadrant_box(t.x, t.y, q) for q in bad]
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                i, j = t.i + di, t.j + dj
                if (di, dj) == (0, 0) or (i, j) in at:
                    continue
                x, y = lat.pos(i, j)
                c = K.tile_candidates(img, x, y, free_mask, dimmed=True)
                if c is None:
                    continue
                feat2, valid2 = c[K.CENTER]
                errs = lib.quadrant_errors(feat2, valid2)
                for q in range(4):
                    col = errs[:, q]
                    order = np.argsort(col)
                    if len(order) < 2 or not np.isfinite(col[order[0]]):
                        continue
                    best, second = col[order[0]], col[order[1]]
                    if best < EXPLAIN_DIST and best < RELOCATE_RATIO * second and int(order[0]) != t.kind:
                        box = K.quadrant_box(x, y, q)
                        if any(_overlap(box, bb) >= 0.5 for bb in bad_boxes):
                            nt = V.Tile(i, j, x, y, False, kind=int(order[0]), kind_conf=0.5)
                            added.append(nt)
                            at.add((i, j))
                            break
                else:
                    continue
    return added


def read_tray(frame: V.Frame, lib: K.KindLibrary) -> list[int]:
    kinds: list[int] = []
    for _, x, y in frame.tray:
        cands = K.tile_candidates(frame.image, x, y)
        if cands is not None:
            kinds.append(lib.learn_free(cands))
    return kinds


def analyze(
    img_bgr: np.ndarray,
    memory: BoardMemory,
    tray_rect: tuple[int, int, int, int] | None = None,
    samples: int | None = None,
    depth: int | None = None,
    budget: float | None = LOOK_CAP,
    seed: int | None = None,
    beam: int | None = None,
    think: float | None = None,
    threads: int | None = None,
) -> Analysis | None:
    """Everything for one screenshot. None when the board is not recognisable. The look-ahead searches all its
    guessed boards (`solver.LOOK_*` unless given); `budget` is only its safety cap. `think` = seconds for the
    whole-game search on top (`solver.deepen`; None or 0: look-ahead only)."""
    frame = V.read_frame(img_bgr, tray_rect)
    if frame is None or frame.lattice is None:
        return None
    refine_tiles(frame, memory.lib)
    new_stage = memory.update(frame)
    mark_parked(frame)
    tray = read_tray(frame, memory.lib)
    n_kinds = max(len(memory.lib), 1)
    snap = [S.SnapTile(t.kind, tuple(t.covered_by), locked=not t.free and not t.covered_by, parked=t.parked) for t in frame.tiles]
    if seed is None:  # the same board must give the same answer, or the suggestion jumps between near-equal taps
        seed = zlib.crc32(repr(([(round(t.x), round(t.y), t.kind) for t in frame.tiles], tray)).encode())
    moves = S.recommend(snap, tray, n_kinds, samples=samples, depth=depth, beam=beam, seed=seed, budget=budget, threads=threads)
    if think:
        moves = S.deepen(snap, tray, n_kinds, moves, budget=think, seed=seed, threads=threads)
    counts = [0] * n_kinds
    for t in frame.tiles:
        if t.kind is not None:
            counts[t.kind] += 1
    for k in tray:
        counts[k] += 1
    hidden = {k: h for k, h in enumerate(S.residue_hidden(counts)) if h}
    return Analysis(
        frame, tray, moves, sum(t.kind is None for t in frame.tiles if not t.free), hidden, new_stage,
        frame_width=img_bgr.shape[1], n_kinds=n_kinds,
    )


def _label_pos(t: V.Tile, tiles: list[V.Tile]) -> tuple[int, int]:
    """Where to write a tile's kind letter: the middle of what is visible of it. (The corner of a half-covered
    tile lies on top of its neighbour, which made the letter look like the neighbour's.)"""
    x0, y0, x1, y1 = V.footprint(*spot(t))
    visible = np.ones((y1 - y0, x1 - x0), bool)
    for m in t.maybe_covered_by if not t.free else ():
        ux0, uy0, ux1, uy1 = V.footprint(*spot(tiles[m]))
        visible[max(0, uy0 - y0 - 3) : max(0, uy1 - y0 + 3), max(0, ux0 - x0 - 3) : max(0, ux1 - x0 + 3)] = False
    ys, xs = np.nonzero(visible[8:-8, 8:-8])
    if len(xs) < 150:  # almost nothing shows: fall back to what is not provably under a covering tile
        return x0 + 6, y0 + 18
    return int(x0 + 8 + xs.mean()) - 5, int(y0 + 8 + ys.mean()) + 6


def build_marks(a: Analysis, labels: bool = False, top: int = 3) -> list[dict]:
    """Drawing primitives in canonical px: {'type': 'rect'|'text', ...}. The best tap is green with the tiles it
    uncovers outlined in cyan; the runners-up are yellow. Only free tiles can be recommended. Drawn where the tiles
    really are (`spot`): the front cards of piles and the parked cards lie off the lattice."""
    marks: list[dict] = []
    tiles = a.frame.tiles
    if labels:
        for t in tiles:
            x, y = _label_pos(t, tiles)
            marks.append({"type": "text", "x": x, "y": y, "text": kind_letter(t.kind), "color": WHITE if t.free else CYAN})
    ranked = [m for m in a.moves if tiles[m.tile].free][:top]
    for rank, m in enumerate(reversed(ranked)):
        place = len(ranked) - rank  # 1 = best
        t = tiles[m.tile]
        x0, y0, x1, y1 = V.footprint(*spot(t))
        color, width = (GREEN, 6) if place == 1 else (YELLOW, 3)
        marks.append({"type": "rect", "x0": x0 + 2, "y0": y0 + 2, "x1": x1 - 2, "y1": y1 - 2, "color": color, "width": width})
        marks.append({"type": "text", "x": x0 + 10, "y": y1 - 14, "text": str(place), "color": color, "big": True})
        if place == 1:  # what the tap uncovers
            for j, u in enumerate(tiles):
                if m.tile in u.covered_by and set(u.covered_by) <= {m.tile}:
                    ux0, uy0, ux1, uy1 = V.footprint(*spot(u))
                    marks.append({"type": "rect", "x0": ux0 + 5, "y0": uy0 + 5, "x1": ux1 - 5, "y1": uy1 - 5, "color": CYAN, "width": 2})
    return marks


def confidence(a: Analysis) -> tuple[bool, str]:
    """May the best tap be clicked without asking? Yes only when it is a free tile whose icon is known, and either
    it completes a set from the tray (never worse than anything else: it only frees slots; the risk left is that of
    the taps after it) or its risk is at most MAX_RISK. Returns (confident, reason when not)."""
    if not a.moves:
        return False, "no tile can be tapped"
    best = a.moves[0]
    tile = a.frame.tiles[best.tile]
    if not tile.free:
        return False, "best tile is not free"
    if best.kind is None:
        return False, "its icon is not read"
    completes = a.tray_kinds.count(best.kind) == S.MATCH - 1
    if not completes and (best.loss_rate > MAX_RISK or best.value <= S.LOSS / 2):
        return False, "risk %d%%" % round(best.loss_rate * 100)
    return True, ""


ABANDON_RISK = 0.6  # when no booster gets the risk below this, the game is most likely lost
BOOSTER_GAIN = 0.15  # a booster is worth using when it lowers the risk by at least this


def at_risk(a: Analysis) -> bool:
    """Is the best tap risky enough that the player should think about a booster (as auto-click waits then)?"""
    if not a.moves:
        return False
    best = a.moves[0]
    completes = best.kind is not None and a.tray_kinds.count(best.kind) == S.MATCH - 1
    return not completes and best.loss_rate > MAX_RISK


def booster_advice(a: Analysis, budget: float | None = 5.0, seed: int = 0) -> str:
    """Keep playing, Remove, Refresh or abandon? Compares the risk as it is with the risk after each booster."""
    tiles = a.frame.tiles
    middle = (a.frame.tray_rect[0] + a.frame.tray_rect[2]) / 2
    spots: dict[int, list[int]] = {}  # parking spot (0 = left) -> its cards (free on top, hidden below)
    for n, t in enumerate(tiles):
        if t.parked:
            spots.setdefault(round((spot(t)[0] + V.TILE_W / 2 - middle) / V.PITCH_X) + 1, []).append(n)
    tops = [next((n for n in spots.get(s, []) if tiles[n].free), None) for s in range(S.REMOVE_CARDS)]
    can_remove = max((len(v) for v in spots.values()), default=0) < S.PARK_LEVELS
    snap = [S.SnapTile(t.kind, tuple(t.covered_by), locked=not t.free and not t.covered_by, parked=t.parked) for t in tiles]
    risks = S.booster_risks(snap, a.tray_kinds, max(a.n_kinds, 1), tops, can_remove, seed=seed, budget=budget)
    now = risks.pop("now")
    shown = ", ".join(f"{name} {risk:.0%}" for name, risk in risks.items())
    best, risk = min(risks.items(), key=lambda kv: kv[1])
    if min(now, risk) >= ABANDON_RISK:
        verdict = "abandon: no booster gets the risk low enough"
    elif risk <= now - BOOSTER_GAIN:
        verdict = f"use {best}"
    else:
        verdict = "keep playing: no booster helps much"
    blocked = "" if can_remove else " (Remove is blocked: a parking spot is full)"
    return f"boosters: now {now:.0%}, {shown}{blocked} -> {verdict}"


def click_point(tile: V.Tile, scale: float, origin: tuple[int, int]) -> tuple[int, int]:
    """Screen pixel of the middle of a free tile. `scale` = canonical px per screen px, `origin` = the game area's
    top-left corner on the screen."""
    x = (tile.x if tile.rx is None else tile.rx) + 47  # ring-match corner -> middle of the face
    y = (tile.y if tile.ry is None else tile.ry) + 46
    return round(origin[0] + x / scale), round(origin[1] + y / scale)


def status_line(a: Analysis) -> str:
    free = sum(t.free for t in a.frame.tiles)
    cov = len(a.frame.tiles) - free
    hid = sum(a.hidden.values())
    parts = [f"tray {len(a.tray_kinds)}/{S.TRAY_SIZE}", f"free {free}", f"covered {cov} ({a.n_unknown} unread)", f"hidden ~{hid}"]
    if a.moves:
        best = a.moves[0]
        parts.append("risk %d%%" % round(best.loss_rate * 100))
        if best.win_rate is not None:
            parts.append("wins %d%%" % round(best.win_rate * 100))
    else:
        parts.append("no move")
    return " | ".join(parts)
