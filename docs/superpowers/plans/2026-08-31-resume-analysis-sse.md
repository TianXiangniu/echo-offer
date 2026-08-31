# Resume Analysis SSE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 为简历项目分析增加可靠的 SSE 阶段进度、心跳、完整结果和错误事件，并在网页端消费这些事件。

**Architecture:** 保留现有同步分析接口，新增一个 POST SSE 接口。后端用异步生成器发送阶段事件，将同步模型调用放入线程并在等待期间发送心跳；模型结果完成全部 JSON 和证据校验后才发送完整结果。前端使用 fetch 的 ReadableStream 读取 SSE，因为请求需要携带 JSON body。

**Tech Stack:** FastAPI StreamingResponse、Python asyncio.to_thread、SQLAlchemy、HTTPX、Next.js 15、浏览器 ReadableStream。

## Global Constraints

- 本次只实现“简历项目分析”的 SSE，不修改答题评分逻辑。
- 不发送模型 token 或 reasoning_content，只发送阶段、心跳、完整结果和错误事件。
- 新增接口为 POST /api/resumes/{resume_id}/agent-project-analysis/stream。
- 现有 POST /api/resumes/{resume_id}/agent-project-analysis 保持可用。
- result 只有在 JSON 解析、字段归一化、证据逐字校验和数据库提交成功后才能发送。
- 事件顺序必须为 stage(received)、stage(analyzing)、可选 heartbeat、stage(validating)、stage(completed)、result、done。
- 错误通过 error 事件返回，不发送 result 或 done。
- API Key 只存在后端运行环境，不能进入前端代码或 SSE 数据。
- 所有代码修改使用测试驱动开发，先看到失败测试，再写生产代码。

---

### Task 1: 创建 SSE 事件格式化工具

**Files:**
- Create: backend/app/sse.py
- Create: backend/tests/test_sse.py

**Interfaces:**
- Produces format_sse_event(event_name: str, data: dict) -> str。
- 输出格式为 event: <name>、data: <JSON>、空行；JSON 使用 ensure_ascii=False。

- [ ] Step 1: Write the failing test

~~~python
import json

from app.sse import format_sse_event


def test_format_sse_event_serializes_utf8_json_and_blank_line():
    result = format_sse_event("stage", {"stage": "analyzing", "message": "正在分析项目"})

    lines = result.splitlines()
    assert lines[0] == "event: stage"
    assert json.loads(lines[1].removeprefix("data: ")) == {
        "stage": "analyzing",
        "message": "正在分析项目",
    }
    assert result.endswith("\n\n")
~~~

- [ ] Step 2: Run test to verify it fails

Run from backend:

~~~powershell
& ".\.venv\Scripts\python.exe" -m pytest -q tests/test_sse.py::test_format_sse_event_serializes_utf8_json_and_blank_line
~~~

Expected: FAIL because app.sse and format_sse_event do not exist.

- [ ] Step 3: Write minimal implementation

~~~python
import json


def format_sse_event(event_name: str, data: dict) -> str:
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_name}\ndata: {serialized}\n\n"
~~~

- [ ] Step 4: Run test to verify it passes

~~~powershell
& ".\.venv\Scripts\python.exe" -m pytest -q tests/test_sse.py
~~~

Expected: PASS.

- [ ] Step 5: Commit

~~~powershell
git add backend/app/sse.py backend/tests/test_sse.py
git commit -m "feat: add SSE event formatter"
~~~

### Task 2: 实现后端流式分析服务

**Files:**
- Modify: backend/app/services.py
- Modify: backend/tests/test_project_analysis.py

**Interfaces:**
- Consumes the existing ProjectAnalysisProvider, validate_analysis_evidence, ResumeProjectAnalysis, and AgentProjectAnalysisResponseEnvelope data shape.
- Produces:

~~~python
async def stream_resume_project_analysis(
    db: Session,
    provider: ProjectAnalysisProvider,
    resume_id: str,
    resume_text: str,
    *,
    heartbeat_interval_seconds: float = 10.0,
) -> AsyncIterator[str]
~~~

The function yields formatted SSE strings and never yields model reasoning content.

- [ ] Step 1: Write the failing tests

Add a fast-provider test that parses each event and asserts the complete event order, result payload, and database persistence:

~~~python
import asyncio
import json

from app.services import stream_resume_project_analysis


async def collect_events(generator):
    return [event async for event in generator]


def event_type(event: str) -> str:
    return event.splitlines()[0].removeprefix("event: ")


def event_data(event: str) -> dict:
    return json.loads(event.splitlines()[1].removeprefix("data: "))


def test_stream_resume_project_analysis_emits_ordered_events_and_result(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    provider = FakeProjectAnalysisProvider(
        result=AgentProjectAnalysisResponse.model_validate(valid_analysis_payload())
    )
    db = client.app.state.session_factory()
    try:
        events = asyncio.run(
            collect_events(
                stream_resume_project_analysis(
                    db, provider, parsed["resume_id"], "负责检索链路和线上监控"
                )
            )
        )
    finally:
        db.close()

    assert [event_type(event) for event in events] == [
        "stage", "stage", "stage", "stage", "result", "done"
    ]
    assert event_data(events[0])["stage"] == "received"
    assert event_data(events[1])["stage"] == "analyzing"
    assert event_data(events[2])["stage"] == "validating"
    assert event_data(events[3])["stage"] == "completed"
    assert event_data(events[-1])["status"] == "completed"
    assert event_data(events[-2])["status"] == "draft"


class SlowProjectAnalysisProvider(FakeProjectAnalysisProvider):
    def analyze(self, resume_text):
        import time

        time.sleep(0.03)
        return super().analyze(resume_text)


def test_stream_resume_project_analysis_emits_heartbeat_while_provider_runs(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    provider = SlowProjectAnalysisProvider(
        result=AgentProjectAnalysisResponse.model_validate(valid_analysis_payload())
    )
    db = client.app.state.session_factory()
    try:
        events = asyncio.run(
            collect_events(
                stream_resume_project_analysis(
                    db,
                    provider,
                    parsed["resume_id"],
                    "负责检索链路和线上监控",
                    heartbeat_interval_seconds=0.01,
                )
            )
        )
    finally:
        db.close()

    assert any(event_type(event) == "heartbeat" for event in events)
    assert event_type(events[-1]) == "done"


def test_stream_resume_project_analysis_emits_error_without_result(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    provider = FakeProjectAnalysisProvider(
        error=ProjectAnalysisProviderError("provider_timeout", "模型请求超时")
    )
    db = client.app.state.session_factory()
    try:
        events = asyncio.run(
            collect_events(
                stream_resume_project_analysis(
                    db, provider, parsed["resume_id"], "负责检索链路和线上监控"
                )
            )
        )
    finally:
        db.close()

    assert event_type(events[-1]) == "error"
    assert event_data(events[-1])["code"] == "provider_timeout"
    assert not any(event_type(event) == "result" for event in events)
    assert not any(event_type(event) == "done" for event in events)
~~~

- [ ] Step 2: Run tests to verify they fail

~~~powershell
& ".\.venv\Scripts\python.exe" -m pytest -q tests/test_project_analysis.py -k "stream_resume_project_analysis"
~~~

Expected: FAIL because stream_resume_project_analysis does not exist.

- [ ] Step 3: Write the minimal implementation

Implement the service with this behavior:

~~~python
async def stream_resume_project_analysis(
    db: Session,
    provider: ProjectAnalysisProvider,
    resume_id: str,
    resume_text: str,
    *,
    heartbeat_interval_seconds: float = 10.0,
) -> AsyncIterator[str]:
    resume = db.get(Resume, resume_id)
    if resume is None:
        yield format_sse_event("error", {"code": "resume_not_found", "message": "resume not found"})
        return
    if resume.user_id != LOCAL_USER_ID:
        yield format_sse_event("error", {"code": "resume_owner_conflict", "message": "resume does not belong to the current user"})
        return
    if not resume_text.strip():
        yield format_sse_event("error", {"code": "resume_text_empty", "message": "简历文本不能为空"})
        return
    if len(resume_text) > MAX_ANALYSIS_RESUME_CHARS:
        yield format_sse_event("error", {"code": "resume_text_too_long", "message": "简历文本过长"})
        return

    analysis = ResumeProjectAnalysis(
        id=str(uuid4()),
        resume_id=resume.id,
        user_id=resume.user_id,
        resume_text_hash=hashlib.sha256(resume_text.encode("utf-8")).hexdigest(),
        model_name=SILICONFLOW_MODEL,
        provider_name="siliconflow",
        status="draft",
        analysis_json="{}",
    )
    db.add(analysis)
    db.flush()
    yield format_sse_event("stage", {"stage": "received", "message": "已接收简历"})
    yield format_sse_event("stage", {"stage": "analyzing", "message": "正在分析项目"})

    task = asyncio.create_task(asyncio.to_thread(provider.analyze, resume_text))
    try:
        while not task.done():
            finished, _ = await asyncio.wait(
                (task,), timeout=heartbeat_interval_seconds
            )
            if not finished:
                yield format_sse_event("heartbeat", {"stage": "analyzing"})
        result = task.result()
        yield format_sse_event("stage", {"stage": "validating", "message": "正在校验证据"})
        result = validate_analysis_evidence(result, resume_text)
        analysis.analysis_json = json.dumps(
            result.model_dump(), ensure_ascii=False, sort_keys=True
        )
        db.commit()
        response = {
            "analysis_id": analysis.id,
            "resume_id": resume.id,
            "resume_text_hash": analysis.resume_text_hash,
            "status": analysis.status,
            **result.model_dump(),
        }
        yield format_sse_event("stage", {"stage": "completed", "message": "分析完成"})
        yield format_sse_event("result", response)
        yield format_sse_event("done", {"status": "completed"})
    except ProjectAnalysisProviderError as exc:
        analysis.status = "failed"
        analysis.error_code = exc.code
        db.commit()
        yield format_sse_event("error", {"code": exc.code, "message": str(exc)})
    except ValueError:
        analysis.status = "failed"
        analysis.error_code = "invalid_model_response"
        db.commit()
        yield format_sse_event(
            "error",
            {"code": "invalid_model_response", "message": "模型返回内容无法确认"},
        )
~~~

Reuse the same input limits, ownership checks, analysis JSON serialization, error codes, and evidence validator as analyze_resume_project. Do not weaken validate_analysis_evidence.

- [ ] Step 4: Run targeted tests to verify they pass

~~~powershell
& ".\.venv\Scripts\python.exe" -m pytest -q tests/test_project_analysis.py -k "stream_resume_project_analysis"
~~~

Expected: PASS, including at least one heartbeat in the slow-provider test.

- [ ] Step 5: Commit

~~~powershell
git add backend/app/services.py backend/tests/test_project_analysis.py
git commit -m "feat: stream resume analysis progress"
~~~

### Task 3: 暴露 FastAPI SSE 路由

**Files:**
- Modify: backend/app/main.py
- Modify: backend/tests/test_api.py

**Interfaces:**
- Produces POST /api/resumes/{resume_id}/agent-project-analysis/stream.
- Response media type is text/event-stream with Cache-Control: no-cache and X-Accel-Buffering: no.
- The existing non-streaming route remains unchanged.

- [ ] Step 1: Write the failing API test

~~~python
def test_stream_analysis_route_returns_sse_events(client):
    parsed = client.post(
        "/api/resumes/parse",
        files={"file": ("resume.pdf", make_pdf_bytes(), "application/pdf")},
    ).json()
    client.app.state.project_analysis_provider = FakeProjectAnalysisProvider(
        result=AgentProjectAnalysisResponse.model_validate(valid_analysis_payload())
    )

    with client.stream(
        "POST",
        f"/api/resumes/{parsed['resume_id']}/agent-project-analysis/stream",
        json={"resume_text": "负责检索链路和线上监控"},
    ) as response:
        body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: result" in body
    assert body.index("event: result") < body.index("event: done")
~~~

- [ ] Step 2: Run test to verify it fails

~~~powershell
& ".\.venv\Scripts\python.exe" -m pytest -q tests/test_api.py::test_stream_analysis_route_returns_sse_events
~~~

Expected: FAIL with 404 because the stream route does not exist.

- [ ] Step 3: Add the route

Use StreamingResponse and delegate all analysis behavior to stream_resume_project_analysis:

~~~python
@app.post("/api/resumes/{resume_id}/agent-project-analysis/stream")
async def analyze_project_stream(
    resume_id: str,
    payload: AgentProjectAnalysisRequest,
    db: Session = Depends(get_db),
):
    return StreamingResponse(
        stream_resume_project_analysis(
            db,
            app.state.project_analysis_provider,
            resume_id,
            payload.resume_text,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
~~~

Import StreamingResponse and stream_resume_project_analysis without changing the existing route.

- [ ] Step 4: Run API and backend tests

~~~powershell
& ".\.venv\Scripts\python.exe" -m pytest -q tests/test_api.py::test_stream_analysis_route_returns_sse_events
& ".\.venv\Scripts\python.exe" -m pytest -q
~~~

Expected: both commands PASS.

- [ ] Step 5: Commit

~~~powershell
git add backend/app/main.py backend/tests/test_api.py
git commit -m "feat: expose resume analysis SSE endpoint"
~~~

### Task 4: 实现前端 SSE 读取器

**Files:**
- Modify: frontend/lib/api.ts

**Interfaces:**
- Produces:

~~~typescript
export type AgentAnalysisStreamEvent =
  | { event: "stage"; data: { stage: "received" | "analyzing" | "validating" | "completed"; message: string } }
  | { event: "heartbeat"; data: { stage: "analyzing" } }
  | { event: "result"; data: AgentProjectAnalysis }
  | { event: "done"; data: { status: "completed" } }
  | { event: "error"; data: { code: string; message: string } };

export function analyzeAgentProjectStream(
  resumeId: string,
  resumeText: string,
  onEvent: (event: AgentAnalysisStreamEvent) => void,
): Promise<AgentProjectAnalysis>;
~~~

- [ ] Step 1: Add a parser-focused test fixture or executable assertion

Because the frontend has no test runner, add a pure parseSseBlock helper in frontend/lib/api.ts and validate it through TypeScript compilation. The helper must parse one block:

~~~text
event: stage
data: {"stage":"analyzing","message":"正在分析项目"}

~~~

into an event object with event equal to stage and the parsed data object.

- [ ] Step 2: Add the streaming request implementation

Implement these exact behaviors:

~~~typescript
const response = await fetch(
  API_BASE + "/api/resumes/" + resumeId + "/agent-project-analysis/stream",
  {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ resume_text: resumeText }),
  },
);
~~~

Read response.body.getReader() with TextDecoder, preserve an incomplete trailing block between chunks, call onEvent for every complete event, save the result payload, and throw ApiError for an error event or an HTTP failure. If the stream ends without both result and done, throw ApiError(0, "分析连接中断，请重试").

- [ ] Step 3: Run TypeScript validation

~~~powershell
npm run build
~~~

Expected: PASS with no TypeScript errors.

- [ ] Step 4: Commit

~~~powershell
git add frontend/lib/api.ts
git commit -m "feat: consume resume analysis SSE"
~~~

### Task 5: 在网页端展示分析阶段

**Files:**
- Modify: frontend/app/page.tsx
- Modify: frontend/lib/api.ts

**Interfaces:**
- Consumes analyzeAgentProjectStream and AgentAnalysisStreamEvent from Task 4.
- Produces visible progress text while analyzing is true and the stream has not produced its final result.

- [ ] Step 1: Add the state-driven UI behavior

Add:

~~~typescript
const [analysisStage, setAnalysisStage] = useState("等待开始");
~~~

Call the streaming function from handleAnalyze and update the stage from stage events. Keep the existing analysisResult update only in the returned final result. Reset analysisStage in clearAnalysis; on an error, set it to 分析失败，可重试.

Render the current stage beside the AI analysis button while analyzing is true:

~~~tsx
{analyzing && <p className="mt-3 text-xs text-signal">{analysisStage}</p>}
~~~

Use the labels 已接收简历、正在分析项目、正在校验证据、分析完成 from the server event message.

- [ ] Step 2: Run the production build

~~~powershell
npm run build
~~~

Expected: PASS and all existing routes compile.

- [ ] Step 3: Run the local smoke check

Start the backend on 127.0.0.1:8010 and frontend on localhost:3000 with NEXT_PUBLIC_API_URL=http://127.0.0.1:8010. Upload a PDF or DOCX resume, click “使用 AI 分析”, and verify that the stage text appears before the final project result.

- [ ] Step 4: Commit

~~~powershell
git add frontend/app/page.tsx frontend/lib/api.ts
git commit -m "feat: show resume analysis progress"
~~~

### Task 6: Final verification

**Files:**
- No new files.

- [ ] Step 1: Run backend regression tests

~~~powershell
Push-Location backend
& ".\.venv\Scripts\python.exe" -m pytest -q
Pop-Location
~~~

Expected: all tests pass; the existing deprecation warning may remain.

- [ ] Step 2: Run frontend build

~~~powershell
npm --prefix frontend run build
~~~

Expected: exit code 0 with /, /interview/[id], and /report/[id] built.

- [ ] Step 3: Verify the HTTP services

~~~powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8010/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000
~~~

Expected: backend and frontend both return HTTP 200.

- [ ] Step 4: Inspect the final diff

~~~powershell
git status --short
git diff --check
git diff --stat
~~~

Expected: only the planned SSE source, test, and documentation changes are present; no API key is present in the diff.
