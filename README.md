# home-services

Personal always-on macOS services, managed as one repo and launched together in tmux.

## Services

| Service | Directory | Description |
|---------|-----------|-------------|
| `dictation-router` | `dictation/` | Local Whisper dictation with global hotkeys |
| `moviewatch` | `moviewatch/` | Watches `~/Documents` for `.mov` files and converts short videos to `.webm` |

## macOS Setup

Install Homebrew first if needed:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Then bootstrap this repo:

```bash
cd ~/bin/home-services
./install.sh
```

The installer uses Homebrew to install:

- `python@3.12`
- `tmux`
- `ffmpeg`
- `whisper-cpp`

It also creates `dictation/.venv` and installs the dictation app in editable mode.

## Whisper Model

The default dictation config expects:

```text
~/.cache/whisper-cpp/ggml-medium.en.bin
```

The model is large, so `./install.sh` does not download it unless asked:

```bash
./install.sh --download-model
```

You can choose a different model with:

```bash
HOME_SERVICES_WHISPER_MODEL=small.en ./install.sh --download-model
```

OpenAI also publishes direct `.pt` model download URLs in
[`whisper/__init__.py`](https://github.com/openai/whisper/blob/main/whisper/__init__.py#L17-L30).
To use one of those PyTorch downloads with `whisper.cpp`, follow the
[`convert-pt-to-ggml.py` conversion instructions](https://github.com/ggml-org/whisper.cpp/tree/master/models#3-convert-with-convert-pt-to-ggmlpy)
and the
[`models/convert-pt-to-ggml.py` script](https://github.com/ggml-org/whisper.cpp/blob/master/models/convert-pt-to-ggml.py)
to produce a `ggml-*.bin` file.

If you use a different model, update `dictation/config.yaml` so `transcription.model` matches the downloaded file.

## Permissions

Grant these macOS permissions to the terminal app that runs `home-services`:

- Microphone
- Accessibility

Path: System Settings -> Privacy & Security.

## Run

```bash
~/bin/home-services/bin/home-services start    # start detached
~/bin/home-services/bin/home-services status   # show service status
~/bin/home-services/bin/home-services stop     # stop services
~/bin/home-services/bin/home-services restart  # restart the tmux session
~/bin/home-services/bin/home-services attach   # start if needed, then attach
~/bin/home-services/bin/home-services doctor   # check dependencies
```

The tmux layout is:

```text
dictation-router
moviewatch2.sh
```

Detach without stopping services with `Ctrl+b`, then `d`.

## Shell Alias

Add this to your shell startup file if `~/bin/home-services/bin` is not already on `PATH`:

```bash
export PATH="$HOME/bin/home-services/bin:$PATH"
alias hs='home-services'
alias hsa='home-services -a'
alias hsr='home-services -r'
```

If your shell setup auto-sources local files, put those aliases in the appropriate local shell file.

## iTerm2 Startup

In iTerm2 -> Profiles -> General -> Command, set "Send text at start" to:

```text
home-services
```

That starts both services in a detached tmux session.

## Menu Bar App

Build the native macOS menu bar utility:

```bash
cd ~/bin/home-services
./menubar/build-app.sh
open "menubar/dist/Home Services.app"
```

The app runs without a Dock icon and adds an `HS` menu bar item with controls for:

- Start, stop, restart, and status
- Opening the tmux session in Terminal
- Opening dictation config and logs
- Running `home-services doctor`

The app defaults to `~/bin/home-services`. If the repo lives somewhere else, launch it with `HOME_SERVICES_ROOT` set to the repo path.

## Configuration

Dictation settings live in `dictation/config.yaml`.

Useful defaults:

```yaml
transcription:
  model: medium.en
  whisper_cli: whisper-cli
  whisper_models_dir: ~/.cache/whisper-cpp

hotkeys:
  insert: "cmd+alt+ctrl+d"
  review: "cmd+alt+ctrl+r"
  clean: "cmd+alt+ctrl+c"
```

## Transcription limits (why content goes missing)

There is **no hard audio duration or character cap** in our app. Whisper.cpp processes the **entire** WAV file.

Content can still disappear because whisper works in **~30 second windows**. Each window can be **silently skipped** when whisper decides there is no speech:

```
no_speech_prob > no_speech_threshold  AND  avg_logprobs < logprob_threshold
```

Default `no_speech_threshold` is **0.6**. Quiet speech, walking away from the mic, and long thinking pauses cause whole 30s chunks to be dropped. This matches "I spoke longer but got less text."

**2351 chars** ≈ ~400 words ≈ **~2.5–3 minutes** of clear continuous speech. If you spoke longer with pauses, the gap is likely skipped windows, not a hard limit.

**Tuning** in `dictation/config.yaml`:

```yaml
transcription:
  no_speech_threshold: 0.35   # lower = keep more quiet speech
  keep_recordings: true       # debug: compare WAV length vs transcript
```

Logs show recording duration, chars/min, and warn when density looks too low. For long dictation, use **Review mode** (⌃⌥⌘R).

**Not transcription limits:** `max_typing_chars` only affects insert mode (typing vs clipboard). It does not truncate whisper output.
