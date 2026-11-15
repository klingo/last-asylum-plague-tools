import json

import pytest

import tags as Tg

KNOWN = {"A/gold", "A/key", "B/hero"}


def test_normalize_lowercases_and_collapses_spaces():
    assert Tg.normalize("  Treasure   BOX ") == "treasure box" and Tg.normalize("   ") == ""


def test_save_sorts_and_leaves_out_the_pictures_that_have_nothing(tmp_path):
    path = tmp_path / "tags.json"
    Tg.save({"B/x": ["b", "a", "a"], "A/y": [], "A/z": ["q"]}, path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"A/z": ["q"], "B/x": ["a", "b"]}
    assert Tg.load(tmp_path / "missing.json") == {}


def test_apply_adds_and_removes_on_every_picture_and_saves(tmp_path):
    path = tmp_path / "tags.json"
    assert Tg.apply(["A/gold", "A/key"], [" Shiny ", "gold"], [], KNOWN, path) == {"A/gold": ["gold", "shiny"], "A/key": ["gold", "shiny"]}
    assert Tg.apply(["A/gold"], ["coin"], ["shiny", "unheard of", "  "], KNOWN, path) == {"A/gold": ["coin", "gold"]}  # a tag nobody has is nothing
    assert json.loads(path.read_text(encoding="utf-8")) == {"A/gold": ["coin", "gold"], "A/key": ["gold", "shiny"]}


def test_apply_with_nothing_left_drops_the_picture(tmp_path):
    path = tmp_path / "tags.json"
    Tg.apply(["A/key"], ["x"], [], KNOWN, path)
    assert Tg.apply(["A/key"], [], ["x"], KNOWN, path) == {"A/key": []}
    assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_a_tags_file_that_cannot_be_read_is_an_error_and_is_never_saved_over(tmp_path):
    path = tmp_path / "tags.json"
    path.write_text("{ not json", encoding="utf-8")  # a merge conflict, a half-edited file
    with pytest.raises(ValueError, match="not valid JSON"):
        Tg.load(path)
    with pytest.raises(ValueError, match="not valid JSON"):
        Tg.apply(["A/gold"], ["x"], [], KNOWN, path)
    assert path.read_text(encoding="utf-8") == "{ not json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="not a tags file"):
        Tg.load(path)


def test_apply_refuses_an_unknown_picture_and_saves_nothing(tmp_path):
    path = tmp_path / "tags.json"
    with pytest.raises(ValueError, match="unknown picture: Z/none"):
        Tg.apply(["A/gold", "Z/none"], ["x"], [], KNOWN, path)
    assert not path.exists()
