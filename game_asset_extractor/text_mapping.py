"""Text mapping: which game text each of the webapp's texts is, and keeping the webapp's wording and translations in step.

A webapp text is a localized string (`{"en": "...", "de": "..."}`) in `data/pack_data.json`, `events.json`,
`hero_skills.json`, `lord_specialty.json` or `raven_epigraphs.json`, named by its location `<file>:<path>` (`pack_data:items.antitoxin.name`;
a list item by its `id` when it has one, else its number: `events:event_rotations.alliance_duel.phases[territory].name`).
`text_mapping.json` (next to this file, committed) says which game text it is, by the game text's id (see `texts.py`):

    "pack_data:items.antitoxin.name": {"source": "tables/ItemIcon:5.name"}
    "hero_skills:heroes.marlena.note": {"source": null}      the webapp's own text: nothing to look up in the game

Some texts the game puts together in its code: the number's unit (`+{0}` where the webapp says `+{value}%`: `texts.adapt`
puts the `%` back), a placeholder the code fills (`CD: {0}`), a stat and its value (`Hero DMG Dealt↑` + `10.00%`), a prefix
(`Lv.{0}` + `Sharp Beak`). An entry is then made of parts, game texts (each with the `fill` of its placeholders: `{0}` is
`119.5h`, `de:0` for one language only) and literal text, the same in every language:

    "pack_data:items.lv3_sharp_beak.name": {"parts": [{"source": "language/Common:TxtLv", "fill": {"0": "3"}}, " ",
                                                      {"source": "tables/Item:item_uav_component_3_3.name"}]}
    "…:random_visitor.description": {"source": "tables/LordJobSkill:1021.desc", "fill": {"0": "119.5h"}}

The editor writes one as a template (`parse_template`, `template_of`): `[[language/Common:TxtLv|0=3]] [[tables/Item:...]]`,
a text with no part but one game text is just its id.

Texts are matched by their English (`texts.norm`: markup, case, spacing, placeholder names and a `%` after a placeholder
don't count), so the game's other languages come with the match. A text that is no game text but is made of two (a game
text and a number, or a placeholder text of the game with its numbers filled next to a game text, `compositions`) is
matched that way, if the parts make its English again. A near match (`NEAR` percent alike, found with rapidfuzz) is a
possible typo and never taken without asking. An unmapped text is

    suggested   its English is in the game (or is made of game texts), and the game has one translation of it (or the
                webapp's own picks one of several)
    ambiguous   its English is in the game with different translations, none of them the webapp's
    near        not in the game, but a text of the game is nearly the same (a typo, another word order)
    unmapped    nothing like it in the game

and a mapped one is

    official    every language the game has says what the webapp says
    to sync     the webapp's text differs from the game's (or is empty) in a language
    mismatch    the placeholders do not pair up (`{0}` against nothing): nothing is synced
    missing     the game text is no longer there
    none        marked as the webapp's own text

`sync` writes the game's text (markup taken off, placeholders named as the webapp names them) into every language the
webapp has, English included, and formats the files with the webapp's own prettier so a git diff shows only the strings.
Without `apply` it only lists what it would do.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from rapidfuzz import fuzz, process

import config as C
import mapping as Mp
import texts as T

PATH = C.HERE / "text_mapping.json"
DATA_FILES = ("pack_data", "events", "hero_skills", "lord_specialty", "raven_epigraphs")
STATUSES = ("official", "to sync", "mismatch", "missing", "suggested", "ambiguous", "near", "unmapped", "none")
NEAR = 85  # percent: how alike two English texts must be to be offered as a possible typo
CANDIDATES = 12  # kept per webapp text
SEARCH_LIMIT = 150
LANGUAGE = re.compile(r"[a-z]{2}(?:-[A-Za-z]+)?")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
TRAILING_NUMBER = re.compile(r"(.*?\S)(\s+[+-]?\d[\d.,]*%?)")  # `Hero DMG Dealt↑ 10.00%`: a text and the number after it
LETTER = re.compile(r"[^\W\d_]")
TEMPLATE_PART = re.compile(r"\[\[([^\[\]|]+)((?:\|[^\[\]|]*)*)\]\]")  # [[id]] / [[id|0=3|de:0=3,5]]
TEXT_ID = re.compile(rf"(?:{'|'.join(T.FOLDERS.values())})/[^\s\[\]|]+:[^\s\[\]|]+")
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# --- the webapp's texts --------------------------------------------------------------------------------------------
def is_text(node) -> bool:
    """A localized string: an object of language codes and texts, with English."""
    return isinstance(node, dict) and isinstance(node.get("en"), str) and all(
        LANGUAGE.fullmatch(key) and isinstance(value, str) for key, value in node.items())


def walk(node, path: str, found: dict[str, dict]) -> None:
    if is_text(node):
        found[path] = node
    elif isinstance(node, dict):
        for key, value in node.items():
            walk(value, f"{path}.{key}" if path else key, found)
    elif isinstance(node, list):
        for number, value in enumerate(node):
            name = value["id"] if isinstance(value, dict) and isinstance(value.get("id"), str) else number
            walk(value, f"{path}[{name}]", found)


def read_webapp(data_dir: Path = C.WEBAPP_DATA) -> tuple[dict[str, dict], dict[str, dict]]:
    """(the data files, the texts): `{file: {data, crlf}}` as parsed, and `{location: the localized object in them}`,
    which is what `sync` changes before it writes the files."""
    C.require_webapp(data_dir)
    docs, found = {}, {}
    for stem in DATA_FILES:
        raw = (data_dir / f"{stem}.json").read_bytes().decode("utf-8")
        docs[stem] = {"data": json.loads(raw), "crlf": "\r\n" in raw}
        texts: dict[str, dict] = {}
        walk(docs[stem]["data"], "", texts)
        found.update({f"{stem}:{path}": node for path, node in texts.items()})
    return docs, found


def webapp_languages(i18n_dir: Path = C.WEBAPP_I18N) -> list[str]:
    """The languages the webapp speaks (a `<lang>.json` in its i18n folder): English first."""
    C.require_webapp(i18n_dir)
    return sorted((p.stem for p in i18n_dir.glob("*.json")), key=lambda lang: (lang != "en", lang))


# --- the game's texts, for matching --------------------------------------------------------------------------------
def rank(text_id: str) -> tuple[int, str]:
    """Where to look first: a table's text (an item's name) before a UI string that happens to say the same, the common UI
    strings (`language/Common`, `Lv.{0}`) before those of one screen."""
    return (0 if text_id.startswith("tables/") else 1 if text_id.startswith("language/Common:") else 2, text_id)


class Game:
    """The extracted texts ({language: {id: raw text}}), indexed by the normalized English for exact matching and over
    those for near matching (what was asked is remembered: the same text is asked for on every redraw)."""

    def __init__(self, texts: dict[str, dict[str, str]]):
        self.texts = texts
        self.by_norm: dict[str, list[str]] = {}
        for text_id, text in texts.get("en", {}).items():
            self.by_norm.setdefault(T.norm(text), []).append(text_id)
        self.norms = list(self.by_norm)
        self.asked: dict[str, list[tuple[str, int]]] = {}
        self.lower: dict[str, dict[str, str]] | None = None

    def text(self, lang: str, text_id: str) -> str | None:
        return self.texts.get(lang, {}).get(text_id)

    def exact(self, english: str) -> list[str]:
        return sorted(self.by_norm.get(T.norm(english), ()), key=rank)

    def near(self, english: str, limit: int = CANDIDATES) -> list[tuple[str, int]]:
        """[(id, percent)] of the texts that are `NEAR` percent alike (the same words in another order count), the most
        alike first; the text itself (an exact match) is not among them."""
        query = T.norm(english)
        if query not in self.asked:
            best: dict[str, float] = {}
            for scorer in (fuzz.ratio, fuzz.token_sort_ratio):
                for choice, score, _ in process.extract(query, self.norms, scorer=scorer, processor=None, score_cutoff=NEAR, limit=limit):
                    best[choice] = max(score, best.get(choice, 0))
            best.pop(query, None)
            ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))
            self.asked[query] = [(text_id, round(score)) for choice, score in ranked for text_id in self.by_norm[choice][:3]]
        return self.asked[query][:limit]

    def search(self, query: str, limit: int = SEARCH_LIMIT) -> list[str]:
        """The ids whose id or text (in any language) contains `query`, case-insensitive."""
        query = query.strip().lower()
        if len(query) < 2:
            return []
        if self.lower is None:
            self.lower = {lang: {i: t.lower() for i, t in entries.items()} for lang, entries in self.texts.items()}
        found: dict[str, None] = {}
        for entries in self.lower.values():
            for text_id, text in entries.items():
                if query in text or query in text_id.lower():
                    found[text_id] = None
                    if len(found) >= limit:
                        return list(found)
        return list(found)


# --- what a mapping entry is made of ------------------------------------------------------------------------------
def single(text_id: str) -> list:
    """The parts of an entry that is one game text."""
    return [{"source": text_id}]


def parts_of(entry: dict) -> list | None:
    """The parts of a mapping entry (game texts `{"source", "fill"?}` and literal strings), None for the webapp's own text."""
    if "parts" in entry:
        return entry["parts"]
    return None if entry.get("source") is None else [entry]


def entry_of(parts: list) -> dict:
    """The mapping entry that says `parts`: the short form when it is one game text."""
    return dict(parts[0]) if len(parts) == 1 and isinstance(parts[0], dict) else {"parts": parts}


def template_of(parts: list) -> str:
    """`parts` as the editor writes them: a game text `[[id]]` (`[[id|0=3|de:0=3,5]]` with its fill), the rest as it is; a
    single game text without a fill is its id alone."""
    if len(parts) == 1 and isinstance(parts[0], dict) and not parts[0].get("fill"):
        return parts[0]["source"]
    return "".join(part if isinstance(part, str) else
                   f"[[{part['source']}{''.join(f'|{name}={value}' for name, value in part.get('fill', {}).items())}]]"
                   for part in parts)


def parse_template(text: str) -> list:
    """The parts a template (`template_of`) says. ValueError, with what is wrong, for one that is no template."""
    if TEXT_ID.fullmatch(text.strip()):
        return single(text.strip())
    parts, at = [], 0
    for match in TEMPLATE_PART.finditer(text):
        parts.append(text[at:match.start()])
        part, fill = {"source": match.group(1).strip()}, {}
        for pair in match.group(2).split("|")[1:]:
            name, equals, value = pair.partition("=")
            if not equals or not name.strip():
                raise ValueError(f"'{pair}' is not name=value")
            fill[name.strip()] = value.strip()
        parts.append({**part, "fill": fill} if fill else part)
        at = match.end()
    parts.append(text[at:])
    parts = [part for part in parts if part != ""]
    if any(isinstance(part, str) and ("[[" in part or "]]" in part) for part in parts):
        raise ValueError("a [[ or ]] is not closed")
    if not any(isinstance(part, dict) for part in parts):
        raise ValueError("no game text in it: [[id]]")
    return parts


def compose(parts: list, game: Game, lang: str) -> str | None:
    """`parts` in `lang`: the game texts cleaned, their placeholders filled (`fill`; `<lang>:<name>` first) or, if not,
    named after the part's place (`{0@2}`: the first placeholder of the third part, so two parts do not share one) and the
    literal text as it is. None when a game text has nothing in `lang`."""
    pieces = []
    for number, part in enumerate(parts):
        if isinstance(part, str):
            pieces.append(part)
            continue
        raw = game.text(lang, part["source"])
        if not raw:
            return None
        fill = part.get("fill", {})

        def put(match: re.Match) -> str:
            name = match.group(0)[1:-1]
            value = fill.get(f"{lang}:{name}", fill.get(name))
            return f"{{{name}@{number}}}" if value is None else value

        pieces.append(T.PLACEHOLDER.sub(put, T.clean(raw)))
    return "".join(pieces)


def targets(node: dict, parts: list, game: Game, langs: list[str]) -> dict[str, str | None]:
    """What the game says for `parts` in each of the webapp's languages it has a text in, written the webapp's way
    (`texts.adapt`; None where the placeholders do not pair up). Empty when the game has no such text."""
    game_en = compose(parts, game, "en")
    if game_en is None:
        return {}
    return {lang: T.adapt(text, game_en, node["en"]) for lang in langs if (text := compose(parts, game, lang))}


def agreement(node: dict, found: dict[str, str | None], langs) -> int:
    """In how many of `langs` the webapp already says what the game says."""
    return sum(1 for lang in langs if found.get(lang) and node.get(lang) == found[lang])


# --- candidates ----------------------------------------------------------------------------------------------------
def distinct(game: Game, text_ids: list[str], langs: list[str]) -> list[str]:
    """`text_ids` without the ones that say the same in every language as an earlier one."""
    seen: dict[tuple, str] = {}
    for text_id in text_ids:
        seen.setdefault(tuple(T.clean(game.text(lang, text_id) or "") for lang in langs), text_id)
    return list(seen.values())


def compositions(node: dict, game: Game, langs: list[str]) -> list[list]:
    """The parts that make the webapp's English out of game texts, for a text that is no game text (the game puts these
    together in its code): a game text and a number after it (`Hero DMG Dealt↑ 10.00%`), else a text with numbers where a
    game text has placeholders (`Lv.{0}`, filled with them) next to a game text, either way round (`Lv.3 Sharp Beak`).
    Only those that make the English again (`texts.norm`), so a stray match does not count."""
    english = node["en"].strip()
    if not NUMBER.search(english):
        return []

    def exact(text: str) -> list[dict]:
        return [{"source": text_id} for text_id in distinct(game, game.exact(text), langs)]

    def filled(text: str) -> list[dict]:
        """The game texts that are `text` with its numbers as placeholders, each with the numbers as its fill."""
        holed = NUMBER.sub("{0}", text)
        if not LETTER.search(T.PLACEHOLDER_UNIT.sub("", holed)):
            return []  # a number alone would be any text that is only a placeholder
        numbers, found = NUMBER.findall(text), []
        for text_id in distinct(game, game.exact(holed), langs):
            names = [name[1:-1] for name in T.PLACEHOLDER.findall(T.clean(game.text("en", text_id)))]
            fill = dict(zip(names, numbers))
            if len(names) == len(numbers) and all(fill[name] == number for name, number in zip(names, numbers)):
                found.append({"source": text_id, "fill": fill})
        return found

    options = []
    if trailing := TRAILING_NUMBER.fullmatch(english):
        options = [[head, trailing.group(2)] for head in exact(trailing.group(1))]
    if not options:
        for gap in re.finditer(r"\s+", english):
            left, right = english[:gap.start()], english[gap.end():]
            if NUMBER.search(left):
                options += [[a, gap.group(), b] for a in filled(left) for b in exact(right)]
            if NUMBER.search(right):
                options += [[a, gap.group(), b] for a in exact(left) for b in filled(right)]
    return [parts for parts in options if T.norm(compose(parts, game, "en")) == T.norm(english)]


def rank_key(parts: list) -> tuple:
    return tuple(rank(part["source"]) for part in parts if isinstance(part, dict))


def ranked(node: dict, options: list[list], game: Game, langs: list[str]) -> list[dict]:
    """The `options` (parts of game texts that could be the webapp's text) as candidates, the best first: those whose
    translations the webapp already has, then those most texts agree with, a table before a UI string. `clear` says
    whether the best of them is a clear choice (one translation, or the webapp's own)."""
    others = [lang for lang in langs if lang != "en"]
    found = []
    for parts in options:
        shown = targets(node, parts, game, langs)
        found.append({"id": template_of(parts), "parts": parts, "exact": True, "score": 100, "targets": shown,
                      "translations": tuple(sorted((l, v) for l, v in shown.items() if l != "en")),
                      "agree": agreement(node, shown, langs), "agree_other": agreement(node, shown, others)})
    shared = {}
    for c in found:
        shared[c["translations"]] = shared.get(c["translations"], 0) + 1
    found.sort(key=lambda c: (-c["agree_other"], -shared[c["translations"]], -c["agree"], rank_key(c["parts"])))
    groups = {c["translations"]: c["agree_other"] for c in found}
    top = sorted(groups.values(), reverse=True)
    clear = len(groups) == 1 or (top[0] > 0 and top[0] > top[1])  # one translation, or the webapp's own picks one
    for c in found:
        c["clear"] = clear
    return found


def candidates(node: dict, game: Game, langs: list[str], limit: int = CANDIDATES) -> list[dict]:
    """The game texts a webapp text may be: the exact ones first (`game.exact`), else what it is made of (`compositions`),
    else the near ones. Each has its `parts` and its `id`, the template of them (the game text's id when it is one);
    `ranked` puts the first two in order and says whether the best is a clear choice."""
    options = [single(text_id) for text_id in game.exact(node["en"])] or compositions(node, game, langs)
    if options:
        return ranked(node, options, game, langs)[:limit]
    return [{"id": text_id, "parts": single(text_id), "exact": False, "score": score, "clear": False,
             "targets": targets(node, single(text_id), game, langs)} for text_id, score in game.near(node["en"], limit)]


# --- statuses ------------------------------------------------------------------------------------------------------
def status_of(node: dict, entry: dict | None, game: Game, langs: list[str]) -> tuple[str, str | None]:
    """(status, the game text it is or would be: its id, or the template of what it is made of) of a webapp text."""
    if entry is not None:
        parts = parts_of(entry)
        if parts is None:
            return "none", None
        found, source = targets(node, parts, game, langs), template_of(parts)
        if not found:
            return "missing", source
        if None in found.values():
            return "mismatch", source
        return ("official" if all(node.get(lang, "") == text for lang, text in found.items()) else "to sync"), source
    best = candidates(node, game, langs, limit=CANDIDATES)
    if not best:
        return "unmapped", None
    if not best[0]["exact"]:
        return "near", best[0]["id"]
    return ("suggested" if best[0]["clear"] else "ambiguous"), best[0]["id"]


def rows(mapping: dict, texts: dict[str, dict], game: Game, langs: list[str]) -> list[dict]:
    """One row per webapp text: {location, status, en, source}."""
    table = []
    for location, node in texts.items():
        status, source = status_of(node, mapping.get(location), game, langs)
        table.append({"location": location, "status": status, "en": node["en"], "source": source})
    return table


def counts(table: list[dict]) -> dict[str, int]:
    return {s: sum(1 for r in table if r["status"] == s) for s in STATUSES}


def summary(table: list[dict]) -> str:
    c = counts(table)
    odd = "".join(f", {name} {c[name]}" for name in ("mismatch", "missing") if c[name])
    return (f"Official {c['official']} of {len(table)} webapp texts - to sync {c['to sync']}, suggested {c['suggested']}, "
            f"ambiguous {c['ambiguous']}, near {c['near']}, unmapped {c['unmapped']}, own text {c['none']}{odd}")


# --- the mapping ---------------------------------------------------------------------------------------------------
def load(path: Path = PATH) -> dict:
    return Mp.load(path)


def set_entry(location: str, parts: list | None, path: Path = PATH) -> None:
    """Map `location` to `parts` (re-read from the file first, so nothing another window wrote is lost); None = the
    webapp's own text."""
    mapping = Mp.load(path)
    mapping[location] = {"source": None} if parts is None else entry_of(parts)
    Mp.save(mapping, path)


def clear(location: str, path: Path = PATH) -> None:
    mapping = Mp.load(path)
    if mapping.pop(location, None) is not None:
        Mp.save(mapping, path)


def accept_suggestions(table: list[dict], path: Path = PATH) -> int:
    """Map every `suggested` text to its game text (an ambiguous or near one is never taken); returns how many."""
    mapping = Mp.load(path)
    taken = [r for r in table if r["status"] == "suggested" and r["location"] not in mapping]
    for r in taken:
        mapping[r["location"]] = entry_of(parse_template(r["source"]))
    if taken:
        Mp.save(mapping, path)
    return len(taken)


def used(mapping: dict) -> dict[str, list[str]]:
    """{game text id: the webapp locations mapped to it (a text made of several is under each)}, for the text browser."""
    found: dict[str, list[str]] = {}
    for location, entry in sorted(mapping.items()):
        for part in parts_of(entry) or ():
            if isinstance(part, dict) and location not in found.setdefault(part["source"], []):
                found[part["source"]].append(location)
    return found


# --- sync ----------------------------------------------------------------------------------------------------------
def plan(mapping: dict, texts: dict[str, dict], game: Game, langs: list[str]) -> list[dict]:
    """What Sync would do, per mapped text and language: {location, lang, action: write / skipped, old, new, note}."""
    done = []
    for location, entry in sorted(mapping.items()):
        node, parts = texts.get(location), parts_of(entry)
        if node is None or parts is None:
            continue
        found, source = targets(node, parts, game, langs), template_of(parts)
        if not found:
            done.append({"location": location, "lang": "", "action": "skipped", "old": "", "new": "",
                         "note": f"{source} is not in the extracted texts"})
        for lang, text in found.items():
            if text is None:
                done.append({"location": location, "lang": lang, "action": "skipped", "old": node.get(lang, ""), "new": "",
                             "note": "the placeholders of the webapp's English and the game's do not pair up"})
            elif node.get(lang, "") != text:
                done.append({"location": location, "lang": lang, "action": "write", "old": node.get(lang, ""), "new": text,
                             "note": source})
    return done


def format_command(webapp: Path) -> list[str]:
    """The command (to add the files to) that formats with the webapp's own prettier, or an error that says what is missing."""
    node, prettier = shutil.which("node"), webapp / "node_modules" / "prettier" / "bin" / "prettier.cjs"
    if node is None:
        raise RuntimeError("node is not installed (or not on the PATH): the webapp's files are formatted with its prettier")
    if not prettier.is_file():
        raise RuntimeError(f"the webapp's prettier is not at {prettier} - run `npm install` in {webapp}")
    return [node, str(prettier), "--write"]


def write_docs(docs: dict[str, dict], stems: set[str], data_dir: Path) -> list[Path]:
    """Write the data files of `stems` as the webapp keeps them (4 spaces, a newline at the end, the line ends they had)."""
    files = []
    for stem in sorted(stems):
        text = json.dumps(docs[stem]["data"], indent=4, ensure_ascii=False) + "\n"
        if docs[stem]["crlf"]:
            text = text.replace("\n", "\r\n")
        files.append(data_dir / f"{stem}.json")
        files[-1].write_bytes(text.encode("utf-8"))
    return files


def sync(apply: bool = False, game: Game | None = None, data_dir: Path = C.WEBAPP_DATA, i18n_dir: Path = C.WEBAPP_I18N,
         path: Path = PATH) -> list[dict]:
    """Make the webapp's texts the game's, for every mapped text. Without `apply` nothing is written. Returns the plan."""
    docs, texts = read_webapp(data_dir)
    langs = webapp_languages(i18n_dir)
    game = game or Game(T.load())
    done = plan(Mp.load(path), texts, game, langs)
    writes = [d for d in done if d["action"] == "write"]
    if apply and writes:
        command = format_command(data_dir.parent)  # fail before changing anything
        for d in writes:
            texts[d["location"]][d["lang"]] = d["new"]
        stems = {d["location"].partition(":")[0] for d in writes}
        files = write_docs(docs, stems, data_dir)
        result = subprocess.run(command + [str(f) for f in files], cwd=data_dir.parent, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
        if result.returncode:
            raise RuntimeError(f"prettier failed: {(result.stderr or result.stdout).strip()}")
    return done
