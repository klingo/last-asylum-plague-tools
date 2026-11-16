# Last Asylum: Plague - tools

Local helper tools for the [Klingo's Companion](https://github.com/klingo/last-asylum-plague) webapp. They are not part
of the webapp and never deployed with it.

| Folder                    | What it is                                                                                          |
| ------------------------- | --------------------------------------------------------------------------------------------------- |
| `game_asset_extractor/`   | Takes the game's pictures from BlueStacks (ADB) and makes the webapp's images from them.            |
| `mahjong_minigame_helper/`| Reads the Halloween Ball (mahjong) minigame's board and suggests the next move.                      |
| `game_ad_ranking_capture/`| Reads the Alliance Duel's daily ranking from the game (ADB + OCR) into weekly files and shows it.     |

Each tool has its own `requirements.txt` and `.venv`; see its README (or the top of `main.py`).

## Layout

The Game Asset Extractor reads and writes the webapp's pictures (`webapp/public/assets`), so the webapp's repository must be
checked out **next to this one**, as `last-asylum-pack-solver`:

```
Projects/
  last-asylum-pack-solver/    the webapp  (github.com/klingo/last-asylum-plague)
  last-asylum-plague-tools/   this repository
```

Another place: set the environment variable `LAST_ASYLUM_WEBAPP` to the webapp's folder. Its `mapping.json` (which game
picture each webapp image is made from) is committed here; the images it writes are committed in the webapp's repository.
