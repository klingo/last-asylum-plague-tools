"""Global hotkeys while the advisor runs: F8 pauses / resumes auto-click, F9 allows one click in step mode."""

from __future__ import annotations

import ctypes

VK_F8, VK_F9 = 0x77, 0x78


def key_down(vk: int) -> bool:
    """Is the key held down right now (works while another window has the focus)?"""
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
