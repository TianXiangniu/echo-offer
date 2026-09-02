# AI Assessment Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make resume analysis and batch interview scoring resilient to malformed, truncated, slow, and partially invalid model responses while preserving usable local results.

**Architecture:** Add one shared model-output utility for safe content extraction and JSON parsing. Keep rubric parsing strict for identities and numeric levels, but derive evidence offsets and hashes in Python and mark only the affected rubric item invalid. Split completed answers into small assessment batches and aggregate successful batches into a ready or partial report.

**Tech Stack:** Python, FastAPI, SQLAlchemy, SQLite, httpx, pytest, Next.js, TypeScript.

## Global Constraints

- Do not expose or persist API keys.
- Keep scoring deferred until the interview is complete.
- Keep skipped answers unscored and preserve explicit unknown as a valid level-zero answer.
- Keep frozen Rubric IDs and deterministic program-side aggregation.
- Do not push or sync any change to GitHub.

### Task 1: Shared model-output parsing

**Files:**
- Create: `backend/app/model_output.py`
- Modify: `backend/app/project_analysis.py`
- Test: `backend/tests/test_model_output.py`

**Interfaces:**
- Produces `parse_model_json(content: object) -> object` and `content_to_text(content: object) -> str`.
- Consumers use the utility before project-analysis and assessment validation.

- [ ] **Step 1: Write failing tests** for code fences, `<think>` wrappers, content-part lists, empty content, and truncated JSON.
- [ ] **Step 2: Run `pytest backend/tests/test_model_output.py -q` and confirm the new tests fail because the utility is absent.
- [ ] **Step 3: Implement the smallest utility that normalizes supported content and extracts one JSON object without logging secrets.
- [ ] **Step 4: Run the focused tests and confirm they pass.

### Task 2: Program-side evidence derivation and precise provider errors

**Files:**
- Modify: `backend/app/assessment_engine.py`
- Modify: `backend/app/providers.py`
- Modify: `backend/app/project_analysis.py`
- Test: `backend/tests/test_assessment_engine.py`
- Test: `backend/tests/test_providers.py`

**Interfaces:**
- `parse_model_assessment` accepts model rubric items with `quoted_text` and derives offsets and SHA-256.
- Provider errors expose `provider_output_truncated`, `empty_model_response`, `invalid_json`, and `invalid_schema` codes while preserving existing public error codes where compatibility requires them.

- [ ] **Step 1: Add failing tests** proving a model need not send offsets/hash, unmatched evidence becomes an invalid item, and a length finish reason gets a truncation error.
- [ ] **Step 2: Run focused tests and confirm failure.**
- [ ] **Step 3: Implement derived evidence and shared JSON parsing; inspect `finish_reason` before parsing.
- [ ] **Step 4: Run focused tests and confirm pass without changing the frozen rubric contract.

### Task 3: Partial batch assessment and stale-job recovery

**Files:**
- Modify: `backend/app/services.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_api.py`
- Test: `backend/tests/test_history_persistence.py`

**Interfaces:**
- `assess_session` splits cases into batches of three, persists successful batch results immediately, and returns a `partial` report when some batches fail.
- A `pending/running` job older than the configured local lease is failed before a new attempt is created.

- [ ] **Step 1: Add failing API tests** for multiple batch calls, partial report creation, and stale running-job recovery.
- [ ] **Step 2: Run focused tests and confirm failure.**
- [ ] **Step 3: Implement batch chunking, per-chunk error persistence, and stale-job recovery without deleting answers.
- [ ] **Step 4: Run focused API and history tests and confirm pass.

### Task 4: Frontend error visibility and partial-result navigation

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/app/interview/[id]/page.tsx`
- Modify: `frontend/app/report/[id]/page.tsx`
- Test: `frontend/lib/assessment-types.test.ts`

**Interfaces:**
- `AssessmentBatchResponse` includes job status and root-level error fields.
- Error-copy helpers map provider timeout, output truncation, JSON/schema errors, and partial results to natural Chinese copy.

- [ ] **Step 1: Add failing TypeScript contract tests** for root-level error fields and error-code copy.
- [ ] **Step 2: Run `npm test` and confirm failure.
- [ ] **Step 3: Implement types and UI handling; allow report navigation for `partial` results.
- [ ] **Step 4: Run the focused frontend test and build.

### Task 5: Full verification

**Files:**
- No production files unless verification reveals a regression.

- [ ] **Step 1: Run `python -m pytest backend/tests -q` from the project root using the `agent` environment.
- [ ] **Step 2: Run `npm test` and `npm run build` in `frontend`.
- [ ] **Step 3: Inspect `git diff` and `git status --short`; preserve existing user-owned UI changes and do not push.
