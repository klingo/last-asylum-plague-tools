"""Text mapping: which game text each of the webapp's texts is, and keeping the webapp's wording and translations in step.

A webapp text is a localized string (`{"en": "...", "de": "..."}`) in `data/pack_data.json`, `events.json`,
`hero_skills.json` or `lord_specialty.json`, named by its location `<file>:<path>` (`pack_data:items.antitoxin.name`;
a list item by its `id` when it has one, else its number: `events:event_rotations.alliance_duel.phases[territory].name`).
`text_mapping.json` (next to this file, committed) says which game text it is, by the game text's id (see `texts.py`):

    "pack_data:items.antitoxin.name": {"source": "tables/ItemIcon:5.name"}
    "hero_skills:heroes.marlena.note": {"source": null}      the webapp's own text: nothing to look up in the game

Texts are matched by their English (`texts.norm`: markup, case, spacing and placeholder names don't count), so the game's
other languages come with the match. A near match (`NEAR` percent alike, found with rapidfuzz) is a possible typo and
never taken without asking. An unmapped text is

    suggested   its English is in the game, and the game has one translation of it (or the webapp's own picks one of several)
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
DATA_FILES = ("pack_data", "events", "hero_skills", "lord_specialty")
STATUSES = ("official", "to sync", "mismatch", "missing", "suggested", "ambiguous", "near", "unmapped", "none")
NEAR = 85  # percent: how alike two English texts must be to be offered as a possible typo
CANDIDATES = 12  # kept per webapp text
SEARCH_LIMIT = 150
LANGUAGE = re.compile(r"[a-z]{2}(?:-[A-Za-z]+)?")
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
    """Where to look first: a table's text (an item's name) before a UI string that happens to say the same."""
    return (0 if text_id.startswith("tables/") else 1, text_id)


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


def targets(node: dict, text_id: str, game: Game, langs: list[str]) -> dict[str, str | None]:
    """What the game says for `text_id` in each of the webapp's languages it has a text in, written the webapp's way
    (`texts.adapt`; None where the placeholders do not pair up). Empty when the game has no such text."""
    game_en = game.text("en", text_id)
    if game_en is None:
        return {}
    return {lang: T.adapt(text, game_en, node["en"]) for lang in langs if (text := game.text(lang, text_id))}


def agreement(node: dict, found: dict[str, str | None], langs) -> int:
    """In how many of `langs` the webapp already says what the game says."""
    return sum(1 for lang in langs if found.get(lang) and node.get(lang) == found[lang])


def candidates(node: dict, game: Game, langs: list[str], limit: int = CANDIDATES) -> list[dict]:
    """The game texts a webapp text may be: the exact ones first (`exact`), then the near ones. Of the exact ones, those
    whose translations the webapp already has first, then those most texts agree with, a table before a UI string.
    `pick` on an exact one says whether the best of them is a clear choice (one translation, or the webapp's own)."""
    others = [lang for lang in langs if lang != "en"]
    exact = []
    for text_id in game.exact(node["en"]):
        found = targets(node, text_id, game, langs)
        exact.append({"id": text_id, "exact": True, "score": 100, "targets": found,
                      "translations": tuple(sorted((l, v) for l, v in found.items() if l != "en")),
                      "agree": agreement(node, found, langs), "agree_other": agreement(node, found, others)})
    shared = {}
    for c in exact:
        shared[c["translations"]] = shared.get(c["translations"], 0) + 1
    exact.sort(key=lambda c: (-c["agree_other"], -shared[c["translations"]], -c["agree"], rank(c["id"])))
    if exact:
        groups = {c["translations"]: c["agree_other"] for c in exact}
        top = sorted(groups.values(), reverse=True)
        clear = len(groups) == 1 or (top[0] > 0 and top[0] > top[1])  # one translation, or the webapp's own picks one
        for c in exact:
            c["clear"] = clear
        return exact[:limit]
    return [{"id": text_id, "exact": False, "score": score, "targets": targets(node, text_id, game, langs), "clear": False}
            for text_id, score in game.near(node["en"], limit)]


# --- statuses ------------------------------------------------------------------------------------------------------
def status_of(node: dict, entry: dict | None, game: Game, langs: list[str]) -> tuple[str, str | None]:
    """(status, the game text id it is or would be) of a webapp text."""
    if entry is not None:
        source = entry.get("source")
        if source is None:
            return "none", None
        found = targets(node, source, game, langs)
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


def set_source(location: str, source: str | None, path: Path = PATH) -> None:
    """Map `location` (re-read from the file first, so nothing another window wrote is lost); None = the webapp's own text."""
    mapping = Mp.load(path)
    mapping[location] = {"source": source}
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
        mapping[r["location"]] = {"source": r["source"]}
    if taken:
        Mp.save(mapping, path)
    return len(taken)


def used(mapping: dict) -> dict[str, list[str]]:
    """{game text id: the webapp locations mapped to it}, for the text browser."""
    found: dict[str, list[str]] = {}
    for location, entry in sorted(mapping.items()):
        if entry.get("source"):
            found.setdefault(entry["source"], []).append(location)
    return found


# --- sync ----------------------------------------------------------------------------------------------------------
def plan(mapping: dict, texts: dict[str, dict], game: Game, langs: list[str]) -> list[dict]:
    """What Sync would do, per mapped text and language: {location, lang, action: write / skipped, old, new, note}."""
    done = []
    for location, entry in sorted(mapping.items()):
        node, source = texts.get(location), entry.get("source")
        if node is None or source is None:
            continue
        found = targets(node, source, game, langs)
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
