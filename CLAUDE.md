# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Last Asylum: Plague - tools

Three local Python helper tools for the mobile game "Last Asylum: Plague" and its webapp, Klingo's Companion (repository
`last-asylum-plague`, checked out next to this one as `../last-asylum-pack-solver`). They are not part of the webapp and are
never deployed. Each tool is a self-contained folder with its own `requirements.txt`, `.venv`, tests and `.gitignore`; they
share no code. Windows, BlueStacks (Android emulator) through ADB.

- `game_asset_extractor/` takes the game's pictures from BlueStacks and makes the webapp's images from them.
  Its `README.md` explains the workflow; each module's header comment says what it does, read it before changing the module.
- `mahjong_minigame_helper/` reads a tile-matching minigame's board (Phantom Treasure of the Halloween Ball) and advises
  the next tap. Advisory only by default, it taps only with `--auto-click`. Usage is in the header of `main.py`.
- `game_ad_ranking_capture/` reads the Alliance Duel's daily ranking from the game (ADB screenshots + OCR) into one file per
  calendar week and shows it in a local browser page. Usage is in the header of `main.py`, details in its `README.md`.

## Git Safety

- NEVER commit, create branches, push to remote, or open PRs unless explicitly asked. Leave changes in the working tree.
- Never downgrade dependency versions to "fix" a problem. If a version looks wrong, ask first.
- Do not touch the webapp's repository (`../last-asylum-pack-solver`) beyond what a tool writes there on purpose (see below).
  Changes there are committed in that repository, separately.

## Commands

Run from the tool's own folder, with its venv (`.venv/Scripts/python`; set it up with `python -m venv .venv` and
`.venv/Scripts/python -m pip install -r requirements.txt`; use `python -m pip`, a moved venv's `pip.exe` points at the old path).

```bash
.venv/Scripts/python -m pytest -q          # the tool's tests (game_asset_extractor: 218, mahjong_minigame_helper: 64, game_ad_ranking_capture: 84)
.venv/Scripts/python main.py --help        # the CLI (game_asset_extractor and game_ad_ranking_capture: also gui.py / start_gui.bat; mahjong: gui.py)
```

Tests use small inline data and need neither the game nor a device. The Mahjong tests on recorded games skip themselves when
the recording (git-ignored `recordings/`) is missing; the mapping-editor test skips when Tk cannot start. CI (`.github/workflows/test.yml`, Windows) runs all three suites with no
webapp checkout and a small screen: tests stub the webapp's folder and size the editor window themselves.

## Game Asset Extractor

- Pipeline: `scan` (the game's file list against what was pulled) > `pull` (bundles into `cache/`) > `extract` (PNGs into
  `out/<type>/<group>/<name>.png`, `out/index.json`) > `match` (perceptual hash of every webapp image against the sprites,
  `out/matches.json`) > `gallery` (`out/index.html`). `mapping.py` / `render.py` / `importer.py` make the webapp's images from
  the mapped game pictures.
- `mapping.json` (committed here) says which game picture each webapp image is made from (`source`, crop `focus`, `resize`,
  `overlay`: a second picture on top, e.g. a trophy, `beside`: one or two more pictures next to the first in equal columns, `synced` fingerprint). It is data about the webapp's files: edit it through
  the mapping editor (`gui.py` > Pictures > Edit mapping) or `main.py map` / `import`, not by hand.
- The webapp's images are written to the webapp's repository: `config.WEBAPP_ASSETS`, `../last-asylum-pack-solver/webapp/public/assets`
  or under `LAST_ASYLUM_WEBAPP`. The commands that touch it (`match`, `update`, `map`, `status`, `sync`, `import`) stop with a
  message when it is missing (`config.require_webapp`), so nothing is written to a wrong place. `sync` / `import` change files
  there: say so in the report, never commit them.
- Texts: the kind "data" (on by default) is extracted as files; `texts.py` reads them (`language_F` CSV, `basedb_F` Lua tables), records
  per extract run which texts were added / changed (`out/texts.json`, same runs and baseline as the pictures), `text_browser.py`
  writes `out/texts/index.html`. `text_mapping.json` (committed) says which game text each localized `{en, de}` of the webapp's
  `data/*.json` is; it is data, edited through the editor (`text_mapping_gui.py`) or `main.py text-map`. An entry is one game text
  (`source`, with a `fill` for a placeholder the game's code fills) or `parts` (game texts and literal text, for what the game puts
  together in code: `Lv.3 Sharp Beak`), written as a template in the editor (`text_mapping.parse_template`). `text-sync --apply` rewrites
  the webapp's data files (every language, English included) and formats them with the webapp's prettier: say so in the report,
  never commit them. `name.de` in the webapp stays the game's own text: it only ever comes from here, never from a guess.
- Tags (the gallery): only the user's own, in `tags.json` (committed, `tags.py`, `{picture id: [tags]}`), edited only through the
  gallery's local server (`gallery.serve`, 127.0.0.1, `POST /tags`; the window's "Open gallery" / `gallery --serve`), not by hand.
  No automatic tagging (game tables, AI): it was tried and dropped, the user wants manual tags only; don't re-propose it.
- `history.json` (committed, `history.py`) is the only copy of which game version added or changed each picture and text (runs merged per resource version,
  and per picture / text the run, only where it differs from the first run); extract writes it at the end of every run and a cache
  that starts empty is rebuilt from it. Commit it after each game update. The "seen" pointer (`meta.baseline`) stays local.
- `cache/`, `out/` (about 1.5 GB together) and `state/` are local, git-ignored game data. Never commit them or the game's files.
- Folder rules of the webapp's images (`render.py`): `items/` and `heroes/` 144x144 PNG, `events/` WebP (a banner of about 2:1 keeps
  the game's size, anything else is cropped to 720x360), `packages/` WebP as it is. Keep these in step with the webapp's own
  asset conventions (its `CLAUDE.md`).
- The gallery page (`gallery.py`) is one Python string with its JavaScript inside; a test runs `node --check` on it, so a
  stray escape sequence is caught.
- `gui.py` and `mapping_gui.py` are tkinter: a new field must fit the window the editor opens at (`CANDIDATES_HEIGHT`, the
  fixed note lines reserve the space a selection fills in).

## Mahjong Minigame Helper

- Pipeline: `capture.py` (frames and taps through ADB) > `vision.py` (finds the tiles) > `kinds.py` (which icon a tile shows) >
  `board.py` (the mental map across frames) > `solver.py` / `solver_fast.py` (search to the end of the game; the fast one is
  compiled with numba, required) > `advice.py` and `overlay.py` (what is shown over the game window).
- Everything that differs between minigames is a profile: `profiles/<name>/profile.json` plus the learned icons
  (`kinds.npz`, git-ignored and rebuilt by `train`; `kinds_default.npz` is the committed starting point). Default profile:
  `halloween_ball`.
- `record` saves settled boards as `recordings/<profile>/<run>/` (git-ignored: the test data and what `train`, `evaluate` and
  `advice` read). `truth.py` derives the ground truth from a recorded game.
- Auto-click sends real taps to the game: do not run `run --auto-click` (or anything that taps) unless asked.

## Game AD Ranking Capture

- Pipeline: `device.py` (ADB frames, taps, swipes) > `screens.py` (which screen, map -> Duel icon -> Rank -> day tab) >
  `scan.py` (one day's list: swipe, `rows.py` reads a page, merge by rank; self-calibrating swipe length) > `capture.py`
  (all days, writes the week file) > `store.py` / `corrections.py` / `aggregate.py` > `viewer_server.py` + `viewer/index.html`.
  `members.py` + `roster.py` read the alliance's member list (Alliance Members screen, folded rank groups opened) into
  `data/members/<year>-W<week>.json` (one file per week; a day uses the latest list valid by then, weeks before the first list
  get none; after a ranking scan `roster.hints` reports names that do not match the list); `aggregate.py` counts a member missing from a day's ranking as 0 points. The screen only takes a drag
  that starts on a card: swipes that start on a header or in a gap are retried from other heights.
  `ocr.py` is RapidOCR (default engine, plus a Cyrillic one only for rows the first could not read; `symbols.py` reads names
  made of square symbols by shape). `gui.py` is the
  window (`start_gui.bat` makes the venv, installs the requirements, starts it); a task thread must not touch Tk.
  The viewer colours the daily points, average and median by the Duel's 9 reward phases (`config.PHASES`, `COLOR_SCALE`;
  position on the scale computed in `aggregate.py`, the page only maps it to a colour).
- The only game input is taps and swipes: never start a capture (or anything that taps) unless asked, and never while the
  user may be using the emulator (they play on it too). Navigation checks the screen after every step and gives up on an
  unknown one instead of tapping around; it leaves screens with the on-screen back arrow, never the Android back key.
- `data/<year>-W<week>.json` (committed, written by `store.py`, never by hand) holds one calendar week: a day is `final`
  once a complete scan of it started after its game day ended (02:00 UTC reset, 03:00 CET); until then it is preliminary and read again. A day tab the game does not switch to has no data yet.
  `corrections.json` (committed; sections `corrections` for OCR misreadings, `aliases` for players who renamed) is applied
  when the table is built (`corrections.py`), never written into the week files: final days are not scanned again. The
  crops of rows to check are in the git-ignored `review/`. The files hold other players' names: don't paste
  them into places outside this repository.
- Layout numbers (`config.py`) are fractions of the 1080 x 1920 portrait frame; the Duel icon template is
  `templates/duel_icon.png`. A game update that moves the screens means measuring them again from a screenshot.
