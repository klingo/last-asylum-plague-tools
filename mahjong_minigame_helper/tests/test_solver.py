import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver import SnapTile, recommend, residue_hidden, sample_kinds  # noqa: E402


def tiles(*specs):
    """specs: (kind, covered_by...) per tile."""
    return [SnapTile(s[0], tuple(s[1:])) for s in specs]


def test_completes_a_triple_from_the_tray():
    # tray holds a pair of kind 0; a free kind-0 tile completes it
    ts = tiles((0,), (1,), (1,), (1,), (0,), (0,))
    moves = recommend(ts, [0, 0], n_kinds=2, depth=3)
    assert moves[0].tile in (0, 4, 5)


def test_prefers_the_tile_that_unlocks_a_triple():
    # tile 0 (kind 1) covers two kind-0 tiles; tile 3 is a free kind-2 loner; tray already has a kind-0 single
    ts = tiles((1,), (0, 0), (0, 0), (2,), (1,), (1,), (2,), (2,))
    moves = recommend(ts, [0], n_kinds=3, depth=5)
    assert moves[0].tile in (0, 4, 5)  # opening the kind-1 stack beats starting kind 2


def test_avoids_filling_the_tray_with_singles():
    # tray has five singles; two more kind-0 tiles complete a triple, kind 5 tiles would overflow the tray
    ts = tiles((5,), (5,), (5,), (0,), (0,))
    moves = recommend(ts, [0, 1, 2, 3, 4], n_kinds=6, depth=4)
    assert moves[0].tile in (3, 4)
    assert moves[0].loss_rate == 0.0
    assert next(m for m in moves if m.tile == 0).loss_rate == 1.0


def test_detects_unavoidable_loss():
    # tray full of six distinct singles, only a distinct seventh kind is free: any tap loses
    ts = tiles((6,), (6,), (6,))
    moves = recommend(ts, [0, 1, 2, 3, 4, 5], n_kinds=7, depth=2)
    assert moves[0].loss_rate == 1.0


def test_unknown_tiles_are_sampled_toward_complete_triples():
    ts = tiles((0,), (0,), (None,), (1,), (1,), (1,))
    rng = random.Random(1)
    draws = [sample_kinds(ts, [], 2, rng)[2] for _ in range(300)]
    assert draws.count(0) > draws.count(1) * 3  # kind 0 needs one more copy, kind 1 is complete


def test_hidden_copies_follow_from_triples():
    assert residue_hidden([3, 2, 1, 0, 4]) == [0, 1, 2, 0, 2]


def test_free_tiles_and_freed_count():
    ts = tiles((0,), (1, 0), (1, 0), (1, 1))
    moves = recommend(ts, [], n_kinds=2, depth=2)
    assert [m.tile for m in moves] == [0] and moves[0].frees == 2  # only 0 is free; it frees 1 and 2


def test_third_tile_clears_the_triple_and_overflow_is_refused():
    assert recommend(tiles((0,), (1,)), [0, 0], n_kinds=2, depth=1)[0].tile == 0  # completes the set
    assert recommend(tiles((6,)), [0, 1, 2, 3, 4, 5], n_kinds=7, depth=1)[0].loss_rate == 1.0  # 7th card: full


# first-move values of the Python look-ahead it replaced (`_World.first_moves(5, 3)`), on seeded random boards
PYTHON_VALUES = [
    ([1, 3, 4, 3], {0: 249.5, 1: 237.5, 6: 249.5, 7: 271.5, 12: 267.5, 14: 228.0, 17: 229.0}),
    ([], {0: 104.0, 1: 104.0, 5: 104.0, 10: 103.0, 11: -19.0, 14: -18.5}),
    ([3, 0, 3], {0: 272.0, 1: 252.0, 5: 239.5, 6: 260.0, 7: 260.0, 8: 252.0, 9: 260.0, 12: 260.0, 14: 260.0, 15: 239.5}),
    ([4, 4, 2, 1], {0: 351.5, 1: 351.5, 4: 351.5, 5: 373.5, 9: 351.5, 10: 351.5, 13: 239.0}),
]


def test_the_compiled_look_ahead_gives_the_values_of_the_python_one():
    import math

    import solver as S
    import solver_fast as F

    rng = random.Random(7)
    fill, pressure = S._lookahead_arrays()
    for tray, expected in PYTHON_VALUES:
        board_tiles, kinds = random_board(rng, n_sets=rng.randint(4, 7))
        assert [rng.randrange(5) for _ in range(rng.randint(0, 4))] == tray  # (the same draws as when recorded)
        board = F.Board(board_tiles, tray, 5, S.TRAY_SIZE, S.MATCH)
        values, _ = F.lookahead(board, [kinds], 5, 3, 0, 0, fill, pressure, threads=1)[0]
        got = {i: round(float(v), 6) for i, v in enumerate(values) if not math.isnan(v)}
        assert got == expected


def test_prefers_the_order_that_keeps_the_tray_roomier():
    """From a real game: tray [cake, potion, potion, lollipop]. Hand A frees a potion (triple at once); the pumpkin P
    frees a second hand. Either order clears the same triples, but pumpkin-first runs at 6/7 slots meanwhile."""
    cake, potion, lolly, hand, pumpkin = 0, 1, 2, 3, 4
    ts = tiles(
        (hand,),  # 0: hand A, free; covers the potion
        (potion, 0),  # 1: potion, freed by A
        (pumpkin,),  # 2: pumpkin P, free; covers a hand
        (hand, 2),  # 3: hand, freed by P
        (hand,),  # 4: hand, free
    )
    moves = recommend(ts, [cake, potion, potion, lolly], n_kinds=5, depth=7, seed=0)
    assert moves[0].tile == 0


def test_auto_click_confidence_and_click_position():
    from types import SimpleNamespace

    import board as B
    import vision as V
    from solver import LOSS, Move

    free = V.Tile(5, 5, 300.0, 400.0, True, kind=1, rx=303.0, ry=402.0)
    covered = V.Tile(5, 6, 300.0, 450.0, False, kind=1)
    frame = SimpleNamespace(tiles=[free, covered])

    def analysis(moves):
        return SimpleNamespace(frame=frame, moves=moves, tray_kinds=[])

    ok = Move(tile=0, value=250.0, loss_rate=0.0, frees=1, kind=1)
    assert B.confidence(analysis([ok])) == (True, "")
    assert not B.confidence(analysis([]))[0]
    assert B.confidence(analysis([Move(0, 250.0, 0.4, 1, 1)])) == (False, "risk 40%")
    assert B.confidence(analysis([Move(0, 250.0, 0.1, 1, 1)])) == (True, "")  # a small risk: noise, keep going
    assert B.confidence(analysis([Move(0, LOSS, 1.0, 1, 1)]))[0] is False
    assert B.confidence(analysis([Move(0, 250.0, 0.0, 1, None)])) == (False, "its icon is not read")
    assert B.confidence(analysis([Move(1, 250.0, 0.0, 1, 1)])) == (False, "best tile is not free")
    # the middle of the face: ring-match corner + (47, 46), canonical px -> screen px of the game area
    assert B.click_point(free, 0.5, (60, 40)) == (60 + 700, 40 + 896)  # (303+47)/0.5, (402+46)/0.5
    assert B.click_point(free, 760 / 760, (0, 0)) == (350, 448)


def test_parked_cards_are_only_suggested_to_close_a_set():
    """A card parked by Remove takes no tray slot where it is: it is only suggested when its set can be completed
    right away (tray + free tiles), or when every other tap is riskier."""
    import solver as S

    a, b, c = 0, 1, 2
    moves = S.recommend([S.SnapTile(b, parked=True), S.SnapTile(c), S.SnapTile(a)], [b], 3, samples=1, depth=3)
    assert moves[0].tile != 0 and moves[-1].tile == 0  # pairing it with the tray's B gains nothing yet: it waits
    moves = S.recommend([S.SnapTile(a, parked=True), S.SnapTile(a), S.SnapTile(c)], [a], 3, samples=1, depth=3)
    assert moves[0].tile in (0, 1)  # tray A + free A + parked A close a set: it may come down
    moves = S.recommend([S.SnapTile(b, parked=True)], [b], 3, samples=1, depth=3)
    assert [m.tile for m in moves] == [0]  # nothing else is free: it must come down


def test_a_tap_that_completes_a_set_is_clicked_even_with_risk_ahead():
    """The risk is that of the taps after it; completing a set from the tray only frees slots."""
    from types import SimpleNamespace

    import board as B
    import solver as S
    import vision as V

    tiles = [V.Tile(0, 0, 100, 100, True, kind=1), V.Tile(2, 0, 200, 100, True, kind=2)]
    a = SimpleNamespace(frame=SimpleNamespace(tiles=tiles), tray_kinds=[0, 1, 1],
                        moves=[S.Move(0, -500.0, 0.6, 0, 1), S.Move(1, -900.0, 0.8, 0, 2)])
    assert B.confidence(a) == (True, "")
    a.moves = [S.Move(1, -400.0, 0.4, 0, 2)]  # the best tap only adds a new icon to the tray: wait for the player
    assert B.confidence(a) == (False, "risk 40%")


def test_booster_risks_tell_when_a_remove_saves_the_game():
    """Tray 6/7 with six singles; the board offers only another 3 (one of the tray's icons): the tray overflows
    before the set is complete. A Remove parks the first three tray cards and leaves room; a Refresh only shuffles
    the two 3s among themselves."""
    import solver as S

    tray = [0, 1, 2, 3, 4, 5]
    tiles = [S.SnapTile(3), S.SnapTile(3)]
    risks = S.booster_risks(tiles, tray, 6, [None, None, None], True, samples=2, seed=0)
    assert risks == {"now": 1.0, "Remove": 0.0, "Refresh": 1.0}
    assert "Remove" not in S.booster_risks(tiles, tray, 6, [None, None, None], False, samples=1, seed=0)  # blocked


def test_the_whole_game_search_finds_a_finish_or_proves_there_is_none():
    import solver as S
    import solver_fast as F

    three = [S.SnapTile(0), S.SnapTile(0), S.SnapTile(0)]
    assert F.Board(three, [], 7, S.TRAY_SIZE, S.MATCH).search([0, 0, 0], 1000)[0] == F.WIN
    full = F.Board(three, [1, 2, 3, 4, 5, 6], 7, S.TRAY_SIZE, S.MATCH)  # 6/7: the first 0 fills the tray
    assert full.search([0, 0, 0], 1000)[0] == F.NO_WIN


def test_deepen_puts_the_tap_with_a_winning_line_first():
    """Tray 1 2 3 4 5 (5/7), free: two 1s and a 6. The 6 first leaves 6/7 and no tap that fits; the 1s first win.
    With a look-ahead of one tap the dead end lies beyond its horizon; the whole-game search sees it."""
    import solver as S

    tiles = [S.SnapTile(6), S.SnapTile(1), S.SnapTile(1)]
    tray = [1, 2, 3, 4, 5]
    moves = S.recommend(tiles, tray, 7, samples=1, depth=1)
    assert next(m for m in moves if m.tile == 0).loss_rate == 0  # the short look-ahead does not see it
    moves = S.deepen(tiles, tray, 7, moves, budget=1.0, seed=0)
    assert moves[0].tile in (1, 2) and moves[0].win_rate == 1.0
    assert next(m for m in moves if m.tile == 0).win_rate == 0.0  # no winning line starts with the 6


def random_board(rng, n_sets=6, n_kinds=5):
    """Tiles in layers: each lies under 0-2 tiles of the layers above; icons in complete sets of 3."""
    import solver as S

    kinds = [k % n_kinds for k in range(3 * n_sets)]
    rng.shuffle(kinds)
    tiles = []
    for i, k in enumerate(kinds):
        above = sorted(set(rng.sample(range(i), min(i, rng.randint(0, 2))))) if i else []
        tiles.append(S.SnapTile(k, tuple(above)))
    return tiles, kinds


def winnable(tiles, kinds, tray, taken=frozenset(), memo=None):
    """Exhaustive reference: can every tile be taken without the tray overflowing? (Small boards only.)"""
    import solver as S

    memo = {} if memo is None else memo
    if taken in memo:
        return memo[taken]
    free = [i for i, t in enumerate(tiles) if i not in taken and all(c in taken for c in t.covered_by)]
    if not free:
        return True
    ok = False
    for i in free:
        k = kinds[i]
        if tray.count(k) == S.MATCH - 1:
            nxt = [x for x in tray if x != k]
        elif len(tray) + 1 >= S.TRAY_SIZE:
            continue
        else:
            nxt = tray + [k]
        if winnable(tiles, kinds, nxt, taken | {i}, memo):  # (the tray follows from the taken tiles)
            ok = True
            break
    memo[taken] = ok
    return ok


def test_the_compiled_search_agrees_with_an_exhaustive_one():
    import random

    import solver as S
    import solver_fast as F

    rng = random.Random(1)
    outcomes = set()
    for _ in range(300):
        tiles, kinds = random_board(rng, n_sets=rng.randint(3, 6))
        tray = [rng.randrange(5) for _ in range(rng.randint(0, 4))]
        status, first, _ = F.Board(tiles, tray, 5, S.TRAY_SIZE, S.MATCH).search(kinds, 10**7)
        assert status == (F.WIN if winnable(tiles, kinds, tray) else F.NO_WIN)
        if status == F.WIN:  # the first tap of the line it found is free
            assert first == -1 or not tiles[first].covered_by
        outcomes.add(status)
    assert outcomes == {F.WIN, F.NO_WIN}  # both kinds of board were tested


def test_guessed_boards_without_a_winning_line_do_not_raise_the_risk():
    """With hidden icons the guessed boards are random deals, nearly never winnable: no risk figure. With nothing to
    guess, no winning line is a proven loss."""
    import solver as S

    tray = [1, 2, 3, 4, 5]  # 5/7, and the two free tiles are new icons: tapping both fills the tray
    known = [S.SnapTile(6), S.SnapTile(0)]
    moves = S.deepen(known, tray, 7, S.recommend(known, tray, 7, samples=1, depth=1), budget=0.5, seed=0)
    assert moves[0].loss_rate == 1.0
    hidden = [S.SnapTile(6), S.SnapTile(0), S.SnapTile(None, (0,))]
    look = S.recommend(hidden, tray, 7, samples=4, depth=1, seed=0)
    before = {m.tile: m.loss_rate for m in look}
    moves = S.deepen(hidden, tray, 7, look, budget=0.5, seed=0)
    assert all(m.loss_rate == before[m.tile] for m in moves)


def test_hidden_tiles_get_exactly_the_counted_mix():
    """The game deals every icon equally often: with the counts of what is still hidden, the guesses use that mix."""
    ts = tiles((0,), (None,), (None,), (None,), (None,), (1,))
    rng = random.Random(0)
    for _ in range(50):
        kinds = sample_kinds(ts, [], 4, rng, hidden_counts=[0, 2, 1, 1])
        assert sorted(kinds[1:5]) == [1, 1, 2, 3]
    trimmed = sample_kinds(ts, [], 4, rng, hidden_counts=[0, 3, 3, 0])  # more counted than unread (undetected tiles)
    assert all(k in (1, 2) for k in trimmed[1:5])
    short = sample_kinds(ts, [], 4, rng, hidden_counts=[0, 1, 0, 0])  # fewer: the rest is drawn as without counts
    assert 1 in short[1:5] and None not in short
