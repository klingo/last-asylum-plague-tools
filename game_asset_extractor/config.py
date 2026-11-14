"""Where things live, and what counts as an image bundle."""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"  # the bundles as pulled from the device, by file name
OUT = HERE / "out"  # the PNGs (out/<type>/<group>/<name>.png, the type being a key of TYPES), index.json, matches.json, the gallery, the texts (data/, texts.json, texts/)
STATE = HERE / "state"  # what was pulled / extracted, the last scan
# The webapp lives in its own repository (last-asylum-plague), checked out next to this one as `last-asylum-pack-solver`
# (or wherever LAST_ASYLUM_WEBAPP points); the pictures it shows are in its webapp/public/assets.
WEBAPP = Path(os.environ.get("LAST_ASYLUM_WEBAPP") or HERE.parents[1] / "last-asylum-pack-solver")
WEBAPP_ASSETS = WEBAPP / "webapp" / "public" / "assets"
WEBAPP_DATA = WEBAPP / "data"  # the data files whose texts the text mapping syncs
WEBAPP_I18N = WEBAPP / "webapp" / "src" / "i18n"  # one <lang>.json per language the webapp speaks


def require_webapp(folder: Path | None = None) -> Path:
    """The webapp's assets folder (or another of its folders), or an error that says where it was looked for (so nothing
    is written to a wrong place)."""
    folder = folder or WEBAPP_ASSETS
    if not folder.is_dir():
        raise FileNotFoundError(f"the webapp's folder is not at {folder} - check out the webapp repository there "
                                "or set LAST_ASYLUM_WEBAPP to its folder")
    return folder


PACKAGE = "com.phs.global"  # Last Asylum: Plague
DEFAULT_SERIAL = "127.0.0.1:5555"  # BlueStacks' usual ADB address (Settings > Advanced > Android Debug Bridge)
ADB_CANDIDATES = (
    r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
    r"C:\Program Files\BlueStacks\HD-Adb.exe",
    r"C:\Program Files (x86)\BlueStacks\HD-Adb.exe",
)

# What a scan can take, by the manifest's `pathName`: key -> (label, path prefixes). The first type whose prefix fits wins,
# whatever fits none is "other". The pictures and the game texts are always taken (REQUIRED_TYPES); the rest is optional (a
# bundle of any type that holds textures yields them as pictures too).
TYPES = {
    "pictures": ("Pictures (atlases, banners, backgrounds)", ("UI/Atlas/", "UITexture/")),
    "data": ("Game texts, tables & scripts", ("GameData/", "LuaScript")),
    "effects": ("Effects, spines & animations", ("Assets/EffectClassify/", "Effects/", "Spines/", "UI/Models/", "UI/DynamicLoadEffects/", "UI/UI_Animation/")),
    "models": ("Characters, props & NPCs (3D)", ("Assets/ArtResources/", "Role/")),
    "scenes": ("Scenes & maps", ("Scenes/",)),
    "layouts": ("UI layouts (prefabs)", ("UI/UIModules/", "UI/CommonPrefab/", "UI/Components/", "UI/Test/")),
    "other": ("Other (fonts, shaders, plugins, ...)", ()),
}
REQUIRED_TYPES = ("pictures", "data")  # always scanned, downloaded and extracted: the webapp's images and texts come from them
TEXT_TYPES = ("data",)  # the types whose bundles hold TextAssets (tables, texts, scripts), written as files instead of cut into pictures
GAME_TEXTS = OUT / "data" / "GameData"  # where the extracted game texts are: language_F/<lang>/<File>.txt and basedb_F/<lang>/<Table>.txt
PICTURES = "pictures"  # the type whose PNGs are the game's pictures: the gallery, the hash match and the mapping work on these only


def is_picture(sprite: dict) -> bool:
    """Is an `out/index.json` entry one of the game's pictures (and not a texture of an effect, a model, ...)?"""
    return sprite.get("type") == PICTURES
