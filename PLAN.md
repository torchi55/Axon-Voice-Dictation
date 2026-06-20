# Plan: Axon Voice — History Edit, Filler Expansion, Model Trim
_Locked via grill-with-docs — by Claude + Theo. Terms per CONTEXT.md._

## Goal
Add three incremental improvements to the existing Axon Voice app: inline editing of History card Transcripts, an expanded Filler Cleanup word list, and a trimmed model picker (tiny/small/large-v3 only). Prompt Mode is deferred entirely.

## Approach
1. **Editable History cards** — Replace the static `QLabel` body in `_make_card` with `_EditableBody`: a custom widget that shows a label by default, switches to `QPlainTextEdit` on click, and commits (updates the entry dict + persists `history.json`) on focus loss.
2. **Expanded Filler Cleanup** — Add conservative new patterns to `processing.py`: `you know what I mean` (global), `does that make sense` (sentence-ender), `so yeah` (sentence-ender), `I mean` (clause-starter interjection), `right` (sentence-ender after comma).
3. **Model picker trim** — Change `self._model_choices` in `SettingsTab` to `["auto", "tiny", "small", "large-v3"]`. `MODEL_ORDER` in `transcriber.py` is unchanged (used for CPU clamping logic).
4. **Desktop launcher** — Create `AXON-NEW.bat` on the desktop pointing to the PyQt6 app.

## Key decisions & tradeoffs
- Prompt Mode deferred: local LLMs on this machine were too slow; Ollama dependency deemed too heavy for this sprint.
- base + medium deleted from HuggingFace cache (done): saves 1.64 GB, picker matches what's on disk.
- Edit saves on `focusOut`, not on an explicit Save button — matches "click off to save" UX the user described.
- Filler patterns stay conservative (sentence-position-gated) — avoids stripping legitimate uses of "I mean" mid-phrase.

## Out of scope
- Prompt Mode (deferred to future session)
- Dev `--dev` flag (user will kill + relaunch manually)
- Mac port
