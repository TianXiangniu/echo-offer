# LLM 可观测性与成本治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每次 LLM 请求记录并发安全的 trace、按本地人民币价格核算成本，并提供本地后台观测与筛选页面。

**Architecture:** 使用 `ContextVar` 作用域收集 Provider 内每次请求的不可变 `ModelCallRecord`，让 Provider 保持现有业务返回值，避免共享 `last_usage` 串账。调用 flow 在成功或失败后将 record 落入新的 `llm_call_traces` 表；聚合 API 只从该表计算指标，Next.js 页面复用现有 fetch/CSS 模式显示数据。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy/Alembic、SQLite、Pydantic、httpx、Next.js 15、React 19、TypeScript；不新增依赖。

## Global Constraints

- 使用 ponytail 原则：复用现有 FastAPI、SQLAlchemy、httpx、React 和 CSS；不增加外部 observability、图表或 decimal 库。
- 价格单位固定为人民币元 / 1M Token；服务端以 `Decimal` 计算，存储精度 8 位小数，界面只负责格式化。
- 任何 token 或对应价格缺失时 `cost_cny` 必须为 `NULL`，绝不能写成 `0`；调用不得因此被阻断。
- trace 绝不保存 API Key、HTTP headers、原始 prompt、原始模型输出、简历或候选人回答正文，也不保存任意异常原文。
- 保持现有业务 API 的状态、错误码、评分、追问和重试语义；观察写入失败不得覆盖模型调用的业务结果。
- 所有数据库变化均通过 Alembic 迁移；不修改已存在迁移。
- 工作区已有用户改动；只触及本计划列出的文件。除非用户明确要求，不执行 `git commit`。

---

## File structure

| 文件 | 职责 |
| --- | --- |
| `backend/app/llm_observability.py` | 请求作用域、不可变调用元数据、人民币成本计算、trace 持久化与查询聚合 |
| `backend/app/models.py` | `LlmCallTrace` ORM 模型、`ModelSetting.pricing_json` |
| `backend/alembic/versions/0017_llm_observability.py` | 新表、索引和模型价格 JSON 配置列 |
| `backend/app/providers.py` | 在 `_chat` 和连接测试处计时、提取 usage，并向当前作用域提交 record |
| `backend/app/model_settings.py`、`schemas.py` | 价格配置的验证、序列化、持久化和 API DTO |
| `backend/app/*_flow.py`、`main.py` | 为实际模型调用提供 trace 上下文并写入调用来源关联 |
| `backend/app/reporting_flow.py`、`schemas.py`、`main.py` | 观测 summary/trace/session 查询与只读路由 |
| `frontend/lib/api.ts` | 设置价格和 observability API 类型/请求函数 |
| `frontend/app/console/page.tsx` | 人民币单价配置 UI |
| `frontend/app/observability/page.tsx` | 本地模型观测页面 |
| `frontend/app/report/[id]/page.tsx` | 跳至当前会话成本明细 |
| `backend/tests/test_llm_observability.py` 等 | 成本、并发、持久化、聚合与 API 回归 |

### Task 1: Add durable pricing and trace schema

**Files:**
- Modify: `backend/app/models.py:27-52`
- Create: `backend/alembic/versions/0017_llm_observability.py`
- Create: `backend/app/llm_observability.py`
- Create: `backend/tests/test_llm_observability.py`

**Interfaces:**
- Produces `ModelPrice(model_name: str, input_price_per_million_cny: Decimal, output_price_per_million_cny: Decimal)`.
- Produces `ModelCallRecord` with `call_kind`, model metadata, usage, timing and sanitized error code.
- Produces `calculate_cost_cny(input_tokens, output_tokens, price) -> Decimal | None` and `record_model_calls(db, records, *, pricing, session_id, operation_job_id) -> int`.

- [ ] **Step 1: Write failing unit tests for pricing and a safe trace record**

```python
def test_calculate_cost_cny_requires_usage_and_both_prices():
    price = ModelPrice("model-a", Decimal("2.5"), Decimal("10"))
    assert calculate_cost_cny(1_000_000, 500_000, price) == Decimal("7.5")
    assert calculate_cost_cny(None, 500_000, price) is None
    assert calculate_cost_cny(1_000, 1_000, None) is None

def test_record_model_calls_persists_only_safe_metadata(db):
    record = ModelCallRecord.success(
        call_kind="project_analysis", provider="siliconflow", model_name="model-a",
        prompt_version="analysis-v3", input_tokens=12, output_tokens=8,
        latency_ms=34, request_bytes=99, response_bytes=88,
    )
    record_model_calls(db, [record], pricing=(), session_id=None, operation_job_id=None)
    saved = db.scalar(select(LlmCallTrace))
    assert saved.cost_cny is None
    assert "prompt" not in saved.__dict__
    assert "secret" not in repr(saved).lower()
```

- [ ] **Step 2: Run the focused test to verify RED**

Run: `python -m pytest backend/tests/test_llm_observability.py -q`

Expected: collection fails because `app.llm_observability` and `LlmCallTrace` do not yet exist.

- [ ] **Step 3: Add the smallest persistence model and migration**

Add `ModelSetting.pricing_json: Text` with default `"[]"`; do not create a separate price table because model prices are a small local settings list. Add `LlmCallTrace` with UUID primary key, `trace_id`, nullable `session_id`/`operation_job_id`, indexed `call_kind`/`model_name`/`status`/`finished_at`, nullable usage and frozen prices, `Numeric(18, 8)` `cost_cny`, and only the safe fields listed in the approved spec.

Migration requirements:

```python
op.add_column("model_settings", sa.Column("pricing_json", sa.Text(), nullable=False, server_default="[]"))
op.create_table("llm_call_traces", ...)
op.create_index("ix_llm_call_traces_finished_at", "llm_call_traces", ["finished_at"])
op.create_index("ix_llm_call_traces_session_id", "llm_call_traces", ["session_id"])
```

Do not add a server default to `llm_call_traces`; every trace must receive values deliberately.

- [ ] **Step 4: Implement price parsing, cost math and best-effort persistence**

In `llm_observability.py`, normalize model names with `strip()`, reject duplicate model names, negative prices and non-finite decimals. Implement cost only when all four token/price inputs exist. `record_model_calls` must derive the matching price from the `ModelSettingsValues.pricing` snapshot held by the caller, serialize no body content, `db.flush()`, and catch only persistence/database exceptions at its outer boundary so a trace failure cannot change the caller’s model result.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest backend/tests/test_llm_observability.py -q`

Expected: PASS; assert exact cost values, `NULL` cost behavior, frozen prices and absent sensitive columns.

### Task 2: Make Provider call accounting request-scoped and concurrency-safe

**Files:**
- Modify: `backend/app/providers.py:163-230, 543-552, 605-828`
- Modify: `backend/app/llm_observability.py`
- Modify: `backend/tests/test_providers.py`
- Modify: `backend/tests/test_llm_observability.py`

**Interfaces:**
- Consumes `capture_model_calls(trace_id: str) -> ModelCallCapture` and `emit_model_call(record)` from Task 1.
- Produces unchanged public Provider return types; `_chat` records one `ModelCallRecord` in the active capture on every success or failure.

- [ ] **Step 1: Add provider-level RED tests without changing public Provider results**

```python
def test_provider_capture_records_usage_latency_and_model_name():
    with capture_model_calls("trace-1") as capture:
        result = provider.assess(question, ANSWER, "submitted")
    assert result.level == 3
    assert capture.records[0].input_tokens == 17
    assert capture.records[0].output_tokens == 9
    assert capture.records[0].status == "succeeded"

def test_provider_capture_records_timeout_without_response_body():
    with capture_model_calls("trace-2") as capture:
        with pytest.raises(AssessmentProviderError):
            timeout_provider.assess(question, ANSWER, "submitted")
    assert capture.records[0].status == "failed"
    assert capture.records[0].error_code == "provider_timeout"
```

- [ ] **Step 2: Run provider and observability tests to verify RED**

Run: `python -m pytest backend/tests/test_providers.py backend/tests/test_llm_observability.py -q`

Expected: new capture assertions fail while pre-existing provider tests still pass.

- [ ] **Step 3: Replace shared `last_usage` with a `ContextVar` capture**

Implement `ModelCallCapture` as a small object containing a `Lock` and `records: list[ModelCallRecord]`; `emit_model_call` appends under that lock to the current `ContextVar` capture. In `_SiliconFlowClient._chat`, use `time.perf_counter_ns()` around `_request`, extract usage on success, calculate request/response byte lengths from serialized JSON and normalized content only, and emit in `finally` for every path. Pass explicit `call_kind` and prompt-version constants from each caller:

```python
_chat(payload, parse, call_kind="assessment_batch", prompt_version=ASSESSMENT_PROMPT_VERSION)
```

Delete `record_usage` and `self.last_usage`; no shared mutable request metrics may remain. Apply the same capture emission to `probe_model_connection` with `call_kind="connection_test"`.

- [ ] **Step 4: Preserve capture in assessment verification workers**

At the `ThreadPoolExecutor` call site in `assessment_flow.py`, submit each verifier with `contextvars.copy_context().run` so the parent capture is visible to worker calls. Add a two-worker test with distinct mocked usage values, then assert both records exist with their own usage and model fields.

- [ ] **Step 5: Run focused regression tests**

Run: `python -m pytest backend/tests/test_providers.py backend/tests/test_assessment_batch.py backend/tests/test_llm_observability.py -q`

Expected: PASS; existing parsing/error mapping remains unchanged and no `last_usage` references remain.

### Task 3: Persist traces from every existing LLM workflow

**Files:**
- Modify: `backend/app/resume_intake.py:219-321`
- Modify: `backend/app/followup_flow.py:126-241`
- Modify: `backend/app/feedback_flow.py:45-89`
- Modify: `backend/app/dialog_flow.py:277-420`
- Modify: `backend/app/assessment_flow.py:211-684`
- Modify: `backend/app/skills_flow.py:207-251`
- Modify: `backend/app/main.py:246-270`
- Modify: `backend/tests/test_project_analysis.py`, `test_followup.py`, `test_dialog_interview.py`, `test_assessment_batch.py`, `test_skills_wiki.py`, `test_settings_api.py`

**Interfaces:**
- Consumes `capture_model_calls` and `record_model_calls` from Tasks 1–2.
- Produces one persisted trace per actual Provider request, with the correct `session_id`, optional `operation_job_id`, `call_kind`, `trace_id` and frozen current model prices.

- [ ] **Step 1: Add one failing flow integration test for each call family**

Add fakes that return valid business responses and usage. Assert the following after each request:

```python
assert [(row.call_kind, row.status, row.session_id)] == [
    ("followup_decision", "succeeded", session_id)
]
assert row.input_price_per_million_cny == Decimal("2.50")
assert row.cost_cny == Decimal("0.000075")
```

Cover project analysis (including stream endpoint), follow-up decision, feedback, dialog turn, assessment batch, verifier, skill deep-dive and connection test. Include one provider error assertion that persists `failed` with a stable error code and no error message body.

- [ ] **Step 2: Run the affected tests to verify RED**

Run: `python -m pytest backend/tests/test_project_analysis.py backend/tests/test_followup.py backend/tests/test_dialog_interview.py backend/tests/test_assessment_batch.py backend/tests/test_skills_wiki.py backend/tests/test_settings_api.py -q`

Expected: new trace assertions fail because flows have not established a capture/persistence boundary.

- [ ] **Step 3: Wrap only actual Provider calls in each flow**

Use this structure at each model invocation, passing the loaded settings pricing snapshot and associations already available in the flow:

```python
with capture_model_calls(str(uuid4())) as capture:
    result = provider.decide_followup(...)
record_model_calls(db, capture.records, pricing=settings.pricing,
                   session_id=session_id, operation_job_id=None)
```

Use `try/finally` so `record_model_calls` runs when the Provider raises; re-raise the original error. Reuse a single capture/trace id for all chunks and verifier calls of one assessment job, and set that job id on each related trace. Do not create a trace for disabled follow-up/feedback paths because no model request occurs.

- [ ] **Step 4: Add low-risk trace-write degradation behavior**

Have `record_model_calls` return `0` on a database write error and log one safe server message containing only the count and call kinds. Do not expose trace failures through existing HTTP responses. Test this by monkeypatching the persistence helper to raise and asserting the original successful follow-up/analysis response remains 200.

- [ ] **Step 5: Run workflow regression tests**

Run: `python -m pytest backend/tests/test_project_analysis.py backend/tests/test_followup.py backend/tests/test_dialog_interview.py backend/tests/test_assessment_batch.py backend/tests/test_skills_wiki.py backend/tests/test_settings_api.py -q`

Expected: PASS; one trace exists per real model request and disabled/fully local paths create none.

### Task 4: Expose validated pricing settings and read-only aggregation APIs

**Files:**
- Modify: `backend/app/schemas.py:34-70, 390-495`
- Modify: `backend/app/model_settings.py:34-180`
- Modify: `backend/app/main.py:246-270, 682-685`
- Modify: `backend/app/llm_observability.py`
- Modify: `backend/tests/test_model_settings.py`
- Modify: `backend/tests/test_settings_api.py`
- Modify: `backend/tests/test_llm_observability.py`

**Interfaces:**
- Produces `ModelPricePayload`, `ObservabilitySummaryResponse`, `LlmCallTraceResponse`, and `LlmTracePageResponse`.
- Produces `GET /api/observability/summary`, `GET /api/observability/traces`, and `GET /api/observability/sessions/{session_id}`.

- [ ] **Step 1: Add RED tests for price validation and response privacy**

```python
def test_settings_reject_duplicate_model_or_negative_price(client):
    response = client.put("/api/settings/model", json={**payload, "pricing": [
        {"model_name": "a", "input_price_per_million_cny": -1, "output_price_per_million_cny": 1}
    ]})
    assert response.status_code == 422

def test_trace_api_excludes_sensitive_content(client, seeded_trace):
    item = client.get("/api/observability/traces").json()["items"][0]
    assert set(item).isdisjoint({"api_key", "prompt", "response", "error_message"})
```

- [ ] **Step 2: Run API/settings tests to verify RED**

Run: `python -m pytest backend/tests/test_model_settings.py backend/tests/test_settings_api.py backend/tests/test_llm_observability.py -q`

Expected: fails on unknown `pricing` payload and missing observability routes.

- [ ] **Step 3: Implement settings DTOs and persistence**

Define `ModelPricePayload` with `model_name` max 160 characters and two `Decimal` fields `ge=0`; define `pricing: list[ModelPricePayload] = []` on both settings update/response. Convert to/from `pricing_json` with canonical JSON sorted by model name. Ensure the public settings response includes prices but never API key.

- [ ] **Step 4: Implement one filtered aggregation query path**

Create `TraceFilters(from_at, to_at, model_name, call_kind, session_id)` and one `_filtered_trace_query` shared by summary and list endpoints. Default `from_at` is UTC now minus 30 days, reject `from_at > to_at`, and limit list pages to 100 records. Compute known cost with `coalesce(sum(cost_cny), 0)`, unpriced count where `cost_cny IS NULL`, success rate from `status`, and p95 in Python from at most the filtered result set because SQLite lacks a portable percentile aggregate. Return daily/model/call-kind groups from straightforward `GROUP BY` queries; do not add an analytics dependency.

- [ ] **Step 5: Implement routes and verify math/filtering**

Wire the three routes in `main.py`. Test default 30-day exclusion, date/model/kind/session filters, cursor continuation `(finished_at, id)`, P95 nearest-rank calculation, `NULL` cost accounting, session 404, and only safe response fields.

- [ ] **Step 6: Run backend coverage for this task**

Run: `python -m pytest backend/tests/test_model_settings.py backend/tests/test_settings_api.py backend/tests/test_llm_observability.py -q`

Expected: PASS.

### Task 5: Add the minimal console pricing editor and observability screen

**Files:**
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/format.ts`
- Modify: `frontend/app/console/page.tsx`
- Create: `frontend/app/observability/page.tsx`
- Modify: `frontend/app/report/[id]/page.tsx`
- Modify: `frontend/app/globals.css`
- Create: `frontend/lib/observability.test.ts`
- Modify: `frontend/package.json`

**Interfaces:**
- Consumes the pricing and observability DTOs from Task 4.
- Produces `/observability`, a settings-editor price list, and `/observability?session_id=<id>` report link.

- [ ] **Step 1: Add a pure RED formatting test and register it**

```ts
import assert from "node:assert/strict";
import { formatCny, formatCostState } from "./format";

assert.equal(formatCny("0.123456"), "¥0.1235");
assert.equal(formatCostState(null), "未配置");
```

Append `node --experimental-strip-types lib/observability.test.ts` to the existing `npm test` chain. Do not introduce a test framework.

- [ ] **Step 2: Run frontend tests to verify RED**

Run: `npm --prefix frontend test`

Expected: fails because cost-format helpers and the new test target do not exist.

- [ ] **Step 3: Extend API types and implement price editing**

Add typed `ModelPrice`, `ObservabilitySummary`, and trace list functions to `frontend/lib/api.ts`. In the existing console form, add only a small repeatable price row: model name, input ¥/1M, output ¥/1M, remove button, and “添加模型价格” button. Validate required nonnegative numbers in the browser for feedback, while relying on the server as the trust boundary. Prepopulate rows from saved settings; do not prepopulate an unknown model with invented prices.

- [ ] **Step 4: Implement a no-dependency observability view**

Build `/observability` with existing `mint-*` classes and semantic tables rather than a chart library: a date range (default 30 days), model/kind filters, four summary cards, per-kind and per-model tables, a compact daily-cost table, latest failed calls, and paged recent-call list. Use CSS bars only for success-rate visual emphasis if useful; text/table data remains authoritative. Render `未配置` for null cost and show the unpriced count beside total cost.

- [ ] **Step 5: Link session detail and add navigation**

Add “模型观测” to console/history/report navigation patterns. On report page, add a regular link to `/observability?session_id=${sessionId}`; on the observability page, read that query parameter and apply it to API requests. Do not add a separate report API field.

- [ ] **Step 6: Run frontend tests and a production compilation**

Run: `npm --prefix frontend test`

Expected: PASS.

Run: `npm --prefix frontend run build`

Expected: PASS; `/observability` is included in the route output.

### Task 6: Full regression and acceptance walkthrough

**Files:**
- Modify: `README.md`
- Test: `backend/tests/`, `frontend/`

**Interfaces:**
- Consumes all prior tasks.
- Produces documented local setup for model prices and the observability page.

- [ ] **Step 1: Document only user-facing behavior**

Add one README subsection explaining: prices are local RMB per 1M input/output tokens, missing price means no cost estimate rather than free usage, `/observability` defaults to the last 30 days, and traces intentionally exclude request/response text and credentials. Do not add implementation internals or token-price recommendations.

- [ ] **Step 2: Run the complete backend suite**

Run: `python -m pytest backend/tests -q`

Expected: PASS; include prior behavior plus all new trace/pricing tests.

- [ ] **Step 3: Run frontend suite and production build**

Run: `npm --prefix frontend test`

Expected: PASS.

Run: `npm --prefix frontend run build`

Expected: PASS.

- [ ] **Step 4: Run migration and manual acceptance checks against a disposable database**

Run: `Set-Location backend; python -m alembic -c alembic.ini upgrade head; Set-Location ..`

Expected: migration applies once without error.

Then use a fake Provider test fixture to make one priced follow-up and one unpriced feedback call; verify `/api/observability/summary` has one known-cost and one unpriced call, and the trace response contains no prompt, response, API key or error-message fields.

- [ ] **Step 5: Inspect the final diff without committing**

Run: `git diff --check`

Expected: no whitespace errors. Review `git status --short` to confirm only intended files were added or modified; do not create a commit unless the user explicitly requests one.

## Plan self-review

- Spec coverage: Tasks 1–3 implement durable request-level accounting for every named call family; Task 4 covers model pricing, filters, aggregates and safe API output; Task 5 supplies the requested local configuration and backend entry; Task 6 verifies privacy, regressions and user documentation.
- Simplicity: `ContextVar` preserves existing Provider return types, `pricing_json` avoids a one-purpose price table, `GROUP BY` plus tables avoids an analytics service and chart dependency, and existing UI/testing tooling is reused.
- Consistency: all tasks use the same `ModelCallRecord`, `pricing`, `record_model_calls`, trace status and null-cost semantics. No task requires a type not defined in Tasks 1–2.
