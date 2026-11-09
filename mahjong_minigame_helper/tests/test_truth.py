"""Ground truth from recorded games (truth.py) on small hand-made sequences."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import truth as T  # noqa: E402


def test_tiles_are_tracked_and_stacked_by_when_they_became_free():
    # frame 0: A (kind 1) free at (100, 200); B lies half under it (not free, so not in the list)
    # frame 1: A still there, C (kind 3) free far away
    # frame 2: A tapped -> B (kind 2) at (150, 200) is free now
    # frame 3: C tapped
    frames = ["f0", "f1", "f2", "f3"]
    free = [
        [(100, 200, 1)],
        [(100, 200, 1), (500, 600, 3)],
        [(150, 201, 2), (501, 600, 3)],
        [(150, 200, 2)],
    ]
    game = T.build(frames, free, breaks=set())
    a, c, b = sorted(game.tiles, key=lambda t: t.first_free * 10 + t.x / 1000)
    assert (a.kind, a.first_free, a.removed) == (1, 0, 2)
    assert (b.kind, b.first_free, b.removed) == (2, 2, None)
    assert (c.kind, c.first_free, c.removed) == (3, 1, 3)
    assert T.overlaps(a, b) and T.above(a, b)
    assert {t.kind for t in game.at(0)} == {1, 2, 3}  # B and C existed from the start, covered / unseen
    assert game.covering(b, 0) == [a] and game.covering(b, 2) == []
    assert 0.4 < game.visible_share(b, 0) < 0.6  # A hides about half of B
    assert game.visible_share(b, 2) == 1.0


def test_pile_tiles_a_few_pixels_apart_are_different_tiles():
    # a pile: the front tile (kind 1) is tapped and the next one shows up 8 px further right with another icon
    free = [[(100, 700, 1)], [(108, 700, 4)]]
    game = T.build(["f0", "f1"], free, breaks=set())
    assert sorted(t.kind for t in game.tiles) == [1, 4]


def test_same_spot_different_icon_is_the_tile_below_and_a_dialog_ends_nothing():
    free = [[(100, 200, 1)], [(100, 200, 5)], None, [(100, 200, 5)]]
    game = T.build(["a", "b", "c", "d"], free, breaks=set())
    assert [(t.kind, t.removed) for t in game.tiles] == [(1, 1), (5, None)]
    assert game.segments == [0, 0, None, 0]
    assert len(game.at(3)) == 1 and game.at(2) == []


def test_a_new_game_after_a_screen_without_board_starts_over():
    board = [(100, 200, 1), (300, 200, 2), (500, 200, 3)]
    other = [(150, 250, 4), (350, 250, 5), (500, 200, 3)]  # one spot and icon alike by chance
    game = T.build(["a", "b", "c"], [board, None, other])
    assert game.segments == [0, None, 1]
    assert all(t.removed is None for t in game.tiles if t.segment == 0)


def test_parked_cards_are_there_from_the_remove_on_and_hide_the_ones_below():
    board = [(100, 200, 1), (300, 200, 2)]
    first = [(232, 994, 3), (333, 994, 4)]
    second = [(232, 974, 5), (333, 974, 6)]
    frames = [board, None, board + first, board + second, board + [(333, 974, 6), (232, 994, 3)]]
    game = T.build(list("abcde"), frames)
    assert game.segments == [0, None, 0, 0, 0]
    low = next(t for t in game.tiles if t.kind == 3)
    top = next(t for t in game.tiles if t.kind == 5)
    assert low.appeared == 2 and low.removed is None and not low.present(0)  # not there before the Remove
    assert top.appeared == 3 and top.removed == 4 and T.above(top, low)
    assert game.covering(low, 3) == [top] and game.covering(low, 4) == []
    assert len(game.tiles) == 6  # the card below shows again: the same tile, not a new one


def test_scoring_against_the_truth():
    import evaluate as E

    free = [[(100, 200, 1)], [(150, 200, 2)]]
    game = T.build(["f0", "f1"], free, breaks=set())
    # frame 0: the tool found A (free) and B (covered, read right, with A on top); frame 1: B free
    readings = [
        {"tiles": [{"x": 100, "y": 200, "free": True, "kind": 1, "covered_by": []},
                   {"x": 151, "y": 201, "free": False, "kind": 2, "covered_by": [0]},
                   {"x": 400, "y": 400, "free": False, "kind": None, "covered_by": []}]},
        {"tiles": [{"x": 150, "y": 200, "free": True, "kind": 2, "covered_by": []}]},
    ]
    from collections import defaultdict

    stats = defaultdict(lambda: defaultdict(int))
    E.score(game, readings, stats)
    assert stats["board:free"]["tiles"] == 2 and stats["board:free"]["icon right"] == 2
    assert stats["board:half visible"]["found"] == 1 and stats["board:half visible"]["icon right"] == 1
    assert stats["_"]["stacking pairs"] == 1 and stats["_"]["stacking right"] == 1
    assert stats["_"]["unverified detections"] == 1  # the tile at (400, 400) is not known
    text = E.report_text({"buckets": {k: dict(v) for k, v in stats.items() if k != "_"}, "overall": dict(stats["_"])})
    assert "half visible" in text and "Confidence:" in text and "Which tile lies on top: 100 %" in text


def test_a_shuffle_is_recognised_without_a_note_from_the_recorder():
    before = [(100, 200, 1), (300, 200, 2), (500, 200, 3), (700, 200, 4), (100, 400, 5)]
    after = [(100, 200, 4), (300, 200, 1), (500, 200, 2), (700, 200, 5), (100, 400, 5)]  # same spots, four swapped
    game = T.build(["a", "b"], [before, after], breaks=set())
    assert game.segments == [0, 1]
    first = [t for t in game.tiles if t.segment == 0]
    assert all(t.removed is None for t in first)  # nothing was tapped: the tiles stayed, only their icons changed


def test_a_tile_put_back_from_the_tray_is_the_same_tile():
    a, b = (100, 200, 1), (400, 200, 2)
    frames = [[a, b], [b], [b], [a, b]]  # A tapped, then put back two frames later (Recall)
    game = T.build(["f0", "f1", "f2", "f3"], frames, breaks=set())
    assert sorted(t.kind for t in game.tiles) == [1, 2]  # still two tiles, not three
    tile_a = next(t for t in game.tiles if t.kind == 1)
    assert tile_a.removed is None and tile_a.first_free == 0


def test_three_cards_stacked_by_remove_are_no_shuffle():
    """Remove parks the tray's cards above it; a second Remove stacks 3 new cards on those 3 spots."""
    board = [(100 * i, 200, i) for i in range(1, 8)]
    parked = [(150, 900, 1), (250, 900, 2), (350, 900, 3)]
    restacked = [(150, 900, 4), (250, 900, 5), (350, 900, 6)]
    game = T.build(["a", "b"], [board + parked, board + restacked], breaks=set())
    assert game.segments == [0, 0]


def test_cards_parked_on_spots_of_used_ones_and_lone_parked_cards():
    board = [(100, 200, 1), (300, 200, 2)]
    frames = [
        board,
        board + [(434, 994, 7)],  # a Remove with one card in the tray
        board + [(232, 994, 3), (333, 994, 4), (434, 974, 5)],  # two more, and one on the parked 7
        board,  # all three top cards used, and the 7 ... (taken right after)
        board + [(232, 994, 6), (333, 994, 8)],  # a new Remove on the spots of the used cards
    ]
    game = T.build(list("abcde"), frames)
    assert all(t.appeared is not None for t in game.tiles if t.y > 900)
    assert [t.kind for t in game.at(0)] == [1, 2]  # no parked card lay there before the first Remove
    assert [t.kind for t in game.at(3)] == [1, 2]  # the 7 was used right after the 5 on it


def test_cards_parked_before_the_recording_started_do_not_hide_later_ones():
    """The recording starts mid-game with cards already parked; they are used up, and much later a Remove parks new
    cards on the same spots: those were not lying under the old ones."""
    board = [(100, 200, 1), (300, 200, 2), (500, 200, 3)]
    old = [(232, 994, 4), (333, 994, 5)]
    frames = [board + old] * 3 + [board] * 10 + [board + [(232, 994, 6), (333, 994, 7)]]
    game = T.build([str(k) for k in range(len(frames))], frames)
    new = [t for t in game.tiles if t.kind in (6, 7)]
    assert all(t.appeared == 13 for t in new)
    assert all(t.kind in (1, 2, 3) for t in game.at(5))  # nothing parked in between


def test_long_runs_report_their_progress_in_steps():
    from multiprocessing.dummy import Pool

    import evaluate as E

    lines = []
    with Pool(2) as pool:
        out = E.mapped(pool, abs, list(range(-40, 0)), "reading", log=lines.append)
    assert out == list(range(40, 0, -1))  # the results in order, as pool.map gives them
    assert lines[0] == "progress reading: 0 %" and lines[-1] == "progress reading: 100 %"
    assert len(lines) <= 100 // E.PROGRESS_STEP + 1  # a line every few percent, not one per board


def test_vertical_piles_are_piles_too():
    t = [T.TruthTile(100, 545 + 10 * k, 1, 0, 0, None, 0) for k in range(3)]
    parked = [T.TruthTile(232, 994, 2, 0, 0, None, 0), T.TruthTile(232, 974, 3, 0, 0, None, 0)]
    assert all(T.in_pile(x, t) for x in t)
    assert not T.in_pile(parked[0], parked)  # a card stacked on a parked one (20 px) is no pile
