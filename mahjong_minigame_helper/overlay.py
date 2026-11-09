"""Transparent, always-on-top, click-through window drawn over the game area (Windows).

The window is excluded from screen capture (`WDA_EXCLUDEFROMCAPTURE`, Windows 10 2004+), so its boxes never confuse
`capture.locate_game`, which finds the emulator window on screen. Marks are the dicts from `board.build_marks`, in canonical px.
"""

from __future__ import annotations

import ctypes
import tkinter as tk

KEY = "#010203"  # transparent colour
READY, BUSY, WAIT, ERROR = "#3ddc84", "#ffb020", "#6cb4ff", "#ff5a5a"  # badge colours
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80000, 0x20, 0x80, 0x08000000
WDA_EXCLUDEFROMCAPTURE = 0x11


def _hex(bgr: tuple[int, int, int]) -> str:
    b, g, r = bgr
    return f"#{r:02x}{g:02x}{b:02x}"


class Overlay:
    def __init__(self, x: int, y: int, w: int, h: int):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True, "-transparentcolor", KEY)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.canvas = tk.Canvas(self.root, width=w, height=h, bg=KEY, highlightthickness=0)
        self.canvas.pack()
        self.root.update_idletasks()
        self.excluded_from_capture = self._make_click_through()

    def move(self, x: int, y: int, w: int, h: int) -> None:
        """Follow the emulator window when it is moved or resized."""
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.canvas.configure(width=w, height=h)

    def _make_click_through(self) -> bool:
        """Clicks pass through, no focus stealing, hidden from screen capture. Returns whether the capture exclusion worked."""
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetAncestor(self.root.winfo_id(), 2)
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            )
            return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
        except (AttributeError, OSError):
            return False

    def show(self, marks: list[dict], status: str = "", scale: float = 1.0, state: tuple[str, str] | None = None) -> None:
        """Redraw. `scale` = canonical px per screen px of the game area. `state` = (label, background colour):
        the badge at the top that says what the script is doing."""
        c = self.canvas
        c.delete("all")
        k = 1.0 / scale
        for m in marks:
            color = _hex(m["color"])
            if m["type"] == "rect":
                c.create_rectangle(m["x0"] * k, m["y0"] * k, m["x1"] * k, m["y1"] * k, outline=color, width=m["width"])
            else:
                size = 22 if m.get("big") else 11
                c.create_text(m["x"] * k, m["y"] * k, text=m["text"], fill=color, anchor="w", font=("Segoe UI", size, "bold"))
        x = 0
        if state:
            label, bg = state
            width = 14 + 9 * len(label)
            c.create_rectangle(0, 0, width, 24, fill=bg, outline="")
            c.create_text(7, 12, text=label, fill="black", anchor="w", font=("Segoe UI", 10, "bold"))
            x = width
        if status:
            c.create_rectangle(x, 0, x + 10 + 7.2 * len(status), 24, fill="#101010", outline="")
            c.create_text(x + 5, 12, text=status, fill="white", anchor="w", font=("Consolas", 10))
        self.root.update_idletasks()
