"""Draws the Mahjong Minigame Helper's icon: a mahjong tile (four circles) with its green back, on a dark rounded
square. Writes `icon.ico` (the shortcut's and the window's icon, 16 to 256 px). Run again after changing the drawing:
`.venv/Scripts/python make_icon.py`."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
SIZE = 1024  # drawn large and scaled down, for smooth edges
BACKGROUND = ((38, 42, 50), (20, 22, 26))
GOLD_DARK = (176, 134, 24)
IVORY, IVORY_SHADE = (248, 241, 222), (214, 202, 170)
JADE, JADE_DARK = (46, 160, 106), (24, 104, 68)
RED, GREEN = (200, 52, 52), (30, 130, 80)
FACE = (276, 150, 748, 738)  # the tile's front; its back shows 70 px lower
DEPTH = 70


def frame(image: Image.Image) -> None:
    gradient = Image.new("RGBA", (1, SIZE))
    for y in range(SIZE):
        mix = y / (SIZE - 1)
        gradient.putpixel((0, y), (*(round(a + (b - a) * mix) for a, b in zip(*BACKGROUND)), 255))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=210, fill=255)
    image.paste(gradient.resize((SIZE, SIZE)), mask=mask)
    ImageDraw.Draw(image).rounded_rectangle((14, 14, SIZE - 15, SIZE - 15), radius=198, outline=(*GOLD_DARK, 255), width=14)


def circle(pen: ImageDraw.ImageDraw, cx: int, cy: int, radius: int, colour: tuple[int, int, int]) -> None:
    """A mahjong circle: coloured ring, ivory ring, coloured disc, ivory dot."""
    for size, fill in ((1.0, colour), (0.76, IVORY), (0.56, colour), (0.18, IVORY)):
        r = round(radius * size)
        pen.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*fill, 255))


def draw() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    frame(image)
    pen = ImageDraw.Draw(image)
    left, top, right, bottom = FACE
    pen.rounded_rectangle((left, top + DEPTH, right, bottom + DEPTH), radius=84, fill=(*JADE_DARK, 255))
    pen.rounded_rectangle((left, top + DEPTH // 2, right, bottom + DEPTH // 2), radius=84, fill=(*JADE, 255))
    pen.rounded_rectangle(FACE, radius=84, fill=(*IVORY_SHADE, 255))
    pen.rounded_rectangle((left + 10, top + 8, right - 10, bottom - 6), radius=76, fill=(*IVORY, 255))
    cx, cy = (left + right) // 2, (top + bottom) // 2
    for dx, dy, colour in ((-100, -125, GREEN), (100, -125, RED), (-100, 125, RED), (100, 125, GREEN)):
        circle(pen, cx + dx, cy + dy, 84, colour)
    return image


def main() -> None:
    image = draw()
    image.resize((256, 256), Image.LANCZOS).save(
        HERE / "icon.ico", format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    image.resize((512, 512), Image.LANCZOS).save(HERE / "icon_preview.png")


if __name__ == "__main__":
    main()
