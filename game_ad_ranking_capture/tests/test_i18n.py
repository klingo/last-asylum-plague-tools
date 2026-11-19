"""The viewer's languages: the files agree with English, the page uses exactly the keys that exist, the helpers work."""

import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request

import pytest

import config as C
import viewer_server
from html_helpers import body_text, inline_scripts
from test_screens_capture import fetch

LANGUAGES = ("en", "de", "ru")
PLURAL_FORMS = {"en": {"one", "other"}, "de": {"one", "other"}, "ru": {"one", "few", "many", "other"}}
PAGE = (C.VIEWER_DIR / "index.html").read_text(encoding="utf-8")


def load(language: str) -> dict:
    return json.loads((C.VIEWER_DIR / "i18n" / f"{language}.json").read_text(encoding="utf-8"))


def entries(node: dict, prefix: str = "") -> dict[str, str | dict]:
    """{"info.players": {...plural forms}, "col.player": "Player", ...}: a text, or the forms of a plural."""
    found = {}
    for key, value in node.items():
        path = prefix + key
        if isinstance(value, dict) and "other" in value:
            found[path] = value
        elif isinstance(value, dict):
            found.update(entries(value, path + "."))
        else:
            found[path] = value
    return found


def placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", text))


def test_every_language_has_the_keys_of_english_and_nothing_else():
    english = entries(load("en"))
    for language in LANGUAGES[1:]:
        assert list(entries(load(language))) == list(english), language  # same keys, same order


def test_the_plural_forms_are_the_ones_the_language_has():
    for language in LANGUAGES:
        for key, value in entries(load(language)).items():
            if isinstance(value, dict):
                assert set(value) == PLURAL_FORMS[language], f"{language}: {key}"


def test_placeholders_are_the_same_in_every_language_and_no_text_is_empty():
    english = entries(load("en"))
    for language in LANGUAGES:
        for key, value in entries(load(language)).items():
            forms = value if isinstance(value, dict) else {"": value}
            for form, text in forms.items():
                assert text.strip(), f"{language}: {key} {form} is empty"
                reference = english[key]
                expected = placeholders(next(iter(reference.values())) if isinstance(reference, dict) else reference)
                assert placeholders(text) == expected, f"{language}: {key} {form}"


def test_a_translation_is_not_a_copy_of_english_unless_the_word_is_the_same():
    english = entries(load("en"))
    same = {"de": set(), "ru": set()}  # words that really are the same
    for language in LANGUAGES[1:]:
        for key, value in entries(load(language)).items():
            if isinstance(value, str) and key not in same[language]:
                assert value != english[key], f"{language}: {key} is not translated"


def used_keys() -> tuple[set[str], set[str]]:
    """(the keys the page asks for by name, the groups it asks for with a computed key such as "weekday." + day)."""
    asked = set(re.findall(r'\bt\("([\w.]+)"', PAGE)) | set(re.findall(r'data-i18n="([\w.]+)"', PAGE))
    groups = set(re.findall(r'\bt\("([\w]+\.)" \+', PAGE))
    return {key for key in asked if key not in groups}, groups


def test_the_page_uses_exactly_the_texts_that_exist():
    names, groups = used_keys()
    english = entries(load("en"))
    assert names <= set(english), f"missing in en.json: {sorted(names - set(english))}"
    unused = [k for k in english if k not in names and not any(k.startswith(g) for g in groups)]
    assert not unused, f"in en.json but not used by the page: {unused}"
    assert groups == {"weekday.", "color."}
    assert {k for k in english if k.startswith("weekday.")} == {f"weekday.{d}" for d in C.DAYS}


def test_no_text_of_the_page_is_hard_coded():
    script = inline_scripts(PAGE)[0]
    for word in ("Player", "Alliance", "Total", "Average", "Median", "preliminary", "Nobody", "No rankings"):
        assert f'"{word}' not in script and f"'{word}" not in script, word
    assert body_text(PAGE) == [], "a text in the markup: it belongs in the language files (data-i18n)"


# -- the helpers, run in Node
NODE = shutil.which("node")


def run_node(expression: str):
    script = f"const I = require({str(C.VIEWER_DIR / 'i18n.js')!r}); console.log(JSON.stringify({expression}))"
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_language_is_the_saved_one_else_the_browsers_else_english():
    pick = run_node(
        """[
        I.pickLanguage("de", ["en-US"]),
        I.pickLanguage(null, ["fr-FR", "ru-RU", "de"]),
        I.pickLanguage(null, ["de-CH"]),
        I.pickLanguage(null, ["DE"]),
        I.pickLanguage(null, ["fr", "es"]),
        I.pickLanguage("xx", ["de"]),
        I.pickLanguage(null, undefined),
        I.pickLanguage(null, [])
    ]"""
    )
    assert pick == ["de", "ru", "de", "de", "en", "de", "en", "en"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_texts_are_found_filled_and_pluralised_in_node():
    dicts = {language: load(language) for language in LANGUAGES}
    script = f"""const dicts = {json.dumps(dicts, ensure_ascii=False)};
        const t = (lang, key, vars) => I.translate(dicts, lang, key, vars);
        console.log(JSON.stringify([
          t("en", "col.player"), t("de", "col.player"), t("ru", "col.player"),
          t("en", "header.mine_named", {{name: "Mice"}}),
          t("en", "info.players", {{n: 1}}), t("en", "info.players", {{n: 0}}), t("en", "info.players", {{n: 2}}),
          t("ru", "info.players", {{n: 1}}), t("ru", "info.players", {{n: 2}}), t("ru", "info.players", {{n: 5}}),
          t("ru", "info.players", {{n: 21}}), t("ru", "info.players", {{n: 11}}), t("ru", "info.players", {{n: 112}}),
          t("de", "compare.members", {{n: 1}}), t("de", "compare.members", {{n: 12}}),
          t("ru", "no.such.key"), t("en", "legend.step", {{color: "red", phase: 5}})
        ]))"""
    program = f"const I = require({str(C.VIEWER_DIR / 'i18n.js')!r});\n{script}"
    done = subprocess.run([NODE, "-e", program], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [
        "Player", "Spieler", "Игрок",
        "My alliance (Mice)",
        "1 player", "0 players", "2 players",
        "1 игрок", "2 игрока", "5 игроков", "21 игрок", "11 игроков", "112 игроков",
        "1 Mitglied",
        "12 Mitglieder",
        "no.such.key", "red ~ phase 5 ({points})",
    ]  # fmt: skip


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_language_without_a_text_falls_back_to_english():
    expression = """I.translate({en: {a: {b: "English"}, c: "only English"}, de: {a: {b: "Deutsch"}}}, "de", "c")"""
    assert run_node(expression) == "only English"
    assert run_node(expression.replace('"c")', '"a.b")')) == "Deutsch"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_helper_script_is_valid_javascript():
    done = subprocess.run([NODE, "--check", str(C.VIEWER_DIR / "i18n.js")], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


# -- served to the page
def test_the_server_serves_the_helper_and_the_language_files_and_nothing_else(tmp_path):
    server, url = viewer_server.start(tmp_path)
    try:
        assert b"pickLanguage" in fetch(url + "i18n.js")[1]
        for language in LANGUAGES:
            assert json.loads(fetch(url + f"i18n/{language}.json")[1]) == load(language)
        for bad in ("i18n/xx.json", "i18n/../index.html", "i18n/en", "i18n/EN.json", "viewer/index.html"):
            with pytest.raises(urllib.error.HTTPError) as error:
                fetch(url + bad)
            assert error.value.code == 404, bad
    finally:
        viewer_server.stop(server)
