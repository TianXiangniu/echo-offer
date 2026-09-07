# LLM 可观测性与成本治理设计

## 目标

为每一次 LLM 调用建立并发安全、可审计的本地追踪记录，并在后台提供按时间、模型、调用类型和面试会话查看的调用质量与人民币成本数据；只观察和提示，不因预算阻断任何功能。

## 背景与问题

系统已有 `operation_jobs`、事件进度和批量评分的 advisory token usage，但 usage 挂在共享 Provider 的 `last_usage` 上，不能覆盖全部调用，且并发时可能串写。成本配置也不存在，用户无法定位延迟、错误或一场面试的调用构成。

## 范围

纳入追踪的调用类型：项目分析、对话面试官、知识题追问、练习反馈、批量评分、评分复核、知识点深讲和连接测试。

本期不做：强制预算上限、自动停止调用、外部可观测性平台、保存原始 prompt/模型原文、跨用户计费或账单结算。

## 方案选择

采用“请求级调用追踪 + 聚合仪表盘”。每次 Provider 请求返回独立的调用元数据，调用方立即持久化为一条 trace；聚合 API 从 trace 表计算统计，前端只显示服务端已计算的成本，避免共享 Provider 实例状态与前端价格计算造成的错误。

## 数据模型

新增 `llm_call_traces`：

| 字段 | 含义 |
| --- | --- |
| `id` / `trace_id` | UUID；一次用户操作共享 `trace_id`，每个模型请求拥有独立 `id` |
| `operation_job_id` / `session_id` | 可选关联，支持评分任务与单次交互两类来源 |
| `call_kind` | `project_analysis`、`dialog_turn`、`followup_decision`、`practice_feedback`、`assessment_batch`、`assessment_verify`、`skill_wiki`、`connection_test` |
| `provider` / `model_name` / `prompt_version` | 实际调用配置与版本快照 |
| `status` / `error_code` | `succeeded`、`failed`；只保存归类错误码，不保存原始错误正文 |
| `input_tokens` / `output_tokens` / `total_tokens` | Provider 返回 usage 时写入；缺失则为 `NULL` |
| `input_price_per_million_cny` / `output_price_per_million_cny` | 调用时冻结的人民币价格；未配置为 `NULL` |
| `cost_cny` | 后端计算结果；usage 或价格缺失则为 `NULL` |
| `latency_ms` / `request_bytes` / `response_bytes` | 性能与规模指标，不保存原文 |
| `created_at` / `finished_at` | 调用起止时间 |

模型设置新增 `model_pricing` 配置，按模型名保存两个非负人民币单价：`input_price_per_million_cny`、`output_price_per_million_cny`。项目整理/追问等使用 `model` 的价格，批量评分/复核使用 `assessment_model` 的价格；模型未配置价格时调用照常完成，相关 trace 只显示 token，不显示虚假的 ¥0。

成本公式固定为：

```text
cost_cny = input_tokens / 1,000,000 × input_price_per_million_cny
         + output_tokens / 1,000,000 × output_price_per_million_cny
```

金额持久化保留足够精度（decimal），展示时保留 4 位小数；聚合总额不先行四舍五入。

## Provider 与数据流

Provider 的 `_chat` 不再写共享的 `last_usage`。它总是返回（或通过受控异常附带）`ModelCallResult[T]`：解析后的业务结果、模型名、usage、延迟、字节数和完成时间。调用方使用一个 `record_llm_call` 边界将成功或失败的结果写入 trace。

`trace_id` 在入口层创建并向下传递：同一面试评分任务、或一次单独的追问/反馈/对话动作共享它。对现有函数采用可选参数，避免改动不调用模型的路径。Provider 错误、JSON 解析失败、超时和 HTTP 错误均必须写一条 `failed` trace；没有 Provider usage 时仍记录延迟、模型、调用类型和错误码。

调用追踪与业务成功不相互阻塞：trace 落库失败时记录服务端日志，保留既有业务结果；模型调用失败时仍按既有错误语义返回。

## 后台 API 与界面

新增只读接口：

- `GET /api/observability/summary?from=&to=&model=&call_kind=&session_id=`：总调用数、成功率、token 总数、已知成本、未定价调用数、平均与 P95 延迟，及按模型/调用类型/日期的聚合。
- `GET /api/observability/traces?...&cursor=`：最新 trace 列表，默认近 30 天、按完成时间倒序，支持相同筛选与游标分页。
- `GET /api/observability/sessions/{session_id}`：该面试会话的聚合和调用明细。

新增 `/observability` 页面与顶部导航入口。默认显示近 30 天：四个关键指标（已知成本、调用次数、token、平均延迟）、按调用类型/模型的汇总、每日成本趋势、最近失败调用和可筛选明细。金额统一用人民币 `¥` 展示；无 token 或价格的成本显示“未配置”，并明确计入“未定价调用数”。报告页增加“查看本场模型成本”链接。

模型控制台增加“模型价格（元 / 1M Token）”编辑区，按当前项目模型和评分模型预填/保存，允许添加其他模型条目以支持切换后持续计量。

## 安全与保留策略

trace 表不得存 API Key、Authorization header、原始 prompt、原始模型回复、简历或回答正文。错误只存既有稳定 error code。指标接口沿用本地单用户模型；未来多用户化时必须强制以 `user_id` 过滤。数据默认永久保存以便本地复盘；本期不新增删除任务，且删除面试历史不删除 trace，以保持成本审计一致。

## 验收标准

1. 每种 LLM 调用成功和失败时都产生一条 trace，且并发请求的 usage 和成本不串写。
2. 已配置价格时成本严格按公式计算；任一 token 或价格缺失时 `cost_cny` 为 null，而不是 0。
3. 聚合 API 的调用数、token、已知成本、未定价调用数、成功率与延迟计算可由 trace 测试数据复算。
4. 控制台可保存非负人民币单价；观测页可按默认 30 天、模型、调用类型和会话筛选。
5. trace 序列化和数据库内容均不包含密钥、prompt、回答或模型原文。
6. 既有模型调用、任务状态、评分与追问接口语义保持不变，后端与前端回归测试通过。
