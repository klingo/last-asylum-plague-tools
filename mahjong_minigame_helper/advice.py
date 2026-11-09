"""Advice quality: how often recognition errors change the advice, measured on the recorded games.

Every recorded game is replayed like a live session (each frame read, the board memory carried from frame to frame),
and for every board the solver chooses a tap twice, with the live settings and the same tray:

- on what the tool read (the advice you would have got), and
- on the board as perfect recognition would read it: every tile that shows at least a little (`truth.py` knows
  where each one lay and what was on top), with its icon where enough of it shows or it was seen earlier. Icons
  that only came to light later stay unknown, as they would for any reader.

The tool's tap is scored with the values of the perfect-recognition run (the same samples for every tap, so taps
compare fairly): the same tap, another one just as good, slightly worse, or clearly worse. A third run on the whole
true board (also the icons that were still hidden) shows how often even perfect recognition picks the tap that
hindsight proves best; the rest is luck that no recognition can fix.

Unknown tiles: in a game that was not won, tiles that never became free are unknown to the truth. Tiles the tool
detected there are added to both reference boards as the tool read them (icon, and stacking among each other; under
the known ones they overlap), so they count neither for nor against it. In a won game every tile became free, so
such detections are phantoms and stay out.
"""

from __future__ import annotations

import os
import zlib
from collections import Counter
from multiprocessing import Pool
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

import board as B
import dataset as D
import evaluate as E
import game_profile as G
import kinds as K
import solver as S
import truth as T
import vision as V

SAMPLES, DEPTH, BEAM, BUDGET = 40, None, None, None  # the live advisor's look-ahead (solver.LOOK_*), but 40 guessed
# boards instead of 500: the check averages over thousands of boards anyway (500 took hours on the big boards)
SEEN = 0.02  # visible share from which a reader can tell that a tile is there ...
ICON_SEEN = 0.1  # ... and from which its icon can be read (below: slivers, icon unreadable)
SAME_VALUE = 1.0  # a tap at most this much below the best value is just as good (ties, rounding)
CLEARLY_WORSE = S.TRIPLE_BONUS / 2  # this much below (half a cleared set), or a tile that is not free: a bad tap
REVIEW_IMAGES = 15  # the worst taps get a picture each


def _read(path: str) -> tuple[list[V.Tile], list[int]] | None:
    """Worker: one frame read as the live advisor does, without the memory (that runs in order afterwards)."""
    img = cv2.imread(path)
    if img is None:
        return None
    frame = V.read_frame(img)
    if frame is None or frame.lattice is None:
        return None
    B.refine_tiles(frame, E._lib)
    B.mark_parked(frame)
    tray = []  # (the live advisor makes an unknown picture a new icon; read-only, the closest one is the best guess)
    for _, x, y in frame.tray:
        cands = K.tile_candidates(frame.image, x, y)
        if cands is not None:
            tray.append(int(np.argmin(E._lib.distances(cands))))
    return frame.tiles, tray


def _solve(job: tuple) -> tuple[list[tuple[int, float, float]], ...]:
    """Worker: the solver on the tool's reading, the perfect reading and the whole true board."""
    tool, perfect, hindsight, tray, n_kinds, seed = job
    out = []
    for snap, s in ((tool, seed), (perfect, 0), (hindsight, 0)):
        moves = S.recommend(snap, tray, n_kinds, samples=SAMPLES, depth=DEPTH, beam=BEAM, seed=s, budget=BUDGET,
                            threads=1)  # (the boards run in parallel processes already)
        out.append([(m.tile, m.value, m.loss_rate) for m in moves])
    return tuple(out)


def _nearest(x: float, y: float, tiles: list[T.TruthTile]) -> T.TruthTile | None:
    best, best_d = None, E.MATCH
    for t in tiles:
        d = max(abs(t.x - x), abs(t.y - y))
        if d <= best_d:
            best, best_d = t, d
    return best


def reference_boards(game: T.GameTruth, k: int, tool: list[V.Tile], won: bool) -> tuple[list[T.TruthTile], list, list]:
    """(tiles, perfect snapshot, hindsight snapshot) of frame k. Both snapshots list the same tiles in the same order:
    the known tiles that show (perfect) / all known tiles (hindsight), then the unknown ones the tool detected."""
    known = game.at(k)
    share = {id(t): game.visible_share(t, k) for t in known}
    seen_before = {id(t) for t in known if t.first_free < k}  # was free earlier (e.g. a parked card hidden since)
    tiles = list(known)
    unknown: dict[int, int] = {}  # index in `tool` -> index in `tiles`
    if not won:
        for n, t in enumerate(tool):
            x, y = B.spot(t)
            if _nearest(x, y, known) is None and not t.free:
                unknown[n] = len(tiles)
                tiles.append(T.TruthTile(x, y, t.kind, k, k, None, game.segments[k]))
    index = {id(t): n for n, t in enumerate(tiles)}
    under = {e: [unknown[m] for m in tool[n].covered_by if m in unknown] for n, e in unknown.items()}
    unseen = {index[id(t)] for t in known if share[id(t)] < SEEN and id(t) not in seen_before}  # no reader knows of them
    perfect, hindsight = [], []
    for n, t in enumerate(tiles):
        if id(t) in share:
            cover = tuple(index[id(u)] for u in game.covering(t, k))
        else:  # unknown: below every known tile it overlaps, and stacked among the unknown ones as the tool saw them
            cover = tuple(sorted({index[id(u)] for u in known if T.overlaps(u, t)} | set(under[n])))
        locked = id(t) not in share and not cover
        readable = id(t) not in share or id(t) in seen_before or share[id(t)] >= ICON_SEEN
        parked = t.appeared is not None if id(t) in share else tool[next(m for m, e in unknown.items() if e == n)].parked
        hindsight.append(S.SnapTile(t.kind, cover, locked, parked))
        if n in unseen:  # hidden completely: not on the board as any reader sees it (and it blocks nothing there)
            perfect.append(S.SnapTile(None, cover, locked=True))
        else:
            perfect.append(S.SnapTile(t.kind if readable else None, tuple(c for c in cover if c not in unseen), locked, parked))
    return tiles, perfect, hindsight


def causes(game: T.GameTruth, k: int, tool: list[V.Tile], won: bool) -> list[str]:
    """What the tool read differently from perfect recognition in frame k."""
    out = []
    seen = [t for t in game.at(k) if game.visible_share(t, k) >= SEEN or t.first_free < k]
    match: dict[int, int] = {}  # id(truth tile) -> index in `tool`
    for t in seen:
        n = min(range(len(tool)), key=lambda n: max(abs(B.spot(tool[n])[0] - t.x), abs(B.spot(tool[n])[1] - t.y)), default=None)
        if n is not None and max(abs(B.spot(tool[n])[0] - t.x), abs(B.spot(tool[n])[1] - t.y)) <= E.MATCH:
            match[id(t)] = n
    found = set(match.values())
    for t in seen:
        share = game.visible_share(t, k)
        cover = [u for u in game.covering(t, k) if u in seen]
        free = not game.covering(t, k)
        x = tool[match[id(t)]] if id(t) in match else None
        if x is None:
            out.append("free tile missed" if free else "covered tile missed")
        elif x.free != free:
            out.append("free / covered mixed up")
        elif (share >= ICON_SEEN or t.first_free < k) and t.kind is not None and x.kind != t.kind:
            if free:
                out.append("free tile's icon misread")
            else:
                out.append("covered tile's icon unread" if x.kind is None else "covered tile's icon misread")
        elif {match[id(u)] for u in cover if id(u) in match} != set(x.covered_by) & found:
            out.append("which tile lies on top differs")
    if won:
        known = game.at(k)
        out += ["tile seen where there is none" for t in tool if _nearest(*B.spot(t), known) is None]
    return out


def check(folders: list[Path], profile: str = "halloween_ball", workers: int | None = None, every: int = 1,
          review_dir: Path | None = None, log=print) -> dict:
    workers = workers or max(1, min(16, (os.cpu_count() or 2) - 2))
    G.activate(G.load(profile))
    n_kinds = max(len(K.KindLibrary()), 1)
    games = [(f, E.frames_of(f)) for f in folders]
    with Pool(workers, initializer=E._init, initargs=(profile,)) as pool:
        log(f"reading {sum(len(files) for _, files in games)} boards...")
        reads = E.mapped(pool, _read, [p for _, files in games for p in files], "1/2 reading the boards", log=log)
        jobs, where = [], []
        i = 0
        for folder, files in games:
            game_reads, i = reads[i : i + len(files)], i + len(files)
            free = [None if r is None else [(*B.spot(t), t.kind) for t in r[0] if t.free] for r in game_reads]
            game = T.build(files, free)
            won = D.summarise(folder, S.TRAY_SIZE, match=S.MATCH).ending == "won"
            memory = B.BoardMemory(None)
            for k, r in enumerate(game_reads):
                if r is None:
                    continue
                tiles, tray = r
                memory.update(SimpleNamespace(tiles=tiles))  # also adds parked cards hidden by a later Remove
                if game.segments[k] is None or k % every or len(tray) >= S.TRAY_SIZE or not any(t.free for t in tiles):
                    continue
                ref, perfect, hindsight = reference_boards(game, k, tiles, won)
                if not any(not s.covered_by and not s.locked for s in perfect):
                    continue
                snap = [S.SnapTile(t.kind, tuple(t.covered_by), locked=not t.free and not t.covered_by, parked=t.parked)
                        for t in tiles]
                seed = zlib.crc32(repr(([(round(t.x), round(t.y), t.kind) for t in tiles], tray)).encode())
                jobs.append((snap, perfect, hindsight, tray, n_kinds, seed))
                where.append((folder, files[k], game, k, tiles, ref, won))
        log(f"choosing taps on {len(jobs)} boards...")
        results = E.mapped(pool, _solve, jobs, "2/2 choosing the taps", chunksize=1, log=log)
    stats: Counter = Counter()
    cause_count: Counter = Counter()
    bad = []
    for (folder, path, game, k, tiles, ref, won), (mine, perfect, hindsight) in zip(where, results):
        stats["boards"] += 1
        best_tile = perfect[0][0]
        if hindsight and hindsight[0][0] == best_tile:
            stats["perfect = hindsight"] += 1
        pick = next((m for m in mine if tiles[m[0]].free), None)
        if pick is None:
            stats["no advice"] += 1
            continue
        x, y = B.spot(tiles[pick[0]])
        target = _nearest(x, y, [t for t in ref[: len(game.at(k))] if not game.covering(t, k)])
        values = {tile: (v, loss) for tile, v, loss in perfect}
        best_v = max(v for v, _ in values.values())
        n = next((n for n, t in enumerate(ref) if t is target), None)
        if n is not None and n == best_tile:
            stats["same"] += 1
            continue
        lost = best_v - values[n][0] if n in values else None
        if lost is not None and lost <= SAME_VALUE:
            stats["as good"] += 1
            continue
        verdict = "clearly worse" if lost is None or lost >= CLEARLY_WORSE else "slightly worse"
        stats[verdict] += 1
        why = causes(game, k, tiles, won)
        cause_count.update(set(why) or {"same reading (chance in the solver's sampling of hidden icons)"})
        bad.append({"game": folder.name, "frame": Path(path).name, "verdict": verdict,
                    "lost": None if lost is None else round(lost, 1), "causes": sorted(set(why)) or ["same reading"],
                    "tap": [round(x), round(y)], "best": [round(ref[best_tile].x), round(ref[best_tile].y)], "path": path})
    bad.sort(key=lambda b: -(b["lost"] if b["lost"] is not None else 1e9))
    if review_dir is not None:
        write_reviews(bad[:REVIEW_IMAGES], review_dir)
    return {"stats": dict(stats), "causes": dict(cause_count), "worse taps": bad}


def write_reviews(bad: list[dict], out: Path) -> None:
    """One picture per bad tap: red = the advisor's tap, green = the best tap with perfect recognition."""
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    for n, b in enumerate(bad, 1):
        img, _ = V.to_canon(cv2.imread(b["path"]))
        for (x, y), colour in ((b["best"], (0, 200, 0)), (b["tap"], (0, 0, 255))):
            x0, y0, x1, y1 = V.footprint(x, y)
            cv2.rectangle(img, (x0, y0), (x1, y1), colour, 4)
        cv2.putText(img, f"{b['verdict']}: {', '.join(b['causes'])}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.imwrite(str(out / f"{n:02d}-{b['game']}-{b['frame']}"), img)


def summary(result: dict) -> tuple[float, list[str]]:
    """(advice quality 0-100, plain lines). Quality = share of boards where the advisor's tap was as good as the
    tap perfect recognition gives."""
    s = result["stats"]
    n = s.get("boards", 0)
    if not n:
        return 0.0, ["No boards to compare."]
    pct = lambda key: 100 * s.get(key, 0) / n  # noqa: E731
    lines = [
        f"Same tap as with perfect recognition: {pct('same'):.0f} %",
        f"Another tap, just as good: {pct('as good'):.0f} %",
        f"Slightly worse: {pct('slightly worse'):.0f} %",
        f"Clearly worse (half a set or more, or a tile that is not free): {pct('clearly worse'):.0f} %",
    ]
    if s.get("no advice"):
        lines.append(f"No advice (no free tile recognised): {pct('no advice'):.0f} %")
    lines.append(f"Even perfect recognition picks the tap hindsight shows best in {pct('perfect = hindsight'):.0f} % "
                 "(the rest is luck: icons still hidden)")
    return pct("same") + pct("as good"), lines


def report_text(result: dict) -> str:
    quality, lines = summary(result)
    out = [f"Advice quality: {quality:.0f} / 100 - {E.grade(quality)}: boards where the advisor's tap was as good as "
           f"with perfect recognition ({result['stats'].get('boards', 0)} boards)"]
    out += ["  " + line for line in lines]
    if result["causes"]:
        out.append("What the tool read differently on the boards with a worse tap (a board can have several):")
        out += [f"  {c}: {n}" for c, n in Counter(result["causes"]).most_common()]
    worst = result["worse taps"][:10]
    if worst:
        out.append("Worst taps:")
        out += [f"  {b['game']}/{b['frame']}: {b['verdict']}"
                f"{'' if b['lost'] is None else ' by ' + str(b['lost'])} - {', '.join(b['causes'])}" for b in worst]
    return "\n".join(out)
