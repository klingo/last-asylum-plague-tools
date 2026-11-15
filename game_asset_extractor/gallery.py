"""Gallery: out/index.html, one static page to browse every extracted picture.

Open it from the window ("Open gallery") or `main.py gallery --serve`, which serve `out/` on this computer only (127.0.0.1),
so the page can save tags; the file itself (`out/index.html`) also works, read-only. It reads `out/data.js` (not a fetched
JSON, which browsers block for files on disk). Only the pictures (`config.is_picture`) are listed. Filter by group, tag, search by name
and tag, and show only what was added or changed (together or each alone) since the baseline
(`main.py baseline` / "Mark all as seen": the extract run up to which everything counts as seen, shared with the text browser), what the webapp
does not have yet, or what it has (a close sprite to a PNG of `webapp/public/assets`, see `match.py`, or the source (or overlay) of
a webapp image in `mapping.json`, which finds cropped ones too), by the resource version a picture was first extracted in
(`meta.runs` of `out/index.json` says which version each extract run was made for; the first run holds everything that
was there from the start, so its version means "this or earlier"), and by size (one of the most frequent sizes, or a range
of the longer side). Clicking a picture copies its id for `python main.py import <id> <dest>` (or the window's Import row).

Tags are yours only (`tags.py`, `tags.json`). Ctrl-click (shift-click: a range) selects pictures; the bar at the bottom adds a
tag to them or removes one. The edits go to `POST /tags` of the local server, which writes `tags.json`.
"""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import config as C
import mapping as Mp
import match as M
import state as S
import tags as Tg

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Last Asylum: Plague - game pictures</title>
<style>
body { font: 14px/1.4 system-ui, sans-serif; margin: 0; background: #1b1d22; color: #e6e6e6; }
body.picking { padding-bottom: 96px; }
header { position: sticky; top: 0; z-index: 1; background: #23262d; padding: 10px 14px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; border-bottom: 1px solid #000; }
select, input { background: #14161a; color: inherit; border: 1px solid #444; border-radius: 4px; padding: 5px 8px; font: inherit; }
input { width: 220px; }
input.px { width: 70px; }
#count { margin-left: auto; color: #9aa; }
#grid { display: grid; grid-template-columns: repeat(auto-fill, 132px); gap: 10px; padding: 14px; }
.tile { position: relative; background: #23262d; border: 1px solid #333; border-radius: 6px; padding: 6px; cursor: pointer; user-select: none; }
.tile:hover { border-color: #7aa7ff; }
.tile.sel { border-color: #f0b429; background: #3a3320; }
.pic { height: 118px; display: flex; align-items: center; justify-content: center; border-radius: 4px;
  background: repeating-conic-gradient(#3a3d44 0% 25%, #2c2f35 0% 50%) 50% / 16px 16px; }
.pic img { max-width: 118px; max-height: 118px; }
.name { margin-top: 4px; font-size: 11px; word-break: break-all; max-height: 3.9em; overflow: hidden; }
.size { color: #8a929c; font-size: 11px; }
.tg { display: inline-block; font-size: 10px; line-height: 1.5; padding: 0 5px; margin: 2px 3px 0 0; border-radius: 8px; background: #3b5bdb; color: #fff; }
.badge { position: absolute; top: 8px; left: 8px; font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 3px; background: #2e9e5b; color: #fff; }
.badge.changed { background: #d98a1d; }
.used { position: absolute; top: 8px; right: 8px; font-size: 10px; padding: 1px 5px; border-radius: 3px; background: #3b5bdb; color: #fff; }
#more { display: block; margin: 0 auto 30px; padding: 8px 22px; }
#bar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 2; background: #23262d; border-top: 1px solid #000; padding: 10px 14px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
#bar[hidden] { display: none; }
#chips { flex-basis: 100%; }
.chip { cursor: pointer; }
.chip:hover { outline: 1px solid #fff; }
#toast { position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%); z-index: 3; background: #3b5bdb; padding: 8px 16px; border-radius: 6px; opacity: 0; transition: opacity .2s; pointer-events: none; }
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
  <select id="tag"></select>
  <label>Longer side <input id="min" class="px" type="number" min="0" placeholder="from px"> <input id="max" class="px" type="number" min="0" placeholder="to px"></label>
  <input id="search" type="search" placeholder="Search names and tags (e.g. chest, gold)">
  <span id="count"></span>
</header>
<div id="grid"></div><button id="more">Show more</button><div id="toast"></div>
<div id="bar" hidden>
  <span id="picked"></span>
  <input id="tagin" list="taglist" placeholder="tags, separated by commas">
  <datalist id="taglist"></datalist>
  <button id="add">Add</button><button id="remove">Remove</button><button id="clear">Clear selection</button>
  <div id="chips"></div>
</div>
<script src="data.js"></script>
<script>
const D = window.GALLERY, PAGE = 400, EDIT = location.protocol !== 'file:';
const NOEDIT = 'Tags can only be edited when the gallery is opened from the window or with: python main.py gallery --serve';
const $ = id => document.getElementById(id);
const groupSel = $('group'), versionSel = $('version'), statusSel = $('status'), sizeSel = $('size'), tagSel = $('tag'), min = $('min'), max = $('max'), search = $('search'), grid = $('grid'), more = $('more');
const byId = new Map(D.sprites.map(s => [s[0], s])), tiles = new Map(), selected = new Set();
let shown = 0, matches = [], anchor = -1;
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
function refreshTags() {  // the tag filter and the bar's suggestions, A to Z: every tag with the number of pictures that have it
  const counts = new Map();
  for (const s of D.sprites) for (const tag of s[7]) counts.set(tag, (counts.get(tag) || 0) + 1);
  const sorted = [...counts].sort((a, b) => a[0].localeCompare(b[0])), keep = tagSel.value;
  tagSel.replaceChildren(new Option('Any tag', ''));
  for (const [tag, n] of sorted) tagSel.append(new Option(tag + ' (' + n + ')', tag));
  tagSel.value = counts.has(keep) ? keep : '';
  $('taglist').replaceChildren(...sorted.map(([tag]) => new Option(tag)));
}
function pass(s) {
  const [id, group, name, w, h, added, changed, tags] = s;
  if (groupSel.value && group !== groupSel.value) return false;
  const terms = search.value.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length) {
    const hay = (id + ' ' + tags.join(' ')).toLowerCase();
    if (!terms.every(t => hay.includes(t))) return false;
  }
  if (tagSel.value && !tags.includes(tagSel.value)) return false;
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
  const [id, group, name, w, h, added, changed, tags] = s;
  const t = document.createElement('div'); t.className = 'tile' + (selected.has(id) ? ' sel' : '');
  t.title = id + (tags.length ? '\ntags: ' + tags.join(', ') : '')
    + '\nfirst extracted in ' + versionOf(added) + (D.used[id] ? '\nin the webapp: ' + D.used[id].join(', ') : '');
  const pic = document.createElement('div'); pic.className = 'pic';
  const img = document.createElement('img'); img.loading = 'lazy'; img.src = encodeURI(group + '/' + name + '.png'); pic.append(img);
  t.append(pic);
  const nm = document.createElement('div'); nm.className = 'name'; nm.textContent = name;
  const sz = document.createElement('div'); sz.className = 'size'; sz.textContent = w + ' x ' + h;
  t.append(nm, sz);
  const chips = document.createElement('div');
  for (const tag of tags.slice(0, 3)) chips.append(Object.assign(document.createElement('span'), { className: 'tg', textContent: tag }));
  t.append(chips);
  if (added > D.baseline) t.append(Object.assign(document.createElement('span'), { className: 'badge', textContent: 'NEW' }));
  else if (changed > D.baseline) t.append(Object.assign(document.createElement('span'), { className: 'badge changed', textContent: 'CHANGED' }));
  if (D.used[id]) t.append(Object.assign(document.createElement('span'), { className: 'used', textContent: 'in webapp' }));
  t.onclick = e => {
    if (e.ctrlKey || e.metaKey) pick(s, false);
    else if (e.shiftKey) pick(s, true);
    else copy(id);
  };
  tiles.set(id, t);
  return t;
}
function toast(text) {
  const el = $('toast'); el.textContent = text; el.classList.add('on'); setTimeout(() => el.classList.remove('on'), 1400);
}
function copy(text) {
  const done = () => toast('Copied ' + text);
  if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, () => fallback(text, done)); else fallback(text, done);
}
function fallback(text, done) {
  const ta = document.createElement('textarea'); ta.value = text; document.body.append(ta); ta.select(); document.execCommand('copy'); ta.remove(); done();
}
function pick(s, range) {  // ctrl-click toggles a picture, shift-click selects everything from the last one to this one
  if (!EDIT) return toast(NOEDIT);
  const at = matches.indexOf(s);
  if (range) for (let i = Math.min(anchor < 0 ? at : anchor, at); i <= Math.max(anchor < 0 ? at : anchor, at); i++) selected.add(matches[i][0]);
  else if (selected.has(s[0])) selected.delete(s[0]); else selected.add(s[0]);
  anchor = at;
  for (const [id, el] of tiles) el.classList.toggle('sel', selected.has(id));
  updateBar();
}
function updateBar() {
  $('bar').hidden = !selected.size; document.body.classList.toggle('picking', selected.size > 0);
  $('picked').textContent = selected.size + ' selected';
  const have = new Map();  // tag -> how many of the selected pictures have it
  for (const id of selected) for (const tag of byId.get(id)[7]) have.set(tag, (have.get(tag) || 0) + 1);
  $('chips').replaceChildren(...[...have].sort((a, b) => a[0].localeCompare(b[0])).map(([tag, n]) => Object.assign(document.createElement('span'), {
    className: 'tg chip', textContent: tag + (n < selected.size ? ' (' + n + '/' + selected.size + ')' : '') + ' ×',
    title: 'Remove this tag from the selected pictures',
    onclick: () => edit([], [tag]),
  })));
}
async function edit(add, remove) {  // true when saved
  let res, body;
  try {
    res = await fetch('/tags', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: [...selected], add, remove }) });
    body = await res.json().catch(() => ({}));
  } catch (e) {
    toast('Not saved: the gallery server is not running, open the gallery again'); return false;
  }
  if (!res.ok) { toast(body.error || 'Saving failed (' + res.status + ')'); return false; }
  const filtered = tagSel.value || search.value.trim();
  for (const [id, tags] of Object.entries(body.tags)) {
    byId.get(id)[7] = tags;
    if (tiles.has(id)) tiles.get(id).replaceWith(tile(byId.get(id)));
  }
  refreshTags(); updateBar();
  if (filtered) { const y = scrollY; render(); scrollTo(0, y); }  // a picture that no longer has the tag leaves the list
  toast('Saved'); return true;
}
function typed() { return $('tagin').value.split(',').map(t => t.trim()).filter(Boolean); }
$('add').onclick = async () => { const t = typed(); if (t.length && await edit(t, [])) $('tagin').value = ''; };
$('remove').onclick = async () => { const t = typed(); if (t.length && await edit([], t)) $('tagin').value = ''; };
$('clear').onclick = () => { selected.clear(); for (const el of tiles.values()) el.classList.remove('sel'); updateBar(); };
function render() {
  matches = D.sprites.filter(pass); shown = 0; anchor = -1; grid.replaceChildren(); tiles.clear(); next();
  $('count').textContent = matches.length + ' pictures';
}
function next() {
  for (const s of matches.slice(shown, shown + PAGE)) grid.append(tile(s));
  shown = Math.min(shown + PAGE, matches.length); more.style.display = shown < matches.length ? '' : 'none';
}
more.onclick = next;
groupSel.onchange = versionSel.onchange = statusSel.onchange = sizeSel.onchange = tagSel.onchange = render; search.oninput = min.oninput = max.oninput = render;
refreshTags(); render();
</script></body></html>
"""


def build_data(index: dict, matches: dict, mapping: dict | None = None, tags: dict | None = None) -> dict:
    """What the page needs: sprites as [id, group, name, w, h, added, changed, tags] (the picture's own tags, see `tags.py`),
    group counts, the resource version of every extract run (`runs`: run -> version, so `added` says in which version a picture
    first showed up) and which sprite is in the webapp: by a close hash, or as the source of a mapped webapp image (an image
    cropped from its sprite hashes far away)."""
    tags = tags or {}
    sprites = sorted((s for s in index["sprites"].values() if C.is_picture(s)), key=lambda s: (s["group"].lower(), s["name"].lower()))
    groups: dict[str, int] = {}
    for s in sprites:
        groups[s["group"]] = groups.get(s["group"], 0) + 1
    used: dict[str, list[str]] = {}
    for path, candidates in matches.items():
        if candidates and candidates[0]["dist"] <= M.CLOSE:
            used.setdefault(candidates[0]["id"], []).append(path)
    for path, entry in (mapping or {}).items():
        for source in Mp.sources(entry):
            if source in index["sprites"] and path not in used.get(source, []):
                used.setdefault(source, []).append(path)
    return {
        "baseline": index["meta"].get("baseline", 0),
        "runs": {run: info.get("version", "?") for run, info in index["meta"].get("runs", {}).items()},
        "groups": sorted(groups.items(), key=lambda g: g[0].lower()),
        "sprites": [[s["id"], s["group"], s["name"], s["w"], s["h"], s["added"], s["changed"], tags.get(s["id"], [])] for s in sprites],
        "used": used,
    }


def write_data(out: Path, index: dict, tags_path: Path = Tg.PATH) -> None:
    """`out/data.js`: what the page shows, with the tags as `tags_path` has them now."""
    try:
        matches = json.loads((out / "matches.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        matches = {}
    out.mkdir(parents=True, exist_ok=True)
    data = build_data(index, matches, Mp.load(), Tg.load(tags_path))
    (out / "data.js").write_text("window.GALLERY = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")


def write(out: Path = C.OUT) -> Path:
    write_data(out, S.load_index())
    page = out / "index.html"
    page.write_text(PAGE, encoding="utf-8")
    return page


def start(out: Path = C.OUT) -> tuple[http.server.ThreadingHTTPServer, str]:
    """Write the gallery and serve it (`serve`): the server and the address to open."""
    write(out)
    return serve(S.load_index(), out)


def stop(server: http.server.ThreadingHTTPServer) -> None:
    """Stop a server `serve` started and give its port back."""
    server.shutdown()
    server.server_close()


def serve(index: dict, out: Path = C.OUT, path: Path = Tg.PATH) -> tuple[http.server.ThreadingHTTPServer, str]:
    """Serve `out/` on 127.0.0.1 (a free port) in a thread, and take the page's tag edits (`POST /tags`: {ids, add, remove}
    -> `tags.apply`, answers {"tags": {id: [tag, ...]}}). Only requests made to this server's own address are
    answered (a web page of another site cannot get at it), and a POST must be JSON (a browser asks first when another
    site sends one, and nothing answers that). A saved edit also rewrites `data.js`, so a reload shows it. Returns the server
    (`stop` ends it) and the gallery's address."""
    known = {s["id"] for s in index["sprites"].values() if C.is_picture(s)}
    lock = threading.Lock()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(out), **kwargs)

        def log_message(self, *args) -> None:  # the window's log has no use for every picture requested
            pass

        def own(self) -> bool:
            port = self.server.server_port
            return self.headers.get("Host") in (f"127.0.0.1:{port}", f"localhost:{port}")

        def end_headers(self) -> None:  # a reload must see the tags just saved, not a cached data.js
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def reply(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.own():
                super().do_GET()
            else:
                self.reply(403, {"error": "not this server's address"})

        def do_HEAD(self) -> None:
            if self.own():
                super().do_HEAD()
            else:
                self.reply(403, {"error": "not this server's address"})

        def do_POST(self) -> None:
            if not self.own():
                return self.reply(403, {"error": "not this server's address"})
            if self.path != "/tags":
                return self.reply(404, {"error": "no such address"})
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self.reply(415, {"error": "JSON expected"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 1_000_000:
                    raise ValueError("no body, or too large")
                body = json.loads(self.rfile.read(length))
                ids, add, remove = body["ids"], body.get("add", []), body.get("remove", [])
                if not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in (ids, add, remove)):
                    raise ValueError("ids, add and remove must be lists of text")
                with lock:
                    changed = Tg.apply(ids, add, remove, known, path)
                    write_data(out, index, path)
            except (ValueError, KeyError, TypeError) as e:
                return self.reply(400, {"error": str(e)})
            except OSError as e:  # tags.json locked by an editor, disk full, ...
                return self.reply(500, {"error": f"could not save: {e}"})
            self.reply(200, {"tags": changed})

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/index.html"
