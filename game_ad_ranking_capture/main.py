"""Game AD Ranking Capture: reads the Alliance Duel's daily ranking from the game (ADB, OCR) into weekly files.

    python main.py check                           adb, device, game and the screen the game shows
    python main.py capture [--days mon,tue] [--force]   scan the days that have data (all Mon-Sat by default)
    python main.py members [--since DATE]          read the alliance's member list (for the zero-point days)
    python main.py status                          what the week files and the member list hold
    python main.py view                            the rankings in the browser (stop with Ctrl+C)

`capture` opens the Rank screen itself (from the map, or from wherever the game is) and puts the game back on the map
at the end. A day that is already final in its week file is skipped (`--force` reads it again), a day that has not
started has no data yet. Do not touch the emulator while it runs. Files: `data/<year>-W<week>.json`.
"""

from __future__ import annotations

import argparse
import sys
import time
import webbrowser
from datetime import date

import capture
import checks
import config as C
import roster
import store
import viewer_server
from device import AdbDevice


def cmd_check(args: argparse.Namespace) -> None:
    results = checks.run_checks(args.adb, args.serial)
    for check in results:
        print(f"{'OK     ' if check.ok else 'PROBLEM'} {check.name}: {check.detail}")
    if not all(check.ok for check in results):
        sys.exit(1)


def cmd_capture(args: argparse.Namespace) -> None:
    days = tuple(day.strip() for day in args.days.split(",") if day.strip())
    unknown = [day for day in days if day not in C.DAYS]
    if unknown:
        sys.exit(f"Unknown day(s) {', '.join(unknown)}: use {', '.join(C.DAYS)}.")
    results = capture.run_capture(AdbDevice(args.serial, args.adb), days, args.force)
    print()
    for result in results:
        print(result.line())
        for warning in result.warnings:
            print(f"    ! {warning}")
    if any(result.review for result in results):
        print(f"Rows to check by eye: {C.REVIEW_DIR}  (fix names in {C.CORRECTIONS.name})")


def cmd_status(_: argparse.Namespace) -> None:
    weeks = store.list_weeks()
    if not weeks:
        print(f"No weeks yet in {C.DATA_DIR}.")
    for name in weeks:
        week = store.load(name)
        parts = [
            f"{C.DAY_LABELS[day]} {len(week['days'][day]['rows'])}{'' if week['days'][day]['final'] else '*'}"
            for day in C.DAYS
            if day in week["days"]
        ]
        print(f"{name}: {', '.join(parts)}")
    if weeks:
        print("(* = preliminary: read before its game day ended, it is read again)")
    snapshots = roster.load().snapshots
    for snapshot in snapshots:
        print(f"Members from {snapshot['since']}: {len(snapshot['members'])} (read {snapshot['scanned_at']})")
    if not snapshots:
        print("No member list yet: `members` reads it (members with 0 points are not in the ranking).")
    else:
        print("(a week without a member list of its own uses the latest earlier one)")


def print_members(scan, stored: bool) -> None:
    ranks = {}
    for member in scan.members:
        ranks[member["rank"]] = ranks.get(member["rank"], 0) + 1
    print(f"{len(scan.members)} members ({', '.join(f'{r} {n}' for r, n in sorted(ranks.items(), reverse=True))})")
    if scan.expanded:
        print(f"Folded groups opened: {', '.join(scan.expanded)} (they stay open in the game)")
    for warning in scan.warnings:
        print(f"    ! {warning}")
    if scan.joined or scan.left:
        print(f"Since the list before: {len(scan.joined)} joined ({', '.join(scan.joined)}),")
        print(f"                       {len(scan.left)} left ({', '.join(scan.left)})")
    print("Stored in data/members/." if stored else "NOT stored: the list does not add up to the member count shown.")


def cmd_members(args: argparse.Namespace) -> None:
    since = date.fromisoformat(args.since) if args.since else None
    scan, stored = capture.run_members(AdbDevice(args.serial, args.adb), since)
    print()
    print_members(scan, stored)
    if not stored:
        sys.exit(1)


def cmd_view(_: argparse.Namespace) -> None:
    server, url = viewer_server.start()
    print(f"Rankings at {url} (Ctrl+C stops the server).")
    webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        viewer_server.stop(server)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # names in any alphabet
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("check", "check adb, the device and the game"),
        ("capture", "scan the rankings"),
        ("members", "read the alliance's member list"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--adb", help="path to adb (default: the PATH, then BlueStacks' own)")
        command.add_argument("--serial", default=C.DEFAULT_SERIAL, help=f"ADB device (default {C.DEFAULT_SERIAL})")
        if name == "members":
            command.add_argument("--since", help="the first day (YYYY-MM-DD) this member list is valid from")
        if name == "capture":
            command.add_argument("--days", default=",".join(C.DAYS), help="days to read, e.g. mon,tue (default all)")
            command.add_argument("--force", action="store_true", help="also read days that are already final")
    commands.add_parser("status", help="what the week files hold")
    commands.add_parser("view", help="open the rankings in the browser")
    args = parser.parse_args()
    handlers = {
        "check": cmd_check,
        "capture": cmd_capture,
        "members": cmd_members,
        "status": cmd_status,
        "view": cmd_view,
    }
    try:
        handlers[args.command](args)
    except (RuntimeError, OSError) as error:  # what the user can act on: adb, the device, navigation
        sys.exit(str(error))


if __name__ == "__main__":
    main()
