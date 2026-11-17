"""The weekly files: `data/<year>-W<week>.json`, one per calendar week, written so a git diff shows what changed.

A week is `{"week", "start", "meta": {"my_name", "my_alliance", "my_tag"}, "days": {"mon": {"date", "captured_at",
"final", "complete", "rows": [{"rank", "name", "alliance", "tag", "points"}]}}}`. `meta` may also hold
`"opponent_members"`, entered by hand: the other alliance's member count, for the members that are in no list (0
points); a scan leaves it alone. Rows are kept sorted by rank, one per line. The names are as the OCR read them
(`corrections.py` fixes them when the table is built); `canonicalize` makes every spelling of one alliance (the OCR reads `SoIM` as `SolM` now and then) the one that was read most often.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import config as C
from weeks import day_date

ROW_KEYS = ("rank", "name", "alliance", "tag", "points")
UNREADABLE = "?"  # the name of a card whose name the OCR could not read (a name made of symbols)
CONFUSABLE = str.maketrans({"l": "i", "|": "i", "1": "i", "0": "o"})  # applied to the lower-cased text (I -> i, O -> o)


def spelling_key(text: str) -> str:
    """The text without spaces or case, with look-alike characters (I l | 1, 0 O) merged: one key is one name."""
    return re.sub(r"\s+", "", text).lower().translate(CONFUSABLE)


def week_path(week: str, directory: Path = C.DATA_DIR) -> Path:
    return directory / f"{week}.json"


def new_week(week: str, monday: date) -> dict:
    return {"week": week, "start": monday.isoformat(), "meta": {}, "days": {}}


def list_weeks(directory: Path = C.DATA_DIR) -> list[str]:
    return sorted(path.stem for path in directory.glob("*-W*.json")) if directory.exists() else []


def load(week: str, directory: Path = C.DATA_DIR) -> dict | None:
    """The week's file, found among the files that exist: `week` is only compared with their names, never made into
    a path (the viewer server passes it on from a request)."""
    for path in sorted(directory.glob("*-W*.json")) if directory.exists() else []:
        if path.stem == week:
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def dumps(week: dict) -> str:
    """The file's text: indented, but a row on one line (a day has up to 200 of them)."""
    lines = ["{", f'  "week": {json.dumps(week["week"])},', f'  "start": {json.dumps(week["start"])},']
    lines.append(f'  "meta": {json.dumps(week["meta"], ensure_ascii=False)},')
    lines.append('  "days": {')
    days = [day for day in C.DAYS if day in week["days"]]
    for index, day in enumerate(days):
        entry = week["days"][day]
        lines.append(f'    "{day}": {{')
        for key in ("date", "captured_at", "final", "complete"):
            lines.append(f'      "{key}": {json.dumps(entry[key])},')
        lines.append('      "rows": [')
        rows = sorted(entry["rows"], key=lambda row: row["rank"])
        for number, row in enumerate(rows):
            text = json.dumps({key: row[key] for key in ROW_KEYS}, ensure_ascii=False)
            lines.append(f"        {text}{',' if number < len(rows) - 1 else ''}")
        lines.append("      ]")
        lines.append("    }" + ("," if index < len(days) - 1 else ""))
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"


def save(week: dict, directory: Path = C.DATA_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = week_path(week["week"], directory)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(dumps(week), encoding="utf-8", newline="\n")
    temporary.replace(path)  # a half-written file never replaces the good one
    return path


def canonicalize(rows: list[dict], known: list[tuple[str, str]] | None = None) -> list[dict]:
    """Every spelling of an alliance (and its tag) becomes the most frequent one; `known` (earlier days) counts too."""
    votes: dict[str, Counter] = {}
    for alliance, tag in [*(known or []), *((row["alliance"], row["tag"]) for row in rows)]:
        votes.setdefault(spelling_key(alliance + "|" + tag), Counter())[(alliance, tag)] += 1
    best = {key: counter.most_common(1)[0][0] for key, counter in votes.items()}
    result = []
    for row in rows:
        alliance, tag = best[spelling_key(row["alliance"] + "|" + row["tag"])]
        result.append({**row, "alliance": alliance, "tag": tag})
    return result


def is_final(week: dict, day: str) -> bool:
    return bool(week["days"].get(day, {}).get("final"))


def put_day(
    week: dict, day: str, monday: date, rows: list[dict], captured_at: datetime, final: bool, complete: bool
) -> None:
    """Stores a scanned day, replacing an earlier scan of it (a name the OCR could not read is stored as `?`)."""
    rows = [{**row, "name": row["name"] or UNREADABLE} for row in rows]
    known = [(r["alliance"], r["tag"]) for entry in week["days"].values() for r in entry["rows"]]
    week["days"][day] = {
        "date": day_date(monday, day).isoformat(),
        "captured_at": captured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "final": final,
        "complete": complete,
        "rows": sorted(canonicalize(rows, known), key=lambda row: row["rank"]),
    }
