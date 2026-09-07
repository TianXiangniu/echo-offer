from sqlalchemy import inspect, select

from app.database import create_database
from app.models import User


def test_existing_database_can_be_opened_again_without_losing_rows(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    _, factory = create_database(database_url)
    with factory() as db:
        db.add(User(id="local-user"))
        db.commit()

    upgraded_engine, upgraded_factory = create_database(database_url)
    with upgraded_factory() as db:
        assert db.scalar(select(User.id)) == "local-user"
        assert inspect(upgraded_engine).has_table("operation_jobs")
        assert inspect(upgraded_engine).has_table("assessment_batches")
        assert inspect(upgraded_engine).has_table("interview_graph_event_receipts")
        session_columns = {
            column["name"]
            for column in inspect(upgraded_engine).get_columns("interview_sessions")
        }
        assert "current_assessment_batch_id" in session_columns
        assert inspect(upgraded_engine).has_table("candidate_profiles")
