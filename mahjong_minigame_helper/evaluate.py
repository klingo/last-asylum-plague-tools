"""How accurate is the tile reading? Runs it on every recorded frame and compares with the ground truth (`truth.py`).

    python main.py evaluate                 # all recordings, report printed and saved to recordings/_evaluation.json

Measured per frame, for every known tile (one that was free at some point of its game), bucketed by how much of it
was visible in that frame:
- found: a detected tile at its position,
- icon: read right / read wrong / not read,
- free: the tool's free / covered call matches (a known tile is free when no known tile lies on it),
- stacking: for overlapping known pairs, whether the detected cover relation has the right one on top.
Detections at positions where no known tile lies are counted apart ("unverified"): they are either tiles that
never became free before the game ended, or phantoms; the recordings cannot tell which.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

import cv2

import truth as T

MATCH = 15.0  # px: a detected tile this close to a known tile is that tile
PROGRESS_STEP = 5  # percent between progress lines


def _say(message: str) -> None:
    print(message, flush=True)


def mapped(pool, fn, items: list, label: str, chunksize: int = 2, log=_say) -> list:
    """`pool.map` that reports "progress <label>: N %" every PROGRESS_STEP % (the launcher shows it in its status
    bar). Used by evaluate, Check advice and Train."""
    out: list = []
    shown = -1
    for n, result in enumerate(pool.imap(fn, items, chunksize=chunksize), 1):
        out.append(result)
        pct = 100 * n // len(items) // PROGRESS_STEP * PROGRESS_STEP
        if pct > shown:
            shown = pct
            log(f"progress {label}: {pct} %")
    return out
BUCKETS = ((1.0, "free"), (0.6, "mostly visible"), (0.3, "half visible"), (0.1, "little visible"), (0.0001, "sliver"))
_lib = None


def _bucket(share: float, free: bool) -> str:
    if free:
        return "free"
    for limit, name in BUCKETS[1:]:
        if share >= limit:
            return name
    return "hidden"


def _init(profile: str, settings: dict | None = None) -> None:
    import game_profile as G
    import kinds as K

    global _lib
    G.activate(G.load(profile))
    G.apply_settings(settings or {})
    _lib = K.KindLibrary()
    _lib.learn_free = lambda cands: K._nearest(_lib, cands)  # read only: no new kinds while evaluating


def analyse_frame(path: str, full: bool = True) -> dict | None:
    """The tool's reading of one recorded frame (worker process). `full=False`: only what the truth needs (the
    free tiles and their icons), which is much faster."""
    import board as B
    import kinds as K
    import vision as V

    img = cv2.imread(path)
    if img is None:
        return None
    frame = V.read_frame(img)
    if frame is None or frame.lattice is None:
        return None
    if full:
        B.refine_tiles(frame, _lib)
    else:
        frame.tiles[:] = [t for t in frame.tiles if t.free]
        K.identify(frame.image, frame.tiles, _lib)
    result = {"full": full, "grid_ok": frame.grid_ok}
    tiles = []
    for t in frame.tiles:
        x, y = (t.rx, t.ry) if t.rx is not None else (t.x, t.y)
        tiles.append({"x": x, "y": y, "free": t.free, "kind": t.kind, "covered_by": list(t.covered_by)})
    result["tiles"] = tiles
    return result


def _analyse(job: tuple[str, bool]) -> dict | None:
    return analyse_frame(*job)


def frames_of(folder: Path) -> list[str]:
    """The recorded boards in order. (The recorder's "big change" notes are no segment breaks: a dialog or a
    Remove changes the screen a lot, too; truth.build recognises shuffles and new games itself.)"""
    meta_path = folder / "game.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"frames": []}
    entries = meta.get("frames") or [{"file": p.name} for p in sorted(folder.glob("*.png"))]
    return [str(folder / e["file"]) for e in entries]


def score(game: T.GameTruth, readings: list[dict | None], stats: dict) -> None:
    piles = {id(t) for t in game.tiles if T.in_pile(t, game.tiles)}
    for k, reading in enumerate(readings):
        known = game.at(k)
        if reading is None or not known:
            continue
        det = reading["tiles"]
        used: set[int] = set()
        matched: dict[int, int] = {}  # id(truth tile) -> detection index
        share = {id(t): game.visible_share(t, k) for t in known}
        # the most visible tile first: a detection at a spot where two tiles lie on top of each other is the upper one
        for t in sorted(known, key=lambda t: -share[id(t)]):
            best, best_d = None, MATCH
            for n, d in enumerate(det):
                dist = max(abs(d["x"] - t.x), abs(d["y"] - t.y))
                if n not in used and dist <= best_d:
                    best, best_d = n, dist
            cover = game.covering(t, k)
            place = "piles" if id(t) in piles else "board"
            s = stats[f"{place}:{_bucket(share[id(t)], not cover)}"]
            s["tiles"] += 1
            if best is None:
                continue
            used.add(best)
            matched[id(t)] = best
            d = det[best]
            s["found"] += 1
            if t.kind is not None:
                if d["kind"] is None:
                    s["icon unread"] += 1
                elif d["kind"] == t.kind:
                    s["icon right"] += 1
                else:
                    s["icon wrong"] += 1
            s["free call right"] += d["free"] == (not cover)
        stats["_"]["unverified detections"] += len(det) - len(used)
        stats["_"]["frames"] += 1
        if reading.get("grid_ok") is not None:  # the profile's lattice: did it fit this board?
            stats["_"]["grid boards"] += 1
            stats["_"]["grid fits"] += reading["grid_ok"]
        for t in known:  # stacking of overlapping known pairs that were both found
            for u in game.covering(t, k):
                if id(t) in matched and id(u) in matched:
                    stats["_"]["stacking pairs"] += 1
                    stats["_"]["stacking right"] += matched[id(u)] in det[matched[id(t)]]["covered_by"]


def evaluate(folders: list[Path], profile: str = "halloween_ball", workers: int | None = None,
             settings: dict | None = None, every: int = 1, log=_say) -> dict:
    """`settings` override detector settings (see game_profile.TUNABLE); `every` > 1 scores every n-th frame only
    (the truth still comes from all frames)."""
    jobs = [(f, frames_of(f)) for f in folders]
    workers = workers or max(1, min(16, (os.cpu_count() or 2) - 2))
    jobs_frames = [(p, n % every == 0) for _, files in jobs for n, p in enumerate(files)]
    with Pool(workers, initializer=_init, initargs=(profile, settings)) as pool:
        readings = mapped(pool, _analyse, jobs_frames, "reading the boards", log=log)
    stats: dict = defaultdict(lambda: defaultdict(int))
    per_game = {}
    i = 0
    for folder, files in jobs:
        game_readings = readings[i : i + len(files)]
        i += len(files)
        free = [None if r is None else [(d["x"], d["y"], d["kind"]) for d in r["tiles"] if d["free"]] for r in game_readings]
        game = T.build(files, free)
        before = sum(v["tiles"] for k, v in stats.items() if k != "_")
        score(game, [r if r is None or r["full"] else None for r in game_readings], stats)
        per_game[folder.name] = {"frames": len(files), "known tiles": len(game.tiles),
                                 "tile-frames": sum(v["tiles"] for k, v in stats.items() if k != "_") - before}
    return {"buckets": {k: dict(v) for k, v in stats.items() if k != "_"}, "overall": dict(stats["_"]), "games": per_game}


ORDER = ["free", "mostly visible", "half visible", "little visible", "sliver", "hidden"]
# what the summary counts as known: found and (where the icon can be seen at all) read right
NEEDS_ICON = {"free", "mostly visible", "half visible", "little visible"}


def _ok(s: dict, bucket: str) -> int:
    return s.get("icon right", 0) if bucket in NEEDS_ICON else s.get("found", 0)


def grade(pct: float) -> str:
    return ("reliable" if pct >= 95 else "good" if pct >= 80 else "partly" if pct >= 50 else
            "weak" if pct >= 20 else "not yet")


def summary(result: dict) -> tuple[float, list[str]]:
    """(confidence 0-100, plain lines). Confidence = of all tiles that showed at least a little, the share the tool
    found and, where the icon was visible, read right."""
    b = result["buckets"]
    groups = [
        ("Free tiles (what you can tap)", [("board", "free"), ("piles", "free")]),
        ("Covered, at least half visible", [("board", "mostly visible"), ("board", "half visible")]),
        ("Covered, little visible (10-30 %)", [("board", "little visible")]),
        ("Slivers on the board (under 10 %)", [("board", "sliver")]),
        ("Tiles inside piles", [("piles", n) for n in ORDER[1:5]]),
    ]
    lines, ok_all, n_all = [], 0, 0
    for title, keys in groups:
        ok = sum(_ok(b.get(f"{p}:{n}", {}), n) for p, n in keys)
        n = sum(b.get(f"{p}:{n}", {}).get("tiles", 0) for p, n in keys)
        ok_all, n_all = ok_all + ok, n_all + n
        if n:
            lines.append(f"{title}: {100 * ok / n:.0f} % - {grade(100 * ok / n)}")
    o = result["overall"]
    if o.get("stacking pairs"):
        pct = 100 * o["stacking right"] / o["stacking pairs"]
        lines.append(f"Which tile lies on top: {pct:.0f} % - {grade(pct)}")
    if o.get("grid boards"):  # below 100 %: a new stage or game version that the learned lattice does not cover
        pct = 100 * o["grid fits"] / o["grid boards"]
        lines.append(f"Board lattice (learned by Train) fits: {pct:.0f} % of boards"
                     + ("" if pct >= 99 else " - click Train again; if it stays low, tell Claude"))
    else:
        lines.append("Board lattice: not learned yet - click Train")
    return (100 * ok_all / n_all if n_all else 0.0), lines


def report_text(result: dict) -> str:
    pct = lambda a, b: f"{100 * a / b:.1f}%" if b else "-"  # noqa: E731
    lines = []
    for place in ("board", "piles"):
        lines.append(f"{place:<16}{'tiles':>8}{'found':>8}{'icon right':>12}{'icon wrong':>12}{'not read':>10}{'free call':>11}")
        for name in ORDER:
            s = result["buckets"].get(f"{place}:{name}")
            if not s:
                continue
            read = s.get("icon right", 0) + s.get("icon wrong", 0) + s.get("icon unread", 0)
            lines.append(f"  {name:<14}{s['tiles']:>8}{pct(s.get('found', 0), s['tiles']):>8}"
                         f"{pct(s.get('icon right', 0), read):>12}{pct(s.get('icon wrong', 0), read):>12}"
                         f"{pct(s.get('icon unread', 0), read):>10}{pct(s.get('free call right', 0), s.get('found', 0)):>11}")
    o = result["overall"]
    lines.append(f"unverified detections: {o.get('unverified detections', 0) / max(1, o.get('frames', 1)):.1f} per frame "
                 f"(tiles that never became free, or phantoms); {o.get('frames', 0)} frames")
    conf, plain = summary(result)
    lines += ["", f"Confidence: {conf:.0f} / 100 - of all tiles that showed at least a little, the share the tool knows "
                  "(found, and the icon read right where it was visible)"]
    lines += ["  " + line for line in plain]
    return "\n".join(lines)
