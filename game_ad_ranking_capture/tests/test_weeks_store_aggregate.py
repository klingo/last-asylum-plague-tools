import json
from datetime import date, datetime, timezone

import pytest

import aggregate
import config as C
import corrections
import store
import weeks


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_the_game_day_starts_at_0200_utc():
    assert weeks.game_date(utc(2026, 11, 16, 1, 59)) == date(2026, 11, 15)  # still Sunday's game day
    assert weeks.game_date(utc(2026, 11, 16, 2, 0)) == date(2026, 11, 16)


def test_calendar_weeks_follow_iso():
    assert weeks.week_id(date(2026, 11, 16)) == "2026-W47"
    assert weeks.week_monday(date(2026, 11, 22)) == date(2026, 11, 16)  # Sunday belongs to the week before it
    assert weeks.week_id(date(2027, 1, 1)) == "2026-W53"  # the year's first days can still be the old year's last week
    assert weeks.day_date(date(2026, 11, 16), "sat") == date(2026, 11, 21)


def test_a_day_is_final_once_its_game_day_has_ended():
    monday = date(2026, 11, 16)
    assert weeks.day_end(monday) == utc(2026, 11, 17, 2, 0)
    assert not weeks.is_final(monday, utc(2026, 11, 17, 1, 59))
    assert weeks.is_final(monday, utc(2026, 11, 17, 2, 0))
    assert weeks.is_future(date(2026, 11, 17), utc(2026, 11, 16, 12))
    assert not weeks.is_future(monday, utc(2026, 11, 16, 12))


def rows(*entries):
    return [
        {"rank": rank, "name": name, "alliance": "Mice", "tag": "SoIM", "points": points}
        for rank, name, points in entries
    ]


def test_a_week_file_is_deterministic_and_round_trips(tmp_path):
    week = store.new_week("2026-W47", date(2026, 11, 16))
    week["meta"] = {"my_name": "Klingo", "my_alliance": "Mice", "my_tag": "SoIM"}
    store.put_day(
        week, "mon", date(2026, 11, 16), rows((2, "Љубица", 80), (1, "Bella1401", 90)), utc(2026, 11, 17, 5), True, True
    )
    path = store.save(week, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert json.loads(text) == week and text.endswith("}\n")
    assert [line.strip()[:20] for line in text.splitlines() if '"rank"' in line] == [
        '{"rank": 1, "name": ',
        '{"rank": 2, "name": ',
    ]
    assert "Љубица" in text  # no \u escapes: names stay readable in a diff
    assert store.load("2026-W47", tmp_path) == week and store.load("2026-W01", tmp_path) is None
    assert store.list_weeks(tmp_path) == ["2026-W47"]
    assert store.is_final(week, "mon") and not store.is_final(week, "tue")
    store.save(week, tmp_path)
    assert path.read_text(encoding="utf-8") == text  # saving twice changes nothing


def test_alliance_spellings_become_the_most_common_one(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CORRECTIONS", tmp_path / "none.json")
    mixed = [
        {"rank": 1, "name": "A", "alliance": "SwarmOfInfectedMice", "tag": "SoIM", "points": 3},
        {"rank": 2, "name": "B", "alliance": "SwarmOflnfectedMice", "tag": "SolM", "points": 2},
        {"rank": 3, "name": "C", "alliance": "SwarmOfInfectedMice", "tag": "SoIM", "points": 1},
        {"rank": 4, "name": "D", "alliance": "FishAndFriends", "tag": "FfS", "points": 0},
    ]
    result = store.canonicalize(mixed)
    assert {r["alliance"] for r in result[:3]} == {"SwarmOfInfectedMice"} and {r["tag"] for r in result[:3]} == {"SoIM"}
    assert result[3]["alliance"] == "FishAndFriends"
    earlier = [("SwarmOflnfectedMice", "SolM")] * 3  # earlier days outvote this day's single misreading
    assert store.canonicalize(mixed[1:2], earlier)[0]["alliance"] == "SwarmOflnfectedMice"


def test_spelling_key_merges_look_alikes():
    assert store.spelling_key("Bella1401") == store.spelling_key("BellaI401") == store.spelling_key("bellal4o1")
    assert store.spelling_key("Sauron") != store.spelling_key("Sauron2")


def test_the_table_has_points_per_day_total_average_and_median(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CORRECTIONS", tmp_path / "none.json")
    week = store.new_week("2026-W47", date(2026, 11, 16))
    week["meta"] = {"my_alliance": "Mice", "my_tag": "SoIM"}
    monday = date(2026, 11, 16)
    store.put_day(week, "mon", monday, rows((1, "Bella1401", 100), (2, "Bob", 50)), utc(2026, 11, 17, 5), True, True)
    store.put_day(week, "tue", monday, rows((1, "Bella1401", 300), (2, "Bob", 40)), utc(2026, 11, 18, 5), True, True)
    # read with an I for the 1 on the third day, and Bob is not in that day's list
    store.put_day(week, "wed", monday, rows((1, "BellaI401", 200)), utc(2026, 11, 18, 12), False, True)
    table = aggregate.week_table(week)
    assert table["days"] == ["mon", "tue", "wed"] and table["my_alliance"] == "Mice"
    ann, bob = table["players"]
    assert (ann["name"], ann["points"], ann["total"], ann["average"], ann["median"]) == (
        "Bella1401",
        {"mon": 100, "tue": 300, "wed": 200},
        600,
        200,
        200,
    )
    assert (bob["points"]["wed"], bob["total"], bob["average"], bob["median"], bob["days"]) == (None, 90, 45, 45, 2)
    assert table["final"] == {"mon": True, "tue": True, "wed": False}


def test_median_of_an_even_number_of_days_is_rounded(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CORRECTIONS", tmp_path / "none.json")
    week = store.new_week("2026-W47", date(2026, 11, 16))
    for day, points in (("mon", 10), ("tue", 21), ("wed", 40), ("thu", 100)):
        store.put_day(week, day, date(2026, 11, 16), rows((1, "Ann", points)), utc(2026, 11, 30), True, True)
    player = aggregate.week_table(week)["players"][0]
    assert (player["total"], player["average"], player["median"]) == (171, 43, 30)


def test_putting_a_day_replaces_an_earlier_scan_of_it(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CORRECTIONS", tmp_path / "none.json")
    week = store.new_week("2026-W47", date(2026, 11, 16))
    store.put_day(week, "mon", date(2026, 11, 16), rows((1, "Ann", 1)), utc(2026, 11, 16, 10), False, True)
    store.put_day(week, "mon", date(2026, 11, 16), rows((1, "Ann", 5)), utc(2026, 11, 17, 10), True, True)
    assert week["days"]["mon"]["rows"][0]["points"] == 5 and week["days"]["mon"]["final"]
    with pytest.raises(ValueError):
        store.put_day(week, "sun", date(2026, 11, 16), [], utc(2026, 11, 17), True, True)


def stored_week(week_id="2026-W47", monday=date(2026, 11, 16), **days):
    """A week file in memory: days = {"mon": rows, ...}, each captured and final."""
    week = store.new_week(week_id, monday)
    week["meta"] = {"my_alliance": "Mice", "my_tag": "SolM"}
    for day, entries in days.items():
        store.put_day(week, day, monday, rows(*entries), utc(2026, 12, 31), True, True)
    return week


def test_an_empty_name_is_stored_as_a_question_mark():
    week = stored_week(mon=[(1, "", 5)])
    assert week["days"]["mon"]["rows"][0]["name"] == "?"


def test_the_stored_names_are_as_scanned_and_corrections_apply_when_the_table_is_built():
    week = stored_week(mon=[(1, "paaT", 9), (2, "", 8)], tue=[(1, "paaT", 7), (2, "", 6)])
    for entry in week["days"].values():
        for row in entry["rows"]:
            row["tag"] = "SolM"  # as the OCR reads it
    fixes = corrections.Corrections({"paaT": "ФрауМарта", "SolM": "SoIM", "2026-W47/tue/2": "Ann"})
    assert week["days"]["mon"]["rows"][0]["name"] == "paaT" and week["days"]["mon"]["rows"][0]["tag"] == "SolM"
    table = aggregate.week_table(week, fixes)
    assert sorted(p["name"] for p in table["players"]) == ["?", "Ann", "ФрауМарта"]
    assert next(p for p in table["players"] if p["name"] == "ФрауМарта")["total"] == 16  # both days, one player
    ann = next(p for p in table["players"] if p["name"] == "Ann")
    assert ann["points"] == {"mon": None, "tue": 6}  # that card only
    assert {p["tag"] for p in table["players"]} == {"SoIM"} and table["my_tag"] == "SoIM"
    assert aggregate.week_table(week, corrections.Corrections())["my_tag"] == "SolM"  # nothing changed in the file


def test_a_rename_in_the_middle_of_the_week_is_one_player_through_an_alias(tmp_path):
    week = stored_week(mon=[(1, "Bob", 100), (2, "Cy", 50)], tue=[(1, "Robert", 300), (2, "Cy", 40)])
    without = aggregate.week_table(week, corrections.Corrections())
    assert sorted((p["name"], p["days"]) for p in without["players"]) == [("Bob", 1), ("Cy", 2), ("Robert", 1)]
    fixes = tmp_path / "corrections.json"
    fixes.write_text(json.dumps({"aliases": {"Bob": "Robert"}}), encoding="utf-8")
    table = aggregate.week_table(week, corrections.load(fixes))
    robert = table["players"][0]
    assert (robert["name"], robert["points"], robert["total"], robert["average"], robert["median"]) == (
        "Robert",
        {"mon": 100, "tue": 300},
        400,
        200,
        200,
    )
    assert [p["name"] for p in table["players"]] == ["Robert", "Cy"]


def test_aliases_follow_a_chain_of_renames_and_match_look_alike_spellings():
    fixes = corrections.Corrections(aliases={store.spelling_key("A1"): "B", store.spelling_key("B"): "C"})
    assert fixes.rename("A1") == "C" and fixes.rename("AI") == "C"  # 1 and I read alike
    assert fixes.rename("Zed") == "Zed"
    loop = corrections.Corrections(aliases={store.spelling_key("X"): "Y", store.spelling_key("Y"): "X"})
    assert loop.rename("X") in ("X", "Y")  # a loop does not hang


def test_an_alias_applies_to_every_week_without_scanning_again(tmp_path):
    fixes = corrections.Corrections(aliases={store.spelling_key("Bob"): "Robert"})
    older = stored_week("2026-W46", date(2026, 11, 9), mon=[(1, "Bob", 10)])
    newer = stored_week("2026-W47", date(2026, 11, 16), mon=[(1, "Robert", 20)])
    assert aggregate.week_table(older, fixes)["players"][0]["name"] == "Robert"
    assert aggregate.week_table(newer, fixes)["players"][0]["name"] == "Robert"
    assert older["days"]["mon"]["rows"][0]["name"] == "Bob"  # the stored week is untouched


def test_the_corrections_file_has_two_sections_and_may_be_missing(tmp_path):
    assert corrections.load(tmp_path / "none.json") == corrections.Corrections()
    path = tmp_path / "corrections.json"
    path.write_text(json.dumps({"corrections": {"SolM": "SoIM"}, "aliases": {"Bob": "Robert"}}), encoding="utf-8")
    loaded = corrections.load(path)
    assert loaded.fix("SolM") == "SoIM" and loaded.fix("other") == "other" and loaded.rename("Bob") == "Robert"
    path.write_text("{}", encoding="utf-8")
    assert corrections.load(path) == corrections.Corrections()


def test_the_phase_is_how_many_daily_rewards_the_points_reach():
    edges = (0, 37_999, 38_000, 144_999, 145_000, 1_019_999, 1_020_000)
    assert [aggregate.phase(p) for p in edges] == [0, 0, 1, 1, 2, 4, 5]
    assert aggregate.phase(7_189_999) == 8 and aggregate.phase(7_190_000) == 9 and aggregate.phase(99_000_000) == 9
    assert aggregate.phase(None) is None


def test_the_colour_scale_is_red_at_phase_5_amber_at_phase_7_and_green_at_phase_9():
    assert [aggregate.heat(p) for p in (0, 38_000, 1_020_000)] == [0.0, 0.0, 0.0]  # phase 5 and below: red
    assert aggregate.heat(2_630_000) == 0.5  # phase 7: amber
    assert aggregate.heat(7_190_000) == 1.0 and aggregate.heat(60_000_000) == 1.0  # phase 9 and more: green
    assert aggregate.heat(1_825_000) == 0.25  # half way from phase 5 to phase 7
    assert aggregate.heat(4_910_000) == 0.75  # half way from phase 7 to phase 9
    values = [aggregate.heat(p) for p in range(0, 9_000_000, 250_000)]
    assert values == sorted(values) and aggregate.heat(None) is None  # never goes back down


def test_the_table_carries_the_scale_and_each_cells_heat_and_phase(tmp_path, monkeypatch):
    week = stored_week(
        mon=[(1, "Ann", 8_000_000), (2, "Bob", 2_630_000), (3, "Cy", 900_000)], tue=[(1, "Ann", 1_020_000)]
    )
    table = aggregate.week_table(week, corrections.Corrections())
    assert table["phases"][4] == 1_020_000 and table["phases"][8] == 7_190_000
    assert table["scale"] == [
        {"color": "red", "phase": 5, "points": 1_020_000},
        {"color": "amber", "phase": 7, "points": 2_630_000},
        {"color": "green", "phase": 9, "points": 7_190_000},
    ]
    ann, bob, cy = table["players"][0], table["players"][1], table["players"][2]
    assert (ann["name"], ann["heat"]["mon"], ann["phase"]["mon"]) == ("Ann", 1.0, 9)
    assert (ann["heat"]["tue"], ann["phase"]["tue"]) == (0.0, 5)
    assert ann["average"] == 4_510_000
    assert ann["heat"]["average"] == aggregate.heat(4_510_000)  # the average is coloured too
    assert "total" not in ann["heat"]  # the total is not a day's points
    assert (bob["heat"]["mon"], bob["heat"]["tue"], bob["phase"]["tue"]) == (0.5, None, None)  # not in Tuesday's list
    assert (cy["heat"]["mon"], cy["phase"]["mon"]) == (0.0, 4)
