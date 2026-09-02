# Interview History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local single-user interview history page that lists every saved interview, supports continuing unfinished sessions, opening or retrying reports, and safely removing one record from the visible history.

**Architecture:** Reuse `interview_sessions` as the history source of truth and read project names, answer counts, scoring status, and report summary from existing related tables. Extend the existing history endpoint with the fields the UI needs, add a soft-delete endpoint backed by `archived_at`, and build a small `/history` page that links to the existing interview and report pages.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, Pydantic, Next.js App Router, React, TypeScript, existing `mint-*` CSS components, pytest, Node strip-types contract tests.

## Global Constraints

- This is a local single-user Alpha; do not add accounts, permissions, search, filters, pagination, trend charts, or a second history table.
- The existing `interview_sessions.archived_at` field is the deletion marker; `DELETE` hides a record from normal UI flows and does not physically delete answers, assessments, reports, or profile data.
- History is ordered by `created_at DESC, session_id DESC` and must keep all previous sessions instead of replacing older records.
- The list must show project name, completion count, report status, strengths count, and gaps count; missing report counts are `null` and render as `—`, never as zero.
- Do not show an uncalibrated 0–100 total score or internal evaluation terms in the UI.
- Use direct, natural Chinese labels. The home page already uses section numbers, so do not add process phrases such as “先做这一步” or “随时可以修改”.
- API errors must use the existing `ApiError` path on the frontend and the existing `NotFoundError` path on the backend.
- Do not add a database migration because the required `archived_at` column already exists.
- Do not run `git push`; each task may create a local commit only.

---

### Task 1: Extend the persisted history summary

**Files:**
- Modify: `backend/app/schemas.py:InterviewHistoryItem`
- Modify: `backend/app/services.py:list_interview_history`
- Create: `backend/tests/test_interview_history.py`

**Interfaces:**
- Consumes: existing `InterviewSession`, `ResumeProject`, `InterviewTarget`, `AnswerAttempt`, `InterviewReport`, and `OperationJob` rows.
- Produces: `list_interview_history(db: Session) -> list[dict]` entries with `project_name`, `completed`, `total`, `report_status`, `analysis_status`, `strength_count`, and `gap_count`.

- [ ] **Step 1: Write the failing backend history tests**

Use the existing `ai_client`, `create_test_session`, and `submit_all_answers` helpers. Add assertions for a fresh session and a completed session:

```python
def test_history_contains_project_name_and_null_report_counts(ai_client, ai_session_context):
    session_id, _ = ai_session_context
    response = ai_client.get("/api/interviews/history")

    assert response.status_code == 200
    item = next(row for row in response.json() if row["session_id"] == session_id)
    assert item["project_name"] == "企业知识库问答 Agent"
    assert item["completed"] == 0
    assert item["total"] == 8
    assert item["strength_count"] is None
    assert item["gap_count"] is None


def test_history_returns_report_summary_counts(ai_client, ai_session_context):
    session_id, questions = ai_session_context
    submit_all_answers(ai_client, session_id, questions, "history-summary")
    assert ai_client.post(f"/api/sessions/{session_id}/assessment").status_code == 200

    item = next(
        row for row in ai_client.get("/api/interviews/history").json()
        if row["session_id"] == session_id
    )
    report = ai_client.get(f"/api/sessions/{session_id}/report").json()
    assert item["strength_count"] == len(report["strengths"])
    assert item["gap_count"] == len(report["gaps"])
```

Add a separate test that creates two sessions and asserts the returned IDs are ordered newest first.

- [ ] **Step 2: Run the focused tests and verify the contract fails**

Run:

```powershell
python -m pytest backend/tests/test_interview_history.py -q
```

Expected: FAIL because the response model and service do not yet return the three new summary fields.

- [ ] **Step 3: Add the response fields and query the summary**

Extend `InterviewHistoryItem` with:

```python
project_name: str | None = None
strength_count: int | None = None
gap_count: int | None = None
```

In `list_interview_history`, load `ResumeProject` using `session.resume_project_id`, parse the latest report's `report_json` only when a report exists, and compute:

```python
report_payload = json.loads(report.report_json) if report else None
strength_count = len(report_payload["strengths"]) if report_payload else None
gap_count = len(report_payload["gaps"]) if report_payload else None
```

Return the project name, keep existing direction and target fields, and preserve the current answer-count and newest-first behavior.

- [ ] **Step 4: Run the focused history tests**

Run:

```powershell
python -m pytest backend/tests/test_interview_history.py backend/tests/test_history_persistence.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the history summary contract**

```powershell
git add backend/app/schemas.py backend/app/services.py backend/tests/test_interview_history.py
git commit -m "feat: extend interview history summary"
```

### Task 2: Add safe single-record deletion

**Files:**
- Modify: `backend/app/services.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_interview_history.py`

**Interfaces:**
- Consumes: active `InterviewSession` rows and the existing `NotFoundError` exception.
- Produces: `archive_interview(db: Session, session_id: str) -> None` and `DELETE /api/sessions/{session_id}` returning HTTP 204.

- [ ] **Step 1: Write failing archive and visibility tests**

Add a test that submits one answer, deletes the session, checks 204, checks that history no longer includes it, and checks the answer remains in SQLite:

```python
def test_delete_hides_session_but_preserves_answers(ai_client, ai_session_context):
    session_id, questions = ai_session_context
    answer = ai_client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "question_id": questions[0]["id"],
            "client_submission_id": "archive-answer",
            "status": "submitted",
            "answer_text": "我负责了检索链路。",
        },
    )
    assert answer.status_code == 200

    response = ai_client.delete(f"/api/sessions/{session_id}")

    assert response.status_code == 204
    assert all(row["session_id"] != session_id for row in ai_client.get("/api/interviews/history").json())
    assert ai_client.get(f"/api/sessions/{session_id}").status_code == 404
    assert ai_client.delete(f"/api/sessions/{session_id}").status_code == 404

    with ai_client.app.state.session_factory() as db:
        session = db.get(InterviewSession, session_id)
        assert session.archived_at is not None
        assert db.scalar(select(func.count(AnswerAttempt.id)).where(AnswerAttempt.session_id == session_id)) == 1
```

Also assert that report lookup, answer submission, and assessment return 404 after archive, preventing a stale browser tab from changing a hidden record. Import `InterviewSession`, `AnswerAttempt`, `select`, and `func` in the test module for the SQLite preservation assertion.

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
python -m pytest backend/tests/test_interview_history.py -q
```

Expected: FAIL because the delete route is absent and archived sessions are still returned.

- [ ] **Step 3: Implement the archive service and route**

Add the service function:

```python
def archive_interview(db: Session, session_id: str) -> None:
    session = db.get(InterviewSession, session_id)
    if session is None or session.archived_at is not None:
        raise NotFoundError("session not found")
    session.archived_at = utc_now()
    db.commit()
```

Filter `InterviewSession.archived_at.is_(None)` in `list_interview_history`. Register this route in `create_app`:

```python
@app.delete("/api/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, db: Session = Depends(get_db)):
    archive_interview(db, session_id)
    return None
```

Use an active-session guard in `get_session_view`, `get_report`, `submit_answer`, and `assess_session`. Keep related rows untouched.

- [ ] **Step 4: Run focused and full backend tests**

Run:

```powershell
python -m pytest backend/tests/test_interview_history.py -q
python -m pytest backend/tests -q
```

Expected: both commands PASS.

- [ ] **Step 5: Commit the archive endpoint**

```powershell
git add backend/app/main.py backend/app/services.py backend/tests/test_interview_history.py
git commit -m "feat: archive interview history records"
```

### Task 3: Build the `/history` page and API client

**Files:**
- Modify: `frontend/lib/api.ts`
- Create: `frontend/app/history/page.tsx`
- Create: `frontend/lib/history-page.test.ts`
- Modify: `frontend/package.json`

**Interfaces:**
- Consumes: `GET /api/interviews/history`, `DELETE /api/sessions/{session_id}`, `/interview/[id]`, and `/report/[id]`.
- Produces: `InterviewHistoryItem`, `getInterviewHistory() -> Promise<InterviewHistoryItem[]>`, and `deleteInterview(sessionId: string) -> Promise<void>`.

- [ ] **Step 1: Write the failing frontend contract test**

Check the API client, route copy, actions, and links:

```ts
import { readFileSync } from "node:fs";

const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/history/page.tsx", import.meta.url), "utf8");

for (const token of ["InterviewHistoryItem", "getInterviewHistory", "deleteInterview", "/api/interviews/history", "/api/sessions/"]) {
  if (!api.includes(token)) throw new Error(`history API contract missing: ${token}`);
}
for (const token of ["面试记录", "继续面试", "查看结果", "重新生成", "删除记录", "再试一次", "还没有面试记录", "/interview/", "/report/"]) {
  if (!page.includes(token)) throw new Error(`history page contract missing: ${token}`);
}
if (/0～100|冻结事实|可信边界|Evidence Rail|Rubric/.test(page)) {
  throw new Error("internal evaluation copy leaked into history page");
}
```

- [ ] **Step 2: Run the focused frontend test and verify it fails**

Run:

```powershell
npm run test:history
```

Expected: FAIL because the route, API types, helpers, and script do not yet exist.

- [ ] **Step 3: Add history types and request helpers**

Add this client type and helpers:

```ts
export type InterviewHistoryItem = {
  session_id: string;
  status: string;
  project_name: string | null;
  direction: string | null;
  target_title: string | null;
  completed: number;
  total: number;
  report_status: string | null;
  analysis_status: string | null;
  strength_count: number | null;
  gap_count: number | null;
  created_at: string;
  updated_at: string;
};

export function getInterviewHistory() {
  return request<InterviewHistoryItem[]>("/api/interviews/history");
}

export function deleteInterview(sessionId: string) {
  return request<void>(`/api/sessions/${sessionId}`, { method: "DELETE" });
}
```

Add `test:history` as `node --experimental-strip-types lib/history-page.test.ts` and include it in the existing `test` script.

- [ ] **Step 4: Implement page states and actions**

Create a client page with `items`, `loading`, `error`, and `deletingId` state. Use existing `mint-shell`, `mint-header`, `mint-card`, `mint-button`, `mint-alert`, and `mint-note` classes. Use these action rules:

```ts
function actionFor(item: InterviewHistoryItem) {
  if (item.status !== "completed") return { href: `/interview/${item.session_id}`, label: "继续面试" };
  const hasReport = item.report_status === "ready" || item.report_status === "partial";
  return { href: `/report/${item.session_id}`, label: hasReport ? "查看结果" : "重新生成" };
}
```

Render `strength_count` and `gap_count` as `count == null ? "—" : count`. Confirm with `window.confirm("确定删除这条面试记录吗？")` before calling `deleteInterview`. Keep the card when deletion fails, show an empty-state link to `/`, and show a retry action when the list request fails. Do not call a model endpoint from this page.

- [ ] **Step 5: Run the focused frontend test**

Run:

```powershell
npm run test:history
```

Expected: PASS.

- [ ] **Step 6: Commit the history page**

```powershell
git add frontend/lib/api.ts frontend/app/history/page.tsx frontend/lib/history-page.test.ts frontend/package.json
git commit -m "feat: add interview history page"
```

### Task 4: Add navigation, responsive styles, and local documentation

**Files:**
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/app/console/page.tsx`
- Modify: `frontend/app/globals.css`
- Modify: `frontend/lib/modern-ui.test.ts`
- Modify: `README.md`

**Interfaces:**
- Consumes: the `/history` route from Task 3 and the existing mint layout.
- Produces: visible top-navigation links from the home page and model console, plus a responsive single-column history layout.

- [ ] **Step 1: Write failing navigation and style assertions**

Extend the UI contract test:

```ts
const consolePage = readFileSync(new URL("../app/console/page.tsx", import.meta.url), "utf8");
for (const source of [homePage, consolePage]) {
  if (!source.includes('href="/history"')) throw new Error("missing interview history navigation");
}
for (const token of ["mint-history", "mint-history-card", "mint-history-actions"]) {
  if (!css.includes(token)) throw new Error(`missing history style: ${token}`);
}
```

- [ ] **Step 2: Run the focused UI test and verify it fails**

Run:

```powershell
npm run test:ui
```

Expected: FAIL because the two navigation bars and history-specific classes do not exist.

- [ ] **Step 3: Add the navigation links and styles**

Add the exact label `面试记录` in both existing navigation bars:

```tsx
<a className="mint-nav-link" href="/history">面试记录</a>
```

Add compact history styles for the card grid, metadata row, status pill, action row, and mobile layout. Keep visible focus states and the existing reduced-motion rules. Do not introduce a table, sidebar, dashboard chart, or new color system.

- [ ] **Step 4: Document local use**

Add this user-facing instruction to `README.md`:

```markdown
打开 `http://localhost:3000/history` 可以查看本机保存的面试记录。未完成的记录可以继续，完成且有报告的记录可以查看结果，评分失败的记录可以重新生成。删除记录只会从历史列表中隐藏，不会在 Alpha 阶段物理删除回答和报告。
```

- [ ] **Step 5: Run all frontend tests and the production build**

Run:

```powershell
npm test
npm run build
```

Expected: all frontend tests pass and the build lists `/history` as a generated route.

- [ ] **Step 6: Commit navigation and documentation**

```powershell
git add frontend/app/page.tsx frontend/app/console/page.tsx frontend/app/globals.css frontend/lib/modern-ui.test.ts README.md
git commit -m "feat: add interview history navigation"
```

### Task 5: Complete verification and handoff

**Files:**
- Test: `backend/tests/`
- Test: `frontend/`

- [ ] **Step 1: Run the complete verification suite**

Run from the repository root:

```powershell
python -m pytest backend/tests -q
Set-Location frontend
npm test
npm run build
Set-Location ..
git diff --check
```

Expected: backend tests pass, frontend tests pass, production build contains `/history`, and `git diff --check` reports no whitespace errors. Windows LF/CRLF conversion notices are acceptable.

- [ ] **Step 2: Inspect the final working tree and secret safety**

Run:

```powershell
git status --short
git log -6 --oneline
```

Confirm the history commits are local, no GitHub push was run, no `sk-...` API key appears in the diff, and unrelated existing working-tree changes remain untouched.
