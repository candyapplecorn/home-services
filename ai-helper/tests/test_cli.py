import json
import urllib.error
from dataclasses import replace

import pytest

from ai_helper_service.config import DEFAULT_LOCAL_MODEL_DIR, Settings, load_settings
from ai_helper_service.client import query_service
from ai_helper_service.model import ModelRunner, resolve_model_path
from ai_helper_service.provider import (
    HttpProvider,
    ProviderConfigError,
    ProviderRequestError,
    PythonProvider,
    build_provider,
    extract_response,
    provider_context,
    redact_secret,
    render_body,
    render_headers,
    validate_api_url,
)
from ai_helper_service.server import serve


AI_ENV_KEYS = (
    "AI_HELPER_BACKEND",
    "AI_HELPER_LOCAL_MODEL",
    "AI_HELPER_MODEL",
    "AI_HELPER_HOST",
    "AI_HELPER_PORT",
    "AI_HELPER_MAX_OUTPUT_TOKENS",
    "AI_HELPER_MAX_NEW_TOKENS",
    "AI_HELPER_ENABLE_THINKING",
    "AI_HELPER_SYSTEM_PROMPT",
    "AI_HELPER_API_URL",
    "AI_HELPER_API_TOKEN",
    "AI_HELPER_API_TOKEN_FILE",
    "AI_TOKEN",
    "AI_HELPER_API_MODEL",
    "AI_HELPER_API_HEADERS_JSON",
    "AI_HELPER_API_BODY_TEMPLATE",
    "AI_HELPER_API_RESPONSE_PATH",
    "AI_HELPER_API_TIMEOUT_SECONDS",
    "AI_HELPER_API_MAX_RESPONSE_BYTES",
    "AI_HELPER_PROVIDER_FUNCTION",
    "AI_HELPER_SERVER_TOKEN",
)


@pytest.fixture(autouse=True)
def clean_ai_env(monkeypatch: pytest.MonkeyPatch):
    for key in AI_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_load_settings_defaults():
    settings = load_settings()

    assert settings == Settings()
    assert settings.backend == "local"
    assert settings.local_model == str(DEFAULT_LOCAL_MODEL_DIR)


def test_load_settings_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path):
    token_file = tmp_path / "token.txt"
    token_file.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setenv("AI_HELPER_BACKEND", "http")
    monkeypatch.setenv("AI_HELPER_LOCAL_MODEL", "/models/local")
    monkeypatch.setenv("AI_HELPER_HOST", "localhost")
    monkeypatch.setenv("AI_HELPER_PORT", "9999")
    monkeypatch.setenv("AI_HELPER_MAX_OUTPUT_TOKENS", "42")
    monkeypatch.setenv("AI_HELPER_ENABLE_THINKING", "true")
    monkeypatch.setenv("AI_HELPER_SYSTEM_PROMPT", "system")
    monkeypatch.setenv("AI_HELPER_API_URL", "https://example.invalid/v1")
    monkeypatch.setenv("AI_HELPER_API_TOKEN", "env-token")
    monkeypatch.setenv("AI_HELPER_API_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("AI_HELPER_API_MODEL", "runtime-model")
    monkeypatch.setenv("AI_HELPER_API_HEADERS_JSON", '{"Authorization":"Bearer ${AI_TOKEN}"}')
    monkeypatch.setenv("AI_HELPER_API_BODY_TEMPLATE", '{"prompt": ${AI_PROMPT_JSON}}')
    monkeypatch.setenv("AI_HELPER_API_RESPONSE_PATH", "choices.0.text")
    monkeypatch.setenv("AI_HELPER_API_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("AI_HELPER_API_MAX_RESPONSE_BYTES", "12345")
    monkeypatch.setenv("AI_HELPER_PROVIDER_FUNCTION", "/tmp/provider.py:complete")
    monkeypatch.setenv("AI_HELPER_SERVER_TOKEN", "server-token")

    settings = load_settings()

    assert settings.backend == "http"
    assert settings.local_model == "/models/local"
    assert settings.host == "localhost"
    assert settings.port == 9999
    assert settings.max_output_tokens == 42
    assert settings.enable_thinking is True
    assert settings.system_prompt == "system"
    assert settings.api_url == "https://example.invalid/v1"
    assert settings.api_token == "file-token"
    assert settings.api_model == "runtime-model"
    assert settings.api_headers == {"Authorization": "Bearer ${AI_TOKEN}"}
    assert settings.api_body_template == '{"prompt": ${AI_PROMPT_JSON}}'
    assert settings.api_response_path == "choices.0.text"
    assert settings.api_timeout_seconds == 12.5
    assert settings.api_max_response_bytes == 12345
    assert settings.provider_function == "/tmp/provider.py:complete"
    assert settings.server_token == "server-token"


def test_legacy_model_alias_maps_by_backend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_HELPER_MODEL", "runtime-model")

    assert load_settings().local_model == "runtime-model"

    monkeypatch.setenv("AI_HELPER_BACKEND", "http")
    settings = load_settings()

    assert settings.local_model == "runtime-model"
    assert settings.api_model == "runtime-model"


def test_invalid_environment_values_fail_closed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_HELPER_PORT", "abc")
    with pytest.raises(ValueError, match="AI_HELPER_PORT"):
        load_settings()

    monkeypatch.setenv("AI_HELPER_PORT", "9999")
    monkeypatch.setenv("AI_HELPER_API_HEADERS_JSON", "[]")
    with pytest.raises(ValueError, match="AI_HELPER_API_HEADERS_JSON"):
        load_settings()


def test_resolve_model_path_expands_existing_local_path(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()

    assert resolve_model_path(str(model_dir)) == str(model_dir)


def test_resolve_model_path_leaves_runtime_id_unchanged():
    assert resolve_model_path("org/model-name") == "org/model-name"


def test_resolve_model_path_raises_for_missing_local_path():
    missing_path = "/tmp/definitely-not-a-real-ai-helper-model"

    with pytest.raises(FileNotFoundError, match=missing_path):
        resolve_model_path(missing_path)


def test_build_provider_selects_backend(tmp_path):
    provider_file = tmp_path / "provider.py"
    provider_file.write_text("def complete(prompt):\n    return prompt.upper()\n", encoding="utf-8")

    assert isinstance(build_provider(Settings()), ModelRunner)
    assert isinstance(
        build_provider(
            Settings(
                backend="http",
                api_url="https://example.invalid/v1",
                api_body_template='{"prompt": ${AI_PROMPT_JSON}}',
            )
        ),
        HttpProvider,
    )
    assert isinstance(
        build_provider(
            Settings(backend="python", provider_function=str(provider_file))
        ),
        PythonProvider,
    )


def test_http_url_policy_requires_https_unless_loopback():
    validate_api_url("https://example.invalid/v1")
    validate_api_url("http://localhost:9999/v1")

    with pytest.raises(ProviderConfigError, match="https"):
        validate_api_url("http://example.invalid/v1")


def test_http_template_renders_json_without_prompt_placeholder_injection():
    settings = Settings(
        backend="http",
        api_url="https://example.invalid/v1",
        api_token="secret-token",
        api_model="runtime-model",
        api_headers={"Authorization": "Bearer ${AI_TOKEN}"},
        api_body_template=(
            '{"model": ${AI_MODEL_JSON}, "token": ${AI_TOKEN_JSON}, '
            '"prompt": ${AI_PROMPT_JSON}, "max": ${AI_MAX_OUTPUT_TOKENS_JSON}}'
        ),
    )

    headers = render_headers(settings)
    body = json.loads(render_body(settings, "literal ${AI_TOKEN}").decode("utf-8"))

    assert headers["Authorization"] == "Bearer secret-token"
    assert body == {
        "model": "runtime-model",
        "token": "secret-token",
        "prompt": "literal ${AI_TOKEN}",
        "max": 512,
    }


def test_http_template_rejects_unknown_placeholder():
    settings = Settings(
        backend="http",
        api_url="https://example.invalid/v1",
        api_body_template='{"prompt": ${AI_UNKNOWN_JSON}}',
    )

    with pytest.raises(ProviderConfigError, match="AI_UNKNOWN_JSON"):
        render_body(settings, "hello")


def test_extract_response_path():
    payload = {"choices": [{"message": {"content": " hello "}}]}

    assert extract_response(payload, "choices.0.message.content") == "hello"

    with pytest.raises(ProviderRequestError):
        extract_response(payload, "choices.1.message.content")


def test_http_provider_builds_request_and_extracts_response(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def read(self, _limit):
            return b'{"answer": "ok"}'

    def fake_urlopen(request, timeout):  # noqa: ANN001
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("ai_helper_service.provider.urllib.request.urlopen", fake_urlopen)
    provider = HttpProvider(
        Settings(
            backend="http",
            api_url="https://example.invalid/v1",
            api_headers={"Authorization": "Bearer ${AI_TOKEN}"},
            api_token="secret-token",
            api_body_template='{"prompt": ${AI_PROMPT_JSON}}',
            api_response_path="answer",
            api_timeout_seconds=3,
        )
    )

    assert provider.generate("hello") == "ok"
    assert captured["url"] == "https://example.invalid/v1"
    assert captured["timeout"] == 3
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["body"] == {"prompt": "hello"}


def test_http_provider_uses_generic_error_for_network_failures(monkeypatch: pytest.MonkeyPatch):
    def fake_urlopen(_request, timeout):  # noqa: ANN001, ARG001
        raise urllib.error.URLError("secret-token and full provider details")

    monkeypatch.setattr("ai_helper_service.provider.urllib.request.urlopen", fake_urlopen)
    provider = HttpProvider(
        Settings(
            backend="http",
            api_url="https://example.invalid/v1",
            api_token="secret-token",
            api_body_template='{"prompt": ${AI_PROMPT_JSON}}',
        )
    )

    with pytest.raises(ProviderRequestError) as error:
        provider.generate("hello")

    assert "secret-token" not in str(error.value)
    assert "network error" in str(error.value)


def test_python_provider_calls_user_function_with_context(tmp_path):
    provider_file = tmp_path / "provider.py"
    provider_file.write_text(
        "def complete(prompt, *, context):\n"
        "    return f'{context.api_model}:{context.max_output_tokens}:{prompt}'\n",
        encoding="utf-8",
    )

    provider = PythonProvider(
        Settings(
            backend="python",
            provider_function=f"{provider_file}:complete",
            api_model="runtime-model",
            max_output_tokens=17,
        )
    )

    assert provider.generate("hello") == "runtime-model:17:hello"


def test_python_provider_requires_string_result(tmp_path):
    provider_file = tmp_path / "provider.py"
    provider_file.write_text("def complete(prompt):\n    return {'text': prompt}\n", encoding="utf-8")

    provider = PythonProvider(Settings(backend="python", provider_function=str(provider_file)))

    with pytest.raises(ProviderRequestError, match="return a string"):
        provider.generate("hello")


def test_provider_context_exposes_generic_runtime_values():
    context = provider_context(
        Settings(
            api_url="https://example.invalid/v1",
            api_token="secret-token",
            api_model="runtime-model",
            api_headers={"Authorization": "Bearer ${AI_TOKEN}"},
            api_body_template='{"prompt": ${AI_PROMPT_JSON}}',
            api_response_path="answer",
            api_timeout_seconds=4,
        )
    )

    assert context.api_url == "https://example.invalid/v1"
    assert context.api_token == "secret-token"
    assert context.api_model == "runtime-model"
    assert context.api_response_path == "answer"
    assert context.api_timeout_seconds == 4


def test_redact_secret():
    assert redact_secret("token=secret-token", "secret-token") == "token=[redacted]"


def test_settings_replace_preserves_backend_fields():
    settings = Settings(
        backend="http",
        api_url="https://example.invalid/v1",
        api_token="secret-token",
        api_model="runtime-model",
    )

    updated = replace(settings, max_output_tokens=99)

    assert updated.backend == "http"
    assert updated.api_url == "https://example.invalid/v1"
    assert updated.api_token == "secret-token"
    assert updated.api_model == "runtime-model"
    assert updated.max_output_tokens == 99


def test_client_sends_local_server_token(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def read(self):
            return b'{"response": "ok"}'

    def fake_urlopen(request, timeout):  # noqa: ANN001
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("ai_helper_service.client.urllib.request.urlopen", fake_urlopen)

    response = query_service("hello", Settings(server_token="local-token"), timeout=3)

    assert response == "ok"
    assert captured["headers"]["X-ai-helper-token"] == "local-token"
    assert captured["timeout"] == 3
    assert captured["body"] == {"prompt": "hello"}


def test_serve_requires_token_for_non_loopback_non_local_backend():
    with pytest.raises(RuntimeError, match="AI_HELPER_SERVER_TOKEN"):
        serve(
            Settings(
                backend="http",
                host="0.0.0.0",
                api_url="https://example.invalid/v1",
                api_body_template='{"prompt": ${AI_PROMPT_JSON}}',
            )
        )
