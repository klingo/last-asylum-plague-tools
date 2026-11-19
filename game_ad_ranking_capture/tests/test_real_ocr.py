"""The OCR pipeline on real frames of the Rank screen (list area, tests/fixtures); skipped without the models."""

from pathlib import Path

import cv2
import numpy as np
import pytest

import scan
import screens
from helpers import HEIGHT, WIDTH, NoWords
from ocr import Ocr

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TOP = round(0.2 * HEIGHT)  # the fixtures hold the frame from here down; the rest of the frame is blank


@pytest.fixture(scope="module")
def scanner():
    primary, secondary = Ocr(), Ocr(cyrillic=True)
    try:
        primary.read(np.zeros((200, 200, 3), np.uint8))
        secondary.read(np.zeros((200, 200, 3), np.uint8))
    except Exception as error:  # no models and no internet
        pytest.skip(f"the OCR models are not available: {error}")
    return scan.Scanner(NoWords(), primary, secondary, progress=lambda text: None)


def frame_of(name: str) -> np.ndarray:
    crop = cv2.imread(str(FIXTURES / f"{name}.png"))
    frame = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    frame[TOP : TOP + crop.shape[0]] = crop
    return frame


def test_the_top_of_the_list_is_read_with_ranks_points_names_and_alliances(scanner):
    page = scanner.read_page(frame_of("rank_top"))
    assert [(r.rank, r.name, r.points) for r in page.rows] == [
        (1, "Badabooom", 57_015_464),
        (2, "Sauron", 51_369_397),
        (3, "Divaaxm", 36_677_876),
        (4, "Bella1401", 35_414_333),
        (5, "MattEagle", 34_915_575),
    ]
    assert (page.rows[0].alliance, page.rows[0].tag) == ("FishAndFriends", "FfS")
    assert page.rows[1].alliance == "SwarmOfInfectedMice"
    assert all(not row.flags for row in page.rows)
    assert (page.me.rank, page.me.name, page.me.points) == (28, "Klingo", 15_422_182)


def test_a_cyrillic_name_is_read_by_the_second_engine(scanner):
    page = scanner.read_page(frame_of("rank_cyrillic"))
    assert [(r.rank, r.points) for r in page.rows] == [
        (6, 32_509_542),
        (7, 30_975_973),
        (8, 30_705_686),
        (9, 28_191_986),
        (10, 27_579_267),
        (11, 27_395_817),
    ]
    assert page.rows[1].name == "ФрауМарта" and page.rows[1].confidence >= 0.9
    assert [r.name for r in page.rows] == ["-Gaia-", "ФрауМарта", "KikiL", "-Helly-", "lostkid1312", "ADDEVIL"]


def test_the_server_numbers_of_the_details_tab_are_read_from_a_real_frame():
    ocr = Ocr()
    try:
        ocr.read(np.zeros((200, 200, 3), np.uint8))
    except Exception as error:  # no models and no internet
        pytest.skip(f"the OCR models are not available: {error}")
    crop = cv2.imread(str(FIXTURES / "duel_details_servers.png"))
    frame = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    frame[600 : 600 + crop.shape[0]] = crop  # the fixture holds the flags, the share bar and the alliance names
    assert screens.server_numbers(ocr.read(frame), WIDTH, HEIGHT) == (127, 122)
