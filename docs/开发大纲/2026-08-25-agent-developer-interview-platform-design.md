# Agent 应用工程师 AI 模拟面试平台设计

日期：2026-08-25  
状态：P0 设计审查修订版，等待最终确认

## 1. 产品目标与 Alpha 人群

构建一个本地单用户、中文文字优先的 AI 模拟面试与训练平台。Alpha 不覆盖所有 Agent 岗位，而是固定服务于：

> 有至少一个 LLM/Agent 项目、具备 1～3 年开发经验、准备中文 Agent 应用/RAG 工程师岗位的开发者。

Alpha 的默认目标岗位为“Agent 应用工程师”。用户可以补充目标公司类型和可选 JD 文本，用于调整场景和技术重点，但不能切换到 Agent 平台、模型工程或任意软件岗位，也不改变冻结 Rubric 的评分口径。

产品闭环必须同时包含测评与学习：

```text
简历项目确认
  → 无提示测评
  → 自适应训练
  → Top 3 复盘与重答
  → 报告和薄弱点
  → 7～14 天延迟验证
  → 下一轮测评与训练
```

“下一场命中上一场薄弱点”仅证明路由生效，不作为能力提升证据。能力提升必须通过未见过的平行题或延迟同构题验证。

## 2. Alpha 范围

### 2.1 包含

- 本地单用户运行，固定 `local-user`。
- 简历文本粘贴。
- 文本型 PDF 上传与解析。
- 手动新增、编辑和确认项目。
- 固定的 Agent 应用工程师方向、1～3 年级别和中文面试语言。
- 可选目标公司类型和可选 JD 文本。
- 一种 8 道主问题、20～30 分钟的面试模式。
- 项目深挖 3 道、Agent 基础 3 道、工程故障排查 2 道。
- 每道主问题最多一次追问，全场追问上限 4 次。
- 测评、训练、复盘、即时平行题与延迟验证。
- 6 个固定且版本化的核心 `SKILL.md`。
- 回答持久化、中断恢复、证据化评估和幂等重试。
- Top 3 优势、Top 3 缺口、覆盖率、置信度和训练建议。
- 结构化知识点状态和下一场针对薄弱点的选题。
- 用户对评估提出异议，并触发保留审计记录的盲重评。
- 单一 DeepSeek Provider，通过适配接口为后续扩展预留边界。

### 2.2 暂缓

- 10/15/25 题多模式和深度面试。
- 任意岗位、Agent 平台、模型工程和全栈 Agent 岗位。
- DOCX、扫描 PDF OCR、图片简历和音频简历。
- 完整八维趋势、雷达图和未经校准的 0～100 总分。
- 技能包自动扫描、插件平台和技能包管理后台。
- 用户直接排除证据并立即重算画像。
- 完整语音字段、实时语音、STT 和 TTS。
- 多 Provider 完整兼容。
- 用户注册、登录和多租户权限。
- Redis、Celery、向量数据库、对象存储和微服务。
- 招聘投递管理、Boss 直聘同步等求职工作台功能。

### 2.3 非功能目标

- 评分可信度、题目相关性和学习闭环优先于极限响应速度。
- 用户提交回答后必须先持久化，再启动任何模型调用。
- 模型失败、页面刷新和进程崩溃不能造成回答丢失或重复观察。
- 所有诊断必须回溯到题目、冻结 Rubric、回答区间和验证状态。
- 标准面试中位完成时间不超过 30 分钟。

## 3. 技术方案

采用 Next.js 前端、FastAPI/LangGraph 后端和单一 SQLite 业务数据库组成的模块化单体。

| 层 | 技术 |
| --- | --- |
| 前端 | Next.js、React、TypeScript、Tailwind CSS |
| 后端 API | Python 3.12、FastAPI、Pydantic |
| 单回合编排 | LangGraph Graph API |
| 模型调用 | LangChain OpenAI-compatible Adapter |
| Alpha Provider | DeepSeek |
| 数据库 | SQLite、SQLAlchemy 2、Alembic |
| 简历解析 | PyMuPDF |
| 技能包 | 固定清单中的 YAML frontmatter + Markdown |
| 后端测试 | pytest |
| 前端测试 | Vitest、Playwright |
| 接口契约 | FastAPI OpenAPI 生成 TypeScript 类型 |
| 本地启动 | Docker Compose |

唯一持久化事实源：

```text
data/app.db
data/uploads/
```

Alpha 不使用独立 `checkpoints.db`。LangGraph 不承担跨请求持久化正确性，面试游标始终由 SQL 业务状态机重建。

## 4. 总体架构

```text
Next.js 前端
    │
    │ HTTP / SSE
    ▼
FastAPI 后端
    ├── resume        简历文本与项目确认
    ├── target        固定岗位范围和可选 JD
    ├── skills        固定技能包加载与版本校验
    ├── interview     SQL 状态机与单回合 LangGraph
    ├── assessment    盲评分、证据定位、事实核验
    ├── training      提示、讲解、重答和延迟验证
    ├── report        派生报告任务
    ├── profile       知识点状态和 Top 3 优势/缺口
    ├── jobs          持久化任务、租约和恢复扫描
    ├── llm           DeepSeek Adapter、Schema 和日志
    └── db            SQLAlchemy Repository 与事务
```

前端主流程：

```text
简历输入
  → 项目确认
  → 面试目标设置
  → 20～30 分钟面试
  → Top 3 复盘训练
  → 报告与知识点状态
  → 到期验证
```

业务模块不直接调用模型 SDK，统一经过 `llm`。LangGraph 节点不直接执行不可控的数据库副作用，所有写入通过支持幂等键和事务的 Repository。

## 5. 岗位上下文

```text
direction       agent_application_rag
level           one_to_three_years
language        zh_cn
company_type    startup / internet / ai_company / enterprise / unspecified
target_title    默认 Agent 应用工程师，可填写更具体名称
jd_text         可选，仅作为场景和覆盖调整信号
```

Rubric 的难度和评分等级由 `direction + level + rubric_version` 冻结。公司类型和 JD 只能影响问题场景、技术重点和候选题排序，不能在评分时动态提高或降低标准。

## 6. 简历与项目确认

Alpha 支持粘贴简历文本、上传文本型 PDF 和完全手动录入项目。PyMuPDF 提取 PDF 文本；文本为空或明显不足时明确提示“扫描件 OCR 暂不支持”，引导用户粘贴文本或手动录入。

项目草稿包括项目名称、背景与目标、技术栈、个人职责、核心方案、工程难点、故障与改进、可量化结果。LLM 抽取只作为草稿，用户确认后的事实才可进入问题上下文。每个确认版本保存文本哈希和版本号，问题记录所引用的项目版本。

## 7. 测评、训练和复盘分离

### 7.1 总体结构

| 类别 | 数量 |
| --- | ---: |
| 项目深挖 | 3 |
| Agent 基础 | 3 |
| 工程故障排查 | 2 |

每题最多一次追问，全场最多四次追问。前端显示预计剩余时间。

### 7.2 测评段

前 3 道为跨场可比较的锚题或平行锚题，分别覆盖项目、Agent 基础和故障排查，占 37.5%。

- 只评价无提示首答。
- 不提供提示、纠错或追问。
- 生成时冻结 Rubric、知识点和参考事实版本。
- 只有锚题用于跨场可比趋势。
- 后续场次使用同一锚题族中未见过的平行题。

### 7.3 自适应训练段

后 5 道根据项目、未覆盖知识点、历史薄弱点和用户重点选择。

- 主问题首答仍是无提示回答，可形成独立诊断证据。
- 允许一次追问、分层提示或纠错。
- 追问、提示后回答和纠错后回答标记为 `assisted`。
- `assisted` 回答只用于教学诊断，不覆盖首答成绩，也不作为新的独立掌握证据。
- 追问决策与评分解耦。

### 7.4 复盘段

主问题结束后选择 Top 3 薄弱点：展示首答证据与缺口、给出答案结构、提供技术讲解，并让用户重答原场景或完成未见即时平行题。复盘回答标记为 `practice`，记录即时迁移但不覆盖首答。

### 7.5 延迟验证

完成复盘的知识点生成 7～14 天后的验证计划。验证使用未见过的同构题，并记录训练前首答等级、即时平行题等级、延迟同构题等级、即时迁移增量、延迟迁移增量和保持率。

## 8. 提前结束和部分报告

- 完成至少 6 道主问题后允许提前结束。
- 未答问题记录为 `skipped`，分数为空。
- 部分报告显示覆盖不足和低置信度。
- 少于 3 道锚题时不生成跨场锚题比较。
- 有效无提示首答仍可形成观察，但报告不得给出整体能力结论。

## 9. 固定技能包

Alpha 使用固定 manifest 加载 6 个技能包，不做通用扫描或插件发现：

```text
skills/
├── project-deep-dive/SKILL.md
├── agent-fundamentals/SKILL.md
├── rag/SKILL.md
├── agent-runtime/SKILL.md
├── engineering-reliability/SKILL.md
└── software-foundations/SKILL.md
```

`agent-runtime` 合并工具调用、记忆、上下文和基础编排；`software-foundations` 覆盖 Python、HTTP、数据库、并发和必要的 React/TypeScript 基础。

frontmatter 至少包含：

```yaml
name: rag
version: 1
target_direction: agent_application_rag
target_level: one_to_three_years
knowledge_points:
  - rag.query_rewrite
  - rag.hybrid_retrieval
  - rag.reranking
rubric_version: rag-rubric-v1
parallel_item_families:
  - rag-recall-debugging-v1
```

正文统一包含考察目标和边界、难度阶梯、项目钩子、锚题和平行题约束、场景模板、参考事实、期望信号与反例、冻结 Rubric 模板。

## 10. 问题规划

1. `InterviewPlanner` 生成 8 个类别槽位、3 个锚题槽位、覆盖约束和追问预算。
2. `QuestionGenerator` 生成正式题、少量候补题、项目事实引用和冻结 Rubric 快照。

验证器检查覆盖、项目事实、知识点 ID、可答性、严重歧义、重复和 Rubric 一致性。

自适应选题不使用固定 50/30/20，而使用可配置优先级评分和硬约束。输入包括薄弱严重度、到期验证、置信度缺口、用户重点、最近考察、连续失误、新知识点价值和过度集中惩罚。硬约束保证 3/3/2 配额、3 道锚题和追问上限。

## 11. 评分可信度架构

评分、证据验证、技术事实核验和追问决策逻辑解耦。

### 11.1 盲评分器

评分器只能看到当前问题、用户首答、冻结 Rubric 和允许使用的技能包参考事实。不能看到历史画像、既有薄弱点、过去分数、下一场优先级或“用户应该强/弱”的标签。

### 11.2 引用来源完整性

每条证据保存 `answer_id`、`start_offset`、`end_offset`、`quoted_text` 和 `answer_text_hash`。程序按字符区间切片并核对文本与 SHA-256 哈希。无法定位的证据不删除，保留为 `invalid` 并记录原因。

### 11.3 证据—结论相关性

独立验证器判断区间是否支持诊断，不把关键词出现等同于理解，输出 `supported / unsupported / ambiguous` 和理由。

### 11.4 技术事实正确性

技术核验器使用冻结 Rubric 和技能包参考事实，检查关键事实、严重错误、关键词堆砌、必需项遗漏，以及条件、边界和权衡是否自洽。

### 11.5 确定性计分

模型只给每个 Rubric 项输出 `0～4` 等级、证据和置信度，最终聚合由程序完成。

| 等级 | 含义 |
| ---: | --- |
| 0 | 明确作答但核心内容完全错误或无有效内容 |
| 1 | 知道名词，但不能正确解释 |
| 2 | 基本理解，缺少机制、边界或工程细节 |
| 3 | 技术正确，并能结合场景分析 |
| 4 | 深入，能解释权衡、故障模式和可执行方案 |

Alpha 不突出 0～100 总分，优先展示等级、有效证据数、覆盖率、置信度和严重错误标记。

### 11.6 追问器

追问器只读取本题缺口、允许追问知识点和预算，不计算分数、不修改评估、不读取历史画像。

## 12. 回答和评估状态

回答结果：

```text
submitted             有实质回答
explicit_unknown      明确“不知道”，是有效首答，可评分
skipped               用户跳过，分数为空
invalid_question      题目无效，分数为空并进入审计
system_error          系统未完成评估，保持 pending
```

评估状态：`pending / valid / invalid / rejected / disputed / confirmed / overturned`。

无回答与错误回答不共用 `0`。只有 `submitted` 或 `explicit_unknown` 的有效评估可以得到等级。

## 13. 证据独立性

- 一道主问题的首答是一个独立评估单元。
- 同题追问、提示和复盘共享 `evidence_group_id`，不增加独立计数。
- 同一回答映射多个 Rubric 项时，对相应知识点只贡献一次本题独立证据。
- 不同主问题、未见平行题和不同场次可构成独立证据。
- 高置信度要求至少三条独立证据并跨至少两道主问题；长期稳定结论优先要求跨场证据。

## 14. 知识点状态与薄弱点

Alpha 不实现完整八维趋势，只保留知识点状态、Top 3 优势和 Top 3 缺口。

```text
knowledge_point_id
mastery_level       unseen / weak / developing / proficient
status              tentative / active / improving / resolved / disputed
confidence
independent_evidence_count
consecutive_misses
first_seen_at
last_assessed_at
next_review_at
priority
```

第一条有效独立证据后进入 `tentative`；至少三条独立证据且满足独立性后才允许高置信度 `active`。辅助回答不直接标记掌握；未见平行题改善后进入 `improving`；延迟验证稳定通过后才进入 `resolved`；跳过和无效题不增加失误。

## 15. 用户异议与盲重评

用户不能直接删除负面证据。异议流程：

```text
提交异议和理由 → 原观察 disputed → 创建 ReevaluationJob
  → 盲重评题目、回答、Rubric 和技能包事实
  → confirmed / overturned / unresolved → 重新聚合
```

原观察、模型版本、异议、重评和最终处理全部保留审计。

## 16. 报告设计

报告是独立派生任务，不阻塞 Session 完成。报告显示完成度、覆盖率、锚题覆盖、Top 3 优势与缺口、严重技术错误、“项目理解、个人贡献陈述与技术一致性”、首答等级、辅助训练表现、答案结构、讲解、延迟验证计划、置信度和独立证据数。

报告不展示未经校准的综合 0～100 总分，不用训练重答覆盖首答。

## 17. SQL 状态机是唯一事实源

Alpha 不依赖 LangGraph interrupt/checkpoint 保存等待状态。每次 HTTP 请求或后台 Job 都从 `app.db` 重建本回合输入，运行短生命周期 Graph，再通过事务写回。

```text
SQL 状态 → 构造本回合 GraphState → LangGraph 计算与路由
  → Repository 幂等事务提交 → SQL 成为下一回合游标
```

LangGraph interrupt 恢复会从节点开头重新执行，前置副作用必须幂等；持久化线程还受节点名、State 字段和流程版本变化影响。参考：

- <https://docs.langchain.com/oss/python/langgraph/interrupts>
- <https://docs.langchain.com/oss/python/langgraph/backward-compatibility>

LangGraph 只组织单回合解析、规划、评分核验和路由，不作为第二个业务数据库。

## 18. 持久化任务与一致性

### 18.1 核心表

```text
User / Resume / ResumeProject / InterviewTarget / InterviewSession
InterviewQuestion / RubricSnapshot / AnswerAttempt
AssessmentOperation / AssessmentObservation / EvidenceSpan
TrainingAttempt / VerificationSchedule / CandidateKnowledgeState
ObservationDispute / InterviewReport / OperationJob
```

### 18.2 OperationJob

所有模型调用和派生任务保存 `kind`、`session_id`、`idempotency_key`、`payload_hash`、状态、重试次数、租约、下次重试、结果引用和错误。启动时扫描 pending、到期 retryable 和租约过期 running。

### 18.3 回答提交事务

前端生成稳定 `client_submission_id`。后端在同一事务中校验 `session_version`、插入 Answer、创建唯一 Job、将 Session 标为等待评估并递增版本。

```text
unique(session_id, client_submission_id)
unique(operation_kind, idempotency_key)
unique(question_id, primary_attempt_kind)
```

同一幂等键和相同 `payload_hash` 返回已有结果；同键不同内容返回 HTTP `409 Conflict`。

### 18.4 Job 完成事务

Worker 获取带过期时间的租约，模型调用后在一个事务中写评估、更新 Job、推进 Session 并递增版本。重复执行只能读取或 upsert 同一结果。报告单独创建；Session 可为 `completed` 而 Report 为 `pending/failed`。

### 18.5 工作流版本

Session 保存 `workflow_version`、技能包和 Rubric 版本。兼容升级使用迁移器；不兼容升级保留旧单回合 Graph 入口直到旧 Session 完成或终止，不依赖旧 checkpoint 节点名。

## 19. LangGraph 单回合图

```text
创建：加载项目 → 覆盖蓝图 → 生成题目 → 验证 → 持久化计划

评估：加载题目和首答 → 盲评分 → 定位证据 → 相关性验证
  → 技术事实核验 → 确定性聚合 → 追问决策 → 幂等提交

完成：补齐评估 → 聚合知识点 → 选择 Top 3 → 创建训练计划
  → 调度报告 → Session completed
```

Graph 失败由 `OperationJob` 重试，不恢复旧 Python 调用栈。

## 20. Provider 边界

Alpha 只验收 DeepSeek，保留 `LLMProvider.generate_structured`、`generate_text` 和 `health_check` 窄接口。记录模型、耗时、Prompt 版本、token 和错误。Alpha 不承诺其他 Provider 的结构化输出质量。

## 21. 安全边界

- 简历、JD、回答和历史报告是不可信数据，不执行其中指令。
- 固定技能包受信任，但校验 Schema、版本和长度。
- PDF 验证扩展名、MIME、文件头和大小，随机命名保存。
- API Key 从 `.env` 读取，不写数据库、不返回前端。
- 盲评分器输入由代码白名单构造，禁止注入历史画像。
- 原始回答、Rubric 快照和审计记录不可被模型覆盖。

## 22. 错误处理

- PDF 无文本：提示 OCR 不支持，转文本或手动录入。
- 项目结构化失败：简化 Schema 重试一次，仍失败则手动录入。
- 题目不足或验证失败：用固定人工模板补足或阻止开始。
- 评估超时：答案已保存，Job retryable，不要求重答。
- 证据区间无效：保留并标记 invalid。
- 证据不支持诊断：标记 rejected，不进入画像。
- 技术核验冲突：降低置信度并进入评测集，不给高等级。
- 报告失败：Session completed，报告独立重试。
- 进程崩溃：启动扫描回收租约并继续任务。
- 版本不兼容：使用旧入口或显式终止，不静默套用新流程。

## 23. 测试与质量评测

### 23.1 单元测试

覆盖技能包版本、项目事实引用、回答/评估枚举、字符区间与哈希、证据独立性、Rubric 聚合、优先级与 3/3/2 约束、知识点迁移、异议重评、幂等冲突、乐观锁和租约。

### 23.2 Graph 测试

用 Mock LLM 覆盖 8 题创建、锚题无提示、追问预算、跳过/不知道/无效题、评分与追问解耦、Job 重试和版本路由。

### 23.3 崩溃与并发测试

在回答写入、Job 创建、模型返回、观察写入和 Session 推进边界主动终止进程。并发提交相同或冲突 `client_submission_id`，验证幂等和 409。

### 23.4 质量评测集

编码前建立版本化评测集，包含标准简历、问题、冻结 Rubric、专家评分和不同质量回答，覆盖项目深挖、Agent 基础、RAG、Runtime、工程可靠性、通用基础，以及关键词堆砌、事实错误和遗漏必需项等对抗样本。

## 24. Alpha 验收门槛

| 指标 | 门槛 |
| --- | ---: |
| 证据引用字符区间可定位率 | 100% |
| 人工抽检的证据—诊断支持准确率 | ≥95% |
| LLM 与专家评分相差不超过一个等级 | ≥85% |
| 技术错误答案被评为高等级 | ≤2% |
| 重复提交、刷新、崩溃后的答案丢失 | 0 |
| 重复观察和重复画像更新 | 0 |
| 问题相关、可答且无严重歧义 | ≥95% |
| 面试中位完成时间 | ≤30 分钟 |

Alpha 必须记录训练前首答、即时未见平行题和 7～14 天延迟同构题，并计算即时迁移、延迟迁移和保持率。

编码前没有真实配对样本，因此不编造学习提升百分比门槛。Alpha 不得宣称“提升能力”，直到积累足够配对样本并经专家确认；功能验收要求学习指标链路端到端可追踪且计算正确。

## 25. Alpha 验收场景

- 粘贴简历或上传文本型 PDF，确认项目事实。
- 固定岗位生成 3/3/2 共 8 道题。
- 三道锚题无提示，训练段追问每题最多一次、全场四次。
- 刷新或关闭后从 SQL 状态继续。
- 重复提交返回同一结果，冲突提交返回 409。
- 每条有效诊断定位到字符区间和冻结 Rubric。
- 跳过、不知道、无效题和系统错误分别处理。
- 报告展示等级、证据、覆盖和置信度，不展示未校准总分。
- 用户异议产生盲重评和完整审计。
- Top 3 缺口进入复盘并生成延迟验证。
- 第二场考虑薄弱点，但能力提升只由平行题和延迟题衡量。

## 26. 后续演进

岗位扩展必须在 Alpha 评分完成专家校准后进行，每个方向和级别有独立技能包与 Rubric。语音方案单独设计，不提前铺设空字段。多用户 Web 再引入认证、PostgreSQL、对象存储、可靠任务队列和服务端密钥管理。

后续演进不得破坏问题、Rubric 快照、回答、证据审计、训练尝试和知识点状态的核心领域接口。
