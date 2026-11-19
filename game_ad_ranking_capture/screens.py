"""Where the game is and how to get to the Rank screen of the Alliance Duel.

A screen is recognised by its text (the OCR of the whole frame); the Duel's icon on the map has none, so it is found by
matching a picture of it (`templates/duel_icon.png`). Every step is checked against the next screen before going on, a
screen that is none of the known ones is left with the on-screen back arrow (never the Android back key: the game
answers that with an exit dialog), and after a few of those the navigation gives up instead of tapping around blindly.
A day tab the game does not switch to has no data yet (a day that has not started): the tap leaves the old tab selected.
The Duel's Details tab shows both alliances' server numbers (`#127`): `server_numbers` reads them.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import Enum

import cv2
import numpy as np

import config as C
from ocr import Word

TEMPLATE_WIDTH = 1080  # the frame width the template was cut from
ICON_MATCH = 0.70  # TM_CCOEFF_NORMED score above which the Duel icon counts as found
ICON_AREA = (0.70, 0.0, 1.0, 0.45)  # where on the map the icon column is (fractions x0, y0, x1, y1)
SELECTED_BLUE = 50  # blue minus red of the selected day tab (unselected ones are about 28, selected about 76)
MAX_STEPS = 10
MAX_BACKS = 6


class Screen(Enum):
    MAP = "the map"
    DUEL = "the Alliance Duel"
    RANK = "the Duel's Rank screen"
    ALLIANCE = "the Alliance page"
    MEMBERS = "the Alliance Members screen"
    OTHER = "another screen"


class NavigationError(RuntimeError):
    """The game is somewhere the navigation does not know and could not leave, or something it needs is missing."""


def identify(words: list[Word], height: int) -> Screen:
    texts = {word.text.strip().lower() for word in words}
    top = {word.text.strip().lower() for word in words if word.cy < 0.12 * height}
    if {"daily", "weekly", "player", "point"} <= texts:
        return Screen.RANK
    if "alliance duel" in top:
        return Screen.DUEL
    if "alliance members" in top:
        return Screen.MEMBERS
    if "alliance" in top and "alliance shop" in texts:
        return Screen.ALLIANCE
    if len(texts & {"squad", "hero", "territory", "mail", "bag"}) >= 2:  # the map's own buttons: it is a busy picture
        return Screen.MAP
    return Screen.OTHER


def on_details(words: list[Word]) -> bool:
    """Whether the Duel shows its Details tab (the heading of that tab is on the screen)."""
    return any(word.text.strip().lower() == "daily score overview" for word in words)


def server_numbers(words: list[Word], width: int, height: int) -> tuple[int, int] | None:
    """The own alliance's server (the left side) and the opponent's (the right) from the Details tab, None unless
    exactly one number is read on each side."""
    sides: dict[bool, list[int]] = {False: [], True: []}
    for word in words:
        number = re.fullmatch(r"#?\s*(\d{1,4})", word.text.strip())
        if number and C.SERVER_BAND[0] * height <= word.cy <= C.SERVER_BAND[1] * height and word.score >= 0.8:
            sides[word.cx > width / 2].append(int(number.group(1)))
    return (sides[False][0], sides[True][0]) if len(sides[False]) == len(sides[True]) == 1 else None


def find_duel_icon(frame: np.ndarray, template: np.ndarray) -> tuple[float, float] | None:
    """The centre of the Duel's icon on the map, None if it is not there (the match is weaker than `ICON_MATCH`)."""
    height, width = frame.shape[:2]
    scale = width / TEMPLATE_WIDTH
    if scale != 1:
        template = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    left, top = round(ICON_AREA[0] * width), round(ICON_AREA[1] * height)
    area = frame[top : round(ICON_AREA[3] * height), left : round(ICON_AREA[2] * width)]
    if area.shape[0] < template.shape[0] or area.shape[1] < template.shape[1]:
        return None
    _, score, _, at = cv2.minMaxLoc(cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED))
    if score < ICON_MATCH:
        return None
    return left + at[0] + template.shape[1] / 2, top + at[1] + template.shape[0] / 2


def day_tabs(words: list[Word], height: int) -> dict[str, Word]:
    """The day tabs' labels (Mon ... Sat) found in the band under the Daily / Weekly tabs."""
    labels = {label: day for day, label in C.DAY_LABELS.items()}
    band = (0.13 * height, 0.19 * height)
    return {labels[w.text]: w for w in words if w.text in labels and band[0] <= w.cy <= band[1]}


def selected_day(frame: np.ndarray, tabs: dict[str, Word]) -> str | None:
    """The day tab that is highlighted (blue), None if none clearly is."""
    scores = {}
    for day, tab in tabs.items():
        patch = frame[max(round(tab.cy) - 35, 0) : round(tab.cy) + 40, max(round(tab.cx) - 45, 0) : round(tab.cx) + 45]
        blue, _, red = patch.reshape(-1, 3).mean(axis=0)
        scores[day] = blue - red
    if not scores:
        return None
    best = max(scores, key=scores.get)
    return best if scores[best] >= SELECTED_BLUE else None


class Navigator:
    def __init__(self, device, ocr, progress: Callable[[str], None] = print):
        self.device, self.ocr, self.progress = device, ocr, progress
        self.template = cv2.imread(str(C.TEMPLATES_DIR / "duel_icon.png"))

    def look(self) -> tuple[np.ndarray, list[Word], Screen]:
        frame = self.device.settled()
        words = self.ocr.read(frame)
        return frame, words, identify(words, frame.shape[0])

    def tap_back(self, frame: np.ndarray) -> None:
        height, width = frame.shape[:2]
        self.device.tap(C.BACK_ARROW[0] * width, C.BACK_ARROW[1] * height)

    def _reach(self, target: Screen, steps: dict, failure: str) -> tuple[np.ndarray, list[Word]]:
        """Gets from wherever the game is to `target`: `steps` says what to do on a screen on the way (a function of
        the frame and its words), any other screen is left with the back arrow, a few times at most."""
        backs = 0
        for _ in range(MAX_STEPS):
            frame, words, screen = self.look()
            if screen is target:
                return frame, words
            self.progress(f"The game shows {screen.value}.")
            if screen in steps:
                steps[screen](frame, words)
            else:
                backs += 1
                if backs > MAX_BACKS:
                    raise NavigationError("Could not get back to the map from the screen the game is showing.")
                self.tap_back(frame)
        raise NavigationError(failure)

    def _tap_duel_icon(self, frame: np.ndarray, words: list[Word]) -> None:
        icon = find_duel_icon(frame, self.template)
        if icon is None:
            raise NavigationError("The Alliance Duel's icon was not found on the map (is the event running?).")
        self.device.tap(*icon)

    def _tap_rank_button(self, frame: np.ndarray, words: list[Word]) -> None:
        button = [w for w in words if w.text.strip().lower() == "rank" and w.cy > 0.85 * frame.shape[0]]
        if not button:
            raise NavigationError("The Alliance Duel is open, but its Rank button was not found.")
        self.device.tap(button[0].cx, button[0].cy - 0.025 * frame.shape[0])  # the trophy above the label

    def _tap_alliance(self, frame: np.ndarray, words: list[Word]) -> None:
        height, width = frame.shape[:2]
        self.device.tap(C.ALLIANCE_BUTTON[0] * width, C.ALLIANCE_BUTTON[1] * height)

    def _tap_members(self, frame: np.ndarray, words: list[Word]) -> None:
        height, width = frame.shape[:2]
        label = [w for w in words if w.text.strip().lower() == "members" and 0.5 * height < w.cy < 0.7 * height]
        x, y = (
            (label[0].cx, label[0].cy - 0.01 * height)
            if label
            else (C.MEMBERS_BUTTON[0] * width, C.MEMBERS_BUTTON[1] * height)
        )
        self.device.tap(x, y)

    def open_rank(self) -> tuple[np.ndarray, list[Word]]:
        """Gets from wherever the game is to the Rank screen; returns its frame and words."""
        steps = {Screen.DUEL: self._tap_rank_button, Screen.MAP: self._tap_duel_icon}
        return self._reach(Screen.RANK, steps, "The Rank screen was not reached.")

    def open_details(self) -> tuple[np.ndarray, list[Word]]:
        """Gets from wherever the game is to the Alliance Duel's Details tab; returns its frame and words."""
        frame, words = self._reach(Screen.DUEL, {Screen.MAP: self._tap_duel_icon}, "The Alliance Duel was not reached.")
        if on_details(words):
            return frame, words
        tab = [w for w in words if w.text.strip().lower() == "details" and w.cy < 0.2 * frame.shape[0]]
        if not tab:
            raise NavigationError("The Alliance Duel is open, but its Details tab was not found.")
        self.device.tap(tab[0].cx, tab[0].cy)
        frame, words, _ = self.look()
        if not on_details(words):
            raise NavigationError("The Details tab of the Alliance Duel did not open.")
        return frame, words

    def open_members(self) -> tuple[np.ndarray, list[Word]]:
        """Gets from wherever the game is to the Alliance Members screen."""
        steps = {Screen.MAP: self._tap_alliance, Screen.ALLIANCE: self._tap_members}
        return self._reach(Screen.MEMBERS, steps, "The Alliance Members screen was not reached.")

    def select_day(self, day: str, tabs: dict[str, Word]) -> np.ndarray | None:
        """Taps the day's tab; its frame once the tab is selected, None if the game did not switch (no data yet)."""
        tab = tabs[day]
        self.device.tap(tab.cx, tab.cy)
        frame = self.device.settled()
        return frame if selected_day(frame, tabs) == day else None

    def go_home(self) -> None:
        """Back out of the Duel to the map (best effort: it is only tidying up)."""
        for _ in range(MAX_BACKS):
            frame, _, screen = self.look()
            if screen is Screen.MAP:
                return
            self.tap_back(frame)
