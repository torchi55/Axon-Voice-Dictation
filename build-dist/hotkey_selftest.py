"""Hotkey listener self-test — drives the REAL HotkeyManager and injects a
synthetic Ctrl+Space to confirm hold_start/hold_end fire. Run under the build
venv (faithful stand-in for the packaged pure-python hotkey path).

  .venv-build\\Scripts\\python.exe build-dist\\hotkey_selftest.py
"""
import ctypes
import sys
import threading
import time
from types import SimpleNamespace

# make src importable
ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication

from src.hotkeys import HotkeyManager

events = []

def log(name):
    events.append((name, time.time()))
    print(f"  >> SIGNAL {name}", flush=True)

# --- synthetic key injection (Win32 keybd_event) --------------------------- #
KEYEVENTF_KEYUP = 0x02
VK_CTRL, VK_SPACE = 0x11, 0x20
def kdown(vk): ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
def kup(vk):   ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)

def inject_ctrl_space(hold_s=0.4):
    time.sleep(0.8)  # let listener spin up
    print("[test] injecting Ctrl+Space DOWN", flush=True)
    kdown(VK_CTRL); time.sleep(0.03); kdown(VK_SPACE)
    time.sleep(hold_s)
    print("[test] injecting Ctrl+Space UP", flush=True)
    kup(VK_SPACE); time.sleep(0.03); kup(VK_CTRL)

def main():
    app = QApplication(sys.argv)
    cfg = SimpleNamespace(hold_hotkey="ctrl+space", free_hotkey="ctrl+alt+space")
    hk = HotkeyManager(cfg)
    hk.hold_start.connect(lambda: log("hold_start"), Qt.ConnectionType.DirectConnection)
    hk.hold_end.connect(lambda: log("hold_end"), Qt.ConnectionType.DirectConnection)
    hk.free_toggle.connect(lambda: log("free_toggle"), Qt.ConnectionType.DirectConnection)
    print(f"[test] frozen={getattr(sys,'frozen',False)} platform={sys.platform}", flush=True)
    hk.start()

    threading.Thread(target=inject_ctrl_space, daemon=True).start()
    QTimer.singleShot(2500, app.quit)
    app.exec()

    names = [n for n, _ in events]
    ok = "hold_start" in names and "hold_end" in names
    print(f"\n[test] signals fired: {names}", flush=True)
    print(f"[test] RESULT: {'PASS — Ctrl+Space works' if ok else 'FAIL — Ctrl+Space did NOT register'}", flush=True)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
