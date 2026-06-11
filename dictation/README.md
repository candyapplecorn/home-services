# Local Whisper Dictation Router

Local-first dictation for macOS (Apple Silicon). Press a hotkey to start recording, press again to stop, transcribe with whisper.cpp, and route text to the active app or an editor.

## Requirements

- macOS Sonoma or later
- Python 3.12+
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) built with Metal (`whisper-cli` on your `PATH`)
- A GGML model in `~/.cache/whisper-cpp/` (e.g. `ggml-medium.en.bin`)
- **Accessibility** permission for Terminal/your launcher (global hotkeys + simulated typing)
- **Microphone** permission

## Install

From the repo root, prefer:

```bash
./install.sh
```

For dictation-only development:

```bash
cd dictation
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### whisper.cpp

The repo installer can install `whisper-cpp` with Homebrew and optionally download the default model:

```bash
./install.sh --download-model
```

Manual model download:

```bash
mkdir -p ~/.cache/whisper-cpp
curl -L -o ~/.cache/whisper-cpp/ggml-medium.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin
```

## Configuration

Edit `config.yaml`:

```yaml
transcription:
  model: medium.en

hotkeys:
  insert: "hyper+d"   # Caps Lock remapped via Karabiner (recommended)
  review: "hyper+r"
  clean: "hyper+c"
```

**Hyper key** (recommended on MacBook): remap Caps Lock to Ctrl+Option+Shift+Cmd in [Karabiner-Elements](https://karabiner-elements.pqrs.org/), then use `hyper+d`, `hyper+r`, `hyper+c`.

Alternative without Karabiner:

```yaml
hotkeys:
  insert: "cmd+alt+ctrl+d"
  review: "cmd+alt+ctrl+r"
  clean: "cmd+alt+ctrl+c"
```

## Run

```bash
dictation-router
# or
python -m dictation_router.main
```

Grant Accessibility when prompted (System Settings → Privacy & Security → Accessibility).

## Modes

| Hotkey | Mode | Behavior |
|--------|------|----------|
| Hyper+D | Insert | Transcribe → type at active cursor (clipboard fallback) |
| Hyper+R | Review | Transcribe → open timestamped file in TextEdit (or WebStorm/Rider if running) |
| Hyper+C | Clean | Transcribe → local cleanup → insert at cursor |

Toggle workflow: press once to start recording, press the **same** hotkey again to stop and process.

## Audio feedback

- Start: single beep
- Stop: double beep
- Success: chime
- Error: bass tone

## Logs & transcripts

- Logs: `~/Library/Application Support/DictationRouter/logs/`
- Review transcripts: `~/Library/Application Support/DictationRouter/transcripts/`

## Tests

```bash
pytest
```
