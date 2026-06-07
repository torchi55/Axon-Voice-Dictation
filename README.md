# Axon Voice

Local voice dictation for Windows. Hold a key, speak, release — text appears at your cursor. No cloud. No subscription. No account.

> Fully private alternative to Wispr Flow and SuperWhisper.

---

## How it works

Axon Voice runs entirely on your machine using [faster-whisper](https://github.com/guillaumekienlen/faster-whisper) (a local Whisper model). Audio never leaves your device. No API key required.

- **Hold-to-Talk** — hold `Ctrl+Space`, speak, release
- **Hands-Free** — press `Ctrl+Win+Space` to start, again to stop
- Text is inserted at your cursor and copied to clipboard
- Works in any app

## Features

- Auto-detects best Whisper model for your GPU (tiny → large-v3)
- Snippet expansion — map spoken keywords to full phrases
- Filler cleanup — strips `um`, `uh`, `like` (optional)
- 24h session history with copy buttons
- Animated overlay during recording
- System tray — stays out of your way
- Fully offline after first model download

## Install

Download the latest `.exe` from [Releases](https://github.com/torchi55/Axon-Voice-Dictation/releases).

Run it. On first launch it downloads the Whisper model weights (~75MB–1.5GB depending on your GPU). That's the only network request it ever makes.

**Requirements:** Windows 10/11. NVIDIA GPU optional but recommended for `large-v3` accuracy.

## Build from source

```bash
git clone https://github.com/torchi55/Axon-Voice-Dictation.git
cd Axon-Voice-Dictation
pip install -r requirements.txt
python main.py
```

To build the installer:

```bash
# 1. Build the exe
.venv-build\Scripts\python.exe -m PyInstaller axon.spec --noconfirm --distpath dist --workpath build

# 2. Build the installer (requires Inno Setup 6)
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build-dist\installer.iss
```

## Privacy

- Zero telemetry
- No network calls after model download
- All data (history, snippets, settings) stored locally in `%APPDATA%\AxonVoice`
- Model weights cached in `%USERPROFILE%\.cache\huggingface`

## License

MIT — see [LICENSE](LICENSE).
