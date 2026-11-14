"""The text mapping editor: for every localized text of the webapp's data files, which game text it is (see text_mapping.py).

Left: the webapp's texts with their status (filter and search above; a click on a column heading sorts, again: the other
way round). Right, for the selected one: its text in every language of the webapp next to what the game says (the chosen
game text, written the webapp's way; a difference is marked), then the closest game texts (the same English first, then
near ones: a possible typo) and a search over all game texts in any language. "Use this text" maps it, "Own text" marks it
as having no original in the game. Every change is written to text_mapping.json at once; nothing in the webapp changes until
Sync texts.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import text_mapping as TM
import texts as T
from mapping_gui import inert

HEADINGS = {"#0": "Webapp text", "status": "Status", "en": "English", "source": "Game text"}
COLOURS = {"official": "#1b7f3b", "to sync": "#b36b00", "mismatch": "#b00020", "missing": "#b00020", "suggested": "#1f5fbf",
           "ambiguous": "#8e3fbf", "near": "#8e3fbf", "unmapped": "#b00020", "none": "#777777"}
NOTES = {
    "official": "The webapp says what the game says in every language.",
    "to sync": "Mapped: Sync texts writes the game's wording into the webapp (the differences are marked).",
    "mismatch": "The placeholders of the webapp's English and the game's do not pair up: nothing is synced.",
    "missing": "The mapped game text is no longer in the extracted texts: choose another or clear it.",
    "suggested": "The game has this English text; 'Use this text' (or 'Map all suggested') maps it.",
    "ambiguous": "The game has this English text with different translations: pick the right one.",
    "near": "Not in the game as written, but the texts below are nearly the same: maybe a typo, pick one if it is the same text.",
    "unmapped": "Nothing like it in the game: search below, or mark it as the webapp's own text.",
    "none": "Marked as the webapp's own text: nothing is synced.",
}
DIFFERS, SAME, BLANK = "#fff0d0", "white", "#f0f0f0"
TEXT_WIDTH, TEXT_HEIGHT = 46, 5  # characters, lines: a webapp text and the game's, side by side
LIST_HEIGHT = 8


def sort_key(row: dict, column: str) -> str:
    return (row["location"] if column == "#0" else row[column] or "").lower()


def readonly(parent: tk.Misc) -> tk.Text:
    box = tk.Text(parent, width=TEXT_WIDTH, height=TEXT_HEIGHT, wrap="word", font=("Segoe UI", 9))
    box.configure(state="disabled", takefocus=False)
    return box


def show(box: tk.Text, text: str, colour: str) -> None:
    box.configure(state="normal", background=colour)
    box.delete("1.0", "end")
    box.insert("1.0", text)
    box.configure(state="disabled")


class Editor(tk.Toplevel):
    def __init__(self, master: tk.Misc, on_change=None):
        super().__init__(master)
        self.title("Text mapping: webapp text -> game text")
        self.on_change = on_change
        self.game: TM.Game | None = None
        self.location: str | None = None
        self.chosen: str | None = None
        self.sort: tuple[str, bool] | None = None  # (column, descending); None: the order of the data
        self.status_note = ""  # what the selected text's status means
        self.cand_ids: list[str] = []
        self.result_ids: list[str] = []
        self.reload()

        right = ttk.Frame(self)  # packed first: it always keeps the width its text boxes need, the list gets the rest
        right.pack(side="right", fill="both", padx=8, pady=8)
        left = ttk.Frame(self)
        left.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        bar = ttk.Frame(left)
        bar.pack(fill="x")
        self.filter = tk.StringVar(value="all")
        box = ttk.Combobox(bar, textvariable=self.filter, values=("all", *TM.STATUSES), state="readonly", width=11)
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda e: self.fill())
        self.query = tk.StringVar()
        self.query.trace_add("write", lambda *a: self.fill())
        ttk.Entry(bar, textvariable=self.query, width=24).pack(side="left", padx=6)
        self.count = tk.StringVar()
        ttk.Label(bar, textvariable=self.count).pack(side="left")
        self.tree = ttk.Treeview(left, columns=("status", "en", "source"), height=26, selectmode="browse")
        for column in HEADINGS:
            self.tree.heading(column, command=lambda c=column: self.sort_by(c))
        self.show_headings()
        self.tree.column("#0", width=300)
        self.tree.column("status", width=70)
        self.tree.column("en", width=220)
        self.tree.column("source", width=260)
        for status, colour in COLOURS.items():
            self.tree.tag_configure(status, foreground=colour)
        scroll = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True, pady=6)
        self.tree.bind("<<TreeviewSelect>>", self.select)

        bulk = ttk.Frame(left)
        bulk.pack(fill="x")
        inert(ttk.Button(bulk, text="Map all suggested", command=self.accept_all)).pack(side="left")
        ttk.Label(bulk, text="  (the same English text in the game, one translation; near and ambiguous ones are never taken)").pack(side="left")

        self.heading = tk.StringVar(value="Select a text on the left.")
        # the heading and the note keep their size whatever a selection puts in them (2 and 3 lines), so nothing below them moves
        heading = tk.Label(right, textvariable=self.heading, font=("Segoe UI", 10, "bold"), justify="left", anchor="nw", height=2)
        heading.pack(anchor="w")
        self.note = tk.StringVar()
        note = tk.Label(right, textvariable=self.note, foreground="#555", justify="left", anchor="nw", height=3)
        note.pack(anchor="w")
        grid = ttk.Frame(right)
        grid.pack(anchor="w", pady=6)
        ttk.Label(grid, text="Webapp now").grid(row=0, column=1)
        ttk.Label(grid, text="Game says (after sync)").grid(row=0, column=2)
        self.boxes: dict[str, tuple[tk.Text, tk.Text]] = {}
        for row, lang in enumerate(self.langs, 1):
            ttk.Label(grid, text=lang).grid(row=row, column=0, padx=4, sticky="n")
            self.boxes[lang] = (readonly(grid), readonly(grid))
            for column, widget in enumerate(self.boxes[lang], 1):
                widget.grid(row=row, column=column, padx=3, pady=2)

        ttk.Label(right, text="Closest game texts (click to choose)").pack(anchor="w", pady=(8, 2))
        self.cands = tk.Listbox(right, height=LIST_HEIGHT, width=2 * TEXT_WIDTH, exportselection=False)
        self.cands.pack(anchor="w", fill="x")
        self.cands.bind("<<ListboxSelect>>", lambda e: self.pick(self.cands, self.cand_ids))
        self.cands.bind("<ButtonRelease-1>", lambda e: self.tree.focus_set())  # picked: back to the list

        ttk.Label(right, text="Or search all game texts (any language)").pack(anchor="w", pady=(8, 2))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *a: self.search_texts())
        ttk.Entry(right, textvariable=self.search, width=50).pack(anchor="w")
        self.results = tk.Listbox(right, height=6, width=2 * TEXT_WIDTH, exportselection=False)
        self.results.pack(anchor="w", fill="x", pady=2)
        self.results.bind("<<ListboxSelect>>", lambda e: self.pick(self.results, self.result_ids))
        self.results.bind("<ButtonRelease-1>", lambda e: self.tree.focus_set())

        buttons = ttk.Frame(right)
        buttons.pack(anchor="w", pady=6)
        inert(ttk.Button(buttons, text="Use this text", command=self.use)).pack(side="left", padx=(0, 6))
        inert(ttk.Button(buttons, text="Own text (no original in the game)", command=self.own_text)).pack(side="left", padx=6)
        inert(ttk.Button(buttons, text="Clear mapping", command=self.clear)).pack(side="left", padx=6)
        self.summary = tk.StringVar()
        summary = ttk.Label(right, textvariable=self.summary, font=("Segoe UI", 9, "bold"))
        summary.pack(anchor="w", pady=(8, 0))
        self.fill()

        # The panel is as wide as the two text boxes and stays so: a long location must not widen it (the list would shrink and
        # everything shift while moving through the rows); the labels wrap at that width.
        self.update_idletasks()
        for label in (heading, note, summary):
            label.configure(wraplength=grid.winfo_reqwidth())
        self.update_idletasks()
        right.configure(width=grid.winfo_reqwidth(), height=right.winfo_reqheight())
        right.pack_propagate(False)

        self.update_idletasks()  # open at the size the content asks for (the list and the text boxes), within the screen
        width = min(self.winfo_reqwidth(), self.winfo_screenwidth() - 40)
        self.geometry(f"{width}x{min(max(self.winfo_reqheight(), 640), self.winfo_screenheight() - 80)}")
        self.minsize(min(right.winfo_reqwidth() + 340, width), 560)

    # --- data ---------------------------------------------------------------------------------------------------
    def reload(self) -> None:
        if self.game is None:
            self.game = TM.Game(T.load())
        _, self.texts = TM.read_webapp()
        self.langs = TM.webapp_languages()
        self.mapping = TM.load()
        self.table = TM.rows(self.mapping, self.texts, self.game, self.langs)

    def changed(self, location: str | None = None) -> None:
        """The mapping changed: of one text (`location`: only its row is redone), or of several (everything is read again)."""
        if location is None:
            keep = self.location
            self.reload()
            self.fill(select=keep)
        else:
            self.update_row(location)
        self.tree.focus_set()  # whatever was clicked, up / down go on from the same row
        if self.on_change:
            self.on_change(self.summary.get())  # the window's count of mapped texts: no need to count them again there

    def update_row(self, location: str) -> None:
        """One text was mapped or unmapped: redo its row and the counts, nothing else (matching all 692 texts again is slow)."""
        self.mapping = TM.load()
        row = next(r for r in self.table if r["location"] == location)
        row["status"], row["source"] = TM.status_of(self.texts[location], self.mapping.get(location), self.game, self.langs)
        if self.filter.get() in ("all", row["status"]):
            self.tree.item(location, tags=(row["status"],), values=(row["status"], row["en"].replace("\n", " "), row["source"] or ""))
            self.select()  # the heading, the note and the boxes follow the new status
        else:
            # a row the filter no longer shows (mapped while the list shows "suggested") hands the selection on to the next
            # one (else the previous one), so up / down go on from where the list was
            neighbour = self.tree.next(location) or self.tree.prev(location)
            self.tree.delete(location)
            if neighbour:
                self.tree.selection_set(neighbour)
                self.tree.focus(neighbour)
                self.tree.see(neighbour)
        self.count.set(f"{len(self.tree.get_children())} of {len(self.table)}")
        self.summary.set(TM.summary(self.table))

    # --- list ---------------------------------------------------------------------------------------------------
    def sort_by(self, column: str) -> None:
        descending = self.sort == (column, False)  # the same heading again turns it round
        self.sort = (column, descending)
        self.show_headings()
        self.fill(select=self.location)

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
        return sorted(self.table, key=lambda r: sort_key(r, column), reverse=descending)

    def fill(self, select: str | None = None) -> None:
        want, q = self.filter.get(), self.query.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for r in self.sorted_table():
            if (want == "all" or r["status"] == want) and (q in r["location"].lower() or q in r["en"].lower()):
                self.tree.insert("", "end", iid=r["location"], text=r["location"], tags=(r["status"],),
                                 values=(r["status"], r["en"].replace("\n", " "), r["source"] or ""))
                shown += 1
        self.count.set(f"{shown} of {len(self.table)}")
        self.summary.set(TM.summary(self.table))
        if select and self.tree.exists(select):
            self.tree.selection_set(select)
            self.tree.focus(select)  # the row the arrow keys move from (selecting alone does not set it)
            self.tree.see(select)

    def select(self, _=None) -> None:
        picked = self.tree.selection()
        if not picked:
            return
        self.location = picked[0]
        row = next(r for r in self.table if r["location"] == self.location)
        node = self.texts[self.location]
        self.chosen = row["source"]
        self.heading.set(f"{self.location}   [{row['status']}]")
        self.status_note = NOTES[row["status"]]
        found = TM.candidates(node, self.game, self.langs)
        self.cand_ids = [c["id"] for c in found]
        self.cands.delete(0, "end")
        for c in found:
            self.cands.insert("end", f"{c['score']:>3}%  {c['id']}   {(self.game.text('en', c['id']) or '')[:60]!r}")
        self.preview()

    # --- previews -----------------------------------------------------------------------------------------------
    def preview(self) -> None:
        """The webapp's text and the chosen game text, language by language; what Sync would change is marked."""
        if self.location is None:
            return
        node = self.texts[self.location]
        found = TM.targets(node, self.chosen, self.game, self.langs) if self.chosen else {}
        for lang, (webapp, game) in self.boxes.items():
            show(webapp, node.get(lang, ""), SAME if node.get(lang) else BLANK)
            if lang not in found:
                show(game, "(no game text)" if self.chosen else "", BLANK)
            elif found[lang] is None:
                show(game, "(the placeholders do not pair up)", DIFFERS)
            else:
                show(game, found[lang], SAME if found[lang] == node.get(lang, "") else DIFFERS)
        tail = f"  Chosen: {self.chosen}" if self.chosen else ""
        self.note.set(self.status_note + tail)

    def pick(self, box: tk.Listbox, ids: list[str]) -> None:
        picked = box.curselection()
        if picked:
            self.chosen = ids[picked[0]]
            self.preview()

    def search_texts(self) -> None:
        self.result_ids = self.game.search(self.search.get())
        self.results.delete(0, "end")
        for text_id in self.result_ids:
            self.results.insert("end", f"{text_id}   {(self.game.text('en', text_id) or '')[:60]!r}")

    # --- changes ------------------------------------------------------------------------------------------------
    def use(self) -> None:
        if self.location and self.chosen:
            TM.set_source(self.location, self.chosen)
            self.changed(self.location)

    def own_text(self) -> None:
        if self.location:
            TM.set_source(self.location, None)
            self.changed(self.location)

    def clear(self) -> None:
        if self.location:
            TM.clear(self.location)
            self.changed(self.location)

    def accept_all(self) -> None:
        taken = TM.accept_suggestions(self.table)
        self.heading.set(f"Mapped {taken} texts to the game text with the same English. Check them with the filter 'to sync': "
                         "the right-hand boxes are what Sync texts would write.")
        self.changed()

