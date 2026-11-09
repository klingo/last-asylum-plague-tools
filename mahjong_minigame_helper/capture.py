"""Frames and taps come from the Android device through ADB: pixel-exact, at the device's own resolution.

ADB frames are cropped to the non-black content, so a portrait game in a landscape emulator works too; `tap` takes
coordinates in the returned image and adds the crop offset itself. `signature` / `difference` are the shared "has
the board moved" measure of `run` and `record`.

The only use of the screen: `locate_game` finds where BlueStacks shows the game on the monitor (by matching an ADB
frame against the emulator window), so the overlay can draw its boxes on top of it.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

DEFAULT_SERIAL = "127.0.0.1:5555"  # BlueStacks' usual ADB address (Settings > Advanced > Android Debug Bridge)
ADB_CANDIDATES = (
    r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
    r"C:\Program Files\BlueStacks\HD-Adb.exe",
    r"C:\Program Files (x86)\BlueStacks\HD-Adb.exe",
)
STABLE = 0.3  # signature difference below which two frames show the same, settled board
CHANGED = 0.6  # ... above which the board changed (a tap, a match, a new stage)
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # no console window flashing up for every adb call
GRAB_TIMEOUT = 6.0  # s for one screencap (normally 0.3 s); longer means the connection stalled
GRAB_TRIES = 3  # attempts per grab, reconnecting in between; the last one restarts the ADB server first


class DeviceUnavailable(RuntimeError):
    """The device did not deliver a frame even after reconnecting. Callers wait and try again later."""


def signature(img_bgr: np.ndarray) -> np.ndarray:
    """Small grey thumbnail used to tell whether the board moved."""
    grey = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    return cv2.resize(grey, (95, 170), interpolation=cv2.INTER_AREA).astype(np.int16)


def difference(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def find_adb(explicit: str | None = None) -> str | None:
    for candidate in (explicit, shutil.which("adb"), *ADB_CANDIDATES):
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


class AdbCapture:
    """Frames and taps through ADB (BlueStacks: enable "Android Debug Bridge" in Settings > Advanced)."""

    def __init__(self, serial: str = DEFAULT_SERIAL, adb: str | None = None):
        self.adb = find_adb(adb)
        if self.adb is None:
            raise RuntimeError("adb not found: install Android platform-tools or pass --adb-exe (BlueStacks: HD-Adb.exe)")
        self.serial = serial
        if ":" in serial:  # network device (emulators): connect first
            out = self._run("connect", serial, device=False).decode(errors="replace")
            if "connected" not in out:
                raise RuntimeError(f"adb could not connect to {serial}: {out.strip()} (is ADB enabled in BlueStacks?)")
        self.box: tuple[int, int, int, int] | None = None

    def _run(self, *args: str, device: bool = True, timeout: float = 15) -> bytes:
        cmd = [self.adb, *(["-s", self.serial] if device else []), *args]
        res = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        if res.returncode != 0:
            raise RuntimeError(f"{' '.join(args)} failed: {res.stderr.decode(errors='replace').strip()}")
        return res.stdout

    def _try(self, *args: str, device: bool = True, timeout: float = 10) -> None:
        """Run an adb command whose failure does not matter (part of reconnecting)."""
        try:
            self._run(*args, device=device, timeout=timeout)
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            pass

    def reconnect(self, restart_server: bool = False) -> None:
        """After a stall: drop and re-open the connection (and, if that did not help, restart adb itself)."""
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
            except (subprocess.TimeoutExpired, RuntimeError, OSError, ValueError, struct.error) as e:
                last = e
                self.reconnect(restart_server=attempt == GRAB_TRIES - 2)
        else:
            raise DeviceUnavailable(f"no frame from {self.serial}: {last}")
        if self.box is None:  # the picture's position stays put; find the black bars once
            self.box = content_box(img)
        x0, y0, x1, y1 = self.box
        return np.ascontiguousarray(img[y0:y1, x0:x1])

    def tap(self, x: float, y: float) -> bool:
        """Tap at (x, y) in the coordinates of the images `grab` returns. False if the device did not take it."""
        ox, oy = (self.box or (0, 0, 0, 0))[:2]
        try:
            self._run("shell", "input", "tap", str(round(x + ox)), str(round(y + oy)), timeout=GRAB_TIMEOUT)
            return True
        except (subprocess.TimeoutExpired, RuntimeError, OSError):
            self.reconnect()
            return False

    def describe(self) -> str:
        return f"adb {self.serial}"

    def close(self) -> None:
        pass


def set_dpi_aware() -> None:
    """Make window positions, the overlay and screen grabs agree on physical pixels (Windows display scaling)."""
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def emulator_windows(title: str = "BlueStacks") -> list[tuple[int, tuple[int, int, int, int]]]:
    """(window handle, client area on screen) of every visible top-level window whose title contains `title`."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[tuple[int, tuple[int, int, int, int]]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if title.lower() in buf.value.lower():
                rect = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                origin = wintypes.POINT(0, 0)
                user32.ClientToScreen(hwnd, ctypes.byref(origin))
                if rect.right > 100 and rect.bottom > 100:
                    found.append((int(hwnd), (origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom)))
        return True

    user32.EnumWindows(visit, 0)
    return found


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """The window's outer rectangle (cheap: used to notice that it moved or was resized)."""
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def find_in(screen_bgr: np.ndarray, frame_bgr: np.ndarray) -> tuple[float, tuple[int, int, int, int]]:
    """Where `frame_bgr`, scaled down, appears inside `screen_bgr`: (match score 0..1, (x0, y0, x1, y1))."""
    grey = lambda im: cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)  # noqa: E731
    sh, sw = screen_bgr.shape[:2]
    fh, fw = frame_bgr.shape[:2]
    d = min(1.0, 320 / sh)  # coarse search on a small copy
    small = cv2.resize(grey(screen_bgr), None, fx=d, fy=d, interpolation=cv2.INTER_AREA)
    best = (-1.0, 1.0, 0, 0)
    for s in np.linspace(0.45, 1.0, 56):  # the game takes 45-100 % of the window height
        h, w = round(fh * s * sh / fh * d), round(fw * s * sh / fh * d)
        if h < 20 or w > small.shape[1] or h > small.shape[0]:
            continue
        tmpl = cv2.resize(grey(frame_bgr), (w, h), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(small, tmpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(res)
        if score > best[0]:
            best = (score, s, x, y)
    score, s, x, y = best
    if score < 0:
        return 0.0, (0, 0, 0, 0)
    h, w = round(sh * s), round(fw * sh * s / fh)
    x0, y0 = round(x / d), round(y / d)
    # refine at full resolution around the coarse hit
    tmpl = cv2.resize(grey(frame_bgr), (w, h), interpolation=cv2.INTER_AREA)
    m = int(4 / d) + 2
    ax0, ay0 = max(0, x0 - m), max(0, y0 - m)
    area = grey(screen_bgr)[ay0 : min(sh, y0 + h + m), ax0 : min(sw, x0 + w + m)]
    if area.shape[0] >= h and area.shape[1] >= w:
        res = cv2.matchTemplate(area, tmpl, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(res)
        x0, y0 = ax0 + x, ay0 + y
    return float(score), (x0, y0, x0 + w, y0 + h)


def locate_game(frame_bgr: np.ndarray, title: str = "BlueStacks") -> tuple[int, tuple[int, int, int, int]] | None:
    """(window handle, screen rectangle) where the emulator shows `frame_bgr`, or None if no visible window does.
    The emulator window must not be covered by other windows while this runs."""
    import mss

    best = None
    with (getattr(mss, "MSS", None) or mss.mss)() as sct:
        for hwnd, (x0, y0, x1, y1) in emulator_windows(title):
            shot = np.array(sct.grab({"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0}))[:, :, :3]
            score, (a, b, c, d) = find_in(np.ascontiguousarray(shot), frame_bgr)
            if score > 0.6 and (best is None or score > best[0]):
                best = (score, hwnd, (x0 + a, y0 + b, x0 + c, y0 + d))
    return None if best is None else (best[1], best[2])


def check_adb(serial: str = DEFAULT_SERIAL, adb: str | None = None, board=None) -> tuple[bool, str]:
    """Connect, grab one frame and describe it: (ok, message). `board(img)` may say what is on screen."""
    import time

    try:
        cap = AdbCapture(serial, adb)
        started = time.monotonic()
        img = cap.grab()
        took = time.monotonic() - started
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
        hints = (
            "Is BlueStacks running? Settings > Advanced > Android Debug Bridge must be on, and the address there must "
            f"match {serial!r}."
        )
        return False, f"ADB not working: {e}\n{hints}"
    msg = f"ADB OK: {serial}, frame {img.shape[1]}x{img.shape[0]} in {took:.2f}s ({cap.adb})"
    if board is not None:
        msg += "\n" + board(img)
    return True, msg

