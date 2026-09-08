import pytest

from app.database import create_database
from app.interview_flow import create_foundation_session
from app.interview_types import interview_type_from_mode
from app.models import InterviewSession


@pytest.fixture
def db(tmp_path):
    engine, factory = create_database(f"sqlite:///{tmp_path / 'foundation.db'}")
    with factory() as session:
        yield session
    engine.dispose()


def test_interview_type_maps_execution_modes():
    assert interview_type_from_mode("classic") == "foundation"
    assert interview_type_from_mode("graph") == "project"
    assert interview_type_from_mode("dialog") == "project"


def test_foundation_session_does_not_require_resume(db):
    result = create_foundation_session(db)
    session = db.get(InterviewSession, result["session_id"])

    assert result["interview_type"] == "foundation"
    assert session is not None
    assert session.resume_project_id is None
    assert session.mode == "classic"
    assert session.session_kind == "foundation"
    assert session.profile_id is not None
    assert len(result["questions"]) == 5


def test_foundation_api_exposes_interview_type(client):
    created = client.post("/api/sessions/foundation")

    assert created.status_code == 200
    body = created.json()
    assert body["interview_type"] == "foundation"
    assert len(body["questions"]) == 5

    view = client.get(f"/api/sessions/{body['session_id']}")
    assert view.status_code == 200
    assert view.json()["interview_type"] == "foundation"

    history = client.get("/api/interviews/history")
    assert history.status_code == 200
    item = next(entry for entry in history.json() if entry["session_id"] == body["session_id"])
    assert item["interview_type"] == "foundation"

    report = client.get(f"/api/sessions/{body['session_id']}/report")
    assert report.status_code == 200
    assert report.json()["interview_type"] == "foundation"
