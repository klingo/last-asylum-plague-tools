"""How good are the advisor's taps? Measured on the won games, where the recording reveals the whole board.

    python benchmark.py                      # decisions at the default thinking time
    python benchmark.py --think 2 5 8 12     # the same for several thinking times (pick the default from this)
    python benchmark.py --throughput         # boards searched per second with 1, 8, 16, 24, 31 threads
    python benchmark.py --critical --think 2 5 8 12   # only the hard decisions (few taps keep the game winnable)
    python benchmark.py --critical --counts  # the guesses get the exact count of each hidden icon (from the truth)
    python benchmark.py --critical --noisy   # ... with two copies counted for the wrong icon (how exact must it be?)

Positions: every `--every`-th board of each won game (after its last Refresh: before it the icons were swapped), as it
really was (`truth.build`; tray as read). For each position:
1. Is it still winnable? Exact whole-game search with every icon known (`solver_fast`).
2. The advisor decides as a player sees it (icons only where enough shows: `advice.reference_boards`).
3. That tap is played on the true board: is the game still winnable? A tap that turns a winnable position into a lost
   one is a blunder. Full playouts would take hours at several seconds per tap; blunders per decision tell the same.
"""

from __future__ import annotations

import argparse
import random
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

import numpy as np

import advice as A
import board as B
import dataset as D
import evaluate as E
import game_profile as G
import kinds as K
import solver as S
import solver_fast as F
import truth as T

CRITICAL_SHARE = 0.5  # a decision is hard when at most this share of the free taps keeps the game winnable
DIFFICULTY_POSITIONS = 3_000_000  # exact check per tap when grading how hard a position is (taps beyond: skipped)
EXACT_POSITIONS = 30_000_000  # positions for the exact check of one position (~10 s on one core), else undecided


def won_games(profile: str) -> list[Path]:
    root = G.recordings_dir(profile)
    folders = [p for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith("_")] if root.exists() else []
    return [f for f in folders if D.summarise(f, S.TRAY_SIZE, match=S.MATCH).ending == "won"]


def positions(folder: Path, every: int, pool) -> list[dict]:
    files = E.frames_of(folder)
    reads = pool.map(A._read, files, chunksize=2)
    free = [None if r is None else [(*B.spot(t), t.kind) for t in r[0] if t.free] for r in reads]
    game = T.build(files, free)
    last = [s for s in game.segments if s is not None][-1]
    out = []
    for k in range(len(files)):
        if game.segments[k] != last or reads[k] is None or (k - game.segments.index(last)) % every:
            continue
        ref, perfect, hindsight = A.reference_boards(game, k, reads[k][0], won=True)
        if not any(not s.covered_by and not s.locked for s in hindsight):
            continue
        out.append({"game": folder.name, "frame": k, "tiles": ref, "seen": perfect, "true": hindsight, "tray": reads[k][1]})
    return out


def exact(board: list[S.SnapTile], tray: list[int], n_kinds: int) -> int:
    """WIN, NO_WIN or OUT_OF_POSITIONS for the true board (every icon known)."""
    kinds = [t.kind if t.kind is not None else 0 for t in board]
    status, _, _ = F.Board(board, tray, n_kinds, S.TRAY_SIZE, S.MATCH).search(kinds, EXACT_POSITIONS)
    return status


def after_tap(board: list[S.SnapTile], tray: list[int], i: int) -> tuple[list[S.SnapTile], list[int]] | None:
    """The true board and tray after tapping tile i; None when the tray overflows."""
    k = board[i].kind
    tray = list(tray)
    if tray.count(k) == S.MATCH - 1:
        tray = [x for x in tray if x != k]
    else:
        tray.append(k)
        if len(tray) >= S.TRAY_SIZE:
            return None
    keep = [j for j in range(len(board)) if j != i]
    new = {j: n for n, j in enumerate(keep)}
    out = [S.SnapTile(board[j].kind, tuple(new[c] for c in board[j].covered_by if c != i), board[j].locked, board[j].parked)
           for j in keep]
    return out, tray


COUNTS = None  # None, "exact" or "noisy": the guesses get the count of each hidden icon (see `hidden_counts`)


def hidden_counts(p: dict, n_kinds: int) -> list[int] | None:
    """How many of each icon a player cannot read on this board, from the truth (the best a tap count can give);
    "noisy": two copies moved to other icons."""
    if COUNTS is None:
        return None
    counts = [0] * n_kinds
    for seen, true in zip(p["seen"], p["true"]):
        if seen.kind is None and true.kind is not None:
            counts[true.kind] += 1
    if COUNTS == "noisy":
        rng = random.Random(p["frame"])
        for _ in range(2):
            have = [k for k, c in enumerate(counts) if c]
            if have:
                counts[rng.choice(have)] -= 1
                counts[rng.randrange(n_kinds)] += 1
    return counts


def decide(p: dict, n_kinds: int, think: float, threads: int | None) -> int:
    seen, tray = p["seen"], p["tray"]
    seed = hash((p["game"], p["frame"])) & 0xFFFF
    counts = hidden_counts(p, n_kinds)
    moves = S.recommend(seen, tray, n_kinds, seed=seed, hidden_counts=counts)  # the live advisor's look-ahead
    if think:
        moves = S.deepen(seen, tray, n_kinds, moves, budget=think, seed=seed, threads=threads, hidden_counts=counts)
    return moves[0].tile


_after: dict = {}  # (position, tap) -> status: the exact checks are the same for every thinking time


def run_decisions(ps: list[dict], n_kinds: int, think: float, threads: int | None, log=print) -> Counter:
    c: Counter = Counter()
    for n, p in enumerate(ps, 1):
        if "before" not in p:
            p["before"] = exact(p["true"], p["tray"], n_kinds)
        before = p["before"]
        if before != F.WIN:
            c["not winnable" if before == F.NO_WIN else "undecided"] += 1
            continue
        tap = decide(p, n_kinds, think, threads)
        key = (p["game"], p["frame"], tap)
        if key not in _after:
            nxt = after_tap(p["true"], p["tray"], tap)
            _after[key] = F.NO_WIN if nxt is None else exact(*nxt, n_kinds)
        status = _after[key]
        c["kept winnable" if status == F.WIN else "blunder" if status == F.NO_WIN else "undecided after"] += 1
        if status == F.NO_WIN:
            c[f"blunder at {p['game']}/{p['frame']:03d}"] += 1
        log(f"progress decisions: {100 * n // len(ps)} %")
    return c


def _winning_share(job: tuple) -> tuple[float | None, int]:
    """Worker: (share of the free taps that keep the true board winnable, free taps), None if undecided."""
    board, tray, n_kinds = job
    import game_profile as Gp

    Gp.activate(Gp.load(G.DEFAULT_NAME))
    free = [i for i, t in enumerate(board) if not t.covered_by and not t.locked]
    wins = decided = 0
    for i in free:
        nxt = after_tap(board, tray, i)
        if nxt is None:
            decided += 1
            continue
        kinds = [t.kind if t.kind is not None else 0 for t in nxt[0]]
        status, _, _ = F.Board(nxt[0], nxt[1], n_kinds, S.TRAY_SIZE, S.MATCH).search(kinds, DIFFICULTY_POSITIONS)
        if status == F.OUT_OF_POSITIONS:
            continue
        decided += 1
        wins += status == F.WIN
    return (wins / decided if decided and wins else None), len(free)


def critical(ps: list[dict], n_kinds: int, pool) -> list[dict]:
    """The positions where at most CRITICAL_SHARE of the free taps keep the game winnable (and at least one does)."""
    shares = pool.map(_winning_share, [(p["true"], p["tray"], n_kinds) for p in ps], chunksize=1)
    out = []
    for p, (share, n_free) in zip(ps, shares):
        if share is not None and share <= CRITICAL_SHARE and n_free > 1:
            p["share"] = share
            out.append(p)
    return out


def throughput(p: dict, n_kinds: int, seconds: float = 5.0) -> None:
    for threads in (1, 8, 16, 24, 31):
        votes, lost, boards = F.deepen(p["seen"], p["tray"], n_kinds, [], S.sample_kinds, S.TRAY_SIZE, S.MATCH,
                                       seconds, 0, S.FAST_POSITIONS, threads)
        print(f"  {threads:2d} threads: {boards / seconds:6.1f} guessed boards searched per second", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--profile", default=G.DEFAULT_NAME)
    ap.add_argument("--think", type=float, nargs="+", default=[5.0])
    ap.add_argument("--every", type=int, default=10, help="every n-th board of a game is a test position")
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--throughput", action="store_true")
    ap.add_argument("--critical", action="store_true", help="only the hard decisions (every board is a candidate)")
    ap.add_argument("--counts", action="store_true", help="the guesses get the exact count of each hidden icon")
    ap.add_argument("--noisy", action="store_true", help="... with two copies counted for the wrong icon")
    args = ap.parse_args()
    global COUNTS
    COUNTS = "noisy" if args.noisy else "exact" if args.counts else None
    G.activate(G.load(args.profile))
    n_kinds = max(len(K.KindLibrary()), 1)
    with Pool(12, initializer=E._init, initargs=(args.profile,)) as pool:
        ps = [p for f in won_games(args.profile) for p in positions(f, 1 if args.critical else args.every, pool)]
        print(f"{len(ps)} positions from the won games", flush=True)
        if args.critical:
            ps = critical(ps, n_kinds, pool)
            print(f"{len(ps)} of them are hard decisions (at most {CRITICAL_SHARE:.0%} of the taps keep the game "
                  f"winnable; mean {np.mean([p['share'] for p in ps]):.0%})", flush=True)
    if args.throughput:
        mid = max(ps, key=lambda p: sum(s.kind is None for s in p["seen"]))  # the one with the most to guess
        throughput(mid, n_kinds)
        return
    for think in args.think:
        t0 = time.monotonic()
        c = run_decisions(ps, n_kinds, think, args.threads)
        decided = c["kept winnable"] + c["blunder"]
        print(f"think {think:g} s, hidden icons {COUNTS or 'guessed as before'}: {c['kept winnable']} of {decided} "
              f"winnable positions kept winnable, {c['blunder']} blunders "
              f"({100 * c['blunder'] / max(decided, 1):.1f} %); not winnable {c['not winnable']}, undecided "
              f"{c['undecided'] + c['undecided after']}; {time.monotonic() - t0:.0f} s", flush=True)
        for key in sorted(k for k in c if k.startswith("blunder at")):
            print("   ", key, flush=True)


if __name__ == "__main__":
    main()
