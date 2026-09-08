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
