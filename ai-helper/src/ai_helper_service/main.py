from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import replace

from .client import ServiceUnavailable, healthcheck, query_service
from .config import load_settings
from .provider import build_provider
from .server import serve


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-helper",
        description="Ask the configured AI helper backend a question.",
    )
    parser.add_argument(
        "prompt",
        nargs=argparse.REMAINDER,
        help="Prompt text. Reserved commands: serve, doctor. If omitted, stdin is used.",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Deprecated: direct mode is now the default.",
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help="Call an already-running ai-helper serve process.",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Record a voice prompt, transcribe it with whisper-cli, then ask the configured backend.",
    )
    parser.add_argument(
        "--max-new-tokens",
        "--max-output-tokens",
        dest="max_output_tokens",
        type=int,
        help="Override AI_HELPER_MAX_OUTPUT_TOKENS for this invocation.",
    )

    return parser


def _prompt_from_args(parts: list[str]) -> str:
    if parts:
        return " ".join(parts).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return ""


def _doctor() -> int:
    settings = load_settings()
    print(f"backend={settings.backend}")
    print(f"endpoint=http://{settings.host}:{settings.port}")
    print(f"service={'running' if healthcheck(settings) else 'stopped'}")
    print(f"server_token_configured={'yes' if settings.server_token else 'no'}")

    if settings.backend == "local":
        print(f"local_model={settings.local_model}")
    elif settings.backend == "http":
        print(f"api_url_configured={'yes' if settings.api_url else 'no'}")
        print(f"api_token_configured={'yes' if settings.api_token else 'no'}")
        print(f"api_model_configured={'yes' if settings.api_model else 'no'}")
        print(f"api_headers_configured={'yes' if settings.api_headers else 'no'}")
        print(f"api_body_template_configured={'yes' if settings.api_body_template else 'no'}")
        print(f"api_response_path={settings.api_response_path}")
    elif settings.backend == "python":
        print(f"provider_function_configured={'yes' if settings.provider_function else 'no'}")

    missing = []
    if settings.backend == "local":
        for module in ("torch", "transformers", "accelerate"):
            if importlib.util.find_spec(module) is None:
                missing.append(module)

    missing_voice = []
    for module in ("numpy", "sounddevice", "soundfile"):
        if importlib.util.find_spec(module) is None:
            missing_voice.append(module)

    if missing:
        print(f"missing_model_runtime={','.join(missing)}")
        print('install_model_runtime=cd ~/bin/home-services/ai-helper && .venv/bin/python -m pip install -e ".[local,voice,dev]"')
    elif settings.backend == "local":
        print("model_runtime=installed")

    if missing_voice:
        print(f"missing_voice_runtime={','.join(missing_voice)}")
    else:
        print("voice_runtime=installed")

    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    settings = load_settings()
    if args.max_output_tokens:
        settings = replace(settings, max_output_tokens=args.max_output_tokens)

    command = args.prompt[0] if args.prompt else None
    if command == "serve" and len(args.prompt) == 1:
        serve(settings)
        return 0

    if command == "doctor" and len(args.prompt) == 1:
        return _doctor()

    if args.voice:
        from .voice import prompt_from_voice

        prompt = prompt_from_voice(settings)
    else:
        prompt = _prompt_from_args(args.prompt)
    if not prompt:
        parser.error("prompt is required unless using serve or doctor")

    try:
        if args.server:
            response = query_service(prompt, settings)
        else:
            response = build_provider(settings).generate(prompt)
    except ServiceUnavailable as error:
        print(str(error), file=sys.stderr)
        print("Start it with: ai-helper serve", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"ai-helper: {error}", file=sys.stderr)
        return 1

    print(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
