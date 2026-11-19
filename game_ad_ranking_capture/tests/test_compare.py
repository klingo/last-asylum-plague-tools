"""The duel of a week table (viewer/compare.js), run in Node."""

import json
import shutil
import subprocess

import pytest

import config as C

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def run_node(expression: str, table: dict):
    script = (
        f"const C = require({str(C.VIEWER_DIR / 'compare.js')!r}); const data = {json.dumps(table)};"
        f"console.log(JSON.stringify({expression}))"
    )
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def player(name, alliance, tag, **points):
    return {"name": name, "alliance": alliance, "tag": tag, "points": points, "total": sum(points.values())}


def week(players, days, final, opponent_members=0):
    return {
        "my_alliance": "Mice",
        "my_tag": "MI",
        "opponent_members": opponent_members,
        "days": days,
        "final": final,
        "players": players,
    }


MICE = [player("a", "Mice", "MI", mon=10, tue=0), player("b", "Mice", "MI", mon=0, tue=0), player("c", "Mice", "MI", mon=2, tue=4)]
FOES = [player("x", "Foes", "FO", mon=5, tue=9), player("y", "Foes", "FO", mon=5, tue=9)]


def test_the_own_alliance_comes_first_with_its_members_zeros_and_averages():
    table = week(FOES + MICE, ["mon", "tue"], {"mon": True, "tue": False})
    sides = run_node("C.compareSides(data).map(({ alliance, members, zero, total, average, median }) => ({ alliance, members, zero, total, average, median }))", table)
    assert sides == [
        {"alliance": "Mice", "members": 3, "zero": 1, "total": 16, "average": 5, "median": 6},
        {"alliance": "Foes", "members": 2, "zero": 0, "total": 28, "average": 14, "median": 14},
    ]


def test_the_other_alliances_unseen_members_count_with_zero_points():
    table = week(FOES + MICE, ["mon"], {"mon": True}, opponent_members=5)
    foes = run_node("C.compareSides(data)[1]", table)
    assert (foes["members"], foes["zero"], foes["average"]) == (5, 3, 6)


def test_a_finished_day_is_won_by_the_higher_side_and_seven_points_win_the_duel():
    table = week(FOES + MICE, ["mon", "tue"], {"mon": True, "tue": False})
    duel = run_node("C.duelDays(data, C.compareSides(data))", table)
    assert [(d["day"], d["points"], d["winner"]) for d in duel["days"]] == [
        ("mon", [12, 10], 0),  # finished: the own alliance has more
        ("tue", [4, 18], -1),  # not finished: no winner yet
        ("wed", [0, 0], -1),
        ("thu", [0, 0], -1),
        ("fri", [0, 0], -1),
        ("sat", [0, 0], -1),
    ]
    assert duel["won"] == [1, 0] and duel["winner"] == -1
    every_day = week(FOES + MICE, ["mon", "tue"], {"mon": True, "tue": True})
    assert run_node("C.duelDays(data, C.compareSides(data)).won", every_day) == [1, 2]
    assert run_node("C.duelDays(data, C.compareSides(data)).winner", every_day) == -1
    days = ["mon", "tue", "wed", "thu", "fri", "sat"]
    sweep = [player("a", "Mice", "MI", **{d: 1 for d in days}), player("x", "Foes", "FO", **{d: 0 for d in days})]
    decided = week(sweep, days, {d: True for d in days})
    duel = run_node("C.duelDays(data, C.compareSides(data))", decided)
    assert duel["won"] == [13, 0] and duel["winner"] == 0


def test_a_draw_and_a_week_without_a_second_alliance_have_no_winner():
    draw = week([player("a", "Mice", "MI", mon=5), player("x", "Foes", "FO", mon=5)], ["mon"], {"mon": True})
    assert run_node("C.duelDays(data, C.compareSides(data)).won", draw) == [0, 0]
    alone = week([player("a", "Mice", "MI", mon=5)], ["mon"], {"mon": True})
    assert run_node("C.compareSides(data).length", alone) == 1


def test_the_script_is_valid_javascript():
    done = subprocess.run([NODE, "--check", str(C.VIEWER_DIR / "compare.js")], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
