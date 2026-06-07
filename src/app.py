import queue
import threading

import numpy as np
from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from .audio import AudioRecorder
from .config import load_snippets, save_config, save_snippets
from .logging_setup import get_logger, safe_text_summary
from .hotkeys import HotkeyManager
from .output import output_text
from .overlay import Overlay
from .processing import process
from .transcriber import Transcriber, build_vocab_prompt
from .tray import TrayIcon
from .window import MainWindow, _pretty

# Module logger — the windowed exe has a null stdout, so the print()s below are
# invisible in the packaged build. These _log.info lines surface the full
# record→transcribe→paste pipeline in axon.log so a failure can be pinpointed.
_log = get_logger()

MIN_AUDIO_SAMPLES = 4800       # 0.3 s at 16 kHz — discard tap-and-release noise
MAX_FREE_SECONDS = 300         # Hands-Free auto-stops after 5 min (PLAN step 4)
TX_BAR_DELAY_MS = 3000         # show the loading bar only if transcription
                               # outlasts this — short/medium clips finish first
                               # and never flash a bar; only a genuinely long
                               # dictation surfaces the indeterminate sweep (Theo's ask)


class _TranscribeWorker(QThread):
    """Single serialized transcription worker (PLAN step 12).

    All Dictations flow through one queue and one WhisperModel.transcribe()
    call at a time — faster-whisper thread-safety is not assumed. Overlapping
    Dictations are queued, never silently dropped.
    """
    done = pyqtSignal(str, float)   # (transcript, recorded_seconds)
    progress = pyqtSignal(float)    # transcription fraction in [0, 1]

    def __init__(self, transcriber: Transcriber):
        super().__init__()
        self._transcriber = transcriber
        self._queue: "queue.Queue[tuple | None]" = queue.Queue()
        self._running = True

    def set_transcriber(self, transcriber: Transcriber) -> None:
        """Hot-swap the model (Settings model change). A reference assignment is
        atomic in CPython; any job already mid-decode finishes on the old model,
        the next dequeued job uses the new one."""
        self._transcriber = transcriber

    def enqueue(self, audio: np.ndarray, prompt: str | None = None) -> None:
        self._queue.put((audio, prompt))

    def shutdown(self) -> None:
        self._running = False
        self._queue.put(None)  # sentinel to unblock get()

    def run(self) -> None:
        from .audio import SAMPLE_RATE
        while self._running:
            item = self._queue.get()
            if item is None:
                break
            audio, prompt = item
            duration = len(audio) / SAMPLE_RATE
            text = self._transcriber.transcribe(
                audio, progress_cb=self.progress.emit, initial_prompt=prompt
            )
            self.done.emit(text, duration)


class App(QObject):
    _paste_done = pyqtSignal(bool)   # paste finished on the output thread → (ok)

    def __init__(self, config, model_name: str, model_path: str, prefer_cuda: bool):
        super().__init__()
        self._config = config
        self._recorder = AudioRecorder()
        self._transcriber = Transcriber(model_name, model_path, prefer_cuda)
        self._free_mode = False

        self._hotkeys = HotkeyManager(self._config)

        self._overlay = Overlay()
        self._overlay.free_keybind = _pretty(self._config.free_hotkey)
        self._window = MainWindow(
            self._config,
            save_config,
            load_snippets,
            save_snippets,
            self._hotkeys,
            self.reload_model,
        )
        self._tray = TrayIcon(self._window)

        self._worker = _TranscribeWorker(self._transcriber)
        self._worker.done.connect(self._on_transcript)
        self._worker.progress.connect(self._overlay.set_transcribe_progress)
        self._worker.start()

        # Deferred-bar timer: started when transcription begins; if it fires
        # before the transcript is ready, promote the calm pill to the real bar.
        self._tx_show_timer = QTimer(self)
        self._tx_show_timer.setSingleShot(True)
        self._tx_show_timer.setInterval(TX_BAR_DELAY_MS)
        self._tx_show_timer.timeout.connect(self._overlay.show_transcribing)

        self._hotkeys.hold_start.connect(self._on_hold_start)
        self._hotkeys.hold_end.connect(self._on_hold_end)
        self._hotkeys.free_toggle.connect(self._on_free_toggle)
        self._overlay.pause_clicked.connect(self._on_pause_clicked)
        self._paste_done.connect(self._on_paste_done)
        self._hotkeys.start()

        # Tear down background workers/listeners/streams on quit so the process
        # doesn't exit with a running QThread, pynput listener, or live stream.
        QApplication.instance().aboutToQuit.connect(self._shutdown)

        self._amp_timer = self.startTimer(40)
        print("[Axon] Running  —  Ctrl+Space (hold) | Ctrl+Alt+Space (toggle)")

    # ------------------------------------------------------------------ #

    def timerEvent(self, _event) -> None:
        if self._recorder.recording:
            self._overlay.set_levels(self._recorder.get_spectrum(self._overlay.bar_count))
            # Hands-Free safety cap: auto-stop a forgotten session.
            if self._free_mode and self._recorder.duration_s >= MAX_FREE_SECONDS:
                print("[Axon] Hands-Free hit max duration → auto-stopping")
                self._tray.notify(
                    "Hands-Free stopped",
                    f"Reached the {MAX_FREE_SECONDS // 60}-minute limit. Transcribing…",
                )
                self._on_free_toggle()

    # ------------------------------------------------------------------ #

    def _on_hold_start(self) -> None:
        if self._free_mode:
            _log.info("hold_start IGNORED — free_mode active (toggle off first)")
            return
        _log.info("hold start → recording")
        self._recorder.start()
        self._overlay.show_recording("hold")

    def _on_hold_end(self) -> None:
        if self._free_mode:
            return
        audio = self._recorder.stop()
        _log.info("hold end → %d samples (%.2fs) rms=%.5f",
                  len(audio), len(audio) / 16000, float(np.sqrt(np.mean(audio ** 2))))
        self._begin_transcribing_ui()
        self._dispatch(audio)

    def _on_free_toggle(self) -> None:
        if not self._free_mode and self._recorder.recording:
            # A Hold-to-Talk recording is already live (user pressed the free
            # combo mid-hold). Ignore it — starting again would double-open the
            # recorder. _on_hold_start has the symmetric guard via _free_mode.
            print("[Axon] free toggle ignored — hold recording active")
            return
        if not self._free_mode:
            self._free_mode = True
            _log.info("free mode ON → recording")
            self._recorder.start()
            self._overlay.free_keybind = _pretty(self._config.free_hotkey)
            self._overlay.show_recording("free")
        else:
            self._free_mode = False
            audio = self._recorder.stop()
            _log.info("free mode OFF → %d samples (%.2fs) rms=%.5f",
                      len(audio), len(audio) / 16000, float(np.sqrt(np.mean(audio ** 2))))
            self._begin_transcribing_ui()
            self._dispatch(audio)

    def _on_pause_clicked(self) -> None:
        print("[Axon] overlay clicked → pause")
        if self._free_mode:
            self._on_free_toggle()
        else:
            self._hotkeys.force_end_hold()

    # ------------------------------------------------------------------ #

    def _begin_transcribing_ui(self) -> None:
        """Show the calm 'warming' pill and arm the deferred determinate bar."""
        self._overlay.show_processing()
        self._tx_show_timer.start()

    def _dispatch(self, audio: np.ndarray) -> None:
        if len(audio) < MIN_AUDIO_SAMPLES:
            _log.info("recording too short (%d samples), skipping", len(audio))
            self._tx_show_timer.stop()
            self._overlay.hide_overlay()
            return
        # Read vocabulary fresh each time so edits in Settings take effect with
        # no restart. Queue the job — serialized worker handles one at a time.
        prompt = build_vocab_prompt(self._config.vocabulary)
        _log.info("dispatch → transcribe queue (%d samples)", len(audio))
        self._worker.enqueue(audio, prompt)

    def _on_transcript(self, raw: str, duration: float) -> None:
        self._tx_show_timer.stop()   # transcript ready — cancel any pending bar
        log = get_logger()
        log.debug("raw transcript %s", safe_text_summary(raw))
        snippets = self._window.get_snippets()
        text = process(raw, snippets, self._config.filler_cleanup)
        _log.info("transcript: raw=%d chars → final=%d chars (%.2fs audio)",
                  len(raw), len(text), duration)
        if not text:
            _log.info("empty transcript → nothing to paste (silence / VAD filtered)")
            self._overlay.hide_overlay()
            return
        self._window.add_history_entry(text, duration)
        self._overlay.show_pasting()
        # Paste off the UI thread: output_text sleeps ~120 ms and may type a
        # long transcript char-by-char — doing that here would freeze the
        # overlay/timers. Result comes back via _paste_done on the GUI thread.
        self._hotkeys.suppress_during_output(True)
        threading.Thread(target=self._do_output, args=(text,), daemon=True).start()

    def _do_output(self, text: str) -> None:
        """Runs on a worker thread — paste + leave on clipboard."""
        try:
            ok = output_text(text)
        finally:
            self._hotkeys.suppress_during_output(False)
        self._paste_done.emit(ok)

    def _on_paste_done(self, ok: bool) -> None:
        _log.info("paste done ok=%s", ok)
        if not ok:
            get_logger().warning("output failed; text left on clipboard")
            self._tray.notify(
                "Couldn't paste",
                "Transcript copied to clipboard — paste it manually.",
            )
        self._overlay.hide_overlay()

    def _shutdown(self) -> None:
        print("[Axon] shutting down…")
        try:
            self._hotkeys.stop()
        except Exception:
            pass
        try:
            if self._recorder.recording:
                self._recorder.stop()
        except Exception:
            pass
        try:
            self._worker.shutdown()
            self._worker.wait(2000)
        except Exception:
            pass

    def reload_model(self, requested: str) -> bool:
        """Apply a Settings model change live — no restart. Resolves the request
        for this hardware, downloads it (modal First-Run dialog) if it isn't
        cached yet, then hot-swaps the transcriber into the worker. Returns False
        if the user cancels the download (caller reverts the picker)."""
        from .download import cached_path, is_cached
        from .transcriber import resolve_target

        name, has_cuda, _vram = resolve_target(requested)
        if is_cached(name):
            path = cached_path(name)
        else:
            from .download_dialog import DownloadDialog
            dlg = DownloadDialog(name, parent=self._window)
            dlg.exec()
            if not dlg.path:
                _log.info("model change to %s cancelled (download aborted)", name)
                return False
            path = dlg.path

        self._transcriber = Transcriber(name, path, has_cuda)
        self._worker.set_transcriber(self._transcriber)
        _log.info("model reloaded → %s (cuda=%s)", name, has_cuda)
        return True

    def show_window(self) -> None:
        """Surface the Main Window (used by the single-instance ping)."""
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
