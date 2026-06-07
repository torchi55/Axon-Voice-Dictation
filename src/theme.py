"""Axon Voice design tokens — one source of truth for color, radius, and glow.

Both the main window (QSS f-strings) and the painted widgets (overlay, nav,
icons — which need ``QColor`` objects) import from here, so the palette is
defined once. Translated from the Axon Voice design-system brief:

  - signal orange is the single brand accent (no second/blue accent)
  - warm near-black base (kept dark per Theo, not the brief's navy)
  - restrained liquid glass: faint translucent panes + a hairline specular rim

Tuning knobs live here, not scattered across the UI files.
"""
from PyQt6.QtGui import QColor

# ---- Brand: the orange signal (replaces the old yellow #ffab2e) ---------- #
SIGNAL = "#FF7A1A"          # primary accent — buttons, active states, glow
COPPER = "#FF9A42"          # lighter copper — gradient top, hover lift
SIGNAL_DEEP = "#E0610C"     # pressed / deep end of the liquid fill
SIGNAL_SOFT = "#FFB36B"     # brightest highlight on the fluid

# ---- Surfaces: warm near-black, layered (not noisy) ---------------------- #
BG = "#0c0a0d"             # window base + opaque fallback (pre-Win11)
SURFACE = "rgba(255,255,255,0.045)"
SURFACE_HOVER = "rgba(255,255,255,0.085)"

# ---- Text: cool neutral greys read premium over the warm base ------------ #
TEXT = "#F4F7FB"           # primary
SECONDARY = "#A7B4C8"      # secondary copy
MUTED = "#708099"          # labels / metadata
FAINT = "#55606f"          # placeholders / faint hints

# ---- Borders ------------------------------------------------------------- #
BORDER = "rgba(255,255,255,0.09)"
BORDER_STRONG = "rgba(255,122,26,0.35)"     # active/focus orange edge
RIM = "rgba(255,255,255,0.28)"              # specular top-edge highlight (glass tell)

# ---- States -------------------------------------------------------------- #
SUCCESS = "#2ECC71"
WARNING = "#F5B73D"
ERROR = "#FF5C5C"

# ---- Radii (brief: surfaces 12–20, buttons 10–14, chips 999) ------------- #
R_CARD = 16
R_BTN = 11
R_INPUT = 11
R_PILL = 999

# ---- QColor objects for the painted widgets ------------------------------ #
C_SIGNAL = QColor(SIGNAL)
C_COPPER = QColor(COPPER)
C_DEEP = QColor(SIGNAL_DEEP)
C_SOFT = QColor(SIGNAL_SOFT)
C_TEXT = QColor(TEXT)
C_SECONDARY = QColor(SECONDARY)
C_MUTED = QColor(MUTED)
C_FAINT = QColor(FAINT)
C_ERROR = QColor(ERROR)


def glow(alpha: float) -> str:
    """A signal-orange wash at the given 0..1 alpha (for hover/active fills)."""
    return f"rgba(255,122,26,{alpha})"


def signal_alpha(a: int) -> QColor:
    """Signal orange at an integer 0..255 alpha — for QPainter."""
    c = QColor(SIGNAL)
    c.setAlpha(a)
    return c


# Restrained liquid-glass pane: a faintly luminous translucent surface (light
# catching the top edge) over the painted backdrop, capped by a bright RIM
# hairline. Lower alphas than the old build = less noise, more clarity.
GLASS_CARD = (
    "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
    "stop:0 rgba(255,255,255,0.085), stop:0.06 rgba(255,255,255,0.04), "
    "stop:0.5 rgba(16,14,18,0.18), stop:1 rgba(9,8,11,0.26))"
)


def glass_decl(radius: int = R_CARD, rim: str = RIM) -> str:
    """Inline QSS for a liquid-glass card: translucent pane + bright top rim."""
    return (f"background: {GLASS_CARD}; border: 1px solid {BORDER}; "
            f"border-top: 1px solid {rim}; border-radius: {radius}px;")
