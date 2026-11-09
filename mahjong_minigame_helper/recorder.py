"""Records games: every settled board while you play, as lossless PNGs plus `game.json`.

A full game reveals every tile in the end, so a recording is self-labelling test data: walking it backwards tells
where each tile was, what it showed and what lay on top of what, for every frame (step 2 of the v2 plan). Nothing
here needs a profile, so a new minigame can be recorded before the tool knows anything about it.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

import capture as C

BIG_CHANGE = 8.0  # signature difference that is more than one tap: a shuffle, a new stage or another screen


def write_json(path: Path, data: dict, tries: int = 6) -> bool:
    """Write via a temporary file and swap it in. On Windows another program (an IDE indexing the folder, a virus
    scanner, Explorer's preview) can hold the file for a moment, so retry briefly. False if it never worked."""
    tmp = path.with_name(path.name + ".tmp")
    for attempt in range(tries):
        try:
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, path)
            return True
        except OSError:
            time.sleep(0.1 * (attempt + 1))
    return False


def write_png(path: Path, img, tries: int = 4) -> bool:
    for attempt in range(tries):
        try:
            if cv2.imwrite(str(path), img, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
                return True
        except cv2.error:
            pass
        time.sleep(0.1 * (attempt + 1))
    return False


def record(
    source,
    out_dir: Path,
    interval: float = 0.25,
    max_frames: int | None = None,
    on_save=print,
    sleep=time.sleep,
    on_event=print,
    extra: dict | None = None,
) -> list[dict]:
    """Grab frames from `source` (an object with `grab()` and `describe()`) until Ctrl+C or `max_frames`; save
    each board that has settled and differs from the last saved one. Returns the frame list of `game.json`.

    "Settled" adapts to the screen: a background that always moves a little (glow, particles) raises the idle noise,
    and the thresholds rise with it, so such a screen is still recorded once per tap.

    Nothing that goes wrong with the device ends the recording: while it does not answer, the recorder says so once
    (`on_event`), keeps trying every second, and carries on in the same folder when the device is back."""
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"started": datetime.now().isoformat(timespec="seconds"), "source": source.describe(), **(extra or {}), "frames": []}
    frames: list[dict] = meta["frames"]
    prev = saved = None
    recent: deque[float] = deque(maxlen=20)  # frame-to-frame differences: the screen's idle noise
    t0 = time.monotonic()
    try:
        outage = None  # since when the device has not answered
        while max_frames is None or len(frames) < max_frames:
            try:
                img = source.grab()
            except KeyboardInterrupt:
                raise
            except Exception as e:  # noqa: BLE001 - a stalled device, a broken frame: wait and try again
                if outage is None:
                    outage = time.monotonic()
                    on_event(f"device not responding ({e}); retrying every second, the recording continues")
                prev = None  # the board may have changed meanwhile: wait for it to settle again
                sleep(1.0)
                continue
            if outage is not None:
                on_event(f"device back after {time.monotonic() - outage:.0f} s")
                outage = None
            sig = C.signature(img)
            moved = None if prev is None else C.difference(sig, prev)
            prev = sig
            if moved is not None:
                recent.append(moved)
            noise = float(np.percentile(recent, 20)) if len(recent) >= 5 else 0.0
            stable = moved is not None and moved < max(C.STABLE, 1.5 * noise)
            if stable and (saved is None or C.difference(sig, saved) > max(C.CHANGED, 3 * noise)):
                name = f"{len(frames):03d}.png"
                if not write_png(out_dir / name, img):
                    on_save({"file": name, "t": round(time.monotonic() - t0, 2), "note": "could not be saved, skipped"})
                    saved = sig
                    sleep(interval)
                    continue
                entry = {"file": name, "t": round(time.monotonic() - t0, 2), "size": [img.shape[1], img.shape[0]]}
                if saved is not None:
                    change = C.difference(sig, saved)
                    entry["change"] = round(change, 2)
                    if change > BIG_CHANGE:
                        entry["note"] = "big change (shuffle, new stage or another screen)"
                frames.append(entry)
                saved = sig
                on_save(entry)
                if not write_json(out_dir / "game.json", meta):  # after every frame, so a crash loses nothing
                    on_save({"file": "game.json", "t": entry["t"], "note": "could not write it right now, will retry"})
            sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        write_json(out_dir / "game.json", meta)
    return frames


class _Frames:
    """A `record` source that hands on the frames someone else grabbed (the advisor); None ends the recording."""

    def __init__(self, describe: str):
        import queue

        self.queue: queue.Queue = queue.Queue(maxsize=8)
        self._describe = describe

    def grab(self):
        img = self.queue.get()
        if img is None:
            raise KeyboardInterrupt  # how `record` is told to finish
        return img

    def describe(self) -> str:
        return self._describe


class AutoRecorder:
    """Records the frames the advisor grabs anyway (no second connection to the device, the advisor is not slowed
    down): `record` runs in a background thread on them, one folder per game. A folder is only created once a frame
    arrives, so a session without a game leaves nothing behind."""

    def __init__(self, root: Path, describe: str, extra: dict | None = None, on_event=print):
        self.root, self.describe, self.extra, self.on_event = root, describe, extra or {}, on_event
        self.source: _Frames | None = None
        self.thread = None
        self.folder: Path | None = None
        self.saved = 0

    def feed(self, img) -> None:
        import queue
        import threading

        if self.source is None:
            name = datetime.now().strftime("%Y%m%d-%H%M%S")
            self.folder = self.root / name
            n = 2
            while self.folder.exists():  # two games within one second
                self.folder, n = self.root / f"{name}-{n}", n + 1
            self.source = _Frames(self.describe)
            self.thread = threading.Thread(target=self._run, args=(self.source, self.folder), daemon=True)
            self.thread.start()
            self.on_event(f"recording this game to {self.folder}")
        try:
            self.source.queue.put_nowait(img)
        except queue.Full:  # the disk is slower than the advisor right now: skip a frame rather than wait
            pass

    def _run(self, source: _Frames, folder: Path) -> None:
        def saved(entry: dict) -> None:
            self.saved += 1

        record(source, folder, interval=0, on_save=saved, sleep=lambda s: None, on_event=self.on_event, extra=self.extra)

    def new_game(self) -> None:
        """Finish the current folder; the next frame starts a new one."""
        if self.source is not None:
            self.source.queue.put(None)
            self.thread.join(timeout=10)
            self.on_event(f"recorded {self.folder.name} ({self.saved} boards)")
        self.source = self.thread = None
        self.saved = 0

    close = new_game


def same_game(before: list[tuple[float, float]], after: list[tuple[float, float]], tol: float = 6.0, share: float = 0.5) -> bool:
    """Is the board back after another screen (a dialog, a result screen) the same game? The free tiles of the last
    board before and the first one after, as positions: a dialog or a Refresh (new icons, same spots) keeps most of
    them, a new game has another layout."""
    if not before or not after:
        return not before and not after
    kept = sum(any(abs(x - a) <= tol and abs(y - b) <= tol for a, b in after) for x, y in before)
    return kept >= share * max(len(before), len(after))
