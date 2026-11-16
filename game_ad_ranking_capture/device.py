"""The Android device through ADB: frames, taps and swipes, at the device's own resolution.

Frames are cropped to the non-black content (a portrait game in a landscape emulator), and `tap` / `swipe` take
coordinates in the cropped frame and add the offset themselves. The game lags behind a tap, so `settled` waits until
two frames in a row show the same picture. A stalled connection is re-opened and retried; `DeviceUnavailable` means it
stayed silent.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import config as C

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # no console window flashing up for every adb call
GRAB_TIMEOUT = 8.0  # s for one screencap (normally 0.3 s)
GRAB_TRIES = 3  # attempts per frame, reconnecting in between; the second to last restarts the ADB server
STABLE = 0.4  # mean grey difference below which two frames count as the same picture
ANIMATED = 3.0  # ... a screen that never gets below STABLE (the world map) is just used as it is


class DeviceUnavailable(RuntimeError):
    """The device did not deliver a frame even after reconnecting."""


def find_adb(explicit: str | None = None) -> str | None:
    for candidate in (explicit, shutil.which("adb"), *C.ADB_CANDIDATES):
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def parse_screencap(data: bytes) -> np.ndarray:
    """BGR image from `adb exec-out screencap` raw output (12- or 16-byte header, then RGBA or BGRA pixels)."""
    width, height, fmt = struct.unpack_from("<III", data, 0)
    pixels = width * height * 4
    header = len(data) - pixels
    if width == 0 or height == 0 or header not in (12, 16):
        raise ValueError(f"unexpected screencap data ({len(data)} bytes for {width}x{height})")
    img = np.frombuffer(data, np.uint8, count=pixels, offset=header).reshape(height, width, 4)
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR if fmt == 5 else cv2.COLOR_RGBA2BGR)


def content_box(img_bgr: np.ndarray, dark: int = 12) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) of everything that is not a black bar around the picture."""
    lit = img_bgr.max(axis=2) > dark
    cols, rows = np.where(lit.any(axis=0))[0], np.where(lit.any(axis=1))[0]
    if len(cols) == 0:
        return 0, 0, img_bgr.shape[1], img_bgr.shape[0]
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def difference(a: np.ndarray, b: np.ndarray) -> float:
    """Mean grey difference of two frames, on a small thumbnail."""

    def thumb(img: np.ndarray) -> np.ndarray:
        return cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (96, 170), interpolation=cv2.INTER_AREA).astype(
            np.int16
        )

    return float(np.abs(thumb(a) - thumb(b)).mean())


class AdbDevice:
    """Frames and taps through ADB (BlueStacks: enable "Android Debug Bridge" in Settings > Advanced)."""

    def __init__(self, serial: str = C.DEFAULT_SERIAL, adb: str | None = None):
        self.adb = find_adb(adb)
        if self.adb is None:
            raise RuntimeError("adb not found: pass its path, or put BlueStacks' HD-Adb.exe on the PATH.")
        self.serial = serial
        if ":" in serial:  # a network device (emulators): connect first
            out = self._run("connect", serial, device=False).decode(errors="replace")
            if "connected" not in out:
                raise RuntimeError(f"adb could not connect to {serial}: {out.strip()} (is ADB enabled in BlueStacks?)")
        self.box: tuple[int, int, int, int] | None = None

    def _run(self, *args: str, device: bool = True, timeout: float = 15) -> bytes:
        cmd = [self.adb, *(["-s", self.serial] if device else []), *args]
        done = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        if done.returncode != 0:
            raise RuntimeError(f"{' '.join(args)} failed: {done.stderr.decode(errors='replace').strip()}")
        return done.stdout

    def _try(self, *args: str, device: bool = True, timeout: float = 10) -> None:
        try:
            self._run(*args, device=device, timeout=timeout)
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            pass

    def reconnect(self, restart_server: bool = False) -> None:
        if restart_server:
            self._try("kill-server", device=False)
            self._try("start-server", device=False, timeout=20)
        if ":" in self.serial:
            self._try("disconnect", self.serial, device=False)
            self._try("connect", self.serial, device=False)
        else:
            self._try("reconnect")

    def grab(self) -> np.ndarray:
        """One frame. A stall or an error reconnects and retries; DeviceUnavailable if the device stays silent."""
        last: Exception | None = None
        for attempt in range(GRAB_TRIES):
            try:
                img = parse_screencap(self._run("exec-out", "screencap", timeout=GRAB_TIMEOUT))
                break
            except (subprocess.TimeoutExpired, RuntimeError, OSError, ValueError, struct.error) as error:
                last = error
                self.reconnect(restart_server=attempt == GRAB_TRIES - 2)
        else:
            raise DeviceUnavailable(f"no frame from {self.serial}: {last}")
        if self.box is None:  # the picture's position stays put: find the black bars once
            self.box = content_box(img)
        x0, y0, x1, y1 = self.box
        return np.ascontiguousarray(img[y0:y1, x0:x1])

    def settled(self) -> np.ndarray:
        """A frame once the picture stopped moving (or the last one of a screen that keeps animating)."""
        previous = self.grab()
        for _ in range(C.SETTLE_TRIES):
            time.sleep(C.SETTLE_PAUSE)
            frame = self.grab()
            if difference(previous, frame) < STABLE:
                return frame
            previous = frame
        return previous

    def tap(self, x: float, y: float) -> None:
        """Tap at (x, y) in the coordinates of the frames `grab` returns, then give the game time to answer."""
        ox, oy = (self.box or (0, 0, 0, 0))[:2]
        self._input("tap", round(x + ox), round(y + oy))
        time.sleep(C.TAP_PAUSE)

    def swipe(self, x0: float, y0: float, x1: float, y1: float, ms: int = C.SWIPE_MS) -> None:
        ox, oy = (self.box or (0, 0, 0, 0))[:2]
        self._input("swipe", round(x0 + ox), round(y0 + oy), round(x1 + ox), round(y1 + oy), ms, lasts=ms / 1000)

    def _input(self, *args, lasts: float = 0.0) -> None:
        try:
            self._run("shell", "input", *map(str, args), timeout=GRAB_TIMEOUT + lasts)
        except (subprocess.TimeoutExpired, RuntimeError, OSError) as error:
            self.reconnect()
            raise DeviceUnavailable(f"{args[0]} was not taken: {error}") from error

    def installed(self, package: str = C.PACKAGE) -> bool:
        return package in self._run("shell", "pm", "list", "packages", package).decode(errors="replace")

    def foreground(self) -> str:
        """The package whose window is in front (`mCurrentFocus`), '' if unknown."""
        out = self._run("shell", "dumpsys", "window").decode(errors="replace")
        for line in out.splitlines():
            if "mCurrentFocus" in line and "/" in line:
                return line.split()[-1].strip("}").split("/")[0]
        return ""
