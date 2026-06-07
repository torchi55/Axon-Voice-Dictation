# Axon Voice — Domain Glossary

## App

**Axon Voice** — A local-first voice dictation desktop app for Windows (Mac later). No API key required. Runs entirely on-device using a local Whisper model.

---

## Recording

**Dictation** — A single voice recording event. Begins when the user activates a Mode and ends when the user releases the hotkey (Hold-to-Talk) or re-triggers the toggle (Hands-Free). Produces exactly one Transcript.

**Hold-to-Talk Mode** — A recording Mode where the user holds `Ctrl+Space`. Recording begins on keydown, ends on keyup. Designed for short, deliberate phrases.

**Hands-Free Mode** — A recording Mode where the user presses `Ctrl+Win+Space` to start listening and the same combo to stop. Designed for longer, continuous dictation.

**Mode** — The active recording behavior. Either Hold-to-Talk or Hands-Free. Only one Mode can be active at a time.

---

## Output

**Transcript** — The text output of a Dictation after the processing pipeline runs in a fixed order: Whisper → Filler Cleanup (if enabled) → Snippet expansion. The Transcript is the final text that gets inserted at the cursor and left on the clipboard.

**Snippet** — A user-defined keyword → text mapping. Applied to the cleaned Whisper output: any occurrence of a Snippet keyword is replaced with its expansion. Snippet expansion is the last pipeline stage, so filler-stripping never mutates an expansion. Defined in the Snippets tab of the Main Window.

**Filler Cleanup** — An optional pipeline stage, default off, applied after Whisper and before Snippet expansion. Removes interjection fillers (`um`, `uh`, and `like`/`you know` only in interjection position, never inside legitimate phrases). Toggleable per-session.

**Output** — The act of inserting a Transcript into the focused application. Always does two things: (1) inserts at the cursor (paste-first, with a type fallback for apps that block paste), (2) leaves the Transcript on the clipboard so it can be re-pasted. The prior clipboard contents are not preserved.

---

## Model

**Model** — The local faster-whisper model used for transcription. Options: `tiny`, `base`, `small`, `medium`, `large-v3`. Selected manually in Settings or via Auto-Detect.

**Auto-Detect** — A startup feature that reads the GPU's **total** VRAM (a stable signal, unlike free VRAM which fluctuates with other apps) and selects the largest Model that fits with headroom, using quantized compute to maximize accuracy per gigabyte. On an NVIDIA GPU with ≥6GB total VRAM this resolves to `large-v3`. With no compatible GPU it falls back to a CPU-safe Model.

**First-Run Download** — The one-time fetch of the resolved Model's weights from HuggingFace when Axon Voice runs for the first time on a machine. Shown with a progress UI. Subsequent Sessions load the cached weights.

---

## UI

**Overlay** — A floating pill/capsule that appears at the bottom-center of the screen during a Dictation. Shows animated waveform bars and a mode label (`HOLD` or `FREE`). Disappears after Output.

**Main Window** — The home panel opened from the Tray Icon. Contains three tabs: History, Snippets, Settings. Styled with a light frosted-glass (liquid glass) aesthetic.

**Tray Icon** — The system tray entry that keeps Axon Voice running in the background. Clicking it opens the Main Window.

---

## Data

**Activity Log** — The in-session list of Transcripts shown in the History tab of the Main Window. Timestamped. Each entry has a Copy button. Cleared when the app quits (session-only).

**Session** — A single run of Axon Voice from launch to quit. The Activity Log does not persist across Sessions.

---

## Settings

**Hotkey** — A user-configurable keyboard shortcut. Two hotkeys exist: one for Hold-to-Talk Mode, one for Hands-Free Mode. Defaults: `Ctrl+Space` and `Ctrl+Win+Space`.
