import math

import numpy as np
from PyQt6.QtCore import (
    Qt, QRect, QPoint, QTimer, QPropertyAnimation, QParallelAnimationGroup,
    QEasingCurve, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QFont,
    QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QWidget

from .theme import SIGNAL, COPPER, SIGNAL_DEEP, SIGNAL_SOFT

_SIGNAL = QColor(SIGNAL)
_TRACK = QColor(255, 122, 26, 45)
_DIM = QColor(110, 110, 110)
# Glass bubble: translucent, warm near-black to match the window's cards.
_BG = QColor(13, 11, 14, 200)
_BG_HOVER = QColor(20, 17, 22, 222)
_SHEEN = QColor(255, 255, 255, 28)
_RIM = QColor(255, 255, 255, 72)
# Mic spectrum gradient endpoints (left → right): signal orange → copper — one
# warm brand ramp, no blue (per the brief).
_SPEC_A = QColor(SIGNAL)
_SPEC_B = QColor(COPPER)

W, H = 200, 42
RADIUS = 11
BAR_COUNT = 20

# States
REC_HOLD = "hold"
REC_FREE = "free"
PROCESSING = "processing"     # brief "warming" pill before the determinate bar
TRANSCRIBING = "transcribing"
PASTING = "pasting"


def _draw_mic_icon(p: QPainter, x: int, y: int, w: int, h: int, color: QColor) -> None:
    """Microphone body + arc stand + stem + base."""
    p.setBrush(QBrush(color))
    p.setPen(Qt.PenStyle.NoPen)
    bw = int(w * 0.48)
    bh = int(h * 0.52)
    bx = x + (w - bw) // 2
    p.drawRoundedRect(bx, y + 1, bw, bh, bw // 2, bw // 2)

    pen = QPen(color, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(x + int(w * 0.14), y + int(h * 0.33),
              int(w * 0.72), int(h * 0.37), 0, -180 * 16)
    cx = x + w // 2
    p.drawLine(cx, y + int(h * 0.70), cx, y + int(h * 0.86))
    p.drawLine(x + int(w * 0.28), y + int(h * 0.86),
               x + int(w * 0.72), y + int(h * 0.86))


class Overlay(QWidget):
    pause_clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._state = REC_HOLD
        self._hovering = False
        self._phase = 0.0
        self._dot_pulse = 0.0
        self._levels = np.zeros(BAR_COUNT, dtype="float32")
        self._spec_norm = 1e-4
        self._tx_progress = 0.0         # eased value actually drawn
        self._tx_target = 0.0           # latest real fraction from the worker
        self.free_keybind = ""          # set by app; shown in the free-mode hint

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(W, H)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._anim: QParallelAnimationGroup | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self.hide()

    @property
    def bar_count(self) -> int:
        return BAR_COUNT

    @property
    def _recording(self) -> bool:
        return self._state in (REC_HOLD, REC_FREE)

    # --- state transitions -------------------------------------------- #

    def show_recording(self, mode: str) -> None:
        first_show = not self.isVisible()
        self._state = REC_HOLD if mode == "hold" else REC_FREE
        self._levels[:] = 0.0
        self._spec_norm = 1e-4
        self._reposition()
        if first_show:
            self.setWindowOpacity(0.0)
            self.show()
            self._animate_in()
        else:
            self.show()

    def show_processing(self) -> None:
        """Calm 'warming' pill shown immediately after recording stops. No
        percentage — short clips finish here and never flash a 0% bar; only if
        transcription is still running after a short delay does the app promote
        this to the determinate show_transcribing() bar."""
        self._state = PROCESSING
        self._tx_progress = 0.0
        self._tx_target = 0.0
        if not self.isVisible():
            self._reposition()
            self.show()
        self.update()

    def show_transcribing(self) -> None:
        self._state = TRANSCRIBING
        if not self.isVisible():
            self._reposition()
            self.show()
        self.update()

    def set_transcribe_progress(self, frac: float) -> None:
        """Worker reports decode progress (end/duration). Monotonic — never
        snaps backward between queued segments."""
        self._tx_target = max(self._tx_target, min(max(frac, 0.0), 1.0))

    def show_pasting(self) -> None:
        self._state = PASTING
        if not self.isVisible():
            self._reposition()
            self.show()
        self.update()

    def hide_overlay(self) -> None:
        self.hide()

    def set_levels(self, raw: np.ndarray) -> None:
        """Feed raw per-band magnitudes; apply adaptive gain + attack/decay."""
        if raw is None or raw.size != BAR_COUNT:
            return
        peak = float(raw.max())
        # Auto-gain: track a decaying peak so the meter normalizes to *this*
        # voice/mic level rather than a fixed scale.
        self._spec_norm = max(peak, self._spec_norm * 0.95, 1e-4)
        norm = np.clip(raw / self._spec_norm, 0.0, 1.0) ** 0.7
        for i in range(BAR_COUNT):
            cur = self._levels[i]
            tgt = float(norm[i])
            a = 0.62 if tgt > cur else 0.30   # snappier attack, quicker settle
            self._levels[i] = cur + (tgt - cur) * a

    # --- entrance animation ------------------------------------------- #

    def _animate_in(self) -> None:
        final = self.pos()
        self.move(final.x(), final.y() + 20)
        pos_a = QPropertyAnimation(self, b"pos")
        pos_a.setDuration(300)
        pos_a.setStartValue(QPoint(final.x(), final.y() + 20))
        pos_a.setEndValue(final)
        pos_a.setEasingCurve(QEasingCurve.Type.OutBack)   # the "pop"
        op_a = QPropertyAnimation(self, b"windowOpacity")
        op_a.setDuration(200)
        op_a.setStartValue(0.0)
        op_a.setEndValue(1.0)
        op_a.setEasingCurve(QEasingCurve.Type.OutCubic)
        group = QParallelAnimationGroup(self)
        group.addAnimation(pos_a)
        group.addAnimation(op_a)
        self._anim = group           # keep a ref so it isn't GC'd mid-flight
        group.start()

    # ------------------------------------------------------------------ #

    def _tick(self) -> None:
        self._phase += 0.12 if self._recording else 0.07
        self._dot_pulse = (math.sin(self._phase * 2.2) * 0.5 + 0.5)
        # Ease the transcription fill toward the latest reported fraction so the
        # bar glides between segment updates instead of stepping.
        if self._state == TRANSCRIBING:
            self._tx_progress += (self._tx_target - self._tx_progress) * 0.30
        self.update()

    def _reposition(self) -> None:
        screen = QApplication.primaryScreen().geometry()
        self.move((screen.width() - W) // 2, screen.height() - H - 80)

    # ------------------------------------------------------------------ #

    def enterEvent(self, _event) -> None:
        self._hovering = True
        self.update()

    def leaveEvent(self, _event) -> None:
        self._hovering = False
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.pause_clicked.emit()

    # ------------------------------------------------------------------ #

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(0, 0, W, H, RADIUS, RADIUS)
        base = _BG_HOVER if (self._hovering and self._recording) else _BG
        p.fillPath(path, base)
        # Top sheen — light catching the glass surface.
        sheen = QLinearGradient(0, 0, 0, H)
        sheen.setColorAt(0.0, _SHEEN)
        sheen.setColorAt(0.42, QColor(255, 255, 255, 0))
        p.fillPath(path, QBrush(sheen))
        # Bright rim hairline (the glass tell).
        p.setPen(QPen(_RIM, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(0, 0, W - 1, H - 1, RADIUS, RADIUS)
        p.setClipPath(path)

        if self._recording:
            self._paint_recording(p)
        else:
            self._paint_working(p)

    # --- recording: icon + live spectrum + hint ----------------------- #

    def _paint_recording(self, p: QPainter) -> None:
        # Pulsing red record dot for BOTH hold and free — Theo wants the free
        # (Ctrl+Alt+Space) view to match the hold (Ctrl+Space) view. No amber dot.
        cx, cy, r = 13, 15, 4
        alpha = int(150 + 105 * self._dot_pulse)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(255, 90, 70, alpha)))
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # Wide live spectrum spanning most of the pill (20 thin reactive bars).
        # No "REC" word — the red dot already says it, freeing room for bars.
        self._paint_spectrum(p, 24, W - 12, top=6, bottom=25, active=True)

        # Bottom hint line. Free mode also shows the stop keybind.
        if self._state == REC_HOLD:
            hint = "release to paste"
        else:
            kb = getattr(self, "free_keybind", "")
            hint = f"click to stop   ·   {kb}" if kb else "click to stop"
        p.setPen(QPen(QColor(165, 165, 172, 210)))
        p.setFont(QFont("Consolas", 7))
        p.drawText(QRect(0, H - 13, W, 11),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, hint)

        # On hover: draw the pause icon OVER the live view (a light scrim), instead
        # of replacing it — Theo wants to still see the spectrum/dot behind it.
        if self._hovering:
            self._paint_pause(p)

    def _paint_spectrum(self, p, x0, x1, top, bottom, active) -> None:
        region_w = x1 - x0
        bar_w = 4
        gap = max(1, (region_w - BAR_COUNT * bar_w) // (BAR_COUNT - 1))
        total = BAR_COUNT * bar_w + (BAR_COUNT - 1) * gap
        start = x0 + (region_w - total) // 2
        mid = (top + bottom) / 2
        max_h = bottom - top
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(BAR_COUNT):
            if active:
                lvl = float(self._levels[i])
                # subtle idle shimmer so silence isn't a dead flat line
                lvl = max(lvl, 0.05 + 0.035 * (math.sin(self._phase + i * 0.5) * 0.5 + 0.5))
            else:
                lvl = 0.10
            bar_h = max(2, int(lvl * max_h))
            bx = start + i * (bar_w + gap)
            by = int(mid - bar_h / 2)
            if active:
                t = i / (BAR_COUNT - 1)          # left amber → right indigo
                col = QColor(
                    int(_SPEC_A.red() + (_SPEC_B.red() - _SPEC_A.red()) * t),
                    int(_SPEC_A.green() + (_SPEC_B.green() - _SPEC_A.green()) * t),
                    int(_SPEC_A.blue() + (_SPEC_B.blue() - _SPEC_A.blue()) * t),
                )
            else:
                col = _DIM
            p.setBrush(QBrush(col))
            p.drawRoundedRect(bx, by, bar_w, bar_h, 2, 2)

    # --- transcribing / pasting: indeterminate working bar ------------ #

    def _paint_working(self, p: QPainter) -> None:
        proc = self._state == PROCESSING
        txn = self._state == TRANSCRIBING

        # First ~3 s after release = blank bubble (no label, no bar). Short clips
        # — almost every Ctrl+Space hold — finish transcribing in this window and
        # go straight to paste, so they never show a bar at all. Only a dictation
        # still decoding past 3 s promotes to the real bar below.
        if proc:
            return

        label = "TRANSCRIBING" if txn else "PASTING"
        p.setPen(QPen(QColor(255, 122, 26, 230)))
        p.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        p.drawText(QRect(0, 5, W, 16),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, label)

        # Frosted recessed track.
        tx, tw, ty, th = 16, W - 32, H - 16, 6
        track = QPainterPath()
        track.addRoundedRect(tx, ty, tw, th, th / 2, th / 2)
        p.fillPath(track, _TRACK)
        # Hairline highlight along the top of the groove — reads as glass depth.
        p.setPen(QPen(QColor(255, 255, 255, 24), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(int(tx + th / 2), ty + 1, int(tx + tw - th / 2), ty + 1)

        if txn:
            # Determinate fill from real decode progress (end/duration) — the bar
            # climbs as Whisper works (not a floating sweep). No % number.
            frac = max(self._tx_progress, 0.05)
        else:
            # Pasting: near-full bar — "done, dropping it in".
            frac = 0.92
        fill_left = tx
        fill_w = max(int(tw * frac), th)

        # Liquid amber: bright on top → deep at the base (a lit, glossy fluid).
        fill = QPainterPath()
        fill.addRoundedRect(fill_left, ty, fill_w, th, th / 2, th / 2)
        grad = QLinearGradient(0, ty, 0, ty + th)
        grad.setColorAt(0.0, QColor(SIGNAL_SOFT))
        grad.setColorAt(0.5, QColor(SIGNAL))
        grad.setColorAt(1.0, QColor(SIGNAL_DEEP))
        p.fillPath(fill, QBrush(grad))

        # Glossy sheen riding the top half of the fluid.
        p.save()
        p.setClipPath(fill)
        sheen = QPainterPath()
        sheen.addRoundedRect(fill_left, ty, fill_w, th / 2, th / 4, th / 4)
        p.fillPath(sheen, QColor(255, 255, 255, 72))
        p.restore()

        # Soft glow at the leading edge — the liquid "head".
        lead = fill_left + fill_w
        glow = QRadialGradient(float(lead), ty + th / 2, th * 1.7)
        glow.setColorAt(0.0, QColor(255, 154, 66, 160))
        glow.setColorAt(1.0, QColor(255, 154, 66, 0))
        gw = int(th * 1.7)
        p.fillRect(QRect(lead - gw, int(ty + th / 2) - gw, gw * 2, gw * 2), QBrush(glow))

    # --- hover pause overlay ------------------------------------------ #

    def _paint_pause(self, p: QPainter) -> None:
        # Light scrim — dims the live spectrum/dot but keeps it visible behind the
        # pause glyph (Theo: don't clear the recorded session on hover).
        p.fillRect(0, 0, W, H, QColor(8, 8, 12, 95))
        pw, ph, gap = 6, 17, 5
        total = pw * 2 + gap
        px_ = (W - total) // 2
        py_ = (H - ph) // 2 - 3
        p.setBrush(QBrush(QColor(255, 255, 255, 230)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(px_, py_, pw, ph, 2, 2)
        p.drawRoundedRect(px_ + pw + gap, py_, pw, ph, 2, 2)
