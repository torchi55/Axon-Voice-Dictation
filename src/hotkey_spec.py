"""Hotkey parsing & validation (PLAN step 3) — pure, no pynput, no Qt.

A Hotkey is a set of modifiers (ctrl/alt/win/shift) plus exactly one main key,
canonicalized to a "+"-joined string in fixed modifier order, e.g.
"ctrl+space", "ctrl+win+space", "ctrl+alt+space".

Rebinding validates the chosen combo: it must have a real modifier (so normal
typing can't trigger it), a typeable main key, must not be a reserved OS
shortcut, and the two Hotkeys must differ.
"""
from dataclasses import dataclass

MOD_ORDER = ["ctrl", "alt", "win", "shift"]
_MODS = set(MOD_ORDER)

# Aliases accepted from config / capture → canonical token.
_ALIASES = {
    "control": "ctrl", "ctl": "ctrl",
    "option": "alt", "alt_gr": "alt", "altgr": "alt",
    "cmd": "win", "super": "win", "meta": "win", "windows": "win", "win": "win",
    "return": "enter",
    "escape": "esc",
}

# Allowed main keys: letters, digits, space, function keys, a few named keys.
_NAMED_KEYS = {"space", "enter", "tab", "esc", "backspace", "insert", "home",
               "end", "pageup", "pagedown", "up", "down", "left", "right"}
_FN_KEYS = {f"f{i}" for i in range(1, 13)}


def _is_main_key(tok: str) -> bool:
    return (
        tok in _NAMED_KEYS
        or tok in _FN_KEYS
        or (len(tok) == 1 and (tok.isalpha() or tok.isdigit()))
    )


# Reserved OS shortcuts that must not be rebound (canonical form).
RESERVED = {
    "ctrl+alt+delete", "ctrl+shift+esc", "ctrl+esc",
    "alt+tab", "alt+esc", "alt+space", "alt+f4",
    "win+l", "win+d", "win+e", "win+r", "win+i", "win+x",
    "win+tab", "win+a", "win+s", "win+m", "win+space",
    "printscreen",
}


@dataclass(frozen=True)
class Hotkey:
    mods: frozenset
    key: str

    @property
    def canonical(self) -> str:
        ordered = [m for m in MOD_ORDER if m in self.mods]
        return "+".join(ordered + [self.key])

    def __str__(self) -> str:
        return self.canonical


def parse(spec: str) -> Hotkey:
    """Parse a hotkey string into a Hotkey. Raises ValueError if malformed."""
    if not spec or not spec.strip():
        raise ValueError("empty hotkey")
    mods: set[str] = set()
    main: str | None = None
    for raw in spec.lower().replace(" ", "").split("+"):
        if not raw:
            continue
        tok = _ALIASES.get(raw, raw)
        if tok in _MODS:
            mods.add(tok)
        elif _is_main_key(tok):
            if main is not None:
                raise ValueError(f"more than one main key in {spec!r}")
            main = tok
        else:
            raise ValueError(f"unrecognized key {raw!r} in {spec!r}")
    if main is None:
        raise ValueError(f"no main key in {spec!r}")
    return Hotkey(frozenset(mods), main)


def validate_one(hk: Hotkey) -> str | None:
    """Return an error string if this Hotkey is unusable, else None."""
    if not (hk.mods & {"ctrl", "alt", "win"}):
        return "Needs at least one of Ctrl, Alt, or Win (so normal typing can't trigger it)."
    if not _is_main_key(hk.key):
        return f"{hk.key!r} is not a usable main key."
    if hk.canonical in RESERVED:
        return f"{hk.canonical} is a reserved system shortcut."
    return None


def validate_pair(hold_spec: str, free_spec: str) -> str | None:
    """Validate both Hotkeys and that they differ. Returns error or None."""
    try:
        hold = parse(hold_spec)
        free = parse(free_spec)
    except ValueError as e:
        return str(e)
    for hk in (hold, free):
        err = validate_one(hk)
        if err:
            return err
    if hold.canonical == free.canonical:
        return "Hold-to-Talk and Hands-Free can't be the same combo."
    return None


# Named non-Win fallback for Hands-Free when a Win combo is swallowed by the shell.
FREE_FALLBACK = "ctrl+alt+space"


def uses_win(spec: str) -> bool:
    try:
        return "win" in parse(spec).mods
    except ValueError:
        return False
