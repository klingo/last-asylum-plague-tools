import json
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest

import capture
import checks
import config as C
import device as D
import screens
import store
import viewer_server
import weeks
from helpers import HEIGHT, WIDTH, word
from html_helpers import inline_scripts
from scan import DayScan


def words(*texts, cy=800):
    return [word(text, 100 + 100 * i, cy) for i, text in enumerate(texts)]


def test_screens_are_told_apart_by_their_text():
    assert screens.identify(words("Rank", "Daily", "Weekly", "Player", "Point"), HEIGHT) is screens.Screen.RANK
    assert screens.identify(words("Alliance Duel", cy=50) + words("Theme", "Raid"), HEIGHT) is screens.Screen.DUEL
    assert screens.identify(words("Squad", "Hero", "Territory"), HEIGHT) is screens.Screen.MAP
    assert screens.identify(words("Chat", "Kingdom", cy=50), HEIGHT) is screens.Screen.OTHER
    assert screens.identify([], HEIGHT) is screens.Screen.OTHER
    assert screens.identify(words("Alliance Duel", cy=900), HEIGHT) is screens.Screen.OTHER  # only a title counts


def details_words(left="#127", right="#122"):
    """The Duel's Details tab as the OCR returns it: the title, then the server numbers under the two flags."""
    return words("Alliance Duel", cy=50) + [
        word("Daily Score Overview", 180, 346),
        word(left, 65, 762),
        word("Vs", 520, 757),
        word(right, 940, 761),
        word("[SolM]SwarmOfInfectedMice", 65, 808),
        word("46%", 220, 688),
    ]


def test_the_details_tab_is_recognised_and_its_server_numbers_are_read_left_and_right():
    found = details_words()
    assert screens.identify(found, HEIGHT) is screens.Screen.DUEL
    assert screens.on_details(found) and not screens.on_details(words("Alliance Duel", "Theme", "Details", cy=50))
    assert screens.server_numbers(found, WIDTH, HEIGHT) == (127, 122)
    assert screens.server_numbers(details_words("127", "# 122"), WIDTH, HEIGHT) == (127, 122)  # a '#' the OCR dropped


def test_server_numbers_are_only_taken_when_each_side_has_exactly_one_clear_number():
    assert screens.server_numbers(details_words("#12x", "#122"), WIDTH, HEIGHT) is None  # unreadable
    assert screens.server_numbers(details_words(right="oops"), WIDTH, HEIGHT) is None
    assert screens.server_numbers(details_words() + [word("#5", 70, 765)], WIDTH, HEIGHT) is None  # two on one side
    assert screens.server_numbers([w for w in details_words() if w.text != "#122"], WIDTH, HEIGHT) is None
    unsure = [w if w.text != "#127" else word("#127", 65, 762, score=0.5) for w in details_words()]
    assert screens.server_numbers(unsure, WIDTH, HEIGHT) is None
    elsewhere = [word("#127", 65, 1200), word("#122", 940, 1200)]  # outside the band: some other number
    assert screens.server_numbers(elsewhere, WIDTH, HEIGHT) is None


def tab_words():
    return {day: word(label, 127 + 167 * i, 304) for i, (day, label) in enumerate(C.DAY_LABELS.items())}


def tab_frame(selected: str | None):
    frame = np.full((HEIGHT, WIDTH, 3), (148, 132, 120), np.uint8)  # BGR of an unselected tab
    if selected:
        tab = tab_words()[selected]
        frame[int(tab.cy) - 35 : int(tab.cy) + 40, int(tab.cx) - 45 : int(tab.cx) + 45] = (200, 163, 124)
    return frame


def test_day_tabs_and_the_selected_one():
    found = screens.day_tabs(list(tab_words().values()) + words("Rank", cy=1000), HEIGHT)
    assert list(found) == list(C.DAYS)
    assert screens.selected_day(tab_frame("wed"), found) == "wed"
    assert screens.selected_day(tab_frame(None), found) is None  # no tab is highlighted: nothing is selected
    assert screens.selected_day(tab_frame("mon"), {}) is None


def test_the_duel_icon_is_found_where_it_is_and_not_where_it_is_not():
    template = cv2.imread(str(C.TEMPLATES_DIR / "duel_icon.png"))
    frame = np.random.default_rng(1).integers(0, 255, (HEIGHT, WIDTH, 3), dtype=np.uint8)
    assert screens.find_duel_icon(frame, template) is None
    top, left = 462, 938
    frame[top : top + template.shape[0], left : left + template.shape[1]] = template
    x, y = screens.find_duel_icon(frame, template)
    assert abs(x - (left + template.shape[1] / 2)) <= 1 and abs(y - (top + template.shape[0] / 2)) <= 1
    smaller = cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)  # another resolution
    assert screens.find_duel_icon(smaller, template) is not None


class FakeGame:
    """A device whose screen is one of the known ones; taps are recorded."""

    def __init__(self, shows):
        self.shows, self.taps = shows, []

    def settled(self):
        return np.zeros((HEIGHT, WIDTH, 3), np.uint8)

    def tap(self, x, y):
        self.taps.append((round(x), round(y)))


class FakeOcr:
    def __init__(self, game, screen_words):
        self.game, self.screen_words = game, screen_words

    def read(self, frame, region=None):
        return self.screen_words[self.game.shows]


def test_navigation_goes_from_the_duel_to_the_rank_screen():
    game = FakeGame("duel")
    screen_words = {
        "duel": words("Alliance Duel", cy=50) + [word("Rank", 718, 1865)],
        "rank": words("Daily", "Weekly", "Player", "Point"),
    }
    navigator = screens.Navigator(game, FakeOcr(game, screen_words), lambda text: None)
    original = game.tap
    game.tap = lambda x, y: (original(x, y), setattr(game, "shows", "rank"))
    frame, found = navigator.open_rank()
    assert (
        game.taps[0][0] == round(718 + (40 + 12 * 4) / 2) and game.taps[0][1] < 1865
    )  # on the trophy, above the label
    assert any(w.text == "Weekly" for w in found)


def test_navigation_opens_the_details_tab_from_the_map_and_from_another_tab_of_the_duel():
    for start in ("map", "duel"):
        game = FakeGame(start)
        screen_words = {
            "map": words("Squad", "Hero", "Territory"),
            "duel": words("Alliance Duel", cy=50) + [word("Details", 400, 209), word("Theme", 130, 212)],
            "details": details_words(),
        }
        navigator = screens.Navigator(game, FakeOcr(game, screen_words), lambda text: None)
        navigator.template = cv2.imread(str(C.TEMPLATES_DIR / "duel_icon.png"))
        original = game.tap
        order = {"map": "duel", "duel": "details", "details": "details"}
        game.tap = lambda x, y: (original(x, y), setattr(game, "shows", order[game.shows]))
        if start == "map":  # the icon is found on the frame itself: give the fake map one
            template = navigator.template
            navigator.device.settled = lambda: np.pad(template, ((462, HEIGHT - 462 - template.shape[0]), (938, WIDTH - 938 - template.shape[1]), (0, 0)))
        frame, found = navigator.open_details()
        assert screens.on_details(found) and game.shows == "details"
        assert game.taps[-1] == (round(400 + (40 + 12 * 7) / 2), 209)  # the Details tab's label, the last tap
        assert len(game.taps) == (2 if start == "map" else 1)


def test_navigation_does_not_tap_around_when_the_details_tab_is_missing_or_does_not_open():
    game = FakeGame("duel")
    navigator = screens.Navigator(game, FakeOcr(game, {"duel": words("Alliance Duel", cy=50)}), lambda text: None)
    with pytest.raises(screens.NavigationError, match="Details tab was not found"):
        navigator.open_details()
    assert game.taps == []
    stuck = FakeOcr(game, {"duel": words("Alliance Duel", cy=50) + [word("Details", 400, 209)]})
    with pytest.raises(screens.NavigationError, match="did not open"):
        screens.Navigator(game, stuck, lambda text: None).open_details()
    assert len(game.taps) == 1


def test_navigation_gives_up_instead_of_tapping_around_blindly():
    game = FakeGame("other")
    navigator = screens.Navigator(game, FakeOcr(game, {"other": words("Chat", cy=50)}), lambda text: None)
    with pytest.raises(screens.NavigationError, match="Could not get back"):
        navigator.open_rank()
    assert len(game.taps) == screens.MAX_BACKS
    assert {tap for tap in game.taps} == {(round(C.BACK_ARROW[0] * WIDTH), round(C.BACK_ARROW[1] * HEIGHT))}


def test_the_map_without_the_icon_is_an_error_not_a_blind_tap():
    game = FakeGame("map")
    navigator = screens.Navigator(game, FakeOcr(game, {"map": words("Squad", "Hero")}), lambda text: None)
    with pytest.raises(screens.NavigationError, match="icon was not found"):
        navigator.open_rank()
    assert game.taps == []


# -- the whole capture, with a fake game and a fake scanner
class FakeNavigator:
    selectable = {"mon", "tue"}

    def __init__(self, device, ocr, progress):
        pass

    details = None  # what the Details tab reads: words, or an error to raise
    opened = []

    def open_details(self):
        FakeNavigator.opened.append(1)
        if isinstance(FakeNavigator.details, Exception):
            raise FakeNavigator.details
        return np.zeros((HEIGHT, WIDTH, 3), np.uint8), FakeNavigator.details or details_words()

    def open_rank(self):
        return np.zeros((HEIGHT, WIDTH, 3), np.uint8), list(tab_words().values()) + [word("Daily", 115, 185)]

    def select_day(self, day, tabs):
        return np.zeros((HEIGHT, WIDTH, 3), np.uint8) if day in self.selectable else None

    def go_home(self):
        pass


class FakeScanner:
    scans: list = []
    complete = True

    def __init__(self, *args):
        pass

    def scan_day(self):
        FakeScanner.scans.append(1)
        row = {"rank": 1, "name": "Klingo", "alliance": "Mice", "tag": "SoIM", "points": 10 * len(FakeScanner.scans)}
        return DayScan([row], dict(row), FakeScanner.complete, [], [])


class FakeClockDevice:
    def tap(self, x, y):
        pass


def test_a_capture_reads_final_and_live_days_and_skips_what_is_not_there(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "Navigator", FakeNavigator)
    monkeypatch.setattr(capture, "Scanner", FakeScanner)
    monkeypatch.setattr(C, "CORRECTIONS", tmp_path / "none.json")
    FakeScanner.scans, FakeScanner.complete = [], True
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)  # Tuesday
    monkeypatch.setattr(weeks, "now_utc", lambda: now)

    def run(**kwargs):
        return capture.run_capture(
            FakeClockDevice(),
            progress=lambda text: None,
            directory=tmp_path,
            review_directory=tmp_path / "review",
            primary=object(),
            secondary=object(),
            **kwargs
        )

    first = {r.day: r for r in run()}
    assert [first[d].status for d in C.DAYS] == [
        "scanned",
        "scanned",
        "no data yet",
        "no data yet",
        "no data yet",
        "no data yet",
    ]
    week = store.load("2026-W47", tmp_path)
    assert (week["days"]["mon"]["final"], week["days"]["tue"]["final"]) == (True, False)  # Monday is over, Tuesday runs
    assert week["meta"] == {
        "my_name": "Klingo",
        "my_alliance": "Mice",
        "my_tag": "SoIM",
        "my_server": 127,
        "opponent_server": 122,
    }
    assert first["mon"].line() == "Mon: 1 rows" and first["wed"].line() == "Wed: no data yet"


def test_final_days_are_skipped_until_forced_and_incomplete_scans_never_replace_complete_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "Navigator", FakeNavigator)
    monkeypatch.setattr(capture, "Scanner", FakeScanner)
    monkeypatch.setattr(C, "CORRECTIONS", tmp_path / "none.json")
    FakeScanner.scans, FakeScanner.complete = [], True
    clock = {"now": datetime(2026, 11, 18, 5, tzinfo=timezone.utc)}  # Wednesday morning: Monday and Tuesday are over
    monkeypatch.setattr(weeks, "now_utc", lambda: clock["now"])

    def run(**kwargs):
        return {
            r.day: r
            for r in capture.run_capture(
                FakeClockDevice(),
                days=("mon", "tue"),
                progress=lambda t: None,
                directory=tmp_path,
                review_directory=tmp_path / "review",
                primary=object(),
                secondary=object(),
                **kwargs
            )
        }

    assert [r.status for r in run().values()] == ["scanned", "scanned"]
    assert all(store.load("2026-W47", tmp_path)["days"][d]["final"] for d in ("mon", "tue"))
    assert [r.status for r in run().values()] == ["final", "final"] and len(FakeScanner.scans) == 2
    by_hand = store.load("2026-W47", tmp_path)
    by_hand["meta"]["opponent_members"] = 100
    store.save(by_hand, tmp_path)
    assert [r.status for r in run(force=True).values()] == ["scanned", "scanned"] and len(FakeScanner.scans) == 4
    assert store.load("2026-W47", tmp_path)["meta"]["opponent_members"] == 100  # a scan keeps what was entered by hand
    FakeScanner.complete = False
    assert [r.status for r in run(force=True).values()] == ["kept", "kept"]
    assert store.load("2026-W47", tmp_path)["days"]["mon"]["rows"][0]["points"] == 30  # the third scan, not the fourth


def test_a_stop_request_ends_the_capture_before_the_next_day(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "Navigator", FakeNavigator)
    monkeypatch.setattr(capture, "Scanner", FakeScanner)
    monkeypatch.setattr(C, "CORRECTIONS", tmp_path / "none.json")
    FakeScanner.scans, FakeScanner.complete = [], True
    results = capture.run_capture(
        FakeClockDevice(),
        progress=lambda t: None,
        should_stop=lambda: True,
        directory=tmp_path,
        review_directory=tmp_path / "review",
        primary=object(),
        secondary=object(),
    )
    assert results == [] and not list(tmp_path.glob("*.json"))


# -- checks
def test_checks_stop_at_the_first_problem(monkeypatch):
    monkeypatch.setattr(D, "find_adb", lambda explicit=None: None)
    assert [(c.name, c.ok) for c in checks.run_checks("", "s")] == [("ADB", False)]

    class Device:
        def __init__(self, serial, adb):
            pass

        def installed(self):
            return True

        def foreground(self):
            return "com.other"

    monkeypatch.setattr(D, "find_adb", lambda explicit=None: "adb.exe")
    monkeypatch.setattr(D, "AdbDevice", Device)
    results = checks.run_checks("", "s")
    assert [(c.name, c.ok) for c in results] == [
        ("ADB", True),
        ("Device", True),
        ("Game", True),
        ("Game in front", False),
    ]

    def refuse(serial, adb):
        raise RuntimeError("adb could not connect")

    monkeypatch.setattr(D, "AdbDevice", refuse)
    assert checks.run_checks("", "s")[-1].detail == "adb could not connect"


# -- the viewer
def week_file(directory: Path) -> None:
    week = store.new_week("2026-W47", date(2026, 11, 16))
    week["meta"] = {"my_name": "Ann", "my_alliance": "Mice", "my_tag": "SoIM"}
    rows = [{"rank": 1, "name": "Ann", "alliance": "Mice", "tag": "SoIM", "points": 100}]
    store.put_day(week, "mon", date(2026, 11, 16), rows, datetime(2026, 11, 17, 5, tzinfo=timezone.utc), True, True)
    store.save(week, directory)


def fetch(url: str):
    with urllib.request.urlopen(url) as response:
        return response.status, response.read()


def test_the_viewer_serves_the_page_the_week_list_and_a_table(tmp_path):
    week_file(tmp_path)
    server, url = viewer_server.start(tmp_path)
    try:
        assert b"Alliance Duel rankings" in fetch(url)[1]
        assert json.loads(fetch(url + "api/weeks.json")[1]) == ["2026-W47"]
        table = json.loads(fetch(url + "api/week/2026-W47.json")[1])
        assert table["players"][0]["total"] == 100 and table["my_alliance"] == "Mice"
        assert fetch(url + "assets/green.png")[1].startswith(b"\x89PNG")
        unknown = ("assets/nope.png", "api/week/2026-W01.json", "api/week/..%2F..%2Fsecret.json", "api/week/2026-W4x.json")
        for bad in (*unknown, "api/week/2026-W47", "elsewhere"):
            with pytest.raises(urllib.error.HTTPError) as error:
                fetch(url + bad)
            assert error.value.code == 404
    finally:
        viewer_server.stop(server)


def test_the_viewer_script_is_valid_javascript(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    page = (C.VIEWER_DIR / "index.html").read_text(encoding="utf-8")
    script = tmp_path / "page.js"
    script.write_text(inline_scripts(page)[0], encoding="utf-8")
    result = subprocess.run([node, "--check", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_the_window_opens_and_closes():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk cannot start here")
    import gui

    app = gui.App(root)
    assert str(app.stop_button["state"]) == "disabled" and all(v.get() for v in app.days.values())
    app.close()


def test_a_scan_that_runs_across_the_reset_is_not_final(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "Navigator", FakeNavigator)
    monkeypatch.setattr(C, "CORRECTIONS", tmp_path / "none.json")
    clock = {"now": datetime(2026, 11, 17, 1, 55, tzinfo=timezone.utc)}  # Monday 5 minutes before the reset (02:00 UTC)
    monkeypatch.setattr(weeks, "now_utc", lambda: clock["now"])

    class SlowScanner(FakeScanner):
        def scan_day(self):
            clock["now"] = datetime(2026, 11, 17, 2, 10, tzinfo=timezone.utc)  # the scan ends after the reset
            return super().scan_day()

    monkeypatch.setattr(capture, "Scanner", SlowScanner)
    FakeScanner.scans, FakeScanner.complete = [], True
    kwargs = dict(
        days=("mon",),
        progress=lambda t: None,
        directory=tmp_path,
        review_directory=tmp_path / "review",
        primary=object(),
        secondary=object(),
    )
    capture.run_capture(FakeClockDevice(), **kwargs)
    mon = store.load("2026-W47", tmp_path)["days"]["mon"]
    assert mon["final"] is False and mon["captured_at"] == "2026-11-17T01:55:00Z"  # it began before Monday ended
    assert [r.status for r in capture.run_capture(FakeClockDevice(), **kwargs)] == ["scanned"]  # so it is read again
    assert store.load("2026-W47", tmp_path)["days"]["mon"]["final"] is True  # begun after the reset: final


# -- the servers of the Details tab, once per week
def read(week, today, tmp_path, force=False):
    FakeNavigator.opened = []
    messages = []
    capture.read_servers(FakeNavigator(None, None, None), week, today, force, messages.append, tmp_path)
    return messages


def test_the_servers_are_read_once_per_week_and_again_when_forced(tmp_path):
    week, tuesday = store.new_week("2026-W47", date(2026, 11, 16)), date(2026, 11, 17)
    FakeNavigator.details = None
    assert read(week, tuesday, tmp_path) == ["Servers: #127 (own) against #122."]
    assert (week["meta"]["my_server"], week["meta"]["opponent_server"]) == (127, 122)
    assert not list(tmp_path.glob("*.json"))  # a new week is no file until a day is stored
    assert read(week, tuesday, tmp_path) == [] and FakeNavigator.opened == []  # known: the game is not touched
    FakeNavigator.details = details_words("#130", "#99")
    assert read(week, tuesday, tmp_path, force=True) and week["meta"]["my_server"] == 130
    FakeNavigator.details = None


def test_the_servers_of_a_week_that_has_a_file_are_saved_right_away(tmp_path):
    week = store.new_week("2026-W47", date(2026, 11, 16))
    week["meta"]["opponent_members"] = 100
    store.save(week, tmp_path)
    FakeNavigator.details = None
    read(week, date(2026, 11, 17), tmp_path)
    assert store.load("2026-W47", tmp_path)["meta"] == {"opponent_members": 100, "my_server": 127, "opponent_server": 122}


def test_a_sunday_has_no_servers_to_read(tmp_path):
    week = store.new_week("2026-W47", date(2026, 11, 16))
    assert read(week, date(2026, 11, 22), tmp_path) == [] and FakeNavigator.opened == [] and week["meta"] == {}


def test_servers_that_cannot_be_read_cost_a_message_and_never_the_capture(tmp_path):
    week = store.new_week("2026-W47", date(2026, 11, 16))
    FakeNavigator.details = details_words("#12x", "#122")
    assert "not found" in read(week, date(2026, 11, 17), tmp_path)[0] and week["meta"] == {}
    FakeNavigator.details = screens.NavigationError("The Details tab of the Alliance Duel did not open.")
    assert read(week, date(2026, 11, 17), tmp_path) == [
        "Servers not read: The Details tab of the Alliance Duel did not open."
    ]
    FakeNavigator.details = None


def test_the_week_table_carries_the_servers():
    from aggregate import week_table
    from corrections import Corrections
    from roster import Roster

    week = store.new_week("2026-W47", date(2026, 11, 16))
    week["meta"].update(my_server=127, opponent_server=122)
    table = week_table(week, Corrections({}, {}), Roster())
    assert (table["my_server"], table["opponent_server"]) == (127, 122)
    assert week_table(store.new_week("2026-W46", date(2026, 11, 9)), Corrections({}, {}), Roster())["my_server"] is None
