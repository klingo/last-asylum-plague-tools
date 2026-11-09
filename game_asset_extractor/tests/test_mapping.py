import pytest
from PIL import Image

import mapping as Mp
import match as M
import render as R


@pytest.fixture
def world(tmp_path):
    """A tiny webapp assets folder, extracted pictures and a mapping file."""
    assets, out = tmp_path / "assets", tmp_path / "out"
    (assets / "items").mkdir(parents=True)
    (assets / "events").mkdir()
    (out / "G").mkdir(parents=True)

    def picture(name, colour, size=(144, 144)):
        Image.new("RGBA", size, colour).save(out / "G" / f"{name}.png")

    picture("gold", "gold")
    picture("red", "red")
    picture("banner", "blue", (1440, 720))
    Image.new("RGBA", (144, 144), "gold").save(assets / "items" / "gold.png")  # already what the game has
    Image.new("RGBA", (144, 144), "gray").save(assets / "items" / "screenshot.png")
    Image.new("RGBA", (144, 144), "pink").save(assets / "items" / "lonely.png")
    Image.new("RGB", (720, 360), "white").save(assets / "events" / "x.webp")
    index = {"sprites": {f"G/{n}": {"id": f"G/{n}", "md5": f"md5-{n}"} for n in ("gold", "red", "banner")}}
    return {"assets": assets, "out": out, "index": index, "path": tmp_path / "mapping.json"}


def test_load_of_a_missing_file_is_empty_and_save_sorts_the_keys(world):
    assert Mp.load(world["path"]) == {}
    Mp.save({"b.png": {"source": None}, "a.png": {"source": "G/x"}}, world["path"])
    assert list(Mp.load(world["path"])) == ["a.png", "b.png"]


def test_status_of_covers_every_state(world):
    sprites, assets = world["index"]["sprites"], world["assets"]
    matches = {"items/screenshot.png": [{"id": "G/red", "dist": 4}], "items/lonely.png": [{"id": "G/red", "dist": M.CLOSE + 1}]}
    mapping = {
        "items/gold.png": {"source": "G/gold", "synced": "md5-gold"},
        "items/screenshot.png": {"source": "G/red"},
        "events/x.webp": {"source": "G/ghost", "synced": "md5-ghost"},
        "items/none.png": {"source": None},
    }
    status = lambda rel, m=mapping: Mp.status_of(rel, m, sprites, matches, assets)  # noqa: E731
    assert status("items/gold.png") == "official"
    assert status("items/screenshot.png") == "to sync"  # mapped, never synced
    assert status("events/x.webp") == "missing"
    assert status("items/none.png") == "none"
    assert status("items/screenshot.png", {}) == "suggested"
    assert status("items/lonely.png", {}) == "unmapped"
    assert Mp.status_of("items/gold.png", {"items/gold.png": {"source": "G/gold", "synced": "OLD"}}, sprites, matches, assets) == "to sync"
    assert Mp.status_of("items/absent.png", {"items/absent.png": {"source": "G/gold", "synced": "md5-gold"}}, sprites, matches, assets) == "to sync"  # file gone


def test_rows_lists_png_and_webp_with_the_best_candidate(world):
    matches = {"items/screenshot.png": [{"id": "G/red", "dist": 4}, {"id": "G/gold", "dist": 50}]}
    table = Mp.rows({"items/gold.png": {"source": "G/gold", "synced": "md5-gold"}}, world["index"], matches, world["assets"])
    by_rel = {r["rel"]: r for r in table}
    assert set(by_rel) == {"items/gold.png", "items/screenshot.png", "items/lonely.png", "events/x.webp"}
    assert by_rel["items/screenshot.png"] == {"rel": "items/screenshot.png", "status": "suggested", "source": "G/red", "dist": 4}
    assert by_rel["items/gold.png"]["source"] == "G/gold" and by_rel["items/gold.png"]["status"] == "official"
    assert Mp.counts(table)["official"] == 1
    assert Mp.summary(table).startswith("Official 1 of 4 webapp images")


def test_set_source_clear_and_accept_suggestions(world):
    path = world["path"]
    Mp.set_source("items/a.png", "G/gold", focus=(0.5, 0.0), path=path)  # the default focus is not stored
    Mp.set_source("events/b.webp", "G/banner", focus=(0.3, 0.25), path=path)
    Mp.set_source("items/c.png", None, path=path)
    assert Mp.load(path) == {"items/a.png": {"source": "G/gold"}, "events/b.webp": {"source": "G/banner", "focus": [0.3, 0.25]},
                             "items/c.png": {"source": None}}
    Mp.clear("items/a.png", path)
    Mp.clear("items/never.png", path)
    assert "items/a.png" not in Mp.load(path)
    table = [{"rel": "items/x.png", "source": "G/red", "dist": 3}, {"rel": "items/y.png", "source": "G/red", "dist": 30},
             {"rel": "items/c.png", "source": "G/red", "dist": 1}, {"rel": "items/z.png", "source": None, "dist": None}]
    assert Mp.accept_suggestions(table, 10, path) == 1  # c is mapped already, y is too far, z has no candidate
    assert Mp.load(path)["items/x.png"] == {"source": "G/red"} and Mp.load(path)["items/c.png"] == {"source": None}


def test_set_source_keeps_the_synced_md5_only_when_given(world):
    Mp.set_source("items/a.png", "G/gold", synced="md5-gold", path=world["path"])
    assert Mp.load(world["path"])["items/a.png"] == {"source": "G/gold", "synced": "md5-gold"}
    Mp.set_source("items/a.png", "G/red", path=world["path"])
    assert Mp.load(world["path"])["items/a.png"] == {"source": "G/red"}


def run_sync(world, **kw):
    return Mp.sync(world["index"], out=world["out"], assets=world["assets"], path=world["path"], **kw)


def test_sync_previews_without_writing_and_applies_on_request(world):
    Mp.save({"items/screenshot.png": {"source": "G/red"}, "events/new.webp": {"source": "G/banner"}}, world["path"])
    shot = world["assets"] / "items" / "screenshot.png"
    before = shot.read_bytes()
    preview = run_sync(world)
    assert {d["rel"]: d["action"] for d in preview} == {"events/new.webp": "write", "items/screenshot.png": "write"}
    assert shot.read_bytes() == before and not (world["assets"] / "events" / "new.webp").exists()
    assert "synced" not in Mp.load(world["path"])["items/screenshot.png"]
    run_sync(world, apply=True)
    assert Image.open(shot).convert("RGBA").getpixel((5, 5)) == (255, 0, 0, 255)
    made = Image.open(world["assets"] / "events" / "new.webp")
    assert made.format == "WEBP" and made.size == (1440, 720)  # near 2:1: the game's size is kept
    assert Mp.load(world["path"])["items/screenshot.png"]["synced"] == "md5-red"


def test_sync_skips_what_is_up_to_date_and_marks_pixel_identical_files_without_rewriting(world):
    Mp.save({"items/gold.png": {"source": "G/gold"}, "items/screenshot.png": {"source": "G/red", "synced": "md5-red"}}, world["path"])
    gold = world["assets"] / "items" / "gold.png"
    mtime = gold.stat().st_mtime_ns
    done = run_sync(world, apply=True)
    assert [(d["rel"], d["action"]) for d in done] == [("items/gold.png", "same")]  # screenshot.png was synced already
    assert gold.stat().st_mtime_ns == mtime  # same picture: the file is left alone
    assert Mp.load(world["path"])["items/gold.png"]["synced"] == "md5-gold"
    assert run_sync(world, apply=True) == []  # nothing left to do
    assert [d["action"] for d in run_sync(world, force=True)] == ["same", "write"]


def test_sync_reports_pictures_that_are_not_extracted(world):
    Mp.save({"items/a.png": {"source": "G/ghost"}, "items/b.png": {"source": None}}, world["path"])
    done = run_sync(world, apply=True)
    assert done == [{"rel": "items/a.png", "action": "skipped", "note": "G/ghost is not extracted"}]


def test_set_source_stores_resize_only_for_a_mapped_picture(world):
    Mp.set_source("events/a.webp", "G/banner", resize=True, path=world["path"])
    Mp.set_source("events/b.webp", None, resize=True, path=world["path"])
    assert Mp.load(world["path"]) == {"events/a.webp": {"source": "G/banner", "resize": True}, "events/b.webp": {"source": None}}


def test_sync_makes_720_by_360_for_an_entry_with_resize(world):
    Mp.save({"events/kept.webp": {"source": "G/banner"}, "events/resized.webp": {"source": "G/banner", "resize": True}}, world["path"])
    run_sync(world, apply=True)
    assert Image.open(world["assets"] / "events" / "kept.webp").size == (1440, 720)
    assert Image.open(world["assets"] / "events" / "resized.webp").size == (720, 360)


def test_sync_uses_the_focus_of_the_entry(world):
    Image.new("RGBA", (100, 600), "red").save(world["out"] / "G" / "tall.png")
    img = Image.open(world["out"] / "G" / "tall.png")
    img.paste(Image.new("RGBA", (100, 100), "blue"), (0, 500))
    img.save(world["out"] / "G" / "tall.png")
    world["index"]["sprites"]["G/tall"] = {"id": "G/tall", "md5": "md5-tall"}
    Mp.save({"events/top.webp": {"source": "G/tall"}, "events/bottom.webp": {"source": "G/tall", "focus": [0.5, 1.0]}}, world["path"])
    run_sync(world, apply=True)
    top = Image.open(world["assets"] / "events" / "top.webp").convert("RGBA").getpixel((360, 180))
    bottom = Image.open(world["assets"] / "events" / "bottom.webp").convert("RGBA").getpixel((360, 340))
    assert top[0] > 200 and top[2] < 60  # red
    assert bottom[2] > 200 and bottom[0] < 60  # blue
    assert R.target_size("events/top.webp") == (720, 360)


def test_an_overlay_is_part_of_the_fingerprint_and_the_status(world):
    sprites, assets = world["index"]["sprites"], world["assets"]
    entry = {"source": "G/banner", "overlay": {"source": "G/gold", "scale": 0.8, "at": [0.5, 0.5]}}
    both = Mp.fingerprint(entry, sprites)
    assert both not in ("md5-banner", "md5-gold") and Mp.fingerprint({"source": "G/banner"}, sprites) == "md5-banner"
    assert Mp.fingerprint({**entry, "overlay": {"source": "G/ghost"}}, sprites) is None
    assert Mp.status_of("events/x.webp", {"events/x.webp": {**entry, "synced": both}}, sprites, {}, assets) == "official"
    assert Mp.status_of("events/x.webp", {"events/x.webp": {**entry, "synced": "md5-banner"}}, sprites, {}, assets) == "to sync"  # the overlay is new
    assert Mp.status_of("events/x.webp", {"events/x.webp": {**entry, "overlay": {"source": "G/ghost"}}}, sprites, {}, assets) == "missing"


def test_sync_puts_the_overlay_on_top_and_marks_both_pictures_as_synced(world):
    Mp.set_source("events/new.webp", "G/banner", resize=True, path=world["path"],
                  overlay={"source": "G/red", "scale": 0.5, "at": [0.5, 0.5]})
    assert Mp.load(world["path"])["events/new.webp"]["overlay"] == {"source": "G/red", "scale": 0.5, "at": [0.5, 0.5]}
    run_sync(world, apply=True)
    made = Image.open(world["assets"] / "events" / "new.webp").convert("RGB")
    assert made.getpixel((360, 180))[0] > 200 and made.getpixel((10, 10))[2] > 200  # red in the middle, blue around
    entry = Mp.load(world["path"])["events/new.webp"]
    assert entry["synced"] == Mp.fingerprint(entry, world["index"]["sprites"])
    assert run_sync(world, apply=True) == []


def test_sync_skips_an_entry_whose_overlay_is_not_extracted(world):
    Mp.save({"events/new.webp": {"source": "G/banner", "overlay": {"source": "G/ghost"}}}, world["path"])
    assert run_sync(world, apply=True) == [{"rel": "events/new.webp", "action": "skipped", "note": "G/ghost is not extracted"}]


def test_set_source_without_an_overlay_drops_it(world):
    Mp.set_source("events/a.webp", "G/banner", path=world["path"], overlay={"source": "G/red"})
    Mp.set_source("events/a.webp", "G/banner", path=world["path"])
    assert Mp.load(world["path"]) == {"events/a.webp": {"source": "G/banner"}}
