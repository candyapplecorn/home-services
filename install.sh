#!/usr/bin/env bash
# Bootstrap home-services on macOS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DICTATION_DIR="$ROOT/dictation"
AI_HELPER_DIR="$ROOT/ai-helper"
MODEL_NAME="${HOME_SERVICES_WHISPER_MODEL:-medium.en}"
MODEL_FILE="ggml-${MODEL_NAME}.bin"
MODELS_DIR="${HOME_SERVICES_WHISPER_MODELS_DIR:-$HOME/.cache/whisper-cpp}"
MODEL_URL="${HOME_SERVICES_WHISPER_MODEL_URL:-https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$MODEL_FILE}"
DOWNLOAD_MODEL=0
INSTALL_AI_HELPER_LOCAL=0
DOWNLOAD_AI_MODEL=0
AI_HELPER_MODEL="${HOME_SERVICES_AI_HELPER_MODEL:-google/gemma-4-E4B-it}"
AI_HELPER_MIN_FREE_MB="${HOME_SERVICES_AI_HELPER_MIN_FREE_MB:-30000}"
HF_HOME_DIR="${HF_HOME:-$HOME/.cache/huggingface}"
AI_HELPER_DEFAULT_MODEL_DIR="$HOME/Library/Application Support/HomeServices/ai-helper/models/gemma-4-e4b-it"

usage() {
  cat <<EOF
Usage:
  ./install.sh                  Install Homebrew packages and Python apps
  ./install.sh --download-model  Also download $MODEL_FILE
  ./install.sh --ai-helper-local Install experimental Gemma + voice Python dependencies
  ./install.sh --download-ai-model
                                Install experimental AI deps and download $AI_HELPER_MODEL

Environment:
  HOME_SERVICES_WHISPER_MODEL       Whisper model name (default: medium.en)
  HOME_SERVICES_WHISPER_MODELS_DIR  Model directory (default: ~/.cache/whisper-cpp)
  HOME_SERVICES_WHISPER_MODEL_URL   Override model download URL
  HOME_SERVICES_AI_HELPER_MODEL     Hugging Face model id (default: google/gemma-4-E4B-it)
  HOME_SERVICES_AI_HELPER_MIN_FREE_MB
                                      Minimum free MB for AI model download (default: 30000)
  HF_HOME                            Hugging Face cache dir (default: ~/.cache/huggingface)
EOF
}

while (($#)); do
  case "$1" in
    --download-model) DOWNLOAD_MODEL=1 ;;
    --ai-helper-local) INSTALL_AI_HELPER_LOCAL=1 ;;
    --download-ai-model) INSTALL_AI_HELPER_LOCAL=1; DOWNLOAD_AI_MODEL=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "install.sh: unknown option $1" >&2; exit 1 ;;
  esac
  shift
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "install.sh: this bootstrap script is intended for macOS" >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  cat >&2 <<'EOF'
install.sh: Homebrew is required.
Install it from https://brew.sh/, then rerun this script.
EOF
  exit 1
fi

brew install python@3.12 tmux ffmpeg whisper-cpp

PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

ensure_venv() {
  local app_dir="$1"
  local venv_dir="$app_dir/.venv"
  local expected_version actual_version

  expected_version="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ -x "$venv_dir/bin/python" ]]; then
    actual_version="$("$venv_dir/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    if [[ "$actual_version" != "$expected_version" ]]; then
      echo "install.sh: recreating $venv_dir (Python $actual_version -> $expected_version)"
      "$PYTHON_BIN" -m venv --clear "$venv_dir"
      return
    fi
  fi

  "$PYTHON_BIN" -m venv "$venv_dir"
}

check_ai_model_disk_space() {
  mkdir -p "$HF_HOME_DIR"
  local free_mb
  free_mb="$(df -Pm "$HF_HOME_DIR" | awk 'NR==2 {print $4}')"
  if [[ -z "$free_mb" ]]; then
    echo "install.sh: could not determine free disk space for $HF_HOME_DIR" >&2
    exit 1
  fi
  if (( free_mb < AI_HELPER_MIN_FREE_MB )); then
    cat >&2 <<EOF
install.sh: not enough free disk space for AI model download.
Cache path: $HF_HOME_DIR
Free: ${free_mb} MB
Required: ${AI_HELPER_MIN_FREE_MB} MB

Free space or choose a smaller model, for example:
  HOME_SERVICES_AI_HELPER_MODEL=google/gemma-4-E2B-it ./install.sh --download-ai-model
EOF
    exit 1
  fi
}

cd "$DICTATION_DIR"
ensure_venv "$DICTATION_DIR"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"

if (( INSTALL_AI_HELPER_LOCAL )); then
  cd "$AI_HELPER_DIR"
  ensure_venv "$AI_HELPER_DIR"
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e ".[local,voice,dev]"
fi

if (( DOWNLOAD_AI_MODEL )); then
  cd "$AI_HELPER_DIR"
  check_ai_model_disk_space
  echo "install.sh: downloading experimental AI model $AI_HELPER_MODEL to the Hugging Face cache"
  HF_HUB_DISABLE_XET=1 HOME_SERVICES_AI_HELPER_MODEL="$AI_HELPER_MODEL" .venv/bin/python - <<'PY'
import os

from huggingface_hub import snapshot_download

model = os.environ["HOME_SERVICES_AI_HELPER_MODEL"]
path = snapshot_download(repo_id=model)
print(f"install.sh: AI model cached at {path}")
PY
else
  cat <<EOF
install.sh: skipped experimental AI helper setup.
The AI helper is in progress and is not part of the default services yet.
To try it later, run:
  ./install.sh --ai-helper-local

Expected model id:
  $AI_HELPER_MODEL

Default local model path:
  $AI_HELPER_DEFAULT_MODEL_DIR
EOF
fi

mkdir -p "$MODELS_DIR"
if [[ -f "$MODELS_DIR/$MODEL_FILE" ]]; then
  echo "install.sh: model already exists: $MODELS_DIR/$MODEL_FILE"
elif (( DOWNLOAD_MODEL )); then
  echo "install.sh: downloading $MODEL_FILE to $MODELS_DIR"
  curl -L --fail --continue-at - -o "$MODELS_DIR/$MODEL_FILE" "$MODEL_URL"
else
  cat <<EOF
install.sh: skipped model download.
To download the default model later, run:
  ./install.sh --download-model

Expected model path:
  $MODELS_DIR/$MODEL_FILE
EOF
fi

cat <<EOF
install.sh: installed home-services.

Next steps:
  1. Grant Microphone and Accessibility permissions to your terminal app.
  2. Start services with: $ROOT/bin/home-services -a
  3. Dictation and moviewatch are the supported services.
EOF
