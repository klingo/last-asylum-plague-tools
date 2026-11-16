import pytest

import text_mapping as TM
import text_mapping_gui as TG

EN = {"tables/Item:gold.name": "Gold", "tables/Item:chest.name": "Raven Chest", "tables/Item:sword.name": "Sword of Dawn"}
DE = {"tables/Item:gold.name": "Gold", "tables/Item:chest.name": "Raben-Truhe", "tables/Item:sword.name": "Schwert der Morgenröte"}
TEXTS = {
    "pack_data:items.gold.name": {"en": "Gold", "de": ""},
    "pack_data:items.chest.name": {"en": "Raven Chest", "de": "Raben-Truhe"},
    "pack_data:items.sword.name": {"en": "Sword of Dawm", "de": ""},
    "pack_data:items.own.name": {"en": "Our own", "de": ""},
    "pack_data:packages.halloween_ball_mystery_shop_lv5_raven_gear_chest_bundle.name": {"en": "Long " * 40, "de": ""},
}


@pytest.fixture
def editor(root, monkeypatch, tmp_path):
    saved = tmp_path / "text_mapping.json"
    for name in ("set_entry", "clear", "accept_suggestions"):  # every change goes to a scratch file, never the real mapping
        original = getattr(TM, name)
        monkeypatch.setattr(TM, name, lambda *a, _o=original, **k: _o(*a, **k, path=saved))
    load = TM.load
    monkeypatch.setattr(TM, "load", lambda path=None: load(saved))

    reloads = []

    def reload(self):
        reloads.append(1)
        self.game = TM.Game({"en": EN, "de": DE})
        self.texts, self.langs, self.mapping = TEXTS, ["en", "de"], TM.load(saved)
        self.table = TM.rows(self.mapping, self.texts, self.game, self.langs)

    monkeypatch.setattr(TG.Editor, "reload", reload)
    ed = TG.Editor(root)
    ed.reloads = reloads
    root.update()
    yield ed
    ed.destroy()


def widgets(parent):
    for child in parent.winfo_children():
        yield child
        yield from widgets(child)


def box_text(box):
    return box.get("1.0", "end").strip()


def test_the_list_shows_every_text_with_its_status(editor):
    rows = {iid: editor.tree.set(iid, "status") for iid in editor.tree.get_children()}
    assert rows["pack_data:items.gold.name"] == "suggested" and rows["pack_data:items.sword.name"] == "near"
    assert rows["pack_data:items.own.name"] == "unmapped" and len(rows) == 5
    editor.filter.set("near")
    editor.fill()
    assert editor.tree.get_children() == ("pack_data:items.sword.name",)


def test_a_selection_shows_the_webapp_text_next_to_what_the_game_says_and_the_candidates(editor):
    editor.tree.selection_set("pack_data:items.sword.name")
    editor.update()
    assert editor.cand_ids == ["tables/Item:sword.name"] and "92%" in editor.cands.get(0)
    assert box_text(editor.boxes["en"][0]) == "Sword of Dawm" and box_text(editor.boxes["en"][1]) == "Sword of Dawn"
    assert box_text(editor.boxes["de"][1]) == "Schwert der Morgenröte"
    assert str(editor.boxes["en"][1].cget("background")) == TG.DIFFERS  # what Sync would change is marked
    editor.tree.selection_set("pack_data:items.chest.name")
    editor.update()
    assert str(editor.boxes["de"][1].cget("background")) == TG.SAME


def test_use_own_text_and_clear_write_the_mapping(editor):
    editor.tree.selection_set("pack_data:items.sword.name")
    editor.update()
    editor.use()
    assert editor.mapping["pack_data:items.sword.name"] == {"source": "tables/Item:sword.name"}
    assert editor.tree.set("pack_data:items.sword.name", "status") == "to sync"
    editor.tree.selection_set("pack_data:items.own.name")
    editor.update()
    editor.own_text()
    assert editor.mapping["pack_data:items.own.name"] == {"source": None}
    editor.clear()
    assert "pack_data:items.own.name" not in editor.mapping


def test_map_all_suggested_takes_only_the_clear_ones(editor):
    editor.accept_all()
    assert sorted(editor.mapping) == ["pack_data:items.chest.name", "pack_data:items.gold.name"]


def test_a_search_finds_game_texts_in_any_language(editor):
    editor.search.set("morgen")
    assert editor.result_ids == ["tables/Item:sword.name"] and editor.results.size() == 1


def test_no_button_takes_the_keyboard_from_the_list(editor):
    clickable = [w for w in widgets(editor) if w.winfo_class() == "TButton"]
    assert len(clickable) == 4 and [w for w in clickable if str(w.cget("takefocus")) != "0"] == []


def test_a_heading_click_sorts_the_list_and_a_second_one_turns_it_round(editor):
    editor.sort_by("#0")
    assert editor.tree.get_children()[0] == "pack_data:items.chest.name"
    editor.sort_by("#0")
    assert editor.tree.get_children()[0].startswith("pack_data:packages.")
    assert editor.tree.heading("#0", "text").startswith("Webapp text")


def test_the_window_opens_wide_enough_for_both_text_boxes(editor):
    editor.update()
    window_right = editor.winfo_rootx() + editor.winfo_width()
    boxes = [box for pair in editor.boxes.values() for box in pair]
    assert [b for b in boxes if b.winfo_rootx() + b.winfo_width() > window_right] == []


def test_moving_through_the_list_moves_nothing_but_the_text_of_the_two_labels(editor):
    """A long location or text once widened the right panel, so the list shrank and everything jumped."""
    def walk(widget):
        for child in widget.winfo_children():
            yield child
            yield from walk(child)

    def layout():
        editor.update()
        return {str(w): (w.winfo_x(), w.winfo_y(), w.winfo_width(), w.winfo_height()) for w in walk(editor)
                if w.winfo_class() != "Label"} | {"window": (editor.winfo_width(), editor.winfo_height())}  # the labels' own text boxes vary

    first = None
    for row in editor.tree.get_children():
        editor.tree.selection_set(row)
        first = first or layout()
        assert layout() == first, row


def test_a_row_that_leaves_the_filtered_list_hands_the_selection_to_the_next_one(editor):
    """With the list filtered to "suggested", mapping a text removes it: up / down must go on from the next row."""
    editor.filter.set("suggested")
    editor.fill()
    first, second = editor.tree.get_children()[:2]
    editor.tree.selection_set(first)
    editor.update()
    editor.use()
    editor.update()
    assert first not in editor.tree.get_children()
    assert editor.tree.selection() == (second,) and editor.tree.focus() == second


def test_the_last_row_hands_the_selection_to_the_previous_one(editor):
    editor.filter.set("suggested")
    editor.fill()
    first, last = editor.tree.get_children()[:2]
    editor.tree.selection_set(last)
    editor.update()
    editor.use()
    editor.update()
    assert editor.tree.get_children() == (first,) and editor.tree.selection() == (first,) and editor.tree.focus() == first


def test_mapping_one_text_redoes_only_its_row_and_tells_the_window_the_new_count(editor):
    told = []
    editor.on_change = told.append
    reloads = len(editor.reloads)
    editor.tree.selection_set("pack_data:items.gold.name")
    editor.update()
    editor.use()
    editor.update()
    assert len(editor.reloads) == reloads  # nothing was read or matched again
    assert editor.tree.set("pack_data:items.gold.name", "status") == "to sync" and "Official 0 of 5" in told[-1] and "to sync 1" in told[-1]
    assert editor.heading.get().endswith("[to sync]")  # the selected row's heading follows
    editor.clear()
    assert editor.tree.set("pack_data:items.gold.name", "status") == "suggested" and "suggested 2" in told[-1]
    editor.accept_all()  # several texts: everything is read again
    assert len(editor.reloads) == reloads + 1 and "Official 1 of 5" in told[-1] and "to sync 1" in told[-1]


def test_the_template_field_shows_the_game_text_and_previews_what_it_says(editor):
    editor.tree.selection_set("pack_data:items.sword.name")
    editor.update()
    assert editor.template.get() == "tables/Item:sword.name"
    editor.template.set("[[tables/Item:chest.name]]")
    assert editor.parts == [{"source": "tables/Item:chest.name"}] and box_text(editor.boxes["de"][1]) == "Raben-Truhe"
    editor.template.set("[[tables/Item:chest.name")
    assert editor.parts is None and "not closed" in editor.note.get() and box_text(editor.boxes["de"][1]) == "(no game text)"
    editor.use()  # nothing valid to map
    assert "pack_data:items.sword.name" not in editor.mapping
    editor.template.set("[[tables/Item:gone]]")
    assert editor.parts is None and "not in the game" in editor.note.get()


def test_use_maps_what_the_template_says_with_its_fill(editor):
    editor.tree.selection_set("pack_data:items.own.name")
    editor.update()
    editor.template.set("[[tables/Item:sword.name|0=3]] 5")
    editor.use()
    assert editor.mapping["pack_data:items.own.name"] == {"parts": [{"source": "tables/Item:sword.name", "fill": {"0": "3"}}, " 5"]}
    assert editor.tree.set("pack_data:items.own.name", "status") == "to sync"


def test_compose_adds_a_clicked_text_to_the_template_else_it_replaces_it(editor):
    editor.tree.selection_set("pack_data:items.sword.name")
    editor.update()
    editor.search.set("morgen")
    editor.results.selection_set(0)
    editor.compose.set(True)
    editor.pick(editor.results, editor.result_ids)  # the id on its own becomes the first part
    assert editor.template.get() == "[[tables/Item:sword.name]][[tables/Item:sword.name]]"
    editor.compose.set(False)
    editor.pick(editor.results, editor.result_ids)
    assert editor.template.get() == "tables/Item:sword.name"


def test_the_window_hints_at_templates_under_the_field(editor):
    assert [w for w in widgets(editor) if w.winfo_class() == "Label" and w.cget("text") == TG.HINT]
