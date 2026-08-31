# AI 面试评分可信度第一阶段设计

日期：2026-08-31

## 1. 目标

在现有 Agent 应用工程师模拟面试垂直切片上，将当前的本地规则评估升级为基于 SiliconFlow 的 AI 盲评分，同时保留回答持久化、幂等提交和报告聚合能力。

第一阶段只实现以下闭环：

~~~text
当前问题 + 冻结 Rubric + 用户首答
        ↓
SiliconFlow 盲评分
        ↓
结构化结果校验
        ↓
证据区间与 SHA-256 完整性验证
        ↓
程序确定性聚合
        ↓
面试题评分与报告
~~~

模型只负责对 Rubric 项进行观察，程序负责证据校验、状态管理和最终等级聚合。

## 2. 范围

### 2.1 本次包含

- SiliconFlow AI 盲评分 Provider。
- 每道题冻结版本化 Rubric。
- 模型对每个 Rubric 项输出 0～4 等级、证据区间、引用文本和置信度。
- 程序校验模型 JSON、Rubric 完整性、证据区间和回答哈希。
- 一条回答对应一个评估运行记录和多个 Rubric 观察记录。
- 程序按固定公式聚合本题等级和置信度。
- pending、valid、invalid、rejected 评估状态。
- 模型超时、连接失败和服务异常时保留回答，并记录 system_error。
- 相同提交 ID 的安全重试；不同 payload 继续返回 409。
- 面试页显示 AI 评分处理中和失败状态。
- 报告聚合有效 AI 评估，不显示未经校准的 0～100 总分。
- Mock Provider、模型响应校验和 API 状态测试。

### 2.2 本次不包含

- 证据—结论语义相关性独立验证。
- 技术事实正确性独立核验器。
- 追问器和追问预算。
- 历史画像、跨场次能力判断和下一场优先级。
- AI 评分 SSE、后台任务队列和 Worker。
- 用户异议、人工复核、确认或推翻流程。
- 将模型自行声称的严重错误直接当作已验证事实。

## 3. 可信度原则

### 3.1 盲评分

Provider 只接收当前问题、当前题目的冻结 Rubric、允许使用的技能包参考事实和用户当前首答。Provider 不访问数据库，不接收简历原文、项目事实、历史回答、过去分数、能力画像或下一场优先级。

现有 AssessmentProvider 接口保留为评分边界；路由只负责传递当前题目和当前回答，不直接编写评分逻辑。

### 3.2 证据完整性

每个 Rubric 观察保存：

~~~text
answer_id
rubric_id
rubric_version
level
evidence_start
evidence_end
quoted_text
answer_text_hash
confidence
validity
invalid_reason
~~~

程序使用原始回答执行字符区间切片，并核对：

~~~text
answer[start:end] == quoted_text
sha256(answer) == answer_text_hash
~~~

证据无法定位时不删除记录，保留为 invalid 并记录原因。本阶段的“有效证据”只表示来源完整且可定位，不表示已经完成语义相关性验证。

### 3.3 状态分离

用户回答的来源状态与评估状态分开保存。

用户可选择的回答来源状态仍为：

~~~text
submitted
explicit_unknown
skipped
~~~

系统结果通过评估运行记录表达：

~~~text
pending
valid
invalid
rejected
~~~

后续为兼容可信度架构，保留 disputed、confirmed、overturned 状态名，但本阶段不创建这些状态。

模型请求失败时，原始回答仍然保留，评估保持 pending，并记录 error_code=system_error。系统不把失败转换为等级 0。等级 0 只用于明确不知道或模型对有效回答判断为无有效内容的情况。

## 4. Rubric 设计

每道题生成时冻结一份 Rubric，评分时不重新生成。快照由版本号、Rubric 项、权重和允许参考事实组成。

第一阶段为每道题提供四个稳定 Rubric 项：

| Rubric ID | 判断内容 |
| --- | --- |
| correctness | 核心概念、方案或判断是否正确 |
| mechanism | 是否解释机制、原因或工作原理 |
| scenario | 是否结合当前问题进行场景化分析 |
| engineering | 是否说明边界、取舍、故障或可执行方案 |

四项默认等权。题目原有的 knowledge_point_id、signals 和 rubric_version 继续保留，用于题目上下文、缺口展示和版本追踪；它们不是模型可以随意改变的评分标准。

固定题可以携带冻结的技能包参考事实。简历生成的项目题如果没有可靠的参考事实，则只依据当前问题和通用 Rubric 评分，不把简历内容偷偷注入盲评分上下文。

每个 Rubric 项使用统一等级定义：

| 等级 | 含义 |
| --- | --- |
| 0 | 明确作答但核心内容完全错误或无有效内容 |
| 1 | 知道名词，但不能正确解释 |
| 2 | 基本理解，缺少机制、边界或工程细节 |
| 3 | 技术正确，并能结合场景分析 |
| 4 | 深入，能解释权衡、故障模式和可执行方案 |

## 5. AI Provider 与模型契约

新增 SiliconFlowAssessmentProvider，实现现有 AssessmentProvider 协议。Provider 使用与现有项目分析一致的 SiliconFlow 基础配置，但使用独立的评分模型配置和超时配置，API Key 只从环境变量读取，禁止写入仓库、数据库或前端。

模型请求上下文只包括：

~~~text
当前问题
Rubric 版本和完整 Rubric 项
允许使用的参考事实
用户首答
严格的 JSON 输出要求
~~~

模型输出只允许包含每个 Rubric 项的：

~~~json
{
  "items": [
    {
      "rubric_id": "mechanism",
      "level": 3,
      "evidence_start": 10,
      "evidence_end": 42,
      "quoted_text": "回答中的原文证据",
      "confidence": 0.86
    }
  ]
}
~~~

Provider 不接受模型生成的最终综合分、历史判断、追问建议或跨场次结论。解析器要求每个 Rubric ID 恰好出现一次，拒绝缺失、重复、多余或字段类型不正确的结果。

## 6. 确定性聚合

程序在所有 Rubric 观察完成并通过完整性校验后，使用固定公式聚合本题结果：

~~~text
本题等级 = floor(平均 Rubric 等级 + 0.5)
本题置信度 = 平均 Rubric 置信度
~~~

结果限制在 0～4 和 0～1 范围内。缺口由程序按 Rubric 等级推导，不使用模型自由生成的缺口作为计分依据：等级低于 3 的 Rubric 项进入本题缺口集合，等级达到 3 的项可进入优势候选集合。

如果任一 Rubric 的证据完整性失败，保留该观察记录但将本次评估标记为 invalid，不进入有效报告聚合。如果模型 JSON 不完整或无法解析，评估标记为 rejected，不创建虚假等级。

explicit_unknown 不调用模型，直接为冻结 Rubric 生成等级 0 的有效观察，证据使用完整回答文本。skipped 不生成评估。

## 7. 数据模型和兼容性

新增以下逻辑结构：

~~~text
AnswerAttempt
    └── AssessmentRun
            ├── RubricObservation 1
            ├── RubricObservation 2
            └── RubricObservation N
~~~

AssessmentRun 保存：

~~~text
answer_id
question_id
evaluator
rubric_version
status
aggregate_level
aggregate_confidence
error_code
error_reason
attempt_number
created_at
~~~

RubricObservation 保存每个 Rubric 项的等级、证据和完整性结果。一次回答只有一个当前有效评估；模型失败后的重试增加评估尝试记录，报告使用最新的有效结果。

现有 assessment_observations 作为旧版本地规则结果保留，不删除已有面试记录。报告读取新 AI 评估；对于没有 AI 评估的旧记录，可以继续按兼容逻辑读取本地规则结果，并明确显示其旧评估器版本。数据库升级只新增结构或字段，不清空 data/app.db。

## 8. API 与前端行为

继续使用：

~~~text
POST /api/sessions/{session_id}/answers
GET  /api/sessions/{session_id}/report
~~~

提交回答响应在保留现有 answer 和 observation 字段的基础上，增加评估状态、评估器和 Rubric 项结果。已有前端能够读取的字段保持兼容。

提交过程为同步请求：

1. 校验题目归属和幂等键。
2. 先持久化原始回答。
3. 调用 AI Provider。
4. 校验并保存评估结果。
5. 返回回答和评估状态。

前端在等待期间显示“AI 评分中”。模型超时或网络失败时显示评分未完成，并允许用相同提交 ID 重试。第一阶段不新增 AI 评分 SSE；简历项目分析现有 SSE 不受影响。

报告只聚合 valid 的 AI 评估和兼容读取的有效旧观察，展示等级、覆盖率、有效证据数、置信度、优势和缺口，不生成 0～100 综合分。

## 9. 错误处理

| 情况 | 处理 |
| --- | --- |
| 没有配置 API Key | 保留回答，评估 pending，错误码 provider_not_configured |
| 超时 | 保留回答，评估 pending，错误码 provider_timeout |
| 网络或 HTTP 错误 | 保留回答，评估 pending，记录对应错误码 |
| JSON 无法解析 | 评估 rejected |
| Rubric 不完整 | 评估 rejected |
| 证据无法定位 | 评估 invalid，保留原始观察和原因 |
| 同一提交 ID、相同 payload | 返回既有回答和最新评估状态 |
| 同一提交 ID、不同 payload | HTTP 409 |

评估异常不回滚已经持久化的回答。客户端重试不创建新的回答记录。

## 10. 测试和验收

### 10.1 Provider 单元测试

- 合法模型 JSON 能解析为全部 Rubric 项。
- 缺失、重复、多余 Rubric 项会被拒绝。
- 等级越界、置信度越界会被拒绝。
- 非 JSON、错误字段类型和空结果会被拒绝。
- Prompt 不包含历史画像、简历原文或过去分数。
- Provider 使用 Mock HTTP 客户端，不使用真实 API Key。

### 10.2 证据与聚合测试

- 证据区间和引用文本一致时为有效。
- 引用文本不一致时保留为 invalid 并记录原因。
- 回答哈希不一致时不能进入有效报告。
- 四个 Rubric 等级按固定公式聚合。
- Rubric 低于 3 时由程序生成缺口。
- explicit_unknown 得到等级 0 的有效观察。
- skipped 不产生评估。

### 10.3 API 测试

- 正常 AI 评分可以提交并读取本题等级。
- 模型超时后回答仍然存在，评估为 pending。
- 相同提交 ID 可以重试未完成评估。
- 不同 payload 继续返回 409。
- 无效评估不进入报告。
- 报告不包含 score_100。

### 10.4 前端验收

- 提交后显示 AI 评分中。
- 评分完成后显示等级、置信度和证据。
- 评分失败后能看到明确错误并重试。
- npm run build 成功。
- 现有简历解析、面试答题、刷新恢复和报告流程继续可用。

## 11. 版本与安全

AI 评估器标识为：

~~~text
siliconflow-blind-rubric-v1
~~~

建议环境变量：

~~~text
SILICONFLOW_ASSESSMENT_MODEL=deepseek-ai/DeepSeek-V4-Flash
ASSESSMENT_TIMEOUT_SECONDS=90
~~~

真实 API Key 只放在本地 backend/.env 或系统环境变量中。不得提交到 Git、数据库、日志、前端构建产物或截图中。

