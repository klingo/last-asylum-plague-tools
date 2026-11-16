import pytest

import config as C
import state as S
import texts as T


def test_parse_language_splits_at_the_first_comma_and_unescapes():
    text = "KEY,Chinese\nplain,Hello, world\nmulti,One\\nTwo\nempty,\nnocomma\nquote,It\\'s\n"
    assert T.parse_language(text) == {"plain": "Hello, world", "multi": "One\nTwo", "quote": "It's"}


def test_parse_table_takes_the_string_fields_of_every_row():
    text = (
        'local data = {\n'
        '\t["item_gold"] = {\t["id"] = "item_gold",\t["name"] = "Gold",\t["description"] = "Don\\\'t \\"spend\\"\\nit",},\n'
        '\t["5"] = {\t["id"] = 5,\t["name"] = "Antitoxin",\t["empty"] = "",\t["limit"] = 9,},\n'
        '}return data'
    )
    assert T.parse_table(text) == {
        "item_gold.name": "Gold", "item_gold.description": 'Don\'t "spend"\nit', "5.name": "Antitoxin"}


def test_clean_takes_the_markup_off_but_keeps_the_words_in_brackets():
    assert T.clean("[c][ec413a]MR Armor[-][/c]") == "MR Armor"
    assert T.clean(" [b]100%[/b] of [Battle Will] [ABCDEF]x ") == "100% of [Battle Will] x"
    assert T.clean("[c][11bfff80]Energy DMG[-][/c]") == "Energy DMG"


def test_norm_ignores_markup_case_spacing_apostrophes_and_placeholder_names():
    assert T.norm("[c][fa5a5a]Warrior  Hero DMG +{0}%[-][/c]") == T.norm("warrior hero dmg +{value}%")
    assert T.norm("Chief’s Coin") == T.norm("chief's  coin")
    assert T.norm("Antitoxin") != T.norm("Antitoxins")


def test_adapt_renames_the_placeholders_by_their_order_in_the_english_texts():
    assert T.adapt("Gewährt {1} Gegengift, {0} mal.", "Grants {0} Antitoxin, {1} times.", "Grants {amount} Antitoxin, {times} times.") \
        == "Gewährt {times} Gegengift, {amount} mal."
    assert T.adapt("[c][ec413a]MR Rüstung[-][/c]", "[c]MR Armor[-][/c]", "MR Armor") == "MR Rüstung"
    assert T.adapt("{0} und {0}", "{0} and {0}", "{n} and {n}") == "{n} und {n}"


@pytest.mark.parametrize("game,game_en,webapp_en", [
    ("{0} {1}", "{0} {1}", "{value}"),  # the webapp has fewer
    ("x", "x", "x {value}"),  # the webapp has more
    ("{0} {2}", "{0}", "{value}"),  # the translation has one the English does not
])
def test_adapt_gives_up_when_the_placeholders_do_not_pair_up(game, game_en, webapp_en):
    assert T.adapt(game, game_en, webapp_en) is None


def write_game(root, files):
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_load_reads_every_language_of_both_folders_and_names_the_texts_by_file_and_key(tmp_path):
    write_game(tmp_path, {
        "language_F/en/Item.txt": "KEY,Chinese\ngold,Gold\n",
        "language_F/de/Item.txt": "KEY,Chinese\ngold,Gold\n",
        "language_F/fr/Item.txt": "KEY,Chinese\ngold,Or\n",
        "basedb_F/en/Item.txt": '\t["a"] = {\t["id"] = "a",\t["name"] = "Axe",},\n',
        "basedb_F/de/Item.txt": '\t["a"] = {\t["id"] = "a",\t["name"] = "Axt",},\n',
        "basedb_F/basedata_jit/Item.bin": "not text",
    })
    assert T.languages(tmp_path) == ["en", "de", "fr"]
    texts = T.load(tmp_path)
    assert texts["en"] == {"language/Item:gold": "Gold", "tables/Item:a.name": "Axe"}
    assert texts["de"]["tables/Item:a.name"] == "Axt" and texts["fr"] == {"language/Item:gold": "Or"}
    assert T.folder_of("tables/Item:a.name") == "tables/Item"


def test_no_texts_extracted_yet_is_an_empty_result(tmp_path):
    assert T.languages(tmp_path / "nothing") == [] and T.load(tmp_path / "nothing") == {}


@pytest.fixture
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "OUT", tmp_path / "out")
    return C.OUT


def marks(index, text_id):
    return {lang: mark[1:] for lang, mark in index["texts"][text_id].items()}


def test_update_index_records_when_a_text_appeared_changed_and_left(out):
    first = T.update_index(1, texts={"en": {"a": "Gold", "b": "Gem"}, "de": {"a": "Gold", "b": "Edelstein"}})
    assert first["first"] == 1 and marks(first, "a") == {"en": [1, 0], "de": [1, 0]}

    # a game update: b changed in German only, c is new (in both languages), a is gone
    second = T.update_index(2, texts={"en": {"b": "Gem", "c": "Ore"}, "de": {"b": "Juwel", "c": "Erz"}})
    assert second["first"] == 1  # the first run stays the one that held everything from the start
    assert marks(second, "b") == {"en": [1, 0], "de": [1, 2]}
    assert marks(second, "c") == {"en": [2, 0], "de": [2, 0]}
    assert "a" not in second["texts"]

    third = T.update_index(3, texts={"en": {"b": "Gem", "c": "Ore"}, "de": {"b": "Juwel", "c": "Erz"}})  # nothing changed
    assert third["texts"] == second["texts"]
    assert T.load_index() == third  # saved


def test_a_language_the_game_adds_is_added_in_that_run(out):
    T.update_index(1, texts={"en": {"a": "Gold"}})
    index = T.update_index(2, texts={"en": {"a": "Gold"}, "fr": {"a": "Or"}})
    assert marks(index, "a") == {"en": [1, 0], "fr": [2, 0]}


def test_current_index_makes_one_in_the_current_run_when_there_is_none(out, tmp_path):
    write_game(tmp_path, {"language_F/en/Item.txt": "KEY,Chinese\ngold,Gold\n"})
    S.save_index({"meta": {"run": 4, "baseline": 0, "runs": {}}, "sprites": {}})
    index = T.current_index(tmp_path)
    assert index["first"] == 4 and marks(index, "language/Item:gold") == {"en": [4, 0]}
    write_game(tmp_path, {"language_F/en/Item.txt": "KEY,Chinese\ngold,Gold\nore,Ore\n"})
    assert "language/Item:ore" not in T.current_index(tmp_path)["texts"]  # the saved one is used: extract updates it


def test_norm_ignores_a_percent_after_a_placeholder_only():
    assert T.norm("Casualty Rate +{value}% when") == T.norm("casualty rate +{0} when")
    assert T.norm("Casualty Rate +{0} % when") == T.norm("Casualty Rate +{0} when")
    assert T.norm("Gain 5% more") != T.norm("Gain 5 more")


def test_adapt_gives_a_number_the_webapp_writes_with_a_percent_its_unit():
    assert T.adapt("Verlustrate +{0} beim", "Casualty Rate +{0} when", "Casualty Rate +{value}% when") == "Verlustrate +{value}% beim"
    assert T.adapt("{0} und {1}", "{0} and {1}", "{a}% and {b}") == "{a}% und {b}"  # per placeholder
    assert T.adapt("Rate +{0}% x", "Rate +{0}% x", "Rate +{value}% x") == "Rate +{value}% x"  # not twice
    assert T.adapt("Rate +{0} % x", "Rate +{0}% x", "Rate +{value}% x") == "Rate +{value} % x"  # the game's own stays
    assert T.adapt("Rate +{0} x", "Rate +{0} x", "Rate +{value} x") == "Rate +{value} x"  # the webapp has no unit: none added
