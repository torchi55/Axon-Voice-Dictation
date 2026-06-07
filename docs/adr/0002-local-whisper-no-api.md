# ADR 0002 — Local faster-whisper, no cloud API

**Status:** Accepted  
**Date:** 2026-06-04 (revised 2026-06-05)

## Context

Speech-to-text can be done via cloud APIs (Gemini, OpenAI Whisper API, AssemblyAI) or a local model. Most commercial dictation apps use cloud to reduce distribution size and support lower-end hardware.

The development machine is an **RTX 4070 Laptop GPU with 8.6GB VRAM** (an earlier draft of this ADR wrongly assumed a 4090 with 24GB). This constrains the float16 model tier but quantized compute (`int8_float16`) changes the math.

## Decision

Run **faster-whisper** locally with CUDA on the user's GPU. No API key.

- **Compute type `int8_float16`** so `large-v3`'s weights occupy ~4.5GB VRAM and run on the 8.6GB 4070 — best accuracy the hardware allows, not the conservative `medium`/float16 tier.
- **Auto-Detect** reads **total** VRAM (stable; free VRAM fluctuates with other apps and is unreliable at startup) and selects the largest Model that fits with headroom under int8_float16: `large-v3` at ≥6GB total, `medium` ≥4GB, `small` ≥2GB, else `base`. The ~6GB gate leaves room above the ~4.5GB weight footprint for activations and other processes.
- **VRAM is queried via `pynvml`/NVML, not torch.** faster-whisper runs on CTranslate2, so torch would otherwise be a multi-hundred-MB dependency bundled solely for one VRAM read. Dropping it shrinks the build.
- **CPU fallback is clamped to `small`** regardless of the requested Model. `large-v3` on CPU takes minutes per Dictation and would appear hung; clamping plus a warning toast prevents that footgun for GPU-less friends.
- **Model weights are not bundled.** The resolved Model is fetched from HuggingFace on First-Run Download (pinned revision + verified hashes) with a progress UI, then cached. Bundling no weights keeps the `.exe` to the measured packaging targets in PLAN.md step 15 (≈120–250MB without bundled CUDA DLLs; ≈1–2GB+ if cuDNN/cuBLAS are shipped) rather than adding gigabytes of model data on top.

## Consequences

- Zero ongoing cost, zero rate limits, audio never leaves the machine
- `large-v3` (int8_float16) on the 4070 transcribes a short phrase in well under a cloud round-trip
- Friends on varied hardware each download only the Model their GPU resolves to — no wasted bundle weight
- First run requires internet and a short wait; offline thereafter
- A GPU-less friend gets `small` on CPU automatically — usable, not great, never hung
- Quantization (int8_float16) trades a sliver of accuracy for the VRAM headroom that makes large-v3 possible on this card
