# Game Asset Extractor

The pictures of *Last Asylum: Plague* for the webapp, taken from the game itself (BlueStacks, through ADB) instead of
screenshots. A local helper: its downloads and results (`cache/`, `out/`, `state/`) are git-ignored and never committed.
It lives in the tools repository and works on the webapp's images in the webapp's own repository,
checked out next to it as `last-asylum-pack-solver` (or at `LAST_ASYLUM_WEBAPP`, see `config.py`): `sync`, `import` and
`status` stop with a message when they do not find `webapp/public/assets` there. The images it writes are committed in
the webapp's repository, `mapping.json` here.

## What it does

The game is a Unity game. Its pictures sit in unencrypted asset bundles (`*.assetbundles`) on the device: the
install-time asset pack (`split_abPack1.apk`) and the hot-updated ones on the sdcard. The game's own file list
(`ABAsset/Version.txt`, one md5 per bundle) tells what is new, so no screenshots and no network interception are needed.

1. **Scan** reads that file list and compares it with what was downloaded before: new / changed / unchanged bundles
   per kind and folder (the pictures and the game texts are always taken; tick more kinds if you want them). It downloads nothing.
2. **Download & extract** pulls exactly those bundles (md5-checked) into `cache/` and cuts every sprite and texture out
   as a PNG: `out/<kind>/<folder>/<name>.png` (item icons are 144 x 144 with transparency, like the webapp's), so a
   kind (pictures, effects, models, ...) is one folder to delete. The match and the gallery only look at the pictures.
   A bundle without a picture leaves no folder.
   The game texts, tables and scripts (kind "Game texts, tables & scripts") hold no pictures: their files are written
   as they are to `out/data/<the bundle's path>/` (`.txt` when readable, `.bin` when obfuscated, as the tables and Lua scripts are).
   What is new or changed in the language texts is recorded per extract run (`out/texts.json`), like the pictures'.
3. **Match** compares every PNG and WebP of `webapp/public/assets` with the sprites by a perceptual hash
   (`out/matches.json`).
4. The **gallery** (`out/index.html`) shows it all: search (names and your tags, see Tags), folders, a tag filter, "new or changed since marked as seen" (or only new, or only changed), "not in the
   webapp yet" / "already in the webapp" (by look, or as the source of a mapped image, so cropped ones count too), resource version
   a picture was first extracted in (each extract run records the game's resource version, shown as `1.0.818`; the first run's
   version means "this or earlier"), size (the four most frequent sizes, or a range of the longer side). Click a picture to copy its id. **Mark all as seen** (`main.py baseline`, the one button of the Scan & download group, for pictures and texts together) starts
   the NEW / CHANGED badges over.
5. **Map**: `mapping.json` (committed) says which game picture each webapp image is made from. The **mapping editor**
   (window: Pictures > Edit mapping...) shows the webapp picture, the game picture and what Sync would make of it, side by side;
   confirm a suggestion, pick another picture, or mark "no original in the game". `main.py map --accept 10` takes every
   near-identical suggestion at once.
6. **Sync** makes the mapped webapp files from the game pictures: items and heroes 144 x 144 PNG; events WebP (quality 85,
   transparency kept) where a banner of about 2:1 (1.8:1 to 2.3:1) **keeps the game's own size** (726 x 346, 706 x 360, ...;
   the page shows banners in a 2:1 `object-fit: cover` box anyway) and anything else, such as a tall poster, is cropped (not
   stretched) to 720 x 360 by the mapping's crop window. A mapping with `"resize": true` (editor checkbox, `import
   --resize`) forces 720 x 360 for a near-2:1 banner too. It only previews unless `--apply`; a file that already looks
   exactly like the result is left alone. Review it as a git diff. A mapping can also carry an `overlay` (editor: "Use chosen picture
   as overlay", with size and position sliders, each with a field for an exact value): a second game picture, e.g. a trophy, put on top of the first. The editor's **Layout** switch chooses between one picture, an overlay,
   and two or three pictures **side by side** (`beside`: equal columns of the first picture's size, each picture cropped to its column by its own crop window).
7. **Status** counts the webapp images that are *official* (mapped and made from the game's current picture): `main.py
   status`, also shown in the window. A game update that changes a picture turns its image back to "to sync".
8. **Import** adds a new picture to the webapp's assets and maps it (`import <id> items/chest/gold`, events become WebP).

### Texts

The language data (`out/data/GameData/language_F/<lang>/*.txt` UI texts, `basedb_F/<lang>/*.txt` tables with item, hero, skill
and event names and descriptions) holds every text of the game in each language the game has downloaded (English and German;
switch the game to another language once and Download & extract it). A text's id is `language/<File>:<key>` or
`tables/<Table>:<row>.<field>`.

9. The **text browser** (`out/texts/index.html`, window: Texts > Open texts, `main.py texts`) lists them all: search across all
   folders or one, a column per ticked language, "new or changed since marked as seen" (the same **Mark all as seen** as the
   gallery's), what a resource version added or changed (the first extract's version means "this or earlier"), and which texts
   the webapp maps. Click a row to copy its id.
10. **Text mapping**: `text_mapping.json` (committed) says which game text each localized text (`{ "en", "de" }`) of the webapp's
    `data/pack_data.json`, `events.json`, `hero_skills.json`, `lord_specialty.json` and `raven_epigraphs.json` is. The editor (Texts > Edit text
    mapping...) matches them by their English (markup, case and placeholder names do not count) and shows the webapp's text
    next to what the game says in every language. A text is *suggested* (its English is in the game with one translation),
    *ambiguous* (several translations: pick one), *near* (a typo? the closest game texts are offered, never taken without you)
    or *unmapped*; mark a text of the webapp's own (a guide note) as **Own text**. **Map all suggested** takes the clear ones
    at once (`main.py text-map --accept`).
    Some texts the game puts together in its code. A `%` the webapp has after a placeholder (`+{value}%`) is kept where the
    game's text has `+{0}`. A text that is made of game texts (`Lv.3 Sharp Beak` = `Lv.{0}` + `Sharp Beak`, `Hero DMG Dealt↑
    10.00%` = a game text + the number) is *suggested* as such. A placeholder the game fills in code (`CD: {0}`) is filled by
    you. Both are a **template** in the editor's field: `[[language/Common:TxtLv|0=3]] [[tables/Item:...name]]` (`|0=3` fills
    `{0}`, `|de:0=3,5` for one language; text outside the `[[ ]]` is literal and the same in every language). A click on a
    game text puts it in the field; with **Compose** on it is added to what is there. The mapping then holds `parts`
    instead of a `source`.
11. **Sync texts** writes the game's wording and translations of every mapped text into the webapp's data files, in **every**
    webapp language, English included (markup taken off, `{0}` named as the webapp names its placeholders; a text whose
    placeholders do not pair up is skipped), then formats the files with the webapp's own prettier so git shows only the
    strings. Preview first (`main.py text-sync`, or Texts > Preview sync); `--apply` writes. It changes the webapp's
    repository: review it there with `git diff` and commit it there.

### Tags

The pictures' own names are pinyin and abbreviations (`icon_dfw_baoxiang05`), so you can give them tags of your own (`chest`,
`hero`, `portrait`, ...) and find them by those: the gallery's search looks through the names and the tags, and the **Any tag**
filter lists every tag with the number of pictures that have it. Nothing is tagged automatically.

Ctrl-click pictures in the gallery (shift-click: a range), type tags separated by commas in the bar that appears at the bottom,
**Add** or **Remove**; a tag chip in the bar (`×`) removes that tag from all selected pictures. The tags are saved in `tags.json`
(committed, next to `mapping.json`, `{picture id: [tags]}`) through a small server that listens on this computer only, which
"Open gallery" / `main.py gallery --serve` start. Opened as a plain file the gallery shows and filters tags but cannot save.

### History (which version added what)

`out/` is a cache you may delete, but *which game version added or changed which picture and text* cannot be read from the
game afterwards. So every extract run also writes `history.json` (committed, next to `mapping.json`): the run to resource
version table, and per picture and text the run that added or changed it, listed only where it differs from "there from
the first run" (a game update adds a few lines). Runs of one resource version are merged into the first of them, since extracting
again within a version only says when you looked (`out/` keeps every run for the "seen" pointer). `main.py history` writes it from the cache
by hand. Commit it after each game update. The "seen" pointer is not in it.

After deleting `out/` (and `state/`), run **1 Scan** and **2 Download & extract** with every kind you had: the run numbers
continue from `history.json` (no new run), and each picture and text gets the version recorded for it. What the history does
not list counts as from the first run, so rebuild right away: what the game added since the last record would show as
"this version or earlier". A rebuild you stop halfway goes on at the next Download & extract and keeps the history.

## Setup (once)

1. BlueStacks: Settings > Advanced > **Android Debug Bridge** on (the address is usually `127.0.0.1:5555`).
2. In this folder:

   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install -r requirements.txt
   ```

   After pulling a change that adds a package (the text mapping needs `rapidfuzz`), run the second command again.
3. Syncing texts needs Node on the PATH and the webapp's own dependencies (`npm install` in `../last-asylum-pack-solver`): its
   prettier formats the files that are written.

## Use

Double-click `start_gui.bat` (or `.venv/Scripts/python gui.py`): Check ADB, **1 Scan**, **2 Download & extract**,
Mark all as seen; then the Pictures group (Open gallery, Edit mapping, Preview sync / Sync to webapp, Import) and
the Texts group (Open texts, Edit mapping, Preview sync / Sync to webapp). The same from the command line (`python main.py --help`):

```bash
python main.py check
python main.py scan                       # what is new since the last download
python main.py update                     # pull + extract + match + gallery (new / changed only)
python main.py gallery --serve            # the gallery on a local server, so tags can be saved (the window's "Open gallery" does this)
python main.py update --types effects,models   # pictures and game texts are always taken; more kinds: effects, models, scenes, layouts, other (or all, about 1 GB)
python main.py baseline                   # everything extracted so far counts as seen
python main.py map --accept 10            # map near-identical suggestions (distance <= 10 of 256)
python main.py status                     # how many webapp images are official
python main.py sync                       # preview: which webapp files would be made from the game pictures
python main.py sync --apply               # write them (git diff shows the result)
python main.py texts                      # write out/texts/index.html, the text browser
python main.py text-status                # how many of the webapp's texts are the game's own
python main.py text-map --accept          # map every suggested text (its English is in the game with one translation)
python main.py text-sync                  # preview: what the game's texts would change in the webapp's data files
python main.py text-sync --apply          # write it (git diff in the webapp shows the result)
python main.py import Zombie_ItemIcon144/icon_gold items/material/gold
python main.py import Zombie_MallGiftIcon/pic_mzth_dazaocailiao packages/exp_special_pack   # a weekday offer's own picture (WebP, game size)
python main.py import Zombie_Act_WorldBoss2/pic_sjboss_haibao events/new_boss --focus 0.5,0.1   # a tall poster: crop window
```

After a game update, run Scan again: the table shows which folders got new or changed bundles (new events and
packs show up here early). Download & extract, then filter the gallery by "New or changed in the last update".

## Notes

- Names are the game's (Chinese pinyin: `icon_baoxiang`, `jingcaibi`), not the webapp's item ids. The gallery's
  "in the webapp" mark and `matches.json` (the three closest sprites per webapp image) help to find the pairs; recoloured
  rarities of one icon look alike to the hash, so check the picture.
- Atlases are cut with their own sprite table (`mSprites`, x/y from the top left); loose textures (banners, backgrounds)
  are exported whole. A texture format UnityPy cannot decode is reported and skipped.
- Tests: `.venv/Scripts/python -m pytest` (small inline data; no game files needed).
