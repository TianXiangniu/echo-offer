# Graph 面试评分与成本观测闭环设计

## 目标

让 LangGraph 面试在完成最后一个节点后，自动复用现有 AI Rubric 评分与报告链路，并确保 Graph 模式的 planner、interviewer、evidence verifier、assessment 调用进入统一的模型成本观测表。

## 范围

本轮只处理两个 P0 缺口：

1. Graph 完成后的评分与报告自动触发；沿用现有 `assess_session`、`assessment_engine` 和 `reporting_flow`，不复制评分规则。
2. Graph API 的模型调用观测；沿用 `capture_model_calls` / `record_model_calls`，按 `session_id` 记录调用、Token、延迟和人民币成本。

本轮不改后台任务队列、不重写 SSE、不拆分新的 Agent 类。异步任务和实时 SSE 作为后续独立子项目。

## 架构与数据流

```text
Graph start/resume
  -> LangGraph invoke / checkpoint
  -> project_graph_event (question/answer/completed)
  -> if status=completed: assess_session
  -> AssessmentRun + RubricObservation + InterviewReport
  -> response includes assessment result

all model calls
  -> capture_model_calls(trace_id)
  -> record_model_calls(session_id)
  -> LlmCallTrace / observability summary
```

评分必须发生在 Graph 事件投影提交之后，否则 `assess_session` 看不到刚提交的最后一个回答。完成态重复 resume 只能复用已有有效评分，不能再次调用模型。

## 接口约束

- `resume_graph(..., on_completed=None)` 增加可选完成回调；回调只在 Graph 状态为 `completed` 且事件投影完成后执行。
- 回调返回现有 `AssessmentBatchResponse` 形状的字典；失败时保留 Graph 已完成状态，并返回可重试的评分状态，不回滚面试回答。
- `graph_start` 与 `graph_resume` 使用 `observed_model_call(db, session_id)` 包裹 Graph 调用；`graph_state` 不包裹，因为只读且不触发模型。
- 所有评分仍使用现有 0–4 内部等级，前端继续通过 `rubricGrade` 显示 A/B/C/D。

## 错误处理

- Graph 运行失败：沿用现有 Graph 错误和事务回滚。
- 评分 provider 失败：Graph 已完成、回答已保存；返回 `assessment.status` 或 `assessment_status=failed`，前端保留重试入口。
- 重复 resume：Graph 和评分均依赖现有幂等键/有效 AssessmentRun，不新增模型调用。

## 验收标准

- 最后一个 Graph 回答提交后，服务端能生成有效 AssessmentBatch、RubricObservation 和 InterviewReport。
- 同一完成态重复 resume 不新增 AnswerAttempt、不新增模型评分调用。
- Graph start/resume 产生的模型调用在 `/api/observability/summary?session_id=...` 可见，并包含 call_kind、Token、延迟和成本字段。
- provider 不可用时面试状态仍为 completed，评分状态可重试。
- 现有后端全量测试、前端测试和 Graph shadow eval 全部通过。
