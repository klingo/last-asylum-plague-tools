"""The member lists, one file per calendar week: which list a day uses, the diff of two lists, the stale-list hints."""

import json
from datetime import date, datetime, timezone

import aggregate
import capture
import corrections
import roster as R
import store
from members_game import VirtualMembers
from test_members_roster import alliance, fake_run, snapshot
from test_weeks_store_aggregate import stored_week, utc


def names_on(roster, day):
    return [m["name"] for m in roster.members_on(date.fromisoformat(day))]


def test_a_week_without_a_list_of_its_own_inherits_the_latest_earlier_one_and_older_weeks_get_none():
    roster = R.Roster()
    snapshot(roster, "2026-11-18", ["Ann", "Bob"])  # read on Wednesday of week 47
    snapshot(roster, "2026-11-25", ["Ann", "Bob", "Cy"])  # read on Wednesday of week 48
    assert names_on(roster, "2026-11-16") == ["Ann", "Bob"]  # Monday, before the list: the week's own first list
    assert names_on(roster, "2026-11-17") == ["Ann", "Bob"]
    assert names_on(roster, "2026-11-19") == ["Ann", "Bob"] and names_on(roster, "2026-11-23") == ["Ann", "Bob"]
    assert names_on(roster, "2026-11-24") == ["Ann", "Bob"]  # Tuesday of week 48: the list read after it is not used
    assert names_on(roster, "2026-11-25") == ["Ann", "Bob", "Cy"] and names_on(roster, "2026-12-20") == [
        "Ann",
        "Bob",
        "Cy",
    ]
    assert names_on(roster, "2026-11-09") == [] and names_on(roster, "2026-11-15") == []  # before the first week: none


def test_the_lists_are_stored_one_file_per_week_and_a_scan_of_the_same_day_replaces_it(tmp_path):
    roster = R.Roster()
    snapshot(roster, "2026-11-16", ["Ann"])
    snapshot(roster, "2026-11-16", ["Ann", "Љубица"])  # read again the same day
    snapshot(roster, "2026-11-25", ["Ann", "Љубица", "Cy"])
    assert [len(s["members"]) for s in roster.snapshots] == [2, 3]
    paths = R.save(roster, tmp_path)
    assert [p.name for p in paths] == ["2026-W47.json", "2026-W48.json"]
    text = (tmp_path / "2026-W47.json").read_text(encoding="utf-8")
    assert json.loads(text)["week"] == "2026-W47" and "Љубица" in text and text.endswith("}\n")
    assert R.load(tmp_path).snapshots == roster.snapshots and R.load(tmp_path / "none").snapshots == []


def test_a_list_read_for_an_earlier_date_goes_to_that_weeks_file(tmp_path):
    roster = R.Roster()
    roster.add(date(2026, 11, 11), utc(2026, 11, 20), [{"name": "Ann", "rank": "R3"}], 1)  # --since: an older change
    assert [p.name for p in R.save(roster, tmp_path)] == ["2026-W46.json"]


def test_who_joined_and_who_left_between_two_lists():
    before = [{"name": "Ann", "rank": "R3"}, {"name": "Bob", "rank": "R3"}, {"name": "?", "rank": "R3"}]
    after = [{"name": "ANN", "rank": "R4"}, {"name": "Cy", "rank": "R3"}, {"name": "?", "rank": "R3"}]
    assert R.changes(before, after) == (["Cy"], ["Bob"])  # a rank change is no change, `?` cannot be compared


def test_the_ranking_hints_that_the_list_is_out_of_date():
    members = [{"name": "Ann", "rank": "R3"}, {"name": "Bob", "rank": "R3"}]
    mine = ("Mice", "SoIM")
    rows = [
        {"rank": 1, "name": "Ann", "alliance": "Mice", "tag": "SoIM", "points": 9},
        {"rank": 2, "name": "Newbie", "alliance": "Mice", "tag": "SoIM", "points": 8},  # not in the list: joined?
        {"rank": 3, "name": "Bob", "alliance": "Fish", "tag": "FfS", "points": 7},  # listed, plays for Fish: left?
        {"rank": 4, "name": "Stranger", "alliance": "Fish", "tag": "FfS", "points": 6},  # not ours: nothing to say
    ]
    plain = corrections.Corrections()
    notes = R.hints(rows, members, "2026-W47", "mon", plain, mine)
    assert "1 players of your alliance are not in the member list (joined?): Newbie" in notes[0]
    assert "1 listed members play for another alliance (left?): Bob" in notes[1]
    assert "Read the member list again" in notes[2]
    assert R.hints(rows, [], "2026-W47", "mon", plain, mine) == []  # no list: no opinion
    assert R.hints(rows[:1] + rows[3:], members, "2026-W47", "mon", plain, mine) == []
    renamed = corrections.Corrections(aliases={store.spelling_key("Newbie"): "Ann"})  # a rename is not a joiner
    assert R.hints(rows[:2], members, "2026-W47", "mon", renamed, mine) == []


def test_players_outside_the_alliance_or_before_the_first_list_stay_as_they_are():
    week = stored_week(mon=[(1, "Ann", 5_000_000), (2, "Out", 4_000_000)], tue=[(1, "Ann", 3_000_000)])
    roster = R.Roster()
    snapshot(roster, "2026-11-17", ["Ann", "Bob"])  # read on Tuesday: Monday of the same week is covered too
    by_name = {p["name"]: p for p in aggregate.week_table(week, corrections.Corrections(), roster)["players"]}
    assert by_name["Bob"]["points"] == {"mon": 0, "tue": 0}
    assert by_name["Out"]["points"] == {"mon": 4_000_000, "tue": None}  # another alliance: no zero is invented
    later = R.Roster()
    snapshot(later, "2026-11-24", ["Ann", "Bob"])  # the first list is from the next week: this week has none
    table = aggregate.week_table(week, corrections.Corrections(), later)
    assert not any(p["filled"] for p in table["players"]) and "Bob" not in [p["name"] for p in table["players"]]


def test_a_player_who_joined_after_the_list_was_read_counts_from_the_first_day_they_are_ranked():
    week = stored_week(
        mon=[(1, "Ann", 5_000_000)],
        tue=[(1, "Ann", 3_000_000), (2, "Newbie", 2_000_000)],  # joined on Tuesday: not in the list
        wed=[(1, "Ann", 1_000_000)],  # Newbie made nothing on Wednesday
    )
    week["meta"]["my_tag"] = "SoIM"  # as the rows spell it (the fixture's own tag is the corrected one)
    roster = R.Roster()
    snapshot(roster, "2026-11-16", ["Ann"])
    by_name = {p["name"]: p for p in aggregate.week_table(week, corrections.Corrections(), roster)["players"]}
    assert by_name["Newbie"]["points"] == {"mon": None, "tue": 2_000_000, "wed": 0}  # Monday: no member yet
    assert by_name["Newbie"]["filled"] == ["wed"] and by_name["Newbie"]["average"] == 1_000_000
    assert by_name["Ann"]["filled"] == []
    snapshot(roster, "2026-11-17", ["Ann", "Newbie"])  # the list read on Tuesday has them: the same result
    again = {p["name"]: p for p in aggregate.week_table(week, corrections.Corrections(), roster)["players"]}
    assert again["Newbie"]["points"] == by_name["Newbie"]["points"]


def test_a_list_is_stored_from_the_day_it_was_read_with_the_changes_since_the_one_before(monkeypatch, tmp_path):
    scan, stored = fake_run(monkeypatch, tmp_path / "members", alliance(folded={2}))  # Wednesday 2026-11-18
    assert stored and len(scan.members) == 19 and (scan.joined, scan.left) == ([], [])  # the first: no comparison
    assert [s["since"] for s in R.load(tmp_path / "members").snapshots] == ["2026-11-18"]
    smaller = VirtualMembers([(4, ["Officer0", "Officer1"]), (3, ["Member0", "NewMember"])])
    friday = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
    scan, stored = fake_run(monkeypatch, tmp_path / "members", smaller, now=friday)
    assert stored and [s["since"] for s in R.load(tmp_path / "members").snapshots] == ["2026-11-18", "2026-11-20"]
    assert scan.joined == ["NewMember"] and "Officer3" in scan.left and len(scan.left) == 15
    again, _ = fake_run(monkeypatch, tmp_path / "members", smaller, now=friday.replace(hour=15))
    assert len(R.load(tmp_path / "members").snapshots) == 2 and again.joined == [] and again.left == []  # replaced


def test_a_ranking_scan_reports_names_that_do_not_match_the_member_list(monkeypatch, tmp_path):
    from test_screens_capture import FakeClockDevice, FakeNavigator, FakeScanner

    monkeypatch.setattr(capture, "Navigator", FakeNavigator)
    monkeypatch.setattr(capture, "Scanner", FakeScanner)
    FakeScanner.scans, FakeScanner.complete = [], True
    monkeypatch.setattr(capture.weeks, "now_utc", lambda: datetime(2026, 11, 17, 12, tzinfo=timezone.utc))
    roster = R.Roster()
    roster.add(date(2026, 11, 16), utc(2026, 11, 16), [{"name": "Someone", "rank": "R3"}], 1)  # not "Klingo"
    R.save(roster, tmp_path / "members")
    results = capture.run_capture(
        FakeClockDevice(),
        days=("mon",),
        progress=lambda t: None,
        directory=tmp_path,
        review_directory=tmp_path / "review",
        roster_directory=tmp_path / "members",
        primary=object(),
        secondary=object(),
    )
    assert any("not in the member list (joined?): Klingo" in w for w in results[0].warnings)


def test_a_members_alliance_rank_is_in_the_table_the_latest_list_deciding():
    week = stored_week(
        mon=[(1, "Ann", 9_000_000), (2, "Bob", 8_000_000), (3, "Out", 7_000_000)],
        tue=[(1, "Ann", 9_000_000), (2, "BellaI401", 8_000_000)],
    )
    roster = R.Roster()
    roster.add(
        date(2026, 11, 16),
        utc(2026, 11, 16),
        [{"name": "Ann", "rank": "R4"}, {"name": "Bob", "rank": "R3"}, {"name": "Bella1401", "rank": "R3"}],
        3,
    )
    roster.add(
        date(2026, 11, 17),
        utc(2026, 11, 17),
        [{"name": "Ann", "rank": "R5"}, {"name": "Bella1401", "rank": "R3"}],  # Ann was promoted, Bob left
        2,
    )
    by_name = {p["name"]: p for p in aggregate.week_table(week, corrections.Corrections(), roster)["players"]}
    assert by_name["Ann"]["alliance_rank"] == "R5"  # Tuesday's list wins
    assert by_name["Bob"]["alliance_rank"] == "R3"  # not in Tuesday's list: the last rank he is known by
    assert by_name["BellaI401"]["alliance_rank"] == "R3"  # a look-alike spelling is the same player
    assert by_name["Out"]["alliance_rank"] == ""  # another alliance: the member list does not know him
    assert aggregate.week_table(week, corrections.Corrections(), R.Roster())["players"][0]["alliance_rank"] == ""
