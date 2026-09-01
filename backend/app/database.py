from collections.abc import Generator
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import Request
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def ensure_schema(engine, database_url: str) -> None:
    """Bring a local database to the current migration head."""
    if engine.dialect.name != "sqlite":
        return
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def create_database(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)

    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def configure_sqlite_connection(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA busy_timeout = 5000")
            cursor.close()

    Base.metadata.create_all(engine)
    ensure_schema(engine, database_url)
    if engine.dialect.name == "sqlite":
        columns = {column["name"] for column in inspect(engine).get_columns("resume_projects")}
        if "analysis_id" not in columns:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "ALTER TABLE resume_projects ADD COLUMN analysis_id VARCHAR(36)"
                )
        question_columns = {
            column["name"] for column in inspect(engine).get_columns("interview_questions")
        }
        if "rubric_json" not in question_columns:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "ALTER TABLE interview_questions ADD COLUMN rubric_json TEXT DEFAULT '{}'"
                )
        assessment_columns = {
            column["name"] for column in inspect(engine).get_columns("assessment_runs")
        }
        if "batch_id" not in assessment_columns:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "ALTER TABLE assessment_runs ADD COLUMN batch_id VARCHAR(36)"
                )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, factory


def get_db(request: Request) -> Generator[Session, None, None]:
    db: Session = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()
