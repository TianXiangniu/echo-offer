# Echo Offer 本地面试历史与用户画像数据库设计

日期：2026-09-01  
状态：已确认  
范围：本地单用户版本

## 1. 目标

Echo Offer 需要长期保存每一次面试的数据，包括简历版本、面试题、用户回答、AI 评分、面试报告和用户能力变化。一次新面试必须新增一组记录，不能覆盖旧面试。

本阶段继续使用本地 SQLite，不实现注册登录和多用户权限。数据库需要支持：

- 保存多次面试及完整回放；
- 全部回答完成后统一进行一次批量 AI 评分；
- 保存 AI 任务进度，支持 SSE、失败诊断和重试；
- 根据有效评分持续更新用户画像；
- 按求职方向展示能力差距和学习建议；
- 保留历史评分、报告和画像版本，避免重新生成覆盖旧结果。

## 2. 存储边界

- SQLite 数据库位于 `data/app.db`。
- PDF、DOCX 原文件位于 `data/uploads/`，数据库只保存文件路径、哈希、解析文本和解析状态。
- 数据库备份位于 `data/backups/`。
- API Key 只通过环境变量提供，不写入数据库。
- 前端只能通过 FastAPI 访问数据，不直接操作 SQLite。
- 本地用户固定为 `local-user`，保留 `user_id` 字段以便未来扩展。

SQLite 开启外键约束、WAL 和合理的 busy timeout。数据库结构升级使用 Alembic，替代运行时手工 `ALTER TABLE`。

## 3. 数据设计原则

### 3.1 历史记录只新增

以下数据采用追加式保存：

- 面试会话；
- 用户回答；
- AI 任务尝试；
- 评分批次；
- 报告版本；
- 用户画像快照。

重新评分或重新生成报告时创建新版本。只有新版本完全成功后，才更新面试记录上的“当前有效评分”和“当前有效报告”指针。

### 3.2 评分与用户画像分离

当前面试的评分器只能读取当前题目、当前回答、当时使用的评分标准和允许参考的技术事实。评分器不能读取历史画像、历史分数和既有薄弱项。

评分成功后，由独立的画像更新流程读取有效评分，更新长期能力状态。这样可以避免历史印象影响当前评分。

### 3.3 结构化结果优先

AI 返回内容必须先经过格式、字段、等级范围和原回答引用位置检查。有效结果写入结构化表，模型原始响应保存在任务记录中用于排错，但不能直接作为当前报告。

### 3.4 可重试但不重复执行

每项模型任务具有操作类型、输入哈希和幂等键。相同任务重复点击时不能同时执行两次。失败后创建新的尝试记录，保留原始回答和既有成功结果。

## 4. 核心关系

```text
User
├── Resume -> ResumeSource / ResumeProject
├── CandidateProfile (按求职方向)
└── InterviewSession
    ├── InterviewQuestion -> AnswerAttempt
    ├── OperationJob -> OperationJobEvent
    ├── AssessmentRun -> RubricObservation -> EvidenceSpan
    ├── InterviewReport
    └── ProfileSnapshot / CandidateKnowledgeState 更新来源
```

## 5. 现有表的调整

### 5.1 `interview_sessions`

一行代表一场独立面试。保留现有字段，并增加：

- `profile_id`：本场面试对应的求职方向画像；
- `current_assessment_run_id`：当前有效评分批次；
- `current_report_id`：当前有效报告；
- `updated_at`：最近更新时间；
- `archived_at`：归档时间，归档不删除记录。

状态：

- `in_progress`：正在回答；
- `answers_completed`：回答已完成，等待分析；
- `analyzing`：正在分析；
- `report_ready`：报告可查看；
- `analysis_failed`：分析失败，可重试；
- `archived`：用户已归档。

### 5.2 `interview_questions`

题目生成后保存题目原文、顺序、类型、知识点以及当时使用的评分标准副本。增加可选的 `project_id`，用于定位项目题对应的简历项目。

约束：`unique(session_id, position)`。

### 5.3 `answer_attempts`

每道题提交后立即保存，不等待模型分析。继续区分：

- `submitted`；
- `explicit_unknown`；
- `skipped`；
- `invalid_question`；
- `system_error`。

保留 `client_submission_id`、回答哈希和提交时间。约束包括：

- `unique(session_id, client_submission_id)`；
- `unique(question_id, primary_attempt_kind)`。

### 5.4 `assessment_runs` 与 `rubric_observations`

一场面试可以有多次评分尝试。每个评分批次保存模型、评分规则版本、状态、置信度和错误信息。每道题的每个评分项保存在 `rubric_observations`，等级范围为 0～4。

## 6. 新增任务与进度表

### 6.1 `operation_jobs`

统一记录所有需要调用模型或异步处理的任务。

主要字段：

- `id`、`user_id`、`session_id`；
- `operation_kind`；
- `idempotency_key`、`request_hash`；
- `status`、`progress`、`current_stage`；
- `provider`、`model_name`、`prompt_version`；
- `attempt_number`；
- `raw_response_json`；
- `error_code`、`error_message`；
- `lease_owner`、`lease_expires_at`；
- `created_at`、`started_at`、`finished_at`。

操作类型至少包括：

- `project_analysis`；
- `question_generation`；
- `batch_assessment`；
- `profile_summary`。

状态为 `pending / running / succeeded / failed / cancelled`。

约束：`unique(operation_kind, idempotency_key)`。

### 6.2 `operation_job_events`

保存 SSE 可恢复的进度事件：

- `job_id`；
- `sequence`；
- `event_type`；
- `progress`；
- `message`；
- `created_at`。

约束：`unique(job_id, sequence)`。

刷新页面后，前端先读取已有事件，再继续订阅新事件。服务重启后，过期的运行中任务可根据租约恢复。

## 7. 新增评分引用与报告表

### 7.1 `evidence_spans`

保存评分所引用的原回答片段：

- `observation_id`、`answer_id`；
- `start_offset`、`end_offset`；
- `quoted_text`、`answer_text_hash`；
- `validity`、`invalid_reason`。

程序按字符区间和回答哈希检查引用。无效引用保留并标记原因，不能作为有效评分依据。

### 7.2 `interview_reports`

一场面试可以有多个报告版本：

- `session_id`、`assessment_run_id`；
- `version`、`status`；
- `summary`；
- `strengths_json`；
- `weaknesses_json`；
- `next_steps_json`；
- `question_results_json`；
- `created_at`。

约束：`unique(session_id, version)`。只有成功报告才可成为 `current_report_id`。

## 8. 技能目录与求职方向

### 8.1 `skill_catalog`

统一技能名称，避免同义词被识别为不同技能：

- `id`；
- `canonical_name`；
- `category`；
- `aliases_json`；
- `description`；
- `is_active`。

### 8.2 `question_skills`

支持一道题关联一个或多个技能：

- `question_id`；
- `skill_id`；
- `weight`。

约束：`unique(question_id, skill_id)`。

### 8.3 `role_skill_requirements`

定义不同求职方向对技能的要求：

- `direction`、`level`；
- `skill_id`；
- `target_level`；
- `importance_weight`。

例如 Agent 应用工程师实习可包含 Python、Agent 工作流、RAG、模型调用与异常处理、数据库基础和系统设计。

## 9. 用户画像与学习建议

### 9.1 `candidate_profiles`

画像按求职方向划分：

- `id`、`user_id`；
- `direction`、`level`、`target_title`；
- `current_snapshot_id`；
- `summary`；
- `created_at`、`updated_at`。

约束：`unique(user_id, direction, level, target_title)`。

### 9.2 `candidate_knowledge_states`

保存每项技能的长期状态：

- `user_id`、`skill_id`；
- `current_level`、`confidence`；
- `valid_sample_count`；
- `trend`；
- `serious_error_count`；
- `first_assessed_at`、`last_assessed_at`；
- `last_session_id`。

通用技能状态可以被多个求职方向引用；岗位画像通过 `role_skill_requirements` 决定展示哪些技能以及目标等级。

### 9.3 `profile_snapshots`

每次有效面试更新画像后创建快照：

- `profile_id`、`source_session_id`；
- `version`；
- `profile_json`；
- `created_at`。

快照用于查看历史画像变化，不覆盖旧版本。

### 9.4 `learning_recommendations`

保存结构化学习建议：

- `profile_id`、`profile_snapshot_id`、`skill_id`；
- `priority`；
- `reason`；
- `actions_json`；
- `success_criteria_json`；
- `recommended_review_at`；
- `status`；
- `created_at`、`updated_at`。

状态为 `recommended / in_progress / completed / dismissed`。

## 10. 用户画像计算

画像数值由程序确定性聚合，AI 不直接修改技能等级。

每场有效评分完成后：

1. 按 `question_skills` 将评分映射到技能；
2. 排除无效评分和无效引用；
3. 结合题目权重、评分置信度和近期程度计算技能等级；
4. 最近五次有效面试权重更高；
5. 样本不足时标记为“数据较少”；
6. 比较近期与此前结果，计算 `improving / stable / declining`；
7. 保存能力状态和画像快照；
8. 根据岗位目标与当前等级的差距生成学习建议。

学习建议优先级由岗位重要程度、能力差距、结果置信度和明显错误共同决定。AI 只负责把结构化建议转成自然语言；为了控制费用，该总结默认复用整场批量评分的输出，跨多场 AI 总结仅在用户主动请求时调用。

## 11. 完整业务流程

1. 上传并解析简历，保存简历版本和项目。
2. 选择求职方向，创建或复用对应画像。
3. 开始面试，创建新的 `interview_session`。
4. 生成并保存题目及评分标准副本。
5. 用户逐题回答，每题立即写入数据库。
6. 全部回答后，将会话标记为 `answers_completed`。
7. 创建唯一的 `batch_assessment` 任务。
8. SSE 从任务事件表发送处理进度。
9. 模型一次返回本场每题评分和报告内容。
10. 后端验证格式、等级和原回答引用。
11. 在同一事务内写入评分、引用片段和报告。
12. 更新当前有效评分、当前报告和用户画像。
13. 创建画像快照和学习建议。
14. 将会话标记为 `report_ready`。

如果步骤 9～13 失败，任务标记为失败，会话进入 `analysis_failed`。原始题目和回答保持不变，用户可以重新分析。

## 12. 历史页面与画像页面

历史面试页面展示：

- 面试时间、方向、简历版本和状态；
- 本场题目、原始回答、评分和报告；
- 失败任务的重新分析入口；
- 归档入口。

用户画像页面展示：

- 当前求职方向；
- 各技能当前等级、置信度和样本数量；
- 最近多次面试的变化趋势；
- 与岗位目标之间的差距；
- 按优先级排列的学习建议；
- 建议的完成和忽略状态。

历史趋势直接读取结构化能力数据，不重复调用模型。只有用户主动请求跨多场自然语言总结时才创建新的 AI 任务。

## 13. 索引、备份与迁移

至少增加以下索引：

- 面试：`(user_id, created_at)`、`(status, updated_at)`；
- 题目：`(session_id, position)`；
- 回答：`(session_id, question_id)`；
- 任务：`(status, created_at)`、`(session_id, operation_kind)`；
- 报告：`(session_id, version)`；
- 能力状态：`(user_id, skill_id)`；
- 建议：`(profile_id, status, priority)`。

迁移前创建带时间戳的数据库备份。所有表结构变化通过 Alembic 完成，禁止删除或覆盖已有面试数据。

## 14. 实施顺序

1. 创建 Alembic 基线，并为现有数据库增加备份流程；
2. 增加 `operation_jobs` 和 `operation_job_events`；
3. 增加 `evidence_spans` 和 `interview_reports`；
4. 完善面试表的当前版本指针和归档字段；
5. 增加技能目录、题目技能映射和岗位技能要求；
6. 增加用户画像、能力状态、画像快照和学习建议；
7. 接入批量评分完成后的画像更新事务；
8. 开发历史面试、用户画像和学习建议接口及页面；
9. 补充迁移、重复提交、失败重试、历史保留和画像更新测试。

本设计只针对本地单用户版本，不包含登录、多用户权限和云端部署。
