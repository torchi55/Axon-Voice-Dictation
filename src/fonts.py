"""App-wide font — Satoshi (bundled).

We bundle the full Satoshi OTFs (assets/fonts/) and load them at startup.
Satoshi is clean, modern, and distinctive — the design-brief typeface — and the
*full* family (not the limited Typo Square demo that broke earlier) covers all
Latin text + digits we render. UI symbols that Satoshi doesn't carry (arrows,
checks, the close glyph) are no longer text — they're painted via ``icons.py`` —
so there are no missing-glyph gaps this time.

``APP_FONT`` is the family every widget/QSS references; if the bundled files
fail to load for any reason we fall back to Segoe UI.
"""
import os
import sys

from PyQt6.QtGui import QFont, QFontDatabase

APP_FONT = "Satoshi"
_FALLBACK = "Segoe UI"
_WEIGHTS = ("Regular", "Medium", "Bold", "Black")


def _assets_dir() -> str:
    """assets/fonts next to the bundle (frozen) or the project root (dev)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "fonts")


def load_fonts(app) -> str:
    """Register the bundled Satoshi weights and set the app-wide default font.
    Returns the family actually in use."""
    global APP_FONT
    loaded = False
    fonts_dir = _assets_dir()
    for w in _WEIGHTS:
        path = os.path.join(fonts_dir, f"Satoshi-{w}.otf")
        if os.path.exists(path) and QFontDatabase.addApplicationFont(path) != -1:
            loaded = True

    if not loaded:
        APP_FONT = _FALLBACK
        print(f"[Axon] Satoshi not found — falling back to {APP_FONT}")

    base = QFont(APP_FONT, 10)
    base.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(base)
    print(f"[Axon] app font: {APP_FONT}")
    return APP_FONT
