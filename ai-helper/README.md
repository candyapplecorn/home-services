# ai-helper

Experimental local command line helper backed by a Gemma-compatible Hugging
Face model.

This service is in progress and is not ready for daily use. The current
Transformers/Gemma path can consume enough memory on an M-series MacBook to
interfere with dictation, so it is opt-in only and is not part of the default
`home-services` startup, installer, or doctor checks.

## Usage

Ask a question:

```bash
ai-helper "how do I use ripgrep to find a string?"
```

The CLI loads the model for that invocation, prints the response to stdout, and
then exits so Gemma does not stay resident in memory.

Voice prompt mode:

```bash
ai-helper --voice
```

Press Enter once to start recording, then Enter again to stop. The recording is
transcribed with `whisper-cli`, and the transcript is sent to Gemma.

Experimental keep-warm service mode:

```bash
ai-helper serve
ai-helper --server "how do I use ripgrep to find a string?"
```

Use this only when you intentionally want the model to remain loaded between
queries.

## Model Runtime

Install the optional local model dependencies when you are ready to run a model:

```bash
cd ~/bin/home-services/ai-helper
.venv/bin/python -m pip install -e ".[local,voice,dev]"
```

That installs the runtime libraries but not Gemma weights. From the repo root,
download the default model with:

```bash
./install.sh --download-ai-model
```

The default model is `google/gemma-4-E4B-it`, and it includes a 16 GB
`model.safetensors` file. The repo installer requires 30 GB free in the Hugging
Face cache location before it starts the download. Override that cache with
`HF_HOME=/path/with/space` if needed.

If Hugging Face requires authentication or license acceptance, run:

```bash
~/bin/home-services/ai-helper/.venv/bin/hf auth login
```

If the network blocks `cas-bridge.xethub.hf.co`, disable Xet for the download:

```bash
HF_HUB_DISABLE_XET=1 ~/bin/home-services/ai-helper/.venv/bin/python -c \
  'from huggingface_hub import snapshot_download; print(snapshot_download("google/gemma-4-E4B-it"))'
```

Some Xet-backed Hugging Face repos can still redirect large files through that
domain even when the local Xet client is disabled. If that happens, use a
smaller model, download from a non-corporate network, or request a web filtering
exception.

Kaggle is a known fallback when the Hugging Face Xet/CAS path is blocked:

```text
https://www.kaggle.com/models/google/gemma-4/transformers/gemma-4-e4b-it
```

After downloading and extracting the Kaggle model, install it into HomeServices'
standard model location. Use the extracted directory that contains `config.json`,
`tokenizer.json`, and `model.safetensors`:

```bash
~/bin/home-services/bin/ai-helper install-model /path/to/gemma-4-e4b-it
~/bin/home-services/bin/ai-helper "Give me a one-line ripgrep example"
```

That copies the model to:

```text
~/Library/Application Support/HomeServices/ai-helper/models/gemma-4-e4b-it
```

If you have Kaggle credentials configured locally, `ai-helper` can also resolve
the Kaggle model handle directly:

```bash
export AI_HELPER_MODEL="kaggle://google/gemma-4/transformers/gemma-4-e4b-it"
ai-helper "Give me a one-line ripgrep example"
```

Defaults:

```text
AI_HELPER_MODEL=google/gemma-4-E4B-it
AI_HELPER_HOST=127.0.0.1
AI_HELPER_PORT=8765
AI_HELPER_MAX_NEW_TOKENS=512
AI_HELPER_WHISPER_MODEL=medium.en
AI_HELPER_WHISPER_CLI=whisper-cli
AI_HELPER_WHISPER_MODELS_DIR=~/.cache/whisper-cpp
```

Use a local Hugging Face model directory instead of downloading by model id:

```bash
AI_HELPER_MODEL=/path/to/gemma-4-E4B-it ai-helper serve
```

Run a dependency/config check:

```bash
ai-helper doctor
```
