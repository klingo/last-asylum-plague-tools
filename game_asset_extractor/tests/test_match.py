import numpy as np
from PIL import Image, ImageDraw

import match as M


def picture(kind: str, size=144, shade=0) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 144
    if kind == "circle":
        d.ellipse([20 * s, 20 * s, 120 * s, 120 * s], fill=(200 + shade, 160, 40, 255))
    elif kind == "bar":
        d.rectangle([10 * s, 60 * s, 130 * s, 90 * s], fill=(60, 120 + shade, 200, 255))
    else:
        d.polygon([(72 * s, 8 * s), (136 * s, 130 * s), (8 * s, 130 * s)], fill=(30, 200, 90 + shade, 255))
    return img


def test_dhash_is_256_bits_and_identical_pictures_have_distance_zero():
    h = M.dhash(picture("circle"))
    assert len(h) == 64
    assert M.distances(h, np.array([np.frombuffer(bytes.fromhex(h), dtype=np.uint8)]))[0] == 0


def test_resized_or_slightly_recoloured_pictures_stay_close_and_other_pictures_far():
    base = np.array([np.frombuffer(bytes.fromhex(M.dhash(picture("circle"))), dtype=np.uint8)])
    assert M.distances(M.dhash(picture("circle", size=100)), base)[0] <= M.CLOSE
    assert M.distances(M.dhash(picture("circle", shade=30)), base)[0] <= M.CLOSE
    assert M.distances(M.dhash(picture("bar")), base)[0] > M.CLOSE
    assert M.distances(M.dhash(picture("triangle")), base)[0] > M.CLOSE


def test_closest_orders_candidates_by_distance():
    kinds = ["bar", "circle", "triangle"]
    ids = [f"G/{k}" for k in kinds]
    hashes = np.array([np.frombuffer(bytes.fromhex(M.dhash(picture(k))), dtype=np.uint8) for k in kinds])
    found = M.closest(M.dhash(picture("circle", size=120)), ids, hashes, top=2)
    assert found[0]["id"] == "G/circle" and len(found) == 2
    assert found[0]["dist"] <= found[1]["dist"]


def test_match_lists_the_closest_sprites_per_webapp_image(tmp_path):
    assets = tmp_path / "assets"
    (assets / "items" / "chest").mkdir(parents=True)
    picture("circle", size=144).save(assets / "items" / "chest" / "coin.png")
    index = {"sprites": {f"G/{k}": {"id": f"G/{k}", "dhash": M.dhash(picture(k))} for k in ("bar", "circle", "triangle")}}
    found = M.match(index, assets)
    assert list(found) == ["items/chest/coin.png"]
    assert found["items/chest/coin.png"][0] == {"id": "G/circle", "dist": 0}


def test_match_without_sprites_is_empty(tmp_path):
    assert M.match({"sprites": {}}, tmp_path) == {}


def test_the_webapp_assets_folder_is_required_and_named_in_the_error(tmp_path):
    import config as C
    import pytest

    with pytest.raises(FileNotFoundError, match="LAST_ASYLUM_WEBAPP"):
        C.require_webapp(tmp_path / "missing")
    with pytest.raises(FileNotFoundError):
        M.webapp_images(tmp_path / "missing")  # no empty list: nothing may be written next to a wrong folder
    assert C.require_webapp(tmp_path) == tmp_path
