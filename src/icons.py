"""Thin-line icon set — one consistent visual language for the whole app.

Per the brief: thin stroke, rounded caps, minimal detail, no mixing of filled
and outline styles. Every glyph is drawn in a normalized 100×100 space and
scaled into the target rect, so stroke weight and proportions stay identical at
any size. Painted (no SVG/asset dependency, scales crisply, themeable color).

Two entry points:
  - ``draw_glyph(painter, name, rect, color, stroke=None)`` paints into an
    existing painter (custom widgets: NavBar, the combo chevron, snippet rows).
  - ``make_icon(name, size, color)`` / ``icon_pixmap(...)`` for QPushButton /
    QComboBox / QLabel.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)

NAMES = (
    "mic", "wave", "key", "gear", "clock", "snippet",
    "check", "close", "arrow", "chevron", "plus", "trash",
)


def _pen(color: QColor, w: float) -> QPen:
    pen = QPen(color, w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def draw_glyph(p: QPainter, name: str, rect: QRectF, color: QColor,
               stroke: float | None = None) -> None:
    """Paint a thin-line glyph into ``rect`` (normalized 100×100 geometry)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = min(rect.width(), rect.height())
    ox = rect.x() + (rect.width() - s) / 2
    oy = rect.y() + (rect.height() - s) / 2
    sw = stroke if stroke is not None else s * 0.085

    def P(x, y):
        return QPointF(ox + x / 100 * s, oy + y / 100 * s)

    def R(x, y, w, h):
        return QRectF(ox + x / 100 * s, oy + y / 100 * s, w / 100 * s, h / 100 * s)

    pen = _pen(color, sw)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    if name == "mic":
        p.drawRoundedRect(R(38, 12, 24, 40), 12 / 100 * s, 12 / 100 * s)
        path = QPainterPath()
        path.moveTo(P(26, 44))
        path.arcTo(R(26, 30, 48, 36), 0, -180)
        p.drawPath(path)
        p.drawLine(P(50, 66), P(50, 84))
        p.drawLine(P(36, 84), P(64, 84))

    elif name == "wave":
        # Signal waveform — symmetric bars, tall in the middle.
        hs = [34, 58, 84, 100, 84, 58, 34]
        n = len(hs)
        for i, hpct in enumerate(hs):
            x = 14 + i * (72 / (n - 1))
            half = hpct / 2 * 0.62
            p.drawLine(P(x, 50 - half), P(x, 50 + half))

    elif name == "key":
        # Keyboard: outline + key ticks + a longer space bar.
        p.drawRoundedRect(R(12, 26, 76, 48), 9 / 100 * s, 9 / 100 * s)
        for x in (26, 42, 58, 74):
            p.drawLine(P(x, 41), P(x, 41.5))
        for x in (26, 42, 58, 74):
            p.drawLine(P(x, 53), P(x, 53.5))
        p.drawLine(P(36, 64.5), P(64, 64.5))

    elif name == "gear":
        cx, cy, ro, ri = 50, 50, 26, 13
        import math
        for k in range(8):
            a = k * math.pi / 4
            p.drawLine(P(cx + ro * math.cos(a), cy + ro * math.sin(a)),
                       P(cx + (ro + 12) * math.cos(a), cy + (ro + 12) * math.sin(a)))
        p.drawEllipse(R(cx - ro, cy - ro, ro * 2, ro * 2))
        p.drawEllipse(R(cx - ri, cy - ri, ri * 2, ri * 2))

    elif name == "clock":
        p.drawEllipse(R(16, 16, 68, 68))
        p.drawLine(P(50, 50), P(50, 30))      # hour-ish
        p.drawLine(P(50, 50), P(66, 58))      # minute

    elif name == "snippet":
        # Text block: a card with three lines of decreasing length.
        p.drawRoundedRect(R(18, 20, 64, 60), 9 / 100 * s, 9 / 100 * s)
        p.drawLine(P(30, 38), P(70, 38))
        p.drawLine(P(30, 50), P(70, 50))
        p.drawLine(P(30, 62), P(56, 62))

    elif name == "check":
        path = QPainterPath()
        path.moveTo(P(24, 52))
        path.lineTo(P(42, 70))
        path.lineTo(P(78, 30))
        p.drawPath(path)

    elif name == "close":
        p.drawLine(P(28, 28), P(72, 72))
        p.drawLine(P(72, 28), P(28, 72))

    elif name == "arrow":
        p.drawLine(P(22, 50), P(74, 50))
        path = QPainterPath()
        path.moveTo(P(58, 34))
        path.lineTo(P(76, 50))
        path.lineTo(P(58, 66))
        p.drawPath(path)

    elif name == "chevron":
        path = QPainterPath()
        path.moveTo(P(32, 42))
        path.lineTo(P(50, 60))
        path.lineTo(P(68, 42))
        p.drawPath(path)

    elif name == "plus":
        p.drawLine(P(50, 28), P(50, 72))
        p.drawLine(P(28, 50), P(72, 50))

    elif name == "trash":
        p.drawLine(P(26, 30), P(74, 30))
        p.drawLine(P(40, 30), P(42, 22))
        p.drawLine(P(60, 30), P(58, 22))
        path = QPainterPath()
        path.moveTo(P(31, 30))
        path.lineTo(P(35, 78))
        path.lineTo(P(65, 78))
        path.lineTo(P(69, 30))
        p.drawPath(path)
        p.drawLine(P(44, 40), P(45, 68))
        p.drawLine(P(56, 40), P(55, 68))

    p.restore()


def icon_pixmap(name: str, size: int, color: QColor, stroke: float | None = None) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    draw_glyph(p, name, QRectF(0, 0, size, size), QColor(color), stroke)
    p.end()
    return px


def make_icon(name: str, size: int, color: QColor, stroke: float | None = None) -> QIcon:
    return QIcon(icon_pixmap(name, size, color, stroke))
