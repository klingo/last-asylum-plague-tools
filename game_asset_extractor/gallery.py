"""Gallery: out/index.html, one static page to browse every extracted picture.

Open it from the folder (`out/index.html`); it reads `out/data.js` (not a fetched JSON, which browsers block for files
on disk). Only the pictures (`config.is_picture`) are listed. Filter by group, search by name, and show only what was added or changed (together or each alone) since the baseline
(`main.py baseline` / "Mark all as seen": the extract run up to which everything counts as seen, shared with the text browser), what the webapp
does not have yet, or what it has (a close sprite to a PNG of `webapp/public/assets`, see `match.py`, or the source (or overlay) of
a webapp image in `mapping.json`, which finds cropped ones too), by the resource version a picture was first extracted in
(`meta.runs` of `out/index.json` says which version each extract run was made for; the first run holds everything that
was there from the start, so its version means "this or earlier"), and by size (one of the most frequent sizes, or a range
of the longer side). Clicking a picture copies its id for `python main.py import <id> <dest>` (or the window's Import row).
"""

from __future__ import annotations

import json
from pathlib import Path

import config as C
import mapping as Mp
import match as M
import state as S

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Last Asylum: Plague - game pictures</title>
<style>
body { font: 14px/1.4 system-ui, sans-serif; margin: 0; background: #1b1d22; color: #e6e6e6; }
header { position: sticky; top: 0; z-index: 1; background: #23262d; padding: 10px 14px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; border-bottom: 1px solid #000; }
select, input { background: #14161a; color: inherit; border: 1px solid #444; border-radius: 4px; padding: 5px 8px; font: inherit; }
input { width: 220px; }
input.px { width: 70px; }
#count { margin-left: auto; color: #9aa; }
#grid { display: grid; grid-template-columns: repeat(auto-fill, 132px); gap: 10px; padding: 14px; }
.tile { position: relative; background: #23262d; border: 1px solid #333; border-radius: 6px; padding: 6px; cursor: pointer; }
.tile:hover { border-color: #7aa7ff; }
.pic { height: 118px; display: flex; align-items: center; justify-content: center; border-radius: 4px;
  background: repeating-conic-gradient(#3a3d44 0% 25%, #2c2f35 0% 50%) 50% / 16px 16px; }
.pic img { max-width: 118px; max-height: 118px; }
.name { margin-top: 4px; font-size: 11px; word-break: break-all; max-height: 3.9em; overflow: hidden; }
.size { color: #8a929c; font-size: 11px; }
.badge { position: absolute; top: 8px; left: 8px; font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 3px; background: #2e9e5b; color: #fff; }
.badge.changed { background: #d98a1d; }
.used { position: absolute; top: 8px; right: 8px; font-size: 10px; padding: 1px 5px; border-radius: 3px; background: #3b5bdb; color: #fff; }
#more { display: block; margin: 0 auto 30px; padding: 8px 22px; }
#toast { position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%); background: #3b5bdb; padding: 8px 16px; border-radius: 6px; opacity: 0; transition: opacity .2s; pointer-events: none; }
#toast.on { opacity: 1; }
</style></head><body>
<header>
  <select id="group"></select>
  <select id="version"></select>
  <select id="status">
    <option value="all">All pictures</option>
    <option value="fresh">New or changed since marked as seen</option>
    <option value="new">New since marked as seen</option>
    <option value="changed">Changed since marked as seen</option>
    <option value="missing">Not in the webapp yet</option>
    <option value="used">Already in the webapp</option>
  </select>
  <select id="size"></select>
  <label>Longer side <input id="min" class="px" type="number" min="0" placeholder="from px"> <input id="max" class="px" type="number" min="0" placeholder="to px"></label>
  <input id="search" type="search" placeholder="Search names (e.g. gold, chest)">
  <span id="count"></span>
</header>
<div id="grid"></div><button id="more">Show more</button><div id="toast"></div>
<script src="data.js"></script>
<script>
const D = window.GALLERY, PAGE = 400;
const $ = id => document.getElementById(id);
const groupSel = $('group'), versionSel = $('version'), statusSel = $('status'), sizeSel = $('size'), min = $('min'), max = $('max'), search = $('search'), grid = $('grid'), more = $('more');
let shown = 0, matches = [];
groupSel.append(new Option('All groups (' + D.sprites.length + ')', ''));
for (const [g, n] of D.groups) groupSel.append(new Option(g.replace(/^pictures\//, '') + ' (' + n + ')', g));
const versionOf = run => D.runs[run] || '?';
const versionCounts = {}, lastRun = {};
for (const s of D.sprites) versionCounts[versionOf(s[5])] = (versionCounts[versionOf(s[5])] || 0) + 1;
for (const run of Object.keys(D.runs)) lastRun[D.runs[run]] = Math.max(lastRun[D.runs[run]] || 0, +run);
const firstVersion = D.runs[Math.min(...Object.keys(D.runs).map(Number))];
versionSel.append(new Option('Any resource version', ''));
for (const v of Object.keys(versionCounts).sort((a, b) => (lastRun[b] || 0) - (lastRun[a] || 0)))
  versionSel.append(new Option((v === '?' ? 'Unknown version' : v) + (v === firstVersion ? ' or earlier' : '') + ' (' + versionCounts[v] + ' new)', v));
const sizeCounts = {};
for (const s of D.sprites) sizeCounts[s[3] + ' x ' + s[4]] = (sizeCounts[s[3] + ' x ' + s[4]] || 0) + 1;
sizeSel.append(new Option('Any size', ''));
for (const [size, n] of Object.entries(sizeCounts).sort((a, b) => b[1] - a[1]).slice(0, 4)) sizeSel.append(new Option(size + ' (' + n + ')', size));
function pass(s) {
  const [id, group, name, w, h, added, changed] = s;
  if (groupSel.value && group !== groupSel.value) return false;
  const q = search.value.trim().toLowerCase();
  if (q && !id.toLowerCase().includes(q)) return false;
  if (versionSel.value && versionOf(added) !== versionSel.value) return false;
  if (sizeSel.value && w + ' x ' + h !== sizeSel.value) return false;
  if (min.value && Math.max(w, h) < +min.value) return false;
  if (max.value && Math.max(w, h) > +max.value) return false;
  switch (statusSel.value) {
    case 'fresh': return added > D.baseline || changed > D.baseline;
    case 'new': return added > D.baseline;
    case 'changed': return added <= D.baseline && changed > D.baseline;  // as the badge: a new picture is not also "changed"
    case 'missing': return !D.used[id];
    case 'used': return !!D.used[id];
  }
  return true;
}
function tile(s) {
  const [id, group, name, w, h, added, changed] = s;
  const t = document.createElement('div'); t.className = 'tile'; t.title = id + '\nfirst extracted in ' + versionOf(added) + (D.used[id] ? '\nin the webapp: ' + D.used[id].join(', ') : '');
  const pic = document.createElement('div'); pic.className = 'pic';
  const img = document.createElement('img'); img.loading = 'lazy'; img.src = encodeURI(group + '/' + name + '.png'); pic.append(img);
  const nm = document.createElement('div'); nm.className = 'name'; nm.textContent = name;
  const sz = document.createElement('div'); sz.className = 'size'; sz.textContent = w + ' x ' + h;
  t.append(pic, nm, sz);
  if (added > D.baseline) t.append(Object.assign(document.createElement('span'), { className: 'badge', textContent: 'NEW' }));
  else if (changed > D.baseline) t.append(Object.assign(document.createElement('span'), { className: 'badge changed', textContent: 'CHANGED' }));
  if (D.used[id]) t.append(Object.assign(document.createElement('span'), { className: 'used', textContent: 'in webapp' }));
  t.onclick = () => copy(id);
  return t;
}
function copy(text) {
  const done = () => { const el = $('toast'); el.textContent = 'Copied ' + text; el.classList.add('on'); setTimeout(() => el.classList.remove('on'), 1400); };
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, () => fallback(text, done)); else fallback(text, done);
}
function fallback(text, done) {
  const ta = document.createElement('textarea'); ta.value = text; document.body.append(ta); ta.select(); document.execCommand('copy'); ta.remove(); done();
}
function render() {
  matches = D.sprites.filter(pass); shown = 0; grid.replaceChildren(); next();
  $('count').textContent = matches.length + ' pictures';
}
function next() {
  for (const s of matches.slice(shown, shown + PAGE)) grid.append(tile(s));
  shown = Math.min(shown + PAGE, matches.length); more.style.display = shown < matches.length ? '' : 'none';
}
more.onclick = next;
groupSel.onchange = versionSel.onchange = statusSel.onchange = sizeSel.onchange = render; search.oninput = min.oninput = max.oninput = render;
render();
</script></body></html>
"""


def build_data(index: dict, matches: dict, mapping: dict | None = None) -> dict:
    """What the page needs: sprites as [id, group, name, w, h, added, changed], group counts, the resource version of every
    extract run (`runs`: run -> version, so `added` says in which version a picture first showed up) and which sprite is in the
    webapp: by a close hash, or as the source of a mapped webapp image (an image cropped from its sprite hashes far away)."""
    sprites = sorted((s for s in index["sprites"].values() if C.is_picture(s)), key=lambda s: (s["group"].lower(), s["name"].lower()))
    groups: dict[str, int] = {}
    for s in sprites:
        groups[s["group"]] = groups.get(s["group"], 0) + 1
    used: dict[str, list[str]] = {}
    for path, candidates in matches.items():
        if candidates and candidates[0]["dist"] <= M.CLOSE:
            used.setdefault(candidates[0]["id"], []).append(path)
    for path, entry in (mapping or {}).items():
        for source in (entry.get("source"), (entry.get("overlay") or {}).get("source")):
            if source in index["sprites"] and path not in used.get(source, []):
                used.setdefault(source, []).append(path)
    return {
        "baseline": index["meta"].get("baseline", 0),
        "runs": {run: info.get("version", "?") for run, info in index["meta"].get("runs", {}).items()},
        "groups": sorted(groups.items(), key=lambda g: g[0].lower()),
        "sprites": [[s["id"], s["group"], s["name"], s["w"], s["h"], s["added"], s["changed"]] for s in sprites],
        "used": used,
    }


def write(out: Path = C.OUT) -> Path:
    index = S.load_index()
    try:
        matches = json.loads((out / "matches.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        matches = {}
    out.mkdir(parents=True, exist_ok=True)
    data = build_data(index, matches, Mp.load())
    (out / "data.js").write_text("window.GALLERY = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    page = out / "index.html"
    page.write_text(PAGE, encoding="utf-8")
    return page
