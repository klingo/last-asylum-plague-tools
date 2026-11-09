"""Training from recordings: the tool learns from the games you recorded with a profile selected.

    python main.py train            # or the "Train from recordings" button

1. Icons: every free tile of every recorded board is matched to the profile's icons (a looser limit than while
   playing, safe because different icons are far apart); each icon's picture is then rebuilt as the median of all
   its pixel-exact crops. An icon that is truly new (seen several times, far from every known one) becomes a new
   kind. Kind numbers stay as they were.
2. The result is saved as the profile's icon library (`kinds_default.npz`, and your learned `kinds.npz` is replaced
   by it), so the advisor uses it from its next start.
3. The board's lattice: every stage puts its tiles on the same half-tile lattice, so its pitch and origin are
   learned from the positions of all free tiles (piles and parked cards lie off it and drop out) and saved in
   `profile.json` (`grid`). The advisor then only moves it on a board, instead of fitting it to a few tiles.

Run `evaluate` before and after to see the effect.
"""

from __future__ import annotations

import os
from multiprocessing import Pool
from pathlib import Path

import cv2
import numpy as np

ASSIGN_DIST = 20.0  # a free tile this close to a known icon is that icon (different icons are 27+ apart)
NEAR_COPY = 4.0  # a learned picture this close to one the icon has already adds nothing
GRID_NEAR = 2.0  # px: a free tile this close to a lattice position counts for the fit
GRID_MIN_TILES = 200  # free tiles needed to learn the lattice
NEW_MIN_TILES = 3  # a new icon must be seen on this many different tiles (icons come in triples; a mis-cut picture
# repeats on one spot frame after frame)
_lib = None


def _init(profile: str) -> None:
    import game_profile as G
    import kinds as K

    global _lib
    G.activate(G.load(profile))
    _lib = K.KindLibrary()


def free_icons(path: str) -> list[tuple[np.ndarray, tuple[int, int]]]:
    """(icon feature, where) of every free tile in one recorded frame, the tray included (worker process)."""
    import kinds as K
    import vision as V

    img = cv2.imread(path)
    if img is None:
        return []
    frame = V.read_frame(img)
    if frame is None:
        return []
    out = []
    for t in frame.tiles:
        if t.free:
            cands = K.tile_candidates(frame.image, t.rx if t.rx is not None else t.x, t.ry if t.ry is not None else t.y)
            if cands is not None:
                out.append((cands[K.CENTER][0], (round(t.x / 25), round(t.y / 25))))
    for _, x, y in frame.tray:
        cands = K.tile_candidates(frame.image, x, y)
        if cands is not None:
            out.append((cands[K.CENTER][0], (-1, -1)))  # the tray: no board position
    return out


def free_corners(path: str) -> list[tuple[float, float]]:
    """Ring-match corners of the free tiles in one recorded frame, the parked cards above the tray left out (worker
    process). They do not depend on any lattice."""
    import vision as V

    img = cv2.imread(path)
    if img is None:
        return []
    canon, _ = V.to_canon(img)
    tray = V.find_tray(canon)
    if tray is None:
        return []
    top = tray[1] - 1.5 * V.TILE_H  # the parking spots (board.PARK_ZONE)
    return [(x, y) for x, y, _ in V.find_free_tiles(canon[: tray[1] - 6]) if y < top]


def learn_grid(corners: list[tuple[float, float]], pitch: tuple[float, float]) -> tuple[tuple[float, float, float, float], float] | None:
    """((x0, y0, hx, hy), share of the tiles within GRID_NEAR px on both axes) of the half-tile lattice that fits
    the most free tiles; `pitch` = the profile's tile pitch, searched within +-3 %. None with too few tiles."""
    if len(corners) < GRID_MIN_TILES:
        return None
    pts = np.array(corners, float)

    def off(v: np.ndarray, o: float, step: float) -> np.ndarray:
        return (v - o + step / 2) % step - step / 2

    def axis(v: np.ndarray, step0: float) -> tuple[float, float]:
        best = None
        for step in np.arange(0.97 * step0, 1.03 * step0, 0.01):
            o = float(np.angle(np.mean(np.exp(2j * np.pi * v / step))) / (2 * np.pi) * step) % step  # circular mean
            r = off(v, o, step)
            o = (o + float(np.median(r[np.abs(r) <= 2 * GRID_NEAR]))) % step if np.any(np.abs(r) <= 2 * GRID_NEAR) else o
            share = float(np.mean(np.abs(off(v, o, step)) <= GRID_NEAR))
            if best is None or share > best[0]:
                best = (share, o, float(step))
        _, o, step = best  # several pitches hold about as many tiles within GRID_NEAR: the line through all the
        for _ in range(2):  # tiles on the lattice (piles left out) pins it down
            on = np.abs(off(v, o, step)) <= GRID_NEAR
            idx = np.round((v[on] - o) / step)
            if len(set(idx)) < 3:
                break
            step, o = (float(c) for c in np.polyfit(idx, v[on], 1))
            o %= step
        return o, step

    x0, hx = axis(pts[:, 0], pitch[0] / 2)
    y0, hy = axis(pts[:, 1], pitch[1] / 2)
    fit = float(np.mean((np.abs(off(pts[:, 0], x0, hx)) <= GRID_NEAR) & (np.abs(off(pts[:, 1], y0, hy)) <= GRID_NEAR)))
    return (round(x0, 2), round(y0, 2), round(hx, 3), round(hy, 3)), fit


def learn_icons(sightings: list[tuple[np.ndarray, tuple[int, int]]], known: list[np.ndarray], kind_of: list[int]) -> tuple[list[np.ndarray], list[int], dict]:
    """Library update from (icon feature, board position) sightings. Every known icon keeps its pictures and gets
    one more: the median of its sightings (unless that is a near copy of one it has). A picture that matches no
    icon becomes a new icon once seen on NEW_MIN_TILES different board positions. Returns (pictures, icon of each
    picture, stats)."""
    refs = np.array(known, np.float32) if known else np.zeros((0, 24, 24, 3), np.float32)
    owner = np.array(kind_of, int)
    n_kinds = max(kind_of) + 1 if kind_of else 0
    groups: list[list[np.ndarray]] = [[] for _ in range(n_kinds)]
    unknown = []
    for f, where in sightings:
        d = np.abs(refs - f).mean(axis=(1, 2, 3)) if len(refs) else np.array([])
        if len(d) and d.min() <= ASSIGN_DIST:
            groups[int(owner[d.argmin()])].append(f)
        else:
            unknown.append((f, where))
    new: list[tuple[list[np.ndarray], set]] = []  # greedy clustering of what matched nothing
    for f, where in unknown:
        for g, places in new:
            if np.abs(g[0] - f).mean() <= ASSIGN_DIST / 2:
                g.append(f)
                places.add(where)
                break
        else:
            new.append(([f], {where}))
    feats, kinds = [np.asarray(f, np.float32) for f in known], list(kind_of)
    added_pictures = 0
    for k, g in enumerate(groups):
        if not g:
            continue
        median = np.median(np.array(g), axis=0).astype(np.float32)
        mine = [f for f, o in zip(known, kind_of) if o == k]
        if min(np.abs(f - median).mean() for f in mine) > NEAR_COPY:
            feats.append(median)
            kinds.append(k)
            added_pictures += 1
    added = [g for g, places in new if len(places - {(-1, -1)}) >= NEW_MIN_TILES]
    for g in added:
        feats.append(np.median(np.array(g), axis=0).astype(np.float32))
        kinds.append(n_kinds)
        n_kinds += 1
    stats = {"sightings": len(sightings), "per icon": [len(g) for g in groups], "new icons": len(added),
             "new pictures": added_pictures, "unmatched": len(unknown) - sum(len(g) for g in added)}
    return feats, kinds, stats


def train(folders: list[Path], profile: str, workers: int | None = None, log=print) -> dict:
    import evaluate
    import game_profile as G
    import kinds as K

    paths = [p for f in folders for p in evaluate.frames_of(f)]
    log(f"learning icons from {len(paths)} recorded boards...")
    workers = workers or max(1, min(16, (os.cpu_count() or 2) - 2))
    with Pool(workers, initializer=_init, initargs=(profile,)) as pool:
        per_frame = evaluate.mapped(pool, free_icons, paths, "1/2 icons", log=log)
        corners = [c for frame in evaluate.mapped(pool, free_corners, paths, "2/2 board lattice", log=log) for c in frame]
    sightings = [s for frame in per_frame for s in frame]
    p = G.load(profile)
    G.activate(p)
    current = K.KindLibrary()
    feats, kinds, stats = learn_icons(sightings, current.feats, current.kind_of)
    for name in ("kinds_default.npz", "kinds.npz"):  # what the advisor learns while playing continues from here
        lib = K.KindLibrary(p.dir / name, default=False)
        lib.feats, lib.kind_of = list(feats), list(kinds)
        lib.save()
    log(f"icons: {len(current)} known ({stats['new pictures']} got a picture from your recordings), "
        f"{stats['new icons']} new, from {stats['sightings']} sightings ({stats['unmatched']} unclear ones ignored)")
    grid = learn_grid(corners, p.pitch)
    if grid is None:
        log(f"board lattice: too few free tiles ({len(corners)}) to learn it, it is fitted on every board meanwhile")
    else:
        (x0, y0, hx, hy), fit = grid
        p.grid = (x0, y0, hx, hy)
        G.save(p)
        stats["grid"], stats["grid fit"] = p.grid, fit
        log(f"board lattice: half-tile pitch {hx:.2f} x {hy:.2f} px from ({x0:.1f}, {y0:.1f}); {fit:.0%} of "
            f"{len(corners)} free tiles lie on it within {GRID_NEAR:.0f} px (the rest: piles)")
    return stats
