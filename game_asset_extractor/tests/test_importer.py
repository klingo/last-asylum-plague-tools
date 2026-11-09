import pytest
from PIL import Image

import importer as I
import mapping as Mp


@pytest.fixture
def world(tmp_path):
    out, assets = tmp_path / "out", tmp_path / "assets"
    (out / "Grp").mkdir(parents=True)
    assets.mkdir()
    index = {"sprites": {"Grp/coin": {"id": "Grp/coin", "md5": "md5-coin"}}}
    return {"out": out, "assets": assets, "index": index, "mapping_path": tmp_path / "mapping.json"}


def sprite(world, name, size, colour="gold"):
    Image.new("RGBA", size, colour).save(world["out"] / "Grp" / f"{name}.png")


def do(world, sprite_id, dest, **kw):
    return I.import_picture(sprite_id, dest, out=world["out"], assets=world["assets"], index=world["index"],
                            mapping_path=world["mapping_path"], **kw)


def test_items_are_resized_to_144_png_and_the_import_is_mapped(world):
    sprite(world, "coin", (240, 240))
    target, note = do(world, "Grp/coin", "items/material/coin")
    assert target == world["assets"] / "items" / "material" / "coin.png"
    assert Image.open(target).size == (144, 144) and note == "resized to 144x144"
    assert Mp.load(world["mapping_path"]) == {"items/material/coin.png": {"source": "Grp/coin", "synced": "md5-coin"}}


def test_events_become_webp_and_a_near_2_to_1_banner_keeps_the_game_size(world):
    sprite(world, "banner", (726, 346))
    target, note = do(world, "Grp/banner", "events/new")
    assert target.name == "new.webp" and Image.open(target).format == "WEBP" and Image.open(target).size == (726, 346)
    assert note == "726x346, the game's size kept"
    assert Mp.load(world["mapping_path"])["events/new.webp"] == {"source": "Grp/banner"}  # no "resize": the rule applies


def test_resize_makes_a_near_2_to_1_banner_720_by_360_and_is_remembered(world):
    sprite(world, "banner", (726, 346))
    target, note = do(world, "Grp/banner", "events/new", resize=True)
    assert Image.open(target).size == (720, 360) and "cropped 726x346 to 720:360" in note
    assert Mp.load(world["mapping_path"])["events/new.webp"]["resize"] is True


def test_a_pack_picture_becomes_webp_at_the_game_size(world):
    sprite(world, "pack", (320, 240))
    target, note = do(world, "Grp/pack", "packages/awakening_special_pack")
    assert target == world["assets"] / "packages" / "awakening_special_pack.webp"
    assert Image.open(target).format == "WEBP" and Image.open(target).size == (320, 240)
    assert note == "320x240, as it is"
    assert "packages/awakening_special_pack.webp" in Mp.load(world["mapping_path"])


def test_resize_changes_nothing_outside_events(world):
    sprite(world, "coin", (240, 240))
    target, _ = do(world, "Grp/coin", "items/coin", resize=True)
    assert Image.open(target).size == (144, 144)


def test_a_tall_poster_is_cropped_not_stretched_and_the_focus_is_remembered(world):
    sprite(world, "poster", (706, 1416), "red")
    target, note = do(world, "Grp/poster", "events/boss.webp", focus=(0.5, 0.2))
    assert Image.open(target).size == (720, 360) and "cropped 706x1416 to 720:360" in note
    assert Mp.load(world["mapping_path"])["events/boss.webp"]["focus"] == [0.5, 0.2]


def test_other_folders_keep_the_size(world):
    sprite(world, "coin", (240, 200))
    target, _ = do(world, "Grp/coin", "ui/coin")
    assert Image.open(target).size == (240, 200)


def test_an_existing_file_is_only_replaced_with_force(world):
    sprite(world, "coin", (144, 144))
    do(world, "Grp/coin", "items/coin")
    with pytest.raises(FileExistsError):
        do(world, "Grp/coin", "items/coin")
    do(world, "Grp/coin", "items/coin", force=True)


@pytest.mark.parametrize("dest", ["../outside", "items/../../x", "/abs/path", "just_a_name"])
def test_destinations_outside_a_folder_of_the_assets_are_refused(world, dest):
    sprite(world, "coin", (144, 144))
    with pytest.raises(ValueError):
        do(world, "Grp/coin", dest)


def test_an_unknown_id_is_reported(world):
    with pytest.raises(FileNotFoundError):
        do(world, "Grp/missing", "items/x")


def test_swapped_fields_are_called_out(world):
    sprite(world, "coin", (144, 144))
    with pytest.raises(FileNotFoundError, match=r"Grp/coin is one: the two look swapped"):
        do(world, "packages/enhancement_special_pack", "Grp/coin")
    with pytest.raises(FileNotFoundError) as plain:  # a plain typo gets no such hint
        do(world, "Grp/typo", "items/x")
    assert "swapped" not in str(plain.value)
