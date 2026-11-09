import tkinter as tk

import pytest

import mapping_gui as MG

TABLE = [
    {"rel": "items/a.png", "status": "suggested", "source": "G/x", "dist": 3},
    {"rel": "items/b.png", "status": "unmapped", "source": None, "dist": None},
    {"rel": "items/c.png", "status": "suggested", "source": "G/y", "dist": 5},
]
MATCHES = {"items/a.png": [{"id": "G/x", "dist": 3}, {"id": "G/y", "dist": 9}, {"id": "G/z", "dist": 12}]}


@pytest.fixture(scope="module")
def root():
    """One Tk root for the whole module: starting and destroying several in one process makes the next one fail to find
    its Tcl library on Windows."""
    try:
        tk_root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"cannot start Tk: {e}")
    tk_root.withdraw()
    yield tk_root
    tk_root.destroy()


@pytest.fixture
def editor(root, monkeypatch):
    def reload(self):  # fixed data: the real index, matches and mapping stay untouched
        self.index, self.matches, self.mapping, self.table, self.ids = {"sprites": {}}, MATCHES, {}, TABLE, []

    monkeypatch.setattr(MG.Editor, "reload", reload)
    ed = MG.Editor(root)
    root.update()
    yield ed
    ed.destroy()


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def test_no_button_or_slider_takes_the_keyboard_from_the_list(editor):
    editor.tree.selection_set("items/a.png")  # shows the three candidate buttons
    editor.update()
    assert len(editor.cands.winfo_children()) == 3
    clickable = [w for w in widgets(editor) if w.winfo_class() in ("TButton", "TCheckbutton", "TScale")]
    assert len(clickable) >= 9  # accept, 3 candidates, checkbox, 2 sliders, 3 actions
    assert [w for w in clickable if str(w.cget("takefocus")) != "0"] == []


def test_the_window_opens_wide_enough_for_all_three_pictures(editor):
    editor.update()
    panes = [editor.panes[k] for k in ("webapp", "game", "result")]
    window_right = editor.winfo_rootx() + editor.winfo_width()
    assert [p.winfo_rootx() + p.winfo_width() for p in panes if p.winfo_rootx() + p.winfo_width() > window_right] == []
    assert min(p.winfo_width() for p in panes) >= MG.THUMB  # none squeezed, none cut off


def test_typing_fields_still_take_the_focus(editor):
    fields = [w for w in widgets(editor) if w.winfo_class() in ("TEntry", "TSpinbox", "TCombobox")]
    assert fields and all(str(w.cget("takefocus")) != "0" for w in fields)


def test_the_list_row_the_arrow_keys_start_from_is_set_after_a_refill(editor):
    editor.fill(select="items/b.png")
    assert editor.tree.selection() == ("items/b.png",) and editor.tree.focus() == "items/b.png"
