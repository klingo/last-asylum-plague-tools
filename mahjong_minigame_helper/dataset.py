"""How much useful test data the recordings hold: per recording its boards and how the game ended, and overall how
many complete games there are against the target of the v2 plan.

A complete game (won or lost) is what makes a recording valuable: by its end every covered tile has shown its icon,
so every earlier board can be labelled. A game cut short (recording stopped or crashed mid-game) still helps, less.
`train` learns the icons from them; `evaluate` measures against them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2

TARGET_GAMES = 5  # complete games before training is worth it
GOOD_GAMES = 10  # beyond this, more games still help, but much less


@dataclass
class Recording:
    name: str
    boards: int  # saved frames that show a game board
    frames: int
    seconds: float | None
    ending: str  # "won", "lost", "cut short", "no board", "empty"

    @property
    def complete(self) -> bool:
        return self.ending in ("won", "lost")


def board_state(img) -> tuple[int, int, int] | None:
    """(tiles on the board, tiles in the tray, covered tiles), or None if no game board is on the picture."""
    import vision as V

    frame = V.read_frame(img)
    if frame is None or frame.lattice is None:
        return None
    return len(frame.tiles), len(frame.tray), sum(not t.free for t in frame.tiles)


def ending(states: list[tuple[int, int, int] | None], tray_size: int, match: int = 3) -> str:
    """How the game ended, from the board states of the last frames (oldest first)."""
    boards = [s for s in states if s is not None]
    if not boards:
        return "no board"
    tiles, tray, covered = boards[-1]
    after = states[-1] is None  # another screen (result, menu) followed the last board
    if tray >= tray_size:
        return "lost"
    if tiles == 0 or (after and tiles <= 3):
        return "won"  # the board was (nearly) cleared and a result screen followed
    if covered == 0 and (tiles + tray) % match == 0 and tiles + tray <= tray_size:
        return "won"  # only full sets left, all free, and they fit in the tray: the last taps can't fail
    if after and tray >= tray_size - 1:
        return "lost"  # an almost full tray, then the "game over" screen covered the board
    return "cut short"


def summarise(folder: Path, tray_size: int = 7, tail: int = 3, match: int = 3) -> Recording:
    meta_path = folder / "game.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"frames": []}
    entries = meta.get("frames") or [{"file": p.name} for p in sorted(folder.glob("*.png"))]
    if not entries:
        return Recording(folder.name, 0, 0, None, "empty")
    states = []
    for e in entries[-tail:]:  # how it ended
        img = cv2.imread(str(folder / e["file"]))
        states.append(None if img is None else board_state(img))
    boards = len(entries) - sum(s is None for s in states)  # the earlier frames are boards while playing
    times = [e["t"] for e in entries if "t" in e]
    return Recording(folder.name, boards, len(entries), times[-1] if times else None, ending(states, tray_size, match))


def report(root: Path, tray_size: int = 7, match: int = 3) -> tuple[str, str]:
    """(one-line verdict, details per recording) for the recordings folder."""
    folders = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("_")) if root.exists() else []
    recs = [summarise(f, tray_size, match=match) for f in folders]
    complete = sum(r.complete for r in recs)
    partial = sum(r.ending == "cut short" for r in recs)
    lines = []
    for r in recs:
        length = f"{r.seconds / 60:.1f} min" if r.seconds else "?"
        lines.append(f"{r.name}: {r.boards} boards, {length}, {r.ending}")
    if complete >= GOOD_GAMES:
        verdict = f"{complete} complete games: plenty. After a few new games, click Train again."
    elif complete >= TARGET_GAMES:
        verdict = f"{complete} complete games: enough to train (click Train). Up to {GOOD_GAMES} is even better."
    else:
        more = TARGET_GAMES - complete
        extra = f" (+{partial} cut short, which count less)" if partial else ""
        verdict = f"{complete} of {TARGET_GAMES} complete games{extra}: record {more} more, each from the first board to the end."
    size = sum(f.stat().st_size for folder in folders for f in folder.iterdir() if f.is_file())
    if size >= 100e6:  # worth knowing when the disk fills up: short cut-short games go first
        verdict += f" Recordings use {size / 1e9:.1f} GB."
    return verdict, "\n".join(lines) or "No recordings yet."
