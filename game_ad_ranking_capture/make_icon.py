"""Draws the viewer's icon: a podium of three bars in the heat colours (amber, green, red) under a gold star, on the
viewer's dark background. Writes `viewer/assets/favicon.png` (the tab icon, served and exported like the other
icons) and `icon.ico` (the shortcut's icon, 16 to 256 px). Run again after changing the drawing:
`.venv/Scripts/python make_icon.py`."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
SIZE = 1024  # drawn large and scaled down, for smooth edges
BACKGROUND = ((38, 42, 50), (20, 22, 26))  # the viewer's #262a32 -> #14161a, top to bottom
GOLD, GOLD_DARK = (232, 190, 62), (176, 134, 24)
BARS = (  # (left, height, colour): second place, first, third
    (120, 400, (230, 169, 58)),
    (392, 540, (92, 184, 92)),
    (664, 290, (217, 83, 79)),
)
BAR_WIDTH, BASELINE, RADIUS = 240, 900, 36


def star(cx: float, cy: float, outer: float, inner: float) -> list[tuple[float, float]]:
    return [
        (cx + (outer if i % 2 == 0 else inner) * math.sin(i * math.pi / 5), cy - (outer if i % 2 == 0 else inner) * math.cos(i * math.pi / 5))
        for i in range(10)
    ]


def shade(colour: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(min(255, round(part * factor)) for part in colour)


def draw() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (1, SIZE))
    for y in range(SIZE):
        mix = y / (SIZE - 1)
        gradient.putpixel((0, y), (*(round(a + (b - a) * mix) for a, b in zip(*BACKGROUND)), 255))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=210, fill=255)
    image.paste(gradient.resize((SIZE, SIZE)), mask=mask)
    pen = ImageDraw.Draw(image)
    pen.rounded_rectangle((14, 14, SIZE - 15, SIZE - 15), radius=198, outline=(*GOLD_DARK, 255), width=14)
    for left, height, colour in BARS:
        top = BASELINE - height
        pen.rounded_rectangle((left, top, left + BAR_WIDTH, BASELINE), radius=RADIUS, fill=(*colour, 255))
        pen.rounded_rectangle((left, top, left + BAR_WIDTH, top + 70), radius=RADIUS, fill=(*shade(colour, 1.22), 255))
        pen.rectangle((left, top + 40, left + BAR_WIDTH, top + 70), fill=(*colour, 255))  # the highlight is a rim only
    centre = BARS[1][0] + BAR_WIDTH / 2
    points = star(centre, BASELINE - BARS[1][1] - 135, 125, 55)
    pen.polygon([(x + 0, y + 10) for x, y in points], fill=(*GOLD_DARK, 255))
    pen.polygon(points, fill=(*GOLD, 255))
    return image


def main() -> None:
    image = draw()
    image.resize((128, 128), Image.LANCZOS).save(HERE / "viewer" / "assets" / "favicon.png", optimize=True)
    image.resize((256, 256), Image.LANCZOS).save(
        HERE / "icon.ico", format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    image.resize((512, 512), Image.LANCZOS).save(HERE / "review" / "icon_preview.png")


if __name__ == "__main__":
    main()
