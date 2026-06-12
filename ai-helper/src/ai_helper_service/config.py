from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_LOCAL_MODEL_DIR = (
    Path.home()
    / "Library/Application Support/HomeServices/ai-helper/models/local-model"
)
DEFAULT_MODEL_DIR = DEFAULT_LOCAL_MODEL_DIR


@dataclass(frozen=True)
class Settings:
    backend: str = "local"
    local_model: str = str(DEFAULT_LOCAL_MODEL_DIR)
    host: str = "127.0.0.1"
    port: int = 8765
    max_output_tokens: int = 512
    enable_thinking: bool = False
    whisper_model: str = "medium.en"
    whisper_cli: str = "whisper-cli"
    whisper_models_dir: str = "~/.cache/whisper-cpp"
    system_prompt: str = "You are a concise command line assistant."
    api_url: str = ""
    api_token: str = ""
    api_model: str = ""
    api_headers: dict[str, str] | None = None
    api_body_template: str = ""
    api_response_path: str = "response"
    api_timeout_seconds: float = 60.0
    api_max_response_bytes: int = 2_000_000
    provider_function: str = ""
    server_token: str = ""

    @property
    def model(self) -> str:
        return self.local_model

    @property
    def max_new_tokens(self) -> int:
        return self.max_output_tokens


def _read_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


def _read_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number") from None


def _read_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _read_json_object(name: str) -> dict[str, str] | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{name} must be valid JSON") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must be a JSON object")
    result: dict[str, str] = {}
    for key, value in parsed.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError(f"{name} must map strings to strings")
        result[key] = value
    return result


def _read_secret_from_file(path_value: str) -> str:
    path = Path(path_value).expanduser()
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ValueError(f"Could not read token file: {path}") from error


def _read_api_token() -> str:
    token_file = os.environ.get("AI_HELPER_API_TOKEN_FILE")
    if token_file:
        return _read_secret_from_file(token_file)
    return os.environ.get("AI_HELPER_API_TOKEN") or os.environ.get("AI_TOKEN") or ""


def load_settings() -> Settings:
    backend = os.environ.get("AI_HELPER_BACKEND", Settings.backend).strip().lower()
    if backend not in {"local", "http", "python"}:
        raise ValueError("AI_HELPER_BACKEND must be one of: local, http, python")

    local_model = (
        os.environ.get("AI_HELPER_LOCAL_MODEL")
        or os.environ.get("AI_HELPER_MODEL")
        or Settings.local_model
    )
    api_model = os.environ.get("AI_HELPER_API_MODEL") or (
        os.environ.get("AI_HELPER_MODEL") if backend != "local" else ""
    )
    if os.environ.get("AI_HELPER_MAX_OUTPUT_TOKENS"):
        max_output_tokens = _read_int(
            "AI_HELPER_MAX_OUTPUT_TOKENS", Settings.max_output_tokens
        )
    else:
        max_output_tokens = _read_int(
            "AI_HELPER_MAX_NEW_TOKENS", Settings.max_output_tokens
        )

    return Settings(
        backend=backend,
        local_model=local_model,
        host=os.environ.get("AI_HELPER_HOST", Settings.host),
        port=_read_int("AI_HELPER_PORT", Settings.port),
        max_output_tokens=max_output_tokens,
        enable_thinking=_read_bool("AI_HELPER_ENABLE_THINKING", False),
        whisper_model=os.environ.get("AI_HELPER_WHISPER_MODEL", Settings.whisper_model),
        whisper_cli=os.environ.get("AI_HELPER_WHISPER_CLI", Settings.whisper_cli),
        whisper_models_dir=os.environ.get(
            "AI_HELPER_WHISPER_MODELS_DIR", Settings.whisper_models_dir
        ),
        system_prompt=os.environ.get("AI_HELPER_SYSTEM_PROMPT", Settings.system_prompt),
        api_url=os.environ.get("AI_HELPER_API_URL", ""),
        api_token=_read_api_token(),
        api_model=api_model or "",
        api_headers=_read_json_object("AI_HELPER_API_HEADERS_JSON"),
        api_body_template=os.environ.get("AI_HELPER_API_BODY_TEMPLATE", ""),
        api_response_path=os.environ.get(
            "AI_HELPER_API_RESPONSE_PATH", Settings.api_response_path
        ),
        api_timeout_seconds=_read_float(
            "AI_HELPER_API_TIMEOUT_SECONDS", Settings.api_timeout_seconds
        ),
        api_max_response_bytes=_read_int(
            "AI_HELPER_API_MAX_RESPONSE_BYTES", Settings.api_max_response_bytes
        ),
        provider_function=os.environ.get("AI_HELPER_PROVIDER_FUNCTION", ""),
        server_token=os.environ.get("AI_HELPER_SERVER_TOKEN", ""),
    )
