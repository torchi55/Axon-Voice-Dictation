"""First-run bootstrap (PLAN steps 1-2).

Resolves the target Model from hardware, and ensures its weights are present
before the app proper starts. Shows the First-Run Download dialog only when the
pinned revision isn't already cached. Returns the data App needs to construct
the Transcriber, or None if the user quit during download.
"""
from .download import cached_path, is_cached
from .transcriber import resolve_target


def ensure_model_ready(requested: str) -> tuple[str, str, bool] | None:
    """Return (model_name, local_path, prefer_cuda), or None if the user quit."""
    name, has_cuda, vram = resolve_target(requested)
    vram_str = f"{vram:.1f}GB" if vram is not None else "n/a"
    print(f"[Axon] Auto-Detect: cuda={has_cuda} vram={vram_str} → model={name}")

    if is_cached(name):
        print(f"[Axon] Model {name} already cached.")
        return name, cached_path(name), has_cuda

    # Not cached → First-Run Download (modal, with its own retry/offline state).
    from .download_dialog import DownloadDialog

    dlg = DownloadDialog(name)
    dlg.exec()
    if dlg.path:
        return name, dlg.path, has_cuda
    return None
