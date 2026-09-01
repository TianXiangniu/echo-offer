from sqlalchemy import inspect

from app.database import create_database


def test_sqlite_connection_enables_foreign_keys_and_wal(tmp_path):
    engine, _ = create_database(f"sqlite:///{tmp_path / 'settings.db'}")

    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"


def test_schema_upgrade_creates_operation_and_profile_tables(tmp_path):
    engine, _ = create_database(f"sqlite:///{tmp_path / 'schema.db'}")
    tables = set(inspect(engine).get_table_names())

    assert {
        "operation_jobs",
        "operation_job_events",
        "interview_reports",
        "skill_catalog",
        "candidate_profiles",
        "candidate_knowledge_states",
        "profile_snapshots",
        "learning_recommendations",
    }.issubset(tables)
