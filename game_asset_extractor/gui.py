"""A small window for the Game Asset Extractor, so nothing needs to be typed.

    python gui.py          (or double-click start_gui.bat)

Every button runs the matching `main.py` command in the background and shows its output below. "Scan" lists what is
new or changed in the game since the last download (per folder), "Download & extract" fetches exactly that and makes
the PNGs, "Mark all as seen" starts the NEW / CHANGED badges of pictures and texts over. The Pictures group: "Open gallery"
shows the game's pictures in the browser, "Edit mapping" opens the editor that says which game picture each webapp image
is made from (mapping_gui.py), "Preview sync" / "Sync to webapp" make the webapp's files from those pictures,
and the Import row adds a new picture to the webapp's assets. The Texts group opens the browser over every extracted game text,
the editor that says which game text each of the webapp's texts is (text_mapping_gui.py), and previews / writes the game's
wording and translations into the webapp's data files.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import config as C  # noqa: E402
import gallery as G  # noqa: E402
import mapping as Mp  # noqa: E402
import mapping_gui  # noqa: E402
import scan as Sc  # noqa: E402
import state as S  # noqa: E402
import text_mapping as TM  # noqa: E402
import text_mapping_gui  # noqa: E402
import texts as T  # noqa: E402

MAIN = HERE / "main.py"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
WRAP = 640  # px: line width of the explanations
BUTTON_WIDTH = 18  # characters: the buttons of the Pictures and Texts groups, so their columns line up

HOW_IT_WORKS = (
    "Reads the game's pictures from BlueStacks through ADB (no screenshots): Scan compares the game's file list with "
    "what was downloaded before and shows what is new or changed, Download & extract fetches that and cuts the "
    "pictures out, the gallery lets you search them and shows which ones the webapp already has.\n"
    "The game's texts come along: the text browser lists them in every language, and the text mapping brings the game's "
    "wording and translations into the webapp's data files.\n"
    "First time: switch on BlueStacks > Settings > Advanced > Android Debug Bridge, then click Check ADB."
)

TIPS = {
    "adb": "Path of adb / HD-Adb.exe. Empty = found by itself (BlueStacks' own HD-Adb.exe or adb on the PATH).",
    "serial": "The ADB address shown in BlueStacks > Settings > Advanced (usually 127.0.0.1:5555).",
    "check": "Connects to BlueStacks and shows the game's version. Use it first when something does not respond.",
    "scan": "Reads the game's file list and compares it with what you downloaded: new, changed and removed pictures, "
            "per folder. Downloads nothing.",
    "pull": "Downloads exactly what the last scan found, cuts the pictures out (out/<kind>/<folder>/<name>.png; game texts, tables and scripts are saved as files in out/data, "
            "what is new or changed in them is recorded for the text browser), compares the pictures with the webapp's and rebuilds the gallery. Scans again first.",
    "required": "Always scanned, downloaded and extracted. Pictures are the atlases, banners and backgrounds; the game's texts, "
                "tables and scripts hold the texts of every language the game has downloaded.",
    "types": "Optional and much bigger (all of them: about 1 GB). What textures they hold become pictures too.",
    "gallery": "Opens the gallery (out/index.html) in the browser. Click a picture there to copy its id.",
    "seen": "Everything extracted so far counts as seen, pictures and texts together (one pointer): the NEW / CHANGED badges of "
            "the gallery and of the text browser and their \"new or changed\" filters start over and only show what the next "
            "game updates bring.",
    "texts": "Opens every extracted game text in the browser (out/texts/index.html): search all folders or one, in every language "
             "the game has downloaded, and see which texts a game version added or changed.",
    "text_mapping": "Which game text each of the webapp's texts (names and descriptions in the data files) is. Confirm the "
                    "suggestions, check near matches (a typo?), pick another text, or mark a text as the webapp's own.",
    "text_preview": "Lists every text Sync texts would change in the webapp's data files (the game's wording, English too, and the "
                    "translations the webapp lacks or has wrong). Writes nothing.",
    "text_sync": "Writes the game's wording and translations of every mapped text into the webapp's data files (data/*.json of "
                 "the webapp's repository). Use the preview first; git shows the result.",
    "mapping": "Which game picture each of the webapp's images comes from. Confirm the suggestions, pick another picture, "
               "or mark an image as having no original in the game. Only images made from the game's own pictures count "
               "as official.",
    "preview": "Lists which webapp files Sync would write from the game's pictures (and how: crop, resize). Writes nothing.",
    "sync": "Makes every mapped webapp image from its game picture (items / heroes 144x144 PNG, events 720x360 WebP) "
            "and overwrites the files in webapp/public/assets. Use Preview first; git shows the result.",
    "import": "Adds a game picture to the webapp as a new image. First field: the GAME picture, its id as the gallery shows "
              "it (click a picture there to copy it), e.g. BigBg/banner016. Second field: the WEBAPP file to make, "
              "<folder>/<name>, e.g. packages/enhancement_special_pack or items/material/gold. Items and heroes become "
              "144x144, events and packages WebP.",
}


def build_command(action: str, serial: str = "", adb: str = "", types: tuple[str, ...] = C.REQUIRED_TYPES,
                  sprite: str = "", dest: str = "", force: bool = False, apply: bool = False) -> list[str]:
    """The `main.py` command line for a button (kept separate so it can be tested without a window)."""
    cmd = [sys.executable, "-u", str(MAIN), "--serial", serial.strip() or C.DEFAULT_SERIAL]
    cmd += ["--adb-exe", adb.strip()] if adb.strip() else []
    cmd.append(action)
    if action in ("scan", "update"):
        cmd += ["--types", ",".join(types)]
    elif action == "import":
        cmd += [sprite.strip(), dest.strip()] + (["--force"] if force else [])
    elif action in ("sync", "text-sync"):
        cmd += ["--apply"] if apply else []
    return cmd


class Tip:
    """The explanation of a widget, shown while the mouse rests on it."""

    def __init__(self, widget: tk.Widget, text: str):
        self.widget, self.text, self.window = widget, text, None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _=None) -> None:
        if self.window:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.attributes("-topmost", True)
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
        self.after_finish = None  # called once the running command has ended (scan: fill the table)
        self.lines: queue.Queue = queue.Queue()  # output lines, None = command ended
        self.summaries: queue.Queue = queue.Queue()  # the texts' summary, worked out in a thread (it takes a few seconds)
        self.action = ""
        root.title("Last Asylum: Plague - Game Asset Extractor")
        root.minsize(700, 700)
        pad = {"padx": 8, "pady": 4}

        how = ttk.LabelFrame(root, text="How it works")
        how.pack(fill="x", **pad)
        ttk.Label(how, text=HOW_IT_WORKS, wraplength=WRAP, justify="left").pack(anchor="w", padx=8, pady=4)

        dev = ttk.LabelFrame(root, text="Device")
        dev.pack(fill="x", **pad)
        ttk.Label(dev, text="ADB address").grid(row=0, column=0, sticky="w", padx=8)
        self.serial = tk.StringVar(value=C.DEFAULT_SERIAL)
        tip(ttk.Entry(dev, textvariable=self.serial, width=18), "serial").grid(row=0, column=1, sticky="w")
        ttk.Label(dev, text="adb.exe (optional)").grid(row=0, column=2, sticky="w", padx=(16, 8))
        self.adb = tk.StringVar()
        tip(ttk.Entry(dev, textvariable=self.adb, width=34), "adb").grid(row=0, column=3, sticky="w")
        tip(ttk.Button(dev, text="Check ADB", command=lambda: self.start("check")), "check").grid(row=0, column=4, padx=12, pady=4)

        new = ttk.LabelFrame(root, text="Scan & download")
        new.pack(fill="both", expand=True, **pad)
        bar = ttk.Frame(new)
        bar.pack(fill="x")
        tip(ttk.Button(bar, text="1  Scan for what is new", command=lambda: self.start("scan")), "scan").pack(side="left", **pad)
        tip(ttk.Button(bar, text="2  Download & extract", command=lambda: self.start("update")), "pull").pack(side="left", **pad)
        tip(ttk.Button(bar, text="3  Mark all as seen", command=lambda: self.start("baseline")), "seen").pack(side="left", **pad)
        kinds = ttk.Frame(new)
        kinds.pack(fill="x", padx=8)
        self.types = {key: tk.BooleanVar(value=key in C.REQUIRED_TYPES) for key in C.TYPES}  # the required ones stay ticked
        for i, (key, (label, _)) in enumerate(C.TYPES.items()):
            required = key in C.REQUIRED_TYPES
            box = ttk.Checkbutton(kinds, text=label, variable=self.types[key], state="disabled" if required else "normal")
            tip(box, "required" if required else "types").grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 24))
        cols = ("new", "changed", "unchanged", "mb")
        self.tree = ttk.Treeview(new, columns=cols, height=8)
        self.tree.heading("#0", text="Kind / folder in the game")
        self.tree.column("#0", width=300)
        for c, title in zip(cols, ("New", "Changed", "Unchanged", "MB to download")):
            self.tree.heading(c, text=title)
            self.tree.column(c, width=100 if c == "mb" else 80, anchor="e")
        self.tree.pack(fill="both", expand=True, **pad)
        self.summary = tk.StringVar(value="Click Scan to see what is new since the last download.")
        ttk.Label(new, textvariable=self.summary, wraplength=WRAP, justify="left", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=8, pady=(0, 6))

        pics = ttk.LabelFrame(root, text="Pictures")
        pics.pack(fill="x", **pad)
        self.coverage = tk.StringVar(value="")
        ttk.Label(pics, textvariable=self.coverage, wraplength=WRAP, justify="left", font=("Segoe UI", 9, "bold")).pack(
            anchor="w", padx=8, pady=(2, 0))
        # the four buttons of a group sit in a grid of their own with the same width in both groups, so they line up
        row = ttk.Frame(pics)
        row.pack(anchor="w")
        for column, (text, command, key) in enumerate((
                ("Open gallery", self.open_gallery, "gallery"), ("Edit mapping...", self.edit_mapping, "mapping"),
                ("Preview sync", lambda: self.start("sync"), "preview"), ("Sync to webapp...", self.sync_now, "sync"))):
            tip(ttk.Button(row, width=BUTTON_WIDTH, text=text, command=command), key).grid(row=0, column=column, sticky="w", **pad)
        imp = ttk.Frame(pics)
        imp.pack(anchor="w")
        ttk.Label(imp, text="Game picture id (from the gallery)").grid(row=0, column=0, sticky="w", padx=8)
        self.sprite = tk.StringVar()
        tip(ttk.Entry(imp, textvariable=self.sprite, width=40), "import").grid(row=0, column=1, sticky="w")
        ttk.Label(imp, text="Webapp file to make (folder/name)").grid(row=1, column=0, sticky="w", padx=8)
        self.dest = tk.StringVar()
        tip(ttk.Entry(imp, textvariable=self.dest, width=40), "import").grid(row=1, column=1, sticky="w", pady=4)
        self.force = tk.BooleanVar(value=False)
        ttk.Checkbutton(imp, text="Replace if it exists", variable=self.force).grid(row=0, column=2, sticky="w", padx=8)
        tip(ttk.Button(imp, text="Import", command=lambda: self.start("import")), "import").grid(row=1, column=2, sticky="w", padx=8)

        texts = ttk.LabelFrame(root, text="Texts")
        texts.pack(fill="x", **pad)
        self.text_coverage = tk.StringVar(value="")
        ttk.Label(texts, textvariable=self.text_coverage, wraplength=WRAP, justify="left", font=("Segoe UI", 9, "bold")).pack(
            anchor="w", padx=8, pady=(2, 0))
        row = ttk.Frame(texts)
        row.pack(anchor="w")
        for column, (text, command, key) in enumerate((
                ("Open texts", lambda: self.start("texts"), "texts"), ("Edit mapping...", self.edit_text_mapping, "text_mapping"),
                ("Preview sync", lambda: self.start("text-sync"), "text_preview"), ("Sync to webapp...", self.sync_texts_now, "text_sync"))):
            tip(ttk.Button(row, width=BUTTON_WIDTH, text=text, command=command), key).grid(row=0, column=column, sticky="w", **pad)

        status = ttk.Frame(root)
        status.pack(fill="x", **pad)
        self.status = tk.StringVar(value="Idle")
        ttk.Label(status, textvariable=self.status).pack(side="left")
        self.stop_button = ttk.Button(status, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="right")

        self.log = tk.Text(root, height=9, wrap="word", state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, **pad)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(100, self.pump)
        root.after(200, self.show_scan)
        root.after(250, self.refresh_coverage)
        root.after(300, self.refresh_text_coverage)

    # --- actions -------------------------------------------------------------------------------------------------
    def start(self, action: str, **extra) -> None:
        if self.proc is not None and self.proc.poll() is not None:  # it ended, but the window missed it
            self.finished()
        if self.proc is not None:
            self.write(f"! {self.status.get()} - press Stop first\n")
            return
        types = tuple(key for key, var in self.types.items() if var.get())
        cmd = build_command(action, self.serial.get(), self.adb.get(), types,
                            self.sprite.get(), self.dest.get(), self.force.get(), **extra)
        self.action = action
        self.write(f"> {action}\n")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        self.proc = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     creationflags=NO_WINDOW, bufsize=1, encoding="utf-8", errors="replace", env=env)
        threading.Thread(target=self.read, args=(self.proc,), daemon=True).start()
        self.status.set(f"Running: {action}")
        self.after_finish = {"scan": self.show_scan, "update": self.show_scan, "import": self.refresh_coverage,
                             "sync": self.refresh_coverage, "texts": self.show_texts, "text-sync": self.refresh_text_coverage}.get(action)
        self.stop_button.configure(state="normal")

    def stop(self) -> None:
        """Ends the command. What it did so far is kept: downloads are checked and picked up again by the next run."""
        if self.proc is not None and self.proc.poll() is None:
            self.write("> stopping...\n")
            self.proc.terminate()

    def refresh_coverage(self) -> None:
        """How many webapp images are made from the game's own pictures (mapping.json against the extracted pictures)."""
        try:
            self.coverage.set(Mp.summary(Mp.rows(Mp.load(), S.load_index(), Mp.load_matches())))
        except OSError as e:
            self.coverage.set(f"({e})")

    def edit_mapping(self) -> None:
        mapping_gui.Editor(self.root, on_change=self.refresh_coverage)

    def refresh_text_coverage(self) -> None:
        """How many of the webapp's texts are the game's own (text_mapping.json against the extracted texts and the webapp's data)."""
        def work() -> None:
            try:
                _, texts = TM.read_webapp()
                self.summaries.put(TM.summary(TM.rows(TM.load(), texts, TM.Game(T.load()), TM.webapp_languages())))
            except (OSError, ValueError) as e:
                self.summaries.put(f"({e})")

        self.text_coverage.set("Counting the webapp's texts ...")
        threading.Thread(target=work, daemon=True).start()

    def edit_text_mapping(self) -> None:
        try:
            text_mapping_gui.Editor(self.root, on_change=self.text_coverage.set)
        except OSError as e:  # the webapp's data is not where it is looked for
            self.write(f"! {e}\n")

    def sync_texts_now(self) -> None:
        text = ("Write the game's wording and translations of every mapped text into the webapp's data files?\n\nThis overwrites "
                "strings in the webapp's data/*.json (git shows the result). 'Preview sync' of the Texts group lists them first.")
        if messagebox.askyesno("Sync texts to webapp", text, parent=self.root):
            self.start("text-sync", apply=True)

    def sync_now(self) -> None:
        text = ("Make every mapped webapp image from its game picture?\n\nThis overwrites files in webapp/public/assets "
                "(git shows the result). 'Preview sync' of the Pictures group lists them first.")
        if messagebox.askyesno("Sync pictures to webapp", text, parent=self.root):
            self.start("sync", apply=True)

    def show_scan(self) -> None:
        """Fill the table from the last scan (state/scan.json)."""
        path = C.STATE / "scan.json"
        if not path.exists():
            return
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.tree.delete(*self.tree.get_children())
        for kind in Sc.by_type(result):
            top = self.tree.insert("", "end", text=kind["label"], open=False, values=self.cells(kind))  # collapsed: the kinds first, a click opens one
            for row in kind["groups"]:
                self.tree.insert(top, "end", text=row["group"], values=self.cells(row))
        if result["removed"]:
            self.tree.insert("", "end", text=f"(removed from the game: {len(result['removed'])})")
        self.summary.set(Sc.summary_lines(result)[0])

    @staticmethod
    def cells(row: dict) -> tuple:
        return (row["new"] or "", row["changed"] or "", row["unchanged"] or "", f"{row['kb'] / 1024:.1f}" if row["kb"] else "")

    def open_gallery(self) -> None:
        page = C.OUT / "index.html"
        if page.exists():
            G.write()  # the webapp images mapped since the last run count as "in webapp"
            webbrowser.open(page.as_uri())
        else:
            self.write("! no gallery yet: run Download & extract first\n")

    def show_texts(self) -> None:
        """The text browser was just written: open it."""
        page = C.OUT / "texts" / "index.html"
        if page.exists():
            webbrowser.open(page.as_uri())

    def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
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
                self.text_coverage.set(self.summaries.get_nowait())
        except queue.Empty:
            pass
        try:
            while True:
                line = self.lines.get_nowait()
                if line is None:  # the command ended
                    self.finished()
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
