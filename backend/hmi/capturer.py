"""
backend/hmi/capturer.py
Cross-platform HMI screenshot capture using mss.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    import mss
    import mss.tools
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

BASELINES_DIR = Path("baselines")


def capture_screen(region: Optional[dict] = None):
    """
    Capture a screenshot of the screen (or a region).
    region: dict with keys top, left, width, height (in pixels)
    Returns: PIL.Image.Image or None
    """
    if not MSS_AVAILABLE or not PIL_AVAILABLE:
        raise RuntimeError("mss and Pillow required: pip install mss pillow")

    with mss.mss() as sct:
        monitor = region or sct.monitors[1]  # monitors[0] = all screens, [1] = primary
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        return img


def capture_window_by_title(title: str):
    """
    Capture a specific window by its title (Windows only for now).
    Falls back to full screen if window not found.
    """
    import platform
    if platform.system() == "Windows":
        try:
            import win32gui
            import win32ui
            import win32con

            hwnd = win32gui.FindWindow(None, title)
            if not hwnd:
                # Try partial match
                def enum_cb(hwnd_, results):
                    if title.lower() in win32gui.GetWindowText(hwnd_).lower():
                        results.append(hwnd_)
                windows: list = []
                win32gui.EnumWindows(enum_cb, windows)
                hwnd = windows[0] if windows else None

            if hwnd:
                rect = win32gui.GetWindowRect(hwnd)
                region = {
                    "left": rect[0], "top": rect[1],
                    "width": rect[2] - rect[0], "height": rect[3] - rect[1],
                }
                return capture_screen(region)
        except ImportError:
            pass  # pywin32 not installed

    return capture_screen()


def save_baseline(image, name: str) -> Path:
    """Save a screenshot as a baseline image."""
    BASELINES_DIR.mkdir(exist_ok=True)
    path = BASELINES_DIR / f"{name}.png"
    image.save(str(path))
    return path


def load_baseline(name: str):
    """Load a baseline image by name."""
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow required: pip install pillow")
    path = BASELINES_DIR / f"{name}.png"
    if not path.exists():
        raise FileNotFoundError(f"Baseline '{name}' not found at {path}")
    return Image.open(str(path))


def list_baselines() -> list[str]:
    """List all available baseline image names."""
    if not BASELINES_DIR.exists():
        return []
    return [p.stem for p in BASELINES_DIR.glob("*.png")]
