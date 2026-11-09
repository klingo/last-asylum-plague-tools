"""Game profiles: everything that differs between minigames of this kind (stacked tiles, a tray, N equal tiles vanish).

A profile lives in `profiles/<name>/`: `profile.json` (geometry, colours, tray, rules) and the icon library
(`kinds_default.npz` shipped, `kinds.npz` learned while playing). The code itself holds no game-specific numbers
that matter: `activate()` writes a profile into the module constants of `vision`, `kinds` and `solver`, scaling the
pixel thresholds that were tuned on the Halloween Ball tiles (half-tile pitch 50.5 canonical px) by the new tile size.

Geometry is in canonical px: the game area is always rescaled to `vision.CANON_W` (760) px wide first.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILES = HERE / "profiles"
DEFAULT_NAME = "halloween_ball"
REFERENCE_PITCH_X = 101.0  # tile pitch of the profile the pixel thresholds were tuned on


@dataclass
class Profile:
    name: str
    pitch: tuple[float, float] = (101.0, 106.7)  # tile-to-tile distance of free tiles side by side / one above another
    tile: tuple[int, int] = (100, 106)  # footprint of a tile, outline and lip included
    ring: tuple[int, int] = (94, 92)  # face box found by the ring match
    corner: tuple[int, int] = (3, 3)  # footprint starts this far left / above the ring-match corner
    icon: tuple[int, int, int, int] = (6, 6, 88, 80)  # icon area relative to the ring-match corner
    face_free: tuple[int, int, int] = (213, 217, 247)  # RGB of a free tile's face
    face_dim: tuple[int, int, int] = (123, 126, 139)  # RGB of a covered tile's face
    lip_dim: tuple[int, int, int] = (95, 93, 126)  # RGB of the shaded band along a covered tile's bottom
    outline_max_v: int = 112  # brightness below which a pixel is outline
    tray_color: tuple[int, int, int] = (123, 65, 57)  # RGB of the tray bar
    tray_slots: int = 7
    tray_pad: int = 13  # tray bar edge to the first slot's ring-match corner
    match: int = 3  # equal tiles in the tray that vanish
    grid: tuple[float, float, float, float] | None = None  # half-tile lattice (x0, y0, hx, hy), the same in every
    # stage; learned by `train` from the recordings (None: fitted on every board)
    notes: dict = field(default_factory=dict)  # free text from `train` (sources, review hints)

    @property
    def dir(self) -> Path:
        return PROFILES / self.name

    @property
    def scale(self) -> float:
        """Tile size relative to the profile the pixel thresholds were tuned on."""
        return self.pitch[0] / REFERENCE_PITCH_X


def load(name: str | None = None) -> Profile:
    name = name or DEFAULT_NAME
    path = PROFILES / name / "profile.json"
    if not path.exists():
        raise FileNotFoundError(f"no profile {name!r} ({path})")
    data = json.loads(path.read_text(encoding="utf-8"))
    for key, value in data.items():
        if isinstance(value, list):
            data[key] = tuple(value)
    data["name"] = name
    return Profile(**data)


def save(p: Profile) -> Path:
    p.dir.mkdir(parents=True, exist_ok=True)
    path = p.dir / "profile.json"
    data = asdict(p)
    data.pop("name")
    lines = [f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in data.items()]  # one setting per line
    path.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")
    return path


def recordings_dir(name: str) -> Path:
    """Where the recordings of this minigame go (one sub-folder per game)."""
    return HERE / "recordings" / name


def create(name: str, template: str = DEFAULT_NAME) -> Profile:
    """A new, untrained profile for another minigame: a copy of `template`'s settings, no icons yet. Good for
    recording right away; its own settings and icons come from training on those recordings."""
    name = name.strip()
    if not name or not all(c.isalnum() or c in "-_" for c in name):
        raise ValueError("use letters, digits, - and _ only")
    if (PROFILES / name).exists():
        raise ValueError(f"profile {name!r} exists already")
    p = load(template)
    p = Profile(**{**{k: getattr(p, k) for k in p.__dataclass_fields__}, "name": name, "grid": None,
                   "notes": {"status": f"untrained copy of {template}: record games of this minigame with it selected"}})
    save(p)
    return p


def available() -> list[str]:
    return sorted(d.name for d in PROFILES.iterdir() if (d / "profile.json").exists()) if PROFILES.exists() else []


def activate(p: Profile) -> None:
    """Make the vision, icon and solver modules use this profile."""
    import numpy as np

    import kinds
    import solver
    import vision

    s = p.scale
    rgb = lambda c: np.array(c, np.float32)  # noqa: E731
    vision.FACE_FREE, vision.FACE_DIM, vision.LIP_DIM = rgb(p.face_free), rgb(p.face_dim), rgb(p.lip_dim)
    vision.DIM_FACTOR = vision.FACE_DIM / vision.FACE_FREE
    vision.TRAY_COLOR = rgb(p.tray_color)
    vision.PITCH_X, vision.PITCH_Y = p.pitch
    vision.TILE_W, vision.TILE_H = p.tile
    vision.RING_W, vision.RING_H = p.ring
    vision.CORNER_DX, vision.CORNER_DY = p.corner
    vision.OUTLINE_MAX_V = p.outline_max_v
    vision.TRAY_SLOTS, vision.TRAY_PAD = p.tray_slots, p.tray_pad
    vision.GRID = p.grid
    # pixel thresholds tuned on the reference tiles grow and shrink with the tiles
    for name, value in _REFERENCE_PX.items():
        setattr(vision, name, max(1, round(value * s)))
    kinds.ICON = p.icon
    kinds._BGR_FACTOR = vision.DIM_FACTOR[::-1].astype(np.float32)
    kinds.EDGE_MARGIN = max(1, round(6 * s))
    kinds.SHIFT = max(1, round(3 * s))
    kinds.DEFAULT_LIBRARY = p.dir / "kinds_default.npz"
    solver.TRAY_SIZE, solver.MATCH = p.tray_slots, p.match


TUNABLE = {  # detector settings `evaluate` can try out (experiments): module.NAME and the current value
    "vision.DIM_MIN_EDGE": 0.78,
    "vision.DIM_MIN_FACE": 0.12,
    "vision.DIM_MIN_VISIBLE": 0.2,
    "vision.DIM_MIN_SEGMENT": 24,
    "kinds.ACCEPT_RATIO": 0.6,
}


def apply_settings(settings: dict) -> None:
    """Set detector settings ("module.NAME": value) on the modules; unknown names are ignored."""
    import importlib

    for key, value in settings.items():
        module, _, name = key.partition(".")
        if key in TUNABLE:
            setattr(importlib.import_module(module), name, value)


_REFERENCE_PX = {  # vision thresholds in px at the reference tile size
    "BLOB": 9,
    "LINE_RUN": 22,
    "CROSS_MIN_SPAN": 20,
    "DIM_MIN_SEGMENT": 24,
    "STACK_MIN_PX": 15,
    "LIP_MIN_PX": 20,
}
