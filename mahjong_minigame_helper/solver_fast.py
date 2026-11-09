"""The search to the end of the game, compiled with numba and run on all CPU cores (numba is required).

Same rules and move order as the short look-ahead (`solver._World`), 2-3 million positions per second per core
(the Python version it replaced: ~50'000, with the same answers): the board is a few
numpy arrays (each tile's icon, the tiles it lies on, a counter of the tiles still on it: free at 0), the search an
explicit stack, and the positions known to lose a hash table keyed by a 64-bit Zobrist hash of the taken tiles
(boards have more tiles than one 64-bit mask holds).

`deepen` spreads the work over threads (the compiled search releases the GIL): each guessed board is searched with
a fixed position cap, so its answer is the same on a fast or a slow core; the threads take the next board from a
shared counter until the time is up, so fast cores simply search more boards. With nothing to guess (one board),
the threads split that board by its first tap instead.
"""

from __future__ import annotations

import os
import random
import threading
import time
from collections import Counter

import numpy as np

from numba import njit


WIN, NO_WIN, OUT_OF_POSITIONS, STOPPED = 1, 0, -1, -2
LOCKED = 1 << 20  # cover count of a tile nobody can reach yet (never free)
TABLE_BITS = 20  # dead-end table: 2^20 entries (8 MB) per thread
PROBES = 8


@njit(cache=True, nogil=True)
def _search(kinds, below_ptr, below_idx, cover0, tray0, tray_size, match, zob, table, cap, forced, stop):
    """Depth-first to the end of the game. Returns (status, first tap of the winning line or -1, positions)."""
    n = kinds.shape[0]
    n_kinds = tray0.shape[0]
    cover = cover0.copy()
    free = np.zeros(n, np.bool_)
    free_cnt = np.zeros(n_kinds, np.int64)
    tray = tray0.copy()
    size = 0
    for k in range(n_kinds):
        size += tray[k]
    n_free = 0
    for i in range(n):
        if cover[i] == 0:
            free[i] = True
            free_cnt[kinds[i]] += 1
            n_free += 1
    mask = table.shape[0] - 1
    cand = np.empty((n + 1, n), np.int64)
    score = np.empty(n, np.float64)
    ncand = np.zeros(n + 1, np.int64)
    pos = np.zeros(n + 1, np.int64)
    chosen = np.empty(n + 1, np.int64)
    before = np.empty(n + 1, np.int64)  # tray count of the tapped icon before the tap
    hashes = np.empty(n + 2, np.uint64)
    h = np.uint64(0x9E3779B97F4A7C15)
    positions = 0
    depth = 0
    entering = True
    while True:
        if entering:
            entering = False
            if n_free == 0:
                return WIN, chosen[0] if depth > 0 else -1, positions
            key = h if h != 0 else np.uint64(1)
            slot = np.int64(key & np.uint64(mask))
            dead = False
            for p in range(PROBES):
                v = table[(slot + p) & mask]
                if v == key:
                    dead = True
                    break
                if v == 0:
                    break
            hashes[depth] = key
            if dead:
                ncand[depth] = 0
                pos[depth] = 0
            else:
                positions += 1
                if positions > cap:
                    return OUT_OF_POSITIONS, -1, positions
                if (positions & 1023) == 0 and stop[0] != 0:
                    return STOPPED, -1, positions
                # candidates in order of promise (as _World.quick)
                m = 0
                for i in range(n):
                    if not free[i]:
                        continue
                    if depth == 0 and forced >= 0 and i != forced:
                        continue
                    k = kinds[i]
                    c = tray[k]
                    q = 0.0
                    for e in range(below_ptr[i], below_ptr[i + 1]):
                        j = below_idx[e]
                        if cover[j] == 1:
                            q += 2.0
                            held = tray[kinds[j]] + (1 if kinds[j] == k else 0)
                            if held >= match - 1:
                                q += 25.0
                            elif held > 0:
                                q += 10.0
                    if c == match - 1:
                        q += 1000.0
                    elif c > 0:
                        q += 30.0
                        if free_cnt[k] > match - 1 - c:
                            q += 5.0
                    else:
                        q -= 5.0
                        if free_cnt[k] >= match:
                            q += 12.0
                    # insertion into the sorted list (best first; ties keep the tile order)
                    a = m
                    while a > 0 and score[a - 1] < q:
                        cand[depth, a] = cand[depth, a - 1]
                        score[a] = score[a - 1]
                        a -= 1
                    cand[depth, a] = i
                    score[a] = q
                    m += 1
                ncand[depth] = m
                pos[depth] = 0
        # the next candidate at this depth
        moved = False
        while pos[depth] < ncand[depth]:
            i = cand[depth, pos[depth]]
            pos[depth] += 1
            k = kinds[i]
            c = tray[k]
            if c < match - 1 and size + 1 >= tray_size:
                continue  # the tray would be full
            chosen[depth] = i
            before[depth] = c
            free[i] = False
            free_cnt[k] -= 1
            n_free -= 1
            for e in range(below_ptr[i], below_ptr[i + 1]):
                j = below_idx[e]
                cover[j] -= 1
                if cover[j] == 0:
                    free[j] = True
                    free_cnt[kinds[j]] += 1
                    n_free += 1
            if c == match - 1:
                tray[k] = 0
                size -= match - 1
            else:
                tray[k] = c + 1
                size += 1
            h ^= zob[i]
            depth += 1
            entering = True
            moved = True
            break
        if moved:
            continue
        # every tap from here loses: remember the position, go back one tap (not the start when the first tap was
        # given: other first taps from there may still win, and the table is shared by those searches)
        if (ncand[depth] > 0 or pos[depth] > 0) and not (depth == 0 and forced >= 0):
            key = hashes[depth]
            slot = np.int64(key & np.uint64(mask))
            for p in range(PROBES):
                s = (slot + p) & mask
                if table[s] == 0 or table[s] == key:
                    table[s] = key
                    break
        if depth == 0:
            return NO_WIN, -1, positions
        depth -= 1
        i = chosen[depth]
        k = kinds[i]
        c = before[depth]
        h ^= zob[i]
        tray[k] = c
        if c == match - 1:
            size += match - 1
        else:
            size -= 1
        for e in range(below_ptr[i], below_ptr[i + 1]):
            j = below_idx[e]
            if cover[j] == 0:
                free[j] = False
                free_cnt[kinds[j]] -= 1
                n_free -= 1
            cover[j] += 1
        free[i] = True
        free_cnt[k] += 1
        n_free += 1


class Board:
    """A snapshot (`solver.SnapTile` list) as the arrays the compiled search works on."""

    def __init__(self, tiles, tray: list[int], n_kinds: int, tray_size: int, match: int, seed: int = 0):
        n = len(tiles)
        below: list[list[int]] = [[] for _ in range(n)]
        cover0 = np.zeros(n, np.int64)
        for i, t in enumerate(tiles):
            for c in t.covered_by:
                below[c].append(i)
            cover0[i] = len(t.covered_by) + (LOCKED if t.locked else 0)
        self.below_ptr = np.zeros(n + 1, np.int64)
        for i in range(n):
            self.below_ptr[i + 1] = self.below_ptr[i] + len(below[i])
        self.below_idx = np.array([j for b in below for j in b], np.int64) if n else np.zeros(0, np.int64)
        self.cover0 = cover0
        self.n_kinds = n_kinds
        self.tray = np.zeros(n_kinds, np.int64)
        for k in tray:
            self.tray[k] += 1
        self.tray_size, self.match = tray_size, match
        self.zob = np.random.default_rng(seed).integers(1, 2**63, n, dtype=np.int64).astype(np.uint64)

    def search(self, kinds, cap: int, table=None, forced: int = -1, stop=None) -> tuple[int, int, int]:
        """(status, first tap of the winning line or -1, positions visited) for these icons."""
        table = table if table is not None else np.zeros(1 << TABLE_BITS, np.uint64)
        stop = stop if stop is not None else np.zeros(1, np.int64)
        return _search(np.asarray(kinds, np.int64), self.below_ptr, self.below_idx, self.cover0, self.tray,
                       self.tray_size, self.match, self.zob, table, cap, forced, stop)


DEFAULT_THREADS = 16  # measured (benchmark.py --throughput, i9-13900K): 1: 4.8, 8: 40, 16: 71, 24: 71, 31: 70 boards/s


def default_threads() -> int:
    return max(1, min(DEFAULT_THREADS, (os.cpu_count() or 2) - 1))  # one left for the overlay and the vision


def deepen(tiles, tray, n_kinds, moves, sample_kinds, tray_size, match, budget: float, seed, positions: int,
           threads: int | None = None):
    """`solver.deepen` on all cores. Returns (votes: guessed boards on which each tap still wins, boards with no winning
    tap at all, boards searched). With nothing to guess, the first tap found to win gets the one vote."""
    threads = threads or default_threads()
    board = Board(tiles, tray, n_kinds, tray_size, match, seed or 0)
    certain = not any(t.kind is None for t in tiles)
    deadline = time.monotonic() + budget
    stop = np.zeros(1, np.int64)
    lock = threading.Lock()
    rng = random.Random(seed)
    votes: Counter = Counter()
    result = {"lost": 0, "boards": 0}
    if certain:
        kinds = np.asarray(sample_kinds(tiles, tray, n_kinds, rng), np.int64)
        firsts = [m.tile for m in moves]  # most promising first; each thread takes the next tap
        nxt = [0]
        proven = []

        def work() -> None:
            table = np.zeros(1 << TABLE_BITS, np.uint64)
            while True:
                with lock:
                    if nxt[0] >= len(firsts) or stop[0]:
                        return
                    first = firsts[nxt[0]]
                    nxt[0] += 1
                table[:] = 0
                status, _, _ = board.search(kinds, 1 << 62, table, first, stop)
                with lock:
                    if status == WIN:
                        votes[first] += 1
                        stop[0] = 1  # a winning line is all we need
                    elif status == NO_WIN:
                        proven.append(first)
    else:
        firsts = [m.tile for m in moves]

        def work() -> None:
            # Every candidate tap on every guessed board (they share the board's dead ends): the vote goes to each tap
            # that still wins there, so the tap that wins whatever the hidden icons are comes first. (Counting only
            # the first winning tap the search happens to find made taps that win on a few guesses look as good.)
            table = np.zeros(1 << TABLE_BITS, np.uint64)
            while time.monotonic() < deadline and not stop[0]:
                with lock:
                    kinds = np.asarray(sample_kinds(tiles, tray, n_kinds, rng), np.int64)
                table[:] = 0
                outcome = []
                for first in firsts:
                    status, _, _ = board.search(kinds, positions, table, first, stop)
                    if status == STOPPED:
                        return  # the time is up: an unfinished board does not count
                    outcome.append((first, status))
                with lock:
                    result["boards"] += 1
                    for first, status in outcome:
                        if status == WIN:
                            votes[first] += 1
                    if all(status == NO_WIN for _, status in outcome):
                        result["lost"] += 1

    pool = [threading.Thread(target=work, daemon=True) for _ in range(threads)]
    for t in pool:
        t.start()
    timer = threading.Timer(budget, lambda: stop.__setitem__(0, 1))
    timer.start()
    for t in pool:
        t.join()
    timer.cancel()
    if certain:
        result["boards"] = 1
        if not votes and len(proven) == len(firsts):
            result["lost"] = 1  # every first tap proven to lose
    return votes, result["lost"], result["boards"]


def warm_up() -> None:
    """Compile the search (the first time after an install; numba caches it on disk) before the first board."""
    from solver import SnapTile

    Board([SnapTile(0), SnapTile(0), SnapTile(0)], [], 1, 7, 3).search([0, 0, 0], 100)


# --- the short look-ahead (`solver.recommend`): a beam search a few taps deep, scored at its ends ----------------
TRIPLE_BONUS, TRIPLE_URGENCY, LOOK_LOSS, LOOK_WIN = 100.0, 8.0, -1000.0, 500.0  # as in solver.py


@njit(cache=True, nogil=True)
def _take(i, kinds, below_ptr, below_idx, cover, free, free_cnt, tray, left, st, match, tray_size):
    """Tap i; returns the tray count of its icon before (to undo), or -1 if the tray would overflow (nothing done).
    st = [size, taken, free tiles]."""
    k = kinds[i]
    c = tray[k]
    if c < match - 1 and st[0] + 1 >= tray_size:
        return -1
    free[i] = False
    free_cnt[k] -= 1
    left[k] -= 1
    st[1] += 1
    st[2] -= 1
    for e in range(below_ptr[i], below_ptr[i + 1]):
        j = below_idx[e]
        cover[j] -= 1
        if cover[j] == 0:
            free[j] = True
            free_cnt[kinds[j]] += 1
            st[2] += 1
    if c == match - 1:
        tray[k] = 0
        st[0] -= match - 1
    else:
        tray[k] = c + 1
        st[0] += 1
    return c


@njit(cache=True, nogil=True)
def _undo(i, c, kinds, below_ptr, below_idx, cover, free, free_cnt, tray, left, st, match):
    k = kinds[i]
    for e in range(below_ptr[i], below_ptr[i + 1]):
        j = below_idx[e]
        if cover[j] == 0:
            free[j] = False
            free_cnt[kinds[j]] -= 1
            st[2] -= 1
        cover[j] += 1
    free[i] = True
    free_cnt[k] += 1
    left[k] += 1
    st[1] -= 1
    st[2] += 1
    if c == match - 1:
        st[0] += match - 1
    else:
        st[0] -= 1
    tray[k] = c


@njit(cache=True, nogil=True)
def _quick(i, kinds, below_ptr, below_idx, cover, free_cnt, tray, match):
    k = kinds[i]
    c = tray[k]
    q = 0.0
    for e in range(below_ptr[i], below_ptr[i + 1]):
        j = below_idx[e]
        if cover[j] == 1:  # i is the last tile on j: tapping i frees it
            q += 2.0
            held = tray[kinds[j]] + (1 if kinds[j] == k else 0)
            if held >= match - 1:
                q += 25.0
            elif held > 0:
                q += 10.0
    if c == match - 1:
        return q + 1000.0
    if c > 0:
        return q + 30.0 + (5.0 if free_cnt[k] > match - 1 - c else 0.0)
    return q - 5.0 + (12.0 if free_cnt[k] >= match else 0.0)


@njit(cache=True, nogil=True)
def _evaluate(free_cnt, tray, left, st, fill, match):
    score = -fill[st[0]]
    ready = 0
    for k in range(tray.shape[0]):
        c = tray[k]
        if c > 0:
            if left[k] + c < match:
                score -= 12.0 * c  # can never be completed: those slots are gone for good
            elif c == match - 1:
                score += 12.0 if free_cnt[k] > 0 else 4.0
            elif free_cnt[k] >= match - c:
                score += 2.0
        if tray[k] + free_cnt[k] >= match:
            ready += 1
    return score + 1.5 * ready + 0.5 * min(st[2], 10)


@njit(cache=True, nogil=True)
def _beam(depth, beam, kinds, below_ptr, below_idx, cover, free, free_cnt, tray, left, st, match, tray_size, fill, pressure):
    """Best value of a line of `depth` taps from here (LOOK_LOSS when every line overflows the tray)."""
    n = kinds.shape[0]
    if st[2] == 0:
        if st[1] == n:
            done = True
            for k in range(left.shape[0]):
                if left[k] != 0:
                    done = False
            if done:
                return LOOK_WIN
        return _evaluate(free_cnt, tray, left, st, fill, match) - 50.0
    if depth == 0:
        return _evaluate(free_cnt, tray, left, st, fill, match)
    cand = np.empty(st[2], np.int64)
    qs = np.empty(st[2], np.float64)
    m = 0
    for i in range(n):  # sorted best first; equal scores: the higher tile first (as Python's sort of (q, i) pairs)
        if not free[i]:
            continue
        q = _quick(i, kinds, below_ptr, below_idx, cover, free_cnt, tray, match)
        a = m
        while a > 0 and (qs[a - 1] < q or (qs[a - 1] == q and cand[a - 1] < i)):
            cand[a] = cand[a - 1]
            qs[a] = qs[a - 1]
            a -= 1
        cand[a] = i
        qs[a] = q
        m += 1
    out = LOOK_LOSS
    for a in range(min(beam, m)):
        i = cand[a]
        cleared = tray[kinds[i]] == match - 1
        c = _take(i, kinds, below_ptr, below_idx, cover, free, free_cnt, tray, left, st, match, tray_size)
        if c < 0:
            continue
        v = (TRIPLE_BONUS + TRIPLE_URGENCY * depth if cleared else 0.0) - pressure[st[0]]
        v += _beam(depth - 1, beam, kinds, below_ptr, below_idx, cover, free, free_cnt, tray, left, st, match,
                   tray_size, fill, pressure)
        _undo(i, c, kinds, below_ptr, below_idx, cover, free, free_cnt, tray, left, st, match)
        if v > out:
            out = v
    return out


@njit(cache=True, nogil=True)
def _first_moves(kinds, below_ptr, below_idx, cover0, tray0, depth, beam, wide, finalists, match, tray_size, fill,
                 pressure, values, frees):
    """Value of every free first tap (NaN for the others) into `values`, and how many tiles it frees into `frees`.
    The best `finalists` are searched again `wide` (if wider than `beam`), as the narrow beam can prune the better
    order of two equivalent plans."""
    n = kinds.shape[0]
    n_kinds = tray0.shape[0]
    cover = cover0.copy()
    tray = tray0.copy()
    free = np.zeros(n, np.bool_)
    free_cnt = np.zeros(n_kinds, np.int64)
    board = np.zeros(n_kinds, np.int64)
    st = np.zeros(3, np.int64)
    for k in range(n_kinds):
        st[0] += tray[k]
    for i in range(n):
        board[kinds[i]] += 1
        if cover[i] == 0:
            free[i] = True
            free_cnt[kinds[i]] += 1
            st[2] += 1
    left = np.zeros(n_kinds, np.int64)
    for k in range(n_kinds):
        left[k] = (-(board[k] + tray[k])) % match + board[k]  # residue still hidden + what lies on the board
    for i in range(n):
        values[i] = np.nan
        frees[i] = 0
    pick = np.zeros(n, np.bool_)
    for width_pass in range(2):
        width = beam
        if width_pass == 1:
            if wide <= beam:
                break
            width = wide
            # the best `finalists` of the narrow pass (equal values: the lower tile first, as Python's stable sort)
            for f in range(finalists):
                best = -1
                for i in range(n):
                    if not np.isnan(values[i]) and not pick[i] and (best < 0 or values[i] > values[best]):
                        best = i
                if best < 0:
                    break
                pick[best] = True
        for i in range(n):
            if not free[i] or (width_pass == 1 and not pick[i]):
                continue
            if width_pass == 0:
                for e in range(below_ptr[i], below_ptr[i + 1]):
                    if cover[below_idx[e]] == 1:
                        frees[i] += 1
            cleared = tray[kinds[i]] == match - 1
            c = _take(i, kinds, below_ptr, below_idx, cover, free, free_cnt, tray, left, st, match, tray_size)
            if c < 0:
                values[i] = LOOK_LOSS
                continue
            v = (TRIPLE_BONUS + TRIPLE_URGENCY * depth if cleared else 0.0) - pressure[st[0]]
            v += _beam(depth - 1, width, kinds, below_ptr, below_idx, cover, free, free_cnt, tray, left, st, match,
                       tray_size, fill, pressure)
            _undo(i, c, kinds, below_ptr, below_idx, cover, free, free_cnt, tray, left, st, match)
            values[i] = v


def lookahead(board: Board, worlds: list, depth: int, beam: int, wide: int, finalists: int, fill, pressure,
              threads: int | None = None, budget: float | None = None) -> list[tuple[np.ndarray, np.ndarray]]:
    """`_first_moves` on every guessed board (`worlds`: one icon list each), on threads; fast cores take more
    boards. Every board is finished; `budget` (seconds) is only a safety cap: boards not started by then stay None
    (one entry per world, in order)."""
    n = len(board.cover0)
    out: list = [None] * len(worlds)
    nxt = [0]
    lock = threading.Lock()
    deadline = None if budget is None else time.monotonic() + budget
    fill, pressure = np.asarray(fill, np.float64), np.asarray(pressure, np.float64)

    def work() -> None:
        while True:
            with lock:
                if nxt[0] >= len(worlds) or (deadline is not None and time.monotonic() > deadline):
                    return
                w = nxt[0]
                nxt[0] += 1
            values, frees = np.empty(n, np.float64), np.empty(n, np.int64)
            _first_moves(np.asarray(worlds[w], np.int64), board.below_ptr, board.below_idx, board.cover0, board.tray,
                         depth, beam, wide, finalists, board.match, board.tray_size, fill, pressure, values, frees)
            out[w] = (values, frees)

    count = min(threads or default_threads(), max(1, len(worlds)))
    pool = [threading.Thread(target=work, daemon=True) for _ in range(count)]
    for t in pool:
        t.start()
    for t in pool:
        t.join()
    return out
