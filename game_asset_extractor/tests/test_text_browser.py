import json
import re
import shutil
import subprocess

import pytest

import state as S
import text_browser as TB
import text_mapping as TM
import texts as T

TEXTS = {
    "en": {"tables/Item:gold.name": "Gold", "language/Common:ok": "[c][11bfff]OK[-][/c]", "tables/Item:ore.name": "Ore"},
    "de": {"tables/Item:gold.name": "Gold", "language/Common:ok": "OK"},
}
INDEX = {"first": 1, "texts": {
    "tables/Item:gold.name": {"en": ["a", 1, 0], "de": ["b", 1, 3]},
    "language/Common:ok": {"en": ["c", 1, 0], "de": ["d", 2, 0]},
    "tables/Item:ore.name": {"en": ["e", 3, 0]},
}}
META = {"run": 3, "baseline": 1, "runs": {"1": {"version": "1.0.1"}, "2": {"version": "1.0.2"}, "3": {"version": "1.0.3"}}}


def test_build_data_orders_by_folder_and_says_per_text_and_language_when_it_came_or_changed():
    header, columns = TB.build_data(TEXTS, INDEX, META, {"pack_data:items.gold.name": {"source": "tables/Item:gold.name"}})
    assert header["ids"] == ["language/Common:ok", "tables/Item:gold.name", "tables/Item:ore.name"]
    assert header["folders"] == [("language/Common", 1), ("tables/Item", 2)]
    assert header["langs"] == ["en", "de"] and header["baseline"] == 1 and header["first"] == 1
    assert header["runs"] == {"1": "1.0.1", "2": "1.0.2", "3": "1.0.3"}
    assert header["added"] == [1, 1, 3] and header["changed"] == [0, 3, 0]  # a text: the first language to have it, the last change
    assert header["used"] == {"1": ["pack_data:items.gold.name"]}
    assert columns["en"] == {"t": ["OK", "Gold", "Ore"], "a": [1, 1, 3], "c": [0, 0, 0]}  # the markup is gone
    assert columns["de"] == {"t": ["OK", "Gold", ""], "a": [2, 1, 0], "c": [0, 3, 0]}  # no German for the ore: blank, not new


def test_write_makes_the_page_and_its_data_files(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "load", lambda: TEXTS)
    monkeypatch.setattr(T, "current_index", lambda: INDEX)
    monkeypatch.setattr(S, "load_index", lambda: {"meta": META, "sprites": {}})
    monkeypatch.setattr(TM, "load", lambda: {})
    page = TB.write(tmp_path / "texts")
    assert page == tmp_path / "texts" / "index.html" and '<script src="ids.js">' in page.read_text(encoding="utf-8")
    assert json.loads((tmp_path / "texts" / "ids.js").read_text(encoding="utf-8").removeprefix("window.TEXTS = ").rstrip(";\n"))["ids"][0] == "language/Common:ok"
    assert (tmp_path / "texts" / "de.js").read_text(encoding="utf-8").startswith('(window.TEXT_LANGS = window.TEXT_LANGS || {})["de"] = {')


def test_the_page_script_and_the_data_files_are_valid_javascript(tmp_path, monkeypatch):
    """The page is a Python string: a stray escape in it would break the whole script."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    monkeypatch.setattr(T, "load", lambda: TEXTS)
    monkeypatch.setattr(T, "current_index", lambda: INDEX)
    monkeypatch.setattr(S, "load_index", lambda: {"meta": META, "sprites": {}})
    monkeypatch.setattr(TM, "load", lambda: {})
    TB.write(tmp_path / "texts")
    script = tmp_path / "page.js"
    script.write_text(re.search(r"<script>([\s\S]*?)</script>", TB.PAGE).group(1), encoding="utf-8")
    for file in (script, tmp_path / "texts" / "ids.js", tmp_path / "texts" / "en.js"):
        result = subprocess.run([node, "--check", str(file)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
