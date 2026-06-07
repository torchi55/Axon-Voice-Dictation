"""Generate the branded Axon app icon (.ico) from assets/axon-mark.svg.

Renders Theo's can-and-thread mark via Qt (keeps the amber gradient),
composites it onto a dark rounded tile that matches the app's GlassBackdrop
(#0a0a10), and writes a multi-resolution Windows .ico (16…256 px).

Run with the build venv (has PyQt6 + Pillow):
    .venv-build/Scripts/python.exe build-dist/make_icon.py
"""
import io
from pathlib import Path

from PyQt6.QtCore import Qt, QRectF, QByteArray
from PyQt6.QtGui import QPainter, QImage, QColor, QBrush, QPainterPath
from PyQt6.QtSvg import QSvgRenderer
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "assets" / "axon-mark.svg"
OUT_ICO = Path(__file__).resolve().parent / "axon.ico"
OUT_PNG = Path(__file__).resolve().parent / "axon-512.png"

BG = QColor(10, 10, 16)          # #0a0a10 — app backdrop base
SIZES = [16, 24, 32, 48, 64, 128, 256]
MASTER = 512


def render_master() -> QImage:
    img = QImage(MASTER, MASTER, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Dark rounded tile (squircle-ish radius ~22%).
    path = QPainterPath()
    r = MASTER * 0.22
    inset = MASTER * 0.0
    path.addRoundedRect(QRectF(inset, inset, MASTER - 2 * inset, MASTER - 2 * inset), r, r)
    p.fillPath(path, QBrush(BG))

    # Faint top sheen so the tile reads like the glass backdrop.
    sheen = QColor(255, 255, 255, 14)
    p.fillPath(path, QBrush(sheen))

    # Amber mark centered, aspect-preserved, ~66% of the tile.
    renderer = QSvgRenderer(QByteArray(SVG.read_bytes()))
    vb = renderer.viewBoxF()
    box = MASTER * 0.74
    scale = box / max(vb.width(), vb.height())
    mw, mh = vb.width() * scale, vb.height() * scale
    renderer.render(p, QRectF((MASTER - mw) / 2, (MASTER - mh) / 2, mw, mh))
    p.end()
    return img


def qimage_to_pil(img: QImage) -> Image.Image:
    buf = QByteArray()
    from PyQt6.QtCore import QBuffer
    qbuf = QBuffer(buf)
    qbuf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(qbuf, "PNG")
    return Image.open(io.BytesIO(bytes(buf))).convert("RGBA")


def main() -> None:
    master = render_master()
    pil = qimage_to_pil(master)
    pil.save(OUT_PNG)
    icons = [pil.resize((s, s), Image.LANCZOS) for s in SIZES]
    icons[-1].save(OUT_ICO, format="ICO",
                   sizes=[(s, s) for s in SIZES])
    print(f"wrote {OUT_ICO}  ({OUT_ICO.stat().st_size} bytes)  sizes={SIZES}")
    print(f"wrote {OUT_PNG}")


if __name__ == "__main__":
    main()
