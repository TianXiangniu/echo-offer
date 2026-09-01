# Resume Project Rich Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend resume project analysis with provenance-aware rich fields and chained project questions while keeping the user-facing form limited to the existing core fields.

**Architecture:** Keep the existing eight core project columns as the confirmed project contract. Store the richer AI analysis as a versioned JSON snapshot in `ResumeProjectAnalysis.analysis_json`; normalize optional nested objects and question metadata in the backend. The frontend renders only the core fields and a small conditional missing-information panel.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, SQLite/Alembic, pytest, Next.js/React, TypeScript, Vitest.

## Global Constraints

- Do not expose or commit SiliconFlow API keys.
- Do not push or sync to GitHub.
- Preserve existing uncommitted frontend UI changes.
- Keep PDF/DOCX parsing and SSE endpoints backward compatible.
- Unknown project facts must remain empty or marked missing; the model must not invent them.
- Project questions and fixed questions must remain separate.

---

### Task 1: Define the rich analysis contract

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `frontend/lib/api.ts`
- Test: `backend/tests/test_project_analysis.py`
- Test: `frontend/lib/assessment-types.test.ts`

**Interfaces:**
- Produces `ProjectAnalysisDetails`, `ProjectFact`, and `ProjectQuestionDetail` types with optional nested groups.
- Keeps the existing eight `ProjectInput` fields and existing response fields valid.

- [ ] **Step 1: Write the failing backend tests**

Add tests asserting that a rich project payload accepts `context`, `ownership`, `architecture`, `agent_details`, `tradeoffs`, `engineering`, `evaluation`, `evolution`, `facts`, and `question_chain`, while old eight-field payloads remain valid.

- [ ] **Step 2: Run the focused backend tests**

Run: `python -m pytest backend/tests/test_project_analysis.py -q`

Expected: FAIL because the response models do not expose the new nested contract.

- [ ] **Step 3: Add minimal Pydantic models and TypeScript interfaces**

Use optional dictionaries/lists for nested groups so the current provider response remains compatible. Define explicit literal values for fact status and question group where practical.

- [ ] **Step 4: Run focused tests again**

Run: `python -m pytest backend/tests/test_project_analysis.py -q`

Expected: PASS for the new model contract and all existing project-analysis tests.

- [ ] **Step 5: Run frontend type tests**

Run: `npm test -- --runInBand frontend/lib/assessment-types.test.ts`

Expected: PASS.

### Task 2: Normalize facts and chained question metadata

**Files:**
- Modify: `backend/app/project_analysis.py`
- Test: `backend/tests/test_project_analysis.py`

**Interfaces:**
- Produces `normalize_project_analysis_payload(payload, resume_text)` returning a backward-compatible payload with `schema_version`, nested groups, facts, missing information, and exactly three linked project questions.

- [ ] **Step 1: Write failing normalization tests**

Cover these behaviors:

```python
def test_normalizes_rich_project_fields_and_fact_statuses():
    result = normalize_project_analysis_payload(rich_payload, resume_text)
    assert result["schema_version"] == "project-analysis-v2"
    assert result["project"]["ownership"]["owned_modules"] == "检索链路"
    assert result["facts"][0]["status"] == "extracted"

def test_rejects_evidence_quote_that_is_not_in_resume():
    result = normalize_project_analysis_payload(payload_with_fake_quote, resume_text)
    assert result["facts"][0]["evidence"][0]["status"] == "invalid"

def test_links_three_project_questions_in_order():
    result = normalize_project_analysis_payload(payload, resume_text)
    chain = result["question_chain"]
    assert [item["order"] for item in chain] == [1, 2, 3]
    assert [item["depends_on"] for item in chain] == [None, 1, 2]
    assert all(item["question_group"] == "project" for item in chain)
```

- [ ] **Step 2: Run the tests and verify the expected failure**

Run: `python -m pytest backend/tests/test_project_analysis.py -q`

Expected: FAIL because nested groups, evidence status, and dependency metadata are not normalized yet.

- [ ] **Step 3: Implement normalization**

Add bounded defaults for the nested groups, preserve empty values, mark non-literal evidence as invalid with a reason, and synthesize missing question metadata only for the three existing project questions. Never turn inferred facts into confirmed facts.

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest backend/tests/test_project_analysis.py -q`

Expected: PASS.

### Task 3: Update the AI prompt to produce useful project facts

**Files:**
- Modify: `backend/app/project_analysis.py`
- Test: `backend/tests/test_project_analysis.py`

**Interfaces:**
- The provider prompt asks for rich analysis but still accepts the current eight core fields.
- The prompt requires facts to be sourced from the resume, unknown fields to stay empty, and questions to use only confirmed/extracted fields.

- [ ] **Step 1: Add failing prompt tests**

Assert the generated prompt contains instructions for ownership boundary, scale, tradeoffs, evaluation method, unknown values, fact status, and a three-question dependency chain.

- [ ] **Step 2: Run the prompt tests**

Run: `python -m pytest backend/tests/test_project_analysis.py -q`

Expected: FAIL because the current prompt mentions only the eight core fields and independent questions.

- [ ] **Step 3: Update the prompt and parser contract**

Add the nested field groups from the design, explicit Agent-specific fields, and the question metadata contract. Keep the token budget bounded by asking the model to omit irrelevant categories or return empty objects.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest backend/tests/test_project_analysis.py -q`

Expected: PASS.

### Task 4: Persist the analysis snapshot when the user confirms the project

**Files:**
- Modify: `backend/app/services.py`
- Modify: `backend/app/models.py` only if a nullable `analysis_schema_version` column is needed
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- `ProfileCreate` may include `analysis_id` and `analysis_payload` or use the existing analysis record by id.
- Confirming a project stores the edited core fields and preserves the rich `analysis_json` snapshot with user-edited core values.

- [ ] **Step 1: Write the failing API test**

Create an analysis with rich JSON, confirm the project with an edited `responsibilities` value, then assert the persisted analysis JSON contains the edited core value and the project record contains the eight edited fields.

- [ ] **Step 2: Run the focused API test**

Run: `python -m pytest backend/tests/test_api.py -q`

Expected: FAIL because confirmation currently persists the project but does not reconcile the analysis snapshot.

- [ ] **Step 3: Implement transactional snapshot reconciliation**

On confirmation, copy the submitted core fields into `analysis_json.project.core`, set the analysis status to `confirmed`, preserve facts and question metadata, and keep the existing project/question creation behavior. If the analysis id is absent, preserve current manual-entry behavior.

- [ ] **Step 4: Run focused API tests**

Run: `python -m pytest backend/tests/test_api.py -q`

Expected: PASS.

### Task 5: Show only high-value missing information in the frontend

**Files:**
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/ui-copy.ts`
- Test: `frontend/lib/modern-ui.test.ts`

**Interfaces:**
- The home page continues editing the eight core fields.
- `missing_information` is rendered as a compact, plain-Chinese supplement area; it must not expose raw internal field names or phrases such as “冻结事实” or “可信边界模型”.

- [ ] **Step 1: Write failing frontend tests**

Assert that the UI copy maps internal missing-information keys to natural Chinese prompts, and that the page does not render more than three supplement prompts at once.

- [ ] **Step 2: Run the frontend test**

Run: `npm test -- --runInBand frontend/lib/modern-ui.test.ts`

Expected: FAIL because the current page renders raw strings in one note.

- [ ] **Step 3: Implement the compact supplement UI**

Add a small conditional block below the AI analysis result. Use friendly labels such as “项目做到什么阶段了？” and “哪些部分是你亲自完成的？”. Keep it optional and preserve current form submission behavior.

- [ ] **Step 4: Run frontend tests and build**

Run: `npm test -- --runInBand frontend/lib/modern-ui.test.ts`

Run: `npm run build`

Expected: PASS and a successful production build.

### Task 6: End-to-end regression verification

**Files:**
- Modify: `README.md` if local testing instructions need the new field behavior
- Test: existing backend and frontend test suites

- [ ] **Step 1: Run all backend tests**

Run: `python -m pytest backend/tests -q`

Expected: all tests pass.

- [ ] **Step 2: Run all frontend tests**

Run: `npm test -- --runInBand`

Expected: all tests pass.

- [ ] **Step 3: Run the frontend build**

Run: `npm run build`

Expected: exit code 0.

- [ ] **Step 4: Check the diff and secret safety**

Run: `git diff --check`

Run: `rg -n "sk-[A-Za-z0-9]{20,}" backend frontend docs --glob '!**/node_modules/**' --glob '!**/.venv/**'`

Expected: no new whitespace errors beyond known line-ending warnings and no API key output.

