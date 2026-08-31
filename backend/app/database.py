from collections.abc import Generator

from fastapi import Request
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def create_database(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
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
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, factory


def get_db(request: Request) -> Generator[Session, None, None]:
    db: Session = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()
