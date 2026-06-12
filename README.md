# home-services

Personal always-on macOS services, managed as one repo and launched together in tmux.

## Services

| Service | Directory | Description |
|---------|-----------|-------------|
| `dictation-router` | `dictation/` | Local Whisper dictation with global hotkeys |
| `moviewatch` | `moviewatch/` | Watches `~/Documents` for `.mov` files and converts short videos to `.webm` |
| `ai-helper` | `ai-helper/` | Experimental configurable AI helper; in progress and not part of the default services |

## Roadmap

- `ai-helper` is in progress and not ready for daily use. It supports local,
  HTTP, and user-owned Python provider backends, but remains opt-in and is not
  installed, started, or checked by the default service workflow.
- Before enabling `ai-helper` as a supported service, verify the chosen backend
  can run without destabilizing `dictation-router`.

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

It creates `dictation/.venv` and installs the supported dictation app in
editable mode. `moviewatch` runs from its shell script.

The AI helper is experimental and is skipped by the default installer. Install
the larger local AI runtime dependencies only when intentionally working on that
roadmap item:

```bash
./install.sh --ai-helper-local
```

That installs Torch, Transformers, Hugging Face tooling, and microphone/audio
packages. It does **not** download a local model itself. To download a local
runtime model into the Hugging Face cache for experimentation, set the model id
explicitly:

```bash
HOME_SERVICES_AI_HELPER_MODEL=org/model-name ./install.sh --download-ai-model
```

This can download many gigabytes. The installer requires 30 GB free in the
Hugging Face cache location before it starts the download. Override that cache
with `HF_HOME=/path/with/space` if needed.

If Hugging Face requires authentication or license acceptance, log in first:

```bash
~/bin/home-services/ai-helper/.venv/bin/hf auth login
```

Some corporate networks block Hugging Face's Xet/CAS bridge for large files.
The installer disables the local Xet client for AI model downloads, but some
Xet-backed Hugging Face repos can still redirect large files through that path.
If that path is blocked, use a smaller model, download from a non-corporate
network, or request a web filtering exception. To retry the download manually
with Xet disabled:

```bash
HF_HUB_DISABLE_XET=1 ~/bin/home-services/ai-helper/.venv/bin/python -c \
  'from huggingface_hub import snapshot_download; print(snapshot_download("org/model-name"))'
```

After downloading and extracting a local model, install it into HomeServices'
standard model location. Use the extracted directory that contains the required
runtime files, including `config.json`, `tokenizer.json`, and
`model.safetensors`:

```bash
~/bin/home-services/bin/ai-helper install-model /path/to/local-model
```

That copies the model to:

```text
~/Library/Application Support/HomeServices/ai-helper/models/local-model
```

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
~/bin/home-services/bin/home-services status   # show service status, including degraded panes
~/bin/home-services/bin/home-services stop     # stop services
~/bin/home-services/bin/home-services kill     # force-kill a wedged tmux session
~/bin/home-services/bin/home-services restart  # restart the tmux session
~/bin/home-services/bin/home-services attach   # start if needed, then attach
~/bin/home-services/bin/home-services doctor   # check dependencies
~/bin/home-services/bin/home-services logs     # print log/job paths
~/bin/home-services/bin/home-services install-startup
~/bin/home-services/bin/home-services uninstall-startup
~/bin/home-services/bin/home-services install-desktop-shortcut
```

The tmux layout is:

```text
dictation-router
moviewatch2.sh
```

`ai-helper` is intentionally not in the tmux layout because some backends can be
heavy, remote, or token-backed. Detach without stopping services with `Ctrl+b`, then
`d`.

If the tmux session is still present but one pane has disappeared,
`home-services status` reports `status=degraded`, and `home-services start`
recreates missing service panes without killing the whole session.

## Reliability And Recovery

Dictation stores each stopped recording as a durable job under:

```text
~/Library/Application Support/DictationRouter/jobs/<job_id>/
```

Each job keeps:

```text
audio.wav
job.json
stdout.log
stderr.log
memory_pressure.txt
transcript.partial.txt
transcript.final.txt
status.txt
```

The reliability goals are:

- No stopped dictation audio is lost if transcription crashes.
- Every transcription failure keeps the exit code, stdout, stderr, command, model, and audio path.
- On app startup, unfinished recorded/transcribing/transcribed/retryable jobs are recovered.
- Recovered insert/clean jobs remember their original routing mode but reopen in review mode instead of typing into whatever app is focused at restart time.
- Failed transcriptions retry once with the same model, then optionally with the smaller fallback model.
- If retry fails, the error is logged and the recording remains available in the job folder.
- Slow recording starts write a `slow_start_json=...` diagnostic entry with timing spans for lock wait, job creation, audio startup, state writes, and beep requests.
- Insert/clean mode falls back to review mode when macOS confidently reports that the current focus is not text-input-capable or the focus changed after recording stopped.

## Shell Alias

Add this to your shell startup file if `~/bin/home-services/bin` is not already on `PATH`:

```bash
export PATH="$HOME/bin/home-services/bin:$PATH"
alias hs='home-services'
alias hsa='home-services -a'
alias hsr='home-services -r'
```

If your shell setup auto-sources local files, put those aliases in the appropriate local shell file.

## Startup Task And Desktop Launcher

Install a macOS LaunchAgent so the detached tmux services start when you log in:

```bash
~/bin/home-services/bin/home-services install-startup
```

Remove it with:

```bash
~/bin/home-services/bin/home-services uninstall-startup
```

Create a double-clickable Desktop launcher that opens and attaches to the tmux session:

```bash
~/bin/home-services/bin/home-services install-desktop-shortcut
```

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
- Opening dictation config, HomeServices logs, DictationRouter logs, and job folders
- Opening a diagnostics window with status, startup task state, paths, and doctor output
- Running `home-services doctor`
- Installing or removing the login startup task
- Creating the Desktop launcher

The app defaults to `~/bin/home-services`. If the repo lives somewhere else, launch it with `HOME_SERVICES_ROOT` set to the repo path.

## Configuration

Dictation settings live in `dictation/config.yaml`.

Useful defaults:

```yaml
transcription:
  model: medium.en
  whisper_cli: whisper-cli
  whisper_models_dir: ~/.cache/whisper-cpp
  threads: 4
  processors: 1
  metal: true
  max_audio_minutes: 10
  retry_count: 1
  retry_with_smaller_model: true
  fallback_model: small.en

hotkeys:
  insert: "cmd+alt+ctrl+d"
  review: "cmd+alt+ctrl+r"
  clean: "cmd+alt+ctrl+c"
  slow_start_threshold_seconds: 1.0

routing:
  fallback_to_review_when_not_insertable: true
  fallback_to_review_on_focus_change: true

audio:
  prewarm_on_startup: true
```

### Experimental AI Helper

`ai-helper` is a roadmap item, not a supported service yet. These notes are for
future development and local experiments only.

AI helper settings are environment variables. The local backend default model
path is the HomeServices app-support model directory:

```bash
export AI_HELPER_BACKEND=local
export AI_HELPER_LOCAL_MODEL="$HOME/Library/Application Support/HomeServices/ai-helper/models/local-model"
export AI_HELPER_MAX_OUTPUT_TOKENS=512
export AI_HELPER_WHISPER_MODEL=medium.en
```

For an HTTP backend, provide the real API URL, token, headers, body template,
and response path through environment variables or user-owned local files:

```bash
export AI_HELPER_BACKEND=http
export AI_HELPER_API_URL="https://example.invalid/v1/chat"
export AI_HELPER_API_TOKEN_FILE="$HOME/.ssh/example-ai-token.txt"
export AI_HELPER_API_HEADERS_JSON='{"Authorization":"Bearer ${AI_TOKEN}"}'
export AI_HELPER_API_BODY_TEMPLATE='{"prompt": ${AI_PROMPT_JSON}}'
export AI_HELPER_API_RESPONSE_PATH="response"
```

Experimental voice mode uses the same `whisper-cli` runtime and default model
path as the dictation service:

```bash
ai-helper --voice
```

Press Enter to start recording, press Enter again to stop, then the transcript is
sent to the configured backend and the response is printed to stdout.

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
