import io

from PIL import Image

import render as R


def bands(width, height, vertical=True):
    """Red | green | blue bands (left to right, or top to bottom)."""
    img = Image.new("RGBA", (width, height))
    n = 3
    for i, colour in enumerate(("red", "lime", "blue")):
        box = (0, i * height // n, width, (i + 1) * height // n) if vertical else (i * width // n, 0, (i + 1) * width // n, height)
        img.paste(Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), colour), box)
    return img


def test_a_picture_of_the_right_size_is_untouched():
    img = Image.new("RGBA", (144, 144), "gold")
    out, note = R.fit(img, (144, 144))
    assert out is img and note == "144x144, as it is"


def test_a_picture_without_a_fixed_size_stays_as_it_is():
    img = Image.new("RGBA", (240, 200))
    assert R.fit(img, None) == (img, "240x200, as it is")


def test_same_aspect_is_only_resized_and_a_near_aspect_too():
    assert R.fit(Image.new("RGBA", (1440, 720)), (720, 360))[1] == "resized to 720x360"
    out, note = R.fit(Image.new("RGBA", (706, 360)), (720, 360))  # 2 % off: stretched, not cropped, and not worth a warning
    assert out.size == (720, 360) and note == "resized to 720x360"


def test_a_tall_picture_is_cropped_to_the_aspect_by_focus_top_by_default():
    tall = bands(100, 600)  # 1:6; the 2:1 window is 100x50 of it
    top, note = R.fit(tall, (100, 50))
    assert top.getpixel((50, 25)) == (255, 0, 0, 255) and note.startswith("cropped 100x600 to 100:50")
    bottom, _ = R.fit(tall, (100, 50), focus=(0.5, 1.0))
    assert bottom.getpixel((50, 25)) == (0, 0, 255, 255)
    middle, _ = R.fit(tall, (100, 50), focus=(0.5, 0.5))
    assert middle.getpixel((50, 25)) == (0, 255, 0, 255)


def test_a_wide_picture_is_cropped_at_the_sides_centred_by_default():
    wide = bands(600, 100, vertical=False)
    out, _ = R.fit(wide, (100, 100))
    assert out.getpixel((50, 50)) == (0, 255, 0, 255)
    left, _ = R.fit(wide, (100, 100), focus=(0.0, 0.0))
    assert left.getpixel((50, 50)) == (255, 0, 0, 255)


def test_focus_is_clamped():
    out, _ = R.fit(bands(100, 600), (100, 50), focus=(5, 9))
    assert out.getpixel((50, 25)) == (0, 0, 255, 255)


def test_only_a_real_enlargement_warns():
    assert "WARNING: enlarged from 102x102" in R.fit(Image.new("RGBA", (102, 102)), (144, 144))[1]
    assert "WARNING" not in R.fit(Image.new("RGBA", (135, 135)), (144, 144))[1]  # 7 %: fine


def test_target_size_and_default_extension_follow_the_folder():
    assert R.target_size("items/chest/gold.png") == (144, 144)
    assert R.target_size("heroes/sr_x.png") == (144, 144)
    assert R.target_size("events/x.webp") == (720, 360)
    assert R.target_size("lord/x.png") is None
    assert R.target_size("packages/x.webp") is None  # a pack picture keeps the game's size
    assert R.default_extension("events") == ".webp" and R.default_extension("items") == ".png"
    assert R.default_extension("packages") == ".webp"


def test_encode_makes_webp_or_png_by_the_extension_and_keeps_transparency():
    img = Image.new("RGBA", (40, 20), (255, 0, 0, 0))
    webp = Image.open(io.BytesIO(R.encode(img, "events/x.webp")))
    png = Image.open(io.BytesIO(R.encode(img, "items/x.png")))
    assert (webp.format, png.format) == ("WEBP", "PNG")
    assert webp.convert("RGBA").getpixel((0, 0))[3] == 0 and png.convert("RGBA").getpixel((0, 0))[3] == 0


def test_render_reads_a_picture_and_returns_the_file_bytes(tmp_path):
    source = tmp_path / "poster.png"
    bands(200, 800).save(source)
    data, note = R.render(source, "events/new.webp")
    img = Image.open(io.BytesIO(data))
    assert img.format == "WEBP" and img.size == (720, 360) and "cropped 200x800 to 720:360" in note


def test_keeps_size_only_for_event_pictures_close_to_2_to_1():
    assert R.keeps_size("events/x.webp", (726, 346)) and R.keeps_size("events/x.webp", (706, 360))
    assert R.keeps_size("events/x.webp", (1440, 720))
    assert not R.keeps_size("events/x.webp", (706, 1416))  # a portrait poster
    assert not R.keeps_size("events/x.webp", (500, 500))
    assert not R.keeps_size("items/x.png", (726, 346))


def test_render_keeps_a_near_2_to_1_banner_and_force_size_makes_it_720_by_360(tmp_path):
    source = tmp_path / "banner.png"
    bands(726, 346, vertical=False).save(source)
    kept, note = R.render(source, "events/b.webp")
    assert Image.open(io.BytesIO(kept)).size == (726, 346) and note == "726x346, the game's size kept"
    forced, note = R.render(source, "events/b.webp", force_size=True)
    assert Image.open(io.BytesIO(forced)).size == (720, 360) and "cropped 726x346 to 720:360" in note


def test_render_still_crops_a_portrait_for_events(tmp_path):
    source = tmp_path / "poster.png"
    bands(706, 1416).save(source)
    data, note = R.render(source, "events/p.webp")
    assert Image.open(io.BytesIO(data)).size == (720, 360) and "cropped 706x1416 to 720:360" in note


def test_same_pixels_ignores_the_encoder(tmp_path):
    img = bands(30, 30)
    plain = tmp_path / "a.png"
    img.save(plain, optimize=False)
    assert R.same_pixels(R.encode(img, "items/a.png"), plain)
    other = tmp_path / "b.png"
    Image.new("RGBA", (30, 30), "white").save(other)
    assert not R.same_pixels(R.encode(img, "items/a.png"), other)
    assert not R.same_pixels(R.encode(img, "items/a.png"), tmp_path / "missing.png")


def test_an_overlay_goes_on_top_scaled_to_a_fraction_of_the_height_and_centred_where_asked(tmp_path):
    base = tmp_path / "bg.png"
    Image.new("RGBA", (720, 360), "blue").save(base)
    top = tmp_path / "trophy.png"
    Image.new("RGBA", (100, 100), "red").save(top)
    data, note = R.render(base, "events/e.webp", overlay={"path": top, "scale": 0.5, "at": [0.25, 0.5]})
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    assert img.size == (720, 360) and note.endswith(", trophy on top")
    assert img.getpixel((180, 180))[:3][0] > 200  # the middle of the 180x180 square, red
    assert img.getpixel((180 + 91, 180))[2] > 200 and img.getpixel((180, 180 + 91))[2] > 200  # just outside it, still the blue background


def test_an_overlay_keeps_the_transparency_of_the_picture_on_top(tmp_path):
    base = tmp_path / "bg.png"
    Image.new("RGBA", (720, 360), "blue").save(base)
    top = tmp_path / "ring.png"
    ring = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    ring.paste(Image.new("RGBA", (20, 100), "red"), (0, 0))
    ring.save(top)
    img = Image.open(io.BytesIO(R.render(base, "events/e.webp", overlay={"path": top, "scale": 1, "at": [0.5, 0.5]})[0])).convert("RGBA")
    assert img.getpixel((200, 180))[0] > 200 and img.getpixel((400, 180))[2] > 200  # red edge on top, background shows elsewhere


def test_load_rgba_decodes_once_until_the_file_changes(tmp_path):
    path = tmp_path / "a.png"
    Image.new("RGB", (4, 4), (255, 0, 0)).save(path)
    first = R.load_rgba(path)
    assert R.load_rgba(path) is first and first.mode == "RGBA"
    Image.new("RGB", (6, 6), (0, 0, 255)).save(path)
    assert R.load_rgba(path).size == (6, 6)


def test_make_is_what_render_encodes(tmp_path):
    path = tmp_path / "a.png"
    Image.new("RGB", (300, 100), (10, 20, 30)).save(path)
    img, note = R.make(path, "items/x.png", (0.5, 0.5))
    data, same_note = R.render(path, "items/x.png", (0.5, 0.5))
    assert img.size == (144, 144) and note == same_note
    assert Image.open(io.BytesIO(data)).convert("RGBA").tobytes() == img.tobytes()


def three_pictures(tmp_path, size=(300, 300)):
    paths = []
    for name, colour in (("a", "red"), ("b", "lime"), ("c", "blue")):
        paths.append(tmp_path / f"{name}.png")
        Image.new("RGBA", size, colour).save(paths[-1])
    return paths


def test_two_pictures_side_by_side_fill_one_half_each(tmp_path):
    a, b, _ = three_pictures(tmp_path, (1440, 720))
    img, note = R.make(a, "events/e.webp", force_size=True, beside=[{"path": b}])
    assert img.size == (720, 360) and note == "720x360, 2 side by side"
    assert img.getpixel((359, 180))[0] > 200 and img.getpixel((360, 180))[1] > 200  # red | green, edge at the middle


def test_three_pictures_side_by_side_fill_a_third_each(tmp_path):
    a, b, c = three_pictures(tmp_path, (1440, 720))
    img, note = R.make(a, "events/e.webp", force_size=True, beside=[{"path": b}, {"path": c}])
    assert img.size == (720, 360) and note.endswith("3 side by side")
    assert [img.getpixel((x, 180))[:3] for x in (0, 239, 240, 479, 480, 719)] == [
        (255, 0, 0), (255, 0, 0), (0, 255, 0), (0, 255, 0), (0, 0, 255), (0, 0, 255)]


def test_side_by_side_takes_its_size_from_the_first_picture(tmp_path):
    a, b, _ = three_pictures(tmp_path, (726, 346))
    assert R.make(a, "events/e.webp", beside=[{"path": b}])[0].size == (726, 346)  # a banner keeps the game's size
    assert R.make(a, "events/e.webp", force_size=True, beside=[{"path": b}])[0].size == (720, 360)
    assert R.make(a, "items/i.png", beside=[{"path": b}])[0].size == (144, 144)
    assert R.make(a, "packages/p.webp", beside=[{"path": b}])[0].size == (726, 346)  # a folder without a size: the first picture's


def test_each_side_by_side_picture_is_cropped_by_its_own_focus(tmp_path):
    left, right = tmp_path / "l.png", tmp_path / "r.png"
    bands(300, 100, vertical=False).save(left)  # red | green | blue, a 3:1 picture for a 1:2 column
    bands(300, 100, vertical=False).save(right)
    img, _ = R.make(left, "items/i.png", (0.0, 0.0), beside=[{"path": right, "focus": (1.0, 0.0)}])
    assert img.getpixel((10, 70))[0] > 200  # the left half shows the left part of its picture: red
    assert img.getpixel((130, 70))[2] > 200  # the right half the right part of its: blue


def test_side_by_side_calls_out_an_enlarged_picture(tmp_path):
    a, b, _ = three_pictures(tmp_path, (1440, 720))
    small = tmp_path / "small.png"
    Image.new("RGBA", (50, 100), "lime").save(small)
    assert "picture 2 WARNING: enlarged from 50x50" in R.make(a, "events/e.webp", beside=[{"path": small}])[1]
    assert "WARNING" not in R.make(a, "events/e.webp", beside=[{"path": b}])[1]


def test_an_overlay_goes_on_top_of_side_by_side_pictures(tmp_path):
    a, b, c = three_pictures(tmp_path, (1440, 720))
    img, note = R.make(a, "events/e.webp", overlay={"path": c, "scale": 0.5, "at": [0.5, 0.5]}, beside=[{"path": b}])
    assert note.endswith("c on top") and img.getpixel((720, 360))[2] > 200 and img.getpixel((10, 10))[0] > 200
