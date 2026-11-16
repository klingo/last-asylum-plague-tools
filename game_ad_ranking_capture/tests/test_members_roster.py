import json
from datetime import date, datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest

import aggregate
import capture
import config as C
import corrections
import members as M
import roster as R
import screens
import store
from helpers import HEIGHT, WIDTH, word
from members_game import VirtualMembers
from ocr import Ocr
from test_weeks_store_aggregate import stored_week, utc

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TOP = 150  # the fixtures hold the frame from here down


# -- the roster: snapshots valid from a date on
def snapshot(roster, since, names, when=utc(2026, 11, 17, 10)):
    roster.add(date.fromisoformat(since), when, [{"name": n, "rank": "R3"} for n in names], len(names))


def test_a_day_has_the_members_of_the_latest_snapshot_valid_by_then():
    roster = R.Roster()
    assert roster.members_on(date(2026, 11, 16)) == []  # no list at all
    snapshot(roster, "2026-11-16", ["Ann", "Bob"])
    snapshot(roster, "2026-11-18", ["Ann", "Bob", "Cy"])  # Cy joined on Wednesday

    def names(day):
        return [m["name"] for m in roster.members_on(date.fromisoformat(day))]

    assert names("2026-11-15") == [] and names("2026-11-16") == ["Ann", "Bob"] and names("2026-11-17") == ["Ann", "Bob"]
    assert names("2026-11-18") == ["Ann", "Bob", "Cy"] and names("2026-12-01") == ["Ann", "Bob", "Cy"]


def test_members_are_ordered_by_rank_then_name():
    roster = R.Roster()
    members = [{"name": "b", "rank": "R3"}, {"name": "Z", "rank": "R5"}, {"name": "a", "rank": "R3"}]
    roster.add(date(2026, 11, 16), utc(2026, 11, 16), members, 3)
    assert [m["name"] for m in roster.snapshots[0]["members"]] == ["Z", "a", "b"]


# -- the zero days in the table
def test_a_member_missing_from_a_days_ranking_gets_zero_for_that_day():
    week = stored_week(mon=[(1, "Ann", 5_000_000)], tue=[(1, "Ann", 3_000_000), (2, "Bob", 1_000_000)])
    roster = R.Roster()
    snapshot(roster, "2026-11-16", ["Ann", "Bob", "Cy"])
    table = aggregate.week_table(week, corrections.Corrections(), roster)
    by_name = {p["name"]: p for p in table["players"]}
    assert by_name["Bob"]["points"] == {"mon": 0, "tue": 1_000_000} and by_name["Bob"]["filled"] == ["mon"]
    assert by_name["Cy"]["points"] == {"mon": 0, "tue": 0} and by_name["Cy"]["filled"] == ["mon", "tue"]
    assert by_name["Ann"]["filled"] == [] and by_name["Cy"]["total"] == 0
    assert (by_name["Bob"]["average"], by_name["Bob"]["median"]) == (500_000, 500_000)  # the 0 counts
    assert by_name["Cy"]["heat"]["mon"] == 0.0 and by_name["Cy"]["phase"]["mon"] == 0
    assert (by_name["Cy"]["alliance"], by_name["Cy"]["tag"]) == ("Mice", "SolM")
    assert sum(len(p["filled"]) for p in table["players"]) == 3


def test_member_names_are_matched_like_the_rankings_names():
    week = stored_week(mon=[(1, "Bella1401", 9_000_000), (2, "ДокторАня", 8_000_000)])
    roster = R.Roster()
    snapshot(roster, "2026-11-16", ["BellaI401", "докторАня", "Bob1", "Old"])  # look-alike spelling, other case
    fixes = corrections.Corrections(aliases={store.spelling_key("Old"): "Bob1"})  # Old renamed to Bob1
    table = aggregate.week_table(week, fixes, roster)
    assert sorted(p["name"] for p in table["players"]) == ["Bella1401", "Bob1", "ДокторАня"]  # nobody twice
    assert next(p for p in table["players"] if p["name"] == "Bob1")["filled"] == ["mon"]


def test_a_member_whose_name_could_not_be_read_is_not_added():
    week = stored_week(mon=[(1, "Ann", 5)])
    roster = R.Roster()
    roster.add(date(2026, 11, 16), utc(2026, 11, 16), [{"name": "Ann", "rank": "R4"}, {"name": "?", "rank": "R3"}], 2)
    assert len(aggregate.week_table(week, corrections.Corrections(), roster)["players"]) == 1


# -- reading the member screen from real frames
@pytest.fixture(scope="module")
def engines():
    primary, secondary = Ocr(), Ocr(cyrillic=True)
    try:
        primary.read(np.zeros((200, 200, 3), np.uint8))
        secondary.read(np.zeros((200, 200, 3), np.uint8))
    except Exception as error:
        pytest.skip(f"the OCR models are not available: {error}")
    return primary, secondary


def frame_of(name):
    crop = cv2.imread(str(FIXTURES / f"{name}.png"))
    frame = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    frame[TOP : TOP + crop.shape[0]] = crop
    return frame


def test_a_real_page_with_open_groups(engines):
    frame = frame_of("members_open")
    page = M.parse_page(frame, engines[0].read(frame), engines[1])
    assert (page.leader, page.total) == ("Bella1401", 88)
    assert [(h.group, h.total, h.collapsed) for h in page.headers] == [(3, 68, False)]
    names = [c.name for c in page.cards]
    assert names[:4] == ["XeroX", "ADDEVIL", "DonFalcone", "Medicissimus"]  # row by row, left to right
    assert names[6] == "љубица"  # the first engine finds nothing: the Cyrillic one reads it
    assert all(c.power for c in page.cards) and len(page.cards) == 10


def test_a_real_page_with_a_folded_group(engines):
    frame = frame_of("members_folded")
    page = M.parse_page(frame, engines[0].read(frame), engines[1])
    assert [(h.group, h.total, h.collapsed) for h in page.headers] == [(2, 2, True)]
    assert [c.name for c in page.cards[:2]] == ["MrsPoppy", "N-aleks"]  # row by row, left to right
    assert {c.name: c.power for c in page.cards}["f-caw-f"] == 147_510_360


# -- scanning the list: folded groups are opened, the counts are checked
def scanner(virtual, stop=lambda: False):
    return M.MemberScanner(virtual, virtual, None, progress=lambda text: None, should_stop=stop)


def alliance(**kwargs):
    groups = [
        (4, [f"Officer{i}" for i in range(4)]),
        (3, [f"Member{i}" for i in range(11)]),
        (2, ["Low1", "Low2", "Low3"]),
    ]
    return VirtualMembers(groups, **kwargs)


def test_a_folded_group_is_opened_and_everyone_is_read():
    virtual = alliance(folded={2})
    result = scanner(virtual).scan()
    names = [m["name"] for m in result.members]
    assert len(names) == 1 + 4 + 11 + 3 == result.total and len(set(names)) == len(names)
    assert result.members[0] == {"name": "Leader1", "rank": "R5"}
    assert {m["rank"] for m in result.members if m["name"].startswith("Low")} == {"R2"}
    assert result.expanded == ["R2"] and result.complete and result.warnings == []
    assert virtual.folded == set()


def test_open_groups_are_left_alone_and_several_folded_ones_are_all_opened():
    virtual = alliance()
    assert scanner(virtual).scan().expanded == [] and virtual.taps == []
    both = alliance(folded={3, 2})
    result = scanner(both).scan()
    assert sorted(result.expanded) == ["R2", "R3"] and len(result.members) == result.total


def test_a_list_that_scrolls_further_than_asked_is_still_complete():
    result = scanner(alliance(folded={2}, overshoot=1.15)).scan()
    assert len(result.members) == result.total and result.warnings == []


def test_the_counts_shown_are_checked():
    result = scanner(alliance(shown_total=99)).scan()
    assert any("the screen says 99" in w for w in result.warnings)


# -- storing it
def fake_run(monkeypatch, roster_directory, virtual, now=datetime(2026, 11, 18, 12, tzinfo=timezone.utc)):
    class FakeNavigator:
        def __init__(self, *args):
            pass

        def open_members(self):
            pass

        def go_home(self):
            pass

    monkeypatch.setattr(capture, "Navigator", FakeNavigator)
    monkeypatch.setattr(capture.weeks, "now_utc", lambda: now)
    return capture.run_members(virtual, None, lambda t: None, lambda: False, roster_directory, virtual, None)


def test_a_list_that_does_not_add_up_is_not_stored(monkeypatch, tmp_path):
    scan, stored = fake_run(monkeypatch, tmp_path / "members", alliance(shown_total=99))
    assert not stored and not (tmp_path / "members").exists()


# -- getting there
class FakeScreens:
    def __init__(self):
        self.shows, self.taps = "map", []

    def settled(self):
        return np.zeros((HEIGHT, WIDTH, 3), np.uint8)

    def tap(self, x, y):
        self.taps.append((round(x), round(y)))
        self.shows = {"map": "alliance", "alliance": "members"}.get(self.shows, "map")


def test_the_navigation_goes_from_the_map_through_the_alliance_page_to_the_members():
    game = FakeScreens()
    pages = {
        "map": [word("Squad", 100, 270), word("Hero", 100, 1850), word("Alliance", 990, 1380)],
        "alliance": [word("Alliance", 300, 50), word("Alliance Shop", 300, 1300), word("Members", 868, 1140)],
        "members": [word("Alliance Members", 300, 50)],
    }

    class FakeOcr:
        def read(self, frame, region=None):
            return pages[game.shows]

    screens.Navigator(game, FakeOcr(), lambda text: None).open_members()
    assert game.shows == "members" and len(game.taps) == 2
    assert game.taps[0] == (round(C.ALLIANCE_BUTTON[0] * WIDTH), round(C.ALLIANCE_BUTTON[1] * HEIGHT))
    assert game.taps[1][0] == round(868 + (40 + 12 * 7) / 2)  # the Members label of the Alliance page


def test_the_new_screens_are_recognised():
    def top(text):
        return [word(text, 300, 50)]

    assert screens.identify(top("Alliance Members"), HEIGHT) is screens.Screen.MEMBERS
    assert screens.identify(top("Alliance") + [word("Alliance Shop", 300, 1300)], HEIGHT) is screens.Screen.ALLIANCE
    mail_bag = [word("Mail", 990, 1530), word("Bag", 990, 1670)]  # a busy map: only some of its words are read
    assert screens.identify(mail_bag, HEIGHT) is screens.Screen.MAP
    assert screens.identify(top("Chat") + [word("Alliance", 300, 180)], HEIGHT) is screens.Screen.OTHER
