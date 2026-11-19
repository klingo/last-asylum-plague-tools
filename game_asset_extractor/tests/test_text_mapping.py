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
    names = {"pack_data": {}, "events": {}, "hero_skills": {}, "lord_specialty": {}, "raven_epigraphs": {}}
    for stem, content in {**names, **files}.items():
        text = json.dumps(content, indent=4, ensure_ascii=False) + "\n"
        (data / f"{stem}.json").write_bytes((text.replace("\n", "\r\n") if stem == "hero_skills" else text).encode("utf-8"))
    i18n = tmp_path / "webapp" / "webapp" / "src" / "i18n"
    i18n.mkdir(parents=True)
    for lang in ("de", "en"):
        (i18n / f"{lang}.json").write_text("{}", encoding="utf-8")
    return data, i18n


def test_read_webapp_finds_the_texts_of_the_five_data_files_and_the_languages(tmp_path):
    data, i18n = webapp(tmp_path, {"pack_data": {"items": {"gold": {"name": {"en": "Gold", "de": "Gold"}}}},
                                   "events": {"events": {"x": {"name": {"en": "X"}}}},
                                   "raven_epigraphs": {"epigraphs": {"guard_of_nature": {"warrior": {
                                       "description": {"en": "Gain a {shield}-HP shield", "de": ""}}}}}})
    docs, texts = TM.read_webapp(data)
    assert list(texts) == ["pack_data:items.gold.name", "events:events.x.name",
                           "raven_epigraphs:epigraphs.guard_of_nature.warrior.description"]
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
    assert TM.targets(node, TM.single("tables/Item:grant.description"), game, LANGS) == {
        "en": "Grants {amount} Antitoxin.", "de": "Gewährt {amount} Gegengift."}
    assert TM.targets({"en": "Grants antitoxin"}, TM.single("tables/Item:grant.description"), game, LANGS) == {"en": None, "de": None}
    assert TM.targets(node, TM.single("tables/Item:gone"), game, LANGS) == {}


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
    TM.set_entry("c", TM.single("tables/Act:1.typeDesc"), path)
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


# --- texts the game puts together in its code -----------------------------------------------------------------------
BUILT_EN = {
    "language/Common:TxtLv": "Lv.{0}",
    "language/Alliance:lv": "Lv.{0}",
    "tables/Item:beak_1.name": "Sharp Beak",
    "tables/Item:beak_2.name": "Sharp Beak",
    "tables/Benefit:1.name": "Hero DMG Dealt↑",
    "tables/Skill:1.desc": "Casualty Rate +{0} when burning",
    "tables/Skill:2.desc": "Obtain 1 random survivor. CD: {0}",
    "tables/Skill:3.desc": "Up {0}",
    "tables/Skill:4.name": "Now",
}
BUILT_DE = {
    "language/Common:TxtLv": "Lv.{0}",
    "language/Alliance:lv": "Lv.{0}",
    "tables/Item:beak_1.name": "Scharfer Schnabel",
    "tables/Item:beak_2.name": "Scharfer Schnabel",
    "tables/Benefit:1.name": "Verursachter Held-SCH↑",
    "tables/Skill:1.desc": "Verlustrate +{0} beim Brennen",
    "tables/Skill:2.desc": "Erhalte 1 zufälligen Überlebenden. AZ: {0}",
    "tables/Skill:3.desc": "Hoch {0}",
    "tables/Skill:4.name": "Jetzt",
}
LEVEL = {"source": "language/Common:TxtLv", "fill": {"0": "3"}}
BEAK = {"source": "tables/Item:beak_1.name"}


@pytest.fixture
def built():
    return TM.Game({"en": BUILT_EN, "de": BUILT_DE})


def test_a_template_says_the_parts_and_a_single_game_text_is_its_id():
    template = "[[language/Common:TxtLv|0=3|de:0=3,5]] [[tables/Item:beak_1.name]]"
    parts = TM.parse_template(template)
    assert parts == [{"source": "language/Common:TxtLv", "fill": {"0": "3", "de:0": "3,5"}}, " ", BEAK]
    assert TM.template_of(parts) == template
    assert TM.parse_template(" tables/Item:gold.name ") == TM.single("tables/Item:gold.name")
    assert TM.template_of(TM.single("tables/Item:gold.name")) == "tables/Item:gold.name"
    assert TM.template_of([{"source": "a:b", "fill": {"0": "1"}}]) == "[[a:b|0=1]]"  # a fill needs the brackets


def test_an_entry_is_short_for_one_game_text_and_has_parts_for_more():
    assert TM.entry_of(TM.single("tables/Item:gold.name")) == {"source": "tables/Item:gold.name"}
    assert TM.entry_of([{"source": "a:b", "fill": {"0": "1"}}]) == {"source": "a:b", "fill": {"0": "1"}}
    parts = [LEVEL, " ", BEAK]
    assert TM.entry_of(parts) == {"parts": parts}
    assert [TM.parts_of(TM.entry_of(p)) for p in (parts, TM.single("a:b"))] == [parts, TM.single("a:b")]
    assert TM.parts_of({"source": None}) is None


@pytest.mark.parametrize("template", ["[[tables/Item:x", "just text", "[[tables/Item:x|0]]", "[[tables/Item:x]] ]]", ""])
def test_a_template_that_is_none_is_refused(template):
    with pytest.raises(ValueError):
        TM.parse_template(template)


def test_compose_fills_the_placeholders_per_language_and_names_the_others_by_the_part(built):
    filled = [{"source": "tables/Skill:2.desc", "fill": {"0": "119.5h", "de:0": "119,5 Std."}}]
    assert TM.compose(filled, built, "en") == "Obtain 1 random survivor. CD: 119.5h"
    assert TM.compose(filled, built, "de") == "Erhalte 1 zufälligen Überlebenden. AZ: 119,5 Std."
    assert TM.compose([{"source": "language/Common:TxtLv"}, " ", {"source": "tables/Skill:2.desc"}], built, "en") \
        == "Lv.{0@0} Obtain 1 random survivor. CD: {0@2}"
    assert TM.compose([BEAK, {"source": "tables/Item:gone"}], built, "en") is None
    assert TM.compose([BEAK], TM.Game({"en": BUILT_EN}), "de") is None  # no text in that language


def test_the_unit_the_games_code_adds_is_kept(built):
    node = {"en": "Casualty Rate +{value}% when burning", "de": ""}
    [found] = TM.candidates(node, built, LANGS)
    assert found["id"] == "tables/Skill:1.desc" and found["clear"]
    assert found["targets"] == {"en": "Casualty Rate +{value}% when burning", "de": "Verlustrate +{value}% beim Brennen"}


def test_a_placeholder_the_games_code_fills_is_a_mismatch_until_it_is_filled(built):
    node = {"en": "Obtain 1 random survivor.", "de": ""}
    assert TM.targets(node, TM.single("tables/Skill:2.desc"), built, LANGS) == {"en": None, "de": None}
    assert [(c["id"], c["exact"]) for c in TM.candidates(node, built, LANGS)] == [("tables/Skill:2.desc", False)]  # a near one
    entry = {"source": "tables/Skill:2.desc", "fill": {"0": "119.5h", "de:0": "119,5 Std."}}
    assert TM.status_of(node, {"source": "tables/Skill:2.desc"}, built, LANGS) == ("mismatch", "tables/Skill:2.desc")
    assert TM.status_of(node, entry, built, LANGS) == ("to sync", "[[tables/Skill:2.desc|0=119.5h|de:0=119,5 Std.]]")
    assert TM.targets(node, TM.parts_of(entry), built, LANGS) == {
        "en": "Obtain 1 random survivor. CD: 119.5h", "de": "Erhalte 1 zufälligen Überlebenden. AZ: 119,5 Std."}


def test_a_game_text_and_the_number_after_it_is_a_composition(built):
    node = {"en": "Hero DMG Dealt↑ 10.00%", "de": ""}
    [found] = TM.candidates(node, built, LANGS)
    assert found["id"] == "[[tables/Benefit:1.name]] 10.00%" and found["clear"] and found["exact"]
    assert found["targets"] == {"en": "Hero DMG Dealt↑ 10.00%", "de": "Verursachter Held-SCH↑ 10.00%"}
    assert TM.status_of(node, None, built, LANGS) == ("suggested", "[[tables/Benefit:1.name]] 10.00%")


def test_a_text_with_numbers_next_to_a_game_text_is_a_composition_either_way_round(built):
    first = TM.candidates({"en": "Lv.3 Sharp Beak", "de": ""}, built, LANGS)
    assert [c["id"] for c in first] == ["[[language/Common:TxtLv|0=3]] [[tables/Item:beak_1.name]]"]  # the same text once
    assert first[0]["targets"] == {"en": "Lv.3 Sharp Beak", "de": "Lv.3 Scharfer Schnabel"}
    [second] = TM.candidates({"en": "Sharp Beak Lv.3", "de": ""}, built, LANGS)
    assert second["id"] == "[[tables/Item:beak_1.name]] [[language/Common:TxtLv|0=3]]"


@pytest.mark.parametrize("english", [
    "Lv.3 Unknown",  # the other side is no game text
    "Hero Gold 3x",  # no number to fill or to add
    "10.00%",  # a number alone is any text that is only a placeholder
    "Up 10% Now",  # the game's `Up {0}` has no unit: the English would not be the webapp's
])
def test_a_text_the_parts_do_not_make_is_not_a_composition(built, english):
    assert TM.compositions({"en": english, "de": ""}, built, LANGS) == []


def test_a_composition_is_ambiguous_when_the_game_says_it_differently_and_the_webapp_does_not_say_which():
    en = {**BUILT_EN, "tables/Benefit:2.name": "Hero DMG Dealt↑"}
    de = {**BUILT_DE, "tables/Benefit:2.name": "Schaden↑"}
    game = TM.Game({"en": en, "de": de})
    found = TM.candidates({"en": "Hero DMG Dealt↑ 10.00%", "de": ""}, game, LANGS)
    assert [c["clear"] for c in found] == [False, False] and len(found) == 2
    found = TM.candidates({"en": "Hero DMG Dealt↑ 10.00%", "de": "Schaden↑ 10.00%"}, game, LANGS)
    assert found[0]["id"] == "[[tables/Benefit:2.name]] 10.00%" and found[0]["clear"]


def test_a_common_ui_string_comes_before_one_of_a_screen(built):
    assert sorted(built.exact("Lv.{0}"), key=TM.rank) == ["language/Common:TxtLv", "language/Alliance:lv"]
    assert sorted(["language/Alliance:lv", "tables/Item:x", "language/Common:y"], key=TM.rank) == [
        "tables/Item:x", "language/Common:y", "language/Alliance:lv"]


def test_a_composed_entry_is_official_to_sync_or_missing(built):
    node = {"en": "Lv.3 Sharp Beak", "de": "Lv.3 Scharfer Schnabel"}
    entry = {"parts": [LEVEL, " ", BEAK]}
    template = "[[language/Common:TxtLv|0=3]] [[tables/Item:beak_1.name]]"
    assert TM.status_of(node, entry, built, LANGS) == ("official", template)
    assert TM.status_of({**node, "de": "Lv.3 Schnabel"}, entry, built, LANGS)[0] == "to sync"
    assert TM.status_of(node, {"parts": [{"source": "tables/Item:gone"}, " 5"]}, built, LANGS) == ("missing", "[[tables/Item:gone]] 5")


def test_accept_suggestions_takes_a_composition_as_parts_and_used_lists_every_part(tmp_path):
    path = tmp_path / "text_mapping.json"
    table = [{"location": "a", "status": "suggested", "source": "[[language/Common:TxtLv|0=3]] [[tables/Item:beak_1.name]]"}]
    assert TM.accept_suggestions(table, path) == 1
    assert Mp.load(path) == {"a": {"parts": [LEVEL, " ", BEAK]}}
    TM.set_entry("b", TM.single("tables/Item:beak_1.name"), path)
    TM.set_entry("c", None, path)
    assert TM.used(TM.load(path)) == {"language/Common:TxtLv": ["a"], "tables/Item:beak_1.name": ["a", "b"]}


def test_plan_writes_a_composition_in_every_language(built):
    done = TM.plan({"x": {"parts": [LEVEL, " ", BEAK]}, "y": {"parts": [{"source": "tables/Item:gone"}, " 5"]}},
                   {"x": {"en": "lv.3 sharp beak", "de": ""}, "y": {"en": "Gone 5"}}, built, LANGS)
    assert [(d["location"], d["lang"], d["action"], d["new"]) for d in done] == [
        ("x", "en", "write", "Lv.3 Sharp Beak"), ("x", "de", "write", "Lv.3 Scharfer Schnabel"), ("y", "", "skipped", "")]
    assert done[-1]["note"] == "[[tables/Item:gone]] 5 is not in the extracted texts"
