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
   per kind and folder (tick the kinds to look at; pictures are on by default). It downloads nothing.
2. **Download & extract** pulls exactly those bundles (md5-checked) into `cache/` and cuts every sprite and texture out
   as a PNG: `out/<folder>/<name>.png` (item icons are 144 x 144 with transparency, like the webapp's).
3. **Match** compares every PNG and WebP of `webapp/public/assets` with the sprites by a perceptual hash
   (`out/matches.json`).
4. The **gallery** (`out/index.html`) shows it all: search, folders, "new or changed since marked as seen" (or only new, or only changed), "not in the
   webapp yet" / "already in the webapp" (by look, or as the source of a mapped image, so cropped ones count too), size
   (the four most frequent sizes, or a range of the longer side). Click a picture to copy its id. **Mark all as seen** (`main.py baseline`) starts
   the NEW / CHANGED badges over.
5. **Map**: `mapping.json` (committed) says which game picture each webapp image is made from. The **mapping editor**
   (window: Edit mapping...) shows the webapp picture, the game picture and what Sync would make of it, side by side;
   confirm a suggestion, pick another picture, or mark "no original in the game". `main.py map --accept 10` takes every
   near-identical suggestion at once.
6. **Sync** makes the mapped webapp files from the game pictures: items and heroes 144 x 144 PNG; events WebP (quality 85,
   transparency kept) where a banner of about 2:1 (1.8:1 to 2.3:1) **keeps the game's own size** (726 x 346, 706 x 360, ...;
   the page shows banners in a 2:1 `object-fit: cover` box anyway) and anything else, such as a tall poster, is cropped (not
   stretched) to 720 x 360 by the mapping's crop window. A mapping with `"resize": true` (editor checkbox, `import
   --resize`) forces 720 x 360 for a near-2:1 banner too. It only previews unless `--apply`; a file that already looks
   exactly like the result is left alone. Review it as a git diff. A mapping can also carry an `overlay` (editor: "Use chosen picture
   as overlay", with size and position sliders): a second game picture, e.g. a trophy, put on top of the first.
7. **Status** counts the webapp images that are *official* (mapped and made from the game's current picture): `main.py
   status`, also shown in the window. A game update that changes a picture turns its image back to "to sync".
8. **Import** adds a new picture to the webapp's assets and maps it (`import <id> items/chest/gold`, events become WebP).

## Setup (once)

1. BlueStacks: Settings > Advanced > **Android Debug Bridge** on (the address is usually `127.0.0.1:5555`).
2. In this folder:

   ```bash
   python -m venv .venv
   .venv/Scripts/pip install -r requirements.txt
   ```

## Use

Double-click `start_gui.bat` (or `.venv/Scripts/python gui.py`): Check ADB, **1 Scan**, **2 Download & extract**,
Open gallery, Edit mapping, Preview sync / Sync to webapp, Import. The same from the command line (`python main.py --help`):

```bash
python main.py check
python main.py scan                       # what is new since the last download
python main.py update                     # pull + extract + match + gallery (new / changed only)
python main.py update --filter itemicon   # only bundles whose Unity path matches the regex
python main.py update --types pictures,data   # more kinds: effects, models, scenes, layouts, data, other (or all, about 1 GB)
python main.py baseline                   # everything extracted so far counts as seen
python main.py map --accept 10            # map near-identical suggestions (distance <= 10 of 256)
python main.py status                     # how many webapp images are official
python main.py sync                       # preview: which webapp files would be made from the game pictures
python main.py sync --apply               # write them (git diff shows the result)
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
