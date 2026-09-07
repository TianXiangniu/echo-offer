# 实用性优化总体设计（Practicality Optimization Design）

> **文档性质：** 这是覆盖多个迭代的总体设计文档，不是单个 implementation plan。每个模块（M0–M5）在动工前应按现有惯例拆成独立的 implementation plan（Goal / Architecture / File Map / Interfaces / Tasks）。
>
> **实施状态（2026-09-04）：** M0～M5 已全部实现并通过全量回归（后端 pytest 184 项、前端 tsc + 契约测试）。落地时与本文的差异：M2 平行题池与 M5 领域扩展合并实现（10 个知识点、每点 2–3 道平行题，会话从池中动态抽 5 道，锚题槽位从锚题知识点池抽取）；M3 专项练习（drill）对没有平行题池的项目类知识点回退为相邻知识点基础题；练习反馈、追问决策与追问回答分别落地为 `question_feedbacks`、`interview_followups` 表（迁移 0005–0008）。

**Goal:** 把"简历 → 8 道固定题 → 离线盲评分 → 报告"这个严谨但静态的评估器，升级为"有追问、题目可复用、练了能提分"的备面教练，同时保持评分可信度工程（证据校验、幂等、审计链）不被破坏。

**现状结论（设计依据）:**

- 评估端很强：盲评分 + 逐字证据校验（quote 必须在回答原文中，否则判 invalid）+ 回答 SHA-256 + AssessmentBatch/OperationJob 审计链 + 失败重评不丢数据。
- 面试端很弱：8 道写死的题（`question_bank.py`）、无追问、答完 8 题才批量评分、每场一模一样。
- 已采集但闲置的数据：AI 项目分析产出的 `followup_if_incomplete` / `followup_if_conflicting`（`backend/app/schemas.py:142`）运行时不使用。
- 已确认 bug：报告页 `rubricLabels` 映射（`mechanism/boundary/tradeoff/failure_mode`）与后端实际 rubric_id（`correctness/mechanism/scenario/engineering`）不匹配，四个维度中三个落到兜底文案"回答表现"。
- 已知占位：`backend/app/rubrics.py` 的 `reference_facts` 恒为空元组、weight 恒 1.0，盲评分 prompt 里"允许的参考事实"实际为空。

**优先级路线图:**

| 模块 | 内容 | 优先级 | 依赖 |
|---|---|---|---|
| M0 | Bug 修复与评分器实质化 | P0（先做，半天） | 无 |
| M1 | 追问器（每题最多 1 次、全场 4 次） | P0 | 无 |
| M2 | 平行题库与抽题策略 | P0 | 无 |
| M3 | 练习闭环（薄弱项重练 + 延迟验证） | P1 | M2 |
| M4 | 逐题即时练习反馈 | P1 | 无 |
| M5 | 领域覆盖扩展（新知识点 + 实战题） | P2 | M2 |
| — | 语音 / 多用户 / OCR / 部署 | 明确不做 | — |

**全局约束（适用于所有模块）:**

- 不破坏盲评分：任何在"回答阶段"新增的模型调用，都不得输出分数或等级，其输出不得进入评分上下文。
- 不破坏首答不可变：`submit_answer` 的首答幂等与 payload hash 机制原样保留，新功能以"追加"而非"修改"的方式扩展数据。
- 所有新表走 Alembic 迁移；所有提交只保留在本地分支，不执行 git push。
- 用户界面不暴露内部术语（Rubric 快照、盲评分器、OperationJob、租约等）。

---

## M0 — Bug 修复与评分器实质化（P0，先行）

### M0.1 修复报告页 Rubric 标签映射

**问题：** `frontend/app/report/[id]/page.tsx:19` 的映射键与后端 `rubrics.py` 实际产出的 rubric_id 不一致。

**方案：** 映射改为四项真实键：

```ts
const rubricLabels: Record<string, string> = {
  correctness: "概念对不对",
  mechanism: "怎么工作",
  scenario: "场景里怎么用",
  engineering: "边界与故障",
};
```

旧键（boundary/tradeoff/failure_mode）保留为兼容别名（历史上已冻结的报告 JSON 里若存过这些 id，仍能显示），但不再出现在新报告中。

**验收：** 前端契约测试断言报告页对 `correctness/scenario/engineering` 三个 id 各有非兜底中文标签；对旧 id 仍能渲染。

### M0.2 reference_facts 实质化

**问题：** `rubrics.py` 中每题四个 criterion 的 `reference_facts` 恒为空，评分 prompt 里"允许的参考事实"为空列表，盲评分只靠 criterion 文本，区分度不足。

**方案：**

- 在 `question_bank.py` 的每个 `QuestionSpec` 上增加可选字段 `reference_facts: tuple[str, ...] = ()`，按知识点为 5 道固定题（非项目题）各写 3–6 条参考事实。示例（`rag.retrieval_diagnosis`）：
  - "先分桶统计坏案例：无召回 / 召回不相关 / 排序靠后"
  - "用标注好的评测集量化召回率与 nDCG，再定位是分块还是嵌入问题"
  - "区分查询侧改写与索引侧问题，分别给出验证方法"
- 项目题（AI 生成）的参考事实从项目分析结果中已有的事实字段（facts / core fields）程序化填充，不新增模型调用。
- `build_rubric` 把 `spec.reference_facts` 写入 Rubric 快照；评分 prompt（`assessment_engine.py`）在"允许的参考事实"一节填入真实内容；无内容时该节省略（保持现状行为）。
- 权重暂保持 1.0（改动留到 M5），本次只实化事实。

**边界：** 参考事实是"允许的答题要点"而非唯一正确答案；评分 prompt 需明确"回答只要覆盖同等信息即可，措辞不必与参考事实一致"，避免评分器变成关键词匹配。

**验收：** 评估引擎测试注入带 reference_facts 的快照，断言评分 prompt 包含这些事实；空快照回退现状。

---

## M1 — 追问器（P0）

### 目标与体验

真实面试的杀伤力在追问。规则沿用设计书：**每题最多追问 1 次，全场最多追问 4 次**。流程：

```
用户提交首答 → 追问决策（轻量模型调用，不出分）
  ├─ 不追问 → 题目完成，进入下一题
  └─ 追问 → 追问题展示在首答下方 → 用户提交追问回答 → 题目完成
全部题目完成 → 批量盲评分（首答 + 追问回答一起作为评分上下文）
```

### 追问决策逻辑

**决策输入（单次调用，JSON mode）：**

- 当前题目文本 + 冻结 Rubric（criterion 文本 + reference_facts）
- 首答全文
- AI 项目分析阶段为该题预备的两条追问（`followup_if_incomplete` / `followup_if_conflicting`），项目题 1–3 可用；固定题 4–8 无预置追问，由决策模型现场生成
- 本场已用追问次数

**决策输出（JSON）：**

```json
{
  "should_followup": true,
  "reason": "incomplete | conflicting | probe",
  "followup_question": "你说做了混合检索，具体 BM25 和向量的权重是怎么定的？",
  "max_chars": 600
}
```

**规则约束（程序侧强制，不信任模型）：**

- `should_followup=false` 直接完成题目。
- 全场追问计数 `>= 4` 时跳过模型调用，直接完成（省 token、行为可预期）。
- 题目状态为 `skipped` / `explicit_unknown` 时绝不追问。
- 追问文本长度上限 300 字符；超出由程序截断或判 invalid 重试一次。
- `explicit_unknown` 的回答：不追问（用户已声明不会，追问无练习价值）。

**与盲评分的隔离：** 决策调用是一次独立的单轮调用，system prompt 明确禁止输出任何评分、等级或"答得好/不好"的结论，只输出追问决策。provider 侧新增 `decide_followup()` 方法（Protocol 扩展），与评分 provider 分开注入，测试中可独立 mock。

### 数据模型（Alembic 迁移）

新表 `interview_followups`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str PK | UUID |
| question_id | str FK → questions | 所属题目 |
| round | int | 恒为 1（预留多轮） |
| question_text | str | 追问题文本 |
| decision_reason | str | incomplete/conflicting/probe |
| answer_text | str nullable | 追问回答，未答为 NULL |
| answer_hash | str nullable | 追问回答 SHA-256 |
| status | str | pending → answered / waived |
| created_at / answered_at | datetime | |

新列 `sessions.followup_budget_used`（int, default 0）。

### 接口

- `POST /api/questions/{id}/followup/decide` — 提交首答后由前端调用。返回 `{followup: {...}}` 或 `{followup: null}`（不追问）。幂等：同一题目重复调用返回已生成的追问（有则返回，无则按"已 waived"处理），不重复调模型。
- `POST /api/questions/{id}/followup/answer` — 提交追问回答，body 含 `client_submission_id`（复用首答的幂等模式）。一次提交，不可修改（沿用首答不可变原则）。
- 会话详情与报告接口的 `rubric_items` 不变；评分时把追问回答拼进该题的评分上下文（见下）。

### 评分侧改造

- `assess_session` 组装每题 case 时，若有 `status=answered` 的追问，则在 user 内容中追加一节：

  ```
  【追问】
  问：{followup_question}
  答：{followup_answer_text}
  ```

- **证据校验扩展：** quote 允许命中首答或追问回答之一；evidence span 记录 `source: "answer" | "followup"`，回答 SHA-256 校验按对应文本计算。
- 盲评分 prompt 增加一句："追问回答与首答共同作为该题的完整回答，评分时综合考量，不因追问本身而扣分。"

### 前端

- `/interview/[id]`：提交首答后调用 decide；返回追问时在首答下方渲染追问卡（视觉上区分"追问"标签），提交后显示"本题完成"。追问预算（剩余次数）不显示具体数字，只显示状态。
- 报告页：每题的"你的回答"区按 首答 / 追问 分块展示。

### 边界情况

- decide 调用失败：题目照常可完成（追问是增强不是门槛），前端提示"追问生成失败，可继续下一题"。
- 用户提交首答后直接离开：追问保持 pending，回到会话时重新 decide（幂等返回既有结果）。
- 追问回答为空字符串：视为 `skipped`，题目仍完成，评分只用首答。

### 验收标准

- 全场追问次数由程序侧硬约束为 ≤ 4（集成测试：9 次连续 decide 只成功 4 次）。
- 追问回答参与评分且证据校验覆盖双文本源。
- 首答幂等与不可变语义不变（回归现有 test_api 用例）。

---

## M2 — 平行题库与抽题策略（P0）

### 目标

用户第二场面试不再看到完全相同的 8 道题。每个知识点准备 3–5 道平行题（考察同一知识点、不同切入场景），创建会话时按知识点抽题，并尽量避免与用户近期做过的题重复。

### 题库结构

`question_bank.py` 重构为按知识点组织的模板池：

```python
QUESTION_TEMPLATES: dict[str, list[QuestionTemplate]] = {
    "rag.retrieval_diagnosis": [
        QuestionTemplate(text=..., signals=..., reference_facts=...),
        ...  # 3–5 道
    ],
    ...
}
```

- 每道模板题自带独立的 `signals` 与 `reference_facts`；Rubric 四 criterion 模板不变，但 criterion 文本允许按题微调。
- 项目题 1–3 仍由 AI 按简历生成（已有能力），本次不动。
- 锚题规则（第 1/4/7 题为锚题）保持：从锚题知识点的模板池中抽。

### 抽题策略

`create_session` 新增抽题逻辑：

1. 对 8 个知识点，各查出该用户近 N 场（默认 3 场）已使用的模板题 id 集合。
2. 从该知识点的模板池中过滤掉近期用过的；若池中全部用过，则重置（允许重复，选最久未用的）。
3. 在剩余候选中随机抽取。
4. Rubric 快照照旧在创建时冻结进 `rubric_json`——评分链路无需感知题目来自哪个模板。

**数据模型：** `questions` 表新增可空列 `template_id`（str），记录题目来源模板；项目题为 NULL。无需新表。

### 验收标准

- 同一用户连续创建 3 场会话，固定题 4–8 的题目文本不完全相同（概率性断言：用固定种子测试确定性；另加一条"近期用过的模板被降权/排除"的单元测试）。
- 项目题生成链路不受影响。
- 报告与画像按知识点聚合的逻辑不受影响（画像本来就按 knowledge_point_id 聚合，与具体题目文本无关）。

---

## M3 — 练习闭环（P1，依赖 M2）

### 目标

把画像页的"优先回看 / 接着练 / 再答几次"从静态清单变成可执行的训练动作：薄弱项 → 重练（平行题）→ 延迟验证（隔几天再测）→ 状态更新。

### 会话类型

`sessions` 表新增两列：

- `session_kind`：`interview`（默认，现有行为）| `drill`（专项重练）| `verification`（延迟验证）
- `source_recommendation_id`：可空，drill/verification 会话回链到画像建议

### 流程设计

**专项重练（drill）：**

- 画像页"接着练"动作 → `POST /api/profile/recommendations/{id}/drill` → 创建一个 `session_kind=drill` 的迷你会话：仅 3 题（该知识点的 1 道项目相关题可省略，直接用 2 道该知识点平行题 + 1 道相邻知识点题），Rubric 照常冻结。
- drill 会话复用现有答题、批量评分、报告全链路——**不新建评分通道**，这是本模块最大的省力点。
- 报告页顶部对 drill 会话显示"专项练习"上下文条，并回链画像。

**延迟验证（verification）：**

- drill 完成且该知识点等级提升后，建议状态自动推进为"已练习，待验证"；记录 `practice_completed_at`（画像建议表新增可空时间列）。
- 画像页在 `practice_completed_at + 3 天` 之后（3 天为常量，暂不做配置）将建议显示为"可以验证了"，动作按钮创建 `session_kind=verification` 的单题会话（该知识点 1 道未用过的平行题）。
- verification 评分落库后，画像引擎照常聚合（它本来就取最近 5 个样本加权），建议状态推进为"已验证"；若等级回落，则重新进入"优先回看"。

### 边界情况

- 同一建议重复点击"接着练"：若已有未完成的 drill 会话，直接跳转该会话而不是新建。
- verification 会话未完成：建议停留在"待验证"，无惩罚。
- 历史数据兼容：存量会话 `session_kind` 默认 `interview`，画像与历史页逻辑不变。

### 验收标准

- drill 会话走完整评分链路并在画像中计入样本（加权规则不变）。
- 建议状态机 `待练习 → 已练习待验证 → 已验证`（含回落路径）有单元测试覆盖。
- 前端契约测试覆盖三个新动作按钮与状态文案。

---

## M4 — 逐题即时练习反馈（P1）

### 目标

答完一题立刻得到一段白话点评（哪里没答到、追问会挖什么），不必等 8 题全部答完。**与正式分数严格隔离。**

### 隔离原则（本模块的硬约束）

- 反馈调用是独立 provider 方法 `feedback_for_answer()`，system prompt 明确禁止输出分数、等级、Rubric 术语。
- 反馈文本存独立表，评分链路（assess_session 组装 case 时）**不读取**该表——用代码保证隔离，而非靠 prompt。
- 前端明确标注"练习提示，不计入正式评估"。

### 数据模型与接口

新表 `question_feedbacks`：

| 字段 | 类型 | 说明 |
|---|---|---|
| id | str PK | |
| question_id | str FK | 一题一条，重复请求覆盖 |
| content | str | 白话点评，≤ 500 字符 |
| focus_hints | JSON | 2–3 条"如果面试官继续挖，会问什么"（配合 M1 的实际追问） |
| created_at | datetime | |

- `POST /api/questions/{id}/feedback` — 生成（若已有且首答未变则直接返回，不重复调模型；首答 hash 变化不可能发生，因首答不可变）。
- 反馈在首答提交后由前端异步请求，不阻塞"下一题"按钮。

### 时序与追问的关系

推荐时序：提交首答 → 并行发起（a）追问 decide、（b）练习反馈。若触发追问，反馈卡与追问卡同屏（反馈在前、追问在后）。M4 不依赖 M1，可独立上线。

### 验收标准

- 评分引擎测试断言 case 组装不含 question_feedbacks 数据（代码级隔离回归）。
- 反馈接口幂等（同题二次调用不重复计费）。
- 前端不显示任何分数/等级于反馈卡。

---

## M5 — 领域覆盖扩展（P2，依赖 M2）

### 新知识点

在 8 个现有知识点外新增（每个先配 2–3 道模板题，后续按 M2 补到 3–5 道）：

| knowledge_point_id | 覆盖的 JD 考点 |
|---|---|
| `mcp.tool_ecosystem` | MCP 协议、tool 生态集成、schema 设计 |
| `multi_agent.orchestration` | 多智能体编排、任务分解、消息传递、失败隔离 |
| `evals.observability` | Agent 评估体系、trace、回归测试、线上监控 |
| `memory.design` | 短期/长期记忆、上下文管理、遗忘策略 |
| `coding.debug_tool_call` | 实战题：给一段有 bug 的 tool-call 代码找问题 |

- 新增后单场会话题量从 8 → 10（题 1–3 项目题 + 7 道知识题中抽固定数量；具体分配在实施 plan 里定，原则是锚题结构保持）。
- `skills` 技能目录、角色技能要求、画像聚合同步扩充（画像引擎按 knowledge_point_id 聚合，理论上是纯数据扩充）。

### 实战题形态（`coding.debug_tool_call`）

- 题目文本含一段 20–40 行的问题代码（Python，展示一个典型的 tool-call 错误：如未校验工具参数、异常吞掉导致死循环、重试无退避等）。
- 作答仍是 textarea（保持技术栈不变，不引入代码编辑器），用户用文字指出问题与修法。
- Rubric 对这类题微调：`correctness` 权重提高（如 1.5），`scenario` 权重降为 0.5——这是 reference_facts 之外第一次实际使用 weight 字段。
- 评分 prompt 中代码块原样传入，证据 quote 校验对代码题仍针对**回答文本**（不含题目代码），无需改校验器。

### 验收标准

- 新知识点的平行题、Rubric 快照、评分、画像聚合端到端跑通（注入假 provider 的集成测试）。
- 权重非 1.0 时单题百分制计算正确（`score_100` 计算已有测试文件，补充加权用例）。

---

## 明确不做（本期范围外）

- **语音面试（STT/TTS）：** 等文字追问闭环（M1）验证有真实练习价值后再评估。
- **多用户/登录/部署（Docker）：** 当前定位是本地单用户工具；若决定开源或产品化，另立设计文档。
- **OCR 扫描件解析、多求职方向、多 Provider 接入。**
- **AI 评分 SSE、证据语义相关性验证、技术事实核验：** 维持 README 中"暂缓"结论。

## 实施顺序建议

```
M0（半天，先修用户可见的 bug）
→ M1 追问器（核心卖点，最大模块）
→ M2 平行题库（可与 M1 并行，互不依赖）
→ M4 即时反馈（小，可穿插）
→ M3 练习闭环（依赖 M2）
→ M5 领域扩展（数据性工作，可拆散到各迭代间隙）
```

每个模块动工前按惯例产出独立 implementation plan（含 File Map / Interfaces / checkbox Tasks），并遵守全局约束。
