import json

import pytest

import mapping as Mp
import text_mapping as TM

EN = {
    "tables/Item:gold.name": "Gold",
    "language/Common:gold": "gold",
    "tables/Item:chest.name": "[c][ec413a]Raven Chest[-][/c]",
    "tables/Item:grant.description": "Grants {0} Antitoxin.",
    "language/Common:research": "Research",
    "tables/Act:1.typeDesc": "Research",
    "tables/Item:sword.name": "Sword of Dawn",
}
DE = {
    "tables/Item:gold.name": "Gold",
    "language/Common:gold": "[c]Gold[-][/c]",
    "tables/Item:chest.name": "[c][ec413a]Raben-Truhe[-][/c]",
    "tables/Item:grant.description": "Gewährt {0} Gegengift.",
    "language/Common:research": "Forschung",
    "tables/Act:1.typeDesc": "Forschen",
    "tables/Item:sword.name": "Schwert der Morgenröte",
}
LANGS = ["en", "de"]


@pytest.fixture
def game():
    return TM.Game({"en": EN, "de": DE})


def test_texts_are_found_by_their_location_a_list_item_by_its_id_else_its_number():
    found = {}
    TM.walk({"items": {"gold": {"name": {"en": "Gold", "de": ""}, "category": "x"}},
             "phases": [{"id": "raid", "name": {"en": "Raid"}}, {"name": {"en": "Plain"}, "tags": [{"en": "A", "de": "B"}]}],
             "number": {"en": 1}}, "", found)
    assert list(found) == ["items.gold.name", "phases[raid].name", "phases[1].name", "phases[1].tags[0]"]
    assert TM.is_text({"en": "x", "de": "y", "pt-BR": "z"}) and not TM.is_text({"en": "x", "level": "y"})
    assert not TM.is_text({"de": "x"}) and not TM.is_text({"en": 3})


def webapp(tmp_path, files):
    """A webapp checkout: its data files and one i18n file per language."""
    data = tmp_path / "webapp" / "data"
    data.mkdir(parents=True)
    names = {"pack_data": {}, "events": {}, "hero_skills": {}, "lord_specialty": {}}
    for stem, content in {**names, **files}.items():
        text = json.dumps(content, indent=4, ensure_ascii=False) + "\n"
        (data / f"{stem}.json").write_bytes((text.replace("\n", "\r\n") if stem == "hero_skills" else text).encode("utf-8"))
    i18n = tmp_path / "webapp" / "webapp" / "src" / "i18n"
    i18n.mkdir(parents=True)
    for lang in ("de", "en"):
        (i18n / f"{lang}.json").write_text("{}", encoding="utf-8")
    return data, i18n


def test_read_webapp_finds_the_texts_of_the_four_data_files_and_the_languages(tmp_path):
    data, i18n = webapp(tmp_path, {"pack_data": {"items": {"gold": {"name": {"en": "Gold", "de": "Gold"}}}},
                                   "events": {"events": {"x": {"name": {"en": "X"}}}}})
    docs, texts = TM.read_webapp(data)
    assert list(texts) == ["pack_data:items.gold.name", "events:events.x.name"]
    assert docs["pack_data"]["crlf"] is False and docs["hero_skills"]["crlf"] is True
    assert TM.webapp_languages(i18n) == ["en", "de"]
    with pytest.raises(FileNotFoundError, match="LAST_ASYLUM_WEBAPP"):
        TM.read_webapp(tmp_path / "missing")


def test_exact_matches_ignore_markup_case_and_placeholder_names_and_near_ones_are_typos(game):
    assert game.exact("raven chest") == ["tables/Item:chest.name"]
    assert game.exact("GOLD") == ["tables/Item:gold.name", "language/Common:gold"]  # a table's text first
    assert game.exact("Grants {amount} Antitoxin.") == ["tables/Item:grant.description"]
    assert game.near("Sword of Dawm") == [("tables/Item:sword.name", 92)]
    assert game.near("Sword of Dawn") == []  # an exact match is not a "near" one
    assert game.near("Dawn of Sword") == [("tables/Item:sword.name", 100)]  # the same words, another order
    assert game.near("Something else entirely") == []


def test_search_looks_in_ids_and_every_language_and_needs_two_letters(game):
    assert game.search("morgen") == ["tables/Item:sword.name"]
    assert game.search("common:res") == ["language/Common:research"]
    assert game.search("g") == [] and len(game.search("tables/", limit=3)) == 3


def test_targets_write_the_game_text_the_webapps_way(game):
    node = {"en": "Grants {amount} antitoxin.", "de": ""}
    assert TM.targets(node, "tables/Item:grant.description", game, LANGS) == {
        "en": "Grants {amount} Antitoxin.", "de": "Gewährt {amount} Gegengift."}
    assert TM.targets({"en": "Grants antitoxin"}, "tables/Item:grant.description", game, LANGS) == {"en": None, "de": None}
    assert TM.targets(node, "tables/Item:gone", game, LANGS) == {}


def test_a_translation_the_webapp_already_has_decides_between_two_game_texts(game):
    node = {"en": "Research", "de": ""}
    found = TM.candidates(node, game, LANGS)
    assert [c["id"] for c in found] == ["tables/Act:1.typeDesc", "language/Common:research"] and not found[0]["clear"]
    node["de"] = "Forschung"
    found = TM.candidates(node, game, LANGS)
    assert [c["id"] for c in found] == ["language/Common:research", "tables/Act:1.typeDesc"] and found[0]["clear"]


def test_candidates_of_a_text_not_in_the_game_are_its_near_matches(game):
    found = TM.candidates({"en": "Sword of Dawm", "de": ""}, game, LANGS)
    assert [(c["id"], c["exact"], c["score"]) for c in found] == [("tables/Item:sword.name", False, 92)]
    assert TM.candidates({"en": "Nothing like it", "de": ""}, game, LANGS) == []


def test_every_status(game):
    texts = {
        "official": {"en": "Gold", "de": "Gold"},
        "to sync": {"en": "Raven Chest", "de": ""},
        "mismatch": {"en": "Grants antitoxin.", "de": ""},
        "missing": {"en": "Gone", "de": "Weg"},
        "none": {"en": "Our own", "de": "Unser"},
        "suggested": {"en": "Gold", "de": ""},
        "ambiguous": {"en": "Research", "de": ""},
        "near": {"en": "Sword of Dawm", "de": ""},
        "unmapped": {"en": "Nothing like it", "de": ""},
    }
    mapping = {"official": {"source": "tables/Item:gold.name"}, "to sync": {"source": "tables/Item:chest.name"},
               "mismatch": {"source": "tables/Item:grant.description"}, "missing": {"source": "tables/Item:gone"},
               "none": {"source": None}}
    table = TM.rows(mapping, texts, game, LANGS)
    assert {r["location"]: r["status"] for r in table} == {name: name for name in texts}
    assert {r["location"]: r["source"] for r in table if r["status"] in ("suggested", "near")} == {
        "suggested": "tables/Item:gold.name", "near": "tables/Item:sword.name"}
    assert TM.counts(table)["official"] == 1
    assert TM.summary(table) == ("Official 1 of 9 webapp texts - to sync 1, suggested 1, ambiguous 1, near 1, unmapped 1, "
                                 "own text 1, mismatch 1, missing 1")


def test_accept_suggestions_maps_only_the_clear_ones_and_keeps_what_was_mapped(game, tmp_path):
    path = tmp_path / "text_mapping.json"
    path.write_text(json.dumps({"b": {"source": None}}), encoding="utf-8")
    table = [{"location": "a", "status": "suggested", "source": "tables/Item:gold.name"},
             {"location": "b", "status": "suggested", "source": "x"},
             {"location": "c", "status": "ambiguous", "source": "y"}, {"location": "d", "status": "near", "source": "z"}]
    assert TM.accept_suggestions(table, path) == 1
    assert Mp.load(path) == {"a": {"source": "tables/Item:gold.name"}, "b": {"source": None}}
    TM.set_source("c", "tables/Act:1.typeDesc", path)
    TM.clear("a", path)
    TM.clear("nothing", path)
    assert TM.load(path) == {"b": {"source": None}, "c": {"source": "tables/Act:1.typeDesc"}}
    assert TM.used(TM.load(path)) == {"tables/Act:1.typeDesc": ["c"]}


def test_plan_lists_what_differs_and_what_cannot_be_synced(game):
    texts = {"chest": {"en": "Raven Chest", "de": "Alte Truhe"}, "gold": {"en": "Gold", "de": "Gold"},
             "grant": {"en": "Grants antitoxin"}, "gone": {"en": "Gone"}, "own": {"en": "Own"}}
    mapping = {"chest": {"source": "tables/Item:chest.name"}, "gold": {"source": "tables/Item:gold.name"},
               "grant": {"source": "tables/Item:grant.description"}, "gone": {"source": "tables/Item:gone"},
               "own": {"source": None}, "removed from the webapp": {"source": "tables/Item:gold.name"}}
    done = TM.plan(mapping, texts, game, LANGS)
    assert [(d["location"], d["lang"], d["action"], d["old"], d["new"]) for d in done] == [
        ("chest", "de", "write", "Alte Truhe", "Raben-Truhe"),
        ("gone", "", "skipped", "", ""),
        ("grant", "en", "skipped", "Grants antitoxin", ""), ("grant", "de", "skipped", "", "")]


def test_a_missing_language_key_is_added_and_english_follows_the_game(game):
    done = TM.plan({"x": {"source": "tables/Item:chest.name"}}, {"x": {"en": "raven chest"}}, game, LANGS)
    assert [(d["lang"], d["old"], d["new"]) for d in done] == [("en", "raven chest", "Raven Chest"), ("de", "", "Raben-Truhe")]


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """A webapp checkout with a (fake) prettier, and the commands that were run on it."""
    data, i18n = webapp(tmp_path, {
        "pack_data": {"items": {"chest": {"name": {"en": "Raven Chest", "de": ""}}, "gold": {"name": {"en": "Gold", "de": "Gold"}}}},
        "hero_skills": {"heroes": {"a": {"note": {"en": "sword of dawn", "de": "Schwert"}}}}})
    prettier = tmp_path / "webapp" / "node_modules" / "prettier" / "bin" / "prettier.cjs"
    prettier.parent.mkdir(parents=True)
    prettier.write_text("", encoding="utf-8")
    calls = []
    monkeypatch.setattr(TM.shutil, "which", lambda name: "node")
    monkeypatch.setattr(TM.subprocess, "run", lambda command, **kw: calls.append((command, kw)) or type("R", (), {"returncode": 0})())
    mapping = tmp_path / "text_mapping.json"
    mapping.write_text(json.dumps({"pack_data:items.chest.name": {"source": "tables/Item:chest.name"},
                                   "pack_data:items.gold.name": {"source": "tables/Item:gold.name"},
                                   "hero_skills:heroes.a.note": {"source": "tables/Item:sword.name"}}), encoding="utf-8")
    return data, i18n, mapping, calls


def run_sync(checkout, game, apply):
    data, i18n, mapping, _ = checkout
    return TM.sync(apply, game, data, i18n, mapping)


def test_sync_previews_without_writing_anything(checkout, game):
    before = {p.name: p.read_bytes() for p in checkout[0].iterdir()}
    done = run_sync(checkout, game, apply=False)
    assert [(d["location"], d["lang"]) for d in done] == [
        ("hero_skills:heroes.a.note", "en"), ("hero_skills:heroes.a.note", "de"),
        ("pack_data:items.chest.name", "de")]
    assert {p.name: p.read_bytes() for p in checkout[0].iterdir()} == before and checkout[3] == []


def test_sync_writes_the_changed_files_as_the_webapp_keeps_them_and_formats_them_with_its_prettier(checkout, game, tmp_path):
    data, _, _, calls = checkout
    events = (data / "events.json").read_bytes()
    run_sync(checkout, game, apply=True)
    pack = json.loads((data / "pack_data.json").read_text(encoding="utf-8"))
    assert pack["items"]["chest"]["name"] == {"en": "Raven Chest", "de": "Raben-Truhe"}
    assert (data / "pack_data.json").read_text(encoding="utf-8").endswith("}\n")
    hero = (data / "hero_skills.json").read_bytes()
    assert b"\r\n" in hero and b"\n" not in hero.replace(b"\r\n", b"")  # the line ends it had
    assert json.loads(hero)["heroes"]["a"]["note"] == {"en": "Sword of Dawn", "de": "Schwert der Morgenröte"}
    assert (data / "events.json").read_bytes() == events  # nothing to change: not touched
    [(command, options)] = calls
    assert command[:3] == ["node", str(tmp_path / "webapp" / "node_modules" / "prettier" / "bin" / "prettier.cjs"), "--write"]
    assert sorted(command[3:]) == sorted(str(data / f"{stem}.json") for stem in ("hero_skills", "pack_data"))
    assert options["cwd"] == tmp_path / "webapp"  # so it finds the webapp's own .prettierrc


def test_sync_stops_before_writing_when_the_webapps_prettier_is_missing(checkout, game, tmp_path):
    (tmp_path / "webapp" / "node_modules" / "prettier" / "bin" / "prettier.cjs").unlink()
    before = (checkout[0] / "pack_data.json").read_bytes()
    with pytest.raises(RuntimeError, match="npm install"):
        run_sync(checkout, game, apply=True)
    assert (checkout[0] / "pack_data.json").read_bytes() == before


def test_a_failing_prettier_is_reported(checkout, game, monkeypatch):
    monkeypatch.setattr(TM.subprocess, "run", lambda command, **kw: type("R", (), {"returncode": 2, "stderr": "boom", "stdout": ""})())
    with pytest.raises(RuntimeError, match="boom"):
        run_sync(checkout, game, apply=True)
