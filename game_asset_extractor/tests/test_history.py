import json

from PIL import Image

import config as C
import extract as E
import history as H
import state as S
import texts as T


def sprite(sid, added, changed=None):
    return {"id": sid, "added": added, "changed": changed}


def index(sprites, runs=None, run=None, **meta):
    runs = runs or {"1": {"version": "1.0.1", "time": "t1"}, "2": {"version": "1.0.2", "time": "t2"}}
    return {"meta": {"run": run or len(runs), "baseline": 0, "runs": runs, **meta}, "sprites": {s["id"]: s for s in sprites}}


def test_record_lists_only_what_came_after_the_first_run_or_changed():
    cache = index([sprite("p/a", 1), sprite("p/b", 2), sprite("p/c", 1, 2)])
    texts = {"first": 2, "texts": {"t:1": {"en": ["h", 2, 0], "de": ["h", 2, 0]}, "t:2": {"en": ["h", 3, 0], "de": ["h", 2, 4]}}}
    history = H.record(cache, texts)
    assert history["runs"] == cache["meta"]["runs"]
    assert history["pictures"] == {"first": 1, "changes": {"p/b": [2, 0], "p/c": [1, 2]}}
    assert history["texts"] == {"first": 2, "changes": {"t:2": {"en": [3, 0], "de": [2, 4]}}}
    assert H.load() == history  # saved, and read back


def test_runs_of_one_version_are_merged_into_the_first_of_them():
    runs = {"1": {"version": "1.0.1", "time": "t1"}, "2": {"version": "1.0.2", "time": "t2"}, "3": {"version": "1.0.2", "time": "t3"},
            "4": {"version": "?", "time": "t4"}, "5": {"version": "?", "time": "t5"}, "6": {"version": "1.0.2", "time": "t6"}}
    assert H.versions(runs) == {"1": 1, "2": 2, "3": 2, "4": 4, "5": 5, "6": 2}
    cache = index([sprite("p/a", 1), sprite("p/b", 3), sprite("p/c", 2, 3), sprite("p/d", 1, 6), sprite("p/e", 1, 4), sprite("p/f", 6)], runs)
    texts = {"first": 1, "texts": {"t:1": {"en": ["h", 3, 0], "de": ["h", 1, 6]}, "t:2": {"en": ["h", 6, 0]}, "t:3": {"en": ["h", 1, 3], "de": ["h", 1, 0]}}}
    history = H.record(cache, texts)
    assert list(history["runs"]) == ["1", "2", "4", "5"]  # the first run of each version
    # p/c was changed in the version that added it: no change
    assert history["pictures"]["changes"] == {"p/b": [2, 0], "p/c": [2, 0], "p/d": [1, 2], "p/e": [1, 4], "p/f": [2, 0]}
    assert history["texts"] == {"first": 1, "changes": {"t:1": {"en": [2, 0], "de": [1, 2]}, "t:2": {"en": [2, 0]}, "t:3": {"en": [1, 2]}}}


def test_the_file_has_one_line_per_run_picture_and_text(tmp_path):
    cache = index([sprite("p/b", 2), sprite("p/a", 1, 2)])
    H.record(cache, {"first": 2, "texts": {"t:1": {"de": ["h", 3, 0]}}})
    lines = H.PATH.read_text(encoding="utf-8").splitlines()
    assert '  "1": {"version": "1.0.1", "time": "t1"},' in lines and '   "p/a": [1, 2],' in lines and '   "p/b": [2, 0]' in lines
    assert '   "t:1": {"de": [3, 0]}' in lines and not H.PATH.read_text(encoding="utf-8").startswith(" ")
    json.loads(H.PATH.read_text(encoding="utf-8"))  # and it is JSON


def test_record_writes_nothing_before_the_first_run_and_keeps_the_texts_without_a_text_index():
    assert H.record({"meta": {"run": 0, "baseline": 0, "runs": {}}, "sprites": {}}) is None and not H.PATH.exists()
    H.record(index([]), {"first": 1, "texts": {"t:1": {"de": ["h", 2, 0]}}})
    assert H.record(index([sprite("p/a", 2)]), {"first": None, "texts": {}})["texts"]["changes"] == {"t:1": {"de": [2, 0]}}


def test_a_half_rebuilt_cache_does_not_make_the_history_forget_the_pictures_not_back_yet():
    H.record(index([sprite("p/a", 2), sprite("p/b", 2)]))
    half = index([sprite("p/a", 2)], restoring=True)
    assert sorted(H.record(half)["pictures"]["changes"]) == ["p/a", "p/b"]
    assert sorted(H.record(index([sprite("p/a", 2)]))["pictures"]["changes"]) == ["p/a"]  # complete: what is gone is gone


def test_restore_run_continues_the_numbering_of_a_fresh_cache_only():
    history = {**H.empty(), "runs": {"1": {"version": "1.0.1", "time": "t"}, "3": {"version": "1.0.3", "time": "t"}}}
    fresh = {"meta": {"run": 0, "baseline": 0, "runs": {}}, "sprites": {}}
    assert H.restore_run(fresh, history) and fresh["meta"] == {"run": 3, "baseline": 3, "runs": history["runs"], "restoring": True}
    assert not H.restore_run(index([]), history) and not H.restore_run(fresh, {**history, "runs": {}})


def test_apply_pictures_gives_the_recorded_runs_else_the_first():
    history = {**H.empty(), "pictures": {"first": 1, "changes": {"p/b": [3, 0], "p/c": [1, 4]}}}
    cache = index([sprite("p/a", 9), sprite("p/b", 9), sprite("p/c", 9, 9)])
    H.apply_pictures(cache, history)
    assert [(s["added"], s["changed"]) for s in cache["sprites"].values()] == [(1, None), (3, None), (1, 4)]


def test_the_text_index_of_a_rebuilt_cache_takes_the_recorded_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path / "out")
    H.save({**H.empty(), "texts": {"first": 2, "changes": {"a": {"de": [3, 4]}}}})
    result = T.update_index(9, texts={"en": {"a": "A", "b": "B"}, "de": {"a": "Ä", "b": "B"}})
    assert result["first"] == 2
    assert {t: {lang: mark[1:] for lang, mark in m.items()} for t, m in result["texts"].items()} == {
        "a": {"en": [2, 0], "de": [3, 4]}, "b": {"en": [2, 0], "de": [2, 0]}}
    # without a record it is the current run, as before
    H.PATH.unlink()
    (tmp_path / "out" / "texts.json").unlink()
    assert T.update_index(9, texts={"en": {"a": "A"}})["texts"]["a"]["en"][1:] == [9, 0] and T.load_index()["first"] == 9


def test_a_deleted_cache_is_rebuilt_from_the_history_and_the_next_update_is_a_new_run(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path / "out")
    monkeypatch.setattr(C, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(C, "STATE", tmp_path / "state")
    C.CACHE.mkdir()
    C.STATE.mkdir()
    for name in ("b1", "b2"):
        (C.CACHE / name).write_bytes(b"x")
    (C.STATE / "version.txt").write_text("1.0.9", encoding="utf-8")
    S.save("pulled.json", {"b1": {"md5": "1", "path": "UI/Atlas/G1"}})
    pictures = {"b1": ["old", "new", "changed"], "b2": ["later"]}
    monkeypatch.setattr(E, "export_bundle", lambda path: [(n, Image.new("RGBA", (4, 4), "red")) for n in pictures[path.name]])
    H.save({"runs": {"1": {"version": "1.0.1", "time": "t1"}, "2": {"version": "1.0.2", "time": "t2"}},
            "pictures": {"first": 1, "changes": {"pictures/G1/new": [2, 0], "pictures/G1/changed": [1, 2]}},
            "texts": {"first": None, "changes": {}}})

    E.run()  # the cache is empty: every bundle comes back
    cache = S.load_index()
    assert (cache["meta"]["run"], cache["meta"]["baseline"], "restoring" in cache["meta"]) == (2, 2, False)
    assert {i: (s["added"], s["changed"]) for i, s in cache["sprites"].items()} == {
        "pictures/G1/old": (1, None), "pictures/G1/new": (2, None), "pictures/G1/changed": (1, 2)}
    assert H.load()["pictures"]["changes"] == {"pictures/G1/new": [2, 0], "pictures/G1/changed": [1, 2]}  # as it was

    S.save("pulled.json", {**S.load("pulled.json"), "b2": {"md5": "2", "path": "UI/Atlas/G2"}})
    E.run()  # a game update: a new run, with the game's version
    cache = S.load_index()
    assert cache["meta"]["run"] == 3 and cache["meta"]["runs"]["3"]["version"] == "1.0.9"
    assert (cache["sprites"]["pictures/G2/later"]["added"], cache["sprites"]["pictures/G1/old"]["added"]) == (3, 1)
    assert H.load()["pictures"]["changes"]["pictures/G2/later"] == [3, 0] and H.load()["runs"]["3"]["version"] == "1.0.9"


def test_a_rebuild_that_did_not_finish_goes_on_without_a_new_run(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path / "out")
    monkeypatch.setattr(C, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(C, "STATE", tmp_path / "state")
    C.CACHE.mkdir()
    for name in ("b1", "b2"):
        (C.CACHE / name).write_bytes(b"x")
    S.save("pulled.json", {"b1": {"md5": "1", "path": "UI/Atlas/G1"}, "b2": {"md5": "2", "path": "UI/Atlas/G2"}})
    broken = {"b2"}

    def export(path):
        if path.name in broken:
            raise RuntimeError("boom")
        return [(path.name, Image.new("RGBA", (4, 4), "red"))]

    monkeypatch.setattr(E, "export_bundle", export)
    H.save({"runs": {"1": {"version": "1.0.1", "time": "t1"}}, "pictures": {"first": 1, "changes": {"pictures/G2/b2": [1, 3]}},
            "texts": {"first": None, "changes": {}}})
    E.run()  # one bundle fails: the rebuild is not complete
    assert S.load_index()["meta"]["restoring"] is True and S.load_index()["meta"]["run"] == 1
    assert "pictures/G2/b2" in H.load()["pictures"]["changes"]  # the history still knows what is not back yet
    broken.clear()
    E.run()
    cache = S.load_index()
    assert "restoring" not in cache["meta"] and cache["meta"]["run"] == 1
    assert (cache["sprites"]["pictures/G2/b2"]["added"], cache["sprites"]["pictures/G2/b2"]["changed"]) == (1, 3)
