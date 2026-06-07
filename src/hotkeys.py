"""Global hotkey engine (PLAN step 3).

Generic combo matching driven by the configured Hotkey strings (not hardcoded),
implemented with a single pynput listener (no elevated privileges, unlike the
`keyboard` package). Supports:
  - Hold-to-Talk: main key down (with exact modifiers) → start; up → end.
  - Hands-Free: main key down (with exact modifiers) → toggle.
  - Live rebinding via set_hotkeys().
  - A capture mode used by Settings to record the next combo a user presses,
    which doubles as the registration test (if pynput sees it, it's bindable).
"""
import ctypes
import sys
import threading

from pynput import keyboard as kb
from PyQt6.QtCore import QObject, pyqtSignal

from .hotkey_spec import Hotkey, parse
from .logging_setup import get_logger

# Module logger — surfaces hotkey state in axon.log even in the windowed exe
# (where print() goes to a null stdout). Critical for diagnosing the packaged
# build, whose hotkey listener cannot otherwise be observed.
_log = get_logger()

_MOD_TOKENS = {
    kb.Key.ctrl: "ctrl", kb.Key.ctrl_l: "ctrl", kb.Key.ctrl_r: "ctrl",
    kb.Key.alt: "alt", kb.Key.alt_l: "alt", kb.Key.alt_r: "alt", kb.Key.alt_gr: "alt",
    kb.Key.cmd: "win", kb.Key.cmd_l: "win", kb.Key.cmd_r: "win",
    kb.Key.shift: "shift", kb.Key.shift_l: "shift", kb.Key.shift_r: "shift",
}

# Hold-to-Talk release debounce. The OS can emit spurious release→re-press
# pairs for the hold main key while it is physically held (key auto-repeat
# artifacts, and IME hotkeys like Ctrl+Space toggling the input method). Each
# spurious release would otherwise end the hold and the next press would start
# a fresh one, fragmenting one utterance into many short Dictations (History
# spam). We defer hold_end by this window; a re-press inside it cancels the
# pending end and the hold stays continuous. A genuine release (no re-press)
# still ends promptly — this only adds ~100 ms of tail latency on release.
_HOLD_RELEASE_DEBOUNCE_S = 0.10


def _mod_of(key) -> str | None:
    return _MOD_TOKENS.get(key)


# --- Windows virtual-key mapping (for low-level event suppression) ------ #
# Maps a hotkey_spec main-key token → Win32 VK code. Covers every key the
# rebind validator allows, so suppression works for *any* combo the user picks.
_VK_NAMED = {
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "backspace": 0x08,
    "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}
_VK_FN = {f"f{i}": 0x6F + i for i in range(1, 13)}  # F1=0x70 … F12=0x7B


def _token_to_vk(token: str) -> int | None:
    if token in _VK_NAMED:
        return _VK_NAMED[token]
    if token in _VK_FN:
        return _VK_FN[token]
    if len(token) == 1:
        if token.isalpha():
            return ord(token.upper())
        if token.isdigit():
            return ord(token)
    return None


# Win32 VK codes for modifier state queried via GetAsyncKeyState.
_VK_CTRL, _VK_SHIFT, _VK_ALT = 0x11, 0x10, 0x12
_VK_LWIN, _VK_RWIN = 0x5B, 0x5C


def _key_token(key) -> str | None:
    """Normalize a pynput key event to a hotkey_spec main-key token."""
    if isinstance(key, kb.Key):
        return key.name  # 'space', 'f1', 'enter', ...
    if isinstance(key, kb.KeyCode):
        vk = key.vk
        if vk == 32:
            return "space"
        if vk is not None and 65 <= vk <= 90:   # A-Z (reliable even with Ctrl held)
            return chr(vk).lower()
        if vk is not None and 48 <= vk <= 57:   # 0-9
            return chr(vk)
        if key.char and len(key.char) == 1 and key.char.isprintable():
            return key.char.lower()
    return None


class HotkeyManager(QObject):
    hold_start = pyqtSignal()
    hold_end = pyqtSignal()
    free_toggle = pyqtSignal()
    combo_captured = pyqtSignal(str)   # canonical combo string from capture mode

    def __init__(self, config):
        super().__init__()
        self._config = config
        self._lock = threading.Lock()
        self._mods: set[str] = set()
        self._hold_active = False
        self._free_key_held = False   # guards the Hands-Free toggle vs key auto-repeat
        self._suppress = False
        self._capturing = False
        self._listener: kb.Listener | None = None
        self._release_timer: threading.Timer | None = None
        self._hold: Hotkey = parse(config.hold_hotkey)
        self._free: Hotkey = parse(config.free_hotkey)

    # ------------------------------------------------------------------ #

    def start(self) -> None:
        try:
            kwargs = dict(on_press=self._on_press, on_release=self._on_release)
            if sys.platform == "win32":
                # Low-level filter lets us swallow the bound combo system-wide
                # (no IME flicker / IntelliSense / stray space leaking to other
                # apps) while STILL receiving the press in our callbacks.
                kwargs["win32_event_filter"] = self._win32_filter
            self._listener = kb.Listener(**kwargs)
            self._listener.daemon = True
            self._listener.start()
            msg = f"Hotkeys listener started: hold={self._hold} free={self._free} (suppress={sys.platform == 'win32'})"
            print(f"[Axon] {msg}")
            _log.info(msg)
        except Exception as e:
            print(f"[Axon] ERROR: keyboard listener failed: {e}")
            _log.error("Hotkeys listener FAILED to start: %r", e)

    def stop(self) -> None:
        with self._lock:
            self._cancel_release_timer()
        if self._listener:
            self._listener.stop()

    def set_hotkeys(self, hold_spec: str, free_spec: str) -> None:
        with self._lock:
            self._hold = parse(hold_spec)
            self._free = parse(free_spec)
            self._free_key_held = False   # don't carry a held-guard across a rebind
        print(f"[Axon] Hotkeys rebound: hold={self._hold} free={self._free}")

    def suppress_during_output(self, value: bool) -> None:
        with self._lock:
            self._suppress = value

    def force_end_hold(self) -> None:
        emit = False
        with self._lock:
            self._cancel_release_timer()
            if self._hold_active:
                self._hold_active = False
                emit = True
        if emit:
            self.hold_end.emit()

    # --- capture mode (Settings rebind + registration test) ----------- #

    def begin_capture(self) -> None:
        with self._lock:
            self._capturing = True

    def cancel_capture(self) -> None:
        with self._lock:
            self._capturing = False

    # ------------------------------------------------------------------ #

    def _on_press(self, key) -> None:
        try:
            mod = _mod_of(key)
            with self._lock:
                if mod:
                    self._mods.add(mod)
                    return
                token = _key_token(key)
                if token is None:
                    return
                active = frozenset(self._mods)

                if self._capturing:
                    self._capturing = False
                    combo = Hotkey(active & {"ctrl", "alt", "win", "shift"}, token)
                    captured = combo.canonical
                    emit_capture = captured
                    action = None
                else:
                    emit_capture = None
                    if self._suppress:
                        return
                    action = self._match(active, token)

            if emit_capture is not None:
                self.combo_captured.emit(emit_capture)
            elif action == "hold":
                _log.info("hotkey fired: hold_start")
                self.hold_start.emit()
            elif action == "free":
                _log.info("hotkey fired: free_toggle")
                self.free_toggle.emit()
        except Exception as e:
            print(f"[Axon] on_press error: {e}")
            _log.error("on_press error: %r", e)

    def _match(self, active: frozenset, token: str) -> str | None:
        """Return 'hold'/'free'/None for a main-key press. Caller holds lock."""
        if token == self._hold.key and active == self._hold.mods:
            # Hold main key down. Any press of it cancels a pending debounced
            # end — this is how a spurious release→re-press flicker (auto-repeat
            # / IME) gets coalesced into one continuous hold.
            self._cancel_release_timer()
            if not self._hold_active:
                self._hold_active = True
                return "hold"
            return None  # auto-repeat or flicker re-press while already holding
        if token == self._free.key and active == self._free.mods:
            # Toggle ONCE per physical press. While the key is physically held,
            # Windows fires repeated keydown events (auto-repeat) with no
            # intervening keyup — each would otherwise re-toggle, so holding the
            # combo a beat flipped recording ON then instantly OFF ("too short,
            # skipping", Hands-Free recording nothing). Ignore repeats until the
            # key is released (reset in _on_release).
            if self._free_key_held:
                return None
            self._free_key_held = True
            return "free"
        return None

    # --- Windows system-wide suppression of the bound combo ----------- #

    def _win32_filter(self, msg, data) -> bool:
        """Low-level keyboard filter (Windows). Toggles per-event suppression.

        pynput posts our on_press/on_release BEFORE it checks the suppress flag,
        so setting it here swallows the keystroke system-wide while we still get
        the callback. We only suppress the main key of a bound hotkey while its
        modifiers are held — every other key (incl. the modifiers themselves)
        passes through untouched.
        """
        suppress = False
        try:
            if not self._capturing:
                suppress = self._should_suppress(int(data.vkCode))
        except Exception:
            suppress = False
        if self._listener is not None:
            self._listener._suppress = suppress
        return True   # always let pynput process → our callbacks still fire

    @staticmethod
    def _async_mods() -> frozenset:
        down = ctypes.windll.user32.GetAsyncKeyState
        mods = set()
        if down(_VK_CTRL) & 0x8000:
            mods.add("ctrl")
        if down(_VK_ALT) & 0x8000:
            mods.add("alt")
        if down(_VK_SHIFT) & 0x8000:
            mods.add("shift")
        if (down(_VK_LWIN) & 0x8000) or (down(_VK_RWIN) & 0x8000):
            mods.add("win")
        return frozenset(mods)

    def _should_suppress(self, vk: int) -> bool:
        with self._lock:
            specs = (self._hold, self._free)
        mods = self._async_mods()
        for hk in specs:
            mvk = _token_to_vk(hk.key)
            if mvk is not None and vk == mvk and mods == hk.mods:
                return True
        return False

    def _on_release(self, key) -> None:
        try:
            with self._lock:
                mod = _mod_of(key)
                if mod:
                    self._mods.discard(mod)
                    return
                token = _key_token(key)
                # Releasing the Hands-Free key re-arms the toggle for the next
                # press (clears the auto-repeat guard set in _match).
                if token == self._free.key:
                    self._free_key_held = False
                # End hold on release of the hold main key, regardless of
                # whether modifiers were released first. Defer the end via a
                # short debounce so a flicker re-press can cancel it.
                if self._hold_active and token == self._hold.key:
                    self._schedule_hold_end_locked()
        except Exception as e:
            print(f"[Axon] on_release error: {e}")

    # --- debounced hold end ------------------------------------------- #

    def _cancel_release_timer(self) -> None:
        """Cancel any pending debounced hold_end. Caller holds the lock."""
        if self._release_timer is not None:
            self._release_timer.cancel()
            self._release_timer = None

    def _schedule_hold_end_locked(self) -> None:
        """Arm the debounce timer that ends the active hold. Caller holds lock."""
        self._cancel_release_timer()
        timer = threading.Timer(
            _HOLD_RELEASE_DEBOUNCE_S, self._finalize_hold_end
        )
        timer.daemon = True
        self._release_timer = timer
        # Bind the timer identity so a late-firing timer that was already
        # cancelled/replaced cannot end a hold it no longer owns.
        timer.args = (timer,)
        timer.start()

    def _finalize_hold_end(self, timer: threading.Timer) -> None:
        emit = False
        with self._lock:
            if self._release_timer is timer and self._hold_active:
                self._hold_active = False
                self._release_timer = None
                emit = True
        if emit:
            self.hold_end.emit()
