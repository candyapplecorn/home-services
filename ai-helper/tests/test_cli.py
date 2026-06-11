from ai_helper_service.config import DEFAULT_MODEL_DIR, Settings, load_settings
from ai_helper_service.model import resolve_model_path


def test_load_settings_defaults(monkeypatch):
    for key in (
        "AI_HELPER_MODEL",
        "AI_HELPER_HOST",
        "AI_HELPER_PORT",
        "AI_HELPER_MAX_NEW_TOKENS",
        "AI_HELPER_ENABLE_THINKING",
    ):
        monkeypatch.delenv(key, raising=False)

    assert load_settings() == Settings()
    assert load_settings().model == str(DEFAULT_MODEL_DIR)


def test_load_settings_from_environment(monkeypatch):
    monkeypatch.setenv("AI_HELPER_MODEL", "/models/gemma")
    monkeypatch.setenv("AI_HELPER_HOST", "localhost")
    monkeypatch.setenv("AI_HELPER_PORT", "9999")
    monkeypatch.setenv("AI_HELPER_MAX_NEW_TOKENS", "42")
    monkeypatch.setenv("AI_HELPER_ENABLE_THINKING", "true")

    assert load_settings() == Settings(
        model="/models/gemma",
        host="localhost",
        port=9999,
        max_new_tokens=42,
        enable_thinking=True,
        whisper_model="medium.en",
        whisper_cli="whisper-cli",
        whisper_models_dir="~/.cache/whisper-cpp",
    )


def test_resolve_model_path_expands_existing_local_path(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()

    assert resolve_model_path(str(model_dir)) == str(model_dir)


def test_resolve_model_path_leaves_hugging_face_id_unchanged():
    assert resolve_model_path("google/gemma-4-E4B-it") == "google/gemma-4-E4B-it"


def test_resolve_model_path_raises_for_missing_local_path():
    missing_path = "/tmp/definitely-not-a-real-ai-helper-model"

    try:
        resolve_model_path(missing_path)
    except FileNotFoundError as error:
        assert missing_path in str(error)
    else:
        raise AssertionError("expected FileNotFoundError")
