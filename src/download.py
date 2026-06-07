"""First-Run Download (PLAN step 2).

Fetches the resolved Model's weights from HuggingFace, pinned to a specific
commit SHA, and returns the local snapshot path. huggingface_hub verifies each
LFS file's sha256 during download; we additionally assert the resolved snapshot
directory matches the pinned SHA. Callers pass the returned path straight to
WhisperModel so faster-whisper never does its own float-by-name fetch.
"""
import os
import threading

from .model_repo import repo_for


class DownloadError(Exception):
    """Raised when a Model cannot be fetched or fails verification."""


class _Aggregator:
    """Sums per-file byte progress into one overall (done, total) callback."""

    def __init__(self, total: int, cb):
        self._total = total
        self._cb = cb
        self._done = 0
        self._lock = threading.Lock()

    def add(self, n: int) -> None:
        with self._lock:
            self._done += n
            done = self._done
        if self._cb:
            self._cb(done, self._total)


def _tqdm_class_for(agg: _Aggregator):
    """A huggingface_hub tqdm subclass that forwards byte deltas to `agg`."""
    from huggingface_hub.utils import tqdm as hf_tqdm

    class _Tqdm(hf_tqdm):  # type: ignore[misc]
        def update(self, n=1):
            agg.add(int(n or 0))
            return super().update(n)

    return _Tqdm


def expected_bytes(name: str) -> int:
    """Approximate total download size for a Model."""
    return repo_for(name)[2]


def downloaded_bytes(name: str) -> int:
    """Bytes currently on disk for a Model (incl. in-progress .incomplete).

    Polled by the download UI for reliable progress — more robust than relying
    on huggingface_hub's per-file tqdm callbacks, which don't always surface
    byte-level updates for large LFS/Xet files.
    """
    from huggingface_hub.constants import HF_HUB_CACHE

    repo, _, _ = repo_for(name)
    blobs = os.path.join(HF_HUB_CACHE, "models--" + repo.replace("/", "--"), "blobs")
    total = 0
    try:
        for f in os.listdir(blobs):
            fp = os.path.join(blobs, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    except FileNotFoundError:
        pass
    return total


def is_cached(name: str) -> bool:
    """True if the pinned revision is already fully present in the local cache."""
    from huggingface_hub import snapshot_download

    repo, sha, _ = repo_for(name)
    try:
        snapshot_download(repo, revision=sha, local_files_only=True)
        return True
    except Exception:
        return False


def cached_path(name: str) -> str | None:
    """Local snapshot path for the pinned revision if cached, else None."""
    from huggingface_hub import snapshot_download

    repo, sha, _ = repo_for(name)
    try:
        return snapshot_download(repo, revision=sha, local_files_only=True)
    except Exception:
        return None


def download(name: str, progress_cb=None) -> str:
    """Download the pinned Model and return its verified local snapshot path.

    progress_cb(done_bytes, total_bytes) is called during transfer. Raises
    DownloadError on network failure or revision mismatch.
    """
    from huggingface_hub import snapshot_download

    repo, sha, approx = repo_for(name)
    agg = _Aggregator(approx, progress_cb)
    try:
        path = snapshot_download(
            repo,
            revision=sha,
            tqdm_class=_tqdm_class_for(agg),
        )
    except Exception as e:
        raise DownloadError(f"Failed to download {name}: {e}") from e

    # Verify the resolved snapshot is exactly the pinned revision.
    if os.path.basename(os.path.normpath(path)) != sha:
        raise DownloadError(
            f"Revision mismatch for {name}: expected {sha}, got {path}"
        )
    return path
