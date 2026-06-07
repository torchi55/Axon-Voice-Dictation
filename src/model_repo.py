"""Pinned model repositories (PLAN step 2).

The Model is fetched at runtime, so supply-chain integrity replaces the trust
you'd get from bundling. Each Model is pinned to a specific HuggingFace commit
SHA — never a floating branch name — so a moved `main` can't silently swap the
weights. huggingface_hub additionally verifies each LFS file's sha256 against
the revision's pointer during download.

SHAs captured 2026-06-05. Sizes are approximate total repo size.
"""

# name -> (repo_id, pinned_revision_sha, approx_bytes)
MODEL_REPOS: dict[str, tuple[str, str, int]] = {
    "tiny":     ("Systran/faster-whisper-tiny",     "d90ca5fe260221311c53c58e660288d3deb8d356",   78_000_000),
    "base":     ("Systran/faster-whisper-base",     "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66",  148_000_000),
    "small":    ("Systran/faster-whisper-small",    "536b0662742c02347bc0e980a01041f333bce120",  486_000_000),
    "medium":   ("Systran/faster-whisper-medium",   "08e178d48790749d25932bbc082711ddcfdfbc4f", 1_531_000_000),
    "large-v3": ("Systran/faster-whisper-large-v3", "edaa852ec7e145841d8ffdb056a99866b5f0a478", 3_091_000_000),
}


def repo_for(name: str) -> tuple[str, str, int]:
    """Return (repo_id, revision_sha, approx_bytes) for a Model name."""
    if name not in MODEL_REPOS:
        raise ValueError(f"Unknown model: {name!r}")
    return MODEL_REPOS[name]
