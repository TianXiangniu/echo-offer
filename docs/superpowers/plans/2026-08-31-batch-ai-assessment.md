# Batch AI Assessment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AI 评分从逐题调用改为面试结束后一次批量调用，同时保留逐题 Rubric 评分、证据审计、失败重试和报告展示。

**Architecture:** 回答接口只负责幂等保存首答；面试完成后由独立批量评估接口收集本场回答，调用 `AssessmentProvider.assess_batch` 一次，再拆分保存每个回答的 `AssessmentRun` 和 `RubricObservation`。前端在最后一题保存成功后触发批量接口并显示阶段进度，报告页读取持久化结果。

**Tech Stack:** FastAPI、SQLAlchemy、SQLite、Pydantic、httpx、pytest、Next.js 15、React 19、TypeScript。

## Global Constraints

- 面试过程中模型调用次数为 0。
- 全部问题完成后，模型调用次数为 1。
- 批量输入只包含问题文本、问题类别、知识点 ID、冻结 Rubric 和当前回答。
- 不携带简历全文、历史画像、过去分数、薄弱点或下一题优先级。
- `submitted` 和 `explicit_unknown` 都视为已完成；`skipped` 也结束当前问题，但不进入 AI 评分。
- `explicit_unknown` 是有效首答，按等级 0 记录；`skipped` 不转换为等级 0。
- 只有 `valid` 评估进入报告统计，不展示未经校准的 0～100 综合分数。
- 模型失败时保留所有回答，重试只创建新的评估尝试，不创建新的回答。
- API Key 只从后端环境变量读取，不进入前端代码、日志、数据库或 Git 提交。
- 不自动推送 GitHub、创建 Pull Request 或改变远程仓库。

## File Map

- `backend/app/providers.py`：批量 Provider 合同、Prompt、SiliconFlow 单次请求和错误映射。
- `backend/app/assessment_engine.py`：批量 JSON 解析、证据校验和程序化聚合。
- `backend/app/models.py`、`backend/app/database.py`：批次 ID、评估运行和 SQLite 兼容迁移。
- `backend/app/schemas.py`：批量评估响应模型。
- `backend/app/services.py`、`backend/app/main.py`：回答保存、完成度检查、批量评估和路由。
- `backend/tests/test_assessment_batch.py`、`backend/tests/test_api.py`、`backend/tests/conftest.py`：Provider、API、调用次数和重试测试。
- `frontend/lib/api.ts`、`frontend/app/interview/[id]/page.tsx`、`frontend/app/report/[id]/page.tsx`：前端请求、完成后评分、进度和重试 UI。
- `frontend/lib/assessment-types.test.ts`、`README.md`：类型契约和使用说明。

---

### Task 1: 添加批量 Provider 合同和严格模型输出解析

**Files:**
- Modify: `backend/app/providers.py`
- Modify: `backend/app/assessment_engine.py`
- Test: `backend/tests/test_assessment_batch.py`

**Interfaces:**
- Consumes: 现有 `QuestionSpec`、`RubricSnapshot`、`AssessmentResult`、证据校验和确定性聚合函数。
- Produces: `BatchAssessmentCase`、`BatchAssessmentItem`、`AssessmentProvider.assess_batch(cases)`、`build_batch_assessment_prompt`、`parse_batch_model_assessment`。

- [ ] **Step 1: Write the failing tests**

```python
def test_batch_prompt_contains_independent_cases_without_resume_context():
    cases = make_cases()
    system_prompt, user_prompt = build_batch_assessment_prompt(cases)

    assert "独立" in system_prompt + user_prompt
    assert all(case.question.prompt in user_prompt for case in cases)
    assert all(case.answer_text in user_prompt for case in cases)
    assert "resume_text" not in user_prompt
    assert "过去分数" not in user_prompt


def test_batch_parser_requires_exact_case_and_rubric_sets():
    content = json.dumps({"items": [valid_case_payload(case) for case in make_cases()]})

    results = parse_batch_model_assessment(content, make_cases())

    assert {item.answer_id for item in results} == {
        case.answer_id for case in make_cases()
    }
    assert all(len(item.result.rubric_items) == 4 for item in results)


def test_batch_parser_rejects_missing_case_and_invalid_evidence():
    content = json.dumps({"items": [valid_case_payload(make_cases()[0])]})

    with pytest.raises(AssessmentResponseError):
        parse_batch_model_assessment(content, make_cases())


def test_siliconflow_batch_provider_uses_one_http_request(httpx_mock):
    httpx_mock.add_response(json=batch_model_response(make_cases()))
    provider = make_provider(httpx_mock)

    result = provider.assess_batch(make_cases())

    assert len(result) == 2
    assert httpx_mock.request_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_assessment_batch.py -q`

Expected: FAIL because the batch DTO, prompt builder, parser and `assess_batch` method do not exist.

- [ ] **Step 3: Implement the minimal batch contract and provider**

Add:

```python
@dataclass(frozen=True, slots=True)
class BatchAssessmentCase:
    answer_id: str
    question_id: str
    question: QuestionSpec
    answer_text: str


@dataclass(frozen=True, slots=True)
class BatchAssessmentItem:
    answer_id: str
    question_id: str
    result: AssessmentResult


class AssessmentProvider(Protocol):
    def assess_batch(
        self, cases: Sequence[BatchAssessmentCase]
    ) -> tuple[BatchAssessmentItem, ...]:
        ...
```

The model JSON must be exactly `{"items":[...]}`; every item contains `answer_id`, `question_id` and all Rubric observations. `parse_batch_model_assessment` must reject missing, duplicate or unknown case IDs, reject missing/extra/duplicate Rubric IDs, verify `answer[start:end] == quoted_text`, compute the SHA-256 hash and call existing deterministic aggregation. `SiliconFlowAssessmentProvider.assess_batch` sends one `/chat/completions` request and reuses timeout, HTTP, connection and response-format error mapping. Keep `assess` as a one-case compatibility wrapper delegating to `assess_batch`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_assessment_batch.py backend/tests/test_providers.py -q`

Expected: all selected tests pass and the batch Provider test reports one HTTP request.

- [ ] **Step 5: Commit**

```bash
git add backend/app/providers.py backend/app/assessment_engine.py backend/tests/test_assessment_batch.py
git commit -m "feat: add batch assessment provider contract"
```

### Task 2: Add batch persistence schema and API response types

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/database.py`
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_assessment_batch.py`

**Interfaces:**
- Consumes: `BatchAssessmentItem` and existing `AssessmentRun`/`RubricObservation` tables.
- Produces: `AssessmentRun.batch_id`、`AssessmentBatchItemResponse` 和 `AssessmentBatchResponse`。

- [ ] **Step 1: Write the failing test**

```python
def test_batch_persistence_and_response_contract():
    assert hasattr(AssessmentRun, "batch_id")

    response = AssessmentBatchResponse(
        status="valid",
        batch_id="batch-1",
        evaluated_count=2,
        total_count=3,
        assessments=[],
    )

    assert response.batch_id == "batch-1"
    assert response.evaluated_count == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest backend/tests/test_assessment_batch.py::test_batch_persistence_and_response_contract -q`

Expected: FAIL because `batch_id` and `AssessmentBatchResponse` are not defined.

- [ ] **Step 3: Implement the schema and migration**

Add a nullable indexed `batch_id: Mapped[str | None]` to `AssessmentRun`. Extend the existing SQLite compatibility routine to run `ALTER TABLE assessment_runs ADD COLUMN batch_id VARCHAR(36)` only when `PRAGMA table_info(assessment_runs)` lacks the column.

Add:

```python
class AssessmentBatchItemResponse(BaseModel):
    answer_id: str
    question_id: str
    assessment: AssessmentResponse


class AssessmentBatchResponse(BaseModel):
    status: str
    batch_id: str | None = None
    evaluated_count: int
    total_count: int
    assessments: list[AssessmentBatchItemResponse] = Field(default_factory=list)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest backend/tests/test_assessment_batch.py -q`

Expected: selected schema tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/database.py backend/app/schemas.py backend/tests/test_assessment_batch.py
git commit -m "feat: persist batch assessment identity"
```

### Task 3: Make answer submission save-only and add the batch service

**Files:**
- Modify: `backend/app/services.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `AssessmentProvider.assess_batch`、`build_explicit_unknown_assessment` 和 `AssessmentProviderError`。
- Produces: `assess_session(db, session_id, assessment_provider)` 和 `POST /api/sessions/{session_id}/assessment`。

- [ ] **Step 1: Write failing tests for call timing and batching**

```python
def test_answer_submission_does_not_call_ai(ai_client, ai_session_context):
    session_id, questions = ai_session_context

    response = ai_client.post(
        f"/api/sessions/{session_id}/answers",
        json=answer_payload(questions[0], "先保存回答，不应该立即评分。"),
    )

    assert response.status_code == 200
    assert response.json()["assessment"] is None
    assert ai_client.app.state.assessment_provider.batch_calls == 0


def test_completed_session_uses_one_batch_call(ai_client, ai_session_context):
    session_id, questions = ai_session_context
    submit_all_answers(ai_client, session_id, questions)

    response = ai_client.post(f"/api/sessions/{session_id}/assessment")

    assert response.status_code == 200
    assert response.json()["status"] == "valid"
    assert response.json()["evaluated_count"] == len(questions)
    assert ai_client.app.state.assessment_provider.batch_calls == 1


def test_repeating_valid_batch_does_not_call_ai(ai_client, ai_session_context):
    session_id, questions = ai_session_context
    submit_all_answers(ai_client, session_id, questions)
    ai_client.post(f"/api/sessions/{session_id}/assessment")

    second = ai_client.post(f"/api/sessions/{session_id}/assessment")

    assert second.status_code == 200
    assert ai_client.app.state.assessment_provider.batch_calls == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_api.py -k "does_not_call_ai or_one_batch_call or_repeating_valid_batch" -q`

Expected: FAIL because answer submission still calls the per-answer evaluator and the batch route does not exist.

- [ ] **Step 3: Implement save-only submission and `assess_session`**

Change `submit_answer` so it commits the `AnswerAttempt`, advances progress and returns `assessment: None`; remove per-answer evaluation from new and duplicate answer paths while keeping payload conflict handling.

Implement:

```python
def assess_session(
    db: Session,
    session_id: str,
    assessment_provider: AssessmentProvider,
) -> dict:
    """Evaluate all completed answers with one provider call."""
```

The function must load the session and questions, reject incomplete sessions with HTTP 409 data containing missing count, return stored valid results without a Provider call, create one shared `batch_id` and pending run per answer, create deterministic level-0 runs for `explicit_unknown`, omit `skipped`, call `assess_batch` exactly once for submitted cases, verify returned IDs, persist observations and aggregate states, preserve Provider error codes in pending runs, mark parser errors rejected, commit, and return `AssessmentBatchResponse` data. A retry creates new runs and a new batch ID but never a new `AnswerAttempt`.

Register `POST /api/sessions/{session_id}/assessment` and pass the app's configured Provider.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_api.py -k "does_not_call_ai or_one_batch_call or_repeating_valid_batch" -q`

Expected: all selected tests pass; zero calls occur during answer submission and exactly one occurs after completion.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services.py backend/app/main.py backend/tests/conftest.py backend/tests/test_api.py
git commit -m "feat: score completed sessions in one batch"
```

### Task 4: Cover statuses, failures, retry and report integration

**Files:**
- Modify: `backend/app/services.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `assess_session` and existing report aggregation.
- Produces: correct `submitted`、`explicit_unknown`、`skipped`、invalid evidence and Provider failure behavior.

- [ ] **Step 1: Write failing tests**

```python
def test_explicit_unknown_is_level_zero_and_skipped_is_not_scored(
    ai_client, ai_session_context
):
    session_id, questions = ai_session_context
    submit_answer_with_status(ai_client, session_id, questions[0], "explicit_unknown", "不知道")
    submit_answer_with_status(ai_client, session_id, questions[1], "skipped", "")
    submit_remaining_submitted(ai_client, session_id, questions[2:])

    response = ai_client.post(f"/api/sessions/{session_id}/assessment")
    report = ai_client.get(f"/api/sessions/{session_id}/report").json()

    assert response.json()["status"] == "valid"
    assert response.json()["evaluated_count"] == len(questions) - 1
    assert report["assessment_status_counts"]["valid"] == len(questions) - 1


def test_failed_batch_preserves_answers_and_retry_reuses_them(
    failing_batch_client, failing_batch_session_context
):
    session_id, questions = failing_batch_session_context
    submit_all_answers(failing_batch_client, session_id, questions)

    first = failing_batch_client.post(f"/api/sessions/{session_id}/assessment")
    second = failing_batch_client.post(f"/api/sessions/{session_id}/assessment")

    assert first.json()["status"] == "pending"
    assert second.json()["status"] == "valid"
    assert count_answers(failing_batch_client, session_id) == len(questions)
    assert failing_batch_client.app.state.assessment_provider.batch_calls == 2


def test_invalid_evidence_is_retained_but_report_excludes_it(
    invalid_batch_client, invalid_batch_session_context
):
    session_id, questions = invalid_batch_session_context
    submit_all_answers(invalid_batch_client, session_id, questions)

    response = invalid_batch_client.post(f"/api/sessions/{session_id}/assessment")
    report = invalid_batch_client.get(f"/api/sessions/{session_id}/report").json()

    assert response.json()["status"] == "invalid"
    assert any(
        item["validity"] == "invalid"
        for item in response.json()["assessments"][0]["assessment"]["rubric_items"]
    )
    assert report["valid_evidence_count"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_api.py -k "explicit_unknown or failed_batch or invalid_evidence" -q`

Expected: FAIL until the batch service handles the statuses and report selection.

- [ ] **Step 3: Implement and verify status rules**

Update fake Providers with `batch_calls`, failure and invalid modes. Enforce:

```text
submitted        -> included in one batch model call
explicit_unknown -> deterministic valid level 0, no separate model call
skipped          -> no AssessmentRun and no score
Provider failure -> pending with exact Provider error code
invalid evidence -> invalid with preserved Rubric observations
```

Update `get_report` to select the newest run per answer, count `pending/valid/invalid/rejected`, include only valid observations and preserve the no-0–100 contract.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_api.py -k "explicit_unknown or failed_batch or invalid_evidence" -q`

Expected: all selected tests pass and retry leaves the answer count unchanged.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services.py backend/tests/conftest.py backend/tests/test_api.py
git commit -m "test: cover batch assessment statuses and retry"
```

### Task 5: Update frontend API types and interview completion flow

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/app/interview/[id]/page.tsx`
- Test: `frontend/lib/assessment-types.test.ts`

**Interfaces:**
- Consumes: `POST /api/sessions/{session_id}/assessment` and `AssessmentBatchResponse`.
- Produces: `assessSession(sessionId)` and a UI that does not expect per-answer assessment data.

- [ ] **Step 1: Write the failing TypeScript contract test**

```ts
import type { AssessmentBatchResponse } from "./api";

const batchResponse: AssessmentBatchResponse = {
  status: "valid",
  batch_id: "batch-1",
  evaluated_count: 2,
  total_count: 3,
  assessments: [],
};

void batchResponse;
```

- [ ] **Step 2: Run the type check to verify it fails**

Run: `npx tsc --noEmit`

Expected: FAIL because `AssessmentBatchResponse` and `assessSession` are not defined.

- [ ] **Step 3: Implement the API contract and UI flow**

Add the batch response types and:

```ts
export function assessSession(sessionId: string) {
  return request<AssessmentBatchResponse>(
    "/api/sessions/" + sessionId + "/assessment",
    { method: "POST", body: JSON.stringify({}) },
  );
}
```

In the interview page, remove per-answer AI scoring; show “回答已保存”. After the final answer is saved and the session is completed, set stages to `收集回答` and `请求模型`, call `assessSession` once, then show `校验证据` and `生成报告` before navigating. On failure keep the completed session and show “回答已保存，评估未完成” with a retry button that calls only `assessSession`. Non-final answers clear the editor and load the next question without any Provider request.

- [ ] **Step 4: Run type check and build**

Run from `frontend`: `npx tsc --noEmit`

Expected: PASS.

Run: `npm run build`

Expected: Next.js production build exits with code 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/api.ts frontend/app/interview/[id]/page.tsx frontend/lib/assessment-types.test.ts
git commit -m "feat: trigger assessment after interview completion"
```

### Task 6: Add report retry entry and document the one-call behavior

**Files:**
- Modify: `frontend/app/report/[id]/page.tsx`
- Modify: `README.md`
- Test: `frontend/lib/assessment-types.test.ts`

**Interfaces:**
- Consumes: `assessSession` and report `assessment_status_counts`.
- Produces: report-page retry action and user-facing batch scoring instructions.

- [ ] **Step 1: Write the failing type contract assertion**

```ts
const retryableStatuses = ["pending", "invalid", "rejected"] as const;
const isRetryable = (status: string) =>
  retryableStatuses.includes(status as (typeof retryableStatuses)[number]);

if (!isRetryable("pending")) throw new Error("pending must be retryable");
```

- [ ] **Step 2: Run the check to verify the new report contract is absent**

Run: `npx tsc --noEmit`

Expected: FAIL if the report retry implementation references missing batch fields or helpers.

- [ ] **Step 3: Implement retry and documentation**

When the report contains pending, invalid or rejected assessment counts, render “重新生成评估”. The button calls `assessSession(sessionId)`, disables itself, reloads the report on success and displays the returned error reason on failure. Keep valid-evidence and no-0–100 wording. Update `README.md` with: “回答阶段不会调用评分模型；一场面试全部完成后只进行一次批量评分。模型失败不会删除回答，用户可以重新生成评估。” Document that `NEXT_PUBLIC_API_URL` points to the backend port and the key remains backend-only.

- [ ] **Step 4: Run frontend verification**

Run from `frontend`: `npx tsc --noEmit` and then `npm run build`.

Expected: both commands exit with code 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/report/[id]/page.tsx frontend/lib/assessment-types.test.ts README.md
git commit -m "docs: explain batch assessment retry flow"
```

### Task 7: Complete verification and finish the branch safely

**Files:**
- Verify: all changed backend and frontend files

**Interfaces:**
- Consumes: completed batch assessment implementation.
- Produces: verified local branch with no accidental secret or generated-file changes.

- [ ] **Step 1: Run the complete backend suite**

Run: `python -m pytest backend/tests -q`

Expected: exit code 0 and zero failed tests.

- [ ] **Step 2: Run frontend checks sequentially**

Run from `frontend`:

```powershell
npx tsc --noEmit
npm run build
```

Expected: both commands exit with code 0; do not run them concurrently because Next.js type generation can race with TypeScript checking.

- [ ] **Step 3: Inspect the final diff and scan for keys**

Run:

```powershell
git diff --check
git status --short --branch
git diff --stat HEAD~7..HEAD
$hits = @(rg -n --hidden --glob '!**/.git/**' --glob '!**/node_modules/**' --no-ignore-vcs 'sk-[A-Za-z0-9]{20,}' . 2>$null)
Write-Output "possible_api_key_matches=$($hits.Count)"
```

Expected: no whitespace errors, only intentional source/docs changes, and `possible_api_key_matches=0`.

- [ ] **Step 4: Commit only any final documentation adjustment**

If a tracked source or documentation change remains after checks:

```bash
git add README.md docs/superpowers/specs/2026-08-31-batch-ai-assessment-design.md docs/superpowers/plans/2026-08-31-batch-ai-assessment.md
git commit -m "docs: finalize batch assessment implementation notes"
```

- [ ] **Step 5: Use finishing-a-development-branch**

The repository is a normal named branch `codex/resume-pdf-docx` with base branch `main`. After the green suite, present exactly:

```text
Implementation complete. What would you like to do?

1. Merge back to main locally
2. Push and create a Pull Request
3. Keep the branch as-is (I'll handle it later)

Which option?
```

