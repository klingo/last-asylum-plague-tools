"""Text in a frame: a lazy RapidOCR wrapper that returns plain words with their pixel boxes.

The models (about 20 MB) download on the first use. `read` can look at a part of the frame (`region`, fractions of
width / height) and still reports boxes in the whole frame's pixels.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Word:
    text: str
    score: float
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


class Ocr:
    """The default engine (Chinese + English models, good with Latin names and digits), or with `cyrillic` the one
    for Cyrillic names, which reads Latin too but is only used on what the first one could not read."""

    def __init__(self, cyrillic: bool = False) -> None:
        self.cyrillic = cyrillic
        self._engine = None

    def read(self, frame: np.ndarray, region: tuple[float, float, float, float] | None = None) -> list[Word]:
        """Words of the frame (or of `region` = (x0, y0, x1, y1) as fractions), top to bottom, left to right."""
        if self._engine is None:
            from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR

            params = {"Global.log_level": "error"}
            if self.cyrillic:
                params |= {
                    "Rec.lang_type": LangRec.CYRILLIC,
                    "Rec.ocr_version": OCRVersion.PPOCRV5,
                    "Rec.model_type": ModelType.MOBILE,
                }
            self._engine = RapidOCR(params=params)
        height, width = frame.shape[:2]
        left, top = 0, 0
        if region:
            left, top = round(region[0] * width), round(region[1] * height)
            frame = frame[top : round(region[3] * height), left : round(region[2] * width)]
        found = self._engine(frame)
        if found.txts is None:
            return []
        words = [
            Word(
                text,
                float(score),
                int(box[:, 0].min()) + left,
                int(box[:, 1].min()) + top,
                int(box[:, 0].max()) + left,
                int(box[:, 1].max()) + top,
            )
            for box, text, score in zip(found.boxes, found.txts, found.scores)
        ]
        return sorted(words, key=lambda word: (word.cy // 10, word.x0))
