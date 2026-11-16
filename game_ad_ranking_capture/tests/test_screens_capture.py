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
    assert week["meta"] == {"my_name": "Klingo", "my_alliance": "Mice", "my_tag": "SoIM"}
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
    assert [r.status for r in run(force=True).values()] == ["scanned", "scanned"] and len(FakeScanner.scans) == 4
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
        unknown = ("api/week/2026-W01.json", "api/week/..%2F..%2Fsecret.json", "api/week/2026-W4x.json")
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
