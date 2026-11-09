"""Advice quality (advice.py): the reference boards and the summary."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import advice as A  # noqa: E402
import truth as T  # noqa: E402
import vision as V  # noqa: E402


def test_perfect_recognition_does_not_know_what_is_still_hidden():
    # frame 0: A (kind 1) free; D (kind 4) lies exactly under it; B (kind 2) half under A, far from D's footprint
    free = [[(100, 200, 1)], [(100, 200, 4), (150, 200, 2)], [(150, 200, 2)]]
    game = T.build(["f0", "f1", "f2"], free)
    tiles, perfect, hindsight = A.reference_boards(game, 0, [], won=True)
    kinds = [t.kind for t in tiles]
    a, d = kinds.index(1), kinds.index(4)
    assert hindsight[d].kind == 4 and not hindsight[d].locked and a in hindsight[d].covered_by
    assert perfect[d].kind is None and perfect[d].locked  # nobody can see it yet: not on the perfect board
    assert perfect[a] == hindsight[a] and not perfect[a].covered_by


def test_tiles_the_truth_does_not_know_count_in_lost_games_only():
    free = [[(100, 200, 1)], []]
    game = T.build(["f0", "f1"], free)
    unseen = V.Tile(1, 1, 120, 230, False, kind=5, rx=120, ry=230)  # detected under A, never became free
    tiles, perfect, _ = A.reference_boards(game, 0, [unseen], won=False)
    assert len(tiles) == 2 and perfect[1].kind == 5 and perfect[1].covered_by == (0,)  # as the tool read it
    assert len(A.reference_boards(game, 0, [unseen], won=True)[0]) == 1  # a won game revealed all: a phantom


def test_summary_counts_just_as_good_taps_as_good_advice():
    result = {"stats": {"boards": 10, "same": 7, "as good": 1, "slightly worse": 1, "clearly worse": 1,
                        "perfect = hindsight": 6}, "causes": {"covered tile missed": 2}, "worse taps": []}
    quality, lines = A.summary(result)
    assert quality == 80 and lines[0].endswith("70 %") and "60 %" in lines[-1]
    assert "covered tile missed: 2" in A.report_text(result)


def test_a_tile_no_reader_can_see_blocks_nothing_on_the_perfect_board():
    # A (kind 1) free; H (kind 9) hidden exactly under A; B (kind 2) half under A and also under H
    free = [[(100, 200, 1)], [(100, 200, 9)], [(150, 200, 2)]]
    game = T.build(["f0", "f1", "f2"], free)
    tiles, perfect, hindsight = A.reference_boards(game, 0, [], won=True)
    kinds = [t.kind for t in tiles]
    a, h, b = kinds.index(1), kinds.index(9), kinds.index(2)
    assert set(hindsight[b].covered_by) == {a, h}
    assert perfect[b].covered_by == (a,)  # what a reader sees: only A lies on B
