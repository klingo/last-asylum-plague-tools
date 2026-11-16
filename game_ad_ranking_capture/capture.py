"""The whole capture: open the Duel's Rank screen, check each day, scan what has data, write the week file.

For every wanted day, in order: a day that is already final in the week file is left alone (`force` reads it again), a
day tab the game does not switch to has no data yet, anything else is scanned. A list that is still changing is
preliminary: today's, and any day not read completely after its game day ended, so it is read again on the next run.
A day becomes final when a complete scan of it *started* after its game day ended (a scan that runs across the reset
is not trusted). The file is written after every day, so a stopped or failed run keeps what it already read. Crops of
the rows the OCR was unsure about go to `review/`.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2

import config as C
import store
import weeks
from device import AdbDevice
from ocr import Ocr
from scan import Scanner
from screens import Navigator, day_tabs


@dataclass
class DayResult:
    day: str
    status: str  # "scanned", "final" (already had it), "no data yet", "empty", "kept" (a worse scan was dropped)
    rows: int = 0
    complete: bool = False
    warnings: list[str] = field(default_factory=list)
    review: int = 0

    def line(self) -> str:
        label = C.DAY_LABELS[self.day]
        if self.status != "scanned":
            return f"{label}: {self.status}"
        text = f"{label}: {self.rows} rows" + ("" if self.complete else " (list not complete)")
        extra = ([f"{len(self.warnings)} warnings"] if self.warnings else []) + (
            [f"{self.review} to review"] if self.review else []
        )
        return text + (f", {', '.join(extra)}" if extra else "")


def write_review(week: str, day: str, review: list, unreadable: list, directory: Path = C.REVIEW_DIR) -> None:
    """The cards to check (`rank-<n>.png`) and the whole frames of pages that could not be read (`page-<n>.png`)."""
    target = directory / week / day
    shutil.rmtree(target, ignore_errors=True)
    if review or unreadable:
        target.mkdir(parents=True)
    for item in review:
        cv2.imwrite(str(target / f"rank-{item.rank:04d}.png"), item.crop)
    for number, frame in enumerate(unreadable, 1):
        cv2.imwrite(str(target / f"page-{number}.png"), frame)


def run_capture(
    device: AdbDevice,
    days: tuple[str, ...] = C.DAYS,
    force: bool = False,
    progress: Callable[[str], None] = print,
    should_stop: Callable[[], bool] = lambda: False,
    directory: Path = C.DATA_DIR,
    review_directory: Path = C.REVIEW_DIR,
    primary: Ocr | None = None,
    secondary: Ocr | None = None,
) -> list[DayResult]:
    primary, secondary = primary or Ocr(), secondary or Ocr(cyrillic=True)
    moment = weeks.now_utc()
    today = weeks.game_date(moment)
    monday, week_name = weeks.week_monday(today), weeks.week_id(today)
    week = store.load(week_name, directory) or store.new_week(week_name, monday)
    progress(f"Week {week_name} (game day {today.isoformat()}).")

    navigator = Navigator(device, primary, progress)
    scanner = Scanner(device, primary, secondary, progress, should_stop)
    frame, words = navigator.open_rank()
    tabs = day_tabs(words, frame.shape[0])
    if len(tabs) < len(C.DAYS):
        raise RuntimeError(f"Only {len(tabs)} of the {len(C.DAYS)} day tabs were found on the Rank screen.")
    daily = [word for word in words if word.text.strip().lower() == "daily"]
    if daily:  # the Weekly tab has no day tabs: make sure the Daily one is showing
        device.tap(daily[0].cx, daily[0].cy)

    results: list[DayResult] = []
    for day in days:
        if should_stop():
            break
        if store.is_final(week, day) and not force:
            results.append(DayResult(day, "final"))
        elif navigator.select_day(day, tabs) is None:
            results.append(DayResult(day, "no data yet"))
        else:
            progress(f"{C.DAY_LABELS[day]}: reading the list ...")
            started = weeks.now_utc()  # a day is final only if the scan began after its game day ended
            results.append(
                store_day(week, day, monday, scanner.scan_day(), week_name, directory, started, review_directory)
            )
        progress(results[-1].line())
    navigator.go_home()
    return results


def store_day(
    week: dict, day: str, monday, scan, week_name: str, directory: Path, started, review_directory: Path
) -> DayResult:
    if not scan.rows:
        return DayResult(day, "empty")
    write_review(week_name, day, scan.review, scan.unreadable, review_directory)  # this scan's pictures, stored or not
    kept = week["days"].get(day)
    if kept and kept["complete"] and not scan.complete:
        return DayResult(day, "kept", warnings=["an incomplete scan did not replace a complete one", *scan.warnings])
    final = scan.complete and weeks.is_final(weeks.day_date(monday, day), started)
    store.put_day(week, day, monday, scan.rows, started, final, scan.complete)
    if scan.me:  # the own row as it was stored (corrected, spelled like the rest of the alliance)
        stored = next((r for r in week["days"][day]["rows"] if r["rank"] == scan.me["rank"]), scan.me)
        week["meta"] = {"my_name": stored["name"], "my_alliance": stored["alliance"], "my_tag": stored["tag"]}
    store.save(week, directory)
    return DayResult(day, "scanned", len(scan.rows), scan.complete, scan.warnings, len(scan.review))
