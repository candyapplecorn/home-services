from __future__ import annotations

import importlib.util
import inspect
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import Settings
from .model import ModelRunner


class AiProvider(Protocol):
    def generate(self, prompt: str) -> str:
        pass


@dataclass(frozen=True)
class ProviderContext:
    system_prompt: str
    max_output_tokens: int
    api_url: str
    api_token: str
    api_model: str
    api_headers: dict[str, str]
    api_body_template: str
    api_response_path: str
    api_timeout_seconds: float


class ProviderConfigError(RuntimeError):
    pass


class ProviderRequestError(RuntimeError):
    pass


_PLACEHOLDER_PATTERN = re.compile(r"\$\{AI_[A-Z0-9_]+\}")


def redact_secret(text: str, *secrets: str) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted


def build_provider(settings: Settings) -> AiProvider:
    if settings.backend == "local":
        return ModelRunner(settings)
    if settings.backend == "http":
        return HttpProvider(settings)
    if settings.backend == "python":
        return PythonProvider(settings)
    raise ProviderConfigError("Unsupported AI helper backend")


def provider_context(settings: Settings) -> ProviderContext:
    return ProviderContext(
        system_prompt=settings.system_prompt,
        max_output_tokens=settings.max_output_tokens,
        api_url=settings.api_url,
        api_token=settings.api_token,
        api_model=settings.api_model,
        api_headers=settings.api_headers or {},
        api_body_template=settings.api_body_template,
        api_response_path=settings.api_response_path,
        api_timeout_seconds=settings.api_timeout_seconds,
    )


def is_loopback_host(hostname: str | None) -> bool:
    return hostname in {"localhost", "127.0.0.1", "::1"}


def validate_api_url(url: str) -> urllib.parse.ParseResult:
    if not url:
        raise ProviderConfigError("AI_HELPER_API_URL is required for the http backend")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderConfigError("AI_HELPER_API_URL must be an absolute http or https URL")
    if parsed.scheme != "https" and not is_loopback_host(parsed.hostname):
        raise ProviderConfigError("AI_HELPER_API_URL must use https unless it targets loopback")
    return parsed


def render_template(template: str, settings: Settings, prompt: str = "") -> str:
    replacements = {
        "${AI_PROMPT_JSON}": json.dumps(prompt, ensure_ascii=False),
        "${AI_SYSTEM_PROMPT_JSON}": json.dumps(settings.system_prompt, ensure_ascii=False),
        "${AI_MAX_OUTPUT_TOKENS_JSON}": json.dumps(settings.max_output_tokens),
        "${AI_MODEL_JSON}": json.dumps(settings.api_model, ensure_ascii=False),
        "${AI_TOKEN_JSON}": json.dumps(settings.api_token, ensure_ascii=False),
        "${AI_MODEL}": settings.api_model,
        "${AI_TOKEN}": settings.api_token,
    }
    unknown: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        placeholder = match.group(0)
        if placeholder not in replacements:
            unknown.add(placeholder)
            return placeholder
        return replacements[placeholder]

    rendered = _PLACEHOLDER_PATTERN.sub(replace, template)
    if unknown:
        raise ProviderConfigError(f"Unknown AI helper placeholder(s): {', '.join(sorted(unknown))}")
    return rendered


def render_headers(settings: Settings) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    for key, value in (settings.api_headers or {}).items():
        headers[key] = render_template(value, settings)
    return headers


def render_body(settings: Settings, prompt: str) -> bytes:
    if not settings.api_body_template:
        raise ProviderConfigError("AI_HELPER_API_BODY_TEMPLATE is required for the http backend")
    rendered = render_template(settings.api_body_template, settings, prompt=prompt)
    try:
        parsed = json.loads(rendered)
    except json.JSONDecodeError as error:
        raise ProviderConfigError("AI_HELPER_API_BODY_TEMPLATE must render valid JSON") from error
    return json.dumps(parsed, ensure_ascii=False).encode("utf-8")


def extract_response(payload: Any, path: str) -> str:
    current = payload
    if path:
        for part in path.split("."):
            if isinstance(current, list):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError) as error:
                    raise ProviderRequestError("AI provider response did not match configured path") from error
            elif isinstance(current, dict):
                if part not in current:
                    raise ProviderRequestError("AI provider response did not match configured path")
                current = current[part]
            else:
                raise ProviderRequestError("AI provider response did not match configured path")

    if isinstance(current, str):
        return current.strip()
    if current is None:
        return ""
    return json.dumps(current, ensure_ascii=False)


class HttpProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        validate_api_url(settings.api_url)

    def generate(self, prompt: str) -> str:
        request = urllib.request.Request(
            self.settings.api_url,
            data=render_body(self.settings, prompt),
            headers=render_headers(self.settings),
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.settings.api_timeout_seconds,
            ) as response:
                body = response.read(self.settings.api_max_response_bytes + 1)
        except urllib.error.HTTPError as error:
            raise ProviderRequestError(
                f"AI provider request failed with HTTP {error.code}"
            ) from error
        except urllib.error.URLError as error:
            raise ProviderRequestError("AI provider request failed with a network error") from error

        if len(body) > self.settings.api_max_response_bytes:
            raise ProviderRequestError("AI provider response exceeded configured size limit")

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderRequestError("AI provider response was not valid JSON") from error

        return extract_response(payload, self.settings.api_response_path)


class PythonProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.provider_function:
            raise ProviderConfigError(
                "AI_HELPER_PROVIDER_FUNCTION is required for the python backend"
            )
        self.settings = settings
        self.function = self._load_function(settings.provider_function)

    def generate(self, prompt: str) -> str:
        context = provider_context(self.settings)
        signature = inspect.signature(self.function)
        if "context" in signature.parameters:
            result = self.function(prompt, context=context)
        elif len(signature.parameters) >= 2:
            result = self.function(prompt, context)
        else:
            result = self.function(prompt)
        if not isinstance(result, str):
            raise ProviderRequestError("Python AI provider must return a string")
        return result.strip()

    @staticmethod
    def _load_function(locator: str):
        path_value, separator, function_name = locator.partition(":")
        function_name = function_name if separator else "complete"
        path = Path(path_value).expanduser()
        if not path.is_file():
            raise ProviderConfigError(f"AI provider function file not found: {path}")

        spec = importlib.util.spec_from_file_location("ai_helper_user_provider", path)
        if spec is None or spec.loader is None:
            raise ProviderConfigError(f"Could not load AI provider function file: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = getattr(module, function_name, None)
        if not callable(function):
            raise ProviderConfigError(
                f"AI provider function {function_name!r} was not found in {path}"
            )
        return function
