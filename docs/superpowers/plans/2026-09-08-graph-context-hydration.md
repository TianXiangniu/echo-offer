# Graph 项目事实上下文与降级链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Graph 面试从已确认的项目分析快照读取可验证事实，并在模型不可用时安全降级到可继续的六节点问题链。

**Architecture:** 在创建 Graph 会话时只抽取已确认/提取的项目事实和必要项目字段，写入 LangGraph 初始 State；不把简历原文、API Key 或模型响应带入 State。Planner、Interviewer、Verifier 的模型异常分别回退到程序生成的六节点计划、节点开场题和“待补充”核验结果，保留现有 checkpoint 与业务投影事务边界。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy 2、LangGraph、Pydantic 2、pytest。

## Global Constraints

- `session_id` 必须作为 LangGraph `thread_id`。
- Graph State 不得包含 API Key、ORM 对象、完整简历、原始模型响应或思维链。
- Planner、Interviewer、Verifier 不得输出等级；Evaluator 只在面试完成后运行。
- 每个计划固定 6 个节点；每节点最多 2 次追问。
- 业务写入必须幂等；checkpoint 失败时不得确认用户回答已提交。
- 每批代码修改后重启前后端，并验证 `GET /health` 与 `/console` 均返回 200。
- 使用 ponytail 原则，不新增依赖，不重构无关模块。

---

### Task 1: 从已确认分析快照构建安全的 Graph 上下文

**Files:**
- Modify: `backend/app/interview_graph_api.py`
- Create: `backend/tests/test_interview_graph_context.py`

**Interfaces:**
- Produces: `build_graph_context(project: ResumeProject, analysis: ResumeProjectAnalysis | None) -> dict`
- Consumes: `ResumeProject.analysis_id` 和 `ResumeProjectAnalysis.analysis_json`

- [x] **Step 1: Write the failing context tests**

```python
def test_graph_context_keeps_only_confirmed_project_facts():
    context = build_graph_context(project, analysis_with_facts())
    assert context["verified_facts"] == [{"fact_id": "f1", "field": "latency", "value": "P95 降低 20%"}]
    assert "resume_text" not in json.dumps(context, ensure_ascii=False)
    assert "api_key" not in json.dumps(context, ensure_ascii=False)
```

```python
def test_graph_context_falls_back_to_confirmed_project_fields():
    context = build_graph_context(project, None)
    assert context["verified_facts"]
    assert context["project"]["name"] == project.project_name
```

- [x] **Step 2: Run the focused tests and confirm RED**

Run: `python -m pytest backend/tests/test_interview_graph_context.py -q`

Expected: FAIL because `build_graph_context` does not exist.

- [x] **Step 3: Implement minimal safe context hydration**

Load the analysis row by `project.analysis_id`. Keep only facts whose status is `extracted` or `confirmed`, copy `fact_id`, `field`, `value`, and at most the first three evidence quotes; strip whitespace and cap each value at 500 characters. If no eligible facts exist, create facts from the eight confirmed `ResumeProject` text fields with deterministic IDs such as `project:tech_stack`. Never copy `resume_text`, API settings, or the full analysis JSON.

- [x] **Step 4: Run focused and graph API tests**

Run: `python -m pytest backend/tests/test_interview_graph_context.py backend/tests/test_interview_graph_api.py -q`

Expected: PASS.

- [x] **Step 5: Commit context hydration**

```bash
git add backend/app/interview_graph_api.py backend/tests/test_interview_graph_context.py
git commit -m "feat: hydrate graph interviews with verified project facts"
```

### Task 2: 为模型异常增加安全的程序侧降级

**Files:**
- Modify: `backend/app/interview_graph.py`
- Modify: `backend/app/interview_graph_types.py`
- Create: `backend/tests/test_interview_graph_fallbacks.py`

**Interfaces:**
- Produces: `fallback_interview_plan(state) -> InterviewPlan`
- Produces: `fallback_interviewer_turn(state) -> dict`
- Produces: `fallback_evidence_verification(state) -> EvidenceVerification`

- [x] **Step 1: Write failing fallback tests**

```python
def test_planner_failure_still_returns_six_node_plan():
    plan = fallback_interview_plan({"project": {"name": "RAG Agent"}, "verified_facts": []})
    assert len(plan.nodes) == 6
    assert {node.kind for node in plan.nodes} == set(REQUIRED_PLAN_KINDS)
```

```python
def test_verifier_failure_does_not_claim_coverage():
    result = fallback_evidence_verification({})
    assert result.route == "insufficient"
    assert result.confidence == 0
```

- [x] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest backend/tests/test_interview_graph_fallbacks.py -q`

Expected: FAIL because the fallback helpers do not exist.

- [x] **Step 3: Implement exception boundaries in graph nodes**

Use a fixed six-node plan whose opening questions reference only the project name or ask openly for missing details. Catch only model/provider/parsing exceptions around each role call: planner falls back to the fixed plan, interviewer falls back to the current node opening question, and verifier returns `insufficient` with no claims or coverage. Emit a safe `state_updated` payload with `degraded=true` and a user-facing status, without including exception text, prompts, or raw responses.

- [x] **Step 4: Run graph regression tests**

Run: `python -m pytest backend/tests/test_interview_graph_fallbacks.py backend/tests/test_interview_graph.py backend/tests/test_interview_graph_api.py -q`

Expected: PASS, including existing transactional rollback and checkpoint recovery tests.

- [x] **Step 5: Restart services and verify the degraded path**

Stop ports 8010 and 3000, start the backend and frontend with the README commands, then verify `GET http://127.0.0.1:8010/health` and `GET http://127.0.0.1:3000/console` both return 200. Use a fake agent that raises from `plan`, `ask`, and `verify` to confirm a Graph session still returns a question instead of a 500.

- [x] **Step 6: Commit fallback hardening**

```bash
git add backend/app/interview_graph.py backend/app/interview_graph_types.py backend/tests/test_interview_graph_fallbacks.py
git commit -m "fix: degrade contextual interview safely when model fails"
```
