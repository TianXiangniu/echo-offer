# 基础面试与项目面试双模式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将产品明确拆分为“一键开始的大模型基础面试”和“基于简历项目的上下文面试”，两种模式共享评分、报告、能力画像、人民币成本与可观测性，但使用彼此独立的出题链路。

**Architecture:** 用户层新增 `foundation` 与 `project` 两个业务类型；执行层继续保留现有 `classic`、`graph`、`dialog` 值，避免破坏已有会话。基础面试使用题库线性流程和现有追问接口，不引入 LangGraph；项目面试继续使用现有 LangGraph 规划、事实核验、追问路由与完成态评分。基础面试允许在没有简历和项目的情况下创建，因此只把 `InterviewSession.resume_project_id` 调整为可空，其余评分与画像关系保持不变。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy、Alembic、LangGraph、pytest、Next.js 15、React 19、TypeScript。

## Global Constraints

- 用户界面只展示两个模式：`foundation`（大模型基础面试）和 `project`（项目经历面试）。
- 内部执行值继续使用 `classic` 与 `graph`；`dialog` 只为存量会话兼容，不在新首页展示。
- 基础面试无需上传简历、无需填写配置，一次从题库抽取 5 道技术题。
- 基础题覆盖 RAG、Agent/工具、多智能体/记忆、评估与工程、系统设计或编码；不抽取 `project.*` 与 `behavioral.*`。
- 项目面试保持“上传简历 → 识别项目 → 选择一个项目 → AI 整理 → LangGraph 深挖”的现有流程。
- 两种模式继续使用同一套 Rubric；用户看到 A/B/C/D，内部继续保存 0–4，其中 D 对应 0–1。
- 两种模式继续进入统一 `LlmCallTrace`，模型价格与成本单位保持人民币，不增加强制停服或预算熔断。
- 使用 ponytail：不新增前端状态库、不为基础面试接入 LangGraph、不新增第二套评分或报告系统。
- 所有生产代码遵循 TDD：先写失败测试，确认失败原因正确，再写最小实现。
- 每次代码修改后重启 backend/frontend，并确认 `http://127.0.0.1:8010/health` 与 `http://127.0.0.1:3000/console` 返回 200。
- 保留工作区中与本计划无关的未提交改动；只暂存和提交当前任务文件，不自动推送 GitHub。

每个任务提到“重启服务”时，执行下面这套 PowerShell 流程。停止动作只作用于当前监听 8010、3000 的明确 PID：

```powershell
$echoOfferPids = Get-NetTCPConnection -LocalPort 8010,3000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
$echoOfferPids | ForEach-Object { Stop-Process -Id $_ -Force }

Start-Process -FilePath 'C:\Users\海阔天空\AppData\Local\Programs\Python\Python311\python.exe' `
    -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8010' `
    -WorkingDirectory 'C:\Users\海阔天空\Desktop\Echo Offer\backend' -WindowStyle Hidden
Start-Process -FilePath 'npm.cmd' `
    -ArgumentList 'run','dev','--','--hostname','127.0.0.1','--port','3000' `
    -WorkingDirectory 'C:\Users\海阔天空\Desktop\Echo Offer\frontend' -WindowStyle Hidden

Start-Sleep -Seconds 5
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8010/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000/console
```

## Current-to-Target Mapping

| 用户看到的模式 | 内部 `mode` | `session_kind` | 出题来源 | 是否需要项目 | 追问方式 |
| --- | --- | --- | --- | --- | --- |
| 大模型基础面试 | `classic` | `foundation` | `QUESTION_TEMPLATES` | 否 | 现有 `decideFollowup` |
| 项目经历面试 | `graph` | `interview` | LangGraph planner + 项目事实 | 是 | Graph verifier + 条件路由 |
| 存量对话面试 | `dialog` | 保持原值 | 存量对话流程 | 是 | 存量 dialog flow |

## File Responsibility Map

**Create:**

- `backend/app/interview_types.py`：把内部执行模式映射为用户业务类型。
- `backend/alembic/versions/0021_foundation_sessions.py`：允许基础会话没有 `resume_project_id`。
- `backend/tests/test_foundation_interview.py`：基础题选择、会话创建、API 与无简历流程测试。
- `frontend/app/project/page.tsx`：承接当前首页中的简历项目准备流程。
- `frontend/lib/interview-type.ts`：两种模式的名称、入口路径和显示文案。
- `frontend/lib/interview-type.test.ts`：前端业务类型映射回归测试。

**Modify:**

- `backend/app/models.py`：将 `InterviewSession.resume_project_id` 标注为可空。
- `backend/app/question_bank.py`：新增只抽技术题的 `build_foundation_specs`。
- `backend/app/interview_flow.py`：创建无项目的基础会话，并在会话响应中输出业务类型。
- `backend/app/interview_graph_projection.py`：Graph 响应固定输出 `interview_type="project"`。
- `backend/app/reporting_flow.py`：历史记录与报告输出业务类型。
- `backend/app/schemas.py`：更新会话、历史与报告响应结构。
- `backend/app/main.py`：增加 `POST /api/sessions/foundation`。
- `backend/tests/test_question_bank.py`、`backend/tests/test_api.py`、`backend/tests/test_migrations.py`：补充模式隔离与迁移测试。
- `frontend/app/page.tsx`：改成双模式入口页。
- `frontend/app/interview/[id]/page.tsx`：按业务类型显示标题，并补齐基础题题面。
- `frontend/app/history/page.tsx`：区分基础面试与项目面试记录。
- `frontend/app/report/[id]/page.tsx`：显示本场模式并提供正确的“再做一场”入口。
- `frontend/app/globals.css`：增加模式卡片布局，复用现有配色和按钮。
- `frontend/lib/api.ts`：增加 `InterviewType`、基础会话 API 和响应字段。
- `frontend/package.json`：把新测试加入现有 `npm test` 串行脚本。
- `README.md`：记录两个用户入口与基础会话 API。

---

### Task 1: 从题库生成纯技术基础面试

**Files:**

- Modify: `backend/app/question_bank.py`
- Modify: `backend/tests/test_question_bank.py`

**Interfaces:**

- Produces: `FOUNDATION_QUESTION_GROUPS: tuple[tuple[str, ...], ...]`
- Produces: `build_foundation_specs(*, excluded_template_ids: set[str] | None = None, rng: random.Random | None = None) -> list[QuestionSpec]`
- Guarantees: 返回 5 道题，每组 1 道，不包含 `project.*` 或 `behavioral.*`。

- [x] **Step 1: Write the failing selector test**

在 `backend/tests/test_question_bank.py` 增加：

```python
import random

from app.question_bank import FOUNDATION_QUESTION_GROUPS, build_foundation_specs


def test_foundation_specs_are_balanced_and_exclude_project_questions():
    specs = build_foundation_specs(rng=random.Random(7))

    assert len(specs) == 5
    assert [spec.order for spec in specs] == [1, 2, 3, 4, 5]
    assert all(
        not spec.knowledge_point_id.startswith(("project.", "behavioral."))
        for spec in specs
    )
    assert all(
        spec.knowledge_point_id in group
        for spec, group in zip(specs, FOUNDATION_QUESTION_GROUPS)
    )
```

- [x] **Step 2: Run the test and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_question_bank.py::test_foundation_specs_are_balanced_and_exclude_project_questions -q
```

Expected: FAIL because `FOUNDATION_QUESTION_GROUPS` and `build_foundation_specs` do not exist.

- [x] **Step 3: Implement the five balanced groups**

在 `backend/app/question_bank.py` 定义固定分组：

```python
FOUNDATION_QUESTION_GROUPS: tuple[tuple[str, ...], ...] = (
    ("rag.retrieval_diagnosis", "rag.query_rewrite_and_hybrid_retrieval"),
    ("agent_runtime.tool_calling", "mcp.tool_ecosystem"),
    ("multi_agent.orchestration", "memory.design"),
    ("evals.observability", "engineering.latency_diagnosis", "engineering.output_safety"),
    ("design.agent_platform", "design.rag_system", "coding.debug_tool_call", "coding.write_tool_loop"),
)
```

实现选择器时复用 `_fresh_pool` 和 `QuestionTemplate`，优先选择最近没出现过的模板；没有新模板时允许回退到该组已有模板。`rng is None` 时选择每组第一个可用知识点和第一道模板，传入 `rng` 时在组内随机选择，但始终保持 5 个组的顺序。

```python
def build_foundation_specs(*, excluded_template_ids=None, rng=None):
    excluded = excluded_template_ids or set()
    specs = []
    for order, group in enumerate(FOUNDATION_QUESTION_GROUPS, start=1):
        available = [point for point in group if _fresh_pool(point, excluded)[1]]
        points = available or list(group)
        point = rng.choice(points) if rng else points[0]
        pool, fresh = _fresh_pool(point, excluded)
        templates = fresh or list(pool)
        template = rng.choice(templates) if rng else templates[0]
        specs.append(
            QuestionSpec(
                order=order,
                category=category_for_kp(point),
                is_anchor=order in {1, 4},
                prompt=template.prompt,
                knowledge_point_id=point,
                rubric_version="alpha-local-v1",
                signals=template.signals,
                reference_facts=template.reference_facts,
                template_id=template.template_id,
                rubric_weights=template.rubric_weights,
                criteria_override=template.criteria_override,
            )
        )
    return specs
```

- [x] **Step 4: Restart services and confirm GREEN**

先解析 8010、3000 的监听 PID，只停止这两个明确进程；然后使用当前项目既有启动命令重启 backend/frontend。确认两个健康请求均为 200 后运行：

```powershell
python -m pytest backend/tests/test_question_bank.py -q
```

Expected: PASS，现有 `build_question_specs` 和 `build_knowledge_specs` 行为保持不变。

- [x] **Step 5: Commit the selector**

```powershell
git add backend/app/question_bank.py backend/tests/test_question_bank.py
git commit -m "feat: add foundation question selection"
```

### Task 2: 支持没有简历项目的基础会话

**Files:**

- Create: `backend/app/interview_types.py`
- Create: `backend/alembic/versions/0021_foundation_sessions.py`
- Create: `backend/tests/test_foundation_interview.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/interview_flow.py`
- Modify: `backend/tests/test_migrations.py`

**Interfaces:**

- Produces: `interview_type_from_mode(mode: str) -> Literal["foundation", "project"]`
- Produces: `create_foundation_session(db: Session) -> dict`
- Persists: `mode="classic"`、`session_kind="foundation"`、`stage="knowledge"`、`resume_project_id=None`。

- [x] **Step 1: Write failing persistence and migration tests**

在 `backend/tests/test_foundation_interview.py` 创建没有简历的数据库，调用新函数并断言：

```python
import pytest

from app.database import create_database
from app.interview_flow import create_foundation_session
from app.models import InterviewSession


@pytest.fixture
def db(tmp_path):
    engine, factory = create_database(f"sqlite:///{tmp_path / 'foundation.db'}")
    with factory() as session:
        yield session
    engine.dispose()


def test_foundation_session_does_not_require_resume(db):
    result = create_foundation_session(db)
    session = db.get(InterviewSession, result["session_id"])

    assert result["interview_type"] == "foundation"
    assert session.resume_project_id is None
    assert session.mode == "classic"
    assert session.session_kind == "foundation"
    assert session.profile_id is not None
    assert len(result["questions"]) == 5
```

在 `backend/tests/test_migrations.py` 检查升级后的列：

```python
columns = {
    column["name"]: column
    for column in inspect(upgraded_engine).get_columns("interview_sessions")
}
assert columns["resume_project_id"]["nullable"] is True
```

- [x] **Step 2: Run both tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_foundation_interview.py backend/tests/test_migrations.py -q
```

Expected: FAIL because the factory is missing and `resume_project_id` is non-nullable.

- [x] **Step 3: Add the business-type mapper**

创建 `backend/app/interview_types.py`：

```python
from typing import Literal

InterviewType = Literal["foundation", "project"]


def interview_type_from_mode(mode: str) -> InterviewType:
    return "project" if mode in {"graph", "dialog"} else "foundation"
```

这层只负责用户语义，不改变任何 Graph、Dialog 或 Classic 分支判断。

- [x] **Step 4: Make the project relation nullable safely**

将 ORM 字段改为：

```python
resume_project_id: Mapped[str | None] = mapped_column(
    ForeignKey("resume_projects.id"), nullable=True
)
```

创建 Alembic revision，`down_revision = "0020_graph_submission_receipts"`。升级使用 SQLite 兼容的 batch alter：

```python
def upgrade() -> None:
    with op.batch_alter_table("interview_sessions") as batch:
        batch.alter_column(
            "resume_project_id",
            existing_type=sa.String(36),
            nullable=True,
        )
```

降级前查询空值数量；存在基础会话时抛出明确错误，不删除用户数据：

```python
def downgrade() -> None:
    null_count = op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM interview_sessions WHERE resume_project_id IS NULL")
    )
    if null_count:
        raise RuntimeError("cannot downgrade while foundation sessions exist")
    with op.batch_alter_table("interview_sessions") as batch:
        batch.alter_column(
            "resume_project_id",
            existing_type=sa.String(36),
            nullable=False,
        )
```

- [x] **Step 5: Implement the foundation session factory**

在 `backend/app/interview_flow.py` 新增 `create_foundation_session`。它必须：

1. 获取或创建 `LOCAL_USER_ID` 用户。
2. 复用该用户已有 `InterviewTarget`；没有时创建默认 `Agent 应用工程师` 目标。
3. 通过 `get_or_create_candidate_profile` 获取能力画像。
4. 使用 `_recent_template_ids` 与 `build_foundation_specs` 生成 5 题。
5. 持久化题目和 Rubric 快照，并一次性提交事务。

核心会话对象为：

```python
session = InterviewSession(
    id=str(uuid4()),
    user_id=user.id,
    resume_project_id=None,
    target_id=target.id,
    profile_id=profile.id,
    status="in_progress",
    current_question_index=0,
    total_questions=len(specs),
    followup_budget_used=0,
    session_kind="foundation",
    mode="classic",
    stage="knowledge",
    workflow_version=WORKFLOW_VERSION,
    session_version=1,
)
```

把 `create_session` 中现有的题目持久化循环提取为 `_persist_questions(db, session, specs)`，两种工厂复用同一个函数，避免复制 Rubric 构建代码。

- [x] **Step 6: Restart services and verify the vertical slice**

重启前后端并确认两个健康请求为 200，然后运行：

```powershell
python -m pytest backend/tests/test_foundation_interview.py backend/tests/test_migrations.py backend/tests/test_question_bank.py -q
```

Expected: PASS；已有项目会话仍保存非空 `resume_project_id`。

- [x] **Step 7: Commit persistence support**

```powershell
git add backend/app/interview_types.py backend/alembic/versions/0021_foundation_sessions.py backend/app/models.py backend/app/interview_flow.py backend/tests/test_foundation_interview.py backend/tests/test_migrations.py
git commit -m "feat: support resume-free foundation sessions"
```

### Task 3: 暴露清晰的双模式 API 契约

**Files:**

- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/interview_flow.py`
- Modify: `backend/app/interview_graph_projection.py`
- Modify: `backend/tests/test_foundation_interview.py`
- Modify: `backend/tests/test_interview_graph_api.py`

**Interfaces:**

- Produces: `POST /api/sessions/foundation`，无请求体，返回 `SessionCreateResponse`。
- Adds: `interview_type: Literal["foundation", "project"]` to `SessionCreateResponse` and `SessionView`。
- Keeps: `POST /api/sessions` 作为已有项目/兼容入口，现有 Graph 路由不改名。

- [x] **Step 1: Write failing API contract tests**

基础会话测试：

```python
def test_foundation_session_api_starts_without_profile(client):
    created = client.post("/api/sessions/foundation")

    assert created.status_code == 200
    body = created.json()
    assert body["interview_type"] == "foundation"
    assert len(body["questions"]) == 5

    view = client.get(f"/api/sessions/{body['session_id']}")
    assert view.status_code == 200
    assert view.json()["interview_type"] == "foundation"
    assert view.json()["mode"] == "classic"
```

Graph 测试增加：

```python
assert graph_response.json()["interview_type"] == "project"
assert graph_response.json()["mode"] == "graph"
```

- [x] **Step 2: Run API tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_foundation_interview.py backend/tests/test_interview_graph_api.py -q
```

Expected: FAIL with 404 for `/api/sessions/foundation` and missing `interview_type`.

- [x] **Step 3: Extend response schemas**

在 `backend/app/schemas.py` 增加：

```python
class SessionCreateResponse(BaseModel):
    session_id: str
    status: str
    interview_type: Literal["foundation", "project"]
    questions: list[QuestionResponse]


class SessionView(BaseModel):
    session_id: str
    status: str
    interview_type: Literal["foundation", "project"]
    mode: str = "classic"
    stage: str = "knowledge"
    current_question: dict | None
    questions: list[dict]
    progress: dict[str, int]
    timeline: list[dict] = Field(default_factory=list)
```

- [x] **Step 4: Add the foundation route and both response mappings**

在 `backend/app/main.py` 注册：

```python
@app.post("/api/sessions/foundation", response_model=SessionCreateResponse)
def foundation_session(db: Session = Depends(get_db)):
    return create_foundation_session(db)
```

`create_session` 与 `get_session_view` 通过 `interview_type_from_mode(session.mode)` 输出业务类型；`graph_session_view` 固定输出：

```python
"interview_type": "project",
"mode": "graph",
```

- [x] **Step 5: Restart services and confirm GREEN**

重启服务，检查 `/health` 与 `/console` 为 200，然后运行：

```powershell
python -m pytest backend/tests/test_foundation_interview.py backend/tests/test_interview_graph_api.py backend/tests/test_interview_graph_projection.py backend/tests/test_api.py -q
```

Expected: PASS；基础会话调用 `/graph/start` 仍返回 409，项目会话仍正常启动 Graph。

- [x] **Step 6: Commit the API contract**

```powershell
git add backend/app/schemas.py backend/app/main.py backend/app/interview_flow.py backend/app/interview_graph_projection.py backend/tests/test_foundation_interview.py backend/tests/test_interview_graph_api.py
git commit -m "feat: expose foundation and project interview types"
```

### Task 4: 将首页拆成两个清晰入口

**Files:**

- Create: `frontend/app/project/page.tsx`
- Create: `frontend/lib/interview-type.ts`
- Create: `frontend/lib/interview-type.test.ts`
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/app/globals.css`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/package.json`

**Interfaces:**

- Produces: `createFoundationSession() -> Promise<SessionResponse>`
- Produces: `/` 双模式选择页。
- Produces: `/project` 项目准备页。
- Keeps: `/interview/:id` 作为两种模式共用的面试页面。

- [x] **Step 1: Write the failing frontend type test**

创建 `frontend/lib/interview-type.test.ts`：

```typescript
import { interviewEntryPath, interviewTypeLabel } from "./interview-type.ts";

if (interviewTypeLabel("foundation") !== "大模型基础面试") {
  throw new Error("foundation label must be user-facing");
}
if (interviewTypeLabel("project") !== "项目经历面试") {
  throw new Error("project label must be user-facing");
}
if (interviewEntryPath("foundation") !== "/") {
  throw new Error("foundation starts from the mode chooser");
}
if (interviewEntryPath("project") !== "/project") {
  throw new Error("project setup must have its own route");
}
```

将该文件加入 `frontend/package.json` 的 `test` 脚本末尾。

- [x] **Step 2: Run the test and confirm RED**

Run:

```powershell
node --experimental-strip-types frontend/lib/interview-type.test.ts
```

Expected: FAIL because `frontend/lib/interview-type.ts` does not exist.

- [x] **Step 3: Add the shared frontend business type**

创建：

```typescript
export type InterviewType = "foundation" | "project";

export function interviewTypeLabel(type: InterviewType) {
  return type === "foundation" ? "大模型基础面试" : "项目经历面试";
}

export function interviewEntryPath(type: InterviewType) {
  return type === "foundation" ? "/" : "/project";
}
```

在 `frontend/lib/api.ts` 为 `SessionResponse`、`SessionView`、`GraphSessionResponse` 增加 `interview_type`，并增加：

```typescript
export function createFoundationSession() {
  return request<SessionResponse>("/api/sessions/foundation", { method: "POST" });
}
```

同时把 `Question.category` 从过窄的联合类型改为 `string`，因为题库已有 `coding`、`design` 等合法类别。

- [x] **Step 4: Move the existing project setup without changing its behavior**

将当前 `frontend/app/page.tsx` 的完整组件移动到 `frontend/app/project/page.tsx`，只做以下路径级修改：

- 默认导出改名为 `ProjectInterviewSetupPage`。
- 页面标题明确为“项目经历面试”。
- Brand 仍链接 `/`。
- 创建会话仍调用 `createSession(profile.profile_id, "graph")`。
- 上传、识别候选项目、单项目选择、AI 整理与确认逻辑保持原样。

- [x] **Step 5: Replace root page with the mode chooser**

新的 `frontend/app/page.tsx` 只保留模式选择与基础会话启动状态。关键行为为：

```tsx
async function startFoundation() {
  setBusy(true);
  setError("");
  try {
    const session = await createFoundationSession();
    router.push(`/interview/${session.session_id}`);
  } catch (caught) {
    setError(caught instanceof Error ? caught.message : "创建基础面试失败，请稍后重试。");
  } finally {
    setBusy(false);
  }
}
```

页面呈现两个卡片：

- “大模型基础面试”：说明“从题库抽取 5 道题，无需上传简历”，按钮调用 `startFoundation`。
- “项目经历面试”：说明“上传简历并围绕一个真实项目深挖”，链接 `/project`。

- [x] **Step 6: Add minimal responsive mode-card CSS**

在 `frontend/app/globals.css` 复用 `.mint-card`、`.mint-button` 与现有变量，仅增加：

```css
.mint-mode-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }
.mint-mode-card { display: flex; min-height: 280px; flex-direction: column; padding: 30px; }
.mint-mode-card .mint-button { margin-top: auto; align-self: flex-start; }

@media (max-width: 760px) {
  .mint-mode-grid { grid-template-columns: 1fr; }
}
```

- [x] **Step 7: Restart services and verify frontend navigation**

重启前后端，确认健康请求为 200，然后运行：

```powershell
npm.cmd --prefix frontend test
npm.cmd --prefix frontend exec tsc -- --noEmit
```

Expected: PASS；访问 `/` 能看到两个入口，访问 `/project` 能看到原有三步项目准备流程。

- [x] **Step 8: Commit the entry split**

```powershell
git add frontend/app/page.tsx frontend/app/project/page.tsx frontend/app/globals.css frontend/lib/api.ts frontend/lib/interview-type.ts frontend/lib/interview-type.test.ts frontend/package.json
git commit -m "feat: split foundation and project interview entry"
```

### Task 5: 让共享面试页正确呈现基础题

**Files:**

- Modify: `frontend/app/interview/[id]/page.tsx`
- Modify: `frontend/lib/interview-graph.ts`
- Modify: `frontend/lib/interview-graph.test.ts`
- Modify: `frontend/lib/interview-type.ts`
- Modify: `frontend/lib/interview-type.test.ts`

**Interfaces:**

- Consumes: `SessionView.interview_type` and `GraphSessionView.interview_type`。
- Produces: `interviewStageLabel(type, completed, total) -> string`。
- Guarantees: 基础题显示一次，Graph 和 Dialog 的现有对话不重复显示。

- [x] **Step 1: Write failing label and graph normalization tests**

先将 `interview-type.test.ts` 顶部 import 更新为下面内容，再增加断言：

```typescript
import {
  interviewEntryPath,
  interviewStageLabel,
  interviewTypeLabel,
} from "./interview-type.ts";

if (interviewStageLabel("foundation", 2, 5) !== "基础面试 · 已答 2/5") {
  throw new Error("foundation stage label is incorrect");
}
if (interviewStageLabel("project", 2, 6) !== "项目面试 · 已答 2/6") {
  throw new Error("project stage label is incorrect");
}
```

在 `interview-graph.test.ts` 断言：

```typescript
if (active.interview_type !== "project") {
  throw new Error("graph sessions are project interviews");
}
```

- [x] **Step 2: Run frontend tests and confirm RED**

Run:

```powershell
npm.cmd --prefix frontend test
```

Expected: FAIL because the new stage helper and Graph business type are missing.

- [x] **Step 3: Add mode-aware labels**

在 `frontend/lib/interview-type.ts` 增加：

```typescript
export function interviewStageLabel(type: InterviewType, completed: number, total: number) {
  const prefix = type === "foundation" ? "基础面试" : "项目面试";
  return `${prefix} · 已答 ${completed}/${total}`;
}
```

`normalizeGraphState` 固定返回 `interview_type: "project"`；`GraphSessionView` 同步增加该字段。

- [x] **Step 4: Render the foundation current question**

在 `frontend/app/interview/[id]/page.tsx` 的聊天区中、`timeline.map` 之前加入：

```tsx
{!isGraph && !isDialog && question && (
  <div className="mint-msg">
    <div className="mint-ava">✦</div>
    <div className="mint-msg-body">
      <div className="mint-who">面试官</div>
      <div className="mint-bubble">{question.prompt}</div>
    </div>
  </div>
)}
```

阶段标题使用 `session.interview_type`，Graph 地图保留在项目模式；基础模式不展示项目节点地图。基础题提交继续复用现有 `submitAnswer → decideFollowup → getSession → assessSession` 链路。

- [x] **Step 5: Restart services and verify both render paths**

重启服务并确认健康请求为 200，然后运行：

```powershell
npm.cmd --prefix frontend test
npm.cmd --prefix frontend exec tsc -- --noEmit
```

手动检查：

1. 基础面试进入后立即看到第 1 道题。
2. 基础面试不显示项目地图。
3. 项目面试仍显示 6 节点地图和完整上下文对话。
4. 两种模式都能提交、“我不知道”和跳过。

- [x] **Step 6: Commit the shared interview UI**

```powershell
git add frontend/app/interview/[id]/page.tsx frontend/lib/interview-graph.ts frontend/lib/interview-graph.test.ts frontend/lib/interview-type.ts frontend/lib/interview-type.test.ts
git commit -m "feat: render foundation interviews in shared room"
```

### Task 6: 在历史记录和报告中区分两种模式

**Files:**

- Modify: `backend/app/reporting_flow.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/tests/test_api.py`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/app/history/page.tsx`
- Modify: `frontend/app/report/[id]/page.tsx`
- Modify: `frontend/lib/interview-type.ts`
- Modify: `frontend/lib/interview-type.test.ts`

**Interfaces:**

- Adds: `interview_type` to `InterviewHistoryItem` and `ReportResponse`。
- Produces: `interviewRecordTitle(type, projectName) -> string`。
- Guarantees: 基础会话没有项目名时显示“大模型基础面试”，不显示“未命名项目”。

- [x] **Step 1: Write failing backend history/report tests**

在已有 API 测试中创建一个基础会话并完成最小回答，断言：

```python
history_item = next(
    item for item in client.get("/api/interviews/history").json()
    if item["session_id"] == session_id
)
assert history_item["interview_type"] == "foundation"
assert history_item["project_name"] is None

report = client.get(f"/api/sessions/{session_id}/report")
assert report.status_code == 200
assert report.json()["interview_type"] == "foundation"
```

现有 Graph 报告测试增加 `interview_type == "project"`。

- [x] **Step 2: Run backend tests and confirm RED**

Run:

```powershell
python -m pytest backend/tests/test_api.py backend/tests/test_graph_scoring_observability.py -q
```

Expected: FAIL because history and report responses do not contain the field.

- [x] **Step 3: Add type to backend read models**

`list_interview_history` 对每条会话增加：

```python
"interview_type": interview_type_from_mode(session.mode),
```

`get_report` 保留读取到的 session，并在返回前注入：

```python
session = _get_active_session(db, session_id)
payload = get_persisted_report(db, session_id) or _build_report_payload(db, session_id)
payload["interview_type"] = interview_type_from_mode(session.mode)
payload["transcript"] = _build_transcript(db, session_id)
return payload
```

在 `InterviewHistoryItem` 与 `ReportResponse` 中将字段声明为 `Literal["foundation", "project"]`。

- [x] **Step 4: Write failing frontend title tests**

将 `frontend/lib/interview-type.test.ts` 顶部 import 更新为下面内容，再增加断言：

```typescript
import {
  interviewEntryPath,
  interviewRecordTitle,
  interviewStageLabel,
  interviewTypeLabel,
} from "./interview-type.ts";

if (interviewRecordTitle("foundation", null) !== "大模型基础面试") {
  throw new Error("foundation history must not show unnamed project");
}
if (interviewRecordTitle("project", "DeepResearch") !== "DeepResearch") {
  throw new Error("project history must prefer the project name");
}
```

- [x] **Step 5: Implement history and report copy**

在 `frontend/lib/interview-type.ts` 增加：

```typescript
export function interviewRecordTitle(type: InterviewType, projectName: string | null) {
  return type === "foundation" ? "大模型基础面试" : projectName || "项目经历面试";
}
```

历史卡片标题调用该函数，并在日期旁增加模式标签。报告页 overline 显示模式名称，“再做一场”跳转规则为：

```typescript
router.push(interviewEntryPath(report.interview_type));
```

- [x] **Step 6: Restart services and confirm GREEN**

重启前后端并确认健康请求为 200，然后运行：

```powershell
python -m pytest backend/tests/test_api.py backend/tests/test_graph_scoring_observability.py -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend exec tsc -- --noEmit
```

Expected: PASS；基础记录与项目记录有清晰标题，存量 `dialog` 记录显示为项目面试。

- [x] **Step 7: Commit result labeling**

```powershell
git add backend/app/reporting_flow.py backend/app/schemas.py backend/tests/test_api.py frontend/lib/api.ts frontend/app/history/page.tsx frontend/app/report/[id]/page.tsx frontend/lib/interview-type.ts frontend/lib/interview-type.test.ts
git commit -m "feat: label interview modes in history and reports"
```

### Task 7: 全链路回归、成本验证与交付

**Files:**

- Modify: `README.md`
- Verify: `backend/tests/`
- Verify: `frontend/`
- Verify: `backend/scripts/eval_interview_graph.py`
- Verify: `docs/superpowers/plans/2026-09-08-foundation-project-interview-modes.md`

**Interfaces:**

- Confirms: 两个入口独立、评分共享、Graph 不退化、人民币成本继续记录。
- Documents: 新入口、API、内部兼容映射与非目标。

- [x] **Step 1: Update README with exact user flows**

在 README 的运行与功能部分加入：

```markdown
## 面试模式

- 大模型基础面试：在首页一键开始，从本地题库抽取 5 道技术题，不需要简历。
- 项目经历面试：进入 `/project`，上传简历、选择一个项目并完成 AI 整理后，由 LangGraph 进行上下文追问。

基础会话接口：`POST /api/sessions/foundation`
项目会话接口：`POST /api/sessions` 创建 `mode=graph` 会话，再调用 `/api/sessions/{id}/graph/start`。
```

- [x] **Step 2: Run full backend verification**

Run:

```powershell
python -m pytest backend/tests -q
```

Expected: 全部通过，失败数为 0。

- [x] **Step 3: Run Graph quality regression**

Run:

```powershell
python backend/scripts/eval_interview_graph.py --cases backend/tests/fixtures/interview_graph_cases.json --output data/evals/interview-graph-mode-split.json
```

Expected: 全部 Graph gates 通过，项目问题链未因入口拆分发生退化。

- [x] **Step 4: Run frontend verification**

Run:

```powershell
npm.cmd --prefix frontend test
npm.cmd --prefix frontend exec tsc -- --noEmit
```

Expected: 两条命令退出码均为 0。

- [x] **Step 5: Verify observability remains shared**

分别完成一场基础面试和一场项目面试，将两次创建响应返回的真实 `session_id` 传给 `/api/observability/summary` 的 `session_id` 查询参数。确认两种会话都能看到模型调用次数、Token、延迟和人民币成本；基础会话创建本身不调用模型，因此成本只来自追问与评分。

- [x] **Step 6: Perform browser acceptance**

按顺序检查：

1. `/` 只展示“大模型基础面试”和“项目经历面试”两个主要入口。
2. 未上传简历时可以一键进入基础面试，看到 5 道题中的第 1 道。
3. 基础问题不包含项目经历题或行为题；提交后可以出现一次自然追问。
4. 基础面试完成后生成 A/B/C/D 报告，历史标题为“大模型基础面试”。
5. `/project` 完整保留上传、项目识别、单项目选择、AI 整理和确认流程。
6. 项目面试进入 Graph 地图，后续问题承接上一轮答案，完成后报告标题显示项目模式。
7. 刷新进行中的两种会话都能恢复，已保存回答不会丢失。

- [x] **Step 7: Restart services and perform final health check**

重启明确监听 8010 与 3000 的进程，随后运行：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8010/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000/
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000/project
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:3000/console
```

Expected: 四个请求均返回 200，页面样式文件正常加载。

- [x] **Step 8: Check the final diff and commit documentation**

Run:

```powershell
git diff --check
git status --short
```

只暂存本计划涉及的 README 与计划勾选更新：

```powershell
git add README.md docs/superpowers/plans/2026-09-08-foundation-project-interview-modes.md
git commit -m "docs: document dual interview modes"
```

## Explicit Non-Goals

- 不增加“综合模拟面试”第三模式。
- 不在第一版增加题目数量、难度、公司风格和知识点的手动配置。
- 不把基础题接入 LangGraph；基础题之间不需要项目事实依赖与事实核验路由。
- 不删除 `dialog` 存量实现和存量会话。
- 不修改 A/B/C/D 规则、模型价格配置、人民币成本计算和现有可观测性表结构。
- 不增加语音输入、倒计时、排行榜或远程账号系统。

## Definition of Done

- 新用户没有简历也能开始 5 题基础面试。
- 项目面试仍必须选择一个已整理项目并使用 LangGraph。
- 前端入口、面试页、历史记录和报告都能明确区分两种模式。
- 两种模式共享现有评分、能力画像、报告与成本观测。
- 所有 backend tests、frontend tests、TypeScript 检查和 Graph eval 通过。
- 每次代码修改后均完成服务重启，最终 8010 与 3000 保持运行且健康请求为 200。
