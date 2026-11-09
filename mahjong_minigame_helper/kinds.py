"""Tile kinds: which icon a tile shows.

A kind is a small blurred picture of the icon (KIND_SIZE x KIND_SIZE, BGR). Free tiles and tray tiles are shown in
full colour on a plain face, so they are clustered into kinds without any reference images. A covered tile is drawn
darker and partly hidden: its crop is brightened back (`DIM_FACTOR`) and compared with every kind on the visible
pixels only.

Tile positions jitter by a couple of pixels between frames (and between the tray and the board), which moves wide
icons far enough to look like another kind. So every tile is described by `tile_candidates`: the same crop at nine
small shifts, and a distance is the best of them. The library is saved in the game profile so kind ids stay
stable between stages and sessions.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from vision import DIM_FACTOR, Tile, footprint, _paint

KIND_SIZE = 24
BLUR = 3
SHIFT = 3  # px: candidates are the crop shifted by -SHIFT, 0, +SHIFT in both directions
SAME_DIST = 12.0  # free tiles closer than this (mean abs. difference, 0-255) are the same kind
ACCEPT_DIST = 25.0  # a covered tile matches a kind only below this ...
ACCEPT_RATIO = 0.6  # ... and when it beats the runner-up clearly
MIN_VISIBLE_CELLS = 20  # of KIND_SIZE**2: less than that tells nothing
QUAD_MIN_CELLS = 24  # of a quadrant's 144 cells
SINGLE_QUAD_PENALTY = 3.0  # added when a tile is judged by one quadrant alone
EDGE_MARGIN = 6  # px around a covering tile (its outline, shadow and lip) that are not the covered tile's icon
CELL_VISIBLE = 0.75  # share of a cell's pixels that must be visible for the cell to count
ICON = (6, 6, 88, 80)  # icon area relative to a tile's ring-match corner
LIBRARY_VERSION = 3  # bump when the feature changes: older files are ignored
DEFAULT_LIBRARY = Path(__file__).parent / "profiles" / "halloween_ball" / "kinds_default.npz"  # shipped icons of the active profile

_BGR_FACTOR = DIM_FACTOR[::-1].astype(np.float32)
Candidates = list  # of (feature, valid) pairs, the unshifted one at index CENTER
CENTER = 4


def tile_candidates(img_bgr: np.ndarray, x: float, y: float, covered: np.ndarray | None = None, dimmed: bool = False):
    """Nine shifted (feature, valid) pairs of the tile whose ring-match corner is (x, y), or None off-screen.
    `covered` marks hidden pixels of the image; `valid` marks the feature cells that are visible. The blur is
    normalised by the visible weight, so hidden neighbours do not bleed into the cells that are kept."""
    x, y = int(round(x)), int(round(y))
    x0, y0, x1, y1 = ICON
    h, w = img_bgr.shape[:2]
    cx0, cy0, cx1, cy1 = x + x0 - SHIFT, y + y0 - SHIFT, x + x1 + SHIFT, y + y1 + SHIFT
    if cx0 < 0 or cy0 < 0 or cx1 > w or cy1 > h:
        return None
    crop = img_bgr[cy0:cy1, cx0:cx1].astype(np.float32)
    if dimmed:
        crop = np.clip(crop / _BGR_FACTOR, 0, 255)
    weight = np.ones(crop.shape[:2], np.float32) if covered is None else (~covered[cy0:cy1, cx0:cx1]).astype(np.float32)
    num = cv2.GaussianBlur(crop * weight[:, :, None], (0, 0), BLUR)
    den = cv2.GaussianBlur(weight, (0, 0), BLUR)
    out = []
    for dy in (-SHIFT, 0, SHIFT):
        for dx in (-SHIFT, 0, SHIFT):
            sl = (slice(SHIFT + dy, SHIFT + dy + y1 - y0), slice(SHIFT + dx, SHIFT + dx + x1 - x0))
            n = cv2.resize(num[sl], (KIND_SIZE, KIND_SIZE), interpolation=cv2.INTER_AREA)
            d = cv2.resize(den[sl], (KIND_SIZE, KIND_SIZE), interpolation=cv2.INTER_AREA)
            out.append((n / np.maximum(d, 1e-3)[:, :, None], d >= CELL_VISIBLE))
    return out


class KindLibrary:
    """The known icons. An icon may have several reference pictures (`feats`, with `kind_of[n]` the icon of picture
    n): the same icon looks slightly different in a window screenshot and in a pixel-exact ADB frame, and training
    adds pictures instead of replacing them, so whatever matched before still matches. Distances are per icon, to
    its closest picture."""

    def __init__(self, path: Path | None = None, default: bool = True):
        self.path = path
        self.feats: list[np.ndarray] = []
        self.kind_of: list[int] = []
        for source in (path, DEFAULT_LIBRARY if default else None):  # your own file wins; otherwise start from the shipped icons
            if source is not None and source.exists():
                data = np.load(source)
                if "version" in data and int(data["version"]) == LIBRARY_VERSION:
                    self.feats = list(data["feats"].astype(np.float32))
                    self.kind_of = list(data["kind_of"].astype(int)) if "kind_of" in data else list(range(len(self.feats)))
                    break

    def __len__(self) -> int:
        """Number of icons (not pictures)."""
        return max(self.kind_of) + 1 if self.kind_of else 0

    def add(self, feat: np.ndarray, kind: int | None = None) -> int:
        """Add a picture of icon `kind` (a new icon if None); returns the icon."""
        kind = len(self) if kind is None else kind
        self.feats.append(np.asarray(feat, np.float32))
        self.kind_of.append(kind)
        return kind

    def _refs(self) -> tuple[np.ndarray, np.ndarray]:
        if getattr(self, "_stack_len", -1) != len(self.feats):
            self._stack = np.array(self.feats, np.float32)
            self._kinds = np.array(self.kind_of, int)
            self._stack_len = len(self.feats)
        return self._stack, self._kinds

    def _per_kind(self, values: np.ndarray) -> np.ndarray:
        """Per picture -> per icon: the smallest value over each icon's pictures."""
        _, kinds = self._refs()
        out = np.full((len(self),) + values.shape[1:], np.inf)
        np.minimum.at(out, kinds, values)
        return out

    def distances(self, cands: Candidates) -> list[float]:
        """Per icon: the best mean abs. difference over the shifts, on the visible cells (inf if too few)."""
        if not self.feats:
            return []
        refs, _ = self._refs()
        best = np.full(len(refs), np.inf)
        for feat, valid in cands:
            n = int(valid.sum())
            if n >= MIN_VISIBLE_CELLS:
                err = (np.abs(refs - feat).mean(axis=3) * valid).sum(axis=(1, 2)) / n
                best = np.minimum(best, err)
        return self._per_kind(best).tolist()

    def quadrant_distances(self, cands: Candidates, allow_single: bool = True) -> list[float]:
        """Like `distances`, but a tile is judged by its best two quadrants only (or one, with a penalty, if
        `allow_single`). A covered tile's visible area may include pixels of a tile that was wrongly taken to be
        below it; those spoil a quadrant, not the read."""
        if not self.feats:
            return []
        refs, _ = self._refs()
        h = KIND_SIZE // 2
        best = np.full(len(refs), np.inf)
        for feat, valid in cands:
            err = np.abs(refs - feat).mean(axis=3) * valid  # (pictures, 24, 24), hidden cells count 0
            per = np.full((len(refs), 4), np.inf)
            for q, (ys, xs) in enumerate(((slice(0, h), slice(0, h)), (slice(0, h), slice(h, None)), (slice(h, None), slice(0, h)), (slice(h, None), slice(h, None)))):
                n = int(valid[ys, xs].sum())
                if n >= QUAD_MIN_CELLS:
                    per[:, q] = err[:, ys, xs].sum(axis=(1, 2)) / n
            per.sort(axis=1)
            top = per[:, :2]
            finite = np.isfinite(top)
            cnt = finite.sum(axis=1)
            mean = np.where(cnt > 0, np.where(finite, top, 0).sum(axis=1) / np.maximum(cnt, 1), np.inf)
            # one clean quadrant can be all there is (a tile showing a single corner): it counts, with a penalty
            # (reading a tile only; a lone quadrant says too little to place one)
            if allow_single:
                mean = np.minimum(mean, per[:, 0] + SINGLE_QUAD_PENALTY)
            else:
                mean = np.where(cnt >= 2, mean, np.inf)
            best = np.minimum(best, mean)
        return self._per_kind(best).tolist()

    def quadrant_errors(self, feat: np.ndarray, valid: np.ndarray) -> np.ndarray:
        """(icons, 4) mean abs. difference per quadrant (top-left, top-right, bottom-left, bottom-right) for one
        unshifted candidate; inf where fewer than QUAD_MIN_CELLS cells are visible."""
        refs, _ = self._refs()
        h = KIND_SIZE // 2
        err = np.abs(refs - feat).mean(axis=3) * valid
        out = np.full((len(refs), 4), np.inf)
        for q, (ys, xs) in enumerate(((slice(0, h), slice(0, h)), (slice(0, h), slice(h, None)), (slice(h, None), slice(0, h)), (slice(h, None), slice(h, None)))):
            n = int(valid[ys, xs].sum())
            if n >= QUAD_MIN_CELLS:
                out[:, q] = err[:, ys, xs].sum(axis=(1, 2)) / n
        return self._per_kind(out)

    def learn_free(self, cands: Candidates) -> int:
        """Icon of a clean (bright) tile; unknown pictures become new icons."""
        d = self.distances(cands)
        if d and min(d) <= SAME_DIST:
            return int(np.argmin(d))
        return self.add(cands[CENTER][0])

    def classify(self, cands: Candidates) -> tuple[int | None, float]:
        """(icon or None, confidence 0-1) for a covered tile."""
        if not self.feats:
            return None, 0.0
        d = self.quadrant_distances(cands)
        order = np.argsort(d)
        best = d[order[0]]
        second = d[order[1]] if len(d) > 1 else 99.0
        if not np.isfinite(best) or best > ACCEPT_DIST or best > ACCEPT_RATIO * second:
            return None, 0.0
        return int(order[0]), float(1 - best / max(second, 1e-6))

    def save(self) -> None:
        if self.path is not None and self.feats:
            np.savez(self.path, feats=np.array(self.feats, np.float32), kind_of=np.array(self.kind_of, np.int32),
                     version=LIBRARY_VERSION)


def identify(img_bgr: np.ndarray, tiles: list[Tile], lib: KindLibrary, learn: bool = True) -> None:
    """Sets `kind` / `kind_conf` on every tile. `tiles` is free tiles first, then covered ones in peel order
    (each tile's `covered_by` indexes into this list)."""
    for t in tiles:
        if t.free:
            cands = tile_candidates(img_bgr, t.x if t.rx is None else t.rx, t.y if t.ry is None else t.ry)
            if cands is not None:
                t.kind, t.kind_conf = (lib.learn_free(cands) if learn else _nearest(lib, cands)), 1.0
    for t in tiles:
        if t.free:
            continue
        cands = tile_candidates(img_bgr, t.x, t.y, hidden_mask(img_bgr.shape[:2], tiles, t), dimmed=True)
        if cands is not None:
            t.kind, t.kind_conf = lib.classify(cands)


def quadrant_box(x: float, y: float, q: int) -> tuple[float, float, float, float]:
    """Pixel box of quadrant q (0 TL, 1 TR, 2 BL, 3 BR) of the icon area of the tile whose corner is (x, y)."""
    x0, y0, x1, y1 = ICON
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    xs = (x + x0, x + mx) if q % 2 == 0 else (x + mx, x + x1)
    ys = (y + y0, y + my) if q < 2 else (y + my, y + y1)
    return xs[0], ys[0], xs[1], ys[1]


def hidden_mask(shape: tuple[int, int], tiles: list[Tile], t: Tile) -> np.ndarray:
    """Pixels of tile t that may show another tile: everything not proven to lie below it, with a margin for
    that tile's outline and shadow."""
    hidden = np.zeros(shape, bool)
    for m in t.maybe_covered_by:
        _paint(hidden, footprint(tiles[m].x, tiles[m].y), shrink=-EDGE_MARGIN)
    return hidden


def _nearest(lib: KindLibrary, cands: Candidates) -> int | None:
    d = lib.distances(cands)
    return int(np.argmin(d)) if d and min(d) <= SAME_DIST else None
