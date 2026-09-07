# “我还要补什么？”能力概况重设计 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 /profile 从抽象的能力仪表盘改成以具体历史问题为入口的薄弱项清单，让用户知道下一步先回看什么，并能回到对应面试报告。

**Architecture:** 后端继续使用现有画像、面试题、回答和评估记录，动态派生每条建议的来源问题，不新增模型调用、数据库表或持久化字段。前端保留多求职方向选择、建议状态和长期记录，但把首屏主任务改为“优先回看 / 接着练 / 再答几次看看”，用稳定的报告锚点连接真实问题。

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, SQLite, Next.js 15, React 19, TypeScript, CSS, pytest, Node.js contract tests.

## Global Constraints

- 本次不增加专项练习流程。
- 本次不改评分模型、Rubric、评分等级或 100 分计算方式。
- 本次不增加雷达图、复杂趋势图或新的统计指标。
- 本次不删除数据库中的画像快照和面试记录。
- 不增加新的模型请求；来源信息必须由现有数据库记录派生。
- 不增加数据库表和持久化字段；接口新增字段全部由查询结果动态返回。
- 用户主界面不显示 priority、status、profile_snapshot、last_session_id、有效样本、稳定程度、证据覆盖率、冻结事实、盲评分器等内部概念。
- 沿用现有本地单用户模式、多方向选择器和建议状态更新接口。
- 所有提交只保留在本地分支，不执行 git push。

---

## File Map

- Modify: backend/app/schemas.py — 为 LearningRecommendationResponse 增加五个可空来源字段。
- Modify: backend/app/profile_engine.py — 保持画像计算逻辑不变，只把建议原因和练习文案改成自然中文，避免将 0–4 等级和岗位目标写进用户文案。
- Modify: backend/app/services.py — 新增 _find_recommendation_source 查询 helper，并在建议响应和状态更新响应中返回来源信息。
- Modify: backend/tests/test_profile_api.py — 覆盖有效来源、同技能多题选择、无效评估和隐藏面试来源。
- Modify: backend/tests/test_profile_engine.py — 保留现有优先级单元测试，并补充来源选择规则的边界测试入口。
- Modify: frontend/lib/api.ts — 同步 LearningRecommendation 的来源字段类型。
- Modify: frontend/app/report/[id]/page.tsx — 给每道题的第一个报告内容容器增加 question-{question_id} 稳定 id。
- Modify: frontend/app/profile/page.tsx — 保留数据加载和状态更新逻辑，重做右侧主体为薄弱项摘要、三段清单、次级完整记录和历史记录。
- Modify: frontend/app/globals.css — 增加薄弱项清单、来源回答、练习动作和移动端布局样式，并保留键盘焦点与减少动态效果支持。
- Modify: frontend/lib/profile-page.test.ts — 更新页面文案契约，检查自然中文和来源跳转，不允许内部术语回到主界面。
- Create: frontend/lib/profile-weak-points.test.ts — 单独覆盖来源字段、报告锚点、空来源和三段清单的前端静态契约。
- Modify: frontend/package.json — 将新的前端契约测试接入 npm test。
- Modify: README.md — 简要记录能力页面现在以历史问题回看和练习建议为主，不记录内部实现术语。

## Interfaces

后端新增的推荐响应字段固定为：

~~~python
{
    "source_session_id": str | None,
    "source_question_id": str | None,
    "source_question": str | None,
    "source_answer_excerpt": str | None,
    "source_level": int | None,
}
~~~

后端来源 helper 的接口固定为：

~~~python
def _find_recommendation_source(
    db: Session,
    *,
    skill_id: str,
    preferred_session_id: str | None,
) -> dict[str, object | None]:
    """从现有记录中找出建议对应的最低等级有效回答。"""
~~~

前端链接 helper 的行为固定为：

~~~ts
function recommendationSourceHref(
  recommendation: LearningRecommendation,
): string | null {
  if (!recommendation.source_session_id || !recommendation.source_question_id) return null;
  return "/report/" + encodeURIComponent(recommendation.source_session_id)
    + "#question-" + encodeURIComponent(recommendation.source_question_id);
}
~~~

---

### Task 1: 先写后端来源字段和选择规则的失败测试

**Files:**
- Modify: backend/tests/test_profile_api.py
- Modify: backend/tests/test_profile_engine.py

**Interfaces:**
- Consumes: 现有 ai_client、ai_session_context、create_test_session、app.state.session_factory() 和 update_candidate_profile。
- Produces: 能够锁定来源字段、最低等级选择、有效状态过滤和隐藏来源行为的回归测试。

- [ ] **Step 1: 写单场有效来源测试**

在 test_valid_batch_updates_profile_and_recommendations 或其旁边增加断言：完成一场 fake 评估后，至少一条 recommendation 返回五个来源字段；source_question 必须等于该场已有 InterviewQuestion.prompt，source_answer_excerpt 必须是回答开头，且长度不超过 240。测试不得假定第一条 recommendation 就对应第一道题，只通过来源 id 回查真实记录。

~~~python
with ai_client.app.state.session_factory() as db:
    question = db.scalar(
        select(InterviewQuestion)
        .where(InterviewQuestion.session_id == session_id)
        .order_by(InterviewQuestion.order)
    )
    assert question is not None

source = next(
    item for item in body["recommendations"]
    if item["source_question_id"] is not None
)
assert source["source_session_id"] == session_id
assert len(source["source_answer_excerpt"]) <= 240
assert source["source_level"] in {0, 1, 2, 3, 4}

with ai_client.app.state.session_factory() as db:
    source_question = db.get(InterviewQuestion, source["source_question_id"])
    assert source_question is not None
    assert source["source_question"] == source_question.prompt
~~~

- [ ] **Step 2: 写同技能多题的最低等级和顺序测试**

完成 fake 评估后，在测试数据库里把同一场的两道 InterviewQuestion.knowledge_point_id 改成同一个 skill；将对应两个 AssessmentRun.aggregate_level 设为 3 和 1，调用 update_candidate_profile(db, session_id) 重新生成画像。断言推荐项选中等级 1 的问题。再将两个等级都设为 2，重新生成画像，断言选中 order 更小的问题。

~~~python
question_ids = [item["id"] for item in questions[:2]]
with ai_client.app.state.session_factory() as db:
    first = db.get(InterviewQuestion, question_ids[0])
    second = db.get(InterviewQuestion, question_ids[1])
    assert first is not None and second is not None
    second.knowledge_point_id = first.knowledge_point_id
    runs = list(
        db.scalars(
            select(AssessmentRun)
            .where(AssessmentRun.question_id.in_(question_ids))
            .order_by(AssessmentRun.question_id)
        )
    )
    assert len(runs) == 2
    runs[0].aggregate_level = 3
    runs[1].aggregate_level = 1
    db.commit()
    update_candidate_profile(db, session_id)

summary = ai_client.get("/api/profiles/" + profile_id + "/summary").json()
recommendation = next(
    item for item in summary["recommendations"]
    if item["skill_id"] == first.knowledge_point_id
)
assert recommendation["source_question_id"] == question_ids[1]
~~~

tie case 使用相同的 profile/session 数据，将两条 run 都设为 2，重新调用画像更新后断言来源为 order 更小的题。

- [ ] **Step 3: 写无效评估和隐藏面试测试**

增加两组测试：

1. 将来源题目的所有 AssessmentRun.status 改为 pending、invalid 或 rejected，确认 recommendation 仍能返回，但五个来源字段均为 None；这些状态不得被当作有效来源。
2. 将来源 InterviewSession.archived_at 设置为当前时间，确认 recommendation 保留 source_question、source_answer_excerpt 和 source_level，但 source_session_id 为 None，这样前端仍能显示问题和建议而不会生成失效链接。

~~~python
assert recommendation["source_session_id"] is None
assert recommendation["source_question"] is None
assert recommendation["source_answer_excerpt"] is None
assert recommendation["source_level"] is None
~~~

隐藏面试测试必须单独断言问题文本仍存在，防止实现为了隐藏链接而把整条薄弱项删掉。

- [ ] **Step 4: 运行新增后端测试，确认当前实现先失败**

Run: & ".\backend\.venv\Scripts\python.exe" -m pytest backend/tests/test_profile_api.py backend/tests/test_profile_engine.py -q

Expected: FAIL，失败原因应是响应缺少 source_* 字段或来源选择逻辑尚未存在；不能因为导入错误、fixture 错误或语法错误失败。

- [ ] **Step 5: Commit tests only**

~~~bash
git add backend/tests/test_profile_api.py backend/tests/test_profile_engine.py
git commit -m "test: specify profile recommendation sources"
~~~

---

### Task 2: 实现后端来源派生和自然中文建议

**Files:**
- Modify: backend/app/schemas.py:354-365
- Modify: backend/app/profile_engine.py:222-236
- Modify: backend/app/services.py:1687-1750

**Interfaces:**
- Consumes: Task 1 的来源选择测试、CandidateKnowledgeState.last_session_id、InterviewQuestion、AnswerAttempt、AssessmentRun 和 InterviewSession.archived_at。
- Produces: _find_recommendation_source(...)、包含来源字段的 _recommendation_response(...)，以及兼容原有状态更新接口的响应。

- [ ] **Step 1: 给 Pydantic 响应模型增加可空字段**

在 LearningRecommendationResponse 的 recommended_review_at 后增加：

~~~python
source_session_id: str | None = None
source_question_id: str | None = None
source_question: str | None = None
source_answer_excerpt: str | None = None
source_level: int | None = Field(default=None, ge=0, le=4)
~~~

不修改 LearningRecommendation 数据库模型，不创建 migration。

- [ ] **Step 2: 把 _recommendation_text 的用户文案改成自然中文**

保留函数返回值类型 tuple[str, list[str], list[str]]，但不再把“当前 2 级 / 岗位目标 3 级”等内部计算写进 reason。使用下面这组文案方向：

~~~python
if state.valid_sample_count == 0:
    reason = f"还没有足够的回答可以判断“{skill.canonical_name}”，先积累几次相关回答。"
    actions = [f"先回答一道{skill.canonical_name}相关问题", "说清楚自己的做法、原因和限制"]
    criteria = ["能结合具体场景讲清楚方案和取舍"]
elif gap > 0:
    reason = f"最近的回答提到了“{skill.canonical_name}”，但做法、边界或验证还可以说得更具体。"
    actions = [f"回看{skill.canonical_name}的核心机制", "用一个真实项目场景重新回答", "补上边界、故障和验证方式"]
    criteria = ["连续两次相关回答都能讲清方案、原因和限制"]
else:
    reason = f"“{skill.canonical_name}”最近保持得不错，可以继续用真实案例巩固。"
    actions = ["整理一个可复现的项目案例", "继续关注异常情况和方案取舍"]
    criteria = ["能结合场景说明方案和取舍"]
~~~

这里的 gap 只参与后端推荐优先级和文案分支，不向用户暴露数字等级。

- [ ] **Step 3: 实现 _find_recommendation_source**

在 backend/app/services.py 中新增空结果 helper 和来源查询。查询规则必须按以下顺序执行：

1. preferred_session_id 为空或 session 不存在时返回五个 None。
2. 在 preferred session 中按 InterviewQuestion.order 查询 knowledge_point_id == skill_id 的题目。
3. 每道题只取状态为 submitted 或 explicit_unknown 的最新 AnswerAttempt。
4. 每个回答只取最新一次 AssessmentRun，并且必须同时满足 status == "valid"、aggregate_level is not None。
5. 候选按 (aggregate_level, question.order, question.id) 升序取第一条。
6. source_answer_excerpt 使用 answer.answer_text[:240]，不调用模型、不拼接回答之外的事实。
7. session 已隐藏时仍返回题目、回答片段和等级，但把 source_session_id 设为 None；正常 session 返回真实 session id。

~~~python
def _empty_recommendation_source() -> dict[str, object | None]:
    return {
        "source_session_id": None,
        "source_question_id": None,
        "source_question": None,
        "source_answer_excerpt": None,
        "source_level": None,
    }


def _find_recommendation_source(
    db: Session,
    *,
    skill_id: str,
    preferred_session_id: str | None,
) -> dict[str, object | None]:
    empty = _empty_recommendation_source()
    if not preferred_session_id:
        return empty
    session = db.get(InterviewSession, preferred_session_id)
    if session is None:
        return empty

    candidates = []
    questions = db.scalars(
        select(InterviewQuestion)
        .where(
            InterviewQuestion.session_id == session.id,
            InterviewQuestion.knowledge_point_id == skill_id,
        )
        .order_by(InterviewQuestion.order.asc(), InterviewQuestion.id.asc())
    )
    for question in questions:
        answer = db.scalar(
            select(AnswerAttempt)
            .where(
                AnswerAttempt.session_id == session.id,
                AnswerAttempt.question_id == question.id,
                AnswerAttempt.status.in_(("submitted", "explicit_unknown")),
            )
            .order_by(AnswerAttempt.created_at.desc(), AnswerAttempt.id.desc())
        )
        if answer is None:
            continue
        run = db.scalar(
            select(AssessmentRun)
            .where(AssessmentRun.answer_id == answer.id)
            .order_by(
                AssessmentRun.attempt_number.desc(),
                AssessmentRun.created_at.desc(),
                AssessmentRun.id.desc(),
            )
        )
        if run is None or run.status != "valid" or run.aggregate_level is None:
            continue
        candidates.append(
            (run.aggregate_level, question.order, question.id, question, answer, run)
        )

    if not candidates:
        return empty
    _, _, _, question, answer, run = min(candidates, key=lambda item: item[:3])
    return {
        "source_session_id": None if session.archived_at is not None else session.id,
        "source_question_id": question.id,
        "source_question": question.prompt,
        "source_answer_excerpt": answer.answer_text[:240],
        "source_level": run.aggregate_level,
    }
~~~

- [ ] **Step 4: 在 _recommendation_response 中注入来源**

先按 recommendation 的 profile 和 skill 找到对应的 CandidateKnowledgeState，将其 last_session_id 传给 helper，再合并到现有响应：

~~~python
state = db.scalar(
    select(CandidateKnowledgeState).where(
        CandidateKnowledgeState.profile_id == recommendation.profile_id,
        CandidateKnowledgeState.skill_id == recommendation.skill_id,
    )
)
source = _find_recommendation_source(
    db,
    skill_id=recommendation.skill_id,
    preferred_session_id=state.last_session_id if state else None,
)
return {
    "id": recommendation.id,
    "skill_id": recommendation.skill_id,
    "skill_name": skill.canonical_name if skill else recommendation.skill_id,
    "priority": recommendation.priority,
    "reason": recommendation.reason,
    "actions": json.loads(recommendation.actions_json),
    "success_criteria": json.loads(recommendation.success_criteria_json),
    "status": recommendation.status,
    "recommended_review_at": recommendation.recommended_review_at,
    **source,
}
~~~

这样 get_profile_summary 和 update_recommendation_status 都能返回同样完整的响应，前端更新练习状态时不会丢失历史来源。

- [ ] **Step 5: 运行后端目标测试并修正实现**

Run: & ".\backend\.venv\Scripts\python.exe" -m pytest backend/tests/test_profile_api.py backend/tests/test_profile_engine.py -q

Expected: PASS，来源字段、有效状态过滤、最低等级和同等级题目顺序测试全部通过。

- [ ] **Step 6: Commit backend implementation**

~~~bash
git add backend/app/schemas.py backend/app/profile_engine.py backend/app/services.py
git commit -m "feat: expose profile recommendation sources"
~~~

---

### Task 3: 同步前端类型并先写前端契约测试

**Files:**
- Modify: frontend/lib/api.ts:190-202
- Modify: frontend/lib/profile-page.test.ts
- Create: frontend/lib/profile-weak-points.test.ts
- Modify: frontend/package.json

**Interfaces:**
- Consumes: Task 2 的 LearningRecommendationResponse 字段。
- Produces: 前端 LearningRecommendation 类型和可执行的页面静态契约，供 UI 重做时防止内部文案回归。

- [ ] **Step 1: 扩展 LearningRecommendation 类型**

在 recommended_review_at 后加入：

~~~ts
source_session_id: string | null;
source_question_id: string | null;
source_question: string | null;
source_answer_excerpt: string | null;
source_level: number | null;
~~~

- [ ] **Step 2: 写前端来源跳转和文案契约**

创建 frontend/lib/profile-weak-points.test.ts，读取 api.ts、profile/page.tsx、report/[id]/page.tsx 和 globals.css，检查：

~~~ts
assert.match(api, /source_session_id: string \| null/);
assert.match(api, /source_question_id: string \| null/);
assert.match(page, /我还要补什么/);
assert.match(page, /优先回看/);
assert.match(page, /接着练/);
assert.match(page, /再答几次看看/);
assert.match(page, /查看这次回答/);
assert.match(page, /还没有足够的回答可以判断/);
assert.match(page, /question-/);
assert.match(report, /question-/);
for (const forbidden of [
  "冻结事实",
  "盲评分器",
  "稳定程度",
  "有效样本",
  "profile_snapshot",
  "last_session_id",
]) {
  assert.equal(page.includes(forbidden), false);
}
~~~

测试使用实际页面源代码中的用户可见文案，不要求删除 TypeScript 内部变量 priority 或 status；禁止的是将内部概念写进 UI。

- [ ] **Step 3: 把契约测试接入 npm test**

在 frontend/package.json 中增加 test:profile-weak-points，并在 aggregate test 命令中放在 test:profile 后、test:score-100 前：

~~~json
"test:profile-weak-points": "node --experimental-strip-types lib/profile-weak-points.test.ts"
~~~

- [ ] **Step 4: 运行前端测试，确认 UI 尚未实现时按预期失败**

Run: npm run test:profile-weak-points

Expected: FAIL，失败应来自尚未替换的旧页面文案或尚未增加的锚点，不得来自测试脚本语法错误。

- [ ] **Step 5: Commit frontend contract**

~~~bash
git add frontend/lib/api.ts frontend/lib/profile-page.test.ts frontend/lib/profile-weak-points.test.ts frontend/package.json
git commit -m "test: specify profile weak point page contract"
~~~

---

### Task 4: 为报告页增加可回看的问题锚点

**Files:**
- Modify: frontend/app/report/[id]/page.tsx:150

**Interfaces:**
- Consumes: report.rubric_items[].question_id。
- Produces: 每道题至少一个唯一的 id="question-{question_id}"，供 /report/{session}#question-{question} 跳转。

- [ ] **Step 1: 写锚点实现前的最小检查**

先在 frontend/lib/profile-weak-points.test.ts 中保留以下约束：报告页必须根据 item.question_id 形成 question- id，且同一 question id 不能在多个并列 rubric item 上重复挂载。

- [ ] **Step 2: 在报告页只给同题第一条内容容器挂锚点**

在 rubric_items.map 前建立本次 render 使用的 Set<string>；map 中第一次遇到 question id 时设置锚点，后续同题 rubric item 的 id 为 undefined。将现有单行 map JSX 拆成带 block body 的回调，保持现有评分、回答和说明内容不变：

~~~tsx
const anchoredQuestionIds = new Set<string>();

{report.rubric_items.map((item) => {
  const shouldAnchor =
    Boolean(item.question_id) && !anchoredQuestionIds.has(item.question_id);
  if (item.question_id) anchoredQuestionIds.add(item.question_id);
  return (
    <article
      key={item.question_id + "-" + item.rubric_id}
      id={shouldAnchor ? "question-" + item.question_id : undefined}
      className="mint-report-item"
    >
      {/* existing item content */}
    </article>
  );
})}
~~~

这里的 Set 每次组件 render 都重新创建，不能放到模块级共享，避免不同报告之间互相污染。

- [ ] **Step 3: 运行报告和前端类型测试**

Run: npm run test:profile-weak-points && npm run test:assessment-types

Expected: PASS。

- [ ] **Step 4: Commit report anchors**

~~~bash
git add frontend/app/report/[id]/page.tsx
git commit -m "feat: add report question anchors"
~~~

---

### Task 5: 重做 /profile 的薄弱项主视图

**Files:**
- Modify: frontend/app/profile/page.tsx

**Interfaces:**
- Consumes: ProfileSummary.recommendations、LearningRecommendation 五个来源字段、现有 updateRecommendationStatus。
- Produces: WeakPointSummary、WeakPointSection、WeakPointCard 和 RecommendationStatusAction 的页面内实现；不在前端重新计算分数、能力等级或优先级。

- [ ] **Step 1: 添加页面内纯展示 helper**

在现有 statusAction 附近增加三段清单配置和来源链接 helper：

~~~tsx
const weakPointSections = [
  { priority: "high", title: "优先回看", description: "先回到最值得重听的一次回答。" },
  { priority: "medium", title: "接着练", description: "方向已经有了，再把细节讲完整。" },
  { priority: "insufficient_data", title: "再答几次看看", description: "记录还少，先多答几次再下结论。" },
] as const;

function recommendationSourceHref(
  recommendation: LearningRecommendation,
): string | null {
  if (!recommendation.source_session_id || !recommendation.source_question_id) {
    return null;
  }
  return "/report/" + encodeURIComponent(recommendation.source_session_id)
    + "#question-" + encodeURIComponent(recommendation.source_question_id);
}

function plainRecommendationReason(recommendation: LearningRecommendation) {
  if (!recommendation.source_question) {
    return "还没有足够的回答可以判断，先积累几次相关回答。";
  }
  if (recommendation.priority === "high") {
    return "这次回答提到了方向，但做法、边界或验证还可以说得更具体。";
  }
  if (recommendation.priority === "medium") {
    return "方向基本清楚，再补上具体做法和限制。";
  }
  return "现在的记录还少，再答几次更容易看准。";
}
~~~

plainRecommendationReason 只负责展示自然文案；动作列表和完成标准直接使用后端已经生成的数组，不在前端生成新的事实。

- [ ] **Step 2: 调整页头和摘要**

将导航当前项、overline、主标题和 lead 替换为：

~~~tsx
<span className="mint-nav-current">我还要补什么</span>
<p className="mint-overline">最近几场面试</p>
<h1 id="profile-title" className="mint-profile-title">我还要补什么？</h1>
<p className="mint-lead">根据最近几场面试，整理出最值得回看的地方。</p>
~~~

摘要卡只保留目标方向、方向说明、参考面试场次和最近更新；将“相关面试”改为“参考面试”，将“已完成”改为“已结束”，不出现“画像”“稳定程度”“有效回答”等系统名词。

- [ ] **Step 3: 用三段清单替换主能力和推荐区域**

在 summary 存在时先计算：

~~~tsx
const weakRecommendations = summary.recommendations.filter(
  (recommendation) => recommendation.priority !== "low",
);
~~~

按 weakPointSections 顺序渲染，每段只过滤对应 priority。每个 WeakPointCard 按以下顺序展示：技能主题、分区标签、真实历史问题、自然原因、source_answer_excerpt（有则显示“你当时提到：…”）、1–3 条练习动作、可选的“查看这次回答”链接、现有状态按钮。

卡片的核心结构必须类似：

~~~tsx
<article className="mint-card mint-weak-point-card">
  <div className="mint-weak-point-heading">
    <span>{recommendation.skill_name}</span>
    <span>{section.title}</span>
  </div>
  <h3>{recommendation.source_question ?? "还没有足够的回答可以判断"}</h3>
  <p className="mint-weak-point-reason">{plainRecommendationReason(recommendation)}</p>
  {recommendation.source_answer_excerpt && (
    <blockquote className="mint-weak-point-source">
      你当时提到：{recommendation.source_answer_excerpt}
    </blockquote>
  )}
  <div className="mint-recommendation-block">
    <span>建议怎么练</span>
    <ul>
      {recommendation.actions.slice(0, 3).map((item) => <li key={item}>{item}</li>)}
    </ul>
  </div>
  <div className="mint-weak-point-actions">
    {recommendationSourceHref(recommendation) && (
      <a href={recommendationSourceHref(recommendation)!}>查看这次回答</a>
    )}
    <button type="button" onClick={...}>标记为练习中</button>
  </div>
</article>
~~~

实际实现中继续复用当前 changeRecommendationStatus、loading disabled 状态、错误提示和 statusAction；已完成/暂时放一放的卡片也保留恢复操作。无来源时只隐藏链接，不隐藏薄弱项。

- [ ] **Step 4: 处理空状态和保留长期记录**

实现以下互斥显示规则：

1. 没有任何 profile choice：显示“完成一场面试后，这里会告诉你下一步先练什么”。
2. 有 profile 但 weakRecommendations.length === 0：显示“目前没有需要优先补的地方，继续保持并积累新的回答”。
3. 有 profile 且有 recommendation：显示三段清单；空的某一段显示简短说明，不伪造卡片。
4. 在主清单下方保留一个次级“查看完整记录”区域，继续展示现有 summary.skills，但把字段标签改成“最近表现”“相关回答”“最近变化”，不展示“等级 0–4”“有效回答”“稳定程度”。
5. 继续保留快照列表，但将标题和说明改成“以前的面试记录 / 每次面试都会留下一笔”，不删除历史报告链接。

- [ ] **Step 5: 更新 profile 页面契约测试并运行**

Run: npm run test:profile && npm run test:profile-weak-points

Expected: PASS，旧的“能力概况 / 接下来练什么”主界面契约被新的“我还要补什么 / 优先回看”契约替代，内部术语检查通过。

- [ ] **Step 6: Commit profile page**

~~~bash
git add frontend/app/profile/page.tsx frontend/lib/profile-page.test.ts
git commit -m "feat: redesign profile as weak point list"
~~~

---

### Task 6: 补齐薄弱项清单的视觉、响应式和可访问性样式

**Files:**
- Modify: frontend/app/globals.css:699-790
- Modify: frontend/lib/profile-weak-points.test.ts

**Interfaces:**
- Consumes: Task 5 的 mint-weak-point-*、来源回答和次级记录 class names。
- Produces: 桌面端清晰的主次层级、移动端可读卡片、可见键盘焦点和减少动态效果支持。

- [ ] **Step 1: 写样式契约**

在 profile-weak-points.test.ts 中检查以下 class names 存在于 CSS：mint-weak-point-list、mint-weak-point-card、mint-weak-point-source、mint-weak-point-actions、mint-profile-secondary 和 prefers-reduced-motion。

- [ ] **Step 2: 增加桌面端样式**

沿用现有 cream / ink / mint / coral 色彩 token，不引入渐变、霓虹色或新的工作台式面板。使用以下布局基线：

~~~css
.mint-weak-point-list { display: grid; gap: 14px; }
.mint-weak-point-card { padding: 25px 27px 24px; }
.mint-weak-point-heading { display: flex; justify-content: space-between; gap: 18px; color: var(--color-muted); font-size: 11px; }
.mint-weak-point-card h3 { max-width: 720px; margin: 18px 0 0; color: var(--color-forest); font-family: var(--font-display); font-size: clamp(21px, 2.2vw, 30px); line-height: 1.25; }
.mint-weak-point-reason { max-width: 680px; margin: 14px 0 0; color: var(--color-ink); font-size: 14px; line-height: 1.8; }
.mint-weak-point-source { margin: 16px 0 0; padding: 13px 16px; border-left: 2px solid var(--color-coral); color: var(--color-muted); font-size: 12px; line-height: 1.7; }
.mint-weak-point-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 11px; margin-top: 21px; }
.mint-weak-point-actions a { color: var(--color-forest-soft); font-size: 12px; font-weight: 700; text-decoration: none; }
.mint-weak-point-actions a:hover { color: var(--color-forest); text-decoration: underline; }
.mint-profile-secondary { margin-top: 44px; }
.mint-weak-point-card:focus-within { border-color: var(--color-forest-soft); box-shadow: 0 15px 38px rgb(24 61 50 / 8%); }
~~~

链接和按钮必须沿用全局 :focus-visible 样式；不能为了视觉简洁移除焦点轮廓。

- [ ] **Step 3: 增加移动端和减少动态效果规则**

在现有 profile media query 中加入：

~~~css
@media (max-width: 760px) {
  .mint-weak-point-card { padding: 20px; }
  .mint-weak-point-heading { align-items: flex-start; flex-direction: column; gap: 7px; }
  .mint-weak-point-card h3 { font-size: 22px; }
  .mint-weak-point-actions { align-items: stretch; flex-direction: column; }
  .mint-weak-point-actions .mint-button,
  .mint-weak-point-actions a { width: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  .mint-weak-point-card,
  .mint-weak-point-actions a,
  .mint-button {
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}
~~~

- [ ] **Step 4: 运行前端契约测试和生产构建**

Run: npm run test:profile-weak-points && npm run build

Expected: PASS，Next.js 生产构建成功，没有 TypeScript 或 CSS 解析错误。

- [ ] **Step 5: Commit styling**

~~~bash
git add frontend/app/globals.css frontend/lib/profile-weak-points.test.ts
git commit -m "style: refine profile weak point cards"
~~~

---

### Task 7: 更新说明并完成全量验证

**Files:**
- Modify: README.md

**Interfaces:**
- Consumes: 已完成的后端来源响应、报告锚点和 /profile 页面。
- Produces: 用户能理解的功能说明和最终验收证据；不修改业务逻辑。

- [ ] **Step 1: 更新 README 的功能说明**

在现有能力概况/历史记录说明附近补充简短中文说明：能力页面会按“优先回看、接着练、再答几次看看”整理建议；建议可回到对应面试报告；没有足够记录时会明确说明，不把缺失记录当成错误回答。不要在 README 中写 API key、真实 token 或内部评分器提示词。

- [ ] **Step 2: 运行后端全量测试**

Run: & ".\backend\.venv\Scripts\python.exe" -m pytest backend/tests -q

Expected: 全部 PASS；历史记录、批量评分、100 分汇总、画像更新和推荐状态接口均不回归。

- [ ] **Step 3: 运行前端全量测试和构建**

Run from frontend: npm test

Expected: 全部前端 contract tests PASS。

Run from frontend: npm run build

Expected: Next.js production build PASS。

- [ ] **Step 4: 做浏览器验收**

启动现有前后端，在有至少一场有效面试的本地数据下打开 /profile，逐项确认：

1. 首屏标题是“我还要补什么？”，主说明是“根据最近几场面试，整理出最值得回看的地方”。
2. 薄弱项按三个分区出现，低优先级能力不会混进主清单。
3. 卡片显示真实问题和回答片段；没有来源时显示“还没有足够的回答可以判断”，没有“查看这次回答”链接。
4. 点击来源链接进入 /report/{session_id}#question-{question_id}，页面滚动到对应报告内容。
5. 练习状态按钮仍能更新，更新后来源信息没有消失。
6. 隐藏来源仍保留卡片内容但不显示失效链接。
7. 缩小到手机宽度后卡片、按钮和方向选择器不溢出；Tab 可以看到焦点；系统启用减少动态效果时页面不依赖动画才能理解。

- [ ] **Step 5: Commit documentation and final local state**

~~~bash
git add README.md
git commit -m "docs: explain profile weak point workflow"
~~~

不要执行 git push；向用户汇报本地测试结果和浏览器验收结果即可。

## Self-Review Against the Approved Spec

- Section 3 UI: Task 5 覆盖标题、三段清单、卡片顺序、自然文案、空状态和建议状态操作；Task 6 覆盖响应式与焦点。
- Section 3.4 history jump: Task 4 提供稳定 question anchor，Task 5 使用完整 report/hash 链接。
- Section 4.1/4.2 response and source rules: Task 1 写失败测试，Task 2 实现五字段、有效评估过滤、最低等级和顺序 tie-break。
- Section 4.3 no database change: Global Constraints 和 Task 2 明确只做动态查询，不改模型和 migration。
- Section 5 component boundaries: Task 5 在当前单页约定下实现 WeakPointSummary、WeakPointSection、WeakPointCard 和状态动作的等价页面内边界，不为了拆文件破坏现有页面结构。
- Section 6 copy rules: Task 2 和 Task 5 移除数字等级、画像和系统验证术语的用户可见表达。
- Section 7 tests/acceptance: Task 1、Task 3、Task 4、Task 6 和 Task 7 覆盖后端、前端、构建与浏览器验收。
- No new AI request, no scoring change, no radar/trend chart, no deletion of history: each is explicitly constrained and has no implementation step that violates it.
