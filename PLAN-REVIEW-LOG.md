# Plan Review Log: Axon Voice v1
Act 1 (grill-with-docs) complete — plan locked, CONTEXT.md + ADR 0002 updated (hardware correction: RTX 4070 Laptop 8.6GB, int8_float16 large-v3, CPU clamp, first-run download). MAX_ROUNDS=5.

## Round 1 — Codex — BLOCKED (environment)
Codex CLI 0.118.0 (skill requires ≥0.130). Under ChatGPT-account auth, every attempted model ID
(gpt-5.3-codex default, gpt-5.3, gpt-5.1, gpt-5, gpt-5.1-codex, gpt-5-codex) returns
HTTP 400 "model is not supported when using Codex with a ChatGPT account." OAuth token is fresh
(last_refresh 2026-06-05), so this is not a stale login — the CLI version is too old for the
current backend's ChatGPT-auth model allowlist. No verdict produced. Act 2 cannot run until the
CLI is upgraded (or API-key auth is configured). Act 1 artifacts (PLAN.md, CONTEXT.md, ADRs) stand.

## Round 1 — Codex (thread 019e98a2-bf84-7c23-807d-b65b79a5cc6d)
VERDICT: REVISE. 16 findings. Codex reviewed the existing `src/` scaffold against the plan and found code/plan contradictions plus genuine gaps:
1. Auto-Detect uses total VRAM & ≥10GB gate, not plan's free-VRAM/≥4.5GB.
2. Code loads `float16`, plan requires `int8_float16`.
3. CPU fallback retries same model instead of clamping to `small`.
4. First-Run Download has no progress UI — implicit download behind `print()`.
5. Hotkey rebinding claimed but `window.py` defers to v1.1, `hotkeys.py` hardcodes.
6. Output: `output.py` restores original clipboard, contradicting "leave Transcript copied."
7. Plan says `pynput` but `output.py` uses `keyboard` (Windows admin risk).
8. Rapid Dictations silently drop earlier transcripts (worker disconnect, no queue).
9. Concurrent `WhisperModel.transcribe()` calls — thread-safety unproven.
10. Pipeline order: code expands Snippets before Filler Cleanup; CONTEXT ambiguous.
11. Filler Cleanup strips `like` globally — damages "I like this".
12. Snippet overlap (`api` vs `api key`) nondeterministic by JSON order.
13. Login startup planned but absent from code.
14. Mac-port claim overstated (hotkeys/startup/CUDA/tray/injection are platform-specific).
15. Observability is `print()`-only; no user-visible error paths.
16. Snippet/config JSON written without schema validation/atomicity/corruption recovery.

### Claude's response
Accepted 4, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16 and folded them into PLAN.md (new steps: 0 reconcile-scaffold, 11 serialized worker queue, 12 structured logging+toasts, 13 atomic/validated config; revised 2 first-run progress UI, 5 conservative default-off filler + length-sorted snippets, 6 clipboard semantics, 3 pynput standardization, 14 "UI portable, system integration needs per-platform adapters"). CONTEXT.md tightened: locked pipeline order (Whisper→Filler→Snippet) and clipboard-retention semantics.
PARTIAL REJECT — #1: use **total** VRAM with headroom, not *free* VRAM (free fluctuates with other apps; unreliable at startup). Adjusted thresholds (large-v3 ≥6GB, medium ≥4GB, small ≥2GB).
REJECT (scope) — #5's "remove from v1" option: hotkey rebinding stays in v1 per explicit user requirement; the scaffold must implement it end-to-end (added to step 0), not be descoped.
Findings 1/2/3/13 are largely "scaffold hasn't caught up to plan" — captured as step 0 reconciliation rather than plan flaws.

## Round 2 — Codex (resumed)
VERDICT: REVISE. 10 findings, all accepted (none rejected):
1. Doc desync — CONTEXT.md/ADR 0002 still said free VRAM/≥4.5GB while PLAN said total/≥6GB.
2. Mac-port overclaim only half-fixed — Goal + ADR 0001 still said "repackage, not a rewrite."
3. ~50MB .exe claim false for PyInstaller+PyQt6+faster-whisper+CTranslate2 (+CUDA).
4. First-Run Download has no supply-chain integrity (unpinned HF fetch by name).
5. Hands-Free unbounded buffer → memory exhaustion / unusable transcription.
6. Hotkey rebinding lacks validation (reserved/duplicate/untypeable/registration failure).
7. Auto-type underspecified for Unicode/newlines/symbols.
8. Model override too-large-for-GPU silently ignored by CPU clamp.
9. Logs in %APPDATA% could leak transcript/audio text vs the non-persistent privacy story.
10. No multi-process safety — second instance + concurrent config writes race.

### Claude's response
All 10 folded in. Doc sync: CONTEXT.md Auto-Detect + ADR 0002 now state total-VRAM/≥6GB policy and pynvml-not-torch; ADR 0001 + PLAN Goal reworded to "UI repackage plus per-platform adapters." PLAN updates: step 1 pynvml VRAM detection (drop torch), step 2 pinned HF revision + hash verification, step 4 Hands-Free max-duration auto-stop, step 3 hotkey validation (reserved/duplicate/untypeable/registration test), step 6 paste-first output (Unicode/newlines) + type fallback, step 9 model-override hardware validation+confirm, step 11 single-instance lock, step 13 transcript/audio banned from logs + redacted diagnostic mode, step 14 file-locked atomic writes, step 15 measured size ranges replacing the 50MB claim. New decision bullets: drop-torch/pynvml, paste-first, pinned-revision integrity. New risks: measured size, HF outage path.

## Round 3 — Codex (resumed)
VERDICT: REVISE. 3 findings, all doc-consistency residue from round-2 edits, all accepted:
1. ADR 0002 still said ".exe ships ~50MB" — contradicted PLAN step 15's measured ranges.
2. ADR 0001 still said "no runtime dependency" — CUDA-detected build needs an installed CUDA runtime.
3. Vocabulary mismatch — Goal/CONTEXT said "auto-typed at cursor" (implies char injection) vs PLAN step 6 paste-first.

### Claude's response
All 3 fixed. ADR 0002 Decision now references the step-15 measured targets instead of 50MB. ADR 0001 consequence qualified (CPU-only/CUDA-bundled = no external dep; CUDA-detected = needs installed runtime). Domain language changed to "inserted at the cursor" across CONTEXT.md (Transcript + Output terms) and PLAN.md Goal, with "type fallback" reserved for the fallback path.

## Round 4 — Codex (resumed)
VERDICT: APPROVED. No blocking inconsistencies across PLAN.md, CONTEXT.md, ADR 0001, ADR 0002.
One non-blocking nit: Win-fallback wording inconsistent ("provided" vs "may be needed").

### Claude's response
Applied the nit anyway: named `Ctrl+Alt+Space` as the concrete Hands-Free fallback, auto-selected when the `Ctrl+Win+Space` registration test fails. Approach step 3 and Risks now agree.

## Resolution — CONVERGED (APPROVED, round 4 of 5)
Act 1 (grill-with-docs) + Act 2 (Codex adversarial review) complete. 4 review rounds: 16 → 10 → 3 → 0 findings. Plan, glossary, and both ADRs are internally consistent and hardened. Code reconciliation (scaffold → plan) is captured as PLAN.md step 0 for implementation. No code written during either act. Awaiting user sign-off before build.
