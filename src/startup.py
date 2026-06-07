"""Login startup (PLAN step 10).

Registers Axon Voice under HKCU\\...\\CurrentVersion\\Run with a properly quoted
executable path so it launches at login. Toggleable, with clean removal and
error reporting. HKCU (not HKLM) so no admin rights are needed.
"""
import sys
from pathlib import Path

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "AxonVoice"


def _launch_command() -> str:
    """Quoted command that relaunches this app, frozen exe or dev script."""
    if getattr(sys, "frozen", False):  # PyInstaller bundle
        return f'"{sys.executable}"'
    # Dev: use pythonw (no console) to run main.py
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else exe
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{runner}" "{main_py}"'


def is_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable() -> tuple[bool, str]:
    """Register for login startup. Returns (ok, message)."""
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
        return True, "Will start with Windows."
    except OSError as e:
        return False, f"Could not enable startup: {e}"


def disable() -> tuple[bool, str]:
    """Remove the login-startup entry. Returns (ok, message)."""
    import winreg
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
        return True, "Won't start with Windows."
    except FileNotFoundError:
        return True, "Won't start with Windows."
    except OSError as e:
        return False, f"Could not disable startup: {e}"
