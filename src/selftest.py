"""Frozen-bundle transcription self-test (diagnostic only).

Triggered by setting AXON_SELFTEST=1. Loads the CPU `small` model and runs a
real transcription with a watchdog, logging every phase to axon.log. This is how
we verify the PACKAGED app can actually transcribe — a missing native DLL
(onnxruntime VAD / ctranslate2 CPU libs) shows up here as a hang or error that a
normal-venv run would never reveal. Not part of the shipped UX.
"""
import threading
import time

import numpy as np


def _test_recorder(log) -> None:
    """Confirm the frozen bundle can actually capture mic audio (PortAudio).

    A broken PortAudio load shows up here as an exception or all-zero frames —
    which in the live app would make every dictation 'too short, skipping' and
    look exactly like 'Ctrl+Space does nothing'.
    """
    try:
        from .audio import AudioRecorder, SAMPLE_RATE
        rec = AudioRecorder()
        rec.start()
        if not rec.recording:
            log.error("SELFTEST: recorder failed to start (PortAudio?)")
            return
        time.sleep(1.0)
        audio = rec.stop()
        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) if audio.size else 0.0
        log.warning("SELFTEST: recorder captured %d samples (%.2fs) rms=%.5f",
                    audio.size, audio.size / SAMPLE_RATE, rms)
        if audio.size <= 1:
            log.error("SELFTEST: recorder returned NO audio — mic capture broken in bundle")
    except Exception as e:
        log.error("SELFTEST: recorder ERROR: %r", e)


def _test_hotkeys(log) -> None:
    """Confirm the frozen bundle's global hotkey hook receives Ctrl+Space.

    Builds the real HotkeyManager, starts the listener (with the win32 suppress
    filter), and injects a synthetic Ctrl+Space via keybd_event. If pynput's
    low-level hook is broken in the bundle, no signal fires.
    """
    try:
        import ctypes
        from types import SimpleNamespace
        from PyQt6.QtCore import Qt
        from .hotkeys import HotkeyManager

        fired = []
        cfg = SimpleNamespace(hold_hotkey="ctrl+space", free_hotkey="ctrl+alt+space")
        hk = HotkeyManager(cfg)
        hk.hold_start.connect(lambda: fired.append("hold_start"), Qt.ConnectionType.DirectConnection)
        hk.hold_end.connect(lambda: fired.append("hold_end"), Qt.ConnectionType.DirectConnection)
        hk.start()
        time.sleep(0.8)  # let the hook install

        KEYEVENTF_KEYUP = 0x02
        ke = ctypes.windll.user32.keybd_event
        ke(0x11, 0, 0, 0); time.sleep(0.03); ke(0x20, 0, 0, 0)   # Ctrl+Space down
        time.sleep(0.4)
        ke(0x20, 0, KEYEVENTF_KEYUP, 0); time.sleep(0.03); ke(0x11, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.5)  # allow the release debounce to finalize hold_end
        hk.stop()

        ok = "hold_start" in fired and "hold_end" in fired
        log.warning("SELFTEST: hotkey injection fired=%s ok=%s", fired, ok)
        if not ok:
            log.error("SELFTEST: Ctrl+Space hook did NOT fire in bundle — keyboard listener broken")
    except Exception as e:
        log.error("SELFTEST: hotkey test ERROR: %r", e)


def run_selftest() -> int:
    from .logging_setup import get_logger
    log = get_logger()
    log.warning("SELFTEST: starting")

    _test_hotkeys(log)
    _test_recorder(log)

    from .transcriber import resolve_target
    from .download import cached_path
    name, has_cuda, vram = resolve_target("auto")
    log.warning("SELFTEST: resolved model=%s cuda=%s", name, has_cuda)

    try:
        from faster_whisper import WhisperModel
        path = cached_path(name) or cached_path("small")
        device = "cuda" if has_cuda else "cpu"
        ctype = "int8_float16" if has_cuda else "int8"
        t0 = time.time()
        model = WhisperModel(path, device=device, compute_type=ctype)
        log.warning("SELFTEST: model loaded in %.1fs (%s/%s)", time.time() - t0, device, ctype)
    except Exception as e:
        log.error("SELFTEST: model load FAILED: %r", e)
        return 1

    # A voiced-ish synthetic signal (sweeping harmonics) so VAD has something.
    sr = 16000
    t = np.arange(int(sr * 4)) / sr
    f = 130 + 60 * np.sin(2 * np.pi * 0.5 * t)
    sig = sum(0.3 / k * np.sin(2 * np.pi * k * f * t) for k in (1, 2, 3))
    audio = (sig * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)

    for vad in (True, False):
        done = {"ok": False}

        def work():
            try:
                segs, info = model.transcribe(audio, language="en", beam_size=5, vad_filter=vad)
                _ = [s.text for s in segs]   # drive the generator (the actual decode)
                done["ok"] = True
            except Exception as e:
                log.error("SELFTEST: transcribe(vad=%s) ERROR: %r", vad, e)
                done["ok"] = "error"

        th = threading.Thread(target=work, daemon=True)
        t1 = time.time()
        th.start()
        th.join(timeout=20.0)
        if th.is_alive():
            log.error("SELFTEST: transcribe(vad=%s) HUNG >20s — likely missing native dep", vad)
        else:
            log.warning("SELFTEST: transcribe(vad=%s) returned in %.1fs ok=%s",
                        vad, time.time() - t1, done["ok"])

    log.warning("SELFTEST: done")
    return 0
