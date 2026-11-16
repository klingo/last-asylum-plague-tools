"""Test helper: a fake Alliance Members screen (leader pinned, groups with fold arrows, cards in two columns)."""

import cv2
import numpy as np

import members as M
from helpers import HEIGHT, WIDTH, word

CARD_ROW = 187  # px between two rows of cards
HEADER = 100  # px a group header takes
TOP = round(M.CONTENT_TOP * HEIGHT) + 20  # where the scrolling content starts on the screen


class VirtualMembers:
    """`groups` = [(rank, [names])]; the ones in `folded` show no cards until their arrow is tapped.

    It plays device and OCR at once: `settled` / `swipe` / `tap` and `read`."""

    def __init__(self, groups, folded=(), shown_total=None, overshoot=1.0):
        self.groups, self.folded, self.overshoot, self.offset = groups, set(folded), overshoot, 0.0
        self.shown_total = shown_total if shown_total is not None else 1 + sum(len(names) for _, names in groups)
        self.taps = []
        names = [name for _, group in groups for name in group]
        self.power = {name: 50_000_000 + 1_234_567 * index for index, name in enumerate(names)}  # every member differs

    def layout(self):
        """([(kind, y in the content, data)], height) for the current fold state."""
        items, y = [], 0
        for rank, names in self.groups:
            items.append(("header", y, rank))
            y += HEADER
            if rank not in self.folded:
                for index, name in enumerate(names):
                    items.append(("card", y + (index // 2) * CARD_ROW, (name, index % 2)))
                y += ((len(names) + 1) // 2) * CARD_ROW
        return items, y

    def screen_y(self, y):
        return TOP + y - self.offset

    # -- the device
    def frame(self):
        image = np.full((HEIGHT, WIDTH, 3), min(255, round(self.offset / 8)), np.uint8)
        for kind, y, data in self.layout()[0]:
            if kind == "header" and M.CONTENT_TOP * HEIGHT < self.screen_y(y) + 40 < 0.95 * HEIGHT:
                cy, x = round(self.screen_y(y) + 40), round(M.ARROW_X * WIDTH)
                cv2.rectangle(image, (x - 40, cy - 30), (x + 40, cy + 30), (200, 120, 60), -1)
                if data in self.folded:  # folded: the triangle points up
                    points = [(x - 18, cy + 10), (x + 18, cy + 10), (x, cy - 12)]
                else:
                    points = [(x - 18, cy - 10), (x + 18, cy - 10), (x, cy + 12)]
                cv2.fillPoly(image, [np.array(points)], (255, 255, 255))
        return image

    def settled(self):
        return self.frame()

    def swipe(self, x0, y0, x1, y1, ms=0):
        content_y = y0 - TOP + self.offset
        on_header = any(kind == "header" and y <= content_y < y + HEADER for kind, y, _ in self.layout()[0])
        if on_header or content_y % CARD_ROW > CARD_ROW - 30:
            return  # a drag that starts on a rank header or in the gap between two rows is not taken
        _, height = self.layout()
        self.offset = min(max(self.offset + (y0 - y1) * self.overshoot, 0.0), max(height - (0.96 * HEIGHT - TOP), 0))

    def tap(self, x, y):
        self.taps.append((round(x), round(y)))
        for kind, item_y, rank in self.layout()[0]:
            if kind == "header" and abs(self.screen_y(item_y) + 40 - y) < 40 and x > 0.85 * WIDTH:
                self.folded ^= {rank}  # the arrow toggles the group

    # -- the OCR
    def read(self, frame, region=None):
        words = [word(str(self.shown_total), 972, 207), word("Leader1", 560, 425)]
        for kind, y, data in self.layout()[0]:
            cy = self.screen_y(y)
            if kind == "header":
                group = next(g for g in self.groups if g[0] == data)
                if cy + 40 < 0.95 * HEIGHT and cy > M.CONTENT_TOP * HEIGHT:
                    words += [word(f"R{data}", 80, cy + 40), word(f"0/{len(group[1])}", 170, cy + 40)]
            else:
                name, column = data
                if M.CONTENT_TOP * HEIGHT < cy and cy + 175 < M.CONTENT_BOTTOM * HEIGHT:
                    x = 275 if column == 0 else 770
                    lv = cy + 100
                    words += [
                        word(name, x, lv - 58, x1=x + 150),
                        word("Lv.30", x, lv),
                        word(f"{self.power[name]:,}", x, lv + 51, x1=x + 200),
                    ]
        return sorted(words, key=lambda w: (w.cy // 10, w.x0))
