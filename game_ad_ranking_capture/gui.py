"""A small window for Game AD Ranking Capture: check, scan, open the rankings in the browser.

    python gui.py          (or double-click start_gui.bat)

"Check again" tests adb, the device, the game and the screen it shows (it runs when the window opens). "Scan" opens the
Alliance Duel's Rank screen by itself and reads every chosen day that has data; days already final are skipped unless
"Read final days again" is ticked, and "Stop" ends the scan after the current page. "Open rankings in browser" shows
the weekly files in the local viewer. Do not touch the emulator while a scan runs: it taps and swipes the game.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import scrolledtext, ttk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import capture  # noqa: E402
import checks  # noqa: E402
import config as C  # noqa: E402
import store  # noqa: E402
import viewer_server  # noqa: E402
from device import AdbDevice  # noqa: E402

POLL_MS = 100  # how often the window looks for what a background task has said or finished
GOOD, BAD = "#1a7f37", "#c62828"


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.stop_flag = threading.Event()
        self.server = None  # the viewer's local server, started with the first "Open rankings in browser"
        self.url = ""
        root.title("Game AD Ranking Capture")
        root.geometry("820x700")
        root.protocol("WM_DELETE_WINDOW", self.close)

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill="both", expand=True)

        device = ttk.LabelFrame(frame, text="Device", padding=8)
        device.pack(fill="x")
        self.adb, self.serial = tk.StringVar(), tk.StringVar(value=C.DEFAULT_SERIAL)
        ttk.Label(device, text="adb (empty = found by itself)").grid(row=0, column=0, sticky="w")
        ttk.Entry(device, textvariable=self.adb, width=60).grid(row=0, column=1, padx=6, sticky="ew")
        ttk.Label(device, text="ADB address").grid(row=1, column=0, sticky="w")
        ttk.Entry(device, textvariable=self.serial, width=24).grid(row=1, column=1, padx=6, sticky="w")
        device.columnconfigure(1, weight=1)

        self.checks_box = ttk.LabelFrame(frame, text="Checks", padding=8)
        self.checks_box.pack(fill="x", pady=(8, 0))
        self.check_button = ttk.Button(frame, text="Check again", command=self.run_checks)
        self.check_button.pack(anchor="w", pady=(4, 0))

        scan = ttk.LabelFrame(frame, text="Scan", padding=8)
        scan.pack(fill="x", pady=(8, 0))
        self.days = {day: tk.BooleanVar(value=True) for day in C.DAYS}
        for column, day in enumerate(C.DAYS):
            ttk.Checkbutton(scan, text=C.DAY_LABELS[day], variable=self.days[day]).grid(
                row=0, column=column, padx=(0, 10)
            )
        self.force = tk.BooleanVar(value=False)
        ttk.Checkbutton(scan, text="Read final days again", variable=self.force).grid(
            row=1, column=0, columnspan=4, sticky="w"
        )
        ttk.Label(scan, text="Do not touch the emulator while a scan runs.").grid(
            row=2, column=0, columnspan=6, sticky="w"
        )

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(8, 0))
        self.scan_button = ttk.Button(buttons, text="Scan", command=self.start_scan)
        self.stop_button = ttk.Button(buttons, text="Stop", command=self.stop_scan, state="disabled")
        self.members_button = ttk.Button(buttons, text="Scan alliance members", command=self.start_members)
        self.browser_button = ttk.Button(buttons, text="Open rankings in browser", command=self.open_browser)
        self.folder_button = ttk.Button(buttons, text="Open data folder", command=self.open_folder)
        for button in (
            self.scan_button,
            self.stop_button,
            self.members_button,
            self.browser_button,
            self.folder_button,
        ):
            button.pack(side="left", padx=(0, 6))

        self.log_box = scrolledtext.ScrolledText(frame, height=16, font=("Consolas", 9), wrap="none")
        self.log_box.pack(fill="both", expand=True, pady=(8, 0))

        root.after(POLL_MS, self.poll)
        root.after(200, self.run_checks)

    # -- background work: a task runs in a thread and only talks to the window through the queue
    def background(self, work, done=None, scanning: bool = False) -> None:
        self.set_busy(True, scanning)

        def run() -> None:
            try:
                result = work()
            except Exception as error:  # shown in the window, not lost with the thread
                message = str(error) or type(error).__name__
                self.events.put(lambda: (self.set_busy(False), self.log(f"Error: {message}")))
                return
            self.events.put(lambda: (self.set_busy(False), done(result) if done else None))

        threading.Thread(target=run, daemon=True).start()

    def say(self, text: str) -> None:
        """Progress from a task thread."""
        self.events.put(lambda: self.log(text))

    def poll(self) -> None:
        while not self.events.empty():
            self.events.get()()
        self.root.after(POLL_MS, self.poll)

    def set_busy(self, busy: bool, scanning: bool = False) -> None:
        self.check_button.config(state="disabled" if busy else "normal")
        self.scan_button.config(state="disabled" if busy else "normal")
        self.members_button.config(state="disabled" if busy else "normal")
        self.stop_button.config(state="normal" if busy and scanning else "disabled")

    def log(self, text: str) -> None:
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")

    def device(self) -> tuple[str, str]:
        """The adb path and address as typed. Read on the window's thread: a task thread must not touch Tk."""
        return self.adb.get().strip(), self.serial.get().strip()

    # -- checks
    def run_checks(self) -> None:
        adb, serial = self.device()
        self.background(lambda: checks.run_checks(adb, serial), self.show_checks)

    def show_checks(self, results: list[checks.Check]) -> None:
        for widget in self.checks_box.winfo_children():
            widget.destroy()
        for row, check in enumerate(results):
            text, color = ("OK", GOOD) if check.ok else ("Problem", BAD)
            ttk.Label(self.checks_box, text=check.name, width=16).grid(row=row, column=0, sticky="w")
            tk.Label(self.checks_box, text=text, fg=color, width=8).grid(row=row, column=1, sticky="w")
            ttk.Label(self.checks_box, text=check.detail).grid(row=row, column=2, sticky="w")

    # -- scan
    def start_scan(self) -> None:
        days = tuple(day for day in C.DAYS if self.days[day].get())
        if not days:
            self.log("Tick at least one day.")
            return
        adb, serial = self.device()
        force = self.force.get()
        self.stop_flag.clear()

        def work():
            return capture.run_capture(AdbDevice(serial, adb), days, force, self.say, self.stop_flag.is_set)

        self.background(work, self.show_results, scanning=True)

    def start_members(self) -> None:
        adb, serial = self.device()
        self.stop_flag.clear()

        def work():
            return capture.run_members(AdbDevice(serial, adb), None, self.say, self.stop_flag.is_set)

        self.background(work, self.show_members, scanning=True)

    def show_members(self, result) -> None:
        scan, stored = result
        ranks: dict[str, int] = {}
        for member in scan.members:
            ranks[member["rank"]] = ranks.get(member["rank"], 0) + 1
        self.log("")
        self.log(
            f"{len(scan.members)} members ({', '.join(f'{r} {n}' for r, n in sorted(ranks.items(), reverse=True))})"
        )
        if scan.expanded:
            self.log(f"Folded groups opened: {', '.join(scan.expanded)} (they stay open in the game)")
        for warning in scan.warnings:
            self.log(f"    ! {warning}")
        self.log("Stored in data/members/." if stored else "NOT stored: the list does not add up to the member count.")

    def stop_scan(self) -> None:
        self.stop_flag.set()
        self.log("Stopping after the current page ...")

    def show_results(self, results: list[capture.DayResult]) -> None:
        self.log("")
        for result in results:
            self.log(result.line())
            for warning in result.warnings:
                self.log(f"    ! {warning}")
        if any(result.review for result in results):
            self.log(f"Rows to check by eye: {C.REVIEW_DIR}  (fix names in {C.CORRECTIONS.name})")
        self.log("Done." if not self.stop_flag.is_set() else "Stopped.")

    # -- the viewer
    def open_browser(self) -> None:
        if not store.list_weeks():
            self.log("There are no weekly files yet: scan first.")
        if self.server is None:
            self.server, self.url = viewer_server.start()
        webbrowser.open(self.url)

    def open_folder(self) -> None:
        C.DATA_DIR.mkdir(exist_ok=True)
        os.startfile(C.DATA_DIR)

    def close(self) -> None:
        self.stop_flag.set()
        if self.server is not None:
            viewer_server.stop(self.server)
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
