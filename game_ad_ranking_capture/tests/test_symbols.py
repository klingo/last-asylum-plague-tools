from pathlib import Path

import cv2
import numpy as np

import scan
import symbols
from helpers import HEIGHT, WIDTH, NoWords, card

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CY = 984  # where the fixture's card is centred in the frame


def frame_with(card_image: np.ndarray, cy: int = CY) -> np.ndarray:
    frame = np.full((HEIGHT, WIDTH, 3), (235, 222, 214), np.uint8)
    top = cy - card_image.shape[0] // 2
    frame[top : top + card_image.shape[0]] = card_image
    return frame


def squares_frame(pattern: str) -> np.ndarray:
    """A card background with the symbols drawn on the name line: # solid square, o outlined square."""
    image = np.full((182, WIDTH, 3), (235, 222, 214), np.uint8)
    for number, kind in enumerate(pattern):
        x = 382 + number * 37
        if kind == "#":
            cv2.rectangle(image, (x, 48), (x + 26, 74), (60, 40, 30), -1)
        elif kind == "o":
            cv2.rectangle(image, (x, 48), (x + 26, 74), (140, 130, 120), 2)
        elif kind == "c":
            cv2.circle(image, (x + 13, 61), 13, (60, 40, 30), -1)
    return frame_with(image)


def test_the_real_card_with_a_name_of_squares_is_read():
    assert symbols.read_squares(frame_with(cv2.imread(str(FIXTURES / "symbol_card.png"))), CY) == "■□■"


def test_solid_and_outlined_squares_in_any_order():
    assert symbols.read_squares(squares_frame("o##o"), CY) == "□■■□"
    assert symbols.read_squares(squares_frame("#"), CY) == "■"


def test_anything_that_is_not_a_square_makes_it_give_up():
    assert symbols.read_squares(squares_frame("#c#"), CY) == ""  # a circle among them: some other symbol
    assert symbols.read_squares(squares_frame(""), CY) == ""  # nothing on the line


def test_the_scanner_uses_it_only_when_the_ocr_found_no_name():
    symbol_card = frame_with(cv2.imread(str(FIXTURES / "symbol_card.png")))
    nameless = [w for w in card(CY, 18, "x", "Mice", 25_116_849) if w.text != "x"]  # the OCR sees no name

    class Reads:
        def __init__(self, words):
            self.words = words

        def read(self, frame, region=None):
            return self.words

    page = scan.Scanner(None, Reads(nameless), NoWords()).read_page(symbol_card)
    assert [(r.rank, r.name, r.points, r.flags) for r in page.rows] == [(18, "■□■", 25_116_849, [])]
    named = Reads(card(CY, 18, "Dend1s", "Mice", 25_116_849))  # a name the OCR read: the shapes are not looked at
    assert scan.Scanner(None, named, NoWords()).read_page(symbol_card).rows[0].name == "Dend1s"
    blank = frame_with(np.full((182, WIDTH, 3), (235, 222, 214), np.uint8))
    assert scan.Scanner(None, Reads(nameless), NoWords()).read_page(blank).rows[0].flags == ["no name"]
