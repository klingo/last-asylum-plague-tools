import random

import config as C
import scan
from helpers import HEIGHT, WIDTH, NoWords, VirtualList
from scan import READ_TRIES


def scanner(virtual, stop=lambda: False):
    return scan.Scanner(virtual, virtual, NoWords(), progress=lambda text: None, should_stop=stop)


def test_reads_the_whole_list_without_gaps():
    virtual = VirtualList(60)
    virtual.offset = 20  # the list was left in the middle
    result = scanner(virtual).scan_day()
    assert [row["rank"] for row in result.rows] == list(range(1, 61))
    assert result.complete and result.warnings == []
    assert result.rows[0] == {"rank": 1, "name": "Player1", "alliance": "Mice", "tag": "SoIM", "points": 9_999_000}
    assert result.rows[2]["rank"] == 3  # a medal row: no number on the card
    assert result.me["name"] == "Klingo" and result.me["rank"] == 28


def test_a_list_that_scrolls_further_than_asked_is_still_complete():
    result = scanner(VirtualList(60, overshoot=1.3)).scan_day()
    assert [row["rank"] for row in result.rows] == list(range(1, 61))


def test_a_skipped_card_is_found_again():
    virtual = VirtualList(40, overshoot=1.9)  # about 6.6 cards a swipe: more than a page shows
    result = scanner(virtual).scan_day()
    assert [row["rank"] for row in result.rows] == list(range(1, 41))


def test_stops_at_the_games_maximum(monkeypatch):
    monkeypatch.setattr(C, "MAX_ROWS", 20)
    result = scanner(VirtualList(80)).scan_day()
    assert result.complete and 20 <= len(result.rows) < 30


def test_a_stop_request_returns_what_was_read():
    virtual = VirtualList(60)
    result = scanner(virtual, stop=lambda: virtual.swipes >= 3 and virtual.offset > 5).scan_day()
    assert not result.complete and 0 < len(result.rows) < 60


def test_check_reports_gaps_and_rising_points():
    rows = [{"rank": 1, "points": 90}, {"rank": 2, "points": 95}, {"rank": 4, "points": 50}]
    warnings = scan.check(rows)
    assert any("missing ranks: 3" in text for text in warnings)
    assert any("rank 2 has more points than rank 1" in text for text in warnings)
    assert scan.check([{"rank": 1, "points": 5}, {"rank": 2, "points": 5}]) == []  # ties are fine
    assert any("starts at rank 2" in text for text in scan.check([{"rank": 2, "points": 5}]))


def test_weak_rows_come_back_with_a_picture():
    class Unsure(VirtualList):
        def read(self, frame, region=None):
            words = super().read(frame, region)
            return [w if w.text != "Player5" else type(w)(w.text, 0.5, w.x0, w.y0, w.x1, w.y1) for w in words]

    unsure = Unsure(8)
    result = scanner(unsure).scan_day()
    assert [item.rank for item in result.review] == [5]
    assert "low confidence 0.50" in result.review[0].flags[0]
    assert result.review[0].crop.shape[1] == WIDTH and 0 < result.review[0].crop.shape[0] <= HEIGHT


class Blind(VirtualList):
    """A list whose rank numbers and names cannot be read on the next `blind` reads once it is scrolled past `after`
    cards: a page that cannot be placed at all (no number, and nothing the earlier pages read to match it by)."""

    def __init__(self, size, after, blind):
        super().__init__(size)
        self.after, self.blind = after, blind

    def read(self, frame, region=None):
        words = super().read(frame, region)
        if float(frame[0, 0, 0]) / 4 >= self.after and self.blind > 0:
            self.blind -= 1
            return [w for w in words if w.x0 > 700]  # only the points are left
        return words


def test_unreadable_pages_in_the_middle_do_not_end_the_scan():
    blind = Blind(60, after=20, blind=READ_TRIES)  # one page whose ranks are unreadable for every look at it
    result = scanner(blind).scan_day()
    assert [row["rank"] for row in result.rows] == list(range(1, 61))
    assert result.complete
    assert len(result.unreadable) == 1 and "without a readable rank" in result.warnings[0]


def test_too_many_unreadable_pages_make_the_scan_incomplete_not_complete():
    result = scanner(Blind(60, after=20, blind=10_000)).scan_day()
    assert not result.complete and len(result.unreadable) == scan.MAX_UNREADABLE + 1
    assert [row["rank"] for row in result.rows] == list(range(1, result.rows[-1]["rank"] + 1))


def test_a_list_that_ends_right_after_a_skipped_page_is_not_complete():
    result = scanner(Blind(24, after=18, blind=2 * READ_TRIES)).scan_day()  # the last page is skipped twice
    assert len(result.unreadable) == 2 and len(result.rows) == 23
    assert not result.complete


def test_cards_without_a_rank_number_are_placed_by_the_cards_read_before_them():
    result = scanner(VirtualList(60, unnumbered_from=25)).scan_day()  # "Not ranked" from rank 25 on
    assert [row["rank"] for row in result.rows] == list(range(1, 61))
    assert result.complete and result.warnings == [] and result.unreadable == []


def test_a_page_that_cannot_be_placed_is_read_again_from_further_up():
    result = scanner(VirtualList(60, overshoot=1.9, unnumbered_from=25)).scan_day()
    assert [row["rank"] for row in result.rows] == list(range(1, 61)) and result.complete


class Uneven(VirtualList):
    """A list whose swipes move it a different distance every time, within `low` to `high` times what was asked."""

    def __init__(self, size, unnumbered_from, seed, low=0.9, high=1.2):
        super().__init__(size, unnumbered_from=unnumbered_from)
        self.random, self.low, self.high = random.Random(seed), low, high

    def swipe(self, x0, y0, x1, y1, ms=0):
        self.overshoot = self.random.uniform(self.low, self.high)
        super().swipe(x0, y0, x1, y1, ms)


def test_uneven_swipes_over_cards_without_a_rank_number_leave_no_gap_and_no_early_end():
    for seed in range(40):  # a swipe that overshoots leaves no known card on the page: back to the last placed one
        result = scanner(Uneven(66, unnumbered_from=31, seed=seed)).scan_day()
        assert [row["rank"] for row in result.rows] == list(range(1, 67)), seed
        assert result.complete, seed
