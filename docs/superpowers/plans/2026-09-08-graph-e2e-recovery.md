# Graph 真实端到端验收与可恢复性增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Graph 面试的模型降级、重复提交、断点恢复和完成态在 API 与前端层都可验证、可解释且不重复计费。

**Architecture:** 保持现有 LangGraph checkpoint 与 SQLAlchemy 业务投影边界，只在公开状态适配层派生 `degraded` 标记，在 resume 入口增加“已完成直接返回”守卫，并用 API 级 fake provider 测试真实调用链。前端复用现有 Graph 状态轮询/SSE，只增加降级提示，不引入新依赖或新表。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2、LangGraph、pytest、Next.js 15、React 19。

## Global Constraints

- `session_id` 必须作为 LangGraph `thread_id`。
- Graph State 不得包含 API Key、ORM 对象、完整简历、原始模型响应或思维链。
- 只有模型/provider/解析错误允许进入降级；其他 RuntimeError 必须继续抛出并回滚。
- 重复 `client_submission_id` 不得再次 invoke Graph、写回答或产生模型调用。
- 已完成 Graph 会话的后续 resume 必须返回稳定完成态，不新增回答。
- SSE 只发送白名单事件，不发送回答原文、错误堆栈或 prompt。
- 每批代码修改后重启前后端，并验证 `GET /health` 与 `/console` 均返回 200。
- 使用 ponytail 原则，不新增依赖，不修改 classic/dialog 业务。

---

### Task 1: 完成态守卫与 API 幂等验收

**Files:**
- Modify: `backend/app/interview_graph_api.py`
- Create: `backend/tests/test_interview_graph_e2e_recovery.py`

**Interfaces:**
- `resume_graph(...) -> dict` 在 checkpoint 状态为 `completed` 时直接返回 `graph_session_view`。
- API 测试通过 `create_app` 和 fake provider 覆盖 start/resume/duplicate/completed。

- [x] **Step 1: Write failing API tests**

```python
def test_completed_graph_resume_is_stable_and_does_not_add_answer(tmp_path):
    client, session_id = graph_client(tmp_path)
    complete_six_nodes(client, session_id)
    before = count_answers(client, session_id)
    response = client.post(
        f"/api/sessions/{session_id}/graph/resume",
        json={"answer_text": "late answer", "client_submission_id": "late-1"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert count_answers(client, session_id) == before
```

```python
def test_duplicate_graph_resume_returns_state_without_second_agent_call(tmp_path):
    client, session_id = graph_client(tmp_path)
    client.post(f"/api/sessions/{session_id}/graph/start")
    first = client.post(
        f"/api/sessions/{session_id}/graph/resume",
        json={"answer_text": "同一回答", "client_submission_id": "same-1"},
    )
    second = client.post(
        f"/api/sessions/{session_id}/graph/resume",
        json={"answer_text": "同一回答", "client_submission_id": "same-1"},
    )
    assert second.status_code == 200
    assert second.json()["current_question"] == first.json()["current_question"]
```

- [x] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest backend/tests/test_interview_graph_e2e_recovery.py -q`

Expected: the completed-resume test fails because the endpoint tries to resume an already completed interrupt.

- [x] **Step 3: Add the minimal completed checkpoint guard**

Read `graph.get_state(graph_config(session.id)).values` after the active-session lookup. If `status == "completed"`, return `_public_state(...)` before the `AnswerAttempt` lookup and before invoking `Command(resume=...)`. Keep the existing same-ID/different-answer 409 behavior for non-completed sessions.

- [x] **Step 4: Run focused and existing graph suites**

Run: `python -m pytest backend/tests/test_interview_graph_e2e_recovery.py backend/tests/test_interview_graph.py backend/tests/test_interview_graph_api.py -q`

Expected: PASS with no change to RuntimeError rollback behavior.

- [x] **Step 5: Restart services and verify API health**

Restart ports 8010 and 3000 using the README commands, then verify `GET http://127.0.0.1:8010/health` and `GET http://127.0.0.1:3000/console` both return 200.

- [x] **Step 6: Commit the API recovery guard**

```bash
git add backend/app/interview_graph_api.py backend/tests/test_interview_graph_e2e_recovery.py
git commit -m "fix: keep completed graph resumes stable"
```

### Task 2: 公开降级状态并在前端显示可操作提示

**Files:**
- Modify: `backend/app/interview_graph_projection.py`
- Modify: `frontend/lib/interview-graph.ts`
- Modify: `frontend/app/interview/[id]/page.tsx`
- Create: `frontend/lib/interview-graph-recovery.test.ts`

**Interfaces:**
- `graph_session_view(...)` returns `degraded: boolean` derived only from safe `state_updated` events.
- `normalizeGraphState(...)` preserves `degraded` and exposes it to the interview page.

- [x] **Step 1: Write failing frontend state tests**

```ts
const view = normalizeGraphState({
  status: "awaiting_answer",
  degraded: true,
  nodes: [],
  current_question: { prompt: "保底问题" },
});
if (view.degraded !== true) throw new Error("degraded state must be preserved");
```

- [x] **Step 2: Run the focused test and confirm RED**

Run: `node --experimental-strip-types frontend/lib/interview-graph-recovery.test.ts`

Expected: FAIL because Graph state normalization has no degraded field.

- [x] **Step 3: Derive and render the safe degraded flag**

In the backend, scan only `graph_events` for `event_kind == "state_updated"` and `payload.degraded == true`; never copy the payload body to the public response. In the frontend, carry the boolean through normalization and render one muted banner above the answer dock: `模型暂不可用，已切换保底问题；回答仍会保存。` Do not show provider codes or exception text.

- [x] **Step 4: Run frontend and backend regression tests**

Run: `node --experimental-strip-types frontend/lib/interview-graph-recovery.test.ts`

Run: `npm.cmd --prefix frontend test`

Run: `python -m pytest backend/tests/test_interview_graph_e2e_recovery.py backend/tests/test_interview_graph_projection.py -q`

Expected: PASS.

- [x] **Step 5: Restart services and verify the visible entry**

Restart both services, then verify `/console` and the interview route return 200. The banner appears only when `degraded=true`; normal Graph sessions keep the existing UI.

- [x] **Step 6: Commit the safe user feedback**

```bash
git add backend/app/interview_graph_projection.py frontend/lib/interview-graph.ts frontend/app/interview/[id]/page.tsx frontend/lib/interview-graph-recovery.test.ts
git commit -m "feat: show safe graph degradation status"
```

### Task 3: 阶段验收与运行文档

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-09-08-graph-e2e-recovery.md`

- [x] **Step 1: Run the complete verification set**

Run: `python -m pytest backend/tests -q`

Run: `npm.cmd --prefix frontend test`

Run: `python backend/scripts/eval_interview_graph.py --cases backend/tests/fixtures/interview_graph_cases.json`

- [x] **Step 2: Document recovery behavior**

Add one README paragraph explaining that missing model configuration uses a safe fallback question chain, duplicate submissions are idempotent, and completed Graph sessions are read-only. Keep the existing 8010/3000 startup commands as the only local startup path.

- [x] **Step 3: Restart services and final health check**

Restart both services after all code changes and verify backend/frontend status 200.

- [x] **Step 4: Mark the plan complete and commit documentation**

```bash
git add README.md docs/superpowers/plans/2026-09-08-graph-e2e-recovery.md
git commit -m "docs: verify graph recovery workflow"
```
