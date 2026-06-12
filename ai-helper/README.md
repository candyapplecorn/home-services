# ai-helper

Experimental command line AI helper. It supports three runtime backends:

- `local`: load a local model with the optional local runtime dependencies
- `http`: call a user-configured JSON HTTP API
- `python`: call a user-owned Python provider function

The helper is opt-in only and is not part of the default `home-services`
startup, installer, or doctor checks.

## Usage

Ask a question:

```bash
ai-helper "how do I use ripgrep to find a string?"
```

Voice prompt mode:

```bash
ai-helper --voice
```

Press Enter once to start recording, then Enter again to stop. The recording is
transcribed with `whisper-cli`, and the transcript is sent to the configured
backend.

Experimental keep-warm service mode:

```bash
ai-helper serve
ai-helper --server "how do I use ripgrep to find a string?"
```

For non-local backends, keep the service bound to loopback unless you also set
`AI_HELPER_SERVER_TOKEN`.

## Backend Selection

Defaults:

```text
AI_HELPER_BACKEND=local
AI_HELPER_LOCAL_MODEL=~/Library/Application Support/HomeServices/ai-helper/models/local-model
AI_HELPER_MAX_OUTPUT_TOKENS=512
AI_HELPER_HOST=127.0.0.1
AI_HELPER_PORT=8765
AI_HELPER_WHISPER_MODEL=medium.en
AI_HELPER_WHISPER_CLI=whisper-cli
AI_HELPER_WHISPER_MODELS_DIR=~/.cache/whisper-cpp
```

`AI_HELPER_MODEL` remains a compatibility alias. For the local backend it maps
to `AI_HELPER_LOCAL_MODEL`; for non-local backends it maps to
`AI_HELPER_API_MODEL`.

## Local Backend

Install optional local model dependencies when you intentionally want to run a
model on this machine:

```bash
cd ~/bin/home-services/ai-helper
.venv/bin/python -m pip install -e ".[local,voice,dev]"
```

Install a downloaded local model directory into HomeServices' standard location:

```bash
~/bin/home-services/bin/ai-helper install-model /path/to/local-model
```

The source directory must contain the model files required by the local runtime,
including `config.json`, `tokenizer.json`, and `model.safetensors`.

Use a different local model path:

```bash
export AI_HELPER_BACKEND=local
export AI_HELPER_LOCAL_MODEL="/path/to/local-model"
ai-helper "Give me a one-line shell example"
```

## HTTP Backend

The HTTP backend has no default provider, URL, model, headers, or payload. Put
real values in your shell environment, a local token file, or another user-owned
secret store.

```bash
export AI_HELPER_BACKEND=http
export AI_HELPER_API_URL="https://example.invalid/v1/chat"
export AI_HELPER_API_TOKEN_FILE="$HOME/.ssh/example-ai-token.txt"
export AI_HELPER_API_MODEL="example-model"
export AI_HELPER_API_HEADERS_JSON='{"Authorization":"Bearer ${AI_TOKEN}"}'
export AI_HELPER_API_BODY_TEMPLATE='{
  "model": ${AI_MODEL_JSON},
  "max_tokens": ${AI_MAX_OUTPUT_TOKENS_JSON},
  "messages": [
    {"role": "system", "content": ${AI_SYSTEM_PROMPT_JSON}},
    {"role": "user", "content": ${AI_PROMPT_JSON}}
  ]
}'
export AI_HELPER_API_RESPONSE_PATH="choices.0.message.content"
```

Supported JSON-safe placeholders:

```text
${AI_PROMPT_JSON}
${AI_SYSTEM_PROMPT_JSON}
${AI_MAX_OUTPUT_TOKENS_JSON}
${AI_MODEL_JSON}
${AI_TOKEN_JSON}
```

Header values may also use raw string placeholders:

```text
${AI_MODEL}
${AI_TOKEN}
```

The HTTP backend sends `POST` requests only, enforces `https` unless the URL is
loopback, limits response size, and does not print tokens or provider response
bodies on failure.

## Python Backend

Use the Python backend when the request shape needs custom code. The provider
file is arbitrary user-owned code; keep it outside source control or in an
ignored local file.

```bash
export AI_HELPER_BACKEND=python
export AI_HELPER_PROVIDER_FUNCTION="$HOME/.config/ai-helper/provider.py:complete"
```

Provider function:

```python
def complete(prompt: str, *, context) -> str:
    # Build any request shape here using context.api_url, context.api_token,
    # context.api_model, context.max_output_tokens, and context.system_prompt.
    return "response text"
```

## Doctor

Run a dependency/config check:

```bash
ai-helper doctor
```

Doctor reports whether secrets are configured, but it does not print token
values or API URLs.
