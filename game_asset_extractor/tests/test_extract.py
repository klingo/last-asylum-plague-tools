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
    n = E.extract_bundle("b1", "Grp", [("gold", solid("gold")), ("gold", solid("red")), ("gem", solid("blue"))], index, run=1, kind="pictures")
    assert n == 3
    assert sorted(index["sprites"]) == ["pictures/Grp/gem", "pictures/Grp/gold", "pictures/Grp/gold_2"]
    assert (out / "pictures" / "Grp" / "gold_2.png").is_file()
    s = index["sprites"]["pictures/Grp/gold"]
    assert (s["w"], s["h"], s["bundle"], s["added"], s["changed"]) == (8, 8, "b1", 1, None) and len(s["dhash"]) == 64


def test_extract_bundle_marks_changed_pictures_and_keeps_added(out):
    index = new_index()
    E.extract_bundle("b1", "Grp", [("gold", solid("gold")), ("gem", solid("blue"))], index, run=1, kind="pictures")
    n = E.extract_bundle("b1", "Grp", [("gold", solid("gold")), ("gem", solid("green"))], index, run=2, kind="pictures")
    assert n == 1  # only the gem differs; the gold file is not rewritten
    assert (index["sprites"]["pictures/Grp/gem"]["added"], index["sprites"]["pictures/Grp/gem"]["changed"]) == (1, 2)
    assert (index["sprites"]["pictures/Grp/gold"]["added"], index["sprites"]["pictures/Grp/gold"]["changed"]) == (1, None)


def test_extract_bundle_drops_pictures_that_left_the_bundle(out):
    index = new_index()
    E.extract_bundle("b1", "Grp", [("gold", solid("gold")), ("gem", solid("blue"))], index, run=1, kind="pictures")
    E.extract_bundle("b1", "Grp", [("gold", solid("gold"))], index, run=2, kind="pictures")
    assert list(index["sprites"]) == ["pictures/Grp/gold"]
    assert not (out / "pictures" / "Grp" / "gem.png").exists()


def test_extract_bundle_keeps_other_bundles_names_taken(out):
    index = new_index()
    E.extract_bundle("b1", "Grp", [("gold", solid("gold"))], index, run=1, kind="pictures")
    E.extract_bundle("b2", "Grp", [("gold", solid("red"))], index, run=1, kind="pictures")
    assert sorted(index["sprites"]) == ["pictures/Grp/gold", "pictures/Grp/gold_2"]
    assert index["sprites"]["pictures/Grp/gold"]["bundle"] == "b1"


def test_mark_seen_sets_the_baseline_to_the_current_run(out):
    import state as S

    index = new_index()
    index["meta"]["run"] = 3
    S.save_index(index)
    assert E.mark_seen() == 3
    assert S.load_index()["meta"]["baseline"] == 3


def test_other_types_go_into_their_own_folder_and_a_bundle_without_pictures_leaves_none(out):
    index = new_index()
    E.extract_bundle("b1", "Fx", [("glow", solid("gold"))], index, run=1, kind="effects")
    E.extract_bundle("b2", "Empty", [], index, run=1, kind="data")
    assert list(index["sprites"]) == ["effects/Fx/glow"]
    assert (index["sprites"]["effects/Fx/glow"]["group"], index["sprites"]["effects/Fx/glow"]["type"]) == ("effects/Fx", "effects")
    assert (out / "effects" / "Fx" / "glow.png").is_file() and not (out / "Empty").exists()
    E.extract_bundle("b1", "Fx", [], index, run=2, kind="effects")  # it left the bundle: its file goes too
    assert not (out / "effects" / "Fx" / "glow.png").exists()


def test_write_texts_names_files_by_their_content_and_keeps_the_folders_of_other_bundles(out):
    E.write_texts("data", "LuaScript/Sub", [("t", b"x")])
    files = [("a", b"text"), ("a", b"\xff\x00"), ("api.proto", b"syntax"), ("b c", "\u4e2d".encode()), ("A", b"1"), ("a", b"2")]
    assert E.write_texts("data", "LuaScript", files) == 6
    folder = out / "data" / "LuaScript"
    # Windows folds the case: A and a must not overwrite each other
    assert sorted(p.name for p in folder.iterdir() if p.is_file()) == ["A_2.txt", "a.bin", "a.txt", "a_3.txt", "api.proto", "b_c.txt"]
    assert (folder / "a.txt").read_bytes() == b"text" and (folder / "a.bin").read_bytes() == b"\xff\x00"
    E.write_texts("data", "LuaScript", [("n", b"1")])  # the bundle changed: its old files go, the sub-bundle's stay
    assert sorted(p.name for p in folder.iterdir()) == ["Sub", "n.txt"] and (folder / "Sub" / "t.txt").is_file()


def test_a_run_that_wrote_texts_records_them_under_its_run_number(out, monkeypatch, tmp_path):
    import state as S
    import texts as T

    monkeypatch.setattr(C, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(C, "STATE", tmp_path / "state")
    C.CACHE.mkdir()
    (C.CACHE / "b1").write_bytes(b"bundle")
    S.save("pulled.json", {"b1": {"md5": "m", "path": "GameData/language_F/en"}})
    monkeypatch.setattr(E, "export_texts", lambda path: [("Item", b"KEY,Chinese\ngold,Gold\n")])
    runs = []
    monkeypatch.setattr(T, "update_index", lambda run: runs.append(run))
    assert E.run()["texts"] == 1
    assert runs == [1] and (out / "data" / "GameData" / "language_F" / "en" / "Item.txt").is_file()
    assert E.run()["bundles"] == 0 and runs == [1]  # nothing new: no new run, nothing to record
