import pytest

from app.config import (
    ANALYSIS_TIMEOUT_SECONDS,
    ASSESSMENT_CASE_BATCH_SIZE,
    ASSESSMENT_TIMEOUT_SECONDS,
    SILICONFLOW_API_KEY,
    SILICONFLOW_ASSESSMENT_MODEL,
    SILICONFLOW_BASE_URL,
    SILICONFLOW_MODEL,
)
from app.database import create_database
from app.model_settings import (
    ModelSettingsValues,
    load_model_settings,
    public_model_settings,
    save_model_settings,
    validate_model_settings,
)
from app.schemas import ModelSettingsUpdate


def test_load_model_settings_uses_environment_defaults_without_a_saved_row(tmp_path):
    _, session_factory = create_database(f"sqlite:///{tmp_path / 'settings.db'}")

    with session_factory() as db:
        settings = load_model_settings(db)

    assert settings.base_url == SILICONFLOW_BASE_URL
    assert settings.model == SILICONFLOW_MODEL
    assert settings.assessment_model == SILICONFLOW_ASSESSMENT_MODEL
    assert settings.timeout_seconds == max(
        ANALYSIS_TIMEOUT_SECONDS,
        ASSESSMENT_TIMEOUT_SECONDS,
    )
    assert settings.assessment_batch_size == ASSESSMENT_CASE_BATCH_SIZE
    assert settings.api_key == SILICONFLOW_API_KEY


def test_public_model_settings_never_returns_the_api_key():
    settings = ModelSettingsValues(
        base_url="https://example.test/v1",
        model="test-model",
        assessment_model="test-assessment-model",
        api_key="secret-key",
        temperature=0.7,
        max_tokens=4800,
        timeout_seconds=120,
        assessment_batch_size=2,
    )

    public = public_model_settings(settings)

    assert public["api_key_configured"] is True
    assert "api_key" not in public
    assert public["max_tokens"] == 4800


def test_update_with_empty_key_preserves_old_key_and_explicit_clear_removes_it(tmp_path):
    _, session_factory = create_database(f"sqlite:///{tmp_path / 'settings.db'}")

    with session_factory() as db:
        saved = save_model_settings(
            db,
            ModelSettingsUpdate(
                base_url="https://example.test/v1",
                model="test-model",
                assessment_model="test-assessment-model",
                api_key="secret-key",
                temperature=0.7,
                max_tokens=4800,
                timeout_seconds=120,
                assessment_batch_size=2,
            ),
        )
        db.commit()
        assert saved.api_key == "secret-key"

        preserved = save_model_settings(
            db,
            ModelSettingsUpdate(
                base_url="https://example.test/v1",
                model="test-model",
                assessment_model="test-assessment-model",
                api_key="",
                temperature=0.7,
                max_tokens=4800,
                timeout_seconds=120,
                assessment_batch_size=2,
            ),
        )
        assert preserved.api_key == "secret-key"

        cleared = save_model_settings(
            db,
            ModelSettingsUpdate(
                base_url="https://example.test/v1",
                model="test-model",
                assessment_model="test-assessment-model",
                api_key="",
                clear_api_key=True,
                temperature=0.7,
                max_tokens=4800,
                timeout_seconds=120,
                assessment_batch_size=2,
            ),
        )
        assert cleared.api_key == ""


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperature", -0.1),
        ("temperature", 2.1),
        ("max_tokens", 100),
        ("max_tokens", 8193),
        ("timeout_seconds", 9),
        ("timeout_seconds", 301),
        ("assessment_batch_size", 0),
        ("assessment_batch_size", 6),
    ],
)
def test_model_settings_reject_values_outside_supported_ranges(field, value):
    values = {
        "base_url": "https://example.test/v1",
        "model": "test-model",
        "assessment_model": "test-assessment-model",
        "api_key": "",
        "temperature": 0.1,
        "max_tokens": 2400,
        "timeout_seconds": 90,
        "assessment_batch_size": 3,
    }
    values[field] = value

    with pytest.raises(ValueError):
        validate_model_settings(ModelSettingsValues(**values))
