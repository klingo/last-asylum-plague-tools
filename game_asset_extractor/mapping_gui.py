"""The mapping editor: for every image of the webapp, which game picture it is made from (see mapping.py).

Left: the webapp's images with their status (filter and search above). Right, for the selected one: the webapp picture,
the game picture it is mapped to (or the closest the hash match found), and what `sync` would make of it, then the
closest candidates and a search over all game pictures. "Use this picture" maps it, "No original" marks it as having none
in the game. A second picture (a trophy) can be put on top of the game picture ("Overlay"). Every change is written to mapping.json at once; nothing in the webapp changes until Sync.
While a slider moves the result is redrawn at most every `LIVE_DELAY` ms, without encoding it; the exact one follows when it rests.
The list sorts by a click on a column heading (again: the other way round). Every slider has a field next to it for an exact value.
"""

from __future__ import annotations

import io
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageTk

import config as C
import mapping as Mp
import render as R
import state as S

THUMB = 230  # px: the three big previews
SMALL = 64  # px: candidate buttons
CANDIDATES_HEIGHT = 112  # px: the row of candidate buttons (a picture of SMALL and two lines of text)
SEARCH_LIMIT = 150
LIVE_DELAY = 30  # ms: a moving slider redraws the result at most this often ...
SETTLE_DELAY = 250  # ms: ... and the exact preview (encoded, compared with the webapp's file) comes when it rests
SLIDER_LENGTH = 110  # px: a slider (its field sits next to it)
HEADINGS = {"#0": "Webapp image", "status": "Status", "source": "Game picture", "dist": "Dist"}
COLOURS = {"official": "#1b7f3b", "to sync": "#b36b00", "missing": "#b00020", "suggested": "#1f5fbf", "unmapped": "#b00020", "none": "#777777"}


def load_picture(path: Path) -> Image.Image | None:
    try:
        with Image.open(path) as img:
            return img.convert("RGBA")
    except (OSError, ValueError):
        return None


def thumbnail(img: Image.Image | None, size: int) -> ImageTk.PhotoImage:
    """`img` scaled to fit `size`, on a dark grey (so transparency shows), as a Tk image."""
    canvas = Image.new("RGBA", (size, size), (58, 60, 68, 255))
    if img is not None:
        img = img.copy()
        img.thumbnail((size, size), Image.LANCZOS)
        canvas.alpha_composite(img, ((size - img.width) // 2, (size - img.height) // 2))
    return ImageTk.PhotoImage(canvas)


def inert(widget: tk.Widget) -> tk.Widget:
    """A widget that never takes the keyboard when clicked (buttons, sliders): the list keeps the arrow keys."""
    widget.configure(takefocus=False)
    return widget


def sort_key(row: dict, column: str):
    """What the list sorts a row by in `column`: the distance as a number, the rest as lower-case text."""
    if column == "dist":
        return row["dist"]
    return ((row["rel"] if column == "#0" else row[column]) or "").lower()


class Editor(tk.Toplevel):
    def __init__(self, master: tk.Misc, on_change=None):
        super().__init__(master)
        self.title("Mapping: webapp image -> game picture")
        self.on_change = on_change
        self.photos: dict[str, ImageTk.PhotoImage] = {}
        self.rel: str | None = None
        self.chosen: str | None = None
        self.sort: tuple[str, bool] | None = None  # (column, descending); None: the order of the data
        self.timers: dict[str, str | None] = {"live": None, "settle": None}  # the pending `after` calls of a moving slider
        self.bind("<Destroy>", lambda e: self.stop_timers() if e.widget is self else None)
        self.overlay: str | None = None  # the picture put on top of the chosen one
        self.reload()

        right = ttk.Frame(self)  # packed first: it always keeps the width its three pictures need, the list gets the rest
        right.pack(side="right", fill="both", padx=8, pady=8)
        left = ttk.Frame(self)
        left.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        bar = ttk.Frame(left)
        bar.pack(fill="x")
        self.filter = tk.StringVar(value="all")
        box = ttk.Combobox(bar, textvariable=self.filter, values=("all", *Mp.STATUSES), state="readonly", width=11)
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda e: self.fill())
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *a: self.fill())
        ttk.Entry(bar, textvariable=self.query, width=24).pack(side="left", padx=6)
        self.count = tk.StringVar()
        ttk.Label(bar, textvariable=self.count).pack(side="left")
        self.tree = ttk.Treeview(left, columns=("status", "source", "dist"), height=26, selectmode="browse")
        for column in HEADINGS:
            self.tree.heading(column, command=lambda c=column: self.sort_by(c))
        self.show_headings()
        self.tree.column("#0", width=260)
        self.tree.column("status", width=70)
        self.tree.column("source", width=230)
        self.tree.column("dist", width=40, anchor="e")
        for status, colour in COLOURS.items():
            self.tree.tag_configure(status, foreground=colour)
        scroll = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True, pady=6)
        self.tree.bind("<<TreeviewSelect>>", self.select)

        bulk = ttk.Frame(left)
        bulk.pack(fill="x")
        ttk.Label(bulk, text="Map all unmapped images whose closest picture is within distance").pack(side="left")
        self.bulk = tk.IntVar(value=10)
        ttk.Spinbox(bulk, from_=0, to=64, textvariable=self.bulk, width=4).pack(side="left", padx=4)
        inert(ttk.Button(bulk, text="Accept", command=self.accept_all)).pack(side="left")

        self.heading = tk.StringVar(value="Select an image on the left.")
        ttk.Label(right, textvariable=self.heading, font=("Segoe UI", 10, "bold"), wraplength=720).pack(anchor="w")
        row = ttk.Frame(right)
        row.pack(pady=6)
        self.panes = {}
        for i, (key, title) in enumerate((("webapp", "Webapp now"), ("game", "Game picture"), ("result", "After sync"))):
            ttk.Label(row, text=title).grid(row=0, column=i)
            self.panes[key] = ttk.Label(row)
            self.panes[key].grid(row=1, column=i, padx=4)
            self.put(key, None)  # a blank picture of the final size: the window is sized for all three from the start
        self.note = tk.StringVar()
        # room for what a selection fills in (3 lines of note, the candidates), so the window opens high enough for it
        tk.Label(right, textvariable=self.note, foreground="#555", wraplength=720, justify="left", anchor="nw", height=3).pack(anchor="w")

        ttk.Label(right, text="Closest game pictures (click to choose)").pack(anchor="w", pady=(10, 2))
        self.cands = ttk.Frame(right, height=CANDIDATES_HEIGHT)
        self.cands.pack(anchor="w", fill="x")
        self.cands.pack_propagate(False)

        ttk.Label(right, text="Or search all game pictures").pack(anchor="w", pady=(10, 2))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *a: self.search_pictures())
        ttk.Entry(right, textvariable=self.search, width=50).pack(anchor="w")
        self.results = tk.Listbox(right, height=6, width=70, exportselection=False)
        self.results.pack(anchor="w", pady=2)
        self.results.bind("<<ListboxSelect>>", self.pick_result)
        self.results.bind("<ButtonRelease-1>", lambda e: self.tree.focus_set())  # picked: back to the list

        self.resize = tk.BooleanVar(value=False)
        inert(ttk.Checkbutton(right, text="Always make it the folder's size (720x360 for events), even if it is close to 2:1",
                              variable=self.resize, command=self.preview)).pack(anchor="w", pady=(8, 0))
        crop = ttk.Frame(right)
        crop.pack(anchor="w", pady=6)
        ttk.Label(crop, text="Crop window (a picture of another aspect)").grid(row=0, column=0, columnspan=4, sticky="w")
        self.fx = tk.DoubleVar(value=R.DEFAULT_FOCUS[0])
        self.fy = tk.DoubleVar(value=R.DEFAULT_FOCUS[1])
        ttk.Label(crop, text="left-right").grid(row=1, column=0)
        self.slider(crop, self.fx, 0, 1).grid(row=1, column=1, padx=(2, 10))
        ttk.Label(crop, text="top-bottom").grid(row=1, column=2)
        self.slider(crop, self.fy, 0, 1).grid(row=1, column=3, padx=2)

        over = ttk.Frame(right)
        over.pack(anchor="w", pady=(0, 6))
        self.overlay_label = tk.StringVar()
        ttk.Label(over, textvariable=self.overlay_label).grid(row=0, column=0, columnspan=4, sticky="w")
        inert(ttk.Button(over, text="Use chosen picture as overlay", command=self.set_overlay)).grid(row=1, column=0, padx=(0, 6))
        inert(ttk.Button(over, text="Remove overlay", command=self.remove_overlay)).grid(row=1, column=1, padx=6)
        self.ov = {key: tk.DoubleVar(value=default) for key, default in (("scale", R.OVERLAY_SCALE), ("x", R.OVERLAY_AT[0]), ("y", R.OVERLAY_AT[1]))}
        for column, (key, title) in enumerate((("scale", "size"), ("x", "left-right"), ("y", "top-bottom"))):
            ttk.Label(over, text=title).grid(row=2, column=column)
            self.slider(over, self.ov[key], 0.05 if key == "scale" else 0, 1).grid(row=3, column=column, padx=4)

        buttons = ttk.Frame(right)
        buttons.pack(anchor="w", pady=6)
        inert(ttk.Button(buttons, text="Use this picture", command=self.use)).pack(side="left", padx=(0, 6))
        inert(ttk.Button(buttons, text="No original in the game", command=self.no_original)).pack(side="left", padx=6)
        inert(ttk.Button(buttons, text="Clear mapping", command=self.clear)).pack(side="left", padx=6)
        self.summary = tk.StringVar()
        ttk.Label(right, textvariable=self.summary, font=("Segoe UI", 9, "bold"), wraplength=720).pack(anchor="w", pady=(8, 0))
        self.fill()

        self.update_idletasks()  # open at the size the content asks for (the list and the three pictures), within the screen
        width = min(self.winfo_reqwidth(), self.winfo_screenwidth() - 40)
        self.geometry(f"{width}x{min(max(self.winfo_reqheight(), 720), self.winfo_screenheight() - 80)}")
        self.minsize(min(right.winfo_reqwidth() + 340, width), 600)

    # --- data ---------------------------------------------------------------------------------------------------
    def reload(self) -> None:
        self.index = S.load_index()
        self.matches = Mp.load_matches()
        self.mapping = Mp.load()
        self.table = Mp.rows(self.mapping, self.index, self.matches)
        self.ids = sorted(self.index["sprites"])

    def changed(self) -> None:
        keep = self.rel
        self.reload()
        self.fill(select=keep)
        self.tree.focus_set()  # whatever was clicked, up / down go on from the same row
        if self.on_change:
            self.on_change()

    # --- list ---------------------------------------------------------------------------------------------------
    def sort_by(self, column: str) -> None:
        descending = self.sort == (column, False)  # the same heading again turns it round
        self.sort = (column, descending)
        self.show_headings()
        self.fill(select=self.rel)

    def show_headings(self) -> None:
        for column, title in HEADINGS.items():
            arrow = ""
            if self.sort and self.sort[0] == column:
                arrow = "  ▼" if self.sort[1] else "  ▲"
            self.tree.heading(column, text=title + arrow)

    def sorted_table(self) -> list[dict]:
        if not self.sort:
            return self.table
        column, descending = self.sort
        if column == "dist":  # images without a candidate go last either way
            known = sorted((r for r in self.table if r["dist"] is not None), key=lambda r: r["dist"], reverse=descending)
            return known + [r for r in self.table if r["dist"] is None]
        return sorted(self.table, key=lambda r: sort_key(r, column), reverse=descending)

    def fill(self, select: str | None = None) -> None:
        want, q = self.filter.get(), self.query.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for r in self.sorted_table():
            if (want == "all" or r["status"] == want) and q in r["rel"].lower():
                self.tree.insert("", "end", iid=r["rel"], text=r["rel"], tags=(r["status"],),
                                 values=(r["status"], r["source"] or "", "" if r["dist"] is None else r["dist"]))
                shown += 1
        self.count.set(f"{shown} of {len(self.table)}")
        self.summary.set(Mp.summary(self.table))
        if select and self.tree.exists(select):
            self.tree.selection_set(select)
            self.tree.focus(select)  # the row the arrow keys move from (selecting alone does not set it)
            self.tree.see(select)

    def select(self, _=None) -> None:
        picked = self.tree.selection()
        if not picked:
            return
        self.rel = picked[0]
        entry = self.mapping.get(self.rel) or {}
        best = Mp.best_candidate(self.matches, self.rel)
        self.chosen = entry.get("source") or (best["id"] if best else None)
        fx, fy = entry.get("focus") or R.DEFAULT_FOCUS
        self.fx.set(fx)
        self.fy.set(fy)
        self.resize.set(bool(entry.get("resize")))
        over = entry.get("overlay") or {}
        self.overlay = over.get("source")
        self.ov["scale"].set(over.get("scale", R.OVERLAY_SCALE))
        self.ov["x"].set(over.get("at", R.OVERLAY_AT)[0])
        self.ov["y"].set(over.get("at", R.OVERLAY_AT)[1])
        row = next(r for r in self.table if r["rel"] == self.rel)
        self.heading.set(f"{self.rel}   [{row['status']}]")
        self.show_candidates()
        self.preview()

    # --- previews -----------------------------------------------------------------------------------------------
    def put(self, key: str, img: Image.Image | None, size: int = THUMB) -> None:
        self.photos[key] = thumbnail(img, size)
        self.panes[key].configure(image=self.photos[key])

    def stop_timers(self) -> None:
        for name, timer in self.timers.items():
            if timer:
                self.after_cancel(timer)
            self.timers[name] = None

    def drag(self) -> None:
        """A slider moved: redraw the result now and then (not on every event, which makes the slider lag), the exact
        preview when it comes to rest."""
        if self.rel is None:
            return
        if not self.timers["live"]:
            self.timers["live"] = self.after(LIVE_DELAY, self.draw_live)
        if self.timers["settle"]:
            self.after_cancel(self.timers["settle"])
        self.timers["settle"] = self.after(SETTLE_DELAY, self.preview)

    def draw_live(self) -> None:
        self.timers["live"] = None
        self.show_result(exact=False)

    def preview(self) -> None:
        """All three pictures, the result exactly as Sync would write it."""
        if self.rel is None:
            return
        self.stop_timers()
        self.put("webapp", load_picture(C.WEBAPP_ASSETS / self.rel))
        picture = C.OUT / f"{self.chosen}.png" if self.chosen else None
        self.put("game", load_picture(picture) if picture else None)
        self.show_result(exact=True)
        self.overlay_label.set(f"Overlay: {self.overlay}" if self.overlay else "Overlay: none")

    def show_result(self, exact: bool) -> None:
        """The "After sync" picture. Not `exact`: the rendered picture as it is, without encoding it and comparing it with
        the webapp's file (what takes the time)."""
        picture = C.OUT / f"{self.chosen}.png" if self.chosen else None
        result, note = None, "No game picture chosen."
        if picture and picture.is_file():
            overlay = Mp.overlay_of({"overlay": self.overlay_entry()})
            if overlay and not overlay["path"].is_file():
                overlay = None
            args = (picture, self.rel, (self.fx.get(), self.fy.get()), self.resize.get(), overlay)
            if exact:
                data, note = R.render(*args)
                result = load_picture_bytes(data)
                same = R.same_pixels(data, C.WEBAPP_ASSETS / self.rel)
                note += "  -  the webapp file already looks exactly like this" if same else ""
            else:
                result, note = R.make(*args)
            note = f"{self.chosen}: {note}"
        self.put("result", result)
        self.note.set(note)

    def show_candidates(self) -> None:
        for child in self.cands.winfo_children():
            child.destroy()
        for i, cand in enumerate(self.matches.get(self.rel, [])):
            photo = thumbnail(load_picture(C.OUT / f"{cand['id']}.png"), SMALL)
            self.photos[f"cand{i}"] = photo
            inert(ttk.Button(self.cands, image=photo, text=f"{cand['id'].split('/')[-1][:22]}\ndist {cand['dist']}", compound="top",
                             command=lambda c=cand["id"]: self.choose(c))).pack(side="left", padx=4)

    def slider(self, parent: tk.Misc, var: tk.DoubleVar, low: float, high: float) -> ttk.Frame:
        """A slider on `var` with a field beside it for an exact value; each follows the other."""
        frame = ttk.Frame(parent)
        inert(ttk.Scale(frame, from_=low, to=high, variable=var, length=SLIDER_LENGTH, command=lambda v: self.drag())).pack(side="left")
        text = tk.StringVar(value=f"{var.get():.3f}")
        var.trace_add("write", lambda *a: text.set(f"{var.get():.3f}"))  # a drag, or a selection that sets it

        def commit(_=None) -> None:
            try:
                value = round(min(max(float(text.get().replace(",", ".")), low), high), 3)
            except ValueError:
                value = var.get()  # not a number: back to what the slider has
            var.set(value)
            text.set(f"{value:.3f}")  # also when var did not change (a write of the same value does not notify)
            self.preview()

        field = ttk.Spinbox(frame, from_=low, to=high, increment=0.01, textvariable=text, width=6, command=commit)
        field.pack(side="left", padx=(4, 0))
        field.bind("<Return>", commit)
        field.bind("<FocusOut>", commit)
        return frame

    def overlay_entry(self) -> dict | None:
        """The overlay as mapping.json keeps it ({source, scale, at}), None without one."""
        if not self.overlay:
            return None
        return {"source": self.overlay, "scale": round(self.ov["scale"].get(), 3),
                "at": [round(self.ov["x"].get(), 3), round(self.ov["y"].get(), 3)]}

    def set_overlay(self) -> None:
        self.overlay = self.chosen
        self.preview()

    def remove_overlay(self) -> None:
        self.overlay = None
        self.preview()

    def choose(self, sprite_id: str) -> None:
        self.chosen = sprite_id
        self.preview()

    def search_pictures(self) -> None:
        q = self.search.get().strip().lower()
        self.results.delete(0, "end")
        if len(q) >= 2:
            for sid in [i for i in self.ids if q in i.lower()][:SEARCH_LIMIT]:
                self.results.insert("end", sid)

    def pick_result(self, _=None) -> None:
        picked = self.results.curselection()
        if picked:
            self.choose(self.results.get(picked[0]))

    # --- changes ------------------------------------------------------------------------------------------------
    def use(self) -> None:
        if self.rel and self.chosen:
            Mp.set_source(self.rel, self.chosen, (self.fx.get(), self.fy.get()), resize=self.resize.get(),
                          overlay=self.overlay_entry())
            self.changed()

    def no_original(self) -> None:
        if self.rel:
            Mp.set_source(self.rel, None)
            self.changed()

    def clear(self) -> None:
        if self.rel:
            Mp.clear(self.rel)
            self.changed()

    def accept_all(self) -> None:
        taken = Mp.accept_suggestions(self.table, self.bulk.get())
        self.heading.set(f"Mapped {taken} images to their closest game picture (within distance {self.bulk.get()}). "
                         "Check them with the filter 'to sync': the picture on the right is what Sync would make.")
        self.changed()


def load_picture_bytes(data: bytes) -> Image.Image | None:
    try:
        with Image.open(io.BytesIO(data)) as img:
            return img.convert("RGBA")
    except (OSError, ValueError):
        return None
