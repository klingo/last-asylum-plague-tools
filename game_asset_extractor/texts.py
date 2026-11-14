"""The game's texts: reading the extracted files, cleaning them, and remembering when each one appeared or changed.

The language data of the game (`config.GAME_TEXTS`, written by `extract.py` from the bundles of the kind "data") is
plain text in two shapes, one folder per language (`en`, `de`, ...):

    language_F/<lang>/<File>.txt    `KEY,Chinese` header, then `key,text` lines (split at the first comma)
    basedb_F/<lang>/<Table>.txt     a Lua table, one row per line: `\\t["<row>"] = {\\t["id"] = 1,\\t["name"] = "...",},`

A text has one id in every language: `language/<File>:<key>` or `tables/<Table>:<row>.<field>`. Newlines are written
`\\n`, Lua also escapes quotes. The texts carry NGUI markup (`[c][ec413a]red[-][/c]`, `[b]`) and numbered placeholders
(`{0}`); `clean` takes the markup off, `norm` makes the key texts are compared by, `adapt` gives a game text the
webapp's placeholder names.

`out/texts.json` is what the pictures' `added` / `changed` runs are for the pictures: for every text and language the
hash of its raw text and the extract run that first saw it (`added`) and last changed it (`changed`, 0 = never), so the
text browser can show what a resource version added or changed (`meta.runs` of `out/index.json` says which version a
run was). `update_index` brings it up to date after an extract; without a file yet the texts already on disk count as
added in the current run.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import config as C
import history as H
import state as S

LANGUAGE_DIR, TABLE_DIR = "language_F", "basedb_F"
FOLDERS = {LANGUAGE_DIR: "language", TABLE_DIR: "tables"}  # the game's folder -> the first part of a text id
MARKUP = re.compile(r"\[(?:/?[cbius]|-|[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?)\]")
PLACEHOLDER = re.compile(r"\{[^{}]*\}")
ROW = re.compile(r'^\t\["(.*?)"\] = \{(.*)\},$')
FIELD = re.compile(r'\["(\w+)"\] = "((?:[^"\\]|\\.)*)"')
ESCAPE = re.compile(r"\\(.)")
ESCAPES = {"n": "\n", "t": "\t"}


def unescape(text: str) -> str:
    """`\\n` as a newline, `\\'`, `\\"`, `\\\\` as the character itself."""
    return ESCAPE.sub(lambda m: ESCAPES.get(m.group(1), m.group(1)), text)


def parse_language(text: str) -> dict[str, str]:
    """{key: text} of a `language_F` file (the header line and empty texts are left out)."""
    found = {}
    for line in text.splitlines()[1:]:
        key, comma, value = line.partition(",")
        if comma and value.strip():
            found[key] = unescape(value)
    return found


def parse_table(text: str) -> dict[str, str]:
    """{"<row>.<field>": text} of a `basedb_F` file: the string fields of every row, `id` and empty ones left out."""
    found = {}
    for line in text.splitlines():
        row = ROW.match(line)
        if row:
            for field, value in FIELD.findall(row.group(2)):
                if field != "id" and value.strip():
                    found[f"{row.group(1)}.{field}"] = unescape(value)
    return found


def folder_of(text_id: str) -> str:
    """`language/Item` or `tables/Item`: what the browser filters by."""
    return text_id.partition(":")[0]


def languages(root: Path = C.GAME_TEXTS) -> list[str]:
    """The languages with extracted texts: English first, then by code. (`basedb_F/basedata_jit` holds only tables that
    are not text.)"""
    found = set()
    for folder in FOLDERS:
        if (root / folder).is_dir():
            found.update(p.name for p in (root / folder).iterdir() if p.is_dir() and any(p.glob("*.txt")))
    return sorted(found, key=lambda lang: (lang != "en", lang))


def load(root: Path = C.GAME_TEXTS) -> dict[str, dict[str, str]]:
    """{language: {text id: raw text}} of everything extracted, the texts of a file in the order the game has them."""
    texts: dict[str, dict[str, str]] = {}
    for lang in languages(root):
        entries = texts[lang] = {}
        for folder, parser in ((LANGUAGE_DIR, parse_language), (TABLE_DIR, parse_table)):
            for path in sorted((root / folder / lang).glob("*.txt")):
                for key, value in parser(path.read_text(encoding="utf-8", errors="replace")).items():
                    entries[f"{FOLDERS[folder]}/{path.stem}:{key}"] = value
    return texts


def clean(text: str) -> str:
    """`text` without the game's colour / style markup, trimmed: what goes into the webapp."""
    return MARKUP.sub("", text).strip()


def norm(text: str) -> str:
    """The key two texts are called the same by: clean, lower case, one space between words, a typographic apostrophe
    as a plain one, every placeholder as `{}`."""
    text = PLACEHOLDER.sub("{}", clean(text).replace("’", "'"))
    return " ".join(text.lower().split())


def placeholders(text: str) -> list[str]:
    """The distinct placeholders of `text` in the order they first appear."""
    return list(dict.fromkeys(PLACEHOLDER.findall(text)))


def adapt(game: str, game_en: str, webapp_en: str) -> str | None:
    """`game` (a game text in any language, with its English `game_en`) cleaned, with the game's placeholders (`{0}`,
    `{1}`) named as the webapp's English `webapp_en` names its own (`{value}`), paired by their order in the two English
    texts. None when they do not pair up: the texts have a different number of placeholders (or the game text has one
    its English does not)."""
    game_names, webapp_names = placeholders(clean(game_en)), placeholders(clean(webapp_en))
    if len(game_names) != len(webapp_names):
        return None
    rename = dict(zip(game_names, webapp_names))
    text = clean(game)
    if any(name not in rename for name in placeholders(text)):
        return None
    return PLACEHOLDER.sub(lambda m: rename[m.group(0)], text)


# --- when did a text appear or change ------------------------------------------------------------------------------
def index_path() -> Path:
    return C.OUT / "texts.json"


def digest(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:8]


def load_index() -> dict:
    """out/texts.json: {"first": run, "texts": {text id: {language: [hash, added, changed]}}} (see the module doc)."""
    try:
        index = json.loads(index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = None
    return index if isinstance(index, dict) and "texts" in index else {"first": None, "texts": {}}


def update_index(run: int, root: Path = C.GAME_TEXTS, texts: dict[str, dict[str, str]] | None = None) -> dict:
    """Compare the extracted texts with the index and save it: a text (in a language) that is new was `added` in `run`,
    one whose raw text differs from before `changed` in `run`, one no longer in the game is dropped. Without an index
    yet everything counts as added in `run`, and `first` says that this run holds everything that was there from the
    start; unless `history.json` knows the texts (a rebuilt cache): then each gets the runs recorded there. Returns the index."""
    old = load_index()
    known = H.load()["texts"] if old["first"] is None else {"first": None}
    first = old["first"] if old["first"] is not None else (known["first"] if known["first"] is not None else run)
    texts = load(root) if texts is None else texts
    new: dict[str, dict[str, list]] = {}
    for lang, entries in texts.items():
        for text_id, text in entries.items():
            mark = digest(text)
            before = old["texts"].get(text_id, {}).get(lang)
            if before is None and known["first"] is not None:
                entry = [mark, *known["changes"].get(text_id, {}).get(lang, [known["first"], 0])]
            elif before is None:
                entry = [mark, run, 0]
            elif before[0] != mark:
                entry = [mark, before[1], run]
            else:
                entry = before
            new.setdefault(text_id, {})[lang] = entry
    index = {"first": first, "texts": new}
    S.write_json(index_path(), index, indent=None)
    return index


def current_index(root: Path = C.GAME_TEXTS) -> dict:
    """The index for the browser and the mapping: the saved one, or (nothing saved yet) one made now, counting the texts
    as added in the current extract run."""
    if index_path().is_file():
        return load_index()
    return update_index(S.load_index()["meta"]["run"], root)
