"""First-Run Download UI (PLAN step 2).

A modal dialog shown only when the resolved Model is not yet cached. It runs the
download on a worker thread, shows real byte progress, and on failure switches
to an explicit offline-error state with Retry / Quit (never a silent failure).
"""
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .download import download, downloaded_bytes, expected_bytes

_STYLE = """
QDialog { background: #12121f; color: #e0e0e0; font-family: 'Segoe UI'; }
QLabel { color: #e0e0e0; background: transparent; }
QProgressBar {
    background: rgba(255,255,255,0.06); border: none; border-radius: 6px;
    height: 12px; text-align: center; color: transparent;
}
QProgressBar::chunk { background: rgb(255,165,0); border-radius: 6px; }
QPushButton {
    background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.10);
    border-radius: 6px; padding: 6px 16px;
}
QPushButton:hover { background: rgba(255,255,255,0.13); }
"""


def _fmt_mb(n: int) -> str:
    return f"{n / 1e6:.0f} MB"


class _DownloadThread(QThread):
    progress = pyqtSignal(int, int)   # done_bytes, total_bytes
    ok = pyqtSignal(str)              # local path
    failed = pyqtSignal(str)         # error message

    def __init__(self, name: str):
        super().__init__()
        self._name = name

    def run(self) -> None:
        try:
            path = download(self._name, lambda d, t: self.progress.emit(d, t))
            self.ok.emit(path)
        except Exception as e:
            self.failed.emit(str(e))


class DownloadDialog(QDialog):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.path: str | None = None
        self._name = name
        self._thread: _DownloadThread | None = None
        self._total = expected_bytes(name)
        self._last_bytes = 0
        self._last_t = None

        # Poll bytes-on-disk for reliable progress (callback path is flaky for
        # large files). 800 ms keeps it smooth without hammering the filesystem.
        self._poll = QTimer(self)
        self._poll.setInterval(800)
        self._poll.timeout.connect(self._tick)

        self.setWindowTitle("Axon Voice — First-Run Setup")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(_STYLE)
        # No close button — must finish or explicitly Quit.
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(14)

        title = QLabel(f"Downloading speech model: {name}")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        root.addWidget(title)

        self._status = QLabel("Preparing…")
        self._status.setStyleSheet("color: #aaa; font-size: 12px;")
        root.addWidget(self._status)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        root.addWidget(self._bar)

        self._hint = QLabel("Weights are downloaded once and cached for future sessions.")
        self._hint.setStyleSheet("color: #666; font-size: 11px;")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)

        btns = QHBoxLayout()
        btns.addStretch()
        self._retry_btn = QPushButton("Retry")
        self._retry_btn.clicked.connect(self._start)
        self._retry_btn.hide()
        self._quit_btn = QPushButton("Quit")
        self._quit_btn.clicked.connect(self.reject)
        self._quit_btn.hide()
        btns.addWidget(self._retry_btn)
        btns.addWidget(self._quit_btn)
        root.addLayout(btns)

        self._start()

    # ------------------------------------------------------------------ #

    def _start(self) -> None:
        import time
        self._retry_btn.hide()
        self._quit_btn.hide()
        self._bar.setStyleSheet("")  # reset any error tint
        self._last_bytes = downloaded_bytes(self._name)
        self._last_t = time.monotonic()
        self._tick()
        self._status.setText("Connecting to HuggingFace…")
        self._poll.start()
        self._thread = _DownloadThread(self._name)
        self._thread.ok.connect(self._on_ok)
        self._thread.failed.connect(self._on_failed)
        self._thread.start()

    def _tick(self) -> None:
        import time
        done = downloaded_bytes(self._name)
        if self._total > 0:
            self._bar.setValue(min(99, int(done * 100 / self._total)))
        now = time.monotonic()
        speed = ""
        if self._last_t is not None and now > self._last_t:
            mbps = (done - self._last_bytes) / 1e6 / (now - self._last_t)
            if mbps > 0.05:
                speed = f"   ·   {mbps:.1f} MB/s"
        self._last_bytes, self._last_t = done, now
        self._status.setText(
            f"Downloading {self._name}…   {_fmt_mb(done)} / {_fmt_mb(self._total)}{speed}"
        )

    def _on_ok(self, path: str) -> None:
        self._poll.stop()
        self.path = path
        self._bar.setValue(100)
        self._status.setText("Verified. Starting Axon Voice…")
        self.accept()

    def _on_failed(self, msg: str) -> None:
        self._poll.stop()
        self._status.setText("Download failed — check your internet connection.")
        self._status.setStyleSheet("color: #ff6b6b; font-size: 12px;")
        self._hint.setText(msg)
        self._retry_btn.show()
        self._quit_btn.show()

    def reject(self) -> None:
        self._poll.stop()
        if self._thread and self._thread.isRunning():
            self._thread.terminate()
            self._thread.wait(2000)
        super().reject()
