"""Training from recordings (icons with several pictures, learning rules) and the board memory."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import kinds as K  # noqa: E402
import train  # noqa: E402

def picture(value: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (np.full((24, 24, 3), value) + rng.normal(0, 2, (24, 24, 3))).astype(np.float32)


def full(feat):
    return [(feat, np.ones((24, 24), bool))]


def test_an_icon_can_have_several_pictures(tmp_path):
    lib = K.KindLibrary(tmp_path / "lib.npz", default=False)
    a = lib.add(picture(50))
    b = lib.add(picture(150))
    lib.add(picture(90), a)  # icon a as it looks in another kind of capture
    assert (len(lib), a, b) == (2, 0, 1)
    d = lib.distances(full(picture(92, 1)))
    assert len(d) == 2 and d[0] < 5  # close to a's second picture
    assert lib.learn_free(full(picture(88, 2))) == a
    lib.save()
    again = K.KindLibrary(tmp_path / "lib.npz", default=False)
    assert again.kind_of == [0, 1, 0] and len(again) == 2


def test_training_adds_pictures_and_needs_three_tiles_for_a_new_icon():
    known, kind_of = [picture(50), picture(150)], [0, 1]
    sightings = [(picture(60, s), (s, 1)) for s in range(5)]  # icon 0, a bit brighter on this device
    sightings += [(picture(151, s), (s, 2)) for s in range(5)]  # icon 1, same as known: no new picture
    sightings += [(picture(220, s), (7, 7)) for s in range(9)]  # unknown picture, always on one spot: a mis-cut
    feats, kinds, stats = train.learn_icons(sightings, known, kind_of)
    assert kinds == [0, 1, 0] and stats["new pictures"] == 1 and stats["new icons"] == 0
    sightings += [(picture(220, s), (s, 9)) for s in range(3)]  # now on three different tiles: a real new icon
    feats, kinds, stats = train.learn_icons(sightings, known, kind_of)
    assert kinds[-1] == 2 and stats["new icons"] == 1


def test_memory_does_not_give_one_tiles_icon_to_another_in_the_same_cell():
    """A pile's tiles share the front tile's lattice cell, and stacked layouts put tiles exactly on top of each
    other: the hidden ones must not inherit the icon of the one in front / on top."""
    from types import SimpleNamespace

    import board as B
    import vision as V

    memory = B.BoardMemory(K.KindLibrary(default=False))
    front = V.Tile(1, 15, 80, 806, True, kind=9)
    behind = V.Tile(1, 15, 90, 806, False, pile=True)
    under = V.Tile(4, 4, 200, 200, False, kind=3, kind_conf=0.9)
    memory.update(SimpleNamespace(tiles=[front, behind, under]))
    assert behind.kind is None  # not the candle in front of it
    later = V.Tile(4, 4, 200, 200, False)  # unreadable now: the earlier read fills it
    memory.update(SimpleNamespace(tiles=[front, later]))
    assert later.kind == 3
    on_top = V.Tile(6, 6, 300, 300, True, kind=5)
    memory.update(SimpleNamespace(tiles=[on_top]))
    below = V.Tile(6, 6, 300, 300, False)  # the free tile there was tapped; this is the one below it
    memory.update(SimpleNamespace(tiles=[below]))
    assert below.kind is None


def test_memory_forgets_everything_after_a_shuffle():
    from types import SimpleNamespace

    import board as B
    import vision as V

    memory = B.BoardMemory(K.KindLibrary(default=False))
    free = [V.Tile(i, 0, 100 * i, 100, True, kind=i) for i in range(5)]
    covered = V.Tile(2, 3, 200, 300, False, kind=7, kind_conf=0.9)
    memory.update(SimpleNamespace(tiles=free + [covered]))
    shuffled = [V.Tile(i, 0, 100 * i, 100, True, kind=(i + 1) % 5) for i in range(5)]
    unreadable = V.Tile(2, 3, 200, 300, False)
    assert memory.update(SimpleNamespace(tiles=shuffled + [unreadable]))  # reported like a new stage
    assert unreadable.kind is None  # not the icon it had before the shuffle


def test_memory_keeps_its_icons_when_remove_stacks_parked_cards():
    from types import SimpleNamespace

    import board as B
    import vision as V

    memory = B.BoardMemory(K.KindLibrary(default=False))
    board = [V.Tile(i, 0, 100 * i, 100, True, kind=i) for i in range(8)]
    parked = [V.Tile(i, 16, 100 * i, 900, True, kind=i) for i in range(3)]
    covered = V.Tile(2, 3, 200, 300, False, kind=7, kind_conf=0.9)
    memory.update(SimpleNamespace(tiles=board + parked + [covered]))
    restacked = [V.Tile(i, 16, 100 * i, 900, True, kind=i + 4) for i in range(3)]
    unreadable = V.Tile(2, 3, 200, 300, False)
    assert not memory.update(SimpleNamespace(tiles=board + restacked + [unreadable]))
    assert unreadable.kind == 7  # remembered: a Remove is no shuffle


def test_memory_keeps_parked_cards_that_a_second_remove_hides():
    from types import SimpleNamespace

    import board as B
    import vision as V

    memory = B.BoardMemory(K.KindLibrary(default=False))
    board = [V.Tile(i, 0, 100 * i, 100, True, kind=i) for i in range(5)]

    def parked(y, kinds):
        return [V.Tile(2 + 2 * n, 18, 232 + 101 * n, y, True, kind=k, rx=232 + 101 * n, ry=y) for n, k in enumerate(kinds)]

    memory.update(SimpleNamespace(tiles=board + parked(994, [7, 8, 8])))
    frame = SimpleNamespace(tiles=board + parked(974, [9, 9, 3]))
    memory.update(frame)
    hidden = [t for t in frame.tiles if not t.free]
    assert [t.kind for t in hidden] == [7, 8, 8]
    assert [frame.tiles[t.covered_by[0]].kind for t in hidden] == [9, 9, 3]  # each under the card put on it
    top_used = SimpleNamespace(tiles=board + parked(974, [9, 9, 3])[1:] + parked(994, [7]))  # the 7 shows again
    memory.update(top_used)
    assert sorted(t.kind for t in top_used.tiles if not t.free) == [8, 8]


def test_the_board_lattice_is_learned_from_free_tiles_and_piles_do_not_bend_it():
    rng = np.random.default_rng(0)
    hx, hy, x0, y0 = 50.65, 53.65, 29.65, 6.8
    on = [(x0 + i * hx + rng.normal(0, 0.6), y0 + j * hy + rng.normal(0, 0.6)) for i in range(1, 12) for j in range(4, 15)]
    piles = [(60 + 10 * k, y0 + 15 * hy) for k in range(5)] * 8 + [(560 + 10 * k, y0 + 14 * hy) for k in range(5)] * 8
    # (pile cards: on a row of the lattice, but a few px apart, off its columns)
    (gx0, gy0, ghx, ghy), fit = train.learn_grid(on * 2 + piles, (101.0, 106.7))
    assert abs(ghx - hx) < 0.02 and abs(ghy - hy) < 0.02  # the profile's 106.7 was 0.6 px too short
    assert abs(gx0 - x0) < 0.5 and abs(gy0 - y0) < 0.5 and fit > 0.7
    assert train.learn_grid(on[:10], (101.0, 106.7)) is None  # too few tiles to learn from


def test_the_profile_lattice_is_only_moved_never_stretched():
    import vision as V

    old = V.GRID
    try:
        V.GRID = (29.65, 6.8, 50.65, 53.65)
        corners = [(29.65 + i * 50.65 + 1.0, 6.8 + j * 53.65 - 1.0, 1.0) for i, j in ((2, 5), (4, 5), (6, 7), (9, 9))]
        lat, ok = V.board_lattice(corners + [(65.0, 811.0, 1.0)])  # a pile's front tile off the lattice
        assert ok and (lat.hx, lat.hy) == (50.65, 53.65)
        assert abs(lat.x0 - 30.65) < 0.01 and abs(lat.y0 - 5.8) < 0.01  # moved by the shift the tiles agree on
        lat, ok = V.board_lattice([(10.0 + 37 * k, 20.0 + 41 * k, 1.0) for k in range(6)])  # tiles that do not fit
        assert ok is False
    finally:
        V.GRID = old
