"""The "is everything in place" list of the command line and the window: adb, device, game, current screen."""

from __future__ import annotations

from dataclasses import dataclass

import config as C
import device as D
from ocr import Ocr
from screens import Screen, identify


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def run_checks(adb_path: str | None, serial: str, ocr: Ocr | None = None) -> list[Check]:
    adb = D.find_adb(adb_path or None)
    checks = [
        Check("ADB", adb is not None, adb or "Not found: set its path, or put BlueStacks' HD-Adb.exe on the PATH.")
    ]
    if adb is None:
        return checks
    try:
        device = D.AdbDevice(serial, adb)
        installed = device.installed()
    except (RuntimeError, OSError) as error:
        checks.append(Check("Device", False, str(error)))
        return checks
    checks.append(Check("Device", True, f"Connected to {serial}."))
    checks.append(
        Check("Game", installed, f"{C.PACKAGE} is installed." if installed else f"{C.PACKAGE} is not installed.")
    )
    if not installed:
        return checks
    front = device.foreground()
    checks.append(
        Check("Game in front", front == C.PACKAGE, "Yes." if front == C.PACKAGE else f"No, {front or 'unknown'} is.")
    )
    if front != C.PACKAGE:
        return checks
    try:
        frame = device.settled()
        screen = identify((ocr or Ocr()).read(frame), frame.shape[0])
    except (D.DeviceUnavailable, RuntimeError) as error:
        checks.append(Check("Screen", False, str(error)))
        return checks
    known = screen is not Screen.OTHER
    checks.append(
        Check(
            "Screen",
            known,
            f"The game shows {screen.value}." + ("" if known else " It will be left with the back arrow."),
        )
    )
    return checks
