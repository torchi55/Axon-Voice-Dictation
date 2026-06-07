import os
import sys

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


def _mark_path() -> str:
    """assets/axon-mark.svg — frozen (PyInstaller) or dev tree."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "axon-mark.svg")


def _make_icon() -> QIcon:
    """Theo's can-and-thread mark, rendered crisply at a few tray/taskbar sizes
    (multi-res so Windows picks the sharpest). Aspect-preserved, centred."""
    renderer = QSvgRenderer(_mark_path())
    vb = renderer.viewBoxF()
    icon = QIcon()
    for s in (16, 24, 32, 48, 64):
        px = QPixmap(s, s)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = (s * 0.92) / max(vb.width(), vb.height())
        mw, mh = vb.width() * scale, vb.height() * scale
        renderer.render(p, QRectF((s - mw) / 2, (s - mh) / 2, mw, mh))
        p.end()
        icon.addPixmap(px)
    return icon


class TrayIcon(QSystemTrayIcon):
    def __init__(self, main_window, parent=None):
        super().__init__(_make_icon(), parent)
        self._window = main_window
        self.setToolTip("Axon Voice")

        menu = QMenu()
        menu.addAction("Open Axon Voice", self._open)
        menu.addSeparator()
        menu.addAction("Quit", QApplication.quit)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activate)
        self.show()

    def notify(self, title: str, message: str) -> None:
        """Show a tray balloon for recoverable events (PLAN steps 4, 12, 13)."""
        try:
            self.showMessage(title, message, self.icon(), 4000)
        except Exception as e:
            print(f"[Axon] tray notify failed: {e}")

    def _open(self) -> None:
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _on_activate(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self._window.isVisible():
                self._window.hide()
            else:
                self._open()
