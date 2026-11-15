import pytest

import mapping_gui as MG

TABLE = [
    {"rel": "items/a.png", "status": "suggested", "source": "G/x", "dist": 3},
    {"rel": "items/b.png", "status": "unmapped", "source": None, "dist": None},
    {"rel": "items/c.png", "status": "suggested", "source": "G/y", "dist": 5},
]
MATCHES = {"items/a.png": [{"id": "G/x", "dist": 3}, {"id": "G/y", "dist": 9}, {"id": "G/z", "dist": 12}]}


@pytest.fixture
def editor(root, monkeypatch):
    def reload(self):  # fixed data: the real index, matches and mapping stay untouched
        self.index, self.matches, self.mapping, self.table, self.ids = {"sprites": {}}, MATCHES, {}, TABLE, []

    monkeypatch.setattr(MG.Editor, "reload", reload)
    ed = MG.Editor(root)
    root.update()
    yield ed
    ed.destroy()


def full_height(editor):
    """The window as tall as its content asks for: on a small screen (a CI runner's) it opens clamped to the screen, and
    pack then squeezes the lower controls out, unmapped."""
    editor.update()
    editor.geometry(f"{editor.winfo_width()}x{editor.winfo_reqheight()}")
    editor.update()


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def test_no_button_or_slider_takes_the_keyboard_from_the_list(editor):
    editor.tree.selection_set("items/a.png")  # shows the three candidate buttons
    editor.update()
    assert len(editor.cands.winfo_children()) == 3
    clickable = [w for w in widgets(editor) if w.winfo_class() in ("TButton", "TCheckbutton", "TRadiobutton", "TScale")]
    assert len(clickable) >= 20  # accept, 3 candidates, 4 layouts, checkbox, 9 sliders, 3 picture buttons, 3 actions
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


def test_a_heading_click_sorts_the_list_and_a_second_one_turns_it_round(editor):
    editor.sort_by("dist")
    assert editor.tree.get_children() == ("items/a.png", "items/c.png", "items/b.png")  # no candidate: last
    editor.sort_by("dist")
    assert editor.tree.get_children() == ("items/c.png", "items/a.png", "items/b.png")
    assert editor.tree.heading("dist", "text").startswith("Dist")
    editor.sort_by("#0")
    assert editor.tree.get_children() == ("items/a.png", "items/b.png", "items/c.png")
    assert not editor.tree.heading("dist", "text").endswith(("\u25b2", "\u25bc"))


def test_a_slider_and_its_field_follow_each_other(editor):
    full_height(editor)
    spinboxes = [w for w in widgets(editor) if w.winfo_class() == "TSpinbox" and w.cget("increment") == 0.01]
    assert len(spinboxes) == 9  # crop: 2, overlay: 3, pictures 2 and 3: 4
    editor.fx.set(0.25)
    assert spinboxes[0].get() == "0.250"
    spinboxes[0].focus_force()  # key events go to the focused widget
    editor.update()
    spinboxes[0].delete(0, "end")
    spinboxes[0].insert(0, "0.8764")
    spinboxes[0].event_generate("<Return>")
    assert editor.fx.get() == 0.876 and spinboxes[0].get() == "0.876"
    spinboxes[0].delete(0, "end")
    spinboxes[0].insert(0, "7")
    spinboxes[0].event_generate("<Return>")
    assert editor.fx.get() == 1 and spinboxes[0].get() == "1.000"  # clamped to the slider's range
    spinboxes[0].delete(0, "end")
    spinboxes[0].insert(0, "abc")
    spinboxes[0].event_generate("<Return>")
    assert editor.fx.get() == 1 and spinboxes[0].get() == "1.000"  # not a number: unchanged


def test_a_moving_slider_redraws_now_and_then_and_the_exact_preview_comes_at_rest(editor, monkeypatch):
    calls = []
    monkeypatch.setattr(editor, "show_result", lambda exact: calls.append(exact))
    editor.rel = "items/a.png"
    for _ in range(20):
        editor.drag()
    editor.after(MG.SETTLE_DELAY + 100, editor.quit)
    editor.mainloop()
    assert calls.count(False) < 5 and calls[-1] is True  # a few live redraws, then the exact one
    assert editor.timers == {"live": None, "settle": None}


def shown_frames(editor):
    # gridded, not mapped: the empty "single" frame has no size (Tk never maps such a window), and a CI window isn't shown at all
    return sorted(key for key, frame in editor.layout_frames.items() if frame.grid_info())


def test_the_layout_switch_shows_only_the_controls_of_the_chosen_layout(editor):
    full_height(editor)
    assert editor.mode.get() == "single" and shown_frames(editor) == ["single"]  # no controls: an empty frame
    for mode, frame, rows in (("overlay", "overlay", 0), ("beside2", "beside", 1), ("beside3", "beside", 2)):
        editor.mode.set(mode)
        editor.layout_changed()
        editor.update()
        assert shown_frames(editor) == [frame]
        assert sum(bool(row.grid_info()) for row in editor.beside_rows) == rows


def test_the_controls_of_every_layout_fit_the_space_the_window_opened_with(editor):
    editor.update()
    if editor.winfo_height() < editor.winfo_reqheight():
        pytest.skip("the screen is too small for the window to open at the size its content asks for")
    height = editor.stack.winfo_height()
    for mode in ("overlay", "beside3", "single"):
        editor.mode.set(mode)
        editor.layout_changed()
        editor.update()
        assert editor.stack.winfo_height() == height and editor.winfo_height() >= editor.winfo_reqheight()


def test_a_split_layout_writes_its_pictures_and_waits_for_a_missing_one(editor, monkeypatch):
    written = []
    monkeypatch.setattr(MG.Mp, "set_source", lambda *args, **kwargs: written.append((args, kwargs)))
    monkeypatch.setattr(editor, "changed", lambda: None)
    editor.rel, editor.chosen = "items/a.png", "G/x"
    editor.mode.set("beside3")
    editor.beside[0] = "G/y"
    editor.use()  # picture 3 is still missing
    assert written == [] and editor.missing_slot() == 3 and "picture 3" in editor.heading.get()
    editor.beside[1] = "G/z"
    editor.beside_focus[1][0].set(0.25)
    editor.use()
    assert written[0][1]["beside"] == [{"source": "G/y", "focus": [0.5, 0.0]}, {"source": "G/z", "focus": [0.25, 0.0]}]
    assert written[0][1]["overlay"] is None


def test_only_the_chosen_layouts_pictures_are_written(editor):
    editor.overlay, editor.beside = "G/o", ["G/y", "G/z"]
    editor.mode.set("overlay")
    assert editor.overlay_entry()["source"] == "G/o" and editor.beside_entry() is None
    editor.mode.set("beside2")
    assert editor.overlay_entry() is None and [b["source"] for b in editor.beside_entry()] == ["G/y"]
    editor.mode.set("single")
    assert editor.overlay_entry() is None and editor.beside_entry() is None and editor.missing_slot() is None


def test_selecting_an_image_sets_the_layout_from_its_entry(editor):
    editor.mapping = {"items/a.png": {"source": "G/x", "beside": [{"source": "G/y"}, {"source": "G/z", "focus": [0.9, 0.2]}]},
                      "items/b.png": {"source": "G/x", "overlay": {"source": "G/o"}}}
    editor.tree.selection_set("items/a.png")
    editor.update()
    assert editor.mode.get() == "beside3" and editor.beside == ["G/y", "G/z"] and editor.beside_focus[1][0].get() == 0.9
    editor.tree.selection_set("items/b.png")
    editor.update()
    assert editor.mode.get() == "overlay" and editor.overlay == "G/o"
    editor.tree.selection_set("items/c.png")
    editor.update()
    assert editor.mode.get() == "single" and editor.beside == [None, None]
