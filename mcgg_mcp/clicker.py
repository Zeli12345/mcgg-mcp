"""Click a point inside the game window (local operator machine only).

Used by welfare_pick so the card is clicked the moment the turn opens, with no
round trip through the agent. Coordinates are in the 1280-wide screenshot space of
window 'MagicChessGoGo'; they are scaled to the real client area.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)
SHOT_W, SHOT_H = 1280, 749
TITLE = 'MagicChessGoGo'

# Card centres in screenshot space (measured on the 8-card welfare ring).
WELFARE_CARDS = {
    'top_left': (376, 310), 'top': (527, 228), 'top_right': (903, 310), 'top_mid_right': (748, 225),
    'left': (303, 440), 'mid_left': (456, 440), 'mid_right': (825, 440), 'right': (975, 440),
}


class _RECT(ctypes.Structure):
    _fields_ = [('left', wintypes.LONG), ('top', wintypes.LONG),
                ('right', wintypes.LONG), ('bottom', wintypes.LONG)]


class _POINT(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]


def _client_origin_and_size():
    hwnd = user32.FindWindowW(None, TITLE)
    if not hwnd:
        raise RuntimeError(f"window '{TITLE}' not found")
    rc = _RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    pt = _POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return hwnd, pt.x, pt.y, rc.right - rc.left, rc.bottom - rc.top


def click_shot_point(x: int, y: int) -> None:
    """Map a screenshot point to the screen the same way the winput window clicks do
    (physical = screenshot point * 1.517, origin 0,0; verified against a live click).

    The pointer glides to the target and dwells before the press. A bare jump plus an
    instant press was ignored by the welfare ring (NO_EFFECT on all eight cards); a
    winput click, which glides and hovers first, selected the card."""
    import time
    SCALE = 1.517
    tx, ty = round(x * SCALE), round(y * SCALE)
    pt = _POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    sx, sy = pt.x, pt.y
    steps = 12
    for i in range(1, steps + 1):
        t = i / steps
        user32.SetCursorPos(round(sx + (tx - sx) * t), round(sy + (ty - sy) * t))
        time.sleep(0.012)
    time.sleep(0.06)                       # hover dwell before the press
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
