"""Single-instance lock (PLAN step 11).

Ensures one running Axon Voice. A relaunch (or login autostart firing twice)
detects the primary via a Qt local socket, tells it to surface its window, and
exits — instead of starting a second process that would race on hotkeys/config.
"""
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

_NAME = "AxonVoiceSingleInstance"
_PING = b"show"


class SingleInstance(QObject):
    """Created once at startup. `is_primary` is False if another instance owns
    the lock (caller should exit). On the primary, `activated` fires when a
    later instance pings."""

    activated = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.is_primary = False
        self._server: QLocalServer | None = None

        # Try to reach an existing primary.
        probe = QLocalSocket()
        probe.connectToServer(_NAME)
        if probe.waitForConnected(200):
            probe.write(_PING)
            probe.flush()
            probe.waitForBytesWritten(200)
            probe.disconnectFromServer()
            self.is_primary = False
            return

        # No primary → become it. Clear any stale socket left by a crash.
        QLocalServer.removeServer(_NAME)
        self._server = QLocalServer()
        if not self._server.listen(_NAME):
            # Couldn't listen — fail open (run anyway) rather than block startup.
            print(f"[Axon] single-instance listen failed: {self._server.errorString()}")
            self.is_primary = True
            return
        self._server.newConnection.connect(self._on_new_connection)
        self.is_primary = True

    def _on_new_connection(self) -> None:
        conn = self._server.nextPendingConnection()
        if conn is None:
            return
        conn.readyRead.connect(lambda: self._read(conn))

    def _read(self, conn) -> None:
        data = bytes(conn.readAll())
        if _PING in data:
            self.activated.emit()
        conn.disconnectFromServer()
