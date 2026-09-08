# Graph 评分与成本观测闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不复制现有评分规则的前提下，让 Graph 面试完成后自动返回 AI Rubric 评分结果，并把 Graph 模型调用写入统一的人民币成本观测表。

**Architecture:** Graph 继续负责上下文、出题、核验和路由；最后一个事件投影提交后，由 API 层调用现有 `assess_session` 完成 AssessmentRun、RubricObservation 和 InterviewReport。Graph start/resume 外层使用现有 `capture_model_calls` / `record_model_calls`，只读 state 接口不触发模型采集。

**Tech Stack:** Python、FastAPI、LangGraph、SQLAlchemy、SQLite、pytest、Next.js/TypeScript。

## Global Constraints

- 使用现有评分引擎、Rubric 0–4 内部等级和前端 A/B/C/D 映射，不新增第二套评分算法。
- 使用 ponytail：不引入队列、依赖或新的 Agent 抽象；异步任务和实时 SSE 另立子项目。
- 每次代码修改后重启 backend/frontend，并确认 `/health` 与 `/console` 返回 200。
- 保留工作区内与本计划无关的已有未提交改动，不清理、不重置、不自动推送 GitHub。
- 所有生产代码先写会失败的测试，再实现最小修改。

---

### Task 1: Graph 完成后自动触发现有评分链路

**Files:**
- Modify: `backend/app/interview_graph_api.py` (`resume_graph` 完成态返回路径)
- Modify: `backend/app/main.py` (`graph_start`、`graph_resume` 路由)
- Test: `backend/tests/test_graph_scoring_observability.py`

**Interfaces:**
- `resume_graph(..., on_completed: Callable[[], Mapping] | None = None) -> dict`
- 完成态响应新增可选 `assessment` 字段，值为现有 `AssessmentBatchResponse` 字典；未完成时不添加该字段。

- [ ] **Step 1: Write the failing test**

在新测试中创建本地 Graph session，注入稳定的六节点 Graph agents 和可重复的本地 AssessmentProvider，提交六个回答，断言最后一次 `/graph/resume` 返回：

```python
assert response.json()["status"] == "completed"
assert response.json()["assessment"]["status"] == "valid"
assert response.json()["assessment"]["evaluated_count"] == 6
```

同时查询数据库，断言存在有效 `AssessmentRun` 与 `InterviewReport`；再次用新 submission id resume，断言 assessment provider 的 batch 调用次数不增加。

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_graph_scoring_observability.py::test_completed_graph_resume_returns_assessment -q`

Expected: FAIL because Graph response currently has no `assessment` field and `/graph/resume` does not invoke `assess_session`.

- [ ] **Step 3: Write minimal implementation**

在 `resume_graph` 内增加一个小的完成回调包装：普通提交、重复提交和已完成短路都先得到公开状态；当状态为 `completed` 且传入 `on_completed` 时执行回调并把结果放到 `response["assessment"]`。在 `main.py` 中传入：

```python
lambda: assess_session(db, session_id, app.state.assessment_provider)
```

回调只在事件投影提交后执行；已有 `assess_session` 的幂等逻辑负责重复恢复，不新增评分算法。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_graph_scoring_observability.py::test_completed_graph_resume_returns_assessment -q`

Expected: PASS，且数据库中的报告状态为 `ready` 或 `partial`。

- [ ] **Step 5: Commit**

```bash
git add backend/app/interview_graph_api.py backend/app/main.py backend/tests/test_graph_scoring_observability.py
git commit -m "feat: close graph assessment loop"
```

### Task 2: Graph 模型调用进入成本观测

**Files:**
- Modify: `backend/app/main.py` (`graph_start`、`graph_resume`)
- Test: `backend/tests/test_graph_scoring_observability.py`

**Interfaces:**
- Graph start/resume 的业务行为不变；每次模型调用写入 `LlmCallTrace.session_id`。
- `/api/observability/summary?session_id=<id>` 能返回 Graph 调用的 `call_kind`、Token、`cost_cny` 和 `latency_ms`。

- [ ] **Step 1: Write the failing test**

注入会调用 `emit_model_call` 的测试 Graph agents，配置一个人民币模型价格，调用 Graph start 和一次 resume，断言：

```python
rows = list(db.scalars(select(LlmCallTrace).where(LlmCallTrace.session_id == session_id)))
assert {row.call_kind for row in rows} >= {"planner", "interviewer", "evidence_verifier"}
assert all(row.cost_cny is not None for row in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_graph_scoring_observability.py::test_graph_model_calls_are_observed -q`

Expected: FAIL because Graph endpoints currently do not establish `capture_model_calls`，模型记录不会落库。

- [ ] **Step 3: Write minimal implementation**

将 `graph_start` 和 `graph_resume` 的调用包在已有 `observed_model_call(db, session_id)` 上下文中；`graph_state` 保持只读，不包裹观测上下文。评分回调同样位于 `graph_resume` 的观测上下文内，使完成时的 assessment 调用也带 session_id。

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_graph_scoring_observability.py::test_graph_model_calls_are_observed -q`

Expected: PASS，且 summary 的 `known_cost_cny` 大于 0。

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_graph_scoring_observability.py
git commit -m "feat: observe graph model costs"
```

### Task 3: 集成验证与交付

**Files:**
- Verify: `backend/tests/`, `frontend/`, `backend/scripts/eval_interview_graph.py`
- Modify: `docs/superpowers/plans/2026-09-08-graph-scoring-observability.md`（仅勾选完成项）

- [ ] **Step 1: Run focused backend tests**

Run: `python -m pytest backend/tests/test_graph_scoring_observability.py backend/tests/test_interview_graph_e2e_recovery.py -q`

- [ ] **Step 2: Run full verification**

Run: `python -m pytest backend/tests -q`、`npm.cmd --prefix frontend test`、`python backend/scripts/eval_interview_graph.py --cases backend/tests/fixtures/interview_graph_cases.json` 和 `git diff --check`。

- [ ] **Step 3: Restart services and verify health**

重启监听 8010 和 3000 的现有进程，确认 `GET http://127.0.0.1:8010/health` 与 `GET http://127.0.0.1:3000/console` 均为 200。

- [ ] **Step 4: Request code review and commit plan update**

使用独立审查检查完成态幂等、评分失败可重试、成本 session 归属和未改动旧模式；通过后勾选计划并提交文档更新。
