import time
import os
import sys

import pyperclip
from PyQt6.QtCore import (
    Qt,
    QDateTime,
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QPointF,
    QRectF,
    QSize,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
import math
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .fonts import APP_FONT
from .hotkey_spec import FREE_FALLBACK, parse, uses_win, validate_pair
from .platform_win import enable_dark_titlebar
from .config import load_history, save_history
from .tray import _make_icon as _brand_icon
from .snippets_util import find_collisions
from .transcriber import MODEL_ORDER, resolve_model, resolve_target

# ---------------------------------------------------------------------- #
# Design system — tokens live in theme.py (one source of truth, shared with the
# overlay + painted widgets). Local aliases keep the rest of this file terse.
# ---------------------------------------------------------------------- #
from .theme import (
    BG, SURFACE, SURFACE_HOVER, BORDER, BORDER_STRONG, RIM, TEXT, SECONDARY,
    MUTED, FAINT, SIGNAL, COPPER, SIGNAL_DEEP, SUCCESS, ERROR,
    R_CARD, R_BTN, R_INPUT, GLASS_CARD, glass_decl, glow,
)
from . import icons

ACCENT = SIGNAL          # the brand orange (was the old yellow #ffab2e)
DANGER = ERROR
_glass_decl = glass_decl

_STYLE = f"""
QMainWindow {{ background: transparent; }}
QWidget {{
    background: transparent; color: {TEXT};
    font-family: '{APP_FONT}', 'Segoe UI'; font-size: 13px;
}}
/* Cards float over the painted GlassBackdrop. The page itself is transparent so
   the backdrop reads through; the sidebar carries a faint tint + divider. */
QWidget#page {{
    background: transparent;
    border-top: 1px solid rgba(255,255,255,0.05);
}}
QWidget#sidebar {{
    background: rgba(9,8,11,0.18);
    border-right: 1px solid rgba(255,255,255,0.07);
}}
/* Solid fallback when the backdrop can't paint (pre-Win11 edge cases). */
QWidget#page[glass="false"] {{ background: {BG}; border-top: none; }}
QWidget#sidebar[glass="false"] {{ background: rgba(0,0,0,0.30); border-right: none; }}

/* Buttons — glass secondary by default, filled-orange primary, danger ghost */
QPushButton {{
    background: {GLASS_CARD}; border: 1px solid {BORDER};
    border-top: 1px solid {RIM};
    border-radius: {R_BTN}px; padding: 8px 14px; color: {TEXT};
}}
QPushButton:hover {{ background: {SURFACE_HOVER}; border-color: {BORDER_STRONG}; }}
QPushButton:pressed {{ background: {glow(0.16)}; }}
QPushButton#primary {{
    background: {SIGNAL}; border: none; color: #1a0d02; font-weight: 700;
}}
QPushButton#primary:hover {{ background: {COPPER}; }}
QPushButton#primary:pressed {{ background: {SIGNAL_DEEP}; }}
QPushButton#danger {{ color: {DANGER}; border-color: rgba(255,92,92,0.22); }}
QPushButton#danger:hover {{ background: rgba(255,92,92,0.12); border-color: rgba(255,92,92,0.4); }}

/* Inputs — orange focus ring for clear feedback + accessibility */
QLineEdit {{
    background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: {R_INPUT}px; padding: 8px 11px; color: {TEXT};
    selection-background-color: {glow(0.35)};
}}
QLineEdit:focus {{ border: 1px solid {SIGNAL}; background: {glow(0.05)}; }}
QLineEdit::placeholder {{ color: {FAINT}; }}

QComboBox {{
    background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: {R_INPUT}px; padding: 7px 12px; min-width: 130px; color: {TEXT};
}}
QComboBox:focus, QComboBox:on {{ border-color: {SIGNAL}; }}
/* native arrow removed — IconComboBox paints a thin chevron instead */
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
QComboBox QAbstractItemView {{
    background: #131015; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 10px; padding: 4px;
    selection-background-color: {glow(0.22)}; outline: none;
}}
QComboBox QAbstractItemView::item {{ padding: 6px 8px; border-radius: 7px; min-height: 22px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.14); border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {glow(0.5)}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


class IconComboBox(QComboBox):
    """QComboBox that paints a thin-line chevron (brief: 'dropdown chevrons
    should be thin and minimal'), replacing Qt's native arrow.

    `on_popup` (optional callable) fires the moment the user opens the list —
    used by the model picker to resolve the Auto recommendation lazily (only
    when the user actually looks, so a fresh install never probes the PC)."""

    on_popup = None

    def showPopup(self):
        if callable(self.on_popup):
            try:
                self.on_popup()
            except Exception:
                pass
        super().showPopup()

    def paintEvent(self, event):
        super().paintEvent(event)
        from PyQt6.QtGui import QColor
        p = QPainter(self)
        size = 16
        x = self.width() - 24
        y = (self.height() - size) // 2
        icons.draw_glyph(p, "chevron", QRectF(x, y, size, size),
                         QColor(MUTED), stroke=1.6)
        p.end()


class ToggleSwitch(QCheckBox):
    """iOS-style on/off switch. Subclasses QCheckBox so existing
    checked/toggled wiring (and setChecked) keeps working unchanged.

    The knob eases toward the checked state on every repaint, so it animates
    smoothly and self-corrects even when setChecked() is called with signals
    blocked (e.g. reverting a failed startup toggle)."""

    def __init__(self, checked: bool = False):
        super().__init__()
        self.setText("")
        self.setChecked(checked)
        self.setFixedSize(48, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._knob = 1.0 if checked else 0.0
        # Always kick a repaint on toggle so the ease loop in paintEvent starts.
        self.toggled.connect(self.update)

    def sizeHint(self) -> QSize:
        return QSize(48, 26)

    def hitButton(self, pos) -> bool:
        # QCheckBox normally only treats the tiny ::indicator rect (set by the
        # global QSS) as clickable. Our switch is custom-painted across the whole
        # 48x26 widget, so without this the visible knob isn't clickable and the
        # toggle appears dead. Make the entire widget the hit target.
        return self.rect().contains(pos)

    @staticmethod
    def _lerp(a, b, t):
        return a + (b - a) * t

    def paintEvent(self, _event) -> None:
        target = 1.0 if self.isChecked() else 0.0
        if abs(self._knob - target) > 0.004:
            self._knob += (target - self._knob) * 0.22   # smoother glide
            self.update()
        else:
            self._knob = target
        k = self._knob

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        off = QColor(255, 255, 255, 30)
        on = QColor(ACCENT)
        track = QColor(
            int(self._lerp(off.red(), on.red(), k)),
            int(self._lerp(off.green(), on.green(), k)),
            int(self._lerp(off.blue(), on.blue(), k)),
            int(self._lerp(off.alpha(), 255, k)),
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(track))
        p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)
        # glass rim brightens as it turns on
        p.setPen(QPen(QColor(255, 255, 255, int(38 + 42 * k)), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), (h - 1) / 2, (h - 1) / 2)

        # Knob: swells slightly mid-travel (liquid squash) and casts a soft shadow.
        grow = 2.0 * (1.0 - abs(2 * k - 1))      # 0 at the ends, ~2px at midpoint
        base = h - 8
        d = base + grow
        x = self._lerp(4, w - base - 4, k) - grow / 2
        y = 4 - grow / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 55))
        p.drawEllipse(QRectF(x, y + 1.2, d, d))      # shadow
        knob = QColor(255, 255, 255) if k > 0.5 else QColor(232, 232, 238)
        p.setBrush(QBrush(knob))
        p.drawEllipse(QRectF(x, y, d, d))


def _asset(*parts: str) -> str:
    """Path to an assets/ file — frozen (PyInstaller _MEIPASS) or dev tree."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", *parts)


class LogoMark(QWidget):
    """The Axon brand mark — Theo's can-and-thread drawing (person speaking into
    a can, sound waves, thread to the receiver). Rendered straight from his SVG
    (assets/axon-mark.svg), amber gradient baked into the file. Aspect-preserved
    and centred so it fills the box without distortion. One renderer is shared
    across instances (the SVG is recoloured/static)."""

    _renderer: QSvgRenderer | None = None

    def __init__(self, size: int = 30):
        super().__init__()
        self.setFixedSize(size, size)
        if LogoMark._renderer is None:
            LogoMark._renderer = QSvgRenderer(_asset("axon-mark.svg"))

    def paintEvent(self, _event) -> None:
        r = LogoMark._renderer
        if r is None or not r.isValid():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Fit the SVG viewBox into the widget preserving aspect ratio, centred.
        vb = r.viewBoxF()
        w, h = self.width(), self.height()
        scale = min(w / vb.width(), h / vb.height())
        tw, th = vb.width() * scale, vb.height() * scale
        r.render(p, QRectF((w - tw) / 2, (h - th) / 2, tw, th))


class NavBar(QWidget):
    """Sidebar nav with a single amber 'bubble' that smoothly slides between
    items, and items that grow a touch on hover. Replaces QListWidget so the
    selection is one animated pill, not a static highlight."""

    currentChanged = pyqtSignal(int)

    _ROW_H = 46
    _GAP = 6

    def __init__(self, items, icon_names=None):
        super().__init__()
        self._items = list(items)
        self._icons = list(icon_names) if icon_names else [None] * len(self._items)
        self._current = 0
        self._hover = -1
        self._pill = 0.0                       # animated row position of the bubble
        self._hot = [0.0] * len(self._items)   # per-row hover ease 0..1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        n = len(self._items)
        self.setFixedHeight(n * self._ROW_H + (n - 1) * self._GAP)
        self.setMinimumWidth(150)
        self._anim = QPropertyAnimation(self, b"pillPos")
        self._anim.setDuration(340)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuint)

    def _get_pill(self):
        return self._pill

    def _set_pill(self, v):
        self._pill = v
        self.update()

    pillPos = pyqtProperty(float, fget=_get_pill, fset=_set_pill)

    def currentRow(self) -> int:
        return self._current

    def setCurrentRow(self, i: int, animate: bool = True) -> None:
        i = max(0, min(i, len(self._items) - 1))
        if i == self._current:
            return
        self._current = i
        if animate:
            self._anim.stop()
            self._anim.setStartValue(self._pill)
            self._anim.setEndValue(float(i))
            self._anim.start()
        else:
            self._pill = float(i)
            self.update()
        self.currentChanged.emit(i)

    def _row_top(self, i: int) -> int:
        return i * (self._ROW_H + self._GAP)

    def _row_at(self, y: float) -> int:
        for i in range(len(self._items)):
            top = self._row_top(i)
            if top <= y <= top + self._ROW_H:
                return i
        return -1

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        busy = False
        for i in range(len(self._items)):
            tgt = 1.0 if i == self._hover else 0.0
            if abs(self._hot[i] - tgt) > 0.01:
                self._hot[i] += (tgt - self._hot[i]) * 0.22
                busy = True
            else:
                self._hot[i] = tgt

        w = self.width()
        # The sliding amber bubble — FIXED size, inset so it never spills off the
        # sidebar. Hover no longer grows the box (that pushed it off-screen); only
        # the text scales/brightens on hover.
        pill_y = self._pill * (self._ROW_H + self._GAP)
        pr = QRectF(2, pill_y, w - 4, self._ROW_H)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 122, 26, 34))          # signal orange wash
        p.drawRoundedRect(pr, 11, 11)
        p.setPen(QPen(QColor(255, 122, 26, 78), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pr.adjusted(0.5, 0.5, -0.5, -0.5), 11, 11)

        muted, text, accent = QColor(MUTED), QColor(TEXT), QColor(ACCENT)
        for i, label in enumerate(self._items):
            top = self._row_top(i)
            r = QRectF(0, top, w, self._ROW_H)
            ha = self._hot[i]
            if i != self._current and ha > 0:
                # Faint fixed-size hover wash (no growth).
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, int(14 * ha)))
                p.drawRoundedRect(QRectF(2, top, w - 4, self._ROW_H), 10, 10)
            if i == self._current:
                col = accent
            else:
                col = QColor(
                    int(muted.red() + (text.red() - muted.red()) * ha),
                    int(muted.green() + (text.green() - muted.green()) * ha),
                    int(muted.blue() + (text.blue() - muted.blue()) * ha),
                )
            # Thin-line icon, then the label — gives nav a clear visual language.
            name = self._icons[i]
            if name:
                isz = 19 + ha * 1.0
                iy = top + (self._ROW_H - isz) / 2
                icons.draw_glyph(p, name, QRectF(14, iy, isz, isz), col, stroke=1.7)
            f = QFont(self.font())
            f.setPointSizeF(12.0 + ha * 1.0)
            f.setBold(i == self._current)
            p.setFont(f)
            p.setPen(col)
            p.drawText(r.adjusted(45, 0, -8, 0),
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), label)
        if busy:
            self.update()

    def mouseMoveEvent(self, e) -> None:
        i = self._row_at(e.position().y())
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = -1
        self.update()

    def mousePressEvent(self, e) -> None:
        i = self._row_at(e.position().y())
        if i >= 0:
            self.setCurrentRow(i)


class _Lift(QObject):
    """Hover micro-interaction for a button: an amber glow eases in on hover and
    out on leave, so every button feels alive. Attached via event filter so it
    works on any QPushButton without subclassing."""

    def __init__(self, btn: QPushButton):
        super().__init__(btn)
        self._fx = QGraphicsDropShadowEffect(btn)
        self._fx.setOffset(0, 0)
        self._fx.setBlurRadius(0)
        self._fx.setColor(QColor(255, 122, 26, 0))
        btn.setGraphicsEffect(self._fx)
        self._blur = QPropertyAnimation(self._fx, b"blurRadius", self)
        self._blur.setDuration(170)
        self._blur.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._col = QPropertyAnimation(self._fx, b"color", self)
        self._col.setDuration(170)
        btn.installEventFilter(self)

    def _animate(self, blur: float, alpha: int) -> None:
        self._blur.stop()
        self._blur.setStartValue(self._fx.blurRadius())
        self._blur.setEndValue(blur)
        self._blur.start()
        self._col.stop()
        self._col.setStartValue(self._fx.color())
        self._col.setEndValue(QColor(255, 122, 26, alpha))
        self._col.start()

    def eventFilter(self, _obj, ev) -> bool:
        t = ev.type()
        if t == QEvent.Type.Enter:
            self._animate(24.0, 150)
        elif t == QEvent.Type.Leave:
            self._animate(0.0, 0)
        return False


def _fmt_duration(seconds: float) -> str:
    """Human-friendly recording length, e.g. '6s', '1m 12s'."""
    s = max(0, int(round(seconds)))
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m {s % 60:02d}s"


class _EditableBody(QWidget):
    """History card body. Looks like a label; click it to edit; focus-out saves."""

    def __init__(self, text: str, on_save):
        super().__init__()
        self._on_save = on_save
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._lbl = QLabel(text)
        self._lbl.setWordWrap(True)
        self._lbl.setCursor(Qt.CursorShape.IBeamCursor)
        self._lbl.setStyleSheet(
            f"font-size: 13.5px; color: {TEXT}; background: transparent;"
        )
        lay.addWidget(self._lbl)

        self._ed = QPlainTextEdit(text)
        self._ed.setStyleSheet(
            f"QPlainTextEdit {{ background: rgba(255,255,255,0.07); "
            f"border: 1px solid {SIGNAL}; border-radius: 8px; "
            f"padding: 4px 8px; font-size: 13.5px; color: {TEXT}; }}"
        )
        self._ed.hide()
        lay.addWidget(self._ed)

        # Install AFTER both widgets exist so eventFilter never fires mid-init.
        self._lbl.installEventFilter(self)
        self._ed.installEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:
        if obj is self._lbl and ev.type() == QEvent.Type.MouseButtonPress:
            self._start_edit()
            return True
        if obj is self._ed and ev.type() == QEvent.Type.FocusOut:
            self._commit()
        return False

    def _start_edit(self) -> None:
        self._ed.setPlainText(self._lbl.text())
        self._lbl.hide()
        self._ed.show()
        self._ed.setFocus()
        cur = self._ed.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        self._ed.setTextCursor(cur)

    def _commit(self) -> None:
        text = self._ed.toPlainText()
        self._lbl.setText(text)
        self._ed.hide()
        self._lbl.show()
        self._on_save(text)


# ---------------------------------------------------------------------- #
# History
# ---------------------------------------------------------------------- #
_RETENTION_PHRASE = {
    "session": "cleared every time you open Axon — kept only for this session",
    "24h": "kept for 24 hours, then cleared automatically",
    "1week": "kept for 1 week, then cleared automatically",
    "1month": "kept for 1 month, then cleared automatically",
    "never": "kept indefinitely — cleared only when you choose",
}


def _history_subtitle(retention: str) -> str:
    return f"Your dictations — {_RETENTION_PHRASE.get(retention, _RETENTION_PHRASE['24h'])}."


class HistoryTab(QWidget):
    def __init__(self, load_fn, save_fn, config):
        super().__init__()
        self._save_fn = save_fn
        self._load_fn = load_fn
        self._config = config
        from .config import set_retention
        set_retention(config.history_retention)
        self._entries = load_fn()   # pruned to the retention window, newest first

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 26, 26)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.addWidget(_header("History"))
        head.addStretch()
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedSize(60, 26)
        self._clear_btn.setStyleSheet("font-size: 11px; padding: 0;")
        self._clear_btn.clicked.connect(self._clear)
        head.addWidget(self._clear_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(head)

        self._sub = QLabel(_history_subtitle(config.history_retention))
        self._sub.setWordWrap(True)
        self._sub.setStyleSheet(f"color: {SECONDARY}; font-size: 13.5px; background: transparent;")
        root.addWidget(self._sub)
        root.addSpacing(10)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._container = QWidget()
        self._list = QVBoxLayout(self._container)
        self._list.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._list.setSpacing(10)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll)

        self._empty = QLabel("No recordings yet — hold your hotkey and speak.")
        self._empty.setStyleSheet(f"color: {FAINT}; font-style: italic; background: transparent;")
        self._list.addWidget(self._empty)

        # Rebuild persisted entries (newest first → append top-to-bottom).
        for e in self._entries:
            self._empty.hide()
            self._list.addWidget(self._make_card(e))

    def add_entry(self, text: str, duration: float = 0.0) -> None:
        self._empty.hide()
        entry = {"text": text, "ts": time.time(), "duration": float(duration)}
        self._entries.insert(0, entry)
        self._save_fn(self._entries)
        self._list.insertWidget(0, self._make_card(entry))

    def _make_card(self, entry: dict) -> QFrame:
        text = entry["text"]
        ts = entry["ts"]
        duration = entry.get("duration", 0.0)
        when = QDateTime.fromSecsSinceEpoch(int(ts)).toString("MMM d  h:mm AP")
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: rgba(255,255,255,0.045); border: none; border-radius: 14px; }"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 13)
        cl.setSpacing(8)

        top = QHBoxLayout()
        meta = QLabel(f"{when}  ·  dictated for {_fmt_duration(duration)}")
        meta.setStyleSheet(f"color: {MUTED}; font-size: 11px; background: transparent;")
        top.addWidget(meta)
        top.addStretch()
        copy_btn = QPushButton("Copy")
        copy_btn.setFixedSize(60, 26)
        copy_btn.setStyleSheet("font-size: 11px; padding: 0;")
        copy_btn.clicked.connect(lambda: self._copy(copy_btn, entry["text"]))
        top.addWidget(copy_btn)
        cl.addLayout(top)

        def _on_body_save(new_text: str) -> None:
            entry["text"] = new_text
            copy_btn.clicked.disconnect()
            copy_btn.clicked.connect(lambda: self._copy(copy_btn, entry["text"]))
            self._save_fn(self._entries)

        body = _EditableBody(text, _on_body_save)
        cl.addWidget(body)
        return card

    def _clear(self) -> None:
        self._entries = []
        self._save_fn(self._entries)
        self._drop_cards()
        self._empty.show()

    def _drop_cards(self) -> None:
        """Remove every card widget, keeping the empty-state label."""
        for i in reversed(range(self._list.count())):
            w = self._list.itemAt(i).widget()
            if w is not None and w is not self._empty:
                w.setParent(None)

    def reload(self) -> None:
        """Re-apply the retention window (called when Settings changes it) and
        rebuild the list from the freshly pruned store + refresh the subtitle."""
        from .config import set_retention
        set_retention(self._config.history_retention)
        self._sub.setText(_history_subtitle(self._config.history_retention))
        self._entries = self._load_fn()
        self._drop_cards()
        if self._entries:
            self._empty.hide()
            for e in self._entries:
                self._list.addWidget(self._make_card(e))
        else:
            self._empty.show()

    @staticmethod
    def _copy(btn: QPushButton, text: str) -> None:
        pyperclip.copy(text)
        btn.setText("Copied")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(1100, lambda: btn.setText("Copy"))


# ---------------------------------------------------------------------- #
# Snippets — form-style editable cards (keyword → expansion)
# ---------------------------------------------------------------------- #
class _SnippetRow(QFrame):
    def __init__(self, kw: str, exp: str, on_delete):
        super().__init__()
        self.setStyleSheet(
            f"QFrame {{ {_glass_decl(16)} }}"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(10)

        self.kw = QLineEdit(kw)
        self.kw.setPlaceholderText("keyword")
        self.kw.setFixedWidth(150)
        h.addWidget(self.kw)

        arrow = QLabel()
        arrow.setPixmap(icons.icon_pixmap("arrow", 20, QColor(SIGNAL), stroke=1.8))
        arrow.setStyleSheet("background: transparent; border: none;")
        h.addWidget(arrow)

        self.exp = QLineEdit(exp)
        self.exp.setPlaceholderText("expansion")
        h.addWidget(self.exp, 1)

        dele = QPushButton()
        dele.setObjectName("danger")
        dele.setIcon(icons.make_icon("trash", 16, QColor(ERROR), stroke=1.7))
        dele.setFixedSize(34, 34)
        dele.setCursor(Qt.CursorShape.PointingHandCursor)
        dele.setToolTip("Delete snippet")
        dele.clicked.connect(lambda: on_delete(self))
        h.addWidget(dele)

    def values(self) -> tuple[str, str]:
        return self.kw.text().strip(), self.exp.text()


class SnippetsTab(QWidget):
    def __init__(self, load_fn, save_fn):
        super().__init__()
        self._load_fn = load_fn
        self._save_fn = save_fn
        self._rows: list[_SnippetRow] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 22)
        root.setSpacing(6)

        root.addWidget(_header("Snippets"))
        sub = QLabel("Say the keyword, get the expansion. Applied automatically before pasting.")
        sub.setStyleSheet(f"color: {SECONDARY}; font-size: 13.5px; background: transparent;")
        root.addWidget(sub)
        root.addSpacing(12)

        # Secondary (glass) with an orange icon + label — keeps Save as the one
        # filled-orange primary on this view (clearer hierarchy than two big
        # orange bars).
        add_btn = QPushButton("  Add snippet")
        add_btn.setIcon(icons.make_icon("plus", 16, QColor(SIGNAL), stroke=2.0))
        add_btn.setStyleSheet(f"QPushButton {{ color: {SIGNAL}; font-weight: 600; }}")
        add_btn.setFixedHeight(38)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(self._add_blank)
        root.addWidget(add_btn)
        root.addSpacing(10)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._container = QWidget()
        self._vbox = QVBoxLayout(self._container)
        self._vbox.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._vbox.setSpacing(10)
        self._vbox.setContentsMargins(0, 0, 4, 0)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll, 1)

        self._empty = QLabel("No snippets yet. Click “Add snippet” to create one.")
        self._empty.setStyleSheet(f"color: {FAINT}; font-style: italic; background: transparent;")
        self._vbox.addWidget(self._empty)

        footer = QHBoxLayout()
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {MUTED}; font-size: 11px; background: transparent;")
        footer.addWidget(self._status, 1)
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primary")
        save_btn.setFixedSize(96, 36)
        save_btn.clicked.connect(self._save)
        footer.addWidget(save_btn)
        root.addLayout(footer)

        self._populate()

    # --- row management ------------------------------------------------ #

    def _populate(self) -> None:
        data = self._load_fn()
        for kw, exp in data.items():
            self._add_row(kw, exp)
        self._refresh_empty()

    def _add_row(self, kw: str, exp: str) -> _SnippetRow:
        row = _SnippetRow(kw, exp, self._delete_row)
        self._rows.append(row)
        self._vbox.insertWidget(len(self._rows) - 1, row)
        self._refresh_empty()
        return row

    def _add_blank(self) -> None:
        row = self._add_row("", "")
        row.kw.setFocus()
        self._scroll.ensureWidgetVisible(row)

    def _delete_row(self, row: _SnippetRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
        row.setParent(None)
        row.deleteLater()
        self._refresh_empty()
        self._save()

    def _refresh_empty(self) -> None:
        self._empty.setVisible(not self._rows)

    # --- persistence --------------------------------------------------- #

    def _raw_rows(self) -> list[tuple[str, str]]:
        return [r.values() for r in self._rows]

    def _save(self) -> None:
        errors, warnings = find_collisions(self._raw_rows())
        if errors:
            self._set_status("Not saved — " + "  ".join(errors), DANGER)
            return
        self._save_fn(self.get_snippets())
        if warnings:
            self._set_status("Saved  (note: " + "  ".join(warnings) + ")", ACCENT)
        else:
            self._set_status("Saved.", SUCCESS)

    def _set_status(self, text: str, color: str) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {color}; font-size: 11px; background: transparent;")

    def get_snippets(self) -> dict:
        out = {}
        for row in self._rows:
            kw, exp = row.values()
            if kw:
                out[kw] = exp
        return out


# ---------------------------------------------------------------------- #
# Settings
# ---------------------------------------------------------------------- #
class SettingsTab(QWidget):
    def __init__(self, config, save_fn, hotkeys, on_change=None, on_model_change=None,
                 on_retention_change=None):
        super().__init__()
        self._config = config
        self._save_fn = save_fn
        self._hotkeys = hotkeys
        self._on_change = on_change
        self._on_model_change = on_model_change
        self._on_retention_change = on_retention_change
        self._pending_hold = config.hold_hotkey
        self._pending_free = config.free_hotkey
        self._capture_target: str | None = None
        # What "Auto" resolves to on THIS hardware. Left unresolved (None) at
        # startup ON PURPOSE: a fresh install must not probe the user's PC just
        # to draw the Settings tab — it downloads `base` and gets on with it.
        # We only read the hardware the first time the user opens the model
        # picker (or Learn more) and asks "which one should it be?".
        self._auto_model: str | None = None
        self._auto_target: tuple[str, bool, float | None] | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 26, 28, 18)
        outer.setSpacing(0)
        outer.addWidget(_header("Settings"))
        outer.addSpacing(16)

        # Settings is tall — put it in a scroll area so a short window scrolls
        # instead of cramming the rows together (Theo's "settings bar breaks").
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 6, 4)
        root.setSpacing(14)

        filler_row, self._filler_check = _toggle_row(
            "Filler cleanup",
            "Strips um/uh (like/you-know only as interjections).",
            config.filler_cleanup,
            self._toggle_filler,
        )
        root.addWidget(filler_row)

        from .startup import is_enabled
        startup_row, self._startup_check = _toggle_row(
            "Launch at startup",
            "Start Axon Voice when you sign in to Windows.",
            is_enabled(),
            self._toggle_startup,
        )
        root.addWidget(startup_row)

        # --- Hotkeys ---
        root.addSpacing(6)
        root.addWidget(_section_header("HOTKEYS", "key"))
        self._hold_row, self._hold_val, self._hold_btn = _rebind_row(
            "Hold-to-Talk", _pretty(self._pending_hold), lambda: self._change("hold")
        )
        self._free_row, self._free_val, self._free_btn = _rebind_row(
            "Hands-Free", _pretty(self._pending_free), lambda: self._change("free")
        )
        root.addWidget(self._hold_row)
        root.addWidget(self._free_row)

        self._fallback_btn = QPushButton(f"Use fallback ({_pretty(FREE_FALLBACK)}) for Hands-Free")
        self._fallback_btn.setStyleSheet("font-size: 11px;")
        self._fallback_btn.clicked.connect(self._use_fallback)
        root.addWidget(self._fallback_btn)

        self._status = QLabel(
            "Click “Change”, press any combo — it becomes your hotkey instantly. "
            "It’s captured globally while Axon runs, so it won’t trigger other apps’ shortcuts."
        )
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {MUTED}; font-size: 11px; background: transparent;")
        root.addWidget(self._status)

        # --- Model ---
        root.addSpacing(6)
        model_head = QHBoxLayout()
        model_head.setContentsMargins(0, 0, 0, 0)
        model_head.addWidget(_section_header("MODEL", "wave"))
        model_head.addStretch()
        self._learn_btn = QPushButton("Learn more")
        self._learn_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._learn_btn.setStyleSheet(
            f"QPushButton {{ color: {SIGNAL}; background: transparent; border: none; "
            f"font-size: 12px; font-weight: 700; }} QPushButton:hover {{ color: {COPPER}; }}"
        )
        self._learn_btn.clicked.connect(self._toggle_model_info)
        model_head.addWidget(self._learn_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(model_head)
        self._model_choices = ["auto", "tiny", "small", "large-v3"]
        self._model_combo = IconComboBox()
        # Resolve Auto lazily, the instant the user opens the list.
        self._model_combo.on_popup = self._resolve_auto
        self._build_model_items()
        start = config.model if config.model in self._model_choices else "auto"
        self._prev_model = start
        self._select_model_key(start)
        self._model_combo.currentIndexChanged.connect(self._on_model_changed)

        model_row = QWidget()
        model_row.setStyleSheet(_glass_decl(14))
        mh = QHBoxLayout(model_row)
        mh.setContentsMargins(14, 9, 14, 9)
        mlbl = QLabel("Whisper model")
        mlbl.setStyleSheet(f"color: {MUTED}; font-size: 12px; background: transparent; border: none;")
        mh.addWidget(mlbl)
        mh.addStretch()
        mh.addWidget(self._model_combo)
        root.addWidget(model_row)

        self._model_note = QLabel(
            "Each model is an AI that runs fully on your PC (nothing leaves the "
            "machine). Bigger = more accurate but slower and a larger one-time "
            "download. “Auto” picks the best fit for your hardware."
        )
        self._model_note.setWordWrap(True)
        self._model_note.setStyleSheet(f"color: {MUTED}; font-size: 11px; background: transparent;")
        root.addWidget(self._model_note)

        # Inline "Learn more" panel — expands down in place instead of popping a
        # separate window. Starts collapsed (maximumHeight 0); animated open/shut.
        self._info_panel = self._build_model_info_panel()
        self._info_panel.setMaximumHeight(0)
        self._info_open = False
        self._info_anim = QPropertyAnimation(self._info_panel, b"maximumHeight", self)
        self._info_anim.setDuration(220)
        self._info_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        root.addWidget(self._info_panel)

        # --- History retention ---
        root.addSpacing(6)
        root.addWidget(_section_header("HISTORY", "clock"))
        self._retention_combo = IconComboBox()
        _blank = QIcon()
        for key, label in (("session", "Per session (clear on open)"),
                           ("24h", "24 hours"),
                           ("1week", "1 week"),
                           ("1month", "1 month"),
                           ("never", "Never (keep forever)")):
            self._retention_combo.addItem(_blank, label, key)
        _ridx = self._retention_combo.findData(config.history_retention)
        if _ridx < 0:
            _ridx = self._retention_combo.findData("24h")
        self._retention_combo.blockSignals(True)
        self._retention_combo.setCurrentIndex(max(_ridx, 0))
        self._retention_combo.blockSignals(False)
        self._retention_combo.currentIndexChanged.connect(self._on_retention_changed)

        ret_row = QWidget()
        ret_row.setStyleSheet(_glass_decl(14))
        rh = QHBoxLayout(ret_row)
        rh.setContentsMargins(14, 9, 14, 9)
        rlbl = QLabel("Keep dictation history for")
        rlbl.setStyleSheet(f"color: {MUTED}; font-size: 12px; background: transparent; border: none;")
        rh.addWidget(rlbl)
        rh.addStretch()
        rh.addWidget(self._retention_combo)
        root.addWidget(ret_row)

        rnote = QLabel("How long your dictations stay in the History tab. Everything "
                       "is stored only on this PC — nothing is uploaded.")
        rnote.setWordWrap(True)
        rnote.setStyleSheet(f"color: {MUTED}; font-size: 11px; background: transparent;")
        root.addWidget(rnote)

        # --- Vocabulary ---
        root.addSpacing(6)
        root.addWidget(_section_header("VOCABULARY", "snippet"))
        self._vocab = QPlainTextEdit()
        self._vocab.setPlainText(config.vocabulary)
        self._vocab.setPlaceholderText("Rhino, Grasshopper, parametric, Theo Janeway…")
        self._vocab.setFixedHeight(76)
        self._vocab.setStyleSheet(
            f"QPlainTextEdit {{ {_glass_decl(12)} color: {TEXT}; font-size: 12px; "
            f"padding: 6px 8px; }}"
        )
        root.addWidget(self._vocab)
        vnote = QLabel("Comma- or line-separated terms Axon should get right "
                       "(names, jargon). Applies on your next dictation — no restart.")
        vnote.setWordWrap(True)
        vnote.setStyleSheet(f"color: {MUTED}; font-size: 11px; background: transparent;")
        root.addWidget(vnote)

        # Debounced autosave — persist 0.5 s after the last keystroke, not every one.
        self._vocab_timer = QTimer(self)
        self._vocab_timer.setSingleShot(True)
        self._vocab_timer.setInterval(500)
        self._vocab_timer.timeout.connect(self._save_vocab)
        self._vocab.textChanged.connect(self._vocab_timer.start)

        root.addStretch()

        if hotkeys is not None:
            hotkeys.combo_captured.connect(self._on_captured)

    def _save_vocab(self) -> None:
        self._config.vocabulary = self._vocab.toPlainText()
        self._save_fn(self._config)

    def _on_retention_changed(self, _index: int) -> None:
        key = self._retention_combo.currentData()
        if key is None:
            return
        self._config.history_retention = key
        self._save_fn(self._config)
        from .config import set_retention
        set_retention(key)
        # Re-prune + rebuild the History tab so the change is visible immediately.
        if self._on_retention_change is not None:
            self._on_retention_change()

    def _resolve_auto(self) -> str:
        """Read the hardware ONCE and cache which model "Auto" maps to here.

        Deferred until the user actually opens the picker / Learn more, so a
        fresh install never probes the PC just to render Settings. After the
        first read, refresh the Auto label + any open info panel."""
        if self._auto_model is None:
            try:
                self._auto_target = resolve_target("auto")
                self._auto_model = self._auto_target[0]
            except Exception:
                self._auto_target = ("auto", False, None)
                self._auto_model = "auto"
            self._build_model_items()
            self._select_model_key(self._prev_model)
            self._refresh_info_panel()
        return self._auto_model

    def _build_model_info_panel(self) -> QWidget:
        """The 'Learn more' content, built once and expanded inline (no popup):
        what each model is good for on what hardware + a speed/accuracy table."""
        from PyQt6.QtWidgets import QGridLayout
        panel = QFrame()
        panel.setStyleSheet(_glass_decl(14))
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        intro = QLabel(
            "Every model runs fully on your PC — bigger means more accurate but slower "
            "and a larger one-time download. Switching is instant: your next dictation "
            "uses the new model, no restart."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {SECONDARY}; font-size: 12.5px; background: transparent; border: none;")
        lay.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        for c, h in enumerate(("Model", "Speed", "Accuracy", "Best for")):
            hl = QLabel(h)
            hl.setStyleSheet(f"color: {MUTED}; font-size: 10.5px; font-weight: 700; "
                             f"letter-spacing: 1px; background: transparent; border: none;")
            grid.addWidget(hl, 0, c)
        rows = [
            ("tiny", "Fastest", "Fair", "Old or light laptops, MacBook Air"),
            ("base", "Very fast", "Decent", "Most laptops"),
            ("small", "Fast", "Good", "Typical desktops — solid balance"),
            ("medium", "Slower", "Very good", "Strong CPU or mid-range GPU"),
            ("large-v3", "Slowest", "Best", "Powerful GPU (≥6 GB VRAM)"),
        ]
        self._info_rows = {}   # model name -> its name QLabel, for Auto highlighting
        for r, (m, sp, ac, bf) in enumerate(rows, start=1):
            nm = QLabel(m)
            grid.addWidget(nm, r, 0)
            self._info_rows[m] = nm
            for c, val in enumerate((sp, ac, bf), start=1):
                vl = QLabel(val)
                vl.setWordWrap(True)
                vl.setStyleSheet(f"color: {SECONDARY}; font-size: 12px; background: transparent; border: none;")
                grid.addWidget(vl, r, c)
        grid.setColumnStretch(3, 1)
        lay.addLayout(grid)

        self._info_foot = QLabel()
        self._info_foot.setWordWrap(True)
        self._info_foot.setStyleSheet(f"color: {MUTED}; font-size: 11px; background: transparent; border: none;")
        lay.addWidget(self._info_foot)
        self._refresh_info_panel()
        return panel

    def _refresh_info_panel(self) -> None:
        """Apply the current Auto pick to the info table (highlight the row +
        update the footer). No-op until the panel exists / Auto is resolved."""
        if not hasattr(self, "_info_rows"):
            return
        for m, lbl in self._info_rows.items():
            is_auto = (m == self._auto_model)
            lbl.setText(f"{m}  · Auto" if is_auto else m)
            lbl.setStyleSheet(f"color: {SIGNAL if is_auto else TEXT}; font-size: 12.5px; "
                              f"font-weight: {'800' if is_auto else '600'}; "
                              f"background: transparent; border: none;")
        if self._auto_model is None:
            self._info_foot.setText(
                "Open the model menu and Axon will check this PC and mark the best fit. "
                "Tip: dictate the same sentence on two models to feel the accuracy gap."
            )
        else:
            self._info_foot.setText(
                f"On this PC, Auto picks “{self._auto_model}” (marked above). Tip: dictate the "
                "same sentence on tiny vs a bigger model to feel the accuracy gap before you commit."
            )

    def _toggle_model_info(self) -> None:
        """Expand/collapse the inline Learn-more panel with a height animation."""
        self._info_open = not self._info_open
        if self._info_open:
            self._resolve_auto()           # mark the Auto row when it first opens
            self._info_panel.setMaximumHeight(0)
            target = self._info_panel.sizeHint().height()
            self._info_anim.stop()
            self._info_anim.setStartValue(0)
            self._info_anim.setEndValue(target)
            self._learn_btn.setText("Hide")
            # Let the panel grow freely once open (wrapped text may exceed sizeHint).
            try:
                self._info_anim.finished.disconnect()
            except TypeError:
                pass
            self._info_anim.finished.connect(
                lambda: self._info_panel.setMaximumHeight(16777215))
            self._info_anim.start()
        else:
            self._info_anim.stop()
            try:
                self._info_anim.finished.disconnect()
            except TypeError:
                pass
            self._info_anim.setStartValue(self._info_panel.height())
            self._info_anim.setEndValue(0)
            self._learn_btn.setText("Learn more")
            self._info_anim.start()

    # --- model override ------------------------------------------------ #

    def _build_model_items(self) -> None:
        """(Re)populate the dropdown with each model's download size + a ✓ for the
        ones already on disk. Signals are blocked so the rebuild doesn't fire a
        spurious model change."""
        from .download import expected_bytes, is_cached
        combo = self._model_combo
        check = icons.make_icon("check", 14, QColor(SUCCESS), stroke=1.8)
        blank = QIcon()
        combo.blockSignals(True)
        combo.clear()
        for key in self._model_choices:
            if key == "auto":
                # Until the user opens the list we haven't probed the PC, so keep
                # the label generic; name the resolved model once we know it.
                if self._auto_model is None:
                    label = "Auto · best for your PC"
                else:
                    label = f"Auto · {self._auto_model} (best for this PC)"
                combo.addItem(blank, label, "auto")
                continue
            size = _fmt_size(expected_bytes(key))
            try:
                cached = is_cached(key)
            except Exception:
                cached = False
            # A check icon (not a text glyph) marks models already on disk.
            combo.addItem(check if cached else blank, f"{key} · {size}", key)
        combo.blockSignals(False)

    def _select_model_key(self, key: str) -> None:
        combo = self._model_combo
        idx = combo.findData(key)
        if idx < 0:
            idx = max(combo.findData("auto"), 0)
        combo.blockSignals(True)
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _set_model_note(self, text: str, color: str) -> None:
        self._model_note.setText(text)
        self._model_note.setStyleSheet(f"color: {color}; font-size: 11px; background: transparent;")

    def _on_model_changed(self, _index: int) -> None:
        key = self._model_combo.currentData()
        if key is None or key == self._prev_model:
            return

        # Warn before committing to a model bigger than what this PC recommends.
        if key != "auto":
            # Reuse the cached hardware probe (resolved lazily when the picker
            # first opened) instead of hitting NVML again on every change.
            self._resolve_auto()
            _name, has_cuda, vram = self._auto_target
            recommended = resolve_model("auto", has_cuda, vram)
            if _model_rank(key) > _model_rank(recommended):
                if has_cuda:
                    vram_str = f"{vram:.1f} GB VRAM" if vram is not None else "no CUDA GPU"
                    detail = (f"“{key}” may not fit your GPU ({vram_str}; recommended "
                              f"“{recommended}”). Axon falls back automatically if it can’t load.")
                else:
                    detail = (f"“{key}” runs on the CPU and is noticeably slower than "
                              f"“{recommended}” — expect a few seconds per sentence.")
                ok = QMessageBox.question(self, "Larger model selected",
                                          f"{detail}\n\nUse “{key}” anyway?")
                if ok != QMessageBox.StandardButton.Yes:
                    self._select_model_key(self._prev_model)
                    return

        # Apply live: the callback downloads the model (modal progress) if needed,
        # then hot-swaps it in — no restart. Returns False if the user cancels.
        if self._on_model_change is not None:
            from PyQt6.QtWidgets import QApplication
            self._set_model_note("Preparing model…", MUTED)
            QApplication.processEvents()
            if not self._on_model_change(key):
                self._select_model_key(self._prev_model)
                self._set_model_note("Model change cancelled.", MUTED)
                return

        self._prev_model = key
        self._config.model = key
        self._save_fn(self._config)
        self._build_model_items()      # refresh ✓ badges (the new one is now cached)
        self._select_model_key(key)
        pretty = "auto-selected model" if key == "auto" else f"“{key}”"
        suffix = "" if self._on_model_change is not None else " Restart to apply."
        self._set_model_note(f"Now using {pretty}.{suffix}", SUCCESS)

    # ------------------------------------------------------------------ #

    def _toggle_filler(self, checked: bool) -> None:
        self._config.filler_cleanup = checked
        self._save_fn(self._config)

    def _toggle_startup(self, checked: bool) -> None:
        from .startup import disable, enable
        ok, msg = enable() if checked else disable()
        if ok:
            self._config.start_with_windows = checked
            self._save_fn(self._config)
        else:
            self._startup_check.blockSignals(True)
            self._startup_check.setChecked(not checked)
            self._startup_check.blockSignals(False)
        self._set_status(msg, SUCCESS if ok else DANGER)

    def _change(self, target: str) -> None:
        if self._hotkeys is None:
            return
        if self._capture_target == target:
            self._hotkeys.cancel_capture()
            self._capture_target = None
            self._reset_buttons()
            self._set_status("Cancelled.", MUTED)
            return
        self._capture_target = target
        self._reset_buttons()
        btn = self._hold_btn if target == "hold" else self._free_btn
        btn.setText("Press combo…")
        self._set_status("Listening — press your key combination now.", ACCENT)
        self._hotkeys.begin_capture()

    def _on_captured(self, combo: str) -> None:
        target = self._capture_target
        self._capture_target = None
        self._reset_buttons()
        if target is None:
            return
        if combo == "esc":
            self._set_status("Cancelled.", MUTED)
            return

        new_hold = combo if target == "hold" else self._pending_hold
        new_free = combo if target == "free" else self._pending_free
        err = validate_pair(new_hold, new_free)
        if err:
            self._set_status(err, DANGER)
            return

        # A captured combo IS the new hotkey — apply + persist immediately,
        # no separate Save step (that two-step flow silently left the old one
        # bound, which read as "custom hotkeys don't work").
        self._pending_hold, self._pending_free = new_hold, new_free
        self._hold_val.setText(_pretty(self._pending_hold))
        self._free_val.setText(_pretty(self._pending_free))
        self._apply_pending()
        label = "Hold-to-Talk" if target == "hold" else "Hands-Free"
        extra = ""
        if target == "free" and uses_win(combo):
            extra = "  (Win combos can be swallowed by Windows — if it doesn’t fire, use the fallback below.)"
        self._set_status(f"{_pretty(combo)} is now your {label} hotkey — active.{extra}", SUCCESS)

    def _use_fallback(self) -> None:
        err = validate_pair(self._pending_hold, FREE_FALLBACK)
        if err:
            self._set_status(err, DANGER)
            return
        self._pending_free = FREE_FALLBACK
        self._free_val.setText(_pretty(FREE_FALLBACK))
        self._apply_pending()
        self._set_status(f"Hands-Free is now {_pretty(FREE_FALLBACK)} — active.", SUCCESS)

    def _apply_pending(self) -> None:
        """Rebind the live listener + persist the moment a combo is chosen."""
        if self._hotkeys is not None:
            self._hotkeys.set_hotkeys(self._pending_hold, self._pending_free)
        self._config.hold_hotkey = self._pending_hold
        self._config.free_hotkey = self._pending_free
        self._save_fn(self._config)
        if self._on_change is not None:
            self._on_change()

    def _reset_buttons(self) -> None:
        self._hold_btn.setText("Change")
        self._free_btn.setText("Change")

    def _set_status(self, text: str, color: str) -> None:
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {color}; font-size: 11px; background: transparent;")


# ---------------------------------------------------------------------- #
# Shared widgets / helpers
# ---------------------------------------------------------------------- #
def _model_rank(name: str) -> int:
    try:
        return MODEL_ORDER.index(name)
    except ValueError:
        return MODEL_ORDER.index("base")


_PRETTY = {"ctrl": "Ctrl", "alt": "Alt", "win": "Win", "shift": "Shift"}


def _pretty(spec: str) -> str:
    try:
        hk = parse(spec)
    except Exception:
        return spec
    from .hotkey_spec import MOD_ORDER
    parts = [_PRETTY[m] for m in MOD_ORDER if m in hk.mods]
    parts.append(hk.key.capitalize() if len(hk.key) > 1 else hk.key.upper())
    return "+".join(parts)


def _header(text: str) -> QLabel:
    lbl = QLabel(text)
    f = QFont(APP_FONT, 22, QFont.Weight.Bold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.3)   # slightly tighter heading
    lbl.setFont(f)
    lbl.setStyleSheet(f"color: {TEXT}; background: transparent;")
    return lbl


def _fmt_size(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1e9:.1f} GB"
    return f"{n / 1e6:.0f} MB"


def _section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px; font-weight: 700; "
                      f"letter-spacing: 1.6px; background: transparent;")
    return lbl


def _section_header(text: str, icon_name: str) -> QWidget:
    """Section title with a small thin-line icon — gives Settings clear,
    scannable groupings instead of bare uppercase text."""
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(8)
    glyph = QLabel()
    glyph.setPixmap(icons.icon_pixmap(icon_name, 15, QColor(SIGNAL), stroke=1.6))
    glyph.setStyleSheet("background: transparent; border: none;")
    h.addWidget(glyph)
    h.addWidget(_section_label(text))
    h.addStretch()
    return w


def _rebind_row(name: str, value: str, on_change):
    w = QWidget()
    w.setStyleSheet(_glass_decl(14))
    h = QHBoxLayout(w)
    h.setContentsMargins(14, 9, 12, 9)
    key = QLabel(name)
    key.setStyleSheet(f"color: {MUTED}; font-size: 12px; background: transparent; border: none;")
    val = QLabel(value)
    val.setStyleSheet(f"color: {ACCENT}; font-size: 12px; font-family: 'Consolas'; "
                      f"background: transparent; border: none;")
    btn = QPushButton("Change")
    btn.setFixedWidth(110)
    btn.clicked.connect(on_change)
    h.addWidget(key)
    h.addStretch()
    h.addWidget(val)
    h.addSpacing(10)
    h.addWidget(btn)
    return w, val, btn


class _ClickRow(QWidget):
    """A settings row whose entire surface toggles its switch — bigger, more
    forgiving hit target than the 48px switch alone."""

    def __init__(self, switch: "ToggleSwitch"):
        super().__init__()
        self._sw = switch
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e) -> None:
        if (e.button() == Qt.MouseButton.LeftButton
                and self.rect().contains(e.position().toPoint())):
            self._sw.toggle()


def _toggle_row(title: str, subtitle: str, checked: bool, on_toggled):
    """Settings row: title + subtitle on the left, ToggleSwitch on the right.
    The whole row is clickable."""
    sw = ToggleSwitch(checked)
    sw.toggled.connect(on_toggled)

    w = _ClickRow(sw)
    w.setStyleSheet(_glass_decl(14))
    h = QHBoxLayout(w)
    h.setContentsMargins(14, 11, 14, 11)
    h.setSpacing(12)

    col = QVBoxLayout()
    col.setSpacing(2)
    t = QLabel(title)
    t.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 600; background: transparent; border: none;")
    col.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setWordWrap(True)
        s.setStyleSheet(f"color: {MUTED}; font-size: 11px; background: transparent; border: none;")
        col.addWidget(s)
    h.addLayout(col, 1)

    h.addWidget(sw, 0, Qt.AlignmentFlag.AlignVCenter)
    return w, sw


_TABS = ["History", "Snippets", "Settings"]


class GlassBackdrop(QWidget):
    """The window's own baked ambient backdrop — a single warm signal-orange
    glow over warm near-black, plus a faint top sheen. Glass cards float over
    THIS, which sells the frosted look on any desktop (Win11 won't give us live
    blur-behind, so we supply the ambient light ourselves).

    Restraint over spectacle (per the brief): ONE glow, no blue, and a slow
    near-imperceptible breathing drift instead of the old crossing Lissajous
    orbs — the background should feel calm and premium, not busy."""

    def __init__(self):
        super().__init__()
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(66)      # ~15fps; the drift is slow, this is plenty
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    def _advance(self) -> None:
        self._t += 0.010
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        w, h = r.width(), r.height()
        t = self._t
        m = max(w, h)
        p.fillRect(r, QColor(BG))

        # A single warm orange glow anchored upper-left, breathing gently — the
        # ambient "signal" light. Tuning: the alphas + the small drift amplitudes.
        gx = w * (0.30 + 0.05 * math.sin(t * 0.6))
        gy = h * (0.26 + 0.06 * math.sin(t * 0.45 + 1.1))
        radius = m * (0.72 + 0.03 * math.sin(t * 0.5))
        warm = QRadialGradient(gx, gy, radius)
        warm.setColorAt(0.0, QColor(255, 122, 26, 60))
        warm.setColorAt(0.38, QColor(150, 70, 22, 24))
        warm.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(r, QBrush(warm))

        # A faint deep-copper ember lower-right grounds the composition (warm, not
        # blue) — very low alpha so it reads as depth, not a second orb.
        ex = w * 0.78
        ey = h * 0.82
        ember = QRadialGradient(ex, ey, m * 0.55)
        ember.setColorAt(0.0, QColor(120, 48, 12, 26))
        ember.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(r, QBrush(ember))

        sheen = QLinearGradient(0, 0, 0, h)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 11))
        sheen.setColorAt(0.22, QColor(255, 255, 255, 0))
        p.fillRect(r, QBrush(sheen))


class MainWindow(QMainWindow):
    def __init__(self, config, save_config, load_snippets, save_snippets, hotkeys=None,
                 on_model_change=None):
        super().__init__()
        self._config = config
        self._hotkeys = hotkeys
        self._on_model_change = on_model_change
        self._glass_applied = False
        self.setWindowTitle("Axon Voice")
        self.setWindowIcon(_brand_icon())
        self.setMinimumSize(780, 580)
        self.setStyleSheet(_STYLE)
        self._build_ui(config, save_config, load_snippets, save_snippets)

    def showEvent(self, event):
        super().showEvent(event)
        if self._glass_applied:
            return
        self._glass_applied = True
        # Opaque window; we paint our own ambient backdrop (GlassBackdrop). Just
        # match the title bar to the dark theme. No acrylic — see enable_dark_titlebar.
        enable_dark_titlebar(self)

    def _build_ui(self, config, save_config, load_snippets, save_snippets) -> None:
        central = GlassBackdrop()
        central.setObjectName("page")
        self._page = central
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Sidebar ---
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        self._sidebar = sidebar
        sidebar.setFixedWidth(184)
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(16, 22, 16, 18)
        sv.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(0, 0, 0, 0)
        brand_row.addWidget(LogoMark(88))
        brand_row.addStretch()
        sv.addLayout(brand_row)
        sv.addSpacing(8)
        wordmark = QLabel("AXON VOICE")
        wordmark.setStyleSheet(f"color: {ACCENT}; font-size: 16px; font-weight: 800; "
                               f"letter-spacing: 2px; background: transparent;")
        sv.addWidget(wordmark)
        sv.addSpacing(20)

        nav = NavBar(_TABS, ["clock", "snippet", "gear"])
        nav.setFont(QFont(APP_FONT, 12))
        nav.currentChanged.connect(self._switch_tab)
        self._nav = nav
        sv.addWidget(nav)
        sv.addStretch()

        hint = QLabel(f"Hold  {_pretty(config.hold_hotkey)}\nFree  {_pretty(config.free_hotkey)}")
        hint.setStyleSheet(f"color: {FAINT}; font-size: 10px; font-family: 'Consolas'; "
                           f"background: transparent;")
        self._hotkey_hint = hint
        sv.addWidget(hint)
        root.addWidget(sidebar)

        # --- Content stack ---
        self._stack = QStackedWidget()
        self._history = HistoryTab(load_history, save_history, config)
        self._snippets = SnippetsTab(load_snippets, save_snippets)
        self._settings = SettingsTab(config, save_config, self._hotkeys,
                                     self._refresh_hotkey_hint, self._on_model_change,
                                     on_retention_change=self._history.reload)
        self._stack.addWidget(self._history)
        self._stack.addWidget(self._snippets)
        self._stack.addWidget(self._settings)
        root.addWidget(self._stack, 1)

        # Cross-fade between tabs. The QGraphicsOpacityEffect is installed ONLY
        # for the ~300ms of the fade and removed (setGraphicsEffect(None)) the
        # instant it ends. Why: a graphics effect renders its whole subtree to an
        # offscreen pixmap, but the pages here hold QScrollAreas, which repaint by
        # blitting (scroll()) — an optimization the cached effect pixmap never
        # sees. Leaving the effect on permanently meant every window resize blitted
        # a stale frame that overlapped the live re-layout → rows crammed/ghosted.
        # Idle = no effect = direct rendering = clean native resize.

        # Every button gets the amber hover-glow micro-interaction.
        self._lifts = [_Lift(b) for b in self.findChildren(QPushButton)]

        # Pre-measure every page so the first time a tab is shown its content is
        # already laid out — kills the 'content loads in the middle then plops to
        # the top' settle (Snippets was the worst offender).
        for i in range(self._stack.count()):
            pg = self._stack.widget(i)
            pg.ensurePolished()
            lay = pg.layout()
            if lay is not None:
                lay.activate()

    def _switch_tab(self, i: int) -> None:
        # Instant switch. A cross-fade via QGraphicsOpacityEffect was dropped: on a
        # stack of QScrollAreas it rendered the page offscreen, which flashed the
        # content mid-page then snapped it to the top on first show (the "Snippets
        # add-bar jumps" bug) and caused stale-blit cram on resize. Reliability wins.
        if 0 <= i < self._stack.count() and i != self._stack.currentIndex():
            self._stack.setCurrentIndex(i)

    def add_history_entry(self, text: str, duration: float = 0.0) -> None:
        self._history.add_entry(text, duration)

    def get_snippets(self) -> dict:
        return self._snippets.get_snippets()

    def _refresh_hotkey_hint(self) -> None:
        """Keep the sidebar reminder in sync after a live rebind."""
        self._hotkey_hint.setText(
            f"Hold  {_pretty(self._config.hold_hotkey)}\nFree  {_pretty(self._config.free_hotkey)}"
        )

    def filler_cleanup_enabled(self) -> bool:
        return self._config.filler_cleanup
