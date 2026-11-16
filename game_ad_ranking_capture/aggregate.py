"""A week file -> the table the viewer shows: points per day, total, average and median per player.

A player is one `spelling_key` of the name (the OCR may read the same name with an `I` one day and an `l` another),
shown with the spelling read most often, after `corrections.py` has fixed the OCR's misreadings and joined a player's
old and new names (a rename). A player who is not in a day's list has no points for that day (`None`, shown
as a dash): such a day is left out of the average and the median, not counted as 0. The alliance is the one of the
player's latest day.

The daily points, the average and the median are put on a colour scale from the Duel's daily reward phases
(`config.PHASES`, `config.COLOR_SCALE`): `heat` is 0 (red) at the first anchor's points, 0.5 (amber) at the second's, 1
(green) at the third's and above, blended in between; `phase` is how many of the 9 phases the points reach. The total
has none: it is not a day's points.

A member's alliance rank (R5 .. R1) comes from the member list (the latest day's list that has them); players the
lists do not know, such as those of other alliances, have none.

An alliance member (`roster.py`) who is not in a day's ranking made 0 points that day: the ranking only lists players
with points. Such a member gets 0 for the day, counted in the average and the median (`filled` lists those days);
members of an older roster snapshot are only counted from the day it was valid. Other alliances' players stay as
they are.
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import date

import config as C
import corrections
import roster as roster_file
from store import UNREADABLE, spelling_key


def phase(points: int | None) -> int | None:
    """How many of the daily reward phases the points reach (0 to 9)."""
    return None if points is None else sum(points >= needed for needed in C.PHASES)


def heat(points: int | None) -> float | None:
    """Where the points are on the colour scale: 0 = red, 0.5 = amber, 1 = green (below / above the ends: clamped)."""
    if points is None:
        return None
    anchors = [C.PHASES[number - 1] for _, number in C.COLOR_SCALE]
    if points <= anchors[0]:
        return 0.0
    for index in range(1, len(anchors)):
        if points <= anchors[index]:
            low, high = anchors[index - 1], anchors[index]
            return round((index - 1 + (points - low) / (high - low)) / (len(anchors) - 1), 4)
    return 1.0


def week_table(
    week: dict, fixes: corrections.Corrections | None = None, roster: roster_file.Roster | None = None
) -> dict:
    fixes = fixes or corrections.load()
    roster = roster if roster is not None else roster_file.load()
    days = [day for day in C.DAYS if day in week["days"] and week["days"][day]["rows"]]
    players: dict[str, dict] = {}
    for day in days:
        for stored in week["days"][day]["rows"]:
            row = fixes.row(stored, week["week"], day)
            # a name the OCR could not read says nothing about who it is: such a card is a player of its own that day
            key = f"?{day}{row['rank']}" if row["name"] == UNREADABLE else spelling_key(row["name"])
            player = players.setdefault(
                key,
                {
                    "spellings": Counter(),
                    "alliance": "",
                    "tag": "",
                    "points": dict.fromkeys(days),
                    "filled": [],
                    "rank": "",
                },
            )
            player["spellings"][row["name"]] += 1
            player["alliance"], player["tag"] = row["alliance"], row["tag"]
            player["points"][day] = row["points"]
    mine = (fixes.fix(week["meta"].get("my_alliance", "")), fixes.fix(week["meta"].get("my_tag", "")))
    for day in days:
        for member in roster.members_on(date.fromisoformat(week["days"][day]["date"])):
            name = fixes.rename(fixes.fix(member["name"]))
            if name == UNREADABLE:
                continue  # a member whose name could not be read cannot be matched with anyone
            player = players.setdefault(
                spelling_key(name),
                {
                    "spellings": Counter({name: 1}),
                    "alliance": mine[0],
                    "tag": mine[1],
                    "points": dict.fromkeys(days),
                    "filled": [],
                    "rank": "",
                },
            )
            player["rank"] = member["rank"]  # the days run in order: the latest list that has the member decides
            if player["points"][day] is None:
                player["points"][day] = 0
                player["filled"].append(day)
    table = []
    for player in players.values():
        values = [points for points in player["points"].values() if points is not None]
        table.append(
            {
                "name": player["spellings"].most_common(1)[0][0],
                "alliance": player["alliance"],
                "tag": player["tag"],
                "alliance_rank": player["rank"],
                "points": player["points"],
                "total": sum(values),
                "average": round(statistics.mean(values)),
                "median": round(statistics.median(values)),
                "days": len(values),
                "filled": player["filled"],
            }
        )
        shown = {**table[-1]["points"], "average": table[-1]["average"], "median": table[-1]["median"]}
        table[-1]["heat"] = {key: heat(value) for key, value in shown.items()}
        table[-1]["phase"] = {key: phase(value) for key, value in shown.items()}
    table.sort(key=lambda entry: (-entry["total"], entry["name"].lower()))
    return {
        "week": week["week"],
        "start": week["start"],
        "my_alliance": fixes.fix(week["meta"].get("my_alliance", "")),
        "my_tag": fixes.fix(week["meta"].get("my_tag", "")),
        "days": days,
        "dates": {day: week["days"][day]["date"] for day in days},
        "final": {day: week["days"][day]["final"] for day in days},
        "phases": list(C.PHASES),
        "scale": [{"color": color, "phase": number, "points": C.PHASES[number - 1]} for color, number in C.COLOR_SCALE],
        "players": table,
    }
