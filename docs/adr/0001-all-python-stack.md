# ADR 0001 — All-Python stack (PyQt6 + faster-whisper)

**Status:** Accepted  
**Date:** 2026-06-04

## Context

A voice dictation overlay needs: (1) system-level audio capture, (2) global hotkeys, (3) clipboard + keyboard injection, (4) a floating translucent UI. Common alternatives are Electron (JS + Chromium), Tauri (Rust + web), or a native C# app.

## Decision

Use Python throughout: **PyQt6** for the UI (including the Overlay and Main Window) and **faster-whisper** for local transcription. No separate JS/Node layer.

## Consequences

- One language across the whole app; owner already knows Python
- PyQt6 supports frameless translucent windows and Win11 Acrylic blur via win32api calls — sufficient for the liquid glass aesthetic
- PyInstaller packages everything into a single `.exe`. CPU-only and CUDA-bundled builds have no external runtime dependency; a CUDA-detected build (DLLs not shipped) requires a compatible CUDA runtime already installed on the machine. See PLAN.md step 15.
- UI ceiling is lower than Electron/web (no CSS backdrop-filter), but adequate for v1
- Mac port later is a **UI repackage plus per-platform system-integration adapters** — the PyQt6 UI carries over, but global hotkeys, login-startup registration, GPU detection, tray behavior, and keyboard/clipboard injection are platform-specific seams that must be re-implemented. Not a full rewrite, not a clean repackage either.
