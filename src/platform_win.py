"""Windows 11 visual integration — dark title bar + real acrylic blur-behind.

We use ``SetWindowCompositionAttribute`` with ACCENT_ENABLE_ACRYLICBLURBEHIND so
the actual desktop behind the window is *blurred* and shows through (true liquid
glass), tinted by a low-alpha colour for legibility. This works with Qt's
``WA_TranslucentBackground`` layered window — unlike DWMWA_SYSTEMBACKDROP_TYPE
(Mica/Acrylic), which DWM refuses to draw behind a layered window and so renders
as a flat black box. Pure ctypes, no third-party deps. Pre-Win11 → returns False.
"""
import ctypes
import sys
from ctypes import wintypes

# --- DwmSetWindowAttribute (dark title bar) ---
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20

# --- SetWindowCompositionAttribute (blur-behind) ---
_WCA_ACCENT_POLICY = 19
_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4   # blurs the desktop behind the window
_ACCENT_ENABLE_BLURBEHIND = 3          # older Aero blur (fallback)

# Tint painted over the blur: low-alpha cool-dark so the desktop reads through
# but text stays legible. Format is 0xAABBGGRR. Lower the alpha byte (0x4D) for
# a clearer / more see-through glass; raise it for a darker, more frosted pane.
_TINT_R, _TINT_G, _TINT_B, _TINT_A = 0x16, 0x17, 0x21, 0x20
_GRADIENT = (_TINT_A << 24) | (_TINT_B << 16) | (_TINT_G << 8) | _TINT_R


class _ACCENTPOLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_uint),
        ("AccentFlags", ctypes.c_uint),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_uint),
    ]


class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.POINTER(_ACCENTPOLICY)),
        ("SizeOfData", ctypes.c_size_t),
    ]


def _build() -> int:
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0


def _set_dark_titlebar(hwnd: int) -> None:
    try:
        flag = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(flag), ctypes.sizeof(flag),
        )
    except Exception:
        pass


def enable_dark_titlebar(window) -> bool:
    """Just the dark title bar (no acrylic). For the painted-backdrop glass mode,
    where the window is opaque and we render our own ambient backdrop + glass cards.
    On current Win11 builds the old ACCENT_ENABLE_ACRYLICBLURBEHIND no longer
    composites live content behind a layered window (renders a flat tint), so we
    don't use it. Returns True on Win11, False otherwise."""
    if sys.platform != "win32" or _build() < 22000:
        return False
    try:
        _set_dark_titlebar(int(window.winId()))
        return True
    except Exception:
        return False


def enable_acrylic(window, dark: bool = True, accent_state: int | None = None) -> bool:
    """Apply a dark title bar + acrylic desktop blur to a Qt window. Returns True on success."""
    if sys.platform != "win32" or _build() < 22000:
        return False
    try:
        hwnd = int(window.winId())
        if dark:
            _set_dark_titlebar(hwnd)

        accent = _ACCENTPOLICY()
        accent.AccentState = accent_state or _ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags = 0
        accent.GradientColor = _GRADIENT
        data = _WINCOMPATTRDATA()
        data.Attribute = _WCA_ACCENT_POLICY
        data.SizeOfData = ctypes.sizeof(accent)
        data.Data = ctypes.pointer(accent)

        set_wca = ctypes.windll.user32.SetWindowCompositionAttribute
        set_wca.argtypes = [wintypes.HWND, ctypes.POINTER(_WINCOMPATTRDATA)]
        set_wca.restype = ctypes.c_int
        ok = bool(set_wca(hwnd, ctypes.byref(data)))
        print(f"[Axon] acrylic blur-behind: {'ON' if ok else 'FAILED'} "
              f"(build {_build()}, hwnd {hwnd})")
        return ok
    except Exception as e:
        print(f"[Axon] acrylic blur unavailable: {e}")
        return False
