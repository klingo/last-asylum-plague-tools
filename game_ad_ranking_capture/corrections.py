"""`corrections.json`: what the OCR got wrong, and players who changed their names. Applied when the table is built.

    {"corrections": {"SolM": "SoIM", "2026-W47/mon/18": "Name"}, "aliases": {"OldName": "NewName"}}

- `corrections`: a misread text is replaced wherever it is a name, an alliance or a tag; `<week>/<day>/<rank>` sets the
  name of that one card (for a name the OCR cannot read at all, stored as `?`; the crop is in `review/<week>/<day>/`).
- `aliases`: a player who renamed. `"OldName": "NewName"` makes every card named OldName, in every week, a card of
  NewName, so the days before and after the rename are one player. A name is matched like the table matches players
  (look-alike characters merged), and renames can be chained (A to B, B to C).

Nothing is changed in the weekly files: the corrections are applied to what is read from them, so editing this file
takes effect at once, also on days that are final and never scanned again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import config as C
from store import spelling_key

MAX_CHAIN = 5  # renames followed one after the other


@dataclass
class Corrections:
    fixes: dict[str, str] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)  # spelling key of the old name -> the name to use

    def fix(self, text: str) -> str:
        return self.fixes.get(text, text)

    def rename(self, name: str) -> str:
        for _ in range(MAX_CHAIN):
            new = self.aliases.get(spelling_key(name))
            if not new or new == name:
                break
            name = new
        return name

    def row(self, row: dict, week: str, day: str) -> dict:
        """The row as it is meant: OCR fixes on name, alliance and tag, a card-specific name, then renames."""
        name = self.fixes.get(f"{week}/{day}/{row['rank']}") or self.fix(row["name"])
        return {**row, "name": self.rename(name), "alliance": self.fix(row["alliance"]), "tag": self.fix(row["tag"])}


def load(path: Path | None = None) -> Corrections:
    path = path or C.CORRECTIONS
    if not path.exists():
        return Corrections()
    raw = json.loads(path.read_text(encoding="utf-8"))
    aliases = {spelling_key(old): new for old, new in raw.get("aliases", {}).items()}
    return Corrections(dict(raw.get("corrections", {})), aliases)
