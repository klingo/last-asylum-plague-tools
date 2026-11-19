"""Where things are: the game, BlueStacks' ADB, the data folder, and the Rank screen's layout and timings.

Layout numbers are fractions of the frame (width or height), measured on the reference 1080 x 1920 portrait frame, so
another BlueStacks resolution still works as long as the game keeps its proportions.
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"  # one file per calendar week, committed
REVIEW_DIR = HERE / "review"  # crops of uncertain rows, git-ignored
TEMPLATES_DIR = HERE / "templates"
VIEWER_DIR = HERE / "viewer"
VIEWER_FILES = ("index.html", "overview.html", "i18n.js", "compare.js", "week-panel.js", "week-panel.css", "base.css")  # the pages and scripts the viewer serves and the export copies
ROSTER_DIR = DATA_DIR / "members"  # the alliance's member lists, one file per calendar week
CORRECTIONS = HERE / "corrections.json"  # {"misread name": "right name"}, applied when a day is stored

PACKAGE = "com.phs.global"  # Last Asylum: Plague
DEFAULT_SERIAL = "127.0.0.1:5555"  # BlueStacks' usual ADB address (Settings > Advanced > Android Debug Bridge)
ADB_CANDIDATES = (
    r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
    r"C:\Program Files\BlueStacks\HD-Adb.exe",
    r"C:\Program Files (x86)\BlueStacks\HD-Adb.exe",
)

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat")  # the Rank screen's day tabs (Sunday has no Duel)
DAY_LABELS = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat"}
MAX_ROWS = 200  # the game's own maximum of the list
# the points a player has to reach in a day for each of the Duel's 9 daily reward phases (game data)
PHASES = (38_000, 145_000, 550_000, 650_000, 1_020_000, 2_280_000, 2_630_000, 3_620_000, 7_190_000)
# the viewer's colour scale: red around phase 5, amber around phase 7, green from phase 9 on, blended in between
COLOR_SCALE = (("red", 5), ("amber", 7), ("green", 9))

# -- timings (seconds)
SETTLE_TRIES = 12  # frames compared while waiting for the screen to stop moving
SETTLE_PAUSE = 0.35
TAP_PAUSE = 1.2  # after a tap: the game lags
SWIPE_MS = 900  # a slow swipe: little fling, so the list moves about the same every time
FLING_MS = 100  # a fast swipe, to get back to the top: the list flies on after the finger, nothing is read on the way
FLING_BATCH = 4  # flings in a row before the screen is looked at to see whether the top is reached

# -- Rank screen layout (fractions of the frame)
BACK_ARROW = (0.083, 0.029)  # (x of width, y of height)
ALLIANCE_BUTTON = (0.917, 0.719)  # the map's Alliance button (no OCR needed: it is a fixed part of the screen)
MEMBERS_BUTTON = (0.804, 0.583)  # the Alliance page's Alliance Members button
LIST_TOP = 0.238  # the list's visible area, between the column heads and the pinned own row
LIST_BOTTOM = 0.800
SWIPE_ROWS = 3.5  # cards the list is moved per swipe (five are fully visible at once, so a card is read twice)
ROW_PITCH = 0.0951  # distance between two row cards, of height (182.6 px)
CARD_HALF = 0.043  # half the height of a card itself (about 165 px: the cards have gaps between them)
NAME_COLUMN = (0.33, 0.74)  # x range of name and alliance
POINTS_COLUMN = (0.72, 1.0)
RANK_COLUMN = (0.0, 0.19)

# -- OCR
MIN_CONFIDENCE = 0.90  # below this a name / alliance / points reading goes to the review list
