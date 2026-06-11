#!/usr/bin/env bash
# Bootstrap home-services on macOS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DICTATION_DIR="$ROOT/dictation"
MODEL_NAME="${HOME_SERVICES_WHISPER_MODEL:-medium.en}"
MODEL_FILE="ggml-${MODEL_NAME}.bin"
MODELS_DIR="${HOME_SERVICES_WHISPER_MODELS_DIR:-$HOME/.cache/whisper-cpp}"
MODEL_URL="${HOME_SERVICES_WHISPER_MODEL_URL:-https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$MODEL_FILE}"
DOWNLOAD_MODEL=0

usage() {
  cat <<EOF
Usage:
  ./install.sh                  Install Homebrew packages and Python app
  ./install.sh --download-model  Also download $MODEL_FILE

Environment:
  HOME_SERVICES_WHISPER_MODEL       Whisper model name (default: medium.en)
  HOME_SERVICES_WHISPER_MODELS_DIR  Model directory (default: ~/.cache/whisper-cpp)
  HOME_SERVICES_WHISPER_MODEL_URL   Override model download URL
EOF
}

while (($#)); do
  case "$1" in
    --download-model) DOWNLOAD_MODEL=1 ;;
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

cd "$DICTATION_DIR"
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"

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
EOF
