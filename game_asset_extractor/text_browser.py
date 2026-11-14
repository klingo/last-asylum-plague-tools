"""Text browser: out/texts/index.html, one static page to read and search every extracted game text.

Open it from the folder (`out/texts/index.html`); it reads `ids.js` (the ids, which extract run added or changed each, the
runs' resource versions, which webapp texts are mapped to it) and one `<language>.js` per extracted language (the texts,
with the markup taken off, aligned with the ids), loaded when its box is ticked: not a fetched JSON, which browsers block
for files on disk. A row is a text id, with a column per ticked language. Filter by folder (`language/<File>` or
`tables/<Table>`), search the ids and the ticked languages' texts, and show what was added or changed (together or each
alone) since the baseline ("Mark all as seen", shared with the pictures' gallery), what the webapp maps to a game text or not,
or what a resource version added or changed (the first run holds everything that was there from the start, so its version
means "this or earlier"). Clicking a row copies its id (for the text mapping editor's search).
"""

from __future__ import annotations

import json
from pathlib import Path

import config as C
import state as S
import text_mapping as TM
import texts as T

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Last Asylum: Plague - game texts</title>
<style>
body { font: 14px/1.4 system-ui, sans-serif; margin: 0; background: #1b1d22; color: #e6e6e6; }
header { position: sticky; top: 0; z-index: 1; background: #23262d; padding: 10px 14px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; border-bottom: 1px solid #000; }
select, input[type=search] { background: #14161a; color: inherit; border: 1px solid #444; border-radius: 4px; padding: 5px 8px; font: inherit; }
input[type=search] { width: 260px; }
label.lang { white-space: nowrap; }
#count { margin-left: auto; color: #9aa; }
table { border-collapse: collapse; width: 100%; table-layout: fixed; }
th { position: sticky; top: 49px; background: #2b2f37; text-align: left; padding: 6px 10px; font-size: 12px; color: #9aa; }
th.id, td.id { width: 270px; }
td { vertical-align: top; padding: 6px 10px; border-bottom: 1px solid #2c2f35; white-space: pre-wrap; word-break: break-word; }
td.id { font-size: 11px; color: #8a929c; word-break: break-all; cursor: pointer; }
tr:hover td { background: #23262d; }
td.chg { background: #3a2f17; }
.badge { display: inline-block; margin-left: 6px; font-size: 10px; font-weight: 700; padding: 0 5px; border-radius: 3px; background: #2e9e5b; color: #fff; }
.badge.changed { background: #d98a1d; }
.badge.used { background: #3b5bdb; font-weight: 400; }
#more { display: block; margin: 14px auto 30px; padding: 8px 22px; }
#toast { position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%); background: #3b5bdb; padding: 8px 16px; border-radius: 6px; opacity: 0; transition: opacity .2s; pointer-events: none; }
#toast.on { opacity: 1; }
</style></head><body>
<header>
  <select id="folder"></select>
  <span id="langs"></span>
  <select id="status">
    <option value="all">All texts</option>
    <option value="fresh">New or changed since marked as seen</option>
    <option value="new">New since marked as seen</option>
    <option value="changed">Changed since marked as seen</option>
    <option value="used">Mapped to a webapp text</option>
    <option value="unused">Not mapped</option>
  </select>
  <select id="version"></select>
  <input id="search" type="search" placeholder="Search ids and texts (e.g. antitoxin)">
  <span id="count"></span>
</header>
<table><thead><tr id="head"></tr></thead><tbody id="rows"></tbody></table><button id="more">Show more</button><div id="toast"></div>
<script src="ids.js"></script>
<script>
const D = window.TEXTS, PAGE = 400, L = {};
const $ = id => document.getElementById(id);
const folderSel = $('folder'), statusSel = $('status'), versionSel = $('version'), search = $('search'), rows = $('rows'), more = $('more');
const active = new Set(D.langs.slice(0, 2));
let shown = 0, matches = [];
const folderOf = D.ids.map(id => id.slice(0, id.indexOf(':')));
const versionOf = run => D.runs[run] || '?';
const fresh = i => D.added[i] > D.baseline || D.changed[i] > D.baseline;
folderSel.append(new Option('All folders (' + D.ids.length + ')', ''));
for (const [f, n] of D.folders) folderSel.append(new Option(f + ' (' + n + ')', f));
const added = {}, changed = {}, lastRun = {};
D.ids.forEach((_, i) => {
  const v = versionOf(D.added[i]);
  added[v] = (added[v] || 0) + 1;
  if (D.changed[i] && versionOf(D.changed[i]) !== v) changed[versionOf(D.changed[i])] = (changed[versionOf(D.changed[i])] || 0) + 1;
});
for (const run of Object.keys(D.runs)) lastRun[D.runs[run]] = Math.max(lastRun[D.runs[run]] || 0, +run);
versionSel.append(new Option('Any resource version', ''));
for (const v of [...new Set([...Object.keys(added), ...Object.keys(changed)])].sort((a, b) => (lastRun[b] || 0) - (lastRun[a] || 0)))
  versionSel.append(new Option((v === '?' ? 'Unknown version' : v) + (v === versionOf(D.first) ? ' or earlier' : '') + ' (' + (added[v] || 0) + ' new, ' + (changed[v] || 0) + ' changed)', v));
for (const lang of D.langs) {
  const box = document.createElement('input'); box.type = 'checkbox'; box.checked = active.has(lang);
  box.onchange = () => { if (box.checked) active.add(lang); else active.delete(lang); load(lang, render); };
  const label = document.createElement('label'); label.className = 'lang'; label.append(box, ' ' + lang + '  ');
  $('langs').append(label);
}
function load(lang, done) {
  if (L[lang] || !active.has(lang)) return done();
  const s = document.createElement('script'); s.src = lang + '.js';
  s.onload = () => { L[lang] = window.TEXT_LANGS[lang]; L[lang].low = L[lang].t.map(t => t.toLowerCase()); done(); };
  document.head.append(s);
}
function pass(i) {
  if (folderSel.value && folderOf[i] !== folderSel.value) return false;
  if (versionSel.value && versionOf(D.added[i]) !== versionSel.value && !(D.changed[i] && versionOf(D.changed[i]) === versionSel.value)) return false;
  const q = search.value.trim().toLowerCase();
  if (q && !D.ids[i].toLowerCase().includes(q) && ![...active].some(lang => L[lang] && L[lang].low[i].includes(q))) return false;
  switch (statusSel.value) {
    case 'fresh': return fresh(i);
    case 'new': return D.added[i] > D.baseline;
    case 'changed': return D.added[i] <= D.baseline && D.changed[i] > D.baseline;  // as the badge: a new text is not also "changed"
    case 'used': return !!D.used[i];
    case 'unused': return !D.used[i];
  }
  return true;
}
function cell(text, className, title) {
  const td = document.createElement('td'); td.textContent = text; if (className) td.className = className; if (title) td.title = title; return td;
}
function when(lang, i) {
  const l = L[lang], a = l.a[i], c = l.c[i];
  return lang + ': first extracted in ' + versionOf(a) + (c ? ', changed in ' + versionOf(c) : '');
}
function row(i) {
  const tr = document.createElement('tr'), id = cell(D.ids[i], 'id', D.ids[i] + (D.used[i] ? '\nin the webapp: ' + D.used[i].join(', ') : ''));
  if (D.added[i] > D.baseline) id.append(Object.assign(document.createElement('span'), { className: 'badge', textContent: 'NEW' }));
  else if (D.changed[i] > D.baseline) id.append(Object.assign(document.createElement('span'), { className: 'badge changed', textContent: 'CHANGED' }));
  if (D.used[i]) id.append(Object.assign(document.createElement('span'), { className: 'badge used', textContent: 'in webapp' }));
  id.onclick = () => copy(D.ids[i]);
  tr.append(id);
  for (const lang of D.langs) if (active.has(lang) && L[lang]) tr.append(cell(L[lang].t[i], L[lang].c[i] > D.baseline ? 'chg' : '', when(lang, i)));
  return tr;
}
function copy(text) {
  const done = () => { const el = $('toast'); el.textContent = 'Copied ' + text; el.classList.add('on'); setTimeout(() => el.classList.remove('on'), 1400); };
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, () => fallback(text, done)); else fallback(text, done);
}
function fallback(text, done) {
  const ta = document.createElement('textarea'); ta.value = text; document.body.append(ta); ta.select(); document.execCommand('copy'); ta.remove(); done();
}
function render() {
  const head = $('head'); head.replaceChildren(Object.assign(document.createElement('th'), { className: 'id', textContent: 'Text id' }));
  for (const lang of D.langs) if (active.has(lang)) head.append(Object.assign(document.createElement('th'), { textContent: lang }));
  matches = D.ids.map((_, i) => i).filter(pass); shown = 0; rows.replaceChildren(); next();
  $('count').textContent = matches.length + ' texts';
}
function next() {
  for (const i of matches.slice(shown, shown + PAGE)) rows.append(row(i));
  shown = Math.min(shown + PAGE, matches.length); more.style.display = shown < matches.length ? '' : 'none';
}
more.onclick = next;
folderSel.onchange = statusSel.onchange = versionSel.onchange = render; search.oninput = render;
Promise.all([...active].map(lang => new Promise(done => load(lang, done)))).then(render);
</script></body></html>
"""


def build_data(texts: dict[str, dict[str, str]], index: dict, meta: dict, mapping: dict | None = None) -> tuple[dict, dict]:
    """(what ids.js holds, {language: its columns for `<language>.js`}). The ids are in the folders' order (a file's texts
    as the game has them); `added` / `changed` say per id which extract run first saw it in any language and last changed it
    in one (0 = never); a language's columns hold its cleaned texts and the same two runs for itself."""
    ordered: dict[str, None] = {}
    for entries in texts.values():
        ordered.update(dict.fromkeys(entries))
    ids = sorted(ordered, key=lambda text_id: T.folder_of(text_id).lower())
    marks = [index["texts"].get(text_id, {}) for text_id in ids]
    folders: dict[str, int] = {}
    for text_id in ids:
        folders[T.folder_of(text_id)] = folders.get(T.folder_of(text_id), 0) + 1
    users = TM.used(mapping or {})
    header = {
        "baseline": meta.get("baseline", 0),
        "first": index.get("first") or 0,
        "runs": {run: info.get("version", "?") for run, info in meta.get("runs", {}).items()},
        "langs": list(texts),
        "folders": list(folders.items()),
        "ids": ids,
        "added": [min((m[1] for m in found.values()), default=0) for found in marks],
        "changed": [max((m[2] for m in found.values()), default=0) for found in marks],
        "used": {str(i): users[text_id] for i, text_id in enumerate(ids) if text_id in users},
    }
    columns = {
        lang: {"t": [T.clean(texts[lang].get(text_id, "")) for text_id in ids],
               "a": [found.get(lang, [0, 0, 0])[1] for found in marks],
               "c": [found.get(lang, [0, 0, 0])[2] for found in marks]}
        for lang in texts
    }
    return header, columns


def write(out: Path | None = None) -> Path:
    out = out or C.OUT / "texts"
    texts = T.load()
    header, columns = build_data(texts, T.current_index(), S.load_index()["meta"], TM.load())
    out.mkdir(parents=True, exist_ok=True)
    (out / "ids.js").write_text("window.TEXTS = " + json.dumps(header, ensure_ascii=False) + ";\n", encoding="utf-8")
    for lang, data in columns.items():
        (out / f"{lang}.js").write_text(
            f"(window.TEXT_LANGS = window.TEXT_LANGS || {{}})[{json.dumps(lang)}] = " + json.dumps(data, ensure_ascii=False) + ";\n",
            encoding="utf-8")
    page = out / "index.html"
    page.write_text(PAGE, encoding="utf-8")
    return page
