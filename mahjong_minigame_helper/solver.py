"""Mahjong minigame solver: which tile to tap next.

Rules: tapping a free tile moves it into the tray (TRAY_SIZE slots, 7 in the Halloween Ball); MATCH equal tiles in
the tray vanish (3, "a triple" below); a full tray without a match loses the game. A tile is free once every tile
covering it is gone. Both numbers come from the game profile (`game_profile.activate`).

The board is only partly known, so the search runs on *determinizations*: tiles whose kind could not be read are
assigned kinds at random (a kind that still needs copies to complete its triples is more likely), and every kind
is assumed to exist in multiples of MATCH, which also tells how many copies are still hidden under other tiles
(`hidden`). Each sample is searched a few taps deep (beam search); a first move is scored by its average best line.

No OpenCV / GUI here, so it can be tested on tiny hand-made boards.
"""

from __future__ import annotations

import random
import time
from collections import Counter
from dataclasses import dataclass

TRAY_SIZE = 7
MATCH = 3  # equal tiles that vanish together
TRIPLE_BONUS = 100.0
TRIPLE_URGENCY = 8.0  # extra per remaining tap of depth: a triple now beats the same triple a few taps later
LOSS = -1000.0
WIN = 500.0
FILL_BY_FREE = {1: 40, 2: 20, 3: 10, 4: 5, 5: 2}  # leaf penalty by tray slots still free (more = 0)
PRESSURE_BY_FREE = {1: 45, 2: 14, 3: 4, 4: 1}  # paid for every tap that leaves this many slots free: a plan that
# runs at one free slot for several taps is one wrong guess (an unread or hidden tile) away from a lost game


def fill_penalty(size: int) -> float:
    return FILL_BY_FREE.get(TRAY_SIZE - size, 0)


def path_pressure(size: int) -> float:
    return PRESSURE_BY_FREE.get(TRAY_SIZE - size, 0)


@dataclass
class SnapTile:
    """One tile of the snapshot. `covered_by` are indices into the snapshot's tile list."""

    kind: int | None
    covered_by: tuple[int, ...] = ()
    locked: bool = False  # drawn as covered, but no covering tile is known: never pickable
    parked: bool = False  # put aside above the tray (Remove): only suggested when it helps close a set


@dataclass
class Move:
    tile: int
    value: float  # average best line value over the samples (higher is better)
    loss_rate: float  # share of samples whose best line still ends in a lost game
    frees: int  # tiles this tap uncovers
    kind: int | None  # kind of the tile in the samples where it is known (None if it varies)
    win_rate: float | None = None  # share of the sampled boards on which a whole winning line follows (`deepen`)


def residue_hidden(counts: list[int]) -> list[int]:
    """Copies of each kind that must still be hidden somewhere if kinds come in groups of MATCH."""
    return [(-c) % MATCH for c in counts]


def sample_kinds(tiles: list[SnapTile], tray: list[int], n_kinds: int, rng: random.Random,
                 hidden_counts: list[int] | None = None) -> list[int]:
    """Kinds for every tile; the unread ones are drawn so that kinds tend towards complete triples. With
    `hidden_counts` (how many of each icon are still hidden: the game deals every icon equally often) the unread
    tiles get exactly that mix, at random places; if it holds more icons than there are unread tiles (some hidden ones
    were not detected), a random part of it; if fewer, the rest is drawn as without counts."""
    kinds = [t.kind for t in tiles]
    if hidden_counts is not None:
        unknown = [i for i, k in enumerate(kinds) if k is None]
        pool = [k for k, c in enumerate(hidden_counts) for _ in range(max(0, c))]
        rng.shuffle(pool)
        rng.shuffle(unknown)
        for i, k in zip(unknown, pool):
            kinds[i] = k
        if len(pool) >= len(unknown):
            return kinds  # type: ignore[return-value]
        # the rest: as without counts, around what is placed now
    counts = [0] * n_kinds
    for k in kinds:
        if k is not None:
            counts[k] += 1
    for k in tray:
        counts[k] += 1
    unknown = [i for i, k in enumerate(kinds) if k is None]
    if not unknown:
        return kinds  # type: ignore[return-value]
    # The copies that must still exist (every kind comes in groups of MATCH) lie somewhere among the unknown tiles,
    # any further unknowns come in whole groups of a random kind; which unknown tile is which is random. (Drawing
    # each tile towards a needed kind instead makes a pile of 20 unknown tiles look like 20 perfect matches.)
    pool = [k for k, need in enumerate(residue_hidden(counts)) for _ in range(need)]
    while len(pool) < len(unknown):
        pool += [rng.randrange(n_kinds)] * MATCH
    rng.shuffle(pool)
    for i, k in zip(unknown, pool):
        kinds[i] = k
    return kinds  # type: ignore[return-value]


LOOK_SAMPLES = 500  # guessed boards for the look-ahead, all always searched (risk of one board over 12 runs: 2 boards
# 0-50 %, 40: 32-50 %, 200: 33-45 %, 1000: 35-41 %; 500 takes 0.1-0.5 s, the biggest boards (Stage 13 start) ~8 s)
LOOK_DEPTH = 7  # taps the look-ahead looks ahead (8 costs ~10x, 9 ~70x on big boards: the whole-game search
# covers the long range instead)
LOOK_BEAM = 4  # taps it follows at every step (the best `LOOK_FINALISTS` first taps get `LOOK_WIDE`)
LOOK_WIDE = 8
LOOK_FINALISTS = 3
LAST_LOOKAHEAD = [0, 0]  # (guessed boards searched, asked for) of the last `recommend`: fewer if the time cap cut in


def _lookahead_arrays() -> tuple[list[float], list[float]]:
    return [fill_penalty(s) for s in range(TRAY_SIZE + 1)], [path_pressure(s) for s in range(TRAY_SIZE + 1)]


def recommend(
    tiles: list[SnapTile],
    tray: list[int],
    n_kinds: int,
    samples: int | None = None,
    depth: int | None = None,
    beam: int | None = None,
    wide: int | None = None,
    finalists: int | None = None,
    seed: int | None = None,
    budget: float | None = None,
    threads: int | None = None,
    hidden_counts: list[int] | None = None,
) -> list[Move]:
    """All pickable tiles, best first. `hidden_counts`: see `sample_kinds`. On `samples` guessed boards (the unread icons drawn by `sample_kinds`), a
    beam search `depth` taps deep scores every first tap (compiled, on `threads` cores: `solver_fast.lookahead`);
    `value` is the mean, `loss_rate` the share of guessed boards on which every line overflows the tray. Every
    guessed board is searched to the end; `budget` (seconds) is only a safety cap (`LAST_LOOKAHEAD` tells)."""
    import solver_fast as F

    samples, depth = samples or LOOK_SAMPLES, depth or LOOK_DEPTH
    beam, wide, finalists = beam or LOOK_BEAM, LOOK_WIDE if wide is None else wide, finalists or LOOK_FINALISTS
    rng = random.Random(seed)
    if not any(t.kind is None for t in tiles):
        samples = 1  # nothing to guess
    worlds = [sample_kinds(tiles, tray, n_kinds, rng, hidden_counts) for _ in range(samples)]  # drawn first: the same seed, the same
    board = F.Board(tiles, tray, n_kinds, TRAY_SIZE, MATCH)  # answer, however the threads run
    fill, pressure = _lookahead_arrays()
    results = F.lookahead(board, worlds, depth, beam, wide, finalists, fill, pressure, threads, budget)
    done = [(kinds, r) for kinds, r in zip(worlds, results) if r is not None]
    LAST_LOOKAHEAD[:] = [len(done), samples]
    if not done:
        return []
    totals: dict[int, float] = {}
    losses: dict[int, int] = {}
    kinds_seen: dict[int, set[int]] = {}
    frees: dict[int, int] = {}
    for kinds, (values, freed) in done:
        for i in range(len(tiles)):
            v = values[i]
            if v != v:  # NaN: not free
                continue
            totals[i] = totals.get(i, 0.0) + float(v)
            losses[i] = losses.get(i, 0) + (v <= LOSS / 2)
            kinds_seen.setdefault(i, set()).add(kinds[i])
            frees[i] = int(freed[i])
    moves = [
        Move(
            tile=i,
            value=totals[i] / len(done),
            loss_rate=losses[i] / len(done),
            frees=frees[i],
            kind=next(iter(kinds_seen[i])) if len(kinds_seen[i]) == 1 else None,
        )
        for i in totals
    ]
    # Completing a match from the tray is never worse than waiting (it only frees slots), so those taps lead.
    # Ties (common: several lines clear the same triples) go to taps that add to tiles already in the tray, then
    # to the tap that uncovers more tiles.
    held = {k: tray.count(k) for k in set(tray)}

    def rank(m: Move):
        count = held.get(m.kind, 0) if m.kind is not None else 0
        return (count != MATCH - 1, -round(m.value, 1), count == 0, -m.frees, m.tile)

    moves.sort(key=rank)
    return _parked_last(moves, tiles, tray)


def _parked_last(moves: list[Move], tiles: list[SnapTile], tray: list[int]) -> list[Move]:
    """A parked card (Remove) is safe where it is and takes no slot: it is only suggested when it helps close a set
    right away (tray + free tiles complete it) or every other tap is riskier. (The searches may still use it later:
    they often need those cards, and banning them there makes the plans worse.)"""
    held = Counter(tray)
    free_of = Counter(t.kind for t in tiles if not t.covered_by and not t.locked and t.kind is not None)

    def idle(m: Move) -> bool:
        return tiles[m.tile].parked and (m.kind is None or held[m.kind] + free_of[m.kind] < MATCH)

    other = next((m for m in moves if not idle(m)), None)
    if other is not None:
        moves.sort(key=lambda m: idle(m) and m.loss_rate >= other.loss_rate)  # stable: the order stays otherwise
    return moves


def deepen(
    tiles: list[SnapTile],
    tray: list[int],
    n_kinds: int,
    moves: list[Move],
    budget: float = 5.0,
    seed: int | None = None,
    positions: int | None = None,
    threads: int | None = None,
    hidden_counts: list[int] | None = None,
) -> list[Move]:
    """Look to the end of the game, not only `depth` taps: the compiled whole-game search (`solver_fast`, numba, on
    `threads` cores) tries every tap on as many guessed boards as fit in `budget` seconds (`positions` = the cap per
    board). The taps that still win on the most guessed boards come first, the look-ahead's order (`moves`, from
    `recommend`) breaks ties. `win_rate` = share of the boards on which the tap still wins. With nothing to guess,
    the one board gets the whole budget, and no winning line there is a proven loss (`loss_rate` 1). With guessed
    icons the risk stays the look-ahead's: the guessed boards are random deals, almost never winnable (Stage 9,
    board 60: 1'993 of 2'003 without a winning line in a game that was won), so their share is no risk figure."""
    if not moves:
        return moves
    import solver_fast as F

    guess = lambda ts, tr, nk, rng: sample_kinds(ts, tr, nk, rng, hidden_counts)  # noqa: E731
    votes, lost, boards = F.deepen(tiles, tray, n_kinds, moves, guess, TRAY_SIZE, MATCH, budget, seed,
                                   positions or FAST_POSITIONS, threads)
    certain = not any(t.kind is None for t in tiles)
    return _ranked(moves, tiles, tray, votes, lost if certain else 0, max(boards, 1))


def _ranked(moves: list[Move], tiles: list[SnapTile], tray: list[int], votes: Counter, lost: int, boards: int) -> list[Move]:
    order = {m.tile: n for n, m in enumerate(moves)}
    for m in moves:
        m.win_rate = votes[m.tile] / boards
        m.loss_rate = max(m.loss_rate, lost / boards)
    moves = sorted(moves, key=lambda m: (-votes[m.tile], order[m.tile]))
    return _parked_last(moves, tiles, tray)


FAST_POSITIONS = 300_000  # cap per guessed board for the compiled search (a fraction of a second on one core)


BOOSTER_SAMPLES = 200  # guessed boards per option of the booster check (now / Remove / Refresh: 3 look-aheads; with
# 500 each a risky board of Stage 13's size would take ~25 s)
REMOVE_CARDS = 3  # cards a Remove takes from the front of the tray
PARK_LEVELS = 3  # Remove stacks at most this many cards on a parking spot; then it is blocked


def booster_risks(
    tiles: list[SnapTile],
    tray: list[int],
    n_kinds: int,
    park_tops: list[int | None],
    can_remove: bool,
    samples: int | None = None,
    depth: int | None = None,
    beam: int | None = None,
    seed: int | None = None,
    budget: float | None = None,
    threads: int | None = None,
) -> dict[str, float]:
    """Risk (share of guessed boards on which every line of `depth` taps overflows the tray) as it is ("now"),
    after a Remove and after a Refresh, on the same guessed boards so they compare fairly. A Remove parks the first
    REMOVE_CARDS tray cards on the parking spots, the i-th on top of `park_tops[i]` (the card parked there before,
    if any). A Refresh shuffles the icons of the board tiles; the tray and the parked cards stay."""
    import solver_fast as F

    samples, depth, beam = samples or BOOSTER_SAMPLES, depth or LOOK_DEPTH, beam or LOOK_BEAM
    rng = random.Random(seed)
    moved = tray[:REMOVE_CARDS]
    parked_tiles = list(tiles)
    for n, k in enumerate(moved):
        parked_tiles.append(SnapTile(k, parked=True))
        below = park_tops[n] if n < len(park_tops) else None
        if below is not None:  # the new card lies on the one parked there before
            t = parked_tiles[below]
            parked_tiles[below] = SnapTile(t.kind, t.covered_by + (len(parked_tiles) - 1,), t.locked, t.parked)
    board = [i for i, t in enumerate(tiles) if not t.parked]
    worlds: dict[str, list] = {"now": [], "Refresh": [], "Remove": []}
    for _ in range(samples):
        kinds = sample_kinds(tiles, tray, n_kinds, rng)
        shuffled = list(kinds)
        icons = [kinds[i] for i in board]
        rng.shuffle(icons)
        for i, k in zip(board, icons):
            shuffled[i] = k
        worlds["now"].append(kinds)
        worlds["Refresh"].append(shuffled)
        worlds["Remove"].append(kinds + moved)
    names = ["now", "Remove", "Refresh"] if can_remove and moved else ["now", "Refresh"]
    fill, pressure = _lookahead_arrays()
    out = {}
    for name in names:
        b = F.Board(parked_tiles, tray[REMOVE_CARDS:], n_kinds, TRAY_SIZE, MATCH) if name == "Remove" else \
            F.Board(tiles, tray, n_kinds, TRAY_SIZE, MATCH)
        results = [r for r in F.lookahead(b, worlds[name], depth, beam, 0, 0, fill, pressure, threads, budget) if r is not None]
        lost = sum(1 for values, _ in results if not any(v > LOSS / 2 for v in values if v == v))
        out[name] = lost / max(len(results), 1)
    return out
