# Local Interview History and Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the local SQLite application persist every interview, batch AI analysis, report version, long-term skill state, and role-based learning recommendation without overwriting historical data.

**Architecture:** Keep the current FastAPI + SQLAlchemy + SQLite stack and extend its existing models. Treat completed interviews, answers, assessment attempts, reports, and profile snapshots as append-only records. Add durable operation jobs and events for batch assessment progress, then update the profile only after a valid assessment has been committed.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy 2, SQLite, Alembic, Pydantic 2, pytest, httpx.

## Global Constraints

- The implementation is for the local single-user flow and uses `local-user`.
- SQLite remains the runtime database at `data/app.db`; do not add authentication or PostgreSQL in this phase.
- The original PDF/DOCX files remain in `data/uploads/`; API keys remain environment variables.
- Historical interview, answer, assessment, report, and profile records must not be overwritten or hard-deleted.
- Batch scoring remains deferred until all answers are submitted and must preserve the existing single-batch-call behavior.
- The blind scorer must not receive historical profile data or previous scores.
- Existing uncommitted frontend changes are unrelated and must not be staged or modified by this plan.
- Do not push or sync any change to GitHub.

---

### Task 1: Add durable database settings and migration support

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_local_history_profile.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/config.py`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_database.py`

**Interfaces:**
- `create_database(database_url: str)` continues to return `(engine, session_factory)`.
- Add `configure_sqlite_connection(dbapi_connection, connection_record)` in `backend/app/database.py` to enable foreign keys, WAL, and a 5-second busy timeout for SQLite connections.
- Add `ensure_schema(engine, database_url)` in `backend/app/database.py` to run the Alembic head after model metadata has been created; the migration must be safe for both a new database and the existing `data/app.db`.

- [ ] **Step 1: Write the failing database settings tests**

```python
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
```

- [ ] **Step 2: Run the focused tests and verify the expected RED failure**

Run: `python -m pytest backend/tests/test_database.py -q`

Expected: FAIL because the new settings and tables do not exist yet.

- [ ] **Step 3: Add Alembic and SQLite connection configuration**

Add `alembic` to `backend/requirements.txt`. Register a SQLAlchemy `connect` listener for SQLite and set:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
```

Keep `Base.metadata.create_all(engine)` for empty test databases, then run the migration head so an existing database receives missing columns and tables. The migration must inspect existing tables before adding columns and use nullable fields for new current-report/profile pointers.

- [ ] **Step 4: Add the initial local-history/profile migration**

Create the new tables and add these nullable columns to `interview_sessions`: `profile_id`, `current_assessment_run_id`, `current_report_id`, `updated_at`, and `archived_at`. Add required indexes and unique constraints. The migration must not delete or rename existing data.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run: `python -m pytest backend/tests/test_database.py -q`

Expected: PASS with zero failures.

- [ ] **Step 6: Run the existing backend suite**

Run: `python -m pytest backend/tests -q`

Expected: the existing suite remains green before model/service integration begins.

### Task 2: Persist operation jobs, SSE events, reports, and evidence spans

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/services.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_history_persistence.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Add SQLAlchemy models `OperationJob`, `OperationJobEvent`, `EvidenceSpan`, and `InterviewReport`.
- Add `persist_interview_report(db: Session, session_id: str, assessment_run_id: str | None) -> InterviewReport`.
- Add `list_interview_history(db: Session) -> list[dict]`.
- Add `get_persisted_report(db: Session, session_id: str) -> dict | None`.
- Add endpoint `GET /api/interviews/history`.

- [ ] **Step 1: Write failing persistence tests**

```python
def test_each_completed_interview_has_its_own_persisted_report(ai_client):
    first_session_id, first_questions = create_test_session(ai_client)
    second_session_id, second_questions = create_test_session(ai_client)
    submit_all_batch_answers(ai_client, first_session_id, first_questions)
    submit_all_batch_answers(ai_client, second_session_id, second_questions)

    assert ai_client.post(f"/api/sessions/{first_session_id}/assessment").status_code == 200
    assert ai_client.post(f"/api/sessions/{second_session_id}/assessment").status_code == 200

    history = ai_client.get("/api/interviews/history")
    assert history.status_code == 200
    assert {item["session_id"] for item in history.json()} == {
        first_session_id,
        second_session_id,
    }


def test_failed_assessment_preserves_job_error_and_answers(failing_ai_client, failing_ai_session_context):
    session_id, questions = failing_ai_session_context
    submit_all_batch_answers(failing_ai_client, session_id, questions)
    response = failing_ai_client.post(f"/api/sessions/{session_id}/assessment")

    assert response.status_code == 200
    with failing_ai_client.app.state.session_factory() as db:
        job = db.scalar(select(OperationJob).where(OperationJob.session_id == session_id))
        assert job.status == "failed"
        assert job.error_code
        assert db.scalar(select(func.count(AnswerAttempt.id)).where(AnswerAttempt.session_id == session_id)) == len(questions)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest backend/tests/test_history_persistence.py -q`

Expected: FAIL because the new models, persistence service, and history endpoint do not exist.

- [ ] **Step 3: Add models and response schemas**

Store `operation_kind`, idempotency data, progress, model metadata, attempts, raw response, error details, and lease fields in `operation_jobs`. Store ordered progress messages in `operation_job_events`. Store versioned report JSON in `interview_reports` and normalized answer references in `evidence_spans`.

Add response models for history items and persisted reports while retaining the current `ReportResponse` shape so existing frontend and tests remain compatible.

- [ ] **Step 4: Integrate batch assessment persistence**

At the beginning of `assess_session`, create or reuse one `batch_assessment` operation job. Keep the current provider call count and blind input unchanged. On success, persist `AssessmentRun`, `RubricObservation`, `EvidenceSpan`, and a report in one transaction, then mark the job succeeded. On provider, parser, or system failure, mark the job failed and retain all answers and error details.

When the current valid batch already exists, return it without another model call and reuse the persisted report.

- [ ] **Step 5: Expose interview history**

Implement `GET /api/interviews/history` ordered by `created_at DESC`. Return session ID, status, target title/direction, answer completion, report status, latest assessment status, and timestamps. Add `GET /api/sessions/{session_id}/report` lookup of the persisted report, with the current calculated response as a backward-compatible fallback for sessions created before this migration.

- [ ] **Step 6: Run focused and existing tests**

Run: `python -m pytest backend/tests/test_history_persistence.py backend/tests/test_api.py -q`

Expected: PASS with zero failures, including existing batch-call and failure-retry tests.

### Task 3: Add skills, role requirements, and deterministic profile aggregation

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/app/profile_engine.py`
- Modify: `backend/app/services.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_profile_engine.py`

**Interfaces:**
- Add models `SkillCatalog`, `QuestionSkill`, `RoleSkillRequirement`, `CandidateProfile`, `CandidateKnowledgeState`, `ProfileSnapshot`, and `LearningRecommendation`.
- Add `get_or_create_candidate_profile(db: Session, user_id: str, direction: str, level: str, target_title: str) -> CandidateProfile`.
- Add `update_candidate_profile(db: Session, session_id: str) -> CandidateProfile`.
- Add `build_learning_recommendations(db: Session, profile: CandidateProfile) -> list[LearningRecommendation]`.

- [ ] **Step 1: Write failing aggregation tests**

```python
def test_profile_uses_only_valid_observations_and_keeps_history(tmp_path):
    engine, factory = create_database(f"sqlite:///{tmp_path / 'profile.db'}")
    with factory() as db:
        source_session_id = seed_profile_and_skill_observations(
            db, session_levels=[1, 3], invalid_last=True
        )
        update_candidate_profile(db, source_session_id)
        state = db.scalar(select(CandidateKnowledgeState))

        assert state.valid_sample_count == 2
        assert state.current_level == 2
        assert state.trend == "improving"
        assert db.scalar(select(func.count(ProfileSnapshot.id))) == 2


def test_recommendation_targets_skill_gap_and_role_requirement(tmp_path):
    engine, factory = create_database(f"sqlite:///{tmp_path / 'recommendations.db'}")
    with factory() as db:
        profile_id, skill_id = seed_profile_with_skill_gap(db, skill_level=1, target_level=3)
        profile = db.get(CandidateProfile, profile_id)

        recommendations = build_learning_recommendations(db, profile)

        assert recommendations[0].skill_id == skill_id
        assert recommendations[0].priority == "high"
        assert recommendations[0].status == "recommended"
```

The test module must define `seed_profile_and_skill_observations` (returning the
latest session ID) and `seed_profile_with_skill_gap` as database-only fixtures that insert the
corresponding users, profiles, skills, role requirements, sessions, and valid
or invalid assessment rows; these helpers are test setup, not production APIs.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest backend/tests/test_profile_engine.py -q`

Expected: FAIL because the profile models and aggregation functions do not exist.

- [ ] **Step 3: Add skill catalog and mapping models**

Seed the local catalog with the current Agent interview knowledge points and map each generated question to a canonical skill. Preserve the existing `knowledge_point_id` field for compatibility; use `question_skills` for normalized aggregation.

- [ ] **Step 4: Implement deterministic aggregation**

For each completed session, include only `submitted` and `explicit_unknown` answers with valid assessment observations. Calculate a per-session skill level from rubric levels using question-skill weights and confidence. Aggregate the latest five valid sessions with recency weights, store sample count and confidence, and classify trend as `improving`, `stable`, or `declining` using the difference between recent and earlier valid averages.

Create a new `profile_snapshot` after every successful profile update. Do not let an invalid assessment alter the current skill state.

- [ ] **Step 5: Generate structured recommendations**

Compare `current_level` with `role_skill_requirements.target_level`. Set priority to `high` when the gap is at least one level and the skill is important or has a serious error; otherwise use `medium`, `low`, or `insufficient_data`. Save a concrete reason, action list, success criteria, and status `recommended`.

- [ ] **Step 6: Run focused tests**

Run: `python -m pytest backend/tests/test_profile_engine.py -q`

Expected: PASS with zero failures.

### Task 4: Update assessment completion to update the profile transactionally

**Files:**
- Modify: `backend/app/services.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_profile_api.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Add `GET /api/profiles/{profile_id}/summary` returning current skills, trend, sample count, and recommendations.
- Add `GET /api/profiles/{profile_id}/history` returning profile snapshots ordered newest first.
- Add `PATCH /api/recommendations/{recommendation_id}` for `in_progress`, `completed`, or `dismissed`.

- [ ] **Step 1: Write failing API tests**

```python
def test_valid_batch_updates_profile_and_recommendations(ai_client, ai_session_context):
    session_id, questions = ai_session_context
    submit_all_batch_answers(ai_client, session_id, questions)

    assessment = ai_client.post(f"/api/sessions/{session_id}/assessment")
    assert assessment.status_code == 200

    with ai_client.app.state.session_factory() as db:
        profile_id = db.get(InterviewSession, session_id).profile_id
    response = ai_client.get(f"/api/profiles/{profile_id}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["profile_id"] == profile_id
    assert body["skills"]
    assert "recommendations" in body


def test_failed_batch_does_not_update_profile(failing_ai_client, failing_ai_session_context):
    session_id, questions = failing_ai_session_context
    submit_all_batch_answers(failing_ai_client, session_id, questions)
    failing_ai_client.post(f"/api/sessions/{session_id}/assessment")

    with failing_ai_client.app.state.session_factory() as db:
        profile_id = db.get(InterviewSession, session_id).profile_id
    body = failing_ai_client.get(f"/api/profiles/{profile_id}/summary").json()
    assert body["last_session_id"] is None
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest backend/tests/test_profile_api.py -q`

Expected: FAIL because the profile endpoints and transactional update are not implemented.

- [ ] **Step 3: Link sessions to role profiles**

When `create_session` creates a new interview, resolve or create the profile from the target direction, level, and title, and save `InterviewSession.profile_id`. Do not create a new profile for every interview in the same direction.

- [ ] **Step 4: Update the profile only after valid assessment commit**

After batch persistence succeeds, call `update_candidate_profile`. If the assessment is pending, invalid, rejected, or failed, keep the profile unchanged. The profile update transaction creates or updates skill states, creates a snapshot, writes recommendations, and updates the profile current snapshot pointer.

- [ ] **Step 5: Add profile endpoints and recommendation status updates**

Return plain Chinese labels and structured data suitable for the existing frontend. Recommendation status updates must be scoped to the local user and reject unsupported statuses with HTTP 422.

- [ ] **Step 6: Run focused and existing tests**

Run: `python -m pytest backend/tests/test_profile_api.py backend/tests/test_api.py -q`

Expected: PASS with zero failures.

### Task 5: Add local backup, migration documentation, and full verification

**Files:**
- Modify: `backend/app/database.py`
- Modify: `backend/app/main.py`
- Create: `backend/app/backup.py`
- Modify: `README.md`
- Test: `backend/tests/test_backup.py`
- Test: `backend/tests/test_migrations.py`

**Interfaces:**
- Add `backup_database(database_path: Path, backup_root: Path) -> Path`.
- Add `GET /health` response field `database` with `connected` or `unavailable`.

- [ ] **Step 1: Write failing backup and migration tests**

```python
def test_backup_creates_timestamped_copy_without_changing_source(tmp_path):
    source = tmp_path / "app.db"
    source.write_bytes(b"sqlite-test")

    backup = backup_database(source, tmp_path / "backups")

    assert backup.exists()
    assert backup.read_bytes() == source.read_bytes()
    assert backup.parent.name == "backups"


def test_existing_database_can_be_upgraded_without_losing_rows(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine, factory = create_database(database_url)
    with factory() as db:
        db.add(User(id="local-user"))
        db.commit()

    upgraded_engine, upgraded_factory = create_database(database_url)
    with upgraded_factory() as db:
        assert db.get(User, "local-user") is not None
        assert inspect(upgraded_engine).has_table("operation_jobs")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest backend/tests/test_backup.py backend/tests/test_migrations.py -q`

Expected: FAIL because backup and migration verification are not yet implemented.

- [ ] **Step 3: Implement backup and health reporting**

Copy the SQLite file to `data/backups/app-YYYYMMDD-HHMMSS.db` using a temporary sibling file and replace it only after the copy completes. Do not delete old backups. Keep health checks read-only and do not expose the API key or database path.

- [ ] **Step 4: Document local operation**

Document database location, backup location, migration command, history/profile endpoints, and the fact that no command in this task pushes to GitHub.

- [ ] **Step 5: Run the complete verification suite**

Run:

```powershell
python -m pytest backend/tests -q
```

Expected: PASS with zero failures.

Then run the existing frontend checks without staging frontend files:

```powershell
Set-Location frontend
npm test -- --runInBand
npm run build
```

Expected: both commands exit with code 0.

- [ ] **Step 6: Inspect the final diff and local status**

Run:

```powershell
git diff --check
git status --short
git diff --stat
```

Confirm that only the intended backend, migration, documentation, and backend-test files are part of the implementation diff. Do not stage or push frontend changes unless explicitly requested.
