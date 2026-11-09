"""The whole pipeline on recorded boards (skipped when the recording is missing)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import board as B  # noqa: E402
import game_profile as G  # noqa: E402
import kinds as K  # noqa: E402

REC = Path(__file__).resolve().parents[1] / "recordings" / "halloween_ball" / "20261030-201811"
pytestmark = pytest.mark.skipif(not (REC / "056.png").exists(), reason="recording 20261030-201811 missing")


def test_a_second_remove_hides_the_parked_cards_and_the_advisor_keeps_them():
    """Frame 55: three cards parked above the tray (first Remove). Frame 56: the second Remove put three more on them."""
    import cv2

    G.activate(G.load("halloween_ball"))
    memory = B.BoardMemory(K.KindLibrary())
    before = B.analyze(cv2.imread(str(REC / "055.png")), memory, samples=1, depth=2, budget=None, seed=0)
    parked = sorted((round(t.x if t.rx is None else t.rx), t.kind) for t in before.frame.tiles if t.free and t.ry and t.ry > 980)
    assert len(parked) == 3
    after = B.analyze(cv2.imread(str(REC / "056.png")), memory, samples=1, depth=2, budget=None, seed=0)
    tiles = after.frame.tiles
    hidden = sorted((round(t.rx), t.kind) for t in tiles if not t.free and t.ry and t.ry > 980)
    assert hidden == parked  # the same icons, now under the new cards
    for t in (t for t in tiles if not t.free and t.ry and t.ry > 980):
        assert len(t.covered_by) == 1 and tiles[t.covered_by[0]].free and tiles[t.covered_by[0]].ry < t.ry


STAGE_13 = REC.parent / "20261101-000539" / "000.png"


@pytest.mark.skipif(not STAGE_13.exists(), reason="recording 20261101-000539 missing")
def test_piles_fanned_vertically_and_sideways_are_both_found():
    """Stage 13: three piles fan out downwards (6 card edges below the hand, broom and ghost), two sideways."""
    import cv2

    import vision as V

    G.activate(G.load("halloween_ball"))
    frame = V.read_frame(cv2.imread(str(STAGE_13)))
    piles = [(frame.tiles[n], behind) for n, behind in V.find_piles(frame)]
    vertical = [b for t, b in piles if all(abs(x - B.spot(t)[0]) < 2 for x, _ in b)]
    sideways = [b for t, b in piles if all(abs(y - B.spot(t)[1]) < 2 for _, y in b)]
    assert [len(b) for b in vertical] == [6, 6, 6] and [len(b) for b in sideways] == [6, 6]
    assert all(b[1][1] - b[0][1] > 5 for b in vertical)  # each card a few px lower than the one in front
