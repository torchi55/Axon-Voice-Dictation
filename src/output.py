"""Output (PLAN step 6).

Paste-first: set the clipboard to the Transcript, then send Ctrl+V via pynput.
Paste handles Unicode / newlines / symbols where per-character synthetic typing
misfires. A type-fallback covers apps that block paste. Either way the Transcript
is LEFT on the clipboard (per CONTEXT) — prior clipboard contents are intentionally
not restored; the clipboard is the safety net.
"""
import time

import pyperclip
from pynput.keyboard import Controller, Key

_kbd = Controller()


def _paste() -> None:
    _kbd.press(Key.ctrl)
    _kbd.press("v")
    _kbd.release("v")
    _kbd.release(Key.ctrl)


def output_text(text: str, type_fallback: bool = False) -> bool:
    """Insert `text` at the cursor and leave it on the clipboard.

    Returns True on apparent success. `type_fallback=True` types the text
    character-by-character instead of pasting (for apps that block Ctrl+V).
    """
    if not text:
        return False

    # Always leave the Transcript on the clipboard (the safety net).
    try:
        pyperclip.copy(text)
    except Exception as e:
        print(f"[Axon] Clipboard copy failed: {e}")

    # Let the previously-focused window re-acquire focus before we inject keys.
    time.sleep(0.12)

    if type_fallback:
        try:
            _kbd.type(text)
            return True
        except Exception as e:
            print(f"[Axon] Type-fallback failed: {e}")
            return False

    try:
        _paste()
        return True
    except Exception as e:
        print(f"[Axon] Paste failed ({e}); trying type-fallback")
        try:
            _kbd.type(text)
            return True
        except Exception as e2:
            print(f"[Axon] Type-fallback also failed: {e2}")
            return False
