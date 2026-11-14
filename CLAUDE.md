# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Last Asylum: Plague - tools

Two local Python helper tools for the mobile game "Last Asylum: Plague" and its webapp, Klingo's Companion (repository
`last-asylum-plague`, checked out next to this one as `../last-asylum-pack-solver`). They are not part of the webapp and are
never deployed. Each tool is a self-contained folder with its own `requirements.txt`, `.venv`, tests and `.gitignore`; they
share no code. Windows, BlueStacks (Android emulator) through ADB.

- `game_asset_extractor/` takes the game's pictures from BlueStacks and makes the webapp's images from them.
  Its `README.md` explains the workflow; each module's header comment says what it does, read it before changing the module.
- `mahjong_minigame_helper/` reads a tile-matching minigame's board (Phantom Treasure of the Halloween Ball) and advises
  the next tap. Advisory only by default, it taps only with `--auto-click`. Usage is in the header of `main.py`.

## Git Safety

- NEVER commit, create branches, push to remote, or open PRs unless explicitly asked. Leave changes in the working tree.
- Never downgrade dependency versions to "fix" a problem. If a version looks wrong, ask first.
- Do not touch the webapp's repository (`../last-asylum-pack-solver`) beyond what a tool writes there on purpose (see below).
  Changes there are committed in that repository, separately.

## Commands

Run from the tool's own folder, with its venv (`.venv/Scripts/python`; set it up with `python -m venv .venv` and
`.venv/Scripts/python -m pip install -r requirements.txt`; use `python -m pip`, a moved venv's `pip.exe` points at the old path).

```bash
.venv/Scripts/python -m pytest -q          # the tool's tests (game_asset_extractor: 108, mahjong_minigame_helper: 64)
.venv/Scripts/python main.py --help        # the CLI (game_asset_extractor: also gui.py / start_gui.bat; mahjong: gui.py)
```

Tests use small inline data and need neither the game nor a device. The Mahjong tests on recorded games skip themselves when
the recording (git-ignored `recordings/`) is missing; the mapping-editor test skips when Tk cannot start. There is no CI.

## Game Asset Extractor

- Pipeline: `scan` (the game's file list against what was pulled) > `pull` (bundles into `cache/`) > `extract` (PNGs into
  `out/<type>/<group>/<name>.png`, `out/index.json`) > `match` (perceptual hash of every webapp image against the sprites,
  `out/matches.json`) > `gallery` (`out/index.html`). `mapping.py` / `render.py` / `importer.py` make the webapp's images from
  the mapped game pictures.
- `mapping.json` (committed here) says which game picture each webapp image is made from (`source`, crop `focus`, `resize`,
  `overlay`: a second picture on top, e.g. a trophy, `synced` fingerprint). It is data about the webapp's files: edit it through
  the mapping editor (`gui.py` > Edit mapping) or `main.py map` / `import`, not by hand.
- The webapp's images are written to the webapp's repository: `config.WEBAPP_ASSETS`, `../last-asylum-pack-solver/webapp/public/assets`
  or under `LAST_ASYLUM_WEBAPP`. The commands that touch it (`match`, `update`, `map`, `status`, `sync`, `import`) stop with a
  message when it is missing (`config.require_webapp`), so nothing is written to a wrong place. `sync` / `import` change files
  there: say so in the report, never commit them.
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
