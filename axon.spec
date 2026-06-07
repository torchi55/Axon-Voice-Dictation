# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Axon Voice (CPU-first public build).

One-folder build (fast startup, no temp extraction of the ~150 MB of native
libs). Collects the native deps that PyInstaller's static analysis can't see:
faster-whisper's bundled Silero VAD onnx, the ctranslate2 / onnxruntime DLLs,
and PortAudio (sounddevice). torch is excluded — this project never imports it.
"""
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in (
    "faster_whisper",   # bundles the Silero VAD onnx under assets/
    "ctranslate2",      # inference backend + its DLLs
    "onnxruntime",      # VAD runtime + DLLs
    "sounddevice",      # PortAudio DLL
    "huggingface_hub",  # first-run model download
    "tokenizers",
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# App assets — REQUIRED at runtime now: assets/fonts/Satoshi-*.otf are loaded by
# fonts.py at startup (it falls back to Segoe UI if missing, but we ship them so
# the brand typeface is guaranteed). assets/ also carries the logo SVG.
datas += [("assets", "assets")]

hiddenimports += [
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "pynvml",            # lazy import in transcriber (GPU detect); never runs on CPU
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["torch", "tkinter", "matplotlib", "scipy", "pandas", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AxonVoice",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                 # GUI app — no console window
    disable_windowed_traceback=False,
    icon="build-dist/axon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AxonVoice",
)
