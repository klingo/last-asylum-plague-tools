"""`data/members/<year>-W<week>.json`: who was in the alliance, as lists read from the Alliance Members screen.

One file per calendar week, like the points files: `{"week", "snapshots": [{"since", "scanned_at", "total", "members":
[{"name", "rank"}]}]}`. A snapshot is valid from its `since` date, the game day it was read (or the date given with
`--since` when a change is known to be older), until the next one. The list is read on demand, when someone joined or
left, so a week without a list of its own uses the latest earlier one.

For a day the members are those of the latest snapshot valid by then; if there is none, those of the earliest
snapshot of the same calendar week (a first list read on Wednesday covers Monday and Tuesday too); else the day has no
member list and no zeros are invented for it (weeks before the first list). Reading the list again on the same day
replaces that snapshot. `changes` tells who joined or left since the list that applied before, `hints` which names of a
day's ranking suggest that the list is out of date.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import config as C
import corrections
import weeks
from store import UNREADABLE, spelling_key


@dataclass
class Roster:
    snapshots: list[dict] = field(default_factory=list)

    def snapshot_for(self, day: date) -> dict | None:
        valid = [s for s in self.snapshots if date.fromisoformat(s["since"]) <= day]
        if valid:
            return max(valid, key=lambda s: s["since"])
        same_week = [s for s in self.snapshots if weeks.week_id(date.fromisoformat(s["since"])) == weeks.week_id(day)]
        return min(same_week, key=lambda s: s["since"]) if same_week else None

    def members_on(self, day: date) -> list[dict]:
        snapshot = self.snapshot_for(day)
        return snapshot["members"] if snapshot else []

    def add(self, since: date, scanned_at: datetime, members: list[dict], total: int | None) -> None:
        self.snapshots = [s for s in self.snapshots if s["since"] != since.isoformat()]
        self.snapshots.append(
            {
                "since": since.isoformat(),
                "scanned_at": scanned_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "total": total,
                "members": sorted(members, key=lambda m: (-int(m["rank"][1:]), m["name"].lower())),
            }
        )
        self.snapshots.sort(key=lambda s: s["since"])


def week_path(week: str, directory: Path | None = None) -> Path:
    return (directory or C.ROSTER_DIR) / f"{week}.json"


def load(directory: Path | None = None) -> Roster:
    directory = directory or C.ROSTER_DIR
    snapshots: list[dict] = []
    for path in sorted(directory.glob("*-W*.json")) if directory.exists() else []:
        snapshots += json.loads(path.read_text(encoding="utf-8"))["snapshots"]
    return Roster(sorted(snapshots, key=lambda s: s["since"]))


def dumps(week: str, snapshots: list[dict]) -> str:
    """A week file's text: a member on one line, so a diff shows who joined or left."""
    lines = ["{", f'  "week": {json.dumps(week)},', '  "snapshots": [']
    for index, snapshot in enumerate(snapshots):
        lines.append("    {")
        for key in ("since", "scanned_at", "total"):
            lines.append(f'      "{key}": {json.dumps(snapshot[key])},')
        lines.append('      "members": [')
        for number, member in enumerate(snapshot["members"]):
            comma = "," if number < len(snapshot["members"]) - 1 else ""
            lines.append(f"        {json.dumps(member, ensure_ascii=False)}{comma}")
        lines.append("      ]")
        lines.append("    }" + ("," if index < len(snapshots) - 1 else ""))
    return "\n".join([*lines, "  ]", "}"]) + "\n"


def save(roster: Roster, directory: Path | None = None) -> list[Path]:
    """Writes every week that has snapshots (a snapshot goes to the week of its `since`)."""
    directory = directory or C.ROSTER_DIR
    directory.mkdir(parents=True, exist_ok=True)
    by_week: dict[str, list[dict]] = {}
    for snapshot in roster.snapshots:
        by_week.setdefault(weeks.week_id(date.fromisoformat(snapshot["since"])), []).append(snapshot)
    paths = []
    for week, snapshots in sorted(by_week.items()):
        path = week_path(week, directory)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(dumps(week, snapshots), encoding="utf-8", newline="\n")
        temporary.replace(path)
        paths.append(path)
    return paths


def changes(before: list[dict], after: list[dict]) -> tuple[list[str], list[str]]:
    """(joined, left): the names in `after` that are not in `before`, and the other way round."""
    old = {spelling_key(m["name"]): m["name"] for m in before if m["name"] != UNREADABLE}
    new = {spelling_key(m["name"]): m["name"] for m in after if m["name"] != UNREADABLE}
    return [name for key, name in new.items() if key not in old], [name for key, name in old.items() if key not in new]


def hints(
    rows: list[dict], members: list[dict], week: str, day: str, fixes: corrections.Corrections, mine: tuple[str, str]
) -> list[str]:
    """What a day's ranking says about a member list that does not match it. Players of the own alliance who are not in
    the list probably joined; listed members who play for another alliance in the ranking probably left."""
    if not members:
        return []
    known = {spelling_key(fixes.rename(fixes.fix(m["name"]))) for m in members if m["name"] != UNREADABLE}
    joined, left = [], []
    for stored in rows:
        row = fixes.row(stored, week, day)
        if row["name"] == UNREADABLE:
            continue
        own = (row["alliance"], row["tag"]) == mine
        if own and spelling_key(row["name"]) not in known:
            joined.append(row["name"])
        elif not own and spelling_key(row["name"]) in known:
            left.append(row["name"])
    notes = []
    if joined:
        notes.append(
            f"{len(joined)} players of your alliance are not in the member list (joined?): {', '.join(joined[:8])}"
        )
    if left:
        notes.append(f"{len(left)} listed members play for another alliance (left?): {', '.join(left[:8])}")
    if notes:
        notes.append("Read the member list again to bring it up to date (members).")
    return notes
