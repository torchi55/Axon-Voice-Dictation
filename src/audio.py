import threading
import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000
CHANNELS = 1
BLOCK_SIZE = 1024
MIN_DURATION_S = 0.3          # discard recordings shorter than this


class AudioRecorder:
    def __init__(self):
        self._recording = False
        self._frames: list[np.ndarray] = []
        self._sample_count = 0
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._win_cache: dict[int, np.ndarray] = {}
        self._band_cache: dict[tuple[int, int], list[np.ndarray]] = {}

    def _teardown_stream(self) -> None:
        """Stop + close the current stream (if any) and drop the reference."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def start(self) -> None:
        # Idempotent: tear down any existing stream first. Without this, an
        # overlapping start (e.g. the Hands-Free toggle pressed while a
        # Hold-to-Talk recording is live) would orphan the old InputStream,
        # which keeps firing its callback into _frames — a leak + garbled audio.
        self._teardown_stream()
        with self._lock:
            self._frames = []
            self._sample_count = 0
            self._recording = True
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                blocksize=BLOCK_SIZE,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as e:
            print(f"[Axon] Audio start error: {e}")
            with self._lock:
                self._recording = False

    def stop(self) -> np.ndarray:
        with self._lock:                    # set flag inside lock — same as _callback checks
            self._recording = False
        self._teardown_stream()
        with self._lock:
            frames = list(self._frames)
        if not frames:
            return np.zeros(1, dtype="float32")
        audio = np.concatenate(frames, axis=0).flatten()
        # discard recordings that are too short to contain speech
        if len(audio) < int(SAMPLE_RATE * MIN_DURATION_S):
            return np.zeros(1, dtype="float32")
        return audio

    def get_amplitude(self) -> float:
        with self._lock:
            if self._frames:
                return float(np.abs(self._frames[-1]).mean())
            return 0.0

    def get_spectrum(self, n_bands: int) -> np.ndarray:
        """Per-band energy of the latest audio block (low → high frequency).

        Buckets an FFT of the most recent block into ``n_bands`` log-spaced bands
        across the speech range (80 Hz–4 kHz). The caller (overlay) applies its
        own adaptive gain + smoothing, so this returns raw band magnitudes. The
        log spacing is what lets the meter react to vocal pitch — low notes light
        the left bars, high notes the right.
        """
        with self._lock:
            block = self._frames[-1].flatten() if self._frames else None
        if block is None or len(block) < 256:
            return np.zeros(n_bands, dtype="float32")
        n = len(block)
        mag = np.abs(np.fft.rfft(block * self._hann(n)))
        out = np.zeros(n_bands, dtype="float32")
        for i, sel in enumerate(self._band_indices(n, n_bands)):
            if sel.size:
                out[i] = float(mag[sel].mean())
        return out

    def _hann(self, n: int) -> np.ndarray:
        """Cached Hann window — block length is fixed, so build it once."""
        w = self._win_cache.get(n)
        if w is None:
            w = np.hanning(n).astype("float32")
            self._win_cache[n] = w
        return w

    def _band_indices(self, n: int, n_bands: int) -> list[np.ndarray]:
        """Cached log-spaced FFT-bin groupings (80 Hz–4 kHz) for this block
        length + band count — avoids rebuilding freqs/edges/masks every tick."""
        key = (n, n_bands)
        idx = self._band_cache.get(key)
        if idx is None:
            freqs = np.fft.rfftfreq(n, 1.0 / SAMPLE_RATE)
            edges = np.logspace(np.log10(80.0), np.log10(4000.0), n_bands + 1)
            idx = [np.where((freqs >= edges[i]) & (freqs < edges[i + 1]))[0]
                   for i in range(n_bands)]
            self._band_cache[key] = idx
        return idx

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def duration_s(self) -> float:
        with self._lock:
            return self._sample_count / SAMPLE_RATE

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time,
        status: sd.CallbackFlags,
    ) -> None:
        with self._lock:
            if self._recording:
                self._frames.append(indata.copy())
                self._sample_count += len(indata)
