"""Draws the Game Asset Extractor's icon: a picture (sky, sun, mountains) with gold crop marks around it, on a dark
rounded square. Writes `icon.ico` (the shortcut's and the windows' icon, 16 to 256 px) and `favicon.png` (the icon of
the gallery's and the texts' pages, which embed it). Run again after changing the drawing:
`.venv/Scripts/python make_icon.py`."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent
SIZE = 1024  # drawn large and scaled down, for smooth edges
BACKGROUND = ((38, 42, 50), (20, 22, 26))
GOLD, GOLD_DARK = (232, 190, 62), (176, 134, 24)
PICTURE = (200, 250, 824, 774)  # left, top, right, bottom
SKY = ((70, 140, 215), (150, 205, 240))  # top, bottom
MOUNTAINS = ((47, 125, 107), (36, 96, 84))  # far, near


def frame(image: Image.Image) -> None:
    gradient = Image.new("RGBA", (1, SIZE))
    for y in range(SIZE):
        mix = y / (SIZE - 1)
        gradient.putpixel((0, y), (*(round(a + (b - a) * mix) for a, b in zip(*BACKGROUND)), 255))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=210, fill=255)
    image.paste(gradient.resize((SIZE, SIZE)), mask=mask)
    ImageDraw.Draw(image).rounded_rectangle((14, 14, SIZE - 15, SIZE - 15), radius=198, outline=(*GOLD_DARK, 255), width=14)


def picture() -> Image.Image:
    left, top, right, bottom = PICTURE
    width, height = right - left, bottom - top
    layer = Image.new("RGBA", (width, height))
    for y in range(height):
        mix = y / (height - 1)
        ImageDraw.Draw(layer).line([(0, y), (width, y)], fill=(*(round(a + (b - a) * mix) for a, b in zip(*SKY)), 255))
    pen = ImageDraw.Draw(layer)
    pen.ellipse((width - 270, 70, width - 130, 210), fill=(*GOLD, 255))
    pen.polygon([(0, height), (0, 330), (170, 190), (330, 340), (470, 250), (width, 400), (width, height)], fill=(*MOUNTAINS[0], 255))
    pen.polygon([(0, height), (0, 470), (150, 360), (300, 520), (440, 430), (width, 560), (width, height)], fill=(*MOUNTAINS[1], 255))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=44, fill=255)
    layer.putalpha(mask)
    return layer


def crop_marks(pen: ImageDraw.ImageDraw) -> None:
    """Gold corner brackets around the picture: what is cut out of it."""
    left, top, right, bottom = PICTURE
    gap, arm, thick = 46, 150, 38
    for x, sx in ((left - gap, 1), (right + gap, -1)):
        for y, sy in ((top - gap, 1), (bottom + gap, -1)):
            pen.rectangle(sorted_box(x, y, x + sx * arm, y + sy * thick), fill=(*GOLD, 255))
            pen.rectangle(sorted_box(x, y, x + sx * thick, y + sy * arm), fill=(*GOLD, 255))


def sorted_box(x0: int, y0: int, x1: int, y1: int) -> tuple[int, int, int, int]:
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def draw() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    frame(image)
    image.alpha_composite(picture(), PICTURE[:2])
    crop_marks(ImageDraw.Draw(image))
    return image


def main() -> None:
    image = draw()
    image.resize((64, 64), Image.LANCZOS).save(HERE / "favicon.png", optimize=True)
    image.resize((256, 256), Image.LANCZOS).save(
        HERE / "icon.ico", format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    )
    image.resize((512, 512), Image.LANCZOS).save(HERE / "icon_preview.png")


if __name__ == "__main__":
    main()
