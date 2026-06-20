"""Transcription core (PLAN steps 1, 12).

Auto-Detect reads TOTAL VRAM via pynvml/NVML (not torch — faster-whisper's
CTranslate2 backend needs neither torch nor it for inference) and resolves the
largest Model that fits with headroom. CUDA uses compute_type="int8_float16";
CPU clamps to `small` and uses "int8".
"""
import threading

import numpy as np

SAMPLE_RATE = 16_000

# Model size ordering, smallest → largest. Used for CPU clamping and overrides.
MODEL_ORDER = ["tiny", "base", "small", "medium", "large-v3"]
CPU_MAX_MODEL = "small"


def build_vocab_prompt(vocabulary: str) -> str | None:
    """Turn the user's vocabulary box (comma/newline separated terms) into a
    Whisper `initial_prompt`. Whisper treats it as preceding context, so seeding
    it with domain terms biases the decoder toward their spelling (Rhino,
    Grasshopper, proper names). Returns None when empty."""
    if not vocabulary:
        return None
    terms = [t.strip() for t in vocabulary.replace("\n", ",").split(",")]
    terms = [t for t in terms if t]
    if not terms:
        return None
    return "Vocabulary: " + ", ".join(terms) + "."


def _model_rank(name: str) -> int:
    try:
        return MODEL_ORDER.index(name)
    except ValueError:
        return MODEL_ORDER.index("base")


def _clamp_model(name: str, ceiling: str) -> str:
    """Return the smaller of `name` and `ceiling` by size rank."""
    return name if _model_rank(name) <= _model_rank(ceiling) else ceiling


def cuda_available() -> bool:
    """True if CTranslate2 sees at least one CUDA device (no torch needed).

    PACKAGED (frozen) builds are CPU-first BY DESIGN: we ship without the full
    CUDA runtime (cuBLAS etc.) to keep the download universal + small. The
    ctranslate2 wheel bundles cuDNN, so on an NVIDIA machine get_cuda_device_count()
    returns >0 and the app would pick a CUDA model — then inference dies on a
    missing cublas64_*.dll (and a follow-up call HANGS the worker at 0%). So force
    CPU when frozen. Dev runs (not frozen) still auto-detect the GPU normally.
    """
    import sys
    if getattr(sys, "frozen", False):
        return False
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def detect_total_vram_gb() -> float | None:
    """Total VRAM of GPU 0 in GiB via NVML, or None if unavailable.

    Total (not free) VRAM is the stable signal Auto-Detect keys off — free VRAM
    fluctuates with whatever else is running.
    """
    try:
        import pynvml
        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            return info.total / (1024 ** 3)
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return None


def resolve_target(requested: str) -> tuple[str, bool, float | None]:
    """Fast, side-effect-free resolution for the bootstrap/first-run flow.

    Returns (model_name, has_cuda, vram_gb) without loading any weights, so the
    UI can decide whether a First-Run Download is needed before constructing the
    Transcriber.
    """
    has_cuda = cuda_available()
    vram = detect_total_vram_gb() if has_cuda else None
    name = resolve_model(requested, has_cuda, vram)
    return name, has_cuda, vram


def resolve_model(requested: str, has_cuda: bool, vram_gb: float | None) -> str:
    """Pure resolver: map (requested, hardware) → concrete Model name.

    - CPU (no CUDA): "auto" → small (the sane CPU default); an EXPLICIT choice is
      honored as-is (even medium/large) — the user picked it knowing it's slower
      on CPU, and the Settings picker warns about that. (Only the CUDA→CPU load
      *fallback* in Transcriber clamps size, since there the GPU just failed.)
    - CUDA: honor an explicit request; for "auto" pick the largest tier that
      fits total VRAM with headroom (large-v3 ≥6GB, medium ≥4GB, small ≥2GB,
      else base).
    """
    if not has_cuda:
        if requested == "auto":
            return CPU_MAX_MODEL
        return requested

    if requested != "auto":
        return requested

    if vram_gb is None:
        return "base"
    if vram_gb >= 6:
        return "large-v3"
    if vram_gb >= 4:
        return "medium"
    if vram_gb >= 2:
        return "small"
    return "base"


class Transcriber:
    """Loads a Model from a verified local snapshot path on a background thread.

    The First-Run Download / cache resolution happens in bootstrap before this
    is constructed, so `model_path` already points at downloaded, hash-verified
    weights. `prefer_cuda` reflects Auto-Detect; if a CUDA load unexpectedly
    fails we clamp to a CPU-safe Model (fetching it if necessary).
    """

    def __init__(self, name: str, model_path: str, prefer_cuda: bool):
        self._model = None
        self._name = name
        self._path = model_path
        self._prefer_cuda = prefer_cuda
        self._model_lock = threading.Lock()
        self._ready = threading.Event()
        self._resolved_name: str = name
        self._device: str = ""
        self._load_error: str = ""
        t = threading.Thread(target=self._load, daemon=True)
        t.start()

    def _load(self) -> None:
        from faster_whisper import WhisperModel

        if self._prefer_cuda:
            try:
                model = WhisperModel(
                    self._path, device="cuda", compute_type="int8_float16"
                )
                self._device = "cuda"
                self._finish(model, self._name)
                return
            except Exception as e:
                print(f"[Axon] CUDA load failed ({e}); falling back to CPU")

        # CPU path: clamp model size, fetching the clamped Model if it differs.
        # The whole branch (incl. the download) is inside the try so a fetch or
        # load failure records _load_error and the loader thread dies cleanly —
        # otherwise an uncached-CPU-model download exception would kill the
        # thread with _ready never set, hanging the app on "loading" forever.
        try:
            # Clamp size ONLY when this CPU path is a *fallback* from a failed
            # CUDA load (prefer_cuda was True). An intentional CPU run honors the
            # already-resolved name so an explicit medium/large choice loads.
            cpu_name = _clamp_model(self._name, CPU_MAX_MODEL) if self._prefer_cuda else self._name
            cpu_path = self._path
            if cpu_name != self._name:
                from .download import cached_path, download
                cpu_path = cached_path(cpu_name) or download(cpu_name)
            self._resolved_name = cpu_name
            model = WhisperModel(cpu_path, device="cpu", compute_type="int8")
            self._device = "cpu"
            self._finish(model, cpu_name)
        except Exception as e:
            self._load_error = str(e)
            print(f"[Axon] Model load failed: {e}")

    def _finish(self, model, name: str) -> None:
        with self._model_lock:
            self._model = model
        self._ready.set()
        print(f"[Axon] Model ready: {name} on {self._device}")

    @property
    def resolved_model(self) -> str:
        return self._resolved_name

    @property
    def device(self) -> str:
        return self._device

    @property
    def load_error(self) -> str:
        return self._load_error

    def is_ready(self) -> bool:
        return self._ready.is_set()

    def transcribe(self, audio: np.ndarray, progress_cb=None,
                   initial_prompt: str | None = None) -> str:
        """Transcribe audio to text.

        `segments` is a lazy generator — iterating it *is* the decode work. Each
        segment carries a `.end` timestamp, and `info.duration` is the total
        audio length, so we report real progress (end/duration) as we go rather
        than a fake sweep. `progress_cb(frac)` is called from this worker thread
        with frac in [0, 1]; the caller marshals it to the GUI thread.
        """
        with self._model_lock:
            model = self._model
        if model is None:
            # Hotkeys go live before the model finishes loading. Rather than
            # silently lose an early dictation, wait briefly for the load to
            # finish (success sets _ready). Bail fast if the load already failed.
            if self._load_error or not self._ready.wait(timeout=60.0):
                print("[Axon] Model not ready (load slow or failed); clip dropped")
                return ""
            with self._model_lock:
                model = self._model
            if model is None:
                return ""
        try:
            segments, info = model.transcribe(
                audio,
                language="en",
                beam_size=5,
                vad_filter=True,
                vad_parameters={"threshold": 0.2, "min_silence_duration_ms": 500},
                initial_prompt=initial_prompt,
            )
            total = max(float(getattr(info, "duration", 0.0)) or 0.0, 1e-6)
            parts: list[str] = []
            for seg in segments:
                parts.append(seg.text.strip())
                if progress_cb is not None:
                    progress_cb(min(seg.end / total, 1.0))
            if progress_cb is not None:
                progress_cb(1.0)
            return " ".join(parts).strip()
        except Exception as e:
            print(f"[Axon] Transcription error: {e}")
            return ""
