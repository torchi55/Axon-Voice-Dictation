import sys

from PyQt6.QtWidgets import QApplication

from src.app import App
from src.bootstrap import ensure_model_ready
from src.config import load_config
from src.fonts import load_fonts
from src.logging_setup import setup_logging
from src.single_instance import SingleInstance


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    load_fonts(app)   # brand font app-wide (Typo Square), before any window builds
    log = setup_logging()

    # Diagnostic: AXON_SELFTEST=1 runs an in-bundle transcription check and exits.
    import os as _os
    if _os.environ.get("AXON_SELFTEST") == "1":
        from src.selftest import run_selftest
        return run_selftest()

    # Single-instance: if one is already running, ping it to surface and exit.
    instance = SingleInstance()
    if not instance.is_primary:
        log.info("Another instance is running — asked it to surface; exiting.")
        return 0

    config = load_config()

    # First-run: resolve the Model from hardware and ensure weights are present
    # (shows the download dialog only if not already cached).
    resolved = ensure_model_ready(config.model)
    if resolved is None:
        log.info("Model not ready — exiting.")
        return 0

    model_name, model_path, prefer_cuda = resolved
    axon = App(config, model_name, model_path, prefer_cuda)
    instance.activated.connect(axon.show_window)
    axon.show_window()   # surface the window on launch (lives on the desktop)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
