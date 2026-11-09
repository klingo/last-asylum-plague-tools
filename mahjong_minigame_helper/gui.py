"""A small launcher window for the Mahjong Minigame Helper, so nothing needs to be typed.

    python gui.py          (or double-click start_gui.bat)

Every button runs the matching `main.py` command in the background with the options chosen in the window, and shows
its output below. Stop ends the running command the way Ctrl+C does (recordings and the icon library are saved): it
closes the command's input, which `main.py` watches when started from here.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import capture as C  # noqa: E402
import game_profile as G  # noqa: E402

MAIN = HERE / "main.py"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
WRAP = 600  # px: line width of the explanations

HOW_IT_WORKS = (
    "The advisor takes a picture of BlueStacks after every move (through ADB), recognises every tile - also the "
    "covered ones and the piles - and works out the best order to tap. It marks it on top of the game: green 1 = tap "
    "this, cyan = tiles that tap uncovers, yellow 2 / 3 = alternatives. You tap, or let it tap with Auto-click.\n"
    "First time: switch on BlueStacks > Settings > Advanced > Android Debug Bridge, then click Check ADB."
)

TIPS = {
    "profile": "Which minigame you play. A profile holds how its tiles and icons look; it works for every level and "
               "layout of that minigame. Recordings, training and the accuracy belong to the selected profile.",
    "new": "Only for a different minigame (other tiles, other icons) - not for a new level. Creates an empty profile; "
           "select it and record its games, then Train.",
    "serial": "The ADB address shown in BlueStacks > Settings > Advanced (usually 127.0.0.1:5555).",
    "check": "Connects to BlueStacks, takes one picture and tells whether the game board is on screen. "
             "Use it first when something does not respond.",
    "advisor": "Starts the advisor: open the minigame and keep the BlueStacks window visible (not minimised). The "
               "badge at the top says WAITING (board moving), ANALYZING... or READY.",
    "letters": "Writes the recognised icon on every tile (? = not recognised). Handy to spot misreadings.",
    "auto": "The advisor taps for you, but only when it is sure (no risk, icon read); otherwise it waits for you. "
            "F8 pauses / resumes.",
    "step": "With Auto-click: it waits until you press F9 before each tap.",
    "rec_run": "Saves every game you play with the advisor as a recording (one folder per game, about 110 MB each), "
               "so Train and the checks get more data without extra steps. If you tap by hand, wait for READY: "
               "boards you pass while it is still ANALYZING are not recorded.",
    "record": "Records without the advisor (when you play without it). Start it before a game and press Stop after "
              "the result screen. The advisor records by itself (Record games).",
    "train": "Learns from all recordings of this profile how every icon looks on your device, and the board's grid "
             "(the same in every stage) (about a minute). The advisor uses it from its next start.",
    "measure": "Runs the recognition on every recorded board and compares it with what each game revealed later. "
               "Shows the accuracy below (about a minute).",
    "advice": "Replays every recorded game and checks for each board whether the advisor's tap was as good as the tap "
              "with perfect recognition. Tells how much better recognition would still help (several minutes).",
    "list": "Lists the recordings of this profile and how each game ended (won, lost, cut short).",
    "folder": "Opens the folder with this profile's recordings.",
    "analyse": "Picks a screenshot of the game, marks the best tap on it and opens the result.",
}

IMPROVE = (
    "Routine: play with the advisor (it records each game), and every few games click Train, then Measure accuracy. "
    "Check advice tells whether reading errors still cost good taps.\n"
    "New level or layout: nothing to set up - the same profile works. Record a few games of it; Train if new "
    "icons appear (? on tiles); if the accuracy drops, tell Claude. Won games help most: they reveal every tile."
)


def build_command(action: str, profile: str, serial: str = "", labels: bool = False, auto_click: bool = False,
                  step: bool = False, image: str | None = None, out: str | None = None, record: bool = True) -> list[str]:
    """The `main.py` command line for a button (kept separate so it can be tested without a window)."""
    cmd = [sys.executable, "-u", str(MAIN), "--profile", profile, action]
    device = ["--serial", serial.strip() or C.DEFAULT_SERIAL]
    if action == "run":
        cmd += device + (["--labels"] if labels else []) + (["--auto-click"] if auto_click else [])
        cmd += ["--step"] if auto_click and step else []
        cmd += [] if record else ["--no-record"]
    elif action == "record":
        cmd += device
    elif action == "analyze":
        cmd += ["--image", str(image), "--out", str(out), "--labels"]
    return cmd


def describe_screen(img, profile: str) -> str:
    """Is the minigame board on screen? (Uses the chosen profile's colours and tile size.)"""
    import vision as V

    G.activate(G.load(profile))
    frame = V.read_frame(img)
    if frame is None or not any(t.free for t in frame.tiles):
        return "No game board on screen right now (fine if you are not in the minigame)."
    free = sum(t.free for t in frame.tiles)
    return f"Game board visible: {free} free tiles, {len(frame.tray)} in the tray."


def missing_numba() -> bool:
    """numba compiles the advisor's search to the end of the game; the commands run with this same Python."""
    import importlib.util

    return importlib.util.find_spec("numba") is None


def note(parent: tk.Widget, text: str, row: int) -> None:
    """A grey guiding line under a group of buttons."""
    ttk.Label(parent, text=text, foreground="#555", wraplength=WRAP, justify="left").grid(
        row=row, column=0, columnspan=5, sticky="w", padx=8, pady=(0, 6)
    )


class Tip:
    """The explanation of a button, shown while the mouse rests on it."""

    def __init__(self, widget: tk.Widget, text: str):
        self.widget, self.text, self.window = widget, text, None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _=None) -> None:
        if self.window:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.attributes("-topmost", True)  # above the launcher, even when that is kept on top
        x, y = self.widget.winfo_rootx() + 12, self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window.wm_geometry(f"+{x}+{y}")
        tk.Label(self.window, text=self.text, wraplength=380, justify="left", background="#ffffe8", relief="solid",
                 borderwidth=1, padx=6, pady=4).pack()

    def hide(self, _=None) -> None:
        if self.window:
            self.window.destroy()
            self.window = None


def tip(widget: tk.Widget, key: str) -> tk.Widget:
    Tip(widget, TIPS[key])
    return widget


class Launcher:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.after_finish = None  # called once the running command has ended (analyse: open the result)
        self.lines: queue.Queue = queue.Queue()  # output lines, None = command ended, ("data", text) = verdict
        self.action = ""  # the running command (for its progress in the status bar)
        root.title("Last Asylum: Plague - Mahjong Minigame Helper")
        root.minsize(640, 640)
        pad = {"padx": 8, "pady": 4}

        how = ttk.LabelFrame(root, text="How it works")
        how.pack(fill="x", **pad)
        ttk.Label(how, text=HOW_IT_WORKS, wraplength=WRAP, justify="left").pack(anchor="w", padx=8, pady=4)

        top = ttk.Frame(root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Game profile").grid(row=0, column=0, sticky="w")
        profiles = G.available() or [G.DEFAULT_NAME]
        self.profile = tk.StringVar(value=G.DEFAULT_NAME if G.DEFAULT_NAME in profiles else profiles[0])
        prof = ttk.Frame(top)
        prof.grid(row=0, column=1, sticky="w")
        self.profile_box = tip(ttk.Combobox(prof, textvariable=self.profile, values=profiles, state="readonly", width=22), "profile")
        self.profile_box.pack(side="left")
        self.profile_box.bind("<<ComboboxSelected>>", lambda e: (self.refresh_data(), self.show_accuracy()), add="+")
        tip(ttk.Button(prof, text="New minigame...", command=self.new_profile), "new").pack(side="left", padx=6)
        ttk.Label(top, text="Device (ADB address)").grid(row=1, column=0, sticky="w", padx=(0, 8))
        dev = ttk.Frame(top)
        dev.grid(row=1, column=1, sticky="w")
        self.serial = tk.StringVar(value=C.DEFAULT_SERIAL)
        tip(ttk.Entry(dev, textvariable=self.serial, width=18), "serial").pack(side="left")
        tip(ttk.Button(dev, text="Check ADB", command=self.check_adb), "check").pack(side="left", padx=6)
        note(top, "One profile per minigame - it covers all its levels and layouts. Hover over any button for details.", row=2)
        if missing_numba():  # the advisor needs it: say so where it cannot be missed
            ttk.Label(top, text=f"numba is missing - the advisor cannot start. Install it with:\n"
                                f"{sys.executable} -m pip install numba",
                      foreground="#b00020", wraplength=WRAP, justify="left").grid(row=3, column=0, columnspan=3, sticky="w")

        play = ttk.LabelFrame(root, text="Play")
        play.pack(fill="x", **pad)
        self.labels = tk.BooleanVar(value=True)
        self.auto_click = tk.BooleanVar(value=False)
        self.step = tk.BooleanVar(value=True)
        self.record = tk.BooleanVar(value=True)
        tip(ttk.Button(play, text="Start advisor", command=self.start_run), "advisor").grid(row=0, column=0, **pad)
        tip(ttk.Checkbutton(play, text="Kind letters", variable=self.labels), "letters").grid(row=0, column=1, sticky="w")
        tip(ttk.Checkbutton(play, text="Auto-click", variable=self.auto_click), "auto").grid(row=0, column=2, sticky="w")
        tip(ttk.Checkbutton(play, text="Ask before each click (F9)", variable=self.step), "step").grid(row=0, column=3, sticky="w")
        tip(ttk.Checkbutton(play, text="Record games", variable=self.record), "rec_run").grid(row=0, column=4, sticky="w")
        note(play, "Start the advisor, open the minigame and play. F8 pauses auto-click, F9 allows one tap. "
                   "Each game is recorded for training unless Record games is off.", row=1)

        data = ttk.LabelFrame(root, text="Improve recognition")
        data.pack(fill="x", **pad)
        tip(ttk.Button(data, text="Start recording", command=lambda: self.start("record")), "record").grid(row=0, column=0, sticky="w", **pad)
        tip(ttk.Button(data, text="Train", command=lambda: self.start("train")), "train").grid(row=0, column=1, sticky="w", **pad)
        tip(ttk.Button(data, text="Measure accuracy", command=lambda: self.start("evaluate")), "measure").grid(row=0, column=2, sticky="w", **pad)
        tip(ttk.Button(data, text="Check advice", command=lambda: self.start("advice")), "advice").grid(row=0, column=3, sticky="w", **pad)
        tip(ttk.Button(data, text="Check recordings", command=lambda: self.refresh_data(verbose=True)), "list").grid(row=1, column=0, sticky="w", **pad)
        tip(ttk.Button(data, text="Open recordings folder", command=self.open_recordings), "folder").grid(row=1, column=1, sticky="w", **pad)
        tip(ttk.Button(data, text="Analyse a screenshot...", command=self.analyze), "analyse").grid(row=1, column=2, sticky="w", **pad)
        note(data, IMPROVE, row=2)
        self.data_status = tk.StringVar(value="Checking the recordings...")
        ttk.Label(data, textvariable=self.data_status, wraplength=WRAP, justify="left", font=("Segoe UI", 9, "bold")).grid(
            row=3, column=0, columnspan=5, sticky="w", padx=8)
        self.accuracy = tk.StringVar(value="")
        ttk.Label(data, textvariable=self.accuracy, wraplength=WRAP, justify="left").grid(
            row=4, column=0, columnspan=5, sticky="w", padx=8, pady=(0, 6))
        bar = ttk.Frame(root)
        bar.pack(fill="x", **pad)
        self.status = tk.StringVar(value="Idle")
        ttk.Label(bar, textvariable=self.status).pack(side="left")
        self.stop_button = ttk.Button(bar, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="right")

        self.log = tk.Text(root, height=10, wrap="word", state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, **pad)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.pump)
        root.after(300, self.refresh_data)
        root.after(400, self.show_accuracy)

    # --- actions -------------------------------------------------------------------------------------------------
    def options(self) -> dict:
        return {"profile": self.profile.get(), "serial": self.serial.get()}

    def check_adb(self) -> None:
        """Runs in the background so the window stays responsive while adb connects."""
        serial, profile = self.serial.get().strip() or C.DEFAULT_SERIAL, self.profile.get()
        self.write(f"> checking ADB {serial}...\n")

        def work() -> None:
            ok, msg = C.check_adb(serial, board=lambda img: describe_screen(img, profile))
            self.lines.put(("OK  " if ok else "!!  ") + msg.replace("\n", "\n    ") + "\n")

        threading.Thread(target=work, daemon=True).start()

    def show_accuracy(self) -> None:
        """The confidence rating of the last "Measure accuracy" and the last "Check advice" for the selected profile."""
        import json

        def last(name: str) -> dict | None:
            try:
                return json.loads((G.recordings_dir(self.profile.get()) / name).read_text(encoding="utf-8")).get("summary")
            except (OSError, ValueError):
                return None

        summary = last("_evaluation.json")
        if not summary:
            text = "Accuracy: not measured yet - click Measure accuracy."
        else:
            lines = "\n".join("   " + line for line in summary["lines"])
            text = (f"Accuracy: {summary['confidence']} / 100 (measured {summary['measured'].replace('T', ' ')}, "
                    f"{summary['games']} recordings)\n{lines}")
        advice = last("_advice.json")
        if advice:
            lines = "\n".join("   " + line for line in advice["lines"])
            text += (f"\nAdvice quality: {advice['quality']} / 100 (checked {advice['measured'].replace('T', ' ')}, "
                     f"{advice['games']} recordings)\n{lines}")
        self.accuracy.set(text)

    def refresh_data(self, verbose: bool = False) -> None:
        """Count the complete games in the background and show the verdict above the explanation."""
        profile = self.profile.get()

        def work() -> None:
            import dataset

            p = G.load(profile)
            G.activate(p)
            verdict, details = dataset.report(G.recordings_dir(profile), p.tray_slots, p.match)
            if verbose:
                self.lines.put("> recordings\n" + details + "\n")
            self.lines.put(("data", verdict))

        threading.Thread(target=work, daemon=True).start()

    def new_profile(self) -> None:
        from tkinter import simpledialog

        name = simpledialog.askstring("New minigame", "Short name for the new minigame (letters, digits, - and _), "
                                      "e.g. christmas_tiles:", parent=self.root)
        if not name:
            return
        try:
            G.create(name, template=self.profile.get())
        except ValueError as e:
            self.write(f"!! {e}\n")
            return
        self.profile_box.configure(values=G.available())
        self.profile.set(name)
        self.write(f"> new profile {name}: select it before recording games of that minigame\n")
        self.refresh_data()

    def start_run(self) -> None:
        status = G.load(self.profile.get()).notes.get("status", "")
        if status.startswith("untrained"):
            self.write("! this profile is not trained yet: the advisor cannot read its tiles well. Record games with it "
                       "and ask Claude to train it.\n")
        self.start("run", labels=self.labels.get(), auto_click=self.auto_click.get(), step=self.step.get(), record=self.record.get())

    def start(self, action: str, **extra) -> None:
        if self.proc is not None and self.proc.poll() is not None:  # it ended, but the window missed it
            self.finished()
        if self.proc is not None:
            self.write(f"! {self.status.get()} - press Stop first\n")
            return
        cmd = build_command(action, **self.options(), **extra)
        self.action = action
        self.write(f"> {action}\n")
        env = {**os.environ, "HELPER_STOP_ON_EOF": "1", "PYTHONIOENCODING": "utf-8"}
        self.proc = subprocess.Popen(cmd, cwd=HERE, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, creationflags=NO_WINDOW, bufsize=1, encoding="utf-8", errors="replace", env=env)
        threading.Thread(target=self.read, args=(self.proc,), daemon=True).start()
        self.status.set(f"Running: {action}")
        if action in ("record", "run"):
            self.after_finish = lambda: self.refresh_data(verbose=True)
        elif action in ("evaluate", "train", "advice"):
            self.after_finish = self.show_accuracy
        self.stop_button.configure(state="normal")

    def analyze(self) -> None:
        image = filedialog.askopenfilename(title="Screenshot of the game", filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All", "*.*")])
        if image:
            out = Path(image).with_name(Path(image).stem + "_analysed.png")
            self.start("analyze", image=image, out=str(out))
            self.after_finish = lambda: os.startfile(out) if out.exists() else None

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is not None:  # it ended already
            self.finished()
            return
        self.write("> stopping...\n")
        try:
            self.proc.stdin.close()  # main.py takes that as Ctrl+C: it saves, then ends
        except OSError:
            self.proc.terminate()
        self.root.after(8000, self.kill_if_running, self.proc)

    def kill_if_running(self, proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.kill()

    def open_recordings(self) -> None:
        folder = G.recordings_dir(self.profile.get())
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def close(self) -> None:
        if self.proc is not None:
            self.stop()
            self.root.after(800, self.root.destroy)
        else:
            self.root.destroy()

    # --- output --------------------------------------------------------------------------------------------------
    def read(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            self.lines.put(line)
        proc.wait()
        self.lines.put(f"> finished (exit {proc.returncode})\n")
        self.lines.put(None)  # end marker

    def pump(self) -> None:
        """Move the command's output into the window. It must keep running whatever a line holds: if it stopped, the
        window would never learn that a command ended (and refuse every button with "press Stop first")."""
        try:
            while True:
                line = self.lines.get_nowait()
                if line is None:  # the command ended
                    self.finished()
                elif isinstance(line, tuple):  # ("data", verdict) from refresh_data
                    self.data_status.set(line[1])
                elif line.startswith("progress "):  # "progress <phase>: N %" goes to the status bar, not the log
                    self.status.set(f"Running: {self.action} - {line[len('progress '):].strip()}")
                else:
                    self.write(line)
        except queue.Empty:
            pass
        except Exception as e:  # noqa: BLE001 - show it, and keep pumping
            self.write(f"!! {e}\n")
        finally:
            self.root.after(100, self.pump)

    def finished(self) -> None:
        self.proc = None
        self.status.set("Idle")
        self.stop_button.configure(state="disabled")
        if self.after_finish:
            after, self.after_finish = self.after_finish, None
            after()

    def write(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")


def main() -> None:
    root = tk.Tk()
    Launcher(root)
    root.mainloop()


if __name__ == "__main__":
    main()
