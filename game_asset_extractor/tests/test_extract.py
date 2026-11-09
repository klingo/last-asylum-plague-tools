import pytest
from PIL import Image

import config as C
import extract as E


def atlas(width=40, height=30):
    """Four coloured 10x10 squares: red top left, green top right, blue bottom left, yellow bottom right."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for (x, y), colour in {(0, 0): "red", (10, 0): "lime", (0, 10): "blue", (10, 10): "yellow"}.items():
        img.paste(Image.new("RGBA", (10, 10), colour), (x, y))
    return img


def test_crop_ngui_counts_y_from_the_top():
    img = atlas()
    assert E.crop_ngui(img, {"x": 0, "y": 0, "width": 10, "height": 10}).getpixel((5, 5)) == (255, 0, 0, 255)
    assert E.crop_ngui(img, {"x": 10, "y": 10, "width": 10, "height": 10}).getpixel((5, 5)) == (255, 255, 0, 255)


def test_crop_ngui_puts_a_trimmed_sprite_back_into_its_full_box():
    sprite = {"x": 0, "y": 0, "width": 10, "height": 10, "paddingLeft": 2, "paddingRight": 3, "paddingTop": 4, "paddingBottom": 1}
    out = E.crop_ngui(atlas(), sprite)
    assert out.size == (15, 15)
    assert out.getpixel((0, 0))[3] == 0  # padding is transparent
    assert out.getpixel((2, 4)) == (255, 0, 0, 255)


def test_crop_ngui_skips_empty_sprites():
    assert E.crop_ngui(atlas(), {"x": 0, "y": 0, "width": 0, "height": 10}) is None


@pytest.mark.parametrize("raw,expected", [("icon_gold", "icon_gold"), ("a b/c:d", "a_b_c_d"), ("..", "unnamed"), ("Icon.v2", "Icon.v2")])
def test_safe_name(raw, expected):
    assert E.safe_name(raw) == expected


@pytest.fixture
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path / "out")
    return C.OUT


def new_index():
    return {"meta": {"run": 0, "runs": {}}, "sprites": {}}


def solid(colour, size=(8, 8)):
    return Image.new("RGBA", size, colour)


def test_extract_bundle_writes_pngs_and_numbers_name_collisions(out):
    index = new_index()
    n = E.extract_bundle("b1", "Grp", [("gold", solid("gold")), ("gold", solid("red")), ("gem", solid("blue"))], index, run=1)
    assert n == 3
    assert sorted(index["sprites"]) == ["Grp/gem", "Grp/gold", "Grp/gold_2"]
    assert (out / "Grp" / "gold_2.png").is_file()
    s = index["sprites"]["Grp/gold"]
    assert (s["w"], s["h"], s["bundle"], s["added"], s["changed"]) == (8, 8, "b1", 1, None) and len(s["dhash"]) == 64


def test_extract_bundle_marks_changed_pictures_and_keeps_added(out):
    index = new_index()
    E.extract_bundle("b1", "Grp", [("gold", solid("gold")), ("gem", solid("blue"))], index, run=1)
    n = E.extract_bundle("b1", "Grp", [("gold", solid("gold")), ("gem", solid("green"))], index, run=2)
    assert n == 1  # only the gem differs; the gold file is not rewritten
    assert (index["sprites"]["Grp/gem"]["added"], index["sprites"]["Grp/gem"]["changed"]) == (1, 2)
    assert (index["sprites"]["Grp/gold"]["added"], index["sprites"]["Grp/gold"]["changed"]) == (1, None)


def test_extract_bundle_drops_pictures_that_left_the_bundle(out):
    index = new_index()
    E.extract_bundle("b1", "Grp", [("gold", solid("gold")), ("gem", solid("blue"))], index, run=1)
    E.extract_bundle("b1", "Grp", [("gold", solid("gold"))], index, run=2)
    assert list(index["sprites"]) == ["Grp/gold"]
    assert not (out / "Grp" / "gem.png").exists()


def test_extract_bundle_keeps_other_bundles_names_taken(out):
    index = new_index()
    E.extract_bundle("b1", "Grp", [("gold", solid("gold"))], index, run=1)
    E.extract_bundle("b2", "Grp", [("gold", solid("red"))], index, run=1)
    assert sorted(index["sprites"]) == ["Grp/gold", "Grp/gold_2"]
    assert index["sprites"]["Grp/gold"]["bundle"] == "b1"


def test_mark_seen_sets_the_baseline_to_the_current_run(out):
    import state as S

    index = new_index()
    index["meta"]["run"] = 3
    S.save_index(index)
    assert E.mark_seen() == 3
    assert S.load_index()["meta"]["baseline"] == 3
