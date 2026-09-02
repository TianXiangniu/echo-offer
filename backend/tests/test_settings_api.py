from app import main
from app.config import SILICONFLOW_API_KEY
from app.models import ModelSetting
from app.providers import RuleBasedAssessmentProvider
from app.main import create_app


def make_settings_client(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'settings-api.db'}",
        upload_root=tmp_path / "uploads",
        assessment_provider=RuleBasedAssessmentProvider(),
    )
    from fastapi.testclient import TestClient

    return TestClient(app)


def complete_update_payload(**overrides):
    payload = {
        "base_url": "https://example.test/v1",
        "model": "test-analysis-model",
        "assessment_model": "test-assessment-model",
        "api_key": "",
        "clear_api_key": False,
        "temperature": 0.7,
        "max_tokens": 4800,
        "timeout_seconds": 120,
        "assessment_batch_size": 2,
    }
    payload.update(overrides)
    return payload


def test_get_model_settings_returns_redacted_effective_configuration(tmp_path):
    client = make_settings_client(tmp_path)

    response = client.get("/api/settings/model")

    assert response.status_code == 200
    body = response.json()
    assert body["model"]
    assert body["api_key_configured"] is bool(SILICONFLOW_API_KEY)
    assert "api_key" not in body


def test_put_model_settings_persists_and_refreshes_runtime_providers(tmp_path):
    client = make_settings_client(tmp_path)

    response = client.put(
        "/api/settings/model",
        json=complete_update_payload(api_key="test-secret"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "test-analysis-model"
    assert body["assessment_model"] == "test-assessment-model"
    assert body["temperature"] == 0.7
    assert body["max_tokens"] == 4800
    assert body["timeout_seconds"] == 120
    assert body["assessment_batch_size"] == 2
    assert body["api_key_configured"] is True
    assert "test-secret" not in response.text

    assessment_provider = client.app.state.assessment_provider
    project_provider = client.app.state.project_analysis_provider
    assert assessment_provider._model == "test-assessment-model"
    assert assessment_provider._temperature == 0.7
    assert assessment_provider._max_tokens == 4800
    assert project_provider._model == "test-analysis-model"
    assert project_provider._temperature == 0.7
    assert project_provider._max_tokens == 4800

    with client.app.state.session_factory() as db:
        assert db.query(ModelSetting).count() == 1


def test_invalid_model_settings_are_rejected_without_overwriting_previous_values(tmp_path):
    client = make_settings_client(tmp_path)
    original = client.get("/api/settings/model").json()

    response = client.put(
        "/api/settings/model",
        json=complete_update_payload(max_tokens=100),
    )

    assert response.status_code == 422
    current = client.get("/api/settings/model").json()
    assert current["max_tokens"] == original["max_tokens"]


def test_empty_key_keeps_saved_key_and_explicit_clear_removes_it(tmp_path):
    client = make_settings_client(tmp_path)
    client.put(
        "/api/settings/model",
        json=complete_update_payload(api_key="test-secret"),
    )

    preserved = client.put(
        "/api/settings/model",
        json=complete_update_payload(api_key=""),
    )
    assert preserved.status_code == 200
    assert preserved.json()["api_key_configured"] is True

    cleared = client.put(
        "/api/settings/model",
        json=complete_update_payload(api_key="", clear_api_key=True),
    )
    assert cleared.status_code == 200
    assert cleared.json()["api_key_configured"] is False


def test_model_connection_test_returns_probe_metadata_without_business_records(
    tmp_path,
    monkeypatch,
):
    client = make_settings_client(tmp_path)
    client.put(
        "/api/settings/model",
        json=complete_update_payload(api_key="test-secret"),
    )
    calls = []

    def fake_probe(settings):
        calls.append(settings)
        return {
            "ok": True,
            "message": "模型连接正常",
            "model": settings.model,
            "latency_ms": 12,
            "error_code": None,
        }

    monkeypatch.setattr(main, "probe_model_connection", fake_probe)

    response = client.post("/api/settings/model/test")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["model"] == "test-analysis-model"
    assert calls and calls[0].api_key == "test-secret"
    with client.app.state.session_factory() as db:
        assert db.query(ModelSetting).count() == 1
