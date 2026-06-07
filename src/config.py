"""Config & data safety (PLAN step 14).

Config and Snippets JSON live in %APPDATA%/AxonVoice. Writes are atomic
(temp file + os.replace) so a crash mid-write can't truncate the file. Reads are
schema-validated; a corrupt file is backed up (never silently wiped) before
falling back to defaults. Snippets may hold sensitive expansions and never leave
the machine.
"""
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .hotkey_spec import parse as _parse_hotkey

CONFIG_DIR = Path(os.environ.get("APPDATA", "~")).expanduser() / "AxonVoice"
CONFIG_FILE = CONFIG_DIR / "config.json"
SNIPPETS_FILE = CONFIG_DIR / "snippets.json"
HISTORY_FILE = CONFIG_DIR / "history.json"

_ALLOWED_MODELS = {"auto", "tiny", "base", "small", "medium", "large-v3"}

# How long dictations are kept. The user picks this in Settings; default 24h.
#   session  → wiped every time the app opens (kept only for the current run)
#   24h/1week/1month → entries older than the window are dropped
#   never    → kept indefinitely (still capped at HISTORY_MAX for file sanity)
HISTORY_RETENTIONS = ("session", "24h", "1week", "1month", "never")
_RETENTION_SECONDS = {
    "24h": 24 * 60 * 60,
    "1week": 7 * 24 * 60 * 60,
    "1month": 30 * 24 * 60 * 60,
}  # "session"/"never" have no age window (None) — handled specially.
HISTORY_MAX = 1000  # hard cap so even "never" can't bloat the file unboundedly

# Active retention, set at startup + on each Settings change via set_retention().
# A module global (not a load/save arg) keeps the persisted callbacks' signatures
# stable across the window/app call sites.
_retention = "24h"


def set_retention(value: str) -> None:
    """Point history load/save at the user's chosen retention window."""
    global _retention
    _retention = value if value in HISTORY_RETENTIONS else "24h"


def _retention_ttl() -> int | None:
    """Seconds of history to keep, or None for no age window (session/never)."""
    return _RETENTION_SECONDS.get(_retention)


@dataclass
class Config:
    hold_hotkey: str = "ctrl+space"          # 2-key push-to-talk
    free_hotkey: str = "ctrl+alt+space"      # 3-key hands-free toggle (no Win/IME conflict)
    model: str = "base"   # out-of-box default: small (~140MB), runs on any PC.
                          # Users upgrade via the picker; "Auto" detects their best fit.
    filler_cleanup: bool = False  # default OFF — naive filler stripping damages real text
    start_with_windows: bool = False
    vocabulary: str = ""          # user terms that prime Whisper (Rhino, Grasshopper, names…)
    history_retention: str = "24h"  # session | 24h | 1week | 1month | never


# ---------------------------------------------------------------------- #
# Safe IO primitives
# ---------------------------------------------------------------------- #

def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same filesystem


def _backup_corrupt(path: Path) -> None:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(path.suffix + f".corrupt-{stamp}.bak")
    try:
        shutil.copy2(path, backup)
    except Exception as e:
        print(f"[Axon] could not back up corrupt {path.name}: {e}")
        return
    print(f"[Axon] backed up corrupt {path.name} -> {backup.name}")


def _valid_hotkey(value, default: str) -> str:
    if not isinstance(value, str):
        return default
    try:
        _parse_hotkey(value)
        return value
    except Exception:
        return default


# ---------------------------------------------------------------------- #
# Config
# ---------------------------------------------------------------------- #

def _coerce_config(data: dict) -> Config:
    d = Config()
    if not isinstance(data, dict):
        return d
    d.hold_hotkey = _valid_hotkey(data.get("hold_hotkey"), d.hold_hotkey)
    d.free_hotkey = _valid_hotkey(data.get("free_hotkey"), d.free_hotkey)
    model = data.get("model", d.model)
    d.model = model if model in _ALLOWED_MODELS else "base"
    d.filler_cleanup = bool(data.get("filler_cleanup", d.filler_cleanup))
    d.start_with_windows = bool(data.get("start_with_windows", d.start_with_windows))
    vocab = data.get("vocabulary", d.vocabulary)
    d.vocabulary = vocab if isinstance(vocab, str) else d.vocabulary
    retention = data.get("history_retention", d.history_retention)
    d.history_retention = retention if retention in HISTORY_RETENTIONS else "24h"
    return d


def load_config() -> Config:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        return Config()
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _backup_corrupt(CONFIG_FILE)
        return Config()
    return _coerce_config(data)


def save_config(config: Config) -> None:
    _atomic_write(CONFIG_FILE, json.dumps(asdict(config), indent=2))


# ---------------------------------------------------------------------- #
# Snippets
# ---------------------------------------------------------------------- #

def _coerce_snippets(data) -> dict:
    if not isinstance(data, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in data.items()
        if isinstance(k, str) and k.strip()
    }


def load_snippets() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not SNIPPETS_FILE.exists():
        return {}
    try:
        data = json.loads(SNIPPETS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _backup_corrupt(SNIPPETS_FILE)
        return {}
    return _coerce_snippets(data)


def save_snippets(snippets: dict) -> None:
    _atomic_write(SNIPPETS_FILE, json.dumps(snippets, indent=2))


# ---------------------------------------------------------------------- #
# History (persisted, but self-expiring after HISTORY_TTL_S)
# ---------------------------------------------------------------------- #

def _prune_history(entries: list) -> list:
    """Keep only well-formed entries inside the active retention window, newest
    first, capped at HISTORY_MAX. With no age window (session/never) only the
    well-formedness + cap rules apply."""
    ttl = _retention_ttl()
    cutoff = (time.time() - ttl) if ttl is not None else None
    clean = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        text = e.get("text")
        ts = e.get("ts")
        if not isinstance(text, str) or not isinstance(ts, (int, float)):
            continue
        if cutoff is not None and ts < cutoff:
            continue
        clean.append({"text": text, "ts": float(ts),
                      "duration": float(e.get("duration", 0.0) or 0.0)})
    clean.sort(key=lambda e: e["ts"], reverse=True)
    return clean[:HISTORY_MAX]


def load_history() -> list:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # "Per session" means a clean slate each open — wipe the persisted file so
    # nothing survives between runs.
    if _retention == "session":
        try:
            HISTORY_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return []
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _backup_corrupt(HISTORY_FILE)
        return []
    if not isinstance(data, list):
        return []
    return _prune_history(data)


def save_history(entries: list) -> None:
    _atomic_write(HISTORY_FILE, json.dumps(_prune_history(entries), indent=2))
