# Agent 应用工程师模拟面试垂直切片 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在当前仓库中实现一个无需外部 API Key 即可运行的中文 Agent 应用工程师模拟面试垂直切片。

**Architecture:** 使用 `backend/` 中的 FastAPI + SQLAlchemy + SQLite 提供资料、面试、回答和报告 API；使用 `frontend/` 中的 Next.js App Router 页面消费 JSON API。题目由固定版本化题库生成，评估由可替换的本地规则 Provider 完成；SQLite 是唯一业务事实源，前端不保存面试游标。

**Tech Stack:** Python 3.12 目标兼容（当前本机 Python 3.11.9）、FastAPI、Pydantic、SQLAlchemy 2、SQLite、pytest、Next.js、React、TypeScript、Tailwind CSS、npm。

## Global Constraints

- 本地单用户固定为 `local-user`，不做登录和多租户。
- 固定方向为 `agent_application_rag`，级别为 `one_to_three_years`，语言为 `zh_cn`。
- 题目结构固定为项目深挖 3 题、Agent 基础 3 题、工程故障排查 2 题，前三题为锚题。
- 回答必须在服务端持久化后再进行评估；刷新不能丢失已提交回答。
- `submitted`、`explicit_unknown`、`skipped` 分开保存；跳过不评分，明确不知道可形成 0 级有效观察。
- 相同 `client_submission_id` 和相同 payload 返回既有结果；相同 ID 携带不同 payload 返回 HTTP 409。
- 报告只展示 0～4 等级、覆盖率、证据、置信度和 Top 3，不展示未经校准的 0～100 总分。
- 本切片不接入 DeepSeek、LangGraph、PDF、训练复盘、追问、延迟验证、OperationJob 和用户异议重评。
- 本地启动无需 API Key；业务数据库固定存放于 `data/app.db`。

---

### Task 1: 建立项目骨架与可重复测试入口

**Files:**
- Create: `.gitignore`
- Create: `README.md` (replace the repository placeholder README with local setup instructions)
- Create: `backend/requirements.txt`
- Create: `backend/pytest.ini`
- Create: `backend/app/__init__.py`
- Create: `backend/tests/__init__.py`
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/next-env.d.ts`
- Create: `data/.gitkeep`

**Interfaces:**
- Produces a Python test command `python -m pytest backend/tests -q` and a frontend command `npm --prefix frontend run build`.
- Produces a frontend runtime contract `NEXT_PUBLIC_API_URL`, defaulting to `http://localhost:8000`.

- [ ] **Step 1: Add the project ignore rules**

`.gitignore` must include:

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
backend/.venv/
data/app.db
data/*.db-*
node_modules/
frontend/.next/
frontend/out/
frontend/.env.local
```

- [ ] **Step 2: Add backend dependency and test configuration**

`backend/requirements.txt` must pin compatible minimums:

```text
fastapi>=0.115,<1
uvicorn[standard]>=0.30,<1
sqlalchemy>=2.0,<3
pydantic>=2.8,<3
pytest>=8,<9
httpx>=0.27,<1
```

`backend/pytest.ini` must set `pythonpath = .` and `testpaths = tests`.

- [ ] **Step 3: Add the frontend package manifest**

`frontend/package.json` must define:

```json
{
  "name": "agent-echo-frontend",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint"
  },
  "dependencies": {
    "next": "^15.4.0",
    "react": "^19.1.0",
    "react-dom": "^19.1.0"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "typescript": "^5.6.0",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.40",
    "tailwindcss": "^3.4.10"
  }
}
```

- [ ] **Step 4: Install dependencies and verify the empty test/build entry points**

Run:

```powershell
python -m pip install -r backend/requirements.txt
npm --prefix frontend install
python -m pytest backend/tests -q
npm --prefix frontend run build
```

Expected: pytest reports no collected tests and the Next.js build fails only if the minimal app entry has not yet been added; after the entry files are added in Task 4, the build must pass.

- [ ] **Step 5: Commit the scaffold**

```powershell
git add .gitignore README.md backend frontend data
git commit -m "chore: scaffold vertical slice"
```

### Task 2: Implement the fixed question bank and assessment rules with TDD

**Files:**
- Create: `backend/app/question_bank.py`
- Create: `backend/app/providers.py`
- Create: `backend/tests/test_question_bank.py`
- Create: `backend/tests/test_assessment.py`

**Interfaces:**
- `question_bank.build_question_specs() -> list[QuestionSpec]` returns exactly 8 specs.
- `QuestionSpec` exposes `order`, `category`, `is_anchor`, `prompt`, `knowledge_point_id`, `rubric_version`, and `signals`.
- `RuleBasedAssessmentProvider.assess(question: QuestionSpec, answer_text: str, status: str) -> AssessmentResult` returns `level`, `evidence_start`, `evidence_end`, `quoted_text`, `answer_text_hash`, `gaps`, and `confidence`.

- [ ] **Step 1: Write failing question-bank tests**

`backend/tests/test_question_bank.py` must assert the required behavior:

```python
from app.question_bank import build_question_specs


def test_question_bank_has_three_two_three_shape_and_three_anchors():
    specs = build_question_specs()
    assert len(specs) == 8
    assert [spec.category for spec in specs].count("project") == 3
    assert [spec.category for spec in specs].count("agent") == 3
    assert [spec.category for spec in specs].count("reliability") == 2
    assert [spec.is_anchor for spec in specs[:3]] == [True, True, True]
    assert sum(spec.is_anchor for spec in specs) == 3
```

- [ ] **Step 2: Run the question-bank test and verify RED**

Run `python -m pytest backend/tests/test_question_bank.py -q`. Expected: FAIL because `app.question_bank` does not exist.

- [ ] **Step 3: Implement the fixed eight-question bank**

Implement three project prompts, three Agent/RAG prompts, and two reliability prompts. Every spec must include a non-empty `knowledge_point_id`, `rubric_version="alpha-local-v1"`, and at least two signal strings. Set `is_anchor=True` only for orders 1, 2, and 3.

- [ ] **Step 4: Run the question-bank test and verify GREEN**

Run the same command and expect one passing test.

- [ ] **Step 5: Write failing assessment tests**

`backend/tests/test_assessment.py` must cover explicit unknown, evidence slicing and a high-signal submitted answer:

```python
from app.providers import RuleBasedAssessmentProvider
from app.question_bank import build_question_specs


def test_explicit_unknown_is_a_valid_zero_level_observation():
    result = RuleBasedAssessmentProvider().assess(
        build_question_specs()[0], "不知道", "explicit_unknown"
    )
    assert result.level == 0
    assert result.evidence_start == 0
    assert result.evidence_end == len("不知道")
    assert result.quoted_text == "不知道"


def test_submitted_answer_evidence_matches_the_answer_hash():
    answer = "我们先做查询改写，再用混合检索召回候选文档，并通过 rerank 控制延迟和召回率。"
    result = RuleBasedAssessmentProvider().assess(
        build_question_specs()[4], answer, "submitted"
    )
    assert 1 <= result.level <= 4
    assert result.quoted_text == answer[result.evidence_start:result.evidence_end]
    assert result.answer_text_hash
```

- [ ] **Step 6: Run the assessment tests and verify RED**

Run `python -m pytest backend/tests/test_assessment.py -q`. Expected: FAIL because `RuleBasedAssessmentProvider` does not exist.

- [ ] **Step 7: Implement the minimal assessment Provider**

Use SHA-256 for `answer_text_hash`. For `submitted`, calculate a 0～4 level from answer length, matched signal count, and explicit mechanism/boundary/trade-off terms; for `explicit_unknown`, return level 0; reject ordinary blank submitted text with `ValueError`. Use the complete answer as the evidence span so the character range is always verifiable.

- [ ] **Step 8: Run all domain tests and verify GREEN**

Run `python -m pytest backend/tests/test_question_bank.py backend/tests/test_assessment.py -q` and expect all tests to pass.

- [ ] **Step 9: Commit the domain layer**

```powershell
git add backend/app/question_bank.py backend/app/providers.py backend/tests
git commit -m "feat: add fixed interview bank and local assessment"
```

### Task 3: Add SQLite models, services, and FastAPI API with idempotent answers

**Files:**
- Create: `backend/app/config.py`
- Create: `backend/app/database.py`
- Create: `backend/app/models.py`
- Create: `backend/app/schemas.py`
- Create: `backend/app/services.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_api.py`

**Interfaces:**
- `POST /api/profile` accepts resume and confirmed project fields and returns `profile_id`.
- `POST /api/sessions` accepts `profile_id` and returns `session_id` plus eight questions.
- `GET /api/sessions/{session_id}` returns current question, all question summaries, answer states, progress, and session status.
- `POST /api/sessions/{session_id}/answers` accepts `{question_id, client_submission_id, status, answer_text}` and returns the answer plus optional observation.
- `GET /api/sessions/{session_id}/report` returns progress, anchor coverage, strengths, gaps, level distribution, valid evidence count, and confidence.
- `create_app(database_url: str | None = None) -> FastAPI` creates an isolated app for tests or the default `data/app.db` app for local running.

- [ ] **Step 1: Write failing API tests for profile and session creation**

Use FastAPI `TestClient` with a temporary SQLite database. Assert that creating a profile persists a resume hash and project version, and creating a session returns exactly 8 questions with the 3/3/2 categories.

- [ ] **Step 2: Run the API creation tests and verify RED**

Run `python -m pytest backend/tests/test_api.py -q`. Expected: FAIL because `app.main` and the database models do not exist.

- [ ] **Step 3: Implement database configuration and models**

Create SQLAlchemy 2 declarative models for `User`, `Resume`, `ResumeProject`, `InterviewTarget`, `InterviewSession`, `InterviewQuestion`, `AnswerAttempt`, and `AssessmentObservation`. Use string UUID primary keys, UTC timestamps, `session_id + client_submission_id` uniqueness, and a `question_id + primary_attempt_kind` uniqueness constraint. `database.py` must create `data/app.db` parent directories and expose `get_db`.

- [ ] **Step 4: Implement schemas and profile/session services**

Add Pydantic models for profile creation, session creation, answer submission, and all response views. `create_profile` must SHA-256 hash the exact resume text and set `project_version=1` for the first confirmed project. `create_session` must save all fixed question specs in one transaction and set `workflow_version="alpha-local-v1"`.

- [ ] **Step 5: Run the API creation tests and verify GREEN**

Run `python -m pytest backend/tests/test_api.py -k "profile or session" -q` and expect the creation tests to pass.

- [ ] **Step 6: Write failing tests for answer states, idempotency and report aggregation**

Add tests that:

```python
def test_duplicate_submission_returns_one_answer_and_one_observation(client, session_id, question_id):
    payload = {
        "question_id": question_id,
        "client_submission_id": "stable-1",
        "status": "submitted",
        "answer_text": "我会先定位检索链路，再对召回率和延迟做分层监控。",
    }
    first = client.post(f"/api/sessions/{session_id}/answers", json=payload)
    second = client.post(f"/api/sessions/{session_id}/answers", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["answer"]["id"] == second.json()["answer"]["id"]


def test_same_submission_id_with_different_payload_returns_409(client, session_id, question_id):
    # Submit the first payload, then change only answer_text before resubmitting.
    assert client.post(...).status_code == 200
    assert client.post(...).status_code == 409
```

Also test `explicit_unknown` gets level 0, `skipped` has no observation, ordinary blank `submitted` returns 422, and the report never contains a `score_100` field.

- [ ] **Step 7: Run the answer/report tests and verify RED**

Run `python -m pytest backend/tests/test_api.py -k "answer or report" -q`. Expected: FAIL because answer and report routes are not implemented.

- [ ] **Step 8: Implement answer persistence, idempotency and report aggregation**

Persist an answer and commit it before calling the Provider. On a repeated `client_submission_id`, compare a stable payload hash; return the existing result for an identical hash and raise a typed conflict for a different hash. Advance the SQL cursor to the next unanswered question. Mark the session `completed` when all eight questions have a primary answer. Build the report from valid observations only, ranking levels descending for strengths and ascending for gaps.

- [ ] **Step 9: Add FastAPI routes and error handlers**

Register CORS for `http://localhost:3000`, `/health`, the four API routes, 404 handling for missing IDs, 409 handling for idempotency conflicts, and 422 handling for validation errors. Run the Provider through its interface, never from a route directly.

- [ ] **Step 10: Run the complete backend suite and verify GREEN**

Run `python -m pytest backend/tests -q`. Expected: all tests pass.

- [ ] **Step 11: Commit the backend vertical slice**

```powershell
git add backend data
git commit -m "feat: add persistent interview API"
```

### Task 4: Build the Next.js profile setup and interview flow

**Files:**
- Create: `frontend/app/layout.tsx`
- Create: `frontend/app/page.tsx`
- Create: `frontend/app/interview/[id]/page.tsx`
- Create: `frontend/lib/api.ts`
- Create: `frontend/app/globals.css`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.mjs`

**Interfaces:**
- `api.createProfile(input: ProfileInput): Promise<ProfileResponse>` calls `POST /api/profile`.
- `api.createSession(profileId: string): Promise<SessionResponse>` calls `POST /api/sessions`.
- `api.getSession(sessionId: string): Promise<SessionView>` calls `GET /api/sessions/{id}`.
- `api.submitAnswer(sessionId: string, input: AnswerInput): Promise<AnswerResponse>` calls the answer endpoint and preserves the client submission ID across retry.

- [ ] **Step 1: Define the profile form manual acceptance checklist**

Because this task is UI scaffolding, use this executable browser acceptance checklist: a user can paste resume text, fill all project fields, click “创建面试”, and navigate to `/interview/{id}`. The backend tests remain the source of truth for data behavior.

- [ ] **Step 2: Implement the Next.js app shell and API client**

Use a dark ink background, warm paper cards, blue-violet accent, high-contrast headings, and Chinese labels. Define the API client with `fetch`, JSON parsing, and explicit error messages for 409/422/network failures.

- [ ] **Step 3: Implement the profile page**

Collect `resume_text`, `project_name`, `background_goal`, `tech_stack`, `responsibilities`, `core_solution`, `engineering_challenges`, `failure_improvements`, and `quantified_results`. Disable the submit button while creating the profile/session and navigate only after both requests succeed.

- [ ] **Step 4: Implement the interview page**

Load the session from the API on every page load. Display category, anchor badge, progress, remaining count, current prompt, and a textarea. Provide “提交回答”, “我不知道”, and “跳过” actions. Generate one `crypto.randomUUID()` submission ID per attempt and retain it until the request succeeds; after success reload server state rather than incrementing a browser counter.

- [ ] **Step 5: Run a local frontend build**

Run `npm --prefix frontend run build`. Expected: PASS with no TypeScript errors.

- [ ] **Step 6: Commit the profile/interview UI**

```powershell
git add frontend
git commit -m "feat: add profile and interview pages"
```

### Task 5: Build the report page, README runbook, and integration verification

**Files:**
- Create: `frontend/app/report/[id]/page.tsx`
- Modify: `frontend/app/interview/[id]/page.tsx` (completion navigation)
- Modify: `frontend/app/page.tsx` (resume an existing session link if an ID is present in the response)
- Modify: `README.md`
- Create: `backend/tests/test_smoke.py`

**Interfaces:**
- `api.getReport(sessionId: string): Promise<ReportResponse>` calls `GET /api/sessions/{id}/report`.
- A completed session navigates to `/report/{id}`; an incomplete session remains resumable at `/interview/{id}`.

- [ ] **Step 1: Implement the report page**

Render completion, coverage, anchor coverage, Top 3 strengths, Top 3 gaps, level distribution, valid evidence count, confidence, and the local-rule-evaluator disclaimer. Use empty states for no observations and low coverage; never render a 0～100 score.

- [ ] **Step 2: Add the local runbook**

`README.md` must contain exact Windows PowerShell commands:

```powershell
python -m venv backend/.venv
backend\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python -m uvicorn app.main:app --reload --port 8000" -WorkingDirectory "$PWD\backend"
npm --prefix frontend install
npm --prefix frontend run dev
```

Document that the browser URL is `http://localhost:3000`, the API health URL is `http://localhost:8000/health`, and the local SQLite file is `data/app.db`.

- [ ] **Step 3: Run all verification commands**

Run:

```powershell
python -m pytest backend/tests -q
npm --prefix frontend run build
```

Start the backend and frontend, call `Invoke-RestMethod http://localhost:8000/health`, and manually complete one full interview in the browser. Refresh once during the interview and verify that the server-side progress remains.

- [ ] **Step 4: Commit the completed vertical slice**

```powershell
git add README.md backend frontend
git commit -m "feat: complete agent interview vertical slice"
```

## Plan Self-Review

- Spec coverage: profile/project confirmation is covered by Tasks 3 and 4; fixed 3/3/2 questions by Task 2; persistence and refresh recovery by Task 3; idempotency and 409 by Task 3; report by Task 5; local startup and no API key by Tasks 1 and 5; deferred Alpha capabilities remain explicitly out of scope.
- Placeholder scan: there are no `TBD`, `TODO`, or unspecified implementation steps in the plan.
- Type consistency: `QuestionSpec`, `AssessmentResult`, `ProfileResponse`, `SessionView`, `AnswerResponse`, and `ReportResponse` are introduced at the task where they are first produced and consumed by later tasks.
- Environment note: the target remains Python 3.12 from the product specification; the current machine exposes Python 3.11.9, so implementation must avoid 3.12-only syntax and verification will record the actual interpreter version.
