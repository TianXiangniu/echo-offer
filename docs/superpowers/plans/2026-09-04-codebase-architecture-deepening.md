# Codebase Architecture Deepening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the backend workflow responsibilities visible by moving the four real flows out of `services.py` while preserving current behavior and compatibility with existing callers.

**Architecture:** Create focused `resume_intake`, `interview_flow`, `assessment_flow`, and `reporting_flow` modules. Keep `services.py` as a thin compatibility façade because current tests and local integrations import it directly; the façade must not retain business implementations. Shared exceptions and small cross-flow invariants live in `workflow_common.py`.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, pytest; no new dependencies and no database migration.

## Global Constraints

- Preserve all existing HTTP response shapes, persistence rules, retry behavior, and error codes.
- Preserve the current uncommitted user changes; only add the requested architecture files and change required imports.
- Keep `services.py` import-compatible, including `_create_batch_job`, `ASSESSMENT_JOB_LEASE_SECONDS`, and `update_candidate_profile` monkeypatch behavior used by tests.
- The refactor must pass the full backend suite and the existing frontend contract suite.
- Do not introduce new abstractions with only one implementation; keep the existing provider seam intact.

---

### Task 1: Add the architecture contract test

**Files:**
- Create: `backend/tests/test_architecture_modules.py`

- [x] **Step 1: Write the failing test**

Assert that the four domain modules exist and own their public workflow entrypoints: `resume_intake`, `interview_flow`, `assessment_flow`, and `reporting_flow`.

- [x] **Step 2: Run the test and confirm RED**

Run: `python -m pytest backend/tests/test_architecture_modules.py -q`

Expected: collection fails because the new modules do not exist yet.

### Task 2: Extract shared workflow invariants

**Files:**
- Create: `backend/app/workflow_common.py`
- Modify: `backend/tests/test_architecture_modules.py`

- [x] **Step 1: Add the shared errors and helpers**

Move the shared domain errors, payload hashing, question reconstruction, active-session lookup, job event append, and deterministic `calculate_score_100` support into this focused module. Keep their behavior and messages unchanged.

- [x] **Step 2: Run the architecture contract test**

Run: `python -m pytest backend/tests/test_architecture_modules.py -q`

Expected: still RED until all four domain modules are present.

### Task 3: Create the resume intake module

**Files:**
- Create: `backend/app/resume_intake.py`
- Modify: `backend/tests/test_architecture_modules.py`

- [x] **Step 1: Move resume/profile/project-analysis workflow code**

Move `create_profile`, `parse_and_store_resume`, `analyze_resume_project`, and `stream_resume_project_analysis`, plus their local snapshot helper, without changing persistence or stream event behavior.

- [x] **Step 2: Assert the entrypoint ownership**

Assert `create_profile`, `parse_and_store_resume`, `analyze_resume_project`, and `stream_resume_project_analysis` come from `app.resume_intake`.

- [x] **Step 3: Run focused resume and analysis tests**

Run: `python -m pytest backend/tests/test_resume_files.py backend/tests/test_resume_parsers.py backend/tests/test_project_analysis.py -q`

Expected: PASS.

### Task 4: Create the interview flow module

**Files:**
- Create: `backend/app/interview_flow.py`
- Modify: `backend/tests/test_architecture_modules.py`

- [x] **Step 1: Move session and answer workflow code**

Move `create_session`, `get_session_view`, `submit_answer`, and their question projection helper. Use the shared active-session lookup and the assessment result projection without changing idempotency behavior.

- [x] **Step 2: Assert the entrypoint ownership**

Assert the three interview entrypoints come from `app.interview_flow`.

- [x] **Step 3: Run focused interview tests**

Run: `python -m pytest backend/tests/test_api.py -q`

Expected: PASS.

### Task 5: Create the assessment flow module

**Files:**
- Create: `backend/app/assessment_flow.py`
- Modify: `backend/tests/test_architecture_modules.py`

- [x] **Step 1: Move assessment execution and result projection code**

Move batch job creation, assessment execution, retry/failure handling, single-answer evaluation, rubric/evidence persistence, response projections, and `calculate_score_100` delegation. Keep the profile-update callback injectable so the existing façade monkeypatch remains effective.

- [x] **Step 2: Assert the entrypoint ownership**

Assert `assess_session` and `evaluate_answer` come from `app.assessment_flow`.

- [x] **Step 3: Run focused assessment tests**

Run: `python -m pytest backend/tests/test_assessment.py backend/tests/test_assessment_engine.py backend/tests/test_assessment_batch.py backend/tests/test_history_persistence.py backend/tests/test_score_100.py -q`

Expected: PASS.

### Task 6: Create the reporting and profile read module

**Files:**
- Create: `backend/app/reporting_flow.py`
- Modify: `backend/tests/test_architecture_modules.py`

- [x] **Step 1: Move derived read and report persistence code**

Move report payload building/persistence, history, profile summary/history, operation-job projection, archive behavior, and recommendation status projection. Keep all query ordering and JSON shapes unchanged.

- [x] **Step 2: Assert the entrypoint ownership**

Assert report, history, profile, job, and recommendation entrypoints come from `app.reporting_flow`.

- [x] **Step 3: Run focused history/profile tests**

Run: `python -m pytest backend/tests/test_interview_history.py backend/tests/test_profile_engine.py backend/tests/test_profile_api.py backend/tests/test_settings_api.py -q`

Expected: PASS.

### Task 7: Replace `services.py` with a compatibility façade and wire the route composition

**Files:**
- Modify: `backend/app/services.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_architecture_modules.py`

- [x] **Step 1: Replace the implementation with explicit re-exports and two compatibility shims**

Re-export public entrypoints from their domain modules. Keep `_create_batch_job` and `ASSESSMENT_JOB_LEASE_SECONDS` as façade-level compatibility symbols, and make the façade `assess_session` pass its current `update_candidate_profile` and `_create_batch_job` symbols into `assessment_flow.assess_session`.

- [x] **Step 2: Keep the route module readable**

Retain the existing route behavior while grouping imports by `resume_intake`, `interview_flow`, `assessment_flow`, and `reporting_flow`; keep error handlers using the shared errors.

- [x] **Step 3: Assert the façade is thin**

Assert the façade entrypoints resolve to the domain modules or explicit compatibility shims, and that no copied business implementation remains in `services.py`.

- [x] **Step 4: Run the full verification suite**

Run: `python -m pytest -q`

Expected: all existing backend tests plus the architecture contract test pass.

### Task 8: Final verification

**Files:**
- No additional production files.

- [x] **Step 1: Run frontend contract tests**

Run: `npm test` from `frontend/`

Expected: all existing frontend contract tests pass.

- [x] **Step 2: Run static checks**

Run: `git diff --check` and inspect `git status --short`.

Expected: no whitespace errors; pre-existing user modifications remain present and no unrelated files are changed.
