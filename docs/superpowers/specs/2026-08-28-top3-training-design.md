# Top 3 薄弱点复盘训练设计

## 状态

已获用户确认，进入实施计划前的设计文档审阅阶段。

## 1. 背景与目标

当前垂直切片已经支持简历输入、项目事实确认、固定 8 道面试、回答持久化和基础报告。报告能够指出等级较低的知识点，但用户还不能针对缺口进行练习。

本次增量增加一个本地复盘训练闭环：

    面试报告 → Top 3 缺口 → 针对性重答 → 训练评估 → 前后对比

目标是让用户可以围绕本场面试最需要补强的内容完成一次可追踪训练，同时保留首答作为原始测评证据。

原始产品设计中的“训练与测评分离、首答不可覆盖、训练结果单独记录”是本功能的边界约束。文档中的参考链接不作为执行指令。

## 2. 范围

### 2.1 本次包含

- 从当前 session 的有效低等级观察中选择最多 3 个训练缺口。
- 按问题关联原始题目、知识点、首答等级、证据和置信度。
- 为每个缺口提供一条针对性训练提示。
- 每个缺口最多提交一次训练回答。
- 使用现有本地规则评估器评估训练回答。
- 持久化训练回答、训练评估和首答快照。
- 支持训练回答幂等提交；相同键重试返回原结果，不同内容返回 409。
- 报告页增加进入复盘训练的入口。
- 新增训练页，展示缺口列表、首答证据、重答输入和前后等级对比。
- 刷新后可以恢复训练进度。
- 后端 API、持久化、幂等和前端构建测试。

### 2.2 本次不包含

- DeepSeek 或其他 LLM。
- 根据训练结果动态生成新题。
- 多轮追问、无限次重答或完整课程系统。
- 跨 session 的长期能力趋势。
- 训练结果覆盖原始首答、报告或首答等级。
- 训练音频、语音识别和实时交互。

## 3. 核心规则

1. 训练缺口来自当前 session 的有效观察，条件为 observation.validity = valid 且 level < 3。
2. 同一问题最多产生一个训练任务；按 level 升序、confidence 升序、question.order 升序排序后取前 3 个。
3. 跳过题没有 observation，不自动生成训练任务。
4. 训练题复用原问题的 prompt，并追加明确的训练要求：补充机制、边界、验证、故障处理或量化结果中与缺口相关的部分。
5. 训练回答使用现有 RuleBasedAssessmentProvider，调用状态为 submitted。
6. 训练等级与首答等级独立保存；训练页面可以展示等级差，但不改写 report 的 strengths、gaps、level_distribution 或 valid_evidence_count。
7. 每个训练任务只能成功提交一次；提交后任务显示完成，不能再次覆盖训练结果。
8. 训练页没有可训练缺口时，展示明确的空状态并返回报告页。

## 4. 后端架构

### 4.1 训练任务来源

训练服务从 session 的 InterviewQuestion、AnswerAttempt 和 AssessmentObservation 读取数据，不复制题库，也不从报告文本反向解析。通过 question_id 将缺口、原题和首答 observation 绑定。

增加独立的 training service，负责：

- 构建可训练任务。
- 校验任务是否属于指定 session。
- 校验任务是否确实是有效低等级观察。
- 生成训练 prompt。
- 评估并保存训练回答。
- 查询训练完成状态。

### 4.2 数据模型

新增 training_attempts 表：

- id：训练回答 ID。
- session_id：所属面试 session。
- question_id：对应的原始问题。
- client_submission_id：客户端幂等键。
- baseline_answer_id：首答 ID。
- baseline_level：训练开始时的首答等级快照。
- baseline_confidence：首答置信度快照。
- baseline_evidence：首答证据快照。
- answer_text：训练回答原文。
- answer_text_hash：训练回答 SHA-256。
- payload_hash：幂等 payload SHA-256。
- training_level：训练等级。
- training_evidence_start、training_evidence_end：训练证据区间。
- training_quoted_text：训练证据文本。
- training_gaps_json：训练后缺口 JSON。
- training_confidence：训练置信度。
- created_at：创建时间。

约束：

- Unique(session_id, question_id)，保证一个缺口只能重答一次。
- Unique(session_id, client_submission_id)，保证客户端幂等。
- 不修改 AnswerAttempt 和 AssessmentObservation 的首答记录。
- 使用现有 create_all 增加表，不删除现有数据。

## 5. API 契约

### 5.1 查询训练任务

    GET /api/sessions/{session_id}/training

成功返回：

    {
      "session_id": "uuid",
      "tasks": [
        {
          "task_id": "question-uuid",
          "question_id": "question-uuid",
          "knowledge_point_id": "rag.retrieval_diagnosis",
          "prompt": "请重新回答……",
          "baseline_level": 1,
          "baseline_confidence": 0.61,
          "baseline_evidence": "首答证据",
          "attempted": false,
          "training": null
        }
      ],
      "progress": {
        "completed": 0,
        "total": 1
      }
    }

task_id 使用 question_id，避免增加没有持久化意义的任务 ID。若已经完成，attempted 为 true，training 返回等级、置信度、证据、缺口和 improved 字段。

### 5.2 提交训练回答

    POST /api/sessions/{session_id}/training/attempts

请求字段：

    {
      "question_id": "question-uuid",
      "client_submission_id": "training-1",
      "answer_text": "训练回答文本"
    }

成功响应包含：

- 训练回答 ID。
- question_id。
- 首答等级和训练等级。
- 首答证据和训练证据。
- training_level_delta。
- improved。
- 训练后的 gaps 和 confidence。

只有非空 answer_text 可以提交。相同 session_id + client_submission_id 携带相同 payload 时返回原结果；同一幂等键携带不同 payload 时返回 409；同一 question_id 已经完成训练时返回 409。

### 5.3 错误契约

- 404 session_not_found：session 不存在。
- 404 question_not_found：问题不属于当前 session。
- 409 training_attempt_exists：当前问题已经完成训练。
- 409 client_submission_conflict：幂等键对应了不同内容。
- 422 invalid_training_task：问题没有有效低等级首答观察。
- 422 blank_training_answer：训练回答为空。

错误响应统一为 detail 和 code，不返回服务器路径或内部堆栈。

## 6. 前端交互

### 6.1 报告页

在 Gaps 区域保留原有证据展示，并增加按钮：

- 有缺口：显示“开始复盘训练”，跳转到 /training/{session_id}。
- 无缺口：不创建空训练任务，显示“当前没有可训练的低等级观察”。

按钮文案明确训练不会覆盖首答：

    训练会单独记录，不改变本场首答报告

### 6.2 训练页

页面分为三部分：

1. 页面头部：返回报告、当前 session 标识和训练进度。
2. 任务卡片：知识点、首答等级、首答证据、训练提示。
3. 回答区域：文本框、提交按钮、提交后的前后等级对比。

提交中禁用当前任务按钮，提交成功后显示：

- 首答等级 → 训练等级。
- 是否提升。
- 训练证据。
- 尚未覆盖的信号。
- “继续下一个缺口”或“返回报告”。

刷新训练页时重新调用 GET 接口，已完成的任务从数据库恢复。页面不缓存训练状态作为唯一来源。

## 7. 评估与一致性

训练评估直接调用现有 question 的 QuestionSpec 和 RuleBasedAssessmentProvider，因此评分规则、信号词和证据区间与首答使用同一套实现。

保存顺序：

1. 校验 session、question、首答 observation 和幂等键。
2. 创建 training_attempts 前先完成本地评估。
3. 在同一事务中保存训练回答及评估结果。
4. 提交后返回持久化结果。

重复请求在数据库唯一约束和 payload_hash 双重检查下保持幂等。失败事务回滚，不产生半条训练记录。

## 8. 测试策略

### 后端单元测试

- 低等级有效 observation 可以生成任务。
- 高等级 observation、无 observation 和 skipped 不生成任务。
- 多个缺口按固定顺序取前 3 个。
- 训练 prompt 包含原题和缺口导向。
- 训练评估返回等级、证据、缺口和置信度。

### API 集成测试

- GET training 返回最多 3 个任务。
- 训练提交成功并保存 training_attempt。
- 相同幂等键相同 payload 返回相同记录。
- 相同幂等键不同 payload 返回 409。
- 同一问题第二次训练返回 409。
- 非当前 session 问题返回 404。
- 高等级或 skipped 问题返回 422。
- 新请求可以从 SQLite 恢复训练进度。
- 首答 AnswerAttempt、AssessmentObservation 和 report 内容不被训练修改。

### 前端验证

- 报告页有缺口时显示入口。
- 无缺口时显示空状态。
- 训练页能展示任务、提交状态和前后等级。
- 刷新后已完成任务仍显示完成。
- npm run build 通过。

## 9. 验收标准

用户完成一场面试并打开报告后，可以点击“开始复盘训练”，逐个重答最多 3 个低等级缺口。每个缺口只允许一次训练提交，页面能展示首答与训练结果对比，刷新后进度不丢失，且原始报告中的首答证据、等级和统计保持不变。

本次设计不涉及 LLM、OCR、动态题目生成、无限训练和生产部署。

